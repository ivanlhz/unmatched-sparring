"""Pre-game gate: before a game starts, the bot checks that the loaded table is arranged for a NEW game and, if not,
offers the buttons that clean it and prepare it for the map and heroes the player drops on it. Nothing starts until the
human presses "Start game".

READY TABLE (what `audit` checks, for the two heroes the table shows, or Medusa and Hellboy if it shows none):
  1. No leftover loose object of the save: none of the `remove_table` GUIDs is on the table with its expected TTS name
     inside the central limits (the guard of `lua.prepare_table`, evaluated read only).
  2. Both seats' hands are empty.
  3. Every card of each side is in its draw deck, wherever it lay (hands, discards, combat and ONGOING spots, look rows,
     loose on the table or the board): the deck is found, holds the whole set and no card of the side is outside it
     (`lua.reset_plan` over `Scope(everywhere=True)`; a card is the side's by CardID range AND deck image).
  4. Each draw deck lies face down.
  5. No miniature of the two heroes stands on the board (they are set aside at the dead spots), and a multi-state
     miniature (Hellboy) is in its first state.
  6. Every life dial is at its maximum and the destiny dial at 0; two-faced tokens (Hellboy's ability token, Abe's
     Intuition tokens) show their starting face.
  7. The heroes' decks, pieces, dials and tokens are OUT of their bags, on the table (the pieces are not placed).
  8. No saved game of the bot (`state/session.json`) is left for `--resume` to pick up.
  9. The two discard zones exist (Scripting zones at their GUID) and there is a map on the table (any board whose image
     is in the map catalog; the locked pad boards of the official save do not count).
What it never judges: WHICH map is on the table (a person chooses it), the fighters' placement, the hands dealt, any game
rule. Things it finds but will not touch are reported, not counted as dirt: objects of other heroes on the table, a map
that cannot be played, a loose object whose name or place does not match the removal guard, a foreign card in a hand.

THE OFFICIAL TOURNAMENT TABLE AS IT LOADS (saves/Unmatched Official Tournament Table October 2026 (Hellboy).json, 170
objects): it has out, in the middle, two 78-card decks (addeca, cb6cbc), a d20 (65be8d), the locked Dice Cannon
(5085eb) and two Digital_Clocks (6126d5, 790396); no discard zone and no map (only the locked pad boards 45c723, 8315f0,
6bd0e3); every hero (117 infinite bags) and every map (31 infinite bags) in the roster beyond |z| 40; counters, rules cards,
Doors and Battlefield Items bags, 11 hand zones and a few loose models on the shelves.

THE PLAYER SETS THE TABLE (`sparring/player_setup.py`; three buttons: Clean table, Prepare, Start game):
  - CLEAN TABLE destroys every hero object (decks and cards, character cards, bags the player dropped, miniatures, dials,
    tokens; identified by CardID range AND deck image, by GUID and by name) and every map board of the catalog, the zoom copies
    and the bot's markings, creates or straightens the two discard zones, destroys the leftovers the removal guard lets through
    and deletes the saved game. The infinite bags of the roster and everything else stay where they are.
  - The player drags the map and the two heroes from the roster (a copy of a board, a copy of each hero's inner bag), the bot's
    hero to the bot's half (+x) and their own to theirs (-x), closed or opened.
  - PREPARE reads the table (`player_setup.scan`/`decide`: the map by its image, each half's hero by the bag it holds or the
    deck lying there), says in the chat "Bot: X, Tu: Y, Mapa: Z" and, if all is well, lays the map at the transform calibrated
    for it (`map_setup`: scale, place, rotation; an uncalibrated map is left as it lies and the chat gives the command to
    calibrate it), takes the heroes out of their bags, takes each character card out of its deck (a deck out of a bag holds it on
    top of the 30) and leaves it at its slot of the map layout, returns every card to its deck, shuffles, refills the dials,
    zeroes the destiny dial and sets the miniatures aside, then lays decks, dials, tokens and miniatures at the slots of the
    map layout (`table_layout`: one slot per side and role; the default `layout` of config/table.json for an uncalibrated map).
    A hero the bot cannot play, a missing or duplicated hero, two heroes on one half or no map is said in the chat and nothing
    is touched.
Cards are gathered, never destroyed by Prepare; only Clean table destroys, and only what it recognises. No piece goes to the
board, no hand is dealt, no turn is opened. After preparing, the table is read again and compared with the definition above:
what is still off is named in the chat.

The loop here owns the panel until "Start game": it hides every game button and shows only the gate ones."""
from __future__ import annotations

