"""Yennenga's cards and ability on the interpreter, bot side (player 0 plays Yennenga, the controllers answer). The human side
(panel, FakeTTS) is in tests/test_yennenga_human.py and the full games in tests/test_yennenga_matrix.py. The numbers are the ones
printed on the real cards (data/heroes/yennenga.json)."""
from __future__ import annotations

from conftest import give
from sparring.state import Game
from test_bigfoot_effects import Answers, empty_spaces
from test_effects_combat import hp, pair


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Yennenga = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("yennenga", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def foe_attack(g, title="Service Pistol"):
    return give(g, 1, title)


def archers(g):
    return [g.fighters["archer1"], g.fighters["archer2"]]


def stack(g, hero_fid="yennenga", with_archers=2):
    """Yennenga and her Archers on three spaces of one zone (everybody else parked away from them)."""
    board = g.board
    yen = g.fighters[hero_fid]
    zone = next(z for z in sorted(board.spaces) if len([s for s in board.spaces if board.share_zone(z, s)]) >= 4)
    mates = [zone] + [s for s in sorted(board.spaces) if s != zone and board.share_zone(zone, s)]
    yen.pos = mates[0]
    for a, s in zip(archers(g)[:with_archers], mates[1:]):
        a.pos = s
    taken = set(mates[:1 + with_archers])
    far = [s for s in sorted(board.spaces, reverse=True) if s not in taken and not board.share_zone(zone, s)]
    placed = {"yennenga", *(a.fid for a in archers(g)[:with_archers])}
    for f in g.fighters.values():
        if f.alive and f.fid not in placed:
            f.pos = far.pop(0)
    return yen


# ---------------------------------------------------------------- the figures and the sheet

def test_yennenga_is_interpreted_and_has_the_printed_figures(bprd):
    g = mk(bprd)
    assert "yennenga" in g.fx.dsl_heroes
    assert [f.fid for f in g.own(0)] == ["yennenga", "archer1", "archer2"]
    yen, a1, a2 = g.fighters["yennenga"], *archers(g)
    assert (yen.hp, yen.move, a1.hp, a1.move, a2.hp) == (15, 2, 2, 2, 2)
    assert yen.ranged and a1.ranged and a1.name == "Archer"
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629


def test_the_sheet_follows_the_images(bprd):
    deck = {c.card_id: c for c in mk(bprd).players[0].full_set}
    by_idx = lambda i: deck[17600 + i]
    assert [by_idx(i).title for i in (0, 3, 6, 9, 12, 15, 17, 20, 22, 24, 26, 28)] == [
        "Rain of Arrows", "Surprise Volley", "Point Blank", "Stallion Charge", "Jaws of the Beast", "Skirmish", "Momentous Shift",
        "Pin the Prey", "Divide and Conquer", "Shield Formation", "One With The Land", "Master of the Hunt"]
    assert {by_idx(i).fighter for i in (3, 4, 5, 15, 16, 17, 18, 19)} == {"any"}
    assert {by_idx(i).fighter for i in (20, 21, 22, 23)} == {"Archer"}
    assert {by_idx(i).fighter for i in (0, 1, 2, 6, 7, 8, 9, 10, 11, 12, 13, 14, 24, 25, 26, 27, 28, 29)} == {"Yennenga"}


# ---------------------------------------------------------------- the ability, combat damage

def test_the_archers_take_the_damage_the_owner_assigns_and_yennenga_the_rest(bprd):
    g = mk(bprd, turn=1)
    yen = stack(g)
    a1, a2 = archers(g)
    hellboy = g.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(g.board.adj[yen.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[1], [1]]                          # one point to each Archer
    atk = foe_attack(g)
    res = g.attack(hellboy, yen, atk, None)
    blow = atk.value
    assert res.damage == blow and blow >= 3
    assert (a1.hp, a2.hp, yen.hp) == (1, 1, 15 - (blow - 2))


def test_an_archer_never_takes_more_than_its_remaining_life_and_falls_at_zero(bprd):
    g = mk(bprd, turn=1)
    yen = stack(g)
    a1, a2 = archers(g)
    hellboy = g.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(g.board.adj[yen.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [lambda req: seen.append(req.options) or [max(req.options)]] * 2
    seen = []
    atk = foe_attack(g)
    g.attack(hellboy, yen, atk, None)
    assert all(max(o) <= 2 for o in seen)                        # 2 life: never more than 2
    assert not a1.alive and a1.hp <= 0 and g.fighters["archer1"].died_at is not None
    assert yen.hp == 15 - max(0, atk.value - 2 - 2)


def test_an_archer_out_of_her_zone_cannot_take_damage(bprd):
    g = mk(bprd, turn=1)
    yen = stack(g, with_archers=1)
    a1, a2 = archers(g)
    hellboy = g.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(g.board.adj[yen.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    far = max((s for s in g.board.spaces if not g.board.share_zone(yen.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive)))
    a2.pos = far
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options)]] * 3
    g.attack(hellboy, yen, foe_attack(g), None)
    assert [r.extra["assign"] for r in seen] == ["archer1"]       # only the Archer in her zone is asked
    assert a2.hp == 2


def test_a_defeated_archer_is_not_asked_and_with_none_in_her_zone_nothing_is_asked(bprd):
    g = mk(bprd, turn=1)
    yen = stack(g, with_archers=0)
    hellboy = g.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(g.board.adj[yen.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = []
    atk = foe_attack(g)
    res = g.attack(hellboy, yen, atk, None)
    assert yen.hp == 15 - atk.value and not g.controllers[0].requests


def test_the_blow_is_not_assigned_when_it_is_zero(bprd):
    g = mk(bprd, turn=1)
    yen = stack(g)
    hellboy = g.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(g.board.adj[yen.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    res = g.attack(hellboy, yen, foe_attack(g), give(g, 0, "Shield Formation"), values=(-9, 0))
    assert res.damage == 0 and not [r for r in g.controllers[0].requests if r.extra.get("assign")]


# ---------------------------------------------------------------- the ability, effect damage

def test_effect_damage_to_yennenga_can_be_assigned_too(bprd):
    g = mk(bprd)
    yen = stack(g)
    a1, a2 = archers(g)
    g.controllers[0].queue = [[2], [0]]
    from sparring.effects.ops_core import OPS
    from sparring.effects.run import Ctx, EffectRun
    from sparring.effects.choose import ControllerChooser
    run = EffectRun([{"op": "damage", "target": {"side": "enemy", "kind": "hero"}, "amount": 3}], Ctx(owner=1, this_fid="hellboy"))
    run.run(g, {0: ControllerChooser(), 1: ControllerChooser()})
    assert (a1.hp, yen.hp) == (0, 15 - 1) and not a1.alive and a2.hp == 2


# ---------------------------------------------------------------- Surprise Volley

def volley_scene(bprd, dead=1):
    g = mk(bprd)
    yen = stack(g, with_archers=0)
    hellboy = g.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(g.board.adj[yen.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    for a in archers(g)[:dead]:
        g.defeat(a)
    return g, yen, hellboy


def test_surprise_volley_returns_a_defeated_archer_in_the_opposing_zone_and_it_is_the_attacker(bprd):
    g, yen, hellboy = volley_scene(bprd)
    a1 = g.fighters["archer1"]
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options)]]       # the space the Archer comes back to
    actions = g.actions_left
    res = g.attack(yen, hellboy, give(g, 0, "Surprise Volley"), None)
    assert a1.alive and a1.hp == 2 and g.board.share_zone(a1.pos, hellboy.pos)
    assert res.attacker == "archer1" and res.target == "hellboy"
    assert g.actions_left == actions - 1                           # the attack's own action, no extra one
    assert seen[0].kind == "optional"


def test_surprise_volley_without_a_defeated_archer_gains_an_action(bprd):
    g, yen, hellboy = volley_scene(bprd, dead=0)
    actions = g.actions_left
    res = g.attack(yen, hellboy, give(g, 0, "Surprise Volley"), None)
    assert res.attacker == "yennenga" and g.actions_left == actions - 1 + 1


def test_surprise_volley_declined_gains_an_action_and_the_archer_stays_down(bprd):
    g, yen, hellboy = volley_scene(bprd)
    g.controllers[0].queue = [[False]]
    actions = g.actions_left
    res = g.attack(yen, hellboy, give(g, 0, "Surprise Volley"), None)
    assert res.attacker == "yennenga" and not g.fighters["archer1"].alive and g.actions_left == actions


def test_an_archer_may_play_surprise_volley_and_the_returned_one_replaces_it(bprd):
    g, yen, hellboy = volley_scene(bprd)
    a2 = g.fighters["archer2"]
    a2.pos = next(s for s in sorted(g.board.spaces) if s != hellboy.pos and g.board.share_zone(hellboy.pos, s)
                  and all(f.pos != s for f in g.fighters.values() if f.alive))
    res = g.attack(a2, hellboy, give(g, 0, "Surprise Volley"), None)
    assert res.attacker == "archer1" and g.fighters["archer1"].alive


# ---------------------------------------------------------------- Shield Formation

def shield_scene(bprd, dead=1):
    g = mk(bprd, turn=1)
    yen = stack(g, with_archers=0)
    hellboy = g.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(g.board.adj[yen.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    for a in archers(g)[:dead]:
        g.defeat(a)
    return g, yen, hellboy


def test_shield_formation_returns_a_defeated_archer_when_the_opponent_does_not_discard(bprd):
    g, yen, hellboy = shield_scene(bprd)
    g.controllers[1].queue = [[False]]
    g.players[1].hand.extend(g.players[1].deck[:2])
    g.attack(hellboy, yen, foe_attack(g), give(g, 0, "Shield Formation"))
    a1 = g.fighters["archer1"]
    assert a1.alive and a1.hp == 2 and g.board.share_zone(a1.pos, yen.pos)


def test_shield_formation_discarding_keeps_the_archer_down(bprd):
    g, yen, hellboy = shield_scene(bprd)
    g.players[1].hand.extend(g.players[1].deck[:2])
    discard = len(g.players[1].discard)
    g.controllers[1].queue = [[True]]
    g.attack(hellboy, yen, foe_attack(g), give(g, 0, "Shield Formation"))
    assert not g.fighters["archer1"].alive and len(g.players[1].discard) == discard + 2       # the attack card and the discarded one


def test_shield_formation_against_an_empty_hand_brings_the_archer_back(bprd):
    g, yen, hellboy = shield_scene(bprd)
    g.players[1].hand.clear()
    atk = foe_attack(g)
    g.attack(hellboy, yen, atk, give(g, 0, "Shield Formation"))
    assert g.fighters["archer1"].alive


# ---------------------------------------------------------------- the plain damage and value cards

def beside(g, fid, to_fid):
    g.fighters[fid].pos = next(s for s in sorted(g.board.adj[g.fighters[to_fid].pos])
                               if all(f.pos != s for f in g.fighters.values() if f.alive))
    return g.fighters[fid]


def test_point_blank_deals_two_only_when_the_opposing_fighter_is_adjacent_to_yennenga(bprd):
    g = mk(bprd)
    yen = stack(g, with_archers=0)
    hellboy = beside(g, "hellboy", "yennenga")
    before = hellboy.hp
    res = g.attack(yen, hellboy, give(g, 0, "Point Blank"), None)
    assert hellboy.hp == before - 2 - res.damage
    g2 = mk(bprd)
    yen2 = stack(g2, with_archers=0)
    h2 = g2.fighters["hellboy"]
    h2.pos = next(s for s in sorted(g2.board.spaces) if s != yen2.pos and g2.board.share_zone(yen2.pos, s) and s not in g2.board.adj[yen2.pos]
                  and all(f.pos != s for f in g2.fighters.values() if f.alive))
    before = h2.hp
    res = g2.attack(yen2, h2, give(g2, 0, "Point Blank"), None)
    assert h2.hp == before - res.damage


def test_jaws_of_the_beast_adds_one_per_zone_of_the_opposing_fighter(bprd):
    g = mk(bprd)
    yen = stack(g, with_archers=0)
    hellboy = beside(g, "hellboy", "yennenga")
    zones = len(g.board.zones(hellboy.pos))
    res = g.attack(yen, hellboy, give(g, 0, "Jaws of the Beast"), None)
    assert zones >= 1 and res.atk_value == 3 + zones


def test_momentous_shift_is_five_when_the_fighter_started_the_turn_elsewhere(bprd):
    g = mk(bprd)
    yen = stack(g, with_archers=0)
    hellboy = beside(g, "hellboy", "yennenga")
    g.fx.emit("start_of_turn", 0)
    res = g.attack(yen, hellboy, give(g, 0, "Momentous Shift"), None)
    assert res.atk_value == 3                                       # she has not moved
    g2 = mk(bprd)
    yen2 = stack(g2, with_archers=0)
    h2 = beside(g2, "hellboy", "yennenga")
    g2.fx.emit("start_of_turn", 0)
    yen2.pos = next(s for s in sorted(g2.board.adj[h2.pos]) if all(f.pos != s for f in g2.fighters.values() if f.alive))
    res = g2.attack(yen2, h2, give(g2, 0, "Momentous Shift"), None)
    assert res.atk_value == 5


def test_divide_and_conquer_is_four_for_an_archer_outside_her_zone_and_two_inside(bprd):
    g = mk(bprd)
    stack(g)
    a1 = g.fighters["archer1"]
    hellboy = beside(g, "hellboy", "archer1")
    res = g.attack(a1, hellboy, give(g, 0, "Divide and Conquer"), None)
    assert res.atk_value == 2
    g2 = mk(bprd)
    yen2 = stack(g2)
    a = g2.fighters["archer1"]
    a.pos = next(s for s in sorted(g2.board.spaces, reverse=True) if not g2.board.share_zone(yen2.pos, s)
                 and all(f.pos != s for f in g2.fighters.values() if f.alive))
    h2 = beside(g2, "hellboy", "archer1")
    res = g2.attack(a, h2, give(g2, 0, "Divide and Conquer"), None)
    assert res.atk_value == 4


# ---------------------------------------------------------------- Stallion Charge, Pin the Prey, schemes

def test_stallion_charge_moves_up_to_five_through_opposing_fighters_and_hits_each_one_passed(bprd):
    g = mk(bprd)
    yen = stack(g, with_archers=0)
    hellboy, lobster = beside(g, "hellboy", "yennenga"), g.fighters["lobster"]
    lobster.pos = next(s for s in sorted(g.board.adj[hellboy.pos]) if s != yen.pos and all(f.pos != s for f in g.fighters.values() if f.alive)
                       and s not in g.board.adj[yen.pos])
    dest = next(s for s in sorted(g.board.adj[lobster.pos]) if s not in (hellboy.pos, yen.pos) and all(f.pos != s for f in g.fighters.values() if f.alive)
                and g.board.distance(yen.pos, s) <= 5)
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [dest]]
    before = hp(g, "hellboy", "lobster")
    res = g.attack(yen, hellboy, give(g, 0, "Stallion Charge"), None)
    assert seen[0].extra["steps"] == 5 and seen[0].extra["through"] is True and yen.pos == dest
    assert hellboy.hp == before[0] - res.damage - 1 and lobster.hp == before[1] - 1


def test_stallion_charge_staying_put_hits_nobody_extra(bprd):
    g = mk(bprd)
    yen = stack(g, with_archers=0)
    hellboy = beside(g, "hellboy", "yennenga")
    g.controllers[0].queue = [[]]
    before = hellboy.hp
    res = g.attack(yen, hellboy, give(g, 0, "Stallion Charge"), None)
    assert hellboy.hp == before - res.damage


def test_pin_the_prey_moves_the_opposing_fighter_up_to_four_and_the_opponent_discards_one(bprd):
    g = mk(bprd)
    stack(g)
    a1 = g.fighters["archer1"]
    hellboy = beside(g, "hellboy", "archer1")
    g.players[1].hand.extend(g.players[1].deck[:3])
    hand = len(g.players[1].hand)
    start = hellboy.pos
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options, key=lambda s: g.board.distance(start, s))]]
    g.attack(a1, hellboy, give(g, 0, "Pin the Prey"), None)
    assert seen[0].extra["steps"] == 4 and seen[0].extra["up_to"] is True and 0 < g.board.distance(start, hellboy.pos) <= 4
    assert len(g.players[1].hand) == hand - 1


def test_skirmish_moves_a_fighter_of_the_combat_up_to_two_only_when_won(bprd):
    g = mk(bprd)
    yen = stack(g, with_archers=0)
    hellboy = beside(g, "hellboy", "yennenga")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[0]]] * 2
    res = g.attack(yen, hellboy, give(g, 0, "Skirmish"), None)
    assert res.attacker_won and seen and seen[-1].kind in ("fighter", "space")


def test_one_with_the_land_moves_heals_and_draws(bprd):
    g = mk(bprd)
    yen = stack(g)
    a1, a2 = archers(g)
    a1.hp, yen.hp = 1, 9
    deck = len(g.players[0].deck)
    g.controllers[0].queue = [[]] * 6
    g.play_scheme(0, g.hero(0), give(g, 0, "One With The Land"))
    assert (a1.hp, a2.hp, yen.hp) == (2, 2, 10) and len(g.players[0].deck) == deck - 1 and len(g.players[0].hand) == 1


def test_master_of_the_hunt_gains_two_actions(bprd):
    g = mk(bprd)
    stack(g)
    actions = g.actions_left
    g.play_scheme(0, g.hero(0), give(g, 0, "Master of the Hunt"))
    assert g.actions_left == actions - 1 + 2


# ---------------------------------------------------------------- Rain of Arrows, the double attack

def test_rain_of_arrows_is_a_plain_three_and_then_a_second_attack_of_three(bprd):
    g = mk(bprd)
    yen = stack(g, with_archers=0)
    hellboy = beside(g, "hellboy", "yennenga")
    before = hellboy.hp
    res = g.attack(yen, hellboy, give(g, 0, "Rain of Arrows"), None)
    assert res.damage == 3 and res.second is not None and res.second.damage == res.second.atk_value == 3
    assert hellboy.hp == before - 6


def test_the_defender_may_defend_the_volley_with_a_new_card(bprd):
    g = mk(bprd)
    yen = stack(g, with_archers=0)
    hellboy = beside(g, "hellboy", "yennenga")
    wall = give(g, 1, TRAINING)
    g.controllers[1].choose_second_defense = lambda game, att, tgt, value, card: wall
    before = hellboy.hp
    res = g.attack(yen, hellboy, give(g, 0, "Rain of Arrows"), None)
    assert res.second.def_card is wall and res.second.damage == max(0, 3 - wall.value) and hellboy.hp == before - 3 - res.second.damage


def test_feint_stops_the_volley(bprd):
    g = mk(bprd, "bigfoot")
    yen = stack(g, with_archers=0)
    bigfoot = beside(g, "bigfoot", "yennenga")
    g.fx.dsl_heroes = {"yennenga", "bigfoot"}
    before = bigfoot.hp
    res = g.attack(yen, bigfoot, give(g, 0, "Rain of Arrows"), give(g, 1, "Feint"))
    assert res.second is None and bigfoot.hp == before - 1            # the 3 against Feint's 2 still lands; the volley is an AFTER effect Feint cancels


def test_the_archers_take_their_share_of_the_second_attack_too(bprd):
    g = mk(bprd, "achilles", turn=1)
    yen = stack(g)
    a1, a2 = archers(g)
    achilles = beside(g, "achilles", "yennenga")
    g.fx.dsl_heroes = {"yennenga", "achilles"}
    g.controllers[0].queue = [[0], [0], [1], [1]]              # the first blow stays on her; one point of each Archer takes the volley
    g.controllers[0].choose_second_defense = lambda game, att, tgt, value, card: None
    res = g.attack(achilles, yen, give(g, 1, "Test For Weakness"), None)
    assert res.second is not None and res.second.damage == 3
    assert (a1.hp, a2.hp, yen.hp) == (1, 1, 15 - 1 - 1)
