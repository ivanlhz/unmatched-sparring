"""What the AI knows about Robin Hood's cards (docs/heroes/robin-hood.md): the value an attack will really have, what each AFTER is worth, and
the answer of the rival of Steal From the Rich.

`ai_medusa.card_value` and the rival models read the printed value, so Ambush (it adds the BOOST of a card of the rival's hand) and Highway
Robbery (the defense counts for nothing) need these figures to be played at the price they are worth; Disarming Shot, Snark, Wily Fighting and
Defenders of Sherwood have an AFTER the data-driven profile does not price. Everything reads what the bot can know when it decides: the rival's
cards it has not seen played (their composition minus their discard pile), never their hand.

The weights are the AI's usual ones, passed in by the caller so this module never imports the AI."""
from __future__ import annotations

AMBUSH, ROBBERY, DISARMING, STEAL = "Ambush", "Highway Robbery", "Disarming Shot", "Steal From the Rich"
SNARK, WILY, DEFENDERS = "Snark", "Wily Fighting", "Defenders of Sherwood"
DISARMING_DRAWS = 2.0          # cards Disarming Shot draws on average when it wins: the damage it deals (a 4 against a defense of 2)
OUTLAW_RETURN = 0.5            # a defeated Outlaw back on the board, in cards (a 1 health fighter that may play any card of the deck)


def is_his(game, owner: int) -> bool:
    return game.players[owner].hero.fid == "robin"


def _unseen(game, owner: int) -> list:
    """The cards the rival has not played yet, as far as public information goes (its composition minus its discard pile)."""
    st = game.players[1 - owner]
    return [c for c in st.full_set if c not in st.gone]


def attack_value(game, owner: int, card) -> float | None:
    """The value `card` will have as an attack of Robin Hood's player, or None when it is the printed one."""
    if not is_his(game, owner) or card.title != AMBUSH:
        return None
    left = _unseen(game, owner)
    mean_boost = sum(c.boost for c in left) / len(left) if left else 0.0
    return card.value + (mean_boost if game.players[1 - owner].hand else 0.0)


def ignores_defense(game, owner: int, card) -> bool:
    """Highway Robbery: the defender's value counts for nothing."""
    return is_his(game, owner) and card.title == ROBBERY


def _next_to_a_foe(game, owner: int) -> bool:
    hero = game.hero(owner)
    return hero.pos is not None and any(f.alive and f.owner != owner and f.pos in game.board.adj[hero.pos] for f in game.fighters.values())


def after_value(game, owner: int, card, p_win: float, foe_hp_weight: float, card_value: float) -> float:
    """What the AFTER of one of his cards is worth, in the AI's units (`foe_hp_weight` per hit point of an opposing fighter, `card_value` per
    card). `p_win`: the chance the card's player wins the combat (the chance of no damage for a defense). 0 for any card the AI prices from
    the data."""
    if not is_his(game, owner) or not game.hero(owner).alive:
        return 0.0
    title = card.title
    if title == DISARMING:
        return card_value * DISARMING_DRAWS * p_win
    if title == SNARK:
        return card_value if _next_to_a_foe(game, owner) else 0.0
    if title == WILY:
        hero = game.hero(owner)
        near = [f for f in game.fighters.values() if f.alive and f.owner != owner and hero.pos is not None and f.pos in game.board.adj[hero.pos]]
        return foe_hp_weight * len(near)
    if title == DEFENDERS:
        defeated = any(not f.alive and f.owner == owner and not f.hero and f.died_at is not None for f in game.fighters.values())
        return card_value * (1 + (OUTLAW_RETURN if defeated else 0.0))
    return 0.0


def is_steal(game, req) -> bool:
    """The optional discard the request asks is the one of Robin Hood's Steal From the Rich."""
    card = None if req.card_id is None or req.card_owner is None else game.card_of(req.card_id, req.card_owner)
    return card is not None and card.title == STEAL and is_his(game, req.card_owner)


def steal_pays(game, req) -> bool:
    """Steal From the Rich, answered by the rival of Robin Hood: discard a card, or let him draw one more. The rival discards its least useful
    card when that costs less than the card Robin Hood would draw, judged on the average of what he still holds (the rival's own hand is
    known to it; his is not)."""
    from .search.adapter import card_worth
    me = req.player
    mine = game.players[me].hand
    robin = game.players[1 - me]
    left = [c for c in robin.full_set if c not in robin.gone]
    if not mine or not left:
        return False
    return min(card_worth(c) for c in mine) < sum(card_worth(c) for c in left) / len(left)