import dataclasses
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import player_setup, table_layout
from .board import catalog as board_catalog
from .board_detect import TABLE_PAD_IMAGES, BoardError, choose_board, image_key_of
from .i18n import t
from .heroes import load_hero
from .session import INTUITION_TOKEN, TOKEN_NICKNAMES, Msg, Session, SessionError
from .session_choices import panel_text
from .tts import lua, ui
from .tts.client import TTSLuaError
from .tts.hero_table import TTS_DIR, HeroTableError, load_hero_table, other_variants
from .tts.ui import Event, parse_event

PANEL_CHUNK = 70                              # `lua.set_panel` takes at most 80 elements per call
PANEL_SETTLE = 0.7                            # seconds the panel needs for its XML to exist (it is written 0.5 s after the object)
ENABLED = True                                # tests turn the gate off globally and opt in where they exercise it
START_FACE = {"ability": "occult_detective", "intuition": "inactive"}     # starting face of each two-faced token (token_faces)


class CleaningSession(Session):
    """A throw-away session that only reads and resets the table: its card scope is the whole table (the cards are told
    apart by CardID range and deck image, so loose cards of the heroes are safe to gather)."""

    def _scope(self) -> lua.Scope:
        return dataclasses.replace(super()._scope(), everywhere=True)

    def _reset_button(self) -> str:
        return t("panel.prep")


@dataclass(frozen=True)
class Issue:
    code: str                                 # key of `gate.issue.<code>`
    detail: str = ""


@dataclass
class Audit:
    issues: list[Issue] = field(default_factory=list)       # what makes the table not ready (the clean button fixes it)
    notices: list[str] = field(default_factory=list)        # found and left alone (already worded)

    @property
    def ready(self) -> bool:
        return not self.issues

    def issues_text(self) -> str:
        return "; ".join(t(f"gate.issue.{i.code}", detail=i.detail) for i in self.issues)


def gate_enabled(raw: dict) -> bool:
    return ENABLED and raw.get("pregame_gate", True) is True


def other_hero_presence(pair: tuple[str, str]) -> list[tuple[str, list[str]]]:
    """(label, GUIDs) of every other hero with TTS data. A GUID that a hero of the pair also owns is left out (the save
    shares some between heroes: Abe and Donatello, Lobster and the Jackalope)."""
    used = {g for slug in pair for g in load_hero_table(slug).all_guids()}
    out = []
    for path in sorted(TTS_DIR.glob("*.json")):
        slug = path.stem
        if slug in pair:
            continue
        try:
            guids = [g for g in load_hero_table(slug).all_guids() if g not in used]
        except HeroTableError:
            continue
        if guids:
            out.append((f"other:{slug}", guids))
    return out


def _guids(value) -> list[str]:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _deck_sides(session) -> list[tuple]:
    """(side, deck GUID, spot, CardID range, zone, owner) of each side's draw deck."""
    c = session.cfg
    sides = [("bot", c.bot_deck_guid, c.bot_deck_spot, c.bot_card_ids, c.bot_deck_zone, session.bot)]
    if c.human_deck_guid:
        sides.append(("human", c.human_deck_guid, c.human_deck_spot, c.human_card_ids, c.human_deck_zone, session.human))
    return sides


def _facing_args(session) -> list[tuple]:
    return [(tuple(spot), zone, rng, session._identity(side)) for side, _, spot, rng, zone, _ in _deck_sides(session)]


def _first_face(table, name: str) -> float | None:
    spec = table.token_faces.get(name) or {}
    return (spec.get("faces") or {}).get(START_FACE.get(name, ""))


def _nearest_face(spec: dict, rot_z: float) -> str | None:
    faces = spec.get("faces") or {}
    if not faces:
        return None
    return min(faces, key=lambda k: min(abs((rot_z - faces[k]) % 360), 360 - abs((rot_z - faces[k]) % 360)))


def map_state(found) -> tuple[str, object]:
    """What map the boards read off the table make: ("ok", MapEntry) with a playable one; ("none", "") with only the pad
    boards of the official save; ("other", message) with something the bot cannot play (unknown, excluded, unverified, two)."""
    found = found if isinstance(found, list) else []
    try:
        return "ok", choose_board(found, board_catalog())[0]
    except BoardError as e:
        if all(image_key_of(b.get("image")) in TABLE_PAD_IMAGES for b in found if isinstance(b, dict)):
            return "none", ""
        return "other", str(e)


def read_map(client) -> tuple[str, object]:
    """`map_state` of the boards on the table (one read)."""
    return map_state(client.call_lua(lua.list_boards()))


