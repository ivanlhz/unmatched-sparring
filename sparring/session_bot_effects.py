"""The bot's card effects reach the real table (D3).

What a step of the bot (a combat, a scheme, its start of turn) changed outside its own miniatures and discards is
read off the engine by diff: `snapshot` before the step, `project` after it. The ops report what they did to the table
as intents (`effects.table.intent`) and the diff is the final consistency check: an intent is honoured for what the
diff confirms, and a change no op reported is translated with an intent inferred from the diff. Both go to the
translators of `session_translators` (one per op type, a variant where the bot writes the table and one where the
human does), which queue F1 builders through `Session._w`, so everything travels in the step's one combined script,
and say in the chat what moved:

  * the human's miniatures a bot effect moved or returned (Concussion Device, Leap Away, Foul Journey, Pact Of
    Freedom, Right Hand Of Doom...): `move`, `place`, `swap`, `revive`, `summon`, `move_piece` by GUID, Ivan's rule
    "the bot moves what its card says";
  * Hellboy's form (the bot's): `form`, the miniature swaps state, the ability token is flipped and both are pinged;
  * ability tokens (Abe's Intuition): `counter`, one copy taken from the source token per active point, removed when
    spent;
  * the bot's own hidden zones: `return_to_deck` (Glimpse Of Hell, Pyrotechnics, Pancakes!, Rekindle, Searing
    Clarity), `put_in_hand` (Ward And Prepare, Wildfire) and `search_deck` (Read The Bones: the real order of the
    deck is unknown to the engine, so the cards are dealt from the top);
  * the bot's ONGOING scheme entering play: `ongoing`, face up on its ONGOING spot.

The human's cards are the human's (`setPositionSmooth` never takes a card out of a hand zone and the bot never
reads or reorders their deck): the chat names what to move and `Session.sync_human` / `pending_discard` wait for it.
One exception, Ivan's ruling of 29/10 (live test, Searing Clarity): a card the human picked at the panel out of
their own PUBLIC discard pile for an effect that moves it into their deck is moved by the bot, by GUID, and the bot
shuffles their deck when the card says so (`return_to_deck`, zone discard). Since Ivan's ruling of 31/10 the human's
own discard -> deck picks are made by hand instead (`session_pile`: the human moves them, the bot detects them at
Done and the translator only notes them); the bot's write stays for a request that did not go through the table. A
failed write is said once and the table wins at the next read, like every other projection of the session.

Ivan's rule on hidden information: `read_human_hand` is the only reader of the human's hand; it is installed as
`Game.hand_reader` and called by the `look_hand` op alone, at resolution. Clones never carry the reader."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

from .cards import Card
from .i18n import plural, t
from .session_translators import Ctx, combat_card_to_deck, is_tail, translate
from .tts import lua
from .tts.lua import ChatKind



DIRECT_OPS = ("tuck", "remove", "reveal_deck", "shuffle_deck", "stack_top", "hand_to_deck_all", "future_look")     # translated as they were reported, no diff involved


def bot_cause() -> str:
    """Whose effect the chat blames for what the human must do on the table."""
    return t("cause.bot_effect")


# ---------------------------------------------------------------- the hand the bot may look at

def read_human_hand(session, player: int) -> list[Card]:
    """The real hand of `player` for a `look_hand` op (the only caller, through `Game.hand_reader`). For the human
    it is read from the table now and the engine's virtual hand becomes exactly those cards; the bot's own hand is
    the engine's. A table failure propagates: the combat is rolled back and the button repeated."""
    g = session.game
    if player != session.human:
        return list(g.players[player].hand)
    rows = session.client.call_lua(lua.read_hand(session.cfg.human_seat)) or []
    session.fx_looked = True                     # the virtual hand is re-identified: `project` must not read it as draws
    st = g.players[player]
    by_id = {c.card_id: c for c in st.full_set}
    cards = [by_id[r["id"]] for r in rows if isinstance(r, dict) and r.get("id") in by_id]
    for c in cards:
        session.make_known(c, keep=tuple(cards))
    for c in [c for c in st.hand if c not in cards]:     # the rest of the virtual hand was never there
        st.hand.remove(c)
        st.deck.append(c)
    return cards


# ---------------------------------------------------------------- snapshot and projection

def zones(st) -> dict:
    return {"hand": [c.card_id for c in st.hand], "deck": [c.card_id for c in st.deck],
            "discard": [c.card_id for c in st.discard]}


