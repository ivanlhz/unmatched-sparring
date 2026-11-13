"""Philippa on the engine, bot side (player 0 plays the hero, the controllers answer): her figures, TWO STEPS AHEAD and every card with
the numbers printed on it (read from sheet 176 on 2026-11-13). The human side (panel, FakeTTS) is in tests/test_philippa_human.py and the
full games in tests/test_philippa_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import hand_filler, pair, put_adjacent


def mk(bprd, foe="hellboy", seed=3, turn=0):
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("philippa", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def start_turn(g):
    g.fx.emit("start_of_turn", g.turn)


def far_from(g, fid):
    """A free space that shares no zone with `fid`."""
    me = g.fighters[fid]
    return max(s for s in g.board.spaces if not g.board.share_zone(me.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))


# ---------------------------------------------------------------- the hero and her sidekick

def test_philippa_is_a_ranged_12_life_hero_with_a_melee_dijkstra(bprd):
    g = mk(bprd)
    h, d = g.fighters["philippa"], g.fighters["dijkstra"]
    assert (h.hero, h.hp, h.move, h.ranged, h.name) == (True, 12, 2, True, "Philippa")
    assert (d.hero, d.hp, d.move, d.ranged, d.name) == (False, 6, 2, False, "Dijkstra")
    assert [f.fid for f in g.own(0)] == ["philippa", "dijkstra"] and g.hero(0) is h
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629 and "philippa" in g.fx.dsl_heroes


def test_the_sheet_follows_the_images(bprd):
    deck = {c.card_id: c for c in mk(bprd).players[0].full_set}
    assert [deck[17600 + i].title for i in (0, 3, 6, 8, 10, 13, 15, 18, 20, 22, 24, 26, 28)] == [
        "Owlform", "Lightning bolt", "Chain lightning", "Regicide", "Spellbreaker", "Cunning", "Redanian plot", "Paralyzing fetters",
        "Blinding dust", "Do my bidding", "Polymorphy", "Backup plan", "Spymaster's ruse"]
    assert deck[17628].fighter == deck[17629].fighter == "Dijkstra" and deck[17600].fighter == "Philippa" and deck[17608].fighter == "any"


# ---------------------------------------------------------------- TWO STEPS AHEAD

def test_at_the_end_of_her_turn_she_may_draw_until_she_holds_four(bprd):
    g = mk(bprd)
    hand_filler(g, 0, 1)
    g.controllers[0].queue = [[True]]
    deck = len(g.players[0].deck)
    g.end_turn()
    assert len(g.players[0].hand) == 4 and len(g.players[0].deck) == deck - 3


def test_declining_draws_nothing(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[False]]
    g.end_turn()
    assert len(g.players[0].hand) == 0


@pytest.mark.parametrize("held", [4, 5, 6])
def test_with_four_cards_or_more_there_is_nothing_to_draw_and_nothing_is_asked(bprd, held):
    g = mk(bprd)
    hand_filler(g, 0, held)
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert len(g.players[0].hand) == held and g.controllers[0].queue == [[True]]


def test_an_empty_hand_draws_four(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert len(g.players[0].hand) == 4


def test_only_her_own_turn_ends_with_the_draw(bprd):
    g = mk(bprd, turn=1)
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert len(g.players[0].hand) == 0


# ---------------------------------------------------------------- Owlform

@pytest.mark.parametrize("n", [0, 1, 3])
def test_owlform_is_worth_three_plus_one_per_card_discarded(bprd, n):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    junk = hand_filler(g, 0, 3)
    g.controllers[0].queue = [[c.card_id for c in junk[:n]]]
    res = g.attack(ph, foe, give(g, 0, "Owlform"), None)
    assert res.atk_value == 3 + n and foe.hp == foe.max_hp - 3 - n
    assert all(c in g.players[0].discard for c in junk[:n]) and len(g.players[0].hand) == 3 - n


# ---------------------------------------------------------------- Lightning bolt and Chain lightning

def zone_foes(g, ph):
    return [f for f in g.fighters.values() if f.owner == 1 and f.alive and f.pos is not None and g.board.share_zone(ph.pos, f.pos)]


def test_lightning_bolt_hits_every_opposing_fighter_in_her_zone_when_she_has_not_maneuvered(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    lobster = g.fighters["lobster"]
    lobster.pos = next(s for s in sorted(g.board.spaces) if g.board.share_zone(ph.pos, s) and s not in (ph.pos, foe.pos)
                       and all(f.pos != s for f in g.fighters.values() if f.alive))
    outside = g.fighters["dijkstra"]
    outside.pos = far_from(g, "philippa")
    hp, lhp, dhp = foe.hp, lobster.hp, outside.hp
    g.attack(ph, foe, give(g, 0, "Lightning bolt"), give(g, 1, "B.P.R.D. Training"))
    assert lobster.hp == lhp - 1 and outside.hp == dhp
    assert foe.hp <= hp                                              # the combat itself plus the 1 of the AFTER


def test_lightning_bolt_does_nothing_after_a_maneuver_this_turn(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    lobster = g.fighters["lobster"]
    lobster.pos = next(s for s in sorted(g.board.spaces) if g.board.share_zone(ph.pos, s) and s not in (ph.pos, foe.pos)
                       and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.fx.maneuvers = 1
    lhp = lobster.hp
    g.attack(ph, foe, give(g, 0, "Lightning bolt"), None)
    assert lobster.hp == lhp


def test_lightning_bolt_counts_the_combat_target_too(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    wall = give(g, 1, "B.P.R.D. Training")
    res = g.attack(ph, foe, give(g, 0, "Lightning bolt"), wall)
    assert foe.hp == foe.max_hp - max(0, 3 - res.def_value) - 1


def one_zone_board(g, ph):
    """A space of exactly one zone for Philippa, or None when the map has none."""
    for s in sorted(g.board.spaces):
        if len(g.board.zones(s)) == 1 and all(f.pos != s for f in g.fighters.values() if f.alive):
            return s
    return None


def test_chain_lightning_with_one_zone_asks_nothing_and_hits_that_zones_foes(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    spot = one_zone_board(g, ph)
    assert spot is not None
    ph.pos = spot
    foe.pos = next(s for s in sorted(g.board.adj[spot]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    near = [f for f in zone_foes(g, ph) if f is not foe]
    hp = {f.fid: f.hp for f in zone_foes(g, ph)}
    g.controllers[0].queue = []
    g.attack(ph, foe, give(g, 0, "Chain lightning"), give(g, 1, "B.P.R.D. Training"))
    for f in near:
        assert f.hp == hp[f.fid] - 1
    assert not g.controllers[0].requests or all(r.kind != "effect" for r in g.controllers[0].requests)


def test_chain_lightning_with_several_zones_asks_which_one(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    multi = next(s for s in sorted(g.board.spaces) if len(g.board.zones(s)) > 1 and all(f.pos != s for f in g.fighters.values() if f.alive))
    ph.pos = multi
    zones = sorted(g.board.zones(multi))
    by_zone = {z: next((s for s in sorted(g.board.spaces) if z in g.board.zones(s) and not (g.board.zones(s) - {z}) and s != multi
                        and all(f.pos != s for f in g.fighters.values() if f.alive)), None) for z in zones}
    target_zone = next(z for z in zones if by_zone[z] is not None)
    other = g.fighters["lobster"]
    other.pos = by_zone[target_zone]
    foe.pos = next(s for s in sorted(g.board.adj[multi]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[zones.index(target_zone)]]
    lhp = other.hp
    g.attack(ph, foe, give(g, 0, "Chain lightning"), give(g, 1, "B.P.R.D. Training"))
    asked = [r for r in g.controllers[0].requests if r.kind == "effect" and r.extra.get("tag") == "zone"]
    assert len(asked) == 1 and asked[0].extra["labels"] == zones
    assert other.hp == lhp - 1


def test_a_real_maneuver_switches_the_lightning_bolt_off(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    lobster = g.fighters["lobster"]
    lobster.pos = next(s for s in sorted(g.board.spaces) if g.board.share_zone(ph.pos, s) and s not in (ph.pos, foe.pos)
                       and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.maneuver(0, {})
    assert g.fx.maneuvers == 1
    g.actions_left = 2
    lhp = lobster.hp
    g.attack(ph, foe, give(g, 0, "Lightning bolt"), None)
    assert lobster.hp == lhp


# ---------------------------------------------------------------- Regicide

def test_regicide_is_six_against_a_hero_and_four_against_a_sidekick(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    assert g.attack(ph, foe, give(g, 0, "Regicide"), None).atk_value == 6
    g2 = mk(bprd)
    ph2, side = pair(g2, "philippa", "lobster")
    assert g2.attack(ph2, side, give(g2, 0, "Regicide"), None).atk_value == 4


# ---------------------------------------------------------------- Spellbreaker, Fetters, Redanian plot, Cunning

def test_spellbreaker_cancels_the_rivals_effects_and_ends_the_turn(bprd):
    g = mk(bprd, foe="leonardo")
    ph, leo = pair(g, "philippa", "leonardo")
    flow = g.begin_attack(ph, leo, give(g, 0, "Spellbreaker"), give(g, 1, "Feint") if any(c.title == "Feint" for c in g.players[1].full_set)
                          else give(g, 1, next(c.title for c in g.players[1].deck if c.can_defend)))
    flow.run()
    assert flow.is_cancelled("def") and g.actions_left == 0


def test_spellbreaker_played_in_defense_ends_the_attackers_turn(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    atk = next(c for c in g.players[1].deck if c.can_attack and c.usable_by(leo.name))
    g.players[1].deck.remove(atk)
    g.players[1].hand.append(atk)
    g.attack(leo, ph, atk, give(g, 0, "Spellbreaker"))
    assert g.actions_left == 0


def test_paralyzing_fetters_freezes_the_rivals_value_at_its_printed_one(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    atk = next(c for c in g.players[1].deck if c.can_attack and c.usable_by(leo.name) and c.value)
    g.players[1].deck.remove(atk)
    g.players[1].hand.append(atk)
    res = g.attack(leo, ph, atk, give(g, 0, "Paralyzing fetters"))
    assert res.atk_value == atk.value


def test_redanian_plot_the_opponent_discards_a_card_or_their_value_counts_nothing(bprd):
    g = mk(bprd, foe="leonardo")
    ph, leo = pair(g, "philippa", "leonardo")
    hand_filler(g, 1, 2)
    defense = give(g, 1, next(c.title for c in g.players[1].deck if c.can_defend and (c.value or 0) >= 3))
    g.controllers[1].queue = [[False]]
    res = g.attack(ph, leo, give(g, 0, "Redanian plot"), defense)
    assert res.def_value == 0 and len(g.players[1].hand) == 2
    g2 = mk(bprd, foe="leonardo")
    ph2, leo2 = pair(g2, "philippa", "leonardo")
    hand_filler(g2, 1, 2)
    defense2 = give(g2, 1, defense.title)
    g2.controllers[1].queue = [[True]]
    res2 = g2.attack(ph2, leo2, give(g2, 0, "Redanian plot"), defense2)
    assert res2.def_value == defense.value and len(g2.players[1].hand) == 1        # two fillers and the defense played: one discarded


def test_redanian_plot_with_an_empty_hand_cannot_be_paid(bprd):
    g = mk(bprd, foe="leonardo")
    ph, leo = pair(g, "philippa", "leonardo")
    defense = give(g, 1, next(c.title for c in g.players[1].deck if c.can_defend and (c.value or 0) >= 3))
    res = g.attack(ph, leo, give(g, 0, "Redanian plot"), defense)
    assert res.def_value == 0


def test_cunning_the_opponent_discards_a_card_or_takes_two(bprd):
    g = mk(bprd, foe="leonardo")
    ph, leo = pair(g, "philippa", "leonardo")
    hand_filler(g, 1, 2)
    g.controllers[1].queue = [[False]]
    g.attack(ph, leo, give(g, 0, "Cunning"), None)
    assert leo.hp == leo.max_hp - 4 - 2 and len(g.players[1].hand) == 2
    g2 = mk(bprd, foe="leonardo")
    ph2, leo2 = pair(g2, "philippa", "leonardo")
    hand_filler(g2, 1, 2)
    g2.controllers[1].queue = [[True]]
    g2.attack(ph2, leo2, give(g2, 0, "Cunning"), None)
    assert leo2.hp == leo2.max_hp - 4 and len(g2.players[1].hand) == 1


def test_cunning_against_an_empty_hand_deals_the_two(bprd):
    g = mk(bprd, foe="leonardo")
    ph, leo = pair(g, "philippa", "leonardo")
    g.attack(ph, leo, give(g, 0, "Cunning"), None)
    assert leo.hp == leo.max_hp - 6


# ---------------------------------------------------------------- Blinding dust

def test_blinding_dust_discards_a_card_and_hits_for_its_boost(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    spare = give(g, 0, "Owlform")                                         # BOOST 3
    atk = next(c for c in g.players[1].deck if c.can_attack and c.usable_by(leo.name))
    g.players[1].deck.remove(atk)
    g.players[1].hand.append(atk)
    g.controllers[0].queue = [[spare.card_id]]
    hp = leo.hp
    g.attack(leo, ph, atk, give(g, 0, "Blinding dust"))
    assert spare in g.players[0].discard and leo.hp == hp - 3


def test_blinding_dust_declined_deals_nothing(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    give(g, 0, "Owlform")
    atk = next(c for c in g.players[1].deck if c.can_attack and c.usable_by(leo.name))
    g.players[1].deck.remove(atk)
    g.players[1].hand.append(atk)
    g.controllers[0].queue = [[]]
    hp = leo.hp
    g.attack(leo, ph, atk, give(g, 0, "Blinding dust"))
    assert leo.hp == hp and len(g.players[0].hand) == 1


def test_blinding_dust_with_a_card_that_prints_no_boost_deals_nothing(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    zero = give(g, 0, "Spymaster's ruse")
    zero_boost = zero.boost
    atk = next(c for c in g.players[1].deck if c.can_attack and c.usable_by(leo.name))
    g.players[1].deck.remove(atk)
    g.players[1].hand.append(atk)
    g.controllers[0].queue = [[zero.card_id]]
    hp = leo.hp
    g.attack(leo, ph, atk, give(g, 0, "Blinding dust"))
    assert leo.hp == hp - zero_boost


# ---------------------------------------------------------------- Do my bidding

def attack_cards(g, player, fighter, n=3):
    out = [c for c in g.players[player].deck if c.can_attack and c.usable_by(fighter.name) and c.value]
    return out[:n]


def test_do_my_bidding_makes_the_rival_play_the_card_the_owner_picks(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    weak, strong = sorted(attack_cards(g, 1, leo, 6), key=lambda c: c.value)[0], sorted(attack_cards(g, 1, leo, 6), key=lambda c: c.value)[-1]
    assert weak.value < strong.value
    for c in (weak, strong):
        g.players[1].deck.remove(c)
        g.players[1].hand.append(c)
    g.controllers[0].queue = [[weak.card_id]]
    played = strong
    res = g.attack(leo, ph, played, give(g, 0, "Do my bidding"))
    assert res.atk_card.card_id == weak.card_id and strong in g.players[1].hand and weak in g.players[1].discard
    assert res.atk_value == weak.value


def test_do_my_bidding_choosing_the_same_card_changes_nothing(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    a, b = attack_cards(g, 1, leo, 2)
    for c in (a, b):
        g.players[1].deck.remove(c)
        g.players[1].hand.append(c)
    g.controllers[0].queue = [[a.card_id]]
    res = g.attack(leo, ph, a, give(g, 0, "Do my bidding"))
    assert res.atk_card.card_id == a.card_id and a in g.players[1].discard


def test_do_my_bidding_with_an_empty_rival_hand_leaves_the_card(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    (a,) = attack_cards(g, 1, leo, 1)
    g.players[1].deck.remove(a)
    g.players[1].hand.append(a)
    res = g.attack(leo, ph, a, give(g, 0, "Do my bidding"))
    assert res.atk_card.card_id == a.card_id


def test_do_my_bidding_the_new_cards_own_effects_run(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    plain = next(c for c in attack_cards(g, 1, leo, 20) if not c.text)
    drawer = next((c for c in g.players[1].deck if c.can_attack and c.usable_by(leo.name) and "AFTER COMBAT" in (c.text or "")), None)
    if drawer is None:
        pytest.skip("no attack with an AFTER in Leonardo's deck")
    for c in (plain, drawer):
        g.players[1].deck.remove(c)
        g.players[1].hand.append(c)
    g.controllers[0].queue = [[drawer.card_id]]
    res = g.attack(leo, ph, plain, give(g, 0, "Do my bidding"))
    assert res.atk_card.card_id == drawer.card_id


# ---------------------------------------------------------------- Polymorphy

def test_polymorphy_places_philippa_anywhere_and_her_move_becomes_five(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    spot = far_from(g, "philippa")
    g.controllers[0].queue = [[spot]]
    poly = give(g, 0, "Polymorphy")
    g.play_scheme(0, ph, poly)
    assert ph.pos == spot and ph.move == 5 and g.fx.ongoing_card_id(0) == poly.card_id
    assert g.fighters["dijkstra"].move == 2


def test_polymorphy_lapses_at_the_end_of_her_turn_without_a_foe_in_her_zone(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    foe.pos = far_from(g, "philippa")
    poly = give(g, 0, "Polymorphy")
    g.controllers[0].queue = [[far_from(g, "hellboy")]]
    g.play_scheme(0, ph, poly)
    assert ph.move == 5
    for f in g.fighters.values():
        if f.owner == 1:
            if g.board.share_zone(ph.pos, f.pos):
                f.pos = far_from(g, "philippa")
    g.controllers[0].queue = [[False]]
    g.end_turn()
    assert g.fx.ongoing_card_id(0) is None and ph.move == 2 and poly in g.players[0].discard


def test_polymorphy_stays_while_an_opposing_fighter_shares_a_zone_with_her(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    poly = give(g, 0, "Polymorphy")
    g.controllers[0].queue = [[far_from(g, "hellboy")]]
    g.play_scheme(0, ph, poly)
    foe.pos = next(s for s in sorted(g.board.spaces) if g.board.share_zone(ph.pos, s) and s != ph.pos
                   and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[False]]
    g.end_turn()
    assert g.fx.ongoing_card_id(0) == poly.card_id and ph.move == 5


def test_a_second_ongoing_replaces_polymorphy_and_the_move_goes_back(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    g.controllers[0].queue = [[far_from(g, "hellboy")]]
    g.play_scheme(0, ph, give(g, 0, "Polymorphy"))
    assert ph.move == 5
    g.fx.take_ongoing(0)
    assert ph.move == 2


def test_the_move_of_five_is_what_a_maneuver_can_use(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    g.controllers[0].queue = [[far_from(g, "hellboy")]]
    g.play_scheme(0, ph, give(g, 0, "Polymorphy"))
    assert max(g.board.distance(ph.pos, d) for d in g.legal_moves(ph, ph.move)) > 2


# ---------------------------------------------------------------- Backup plan

def test_backup_plan_sets_her_health_to_five(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    g.controllers[0].queue = [[0]]
    g.play_scheme(0, ph, give(g, 0, "Backup plan"))
    assert ph.hp == 5


def test_backup_plan_may_instead_draw_three(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    g.controllers[0].queue = [[1]]
    g.play_scheme(0, ph, give(g, 0, "Backup plan"))
    assert ph.hp == 12 and len(g.players[0].hand) == 3


# ---------------------------------------------------------------- Spymaster's ruse

def test_spymaster_ruse_the_opponent_reveals_four_the_owner_discards_two_and_they_draw_two(bprd):
    g = mk(bprd, foe="leonardo")
    dij = g.fighters["dijkstra"]
    hand = hand_filler(g, 1, 6)
    reveal = [c.card_id for c in hand[:4]]
    g.controllers[1].queue = [reveal]
    g.controllers[0].queue = [[reveal[0], reveal[2]]]
    deck = len(g.players[1].deck)
    g.play_scheme(0, dij, give(g, 0, "Spymaster's ruse"))
    assert hand[0] in g.players[1].discard and hand[2] in g.players[1].discard
    assert len(g.players[1].hand) == 6 - 2 + 2 and len(g.players[1].deck) == deck - 2
    assert {c.card_id for c in g.players[1].hand} >= {hand[1].card_id, hand[3].card_id, hand[4].card_id, hand[5].card_id}


def test_spymaster_ruse_with_fewer_than_four_cards_reveals_them_all(bprd):
    g = mk(bprd, foe="leonardo")
    dij = g.fighters["dijkstra"]
    hand = hand_filler(g, 1, 3)
    g.controllers[1].queue = [[c.card_id for c in hand]]
    g.controllers[0].queue = [[hand[1].card_id, hand[2].card_id]]
    g.play_scheme(0, dij, give(g, 0, "Spymaster's ruse"))
    assert len(g.players[1].hand) == 1 + 2 and hand[1] in g.players[1].discard


def test_spymaster_ruse_with_an_empty_hand_still_draws_two(bprd):
    g = mk(bprd, foe="leonardo")
    g.play_scheme(0, g.fighters["dijkstra"], give(g, 0, "Spymaster's ruse"))
    assert len(g.players[1].hand) == 2


def test_only_dijkstra_plays_the_ruse(bprd):
    g = mk(bprd)
    ruse = give(g, 0, "Spymaster's ruse")
    assert ruse.usable_by("Dijkstra") and not ruse.usable_by("Philippa")
    assert give(g, 0, "Polymorphy").usable_by("Philippa") and not give(g, 0, "Backup plan").usable_by("Dijkstra")
