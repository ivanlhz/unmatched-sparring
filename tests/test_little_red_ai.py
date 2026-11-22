"""How the bot answers Little Red's wild basket (sparring/ai_little_red.py) and whole games with the search AI on both sides of the table.

The question is asked when a line with a symbol resolves while the basket is wild. The answers here are what each card needs: its one symbol, never a
rose for Large Hands with only the Basket in the pile (the rose line would replace the card's own return with nothing), and the best of the three lines
of Never Leave the Path by the board. The search plays the real engine, so its simulated turns and rollouts ask the same question (`SyntheticChooser`)."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_little_red, sim
from sparring.ai_effects import EffectAI
from sparring.effects.choose import ChoiceRequest, SyntheticChooser
from sparring.effects.plugins_little_red import SYMBOLS
from sparring.search.controller import make_bot_ai
from sparring.state import Game
from test_effects_combat import Asking, pair
from test_little_red_effects import FOE, SLUG, mk, pile

SYMBOL_OF = dict(zip(range(3), SYMBOLS))


def ask(game, title, player=0):
    """The request a wild basket makes while `title` resolves, answered by the bot's decision."""
    card = give(game, player, title)
    req = ChoiceRequest("effect", player, [0, 1, 2], 1, 1, card.card_id, "scheme/0:0", "choose the symbol the basket counts as",
                        {"tag": "basket", "labels": list(SYMBOLS), "symbols": list(SYMBOLS)}, player)
    return req, EffectAI(player).decide(game, req, nested=False)


@pytest.mark.parametrize("title,symbol", [("The Wolf's Skin", "wolf"), ("What a Terrible Big Mouth You Have", "wolf"), ("Once Upon a Time", "axe"),
                                          ("Stones in the Belly", "axe"), ("What Big Eyes You Have", "rose"), ("A Grimm Tale", "wolf")])
def test_a_card_with_one_symbol_line_gets_that_symbol(bprd, title, symbol):
    g = mk(bprd)
    _, answer = ask(g, title)
    assert SYMBOL_OF[answer[0]] == symbol


def test_large_hands_is_never_a_rose_with_only_the_basket_but_a_rose_with_a_card_to_bring_back(bprd):
    g = mk(bprd)
    assert SYMBOL_OF[ask(g, "What Large Hands You Have")[1][0]] != "rose"
    pile(g, "The Wolf's Skin", "What's That In My Basket?")
    assert SYMBOL_OF[ask(g, "What Large Hands You Have")[1][0]] == "rose"


def test_never_leave_the_path_hits_with_the_axe_when_a_weak_rival_stands_in_her_zone(bprd):
    g = mk(bprd)
    red, foe = pair(g, "red", FOE)
    foe.hp = 2
    assert SYMBOL_OF[ask(g, "Never Leave the Path")[1][0]] == "axe"


def test_never_leave_the_path_draws_with_nobody_in_the_zone_and_room_in_the_hand(bprd):
    g = mk(bprd)
    red, foe = pair(g, "red", FOE)
    foe.pos = max(s for s in g.board.spaces if not g.board.share_zone(red.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    assert SYMBOL_OF[ask(g, "Never Leave the Path")[1][0]] == "rose"


def test_never_leave_the_path_takes_the_action_when_the_hand_is_full_and_nobody_is_in_reach(bprd):
    g = mk(bprd)
    red, foe = pair(g, "red", FOE)
    foe.pos = max(s for s in g.board.spaces if not g.board.share_zone(red.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    for c in g.players[0].deck[:7]:
        g.players[0].hand.append(c)
    del g.players[0].deck[:7]
    assert SYMBOL_OF[ask(g, "Never Leave the Path")[1][0]] == "wolf"


def test_the_rollout_chooser_answers_with_the_same_symbol_as_the_bot(bprd):
    g = mk(bprd)
    req, answer = ask(g, "Once Upon a Time")
    for policy in ("greedy", "safe"):
        assert SyntheticChooser(policy=policy).choose(g, req) == answer


def test_the_discard_order_is_part_of_the_searchs_cache_key(bprd):
    """The same cards in another order are another position (the basket is the top one): the pure-loss cache of the adapter keys on the ids in order."""
    from sparring.search.adapter import EngineState
    a, b = mk(bprd), mk(bprd)
    pile(a, "The Wolf's Skin", "Once Upon a Time")
    pile(b, "Once Upon a Time", "The Wolf's Skin")
    card_a, card_b = give(a, 0, "Never Leave the Path"), give(b, 0, "Never Leave the Path")
    ka, kb = EngineState(a, 0)._pure_loss_key(0, card_a, None), EngineState(b, 0)._pure_loss_key(0, card_b, None)
    assert ka != kb


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_ismcts_plays_little_red_to_the_end_without_a_fallback(seed):
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": seed})
    out = sim.play(seed, bot_hero=SLUG, human_hero="hellboy", medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0


@pytest.mark.parametrize("seed", [1, 2])
def test_ismcts_as_the_opponent_of_little_red_never_falls_back(seed):
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_seed": seed})
    out = sim.play(seed, bot_hero="hellboy", human_hero=SLUG, medusa=ai, rival="chaser", max_turns=40)
    assert out.turns >= 3 and ai.fallbacks == 0


def test_the_heuristic_ai_plays_little_red_too():
    out = sim.play(1, bot_hero=SLUG, human_hero="hellboy", rival="chaser", max_turns=40)
    assert out.winner in ("Little Red", "Hellboy", "draw")
