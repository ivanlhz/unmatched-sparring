"""The AIs and the DOUBLE ATTACK: the data are read (`ai_double`), the heuristic adds the second part to the expected damage of an
attack and defends the second part against its exact value, the search plays it in its rollouts (the same engine) and the decision
journal records it. Stub card: Hellboy's Horseshoes And Hand Grenades (attack 2), whose AFTER is a second attack."""
from __future__ import annotations

import json

import pytest

from conftest import give
from sparring import ai_double, decision_log
from sparring.ai_medusa import Act, MedusaAI, Model
from sparring.effects.model import load_effects
from sparring.search.adapter import EngineState, Knowledge
from sparring.search.controller import make_bot_ai
from sparring.state import Game
from test_effects_combat import pair

TITLE = "Horseshoes And Hand Grenades"
PLAIN = [{"op": "second_attack", "amount": 3}]
CONDITIONAL = [{"op": "if", "condition": {"test": "card", "card": "opponent_card", "filter": {}},
                "then": [{"op": "second_attack", "amount": 4}]}]
COMPUTED = [{"op": "second_attack", "amount": {"attr": "value", "of": "opponent_card"}}]


def stub(monkeypatch, ops):
    monkeypatch.setitem(load_effects("hellboy").card(TITLE).moments, "after", ops)


