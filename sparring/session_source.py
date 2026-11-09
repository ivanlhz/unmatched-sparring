"""Ciri's Source dial: the table mirror of the HeroDef counter `source` (the Source cards in her discard pile).

The engine counts the Source from the discard pile (`Game.counter`); the bag's "Source" dial (a Custom_Model dial like Hellboy's destiny
dial, MAX_VALUE 13 = the 13 orb cards of the deck) only shows it. It follows Ciri on either side, the bot's or the human's, and shares
`Session._put_dials` with the life dials and the destiny dial: the same verified write, the same respect for a dial the human touched by
hand, the same debt when the table refuses. What is here is only what is specific to it: whose count it is, what to write and when the
write is due. A game without Ciri has no `source_dial` and none of this runs."""
from __future__ import annotations

from .i18n import t

COUNTER = "source"


def owner(session) -> int | None:
    """The side whose hero keeps the Source count (Ciri, bot or human), None when nobody does."""
    g = session.game
    return next((p for p in (session.human, session.bot) if COUNTER in g.hero_def(p).counters), None)


def count(session) -> int:
    who = owner(session)
    return 0 if who is None else session.game.counter(who, COUNTER)


def stale(session) -> bool:
    """The dial does not yet show the count: `source_seen` only advances after a verified write, so a failed one is retried at the
    next read of the table."""
    if not session.cfg.source_dial:
        return False
    return count(session) != session.source_seen


def want(session) -> dict[str, int]:
    """{dial GUID: value} to write now (nothing without a Source dial)."""
    return {session.cfg.source_dial: count(session)} if session.cfg.source_dial else {}


def label() -> str:
    return t("cause.source_dial")


def written(session, values: dict[str, int]) -> None:
    """A write of `values` was verified on the table."""
    dial = session.cfg.source_dial
    if dial and dial in values:
        session.source_seen = values[dial]
