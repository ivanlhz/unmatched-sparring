"""Elektra on the engine, bot side (player 0 plays her, the controllers answer): the off-board state (her first defeat removes her and the Hand,
nobody is defeated, nobody wins), the Resurrect at the start of her next turn (flip, shuffle, a zone each, her owner chooses: Ivan 2026-11-22,
E1 and E2), the RESURRECTED lines and the ten cards. The human side (panel, FakeTTS) is in tests/test_elektra_human.py and the full games in
tests/test_elektra_matrix.py.

The rival is Leonardo: Katana (attack 6) and Heroes in a half shell (defense 5) have no effect text, so what happens is Elektra's."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import off_board, persist
from sparring.effects.select import counter_value
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import pair, put_adjacent

HANDS = ["hand1", "hand2", "hand3", "hand4"]
FOE = "leonardo"


def mk(bprd, foe=FOE, seed=3, turn=0):
    """Elektra = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("elektra", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    for c in ctl.values():
        c.requests.clear()
    return g


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


def life(g):
    return counter_value(g, 0, "life")


def spread(g):
    """Elektra and her Hand one to a zone, far from the rival: the board as the Resurrect leaves it."""
    zones, far = [], sorted(g.board.spaces, reverse=True)
    for f in [g.fighters["elektra"]] + [g.fighters[h] for h in HANDS]:
        s = next(s for s in far if all(not g.board.share_zone(s, z) for z in zones) and all(o.pos != s for o in g.fighters.values() if o.alive))
        f.pos = s
        zones.append(s)


def remove_elektra(g):
    """Her first defeat, by effect damage."""
    spread(g)
    g.damage(g.fighters["elektra"], 99, "effect")


def resurrect(g, queue=None):
    g.turn = 0
    g.controllers[0].queue = list(queue or [])
    g.fx.emit("start_of_turn", 0)


def fighters_on_board(g, player=0):
    return [f.fid for f in g.own(player)]


# ---------------------------------------------------------------- the hero

def test_elektra_has_seven_health_and_four_hand_on_the_board(bprd):
    g = mk(bprd)
    e = g.fighters["elektra"]
    assert (e.hp, e.max_hp, e.move, e.ranged, e.name) == (7, 7, 2, False, "Elektra")
    assert all((g.fighters[h].hp, g.fighters[h].move, g.fighters[h].ranged, g.fighters[h].name, g.fighters[h].alive) == (1, 2, False, "The Hand", True)
               for h in HANDS)
    assert "elektra" in g.fx.dsl_heroes and g.winner is None and life(g) == 0


def test_the_deck_has_the_printed_bands_and_numbers(bprd):
    g = mk(bprd)
    seen = {}
    for c in g.players[0].full_set:
        s = seen.setdefault(c.title, (c.type, c.value, c.boost, c.fighter, 0))
        seen[c.title] = s[:4] + (s[4] + 1,)
    assert len(g.players[0].full_set) == 20
    assert seen == {
        "Mystic Assassin": ("attack", 6, 1, "Elektra", 2), "Hands of Red": ("attack", 4, 2, "Elektra", 2), "The Fist": ("attack", 3, 3, "The Hand", 2),
        "Cloaked In Shadow": ("versatile", 2, 1, "Elektra", 2), "Sai": ("versatile", 4, 3, "Elektra", 2), "Whirlwind": ("versatile", 2, 1, "Elektra", 2),
        "Ninjitsu": ("versatile", 3, 2, "any", 2), "Intercept": ("defense", 3, 4, "Elektra", 2), "Snakeroot Clan": ("defense", 1, 2, "Elektra", 2),
        "Mesmerize": ("scheme", None, 2, "Elektra", 2)}
    fist = next(c for c in g.players[0].full_set if c.title == "The Fist")
    assert fist.usable_by("The Hand") and not fist.usable_by("Elektra")


# ---------------------------------------------------------------- the first defeat: removed, not defeated

def test_combat_damage_that_would_defeat_her_removes_her_and_all_hand_and_nobody_wins(bprd):
    g = mk(bprd, turn=1)
    foe, e = pair(g, FOE, "elektra")
    e.hp = 1
    g.attack(foe, e, katana(g), None)
    assert g.winner is None and life(g) == 1
    assert fighters_on_board(g) == []
    for f in [e] + [g.fighters[h] for h in HANDS]:
        assert f.off_board and not f.alive and f.pos is None


def test_effect_damage_removes_her_too_and_fires_no_defeat_event(bprd, monkeypatch):
    g = mk(bprd)
    defeated = []
    emit = type(g.fx).emit
    monkeypatch.setattr(type(g.fx), "emit", lambda self, name, *a: (defeated.append(name) if name == "fighter_defeated" else None, emit(self, name, *a))[1])
    remove_elektra(g)
    assert g.winner is None and life(g) == 1 and defeated == []


def test_exhaustion_removes_her_and_the_hand_the_first_time(bprd):
    g = mk(bprd)
    g.players[0].deck.clear()
    g.fighters["elektra"].hp = 2
    g.draw(0)
    assert g.winner is None and life(g) == 1 and fighters_on_board(g) == []
    assert all(g.fighters[h].off_board and g.fighters[h].died_at is not None for h in HANDS)
    g.draw(0)       # nothing is left to hurt: an empty deck costs nothing while she is off the board
    assert g.winner is None


def test_a_hand_defeated_earlier_stays_defeated_and_is_not_off_the_board(bprd):
    g = mk(bprd)
    g.defeat(g.fighters["hand2"])
    remove_elektra(g)
    assert not g.fighters["hand2"].off_board and g.fighters["hand2"].died_at is not None
    assert all(g.fighters[h].off_board for h in ("hand1", "hand3", "hand4"))


def test_a_removed_fighter_is_not_defeated_for_the_selectors(bprd):
    from sparring.effects.select import defeated
    g = mk(bprd)
    g.defeat(g.fighters["hand2"])
    remove_elektra(g)
    assert defeated(g, g.fighters["hand2"])
    assert not any(defeated(g, g.fighters[f]) for f in ["elektra", "hand1", "hand3", "hand4"])


def test_while_she_is_off_the_board_the_rival_cannot_attack_her_and_nothing_ends_the_game(bprd):
    g = mk(bprd, turn=1)
    remove_elektra(g)
    foe = g.fighters["leonardo"]
    assert g.foes(1) == [] and all(not g.can_attack(foe, g.fighters[f], katana(g)) for f in ["elektra"] + HANDS)
    g.end_turn()
    assert g.winner is None


def test_the_second_defeat_after_the_resurrect_ends_the_game(bprd):
    g = mk(bprd)
    remove_elektra(g)
    resurrect(g, [lambda r: [r.options[0]]] * 5)
    assert g.fighters["elektra"].alive
    g.damage(g.fighters["elektra"], 99, "effect")
    assert g.winner == 1 and life(g) == 2


def test_the_state_survives_a_save_and_a_clone(bprd):
    g = mk(bprd)
    g.defeat(g.fighters["hand3"])
    remove_elektra(g)
    c = g.clone()
    assert life(c) == 1 and c.fighters["elektra"].off_board and not c.fighters["hand3"].off_board
    d = persist.game_to_dict(g)
    g2 = mk(bprd, seed=9)
    persist.apply_game(g2, d)
    assert life(g2) == 1 and g2.fighters["elektra"].off_board and g2.fighters["hand1"].off_board and not g2.fighters["hand3"].off_board
    resurrect(g, [lambda r: [r.options[0]]] * 5)
    d = persist.game_to_dict(g)
    g3 = mk(bprd, seed=9)
    persist.apply_game(g3, d)
    assert g3.fighters["elektra"].max_hp == 9 and g3.fighters["elektra"].hp == 9 and life(g3) == 2


# ---------------------------------------------------------------- the Resurrect

def first(req):
    """The first space offered; for anything else (an order) everything offered."""
    return [req.options[0]] if req.kind == "space" else list(req.options)


def resurrected(g, extra=None):
    remove_elektra(g)
    resurrect(g, [first] * 12)
    return g


def test_the_resurrect_flips_the_dial_places_all_five_each_in_a_zone_of_their_own(bprd):
    g = mk(bprd)
    g.fx.emit("start_of_turn", 0)       # not off the board yet: nothing to resurrect
    assert life(g) == 0
    resurrected(g)
    e = g.fighters["elektra"]
    assert (e.hp, e.max_hp, e.alive, e.off_board) == (9, 9, True, False) and life(g) == 2
    assert all(g.fighters[h].alive and g.fighters[h].hp == 1 and not g.fighters[h].off_board for h in HANDS)
    spots = [g.fighters[f].pos for f in ["elektra"] + HANDS]
    assert len(set(spots)) == 5
    assert all(not g.board.share_zone(a, b) for i, a in enumerate(spots) for b in spots[i + 1:]), spots


def test_the_resurrect_brings_back_the_hand_that_were_defeated_before_she_fell(bprd):
    g = mk(bprd)
    g.defeat(g.fighters["hand1"])
    g.defeat(g.fighters["hand4"])
    remove_elektra(g)
    resurrect(g, [first] * 12)
    assert all(g.fighters[h].alive and g.fighters[h].hp == 1 for h in HANDS)


def test_the_resurrect_shuffles_the_discard_pile_into_the_deck(bprd):
    g = mk(bprd)
    p = g.players[0]
    p.discard.extend(p.deck[:6])
    del p.deck[:6]
    deck_before, discard = len(p.deck), len(p.discard)
    remove_elektra(g)
    resurrect(g, [first] * 12)
    assert p.discard == [] and len(p.deck) == deck_before + discard


def test_her_owner_chooses_every_space(bprd):
    g = mk(bprd)
    remove_elektra(g)
    chosen = []

    def last(req):
        if req.kind != "space":
            return list(req.options)
        chosen.append((req.extra.get("fighter"), req.options[-1]))
        return [req.options[-1]]
    resurrect(g, [last] * 12)
    assert [g.fighters[f].pos for f, _ in chosen] == [s for _, s in chosen]
    assert chosen[0][0] == "elektra" and len(chosen) == 5


def test_the_resurrect_waits_for_her_next_turn_when_she_fell_on_her_own_turn(bprd):
    g = mk(bprd, turn=0)
    remove_elektra(g)
    g.end_turn()                      # the rival's whole turn comes first
    g.begin_turn()
    assert life(g) == 1 and fighters_on_board(g) == []
    g.end_turn()
    g.controllers[0].queue = [first] * 12
    g.begin_turn()
    assert life(g) == 2 and len(fighters_on_board(g)) == 5


def test_when_the_board_has_fewer_zones_than_fighters_the_rest_go_to_any_empty_space(bprd, monkeypatch):
    g = mk(bprd)
    remove_elektra(g)
    monkeypatch.setattr(g.board, "share_zone", lambda a, b: True)       # one zone for the whole board: no fighter can be apart from the others
    resurrect(g, [first] * 12)
    assert all(g.fighters[f].alive for f in ["elektra"] + HANDS)
    assert len({g.fighters[f].pos for f in ["elektra"] + HANDS}) == 5


# ---------------------------------------------------------------- removed in the middle of a maneuver

def test_a_maneuver_goes_on_when_the_first_mover_takes_everyone_off_the_board(bprd, monkeypatch):
    """Tomoe Gozen's opportunity attack (or a hazard edge) removes Elektra while she walks: the Hand still planned to move are away too, not moved."""
    g = mk(bprd)
    spread(g)
    g.fighters["elektra"].hp = 1
    original = type(g).move_fighter
    moved = []

    def hurt_on_the_way(self, f, dest, *a, **kw):
        moved.append(f.fid)
        original(self, f, dest, *a, **kw)
        if f.fid == "elektra":
            self.damage(f, 5, "effect")
    monkeypatch.setattr(type(g), "move_fighter", hurt_on_the_way)
    dests = {f: next(iter(sorted(g.board.adj[g.fighters[f].pos] - {o.pos for o in g.fighters.values() if o.pos is not None}))) for f in ["elektra", "hand1", "hand2"]}
    g.maneuver(0, dests)
    assert moved == ["elektra"] and life(g) == 1 and g.winner is None and g.fighters["hand1"].pos is None


def test_whatever_spaces_her_owner_picks_the_five_still_end_in_five_different_zones(bprd):
    """A greedy pick can paint the last Hand into a corner (one in 461 Resurrects did): the options always leave room for the fighters still to come.
    The chooser here is the worst one: each time it takes the space that leaves the fewest zone-free spaces for the others."""
    g = mk(bprd)
    remove_elektra(g)
    board = g.board

    def worst(req):
        if req.kind != "space":
            return list(req.options)
        taken = [f.pos for f in g.fighters.values() if f.alive]
        free = [s for s in board.spaces if s not in taken]
        left = lambda s: sum(1 for o in free if o != s and not board.share_zone(o, s) and all(not board.share_zone(o, t) for t in taken))
        return [min(req.options, key=lambda s: (left(s), s))]
    resurrect(g, [worst] * 12)
    spots = [g.fighters[f].pos for f in ["elektra"] + HANDS]
    assert len(set(spots)) == 5 and all(not board.share_zone(a, b) for i, a in enumerate(spots) for b in spots[i + 1:]), spots


def test_a_space_that_would_leave_a_later_hand_without_a_zone_is_not_offered(bprd):
    """The position of a whole game (Elektra against Triss and Yennefer, the chaser, seed 13): she is back on space 1 with the rivals on 15 and
    16, and the first Hand is offered a space while three more wait. Spaces 7 and 14 are free and outside her zones, but with a Hand there the
    last one finds no zone of its own: `space_options` looks ahead and leaves them out."""
    from sparring import off_board
    from sparring.effects.select import _zones_left, space_options
    g = mk(bprd, foe="triss-yennefer")
    remove_elektra(g)
    off_board.release(g, 0)
    g.fighters["triss"].pos, g.fighters["yennefer"].pos = 15, 16
    elektra, hand = g.fighters["elektra"], g.fighters["hand1"]
    elektra.pos, elektra.alive = 1, True
    free = {s for s in g.board.spaces if s not in (1, 15, 16)}
    for dead_end in (7, 14):
        assert not g.board.share_zone(1, dead_end) and not _zones_left(g.board, [1, dead_end], free, 3)
    offered = space_options(g, None, {"apart_from_own": True}, mover=hand)
    assert offered and not {7, 14} & set(offered), offered
    assert all(_zones_left(g.board, [1, s], free, 3) for s in offered)


class ToyBoard:
    """Six spaces; space 0 shares a zone with 1-4, and 1-4 with nobody else: starting with 0 leaves one zone-free space, starting with 1 leaves four."""
    spaces = range(6)

    @staticmethod
    def share_zone(a, b):
        return a == b or (0 in (a, b) and 5 not in (a, b))


def test_the_search_for_room_refuses_a_first_space_that_leaves_too_few_zones():
    from sparring.effects.select import _zones_left
    free = set(ToyBoard.spaces)
    assert not _zones_left(ToyBoard, [0], free - {0}, 2)       # only space 5 is free of space 0: two more fighters do not fit
    assert _zones_left(ToyBoard, [1], free - {1}, 2)
    assert _zones_left(ToyBoard, [0], free - {0}, 1)