def duel(bprd, ai0=None):
    """The bot (Hellboy, player 0) and Bigfoot (player 1), adjacent, the bot's turn, empty hands."""
    g = Game.new(bprd, 3, controllers={0: ai0 or MedusaAI(0), 1: MedusaAI(1)}, heroes=("hellboy", "bigfoot"), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    hellboy, bigfoot = pair(g, "hellboy", "bigfoot")
    return g, hellboy, bigfoot


# ---------------------------------------------------------------- the data

@pytest.mark.parametrize("ops,none,two,four", [(PLAIN, 3, 3, 3), (CONDITIONAL, 0, 4, 4), (COMPUTED, 0, 2, 4)],
                         ids=["plain", "if the rival defended", "printed value of the rival's card"])
def test_the_second_value_reads_the_three_shapes_of_the_box(bprd, monkeypatch, ops, none, two, four):
    stub(monkeypatch, ops)
    g, hellboy, bigfoot = duel(bprd)
    card = give(g, 0, TITLE)
    assert ai_double.has_second(g, 0, card)
    assert [ai_double.second_value(g, 0, card, dv) for dv in (None, 2, 4)] == [none, two, four]


def test_an_ordinary_card_has_no_second_part(bprd):
    g, hellboy, bigfoot = duel(bprd)
    card = give(g, 0, TITLE)
    assert not ai_double.has_second(g, 0, card) and ai_double.journal_note(g, 0, Act("attack", fid="hellboy", target="bigfoot", card=card)) == {}


# ---------------------------------------------------------------- the heuristic attacks

def test_the_expected_damage_of_an_attack_counts_both_parts(bprd, monkeypatch):
    g, hellboy, bigfoot = duel(bprd)
    card = give(g, 0, TITLE)
    ai = MedusaAI(0)
    single = ai.attack_outcome(g, Model(g, 0), hellboy, bigfoot, card)
    stub(monkeypatch, PLAIN)
    double = ai.attack_outcome(g, Model(g, 0), hellboy, bigfoot, card)
    assert double[1] > single[1] and double[0] > single[0], "more damage, so worth more"
    assert double[1] - single[1] <= 3, "at most the second part's 3"


def test_a_double_attack_can_kill_where_its_first_part_cannot(bprd, monkeypatch):
    g, hellboy, bigfoot = duel(bprd)
    card = give(g, 0, TITLE)
    bigfoot.hp = 4
    ai = MedusaAI(0)
    before = ai.attack_outcome(g, Model(g, 0), hellboy, bigfoot, card)[2]
    stub(monkeypatch, PLAIN)
    assert ai.attack_outcome(g, Model(g, 0), hellboy, bigfoot, card)[2] > before


# ---------------------------------------------------------------- the heuristic defends

def test_the_heuristic_defends_the_second_part_with_a_card_that_blocks_it(bprd, monkeypatch):
    stub(monkeypatch, PLAIN)
    g, hellboy, bigfoot = duel(bprd)
    g.players[1].hand.clear()
    block = give(g, 1, "It's Just Your Imagination")          # defense 3: the whole second part
    attack = give(g, 0, TITLE)
    ai = MedusaAI(1)
    assert ai.choose_second_defense(g, hellboy, bigfoot, 3, attack) is block


def test_the_heuristic_keeps_its_card_when_the_second_part_is_too_small_to_pay_for_it(bprd, monkeypatch):
    stub(monkeypatch, PLAIN)
    g, hellboy, bigfoot = duel(bprd)
    g.players[1].hand.clear()
    give(g, 1, "It's Just Your Imagination")
    attack = give(g, 0, TITLE)
    assert MedusaAI(1).choose_second_defense(g, hellboy, bigfoot, 0, attack) is None


def test_the_second_defense_decision_is_in_the_journal(bprd, monkeypatch, tmp_path):
    stub(monkeypatch, PLAIN)
    g, hellboy, bigfoot = duel(bprd)
    g.players[1].hand.clear()
    give(g, 1, "It's Just Your Imagination")
    attack = give(g, 0, TITLE)
    ai = MedusaAI(1)
    ai.journal = decision_log.DecisionJournal(tmp_path / "decisions.jsonl")
    ai.choose_second_defense(g, hellboy, bigfoot, 3, attack)
    lines = [json.loads(x) for x in (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
    defense = next(x for x in lines if x.get("kind") == "defense")
    assert defense["chosen"]["second_attack"] == 3 and defense["chosen"]["card"] == "It's Just Your Imagination"


# ---------------------------------------------------------------- the search

def test_the_searchs_rollouts_value_a_double_attack_above_the_same_card_without_its_second_part(bprd, monkeypatch):
    def worth(with_second: bool) -> float:
        if with_second:
            stub(monkeypatch, PLAIN)
        g, hellboy, bigfoot = duel(bprd)
        give(g, 0, TITLE)
        state = EngineState(g, observer=0, knowledge=Knowledge.from_game(g, 0))
        state.apply(("attack", "hellboy", "bigfoot"))
        if state.phase == "attack_card":          # a single card to choose resolves itself
            state.apply(("attack_card", "hellboy", TITLE))
        if state.pending is not None:             # the rival has no card to choose from: the defense resolves itself too
            state.apply(("defend", None))
        return state.evaluate(0)
    plain = worth(False)
    monkeypatch.undo()
    assert worth(True) > plain


def test_the_live_ismcts_defends_the_second_part_and_says_so_in_the_journal(bprd, monkeypatch, tmp_path):
    stub(monkeypatch, PLAIN)
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 30, "ai_time_budget": 1.0}, bot=1)
    g, hellboy, bigfoot = duel(bprd, ai0=MedusaAI(0))
    g.controllers[1] = ai
    g.players[1].hand.clear()
    block = give(g, 1, "It's Just Your Imagination")
    attack = give(g, 0, TITLE)
    ai.journal = decision_log.DecisionJournal(tmp_path / "decisions.jsonl")
    assert ai.choose_second_defense(g, hellboy, bigfoot, 3, attack) is block
    defense = next(json.loads(x) for x in (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").splitlines()
                   if json.loads(x).get("kind") == "defense")
    assert defense["chosen"]["second_attack"] == 3 and "second-attack" in defense["via"]


def test_a_rollout_defender_spends_a_card_only_when_it_spares_damage(bprd, monkeypatch):
    stub(monkeypatch, PLAIN)
    g, hellboy, bigfoot = duel(bprd)
    g.players[1].hand.clear()
    block = give(g, 1, "It's Just Your Imagination")
    attack = give(g, 0, TITLE)
    state = EngineState(g, observer=0, knowledge=Knowledge.from_game(g, 0))
    sim = state.game
    att, tgt = sim.fighters["hellboy"], sim.fighters["bigfoot"]
    controller = sim.controllers[1]
    hand_card = next(c for c in sim.players[1].hand if c.title == block.title)
    assert controller.choose_second_defense(sim, att, tgt, 3, attack) is hand_card
    assert controller.choose_second_defense(sim, att, tgt, 0, attack) is None


def test_the_second_bonus_is_the_engines_one_without_the_next_attack_bonus(bprd):
    from sparring.effects import modifiers
    g, hellboy, bigfoot = duel(bprd)
    before = ai_double.second_bonus(g, hellboy, bigfoot)
    modifiers.add_status(g.fx, "next_attack_bonus", owner=0, until={"event": "end_of_turn"}, player=0, amount=2, label="test")
    assert ai_double.second_bonus(g, hellboy, bigfoot) == before, "the first part used the 'next attack' bonus"
    modifiers.add_status(g.fx, "attack_bonus", owner=0, until={"event": "end_of_turn"}, fid="hellboy", amount=1, label="nunchaku")
    assert ai_double.second_bonus(g, hellboy, bigfoot) == before + 1, "a bonus to every attack of the fighter stays"