def snapshot(session) -> dict:
    """JSON-safe: it lives in `Pending.combat["fx"]` while a combat is paused at the panel and in
    `Session.fx_unprojected` between the end of the human's turn and the bot's first write."""
    g, bot, human = session.game, session.bot, session.human
    flow = session.pending.flow if session.pending is not None else None
    return {"human_pieces": {f.fid: [f.pos, f.alive] for f in g.own(human, alive_only=False)},
            "form": g.form(bot), "counters": dict(g.fx.counters[bot]),
            "bot": zones(g.players[bot]), "human": zones(g.players[human]),
            "in_play": g.fx.ongoing_card_id(human), "bot_in_play": g.fx.ongoing_card_id(bot),
            "drawn": g.drawn[bot], "seen": list(g.players[bot].known.seen),
            "bot_played": [c.card_id for owner, c in (flow.played if flow is not None else ()) if owner == bot]}


def project(session, before: dict | None, played: frozenset = frozenset(), cause: str | None = None) -> Callable[[], None]:
    """Queues the writes for everything that changed since `before` and says it. Returns the function that checks
    the results: call it after the step's composite went out (as `_project_stage`'s is called). `played`: cards
    the human played in this combat, which left their hand by their own hand. `cause`: whose effect the chat blames
    for what the human has to do (the bot's, or their own card's in E2).

    The intents the ops reported say which op did what; the diff against `before` is the final consistency check:
    an intent is honoured only for what the diff confirms, and a change no op reported is translated with an intent
    inferred from the diff."""
    intents = _drain_intents(session)             # also when there is nothing to project: no stale intent reaches the next step
    if before is None:
        return lambda: None
    moved = set(session.fx_in_flight)             # what this button already moved (a look row's pick, E3)
    looked, session.fx_looked = session.fx_looked, False
    ctx = Ctx(cause or bot_cause(), before)
    checks = [c for i in intents if i["op"] in DIRECT_OPS for c in translate(session, i, ctx) or []]
    checks += _human_pieces(session, before, intents, ctx) + _form(session, before, ctx) + _tokens(session, before, intents, ctx)
    checks += _bot_cards(session, before, moved, intents, ctx) + _bot_ongoing(session, before, intents, ctx)
    checks += _human_cards(session, before, played, looked, ctx, intents)

    def fin() -> None:
        for check in checks:
            check()
    return fin


def _drain_intents(session) -> list[dict]:
    """What the ops reported since the last projection (`effects.table.intent`). The diff below finds what changed;
    an intent says which op did it, and the translator of that op handles it."""
    intents = session.game.fx.intents
    if not intents:
        return []
    taken, intents[:] = list(intents), []
    return taken


def _groups(intents: list[dict], op: str, player: int, zone: str, ids: list[int], keep_order: bool = False) -> list[dict]:
    """The intents for `ids`, the cards the diff shows moved: those the ops reported (merged by position, cut down to
    what the diff confirms) and one more, with no position, for the cards no op reported. `keep_order`: the
    cards go in the order the op put them (a deck order), else in the diff's."""
    reported: dict = {}
    for i in intents:
        if (i["op"], i.get("player"), i.get("zone")) == (op, player, zone):
            have = reported.setdefault(i.get("position"), [])
            have += [c for c in i["cards"] if c in ids and not any(c in other for other in reported.values())]
    out = []
    for position, got in reported.items():
        got = got if keep_order else [c for c in ids if c in got]
        if got:
            out.append({"op": op, "player": player, "zone": zone, "cards": got, "position": position})
    rest = [c for c in ids if not any(c in o["cards"] for o in out)]
    if rest:
        out.append({"op": op, "player": player, "zone": zone, "cards": rest, "position": None})
    return out


# ---------------------------------------------------------------- the human's miniatures

PIECE_OPS = ("move", "place", "swap", "revive", "summon")


def _human_pieces(session, before: dict, intents: list[dict], ctx: Ctx) -> list[Callable[[], None]]:
    """The piece translators take every human miniature the diff shows elsewhere; the intent of the op that did it
    (`move`, `place`, `swap`, `revive`, `summon`) is used when there is one, else the move is inferred from the diff."""
    reported = {i["fid"]: i for i in intents if i["op"] in PIECE_OPS}
    checks = []
    for fid in before["human_pieces"]:
        intent = reported.get(fid) or {"op": "move", "fid": fid, "owner": session.human}
        checks += translate(session, intent, ctx) or []
    return checks


# ---------------------------------------------------------------- the bot's form (Hellboy) and ability tokens (Abe)

def _form(session, before: dict, ctx: Ctx) -> list[Callable[[], None]]:
    g, bot = session.game, session.bot
    now = g.form(bot)
    if g.hero_def(bot).forms is None or now == before["form"]:
        return []
    return translate(session, {"op": "form", "player": bot, "form": now}, ctx) or []


