"""TTS translators: what an op does to the real table, one function per op type and per who moves the objects.

An op that touches what is on the table leaves an intent (`effects.table.intent`: {"op", ...}); the session hands each
one, with the cause the chat blames, to `translate`. The registry `TRANSLATORS` is keyed by op type and holds two
variants:

  * `bot`   the bot moves the objects itself (a Lua write through `Session._w`, said in the chat) and returns the
            checks to run once the step's composite went out; when the table refuses, the check falls back to the
            human variant, so a failed write never leaves the game stuck;
  * `human` the human acts by hand: the variant says what to move and owes it to the existing flows that wait for it
            and validate it (`Session.pending_discard` settled at "End action", the table sync, the draws the
            human takes themselves).

`mode` picks the variant for an intent, or None when the op has no business with the table (the bot's own draws and
discards are reconciled with its piles). The before/after diff of `session_bot_effects.project` is the final
consistency check: it detects what changed, the intents say which op did it and how (a position in the deck, a zone),
and whatever the ops did not report is translated through this same registry with an intent inferred from the diff.
Phase 1: `draw`, `discard`, `move`. Phase 2: `place`, `swap`, `revive`, `summon` (the human's pieces, as `move`),
`return_to_deck`, `put_in_hand`, `search_deck`, `counter` (the bot's ability tokens), `form` (Hellboy's miniature,
inferred from the counter) and `ongoing` (a scheme entering play). `damage`, `heal` and `set_hp` have no translator:
the dials mirror the engine's HP after every step (`Session._write_dials`), they are not the work of one op. The look
rows of `look_hand` run from the op itself (`session_hidden`). docs/effects-dsl.md, section 21."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .i18n import plural, t
from .spaces import describe
from .tts import effects_bridge, lua
from .tts.client import TTSLuaError
from .tts.hero_table import HeroTable, HeroTableError, load_hero_table
from .tts.lua import ChatKind

DOMAIN = "fx"                  # queue domain of the writes of a projection: no read of the session forces them out early
ERRORS = (TTSLuaError, OSError)
BOT, HUMAN = "bot", "human"
ABILITY_TOKEN = "ability"      # the two-faced token of a hero with forms (Hellboy's)
TOKEN_STEP = 1.5               # distance between the copies of an ability token on the table

Check = Callable[[], None]
Variant = Callable[["object", dict, "Ctx"], list[Check]]


@dataclass(frozen=True)
class Ctx:
    """What a translation needs besides the intent: whose effect the chat blames and the engine snapshot taken before
    the step (`session_bot_effects.snapshot`), None where no diff is involved. `bot_discard`: the loose cards of the
    bot's discard pile as {card id: GUID}, read once before the step's writes (None when nothing needs them)."""
    cause: str = ""
    before: dict | None = None
    bot_discard: dict | None = None


@dataclass(frozen=True)
class Translator:
    mode: Callable[[object, dict], str | None]
    bot: Variant
    human: Variant


TRANSLATORS: dict[str, Translator] = {}


def register(op: str, *, mode: Callable[[object, dict], str | None], human: Variant) -> Callable[[Variant], Variant]:
    """Registers the decorated function as the bot variant of `op`; `human` is the by-hand variant."""
    def wrap(bot: Variant) -> Variant:
        TRANSLATORS[op] = Translator(mode, bot, human)
        return bot
    return wrap


def translate(session, intent: dict, ctx: Ctx) -> list[Check] | None:
    """The checks of the variant that handles `intent`, or None when no translator takes it (the op has none, or the
    intent is not about the table): the caller keeps its diff path."""
    translator = TRANSLATORS.get(intent["op"])
    if translator is None:
        return None
    mode = translator.mode(session, intent)
    if mode is None:
        return None
    return (translator.bot if mode == BOT else translator.human)(session, intent, ctx)


# ---------------------------------------------------------------- shared helpers

def result_of(op) -> dict:
    try:
        return op.result or {}
    except ERRORS:
        return {}


def join_titles(titles) -> str:
    titles = list(titles)
    return titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + t("common.and") + titles[-1]


# ---------------------------------------------------------------- draw (the human's draws)

def _draw_mode(session, intent: dict) -> str | None:
    if intent["player"] != session.human:
        return None                               # the bot's draws are its own hidden zones (`_bot_cards`)
    return BOT if session.cfg.human_deck_guid else HUMAN


def _draw_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    why = f" ({intent['cause']})" if intent.get("cause") else ""
    session.say(t("tr.draw_human", cards=plural(intent["n"], "noun.card"), why=why), ChatKind.YOUR_TURN)
    return []


@register("draw", mode=_draw_mode, human=_draw_human)
def _draw_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """The cards owed to the human are dealt from their physical deck to their hand (`Session._deal_human_cards`)."""
    session._deal_human_cards(intent["n"], intent.get("cause"))
    return []


# ---------------------------------------------------------------- discard

def _discard_mode(session, intent: dict) -> str | None:
    if intent["player"] != session.human:
        return None                               # the bot's discards are reconciled with its pile
    if intent["zone"] == "in_play":
        return BOT if session.cfg.human_ongoing_spot is not None else HUMAN
    return BOT if intent.get("all") else HUMAN    # a whole hand (Crown Of Flame, Ivan 30/10) is moved by the bot


def _discard_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    st = session.game.players[session.human]
    zone = intent["zone"]
    if zone == "in_play":
        return _left_play_by_hand(session, intent, ctx)
    d = session.pending_discard or {"n": 0, "baseline": intent.get("baseline", len(st.discard)), "kind": "cards"}
    if zone == "hand" and "cards" in intent:      # named cards: the human puts them on the pile, the sync waits for them
        by_id = {c.card_id: c for c in st.full_set}
        d["cards"] = list(d.get("cards") or []) + intent["cards"]
        session.pending_discard = d
        session.say(t("tr.discard_named", titles=join_titles(by_id[i].title for i in intent["cards"]), cause=ctx.cause), ChatKind.YOUR_TURN)
    elif intent["n"] > 0:                         # a count: the human chooses which ones
        if not d.get("hand"):
            session._deal_owed_draws()            # the draws that resolved BEFORE this discard are in the hand he discards from
        d["n"] += intent["n"]
        d["hand"] = True                          # the draws the effect owes come after this discard
        session.pending_discard = d
        session.say(t("tr.discard_count", n=intent["n"], reason=intent["reason"], hint=session._wildfire_hint()), ChatKind.YOUR_TURN)
    return []


@register("discard", mode=_discard_mode, human=_discard_human)
def _discard_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    if intent["zone"] == "in_play":
        return _left_play_by_bot(session, intent, ctx)
    # Crown Of Flame (Ivan, 30/10): the bot moves the human's whole hand; what the table could not move is asked by hand
    st = session.game.players[session.human]
    left = session._discard_human_hand(intent["n"], intent["reason"])
    baseline = len(st.discard) + (0 if any(c.title == intent["reason"] for c in st.discard) else 1)   # the plan lands after
    return _discard_human(session, {**intent, "n": left, "baseline": baseline}, ctx)


def _title_of(session, card_id: int) -> str:
    return next(c.title for c in session.game.players[session.human].full_set if c.card_id == card_id)


def _left_play_by_hand(session, intent: dict, ctx: Ctx) -> list[Check]:
    """Your ONGOING left play. With an ONGOING spot it is owed to your discard pile (the sync protects it until it
    is there); without one it already sits on the pile."""
    card_id, title = intent["card"], _title_of(session, intent["card"])
    if session.cfg.human_ongoing_spot is None:
        session.say(t("tr.left_play", title=title, cause=ctx.cause), ChatKind.SCHEME)
        return []
    st = session.game.players[session.human]
    d = session.pending_discard or {"n": 0, "baseline": len(st.discard), "kind": "cards"}
    if card_id in (d.get("cards") or []):
        return []
    d["cards"] = list(d.get("cards") or []) + [card_id]
    session.pending_discard = d
    session.say(t("tr.left_play_hand", title=title, cause=ctx.cause), ChatKind.YOUR_TURN)
    return []


def _left_play_by_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """Your ONGOING scheme left play (Pact Of Freedom when Baba Yaga takes 2+ combat damage...): the bot pings it on
    your ONGOING zone, says why it leaves, waits `ongoing_hold` seconds and moves it to your discard pile itself. Any
    failure (the zone cannot be read, the card is not there exactly once, no identity, the table refuses) falls back
    to asking you to move it (`_left_play_by_hand`)."""
    from .session import TABLE_ERRORS             # the session imports this module: resolved at call time
    cfg, card_id = session.cfg, intent["card"]
    title = _title_of(session, card_id)
    try:
        here = [r for r in session._rd_ongoing("human")
                if isinstance(r, dict) and r.get("id") == card_id and isinstance(r.get("guid"), str)]
        if len(here) != 1:
            raise TTSLuaError(f"{title} is not exactly once in your ONGOING zone ({len(here)})")
        identity = session._identity("human")
        move = lua.card_to_discard(here[0]["guid"], cfg.human_discard_zone, cfg.human_card_ids, identity=identity)
        _show_and_wait(session, here[0]["guid"], t("tr.left_play_ping", title=title, cause=ctx.cause))
        op = session._w(move, "cards")
    except TABLE_ERRORS:
        return _left_play_by_hand(session, intent, ctx)
    session._transit[card_id] = 0                 # the sync keeps it on the engine's pile until the table shows it there

    def check() -> None:
        res = result_of(op)
        if res.get("zone") is not True or res.get("moved") != [card_id]:
            _left_play_by_hand(session, intent, ctx)
    return [check]


def _show_and_wait(session, guid: str, text: str) -> None:
    """Pings the card, says why in the chat and on screen, and lets the ping be seen: in a batch the wait is inside
    the TTS script that carries the ping (`lua.hold`), otherwise it is a sleep."""
    cfg = session.cfg
    session._w(lua.ping_objects([cfg.bot_seat, cfg.human_seat], [[guid]]), "misc")
    session.say(text, ChatKind.SCHEME, shown=True)
    for chunk in lua.ascii_text(text):
        session._w(lua.broadcast(chunk, ChatKind.SCHEME), "misc")
    session._hold(cfg.ongoing_hold)


# ---------------------------------------------------------------- move (the human's miniatures the bot's effects move)

def _move_mode(session, intent: dict) -> str | None:
    return BOT if intent["owner"] == session.human else None     # the human moves their own by hand (session_moves)


def _moved_piece(session, intent: dict, ctx: Ctx):
    """The human's fighter if it really ended elsewhere than it started (a fall is announced by the combat / hp
    code), else None."""
    pos0, alive0 = ctx.before["human_pieces"][intent["fid"]]
    f = session.game.fighters[intent["fid"]]
    if not f.alive or f.pos is None or (alive0 and f.pos == pos0):
        return None
    return f


def _move_say(session, intent: dict, ctx: Ctx, moved: bool) -> None:
    g = session.game
    f = g.fighters[intent["fid"]]
    name, space = session._name(f), describe(g, f.pos, (f.fid,), session._name)
    walks = ctx.before["human_pieces"][f.fid][1]
    if moved:
        session.say(t("tr.moved.moves.done" if walks else "tr.moved.returns.done", name=name, space=space), ChatKind.MOVE)
    else:
        session.say(t("tr.moved.moves.manual" if walks else "tr.moved.returns.manual", name=name, space=space), ChatKind.YOUR_TURN)


def _move_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    if _moved_piece(session, intent, ctx) is not None:
        _move_say(session, intent, ctx, moved=False)
    return []


@register("move", mode=_move_mode, human=_move_human)
def _move_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """Ivan's rule "the bot moves what its card says": `move_piece` by GUID (the one the table shows for a miniature
    with states), said once the table confirms; when it does not, the human is told to move it."""
    f = _moved_piece(session, intent, ctx)
    if f is None:
        return []
    guids = session._guids(f.fid)
    guid = guids[0]
    if len(guids) > 1:                            # a miniature with states: the GUID the table shows now
        info = session._table_pieces().get(f.fid) or {}
        guid = info["guid"] if info.get("found") else guid
    op = session._w(effects_bridge.move_human_piece(session.game.board, guid, f.pos), DOMAIN)

    def check() -> None:
        _move_say(session, intent, ctx, moved=bool(result_of(op).get("moved")))
    return [check]


for _op in ("place", "swap", "revive", "summon"):             # a bot effect that puts the human's miniature elsewhere
    register(_op, mode=_move_mode, human=_move_human)(_move_bot)


# ---------------------------------------------------------------- cards between a hand/discard pile and a deck

WHERE_YOU = {"shuffle": "tr.where.you.shuffle", "bottom": "tr.where.you.bottom", "top": "tr.where.you.top"}
WHERE_BOT = {"shuffle": "tr.where.bot.shuffle", "bottom": "tr.where.bot.bottom", "top": "tr.where.bot.top"}
HAND_WHERE = {"top": "tr.where.hand.top", "bottom": "tr.where.hand.bottom", "shuffle": "tr.where.hand.shuffle"}
WHERE_DONE = {"shuffle": "tr.where.done.shuffle", "bottom": "tr.where.done.bottom", "top": "tr.where.done.top"}


def is_tail(deck: list[int], ids: list[int]) -> bool:
    return bool(ids) and deck[-len(ids):] == ids


def deck_position(d0: list[int], d1: list[int], ids: list[int]) -> tuple[str, list[int]]:
    """Where a step put `ids` (cards that were not in the deck) into a deck that went from `d0` to `d1`: a put on the
    bottom or on top keeps the rest of the deck in its order, a shuffle (the engine permutes the whole deck) does
    not. With fewer than 2 other cards the three are indistinguishable: shuffling is the harmless reading. Returns
    (position, the ids in the order the deck shows them)."""
    n = len(ids)
    rest = [i for i in d1 if i not in ids]
    kept = rest == [i for i in d0 if i in rest]
    if kept and len(rest) >= 2 and set(d1[-n:]) == set(ids):
        return "bottom", d1[-n:]
    if kept and len(rest) >= 2 and set(d1[:n]) == set(ids):
        return "top", d1[:n]
    return "shuffle", list(ids)


def _by_id(session, player: int) -> dict:
    return {c.card_id: c for c in session.game.players[player].full_set}


def _short(session, missing: set[int], by_id: dict, what: str) -> None:
    if missing:
        session.say(t("tr.short", titles=join_titles(by_id[i].title for i in sorted(missing)), what=what), ChatKind.WARNING)


def _unmoved(op, ids: list[int], guids: dict[int, str]) -> set[int]:
    """The ids of a shuffle-into-deck op that did not reach the deck. The script names the GUIDs it moved; a reply
    that does not (an older script) only counts them, and then a short count blames every card."""
    res = result_of(op)
    if isinstance(res.get("moved"), list):
        return {i for i in ids if guids[i] not in res["moved"]}
    return set(ids) if res.get("added") != len(ids) else set()


def _return_mode(session, intent: dict) -> str | None:
    if intent["player"] == session.bot:
        return BOT                                # its own cards: written by GUID, the human moves them if the table refuses
    return BOT if intent["zone"] == "discard" and session.cfg.human_deck_guid else HUMAN    # their hand is theirs


def _bot_position(session, intent: dict) -> str:
    """"bottom" only when the op said so and the engine's deck really ends with those cards; else it is shuffled."""
    deck = [c.card_id for c in session.game.players[session.bot].deck]
    return "bottom" if intent.get("position") in (None, "bottom") and is_tail(deck, intent["cards"]) else "shuffle"


