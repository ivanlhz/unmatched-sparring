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
EXTRA_ACTION_CARDS = 2.0            # what the extra action of next turn is worth, in cards of the hand (a Maneuver's draw and a move, or one more blow)


def is_hers(game, owner: int) -> bool:
    return game.players[owner].hero.fid == "mary"


def _unseen(game, owner: int) -> list:
    """The cards the rival has not played yet, as far as public information goes (its composition minus its discard pile)."""
    st = game.players[1 - owner]
    return [c for c in st.full_set if c not in st.gone]


def third_action(game, owner: int) -> bool:
    """The action about to be spent is the third of the owner's turn (the tally counts the actions already spent)."""
    return game.turn == owner and game.fx.taken == 2


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


def defense_value(game, owner: int, card, attack_card=None) -> float | None:
    """The value `card` will have as a defense of Bloody Mary's player: Mirror Image copies the printed value of the attack it meets (the
    card itself when the bot knows it, else the mean of the attacks the rival may still play); the rest are printed."""
    if not is_hers(game, owner) or card.title != MIRROR:
        return None
    if attack_card is not None and attack_card.value is not None:
        return float(attack_card.value)
    attacks = [c.value for c in _unseen(game, owner) if c.can_attack and c.value is not None]
    return sum(attacks) / len(attacks) if attacks else 0.0


def kept_cards_bonus(game, owner: int, held: int | None = None) -> float:
    """In cards: what the next turn's third action is worth when `owner` ends this turn holding `held` cards (default: now). 0 for any
    other hero, and for a hero that cannot gain actions."""
    if not is_hers(game, owner) or not game.fx.can_gain_actions(owner):
        return 0.0
    held = len(game.players[owner].hand) if held is None else held
    return EXTRA_ACTION_CARDS if held == TRIGGER_CARDS else 0.0
