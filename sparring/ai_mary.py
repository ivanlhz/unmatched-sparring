"""What the AI knows about Bloody Mary's cards and her ability (docs/heroes/bloody-mary.md).

Her ability gives a third action when the turn starts with EXACTLY 3 cards in hand, and three cards read "if this is your third action
this turn". `ai_medusa.card_value` and the rival models read the printed value, so a card whose DURING decides it needs these figures to
be played (or feared) for what it is worth: Speak Three Times is a 7 when the attack is the third action the owner takes, Jump Scare a 6
when she shares no zone with where she started the turn, Out Of The Mirror adds the BOOST of a card of the rival's hand and Mirror Image
copies the printed value of the card it meets. Everything reads what the bot can know when it decides: the rival's cards it has not seen
played (their composition minus their discard pile), never their hand.

The tempo of the ability (`kept_cards_bonus`): a turn that STARTS with 3 cards has a third action, so a hand of 3 at the end of her turn is
worth an extra action next turn. The bot cannot discard at will: it gets there by what it plays and draws (a Maneuver draws one, an attack
spends one, Evade and Closer Than She Appears draw). Both AIs count it: the heuristic in the value of the hand it keeps, the search in the
leaf of the position (`search.adapter.EvalWeights.tempo`).

The weights are the AI's usual ones, passed in by the caller so this module never imports the AI."""
from __future__ import annotations

SPEAK, JUMP, OUT, MIRROR = "Speak Three Times", "Jump Scare", "Out Of The Mirror", "Mirror Image"
THIRD_ACTION_VALUE = 7
JUMP_VALUE = 6
TRIGGER_CARDS = 3                   # "exactly 3 cards in hand"
EXTRA_ACTION_CARDS = 1.5            # what the extra action of next turn is worth, in cards of the hand (a Maneuver's draw and a move, or one more blow)


def is_hers(game, owner: int) -> bool:
    return game.players[owner].hero.fid == "mary"


def _unseen(game, owner: int) -> list:
    """The cards the rival has not played yet, as far as public information goes (its composition minus its discard pile)."""
    st = game.players[1 - owner]
    return [c for c in st.full_set if c not in st.gone]


def third_action(game, owner: int) -> bool:
    """The action about to be spent is the third of the owner's turn (the tally counts the actions already spent)."""
    return game.turn == owner and game.fx.taken == 2


CLOSER = "Closer Than She Appears"


def holds_for_third(game, owner: int, card) -> bool:
    """Speak Three Times is kept in the hand for now: this turn can still give the owner a THIRD action (the actions already taken plus the
    ones left, plus the Closer Than She Appears in the hand that give one back) and no blow of 3 would finish the rival's hero today, so
    the bot spends the actions before it (a Maneuver, another card) and plays it as the third, worth 7 instead of 3. A hard gate on the
    card, like `ai_medusa.held_for_plan`: the search's rollouts play the cards of a turn in random order and never saw the 7 (1500
    iterations, 4 seeds out of 4 attacked with it first)."""
    if not is_hers(game, owner) or card.title != SPEAK or game.turn != owner or game.fx.taken > 1 or not game.fx.can_gain_actions(owner):
        return False
    closers = sum(1 for c in game.players[owner].hand if c.title == CLOSER)
    if game.fx.taken + game.actions_left + closers < 3 or len(game.players[owner].deck) < 2 - game.fx.taken:
        return False                      # no third action to reach, or the Maneuvers before it would draw from an empty deck (2 damage each)
    return not any(f.hero and f.alive and f.hp <= (card.value or 0) for f in game.foes(owner))


def attack_value(game, owner: int, card, fighter) -> float | None:
    """The value `card` will have as an attack of Bloody Mary's player, or None when it is the printed one."""
    if not is_hers(game, owner):
        return None
    title = card.title
    if title == SPEAK:
        return float(THIRD_ACTION_VALUE) if third_action(game, owner) else None
    if title == JUMP:
        start = game.fx.turn_start_pos.get(fighter.fid)
        if start is not None and fighter.pos is not None and not game.board.share_zone(start, fighter.pos):
            return float(JUMP_VALUE)
        return None
    if title == OUT:
        left = _unseen(game, owner)
        mean_boost = sum(c.boost for c in left) / len(left) if left else 0.0
        return card.value + (mean_boost if game.players[1 - owner].hand else 0.0)
    return None


def is_mirror(game, owner: int, card) -> bool:
    """`card` is Mirror Image in the hand of Bloody Mary's player: its value is whatever the attack it meets prints."""
    return is_hers(game, owner) and card.title == MIRROR


def defense_value(game, owner: int, card, attack_card=None) -> float | None:
    """The value `card` will have as a defense of Bloody Mary's player: Mirror Image copies the printed value of the attack it meets (the
    card itself when the bot knows it, else the mean of the attacks the rival may still play); the rest are printed."""
    if not is_hers(game, owner) or card.title != MIRROR:
        return None
    if attack_card is not None and attack_card.value is not None:
        return float(attack_card.value)
    attacks = [c.value for c in _unseen(game, owner) if c.can_attack and c.value is not None]
    return sum(attacks) / len(attacks) if attacks else 0.0


def after_value(game, owner: int, card, card_value: float, hero_hp_weight: float) -> float:
    """What the AFTER of one of her cards is worth, in the AI's units (`card_value` per card, `hero_hp_weight` per hit point of hers): Evade
    and the third-action Out Of The Mirror draw, the third-action Ghostly Touch heals up to 3. The rest of her AFTERs are the generic ones."""
    if not is_hers(game, owner):
        return 0.0
    title = card.title
    if title == "Evade":
        return card_value
    if title == OUT and third_action(game, owner):
        return card_value
    if title == "Ghostly Touch" and third_action(game, owner):
        hero = game.hero(owner)
        return hero_hp_weight * min(3, hero.max_hp - hero.hp) if hero.alive else 0.0
    return 0.0


def pick_broken_glass(values: list[int], options: list[int], labels: list[str]) -> int:
    """Broken Glass's DURING ("+1", "-1" or "0", labels of the choice): the option that makes the two totals of the combat equal, which draws a
    card and deals 2 (the exact tie with the rival's card, or a step of 1 either way), else the point more (it wins a tie, or takes one off the
    blow). `values` = [hers, the rival's] as they stand before the choice."""
    mine, theirs = values
    steps = {k: int(labels[k]) for k in options}
    for k in options:
        if mine + steps[k] == theirs:
            return k
    return next((k for k in options if steps[k] > 0), options[0])


def kept_cards_bonus(game, owner: int, held: int | None = None) -> float:
    """In cards: what the next turn's third action is worth when `owner` ends this turn holding `held` cards (default: now). 0 for any
    other hero, and for a hero that cannot gain actions."""
    if not is_hers(game, owner) or not game.fx.can_gain_actions(owner):
        return 0.0
    held = len(game.players[owner].hand) if held is None else held
    return EXTRA_ACTION_CARDS if held == TRIGGER_CARDS else 0.0
