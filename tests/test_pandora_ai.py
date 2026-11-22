"""How the bot answers Pandora's Box ("keep revealing?", sparring/ai_pandora.py): free while no feather is out, a gamble priced by the Miseries still in
the Box once feathers are, never into a lethal stop, and informed by HOPE; and whole games with the search AI and the heuristic.

The generic answer to an optional is yes, which would walk into three feathers every turn (the effects tests answer by hand)."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_pandora, sim
from sparring.ai_effects import EffectAI
from sparring.effects import plugins_pandora as box
from sparring.effects.choose import ChoiceRequest
from sparring.search.controller import make_bot_ai
from test_pandora_effects import IDX, KAKO, free_next_to, mk


def ask(g, revealed, top=None, ai=None):
    """What the bot answers when the interpreter asks to keep revealing, with `revealed` (Misery indexes) out and `top` seen by HOPE."""
    left = [i for i in range(7) if i not in revealed]
    req = ChoiceRequest("optional", 0, [True, False], key="pandora_box/0:0", prompt="", card_owner=0,
                        extra={"box": "open", "unrevealed": left, "top": top})
    return (ai or EffectAI(0)).decide(g, req, nested=False)[0]


def far_from_the_rival(g):
    far = sorted((s for s in g.board.spaces if not g.board.share_zone(g.fighters["pandora"].pos, s)), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.owner == 1 and f.alive], far):
        f.pos = s


@pytest.mark.parametrize("hp", [14, 6, 2, 1])
def test_with_no_feather_out_one_more_reveal_cannot_cost_anything_so_it_is_free(bprd, hp):
    g = mk(bprd)
    far_from_the_rival(g)
    g.fighters["pandora"].hp = hp
    for first in (IDX["Woe"], IDX["Hope"], IDX["Confusion"]):          # the three feather-free Miseries
        assert ask(g, [first]) is True


def test_after_misfortune_the_next_reveal_is_a_gamble_the_bot_does_not_take(bprd):
    g = mk(bprd)
    far_from_the_rival(g)
    assert ask(g, [IDX["Misfortune"]]) is False


def test_hope_makes_a_safe_top_card_worth_taking_and_a_dangerous_one_not(bprd):
    g = mk(bprd)
    far_from_the_rival(g)
    two = [IDX["Misfortune"]]
    for safe in (IDX["Woe"], IDX["Hope"], IDX["Confusion"]):
        assert ask(g, two, top=safe) is True, box.NAMES[safe]
    for feather in (IDX["Toil"], IDX["Pain"], IDX["Greed"]):          # one feather more is the third: it must stop and pay 2
        assert ask(g, two, top=feather) is False, box.NAMES[feather]


@pytest.mark.parametrize("hp", [2, 3])
def test_it_never_reveals_into_a_stop_that_would_kill_it(bprd, hp):
    g = mk(bprd)
    far_from_the_rival(g)
    g.fighters["pandora"].hp = hp
    assert ask(g, [IDX["Misfortune"], IDX["Hope"]], top=IDX["Toil"]) is False      # 2 + 1 feathers: three revealed, 3 damage


def test_the_hit_points_are_dearer_the_lower_she_is(bprd):
    g = mk(bprd)
    far_from_the_rival(g)
    ai, risks = EffectAI(0), {}
    healthy = ai_pandora.stop_cost(ai, g, 0, 2, risks)
    g.fighters["pandora"].hp = 6
    assert ai_pandora.stop_cost(ai, g, 0, 2, {}) > healthy
    assert ai_pandora.stop_cost(ai, g, 0, 6, {}) == ai_pandora.DEATH


def test_woe_is_worth_a_body_only_while_a_kakodaemon_can_come(bprd):
    g = mk(bprd)
    assert ai_pandora.misery_worth(g, 0, IDX["Woe"]) > 0
    for fid in KAKO:
        f = g.fighters[fid]
        f.alive, f.hp, f.pos = True, 1, free_next_to(g, "pandora", exclude=[x.pos for x in g.fighters.values() if x.alive])
    assert ai_pandora.misery_worth(g, 0, IDX["Woe"]) == 0


def test_pain_is_worth_one_per_rival_next_to_her_and_toil_one_per_attack_in_hand(bprd):
    g = mk(bprd)
    far_from_the_rival(g)
    assert ai_pandora.misery_worth(g, 0, IDX["Pain"]) == 0
    g.fighters["hellboy"].pos = free_next_to(g, "pandora")
    assert ai_pandora.misery_worth(g, 0, IDX["Pain"]) == 1
    assert ai_pandora.misery_worth(g, 0, IDX["Toil"]) == 0
    give(g, 0, "Hindsight")
    assert ai_pandora.misery_worth(g, 0, IDX["Toil"]) == ai_pandora.TOIL_PER_ATTACK


def test_greed_is_worth_less_with_a_full_hand(bprd):
    g = mk(bprd)
    empty = ai_pandora.misery_worth(g, 0, IDX["Greed"])
    for c in list(g.players[0].deck)[:7]:
        g.players[0].deck.remove(c)
        g.players[0].hand.append(c)
    assert 0 < ai_pandora.misery_worth(g, 0, IDX["Greed"]) < empty


# ---------------------------------------------------------------- whole games

def spy_on_the_box(monkeypatch):
    """(hit points, feathers out, answer) of every "keep revealing?" the bot answers."""
    seen = []
    orig = ai_pandora.keep_revealing

    def spy(ai, game, req):
        out = orig(ai, game, req)
        left = req.extra["unrevealed"]
        seen.append((game.hero(req.player).hp, box.feathers(sum(1 << i for i in range(7) if i not in left)), out))
        return out
    monkeypatch.setattr(ai_pandora, "keep_revealing", spy)
    return seen


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ismcts_plays_the_box_in_a_game_and_never_walks_into_its_own_death(monkeypatch, seed):
    seen = spy_on_the_box(monkeypatch)
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": seed})
    out = sim.play(seed, bot_hero="pandora", human_hero="hellboy", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0 and seen
    assert not any(answer and hp <= 2 and feathers >= 1 for hp, feathers, answer in seen), seen


def test_the_heuristic_ai_plays_the_box_too(monkeypatch):
    seen = spy_on_the_box(monkeypatch)
    out = sim.play(1, bot_hero="pandora", human_hero="hellboy", rival="chaser", max_turns=40)
    assert out.winner in ("Pandora", "Hellboy", "draw") and seen
    assert not any(answer and hp <= 2 and feathers >= 1 for hp, feathers, answer in seen), seen


@pytest.mark.parametrize("seed", [1, 2])
def test_the_search_plays_against_a_human_pandora_without_seeing_her_box(seed):
    """The bot (Hellboy) searches while the rival is Pandora: her Box in the simulations draws its Miseries at random when they are revealed."""
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 30, "ai_seed": seed})
    out = sim.play(seed, bot_hero="hellboy", human_hero="pandora", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0