def _tokens(session, before: dict, intents: list[dict], ctx: Ctx) -> list[Callable[[], None]]:
    g, bot, checks = session.game, session.bot, []
    reported = {i["name"]: i for i in intents if i["op"] == "counter" and i["player"] == bot}
    for name in sorted(set(before["counters"]) | set(g.fx.counters[bot])):
        intent = reported.get(name) or {"op": "counter", "player": bot, "name": name}
        checks += translate(session, intent, ctx) or []
    return checks


# ---------------------------------------------------------------- the bot's own hidden zones

def _bot_cards(session, before: dict, moved: set, intents: list[dict], ctx: Ctx) -> list[Callable[[], None]]:
    """Hand -> deck (Glimpse Of Hell, Pyrotechnics), discard -> deck (Pancakes!, Rekindle, Searing Clarity), discard ->
    hand (Ward And Prepare, Wildfire) and cards taken from the deck (Read The Bones: the real order of the deck is
    unknown to the engine, so they are dealt from the top). `moved`: cards another write of this button already took
    to their place (never moved twice)."""
    g, bot = session.game, session.bot
    st = g.players[bot]
    b0, b1 = before["bot"], zones(st)
    just_played = set(b0["hand"]) | set(before.get("bot_played") or ())    # a combat stopped at a choice has the card in play, not in hand
    played_back = [i for it in intents if it["op"] == "return_to_deck" and it["player"] == bot and it["zone"] == "discard"
                   for i in it["cards"] if i in just_played and i in b1["deck"] and i not in moved]    # DARK PACT: the card it just played
    hand_to_deck = [i for i in b0["hand"] if i in b1["deck"] and i not in moved and i not in played_back]
    drawn_back = {i for it in intents if it["op"] == "return_to_deck" and it["player"] == bot and it["zone"] == "discard"
                  for i in it["cards"] if i in b1["hand"]}      # shuffled into the deck and drawn in the same step (Alpine Fortress): the table shuffles it in and deals the draws
    disc_to_deck = [i for i in b0["discard"] if (i in b1["deck"] or i in drawn_back) and i not in moved and i not in played_back]
    disc_to_hand = [i for i in b0["discard"] if i in b1["hand"] and i not in moved and i not in drawn_back]
    taken = len([i for i in b0["deck"] if i in b1["hand"]]) - max(0, g.drawn[bot] - before["drawn"])
    session.fx_in_flight.update(hand_to_deck + disc_to_deck + disc_to_hand + played_back)
    for i in disc_to_deck + disc_to_hand:
        session.bot_discarded.discard(i)          # it may be discarded again later: the table has to move it again
    guids = {r["id"]: r["guid"] for r in session._rd_bot_discard()} if disc_to_deck or disc_to_hand else {}
    ctx = replace(ctx, bot_discard=guids)
    checks: list[Callable[[], None]] = []
    for zone, ids in (("hand", hand_to_deck), ("discard", played_back + disc_to_deck)):
        for intent in _groups(intents, "return_to_deck", bot, zone, ids, keep_order=True):
            checks += translate(session, intent, ctx) or []
    for intent in _groups(intents, "put_in_hand", bot, "discard", disc_to_hand):
        checks += translate(session, intent, ctx) or []
    if taken > 0:
        checks += translate(session, {"op": "search_deck", "player": bot, "n": taken}, ctx) or []
    return checks


def scheme_cards(session, before: dict | None) -> list[str]:
    """What a scheme did to the bot's own cards since `before`, for the chat line that announces it: 'draws 2' and
    'puts 2 cards from the discard pile at the bottom of its deck' / 'shuffles ...'."""
    if before is None:
        return []
    g, bot = session.game, session.bot
    st = g.players[bot]
    b0, deck = before["bot"], [c.card_id for c in st.deck]
    out = []
    drawn = g.drawn[bot] - before["drawn"]
    if drawn > 0:
        out.append(t("bot.scheme_draws", n=drawn))
    back = [i for i in b0["discard"] if i in deck]
    if back:
        out.append(t("bot.scheme_tail" if is_tail(deck, back) else "bot.scheme_shuffle", cards=plural(len(back), "noun.card")))      # the next line names them
    return out



# ---------------------------------------------------------------- the ONGOING zone (E2, Ivan 29/10)

def _bot_ongoing(session, before: dict, intents: list[dict], ctx: Ctx) -> list[Callable[[], None]]:
    """The bot's ONGOING scheme that just entered play (the `ongoing` translator)."""
    bot = session.bot
    now = session.game.fx.ongoing_card_id(bot)
    if now is None or now == before.get("bot_in_play"):
        return []
    intent = next((i for i in intents if i["op"] == "ongoing" and i["player"] == bot and i["card"] == now),
                  {"op": "ongoing", "player": bot, "card": now})
    return translate(session, intent, ctx) or []