def batch(client, named: list[tuple[str, str]], optional: frozenset[str] = frozenset()) -> dict:
    """ONE message to TTS for several builders (`lua.composite`, each runs inside its own pcall): {name: that builder's
    answer}. A builder that failed raises `SessionError` naming it. TTS takes ~0.5 s per message, so the audit and each step of
    the cleaning go out as one. A read named in `optional` that failed answers None instead of raising, and its error is kept in
    `out["__failed"]` = {name: error}: the caller must report it (one failing side read must not kill the whole audit, but
    the table it would have checked is not checked)."""
    res = client.call_lua(lua.composite([script for _, script in named]))
    ops = res.get("ops") if isinstance(res, dict) else None
    if not isinstance(ops, list) or len(ops) != len(named):
        raise SessionError(t("gate.batch_reply", got=repr(str(res)[:80])))
    out = {}
    for (name, _), answer in zip(named, ops):
        if isinstance(answer, dict) and answer.get("__err"):
            if name in optional:
                out[name] = None
                out.setdefault("__failed", {})[name] = answer["__err"]
                continue
            raise SessionError(t("gate.batch_failed", name=name, error=answer["__err"]))
        out[name] = answer
    return out


AUDIT_SIDE_READS = frozenset({"pieces", "dials", "tokens"})      # the audit still says something useful without them


