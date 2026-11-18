"""The hand-limit discard, the effect discards and the maneuver boost keep the defence: a card that no living fighter can use goes first,
and the hand never loses its last card able to defend while an ordinary card can go instead. When the old order already kept a defender,
nothing changes. Asked where the bot chooses: `MedusaAI.choose_discard` (the real end-of-turn discard), `SearchController.choose_discard`
(inside the search), `EffectAI` (a card effect that makes the bot discard) and `EngineState._boost_variants` (the boosts the tree is offered)."""
import pytest

from ai_positions import build, make_ai
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import MedusaAI, can_use, discard_cut, keep_value
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
    assert CHOOSERS[who](game, 1) == [cards["Regroup"]]        # the cheaper defender goes, the other one still defends


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


def test_a_defender_left_out_of_the_offer_still_defends(game):
    """An effect that offers only some cards of the hand: Toil and Danger stays in the hand, so the cut follows the price."""
    cards = hand_of(game, "Regroup", "Voyage to the City of the Man-Eating Apes", "By Fortune and Fate", "Toil and Danger")
    offered = [cards[t] for t in ("Regroup", "Voyage to the City of the Man-Eating Apes", "By Fortune and Fate")]
    hand = list(cards.values())
    price = lambda c: keep_value(c, hand)
    plain = discard_cut(game, 0, offered, price, 2)
    by_price = [cards["By Fortune and Fate"]] + sorted(offered[:2], key=lambda c: (price(c), c.card_id))[:1]     # the dead card, then the cheapest
    assert discard_cut(game, 0, offered, price, 2, hand=hand) == by_price
    assert cards["Regroup"] not in plain       # without the whole hand the cut would have protected it


@pytest.mark.parametrize("n", (0, 4, 9))
def test_a_cut_of_nothing_or_of_everything_is_plain(game, n):
    cards = hand_of(game, "Voyage to the City of the Man-Eating Apes", "Regroup", "Voyage to the Island That Was a Whale", "By Fortune and Fate")
    got = discard_cut(game, 0, list(cards.values()), card_worth, n)
    assert len(got) == min(n, 4)


def test_a_reserved_card_is_never_given_up_to_save_the_defender(game, monkeypatch):
    import sparring.ai_medusa as M
    cards = hand_of(game, "Regroup", "Voyage to the City of the Man-Eating Apes")
    voyage = cards["Voyage to the City of the Man-Eating Apes"]
    monkeypatch.setattr(M, "is_reserved", lambda c: c is voyage)
    price = lambda c: 0.0 if c is cards["Regroup"] else 1.0      # the plain cut gives up Regroup
    assert discard_cut(game, 0, list(cards.values()), price, 1) == [cards["Regroup"]]


def rage(game, margin):
    """Unbridled rage on Liz: each card given up adds 1 to the blow, which already beats the defence by `margin`."""
    ids = [c.card_id for c in game.players[0].hand]
    req = ChoiceRequest(player=0, kind="cards", options=ids, min=0, max=len(ids), prompt="",
                        extra={"zone": "hand", "purpose": "bonus", "of": 0, "foe": "liz", "attacking": True, "per_card": 1, "margin": margin})
    return set(EffectAI(0, game.controllers[0])._bonus_discards(game, req))


def raphael_rage(titles, margin, foe="lobster", hp=3):
    """Raphael's Unbridled rage on Hellboy's side (2 points a card): the cards it gives up from a hand of `titles`."""
    from sparring.board import Board
    from test_raphael_effects import give, mk
    g = mk(Board.load("bprd-hq"), "hellboy")
    cards = [give(g, 0, t, nth=titles[:k].count(t)) for k, t in enumerate(titles)]      # a repeated title is another copy
    g.fighters[foe].hp = hp
    req = ChoiceRequest(player=0, kind="cards", options=[c.card_id for c in cards], min=0, max=len(cards), prompt="",
                        extra={"zone": "hand", "purpose": "bonus", "of": 0, "foe": foe, "attacking": True, "per_card": 2, "margin": margin})
    return EffectAI(0)._bonus_discards(g, req)


def test_rage_does_not_spend_the_last_defence_for_a_sidekick():
    """Two cards kill Lobster Johnson and are worth it by price, but they are the whole defence of the hand: the game is not won."""
    assert raphael_rage(("Sai", "Heroes in a half shell"), margin=0) == []


def test_rage_spends_one_of_two_equal_defenders():
    """Two Sai: giving one up still leaves a defender, so the price decides (one card kills Lobster)."""
    assert len(raphael_rage(("Sai", "Sai"), margin=1)) == 1


def test_rage_spends_the_last_defence_for_the_winning_blow():
    """Both cards turn the blow into Hellboy's defeat: the game is won, nothing is left to defend."""
    assert len(raphael_rage(("Sai", "Heroes in a half shell"), margin=0, foe="hellboy", hp=4)) == 2
