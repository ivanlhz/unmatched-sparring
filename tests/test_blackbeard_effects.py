"""Blackbeard on the engine, bot side (player 0 plays him, the controllers answer): the three doubloons (two counters), the start-of-turn action,
the payment when he takes combat damage, the RANSOM of every "unless" line (Ivan 2026-11-22, BB1: decided after the target or the random card is
known, payable against an uncancelable card), Queen Anne's Revenge, the Sea Dogs that return or reposition (BB2) and the cards with the numbers
printed on them. The human side (panel, FakeTTS) is in tests/test_blackbeard_human.py and the full games in tests/test_blackbeard_matrix.py.

The rival is Leonardo: Katana (attack 6) and Heroes in a half shell (defense 5) have no effect text, so what happens is Blackbeard's."""
from __future__ import annotations

from conftest import give
from sparring.effects.choose import ControllerChooser
from sparring.effects.modifiers import is_uncancelable
from sparring.effects.run import Ctx, EffectRun
from sparring.effects.select import counter_value
from sparring.i18n import t
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import pair, put_adjacent

DOGS = ["seadog1", "seadog2"]
FOE = "leonardo"


def mk(bprd, foe=FOE, seed=3, turn=0):
    """Blackbeard = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands, the start-of-turn action declined."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("blackbeard", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    ctl[0].queue = [[False]]
    g.begin_turn()
    ctl[0].queue.clear()
    for p in g.players:
        p.hand.clear()
    for c in ctl.values():
        c.requests.clear()
    return g


def coins(g):
    """(doubloons Blackbeard holds, doubloons in the Treasury)."""
    return counter_value(g, 0, "doubloons"), counter_value(g, 0, "treasury")


def set_coins(g, held, treasury):
    g.fx.set_counter(0, "doubloons", held)
    g.fx.set_counter(0, "treasury", treasury)


def hand_of(g, player, title):
    c = next(c for c in g.players[player].full_set if c.title == title)
    if c in g.players[player].deck:
        g.players[player].deck.remove(c)
    g.players[player].hand.append(c)
    return c


def wall(g):
    return hand_of(g, 1, "Heroes in a half shell")


def katana(g):
    return hand_of(g, 1, "Katana")


def fill_hand(g, player, n):
    cards = [c for c in g.players[player].deck if c.title not in ("Katana", "Heroes in a half shell")][:n]
    for c in cards:
        g.players[player].deck.remove(c)
        g.players[player].hand.append(c)
    return cards


def asked(g, player, kind):
    return [r for r in g.controllers[player].requests if r.kind == kind]


def ransoms(g):
    return [r for r in asked(g, 1, "optional") if "ransom" in r.extra]


def free_space_in_zone(g, fid):
    me = g.fighters[fid]
    return next(s for s in sorted(g.board.spaces) if s != me.pos and g.board.share_zone(me.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))


# ---------------------------------------------------------------- the hero

def test_blackbeard_is_a_ranged_hero_with_two_sea_dogs_on_the_board(bprd):
    g = mk(bprd)
    b = g.fighters["blackbeard"]
    assert (b.hp, b.move, b.ranged, b.name) == (13, 2, True, "Blackbeard")
    assert all((g.fighters[d].hp, g.fighters[d].move, g.fighters[d].ranged, g.fighters[d].name, g.fighters[d].alive) == (1, 2, False, "Sea Dog", True)
               for d in DOGS)
    assert "blackbeard" in g.fx.dsl_heroes and g.winner is None


def test_the_deck_has_the_printed_bands_and_numbers(bprd):
    g = mk(bprd)
    seen = {}
    for c in g.players[0].full_set:
        s = seen.setdefault(c.title, (c.type, c.value, c.boost, c.fighter, 0))
        seen[c.title] = s[:4] + (s[4] + 1,)
    assert len(g.players[0].full_set) == 30
    assert seen == {
        "A Brace of Primed Pistols": ("attack", 2, 2, "Blackbeard", 2), "Avast Ye!": ("attack", 5, 3, "Blackbeard", 2),
        "Give No Quarter": ("attack", 3, 1, "any", 3), "Light the Fuse": ("attack", 2, 3, "Sea Dog", 3),
        "Queen Anne's Revenge": ("versatile", 7, 3, "Blackbeard", 2), "Fearsome and Calculating": ("versatile", 3, 1, "Blackbeard", 3),
        "Show a Leg!": ("versatile", 2, 2, "any", 2), "No Prey, No Pay": ("versatile", 2, 2, "any", 3), "Parley": ("versatile", 3, 2, "any", 3),
        "Intimidating Visage": ("defense", 4, 1, "Blackbeard", 2), "Plunder": ("scheme", None, 2, "Blackbeard", 3),
        "Scourge of the Seven Seas": ("scheme", None, 2, "Blackbeard", 2)}


def test_light_the_fuse_is_for_a_sea_dog_only_and_the_pistols_for_blackbeard(bprd):
    g = mk(bprd)
    fuse = next(c for c in g.players[0].full_set if c.title == "Light the Fuse")
    brace = next(c for c in g.players[0].full_set if c.title == "A Brace of Primed Pistols")
    assert fuse.usable_by("Sea Dog") and not fuse.usable_by("Blackbeard")
    assert brace.usable_by("Blackbeard") and not brace.usable_by("Sea Dog")


# ---------------------------------------------------------------- the doubloons

def test_the_game_starts_with_two_doubloons_in_his_hand_and_one_in_the_treasury(bprd):
    assert coins(mk(bprd)) == (2, 1)


def test_the_start_of_turn_action_costs_one_doubloon_that_goes_to_the_treasury(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[True]]
    before = g.actions_left
    g.fx.emit("start_of_turn", 0)
    assert coins(g) == (1, 2) and g.actions_left == before + 1


def test_the_start_of_turn_action_may_be_declined(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[False]]
    before = g.actions_left
    g.fx.emit("start_of_turn", 0)
    assert coins(g) == (2, 1) and g.actions_left == before


def test_the_start_of_turn_action_is_not_offered_without_a_doubloon(bprd):
    g = mk(bprd)
    set_coins(g, 0, 3)
    g.fx.emit("start_of_turn", 0)
    assert asked(g, 0, "optional") == [] and coins(g) == (0, 3)


def test_the_start_of_turn_action_is_asked_only_at_the_start_of_his_own_turn(bprd):
    g = mk(bprd)
    g.fx.emit("start_of_turn", 1)
    assert g.controllers[0].requests == []


def test_blackbeard_pays_a_doubloon_when_he_takes_combat_damage(bprd):
    g = mk(bprd, turn=1)
    foe, b = pair(g, FOE, "blackbeard")
    g.attack(foe, b, katana(g), None)
    assert b.hp == 13 - 6 and coins(g) == (1, 2)


def test_he_pays_one_doubloon_per_combat_whatever_the_blow_and_the_visage_heals_it_back(bprd):
    g = mk(bprd, turn=1)
    foe, b = pair(g, FOE, "blackbeard")
    set_coins(g, 3, 0)
    g.attack(foe, b, katana(g), give(g, 0, "Intimidating Visage"))
    assert b.hp == 13 and coins(g) == (2, 1)          # 6 against 4: two points of damage, healed back by the Visage


def test_a_sea_dog_taking_combat_damage_pays_nothing(bprd):
    g = mk(bprd, turn=1)
    foe, dog = pair(g, FOE, "seadog1")
    g.attack(foe, dog, katana(g), None)
    assert not dog.alive and coins(g) == (2, 1)


def test_with_no_doubloon_to_pay_nothing_happens(bprd):
    g = mk(bprd, turn=1)
    set_coins(g, 0, 3)
    foe, b = pair(g, FOE, "blackbeard")
    g.attack(foe, b, katana(g), None)
    assert b.hp == 13 - 6 and coins(g) == (0, 3)


def test_a_blow_the_defense_absorbs_costs_no_doubloon(bprd):
    g = mk(bprd, turn=1)
    foe, b = pair(g, FOE, "blackbeard")
    hand_of(g, 1, "Quick strike")
    g.attack(foe, b, g.players[1].hand[-1], give(g, 0, "Intimidating Visage"))
    assert b.hp == 13 and coins(g) == (2, 1)


def test_effect_damage_to_blackbeard_costs_no_doubloon(bprd):
    g = mk(bprd, turn=1)
    b = g.fighters["blackbeard"]
    g.damage(b, 2)
    assert b.hp == 11 and coins(g) == (2, 1)


# ---------------------------------------------------------------- ransom: A Brace of Primed Pistols

def test_brace_the_owner_picks_the_victim_first_then_the_opponent_decides_on_the_ransom(bprd):
    g = mk(bprd)
    set_coins(g, 1, 2)
    b, foe = pair(g, "blackbeard", FOE)
    put_adjacent(g, "splinter", "blackbeard")
    g.controllers[0].queue = [["splinter"]]
    g.controllers[1].queue = [[False]]
    g.attack(b, foe, give(g, 0, "A Brace of Primed Pistols"), wall(g))
    order = [(r.player, r.kind) for r in g.controllers[0].requests + g.controllers[1].requests]
    assert (0, "fighter") in order and (1, "optional") in order
    assert len(ransoms(g)) == 1 and ransoms(g)[0].extra["effect"] == {"what": "damage", "amount": 3, "fighters": ["splinter"]}
    assert g.fighters["splinter"].hp == g.fighters["splinter"].max_hp - 3 and foe.hp == foe.max_hp


def test_brace_a_paid_ransom_ignores_the_damage_and_moves_two_doubloons_to_blackbeard(bprd):
    g = mk(bprd)
    set_coins(g, 1, 2)
    b, foe = pair(g, "blackbeard", FOE)
    g.controllers[1].queue = [[True]]
    g.attack(b, foe, give(g, 0, "A Brace of Primed Pistols"), wall(g))
    assert foe.hp == foe.max_hp and coins(g) == (3, 0)


def test_brace_a_declined_ransom_deals_three_damage(bprd):
    g = mk(bprd)
    set_coins(g, 1, 2)
    b, foe = pair(g, "blackbeard", FOE)
    g.controllers[1].queue = [[False]]
    g.attack(b, foe, give(g, 0, "A Brace of Primed Pistols"), wall(g))
    assert foe.hp == foe.max_hp - 3 and coins(g) == (1, 2)


def test_brace_cannot_be_ransomed_with_one_doubloon_in_the_treasury(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    g.attack(b, foe, give(g, 0, "A Brace of Primed Pistols"), wall(g))
    assert ransoms(g) == [] and foe.hp == foe.max_hp - 3 and coins(g) == (2, 1)


def test_brace_asks_nothing_when_no_opposing_fighter_is_in_blackbeards_zone(bprd):
    g = mk(bprd)
    set_coins(g, 1, 2)
    b, foe = pair(g, "blackbeard", FOE)
    foe.hp = 1                                                       # the attack defeats the only opposing fighter near him
    g.attack(b, foe, give(g, 0, "A Brace of Primed Pistols"), None)
    assert not foe.alive and ransoms(g) == [] and coins(g) == (1, 2)


# ---------------------------------------------------------------- ransom: Avast Ye!

def test_avast_names_the_random_card_before_the_ransom_and_a_paid_ransom_keeps_it(bprd):
    g = mk(bprd)
    set_coins(g, 2, 1)
    b, foe = pair(g, "blackbeard", FOE)
    defense = wall(g)
    fill_hand(g, 1, 3)
    g.controllers[1].queue = [[True], [False]]
    g.attack(b, foe, give(g, 0, "Avast Ye!"), defense)
    first = ransoms(g)[0]
    assert first.extra["ransom"] == 1 and first.extra["effect"]["what"] == "random_discard" and len(first.extra["effect"]["cards"]) == 1
    assert len(g.players[1].hand) == 3 and coins(g) == (3, 0)


def test_avast_a_declined_ransom_discards_the_card_that_was_named(bprd):
    g = mk(bprd)
    set_coins(g, 2, 1)
    b, foe = pair(g, "blackbeard", FOE)
    defense = wall(g)
    fill_hand(g, 1, 3)
    pile = len(g.players[1].discard)
    g.controllers[1].queue = [[False], [False]]
    g.attack(b, foe, give(g, 0, "Avast Ye!"), defense)
    named = ransoms(g)[0].extra["effect"]["cards"][0]
    discarded = [c.card_id for c in g.players[1].discard[pile:]]
    assert named in discarded and len(g.players[1].hand) == 2


def test_avast_the_damage_to_the_zone_is_a_second_line_with_its_own_ransom(bprd):
    g = mk(bprd)
    set_coins(g, 2, 1)
    b, foe = pair(g, "blackbeard", FOE)
    defense = wall(g)
    fill_hand(g, 1, 2)
    g.controllers[1].queue = [[False], [True]]
    g.attack(b, foe, give(g, 0, "Avast Ye!"), defense)
    assert [r.extra["effect"]["what"] for r in ransoms(g)] == ["random_discard", "damage"]
    assert foe.hp == foe.max_hp and coins(g) == (3, 0)


def test_avast_the_second_ransom_is_closed_once_the_treasury_is_empty(bprd):
    g = mk(bprd)
    set_coins(g, 2, 1)
    b, foe = pair(g, "blackbeard", FOE)
    defense = wall(g)
    fill_hand(g, 1, 2)
    g.controllers[1].queue = [[True]]
    g.attack(b, foe, give(g, 0, "Avast Ye!"), defense)
    assert [r.extra["effect"]["what"] for r in ransoms(g)] == ["random_discard"]
    assert foe.hp == foe.max_hp - 1 and coins(g) == (3, 0)


def test_avast_with_an_empty_rival_hand_asks_no_ransom_for_a_discard(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    g.attack(b, foe, give(g, 0, "Avast Ye!"), None)
    assert not any(r.extra["effect"]["what"] == "random_discard" for r in ransoms(g))


# ---------------------------------------------------------------- Give No Quarter

def test_give_no_quarter_is_five_with_another_friendly_fighter_next_to_the_target(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    put_adjacent(g, "seadog1", FOE)
    assert g.attack(b, foe, give(g, 0, "Give No Quarter"), None).atk_value == 5


def test_give_no_quarter_is_three_with_nobody_else_next_to_the_target(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    assert g.attack(b, foe, give(g, 0, "Give No Quarter"), None).atk_value == 3


def test_give_no_quarter_a_sea_dog_attacking_counts_blackbeard_next_to_the_target(bprd):
    g = mk(bprd)
    dog, foe = pair(g, "seadog1", FOE)
    put_adjacent(g, "blackbeard", FOE)
    assert g.attack(dog, foe, give(g, 0, "Give No Quarter"), None).atk_value == 5


def test_give_no_quarter_gains_an_action_unless_the_opponent_pays_a_doubloon(bprd):
    g = mk(bprd)
    g.actions_left = 2
    b, foe = pair(g, "blackbeard", FOE)
    g.controllers[1].queue = [[False]]
    g.attack(b, foe, give(g, 0, "Give No Quarter"), None)
    assert g.actions_left == 2 and coins(g) == (2, 1)


def test_give_no_quarter_gains_no_action_when_the_ransom_is_paid(bprd):
    g = mk(bprd)
    g.actions_left = 2
    b, foe = pair(g, "blackbeard", FOE)
    g.controllers[1].queue = [[True]]
    g.attack(b, foe, give(g, 0, "Give No Quarter"), None)
    assert g.actions_left == 1 and coins(g) == (3, 0)


# ---------------------------------------------------------------- Light the Fuse

def test_light_the_fuse_hurts_every_fighter_next_to_the_sea_dog_friends_too(bprd):
    g = mk(bprd)
    dog, foe = pair(g, "seadog1", FOE)
    put_adjacent(g, "blackbeard", "seadog1")
    g.controllers[0].queue = [[]]
    near = {f.fid: f.hp for f in g.fighters.values() if f.alive and f.fid != "seadog1" and f.pos in g.board.adj[dog.pos]}
    assert {FOE, "blackbeard"} <= set(near)
    g.attack(dog, foe, give(g, 0, "Light the Fuse"), wall(g))
    assert all(g.fighters[fid].hp == hp - 1 for fid, hp in near.items())


def test_light_the_fuse_counts_the_fighters_next_to_where_the_sea_dog_ends(bprd):
    g = mk(bprd)
    dog, foe = pair(g, "seadog1", FOE)
    dest = free_space_in_zone(g, "seadog1")
    g.controllers[0].queue = [[dest]]
    near = {f.fid: f.hp for f in g.fighters.values() if f.alive and f.fid != "seadog1" and f.pos in g.board.adj[dest]}
    g.attack(dog, foe, give(g, 0, "Light the Fuse"), wall(g))
    assert dog.pos == dest
    assert all(g.fighters[fid].hp == hp - 1 for fid, hp in near.items())


def test_light_the_fuse_may_leave_the_sea_dog_where_it_is(bprd):
    g = mk(bprd)
    dog, foe = pair(g, "seadog1", FOE)
    old = dog.pos
    g.controllers[0].queue = [[]]
    g.attack(dog, foe, give(g, 0, "Light the Fuse"), wall(g))
    assert dog.pos == old


# ---------------------------------------------------------------- Queen Anne's Revenge

def test_queen_annes_revenge_is_seven_when_the_opponent_pays_nothing(bprd):
    g = mk(bprd)
    set_coins(g, 1, 2)
    b, foe = pair(g, "blackbeard", FOE)
    g.controllers[1].queue = [[0]]
    assert g.attack(b, foe, give(g, 0, "Queen Anne's Revenge"), None).atk_value == 7 and coins(g) == (1, 2)


def test_queen_annes_revenge_loses_two_for_each_doubloon_the_opponent_pays(bprd):
    g = mk(bprd)
    set_coins(g, 1, 2)
    b, foe = pair(g, "blackbeard", FOE)
    g.controllers[1].queue = [[2]]
    assert g.attack(b, foe, give(g, 0, "Queen Anne's Revenge"), None).atk_value == 3 and coins(g) == (3, 0)


def test_queen_annes_revenge_offers_zero_up_to_the_whole_treasury(bprd):
    g = mk(bprd)
    set_coins(g, 0, 3)
    b, foe = pair(g, "blackbeard", FOE)
    g.controllers[1].queue = [[1]]
    g.attack(b, foe, give(g, 0, "Queen Anne's Revenge"), None)
    assert list(asked(g, 1, "amount")[0].options) == [0, 1, 2, 3] and coins(g) == (1, 2)


def test_queen_annes_revenge_never_drops_below_zero(bprd):
    g = mk(bprd)
    set_coins(g, 0, 3)
    b, foe = pair(g, "blackbeard", FOE)
    g.controllers[1].queue = [[3]]
    assert g.attack(b, foe, give(g, 0, "Queen Anne's Revenge"), None).atk_value == 1 and coins(g) == (3, 0)


def test_queen_annes_revenge_asks_nothing_with_an_empty_treasury(bprd):
    g = mk(bprd)
    set_coins(g, 3, 0)
    b, foe = pair(g, "blackbeard", FOE)
    res = g.attack(b, foe, give(g, 0, "Queen Anne's Revenge"), None)
    assert asked(g, 1, "amount") == [] and res.atk_value == 7


def test_queen_annes_revenge_defending_is_paid_down_by_the_attacker(bprd):
    g = mk(bprd, turn=1)
    set_coins(g, 1, 2)
    foe, b = pair(g, FOE, "blackbeard")
    g.controllers[1].queue = [[2]]
    res = g.attack(foe, b, katana(g), give(g, 0, "Queen Anne's Revenge"))
    assert res.def_value == 3 and b.hp == 13 - 3 and coins(g) == (2, 1)      # two doubloons paid in, then one out for the damage Blackbeard takes


def test_queen_annes_revenge_effects_cannot_be_cancelled(bprd):
    g = mk(bprd)
    b = g.fighters["blackbeard"]
    assert is_uncancelable(give(g, 0, "Queen Anne's Revenge"), g, b)
    assert not is_uncancelable(give(g, 0, "Parley"), g, b)


# ---------------------------------------------------------------- Fearsome and Calculating, Parley

def test_fearsome_names_the_card_first_and_a_declined_ransom_discards_it(bprd):
    g = mk(bprd)
    set_coins(g, 2, 1)
    b, foe = pair(g, "blackbeard", FOE)
    defense = wall(g)
    fill_hand(g, 1, 3)
    g.controllers[1].queue = [[False]]
    g.attack(b, foe, give(g, 0, "Fearsome and Calculating"), defense)
    r = ransoms(g)[0]
    assert r.extra["ransom"] == 1 and r.extra["effect"]["what"] == "discard" and len(r.extra["effect"]["cards"]) == 1
    assert len(g.players[1].hand) == 2 and coins(g) == (2, 1)


def test_fearsome_a_paid_ransom_keeps_the_card_and_moves_the_doubloon(bprd):
    g = mk(bprd)
    set_coins(g, 2, 1)
    b, foe = pair(g, "blackbeard", FOE)
    defense = wall(g)
    fill_hand(g, 1, 3)
    g.controllers[1].queue = [[True]]
    g.attack(b, foe, give(g, 0, "Fearsome and Calculating"), defense)
    assert len(g.players[1].hand) == 3 and coins(g) == (3, 0)


def test_fearsome_with_an_empty_rival_hand_asks_nothing(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    g.attack(b, foe, give(g, 0, "Fearsome and Calculating"), None)
    assert ransoms(g) == []


def test_parley_cancels_the_rivals_effects_unless_two_doubloons_are_paid(bprd):
    g = mk(bprd)
    set_coins(g, 1, 2)
    b, foe = pair(g, "blackbeard", FOE)
    quick = hand_of(g, 1, "Quick strike")
    g.controllers[1].queue = [[True]]
    g.attack(b, foe, give(g, 0, "Parley"), quick)
    r = ransoms(g)[0]
    assert r.extra["ransom"] == 2 and r.extra["effect"]["what"] == "cancel" and coins(g) == (3, 0)


def test_parley_cancels_when_the_ransom_is_declined(bprd):
    g = mk(bprd)
    set_coins(g, 1, 2)
    b, foe = pair(g, "blackbeard", FOE)
    quick = hand_of(g, 1, "Quick strike")
    hand = len(g.players[1].hand)
    g.controllers[1].queue = [[False]]
    res = g.attack(b, foe, give(g, 0, "Parley"), quick)
    assert coins(g) == (1, 2) and "atk" not in res.cancelled and "def" in res.cancelled


def test_parley_cannot_be_ransomed_with_one_doubloon_in_the_treasury(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    g.attack(b, foe, give(g, 0, "Parley"), wall(g))
    assert ransoms(g) == []


# ---------------------------------------------------------------- Sea Dogs

def test_show_a_leg_returns_a_defeated_sea_dog_to_blackbeards_zone_with_one_health(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    g.defeat(g.fighters["seadog2"])
    g.attack(b, foe, give(g, 0, "Show a Leg!"), wall(g))
    dog = g.fighters["seadog2"]
    assert dog.alive and dog.hp == 1 and g.board.share_zone(b.pos, dog.pos)


def test_show_a_leg_with_no_sea_dog_defeated_lets_blackbeard_reposition_one_into_his_zone(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    where = free_space_in_zone(g, "blackbeard")
    g.controllers[0].queue = [[True], ["seadog1"], [where]]
    g.attack(b, foe, give(g, 0, "Show a Leg!"), wall(g))
    assert g.fighters["seadog1"].pos == where and all(g.fighters[d].alive for d in DOGS)


def test_show_a_leg_repositioning_is_optional(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    before = {d: g.fighters[d].pos for d in DOGS}
    g.controllers[0].queue = [[False]]
    g.attack(b, foe, give(g, 0, "Show a Leg!"), wall(g))
    assert {d: g.fighters[d].pos for d in DOGS} == before


def test_show_a_leg_with_no_free_space_in_the_zone_does_nothing_and_says_so(bprd, monkeypatch):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    g.defeat(g.fighters["seadog2"])
    shared = {b.pos, foe.pos}
    monkeypatch.setattr(g.board, "share_zone", lambda a, c: a == c or {a, c} <= shared)
    res = g.attack(b, foe, give(g, 0, "Show a Leg!"), wall(g))
    assert not g.fighters["seadog2"].alive
    assert any(t("narr.notice.seadog_no_space") in line for line in res.applied), res.applied


# ---------------------------------------------------------------- the other attack and defense cards

def test_no_prey_no_pay_draws_a_card_when_he_wins(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    hand = len(g.players[0].hand)
    g.attack(b, foe, give(g, 0, "No Prey, No Pay"), None)
    assert len(g.players[0].hand) == hand + 1


def test_no_prey_no_pay_draws_nothing_when_he_loses(bprd):
    g = mk(bprd)
    b, foe = pair(g, "blackbeard", FOE)
    hand = len(g.players[0].hand)
    g.attack(b, foe, give(g, 0, "No Prey, No Pay"), wall(g))
    assert len(g.players[0].hand) == hand


def test_intimidating_visage_heals_two_when_blackbeard_is_next_to_an_opposing_fighter(bprd):
    g = mk(bprd, turn=1)
    foe, b = pair(g, FOE, "blackbeard")
    b.hp = 6
    g.attack(foe, b, katana(g), give(g, 0, "Intimidating Visage"))
    assert b.hp == 6 - 2 + 2


def test_intimidating_visage_heals_nothing_when_no_opposing_fighter_is_next_to_him(bprd):
    g = mk(bprd, turn=1)
    foe, b = pair(g, FOE, "blackbeard")
    b.hp = 6
    foe.pos = max(s for s in g.board.spaces if not g.board.share_zone(b.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    ctx = Ctx(owner=0, this_fid="blackbeard", card_id=give(g, 0, "Intimidating Visage").card_id)
    EffectRun.for_card("blackbeard", "Intimidating Visage", "after", ctx).run(g, {0: ControllerChooser(), 1: ControllerChooser()})
    assert b.hp == 6


# ---------------------------------------------------------------- the schemes

def test_plunder_moves_each_of_his_fighters_through_opposing_fighters_and_steals_one_doubloon(bprd):
    g = mk(bprd)
    b = g.fighters["blackbeard"]
    g.play_scheme(0, b, give(g, 0, "Plunder"))
    moves = [r for r in asked(g, 0, "space") if r.extra.get("op") == "move"]
    assert sorted(r.extra["fighter"] for r in moves) == sorted(["blackbeard", *DOGS]) and all(r.extra["steps"] == 3 and r.extra["through"] for r in moves)
    assert coins(g) == (3, 0)


def test_plunder_with_the_treasury_empty_steals_nothing(bprd):
    g = mk(bprd)
    set_coins(g, 3, 0)
    g.play_scheme(0, g.fighters["blackbeard"], give(g, 0, "Plunder"))
    assert coins(g) == (3, 0)


def test_scourge_of_the_seven_seas_heals_summons_and_gains_an_action_unless_each_line_is_ransomed(bprd):
    g = mk(bprd)
    set_coins(g, 0, 3)
    b = g.fighters["blackbeard"]
    b.hp = 5
    g.defeat(g.fighters["seadog1"])
    g.actions_left = 1
    g.controllers[1].queue = [[False], [False], [False]]
    g.play_scheme(0, b, give(g, 0, "Scourge of the Seven Seas"))
    assert [r.extra["effect"]["what"] for r in ransoms(g)] == ["heal", "summon", "action"]
    assert b.hp == 7 and g.fighters["seadog1"].alive and g.actions_left == 1 and coins(g) == (0, 3)      # the scheme spent one action, the line gave one back


def test_scourge_each_line_has_its_own_ransom_and_the_treasury_runs_out(bprd):
    g = mk(bprd)
    set_coins(g, 1, 2)
    b = g.fighters["blackbeard"]
    b.hp = 5
    g.actions_left = 1
    g.controllers[1].queue = [[True], [True]]
    g.play_scheme(0, b, give(g, 0, "Scourge of the Seven Seas"))
    assert [r.extra["effect"]["what"] for r in ransoms(g)] == ["heal", "summon"]       # the Treasury is empty for the third line
    assert b.hp == 5 and coins(g) == (3, 0) and g.actions_left == 1


def test_the_three_doubloons_always_add_up_to_three_through_a_whole_game_of_ransoms(bprd):
    g = mk(bprd)
    for held, treasury in ((2, 1), (3, 0), (0, 3), (1, 2)):
        set_coins(g, held, treasury)
        b, foe = pair(g, "blackbeard", FOE)
        g.controllers[1].queue = [[True]]
        g.actions_left = 2
        g.attack(b, foe, give(g, 0, "Give No Quarter"), None)
        assert sum(coins(g)) == 3
