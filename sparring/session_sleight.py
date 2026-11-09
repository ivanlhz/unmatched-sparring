"""Sleight Of Hand on the real table, the bot's side (the human's half is in `session_rage` and `session_pile`: the `play` pile mode).

The engine swaps the card inside the combat (`CombatFlow.replace_attack_card(back_to_hand=True)`); this module makes the table
agree. House rule: the bot announces each action in the chat, waits `action_announce_hold` and only then acts. It takes Sleight Of
Hand back from its combat spot to its hand by GUID, puts the card it plays instead face up on that spot (with the card zoom) and
remembers the new card's GUID as the card of the combat. A table that refuses is said once, with what to move by hand."""
from __future__ import annotations

from typing import Callable

from .i18n import t
from .session_translators import DOMAIN, ERRORS, result_of
from .tts import lua
from .tts.lua import ChatKind


def bot_swap(session, p) -> Callable[[], None]:
    """Queues the bot's swap when the engine's attack card is no longer the one on the table; returns the check to run after the
    step's writes went out (a no-op when there is nothing to swap). Idempotent: `p.bot_card` follows the table."""
    flow = p.flow
    if flow is None or p.kind != "bot_attacks" or not flow.returned or flow.atk_card is p.bot_card or p.bot_card is None:
        return lambda: None
    from .session import SessionError             # the session imports this module: resolved at call time
    old, new, cfg = p.bot_card, flow.atk_card, session.cfg
    first = len(session.messages)
    session.say(t("sleight.bot", old=old.title, new=new.title), ChatKind.SCHEME)
    session._announce_before(first)
    x, y, z = cfg.bot_card_spot
    p.bot_card = new
    try:
        placed = session._w(lua.place_card_face_up(new.card_id, cfg.bot_seat, x, y, z, cfg.rot_y, cfg.bot_card_ids,
                                                   identity=session._identity(), zoom=session.zoom()), DOMAIN)
        back = session._w(lua.return_card_to_hand(p.bot_card_guid, cfg.bot_seat), DOMAIN) if p.bot_card_guid else None
    except ERRORS + (SessionError,):
        session.say(t("sleight.bot_manual", old=old.title, new=new.title), ChatKind.WARNING)
        return lambda: None

    def check() -> None:
        guid = result_of(placed).get("placed")
        if guid:
            p.bot_card_guid = guid
        if not guid or back is None or not result_of(back).get("returned"):
            session.say(t("sleight.bot_manual", old=old.title, new=new.title), ChatKind.WARNING)
    return check


def bot_card_back(session, p) -> Callable[[], None]:
    """The bot's attack card ended the combat in its HAND (an AFTER that puts it back: Echoing blast, Five Against Thousands): the card
    lies at its combat spot, so it is taken to the bot's hand by GUID before the table is compared with the engine. Like a Sleight
    Of Hand swap, a table that refuses is said once with what to move by hand. A no-op for any other combat."""
    card = p.bot_card
    if p.kind != "bot_attacks" or card is None or not p.bot_card_guid or card not in session.game.players[session.bot].hand:
        return lambda: None
    from .session import SessionError             # the session imports this module: resolved at call time
    try:
        back = session._w(lua.return_card_to_hand(p.bot_card_guid, session.cfg.bot_seat), DOMAIN)
    except ERRORS + (SessionError,):
        session.say(t("card_back.bot_manual", card=card.title), ChatKind.WARNING)
        return lambda: None

    def check() -> None:
        if not result_of(back).get("returned"):
            session.say(t("card_back.bot_manual", card=card.title), ChatKind.WARNING)
    return check
