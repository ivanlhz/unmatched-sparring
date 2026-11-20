"""The DOUBLE ATTACK op in the effects DSL (docs/effects-dsl.md section 45): shape and validator rules."""
import copy

from tests.test_effects_schema import broken, card, load_hero_raw

ATTACK = "Snipe"           # a Medusa attack card, used as the stub double-attack card


def _stub(moment, ops):
    def mutate(doc):
        c = card(doc, ATTACK)
        c["effects"][moment] = ops
    return mutate


def test_the_shapes_of_the_four_cards_of_the_box_validate():
    plain = [{"op": "second_attack", "amount": 3}]
    conditional = [{"op": "if", "condition": {"test": "card", "card": "opponent_card", "filter": {}},
                    "then": [{"op": "second_attack", "amount": 4}]}]
    computed = [{"op": "second_attack", "amount": {"attr": "value", "of": "opponent_card"}}]
    for ops in (plain, conditional, computed):
        assert broken("medusa", _stub("after", copy.deepcopy(ops))) == []


def test_second_attack_is_only_an_after_effect():
    for moment in ("immediately", "during"):
        errs = broken("medusa", _stub(moment, [{"op": "second_attack", "amount": 3}]))
        assert len(errs) == 1 and "only goes in 'after'" in errs[0]


def test_second_attack_needs_an_amount_and_a_card_that_attacks():
    assert any("amount" in e for e in broken("medusa", _stub("after", [{"op": "second_attack"}])))
    defense = next(c["title"] for c in load_hero_raw("medusa")["deck"]["cards"] if c["type"] == "defense")
    def mutate(doc):
        card(doc, defense)["effects"]["after"] = [{"op": "second_attack", "amount": 3}]
    assert any("needs a card that can attack" in e for e in broken("medusa", mutate))
