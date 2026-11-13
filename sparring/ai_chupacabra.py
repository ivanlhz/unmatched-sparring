"""What the AI knows about Chupacabra's cards (docs/heroes/chupacabra.md): the value an attack will really have and what each AFTER is worth.

`ai_medusa.card_value` and the rival models read the printed value, so a card whose DURING decides it needs these figures to be played at
all: The More They Struggle prints 0 (it is twice the value of the card it meets), Ambush adds the BOOST of a card of the rival's hand, and
Wounded Beast is a 5 for a hero that is down to 7 health. Everything reads what the bot can know when it decides: the rival's cards it
has not seen played (their composition minus their discard pile), never their hand.

The weights are the AI's usual ones, passed in by the caller so this module never imports the AI."""
from __future__ import annotations

MORE, AMBUSH, WOUNDED = "The More They Struggle", "Ambush", "Wounded Beast"
FEEDING, LUNGE, TOOTH, TOUGHNESS = "Feeding", "Ravenous Lunge", "Tooth and Tail", "Natural Toughness"
LOW_HEALTH = 7                      # "7 or less health": Wounded Beast is a 5 and Feeding gives an action and a hit point
WOUNDED_VALUE = 5
ADJACENT_TARGETS = 2                # Tooth and Tail hurts up to two fighters
TOUGHNESS_RETURN = 0.6              # Natural Toughness back in the hand after a lost combat, in cards (it is a 3 defense that stays)


def is_his(game, owner: int) -> bool:
    return game.players[owner].hero.fid == "chupacabra"


def _unseen(game, owner: int) -> list:
    """The cards the rival has not played yet, as far as public information goes (its composition minus its discard pile)."""
    st = game.players[1 - owner]
    return [c for c in st.full_set if c not in st.gone]


def wounded(game, owner: int) -> bool:
    hero = game.hero(owner)
    return hero.alive and hero.hp <= LOW_HEALTH


def attack_value(game, owner: int, card) -> float | None:
    """The value `card` will have as an attack of Chupacabra's player, or None when it is the printed one."""
    if not is_his(game, owner):
        return None
    title = card.title
    if title == WOUNDED:
        return float(WOUNDED_VALUE) if wounded(game, owner) else None
    left = _unseen(game, owner)
    if title == MORE:
        blocks = [c.value for c in left if c.can_defend and c.value is not None]
        return 2.0 * sum(blocks) / len(blocks) if blocks else 0.0
    if title == AMBUSH:
        mean_boost = sum(c.boost for c in left) / len(left) if left else 0.0
        return card.value + (mean_boost if game.players[1 - owner].hand else 0.0)
    return None


def defense_value(game, owner: int, card) -> float | None:
    """The value `card` will have as a defense of Chupacabra's player: only Wounded Beast changes (the rest are printed)."""
    if is_his(game, owner) and card.title == WOUNDED and wounded(game, owner):
        return float(WOUNDED_VALUE)
    return None


def after_value(game, owner: int, card, p_win: float, foe_hp_weight: float, card_value: float, hero_hp_weight: float,
                action_value: float) -> float:
    """What the AFTER of one of his cards is worth, in the AI's units (`foe_hp_weight` per hit point of an opposing fighter, `card_value`
    per card, `hero_hp_weight` per hit point of Chupacabra, `action_value` per action). `p_win`: the chance the card's player wins the
    combat (the chance of no damage for a defense). 0 for any card the AI prices from the data."""
    if not is_his(game, owner):
        return 0.0
    hero = game.hero(owner)
    if not hero.alive:
        return 0.0
    missing = hero.max_hp - hero.hp
    title = card.title
    if title == FEEDING:
        if hero.hp > LOW_HEALTH:
            return 0.0
        return hero_hp_weight * min(1, missing) + (action_value if game.turn == owner else 0.0)
    if title == LUNGE:
        return hero_hp_weight * ((1 - p_win) * min(1, missing) + p_win * min(2, missing))
    if title == TOOTH:
        near = [f for f in game.fighters.values() if f.alive and f.owner != owner and f.pos is not None and hero.pos is not None
                and f.pos in game.board.adj[hero.pos]]
        hit = min(ADJACENT_TARGETS, len(near))
        return foe_hp_weight * hit + hero_hp_weight * min(hit, missing)
    if title == TOUGHNESS:
        return card_value * TOUGHNESS_RETURN * (1 - p_win)
    return 0.0
