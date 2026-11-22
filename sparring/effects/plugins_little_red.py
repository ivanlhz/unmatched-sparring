"""Little Red's basket (docs/heroes/little-red-riding-hood.md): the test `red:basket` and the plugin `red:stones`.

THE BASKET is the symbol of the top card of her player's discard pile. The pile is a list whose last element is the newest card
(`Game.discard_card` appends, every effect that returns a card takes it out by identity), so the top is `discard[-1]` and the ORDER of
the pile is part of the game state: it is saved, cloned and part of the search's keys.

  * no card in the pile: the starting Basket, a component that is never a card (it is never drawn, counted or returned). It is wild;
  * a card whose tag is `symbol:wolf|rose|axe`: that symbol;
  * a card whose tag is `symbol:wild` (What's That In My Basket?): wild;
  * a card with no symbol at all (a card of another deck that found its way onto her pile): `none`, which matches nothing.

A wild basket counts as ONE symbol its player chooses (Ivan 2026-11-22, LR1). The choice is asked the first time a line with a symbol needs
it in a card's play and is kept in the flags of that run (saved with it), so Never Leave the Path, whose three lines are three tests of one run, asks
once. The deck has no card with a symbol line in two moments, so no choice has to travel between runs. It is only used while the basket is still
wild: a card that reaches the pile in between (a BOOST card, a discard the opponent forced) makes the basket that card's symbol. The test is
evaluated when each effect line resolves, so the basket can change in the middle of a combat; the combat cards reach the pile last.

`red:stones` is Stones in the Belly's discard: the rival discards 1 random card and its BOOST is added to this card (Ambush's flow)."""
from __future__ import annotations

from ..i18n import t
from . import modifiers
from .model import EffectError
from .ops_core import plugin, plugin_condition
from .random_discard import discard_random_known

SYMBOLS = ("wolf", "rose", "axe")
WILD = "wild"
NONE = "none"
TAG = "symbol:"
FLAG = "basket_symbol"
TAG_NAME = "basket"                    # `extra["tag"]` of the request that asks the player which symbol a wild basket counts as


def symbol_of(card) -> str | None:
    """The symbol printed in the lower left corner of `card` (wolf, rose, axe or wild), None for a card of another hero."""
    for tag in card.tags:
        if tag.startswith(TAG):
            return tag[len(TAG):]
    return None


def basket(game, player: int) -> str:
    """What `player`'s basket shows: a symbol, `wild` (the starting Basket with nothing in the pile, or a star card on top) or `none`."""
    pile = game.players[player].discard
    if not pile:
        return WILD
    return symbol_of(pile[-1]) or NONE


def top_card(game, player: int):
    """The card on top of `player`'s discard pile (None: only the Basket lies there)."""
    pile = game.players[player].discard
    return pile[-1] if pile else None


DEFEND_TAG = "defend_if_axe"          # What Big Ears You Have: "(axe) You may play this card as a defense card"


def may_defend_with(game, player: int, card) -> bool:
    """`card` is an attack that may be played as a defense now: Big Ears while the basket is an axe (a wild basket may count as one: the
    line has nothing to resolve, so no question is asked). It is checked when the card is played; a later cancel keeps it a defense."""
    return DEFEND_TAG in card.tags and basket(game, player) in ("axe", WILD)


def _choose_symbol(game, run, owner: int) -> str:
    chosen = run.flags.get(FLAG)
    if chosen is None:
        labels = [t(f"basket.symbol.{s}") for s in SYMBOLS]
        got = run.ask(game, "effect", owner, list(range(len(SYMBOLS))), 1, 1, "choose the symbol the basket counts as",
                      tag=TAG_NAME, labels=labels, symbols=list(SYMBOLS))
        chosen = SYMBOLS[got[0]]
    run.flags[FLAG] = chosen
    return chosen


@plugin_condition("red:basket")
def _basket_shows(game, run, key: str) -> bool:
    """`wolf`, `rose` or `axe`: the line's symbol matches the basket (a wild one counts as the symbol its player chooses)."""
    if key not in SYMBOLS:
        raise EffectError(f"red:basket: unknown symbol {key!r}")
    owner = run.ctx.owner
    shown = basket(game, owner)
    wild = shown == WILD
    if wild:
        shown = _choose_symbol(game, run, owner)
    if shown in SYMBOLS:
        notices = run.flags.setdefault("notices", [])
        note = f"basket_{'wild_' if wild else ''}{shown}"        # the line of the card says what the basket was, once per run
        if note not in notices:
            notices.append(note)
    return shown == key


@plugin("red:stones")
def _stones(run, game, spec):
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError("red:stones: only inside a combat")
    side = "atk" if run.ctx.played_as == "attack" else "def"
    card = discard_random_known(run, game, 1 - run.ctx.owner) if game.fx.can_force_discard(1 - run.ctx.owner, run.ctx.owner) else None
    if card is not None:
        modifiers.add_value(flow, side, card.boost, t("cf.ambush", title=card.title, boost=card.boost))
