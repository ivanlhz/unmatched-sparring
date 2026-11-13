"""Rosie the Riveter at the live table (docs/heroes/rosie-the-riveter.md): what the session says and does about her upgrade row.

The engine's counters (`upgrades`, `upgrade_shift`: sparring/upgrades.py) are the authority. Every change is said in the chat, for either
seat, as what happened and where the row stands. The four upgrade tokens of her bag are double-sided and their order on the table changes
with every single deactivation: when the BOT plays Rosie it flips them and puts each in the place its row position has (`lua_rosie`), and
pings every token it flips or moves; a HUMAN Rosie flips her own tokens by hand, following the chat.

The row has four resting spots, left to right. They are the positions the four tokens lie at when the session first looks at a game (the
start order 1 to 4), or on a resume with no saved spots the positions of the tokens in the row's current order; they are kept in
`Session.upgrade_slots` and saved with the session. The first look of a game or of a resumed game always writes the whole state."""
from __future__ import annotations

from . import upgrades
from .i18n import t
from .session_translators import DOMAIN, ERRORS
from .tts import lua_rosie
from .tts.hero_table import HeroTableError, load_hero_table
from .tts.lua import ChatKind


def _state(game, player: int) -> tuple[int, int] | None:
    return (upgrades.count(game, player), game.fx.counter_value(player, upgrades.SHIFT)) if upgrades.has(game, player) else None


def _names(items: list[dict]) -> str:
    return ", ".join(u["name"] for u in items) or t("rosie.none")


def describe(game, player: int, before: tuple[int, int] | None) -> str:
    """The change from `before` ((active, shift) as last said; None = first look) to the engine's state now."""
    now = upgrades.count(game, player)
    shift = game.fx.counter_value(player, upgrades.SHIFT)
    total = upgrades.size(game, player)
    name = game.hero(player).name
    if before is None:
        return t("rosie.state", name=name, active=_names(upgrades.active(game, player)), row=_names(upgrades.row(game, player)))
    count0, shift0 = before
    if shift == shift0 and now > count0:
        return t("rosie.on", name=name, names=_names(upgrades.row(game, player)[count0:now]), n=now, max=total)
    if shift == shift0 and now == 0 and count0 == total:
        return t("rosie.reset", name=name, max=total)
    if now == count0 - 1 and shift == (shift0 + 1) % total:
        return t("rosie.off", name=name, names=upgrades.row(game, player)[-1]["name"], n=now, max=total)
    return t("rosie.state", name=name, active=_names(upgrades.active(game, player)), row=_names(upgrades.row(game, player)))


def _tokens(session, player: int):
    """(faces {GUID: (active Z, inactive Z)}, base order of the GUIDs) of the bot's upgrade tokens, or None when the data has none."""
    table = load_hero_table(session.game.hero_def(player).slug)
    row = upgrades.passive(session.game, player)["row"]
    guids = [table.tokens[u["id"]] for u in row]
    faces = {table.tokens[u["id"]]: (float(table.token_faces[u["id"]]["faces"]["active"]), float(table.token_faces[u["id"]]["faces"]["inactive"])) for u in row}
    return faces, guids


def _put_tokens(session, player: int) -> None:
    """The bot flips and moves its Rosie's physical upgrade tokens to match the engine, and pings each one it touched. The table's answer is
    checked later in the step: a token that cannot be found or a write that failed is said once in the chat (the engine stays the authority)."""
    game, c = session.game, session.cfg
    slots = session.upgrade_slots.get(str(player))
    try:
        faces, base = _tokens(session, player)
        by_guid = {table_guid: u["id"] for u, table_guid in zip(upgrades.passive(game, player)["row"], base)}
        order = [g for u in upgrades.row(game, player) for g, uid in by_guid.items() if uid == u["id"]]
        script = lua_rosie.set_upgrade_tokens(faces, order, upgrades.count(game, player), [tuple(s) for s in slots] if slots else None,
                                              [c.human_seat, c.bot_seat])
    except (HeroTableError, KeyError, TypeError, ValueError):
        return
    op = session._w(script, DOMAIN)
    name = game.hero(player).name

    def check() -> None:
        try:
            res = op.result or {}
        except ERRORS:
            session.say(t("rosie.token_failed", name=name), ChatKind.WARNING)
            return
        if int(res.get("found") or 0) < int(res.get("total") or 0):
            session.say(t("rosie.token_missing", name=name), ChatKind.WARNING)
            return
        if not slots and res.get("before"):
            session.upgrade_slots[str(player)] = [list(p) for p in res["before"]]
    session._post.append(check)


def track(session, announce: bool = False) -> None:
    """Says the upgrade changes since the last look, for the bot's Rosie and the human's. `announce`: also say the state when nothing
    was said yet (the start of a game, a resume). Nothing happens when nobody plays Rosie."""
    game = session.game
    said = session.__dict__.setdefault("_upgrades_said", {})
    for player in (session.bot, session.human):
        now = _state(game, player)
        if now is None:
            continue
        before = said.get(player)
        said[player] = now
        if before == now or (before is None and not announce):
            continue
        session.say(describe(game, player, before), ChatKind.ABILITY)
        if player == session.bot:
            _put_tokens(session, player)


def read_slots(raw) -> dict[str, list[list[float]]]:
    """The `upgrade_slots` of a session file, keeping only well-formed entries (four positions of three numbers)."""
    out: dict[str, list[list[float]]] = {}
    for player, spots in (raw if isinstance(raw, dict) else {}).items():
        if (player in ("0", "1") and isinstance(spots, list) and len(spots) == 4
                and all(isinstance(p, list) and len(p) == 3 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in p) for p in spots)):
            out[player] = [[float(v) for v in p] for p in spots]
    return out


def forget(session) -> None:
    """A restart or a table adoption: the next look says the state again."""
    session.__dict__.pop("_upgrades_said", None)
    session.upgrade_slots.clear()