def _bot_what(zone: str, position: str) -> str:
    if zone == "hand":
        return t("tr.bot_what.hand")
    return t("tr.bot_what.bottom" if position == "bottom" else "tr.bot_what.shuffled")


def _return_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    """The human puts the cards back by hand: their own hand cards (named in the chat), their own discard pile cards
    when the bot has no deck to write to, and the bot's cards when the table refused."""
    ids, zone = intent["cards"], intent["zone"]
    if intent["player"] == session.bot:
        position = intent.get("resolved") or _bot_position(session, intent)
        _short(session, set(ids), _by_id(session, session.bot), _bot_what(zone, position))
        return []
    st = session.game.players[session.human]
    by_id = _by_id(session, session.human)
    if zone == "hand":
        position = intent.get("position") or ("top" if [c.card_id for c in st.deck][:len(ids)] == ids else "shuffle")
        session.say(t("tr.put_hand", titles=join_titles(by_id[i].title for i in ids), where=t(HAND_WHERE[position]), cause=ctx.cause),
                    ChatKind.YOUR_TURN)
        return []
    position, ordered = _human_deck_position(session, intent, ctx)
    ordered = _noted_by_hand(session, ordered, position, by_id, ctx)
    if ordered:
        session.say(t("tr.put_discard", titles=join_titles(by_id[i].title for i in ordered), where=t(WHERE_YOU[position]), cause=ctx.cause),
                    ChatKind.YOUR_TURN)
    return []


