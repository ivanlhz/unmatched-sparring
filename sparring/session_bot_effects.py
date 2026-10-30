"""The bot's card effects reach the real table (D3).

What a step of the bot (a combat, a scheme, its start of turn) changed outside its own miniatures and discards is
read off the engine by diff: `snapshot` before the step, `project` after it. The diff becomes F1 builders queued
through `Session._w`, so everything travels in the step's one combined script, and the chat says what moved:

  * the human's miniatures a bot effect moved or returned (Concussion Device, Leap Away, Foul Journey, Pact Of
    Freedom, Right Hand Of Doom...): `move_piece` by GUID, Ivan's rule "the bot moves what its card says";
  * Hellboy's form (the bot's): the miniature swaps state, the ability token is flipped and both are pinged;
  * ability tokens (Abe's Intuition): one copy taken from the source token per active point, removed when spent;
  * the bot's own hidden zones: hand -> deck (Glimpse Of Hell, Pyrotechnics), discard -> deck (Pancakes!, Rekindle,
    Searing Clarity), discard -> hand (Ward And Prepare, Wildfire) and cards taken from the deck (Read The Bones:
    the real order of the deck is unknown to the engine, so they are dealt from the top).

The human's cards are the human's (`setPositionSmooth` never takes a card out of a hand zone and the bot never
reads or reorders their deck): the chat names what to move and `Session.sync_human` / `pending_discard` wait for it.
One exception, Ivan's ruling of 29/10 (live test, Searing Clarity): a card the human picked at the panel out of
their own PUBLIC discard pile for an effect that moves it into their deck is moved by the bot, by GUID, and the bot
shuffles their deck when the card says so (`_human_disc_to_deck`). A failed write is said once and the table wins
at the next read, like every other projection of the session.

Ivan's rule on hidden information: `read_human_hand` is the only reader of the human's hand; it is installed as
`Game.hand_reader` and called by the `look_hand` op alone, at resolution. Clones never carry the reader."""
from __future__ import annotations

from typing import Callable

from .cards import Card
from .tts import effects_bridge, lua
from .tts.client import TTSLuaError
from .tts.hero_table import HeroTable, HeroTableError, load_hero_table
from .tts.lua import ChatKind

ABILITY_TOKEN = "ability"      # the two-faced token of a hero with forms (Hellboy's)
TOKEN_STEP = 1.5               # distance between the copies of an ability token on the table
DOMAIN = "fx"                  # queue domain of these writes: no read of the session forces them out early
BOT_CAUSE = "efecto del bot"   # whose effect the chat blames for what the human must do on the table
_ERRORS = (TTSLuaError, OSError)


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
        session._make_known(c, keep=tuple(cards))
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
    return {"human_pieces": {f.fid: [f.pos, f.alive] for f in g.own(human, alive_only=False)},
            "form": g.form(bot), "counters": dict(g.fx.counters[bot]),
            "bot": zones(g.players[bot]), "human": zones(g.players[human]),
            "in_play": g.fx.ongoing_card_id(human), "bot_in_play": g.fx.ongoing_card_id(bot),
            "drawn": g.drawn[bot], "seen": list(g.players[bot].known.seen)}


def project(session, before: dict | None, played: frozenset = frozenset(), cause: str = BOT_CAUSE) -> Callable[[], None]:
    """Queues the writes for everything that changed since `before` and says it. Returns the function that checks
    the results: call it after the step's composite went out (as `_project_stage`'s is called). `played`: cards
    the human played in this combat, which left their hand by their own hand. `cause`: whose effect the chat blames
    for what the human has to do (the bot's, or their own card's in E2)."""
    if before is None:
        return lambda: None
    moved = set(session.fx_in_flight)             # what this button already moved (a look row's pick, E3)
    looked, session.fx_looked = session.fx_looked, False
    checks = _human_pieces(session, before) + _form(session, before) + _tokens(session, before)
    checks += _bot_cards(session, before, moved) + _bot_ongoing(session, before)
    checks += _human_cards(session, before, played, looked, cause)

    def fin() -> None:
        for check in checks:
            check()
    return fin


