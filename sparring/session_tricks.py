"""Loki's TRICKs at the table (docs/heroes/loki.md, "At the table"): the physical card follows what the engine decided (`sparring/tricks.py`).

A TRICK is a card of LOKI's deck that changes hands: the bot (Loki) gives the human the ones it plays, the human (Loki) gives the bot theirs.
The deck images tell the two decks apart in TTS, but a CardID does not (sheet 176 is shared), so the session keeps a LEDGER of the TRICKs that are
away from their deck: `Session.trick_guids` maps the GUID of each card object to `[home player, CardID]`. A card is a borrowed TRICK if and only
if its GUID is in the ledger; every read of the human's side that resolves a CardID against the human's own deck skips the ledger's GUIDs
(`own_rows`) and `card_of_row` gives the TRICK for them.

The engine reports what it did as table intents (`trick_given`, `trick_to_discard`, `trick_returned`, `trick_to_deck`, `trick_taken`); each has a
`bot` translator: the bot moves the card with the same Lua writes it uses for its own cards, passing the images of the deck the card BELONGS to.
Where the table refuses, the human is told what to move (`human` variant)."""
from __future__ import annotations

from . import tricks
from .i18n import t
from .session_translators import BOT, DOMAIN, ERRORS, Ctx, register, result_of
from .tts import lua
from .tts.lua import ChatKind


# ---------------------------------------------------------------- the ledger

def ledger(session) -> dict[str, list]:
    return session.trick_guids


def guid_of(session, home: int, card_id: int) -> str | None:
    """The GUID of the TRICK `card_id` of `home`'s deck that lies away from it, from the ledger."""
    return next((g for g, (h, i) in ledger(session).items() if h == home and i == card_id), None)


def own_rows(session, rows: list[dict]) -> list[dict]:
    """The rows of a read of the human's side that are NOT a borrowed TRICK: the ones whose CardID may be looked up in the human's own deck."""
    away = ledger(session)
    return [r for r in rows if isinstance(r, dict) and r.get("guid") not in away]


def card_of_row(session, player: int, row: dict):
    """The card a row of a read of `player`'s side shows: a borrowed TRICK (by its GUID in the ledger) or one of `player`'s own cards (by CardID)."""
    g = session.game
    home_id = ledger(session).get(row.get("guid"))
    if home_id is not None:
        return g.card_of(home_id[1], home_id[0])
    return {c.card_id: c for c in g.players[player].full_set}.get(row.get("id"))


def forget(session, guid: str | None) -> None:
    if guid is not None:
        ledger(session).pop(guid, None)


# ---------------------------------------------------------------- finding a card on the table

def _bot_place(session, card_id: int) -> str | None:
    """GUID of the bot's own card `card_id` at its combat spot or in its hand (a bot's own card never collides with a TRICK of the human's deck:
    those are in the ledger, which is skipped)."""
    away = ledger(session)
    for r in (*session._rd_face("bot"), *session._rd_bot_hand()):
        if isinstance(r, dict) and r.get("id") == card_id and r.get("guid") not in away:
            return r["guid"]
    return None


def _spot_guid(session, home: int, card_id: int) -> str | None:
    """Where a TRICK that is not in the ledger yet lies: the bot's own at its spot or hand, the human's at their combat spot."""
    if home == session.bot:
        return _bot_place(session, card_id)
    return session.combat_guids.get(card_id)


# ---------------------------------------------------------------- the translators (the bot moves the card)

def _mode(session, intent: dict) -> str | None:
    return BOT


def _by_hand(what: str):
    """The human variant: the bot could not move the card, it says what to do."""
    def variant(session, intent: dict, ctx: Ctx) -> list:
        card = session.game.card_of(intent["card"], intent.get("home", intent["player"]))
        session.say(t(what, title=card.title if card is not None else "?"), ChatKind.WARNING)
        return []
    return variant


def _identity(session, home: int):
    side = "bot" if home == session.bot else "human"
    cfg = session.cfg
    return (cfg.bot_card_ids if side == "bot" else cfg.human_card_ids), session._identity(side)