def _human_deck_position(session, intent: dict, ctx: Ctx) -> tuple[str, list[int]]:
    if intent.get("position"):
        return intent["position"], list(intent["cards"])
    deck = [c.card_id for c in session.game.players[session.human].deck]
    return deck_position(ctx.before["human"]["deck"], deck, intent["cards"])


def _noted_by_hand(session, ordered: list[int], position: str, by_id: dict, ctx: Ctx) -> list[int]:
    """Session_pile: the cards the human already moved and the bot detected are only noted. Returns the rest."""
    by_hand = [i for i in ordered if i in session.hand_deck]
    if by_hand:
        session.say(t("tr.note_deck", titles=join_titles(by_id[i].title for i in by_hand), cause=ctx.cause), ChatKind.SCHEME)
    return [i for i in ordered if i not in by_hand]


@register("return_to_deck", mode=_return_mode, human=_return_human)
def _return_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    if intent["player"] != session.bot:
        return _human_discard_to_deck(session, intent, ctx)
    cfg, ids, zone = session.cfg, intent["cards"], intent["zone"]
    by_id = _by_id(session, session.bot)
    position = _bot_position(session, intent)
    what = _bot_what(zone, position)
    if zone == "hand":
        bottom = position == "bottom"
        op = session._w(lua.hand_to_deck(cfg.bot_seat, ids, cfg.bot_deck_guid, cfg.bot_card_ids,
                                         identity=session._identity(), bottom=bottom, shuffle=not bottom), DOMAIN)
        session.say(t("tr.bot_puts_hand_bottom" if bottom else "tr.bot_puts_hand_shuffle", cards=plural(len(ids), "noun.card")), ChatKind.SCHEME)
        return [lambda: _fall_back(session, intent, ctx, position, set(ids) - set(result_of(op).get("placed") or []))]
    titles = join_titles(by_id[i].title for i in ids)
    if position == "bottom":
        ops = [(i, session._w(lua.card_to_deck_bottom(i, cfg.bot_deck_guid, cfg.bot_card_ids,
                                                       identity=session._identity()), DOMAIN)) for i in ids]
        session.say(t("tr.bot_puts_bottom", titles=titles), ChatKind.SCHEME)
        return [lambda: _fall_back(session, intent, ctx, position,
                                   {i for i, op in ops if not result_of(op).get("placed")})]
    guids = ctx.bot_discard or {}
    known = [i for i in ids if i in guids]
    op = session._w(lua.shuffle_into_deck(cfg.bot_deck_guid, [guids[i] for i in known], cfg.bot_card_ids,
                                          identity=session._identity()), DOMAIN) if known else None
    session.say(t("tr.bot_shuffles", titles=titles), ChatKind.SCHEME)
    return [lambda: _fall_back(session, intent, ctx, position,
                               set(ids) - (set(known) - _unmoved(op, known, guids) if op is not None else set()))]


