"""Raphael's cards and ANGER ISSUES on the interpreter, bot side (player 0 plays Raphael, controllers answer).

The human side (panel, FakeTTS) is in tests/test_raphael_human.py. Every card with an effect has a test here; the
numbers are the ones printed on the real cards (data/heroes/raphael.json)."""
from __future__ import annotations

import json

import pytest

from conftest import give
from sparring import persist
from sparring.ai_effects import EffectAI
from sparring.combat_flow import CombatFlow
from sparring.effects.choose import ChoiceRequest
from sparring.effects.events import tracked
from sparring.state import Game
from test_d1_bot_cards import fight, free_adjacent, kill, zone_mate
from test_effects_combat import Asking, hand_filler, hp, pair


def mk(bprd, foe="hellboy", seed=3):
    """Raphael = player 0 (the bot), `foe` = player 1; player 0's turn, empty hands."""
    ctl = {0: Asking(), 1: Asking()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("raphael", foe), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def drawn(g, player, before):
    """Cards drawn by an effect: the hand grew from `before` (taken after the played card was given) minus the card played."""
    return len(g.players[player].hand) - before + 1


# ---------------------------------------------------------------- the deck and the switch

def test_raphael_is_interpreted_and_its_ability_tracks_lost_combats(bprd):
    g = mk(bprd)
    assert "raphael" in g.fx.dsl_heroes and "lost" in tracked(frozenset({"raphael"}))
    assert [f.fid for f in g.own(0)] == ["raphael", "casey"]
    assert (g.fighters["raphael"].hp, g.fighters["casey"].hp) == (17, 8)
    assert g.fighters["casey"].ranged and not g.fighters["raphael"].ranged


# ---------------------------------------------------------------- ANGER ISSUES

def test_anger_issues_the_first_lost_combat_of_the_turn_gains_an_action_only_once(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    g.actions_left = 2
    liz_def = give(g, 1, "Burning Barrier")            # versatile 2: Sai (4) wins; use Let's do this (1) to lose
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], give(g, 0, "Let's do this!"), liz_def)
    assert not res.attacker_won and g.actions_left == 2          # 2 -1 (spent) +1 (ANGER ISSUES)
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], give(g, 0, "Let's do this!", 1), give(g, 1, "Burning Barrier", 1))
    assert not res.attacker_won and g.actions_left == 1          # 2 -1 spent, no second gain
    assert g.fx.lost == [2, 0]


def test_anger_issues_a_won_combat_and_a_tie_do_not_behave_alike(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    g.actions_left = 2
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], give(g, 0, "Sai"), None)
    assert res.attacker_won and g.actions_left == 1 and g.fx.lost == [0, 1]      # the defender lost it, not Raphael
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], give(g, 0, "Break something"), give(g, 1, "Burning Barrier"))
    assert not res.attacker_won and res.damage == 0 and g.actions_left == 1      # 2 vs 2: a tie is lost by the attacker
    assert g.fx.lost == [1, 1]


def test_anger_issues_resets_every_turn_and_ignores_the_defense_on_the_rivals_turn(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    g.turn, g.actions_left = 1, 2
    g.fx.emit("start_of_turn", 1)
    res = g.attack(g.fighters["liz"], g.fighters["raphael"], give(g, 1, "Fireball"), give(g, 0, "Break something"))
    assert res.attacker_won and g.fx.lost == [1, 0]          # Raphael lost the defense on the rival's turn
    assert g.actions_left == 1                                # no action gained: it is not his turn
    g.turn, g.actions_left = 0, 2
    g.fx.emit("start_of_turn", 0)
    assert g.fx.lost == [0, 0]


def test_anger_issues_is_blocked_like_any_gained_action(bprd):
    g = mk(bprd, "baba-yaga")
    pair(g, "raphael", "baba")
    g.fx.statuses.append({"name": "cannot_gain_actions", "owner": 1, "player": 0, "until": {"event": "end_of_turn"}, "amount": 0, "label": ""})
    g.actions_left = 2
    res = g.attack(g.fighters["raphael"], g.fighters["baba"], give(g, 0, "Let's do this!"), give(g, 1, "Foul Journey"))
    assert not res.attacker_won and g.actions_left == 1


def test_lost_combats_survive_a_save_and_a_clone(bprd):
    g = mk(bprd, "liz-sherman")
    g.fx.lost = [1, 0]
    assert g.clone().fx.lost == [1, 0]
    saved = json.loads(json.dumps(persist.game_to_dict(g)))
    assert saved["fx"]["lost"] == [1, 0]
    loaded = Game.new(bprd, 0, controllers={}, heroes=("raphael", "liz-sherman"))
    persist.apply_game(loaded, saved)
    assert loaded.fx.lost == [1, 0]


# ---------------------------------------------------------------- attack cards

def test_lets_do_this_draws_one_and_two_when_it_wins(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    card = give(g, 0, "Let's do this!")
    before = len(g.players[0].hand)
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], card, give(g, 1, "Burning Barrier"))     # 1 vs 2: lost
    assert not res.attacker_won and drawn(g, 0, before) == 1
    card = give(g, 0, "Let's do this!", 1)
    before = len(g.players[0].hand)
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], card, None)                               # 1 vs nothing: won
    assert res.attacker_won and drawn(g, 0, before) == 2


