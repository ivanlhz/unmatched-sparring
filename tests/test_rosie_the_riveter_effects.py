"""Rosie the Riveter on the engine, bot side (player 0 plays her, the controllers answer): the row of four upgrades (activate, deactivate and
the order that rotates, the start-of-turn activation, the reset at the end of the turn), what each upgrade does (Merlin Engine's extra space,
Cavity Magnetron's draw, Sedgley Fist Gun's +1, Whizbang's ranged hero), and every card with the numbers printed on it. The human side (panel,
FakeTTS) is in tests/test_rosie_the_riveter_human.py and the full games in tests/test_rosie_the_riveter_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import persist, upgrades
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import MedusaAI
from sparring.state import Game, RuleError
from test_bigfoot_effects import Answers, empty_spaces, start_turn, wall
from test_effects_combat import pair, put_adjacent

SLUG = "rosie-the-riveter"
ROW = ["merlin_engine", "cavity_magnetron", "sedgley_fist_gun", "whizbang"]


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Rosie = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=(SLUG, foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    g.fx.counters = [{}, {}]                  # the start of her turn already activated one upgrade (tested on its own): start from none
    upgrades.sync(g)
    for p in g.players:
        p.hand.clear()
    return g


def counters(g, player=0):
    return g.fx.counter_value(player, "upgrades"), g.fx.counter_value(player, "upgrade_shift")


def ids(items):
    return [u["id"] for u in items]


def to_discard(g, player, *titles):
    out = []
    for title in titles:
        st = g.players[player]
        c = next(c for c in st.full_set if c.title == title and c not in st.discard)
        for zone in (st.deck, st.hand):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)
        out.append(c)
    return out


def far_from(g, fid, steps):
    f = g.fighters[fid]
    return next(s for s in empty_spaces(g, f.pos, steps) if g.board.distance(f.pos, s) == steps)


def apart_in_a_zone(g):
    """Two spaces that share a zone without being adjacent: a ranged hero reaches across them, a melee hero does not."""
    for a in sorted(g.board.spaces):
        for b in sorted(g.board.spaces):
            if a != b and g.board.share_zone(a, b) and b not in g.board.adj[a]:
                return a, b
    raise AssertionError("no two non-adjacent spaces share a zone")


# ---------------------------------------------------------------- the hero

def test_rosie_is_a_melee_hero_with_wendy_and_two_upgrade_counters_at_zero(bprd):
    g = mk(bprd)
    rosie, wendy = g.fighters["rosie"], g.fighters["wendy"]
    assert (rosie.hp, rosie.move, rosie.ranged, rosie.name, rosie.hero) == (15, 2, False, "Rosie The Riveter", True)
    assert (wendy.hp, wendy.move, wendy.ranged, wendy.name, wendy.hero) == (7, 2, False, "Wendy The Welder", False)
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert SLUG in g.fx.dsl_heroes and counters(g) == (0, 0)
    assert upgrades.has(g, 0) and not upgrades.has(g, 1) and upgrades.count(g, 1) == 0 and upgrades.row(g, 1) == []


# ---------------------------------------------------------------- the row: activate, deactivate, rotate

def test_the_upgrades_start_in_order_one_to_four_all_inactive(bprd):
    g = mk(bprd)
    assert ids(upgrades.row(g, 0)) == ROW and upgrades.active(g, 0) == []
    assert ids(upgrades.inactive(g, 0)) == ROW and not any(upgrades.is_active(g, 0, u) for u in ROW)


def test_activating_flips_the_leftmost_inactive_upgrade_and_stops_at_four(bprd):
    g = mk(bprd)
    for n, name in enumerate(ROW, start=1):
        assert ids(upgrades.activate(g, 0)) == [name]
        assert ids(upgrades.active(g, 0)) == ROW[:n] and counters(g) == (n, 0)
    assert upgrades.activate(g, 0) == [] and counters(g) == (4, 0)


def test_deactivating_flips_the_leftmost_active_upgrade_and_sends_it_to_the_end_of_the_row(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 2)                                    # merlin, cavity
    assert upgrades.deactivate(g, 0)["id"] == "merlin_engine"
    assert ids([upgrades.row(g, 0)[-1]]) == ["merlin_engine"]
    assert ids(upgrades.row(g, 0)) == ["cavity_magnetron", "sedgley_fist_gun", "whizbang", "merlin_engine"]
    assert ids(upgrades.active(g, 0)) == ["cavity_magnetron"] and counters(g) == (1, 1)
    upgrades.activate(g, 0)                                       # the next one to flip is the one that was behind it
    assert ids(upgrades.active(g, 0)) == ["cavity_magnetron", "sedgley_fist_gun"]


def test_deactivating_with_none_active_changes_nothing(bprd):
    g = mk(bprd)
    assert upgrades.deactivate(g, 0) is None and counters(g) == (0, 0) and ids(upgrades.row(g, 0)) == ROW


def test_deactivating_all_four_one_by_one_brings_the_row_back_to_its_order(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 4)
    for _ in range(4):
        upgrades.deactivate(g, 0)
    assert counters(g) == (0, 0) and ids(upgrades.row(g, 0)) == ROW


def test_the_upgrades_are_the_players_own_not_the_rivals(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 3)
    assert upgrades.count(g, 1) == 0 and g.fx.counter_value(1, "upgrades") == 0


# ---------------------------------------------------------------- the ability: start and end of the turn

def test_a_game_that_begins_on_her_turn_activates_the_first_upgrade(bprd):
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=(SLUG, "hellboy"), bot_player=0)
    g.turn, g.turn_no = 0, 1
    assert counters(g) == (0, 0)
    g.begin_turn()
    assert ids(upgrades.active(g, 0)) == ["merlin_engine"]


def test_at_the_start_of_her_turn_the_next_upgrade_is_activated(bprd):
    g = mk(bprd)
    g.fx.emit("start_of_turn", 0)
    assert ids(upgrades.active(g, 0)) == ["merlin_engine"]
    g.fx.emit("start_of_turn", 0)
    assert ids(upgrades.active(g, 0)) == ["merlin_engine", "cavity_magnetron"]


def test_the_rivals_start_of_turn_activates_nothing(bprd):
    g = mk(bprd)
    g.fx.emit("start_of_turn", 1)
    assert counters(g) == (0, 0)


def test_with_all_four_active_the_start_of_turn_has_nothing_left_to_activate(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 4)
    g.fx.emit("start_of_turn", 0)
    assert counters(g) == (4, 0)


def test_at_the_end_of_her_turn_with_all_four_active_all_are_deactivated_and_the_row_keeps_its_order(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 2)
    upgrades.deactivate(g, 0)                                     # shift 1, one active
    upgrades.activate(g, 0, 3)
    assert counters(g) == (4, 1)
    order = ids(upgrades.row(g, 0))
    g.end_turn()
    assert counters(g) == (0, 1) and ids(upgrades.row(g, 0)) == order and g.turn == 1


@pytest.mark.parametrize("n", [0, 1, 2, 3])
def test_at_the_end_of_her_turn_with_fewer_than_four_active_nothing_is_deactivated(bprd, n):
    g = mk(bprd)
    upgrades.activate(g, 0, n)
    g.end_turn()
    assert counters(g) == (n, 0)


def test_the_rivals_end_of_turn_does_not_reset_her_upgrades(bprd):
    g = mk(bprd, turn=1)
    upgrades.activate(g, 0, 4)
    g.end_turn()
    assert counters(g) == (4, 0)


# ---------------------------------------------------------------- the upgrades' effects

def test_sedgley_fist_gun_adds_one_to_rosies_attacks_but_not_wendys(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 3)                                    # merlin, cavity, sedgley
    rosie, hellboy = pair(g, "rosie", "hellboy")
    assert upgrades.attack_bonus_parts(g, rosie) == [(1, "SEDGLEY FIST GUN")] and upgrades.attack_bonus_parts(g, g.fighters["wendy"]) == []
    res = g.attack(rosie, hellboy, give(g, 0, "Technological Superiority"), None)
    assert res.atk_value == 3 + 1 and hellboy.hp == hellboy.max_hp - 4 and "SEDGLEY FIST GUN (+1)" in res.atk_parts
    g2 = mk(bprd)
    upgrades.activate(g2, 0, 3)
    wendy, hellboy = pair(g2, "wendy", "hellboy")
    assert g2.attack(wendy, hellboy, give(g2, 0, "Technological Superiority"), None).atk_value == 3


def test_sedgley_fist_gun_is_for_attacks_not_for_a_defense(bprd):
    g = mk(bprd, "leonardo", turn=1)
    upgrades.activate(g, 0, 3)
    rosie, leo = pair(g, "rosie", "leonardo")
    g.actions_left = 2
    res = g.attack(leo, rosie, give(g, 1, "Katana"), give(g, 0, "Technological Superiority"))
    assert res.def_value == 3


def test_sedgley_fist_gun_still_counts_when_the_effects_of_her_card_are_cancelled(bprd):
    g = mk(bprd, "sinbad")
    upgrades.activate(g, 0, 3)
    rosie, sinbad = pair(g, "rosie", "sinbad")
    res = g.attack(rosie, sinbad, give(g, 0, "Technological Superiority"), give(g, 1, "Feint"))        # Feint: cancel all effects on the opponent's card
    assert res.atk_value == 3 + 1


def test_without_sedgley_active_rosies_attack_is_the_printed_value(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 2)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    assert g.attack(rosie, hellboy, give(g, 0, "Technological Superiority"), None).atk_value == 3


def test_sedgley_fist_gun_follows_the_row_when_an_upgrade_is_deactivated(bprd):
    g = mk(bprd)
    rosie = g.fighters["rosie"]
    upgrades.activate(g, 0, 3)
    upgrades.deactivate(g, 0)                                     # row: cavity, sedgley, whizbang, merlin; two active
    assert ids(upgrades.active(g, 0)) == ["cavity_magnetron", "sedgley_fist_gun"] and upgrades.attack_bonus_parts(g, rosie) == [(1, "SEDGLEY FIST GUN")]
    upgrades.deactivate(g, 0)                                     # row: sedgley, whizbang, merlin, cavity; one active
    assert ids(upgrades.active(g, 0)) == ["sedgley_fist_gun"] and upgrades.attack_bonus_parts(g, rosie) == [(1, "SEDGLEY FIST GUN")]
    upgrades.deactivate(g, 0)
    assert upgrades.attack_bonus_parts(g, rosie) == []


def test_whizbang_makes_rosie_but_not_wendy_a_ranged_hero_while_it_is_active(bprd):
    g = mk(bprd)
    rosie, wendy, hellboy = g.fighters["rosie"], g.fighters["wendy"], g.hero(1)
    a, b = apart_in_a_zone(g)
    for f in g.fighters.values():
        if f.alive:
            f.pos = max(g.board.spaces) if f.owner == 1 or f is wendy else f.pos
    rosie.pos, hellboy.pos = a, b
    assert not g.can_attack(rosie, hellboy)
    upgrades.activate(g, 0, 3)
    assert not rosie.ranged and not g.can_attack(rosie, hellboy)          # the third upgrade is the Sedgley Fist Gun
    upgrades.activate(g, 0)
    assert rosie.ranged and not wendy.ranged and g.can_attack(rosie, hellboy)


def test_whizbang_stays_active_through_the_rotations_that_keep_it_in_the_first_places_of_the_row(bprd):
    g = mk(bprd)
    rosie = g.fighters["rosie"]
    upgrades.activate(g, 0, 4)
    seen = []
    for _ in range(4):
        upgrades.deactivate(g, 0)
        seen.append((upgrades.count(g, 0), rosie.ranged))
    assert seen == [(3, True), (2, True), (1, True), (0, False)]          # whizbang walks to the front of the row and is flipped last


def test_a_saved_game_comes_back_with_whizbang_still_making_her_ranged(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 4)
    g2 = mk(bprd)
    persist.apply_game(g2, persist.game_to_dict(g))
    assert counters(g2) == (4, 0) and g2.fighters["rosie"].ranged and not g2.fighters["wendy"].ranged
    assert g2.clone().fighters["rosie"].ranged


def test_a_clone_keeps_the_upgrades_and_changes_them_apart_from_the_game(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 4)
    c = g.clone()
    upgrades.deactivate(c, 0)
    upgrades.deactivate(c, 0)
    upgrades.deactivate(c, 0)
    upgrades.deactivate(c, 0)
    assert counters(g) == (4, 0) and g.fighters["rosie"].ranged
    assert counters(c) == (0, 0) and not c.fighters["rosie"].ranged


def test_merlin_engine_makes_rosies_move_value_three_in_a_maneuver_and_wendys_stays_two(bprd):
    g = mk(bprd)
    rosie, wendy = g.fighters["rosie"], g.fighters["wendy"]
    upgrades.activate(g, 0)
    assert (rosie.move, wendy.move) == (3, 2) and g.maneuver_bonus(0) == 0
    g.players[0].hand.append(g.players[0].deck.pop(0))
    g.maneuver(0, {"rosie": far_from(g, "rosie", 3)})
    assert g.actions_left == 1
    g2 = mk(bprd)
    upgrades.activate(g2, 0)
    g2.players[0].hand.append(g2.players[0].deck.pop(0))
    with pytest.raises(RuleError):
        g2.maneuver(0, {"wendy": far_from(g2, "wendy", 3)})
    with pytest.raises(RuleError):
        g2.maneuver(0, {"rosie": far_from(g2, "rosie", 4)})


def test_the_move_value_goes_back_to_two_when_merlin_engine_is_deactivated_and_follows_the_row(bprd):
    g = mk(bprd)
    rosie = g.fighters["rosie"]
    upgrades.activate(g, 0, 2)
    assert rosie.move == 3
    upgrades.deactivate(g, 0)                                     # merlin goes to the end of the row: not active any more
    assert rosie.move == 2
    upgrades.activate(g, 0, 3)                                    # all four again: merlin is the last one flipped
    assert rosie.move == 3


def test_a_saved_game_and_a_clone_keep_the_move_value_merlin_engine_gave(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0)
    g2 = mk(bprd)
    persist.apply_game(g2, persist.game_to_dict(g))
    assert g2.fighters["rosie"].move == 3 and g2.clone().fighters["rosie"].move == 3 and g2.fighters["wendy"].move == 2


def test_an_ongoing_coming_or_going_does_not_wipe_merlin_engines_move(bprd):
    """Philippa's hero_move sync puts the printed move back when an ONGOING comes or goes: Rosie's own bonus is applied again."""
    g = mk(bprd)
    upgrades.activate(g, 0)
    assert g.fighters["rosie"].move == 3
    g.fx.set_ongoing(0, g.players[0].full_set[0].card_id)
    assert g.fighters["rosie"].move == 3
    g.fx.take_ongoing(0)
    assert g.fighters["rosie"].move == 3 and g.fighters["wendy"].move == 2


def test_without_merlin_engine_a_maneuver_is_the_usual_two_spaces(bprd):
    g = mk(bprd)
    g.players[0].hand.append(g.players[0].deck.pop(0))
    with pytest.raises(RuleError):
        g.maneuver(0, {"rosie": far_from(g, "rosie", 3)})


def test_merlin_engine_adds_to_the_boost_of_the_maneuver(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0)
    boost = give(g, 0, "Full Metal")                              # BOOST 3
    g.players[0].hand.append(g.players[0].deck.pop(0))
    g.maneuver(0, {"rosie": far_from(g, "rosie", 2 + 3 + 1)}, boost)


def test_merlin_engine_does_not_widen_the_moves_of_card_effects(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or []]
    g.attack(rosie, hellboy, give(g, 0, "Overrun"), None)
    assert seen and seen[0].extra["steps"] == 3


def test_cavity_magnetron_lets_rosie_draw_one_card_after_she_attacks(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 2)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    asked = []
    g.controllers[0].queue = [lambda req: asked.append(req) or [True]]
    g.attack(rosie, hellboy, give(g, 0, "Momentous Shift"), None)
    assert [r.kind for r in asked] == ["optional"] and len(g.players[0].hand) == 1


def test_cavity_magnetron_is_optional(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 2)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    g.controllers[0].queue = [[False]]
    g.attack(rosie, hellboy, give(g, 0, "Momentous Shift"), None)
    assert g.players[0].hand == []


def test_cavity_magnetron_is_only_for_rosie_attacking_never_wendy_or_a_defense(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 2)
    wendy, hellboy = pair(g, "wendy", "hellboy")
    g.controllers[0].queue = [[True]]
    g.attack(wendy, hellboy, give(g, 0, "Momentous Shift"), None)
    assert g.players[0].hand == [] and g.controllers[0].queue == [[True]]
    d = mk(bprd, turn=1)
    upgrades.activate(d, 0, 2)
    rosie, hellboy = pair(d, "rosie", "hellboy")
    d.controllers[0].queue = [[True]]
    d.actions_left = 2
    d.attack(hellboy, rosie, give(d, 1, "Excalibur"), give(d, 0, "Momentous Shift"))
    assert d.players[0].hand == [] and d.controllers[0].queue == [[True]]


def test_without_cavity_magnetron_rosie_draws_nothing_after_attacking(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    g.attack(rosie, hellboy, give(g, 0, "Momentous Shift"), None)
    assert g.players[0].hand == []


# ---------------------------------------------------------------- the cards

def test_we_can_do_it_is_a_four_that_activates_an_upgrade_immediately(bprd):
    g = mk(bprd)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    res = g.attack(rosie, hellboy, give(g, 0, "We Can Do It!"), None)
    assert res.atk_value == 4 and counters(g) == (1, 0) and ids(upgrades.active(g, 0)) == ["merlin_engine"]


def test_we_can_do_it_with_all_four_active_changes_nothing(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 4)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    g.attack(rosie, hellboy, give(g, 0, "We Can Do It!"), None)
    assert counters(g) == (4, 0)


def test_the_sedgley_fist_gun_activated_by_we_can_do_it_counts_for_that_very_attack(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 2)                                    # the card flips the third upgrade, the Sedgley Fist Gun
    rosie, hellboy = pair(g, "rosie", "hellboy")
    res = g.attack(rosie, hellboy, give(g, 0, "We Can Do It!"), None)
    assert counters(g) == (3, 0) and res.atk_value == 4 + 1 and hellboy.hp == hellboy.max_hp - 5
    assert any("SEDGLEY FIST GUN" in part for part in res.atk_parts)


def test_another_upgrade_activated_by_we_can_do_it_adds_nothing_to_the_attack(bprd):
    g = mk(bprd)
    upgrades.activate(g, 0, 1)                                    # the card flips the Cavity Magnetron
    rosie, hellboy = pair(g, "rosie", "hellboy")
    assert g.attack(rosie, hellboy, give(g, 0, "We Can Do It!"), None).atk_value == 4


def test_d_day_gains_an_action_and_activates_all_the_upgrades(bprd):
    g = mk(bprd, "leonardo")
    rosie, leo = pair(g, "rosie", "leonardo")
    upgrades.activate(g, 0, 2)
    g.attack(rosie, leo, give(g, 0, "D-Day"), None)
    assert counters(g) == (4, 0) and g.actions_left == 2                       # one spent, one gained
    assert leo.hp == leo.max_hp - 3                                          # not already active: no extra damage


def test_the_free_action_of_d_day_can_only_be_spent_on_an_attack(bprd):
    g = mk(bprd, "leonardo")
    rosie, leo = pair(g, "rosie", "leonardo")
    g.attack(rosie, leo, give(g, 0, "D-Day"), None)
    assert g.actions_left == 2 and g.fx.attack_credit == 1
    g.players[0].hand.append(g.players[0].deck.pop(0))
    g.maneuver(0, {})                                             # the real action
    assert g.actions_left == 1 and g.attack_only()
    with pytest.raises(RuleError):
        g.maneuver(0, {})
    with pytest.raises(RuleError):
        g.play_scheme(0, g.fighters["wendy"], give(g, 0, '"E" Award'))
    res = g.attack(rosie, leo, give(g, 0, "Technological Superiority"), None)
    assert res.atk_value >= 3 and g.actions_left == 0 and g.fx.attack_credit == 0


def test_d_day_with_all_four_already_active_hurts_the_opposing_fighter_and_heals_rosie(bprd):
    g = mk(bprd, "leonardo")
    rosie, leo = pair(g, "rosie", "leonardo")
    upgrades.activate(g, 0, 4)
    rosie.hp = 10
    res = g.attack(rosie, leo, give(g, 0, "D-Day"), give(g, 1, "Heroes in a half shell"))      # 3 + 1 against a 5: only the effects show
    assert not res.attacker_won
    assert leo.hp == leo.max_hp - 1 and rosie.hp == 11 and g.actions_left == 2 and counters(g) == (4, 0)


def test_d_day_with_three_active_is_not_already_active(bprd):
    g = mk(bprd, "leonardo")
    rosie, leo = pair(g, "rosie", "leonardo")
    upgrades.activate(g, 0, 3)
    rosie.hp = 10
    g.attack(rosie, leo, give(g, 0, "D-Day"), give(g, 1, "Heroes in a half shell"))
    assert leo.hp == leo.max_hp and rosie.hp == 10 and counters(g) == (4, 0) and g.actions_left == 2


def test_overrun_moves_rosie_up_to_three_through_the_opposing_fighters_and_hurts_each_one(bprd):
    g = mk(bprd, "baba-yaga")
    rosie = g.fighters["rosie"]
    path = None
    for a in sorted(g.board.spaces):
        for b in sorted(g.board.adj[a]):
            for c in sorted(g.board.adj[b] - {a}):
                for e in sorted(g.board.adj[c] - {a, b}):
                    if len({a, b, c, e}) == 4 and g.board.distance(a, e) == 3:
                        path = (a, b, c, e)
                        break
                if path:
                    break
            if path:
                break
        if path:
            break
    a, b, c, e = path
    foes = g.own(1)
    rosie.pos = a
    foes[0].pos, foes[1].pos = b, c
    for f in foes[2:] + [g.fighters["wendy"]]:
        f.pos = max(s for s in g.board.spaces if s not in path)
    far = max(g.board.spaces)
    others = [f for f in g.fighters.values() if f.alive and f is not rosie and f not in foes[:2]]
    for i, f in enumerate(others):
        f.pos = sorted(s for s in g.board.spaces if s not in path)[-1 - i]
    g.controllers[0].moves = {"rosie": e}
    before = [f.hp for f in foes]
    g.attack(rosie, foes[0], give(g, 0, "Overrun"), wall(g) if False else None)
    after = [f.hp for f in foes]
    assert rosie.pos == e and after[1] == before[1] - 1 and after[2:] == before[2:]


def test_full_metal_is_worth_one_more_for_each_active_upgrade(bprd):
    values = []
    for n in range(5):
        g = mk(bprd)
        upgrades.activate(g, 0, n)
        rosie, hellboy = pair(g, "rosie", "hellboy")
        values.append(g.attack(rosie, hellboy, give(g, 0, "Full Metal"), None).atk_value)
    assert values == [1 + 0, 1 + 1, 1 + 2, 1 + 3 + 1, 1 + 4 + 1]              # the third upgrade is also Sedgley Fist Gun: +1 on top


def test_technological_superiority_cancels_the_opponents_effects_with_three_or_more_active_upgrades(bprd):
    for n, cancelled in ((2, False), (3, True), (4, True)):
        g = mk(bprd, "sinbad", turn=1)
        upgrades.activate(g, 0, n)
        rosie, sinbad = pair(g, "rosie", "sinbad")
        g.actions_left = 2
        g.attack(sinbad, rosie, give(g, 1, "Exploit"), give(g, 0, "Technological Superiority"))     # Exploit: AFTER draw 1
        assert len(g.players[1].hand) == (0 if cancelled else 1), n


def put_on_top(g, player, title):
    st = g.players[player]
    card = next(c for c in st.deck if c.title == title)
    st.deck.remove(card)
    st.deck.insert(0, card)
    return card


def test_loose_lips_sink_ships_lowers_the_opponents_value_by_the_boost_of_their_top_card(bprd):
    g = mk(bprd, "leonardo", turn=1)
    rosie, leo = pair(g, "rosie", "leonardo")
    g.actions_left = 2
    top = put_on_top(g, 1, "Quick strike")                                   # BOOST 3, the opponent's own deck
    res = g.attack(leo, rosie, give(g, 1, "Katana"), give(g, 0, "Loose Lips Sink Ships!"))
    assert g.players[1].deck[0] is top                                       # revealed, not discarded
    assert res.atk_value == 6 - 3 and res.def_value == 2


def test_loose_lips_sink_ships_never_takes_a_value_below_zero(bprd):
    g = mk(bprd, "leonardo", turn=1)
    rosie, leo = pair(g, "rosie", "leonardo")
    g.actions_left = 2
    put_on_top(g, 1, "Heroes in a half shell")                              # BOOST 3 against a 3
    res = g.attack(leo, rosie, give(g, 1, "Turtle power!"), give(g, 0, "Loose Lips Sink Ships!"))
    assert res.atk_value == 0


def test_loose_lips_sink_ships_on_an_attack_lowers_the_defense_and_reveals_the_rivals_deck_not_hers(bprd):
    g = mk(bprd, "leonardo")
    rosie, leo = pair(g, "rosie", "leonardo")
    mine = g.players[0].deck[0]
    top = put_on_top(g, 1, "Quick strike")
    res = g.attack(rosie, leo, give(g, 0, "Loose Lips Sink Ships!"), give(g, 1, "Heroes in a half shell"))
    assert res.def_value == 5 - 3 and g.players[0].deck[0] is mine and g.players[1].deck[0] is top


def test_hasty_repairs_deactivates_the_leftmost_active_upgrade_and_heals_rosie_three(bprd):
    g = mk(bprd, "leonardo", turn=1)
    rosie, leo = pair(g, "rosie", "leonardo")
    upgrades.activate(g, 0, 2)
    rosie.hp = 8
    g.actions_left = 2
    res = g.attack(leo, rosie, give(g, 1, "Katana"), give(g, 0, "Hasty Repairs"))
    assert res.atk_value == 6 and rosie.hp == 8 - 5 + 3
    assert counters(g) == (1, 1) and ids(upgrades.active(g, 0)) == ["cavity_magnetron"]


def test_hasty_repairs_with_no_active_upgrade_does_nothing(bprd):
    g = mk(bprd, "leonardo", turn=1)
    rosie, leo = pair(g, "rosie", "leonardo")
    rosie.hp = 8
    g.actions_left = 2
    g.attack(leo, rosie, give(g, 1, "Katana"), give(g, 0, "Hasty Repairs"))
    assert counters(g) == (0, 0) and rosie.hp == 8 - 5


def test_arc_welding_activates_an_upgrade_or_hurts_each_adjacent_opposing_fighter(bprd):
    g = mk(bprd)
    wendy, hellboy = pair(g, "wendy", "hellboy")
    g.controllers[0].queue = [[0]]
    g.attack(wendy, hellboy, give(g, 0, "Arc Welding"), None)
    assert counters(g) == (1, 0)
    g2 = mk(bprd)
    wendy, hellboy = pair(g2, "wendy", "hellboy")
    put_adjacent(g2, "lobster", "wendy")
    lobster = g2.fighters["lobster"]
    before = (hellboy.hp, lobster.hp)
    g2.controllers[0].queue = [[1]]
    g2.attack(wendy, hellboy, give(g2, 0, "Arc Welding"), None)
    assert counters(g2) == (0, 0) and hellboy.hp == before[0] - 3 - 1 and lobster.hp == before[1] - 1


def test_arc_welding_is_wendys_card_and_rosie_cannot_play_it(bprd):
    g = mk(bprd)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    with pytest.raises(RuleError):
        g.attack(rosie, hellboy, give(g, 0, "Arc Welding"), None)


def test_rapid_development_draws_two_activates_or_deactivates_and_gains_an_action(bprd):
    g = mk(bprd)
    wendy = g.fighters["wendy"]
    g.controllers[0].queue = [[0]]
    g.play_scheme(0, wendy, give(g, 0, "Rapid Development"))
    assert len(g.players[0].hand) == 2 and counters(g) == (1, 0) and g.actions_left == 2
    g2 = mk(bprd)
    upgrades.activate(g2, 0, 2)
    g2.controllers[0].queue = [[1]]
    g2.play_scheme(0, g2.fighters["wendy"], give(g2, 0, "Rapid Development"))
    assert counters(g2) == (1, 1)


def test_rapid_development_gives_a_free_action_that_only_an_attack_may_spend(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[0]]
    g.play_scheme(0, g.fighters["wendy"], give(g, 0, "Rapid Development"))
    assert g.actions_left == 2 and g.fx.attack_credit == 1
    g.players[0].hand.append(g.players[0].deck.pop(0))
    g.maneuver(0, {})
    assert g.attack_only()
    with pytest.raises(RuleError):
        g.maneuver(0, {})


def test_e_award_activates_or_deactivates_and_moves_each_fighter_up_to_three(bprd):
    g = mk(bprd)
    rosie, wendy = g.fighters["rosie"], g.fighters["wendy"]
    r0, w0 = rosie.pos, wendy.pos
    g.controllers[0].queue = [[0]]
    g.controllers[0].moves = {"rosie": far_from(g, "rosie", 3)}
    g.play_scheme(0, wendy, give(g, 0, '"E" Award'))
    assert counters(g) == (1, 0) and g.board.distance(r0, rosie.pos) <= 3 and g.board.distance(w0, wendy.pos) <= 3


def test_momentous_shift_is_five_after_the_fighter_moved_this_turn(bprd):
    g = mk(bprd)
    start_turn(g)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    res = g.attack(rosie, hellboy, give(g, 0, "Momentous Shift"), None)
    assert res.atk_value == 5


# ---------------------------------------------------------------- the AI

def test_the_ai_prices_full_metal_by_the_active_upgrades(bprd):
    from sparring import ai_rosie
    g = mk(bprd)
    full = give(g, 0, "Full Metal")
    rosie = g.fighters["rosie"]
    assert ai_rosie.own_value(g, rosie, full) == 1.0
    upgrades.activate(g, 0, 3)
    assert ai_rosie.own_value(g, rosie, full) == 4.0
    assert ai_rosie.own_value(g, rosie, give(g, 0, "Momentous Shift")) is None


def test_the_ai_values_the_upgrade_cards_more_when_they_have_something_to_do(bprd):
    from sparring import ai_rosie
    g = mk(bprd)
    rosie = g.fighters["rosie"]
    we_can = give(g, 0, "We Can Do It!")
    assert ai_rosie.after_value(g, 0, we_can, 0.5, 1.0, 0.4, 1.2, 5) > 0
    upgrades.activate(g, 0, 4)
    assert ai_rosie.after_value(g, 0, we_can, 0.5, 1.0, 0.4, 1.2, 5) == 0
    hasty = give(g, 0, "Hasty Repairs")
    rosie.hp = 9
    assert ai_rosie.after_value(g, 0, hasty, 0.5, 1.0, 0.4, 1.2, 5) == pytest.approx(1.2 * 3)
    upgrades.activate(g, 0, 0)
    rosie.hp = rosie.max_hp
    assert ai_rosie.after_value(g, 0, hasty, 0.5, 1.0, 0.4, 1.2, 5) == 0
    assert ai_rosie.after_value(g, 1, we_can, 0.5, 1.0, 0.4, 1.2, 5) == 0       # the rival has no upgrades


def test_the_search_ai_plays_a_turn_for_rosie_without_a_fallback(bprd):
    from sparring import sim
    ai = sim.make_bot("ismcts", iterations=6, seed=2)
    out = sim.play(2, bot_hero=SLUG, human_hero="hellboy", medusa=ai, max_turns=12)
    assert out.turns >= 1 and ai.fallbacks == 0


def test_the_ismcts_bot_plans_rosies_turn_next_to_the_rival_without_a_fallback_and_attacks(bprd):
    from sparring.search.controller import make_bot_ai
    g = mk(bprd)
    upgrades.activate(g, 0, 3)
    rosie, hellboy = pair(g, "rosie", "hellboy")
    g.fighters["wendy"].pos = next(s for s in sorted(g.board.spaces, reverse=True)       # Wendy stays out of reach of every rival: Rosie has the only blow
                                   if all(not g.board.can_reach_target(s, f.pos, False, 0) for f in g.foes(0)) and s not in {f.pos for f in g.fighters.values() if f.alive})
    for title in ("We Can Do It!", "Full Metal", "Overrun", "Momentous Shift", "Hasty Repairs"):
        give(g, 0, title)
    for _ in range(4):
        g.players[1].hand.append(g.players[1].deck.pop(0))
    ai = make_bot_ai({"ai": "ismcts"})
    act = ai.plan(g)
    assert ai.fallbacks == 0 and act.kind == "attack" and act.fid == "rosie" and act.card.title in {"We Can Do It!", "Full Metal", "Overrun", "Momentous Shift"}
    assert not rosie.ranged or g.can_attack(rosie, hellboy)

