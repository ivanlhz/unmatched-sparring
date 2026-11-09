"""Sinbad on the engine, bot side (player 0 plays him, the controllers answer): the VOYAGE ability (+1 space in a Maneuver for each
VOYAGE card in his discard pile, for the hero and The Porter), the seven VOYAGE cards (+1 value per VOYAGE card in the discard pile and
their AFTER effects), and every other card with the numbers printed on it. The human side (panel, FakeTTS) is in
tests/test_sinbad_human.py and the full games in tests/test_sinbad_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.ai_medusa import MedusaAI, Model
from sparring.cards import can_be_boost
from sparring.state import Game, RuleError
from test_bigfoot_effects import Answers, empty_spaces, pick, start_turn, wall
from test_effects_combat import pair, put_adjacent

VOYAGES = ["Voyage Home", "Voyage to the Valley of the Giant Snakes", "Voyage to the Island That Was a Whale",
           "Voyage to the Creature With Eyes Like Coals of Fire", "Voyage to the City of the Man-Eating Apes",
           "Voyage to the City of the King of Serendib", "Voyage to the Cannibals With the Root of Madness"]


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Sinbad = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("sinbad", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def to_discard(g, player, *titles):
    """Cards of the deck straight into the discard pile (what a played card does at the end of its combat)."""
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


# ---------------------------------------------------------------- the hero

def test_sinbad_is_a_melee_hero_with_the_porter_and_a_voyage_counter(bprd):
    g = mk(bprd)
    sinbad, porter = g.fighters["sinbad"], g.fighters["porter"]
    assert (sinbad.hp, sinbad.move, sinbad.ranged, sinbad.name) == (15, 2, False, "Sinbad")
    assert (porter.hp, porter.move, porter.ranged, porter.name, porter.hero) == (6, 2, False, "The Porter", False)
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert "sinbad" in g.fx.dsl_heroes and g.counter(0, "voyage") == 0


def test_the_voyage_counter_counts_voyage_cards_in_the_discard_pile_only(bprd):
    g = mk(bprd)
    to_discard(g, 0, VOYAGES[1], VOYAGES[2], "Exploit")
    assert g.counter(0, "voyage") == 2
    give(g, 0, VOYAGES[0])                                       # in the hand it is not counted
    assert g.counter(0, "voyage") == 2


def test_the_voyage_cards_are_attacks_of_sinbad_without_boost_except_voyage_home(bprd):
    g = mk(bprd)
    by = {c.title: c for c in g.players[0].full_set}
    for title in VOYAGES:
        c = by[title]
        assert (c.type, c.value, c.fighter, "voyage" in c.tags) == ("attack", 2, "Sinbad", True), title
        assert (c.boost, can_be_boost(c)) == ((1, True) if title == "Voyage Home" else (0, False)), title
    assert sum("voyage" in c.tags for c in g.players[0].full_set) == 7


# ---------------------------------------------------------------- the ability: reach of a Maneuver

def far_from(g, fid, steps):
    """An empty space exactly `steps` spaces from `fid` (and one `steps - 1` away is reachable with less)."""
    f = g.fighters[fid]
    return next(s for s in empty_spaces(g, f.pos, steps) if g.board.distance(f.pos, s) == steps)


def test_without_voyage_cards_a_maneuver_moves_the_normal_two_spaces(bprd):
    g = mk(bprd)
    g.players[0].hand.append(g.players[0].deck.pop(0))
    dest = far_from(g, "sinbad", 3)
    with pytest.raises(RuleError):
        g.maneuver(0, {"sinbad": dest})
    assert g.maneuver_bonus(0) == 0


@pytest.mark.parametrize("n", [1, 2, 3])
def test_each_voyage_card_in_the_pile_adds_one_space_to_the_hero_and_to_the_porter(bprd, n):
    g = mk(bprd)
    to_discard(g, 0, *VOYAGES[:n])
    assert g.maneuver_bonus(0) == n
    sinbad, porter = g.fighters["sinbad"], g.fighters["porter"]
    far = sorted((s for s in g.board.spaces if not g.board.share_zone(sinbad.pos, s)), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.owner == 1], far):
        f.pos = s
    hero_dest = far_from(g, "sinbad", 2 + n)
    taken = {hero_dest}
    porter_dest = next(s for s in empty_spaces(g, porter.pos, 2 + n) if g.board.distance(porter.pos, s) == 2 + n and s not in taken)
    g.players[0].hand.append(g.players[0].deck.pop(0))
    g.maneuver(0, {"sinbad": hero_dest, "porter": porter_dest})
    assert (sinbad.pos, porter.pos) == (hero_dest, porter_dest)
    assert g.actions_left == 1


def test_one_more_space_than_the_pile_allows_is_refused(bprd):
    g = mk(bprd)
    to_discard(g, 0, VOYAGES[1], VOYAGES[2])
    dest = far_from(g, "sinbad", 5)
    g.players[0].hand.append(g.players[0].deck.pop(0))
    with pytest.raises(RuleError):
        g.maneuver(0, {"sinbad": dest})


def test_the_boost_adds_to_the_voyage_bonus(bprd):
    g = mk(bprd)
    to_discard(g, 0, VOYAGES[1])
    boost = give(g, 0, "Commanding Impact")                       # BOOST 2
    g.players[0].hand.append(g.players[0].deck.pop(0))
    dest = far_from(g, "sinbad", 2 + 2 + 1)
    g.maneuver(0, {"sinbad": dest}, boost)
    assert g.fighters["sinbad"].pos == dest


def test_voyage_home_spent_as_the_boost_counts_itself_in_the_same_maneuver(bprd):
    g = mk(bprd)
    home = give(g, 0, "Voyage Home")                              # BOOST 1; in the pile before anyone moves
    assert g.maneuver_bonus(0) == 0 and g.maneuver_bonus(0, home) == 1       # the planner sees it before it is spent
    g.players[0].hand.append(g.players[0].deck.pop(0))
    dest = far_from(g, "sinbad", 2 + 1 + 1)
    g.maneuver(0, {"sinbad": dest}, home)
    assert g.fighters["sinbad"].pos == dest and g.counter(0, "voyage") == 1


def test_the_rivals_voyage_cards_do_not_help_the_other_hero(bprd):
    g = mk(bprd)
    to_discard(g, 0, *VOYAGES[:3])
    assert g.maneuver_bonus(1) == 0                               # Hellboy
    hellboy = g.fighters["hellboy"]
    g.turn = 1
    g.players[1].hand.append(g.players[1].deck.pop(0))
    with pytest.raises(RuleError):
        g.maneuver(1, {"hellboy": far_from(g, "hellboy", 3)})


def test_the_ability_works_whoever_sits_in_the_other_seat(bprd):
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("hellboy", "sinbad"), bot_player=0)
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    to_discard(g, 1, *VOYAGES[:2])
    assert g.maneuver_bonus(1) == 2 and g.maneuver_bonus(0) == 0


# ---------------------------------------------------------------- the VOYAGE cards: value and AFTER effects

@pytest.mark.parametrize("n", [0, 3, 6])
def test_a_voyage_card_is_worth_two_plus_the_other_voyage_cards_in_the_pile(bprd, n):
    g = mk(bprd)
    pool = [t for t in VOYAGES if t != "Voyage to the City of the Man-Eating Apes"]
    to_discard(g, 0, *pool[:n])
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    res = g.attack(sinbad, hellboy, give(g, 0, "Voyage to the City of the King of Serendib"), None)
    assert res.atk_value == 2 + n and hellboy.hp == hellboy.max_hp - (2 + n) - 0


def test_the_card_in_play_is_not_counted_as_one_of_the_others(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    res = g.attack(sinbad, hellboy, give(g, 0, "Voyage to the City of the King of Serendib"), None)
    assert res.atk_value == 2 and g.counter(0, "voyage") == 1       # it reaches the pile afterwards


def test_voyage_home_takes_the_other_voyage_cards_into_the_hand(bprd):
    g = mk(bprd)
    to_discard(g, 0, VOYAGES[1], VOYAGES[2], VOYAGES[4], "Exploit")
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    res = g.attack(sinbad, hellboy, give(g, 0, "Voyage Home"), None)
    assert res.atk_value == 2 + 3
    hand = sorted(c.title for c in g.players[0].hand)
    assert hand == sorted([VOYAGES[1], VOYAGES[2], VOYAGES[4]])
    assert [c.title for c in g.players[0].discard if "voyage" in c.tags] == ["Voyage Home"]
    assert "Exploit" in [c.title for c in g.players[0].discard]


def test_voyage_home_with_nothing_to_take_does_nothing(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    g.attack(sinbad, hellboy, give(g, 0, "Voyage Home"), None)
    assert g.players[0].hand == []


def test_the_creature_makes_the_rival_discard_a_random_card(bprd):
    g = mk(bprd, "leonardo")
    sinbad, leo = pair(g, "sinbad", "leonardo")
    for _ in range(3):
        g.players[1].hand.append(g.players[1].deck.pop(0))
    wall(g)
    g.players[1].hand.pop()
    discards = len(g.players[1].discard)
    g.attack(sinbad, leo, give(g, 0, "Voyage to the Creature With Eyes Like Coals of Fire"), None)
    assert len(g.players[1].hand) == 2 and len(g.players[1].discard) == discards + 1


def test_the_creature_against_an_empty_hand_does_nothing(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    g.attack(sinbad, hellboy, give(g, 0, "Voyage to the Creature With Eyes Like Coals of Fire"), None)
    assert g.players[1].hand == [] and g.players[1].discard == []


def test_serendib_draws_one_card(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    g.attack(sinbad, hellboy, give(g, 0, "Voyage to the City of the King of Serendib"), None)
    assert len(g.players[0].hand) == 1


def test_the_snakes_let_the_owner_look_at_the_rivals_hand(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    for _ in range(2):
        g.players[1].hand.append(g.players[1].deck.pop(0))
    seen = {c.card_id for c in g.players[1].hand}
    g.attack(sinbad, hellboy, give(g, 0, "Voyage to the Valley of the Giant Snakes"), None)
    assert {c.card_id for c in g.players[0].known.cards(g.players[1])} == seen


def test_the_apes_deal_two_damage_to_the_opposing_fighter_on_top_of_the_combat(bprd):
    g = mk(bprd, "leonardo")
    sinbad, leo = pair(g, "sinbad", "leonardo")
    res = g.attack(sinbad, leo, give(g, 0, "Voyage to the City of the Man-Eating Apes"), wall(g))
    assert not res.attacker_won and leo.hp == leo.max_hp - 2          # blocked: only the 2 of the AFTER


def test_the_apes_deal_their_damage_even_when_the_combat_is_lost_and_hit_a_sidekick(bprd):
    g = mk(bprd, "hellboy")
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    put_adjacent(g, "lobster", "sinbad")
    lobster = g.fighters["lobster"]
    g.attack(sinbad, lobster, give(g, 0, "Voyage to the City of the Man-Eating Apes"), None)
    assert lobster.hp == max(0, lobster.max_hp - 2 - 2) or not lobster.alive


def test_the_whale_heals_sinbad_two(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    sinbad.hp = 10
    g.attack(sinbad, hellboy, give(g, 0, "Voyage to the Island That Was a Whale"), None)
    assert sinbad.hp == 12


def test_the_whale_does_not_exceed_the_maximum(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    sinbad.hp = 14
    g.attack(sinbad, hellboy, give(g, 0, "Voyage to the Island That Was a Whale"), None)
    assert sinbad.hp == 15


def test_the_cannibals_let_sinbad_move_up_to_two_spaces_or_stay(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    start = sinbad.pos
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [pick(lambda s: g.board.distance(start, s) == 2)(req)[0]]]
    g.attack(sinbad, hellboy, give(g, 0, "Voyage to the Cannibals With the Root of Madness"), None)
    assert seen[0].extra["steps"] == 2 and seen[0].extra["up_to"]
    assert g.board.distance(start, sinbad.pos) == 2
    g2 = mk(bprd)
    sinbad, hellboy = pair(g2, "sinbad", "hellboy")
    start = sinbad.pos
    g2.controllers[0].queue = [[]]                                 # up to 2: zero is allowed
    g2.attack(sinbad, hellboy, give(g2, 0, "Voyage to the Cannibals With the Root of Madness"), None)
    assert sinbad.pos == start


# ---------------------------------------------------------------- the other cards

def test_exploit_draws_one_card_win_or_lose(bprd):
    g = mk(bprd, "leonardo")
    sinbad, leo = pair(g, "sinbad", "leonardo")
    res = g.attack(sinbad, leo, give(g, 0, "Exploit"), wall(g))
    assert not res.attacker_won and len(g.players[0].hand) == 1
    g2 = mk(bprd)
    sinbad, hellboy = pair(g2, "sinbad", "hellboy")
    g2.attack(sinbad, hellboy, give(g2, 0, "Exploit"), None)
    assert len(g2.players[0].hand) == 1


def test_commanding_impact_is_a_five_that_draws_one(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    res = g.attack(sinbad, hellboy, give(g, 0, "Commanding Impact"), None)
    assert res.atk_value == 5 and len(g.players[0].hand) == 1


def test_regroup_draws_one_card_and_two_when_the_owner_won(bprd):
    g = mk(bprd, "leonardo")
    sinbad, leo = pair(g, "sinbad", "leonardo")
    res = g.attack(sinbad, leo, give(g, 0, "Regroup"), wall(g))
    assert not res.attacker_won and len(g.players[0].hand) == 1
    g2 = mk(bprd)
    sinbad, hellboy = pair(g2, "sinbad", "hellboy")
    res = g2.attack(sinbad, hellboy, give(g2, 0, "Regroup"), None)
    assert res.attacker_won and len(g2.players[0].hand) == 2


def test_regroup_on_defense_draws_two_when_the_defense_won_and_one_when_it_lost(bprd):
    won = mk(bprd, "hellboy", turn=1)
    sinbad, hellboy = pair(won, "sinbad", "hellboy")
    won.actions_left = 2
    attack = give(won, 1, "Glimpse Of Hell")                      # 2, lowered to 0: the defender takes no damage and wins
    res = won.attack(hellboy, sinbad, attack, give(won, 0, "Regroup"), values=(-2, 0))
    assert not res.attacker_won and len(won.players[0].hand) == 2
    lost = mk(bprd, "hellboy", turn=1)
    sinbad, hellboy = pair(lost, "sinbad", "hellboy")
    lost.actions_left = 2
    res = lost.attack(hellboy, sinbad, give(lost, 1, "Excalibur"), give(lost, 0, "Regroup"))
    assert res.attacker_won and len(lost.players[0].hand) == 1


def test_by_fortune_and_fate_is_the_porters_attack_and_draws_two(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    porter = g.fighters["porter"]
    card = give(g, 0, "By Fortune and Fate")
    assert card.usable_by("The Porter") and not card.usable_by("Sinbad")
    put_adjacent(g, "porter", "hellboy")
    res = g.attack(porter, hellboy, card, None)
    assert res.atk_value == 3 and len(g.players[0].hand) == 2
    with pytest.raises(RuleError):
        g.attack(sinbad, hellboy, give(g, 0, "By Fortune and Fate", 1), None)


def test_the_voyage_cards_and_toil_and_danger_are_sinbads_and_not_the_porters(bprd):
    g = mk(bprd)
    for title in (*VOYAGES, "Toil and Danger", "Riches Beyond Compare"):
        c = give(g, 0, title)
        assert c.usable_by("Sinbad") and not c.usable_by("The Porter"), title
    for title in ("Exploit", "Feint", "Regroup", "Leap Away", "Momentous Shift", "Commanding Impact"):
        c = give(g, 0, title)
        assert c.usable_by("Sinbad") and c.usable_by("The Porter"), title


def test_toil_and_danger_moves_sinbad_up_to_three_after_the_combat(bprd):
    g = mk(bprd, "leonardo")
    sinbad, leo = pair(g, "sinbad", "leonardo")
    start = sinbad.pos
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [pick(lambda s: g.board.distance(start, s) == 3)(req)[0]]]
    g.attack(sinbad, leo, give(g, 0, "Toil and Danger"), wall(g))
    assert seen[0].extra["steps"] == 3 and seen[0].extra["up_to"]
    assert g.board.distance(start, sinbad.pos) == 3


def test_leap_away_moves_a_fighter_of_the_combat_up_to_four_only_when_the_owner_won(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    start = hellboy.pos
    seen = []
    g.controllers[0].queue = [["hellboy"], lambda req: seen.append(req) or [pick(lambda s: g.board.distance(start, s) == 4)(req)[0]]]
    res = g.attack(sinbad, hellboy, give(g, 0, "Leap Away"), None)
    assert res.attacker_won and seen and seen[0].extra["steps"] == 4
    assert g.board.distance(start, hellboy.pos) == 4
    g2 = mk(bprd, "leonardo")
    sinbad, leo = pair(g2, "sinbad", "leonardo")
    g2.controllers[0].queue = [["leonardo"]]
    res = g2.attack(sinbad, leo, give(g2, 0, "Leap Away"), wall(g2))
    assert not res.attacker_won and g2.controllers[0].requests == []


def test_leap_away_may_move_sinbad_himself(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    start = sinbad.pos
    g.controllers[0].queue = [["sinbad"], lambda req: [pick(lambda s: g.board.distance(start, s) == 4)(req)[0]]]
    g.attack(sinbad, hellboy, give(g, 0, "Leap Away"), None)
    assert g.board.distance(start, sinbad.pos) == 4


def test_feint_cancels_every_effect_on_the_rivals_card(bprd):
    g = mk(bprd, "liz-sherman", turn=1)
    sinbad, liz = pair(g, "sinbad", "liz")
    g.actions_left = 2
    liz_atk = give(g, 1, "Flame Lash")
    res = g.attack(liz, sinbad, liz_atk, give(g, 0, "Feint"))
    assert "atk" in res.cancelled


def test_feint_played_as_an_attack_cancels_the_defenders_effects(bprd):
    g = mk(bprd, "leonardo")
    sinbad, leo = pair(g, "sinbad", "leonardo")
    flow = g.begin_attack(sinbad, leo, give(g, 0, "Feint"), wall(g))
    flow.run()
    assert flow.result.atk_value == 2


def test_momentous_shift_is_three_unless_the_fighter_started_the_turn_elsewhere(bprd):
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    start_turn(g)
    assert g.attack(sinbad, hellboy, give(g, 0, "Momentous Shift"), None).atk_value == 3
    g2 = mk(bprd)
    sinbad, hellboy = pair(g2, "sinbad", "hellboy")
    start_turn(g2)
    sinbad.pos = next(s for s in sorted(g2.board.adj[hellboy.pos]) if s != sinbad.pos and all(f.pos != s for f in g2.fighters.values() if f.alive))
    assert g2.attack(sinbad, hellboy, give(g2, 0, "Momentous Shift"), None).atk_value == 5


def test_momentous_shift_reads_the_fighter_that_plays_it(bprd):
    """The Porter walked, Sinbad did not: the Porter's Momentous Shift is 5, Sinbad's is 3."""
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    start_turn(g)
    porter = g.fighters["porter"]
    porter.pos = next(s for s in sorted(g.board.adj[hellboy.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    assert g.attack(porter, hellboy, give(g, 0, "Momentous Shift"), None).atk_value == 5
    g.actions_left = 2
    assert g.attack(sinbad, hellboy, give(g, 0, "Momentous Shift", 1), None).atk_value == 3


def test_riches_beyond_compare_draws_three_cards_as_a_scheme(bprd):
    g = mk(bprd)
    card = give(g, 0, "Riches Beyond Compare")
    assert card.is_scheme and card.usable_by("Sinbad") and not card.usable_by("The Porter")
    g.play_scheme(0, g.fighters["sinbad"], card)
    assert len(g.players[0].hand) == 3 and g.actions_left == 1
    assert card in g.players[0].discard


def test_riches_beyond_compare_with_a_short_deck_draws_what_is_left_and_exhausts(bprd):
    g = mk(bprd)
    g.players[0].deck[:] = g.players[0].deck[:1]
    hp = g.fighters["sinbad"].hp
    g.play_scheme(0, g.fighters["sinbad"], give(g, 0, "Riches Beyond Compare"))
    assert len(g.players[0].hand) == 1 and g.fighters["sinbad"].hp == hp - 2 * 2


# ---------------------------------------------------------------- the AI

def test_the_ai_counts_the_voyage_bonus_when_it_plans_a_maneuver(bprd):
    g = mk(bprd)
    to_discard(g, 0, *VOYAGES[:3])
    ai = MedusaAI(0)
    g.players[0].hand.append(g.players[0].deck.pop(0))
    acts = ai.maneuver_acts(g, Model(g, 0))
    sinbad = g.fighters["sinbad"]
    best_reach = max(g.board.distance(sinbad.pos, a.moves["sinbad"]) for a in acts if "sinbad" in a.moves)
    assert best_reach > sinbad.move
    for a in acts:
        for fid, dest in a.moves.items():
            f = g.fighters[fid]
            assert g.board.distance(f.pos, dest) <= f.move + 3 + (a.boost.boost if a.boost else 0) + (1 if a.boost and "voyage" in a.boost.tags else 0)


def test_a_full_game_of_the_bot_as_sinbad_against_itself_uses_the_voyage_cards(bprd):
    from sparring import sim
    out = sim.play(2, bot_hero="sinbad", human_hero="hellboy")
    assert out.winner != "draw"


def test_the_ai_values_a_voyage_card_with_the_pile_and_momentous_shift_with_the_walk(bprd):
    from sparring.ai_sinbad import own_value, voyage_count
    g = mk(bprd)
    sinbad, hellboy = pair(g, "sinbad", "hellboy")
    ai = MedusaAI(0)
    apes = give(g, 0, "Voyage to the City of the Man-Eating Apes")
    assert ai.card_value(g, sinbad, hellboy, apes) == 2.0
    to_discard(g, 0, *VOYAGES[:3])
    assert voyage_count(g, 0) == 3 and ai.card_value(g, sinbad, hellboy, apes) == 5.0
    shift = give(g, 0, "Momentous Shift")
    start_turn(g)
    assert ai.card_value(g, sinbad, hellboy, shift) == 3.0 and own_value(g, sinbad, shift) is None
    sinbad.pos = next(s for s in sorted(g.board.adj[hellboy.pos]) if s != sinbad.pos and all(f.pos != s for f in g.fighters.values() if f.alive))
    assert ai.card_value(g, sinbad, hellboy, shift) == 5.0


def test_the_ai_fears_a_rival_sinbads_voyage_cards_for_what_they_will_be_worth(bprd):
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("hellboy", "sinbad"), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    sinbad = g.fighters["sinbad"]
    before = Model(g, 0).committed_attack_dist(sinbad)
    to_discard(g, 1, *VOYAGES[1:5])
    model = Model(g, 0)
    assert model.voyages == 4
    assert max(v for _, v in model.committed_attack_dist(sinbad)) > max(v for _, v in before)


def test_the_searchs_cached_moves_follow_the_voyage_pile(bprd):
    """The search memoizes the legal moves by a signature of the state: a Maneuver whose reach depends on the VOYAGE cards in the
    pile must not reuse the destinations of a pile with more (they would be illegal: found by the search against a scripted Sinbad)."""
    from sparring.search.adapter import EngineState
    g = mk(bprd)
    g.players[0].hand.append(g.players[0].deck.pop(0))
    st = EngineState(g, observer=0)
    st.phase, st.partial = "maneuver_place", (None,)
    bare = st._signature()
    reach_bare = {m[1] for m in st._generate_moves()}
    to_discard(st.game, 0, *VOYAGES[:3])
    assert st._signature() != bare
    reach_pile = {m[1] for m in st._generate_moves()}
    assert reach_bare < reach_pile
