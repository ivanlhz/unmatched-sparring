"""Pandora's Box at the table (docs/heroes/pandora.md): what the chat says of the Miseries.

The engine reports each reveal, a look (HOPE) and the stop as intents (`pandora_reveal`, `pandora_look`, `pandora_stop`, from
`effects/plugins_pandora.py`). The bot's Box is virtual (the engine draws the Miseries), so the chat names each one and what it does; the
pieces and dials it moves (a Kakodaemon in her zone, the damage) follow the usual projection. The human's Box is the real deck on the table:
they reveal the cards and the panel asks which one came up, so the chat adds nothing: the line of the trigger already says the damage ("Pandora -3 PV").

The bot's Misery deck is on the table too (Ivan 22/11/2026: `extras` of data/tts/pandora.json unpacks it, `box` is how it is found), beside her own
deck and face down (Ivan 26/11/2026: `box_layout.box_place`). At start-up it gets a Scripting zone of its own, made around where the deck lies then
(`prepare_zone`; its GUID is saved like the discard zones') and the deck is found only inside it, whatever its GUID. Each Misery the engine draws is
taken out of that deck BY CARDID (the table's order is not the engine's) and laid face up in a cascade BELOW her deck from her player's point of view
(`lua.box_reveal`, `lua.BoxPile`: the same pile the human's reveals lie in), so the effects of the turn are seen at a glance; at the end of the bot's
turn every loose Misery goes back and the deck is shuffled (`lua.box_put_back`, which looks for the cards on the table: it keeps nothing to save).
A table with no Misery deck is said once and the chat carries the Box alone, as before."""
from __future__ import annotations

from .effects import plugins_pandora as box
from .i18n import t
from .session_translators import BOT, DOMAIN, ERRORS, HUMAN, Ctx, register, result_of
from .tts import lua
from .tts.hero_table import HeroTableError, load_hero_table
from .tts.lua import ChatKind


def _mode(session, intent: dict) -> str:
    return BOT if intent["owner"] == session.bot else HUMAN


def _nothing(session, intent: dict, ctx: Ctx) -> list:
    return []


def _hero(session, intent: dict) -> str:
    return session._name(session.game.hero(intent["owner"]))


@register("pandora_reveal", mode=_mode, human=_nothing)
def _reveal_bot(session, intent: dict, ctx: Ctx) -> list:
    misery = t("pandora.misery." + box.NAMES[intent["idx"]].lower())
    session.say(t("tr.pandora.reveal", hero=_hero(session, intent), misery=misery, feathers=intent["feathers"]), ChatKind.ABILITY)
    return _on_table(session, lambda deck, spot: lua.box_reveal(deck.guid, intent["idx"], intent["out"],
                                                               identity=deck.identity, spot=spot, zone=session.cfg.box_zone,
                                                               pile=pile_of(session, human=False, box_spot=spot)),
                     lambda res: res.get("taken") is True, why=_row_said)


@register("pandora_shuffle", mode=_mode, human=lambda session, intent, ctx: _put_back(session, human=True))
def _shuffle_bot(session, intent: dict, ctx: Ctx) -> list:
    return _put_back(session, human=False)


def _put_back(session, human: bool) -> list:
    """End of her turn: every Misery lying loose goes back into the Box (the bot's, or the human's: the cards of the row in their reveal zone) and
    it is shuffled. Only cards of the Box's own image and CardIDs: never the human's own."""
    zone = session.cfg.human_box_zone if human else session.cfg.box_zone
    if human:
        session._box_by_panel = session._box_looked = None          # the turn is over: its markers with it
    if human and not zone:
        return []
    return _on_table(session, lambda deck, spot: lua.box_put_back(deck.guid, identity=deck.identity, spot=spot, zone=zone),
                     lambda res: res.get("deck") is True, human)


def pile_of(session, human: bool, box_spot: tuple[float, float] | None = None) -> lua.BoxPile:
    """The pile her revealed Miseries lie in (`lua.BoxPile`): just below the bot's deck, just below the human's Box (Ivan 26/11/2026), from her
    player's point of view (`SeatGeo`: below is the way to her seat), the cards upright for her seat. It keeps clear of the hand zones (read from the table), the discards, the other zones of the Box and
    what her layout lays around her deck; if her deck spot is not known it is anchored at the Box."""
    c = session.cfg
    geo = c.human_seat_geo if human else c.bot_seat_geo
    deck = c.human_deck_spot if human else c.bot_deck_spot
    anchor = (box_spot or c.human_box_spot or deck) if human else (deck or box_spot or c.box_spot)
    discard = _human_discard(session) if human else [(c.bot_discard_spot[0], c.bot_discard_spot[2])]
    own = {c.human_deck_zone, c.human_reveal_zone} if human else {c.bot_deck_zone}
    zones = (c.bot_discard_zone, c.human_discard_zone, c.bot_deck_zone, c.human_deck_zone, c.box_zone, c.human_box_zone)
    return lua.BoxPile(tuple(anchor), geo.up_yaw, geo.down, tuple(discard), tuple(dict.fromkeys(g for g in zones if g and g not in own)),
                       geo.keep, tuple(c.remove_limits))


