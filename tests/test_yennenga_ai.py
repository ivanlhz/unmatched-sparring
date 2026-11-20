"""What the AI makes of Yennenga (sparring/ai_yennenga.py and its hooks in `EffectAI`, `SyntheticChooser`): how much of the damage meant
for her the bot hands the Archers, the bot returning an Archer with Surprise Volley, and the bot playing her with the heuristic and with
the search (`make_bot_ai({"ai": "ismcts"})`)."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_yennenga
from sparring.ai_medusa import MedusaAI
from sparring.effects.choose import ChoiceRequest, SyntheticChooser
from test_effects_combat import pair
from test_yennenga_effects import archers, beside, foe_attack, mk, stack, volley_scene


def request(g, left, assign="archer1", later=("archer2",), player=0):
    return ChoiceRequest("amount", player, list(range(min(left, int(g.fighters[assign].hp)) + 1)), 1, 1, None, "k", "damage",
                         {"assign": assign, "fighter": "yennenga", "left": left, "damage": left, "source": "combat", "later": list(later)})


def scene(bprd, hp, rival_cards=5):
    """Yennenga with the given life and both Archers beside her, a rival hero next to her holding `rival_cards`."""
    g = mk(bprd, turn=1)
    g.controllers[0] = MedusaAI(0)
    yen = stack(g)
    beside(g, "hellboy", "yennenga")
    yen.hp = hp
    g.players[1].hand.extend(g.players[1].deck[:rival_cards])
    return g, yen


def landed(bprd, hp, blow, rival_cards=5):
    g, yen = scene(bprd, hp, rival_cards)
    atk = foe_attack(g)
    g.attack(g.fighters["hellboy"], yen, atk, None, values=(blow - atk.value, 0))
    return g, yen


@pytest.mark.parametrize("hp,blow", [(3, 3), (3, 4), (3, 5), (1, 1), (1, 3), (6, 8), (2, 5)])
def test_the_bot_never_lets_the_archers_fall_to_keep_her_up_when_it_cannot_but_keeps_her_alive_when_it_can(bprd, hp, blow):
    g, yen = landed(bprd, hp, blow)
    capacity = sum(int(a.max_hp) for a in archers(g))
    if blow - capacity < hp:                              # they can soak enough: she lives
        assert yen.alive and g.winner is None
    else:                                                 # nothing saves her
        assert not yen.alive


@pytest.mark.parametrize("hp,blow", [(15, 3), (15, 7), (8, 5), (3, 5)])
def test_no_archer_ever_takes_more_than_its_life_and_nothing_is_lost_or_invented(bprd, hp, blow):
    g, yen = landed(bprd, hp, blow)
    taken = (hp - max(0, yen.hp)) + sum(2 - max(0, a.hp) for a in archers(g))
    assert taken == blow and all(a.hp >= 0 for a in archers(g))


def test_with_the_rival_out_of_reach_and_her_life_high_the_archers_spare_themselves_the_blows_that_would_kill_them(bprd):
    g, yen = landed(bprd, 15, 3, rival_cards=0)
    assert yen.alive and all(a.alive for a in archers(g))


def test_the_two_questions_of_one_blow_agree_with_one_split(bprd):
    g, yen = scene(bprd, 6)
    ai = g.controllers[0].effect_ai()
    first = ai.choose_effect(g, request(g, 7))[0]
    second = ai.choose_effect(g, request(g, 7 - first, assign="archer2", later=()))[0]
    best = [ai_yennenga.archer_share(g, request(g, 7), ai.medusa(0)) for _ in range(2)]
    assert best[0] == best[1] == first and 0 <= first + second <= 4


def test_a_rollout_answers_with_the_same_hit_point_weights_and_without_the_risk_of_the_next_turn(bprd):
    g, yen = scene(bprd, 3)
    answer = SyntheticChooser(policy="greedy").choose(g, request(g, 5))
    assert answer == [ai_yennenga.archer_share(g, request(g, 5))] and answer[0] >= 1       # 5 on 3 life: she needs the Archers


def test_the_default_answer_assigns_nothing_without_an_opinion(bprd):
    from sparring.effects.choose import TableChooser, default_answer
    g, yen = scene(bprd, 3)
    assert default_answer(request(g, 5)) == [0] and TableChooser().choose(g, request(g, 5)) == [0]


def test_the_bot_returns_a_defeated_archer_with_surprise_volley(bprd):
    g, yen, hellboy = volley_scene(bprd)
    g.controllers[0] = MedusaAI(0)
    res = g.attack(yen, hellboy, give(g, 0, "Surprise Volley"), None)
    assert g.fighters["archer1"].alive and res.attacker == "archer1"


@pytest.mark.parametrize("foe", ["hellboy", "bigfoot", "medusa", "houdini", "luke-cage"])
def test_the_search_bot_plays_yennenga_to_the_end_without_falling_back(foe):
    from sparring import sim
    ai = sim.make_bot("ismcts", iterations=20, seed=1)
    out = sim.play(1, bot_hero="yennenga", human_hero=foe, medusa=ai, max_turns=40)
    assert out.turns >= 1 and ai.fallbacks == 0 and out.winner != "draw"


@pytest.mark.parametrize("foe", ["hellboy", "bigfoot"])
def test_the_heuristic_bot_plays_yennenga_to_the_end(foe):
    from sparring import sim
    assert sim.play(2, bot_hero="yennenga", human_hero=foe).winner != "draw"
