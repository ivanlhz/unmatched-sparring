"""Tomoe Gozen, rule decisions of Iván (2026-11-08): ATTACK OF OPPORTUNITY fires on a MOVE out of her zone (a walk, her own effect,
the rival's own effect) and never on a placement or a swap; her own movement never fires it; Refuse to Retreat pins her against
the rival's effects; A Warrior's Way lets the moved fighter cross fighters of its own side."""
from __future__ import annotations

from conftest import give
from test_bigfoot_effects import Answers
from test_effects_combat import pair
from test_effects_events import run_ops
from test_tomoe_gozen_effects import mk, stage

MOVE_OPPOSING = [{"op": "move", "target": "opposing", "amount": 3, "up_to": True, "chooser": "owner"}]


def test_a_move_out_of_her_zone_fires_it_even_when_an_effect_does_the_moving(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    before = h.hp
    run_ops(g, [{"op": "move", "target": "this", "amount": 3, "up_to": True, "chooser": "owner"}], 1, "hellboy",
            chooser=answering_with(outside))
    assert h.pos == outside and h.hp == before - 1                # the rival's own effect moved its hero


def answering_with(dest):
    """A chooser that answers every space question with `dest`."""
    class Chooser:
        def choose(self, game, req):
            return [dest] if dest in req.options else [req.options[0]]
        choose_effect = choose

    return Chooser()


def test_a_placement_out_of_her_zone_does_not_fire_it(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    before = h.hp
    g.place_fighter(h, outside)
    assert h.pos == outside and h.hp == before


def test_the_place_op_does_not_fire_it(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    before = h.hp
    run_ops(g, [{"op": "place", "target": "this", "where": {"any": True}, "chooser": "owner"}], 1, "hellboy",
            chooser=answering_with(outside))
    assert h.pos == outside and h.hp == before


def test_swapping_with_tomoe_does_not_fire_it(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    tomoe_at, hellboy_at = t.pos, h.pos
    run_ops(g, [{"op": "swap", "target": "this", "with": {"side": "enemy", "kind": "hero"}, "chooser": "owner"}], 0, "tomoe")
    assert (t.pos, h.pos) == (hellboy_at, tomoe_at)           # they traded places ...
    assert h.hp == h.max_hp and t.hp == t.max_hp              # ... and nobody was hurt by it


def test_her_own_walk_away_never_fires_it(bprd):
    g = mk(bprd)
    t, h, outside = stage(g)
    before = h.hp
    far = next(s for s in sorted(g.legal_moves(t, t.move)) if s != t.pos)
    g.move_fighter(t, far, t.move)
    assert h.hp == before and t.hp == t.max_hp


def test_refuse_to_retreat_also_stops_the_rivals_effects_from_moving_her(bprd):
    g = mk(bprd, "leonardo", turn=1)
    t, leo = pair(g, "tomoe", "leonardo")
    g.actions_left = 2
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) <= 3))
    g.attack(leo, t, attack, give(g, 0, "Refuse to Retreat"))
    here = t.pos
    run_ops(g, MOVE_OPPOSING, 1, "leonardo")                 # the rival's effect tries to walk her away
    assert t.pos == here


def test_a_warriors_way_lets_the_moved_fighter_cross_fighters_of_its_own_side(bprd):
    g = mk(bprd, "hellboy")
    t, h = pair(g, "tomoe", "hellboy")
    b = g.board
    friend = g.fighters["lobster"]
    spot = target = None
    for mid in sorted(b.adj[h.pos]):
        if mid == t.pos:
            continue
        for c in sorted(b.moves[mid]):
            reach = b.reachable(h.pos, 3, set(), {mid, t.pos}, False)
            if c not in (h.pos, t.pos, mid) and c not in reach and 1 + b.distance(mid, c) <= 3:
                spot, target = mid, c
                break
        if spot is not None:
            break
    assert spot is not None, "this map has no space that only a crossing of a friend reaches"
    friend.pos = spot
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [target], lambda req: [min(req.options)]]
    g.attack(t, h, give(g, 0, "A Warrior's Way"), None)
    assert seen and target in seen[0].options and h.pos == target
