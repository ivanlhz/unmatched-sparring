"""Little Red's decision for the bot: which symbol a wild basket counts as (docs/heroes/little-red-riding-hood.md, AI).

The question is asked when a line with a symbol resolves while the basket is wild (the starting Basket, or a star card on top of the
discard pile). Most cards have ONE symbol line, so the answer is that symbol; Large Hands is the exception (its rose line REPLACES the
return of the card, and with the Basket on top there is nothing to return) and Never Leave the Path has three lines to weigh. Nothing here
reads anything hidden: the rival's hand is never looked at, only the board, the bot's own hand and its own deck size."""
from __future__ import annotations

from .effects.model import load_effects
from .effects.plugins_little_red import SYMBOLS

PATH = "Never Leave the Path"
HANDS = "What Large Hands You Have"
ACTION_WORTH = 1.4           # a free action, in the units of a point of damage


def symbols_of_card(slug: str, title: str) -> list[str]:
    """The symbols the lines of the card's effects test (in order, once each)."""
    found: list[str] = []
    for ops in load_effects(slug).card(title).moments.values():
        for cond in _conditions(ops):
            if cond.get("id") == "red:basket" and cond["key"] not in found:
                found.append(cond["key"])
    return found


def _conditions(node):
    if isinstance(node, dict):
        if node.get("test") == "plugin":
            yield node
        for v in node.values():
            yield from _conditions(v)
    elif isinstance(node, list):
        for v in node:
            yield from _conditions(v)


def pick_symbol(game, req) -> int:
    """The index (into `req.extra["symbols"]`) of the symbol the bot gives its wild basket."""
    me = req.player
    card = game.card_of(req.card_id, req.card_owner if req.card_owner is not None else me) if req.card_id is not None else None
    symbols = list(req.extra.get("symbols") or SYMBOLS)
    if card is None:
        return 0
    lines = symbols_of_card(game.players[me].hero.slug, card.title)
    if card.title == HANDS:                          # rose only when it has a card to bring back
        return symbols.index("rose" if game.players[me].discard else "wolf")
    if len(lines) == 1:
        return symbols.index(lines[0])
    if card.title == PATH:
        return symbols.index(_path_symbol(game, me))
    return symbols.index(lines[0]) if lines else 0


def _path_symbol(game, me: int) -> str:
    """Never Leave the Path: 2 damage to each rival in her zone (a kill counts double), 3 cards, or a free place and an action."""
    hero = game.hero(me)
    st = game.players[me]
    foes = [f for f in game.own(1 - me) if hero.pos is not None and f.pos is not None and game.board.share_zone(hero.pos, f.pos)]
    axe = sum(min(2, f.hp) * (2.0 if f.hp <= 2 else 1.0) for f in foes)
    room = max(0, game.fx.hand_limit(me, st.hero.hand_max) - len(st.hand))
    rose = 0.9 * min(3, len(st.deck), max(room, 1))
    wolf = ACTION_WORTH
    best = max((axe, 2), (rose, 1), (wolf, 0))
    return {2: "axe", 1: "rose", 0: "wolf"}[best[1]]