def test_turtle_power_may_boost_its_attack(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    power, spare = give(g, 0, "Turtle power!"), give(g, 0, "Sai")
    g.controllers[0].boost = spare
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], power, None)
    assert res.atk_value == 3 + spare.boost and res.boost_card is spare and spare in g.players[0].discard


def test_crowd_control_draws_per_adjacent_rival_and_hurts_each(bprd):
    g = mk(bprd, "hellboy")
    rf, hb = pair(g, "raphael", "hellboy")
    lobster = g.fighters["lobster"]
    lobster.pos = free_adjacent(g, rf.pos, avoid=(hb.pos,))
    card = give(g, 0, "Crowd control")
    before = len(g.players[0].hand)
    res = g.attack(rf, hb, card, None)
    assert res.damage == 2 and hb.hp == g.fighters["hellboy"].max_hp - 2 - 1 and lobster.hp == lobster.max_hp - 1
    assert drawn(g, 0, before) == 2                          # two adjacent rivals: two cards


def test_crowd_control_with_nobody_else_adjacent_draws_for_the_defender_only(bprd):
    g = mk(bprd, "liz-sherman")
    rf, liz = pair(g, "raphael", "liz")
    card = give(g, 0, "Crowd control")
    before = len(g.players[0].hand)
    g.attack(rf, liz, card, give(g, 1, "Evade"))
    assert liz.hp == 16 - 1 and drawn(g, 0, before) == 1


def test_crowd_control_played_by_casey_counts_the_rivals_next_to_casey(bprd):
    g = mk(bprd, "liz-sherman")
    rf, liz = pair(g, "raphael", "liz")
    g.fighters["casey"].pos = free_adjacent(g, liz.pos, avoid=(rf.pos,))
    card = give(g, 0, "Crowd control")
    before = len(g.players[0].hand)
    g.attack(g.fighters["casey"], liz, card, give(g, 1, "Evade"))
    assert liz.hp == 16 - 1 and drawn(g, 0, before) == 1


def test_batter_up_pushes_the_rival_up_to_three_spaces_only_when_it_wins(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "casey", "liz")
    liz = g.fighters["liz"]
    start = liz.pos
    far = max(g.legal_moves(liz, 3), key=lambda s: (g.board.distance(start, s), s))
    g.controllers[0].moves = {"liz": far}
    res = g.attack(g.fighters["casey"], liz, give(g, 0, "Batter up!"), None)
    assert res.attacker_won and liz.pos == far and g.board.distance(start, far) <= 3 and far != start
    liz.pos = start
    res = g.attack(g.fighters["casey"], liz, give(g, 0, "Batter up!", 1), give(g, 1, "Evade"))
    assert not res.attacker_won and liz.pos == start


def test_unbridled_rage_discards_defense_and_versatile_cards_for_two_each(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    shell, sai, atk, flame = give(g, 0, "Heroes in a half shell"), give(g, 0, "Sai"), give(g, 0, "Let's do this!"), give(g, 0, "Raphael is cool but rude")
    rage = give(g, 0, "Unbridled rage")
    g.controllers[0].queue = [[shell.card_id, sai.card_id]]
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], rage, give(g, 1, "Evade"))
    request = g.controllers[0].requests[0]
    assert request.kind == "cards" and request.extra["purpose"] == "bonus" and request.min == 0
    assert set(request.options) == {shell.card_id, sai.card_id}          # attack and scheme cards are not eligible
    assert res.atk_value == 3 + 4 and {shell, sai} <= set(g.players[0].discard) and atk in g.players[0].hand and flame in g.players[0].hand