def _hero_table(session) -> HeroTable | None:
    try:
        return load_hero_table(session.game.hero_def(session.bot).slug)
    except HeroTableError:
        return None


def _result(op) -> dict:
    try:
        return op.result or {}
    except _ERRORS:
        return {}


def _join(titles) -> str:
    titles = list(titles)
    return titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " y " + titles[-1]


def _plural(n: int, word: str = "carta") -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


# ---------------------------------------------------------------- the human's miniatures

def _human_pieces(session, before: dict) -> list[Callable[[], None]]:
    g, checks = session.game, []
    for fid, (pos0, alive0) in before["human_pieces"].items():
        f = g.fighters[fid]
        if not f.alive or f.pos is None or (alive0 and f.pos == pos0):
            continue                              # a fall is announced by the combat / hp code
        guids = session._guids(fid)
        guid = guids[0]
        if len(guids) > 1:                        # a miniature with states: the GUID the table shows now
            info = session._table_pieces().get(fid) or {}
            guid = info["guid"] if info.get("found") else guid
        op = session._w(effects_bridge.move_human_piece(g.board, guid, f.pos), DOMAIN)
        name, space, back = session._name(f), f.pos, not alive0

        def check(op=op, name=name, space=space, back=back) -> None:
            what = "vuelve al tablero" if back else "se mueve"
            if _result(op).get("moved"):
                session.say(f"{name} {what} a la casilla {space}: lo he movido yo (efecto del bot).", ChatKind.MOVE)
            else:
                session.say(f"{name} {what} a la casilla {space} por un efecto del bot: no he podido mover su "
                            "miniatura, muevela tu.", ChatKind.YOUR_TURN)
        checks.append(check)
    return checks


# ---------------------------------------------------------------- the bot's form (Hellboy)

def _form(session, before: dict) -> list[Callable[[], None]]:
    g, bot = session.game, session.bot
    forms, now = g.hero_def(bot).forms, g.form(bot)
    if forms is None or now == before["form"]:
        return []
    hero, count = g.hero(bot), g.counter(bot, forms.counter)
    name = session._name(hero)
    head = f"{name} (bot) pasa a {now} ({count} {forms.counter})"
    table = _hero_table(session)
    pieces = list(table.fighters[hero.fid].pieces) if table and hero.fid in table.fighters else []
    state = 1 if now == forms.below else 2
    if len(pieces) < 2 or state > len(pieces):
        session.say(f"{head}: cambia tu su miniatura a esa forma.", ChatKind.ABILITY)
        return []
    info = session._table_pieces().get(hero.fid) or {}
    current = info["guid"] if info.get("found") else pieces[0 if state == 2 else 1]
    token = table.tokens.get(ABILITY_TOKEN)
    op_state = session._w(lua.set_state(current, state), DOMAIN)
    op_token = session._w(lua.flip_token(token), DOMAIN) if token else None
    groups = ([[token]] if token else []) + [pieces]
    session._w(lua.ping_objects([session.cfg.bot_seat, session.cfg.human_seat], groups), "misc")
    session.say(f"{head}: cambio su miniatura" + (" y giro su ficha de habilidad" if token else "")
                + "; ping sobre " + ("las dos" if token else "ella") + ".", ChatKind.ABILITY)

    def check() -> None:
        if not _result(op_state).get("guid"):
            session.say(f"No he podido cambiar la miniatura de {name} a {now}: cambiala tu.", ChatKind.WARNING)
        if op_token is not None and not _result(op_token).get("flipped"):
            session.say(f"No he podido girar la ficha de habilidad de {name}: girala tu.", ChatKind.WARNING)
    return [check]


# ---------------------------------------------------------------- ability tokens (Abe's Intuition)