def _write(session, script: str):
    return session._w(script, DOMAIN)


def _given_check(session, op, guid: str, home: int, card_id: int, title: str, to_human: bool, fallback) -> list:
    def check() -> None:
        if result_of(op).get("returned"):
            return
        fallback()
    ledger(session)[guid] = [home, card_id]
    return [check]


@register("trick_given", mode=_mode, human=_by_hand("tricks.give_by_hand"))
def _given(session, intent: dict, ctx: Ctx) -> list:
    """A TRICK Loki played goes to the opponent's hand: the card at the combat spot (or in the hand, for a scheme) is moved to the opponent's seat."""
    loki, card_id, to = intent["player"], intent["card"], intent["to"]
    card = session.game.card_of(card_id, loki)
    guid = (ctx.before or {}).get("bot_played_guid") if loki == session.bot else None
    guid = guid[1] if guid and guid[0] == card_id else _spot_guid(session, loki, card_id)
    if guid is None:
        return _by_hand("tricks.give_by_hand")(session, {**intent, "home": loki}, ctx)
    seat = session.cfg.human_seat if to == session.human else session.cfg.bot_seat
    op = _write(session, lua.return_card_to_hand(guid, seat))
    session.say(t("tricks.given_to_you" if to == session.human else "tricks.given_to_bot", title=card.title), ChatKind.COMBAT)
    return _given_check(session, op, guid, loki, card_id, card.title, to == session.human,
                        lambda: _by_hand("tricks.give_by_hand")(session, {**intent, "home": loki}, ctx))


@register("trick_to_discard", mode=_mode, human=_by_hand("tricks.discard_by_hand"))
def _to_discard(session, intent: dict, ctx: Ctx) -> list:
    """A TRICK the other player played goes to LOKI's discard pile. The bot's own deck is reconciled with its pile by the engine's discard (the
    card lies at the human's spot and `discard_cards` finds it by identity); Loki the human's pile is written here by the bot."""
    home, card_id = intent["to"], intent["card"]
    guid = guid_of(session, home, card_id)
    forget(session, guid)
    if home == session.bot or guid is None:
        return []
    card = session.game.card_of(card_id, home)
    rng, identity = _identity(session, home)
    op = _write(session, lua.card_to_discard(guid, session.cfg.human_discard_zone, rng, identity=identity))
    session.say(t("tricks.to_discard", title=card.title), ChatKind.COMBAT)

    def check() -> None:
        if not result_of(op).get("moved"):
            _by_hand("tricks.discard_by_hand")(session, intent, ctx)
    return [check]


@register("trick_returned", mode=_mode, human=_by_hand("tricks.return_by_hand"))
def _returned(session, intent: dict, ctx: Ctx) -> list:
    """A TRICK discarded from the opponent's hand goes back to Loki's hand."""
    home, card_id = intent["to"], intent["card"]
    guid = guid_of(session, home, card_id)
    card = session.game.card_of(card_id, home)
    if guid is None:
        return _by_hand("tricks.return_by_hand")(session, {**intent, "home": home}, ctx)
    session._trick_moved[card_id] = guid
    forget(session, guid)
    cfg = session.cfg
    if home == session.bot:                  # the human discarded it: it lies on their pile
        rng, identity = _identity(session, home)
        op = _write(session, lua.pile_card_to_hand(guid, card_id, cfg.bot_seat, rng, identity=identity))
        key = "moved"
    else:                                    # the bot discarded it: it is in the bot's hand
        op = _write(session, lua.return_card_to_hand(guid, cfg.human_seat))
        key = "returned"
    session.say(t("tricks.returned", title=card.title), ChatKind.COMBAT)

    def check() -> None:
        if not result_of(op).get(key):
            _by_hand("tricks.return_by_hand")(session, {**intent, "home": home}, ctx)
    return [check]


