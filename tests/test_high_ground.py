"""Directional attack bonuses of a board (stairs / high ground): a fighter on A hitting one on B gets +value."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import Scripted, give, place
from sparring.ai_medusa import MedusaAI
from sparring.board import Board
from sparring.combat_flow import CombatFlow
from sparring.state import Game

ROOT = Path(__file__).resolve().parents[1]


def duel(bonuses):
    """Medusa on 0, Hellboy on 1 (adjacent), on bprd-hq with the given (from, to) -> value bonuses."""
    board = Board.load("bprd-hq")
    board.bonuses = dict(bonuses)
    g = Game.new(board, seed=3, controllers={0: Scripted(), 1: Scripted()})
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    place(g, medusa=0, hellboy=1, harpy1=20, harpy2=21, harpy3=22, lobster=27)
    return g, g.fighters["medusa"], g.fighters["hellboy"]


def attack_value(g, att, tgt, title="Feint"):
    flow = CombatFlow(g, att, tgt, give(g, att.owner, title), None)
    flow.run()
    return flow.result.atk_value, flow.result.atk_parts


def test_board_lookup_is_directional(tmp_path):
    board = Board.load("bprd-hq")
    board.bonuses = {(0, 1): 1}
    assert board.attack_bonus(0, 1) == 1 and board.attack_bonus(1, 0) == 0 and board.attack_bonus(0, None) == 0


def test_the_attacker_on_the_high_ground_gets_the_bonus_and_says_so():
    g, med, hb = duel({})
    base, _ = attack_value(g, med, hb)
    g, med, hb = duel({(0, 1): 2})
    value, parts = attack_value(g, med, hb)
    assert value == base + 2 and any("+2" in p for p in parts)


def hellboy_hits_medusa(bonuses):
    g, med, hb = duel(bonuses)
    return attack_value(g, hb, med, next(c.title for c in g.players[1].full_set if c.can_attack))[0]


def test_the_bonus_is_only_for_the_attacker_in_that_direction():
    assert attack_value(*duel({(1, 0): 1}))[0] == attack_value(*duel({}))[0]     # Medusa attacks, the stairs are Hellboy's
    assert hellboy_hits_medusa({(0, 1): 1}) == hellboy_hits_medusa({})            # and the other way round
    assert hellboy_hits_medusa({(1, 0): 1}) == hellboy_hits_medusa({}) + 1


def test_a_defender_on_the_high_ground_does_not_defend_better():
    g, med, hb = duel({(1, 0): 1})                 # Hellboy has the stairs over Medusa, but Medusa is the one attacking
    flow = CombatFlow(g, med, hb, give(g, 0, "Feint"), None)
    flow.run()
    g0, med0, hb0 = duel({})
    flow0 = CombatFlow(g0, med0, hb0, give(g0, 0, "Feint"), None)
    flow0.run()
    assert (flow.result.atk_value, flow.result.def_value) == (flow0.result.atk_value, flow0.result.def_value)


def test_without_bonuses_the_game_bonus_is_unchanged():
    g, med, hb = duel({})
    assert g.attack_bonus(med, hb) == g.attack_bonus(med)
    g, med, hb = duel({(0, 1): 1})
    assert g.attack_bonus(med, hb) == g.attack_bonus(med) + 1 and g.attack_bonus(hb, med) == g.attack_bonus(hb)


def test_the_bot_sees_the_high_ground_when_it_weighs_an_attack():
    from sparring.ai_medusa import Model
    ai = MedusaAI(0)
    g, med, hb = duel({})
    flat = ai.attack_outcome(g, Model(g, 0), med, hb, give(g, 0, "Feint"))
    g, med, hb = duel({(0, 1): 3})
    high = ai.attack_outcome(g, Model(g, 0), med, hb, give(g, 0, "Feint"))
    assert high[1] > flat[1]                    # more expected damage with the stairs


def test_hanging_gardens_stairs_are_adjacent_spaces_of_the_map():
    raw = json.loads((ROOT / "data" / "maps" / "hanging-gardens.json").read_text(encoding="utf-8"))
    board = Board.load("hanging-gardens")
    assert {(b["from"], b["to"]) for b in raw["bonuses"]} == {(27, 26), (28, 26), (22, 21)}
    assert all(board.adjacent(a, b) for a, b in board.bonuses)
    assert board.attack_bonus(27, 26) == 1 and board.attack_bonus(26, 27) == 0