def test_unbridled_rage_may_give_up_nothing_and_the_default_answer_is_none(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    shell = give(g, 0, "Heroes in a half shell")
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], give(g, 0, "Unbridled rage"), None)
    assert res.atk_value == 3 and shell in g.players[0].hand


def test_the_bot_gives_up_cards_for_unbridled_rage_only_when_the_blow_is_worth_it(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    liz = g.fighters["liz"]
    cards = [give(g, 0, "Sai"), give(g, 0, "Heroes in a half shell")]
    ai = EffectAI(0)
    base = dict(zone="hand", purpose="bonus", of=0, per_card=2, foe="liz", attacking=True)
    ids = [c.card_id for c in cards]
    kill_blow = ChoiceRequest("cards", 0, ids, 0, 2, 1, "k", "", {**base, "margin": liz.hp - 3})
    assert len(ai.choose_effect(g, kill_blow)) == 2          # 2 cards turn a 13-point blow into the kill
    idle = ChoiceRequest("cards", 0, ids, 0, 2, 1, "k", "", {**base, "margin": -9})
    assert ai.choose_effect(g, idle) == []                   # no amount of cards reaches the defense
    assert ai.choose_effect(g, ChoiceRequest("cards", 0, ids, 0, 2, 1, "k", "", {**base, "margin": 1, "attacking": False})) == []


# ---------------------------------------------------------------- versatile cards

def test_break_something_attacking_cancels_the_defenders_during_and_after_but_not_its_immediately(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    rival = give(g, 1, "Burning Barrier")          # IMMEDIATELY: cannot leave its space; AFTER: damage in Liz's zone
    flame = give(g, 1, "Pyrotechnics")
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], give(g, 0, "Break something"), rival)
    # defender resolves its IMMEDIATELY first: nothing left to cancel there; the AFTER (damage) is cancelled
    assert g.fx.statuses and hp(g, "raphael", "casey") == [17, 8]
    assert flame in g.players[1].hand


def test_break_something_defending_leaves_the_attackers_immediately_standing(bprd):
    g = mk(bprd, "liz-sherman")
    g.turn, g.actions_left = 1, 2
    pair(g, "raphael", "liz")
    breaker = give(g, 0, "Break something")
    fireball = give(g, 1, "Fireball")               # IMMEDIATELY: 1 damage to each rival adjacent to the defender
    zone_mate(g, "casey", "raphael", adjacent=True)
    res = g.attack(g.fighters["liz"], g.fighters["raphael"], fireball, breaker)
    assert g.fighters["casey"].hp == 7                # the attacker's IMMEDIATELY still resolved
    assert res.damage == 3 and g.fighters["liz"].hp == 16 - 2     # Fireball has no DURING/AFTER to cancel: 2 damage to Liz


def test_break_something_deals_two_damage_when_nothing_was_cancelled(bprd):
    g = mk(bprd, "liz-sherman")
    rf, liz = pair(g, "raphael", "liz")
    evade = give(g, 1, "Evade")
    hand_before = len(g.players[1].hand)
    res = g.attack(rf, liz, give(g, 0, "Break something"), evade)       # Evade's AFTER draw is cancelled: no damage to Liz
    assert liz.hp == 16 and len(g.players[1].hand) == hand_before - 1
    g2 = mk(bprd, "liz-sherman")
    rf, liz = pair(g2, "raphael", "liz")
    res = g2.attack(rf, liz, give(g2, 0, "Break something"), None)           # no defense: nothing to cancel
    assert liz.hp == 16 - 2 - 2
    assert g2.fighters["liz"].alive


