"""Rosie the Riveter's plugins (docs/heroes/rosie-the-riveter.md): `rosie:deactivate`, `rosie:attack_bonus`, the test `rosie:upgrade` and `rosie:loose_lips`.

The upgrades are two ability counters (`upgrades` = how many are active, `upgrade_shift` = how far the row has turned, see
sparring/upgrades.py). Activating one, activating all and the reset at the end of the turn are plain `counter` ops of the effects
file; the single DEACTIVATION is the one thing a counter op cannot say, because the upgrade that goes down leaves the front of the
row and lands at its end, which changes which upgrade the next activation flips. That is `rosie:deactivate`.

Loose Lips Sink Ships!: "Your opponent reveals the top card of their deck. Decrease the value of their card by the revealed card's
BOOST value." Whose deck is real follows Jill Trent's Hypnoray Blaster (effects/plugins_jill.py): the engine's player reads its deck,
the table player's top card is read from the table through `Game.deck_reader`, and a table that cannot be read shows nothing."""
from __future__ import annotations

from .. import upgrades
from ..i18n import t
from . import modifiers
from .model import EffectError
from .ops_core import plugin, plugin_condition
from .plugins_jill import show, top_cards
from .select import card_ref


@plugin("rosie:attack_bonus")
def _attack_bonus(run, game, spec):
    """Sedgley Fist Gun ("Add +1 to the value of Rosie's attacks"): what the active upgrades add to the attack of the hero fighter, in this
    combat's DURING (the hero's own `ability.during`, so cancelling the card's effects does not take it away). Read when it resolves:
    an upgrade a card activated in IMMEDIATELY (We Can Do It!) counts for that very attack."""
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError("rosie:attack_bonus: only inside a combat")
    for n, label in upgrades.attack_bonus_parts(game, game.hero(run.ctx.owner)):
        modifiers.add_value(flow, "atk", n, label)


@plugin("rosie:deactivate")
def _deactivate(run, game, spec):
    """Flips the leftmost active upgrade down and sends it to the end of the row (nothing when none is active)."""
    upgrades.deactivate(game, run.ctx.owner)


@plugin_condition("rosie:upgrade")
def _upgrade_active(game, run, key: str) -> bool:
    """`key` is an upgrade id of the hero's row (merlin_engine, cavity_magnetron, sedgley_fist_gun, whizbang): it is active now."""
    owner = run.ctx.owner
    if not any(u["id"] == key for u in upgrades.row(game, owner)):
        raise EffectError(f"rosie:upgrade: unknown upgrade {key!r}")
    return upgrades.is_active(game, owner, key)


@plugin("rosie:loose_lips")
def _loose_lips(run, game, spec):
    """Reveal the top card of the opponent's deck and take its BOOST value off the value of the opponent's card in this combat."""
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError("rosie:loose_lips: only inside a combat")
    owner, rival = run.ctx.owner, 1 - run.ctx.owner
    seen = top_cards(game, rival, 1)
    if not seen:
        return
    show(game, owner, rival, seen)
    cards = card_ref(game, run, "opponent_card")
    if cards:
        side = modifiers.side_of(flow, cards[0])
        if side is not None:
            modifiers.add_value(flow, side, -seen[0].boost, t("fx.rosie.loose_lips", title=seen[0].title))