def _fall_back(session, intent: dict, ctx: Ctx, position: str, missing: set[int]) -> None:
    """What the table did not take is left to the human variant, worded for the position the bot tried."""
    if missing:
        _return_human(session, {**intent, "cards": sorted(missing), "resolved": position}, ctx)


def _human_discard_to_deck(session, intent: dict, ctx: Ctx) -> list[Check]:
    """Ivan's rule (29/10): the cards the human picked out of their own discard pile for an effect that moves them into
    their deck are moved by the bot, by GUID off the pile (`_rd_human_discard`), with the HUMAN's deck GUID and
    identity; the bot shuffles their deck when the card says so. Their hand is never touched (the builders refuse
    hand zones) and their deck is never read. A card already gone from the pile was moved by the human: said, not
    failed."""
    cfg, cause = session.cfg, ctx.cause
    by_id = _by_id(session, session.human)
    position, ordered = _human_deck_position(session, intent, ctx)
    ids = ordered = _noted_by_hand(session, ordered, position, by_id, ctx)
    if not ordered:
        return []
    guids = {r["id"]: r["guid"] for r in session._rd_human_discard() if isinstance(r, dict) and "guid" in r}
    gone = [i for i in ordered if i not in guids]
    if gone:
        session.say(t("tr.gone", titles=join_titles(by_id[i].title for i in gone), where=t(WHERE_DONE[position]), cause=cause), ChatKind.SCHEME)
    todo = [i for i in ordered if i in guids]
    if not todo:
        return []
    from .session import SessionError             # the session imports this module: resolved at call time
    try:
        identity = session._identity("human")
    except ERRORS + (SessionError,) as e:         # no identity, no write: the human does it
        session.say(t("tr.cannot_touch_deck", err=e, titles=join_titles(by_id[i].title for i in todo), where=t(WHERE_YOU[position])),
                    ChatKind.WARNING)
        return []
    session.fx_in_flight.update(todo)
    session.say(t("tr.inserts", titles=join_titles(by_id[i].title for i in todo), where=t(WHERE_BOT[position]), cause=cause), ChatKind.SCHEME)
    what = t("tr.what_you", where=t(WHERE_YOU[position]))
    if position == "shuffle":
        op = session._w(lua.shuffle_into_deck(cfg.human_deck_guid, [guids[i] for i in todo], cfg.human_card_ids,
                                              identity=identity), DOMAIN)
        return [lambda: _short(session, _unmoved(op, todo, guids), by_id, what)]
    build = lua.card_to_deck_bottom if position == "bottom" else lua.card_to_deck_top
    order = todo if position == "bottom" else list(reversed(todo))      # putObject adds on top: the first id ends up last
    ops = [(i, session._w(build(guids[i], cfg.human_deck_guid, cfg.human_card_ids, identity=identity), DOMAIN))
           for i in order]
    return [lambda: _short(session, {i for i, op in ops if not result_of(op).get("placed")}, by_id, what)]


