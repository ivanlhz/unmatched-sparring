"""The hand-limit discard and the maneuver boost keep the defence: a card that no living fighter can use goes first, and the last card able
to defend is the last one to go. Asked in the three places that choose: `MedusaAI.choose_discard` (the real end-of-turn discard),
`SearchController.choose_discard` (inside the search) and `EngineState._boost_variants` (the boosts the tree is offered)."""
import pytest

from ai_positions import build, make_ai
from sparring.ai_medusa import MedusaAI, can_use, discard_order, keep_value
from sparring.search.adapter import EngineState, SearchController, card_worth

POS = "sinbad_liz_t17_keeps_regroup_boost"       # the Porter is dead; the hand: six Voyages, By Fortune and Fate (Porter only), Regroup


def hand_of(game, *titles):
    """The hand set to these titles (taken from the set, each card once), for the bot (player 0)."""
    player, taken, hand = game.players[0], set(), []
    for title in titles:
        card = next(c for c in player.full_set if c.title == title and c.card_id not in taken)
        taken.add(card.card_id)
        hand.append(card)
    player.hand[:] = hand
    return {c.title: c for c in hand}


@pytest.fixture
def game():
    return build(POS, make_ai("heuristic"))


CHOOSERS = {
    "real": lambda g, n: MedusaAI(0).choose_discard(g, 0, n, "hand limit"),
    "tree": lambda g, n: SearchController(0, EngineState(g, observer=0)).choose_discard(g, 0, n, "hand limit"),
}


def test_a_card_nobody_alive_can_use_is_dead_and_the_others_are_not(game):
    cards = hand_of(game, "By Fortune and Fate", "Regroup", "Voyage to the City of the Man-Eating Apes")
    assert not can_use(game, 0, cards["By Fortune and Fate"])
    assert can_use(game, 0, cards["Regroup"]) and can_use(game, 0, cards["Voyage to the City of the Man-Eating Apes"])
    game.fighters["porter"].alive = True
    assert can_use(game, 0, cards["By Fortune and Fate"])


@pytest.mark.parametrize("who", CHOOSERS)
def test_the_dead_card_is_discarded_before_any_other(game, who):
    cards = hand_of(game, "Voyage to the City of the Man-Eating Apes", "By Fortune and Fate", "Regroup", "Voyage to the Island That Was a Whale")
    assert CHOOSERS[who](game, 1) == [cards["By Fortune and Fate"]]


@pytest.mark.parametrize("who", CHOOSERS)
def test_the_last_card_able_to_defend_is_discarded_last(game, who):
    cards = hand_of(game, "Voyage to the City of the Man-Eating Apes", "Regroup", "Voyage to the Island That Was a Whale", "By Fortune and Fate")
    kept = [c for c in cards.values() if c not in CHOOSERS[who](game, 3)]
    assert kept == [cards["Regroup"]]


@pytest.mark.parametrize("who", CHOOSERS)
def test_with_several_defenders_the_best_one_is_kept(game, who):
    cards = hand_of(game, "Regroup", "Toil and Danger", "Voyage to the City of the Man-Eating Apes", "Voyage to the Island That Was a Whale")
    kept = [c for c in cards.values() if c not in CHOOSERS[who](game, 3)]
    assert kept == [cards["Toil and Danger"]]            # value 3 against 1


@pytest.mark.parametrize("who", CHOOSERS)
def test_without_a_dead_card_or_a_defender_the_order_is_the_old_one(game, who):
    cards = hand_of(game, "Voyage to the City of the Man-Eating Apes", "Voyage to the Island That Was a Whale", "Voyage to the Valley of the Giant Snakes")
    old = sorted(cards.values(), key=lambda c: ((keep_value(c, list(cards.values())) if who == "real" else card_worth(c)), c.card_id))
    assert CHOOSERS[who](game, 2) == old[:2]


def test_discard_order_puts_the_dead_first_and_the_best_defender_last(game):
    cards = hand_of(game, "Regroup", "By Fortune and Fate", "Voyage to the City of the Man-Eating Apes", "Toil and Danger")
    order = discard_order(game, 0, list(cards.values()), key=lambda c: card_worth(c))
    assert order[0] is cards["By Fortune and Fate"] and order[-1] is cards["Toil and Danger"]


def boosts(game):
    return EngineState(game, observer=0)._boost_variants(0)


def test_the_last_defence_card_is_the_dearest_boost_of_its_value(game):
    """Regroup and the dead card boost by the same 1: the dead one is offered, the only defender is not."""
    cards = hand_of(game, "Voyage to the City of the Man-Eating Apes", "Regroup", "By Fortune and Fate")
    assert boosts(game)[1:] == [cards["By Fortune and Fate"]]


def test_the_dead_card_is_offered_as_the_boost_before_the_defence_card(game):
    cards = hand_of(game, "Voyage to the City of the Man-Eating Apes", "Regroup", "By Fortune and Fate")
    offered = boosts(game)
    assert cards["By Fortune and Fate"] in offered and cards["Regroup"] not in offered


def test_with_a_second_defender_the_boost_is_free(game):
    """Only the LAST card able to defend is spared: with two, the tree is offered the boosts it always was."""
    cards = hand_of(game, "Regroup", "Toil and Danger", "Voyage to the City of the Man-Eating Apes")
    offered = boosts(game)
    assert cards["Regroup"] in offered or cards["Toil and Danger"] in offered
