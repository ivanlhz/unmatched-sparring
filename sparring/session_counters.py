"""Table dials of the HeroDef counters derived from the discard pile (`pile` + `tag`): Ciri's Source, Sinbad's Voyage.

The engine counts them from the discard pile (`Game.counter`); each bag's dial (a Custom_Model dial like Hellboy's destiny dial) only
shows the number. They follow the hero on either side, the bot's or the human's, and share `Session._put_dials` with the life dials and
the destiny dial: the same verified write, the same respect for a dial the human touched by hand, the same debt when the table refuses.
What is here is only what is specific to them: whose count each one is, what to write and when the write is due. Any change of the
discard (hand limit, attack or defense, a rival's effect, a return to the hand) shows up in `Game.counter`, and `stale` notices it at
the next read of the table, so the cause of the change does not matter. A game with no such dial runs none of this."""
from __future__ import annotations

from .i18n import t


def owner(session, name: str) -> int | None:
    """The side whose hero keeps the counter `name` (bot or human), None when nobody does."""
    g = session.game
    return next((p for p in (session.human, session.bot) if name in g.hero_def(p).counters), None)


def count(session, name: str) -> int:
    who = owner(session, name)
    return 0 if who is None else session.game.counter(who, name)


def stale(session) -> bool:
    """Some dial does not yet show its count: `counter_seen` only advances after a verified write, so a failed one is retried at the
    next read of the table."""
    return any(count(session, name) != session.counter_seen.get(name) for name in session.cfg.counter_dials)


def want(session) -> dict[str, int]:
    """{dial GUID: value} to write now."""
    return {guid: count(session, name) for name, guid in session.cfg.counter_dials.items()}


def labels(session) -> dict[str, str]:
    return {guid: t("cause.counter_dial", name=name) for name, guid in session.cfg.counter_dials.items()}


def written(session, values: dict[str, int]) -> None:
    """A write of `values` was verified on the table."""
    for name, guid in session.cfg.counter_dials.items():
        if guid in values:
            session.counter_seen[name] = values[guid]