def token_spot(session, k: int) -> tuple[float, float, float]:
    """Where the k-th copy of an ability token goes: `token_spot` of the configuration (calibrate live) or, by
    default, beside the bot's deck."""
    c = session.cfg
    x, y, z = c.token_spot if c.token_spot is not None else (c.bot_deck_spot[0] - 3.0, c.bot_card_spot[1],
                                                               c.bot_deck_spot[1])
    return (x + TOKEN_STEP * k, y, z)


def _tokens(session, before: dict) -> list[Callable[[], None]]:
    g, bot, checks = session.game, session.bot, []
    table = None
    for name in sorted(set(before["counters"]) | set(g.fx.counters[bot])):
        c0, c1 = before["counters"].get(name, 0), g.fx.counter_value(bot, name, 0)
        if c0 == c1:
            continue
        table = table or _hero_table(session)
        source = table.tokens.get(name) if table else None
        if source is None:
            continue                              # a counter without a token on the table
        copies = session.token_copies.setdefault(name, [])
        hero = session._name(g.hero(bot))
        if c1 > c0:
            for k in range(c1 - c0):
                op = session._w(lua.take_token_copy(source, token_spot(session, len(copies) + k)), DOMAIN)
                checks.append(lambda op=op, name=name, hero=hero: _token_taken(session, op, name, hero))
            session.say(f"{hero} (bot) activa {_plural(c1 - c0, 'ficha')} de {name}: {c1} activa(s).", ChatKind.ABILITY)
        else:
            for _ in range(c0 - c1):
                if not copies:
                    session.say(f"{hero} (bot) gasta una ficha de {name} que no veo en la mesa: retirala tu.", ChatKind.WARNING)
                    break
                guid = copies.pop()
                op = session._w(lua.remove_token(guid), DOMAIN)
                checks.append(lambda op=op, name=name, hero=hero: _token_removed(session, op, name, hero))
            session.say(f"{hero} (bot) gasta {_plural(c0 - c1, 'ficha')} de {name}: {c1} activa(s).", ChatKind.ABILITY)
    return checks


def _token_taken(session, op, name: str, hero: str) -> None:
    guid = _result(op).get("taken")
    if guid:
        session.token_copies.setdefault(name, []).append(guid)
    else:
        session.say(f"No he podido sacar una ficha de {name} de la mesa: pon tu una activa junto a {hero}.", ChatKind.WARNING)


def _token_removed(session, op, name: str, hero: str) -> None:
    if not _result(op).get("removed"):
        session.say(f"No he podido retirar la ficha de {name} de {hero}: retirala tu.", ChatKind.WARNING)


# ---------------------------------------------------------------- the bot's own hidden zones

def _is_tail(deck: list[int], ids: list[int]) -> bool:
    return bool(ids) and deck[-len(ids):] == ids


