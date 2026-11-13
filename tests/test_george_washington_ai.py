"""The AI's side of George Washington (sparring/ai_washington.py): the values that move (Make A Stand, Network Of Spies, Circumvent), the two
decisions of ESPIONAGE (a ruse token on the bot's attack; discarding a card to take one off the human's) and the whole thing run by the
heuristic bot and by the search (`make_bot_ai({"ai": "ismcts"})`, the bot that plays live)."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import ai_washington as aw
from sparring import sim
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import MedusaAI
from sparring.effects.choose import ChoiceRequest
from sparring.search.controller import make_bot_ai
from test_effects_combat import pair, put_adjacent
from test_george_washington_effects import mk, open_pair, ruse, stock
from test_bigfoot_effects import start_turn


def ai_game(bprd, foe="hellboy", turn=0):
    """Washington (player 0) with the heuristic bot's controller; the rival is the scripted one of the other tests."""
    g = mk(bprd, foe, turn=turn)
    g.controllers[0] = MedusaAI(0)
    return g


def use_request(g, att_fid, tgt_fid, title):
    card = give(g, 0, title)
    return card, ChoiceRequest("optional", 0, [True, False], 1, 1, None, "espionage/0:0", "use a ruse token on this attack?",
                               {"washington": "use", "attack_card": card.card_id, "attacker": att_fid, "target": tgt_fid}, 0)


def remove_request(g, tgt_fid, player=1):
    return ChoiceRequest("optional", player, [True, False], 1, 1, None, "espionage_remove/0:0", "discard 1 random card to remove the ruse token?",
                         {"washington": "remove", "attacker": "washington", "target": tgt_fid}, 0)


# ---------------------------------------------------------------- what the cards are worth