@register("trick_to_deck", mode=_mode, human=_by_hand("tricks.deck_by_hand"))
def _to_deck(session, intent: dict, ctx: Ctx) -> list:
    """Loki put the returned TRICK on top of his deck instead of his hand."""
    home, card_id = intent["player"], intent["card"]
    guid = session._trick_moved.pop(card_id, None) or guid_of(session, home, card_id)
    card = session.game.card_of(card_id, home)
    if guid is None and home == session.bot:
        guid = _bot_place(session, card_id)
    if guid is None:
        return _by_hand("tricks.deck_by_hand")(session, {**intent, "home": home}, ctx)
    side = "bot" if home == session.bot else "human"
    cfg = session.cfg
    rng, identity = _identity(session, home)
    op = _write(session, lua.card_to_deck_top(guid, cfg.bot_deck_guid if side == "bot" else cfg.human_deck_guid, rng,
                                              identity=identity, **session._deck_kw(side)))
    session.say(t("tricks.to_deck", title=card.title), ChatKind.COMBAT)

    def check() -> None:
        if not result_of(op).get("placed"):
            _by_hand("tricks.deck_by_hand")(session, {**intent, "home": home}, ctx)
    return [check]


@register("trick_taken", mode=_mode, human=_by_hand("tricks.take_by_hand"))
def _taken(session, intent: dict, ctx: Ctx) -> list:
    """Laevateinn revealed a TRICK: it goes from the opponent's hand to Loki's."""
    loki, card_id = intent["player"], intent["card"]
    guid = guid_of(session, loki, card_id)
    card = session.game.card_of(card_id, loki)
    if guid is None:
        return _by_hand("tricks.take_by_hand")(session, {**intent, "home": loki}, ctx)
    forget(session, guid)
    seat = session.cfg.bot_seat if loki == session.bot else session.cfg.human_seat
    op = _write(session, lua.return_card_to_hand(guid, seat))
    session.say(t("tricks.taken", title=card.title), ChatKind.COMBAT)

    def check() -> None:
        if not result_of(op).get("returned"):
            _by_hand("tricks.take_by_hand")(session, {**intent, "home": loki}, ctx)
    return [check]


# ---------------------------------------------------------------- what the human does by hand

def settle_discards(session) -> None:
    """A TRICK of Loki's deck the human laid on their own pile (a discard of any kind) goes back to Loki's hand: the engine discards it from their
    hand (`Game.discard_card` sends it to Loki and lets the trigger of MISCHIEF-MONGER ask for the top of his deck) and the bot takes the card
    from the pile. Read from the pile by the ledger's GUIDs; it runs at every read of the human's side."""
    if not session.trick_guids:
        return
    g, human = session.game, session.human
    try:
        rows = session._rd_human_discard()
    except ERRORS:
        return
    for row in rows:
        entry = ledger(session).get(row.get("guid")) if isinstance(row, dict) else None
        if entry is None or entry[0] != session.bot:
            continue
        card = g.card_of(entry[1], entry[0])
        if card is None or card not in g.players[human].hand:
            continue
        g.discard_card(human, card, cause="table")
        _run_intents(session)


def _run_intents(session) -> None:
    """Translates what the engine just reported (the intents of a step the session does not project) and writes it."""
    from .session_bot_effects import _drain_intents
    from .session_translators import translate
    checks = []
    for intent in _drain_intents(session):
        checks += translate(session, intent, Ctx(t("cause.bot_effect"))) or []
    if checks:
        session._flush()
        for check in checks:
            check()


# ---------------------------------------------------------------- requests whose options may name a TRICK

def by_id(session, player: int) -> dict:
    """CardID -> card of `player`'s deck, plus the TRICKs of the other deck by their qualified id (how the options of a request name them)."""
    g = session.game
    out = {c.card_id: c for c in g.players[player].full_set}
    out.update({tricks.QUALIFIED + c.card_id: c for c in g.players[1 - player].full_set if tricks.is_trick(c)})
    return out


def spot_ids(session, rows: list[dict]) -> set[int]:
    """The CardIDs of the cards at a combat spot as a request names them: a borrowed TRICK (its GUID is in the ledger) by its qualified id."""
    away = ledger(session)
    return {r["id"] + tricks.QUALIFIED if r.get("guid") in away else r["id"] for r in rows if isinstance(r, dict) and "id" in r}