def _bot_cards(session, before: dict, moved: set = frozenset()) -> list[Callable[[], None]]:
    """`moved`: cards another write of this button already took to their place (never moved twice)."""
    g, bot, cfg = session.game, session.bot, session.cfg
    st = g.players[bot]
    b0, b1 = before["bot"], zones(st)
    by_id = {c.card_id: c for c in st.full_set}
    hand_to_deck = [i for i in b0["hand"] if i in b1["deck"] and i not in moved]
    disc_to_deck = [i for i in b0["discard"] if i in b1["deck"] and i not in moved]
    disc_to_hand = [i for i in b0["discard"] if i in b1["hand"] and i not in moved]
    taken = len([i for i in b0["deck"] if i in b1["hand"]]) - (g.drawn[bot] - before["drawn"])
    checks: list[Callable[[], None]] = []
    session.fx_in_flight.update(hand_to_deck + disc_to_deck + disc_to_hand)
    for i in disc_to_deck + disc_to_hand:
        session.bot_discarded.discard(i)          # it may be discarded again later: the table has to move it again
    guids = {r["id"]: r["guid"] for r in session._rd_bot_discard()} if disc_to_deck or disc_to_hand else {}
    if hand_to_deck:
        bottom = _is_tail(b1["deck"], hand_to_deck)
        op = session._w(lua.hand_to_deck(cfg.bot_seat, hand_to_deck, cfg.bot_deck_guid, cfg.bot_card_ids,
                                         identity=session._identity(), bottom=bottom, shuffle=not bottom), DOMAIN)
        where = "en el fondo de su mazo" if bottom else "en su mazo y lo baraja"
        session.say(f"El bot pone {_plural(len(hand_to_deck))} de su mano {where}.", ChatKind.SCHEME)
        checks.append(lambda: _short(session, set(hand_to_deck) - set(_result(op).get("placed") or []), by_id,
                                     "de la mano del bot a su mazo"))
    if disc_to_deck:
        titles = _join(by_id[i].title for i in disc_to_deck)
        if _is_tail(b1["deck"], disc_to_deck):
            ops = [(i, session._w(lua.card_to_deck_bottom(i, cfg.bot_deck_guid, cfg.bot_card_ids,
                                                           identity=session._identity()), DOMAIN))
                   for i in disc_to_deck]
            session.say(f"El bot pone {titles} de su descarte en el fondo de su mazo.", ChatKind.SCHEME)
            checks.append(lambda: _short(session, {i for i, op in ops if not _result(op).get("placed")}, by_id,
                                         "del descarte del bot al fondo de su mazo"))
        else:
            known = [i for i in disc_to_deck if i in guids]
            op = session._w(lua.shuffle_into_deck(cfg.bot_deck_guid, [guids[i] for i in known], cfg.bot_card_ids,
                                                  identity=session._identity()), DOMAIN) if known else None
            session.say(f"El bot baraja {titles} de su descarte en su mazo.", ChatKind.SCHEME)
            checks.append(lambda: _short(session, set(disc_to_deck) - (set(known) if op is not None and
                                                                         _result(op).get("added") == len(known) else set()),
                                         by_id, "del descarte del bot a su mazo (barajada)"))
    for i in disc_to_hand:
        title = by_id[i].title
        if i in session.said_returns:             # the Wildfire scene already said it came back
            session.said_returns.discard(i)
        else:
            session.say(f"El bot recupera {title} de su descarte a su mano.", ChatKind.SCHEME)
        if i not in guids:
            session.say(f"No encuentro {title} suelta en el descarte del bot: ponla tu en su mano.", ChatKind.WARNING)
            continue
        op = session._w(lua.return_card_to_hand(guids[i], cfg.bot_seat), DOMAIN)
        checks.append(lambda op=op, title=title: _returned(session, op, title))
    if taken > 0:
        g.drawn[bot] += taken                     # the real deck order is unknown: it is a top card on the table
        session.say(f"El bot toma {_plural(taken)} de su mazo.", ChatKind.SCHEME)
    return checks


def _returned(session, op, title: str) -> None:
    if not _result(op).get("returned"):
        session.say(f"No he podido devolver {title} a la mano del bot: ponla tu.", ChatKind.WARNING)


def _short(session, missing: set[int], by_id: dict, what: str) -> None:
    if missing:
        session.say(f"No he podido mover {_join(by_id[i].title for i in sorted(missing))} {what}: hazlo tu.",
                    ChatKind.WARNING)


# ---------------------------------------------------------------- the ONGOING zone (E2, Ivan 29/10)

def _bot_ongoing(session, before: dict) -> list[Callable[[], None]]:
    """The bot's ONGOING scheme that just entered play goes face up on its ONGOING spot (its own card, out of its
    hand); when it leaves play the reconciliation discards it from there (the spot is in the scope)."""
    g, bot, cfg = session.game, session.bot, session.cfg
    now = g.fx.ongoing_card_id(bot)
    if now is None or now == before.get("bot_in_play"):
        return []
    card = next(c for c in g.players[bot].full_set if c.card_id == now)
    if cfg.bot_ongoing_spot is None:
        session.say(f"El bot deja {card.title} en juego (ONGOING); sin bot_ongoing_spot en la configuracion la carta "
                    "sigue en su mano en la mesa.", ChatKind.WARNING)
        return []
    x, y, z = cfg.bot_ongoing_spot
    op = session._w(lua.place_card_face_up(now, cfg.bot_seat, x, y, z, cfg.rot_y, cfg.bot_card_ids,
                                           identity=session._identity()), DOMAIN)
    session.fx_in_flight.add(now)
    session.say(f"El bot deja {card.title} en juego: la pone boca arriba en su zona ONGOING.", ChatKind.SCHEME)

    def check() -> None:
        if not _result(op).get("placed"):
            session.say(f"No he podido poner {card.title} en la zona ONGOING del bot: ponla tu.", ChatKind.WARNING)
    return [check]