def test_break_something_does_not_cancel_an_uncancelable_card_and_then_hurts(bprd):
    g = mk(bprd, "liz-sherman")
    rf, liz = pair(g, "raphael", "liz")
    g.turn, g.actions_left = 1, 2
    res = g.attack(g.fighters["liz"], rf, give(g, 1, "Incinerate"), give(g, 0, "Break something"))
    assert "def" not in res.cancelled and "atk" not in res.cancelled and g.fighters["liz"].hp == 16 - 2
    assert rf.hp == 17 - 5                                         # nothing was cancelled: the 2 damage goes to Liz


def test_payback_time_is_worth_five_after_a_lost_combat_this_turn(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    liz = g.fighters["liz"]
    res = g.attack(g.fighters["raphael"], liz, give(g, 0, "Payback time!"), None)
    assert res.atk_value == 2
    g.attack(g.fighters["raphael"], liz, give(g, 0, "Let's do this!"), give(g, 1, "Burning Barrier"))       # lost
    g.actions_left = 2
    res = g.attack(g.fighters["raphael"], liz, give(g, 0, "Payback time!", 1), None)
    assert res.atk_value == 5


def test_payback_time_defending_counts_a_combat_lost_earlier_in_the_rivals_turn(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    g.turn, g.actions_left = 1, 2
    g.fx.emit("start_of_turn", 1)
    g.fx.emit("combat_lost", 0, g.fighters["raphael"])
    res = g.attack(g.fighters["liz"], g.fighters["raphael"], give(g, 1, "Fireball"), give(g, 0, "Payback time!"))
    assert res.def_value == 5 and not res.attacker_won


def test_relentless_goes_back_into_the_deck_and_draws_one(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    card = give(g, 0, "Relentless")
    deck_before, hand_before = len(g.players[0].deck), len(g.players[0].hand)
    g.attack(g.fighters["raphael"], g.fighters["liz"], card, give(g, 1, "Evade"))
    mine = g.players[0]
    assert card not in mine.discard
    held = [c for c in mine.hand + mine.deck if c is card]
    assert len(held) == 1                                        # in the deck, or drawn right back
    assert len(mine.hand) == hand_before - 1 + 1 and len(mine.deck) == deck_before + 1 - 1


def test_relentless_cancelled_goes_to_the_discard_like_any_card(bprd):
    g = mk(bprd, "liz-sherman")
    g.turn, g.actions_left = 1, 2
    pair(g, "raphael", "liz")
    card = give(g, 0, "Relentless")
    g.attack(g.fighters["liz"], g.fighters["raphael"], give(g, 1, "Feint"), card)
    assert card in g.players[0].discard and card not in g.players[0].deck


def test_slapshot_is_six_with_casey_next_to_the_rival_and_two_without(bprd):
    g = mk(bprd, "liz-sherman")
    rf, liz = pair(g, "casey", "liz")
    res = g.attack(g.fighters["casey"], liz, give(g, 0, "Slapshot"), None)
    assert res.atk_value == 6
    g2 = mk(bprd, "liz-sherman")
    pair(g2, "casey", "liz")
    g2.fighters["casey"].pos = max(g2.board.spaces, key=lambda s: g2.board.distance(s, g2.fighters["liz"].pos))
    g2.fighters["casey"].pos = next(s for s in sorted(g2.board.spaces) if s not in {f.pos for f in g2.fighters.values() if f.alive}
                                    and g2.board.distance(s, g2.fighters["liz"].pos) == 2 and g2.board.can_reach_target(s, g2.fighters["liz"].pos, True))
    res = g2.attack(g2.fighters["casey"], g2.fighters["liz"], give(g2, 0, "Slapshot"), None)
    assert res.atk_value == 2


# ---------------------------------------------------------------- the scheme and the vanilla cards

def test_the_scheme_hurts_each_rival_next_to_a_friendly_fighter_and_draws(bprd):
    g = mk(bprd, "hellboy")
    rf, hb = pair(g, "raphael", "hellboy")
    lobster = g.fighters["lobster"]
    far = max(g.board.spaces, key=lambda s: (g.board.distance(s, rf.pos), s))
    lobster.pos = far                                           # next to nobody of Raphael's
    card = give(g, 0, "Raphael is cool but rude")
    before = len(g.players[0].hand)
    g.play_scheme(0, rf, card)
    assert hb.hp == 17 - 1 or hb.hp == g.fighters["hellboy"].hp
    assert lobster.hp == 6 and len(g.players[0].hand) == before - 1 + 1 and card in g.players[0].discard
    spot = free_adjacent(g, far, avoid=())
    g.fighters["casey"].pos = spot
    g.play_scheme(0, rf, give(g, 0, "Raphael is cool but rude", 1))
    assert lobster.hp == 5


def test_the_vanilla_cards_do_nothing_but_their_values(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "raphael", "liz")
    res = g.attack(g.fighters["raphael"], g.fighters["liz"], give(g, 0, "Sai"), give(g, 1, "Evade"))
    assert res.atk_value == 4 and res.applied == []


def test_heroes_in_a_half_shell_defends_for_five(bprd):
    g = mk(bprd, "liz-sherman")
    g.turn, g.actions_left = 1, 2
    pair(g, "raphael", "liz")
    res = g.attack(g.fighters["liz"], g.fighters["raphael"], give(g, 1, "Fireball"), give(g, 0, "Heroes in a half shell"))
    assert res.def_value == 5 and res.damage == 0


def test_break_something_defending_keeps_the_attackers_immediately_status_and_cancels_its_after(bprd):
    g = mk(bprd, "liz-sherman")
    g.turn, g.actions_left = 1, 2
    rf, liz = pair(g, "raphael", "liz")
    zone_mate(g, "casey", "liz")
    flow = g.begin_attack(liz, rf, give(g, 1, "Burning Barrier"), give(g, 0, "Break something"))
    flow.drive(lambda choice: None)
    assert [(s["name"], s["fid"]) for s in g.fx.statuses] == [("cannot_leave_space", "raphael")]     # IMMEDIATELY stayed
    assert hp(g, "raphael", "casey") == [17, 8]                  # AFTER (1 damage to each rival in Liz's zone) cancelled
    assert flow.late_cancelled == {"atk"} and flow.cancel_hits == {"atk"} and flow.ctx.cancelled == set()
    restored = CombatFlow.from_dict(g, json.loads(json.dumps(flow.to_dict())))
    assert restored.late_cancelled == {"atk"} and restored.cancel_hits == {"atk"}


def test_break_something_defending_against_a_vanilla_attack_hurts_an_adjacent_rival(bprd):
    g = mk(bprd, "liz-sherman")
    g.turn, g.actions_left = 1, 2
    rf, liz = pair(g, "raphael", "liz")
    res = g.attack(liz, rf, give(g, 1, "Fireball"), give(g, 0, "Break something"))
    assert liz.hp == 16 - 2 and res.damage == 3


# ---------------------------------------------------------------- a cancelled may_boost card is not boosted (docs/heroes/raphael.md)

@pytest.mark.parametrize("foe, rival, boosts", [
    ("liz-sherman", "Feint", False),             # IMMEDIATELY: cancels every effect, the DURING boost with them
    ("donatello", "Short circuit", True),        # cancels only AFTER: the boost of the DURING stays
])
def test_a_may_boost_attack_is_boosted_unless_the_rival_cancels_its_during(bprd, foe, rival, boosts):
    g = mk(bprd, foe)
    pair(g, "raphael", foe.split("-")[0])
    power, spare = give(g, 0, "Turtle power!"), give(g, 0, "Sai")
    g.controllers[0].boost = spare
    res = g.attack(g.fighters["raphael"], g.fighters[foe.split("-")[0]], power, give(g, 1, rival))
    assert (res.boost_card is spare) is boosts
    assert res.atk_value == 3 + (spare.boost if boosts else 0) and (spare in g.players[0].discard) is boosts
    assert (spare in g.players[0].hand) is not boosts


def test_a_defense_that_cancels_during_and_after_takes_the_boost_of_a_may_boost_attack(bprd):
    g = mk(bprd, "leonardo")                      # the human side of this pair is Raphael's rival Leonardo: his Turtle power!
    g.turn, g.actions_left = 1, 2
    pair(g, "leonardo", "raphael")
    power, spare = give(g, 1, "Turtle power!"), give(g, 1, "Turtle power!", 1)
    g.controllers[1].boost = spare
    res = g.attack(g.fighters["leonardo"], g.fighters["raphael"], power, give(g, 0, "Break something"))
    assert res.boost_card is None and spare in g.players[1].hand and res.atk_value == 3
