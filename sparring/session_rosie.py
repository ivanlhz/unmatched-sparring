"""Rosie the Riveter at the live table (docs/heroes/rosie-the-riveter.md): what the session says about her upgrade row.

The engine's counters (`upgrades`, `upgrade_shift`: sparring/upgrades.py) are the authority. The four upgrade tokens of her bag are
double-sided and their order on the table changes with every single deactivation; the bot does not move them. Instead every change is
said in the chat, for either seat, as what happened and where the row stands, so the human can keep the tokens on the table in step
(their own, when they play Rosie; the bot's, to see what she has)."""
from __future__ import annotations

from . import upgrades
from .i18n import t
from .tts.lua import ChatKind


def _state(game, player: int) -> tuple[int, int] | None:
    return (upgrades.count(game, player), game.fx.counter_value(player, upgrades.SHIFT)) if upgrades.has(game, player) else None


def _names(items: list[dict]) -> str:
    return ", ".join(u["name"] for u in items) or t("rosie.none")


def describe(game, player: int, before: tuple[int, int] | None) -> str:
    """The change from `before` ((active, shift) as last said; None = first look) to the engine's state now."""
    now = upgrades.count(game, player)
    shift = game.fx.counter_value(player, upgrades.SHIFT)
    total = upgrades.size(game, player)
    name = game.hero(player).name
    if before is None:
        return t("rosie.state", name=name, active=_names(upgrades.active(game, player)), row=_names(upgrades.row(game, player)))
    count0, shift0 = before
    if shift == shift0 and now > count0:
        return t("rosie.on", name=name, names=_names(upgrades.row(game, player)[count0:now]), n=now, max=total)
    if shift == shift0 and now == 0 and count0 == total:
        return t("rosie.reset", name=name, max=total)
    if now == count0 - 1 and shift == (shift0 + 1) % total:
        return t("rosie.off", name=name, names=upgrades.row(game, player)[-1]["name"], n=now, max=total)
    return t("rosie.state", name=name, active=_names(upgrades.active(game, player)), row=_names(upgrades.row(game, player)))


def track(session, announce: bool = False) -> None:
    """Says the upgrade changes since the last look, for the bot's Rosie and the human's. `announce`: also say the state when nothing
    was said yet (the start of a game, a resume). Nothing happens when nobody plays Rosie."""
    game = session.game
    said = session.__dict__.setdefault("_upgrades_said", {})
    for player in (session.bot, session.human):
        now = _state(game, player)
        if now is None:
            continue
        before = said.get(player)
        said[player] = now
        if before == now or (before is None and not announce):
            continue
        session.say(describe(game, player, before), ChatKind.ABILITY)


def forget(session) -> None:
    """A restart or a table adoption: the next look says the state again."""
    session.__dict__.pop("_upgrades_said", None)