# ---------------------------------------------------------------- put_in_hand (a pile card back into a hand)

def _put_mode(session, intent: dict) -> str | None:
    if intent["zone"] != "discard":
        return None                               # out of a deck: hidden, counted by `search_deck`
    return BOT if intent["player"] == session.bot else HUMAN


def _put_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    ids = intent["cards"]
    if intent["player"] == session.bot:           # the table refused (or the card is not loose on the pile)
        for i in ids:
            session.say(t("tr.return_bot_fail", title=_by_id(session, session.bot)[i].title), ChatKind.WARNING)
        return []
    session.say(t("tr.pickup", titles=join_titles(_by_id(session, session.human)[i].title for i in ids), cause=ctx.cause), ChatKind.YOUR_TURN)
    return []


@register("put_in_hand", mode=_put_mode, human=_put_human)
def _put_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    cfg, by_id, guids, checks = session.cfg, _by_id(session, session.bot), ctx.bot_discard or {}, []
    for i in intent["cards"]:
        title = by_id[i].title
        if i in session.said_returns:             # the Wildfire scene already said it came back
            session.said_returns.discard(i)
        else:
            session.say(t("tr.bot_recovers", title=title), ChatKind.SCHEME)
        if i not in guids:
            session.say(t("tr.not_loose", title=title), ChatKind.WARNING)
            continue
        op = session._w(lua.return_card_to_hand(guids[i], cfg.bot_seat), DOMAIN)
        checks.append(lambda op=op, i=i: None if result_of(op).get("returned") else _put_human(
            session, {**intent, "cards": [i]}, ctx))
    return checks


