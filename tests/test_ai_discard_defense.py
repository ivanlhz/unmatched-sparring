"""The hand-limit discard, the effect discards and the maneuver boost keep the defence: a card that no living fighter can use goes first,
and the hand never loses its last card able to defend while an ordinary card can go instead. When the old order already kept a defender,
nothing changes. Asked where the bot chooses: `MedusaAI.choose_discard` (the real end-of-turn discard), `SearchController.choose_discard`
(inside the search), `EffectAI` (a card effect that makes the bot discard) and `EngineState._boost_variants` (the boosts the tree is offered)."""
import pytest

from ai_positions import build, make_ai
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import MedusaAI, can_use, keep_value
from sparring.effects.choose import ChoiceRequest
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
    old = sorted(cards.values(), key=lambda c: ((keep_value(c, list(cards.values())) if who != "tree" else card_worth(c)), c.card_id))
    assert CHOOSERS[who](game, 2) == old[:2]


def effect_discard(game, n, lo=None):
    """A card effect that makes the bot discard `n` of its hand (at least `lo`, `n` by default), answered as the table answers it."""
    ids = [c.card_id for c in game.players[0].hand]
    req = ChoiceRequest(player=0, kind="cards", options=ids, min=n if lo is None else lo, max=n, prompt="",
                        extra={"zone": "hand", "purpose": "discard", "of": 0})
    by_id = {c.card_id: c for c in game.players[0].hand}
    return [by_id[i] for i in MedusaAI(0).choose_effect(game, req)]


CHOOSERS["effect"] = lambda g, n: effect_discard(g, n)


def test_the_effect_discard_of_the_t17_hand_keeps_regroup(game):
    """The reviewer's case: the same live hand, a card effect asking for three."""
    cards = hand_of(game, "Voyage to the City of the Man-Eating Apes", "Regroup", "Voyage to the Island That Was a Whale", "By Fortune and Fate")
    assert cards["Regroup"] not in effect_discard(game, 3)


def test_the_optional_extras_of_an_effect_discard_never_take_the_last_defence(game):
    cards = hand_of(game, "Voyage to the City of the Man-Eating Apes", "Regroup", "Voyage to the Island That Was a Whale", "By Fortune and Fate")
    assert cards["Regroup"] not in effect_discard(game, 4, lo=1)


@pytest.mark.parametrize("who", CHOOSERS)
def test_a_hand_of_defenders_is_cut_by_price(game, who):
    cards = hand_of(game, "Regroup", "Toil and Danger")
    assert len(CHOOSERS[who](game, 1)) == 1


@pytest.mark.parametrize("who", ("real", "tree"))
def test_when_the_old_cut_keeps_a_defender_nothing_changes(game, who):
    cards = hand_of(game, "Regroup", "Toil and Danger", "Voyage to the City of the Man-Eating Apes", "Voyage to the Island That Was a Whale")
    hand = list(cards.values())
    price = (lambda c: keep_value(c, hand)) if who == "real" else card_worth
    old = sorted(hand, key=lambda c: (price(c), c.card_id))[:2]
    assert sorted(c.card_id for c in CHOOSERS[who](game, 2)) == sorted(c.card_id for c in old)


def boosts(game):
    return EngineState(game, observer=0)._boost_variants(0)


def test_the_last_defence_card_is_the_dearest_boost_of_its_value(game):
    """Regroup and the dead card boost by the same 1: the dead one is offered, the only defender is not."""
    cards = hand_of(game, "Voyage to the City of the Man-Eating Apes", "Regroup", "By Fortune and Fate")
    assert boosts(game)[1:] == [cards["By Fortune and Fate"]]


def test_with_a_second_defender_the_boost_is_free(game):
    """Only the LAST card able to defend is spared: with two, the tree is offered the boosts it always was."""
    cards = hand_of(game, "Regroup", "Toil and Danger", "Voyage to the City of the Man-Eating Apes")
    offered = boosts(game)
    assert cards["Regroup"] in offered or cards["Toil and Danger"] in offered
