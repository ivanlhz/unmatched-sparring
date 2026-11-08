"""Tomoe Gozen on the engine, bot side (player 0 plays her, the controllers answer): ATTACK OF OPPORTUNITY (the event `left_zone`),
the attack that only targets an adjacent fighter and is played face up, the combat damage cap, a move through sidekicks, a card
that returns to the hand, and every card with the numbers printed on it. The human side (panel, FakeTTS) is in
tests/test_tomoe_gozen_human.py and the full games in tests/test_tomoe_gozen_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.combat_flow import CombatFlow
from sparring.state import Game, RuleError
from test_bigfoot_effects import Answers, pick, wall
from test_effects_combat import pair, put_adjacent


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Tomoe Gozen = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("tomoe-gozen", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def zone_exit(board, near=1):
    """(a, inside, outside): `inside` shares a zone with `a`, `outside` shares none and is `near` spaces from `inside` (walkable)."""
    for a in sorted(board.spaces):
        for inside in sorted(board.spaces):
            if inside == a or not board.share_zone(a, inside) or inside in board.adj[a] and False:
                continue
            for outside in sorted(board.spaces):
                if outside not in (a, inside) and not board.share_zone(a, outside) and board.distance(inside, outside) <= near:
                    return a, inside, outside
    raise AssertionError("no zone exit on this map")


def stage(g, foe_fid="hellboy"):
    """Tomoe on `a`, the rival hero on `inside` (her zone), the other fighters away; returns (tomoe, foe, outside)."""
    a, inside, outside = zone_exit(g.board)
    far = sorted((s for s in g.board.spaces if not g.board.share_zone(a, s) and s != outside), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.fid not in ("tomoe", foe_fid)], far):
        f.pos = s
    g.fighters["tomoe"].pos, g.fighters[foe_fid].pos = a, inside
    return g.fighters["tomoe"], g.fighters[foe_fid], outside


# ---------------------------------------------------------------- the hero

def test_tomoe_gozen_is_a_ranged_hero_with_no_sidekick(bprd):
    g = mk(bprd)
    t = g.fighters["tomoe"]
    assert (t.hp, t.move, t.ranged, t.reach, t.name) == (14, 2, True, 0, "Tomoe Gozen")
    assert [f.fid for f in g.own(0)] == ["tomoe"]
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert "tomoe-gozen" in g.fx.dsl_heroes


# ---------------------------------------------------------------- ATTACK OF OPPORTUNITY

def test_an_opposing_hero_that_walks_out_of_her_zone_takes_one_damage(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    before = h.hp
    g.move_fighter(h, outside, g.board.distance(h.pos, outside))
    assert h.hp == before - 1 and h.pos == outside


def test_staying_in_her_zone_costs_nothing(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    other = next(s for s in sorted(bprd.spaces) if s not in (t.pos, h.pos) and bprd.share_zone(t.pos, s)
                 and 0 < bprd.distance(h.pos, s) <= 3 and all(f.pos != s for f in g.fighters.values() if f.alive))
    before = h.hp
    g.move_fighter(h, other, bprd.distance(h.pos, other))
    assert h.hp == before


def test_it_fires_once_per_departure_and_is_effect_damage(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    before = h.hp
    g.place_fighter(h, outside)
    assert h.hp == before - 1                                          # one health, by a placement (no path) too
    back = next(s for s in sorted(bprd.spaces) if bprd.share_zone(t.pos, s) and s != t.pos
                and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.place_fighter(h, back)
    assert h.hp == before - 1                                          # coming back in is free


def test_a_sidekick_that_leaves_her_zone_takes_nothing(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    lobster = g.fighters["lobster"]
    lobster.pos = next(s for s in sorted(bprd.spaces) if bprd.share_zone(t.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.place_fighter(lobster, next(s for s in sorted(bprd.spaces) if not bprd.share_zone(t.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive)))
    assert lobster.hp == lobster.max_hp


def test_her_own_movement_never_fires_it(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    before = h.hp
    g.place_fighter(t, outside)
    assert h.hp == before and t.hp == t.max_hp


def test_a_rival_that_starts_outside_her_zone_takes_nothing_for_moving_around(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    h.pos = outside
    before = h.hp
    spot = next(s for s in sorted(bprd.spaces) if not bprd.share_zone(t.pos, s) and bprd.distance(outside, s) == 1
                and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.move_fighter(h, spot, 1)
    assert h.hp == before


def test_the_damage_can_defeat_a_hero_and_ends_the_game(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    h.hp = 1
    g.move_fighter(h, outside, bprd.distance(h.pos, outside))
    assert not h.alive and g.winner == 0


def test_a_defeated_tomoe_gozen_has_no_ability(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    t.alive, t.pos = False, None
    before = h.hp
    g.place_fighter(h, outside)
    assert h.hp == before


def test_a_maneuver_that_leaves_her_zone_hurts_the_rival_too(bprd):
    g = mk(bprd, turn=1)
    t, h, outside = stage(g)
    g.actions_left = 2
    g.players[1].hand.append(g.players[1].deck.pop(0))
    before = h.hp
    near = next(s for s in sorted(bprd.spaces) if not bprd.share_zone(t.pos, s) and bprd.distance(h.pos, s) <= h.move
                and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.maneuver(1, {h.fid: near})
    assert h.hp == before - 1


# ---------------------------------------------------------------- Witness My Last Battle

def test_witness_my_last_battle_is_an_adjacent_only_attack_played_face_up(bprd):
    from sparring.effects.modifiers import adjacent_only, plays_face_up
    g = mk(bprd)
    witness = give(g, 0, "Witness My Last Battle")
    assert adjacent_only(witness) and plays_face_up(witness)
    assert (witness.value, witness.boost, witness.type) == (7, 4, "attack")
    assert not adjacent_only(give(g, 0, "Piercing Shot")) and not plays_face_up(give(g, 0, "Piercing Shot"))


def test_witness_is_refused_against_a_target_that_is_not_adjacent(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    h.pos = next(s for s in sorted(bprd.spaces) if bprd.share_zone(t.pos, s) and s != t.pos and s not in bprd.adj[t.pos]
                 and all(f.pos != s for f in g.fighters.values() if f.alive))
    assert g.can_attack(t, h)                                       # ranged: she shoots across the zone with other cards
    witness = give(g, 0, "Witness My Last Battle")
    assert not g.attack_card_reaches(t, h, witness)
    with pytest.raises(RuleError):
        g.attack(t, h, witness, None)
    assert witness in g.players[0].hand


def test_witness_hits_for_seven_against_an_adjacent_fighter_and_ends_the_turn(bprd):
    g = mk(bprd)
    t, h = pair(g, "tomoe", "hellboy")
    witness = give(g, 0, "Witness My Last Battle")
    assert g.attack_card_reaches(t, h, witness)
    res = g.attack(t, h, witness, None)
    assert res.attacker_won and h.hp == h.max_hp - 7
    assert g.fx.parked == [] and g.actions_left == 0                 # the AFTER ended the turn and nothing is waiting


def test_witness_ends_the_turn_win_or_lose(bprd):
    g = mk(bprd, "leonardo")
    t, h = pair(g, "tomoe", "leonardo")
    witness = give(g, 0, "Witness My Last Battle")
    assert g.actions_left == 2
    res = g.attack(t, h, witness, wall(g), values=(-4, 0))
    assert not res.attacker_won and g.actions_left == 0                # lost against a wall: the turn ends all the same
    g2 = mk(bprd, "leonardo")
    t, h = pair(g2, "tomoe", "leonardo")
    g2.attack(t, h, give(g2, 0, "Witness My Last Battle"), None)
    assert g2.actions_left == 0


def test_the_defense_is_chosen_seeing_a_face_up_witness(bprd):
    seen = []

    class Spy(Answers):
        def choose_defense(self, game, attacker, target, attack_card=None):
            seen.append(attack_card)
            return None

    g = mk(bprd)
    g.controllers[1] = Spy()
    t, h = pair(g, "tomoe", "hellboy")
    witness = give(g, 0, "Witness My Last Battle")
    g.attack(t, h, witness)
    assert seen == [witness]
    plain = give(g, 0, "Piercing Shot")
    g.actions_left = 2
    g.attack(t, h, plain)
    assert seen[1] is None


def test_the_ai_never_offers_witness_against_a_target_two_spaces_away(bprd):
    from sparring.ai_medusa import MedusaAI, Model
    g = mk(bprd)
    t, h, outside = stage(g)
    h.pos = next(s for s in sorted(bprd.spaces) if bprd.share_zone(t.pos, s) and s != t.pos and s not in bprd.adj[t.pos]
                 and all(f.pos != s for f in g.fighters.values() if f.alive))
    give(g, 0, "Witness My Last Battle")
    ai = MedusaAI(0)
    g.actions_left = 2
    assert ai.attack_acts(g, Model(g, 0)) == []                       # Witness is the only card in the hand
    h.pos = next(s for s in sorted(bprd.adj[t.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    acts = ai.attack_acts(g, Model(g, 0))
    assert [a.card.title for a in acts] == ["Witness My Last Battle"]


# ---------------------------------------------------------------- Piercing Shot, Flash of Steel, Worthy Opponent

def test_piercing_shot_draws_two_cards_win_or_lose(bprd):
    g = mk(bprd, "leonardo")
    t, h = pair(g, "tomoe", "leonardo")
    shot = give(g, 0, "Piercing Shot")
    g.attack(t, h, shot, wall(g))
    assert len(g.players[0].hand) == 2


def test_flash_of_steel_cancels_a_heroes_card_and_hits_an_adjacent_one(bprd):
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    foe_card = give(g, 1, next(c.title for c in g.players[1].deck if c.can_defend and c.type == "defense"))
    before = leo.hp
    flow = g.begin_attack(t, leo, give(g, 0, "Flash of Steel"), foe_card)
    flow.run()
    assert "def" in flow.result.cancelled
    assert leo.hp <= before - 1                                      # the 1 damage of the AFTER (adjacent) at least


def test_flash_of_steel_against_a_sidekick_cancels_nothing(bprd):
    g = mk(bprd, "hellboy")
    t, h = pair(g, "tomoe", "hellboy")
    lobster = g.fighters["lobster"]
    put_adjacent(g, "lobster", "tomoe")
    foe_card = give(g, 1, next(c.title for c in g.players[1].deck if c.can_defend and c.usable_by("Lobster Johnson")))
    flow = g.begin_attack(t, lobster, give(g, 0, "Flash of Steel"), foe_card)
    flow.run()
    assert "def" not in flow.result.cancelled


def test_a_worthy_opponent_is_five_against_a_hero_and_three_against_a_sidekick(bprd):
    g = mk(bprd, "hellboy")
    t, h = pair(g, "tomoe", "hellboy")
    res = g.attack(t, h, give(g, 0, "A Worthy Opponent"), None)
    assert res.atk_value == 5 and h.hp == h.max_hp - 5
    g.actions_left = 2
    put_adjacent(g, "lobster", "tomoe")
    lobster = g.fighters["lobster"]
    res = g.attack(t, lobster, give(g, 0, "A Worthy Opponent", 1), None)
    assert res.atk_value == 3


def test_a_worthy_opponent_defending_is_five_against_a_hero(bprd):
    g = mk(bprd, "hellboy", turn=1)
    t, h = pair(g, "tomoe", "hellboy")
    g.actions_left = 2
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) == 4))
    res = g.attack(h, t, attack, give(g, 0, "A Worthy Opponent"))
    assert res.def_value == 5


# ---------------------------------------------------------------- Fearsome Strength

def test_fearsome_strength_may_swap_then_hits_an_adjacent_fighter(bprd):
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    a, b = t.pos, leo.pos
    g.controllers[0].queue = [[True], ["leonardo"], ["leonardo"]]
    hp = leo.hp
    g.attack(t, leo, give(g, 0, "Fearsome Strength"), wall(g))
    assert (t.pos, leo.pos) == (b, a)
    assert leo.hp <= hp - 1


def test_fearsome_strength_swap_is_optional(bprd):
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    a, b = t.pos, leo.pos
    g.controllers[0].queue = [[False]]
    g.attack(t, leo, give(g, 0, "Fearsome Strength"), wall(g))
    assert (t.pos, leo.pos) == (a, b)


def test_a_swap_with_her_never_counts_as_leaving_her_zone(bprd):
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    g.controllers[0].queue = [[True], ["leonardo"]]
    hp = leo.hp
    g.attack(t, leo, give(g, 0, "Fearsome Strength"), None)
    assert leo.hp == hp - 3 - 1                                      # 3 combat damage + the 1 of the AFTER, nothing from the swap


# ---------------------------------------------------------------- A Warrior's Way

def test_a_warriors_way_moves_the_rival_and_places_her_next_to_a_hero(bprd):
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [pick(lambda s: bprd.distance(leo.pos, s) == 3)(req)[0]],
                              lambda req: seen.append(req) or [min(req.options)]]
    hp = leo.hp
    g.attack(t, leo, give(g, 0, "A Warrior's Way"), wall(g))
    assert seen[0].extra["steps"] == 3 and seen[0].extra["up_to"]
    assert leo.pos in bprd.adj[t.pos] or t.pos in bprd.adj[leo.pos]
    assert t.pos in bprd.adj[leo.pos]


def test_a_warriors_way_on_a_sidekick_does_not_place_her(bprd):
    g = mk(bprd, "hellboy")
    t, h = pair(g, "tomoe", "hellboy")
    put_adjacent(g, "lobster", "tomoe")
    lobster = g.fighters["lobster"]
    here = t.pos
    g.controllers[0].queue = [lambda req: [max(req.options)]]
    g.attack(t, lobster, give(g, 0, "A Warrior's Way"), None)
    assert t.pos == here


def test_a_warriors_way_that_takes_a_hero_out_of_her_zone_costs_it_a_health(bprd):
    g = mk(bprd, "leonardo")
    t, leo, outside = stage(g, "leonardo")
    g.controllers[0].queue = [lambda req: [outside], lambda req: [min(req.options)]]
    hp = leo.hp
    g.attack(t, leo, give(g, 0, "A Warrior's Way"), None)
    assert leo.pos == outside and leo.hp == hp - 2 - 1              # 2 of combat, 1 of ATTACK OF OPPORTUNITY
    assert t.pos in bprd.adj[leo.pos]                                   # then she is placed next to him


# ---------------------------------------------------------------- Five Against Thousands

def test_five_against_thousands_returns_to_the_hand_for_a_discard(bprd):
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    filler = give(g, 0, "Piercing Shot")
    five = give(g, 0, "Five Against Thousands")
    g.controllers[0].queue = [[True], [filler.card_id]]
    g.attack(t, leo, five, wall(g))
    assert five in g.players[0].hand and five not in g.players[0].discard
    assert filler in g.players[0].discard


def test_five_against_thousands_stays_in_the_discard_when_declined(bprd):
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    give(g, 0, "Piercing Shot")
    five = give(g, 0, "Five Against Thousands")
    g.controllers[0].queue = [[False]]
    g.attack(t, leo, five, wall(g))
    assert five in g.players[0].discard and five not in g.players[0].hand


def test_five_against_thousands_needs_her_adjacent_to_the_opposing_fighter(bprd):
    g = mk(bprd, "leonardo")
    t, leo, outside = stage(g, "leonardo")
    far = next(s for s in sorted(bprd.spaces) if bprd.share_zone(t.pos, s) and s not in bprd.adj[t.pos] and s != t.pos
               and all(f.pos != s for f in g.fighters.values() if f.alive))
    leo.pos = far
    give(g, 0, "Piercing Shot")
    five = give(g, 0, "Five Against Thousands")
    g.controllers[0].queue = [[True]]
    g.attack(t, leo, five, wall(g))
    assert five in g.players[0].discard


def test_five_against_thousands_cannot_be_paid_with_an_empty_hand(bprd):
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    five = give(g, 0, "Five Against Thousands")
    g.controllers[0].queue = [[True]]
    g.attack(t, leo, five, wall(g))
    assert five in g.players[0].discard


# ---------------------------------------------------------------- Refuse to Retreat and Deeds Of Valor

def test_refuse_to_retreat_pins_her_for_the_rest_of_the_turn_and_makes_the_rival_discard(bprd):
    g = mk(bprd, "leonardo", turn=1)
    t, leo = pair(g, "tomoe", "leonardo")
    g.actions_left = 2
    for _ in range(3):
        g.players[1].hand.append(g.players[1].deck.pop(0))
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) <= 3))
    hand = len(g.players[1].hand)
    g.controllers[1].queue = [lambda req: [req.options[0]]]
    g.attack(leo, t, attack, give(g, 0, "Refuse to Retreat"))
    assert not g.fx.can_move(t)
    assert len(g.players[1].hand) == hand - 2                        # the attack left it; the discard made it one more
    assert g.legal_moves(t, 2) == {t.pos}


def test_refuse_to_retreat_pin_ends_with_the_turn(bprd):
    g = mk(bprd, "leonardo", turn=1)
    t, leo = pair(g, "tomoe", "leonardo")
    g.actions_left = 2
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) <= 3))
    g.attack(leo, t, attack, give(g, 0, "Refuse to Retreat"))
    assert not g.fx.can_move(t)
    g.turn, g.turn_no = 0, g.turn_no + 1
    g.fx.emit("end_of_turn", 1)
    assert g.fx.can_move(t)


def test_deeds_of_valor_caps_the_combat_damage_at_two(bprd):
    g = mk(bprd, "leonardo", turn=1)
    t, leo = pair(g, "tomoe", "leonardo")
    g.actions_left = 2
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) == 4))
    res = g.attack(leo, t, attack, give(g, 0, "Deeds of Valor"))
    assert res.atk_value - res.def_value >= 2 and t.hp == t.max_hp - 2 and res.damage == 2


def test_deeds_of_valor_takes_less_than_two_when_the_blow_is_smaller(bprd):
    g = mk(bprd, "leonardo", turn=1)
    t, leo = pair(g, "tomoe", "leonardo")
    g.actions_left = 2
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) == 3))
    res = g.attack(leo, t, attack, give(g, 0, "Deeds of Valor"))
    assert t.hp == t.max_hp - 1


def test_deeds_of_valor_does_not_cap_effect_damage(bprd):
    from sparring.effects.ops_combat import OPS
    g = mk(bprd, "leonardo", turn=1)
    t, leo = pair(g, "tomoe", "leonardo")
    flow = g.begin_attack(leo, t, give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) == 4)),
                          give(g, 0, "Deeds of Valor"))
    flow.run()
    g.damage(t, 5, "effect")
    assert t.hp == t.max_hp - 2 - 5


def test_the_damage_cap_survives_a_save_and_is_gone_after_the_combat(bprd):
    g = mk(bprd, "leonardo", turn=1)
    t, leo = pair(g, "tomoe", "leonardo")
    g.actions_left = 2
    flow = g.begin_attack(leo, t, give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) == 4)),
                          give(g, 0, "Deeds of Valor"))
    flow.run()
    assert flow.damage_caps == {"tomoe": 2}
    assert CombatFlow.from_dict(g, flow.to_dict()).damage_caps == {"tomoe": 2}
    nxt = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) == 4))
    g.actions_left = 2
    t.hp = t.max_hp
    res = g.attack(leo, t, nxt, None)
    assert t.hp == t.max_hp - res.damage and res.damage >= 4


# ---------------------------------------------------------------- Lord Kiso's Final Stand

def test_lord_kisos_final_stand_moves_up_to_three_through_sidekicks_and_heals(bprd):
    g = mk(bprd, "hellboy")
    g.actions_left = 2
    t, h = pair(g, "tomoe", "hellboy")
    t.hp = 10
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[-1]], [0]]
    g.play_scheme(0, t, give(g, 0, "Lord Kiso's Final Stand"))
    assert seen[0].extra["steps"] == 3 and seen[0].extra["through"] == "sidekicks"
    assert t.hp == 12 and g.actions_left == 1


def test_lord_kisos_final_stand_can_gain_the_action_instead(bprd):
    g = mk(bprd, "hellboy")
    g.actions_left = 2
    t, h = pair(g, "tomoe", "hellboy")
    t.hp = 10
    g.controllers[0].queue = [[], [1]]
    g.play_scheme(0, t, give(g, 0, "Lord Kiso's Final Stand"))
    assert t.hp == 10 and g.actions_left == 2


def corridor(board):
    """(a, b, c): c is two spaces from a, and b is the only space between them (every other path is longer than two)."""
    for a in sorted(board.spaces):
        for b in sorted(board.adj[a]):
            for c in sorted(board.adj[b]):
                if c != a and c not in board.adj[a] and board.adj[a] & board.adj[c] == {b}:
                    return a, b, c
    raise AssertionError("no corridor on this map")


def test_through_sidekicks_crosses_a_rival_sidekick_but_not_a_rival_hero(bprd):
    g = mk(bprd, "hellboy")
    a, b, c = corridor(bprd)
    t, h, lobster = g.fighters["tomoe"], g.fighters["hellboy"], g.fighters["lobster"]
    t.pos, lobster.pos = a, b
    h.pos = next(s for s in sorted(bprd.spaces, reverse=True) if s not in (a, b, c))
    assert c not in g.legal_moves(t, 2)                                 # a sidekick in the corridor is a wall
    assert c in g.legal_moves(t, 2, "sidekicks") and b not in g.legal_moves(t, 2, "sidekicks")      # crossed, never ended on
    assert c in g.legal_moves(t, 2, True)
    lobster.pos, h.pos = h.pos, b                                       # the rival HERO in the corridor now
    assert c not in g.legal_moves(t, 2, "sidekicks") and c in g.legal_moves(t, 2, True)


def test_the_hazard_path_of_a_move_through_sidekicks_is_not_blocked_by_them(bprd):
    g = mk(bprd, "hellboy")
    a, b, c = corridor(bprd)
    t, lobster = g.fighters["tomoe"], g.fighters["lobster"]
    t.pos, lobster.pos = a, b
    assert g.passable_enemy_spaces(t, "sidekicks") == {b} and g.passable_enemy_spaces(t, True) == frozenset()
    assert g.passable_enemy_spaces(t, False) == frozenset()


# ---------------------------------------------------------------- Confront Any Demon or God, Skirmish

def test_confront_any_demon_or_god_draws_and_strips_a_card_after_a_loss(bprd):
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    for _ in range(3):
        g.players[1].hand.append(g.players[1].deck.pop(0))
    stronger = give(g, 1, next(c.title for c in g.players[1].deck if c.type == "defense" and (c.value or 0) >= 3))
    hand = len(g.players[1].hand)
    g.controllers[0].queue = [lambda req: [req.options[0]]]
    g.attack(t, leo, give(g, 0, "Confront Any Demon or God"), stronger)
    assert len(g.players[1].hand) == hand - 2 or len(g.players[1].hand) == hand - 1


def test_skirmish_after_a_win_may_throw_the_rival_hero_out_of_her_zone(bprd):
    g = mk(bprd, "leonardo")
    t, leo, outside = stage(g, "leonardo")
    g.controllers[0].queue = [["leonardo"], lambda req: [outside]]
    hp = leo.hp
    g.attack(t, leo, give(g, 0, "Skirmish"), None)
    assert leo.pos == outside and leo.hp == hp - 4 - 1              # 4 of combat, 1 of ATTACK OF OPPORTUNITY


# ---------------------------------------------------------------- every card is on the interpreter, with the printed numbers

REAL = {
    "Witness My Last Battle": ("attack", 7, 4, 2), "Piercing Shot": ("attack", 2, 1, 3), "A Warrior's Way": ("attack", 2, 1, 2),
    "Five Against Thousands": ("attack", 4, 1, 2), "Fearsome Strength": ("attack", 3, 1, 2), "A Worthy Opponent": ("versatile", 3, 3, 3),
    "Confront Any Demon or God": ("versatile", 3, 3, 2), "Skirmish": ("versatile", 4, 1, 3), "Flash of Steel": ("versatile", 2, 1, 3),
    "Refuse to Retreat": ("defense", 3, 2, 2), "Deeds of Valor": ("defense", 2, 2, 3), "Lord Kiso's Final Stand": ("scheme", None, 2, 3),
}


def test_every_card_has_its_printed_numbers_and_an_entry_in_the_effects(bprd):
    from sparring.effects.model import load_effects
    g = mk(bprd)
    fx = load_effects("tomoe-gozen")
    deck = g.players[0].full_set
    for title, (kind, value, boost, copies) in REAL.items():
        cards = [c for c in deck if c.title == title]
        assert len(cards) == copies and (cards[0].type, cards[0].value, cards[0].boost) == (kind, value, boost), title
        assert fx.card(title) is not None
    assert len(deck) == sum(c for *_, c in REAL.values()) == 30


# ---------------------------------------------------------------- the bot

def test_the_bot_prices_leaving_her_zone_and_a_hero_that_stays_does_not_pay(bprd):
    from sparring.ai_medusa import MedusaAI
    g = mk(bprd, "hellboy")
    t, h, outside = stage(g)
    inside_other = next(s for s in sorted(bprd.spaces) if bprd.share_zone(t.pos, s) and s not in (t.pos, h.pos)
                        and all(f.pos != s for f in g.fighters.values() if f.alive))
    assert g.fx.departure_damage(h, outside) == 1 and g.fx.departure_damage(h, inside_other) == 0
    assert MedusaAI(1).exit_cost(g, h, outside) > 0 and MedusaAI(1).exit_cost(g, h, inside_other) == 0
    assert MedusaAI(1).hazard_cost(g, h, outside, 2, False) > 0
    assert g.fx.departure_damage(t, outside) == 0                          # her own move costs her nothing


def test_the_bot_does_not_pay_for_leaving_a_zone_of_a_hero_without_the_ability(bprd):
    g = mk(bprd, "hellboy")
    g2 = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("bullseye", "hellboy"), bot_player=0)
    h = g2.fighters["hellboy"]
    assert g2.fx.departure_damage(h, max(bprd.spaces)) == 0 and g.fx.departure_damage(g.fighters["tomoe"], 1) == 0


def test_a_bot_that_defends_against_a_face_up_witness_picks_a_card_that_blocks_it(bprd):
    from sparring.ai_medusa import MedusaAI
    g = mk(bprd, "leonardo", turn=0)
    t, leo = pair(g, "tomoe", "leonardo")
    witness = give(g, 0, "Witness My Last Battle")
    wall_card = wall(g)
    ai = MedusaAI(1)
    assert ai.choose_defense(g, t, leo, attack_card=witness) is not None
    assert ai.choose_defense(g, t, leo, attack_card=witness).title == wall_card.title


def test_the_bot_values_a_worthy_opponent_at_five_against_a_hero_and_deeds_of_valor_as_a_capped_defense(bprd):
    from sparring.ai_medusa import MedusaAI, Model
    g = mk(bprd, "hellboy")
    t, h = pair(g, "tomoe", "hellboy")
    worthy, piercing = give(g, 0, "A Worthy Opponent"), give(g, 0, "Piercing Shot")
    ai = MedusaAI(0)
    assert ai.card_value(g, t, h, worthy) == 5.0
    put_adjacent(g, "lobster", "tomoe")
    assert ai.card_value(g, t, g.fighters["lobster"], worthy) == 3.0
    ai._attacker = h
    deeds, training = give(g, 0, "Deeds of Valor"), give(g, 0, "Refuse to Retreat")
    big = [(1.0, 9)]
    model = Model(g, 0)
    capped = ai.eval_defense(g, model, big, t, deeds)
    uncapped_same_value = ai.eval_defense(g, model, big, t, give(g, 0, "Skirmish"))
    assert capped > uncapped_same_value                                  # 9 - 2 = 7 damage without the cap, 2 with it


def test_a_bot_with_witness_in_hand_pays_for_the_actions_it_will_lose(bprd):
    from sparring.ai_medusa import MedusaAI, Model
    g = mk(bprd, "leonardo")
    t, leo = pair(g, "tomoe", "leonardo")
    witness, shot = give(g, 0, "Witness My Last Battle"), give(g, 0, "Fearsome Strength")
    ai = MedusaAI(0)
    g.actions_left = 2
    two = ai.attack_outcome(g, Model(g, 0), t, leo, witness)[0]
    g.actions_left = 1
    one = ai.attack_outcome(g, Model(g, 0), t, leo, witness)[0]
    assert one > two                                                      # the last action loses nothing when the turn ends


def test_the_bot_takes_five_against_thousands_back_only_for_a_card_it_values_less(bprd):
    from sparring.ai_effects import EffectAI
    from sparring.effects.choose import ChoiceRequest
    g = mk(bprd, "leonardo")
    five = give(g, 0, "Five Against Thousands")
    req = ChoiceRequest("optional", 0, [True, False], 1, 1, five.card_id, "k", "do it?", {"returns_card": five.card_id}, 0)
    ai = EffectAI(0)
    for title, pays in (("Lord Kiso's Final Stand", True), ("Deeds of Valor", True), ("Witness My Last Battle", False)):
        g.players[0].hand[:] = [give(g, 0, title)]
        assert ai._returns_card_pays(g, req) is pays, title                  # a weak card pays for the 4; the 7 is worth more than it
    g.players[0].hand[:] = []
    assert ai._returns_card_pays(g, req) is False                            # nothing to discard: no price to pay


def test_the_search_samples_a_face_up_attack_into_the_attackers_hand(bprd):
    """Regression: a face-up attack (Witness My Last Battle) the bot defends against is in the sampled hand of the attacker."""
    from sparring.search.adapter import EngineState, Knowledge
    g = mk(bprd, "bigfoot", turn=0)
    t, foe = pair(g, "tomoe", "bigfoot")
    witness = give(g, 0, "Witness My Last Battle")
    for _ in range(4):
        g.players[0].hand.append(g.players[0].deck.pop(0))
    wall(g)                                                                  # the bot holds a defense, so the search really has a choice
    state = EngineState(g, observer=1, knowledge=Knowledge.from_game(g, 1), pending=(t.fid, foe.fid, witness))
    import random
    for seed in range(20):
        sample = state.clone()
        sample.determinize(1, random.Random(seed))
        assert witness in sample.game.players[0].hand, seed
