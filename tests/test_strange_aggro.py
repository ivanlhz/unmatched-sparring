"""F-STRANGE-AGGRO: the bot's Doctor Strange fears the rival's reply less (EvalWeights.caution 0.3), so under ISMCTS he
attacks where the default weights maneuvered or played a scheme. Other heroes keep the default weights."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.board import Board
from sparring.search import adapter
from sparring.search.adapter import EvalWeights, hero_weights
from sparring.search.controller import make_bot_ai
from sparring.state import Game

MANOR = "baskerville-manor"
# (hand, (Strange, Wong, Hellboy)): with caution 1.0 the search mostly maneuvers or plays a scheme, with the profile it attacks in most seeds
POSITIONS = [
    (["Feint", "Master of Kamar-Taj", "Bolts of Balthakk", "Seven Suns of Cinnibus", "Steadfast Disciple"], (14, 29, 18)),
    (["Feint", "The Mists of Munnopor", "The Winds of Watoomb", "The Winds of Watoomb", "Bolts of Balthakk"], (25, 10, 14)),
    (["Bolts of Balthakk", "Steadfast Disciple", "The Rings of Raggadorr", "No, Really, I'm a Doctor", "Seven Suns of Cinnibus"], (22, 31, 15)),
    (["Bolts of Balthakk", "Cloak of Levitation", "Master of Kamar-Taj", "The Winds of Watoomb", "Eye of Agamotto"], (26, 9, 12)),
]


def kinds(hand, pos, seeds=(0, 1, 2)):
    out = []
    for seed in seeds:
        ai = make_bot_ai({"ai": "ismcts", "ai_time_budget": 60, "ai_iterations": 200, "ai_seed": seed}, 0)
        g = Game.new(Board.load(MANOR), 5, controllers={0: ai}, heroes=("doctor-strange", "hellboy"), bot_player=0)
        g.turn, g.turn_no = 0, 3
        g.begin_turn()
        st = g.players[0]
        st.deck.extend(st.hand)
        st.hand.clear()
        for i, title in enumerate(hand):
            give(g, 0, title, nth=hand[:i].count(title))
        for fid, space in zip(("strange", "wong", "hellboy"), pos):
            g.fighters[fid].pos = space
        g.actions_left = 2
        out.append(ai.plan(g).kind)
        assert ai.fallbacks == 0
    return out


def test_only_doctor_strange_has_a_profile():
    assert hero_weights(EvalWeights(), "doctor-strange").caution == 0.3
    for slug in ("medusa", "hellboy", "sinbad", "houdini"):
        assert hero_weights(EvalWeights(), slug) == EvalWeights()


def test_the_configuration_wins_over_the_profile():
    assert hero_weights(EvalWeights(caution=0.8), "doctor-strange").caution == 0.8


def test_the_lethal_risk_is_not_scaled_and_wong_weight_stays_zero():
    assert EvalWeights().beside == 0.0
    assert "lethal" not in adapter.HERO_EVAL["doctor-strange"]


@pytest.mark.parametrize("hand,pos", POSITIONS)
def test_strange_attacks_where_the_default_weights_did_not(hand, pos, monkeypatch):
    new = kinds(hand, pos).count("attack")
    monkeypatch.setattr(adapter, "HERO_EVAL", {})
    old = kinds(hand, pos).count("attack")
    assert new >= 2 and new > old, (new, old)