def _human_discard(session) -> list[tuple[float, float]]:
    """Where the human's discard pile is: their discard zone as the configuration spawns it."""
    spawn = session.cfg.zone_spawns.get("human_discard_zone")
    return [(spawn.position[0], spawn.position[2])] if spawn else []


def _zones_to_avoid(session, own: str | None) -> list[str]:
    """Every zone a Box zone must not be taken for when it looks for one already there: discards, decks and the other Box zones (not `own`)."""
    c = session.cfg
    zones = (c.bot_discard_zone, c.human_discard_zone, c.bot_deck_zone, c.human_deck_zone, c.box_zone, c.human_box_zone, c.human_reveal_zone)
    return list(dict.fromkeys(g for g in zones if g and g != own))


def _row_said(session, res) -> None:
    """The bot's reveal did not go through, and why: a lost deck is `pandora.box_missing`; a deck that does not hold that card, or a row
    that fits nowhere, are not the same news."""
    if not isinstance(res, dict) or res.get("deck") is False:
        _missing(session)
    elif res.get("taken") is not True and not session._box_card_said:
        session._box_card_said = True
        session.say(t("pandora.box_card_missing"), ChatKind.WARNING)


def _table_of(session, player: int):
    try:
        return load_hero_table(session.game.hero_def(player).slug)
    except HeroTableError:
        return None


PILE_WHERE = {"side": "pandora.pile_where.side", "above": "pandora.pile_where.above"}
BOX_ZONE_NOTES = {"created": "pandora.box_zone_created", "moved": "pandora.box_zone_moved"}
REVEAL_ZONE_NOTES = {"created": "pandora.reveal_zone_created", "moved": "pandora.reveal_zone_moved", "crowded": "pandora.pile_crowded"}


def prepare_zone(session, resume: bool) -> None:
    """Start-up: each Pandora's Misery deck gets its Scripting zone (`lua.box_zone`), around where it lies now or, if it is still in the bag, where
    the unpack will lay it: `box_zone` for the bot's Box and `human_box_zone` for the human's. The human's also gets a REVEAL zone beside it
    (`human_reveal_zone`, `lua.box_reveal_zone`): where the bot lays the Misery its button takes and where it reads the ones they reveal by hand.
    The GUID of each zone found or created is adopted (saved with the session as `zones_live`, so a resume finds it; a new game keeps looking for
    the saved one and moves it to the Box if the Box is elsewhere). The reveal zone is moved and resized to the pile plan on a new game and
    also on a resume with no Miseries out (a game saved by an earlier version, whose pile lay elsewhere): with some out, the pile lies where it was laid. The bot reads its own Box inside its zone. A zone that overlaps a hand, a
    discard or a deck zone is said in the chat. Never fails: no zone means the old search by GUID and spot."""
    c = session.cfg
    for player, spot, key in ((session.bot, c.box_spot, "box_zone"), (session.human, c.human_box_spot, "human_box_zone")):
        table = _table_of(session, player)
        if table is None or table.box is None or spot is None:
            continue
        deck = table.box
        if not resume:
            _lay_beside_deck(session, deck, player == session.human)
        guid = _make_zone(session, resume, key, lambda found: lua.box_zone(found, deck.guid, identity=deck.identity, spot=spot,
                                                                           recenter=not resume, avoid=_zones_to_avoid(session, getattr(c, key))),
                          BOX_ZONE_NOTES)
        if guid and not resume:                  # the bag hands the Box out in the order it was saved in: the human's first Reveal takes its top card
            _shuffle(session, deck, spot, guid)
        if key == "human_box_zone" and guid:
            _make_zone(session, resume, "human_reveal_zone",
                       lambda found: lua.box_reveal_zone(found, pile_of(session, human=True, box_spot=spot),
                                                         recenter=not resume or not box.mask_of(session.game, session.human)), REVEAL_ZONE_NOTES)


def _lay_beside_deck(session, deck, human: bool) -> None:
    """New game: a Misery deck already on the table that is face up or away from her deck is laid beside it face down, as the unpack does, and the
    chat says so. With her deck spot unknown it is left where it is."""
    c = session.cfg
    deck_spot, spot, geo = (c.human_deck_spot, c.human_box_spot, c.human_seat_geo) if human else (c.bot_deck_spot, c.box_spot, c.bot_seat_geo)
    if not deck_spot or spot is None:
        return
    try:
        res = session.client.call_lua(lua.box_lay(deck.guid, identity=deck.identity, at=tuple(spot), yaw=geo.up_yaw))
    except ERRORS + (ValueError, TypeError):
        return
    if isinstance(res, dict) and res.get("moved") is True:
        session._startup_notes.append((t("pandora.box_laid"), ChatKind.WARNING))