def left_play(session, card_id: int, cause: str) -> None:
    """Your ONGOING left play. With an ONGOING spot it is owed to your discard pile (the sync protects it until it
    is there); without one it already sits on the pile."""
    st = session.game.players[session.human]
    title = next(c.title for c in st.full_set if c.card_id == card_id)
    if session.cfg.human_ongoing_spot is None:
        session.say(f"{title} deja de estar en juego ({cause}): queda en tu descarte.", ChatKind.SCHEME)
        return
    d = session.pending_discard or {"n": 0, "baseline": len(st.discard), "kind": "cards"}
    if card_id in (d.get("cards") or []):
        return
    d["cards"] = list(d.get("cards") or []) + [card_id]
    session.pending_discard = d
    session.say(f"{title} deja de estar en juego ({cause}): pasala de tu zona ONGOING a tu descarte y pulsa Fin de "
                "accion.", ChatKind.YOUR_TURN)


# ---------------------------------------------------------------- the human's cards: the chat, the human's hands

def _human_cards(session, before: dict, played: frozenset, looked: bool, cause: str) -> list[Callable[[], None]]:
    g, human, bot = session.game, session.human, session.bot
    st, known = g.players[human], g.players[bot].known
    h0, h1 = before["human"], zones(st)
    by_id = {c.card_id: c for c in st.full_set}
    in_play = before.get("in_play")               # your ONGOING that left play
    if in_play is not None and in_play in h1["discard"] and in_play not in h0["discard"]:
        left_play(session, in_play, cause)
    to_discard = [i for i in h1["discard"] if i not in h0["discard"] and i not in played and i != in_play]
    if to_discard:
        d = session.pending_discard or {"n": 0, "baseline": len(st.discard), "kind": "cards"}
        d["cards"] = list(d.get("cards") or []) + to_discard
        session.pending_discard = d
        session.say(f"Pon {_join(by_id[i].title for i in to_discard)} de tu mano en tu descarte ({cause}) y "
                    "pulsa Fin de accion.", ChatKind.YOUR_TURN)
    # the virtual hand holds placeholders: only a card the bot knew in your hand (seen before the step, or now known
    # on top of your deck) can be said to have gone to the deck; the rest is counted by the size the hand lost
    # beyond what the discards and the played cards explain (a look re-identifies the hand, which moves
    # placeholders around without moving anything on the table)
    knew = set(before["seen"]) | set(known.top_of_deck)
    hand_to_deck = [i for i in h1["deck"] if i in knew and i not in h0["discard"]]
    if hand_to_deck:
        top = h1["deck"][:len(hand_to_deck)] == hand_to_deck
        where = "en la parte superior de tu mazo" if top else "en tu mazo y baraja"
        session.say(f"Pon {_join(by_id[i].title for i in hand_to_deck)} de tu mano {where} ({cause}).",
                    ChatKind.YOUR_TURN)
    drawn = 0 if looked else len([i for i in h1["hand"] if i in h0["deck"]])    # a look moves placeholders, not cards
    if drawn:
        session.say(f"Robas {_plural(drawn)} ({cause}): hazlo en la mesa.", ChatKind.YOUR_TURN)
    from_hand = len([i for i in h0["hand"] if i in played])
    unknown = len(h0["hand"]) + drawn - len(h1["hand"]) - from_hand - len(to_discard) - len(hand_to_deck)
    if unknown > 0:
        session.say(f"Devuelve {_plural(unknown)} de tu mano a tu mazo y baraja ({cause}; las eliges tu).",
                    ChatKind.YOUR_TURN)
    disc_to_deck = [i for i in h0["discard"] if i in h1["deck"]]
    checks = _human_disc_to_deck(session, disc_to_deck, h0["deck"], h1["deck"], by_id, cause) if disc_to_deck else []
    disc_to_hand = [i for i in h0["discard"] if i in h1["hand"]]
    if disc_to_hand:
        session.say(f"Recoge {_join(by_id[i].title for i in disc_to_hand)} de tu descarte a tu mano ({cause}).",
                    ChatKind.YOUR_TURN)
    return checks