# ---------------------------------------------------------------- search_deck (the bot takes cards out of its deck)

def _search_mode(session, intent: dict) -> str | None:
    return BOT if intent["player"] == session.bot else None    # the human's own deck is searched by hand (table notes)


def _search_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    """Nothing for a human to move: the bot's deck is the bot's. The line is all there is."""
    session.say(t("tr.bot_takes", cards=plural(intent["n"], "noun.card")), ChatKind.SCHEME)
    return []


@register("search_deck", mode=_search_mode, human=_search_human)
def _search_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """The real order of the bot's deck is unknown to the engine: what it took is a top card on the table, so the
    engine's draw counters follow (the card is dealt from the top of the real deck)."""
    g, bot = session.game, session.bot
    g.drawn[bot] += intent["n"]
    g.draw_events[bot] += intent["n"]
    return _search_human(session, intent, ctx)


# ---------------------------------------------------------------- counter (the bot's ability tokens) and form

def hero_table(session) -> HeroTable | None:
    try:
        return load_hero_table(session.game.hero_def(session.bot).slug)
    except HeroTableError:
        return None


def token_spot(session, k: int) -> tuple[float, float, float]:
    """Where the k-th copy of an ability token goes: `token_spot` of the configuration (calibrate live) or, by
    default, beside the bot's deck."""
    c = session.cfg
    x, y, z = c.token_spot if c.token_spot is not None else (c.bot_deck_spot[0] - 3.0, c.bot_card_spot[1],
                                                               c.bot_deck_spot[1])
    return (x + TOKEN_STEP * k, y, z)


def _counter_mode(session, intent: dict) -> str | None:
    if intent["player"] != session.bot:
        return None                               # the human's counters are their dials (`_track_destiny`)
    table = hero_table(session)
    return BOT if table is not None and table.tokens.get(intent["name"]) else None    # a counter without a token on the table


