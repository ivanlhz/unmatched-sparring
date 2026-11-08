"""Jill Trent's gadget token on the table (Iván, 2026-11-08): the active gadget must be seen, not only said in the chat.

The engine's counter `gadget` (0 none, 1 Hypnoray Blaster, 2 Ultrabiotic Tonic) is the authority. The only physical gadget
piece is the Tonic token (`tokens.gadget` in data/tts/jill-trent.json); the Blaster is not printed on the character card
(read from the card image) and has no piece. The convention: the token lies ON Jill's character card while the Tonic is the
active gadget, and BESIDE the card when the Blaster is active or no gadget is (`token_slots.gadget.<side>`: [beside, on card]).

`track` runs wherever the session looks at its own state (every step, game start, resume, restart). It compares the counter with
what it last put on the table and, when they differ, moves the token with `lua.move_token` (a plain write, messageID 3 only,
whoever plays Jill: the bot's AI choice and the human's panel choice both end in the counter). The first look of a game or of a
resumed game always writes, so the token is re-placed from the saved counter. A token the player removed is said once in the chat;
the game never waits for it."""
from __future__ import annotations

from .i18n import t
from .session_translators import DOMAIN, ERRORS, PLACED_TOKEN
from .table_layout import SETTLE_LIFT, own_token_slots
from .tts import lua
from .tts.hero_table import HeroTableError, load_hero_table
from .tts.lua import ChatKind

GADGET = PLACED_TOKEN        # name of the counter and of the token in the hero's data
TONIC = 2                  # value of the counter while the Ultrabiotic Tonic is the active gadget
BESIDE, ON_CARD = 0, 1     # index of each resting place in `token_slots.gadget.<side>`


def owner(session) -> int | None:
    """The player whose hero has the gadget token (Jill Trent), if any."""
    for player in (session.bot, session.human):
        try:
            if GADGET in load_hero_table(session.game.hero_def(player).slug).tokens:
                return player
        except HeroTableError:
            continue
    return None


def spot(session, player: int, active: int):
    """(guid, position, rotation) where the token rests for the gadget `active`, or None if the data gives no places."""
    table = load_hero_table(session.game.hero_def(player).slug)
    side = "bot" if player == session.bot else "human"
    slots = own_token_slots(side, table, GADGET)
    if len(slots) <= ON_CARD:
        return None
    slot = slots[ON_CARD if active == TONIC else BESIDE]
    x, y, z = slot.pos
    return table.tokens[GADGET], (x, y + SETTLE_LIFT, z), slot.rot


def track(session) -> None:
    """Moves the token if the counter is not what it last showed. Nothing happens when nobody plays Jill."""
    player = owner(session)
    if player is None:
        return
    now = session.game.fx.counter_value(player, GADGET, 0)
    if session._gadget_shown == now:
        return
    where = spot(session, player, now)
    if where is None:
        return
    guid, position, rotation = where
    op = session._w(lua.move_token(guid, position, rotation), DOMAIN)
    session._gadget_shown = now

    def check() -> None:
        try:
            res = op.result or {}
        except ERRORS:                                     # the write failed: the same warning, the game goes on
            res = {}
        if not res.get("moved") and not session._gadget_missing_said:
            session._gadget_missing_said = True
            session.say(t("gadget.token_missing", name=session._name(session.game.hero(player))), ChatKind.WARNING)
    session._post.append(check)
