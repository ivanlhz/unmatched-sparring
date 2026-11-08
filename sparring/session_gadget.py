"""Jill Trent's gadget token on the table (Iván, 2026-11-08): the active gadget must be seen, not only said in the chat.

The engine's counter `gadget` (0 none, 1 Hypnoray Blaster, 2 Ultrabiotic Tonic) is the authority. The only physical gadget
piece is the Tonic token (`tokens.gadget` in data/tts/jill-trent.json); the Blaster is not printed on the character card
(read from the card image) and has no separate piece. The token is double-sided (Iván, 2026-11-08): the face up (rot Z 0) is the
Ultrabiotic Tonic and the other face is the Hypnoray Blaster. It has ONE resting spot per side (`token_slots.gadget.<side>[0]`)
and only its rotation tells the gadget: Tonic face up, Blaster flipped (rot Z 180), no gadget (Jill plays second, before her first
turn) face up turned `NONE_TURN` degrees about Y.

`track` runs wherever the session looks at its own state (every step, game start, resume, restart). It compares the counter with
what it last put on the table and, when they differ, moves the token with `lua.move_token` (a plain write, messageID 3 only,
whoever plays Jill: the bot's AI choice and the human's panel choice both end in the counter). The first look of a game or of a
resumed game always writes, so the token is re-placed from the saved counter. A token the player removed is said once per game in the chat (a failed write is a different line, retried at the next step);
the game never waits for it."""
from __future__ import annotations

from .i18n import t
from .session_translators import DOMAIN, ERRORS, PLACED_TOKEN
from .table_layout import SETTLE_LIFT, own_token_slots
from .tts import lua
from .tts.hero_table import HeroTableError, load_hero_table
from .tts.lua import ChatKind

GADGET = PLACED_TOKEN        # name of the counter and of the token in the hero's data
BLASTER, TONIC = 1, 2      # values of the counter while each gadget is the active one
NONE_TURN = 90.0           # degrees about Y the token is turned, face up, while no gadget is active yet


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
    """(guid, position, rotation) where the token rests for the gadget `active`, or None if the data gives no place."""
    table = load_hero_table(session.game.hero_def(player).slug)
    side = "bot" if player == session.bot else "human"
    slots = own_token_slots(side, table, GADGET)
    if not slots:
        return None
    slot = slots[0]
    x, y, z = slot.pos
    rx, ry, rz = slot.rot
    if active == BLASTER:
        rz = 180.0
    elif active != TONIC:
        ry = (ry + NONE_TURN) % 360
    return table.tokens[GADGET], (x, y + SETTLE_LIFT, z), (rx, ry, rz)


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
        except ERRORS:                                     # the write itself failed: told once, retried by the next step
            session._gadget_shown = None
            if not session._gadget_failed_said:
                session._gadget_failed_said = True
                session.say(t("gadget.write_failed", name=session._name(session.game.hero(player))), ChatKind.WARNING)
            return
        if not res.get("moved") and not session._gadget_missing_said:
            session._gadget_missing_said = True
            session.say(t("gadget.token_missing", name=session._name(session.game.hero(player))), ChatKind.WARNING)
    session._post.append(check)