def _counter_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    """A token the table could not give or take: the human puts one next to the hero or removes it."""
    g, name, hero = session.game, intent["name"], session._name(session.game.hero(session.bot))
    delta = intent.get("delta") or g.fx.counter_value(session.bot, name, 0) - ctx.before["counters"].get(name, 0)
    if delta > 0:
        session.say(t("tr.token_fail_add", name=name, hero=hero), ChatKind.WARNING)
    else:
        session.say(t("tr.token_fail_remove", name=name, hero=hero), ChatKind.WARNING)
    return []


@register("counter", mode=_counter_mode, human=_counter_human)
def _counter_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """One copy taken from the source token per active point, removed when spent."""
    g, bot, name = session.game, session.bot, intent["name"]
    c0, c1 = ctx.before["counters"].get(name, 0), g.fx.counter_value(bot, name, 0)
    if c0 == c1:
        return []
    source = hero_table(session).tokens[name]
    copies = session.token_copies.setdefault(name, [])
    hero, checks = session._name(g.hero(bot)), []
    if c1 > c0:
        for k in range(c1 - c0):
            op = session._w(lua.take_token_copy(source, token_spot(session, len(copies) + k)), DOMAIN)
            checks.append(lambda op=op: _token_taken(session, op, intent, ctx))
        session.say(t("tr.token_on", hero=hero, tokens=plural(c1 - c0, "noun.token"), name=name, n=c1), ChatKind.ABILITY)
    else:
        for _ in range(c0 - c1):
            if not copies:
                session.say(t("tr.token_missing", hero=hero, name=name), ChatKind.WARNING)
                break
            op = session._w(lua.remove_token(copies.pop()), DOMAIN)
            checks.append(lambda op=op: None if result_of(op).get("removed") else _counter_human(
                session, {**intent, "delta": -1}, ctx))
        session.say(t("tr.token_off", hero=hero, tokens=plural(c0 - c1, "noun.token"), name=name, n=c1), ChatKind.ABILITY)
    return checks


def _token_taken(session, op, intent: dict, ctx: Ctx) -> None:
    guid = result_of(op).get("taken")
    if guid:
        session.token_copies.setdefault(intent["name"], []).append(guid)
    else:
        _counter_human(session, {**intent, "delta": 1}, ctx)


def _form_head(session, now: str) -> str:
    g, bot = session.game, session.bot
    forms = g.hero_def(bot).forms
    return t("tr.form_head", hero=session._name(g.hero(bot)), form=now, n=g.counter(bot, forms.counter), counter=forms.counter)


def _form_mode(session, intent: dict) -> str | None:
    return BOT if intent["player"] == session.bot else None


def _form_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    session.say(t("tr.form_human", head=_form_head(session, intent["form"])), ChatKind.ABILITY)
    return []


@register("form", mode=_form_mode, human=_form_human)
def _form_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """Hellboy's form (the bot's): the miniature swaps state, the ability token is flipped and both are pinged."""
    g, bot, now = session.game, session.bot, intent["form"]
    forms, hero = g.hero_def(bot).forms, g.hero(bot)
    name, head = session._name(hero), _form_head(session, now)
    table = hero_table(session)
    pieces = list(table.fighters[hero.fid].pieces) if table and hero.fid in table.fighters else []
    state = 1 if now == forms.below else 2
    if len(pieces) < 2 or state > len(pieces):
        return _form_human(session, intent, ctx)
    info = session._table_pieces().get(hero.fid) or {}
    current = info["guid"] if info.get("found") else pieces[0 if state == 2 else 1]
    token = table.tokens.get(ABILITY_TOKEN)
    op_state = session._w(lua.set_state(current, state), DOMAIN)
    op_token = session._w(lua.flip_token(token), DOMAIN) if token else None
    groups = ([[token]] if token else []) + [pieces]
    session._w(lua.ping_objects([session.cfg.bot_seat, session.cfg.human_seat], groups), "misc")
    session.say(t("tr.form_both" if token else "tr.form_one", head=head), ChatKind.ABILITY)

    def check() -> None:
        if not result_of(op_state).get("guid"):
            session.say(t("tr.form_fail_mini", name=name, form=now), ChatKind.WARNING)
        if op_token is not None and not result_of(op_token).get("flipped"):
            session.say(t("tr.form_fail_token", name=name), ChatKind.WARNING)
    return [check]


# ---------------------------------------------------------------- ongoing (a scheme enters play)

def _ongoing_mode(session, intent: dict) -> str:
    if intent["player"] == session.bot:
        return BOT if session.cfg.bot_ongoing_spot is not None else HUMAN
    return HUMAN                                  # theirs: they leave it on their ONGOING zone


