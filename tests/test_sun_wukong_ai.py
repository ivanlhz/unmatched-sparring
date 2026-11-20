"""How the bot answers Sun Wukong's CLONES ("take 1 damage to summon a Clone", sparring/ai_wukong.py): never below a floor of hit points, never when the
hit point raises the chance of dying in the rival's next turn, and otherwise when the Clone is worth more than the hit point; and whole games
with the search AI, where the bot uses the ability without ever killing itself with it.

The generic answer to an optional is yes, so before the hook the bot paid with 1 hit point left (tests/test_sun_wukong_effects.py declines it by hand)."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_wukong, sim
from sparring.ai_effects import EffectAI
from sparring.effects.choose import ChoiceRequest
from sparring.search.controller import make_bot_ai
from test_sun_wukong_effects import CLONES, free_next_to, land, mk


def ask(g, ai=None):
    """What the bot answers when the interpreter asks CLONES at the start of its turn."""
    req = ChoiceRequest("optional", 0, [True, False], key="clone_summon/0:0", prompt="do it?", card_owner=0)
    return (ai or EffectAI(0)).decide(g, req, nested=False)


def far_from_the_rival(g):
    far = sorted((s for s in g.board.spaces if not g.board.share_zone(g.fighters["wukong"].pos, s)), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.owner == 1 and f.alive], far):
        f.pos = s


def test_the_bot_pays_the_hit_point_for_a_clone_when_it_is_healthy_and_safe(bprd):
    g = mk(bprd)
    far_from_the_rival(g)
    assert ask(g) == [True]


@pytest.mark.parametrize("hp", [1, 2, 3, 4, 5])
def test_the_bot_never_leaves_himself_under_the_floor(bprd, hp):
    g = mk(bprd)
    far_from_the_rival(g)
    g.fighters["wukong"].hp = hp
    assert ask(g) == [False]


def test_the_floor_is_the_edge_of_what_it_pays(bprd):
    g = mk(bprd)
    far_from_the_rival(g)
    g.fighters["wukong"].hp = ai_wukong.FLOOR + 1                 # leaves FLOOR: still allowed
    assert ask(g) == [True]
    g.fighters["wukong"].hp = ai_wukong.FLOOR                     # would leave FLOOR - 1
    assert ask(g) == [False]


def risk_curve(monkeypatch, curve):
    """The chance of dying next turn the bot reads for a hero with `hp` hit points (MedusaAI.death_risk), as a function."""
    from sparring.ai_medusa import MedusaAI
    monkeypatch.setattr(MedusaAI, "death_risk", lambda self, game, model, t, hp: curve(hp))


def test_the_bot_does_not_pay_when_the_hit_point_makes_dying_next_turn_likely(bprd, monkeypatch):
    g = mk(bprd)
    far_from_the_rival(g)
    g.fighters["wukong"].hp = 12
    risk_curve(monkeypatch, lambda hp: 0.5 if hp <= 11 else 0.0)       # 12 is safe, 11 is a coin flip
    assert ask(g) == [False]


def test_the_bot_does_not_pay_when_the_risk_is_already_survival_level_after_the_hit_point(bprd, monkeypatch):
    g = mk(bprd)
    far_from_the_rival(g)
    g.fighters["wukong"].hp = 12
    risk_curve(monkeypatch, lambda hp: 0.25)                           # flat: the hit point adds nothing, but it is already SURVIVAL_P
    assert ask(g) == [False]


def test_the_bot_pays_when_the_hit_point_barely_moves_the_risk_and_prices_what_it_does(bprd, monkeypatch):
    g = mk(bprd)
    far_from_the_rival(g)
    g.fighters["wukong"].hp = 12
    risk_curve(monkeypatch, lambda hp: 0.005 if hp <= 11 else 0.0)
    assert ask(g) == [True]


def test_a_clone_is_worth_less_each_time(bprd):
    g = mk(bprd)
    worth = [ai_wukong.clone_worth(g, 0)]
    for fid in CLONES[:2]:
        land(g, fid, free_next_to(g, "wukong"))
        worth.append(ai_wukong.clone_worth(g, 0))
    assert worth[0] > worth[1] > worth[2] > 0


def test_the_cards_in_hand_that_count_the_clones_raise_the_worth(bprd):
    g = mk(bprd)
    base = ai_wukong.clone_worth(g, 0)
    give(g, 0, "Infinite Strikes")
    assert ai_wukong.clone_worth(g, 0) == pytest.approx(base + ai_wukong.STRIKES_BONUS)
    g.fighters["wukong"].hp = 10
    before = ai_wukong.clone_worth(g, 0)
    give(g, 0, "Phoenix Form")
    assert ai_wukong.clone_worth(g, 0) > before                      # hurt: each Clone heals a hit point
    g.fighters["wukong"].hp = g.fighters["wukong"].max_hp
    full = ai_wukong.clone_worth(g, 0)
    assert full < ai_wukong.clone_worth(g, 0) + 1 and ai_wukong.clone_worth(g, 0) == full


def test_nothing_is_paid_with_three_clones_out(bprd):
    g = mk(bprd)
    for fid in CLONES:
        land(g, fid, free_next_to(g, "wukong"))
    assert ask(g) == [False]


# ---------------------------------------------------------------- whole games with the search AI

def paid_hit_points(monkeypatch):
    """Every time the bot says yes to CLONES, the hit points Wukong had."""
    paid = []
    orig = ai_wukong.summon_pays

    def spy(ai, game, req):
        hp = game.hero(req.player).hp
        out = orig(ai, game, req)
        if out:
            paid.append(hp)
        return out
    monkeypatch.setattr(ai_wukong, "summon_pays", spy)
    return paid


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ismcts_uses_the_ability_in_a_game_and_never_below_the_floor(monkeypatch, seed):
    paid = paid_hit_points(monkeypatch)
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": seed})
    out = sim.play(seed, bot_hero="sun-wukong", human_hero="hellboy", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0
    assert all(hp > ai_wukong.FLOOR for hp in paid), paid


def test_the_heuristic_ai_uses_it_too_in_a_game(monkeypatch):
    paid = paid_hit_points(monkeypatch)
    out = sim.play(1, bot_hero="sun-wukong", human_hero="hellboy", rival="chaser", max_turns=40)
    assert out.winner in ("Sun Wukong", "Hellboy", "draw")
    assert paid and all(hp > ai_wukong.FLOOR for hp in paid), paid
