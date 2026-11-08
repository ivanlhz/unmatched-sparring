"""docs/card-identity.md: Medusa and the four turtles share the CardIDs 17600-17629; an id means a card only with its owner."""
from __future__ import annotations

import itertools

import pytest

from sparring.combat import is_medusa_card
from sparring.effects.choose import ChoiceRequest
from sparring.effects.select import find_card
from sparring.heroes import load_hero
from sparring.state import Game

SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen"]


def test_the_five_decks_really_share_one_card_id_range():
    ranges = {slug: (min(c.card_id for c in load_hero(slug).deck()), max(c.card_id for c in load_hero(slug).deck()))
              for slug in SHARING}
    assert {slug: r for slug, r in ranges.items() if slug != "daredevil"} == {slug: (17600, 17629) for slug in SHARING if slug != "daredevil"}
    assert ranges["daredevil"] == (17600, 17621)      # 22 playing cards: his deck object holds 23 with the character card


@pytest.mark.parametrize("a,b", list(itertools.combinations(SHARING, 2)))
def test_no_card_of_one_deck_equals_a_card_of_another(a, b):
    """Comparing a Card by value (==, in) is what tells the decks apart where the id cannot."""
    assert not set(load_hero(a).deck()) & set(load_hero(b).deck())


@pytest.mark.parametrize("bot,human", [("medusa", "leonardo"), ("raphael", "donatello"), ("michelangelo", "medusa")])
def test_a_card_id_is_resolved_against_its_owner(bprd, bot, human):
    g = Game.new(bprd, 1, controllers={}, heroes=(bot, human), bot_player=0)
    for card in g.players[0].full_set:
        assert g.card_of(card.card_id, 0) is card or g.card_of(card.card_id, 0) == card
        mine = g.card_of(card.card_id, 1)
        assert mine in g.players[1].full_set and mine.card_id == card.card_id and mine != card
        assert find_card(g, card.card_id, 0) == card and find_card(g, card.card_id, 1) == mine
    assert all(g.cards_by_id(0)[c.card_id] == c for c in g.players[0].full_set)
    assert all(g.cards_by_id(1)[c.card_id] == c for c in g.players[1].full_set)


def test_is_medusa_card_is_only_true_for_medusas_own_cards(bprd):
    for slug in SHARING:
        verdicts = {is_medusa_card(c) for c in load_hero(slug).deck()}
        assert verdicts == {slug == "medusa"}, slug


def test_a_choice_request_carries_the_owner_of_its_card_through_a_save():
    req = ChoiceRequest("optional", 1, [True, False], 1, 1, 17605, "k", "", {}, 0)
    assert ChoiceRequest.from_dict(req.to_dict()).card_owner == 0
    plain = ChoiceRequest("optional", 1, [True, False], 1, 1, 17605, "k", "", {})
    assert "card_owner" not in plain.to_dict() and ChoiceRequest.from_dict(plain.to_dict()).card_owner is None