# ---------------------------------------------------------------- the human's cards: the chat, the human's hands

def _human_cards(session, before: dict, played: frozenset, looked: bool, ctx: Ctx,
                 intents: list[dict]) -> list[Callable[[], None]]:
    cause = ctx.cause
    g, human, bot = session.game, session.human, session.bot
    st, known = g.players[human], g.players[bot].known
    h0, h1 = before["human"], zones(st)
    in_play = before.get("in_play")               # your ONGOING that left play
    checks: list[Callable[[], None]] = []
    if in_play is not None and in_play in h1["discard"] and in_play not in h0["discard"]:
        left = next((i for i in intents if i["op"] == "discard" and i["zone"] == "in_play" and i["card"] == in_play
                     and i["player"] == human), {"op": "discard", "zone": "in_play", "player": human, "card": in_play})
        checks += translate(session, left, ctx) or []
    to_discard = [i for i in h1["discard"] if i not in h0["discard"] and i not in played and i != in_play
                  and i not in session.hand_discarded]
    by_bot = len([i for i in h1["discard"] if i not in h0["discard"] and i in session.hand_discarded])    # already moved
    if to_discard:
        checks += translate(session, {"op": "discard", "zone": "hand", "player": human, "cards": to_discard}, ctx) or []
    # the virtual hand holds placeholders: only a card the bot knew in your hand (seen before the step, or now known
    # on top of your deck) can be said to have gone to the deck; the rest is counted by the size the hand lost
    # beyond what the discards and the played cards explain (a look re-identifies the hand, which moves
    # placeholders around without moving anything on the table)
    knew = set(before["seen"]) | set(known.top_of_deck)
    hand_to_deck = [i for i in h1["deck"] if i in knew and i not in h0["discard"]]
    for intent in _groups(intents, "return_to_deck", human, "hand", hand_to_deck, keep_order=True):
        checks += translate(session, intent, ctx) or []
    # a pile card an effect shuffled into your deck that the engine then drew for you (Back For Seconds, then a draw of
    # the combat): your engine deck is a guess, so on the table it goes into the real deck and the draw is dealt from
    # it; it is never a pickup from the discard pile
    returned = {c for it in intents if it["op"] == "return_to_deck" and it["player"] == human and it["zone"] == "discard"
                for c in it["cards"]}
    redrawn = [i for i in h0["discard"] if i in returned and i in h1["hand"]]
    drawn = 0 if looked else len([i for i in h1["hand"] if i in h0["deck"]]) + len(redrawn)   # a look moves placeholders, not cards
    played_back = [i for it in intents if it["op"] == "return_to_deck" and it["player"] == human and it["zone"] == "discard"
                   for i in it["cards"] if i in h1["deck"] and i not in h0["discard"] and i not in h0["deck"]]    # Relentless
    if played_back:                               # the bot puts it in the deck BEFORE the draw it owes is dealt
        checks += combat_card_to_deck(session, played_back, ctx) or []
    disc_to_deck = [i for i in h0["discard"] if i in h1["deck"] or i in redrawn]
    if redrawn:                                   # the engine drew after the shuffle: the deck gets them first
        for intent in _groups(intents, "return_to_deck", human, "discard", disc_to_deck, keep_order=True):
            checks += translate(session, intent, ctx) or []
    session._deal_owed_draws(cause)               # the draws of the effect are dealt to the hand (the `draw` translator)
    from_hand = len([i for i in h0["hand"] if i in played])
    entered = g.fx.ongoing_card_id(human)         # an ONGOING that entered play left the hand without a discard
    from_hand += int(entered is not None and entered != in_play and entered in h0["hand"] and entered not in played)
    whole = sum(i["n"] for i in intents if i["op"] == "hand_to_deck_all" and i["player"] == human)   # Eye of Agamotto: told in its own line
    unknown = len(h0["hand"]) + drawn - len(h1["hand"]) - from_hand - len(to_discard) - by_bot - len(hand_to_deck) - len(played_back) - whole
    if unknown > 0:
        session.say(t("bot.return_hand", cards=plural(unknown, "noun.card"), cause=cause), ChatKind.YOUR_TURN)
    if not redrawn:
        for intent in _groups(intents, "return_to_deck", human, "discard", disc_to_deck, keep_order=True):
            checks += translate(session, intent, ctx) or []
    disc_to_hand = [i for i in h0["discard"] if i in h1["hand"] and i not in redrawn]
    for intent in _groups(intents, "put_in_hand", human, "discard", disc_to_hand):
        checks += translate(session, intent, ctx) or []
    return checks