def test_make_a_stand_is_a_five_only_for_a_fighter_that_has_not_moved(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    start_turn(g)
    card = give(g, 0, "Make A Stand")
    assert aw.own_value(g, w, card) == 5.0
    w.pos = next(s for s in sorted(g.board.adj[w.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    assert aw.own_value(g, w, card) is None
    assert MedusaAI(0).card_value(g, w, h, card) == 3.0


def test_make_a_stand_of_another_hero_with_the_same_title_is_never_valued_here(bprd):
    g = mk(bprd)
    h = g.fighters["hellboy"]
    start_turn(g)
    assert aw.own_value(g, h, give(g, 0, "Make A Stand")) is None


def test_network_of_spies_is_worth_two_plus_the_friends_in_washingtons_zone(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    card = give(g, 0, "Network Of Spies")
    assert aw.own_value(g, w, card) == 2.0
    put_adjacent(g, "spy1", "washington")
    put_adjacent(g, "spy2", "washington")
    assert aw.own_value(g, w, card) == 4.0
    assert MedusaAI(0).card_value(g, w, h, card) == 4.0


def test_circumvent_ignores_the_defense_only_while_a_token_can_go_on_it(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    card = give(g, 0, "Circumvent")
    assert MedusaAI.ignores_defense(g, w, h, card)
    g.fx.set_counter(0, "ruse_tokens", 0)
    assert not MedusaAI.ignores_defense(g, w, h, card)
    g.fx.set_counter(0, "ruse_tokens", 2)
    g.fx.set_counter(0, "ruse", 1)
    assert not MedusaAI.ignores_defense(g, w, h, card)


def test_a_ruse_attack_is_worth_more_than_the_same_card_without_a_token_in_the_supply(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    ai = MedusaAI(0)
    from sparring.ai_medusa import Model
    model = Model(g, 0)
    card = give(g, 0, "Agent 711")
    with_tokens = ai.attack_eval(g, model, w, h, card)[0]
    g.fx.set_counter(0, "ruse_tokens", 0)
    without = ai.attack_eval(g, model, w, h, card)[0]
    assert with_tokens > without + 1.0


def test_misinformation_is_worth_a_little_more_when_the_supply_is_not_full(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    ai = MedusaAI(0)
    from sparring.ai_medusa import Model
    model = Model(g, 0)
    card = give(g, 0, "Misinformation")
    full = ai.attack_eval(g, model, w, h, card)[0]
    g.fx.set_counter(0, "ruse_tokens", 2)
    assert ai.attack_eval(g, model, w, h, card)[0] > full


# ---------------------------------------------------------------- the bot puts a token on its attack

@pytest.mark.parametrize("title,expected", [("Agent 711", True), ("Circumvent", True), ("Sabotage", True)])
def test_the_bot_puts_a_token_on_the_cards_that_pay_for_it(bprd, title, expected):
    g = ai_game(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    card, req = use_request(g, "washington", "hellboy", title)
    assert aw.use_ruse(EffectAI(0, g.controllers[0]), g, req) is expected


def test_allies_everywhere_gets_a_token_only_when_washington_has_hit_points_to_heal(bprd):
    g = ai_game(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    card, req = use_request(g, "washington", "hellboy", "Allies Everywhere")
    ai = EffectAI(0, g.controllers[0])
    assert aw.use_ruse(ai, g, req) is False
    w.hp = 8
    assert aw.use_ruse(ai, g, req) is True


def test_the_last_token_is_kept_for_a_card_that_is_not_worth_it(bprd):
    g = ai_game(bprd)
    w, h = pair(g, "washington", "hellboy")
    g.fx.set_counter(0, "ruse_tokens", 1)
    stock(g, 1)
    card, req = use_request(g, "washington", "hellboy", "Sabotage")          # the rival holds one card: Sabotage can only take it
    assert aw.use_ruse(EffectAI(0, g.controllers[0]), g, req) is False


def test_no_token_in_the_supply_means_no(bprd):
    g = ai_game(bprd)
    w, h = pair(g, "washington", "hellboy")
    g.fx.set_counter(0, "ruse_tokens", 0)
    card, req = use_request(g, "washington", "hellboy", "Agent 711")
    assert aw.use_ruse(EffectAI(0, g.controllers[0]), g, req) is False


def test_a_token_is_dearer_the_fewer_are_left(bprd):
    g = mk(bprd)
    prices = []
    for left in (4, 3, 2, 1):
        g.fx.set_counter(0, "ruse_tokens", left)
        prices.append(aw.price(g, 0))
    assert prices == sorted(prices) and prices[0] < prices[-1]


def test_the_search_bot_asks_nothing_the_heuristic_does_not_answer_the_controller_gets_the_decision(bprd):
    g = ai_game(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    g.controllers[1].queue = [[False]]
    g.attack(w, h, give(g, 0, "Agent 711"), None)
    assert ruse(g) == (3, 0) and h.hp == h.max_hp - 4 - 7


# ---------------------------------------------------------------- the bot decides whether to discard a card to remove the human's token

def defender(bprd, hp=18, hand=4, played=()):
    """Washington (human, player 1... here player 0 for the engine's sake) attacks the bot: the bot is player 1 with MedusaAI."""
    g = mk(bprd)
    g.controllers[1] = MedusaAI(1)
    w, h = pair(g, "washington", "hellboy")
    h.hp = hp
    stock(g, hand)
    for title in played:                                    # ruse cards Washington already played: public, in his discard pile
        c = next(c for c in g.players[0].full_set if c.title == title and c not in g.players[0].discard)
        g.players[0].deck.remove(c) if c in g.players[0].deck else None
        g.players[0].discard.append(c)
    return g, h


def test_the_bot_discards_a_card_when_the_unseen_attack_may_cost_it_more(bprd):
    g, h = defender(bprd, hp=7)
    assert aw.remove_ruse(EffectAI(1, g.controllers[1]), g, remove_request(g, "hellboy")) is True       # Agent 711 would finish a hero at 7


def test_the_bot_keeps_its_last_card(bprd):
    g, h = defender(bprd, hp=7, hand=1)
    assert aw.remove_ruse(EffectAI(1, g.controllers[1]), g, remove_request(g, "hellboy")) is False


def test_the_bot_knows_nothing_of_the_card_only_of_what_is_left_of_the_ruse_cards(bprd):
    g, h = defender(bprd, hp=18, played=["Agent 711", "Agent 711", "Circumvent", "Circumvent", "Sabotage", "Sabotage"])
    assert aw.remove_ruse(EffectAI(1, g.controllers[1]), g, remove_request(g, "hellboy")) is False     # only Allies Everywhere can still carry a token


def test_the_bot_pays_a_card_when_its_hero_is_in_the_kill_range_and_not_at_full_health_or_for_a_sidekick(bprd):
    ai_for = lambda g: EffectAI(1, g.controllers[1])
    for hp, expected in ((18, False), (14, False), (9, True), (7, True)):
        g, h = defender(bprd, hp=hp)
        assert aw.remove_ruse(ai_for(g), g, remove_request(g, "hellboy")) is expected, hp
    g, h = defender(bprd, hp=7)
    assert aw.remove_ruse(ai_for(g), g, remove_request(g, "lobster")) is False             # a sidekick dies to the blow itself: the 7 adds nothing


def test_the_decision_never_reads_the_attack_card(bprd):
    """The request the bot gets as a defender names the attacker and the target, not the card: the card cannot be used."""
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    g.attack(w, h, give(g, 0, "Agent 711"), None)
    removal = g.controllers[1].requests[0]
    assert removal.extra == {"washington": "remove", "attacker": "washington", "target": "hellboy"} and removal.card_id is None


def test_through_the_controller_the_heuristic_bot_answers_the_question(bprd):
    g, h = defender(bprd, hp=7)
    answer = g.controllers[1].choose_effect(g, remove_request(g, "hellboy"))
    assert answer == [True]


# ---------------------------------------------------------------- the bot as Washington, whole games

def test_the_heuristic_bot_plays_washington_and_spends_ruse_tokens(bprd):
    spent = []
    original = aw.use_ruse
    aw.use_ruse = lambda ai, game, req: spent.append(original(ai, game, req)) or spent[-1]
    try:
        out = sim.play(2, bot_hero="george-washington", human_hero="hellboy")
    finally:
        aw.use_ruse = original
    assert out.winner != "draw" and spent and any(spent)


def test_the_search_bot_plays_washington_and_spends_ruse_tokens():
    """`make_bot_ai({"ai": "ismcts"})` is the bot that plays live: the search plans the attack, the heuristic EffectAI answers the token."""
    spent = []
    original = aw.use_ruse
    aw.use_ruse = lambda ai, game, req: spent.append(original(ai, game, req)) or spent[-1]
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 12, "ai_seed": 1})
    try:
        out = sim.play(3, bot_hero="george-washington", human_hero="hellboy", medusa=ai, max_turns=20)
    finally:
        aw.use_ruse = original
    assert out.turns >= 1 and ai.fallbacks == 0 and spent


def test_the_search_bot_plays_against_washington_without_a_fallback():
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 12, "ai_seed": 2})
    out = sim.play(4, bot_hero="hellboy", human_hero="george-washington", medusa=ai, max_turns=15)
    assert out.turns >= 1 and ai.fallbacks == 0


# ---------------------------------------------------------------- Undercover Agent: when the bot swaps a Spy in

def undercover(bprd, hp):
    """Hellboy attacks the bot's Washington (hit points `hp`) with a 4; a Spy stands next to him and the bot defends with Undercover Agent."""
    g = mk(bprd, turn=1)
    g.controllers[0] = MedusaAI(0)
    w, h = pair(g, "washington", "hellboy")
    put_adjacent(g, "spy1", "washington")
    g.actions_left = 2
    w.hp = hp
    attack = next(c for c in g.players[1].full_set if c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    g.players[1].hand.append(attack)
    flow = g.begin_attack(h, w, attack, give(g, 0, "Undercover Agent"))
    flow.run()
    return g, flow, w


def test_the_bot_swaps_a_spy_in_when_the_blow_would_kill_washington(bprd):
    g, flow, w = undercover(bprd, hp=3)
    assert flow.tgt.fid == "spy1" and w.hp == 3 and not g.fighters["spy1"].alive


def test_the_bot_keeps_the_spy_out_of_a_blow_washington_can_take(bprd):
    g, flow, w = undercover(bprd, hp=14)
    assert flow.tgt is w and g.fighters["spy1"].alive and w.hp == 14 - 3


# ---------------------------------------------------------------- the small pieces the review pinned

def test_the_default_answers_never_remove_a_token_and_a_rollout_spends_one():
    from sparring.effects.choose import SyntheticChooser, default_answer
    req = ChoiceRequest("optional", 1, [True, False], 1, 1, None, "k", "", {"washington": "remove"}, 0)
    assert default_answer(req) == [False]
    assert default_answer(ChoiceRequest("optional", 0, [True, False], 1, 1, None, "k", "", {"washington": "use"}, 0)) == [True]
    for policy in ("greedy", "safe"):
        chooser = SyntheticChooser(policy=policy)
        assert chooser.choose(None, req) == [False]
        assert chooser.choose(None, ChoiceRequest("optional", 0, [True, False], 1, 1, None, "k", "", {"washington": "use"}, 0)) == [True]


def test_make_a_stand_defending_is_a_five_for_the_bots_defense_evaluation(bprd):
    from sparring.ai_medusa import Model
    g = mk(bprd, turn=1)
    ai = MedusaAI(0)
    w, h = pair(g, "washington", "hellboy")
    start_turn(g)
    card = give(g, 0, "Make A Stand")
    model = Model(g, 0)
    dist = [(1.0, 5)]
    still = ai.eval_defense(g, model, dist, w, card)
    w.pos = next(s for s in sorted(g.board.adj[w.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    moved = ai.eval_defense(g, model, dist, w, card)
    assert still > moved                          # a 5 against a 5 blocks it; the printed 3 does not


def test_misinformation_defending_is_worth_more_with_a_token_to_regain(bprd):
    from sparring.ai_medusa import Model
    g = mk(bprd, turn=1)
    ai = MedusaAI(0)
    w, h = pair(g, "washington", "hellboy")
    card = give(g, 0, "Misinformation")
    model, dist = Model(g, 0), [(1.0, 1)]
    ai._attacker = h
    g.fx.set_counter(0, "ruse_tokens", 4)
    full = ai.eval_defense(g, model, dist, w, card)
    g.fx.set_counter(0, "ruse_tokens", 1)
    assert ai.eval_defense(g, model, dist, w, card) > full


def test_only_a_spy_next_to_washington_can_take_his_place(bprd):
    g = mk(bprd, turn=1)
    g.controllers[0] = MedusaAI(0)
    w, h = pair(g, "washington", "hellboy")                                       # the Spies are far away
    g.actions_left = 2
    w.hp = 3
    attack = next(c for c in g.players[1].full_set if c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    g.players[1].hand.append(attack)
    flow = g.begin_attack(h, w, attack, give(g, 0, "Undercover Agent"))
    flow.run()
    assert flow.tgt is w and w.hp == 0 or not w.alive                            # the blow kills him: no Spy was close enough to swap


def test_the_clear_script_and_the_caps_know_the_ruse_copies_and_a_big_roster():
    from sparring import player_setup
    from sparring.tts import lua
    assert lua.MAX_CLEAR_HEROES >= 80 and lua.MAX_CLEAR_GUIDS >= 1500 and lua.MAX_CLEAR_NAMES >= 500
    assert "'ruse'" in player_setup.clear_script({}) or '"ruse"' in player_setup.clear_script({})