def audit(client, session, state_path: Path | None = None) -> Audit:
    """Reads the table (ONE message, see `batch`; plus the deck identities the first time) and says what is out of place for
    the heroes `session` plays."""
    c, game = session.cfg, session.game
    out = Audit()
    heroes = [game.hero_def(p) for p in (session.bot, session.human)]
    slugs = tuple(h.slug for h in heroes)
    tables = {slug: load_hero_table(slug) for slug in slugs}
    protected = {*session.guids_in_use(), *session.guids_in_use(configured=True)}
    remove = [(g, name) for g, name in c.remove_plan if g not in protected]
    presence = []
    for slug in slugs:
        for kind, guids in tables[slug].unpack_items():
            if kind != "deck":
                presence.append((f"{slug}:{kind}:{guids[0]}", list(guids)))
    sides = _deck_sides(session)
    guids = sorted({g for v in c.pieces.values() for g in _guids(v)})
    wanted = {guid: game.fighters[fid].max_hp for fid, guid in c.dials.items() if fid in game.fighters}
    if c.destiny_dial:
        wanted[c.destiny_dial] = 0
    token_guids = {(slug, name): tables[slug].tokens.get(name) for slug in slugs for name in tables[slug].token_faces
                   if name in START_FACE and tables[slug].tokens.get(name)}
    zones = {"bot_discard_zone": c.bot_discard_zone, "human_discard_zone": c.human_discard_zone}
    reads = [("audit", lua.table_audit(remove, c.remove_limits, [c.bot_seat, c.human_seat],
                                       presence + other_hero_presence(slugs))),
             ("boards", lua.list_boards()),
             ("facing", lua.deck_facing(_facing_args(session), c.deck_radius)),
             ("plans", lua.reset_plan([(guid, spot, rng, session._identity(side), zone)
                                       for side, guid, spot, rng, zone, _ in sides], c.deck_radius, scope=session._scope()))]
    if c.zone_spawns:
        reads.append(("zones", lua.zone_overlaps(sorted(set(zones.values())))))
    if guids:
        reads.append(("pieces", lua.piece_spaces_by_guid(game.board, guids)))
    if wanted:
        reads.append(("dials", lua.read_health_dials(sorted(wanted))))
    if token_guids:
        reads.append(("tokens", lua.inspect_objects(sorted(set(token_guids.values())))))
    got = batch(client, reads, optional=AUDIT_SIDE_READS)

    res = got["audit"] if isinstance(got["audit"], dict) else {}
    present = res.get("present") if isinstance(res.get("present"), dict) else {}
    left = [f"{row.get('name')} {row.get('guid')}" for row in res.get("removable") or [] if isinstance(row, dict)]
    if left:
        out.issues.append(Issue("leftovers", ", ".join(left)))
    for row in res.get("blocked") or []:
        if isinstance(row, dict) and row.get("why") in ("type", "place"):
            out.notices.append(t("prep.skipped", guid=row.get("guid"), what=row.get("name") or "",
                                 why=t("prep.why." + row["why"])))
    hands = res.get("hands") if isinstance(res.get("hands"), dict) else {}
    full = [f"{seat} {n}" for seat, n in hands.items() if isinstance(n, (int, float)) and n > 0]
    if full:
        out.issues.append(Issue("hand_cards", ", ".join(full)))
    state, found_map = map_state(got["boards"])
    if state == "none":
        out.issues.append(Issue("map_missing", ""))
    elif state == "other":
        out.notices.append(t("gate.notice.map_unplayable", error=found_map))
    if "zones" in got:
        read_zones = got["zones"] if isinstance(got["zones"], dict) else {}
        gone = [t("ro.role.bot" if key.startswith("bot") else "ro.role.human") for key, guid in zones.items()
                if key in c.zone_spawns and not ((read_zones.get(guid) or {}).get("found")
                                                 and (read_zones.get(guid) or {}).get("zone") is not False)]
        if gone:
            out.issues.append(Issue("zones", ", ".join(gone)))
    out_of_bag = sorted({slug for slug in slugs for key, here in present.items()
                         if key.startswith(f"{slug}:") and here is False})
    stray = sorted(key.split(":", 1)[1] for key, here in present.items() if key.startswith("other:") and here is True)
    if stray:
        out.notices.append(t("gate.notice.other_heroes", detail=", ".join(load_hero(s).name for s in stray)))

    facing = got["facing"] if isinstance(got["facing"], list) and len(got["facing"]) == len(sides) else [{}] * len(sides)
    plans = got["plans"] if isinstance(got["plans"], list) and len(got["plans"]) == len(sides) else [{}] * len(sides)
    wrong, face_up = [], []
    for (side, *_, owner), plan, face in zip(sides, plans, facing):
        plan = plan if isinstance(plan, dict) else {}
        face = face if isinstance(face, dict) else {}
        name, want = game.hero_def(owner).name, len(game.players[owner].full_set)
        if face.get("found") and face.get("face_down") is False:
            face_up.append(name)
        away = not plan.get("deck") and not face.get("found") and (plan.get("loose") or 0) > 0 and (plan.get("total") or 0) > 0
        if not plan.get("deck") and not face.get("found") and not away:
            if game.hero_def(owner).slug not in out_of_bag:
                out_of_bag.append(game.hero_def(owner).slug)
        elif away and plan.get("total") == want:
            wrong.append(t("gate.deck_away", name=name))           # on the table, only not at its spot: not "in the bag"
        elif plan.get("deck") or away:
            if plan.get("total") != want or plan.get("loose"):
                wrong.append(t("gate.cards_of", name=name, got=plan.get("total"), want=want))
    if wrong:
        out.issues.append(Issue("cards_loose", ", ".join(wrong)))
    if face_up:
        out.issues.append(Issue("deck_face_up", ", ".join(face_up)))
    if out_of_bag:
        out.issues.append(Issue("heroes_out", ", ".join(load_hero(s).name for s in sorted(out_of_bag))))

    found = got.get("pieces") if isinstance(got.get("pieces"), dict) else {}
    if found.get("no_board"):                  # no map on the table: no piece can be on it
        found = {}

    def here(g: str) -> dict:
        return found.get(g) if isinstance(found.get(g), dict) else {}
    on_board = [fid for fid, v in c.pieces.items()
                if any(here(g).get("found") and here(g).get("dist", 0) <= c.off_board_dist for g in _guids(v))]
    if on_board:
        out.issues.append(Issue("pieces_on_board", ", ".join(c.nicknames.get(f, f) for f in on_board)))
    changed = [c.nicknames.get(fid, fid) for fid, v in c.pieces.items()
               if len(_guids(v)) > 1 and not here(_guids(v)[0]).get("found") and any(here(g).get("found") for g in _guids(v)[1:])]
    if changed:
        out.issues.append(Issue("forms", ", ".join(changed)))
    read = got.get("dials") if isinstance(got.get("dials"), dict) else {}
    off = [g for g, v in wanted.items() if (read.get(g) or {}).get("found") and (read.get(g) or {}).get("value") is not None
           and int(read[g]["value"]) != v]
    if off:
        names = {guid: fid for fid, guid in c.dials.items()}
        out.issues.append(Issue("dials", ", ".join(c.nicknames.get(names.get(g, ""), t("gate.destiny_dial")) for g in off)))
    if token_guids:
        seen = got.get("tokens") if isinstance(got.get("tokens"), dict) else {}
        turned = []
        for (slug, name), guid in sorted(token_guids.items()):
            info = seen.get(guid) if isinstance(seen.get(guid), dict) else {}
            if info.get("found") and isinstance(info.get("rot_z"), (int, float)) \
                    and _nearest_face(tables[slug].token_faces[name], float(info["rot_z"])) != START_FACE[name]:
                turned.append(f"{load_hero(slug).name} {name}")
        if turned:
            out.issues.append(Issue("tokens", ", ".join(turned)))
    unchecked = got.get("__failed") or {}
    if unchecked:
        out.issues.append(Issue("unchecked", "; ".join(f"{name}: {err}" for name, err in sorted(unchecked.items()))))
    if state_path is not None and Path(state_path).exists():
        out.issues.append(Issue("saved_game", ""))
    return out