def _shuffle(session, deck, spot, zone: str) -> None:
    try:
        session.client.call_lua(lua.box_shuffle(deck.guid, identity=deck.identity, spot=spot, zone=zone))
    except ERRORS + (ValueError, TypeError):
        pass                                    # the table is not reachable now: the next step says so


def _make_zone(session, resume: bool, key: str, build, notes: dict[str, str]) -> str | None:
    """Finds or creates one of the zones of the Box with the script `build(candidate GUIDs)`, adopts its GUID, says what it did and warns if it
    overlaps a hand, discard or deck zone. Returns the GUID, or None if the table did not give one."""
    c = session.cfg
    saved = session._saved_zones.get(key)
    candidates = list(dict.fromkeys(g for g in ((saved, getattr(c, key)) if resume else (getattr(c, key), saved)) if g))
    before = session._live_zones()
    guid = None
    try:
        res = session.client.call_lua(build(candidates))
        guid = res.get("guid") if isinstance(res, dict) else None
        if not (isinstance(guid, str) and lua._GUID.fullmatch(guid)):
            return None
        session._adopt_zone(key, guid)
        if res.get("crowded") and notes.get("crowded"):
            session._startup_notes.append((t(notes["crowded"], guid=guid), ChatKind.WARNING))
        elif res.get("side") in PILE_WHERE and notes.get("crowded"):
            session._pile_moved_said = True
            session._startup_notes.append((t("pandora.pile_moved", where=t(PILE_WHERE[res["side"]])), ChatKind.WARNING))
        if res.get("status") in ("created", "moved"):
            where = "pandora.box_zone_at_box" if res.get("box") else "pandora.box_zone_at_spot"
            session._startup_notes.append((t(notes[res["status"]], guid=guid, where=t(where)), ChatKind.WARNING))
        zones = (c.bot_discard_zone, c.human_discard_zone, c.bot_deck_zone, c.human_deck_zone, c.box_zone, c.human_box_zone, c.human_reveal_zone)
        over = session.client.call_lua(lua.zone_overlaps([guid], [g for g in zones if g and g != guid], lua.BOX_OVERLAP_TOLERANCE))
        near = over.get(guid) if isinstance(over, dict) else None
        near = near if isinstance(near, dict) else {}
        crowd = [*(near.get("hands") or []), *(near.get("zones") or [])]
        if crowd:
            session._startup_notes.append((t("pandora.box_zone_overlaps", guid=guid, others=", ".join(crowd)), ChatKind.WARNING))
    except ERRORS + (ValueError, TypeError):
        return None                             # the table is not reachable now: the next step says so
    if resume and session._live_zones() != before:
        session._persist()
    return guid


def _on_table(session, build, done, human: bool = False, why=None) -> list:
    """Sends one write about a Misery deck (the bot's, or with `human` the human's); `done(result)` says it reached the table. The first
    failure of the bot's game is said once and the chat goes on alone: a game never waits for the Box. The human's is theirs: a table that
    cannot do it says nothing."""
    try:
        table = _table_of(session, session.human if human else session.bot)
        spot = session.cfg.human_box_spot if human else session.cfg.box_spot
        op = None if table is None or table.box is None or spot is None else session._w(build(table.box, spot), DOMAIN)
    except ERRORS + (ValueError, TypeError):
        op = None
    if op is None:
        if not human:
            _missing(session)
        return []

    def check() -> None:
        try:
            res = result_of(op)
            ok = done(res)
        except ERRORS:
            res, ok = None, False
        if ok and isinstance(res, dict):
            say_pile(session, res)
        if not ok and not human:
            (why or (lambda s, r: _missing(s)))(session, res)
    return [check]


def say_pile(session, res: dict) -> None:
    """What the table said of the pile (`crowded`, `side`): that it could not go below the deck (the human's: below the Box) is said once, so is a pile with no free place."""
    if res.get("crowded"):
        if not session._row_crowded_said:
            session._row_crowded_said = True
            session.say(t("pandora.pile_crowded"), ChatKind.WARNING)
    elif res.get("side") in PILE_WHERE and not session._pile_moved_said:
        session._pile_moved_said = True
        session.say(t("pandora.pile_moved", where=t(PILE_WHERE[res["side"]])), ChatKind.WARNING)


def _missing(session) -> None:
    if not session._box_missing_said:
        session._box_missing_said = True
        session.say(t("pandora.box_missing"), ChatKind.WARNING)


@register("pandora_look", mode=_mode, human=_nothing)
def _look_bot(session, intent: dict, ctx: Ctx) -> list:
    session.say(t("tr.pandora.hope_bot", hero=_hero(session, intent)), ChatKind.ABILITY)
    return []


@register("pandora_stop", mode=_mode, human=_nothing)
def _stop_bot(session, intent: dict, ctx: Ctx) -> list:
    if intent["damage"]:
        session.say(t("tr.pandora.stop_damage", hero=_hero(session, intent), feathers=intent["feathers"], damage=intent["damage"]),
                    ChatKind.ABILITY)
    else:
        session.say(t("tr.pandora.stop", hero=_hero(session, intent)), ChatKind.ABILITY)
    return []