def _ongoing_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    if intent["player"] == session.bot:           # no spot configured, or the table refused the card
        title = _by_id(session, session.bot)[intent["card"]].title
        if session.cfg.bot_ongoing_spot is None:
            session.say(t("tr.ongoing_nospot", title=title), ChatKind.WARNING)
        else:
            session.say(t("tr.ongoing_fail", title=title), ChatKind.WARNING)
        return []
    by_id, was = _by_id(session, session.human), intent.get("replaces")
    replaced = t("fx.replaces", title=by_id[was].title) if was is not None and was in by_id else ""
    where = t("fx.where_ongoing" if session.cfg.human_ongoing_spot is not None else "fx.where_discard")
    session.say(t("fx.in_play", title=by_id[intent["card"]].title, replaced=replaced, where=where), ChatKind.SCHEME)
    return []


@register("ongoing", mode=_ongoing_mode, human=_ongoing_human)
def _ongoing_bot(session, intent: dict, ctx: Ctx) -> list[Check]:
    """The bot's ONGOING scheme that just entered play goes face up on its ONGOING spot (its own card, out of its
    hand); when it leaves play the reconciliation discards it from there (the spot is in the scope)."""
    cfg, card = session.cfg, intent["card"]
    title = _by_id(session, session.bot)[card].title
    x, y, z = cfg.bot_ongoing_spot
    op = session._w(lua.place_card_face_up(card, cfg.bot_seat, x, y, z, cfg.rot_y, cfg.bot_card_ids,
                                           identity=session._identity()), DOMAIN)
    session.fx_in_flight.add(card)
    session.say(t("tr.ongoing_placed", title=title), ChatKind.SCHEME)

    def check() -> None:
        if not result_of(op).get("placed"):
            _ongoing_human(session, intent, ctx)
    return [check]


# ---------------------------------------------------------------- tucked inventions and cards removed from the game (Donatello)

ASIDE_STEP = 1.6               # distance between the cards laid side by side at a set-aside spot


def _aside_spot(session, intent: dict):
    return session.cfg.bot_tuck_spot if intent["op"] == "tuck" else session.cfg.bot_removed_spot


def _aside_mode(session, intent: dict) -> str:
    if intent["player"] != session.bot:
        return HUMAN                              # theirs: they tuck and set aside by hand
    return BOT if _aside_spot(session, intent) is not None else HUMAN


def _aside_ids(intent: dict) -> list[int]:
    return list(intent["cards"]) if intent["op"] == "remove" else [intent["card"]]


def _aside_human(session, intent: dict, ctx: Ctx) -> list[Check]:
    by_id = _by_id(session, intent["player"])
    titles = join_titles(by_id[i].title for i in _aside_ids(intent))
    mine = intent["player"] == session.human
    kind = "tuck" if intent["op"] == "tuck" else "remove"
    session.say(t(f"tr.{kind}_{'human' if mine else 'bot'}", titles=titles), ChatKind.SCHEME if kind == "tuck" else ChatKind.YOUR_TURN)
    return []


def _lay_aside(session, intent: dict, ctx: Ctx) -> list[Check]:
    """The bot's invention goes under (beside) its hero card, a card it removes from the game away from its discard
    pile: one `discard_cards` write to the configured spot, the cards side by side in the order they left play."""
    cfg, st = session.cfg, session.game.players[session.bot]
    ids = _aside_ids(intent)
    pile = [c.card_id for c in (st.tucked if intent["op"] == "tuck" else st.removed)]
    x, y, z = _aside_spot(session, intent)
    spots = [(x + pile.index(i) * ASIDE_STEP, y, z) for i in ids]
    op = session._w(lua.discard_cards(ids, spots, cfg.rot_y, identity=session._identity(), scope=session._scope(),
                                      id_range=cfg.bot_card_ids), DOMAIN)
    session.fx_in_flight.update(ids)
    session.bot_discarded.difference_update(ids)
    by_id = _by_id(session, session.bot)
    session.say(t(f"tr.{intent['op']}_placed", titles=join_titles(by_id[i].title for i in ids)), ChatKind.SCHEME)

    def check() -> None:
        if set(ids) - set(result_of(op).get("moved") or []):
            session.say(t(f"tr.{intent['op']}_fail"), ChatKind.WARNING)
            _aside_human(session, intent, ctx)
    return [check]


register("tuck", mode=_aside_mode, human=_aside_human)(_lay_aside)
register("remove", mode=_aside_mode, human=_aside_human)(_lay_aside)