def start_face_ops(client, session) -> list[tuple[str, str]]:
    """The writes that put Hellboy's miniature back in its first state, the two-faced tokens on their starting face and Abe's
    Intuition tokens inactive, as builders for `batch` (one read first for the miniatures that have several states; a
    table that is already right gets writes that change nothing)."""
    c = session.cfg
    forms = {}
    for owner in (session.bot, session.human):
        for fid in load_hero_table(session.game.hero_def(owner).slug).fighters:
            states = _guids(c.pieces.get(fid) or [])               # the GUIDs of its states, as the session resolved them
            if len(states) > 1:
                forms[fid] = states
    rows = client.call_lua(lua.piece_spaces_by_guid(session.game.board, sorted({g for v in forms.values() for g in v}))) \
        if forms else {}
    rows = rows if isinstance(rows, dict) else {}
    ops = []
    for fid, states in forms.items():
        now = [g for g in states if (rows.get(g) or {}).get("found")]
        if now and now[0] != states[0]:
            ops.append((f"form {fid}", lua.set_state(now[0], 1)))
    for owner in (session.bot, session.human):
        table = load_hero_table(session.game.hero_def(owner).slug)
        for name, spec in table.token_faces.items():
            guid, face = table.tokens.get(name), _first_face(table, name)
            if not guid or face is None:
                continue
            if name == "intuition":
                faces = spec["faces"]
                ops.append((f"{name} tokens", lua.set_intuition_tokens(INTUITION_TOKEN, guid, float(faces["active"]),
                                                                       float(faces["inactive"]), 0, [c.human_seat])))
            else:
                ops.append((f"{name} token", lua.set_token_face(guid, float(face))))
    return ops


def _lifted(slot: table_layout.Slot) -> tuple[tuple, tuple]:
    """(position, rotation) of a slot, a little above the height it rests at, so that nothing is dropped through the table."""
    x, y, z = slot.pos
    return (x, y + table_layout.SETTLE_LIFT, z), slot.rot


def take_character_cards(client, session, raw: dict) -> None:
    """One message: each side's character card leaves its draw deck (the deck that comes out of a hero's bag holds it on top of
    the 30, 31 in all, and no card write accepts a deck with a card outside its range) and lies at the `character_card` slot
    of that side's layout. A deck that has no such card is left alone, so pressing again is harmless."""
    sides = []
    for side, guid, spot, rng, zone, owner in _deck_sides(session):
        slot = table_layout.character_slot(raw, side)
        if slot is None:
            raise SessionError(t("gate.layout_missing", side=side))
        table = load_hero_table(session.game.hero_def(owner).slug)
        sides.append((guid, rng, table.identity, table.character_card_id, *_lifted(slot),
                      tuple(o.character_card_id for o in other_variants(table.slug))))
    client.call_lua(lua.take_character_cards(sides))


def layout_ops(session, raw: dict) -> tuple[list[tuple[str, str]], list[str]]:
    """(the op for `batch` that lays every placeable object of both sides at its slot, GUIDs that have no slot)."""
    items, unplaced = [], []
    for side, _, _, _, _, owner in _deck_sides(session):
        found = table_layout.plan(raw, side, load_hero_table(session.game.hero_def(owner).slug))
        items += [(p.guids, *_lifted(p.slot)) for p in found.placements]
        unplaced += found.unplaced
    ops = [("layout", lua.arrange_objects(items))] if items else []
    split = [(guid, TOKEN_NICKNAMES[name], *_lifted(slot)) for side, _, _, _, _, owner in _deck_sides(session)
             for table in [load_hero_table(session.game.hero_def(owner).slug)]
             for name, guid in table.tokens.items() if name in TOKEN_NICKNAMES
             for slot in table_layout.own_token_slots(side, table, name)[1:]]
    return (ops + ([("token stacks", lua.split_token_stack(split))] if split else [])), unplaced


def reset_cards_and_pieces(client, session, raw: dict, arrange: bool = False) -> list[Msg]:
    """Everything of the session's two heroes back to its starting state: cards to their decks (face down, shuffled),
    pieces off the board, dials full, forms and tokens at their start. Raises what the table raises. With `arrange` the
    objects end at the slots of the layout of `raw` (the last op of the closing batch, so no extra message) and the chat
    lines about what could not be placed are returned.

    Messages: one to take the character cards out of the decks; the deck identities (reads); one to turn a face-up deck down, because the card writes only find face-down
    decks; the restart machinery (`Session._reset_table`, its own few messages: it must see its writes settle before it
    checks); and one batch for what follows (decks face down again, forms, tokens, the layout)."""
    session.resolve_pieces()
    take_character_cards(client, session, raw)
    session.load_identities()
    client.call_lua(lua.flip_decks_down(_facing_args(session), session.cfg.deck_radius))
    session._reset_table(session._fresh_game())
    ops, unplaced = layout_ops(session, raw) if arrange else ([], [])
    # the layout first: a slot's rotation must never decide the face a two-faced token ends on (Abe's Intuition tokens rest
    # at the slot's Z, and the first face op that follows turns them to the starting one)
    got = batch(client, [("decks", lua.flip_decks_down(_facing_args(session), session.cfg.deck_radius)),
                         *ops, *start_face_ops(client, session)])
    res = got.get("layout") if isinstance(got.get("layout"), dict) else {}
    left = [*unplaced, *(res.get("missing") or [])]
    return [Msg(t("gate.layout_unplaced", guids=", ".join(left)), lua.ChatKind.WARNING)] if left else []