# ---------------------------------------------------------------- the human's discard pile card into their deck

WHERE_YOU = {"shuffle": "en tu mazo y baraja", "bottom": "en el fondo de tu mazo", "top": "encima de tu mazo"}
WHERE_BOT = {"shuffle": "en tu mazo y lo barajo", "bottom": "en el fondo de tu mazo", "top": "encima de tu mazo"}


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


def _human_disc_to_deck(session, ids: list[int], d0: list[int], d1: list[int], by_id: dict, cause: str) -> list[Callable[[], None]]:
    """Ivan's rule (29/10): the cards the human picked out of their own discard pile for an effect that moves them into
    their deck are moved by the bot, by GUID off the pile (`_rd_human_discard`), with the HUMAN's deck GUID and
    identity; the bot shuffles their deck when the card says so. Their hand is never touched (the builders refuse
    hand zones) and their deck is never read. A card already gone from the pile was moved by the human: said, not
    failed."""
    cfg = session.cfg
    position, ordered = deck_position(d0, d1, ids)
    if not cfg.human_deck_guid:
        session.say(f"Pon {_join(by_id[i].title for i in ids)} de tu descarte {WHERE_YOU[position]} ({cause}).",
                    ChatKind.YOUR_TURN)
        return []
    guids = {r["id"]: r["guid"] for r in session._rd_human_discard() if isinstance(r, dict) and "guid" in r}
    gone = [i for i in ordered if i not in guids]
    if gone:
        session.say(f"{_join(by_id[i].title for i in gone)} ya no esta en tu descarte: doy por hecho que ya esta "
                    f"{WHERE_YOU[position].replace(' y baraja', '')} ({cause}).", ChatKind.SCHEME)
    todo = [i for i in ordered if i in guids]
    if not todo:
        return []
    from .session import SessionError             # the session imports this module: resolved at call time
    try:
        identity = session._identity("human")
    except _ERRORS + (SessionError,) as e:        # no identity, no write: the human does it
        session.say(f"No puedo tocar tu mazo ({e}): pon {_join(by_id[i].title for i in todo)} de tu descarte "
                    f"{WHERE_YOU[position]} tu.", ChatKind.WARNING)
        return []
    session.fx_in_flight.update(todo)
    titles = _join(by_id[i].title for i in todo)
    session.say(f"Meto {titles} {WHERE_BOT[position]} ({cause}).", ChatKind.SCHEME)
    what = f"de tu descarte {WHERE_YOU[position]}"
    if position == "shuffle":
        op = session._w(lua.shuffle_into_deck(cfg.human_deck_guid, [guids[i] for i in todo], cfg.human_card_ids,
                                              identity=identity), DOMAIN)
        return [lambda: _short(session, set(todo) if _result(op).get("added") != len(todo) else set(), by_id, what)]
    build = lua.card_to_deck_bottom if position == "bottom" else lua.card_to_deck_top
    order = todo if position == "bottom" else list(reversed(todo))      # putObject adds on top: the first id ends up last
    ops = [(i, session._w(build(guids[i], cfg.human_deck_guid, cfg.human_card_ids, identity=identity), DOMAIN))
           for i in order]
    return [lambda: _short(session, {i for i, op in ops if not _result(op).get("placed")}, by_id, what)]
