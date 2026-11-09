"""Sinbad at the live table (docs/heroes/sinbad.md): what the session says about his ability.

The Maneuver of the human is physical (the miniatures are moved by hand and the engine reads where they ended), so the +1 space per
VOYAGE card of the ability needs no check; the chat only tells the human how far his fighters may go, counting the pile the engine holds."""
from __future__ import annotations

from .i18n import t
from .tts.lua import ChatKind


def announce_reach(session) -> None:
    """The human's fighters may move this many spaces more than their move in the Maneuver that begins (nothing is said for 0)."""
    extra = session.game.maneuver_bonus(session.human)
    if extra:
        session.say(t("sinbad.reach", n=extra), ChatKind.YOUR_TURN)