def prepare_session(client, make_session: Callable, cfg, unpack: Callable, echo: Callable[[str], None],
                    rescan: Callable | None = None) -> tuple[list[Msg], Session, object]:
    """Takes the heroes of `cfg` out of what the player dropped (`unpack` returns what it could not do, said in the chat with
    what to do by hand) and leaves the table prepared for them: discard zones, cards in their decks, dials full, everything at
    its slot of the map layout. Raises what the table raises (the caller words it). Returns the chat lines and the session
    that did it (it holds the discard zones it created or adopted), and the configuration it worked with: unpacking spawns the
    decks, TTS may renumber their DeckID there, so `rescan(cfg)` reads the ranges they really carry before anything is searched.

    Not merged into one message: unpacking and `Session.prepare_table` have each their own reply to read (what is missing, the
    GUIDs of the zones TTS creates) before the next step can be worded or addressed."""
    problems = unpack(client, cfg, echo)
    if problems:
        raise SessionError(" ".join(problems))
    if rescan is not None:
        cfg = rescan(cfg)
    session = make_session(cfg)
    session.messages = []
    session.prepare_table(False, None)
    session._say_startup_notes()
    session.messages += reset_cards_and_pieces(client, session, cfg.raw, True)
    return list(session.messages), session, cfg


class Gate:
    """The pre-game loop. `redetect(bot, human)` returns the configuration of the table for those heroes (None = read
    them from the table) and raises what start-up raises when it cannot; `make_session(cfg)` builds a throw-away
    session on a configuration (it is only used to read and reset the table, never to play); `rescan(cfg, settle)`, optional, gives
    the configuration back with the deck ranges read after the heroes were unpacked (`settle()` waits between its reads)."""

    def __init__(self, client, cfg, *, redetect: Callable, make_session: Callable, unpack: Callable,
                 announce: Callable[[list], None], echo: Callable[[str], None], stop: threading.Event,
                 errors: tuple[type[BaseException], ...], poll: float = 0.1, settle: float | None = None,
                 state_path: Path | None = None, notes: tuple[str, ...] = (),
                 rescan: Callable | None = None, configured: Callable[[], tuple[str | None, str | None]] | None = None):
        self.notes = notes                       # what start-up could not read from the table (said first)
        self.client, self.cfg = client, cfg
        self.redetect, self.make_session, self.unpack = redetect, make_session, unpack
        self.configured = configured or (lambda: (None, None))     # () -> (bot hero, human hero) the configuration FIXES (None: auto)
        self.rescan = rescan                     # (cfg, settle) -> cfg with the CardID ranges of the decks as TTS numbered them
        self.announce, self.echo, self.stop, self.errors = announce, echo, stop, errors
        self.poll = poll
        self.settle = PANEL_SETTLE if settle is None else settle
        self.state_path = state_path
        self.session = make_session(cfg)
        self.cleaned = False                     # the last audit found the table ready (prepared)
        self._panel_for: tuple | None = None
        self.asking: tuple[str, ...] | None = None   # the variants the panel is asking the player to choose from (a box of two heroines)

    def _settle(self) -> None:
        self.stop.wait(self.settle)

    def say(self, text: str, kind=lua.ChatKind.NEUTRAL) -> None:
        self.announce([Msg(text, kind)])

    # ---------- panel ----------
    def _panel(self) -> None:
        """Creates the panel for the current heroes (once per hero pair)."""
        s, cfg = self.session, self.cfg
        targets = [f.fid for f in s.game.own(s.bot)]
        key = (tuple(targets), cfg.attacker_ids)
        if self._panel_for == key:
            return
        self.client.call_lua(lua.clear_markings(remove_panel=True))
        self.client.call_lua(lua.create_panel(targets, cfg.panel_position, cfg.panel_rotation, cfg.panel_scale,
                                              cfg.nicknames, snapshot=None, attacker_ids=cfg.attacker_ids,
                                              human_seat=s.cfg.human_seat))
        self._panel_for = key
        self.stop.wait(self.settle)           # the panel's XML is written 0.5 s after the object: a set_panel before is lost

    def show(self, status_tag: str, prep: bool, start: bool, clean: bool = True, options: tuple[str, ...] = ()) -> None:
        """`options`: the heroes the player is asked to choose from, one button each (`btn_choice_1..`, the ones an effect choice uses)."""
        self._panel()
        s = self.session
        ids = ui.element_ids([f.fid for f in s.game.own(s.bot)], tuple(f.fid for f in s.game.own(s.human)))
        states = {i: (False, False) for i in ids}
        states["btn_clean"], states["btn_prep"], states["btn_start"] = (clean, clean), (prep, prep), (start, start)
        labels = {}
        for ident, slug in zip(ui.CHOICE_BUTTONS, options):
            states[ident] = (True, True)
            labels[ident] = panel_text(t("setup.lead_option", name=load_hero(slug).name))
        text = panel_text(t(status_tag))
        items = sorted(states.items())
        for n in range(0, len(items), PANEL_CHUNK):
            self.client.call_lua(lua.set_panel(text, dict(items[n:n + PANEL_CHUNK]), labels=labels if n == 0 else None))

    def refresh(self) -> None:
        if self.asking:
            self.show("gate.status.pick_hero", prep=False, start=False, options=self.asking)
        elif self.cleaned:
            self.show("gate.status.ready", prep=False, start=True)
        else:
            self.show("gate.status.dirty", prep=True, start=False)

    # ---------- steps ----------
    def check(self) -> Audit:
        result = audit(self.client, self.session, self.state_path)
        self.cleaned = result.ready
        return result

    def say_notes(self, full: bool) -> None:
        """What start-up could not read (no map, no heroes: normal on a table that is not ready, which the audit lists and the
        button fixes) is one short line; the details only when the table looks ready or could not be checked."""
        if not self.notes:
            return
        if full:
            for note in self.notes:
                self.say(t("gate.not_read", error=note), lua.ChatKind.WARNING)
        else:
            self.say(t("gate.not_read_yet"), lua.ChatKind.NEUTRAL)

    def begin(self) -> None:
        try:
            result = self.check()
        except self.errors as e:
            self.say_notes(full=True)
            self.say(t("gate.audit_failed", error=e), lua.ChatKind.WARNING)
            self.refresh()
            return
        self.say_notes(full=result.ready)
        for line in result.notices:
            self.say(line, lua.ChatKind.WARNING)
        if result.ready:
            self.say(t("gate.already_ready"), lua.ChatKind.YOUR_TURN)
            self.say_next()
        else:
            self.say(t("gate.dirty", issues=result.issues_text()), lua.ChatKind.WARNING)
        self.refresh()

    def say_next(self) -> None:
        self.say(t("gate.next"), lua.ChatKind.YOUR_TURN)

    def _forget_saved_game(self) -> None:
        if self.state_path is None:
            return
        try:
            Path(self.state_path).unlink(missing_ok=True)
        except OSError as e:
            self.say(t("restart.delete_fail", path=self.state_path, err=e), lua.ChatKind.WARNING)

    def on_clean(self) -> None:
        """Empties the table of every hero and map (and of the leftovers of the official save), so the player can drag the next
        game map and heroes from the roster."""
        self.asking = None
        self.say(t("setup.cleaning"))
        try:
            batch(self.client, [("clear", lua.clear_markings(remove_panel=True))])
            removed, mixed = player_setup.cleared_summary(self.client.call_lua(player_setup.clear_script(self.cfg.raw)))
            self.session.messages = []
            self.session.prep_removed = 0
            self.session.prepare_table(False, None)
            removed += self.session.prep_removed
            self.session._say_startup_notes()
            self.announce(list(self.session.messages))
            self._forget_saved_game()
        except self.errors as e:
            self._panel_for = None
            self.cleaned = False
            self.say(t("setup.clean_failed", error=e), lua.ChatKind.WARNING)
            self.refresh()
            return
        self._panel_for = None                    # the cleaning removed the panel with the zoom copies
        self.cleaned = False
        self.say(t("setup.cleaned", n=removed), lua.ChatKind.YOUR_TURN)
        if mixed:
            self.say(t("setup.mixed_left", guids=", ".join(mixed)), lua.ChatKind.WARNING)
        self.say(t("setup.drag"), lua.ChatKind.YOUR_TURN)
        self.refresh()

    def on_choice(self, payload: dict) -> None:
        """The player's answer to the question of `on_prepare`: the button they pressed picks the variant and Prepare goes on. A press
        with no question open (a stray click) is ignored."""
        options, self.asking = self.asking, None
        index = payload.get("i")
        if not options:
            return
        if isinstance(index, float) and index.is_integer():       # TTS sends Lua numbers as JSON floats
            index = int(index)
        if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= len(options):
            self.asking = options
            return
        self.on_prepare({player_setup.HUMAN: options[index - 1]})

    def on_prepare(self, picks: dict[str, str] | None = None) -> None:
        """Reads the map and the two heroes the player dropped (`player_setup`), says what it found and lays everything out on
        the slots of that map. Anything the bot cannot play, or missing, is said in the chat and nothing is touched. When the
        player's half holds a box of two heroines (Yennefer & Triss) the panel asks which leads before anything is moved; the
        table is read again with the answer (`picks`), so a change made meanwhile is seen."""
        self.asking = None
        try:
            found = player_setup.scan(self.client, self.cfg.raw, batch)
        except self.errors as e:
            self.say(t("setup.scan_failed", error=e), lua.ChatKind.WARNING)
            self.refresh()
            return
        try:
            fixed_bot, fixed_human = self.configured()
        except self.errors as e:
            self.say(t("setup.scan_failed", error=e), lua.ChatKind.WARNING)
            self.refresh()
            return
        options = None if picks else player_setup.question(found, fixed_human)
        if options:
            self.asking = options
            self.say(t("setup.which_hero", names=t("common.and").join(load_hero(s).name for s in options)), lua.ChatKind.YOUR_TURN)
            self.refresh()
            return
        setup, problems = player_setup.decide(found, picks=picks, bot_hero=fixed_bot, human_hero=fixed_human)
        if setup is None:
            for line in problems:
                self.say(line, lua.ChatKind.WARNING)
            self.say(t("setup.fix_then_prepare"), lua.ChatKind.WARNING)
            self.refresh()
            return
        self.say(player_setup.describe(setup), lua.ChatKind.YOUR_TURN)
        if setup.calibration is None:
            self.say(player_setup.not_calibrated(setup), lua.ChatKind.WARNING)
        try:
            if setup.calibration is not None:
                c = setup.calibration
                placed = self.client.call_lua(lua.place_map(setup.board_guid, c.position, c.rot_y, c.scale))
                if not (isinstance(placed, dict) and placed.get("placed")):
                    raise SessionError(t("setup.map_failed", guid=setup.board_guid))
            cfg = self.redetect(setup.bot, setup.human)
            lines, prepared, cfg = prepare_session(self.client, self.make_session, cfg,
                                                   lambda client, on, echo: self.unpack(client, on, echo, False, setup.bags),
                                                   self.echo, self.rescan and (lambda on: self.rescan(on, self._settle)))
            self.announce(lines)
            self._forget_saved_game()
            self.cfg, self.session = cfg, prepared      # the preparing session knows the zones it made
            self._panel_for = None
            result = audit(self.client, self.session, self.state_path)
        except self.errors as e:
            self._panel_for = None
            self.cleaned = False
            self.say(t("setup.prepare_failed", error=e), lua.ChatKind.WARNING)
            self.refresh()
            return
        self.cleaned = result.ready
        for line in result.notices:
            self.say(line, lua.ChatKind.WARNING)
        if result.ready:
            self.say(t("setup.prepared", bot=load_hero(setup.bot).name, human=load_hero(setup.human).name), lua.ChatKind.YOUR_TURN)
            self.say_next()
        else:
            self.say(t("gate.left_over", issues=result.issues_text()), lua.ChatKind.WARNING)
        self.refresh()

    def on_start(self):
        """The configuration of the table as it is now, or None (and the reason in the chat) if it cannot be read. Start game is
        only offered once the table is ready; a press that still arrives on a table that is not ready is refused."""
        if not self.cleaned:
            self.say(t("gate.start_refused"), lua.ChatKind.WARNING)
            self.refresh()
            return None
        self.say(t("gate.starting"))
        try:
            return self.redetect(None, None)
        except self.errors as e:
            self.say(t("gate.start_failed", error=e), lua.ChatKind.WARNING)
            self.refresh()
            return None

    # ---------- loop ----------
    def run(self):
        """Blocks until "Start game": returns the configuration to play with (None if the bot is stopped first)."""
        try:
            self.begin()
        except TTSLuaError as e:                    # the table did not answer at all: the normal start-up says so next
            self.say(t("gate.audit_failed", error=e), lua.ChatKind.WARNING)
        while not self.stop.is_set():
            if self.client.take_reload():
                self._panel_for = None
                self.refresh()
            for raw in self.client.poll_events():
                try:
                    event, payload = parse_event(raw)
                except (KeyError, ValueError, TypeError, AttributeError):
                    continue
                if event is Event.CHOICE:
                    self.on_choice(payload)
                elif event is Event.CLEAN:
                    self.on_clean()
                elif event is Event.PREPARE:
                    self.on_prepare()
                elif event is Event.START:
                    cfg = self.on_start()
                    if cfg is not None:
                        self.client.call_lua(lua.clear_markings(remove_panel=True))
                        return cfg
            self.stop.wait(self.poll)
        return None
