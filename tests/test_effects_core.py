"""Effects interpreter core (C1): selectors, one test per op on real hero data, atomicity, save/resume round trip,
chooser implementations, engine hooks and persistence of `Game.fx`. Flag off: nothing here changes engine
behaviour (the goldens guard that)."""
import json
import random

import pytest

from sparring import persist
from sparring.board import Board
from sparring.controller import Controller
from sparring.effects import ops_core
from sparring.effects.choose import (Await, ChoiceRequest, ControllerChooser, PanelChooser, PendingChoice,
                                     ScriptedChooser, SyntheticChooser, default_answer)
from sparring.effects.model import EffectError, EFFECTS_DIR, load_effects, walk_ops
from sparring.effects.ops_core import OPS, PENDING_PHASES
from sparring.effects.run import Ctx, EffectRun
from sparring.effects.state import EffectState
from sparring.state import Game

from conftest import Scripted, give, place


def mk(bprd, heroes=("abe-sapien", "baba-yaga"), seed=1):
    ctl = {0: Scripted(), 1: Scripted()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=heroes)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    return g


def go(g, ops, chooser=None, owner=0, this="abe", **ctx):
    run = EffectRun(ops, Ctx(owner=owner, this_fid=this, **ctx))
    pending = run.run(g, chooser or ScriptedChooser())
    return run, pending


def free_neighbor(g, fid, nth=0):
    """The nth neighbor space of `fid`, emptied first (whoever stood there is sent to a far free space)."""
    f = g.fighters[fid]
    spot = sorted(g.board.adj[f.pos])[nth]
    for other in g.fighters.values():
        if other.alive and other.pos == spot:
            taken = {x.pos for x in g.fighters.values() if x.alive}
            other.pos = max(s for s in g.board.spaces if s not in taken)
    return spot


def snap(g):
    return json.dumps(persist.game_to_dict(g), sort_keys=True)


@pytest.fixture
def g(bprd):
    return mk(bprd)


# ---------------------------------------------------------------- selectors

def test_pick_one_without_candidates_is_a_no_op(g):
    before = snap(g)
    run, pending = go(g, [{"op": "damage", "target": {"side": "enemy", "where": {"adjacent_to": "this"}},
                           "amount": 2, "as": "hit"}])
    assert pending is None and run.done and snap(g) == before
    assert run.bound("hit", "fighters") == []


def test_pick_all_over_zero_applies_to_zero(g):
    before = snap(g)
    _, pending = go(g, [{"op": "damage", "target": {"side": "enemy", "where": {"adjacent_to": "this"},
                                                    "pick": "all"}, "amount": 2}])
    assert pending is None and snap(g) == before


def test_pick_one_with_several_candidates_asks_the_chooser(g):
    place(g, baba=free_neighbor(g, "abe", 0), koschei=free_neighbor(g, "abe", 1))
    chooser = ScriptedChooser([["koschei"]])
    go(g, [{"op": "damage", "target": {"side": "enemy", "where": {"adjacent_to": "this"}}, "amount": 2}], chooser)
    req = chooser.requests[0]
    assert req.kind == "fighter" and sorted(req.options) == ["baba", "koschei"] and req.key == "fx/0:0"
    assert g.fighters["koschei"].hp == 1 and g.fighters["baba"].hp == 13


def test_a_single_candidate_is_taken_without_asking(g):
    place(g, baba=free_neighbor(g, "abe"))
    chooser = ScriptedChooser()
    go(g, [{"op": "damage", "target": {"side": "enemy", "kind": "hero", "where": {"adjacent_to": "this"}},
             "amount": 2}], chooser)
    assert chooser.requests == [] and g.fighters["baba"].hp == 11


def test_roles_and_other(g):
    place(g, agent1=free_neighbor(g, "abe"))
    run, _ = go(g, [{"op": "damage", "target": {"side": "own", "where": {"zone_of": "this"}, "other": True,
                                                "pick": "all"}, "amount": 1, "as": "hit"}])
    hit = run.bound("hit", "fighters")
    assert "abe" not in hit and set(hit) <= {"agent1", "agent2", "agent3"} and hit
    go(g, [{"op": "damage", "target": "hero", "amount": 1}])
    assert g.fighters["abe"].hp == 12


def test_opposing_attacker_defender_combatant(g):
    place(g, baba=free_neighbor(g, "abe"))
    ctx = dict(attacker_fid="abe", defender_fid="baba")
    go(g, [{"op": "damage", "target": "opposing", "amount": 2}], **ctx)
    assert g.fighters["baba"].hp == 11
    go(g, [{"op": "damage", "target": "attacker", "amount": 1}, {"op": "damage", "target": "defender", "amount": 1}],
       **ctx)
    assert (g.fighters["abe"].hp, g.fighters["baba"].hp) == (12, 10)
    chooser = ScriptedChooser([["baba"]])
    go(g, [{"op": "damage", "target": "combatant", "amount": 1}], chooser, **ctx)
    assert chooser.requests[0].options == ["abe", "baba"] and g.fighters["baba"].hp == 9


def test_state_defeated_and_name_filters(g):
    sel = {"side": "own", "name": "B.P.R.D. Agent", "state": "defeated", "pick": "all"}
    run, _ = go(g, [{"op": "damage", "target": {"side": "own", "name": "B.P.R.D. Agent", "pick": "all"},
                     "amount": 9, "as": "x"},
                    {"op": "revive", "target": sel, "where": {"any": True}, "hp": 1}], ScriptedChooser())
    assert len(run.bound("x", "fighters")) == 3 and all(g.fighters[f].alive for f in ("agent1", "agent2", "agent3"))
    # reserve fighters (never placed) are not defeated: Pact Of Mortality must not pull them
    for fid in ("agent1", "agent2"):
        g.fighters[fid].alive, g.fighters[fid].pos = False, None
    g.fighters["agent1"].died_at, g.fighters["agent2"].died_at = 4, None
    go(g, [{"op": "revive", "target": sel, "where": {"any": True}, "hp": 1}], ScriptedChooser())
    assert g.fighters["agent1"].alive and not g.fighters["agent2"].alive


def test_bad_selectors_raise_effect_error(g):
    with pytest.raises(EffectError):
        go(g, [{"op": "damage", "target": "nobody", "amount": 1}])
    with pytest.raises(EffectError):
        go(g, [{"op": "damage", "target": "$unbound", "amount": 1}])
    with pytest.raises(EffectError):
        go(g, [{"op": "damage", "target": {"side": "sideways"}, "amount": 1}])
    with pytest.raises(EffectError):
        go(g, [{"op": "draw", "player": "everyone", "amount": 1}])
    with pytest.raises(EffectError):
        go(g, [{"op": "draw", "player": "attacking_player", "amount": 1}])
    with pytest.raises(EffectError):
        EffectRun([{"op": "teleport"}], Ctx(owner=0))


# ---------------------------------------------------------------- amounts and conditions

def test_amounts(g):
    hand = g.players[0].hand
    ops = [{"op": "heal", "target": "hero", "amount": {"count_cards": {"zone": "hand", "player": "owner",
                                                                       "filter": {"type_not": "scheme"}}}}]
    g.fighters["abe"].hp = 1
    go(g, ops)
    assert g.fighters["abe"].hp == 1 + sum(1 for c in hand if c.type != "scheme")
    g.fighters["abe"].hp = 1
    go(g, [{"op": "heal", "target": "hero", "amount": {"count": {"side": "own", "kind": "sidekick", "pick": "all"},
                                                       "times": 2}}])
    assert g.fighters["abe"].hp == 7
    g.fighters["abe"].hp = 1
    go(g, [{"op": "heal", "target": "hero", "amount": {"stat": "hand_size"}}])
    assert g.fighters["abe"].hp == 1 + len(hand)
    card = hand[0]
    g.fighters["abe"].hp = 1
    go(g, [{"op": "heal", "target": "hero", "amount": {"attr": "value", "of": "this"}}], card_id=card.card_id)
    assert g.fighters["abe"].hp == 1 + (card.value or 0)
    g.fighters["abe"].hp = 1
    go(g, [{"op": "heal", "target": "hero", "amount": {"attr": "boost", "of": "this"}}], card_id=card.card_id)
    assert g.fighters["abe"].hp == 1 + card.boost


def test_stat_amounts(g):
    g.fighters["abe"].hp = 1
    go(g, [{"op": "heal", "target": "hero", "amount": {"stat": "max_hp", "fighter": "hero"}}])
    assert g.fighters["abe"].hp == 13
    g.fighters["abe"].hp = 1
    go(g, [{"op": "heal", "target": "hero", "amount": {"stat": "actions_taken_this_turn"}}])
    assert g.fighters["abe"].hp == 1          # nothing spent yet (counted from C3 on, see test_effects_events)
    g.fighters["abe"].hp = 2
    go(g, [{"op": "heal", "target": "hero", "amount": {"stat": "damage_dealt_this_combat"}}], damage_dealt=3)
    assert g.fighters["abe"].hp == 5
    go(g, [{"op": "heal", "target": "hero", "amount": {"stat": "damage_taken_this_combat"}}], damage_taken=2)
    assert g.fighters["abe"].hp == 7
    with pytest.raises(EffectError):
        go(g, [{"op": "heal", "target": "hero", "amount": {"stat": "luck"}}])
    with pytest.raises(EffectError):
        go(g, [{"op": "heal", "target": "hero", "amount": {"nothing": 1}}])
    with pytest.raises(EffectError):
        go(g, [{"op": "heal", "target": "hero", "amount": True}])


def test_conditions(g):
    place(g, baba=free_neighbor(g, "abe"))
    hp_after = lambda ops, **ctx: (go(g, ops, **ctx), g.fighters["abe"].hp)[1]
    def cond(c, **ctx):
        g.fighters["abe"].hp = 1
        return hp_after([{"op": "if", "condition": c, "then": [{"op": "heal", "target": "hero", "amount": 1}]}],
                        **ctx) == 2
    adj = {"test": "exists", "fighters": {"role": "opposing", "where": {"adjacent_to": "this"}}}
    ctx = dict(attacker_fid="abe", defender_fid="baba")
    assert cond(adj, **ctx)
    assert cond({"all": [adj, {"not": {"test": "combat_result", "result": "won"}}]}, **ctx)
    assert cond({"any": [{"test": "combat_result", "result": "won"}, adj]}, combat_result="won", **ctx)
    assert not cond({"test": "combat_result", "result": "won"}, combat_result="lost")
    assert cond({"test": "combat_result", "result": "lost"}, combat_result="lost")
    assert cond({"test": "played_as", "side": "attack"}, played_as="attack")
    assert not cond({"test": "played_as", "side": "defense"}, played_as="attack")
    assert cond({"test": "compare", "left": {"stat": "hand_size"}, "op": ">=", "right": 5})
    assert not cond({"test": "compare", "left": 1, "op": "!=", "right": 1})
    assert cond({"test": "fighter_at", "fighter": "this", "space": {"space_of": "this", "empty": False}})
    assert cond({"test": "exists", "space": {"adjacent_to": "this", "empty": False}})
    assert cond({"test": "exists", "cards": {"zone": "hand", "player": "owner"}})
    assert cond({"test": "counter", "name": "intuition", "max": 0})
    assert not cond({"test": "counter", "name": "intuition", "min": 1})
    assert cond({"test": "form_is", "form": None})


def test_card_condition_and_moved_this_turn(g):
    card = g.players[0].hand[0]
    c = {"test": "card", "card": "this", "filter": {"type": card.type, "title": card.title, "tag_not": "zzz"}}
    g.fighters["abe"].hp = 1
    go(g, [{"op": "if", "condition": c, "then": [{"op": "heal", "target": "hero", "amount": 1}]}],
       card_id=card.card_id)
    assert g.fighters["abe"].hp == 2
    go(g, [{"op": "if", "condition": {"test": "card", "card": "opponent_card"},
            "then": [{"op": "heal", "target": "hero", "amount": 1}]}])
    assert g.fighters["abe"].hp == 2
    moved = {"op": "if", "condition": {"test": "moved_this_turn", "fighter": "this"},
             "then": [{"op": "heal", "target": "hero", "amount": 1}]}
    go(g, [moved])
    assert g.fighters["abe"].hp == 2
    g.fx.turn_start_pos["abe"] = g.fighters["abe"].pos
    go(g, [moved])
    assert g.fighters["abe"].hp == 2
    g.fx.turn_start_pos["abe"] = -1
    go(g, [moved])
    assert g.fighters["abe"].hp == 3


def test_hero_counter_condition_reads_the_piles(bprd):
    g = mk(bprd, heroes=("hellboy", "abe-sapien"))
    hb = g.hero(0)
    hb.hp = 1
    cond = {"test": "counter", "name": "destiny", "min": 1}
    ops = [{"op": "if", "condition": cond, "then": [{"op": "heal", "target": "hero", "amount": 1}]}]
    go(g, ops, this="hellboy")
    assert hb.hp == 1
    destiny = next(c for c in g.players[0].full_set if c.destiny)
    g.players[0].discard.append(destiny)
    go(g, ops, this="hellboy")
    assert hb.hp == 2


# ---------------------------------------------------------------- ops

def test_op_damage_binds_the_hit_and_goes_through_game_damage(g):
    place(g, baba=free_neighbor(g, "abe"))
    run, _ = go(g, [{"op": "damage", "target": "opposing", "amount": 2, "as": "hit"}],
                attacker_fid="abe", defender_fid="baba")
    assert g.fighters["baba"].hp == 11 and run.bound("hit", "fighters") == ["baba"]
    g.effect_shield[1] = g.turn_no
    run, _ = go(g, [{"op": "damage", "target": "opposing", "amount": 2, "as": "hit"}],
                attacker_fid="abe", defender_fid="baba")
    assert g.fighters["baba"].hp == 11 and run.bound("hit", "fighters") == []


def test_op_heal_is_capped_at_max_hp(g):
    g.fighters["abe"].hp = 10
    go(g, [{"op": "heal", "target": "hero", "amount": 2}])
    assert g.fighters["abe"].hp == 12
    go(g, [{"op": "heal", "target": "hero", "amount": 99}])
    assert g.fighters["abe"].hp == 13


def test_op_set_hp_raises_lowers_and_kills(g):
    k = g.fighters["koschei"]
    go(g, [{"op": "set_hp", "target": {"side": "enemy", "name": "Koschei"}, "amount": 3}])
    assert k.hp == 3
    go(g, [{"op": "set_hp", "target": {"side": "enemy", "name": "Koschei"}, "amount": 1}])
    assert k.hp == 1
    go(g, [{"op": "set_hp", "target": {"side": "enemy", "name": "Koschei"}, "amount": 9}])
    assert k.hp == 3
    go(g, [{"op": "set_hp", "target": {"side": "enemy", "name": "Koschei"}, "amount": 0}])
    assert not k.alive


def test_op_draw_all_forms(g):
    n = len(g.players[0].hand)
    run, _ = go(g, [{"op": "draw", "player": "owner", "amount": 2, "as": "new"}])
    assert len(g.players[0].hand) == n + 2 and len(run.bound("new", "cards")) == 2
    m = len(g.players[1].hand)
    go(g, [{"op": "draw", "player": "opponent", "amount": 1}])
    assert len(g.players[1].hand) == m + 1
    chooser = ScriptedChooser([[1]])
    go(g, [{"op": "draw", "player": "owner", "amount": 3, "up_to": True}], chooser)
    assert len(g.players[0].hand) == n + 3
    assert chooser.requests[0].kind == "amount" and chooser.requests[0].options == [0, 1, 2, 3]
    go(g, [{"op": "draw", "player": "owner", "amount": 0, "up_to": True}], chooser)
    assert len(g.players[0].hand) == n + 3


def test_op_discard_from_hand_deck_and_refs(g):
    p = g.players[0]
    card = p.hand[2]
    chooser = ScriptedChooser([[card.card_id]])
    run, _ = go(g, [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "amount": 1}, "as": "gone"}],
                chooser)
    assert card in p.discard and card not in p.hand and run.bound("gone", "cards") == [card.card_id]
    assert chooser.requests[0].extra["purpose"] == "discard"
    top = p.deck[0]
    go(g, [{"op": "discard", "cards": {"zone": "deck", "player": "owner", "pick": "top", "amount": 1}}])
    assert p.discard[-1] is top
    bottom = p.deck[-1]
    go(g, [{"op": "discard", "cards": {"zone": "deck", "player": "owner", "pick": "bottom"}}])
    assert p.discard[-1] is bottom
    kept = p.hand[0]
    run, _ = go(g, [{"op": "choose", "cards": {"zone": "hand", "player": "owner", "amount": 1}, "as": "c"},
                    {"op": "discard", "cards": "$c"}], ScriptedChooser([[kept.card_id]]))
    assert kept in p.discard and kept not in p.hand
    go(g, [{"op": "discard", "cards": "this"}], card_id=p.hand[0].card_id)
    go(g, [{"op": "discard", "cards": "opponent_card"}])


def test_discard_from_the_deck_emits_card_discarded(g):
    g.fx = SpyFx()
    go(g, [{"op": "discard", "cards": {"zone": "deck", "player": "owner", "pick": "top"}}])
    assert g.fx.events == ["card_discarded"]


def test_forced_discard_can_be_vetoed(g):
    class NoForced(SpyFx):
        def can_force_discard(self, player, source_player):
            return False
    g.fx = NoForced()
    n = len(g.players[0].hand)
    assert g.force_discard(0, 1, "x") == [] and len(g.players[0].hand) == n and g.fx.events == []


def test_op_discard_random_uses_the_game_rng_and_never_asks(g):
    chooser = ScriptedChooser()
    n = len(g.players[1].hand)
    go(g, [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 2}}], chooser)
    assert len(g.players[1].hand) == n - 2 and len(g.players[1].discard) == 2 and chooser.requests == []


def test_op_discard_in_play_and_zone_discard(g):
    p = g.players[0]
    scheme = next(c for c in p.full_set if c.is_scheme)
    g.fx.set_ongoing(0, scheme.card_id)
    ops = [{"op": "discard", "cards": {"zone": "in_play", "player": "owner", "filter": {"type": "scheme"}}}]
    go(g, ops)
    assert g.fx.ongoing_card_id(0) is None and scheme in p.discard
    go(g, ops)
    assert p.discard.count(scheme) == 1
    go(g, [{"op": "discard", "cards": {"zone": "discard", "player": "owner", "pick": "all"}}])
    with pytest.raises(EffectError):
        go(g, [{"op": "discard", "cards": {"zone": "limbo", "player": "owner", "pick": "all"}}])


def test_card_selectors_filter_except_and_up_to(g):
    p = g.players[0]
    p.hand[:] = [c for c in p.full_set if c.type == "attack"][:3] + [c for c in p.full_set if c.type == "defense"][:1]
    keep = p.hand[0]
    go(g, [{"op": "choose", "cards": {"zone": "hand", "player": "owner", "amount": 1}, "as": "keep"},
           {"op": "discard", "cards": {"zone": "hand", "player": "owner", "pick": "all", "except": "$keep"}}],
       ScriptedChooser([[keep.card_id]]))
    assert p.hand == [keep]
    p.hand[:] = [c for c in p.full_set if c.type == "attack"][:3]
    chooser = ScriptedChooser([[]])
    go(g, [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "amount": 2, "up_to": True}}], chooser)
    assert chooser.requests[0].min == 0 and len(p.hand) == 3
    go(g, [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "amount": 9, "up_to": True}}],
       ScriptedChooser([[p.hand[0].card_id]]))
    assert len(p.hand) == 2
    n = len(p.hand)
    go(g, [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "filter": {"type": "defense"},
                                       "amount": 1}}])
    assert len(p.hand) == n
    go(g, [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "filter": {"fighter": "nobody"},
                                       "pick": "all"}}])
    assert len(p.hand) == n


def test_op_choose_binds_without_moving(g):
    p = g.players[0]
    card = p.hand[1]
    run, _ = go(g, [{"op": "choose", "cards": {"zone": "hand", "player": "owner", "amount": 1}, "as": "pick"}],
                ScriptedChooser([[card.card_id]]))
    assert run.bound("pick", "cards") == [card.card_id] and card in p.hand


def test_choose_effect_resolves_in_printed_order_not_choice_order(g):
    n = len(g.players[0].hand)
    g.fighters["abe"].hp = 1
    options = [{"label": "draw 2", "ops": [{"op": "draw", "player": "owner", "amount": 2}]},
               {"label": "heal", "ops": [{"op": "heal", "target": "hero",
                                           "amount": {"count_cards": {"zone": "hand", "player": "owner"}}}]}]
    go(g, [{"op": "choose_effect", "amount": 2, "distinct": True, "options": options}], ScriptedChooser([[1], [0]]))
    assert g.fighters["abe"].hp == 1 + n + 2        # drew first, then healed by the bigger hand


def test_op_choose_effect_distinct_and_repeats(g):
    g.fighters["abe"].hp = 1
    options = [{"label": "heal", "ops": [{"op": "heal", "target": "hero", "amount": 2}]},
               {"label": "act", "ops": [{"op": "gain_action", "amount": 1}]}]
    chooser = ScriptedChooser([[1], [0]])
    go(g, [{"op": "choose_effect", "amount": 2, "distinct": True, "options": options}], chooser)
    assert g.actions_left == 3 and g.fighters["abe"].hp == 3
    assert len(chooser.requests) == 1       # the second pick is forced: one option left
    g.fighters["abe"].hp = 1
    go(g, [{"op": "choose_effect", "amount": 2, "options": options}], ScriptedChooser([[0], [0]]))
    assert g.fighters["abe"].hp == 5
    go(g, [{"op": "choose_effect", "amount": 3, "distinct": True, "options": options[:1]}])
    assert g.fighters["abe"].hp == 7


def test_op_move_up_to_exact_and_decline(g):
    abe = g.fighters["abe"]
    start = abe.pos
    chooser = ScriptedChooser()
    go(g, [{"op": "move", "target": "hero", "amount": 2, "up_to": True}], chooser)
    req = chooser.requests[0]
    assert req.kind == "space" and req.min == 0 and start not in req.options and abe.pos == start
    dest = req.options[-1]
    go(g, [{"op": "move", "target": "hero", "amount": 2, "up_to": True}], ScriptedChooser([[dest]]))
    assert abe.pos == dest
    chooser = ScriptedChooser()
    go(g, [{"op": "move", "target": "hero", "amount": 2, "up_to": False}], chooser)
    assert chooser.requests[0].min == 1 and abe.pos != dest


def test_op_move_exactly_n_prefers_spaces_n_away(g):
    abe = g.fighters["abe"]
    here = abe.pos
    chooser = ScriptedChooser()
    go(g, [{"op": "move", "target": "hero", "amount": 2, "up_to": False}], chooser)
    options = chooser.requests[0].options
    assert options and all(g.board.distance(here, s) == 2 for s in options)
    assert g.fighters["abe"].pos == options[0]


def test_op_move_many_fighters_sees_earlier_moves(g):
    a1, a2 = g.fighters["agent1"], g.fighters["agent2"]
    chooser = ScriptedChooser()
    first_dest = sorted(g.legal_moves(a1, 1))[0]
    go(g, [{"op": "move", "target": {"side": "own", "name": "B.P.R.D. Agent", "pick": "all"}, "amount": 1,
            "up_to": True}], ScriptedChooser([[first_dest], []]))
    assert a1.pos == first_dest
    both = [{"op": "move", "target": {"side": "own", "name": "B.P.R.D. Agent", "pick": "all"}, "amount": 1,
             "up_to": True}]
    go(g, both, chooser)
    taken_by_first = chooser.requests[0].options
    assert a1.pos not in taken_by_first


def test_op_move_of_a_dead_fighter_is_skipped_and_enemy_move_obeys_the_chooser(g):
    g.fighters["agent2"].alive, g.fighters["agent2"].pos = False, None
    chooser = ScriptedChooser()
    go(g, [{"op": "damage", "target": {"side": "own", "name": "B.P.R.D. Agent", "pick": "all"}, "amount": 5, "as": "gone"},
        {"op": "move", "target": "$gone", "amount": 1, "up_to": True}], chooser)
    assert chooser.requests == []
    baba = g.fighters["baba"]
    chooser = ScriptedChooser()
    go(g, [{"op": "move", "target": {"side": "enemy", "kind": "hero"}, "amount": 1, "up_to": True,
            "chooser": "owner"}], chooser)
    assert chooser.requests[0].player == 0 and chooser.requests[0].extra["fighter"] == "baba"
    assert baba.pos == 30


def test_op_place_options_exclude_occupied_and_follow_where(g):
    k = g.fighters["koschei"]
    chooser = ScriptedChooser()
    go(g, [{"op": "place", "target": {"side": "enemy", "name": "Koschei"}, "where": {"any": True},
            "chooser": "owner"}], chooser)
    options = chooser.requests[0].options
    occupied = {f.pos for f in g.fighters.values() if f.alive and f is not k}
    assert not occupied & set(options) and k.pos == options[0] and chooser.requests[0].player == 0
    dest = sorted(s for s in g.board.spaces if s not in occupied)[-1]
    go(g, [{"op": "place", "target": {"side": "enemy", "name": "Koschei"}, "where": {"any": True}}],
       ScriptedChooser([[dest]]))
    assert k.pos == dest
    chooser = ScriptedChooser()
    go(g, [{"op": "place", "target": {"side": "own", "name": "B.P.R.D. Agent", "pick": "all"},
            "where": {"adjacent_to": "this"}}], chooser)
    adj = set(g.board.adj[g.fighters["abe"].pos])
    assert all(set(r.options) <= adj for r in chooser.requests)
    nearest = ScriptedChooser()
    go(g, [{"op": "place", "target": {"side": "enemy", "name": "Koschei"}, "where": {"nearest_to": "this"}}], nearest)
    abe_pos = g.fighters["abe"].pos
    empty = [s for s in g.board.spaces if s not in {f.pos for f in g.fighters.values() if f.alive and f is not k}]
    assert g.board.distance(abe_pos, k.pos) == min(g.board.distance(abe_pos, s) for s in empty)


def test_op_place_start_space(g):
    chooser = ScriptedChooser()
    g.fighters["koschei"].pos = 19
    start = g.start_spaces[1]
    for f in g.fighters.values():
        if f.alive and f.pos == start and f.fid != "baba":
            f.pos = 31
    g.fighters["baba"].pos = 29
    go(g, [{"op": "place", "target": "hero", "where": {"start_space_of": "opponent"}}], chooser)
    assert g.fighters["abe"].pos == start


def test_op_swap(g):
    a, b = g.fighters["abe"].pos, g.fighters["baba"].pos
    go(g, [{"op": "swap", "target": "hero", "with": {"side": "enemy", "kind": "hero"}}])
    assert (g.fighters["abe"].pos, g.fighters["baba"].pos) == (b, a)
    before = snap(g)
    go(g, [{"op": "swap", "target": "hero", "with": "hero"}])
    go(g, [{"op": "swap", "target": "hero", "with": {"side": "enemy", "name": "Nobody"}}])
    assert snap(g) == before


def test_op_revive_and_summon(g):
    agent = g.fighters["agent2"]
    agent.alive, agent.pos, agent.died_at, agent.hp = False, None, 4, 0
    chooser = ScriptedChooser()
    go(g, [{"op": "revive", "target": {"side": "own", "name": "B.P.R.D. Agent", "state": "defeated"},
            "where": {"zone_of": "hero"}, "hp": 1}], chooser)
    assert agent.alive and agent.hp == 1 and g.board.share_zone(agent.pos, g.fighters["abe"].pos)
    go(g, [{"op": "revive", "target": {"side": "own", "name": "B.P.R.D. Agent", "state": "defeated"},
            "where": {"zone_of": "hero"}, "hp": 1}], chooser)
    reserve = g.fighters["agent3"]
    reserve.alive, reserve.pos, reserve.died_at = False, None, None
    before = reserve.hp
    run, _ = go(g, [{"op": "summon", "name": "B.P.R.D. Agent", "where": {"zone_of": "hero"}, "hp": 5}])
    assert reserve.alive and reserve.hp == min(5, reserve.max_hp) and reserve.max_hp == before
    go(g, [{"op": "summon", "name": "B.P.R.D. Agent", "where": {"zone_of": "hero"}}])
    assert g.fighters["agent1"].alive
    after = snap(g)
    go(g, [{"op": "summon", "name": "Nobody", "where": {"any": True}}])
    assert snap(g) == after


def test_summon_defaults_to_max_hp(g):
    reserve = g.fighters["agent3"]
    reserve.alive, reserve.pos, reserve.died_at, reserve.hp = False, None, None, 0
    go(g, [{"op": "summon", "name": "B.P.R.D. Agent", "where": {"any": True}}])
    assert reserve.alive and reserve.hp == reserve.max_hp


def test_op_counter_clamps_and_rejects_unknown(g):
    go(g, [{"op": "counter", "name": "intuition", "delta": 1}])
    assert g.fx.counter_value(0, "intuition") == 1
    go(g, [{"op": "counter", "name": "intuition", "delta": 5}])
    assert g.fx.counter_value(0, "intuition") == 2
    go(g, [{"op": "counter", "name": "intuition", "delta": -9}])
    assert g.fx.counter_value(0, "intuition") == 0
    go(g, [{"op": "counter", "name": "intuition", "set": 1, "player": "owner"}])
    assert g.fx.counter_value(0, "intuition") == 1
    with pytest.raises(EffectError):
        go(g, [{"op": "counter", "name": "rage", "delta": 1}])
    go(g, [{"op": "if", "condition": {"test": "counter", "name": "intuition", "min": 1},
            "then": [{"op": "heal", "target": "hero", "amount": 0}]}])


def test_op_gain_action_and_end_turn(g):
    go(g, [{"op": "gain_action", "amount": 2}])
    assert g.actions_left == 4
    go(g, [{"op": "gain_action", "amount": 1, "player": "opponent"}])
    assert g.actions_left == 4
    run, _ = go(g, [{"op": "end_turn"}])
    assert g.actions_left == 0 and run.flags["end_turn"] == 0
    g.actions_left = 2
    run, _ = go(g, [{"op": "end_turn"}], owner=1)       # a defense card ends the ATTACKER's turn
    assert g.actions_left == 0 and run.flags["end_turn"] == 0


def test_op_if_then_else_and_missing_branches(g):
    g.fighters["abe"].hp = 1
    yes = {"test": "compare", "left": 1, "op": "==", "right": 1}
    no = {"test": "compare", "left": 1, "op": "==", "right": 2}
    heal1, heal2 = [{"op": "heal", "target": "hero", "amount": 1}], [{"op": "heal", "target": "hero", "amount": 2}]
    go(g, [{"op": "if", "condition": yes, "then": heal1, "else": heal2}])
    assert g.fighters["abe"].hp == 2
    go(g, [{"op": "if", "condition": no, "then": heal1, "else": heal2}])
    assert g.fighters["abe"].hp == 4
    go(g, [{"op": "if", "condition": no, "then": heal1}])
    assert g.fighters["abe"].hp == 4


def test_op_optional_accept_decline_else_and_cost(g):
    g.fighters["abe"].hp = 1
    heal = [{"op": "heal", "target": "hero", "amount": 1}]
    hurt = [{"op": "heal", "target": "hero", "amount": 3}]
    spec = {"op": "optional", "ops": heal, "else": hurt}
    chooser = ScriptedChooser([[True]])
    go(g, [spec], chooser)
    assert g.fighters["abe"].hp == 2 and chooser.requests[0].kind == "optional"
    go(g, [spec], ScriptedChooser([[False]]))
    assert g.fighters["abe"].hp == 5
    go(g, [{"op": "optional", "ops": heal}], ScriptedChooser([[False]]))
    assert g.fighters["abe"].hp == 5
    p = g.players[0]
    n = len(p.hand)
    costed = {"op": "optional", "cost": [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "amount": 2}}],
              "ops": heal, "else": hurt}
    go(g, [costed], ScriptedChooser([[True]]))
    assert len(p.hand) == n - 2 and g.fighters["abe"].hp == 6
    p.hand[:] = p.hand[:1]
    chooser = ScriptedChooser()
    go(g, [costed], chooser)
    assert chooser.requests == [] and g.fighters["abe"].hp == 9 and len(p.hand) == 1
    p.hand[:] = []
    go(g, [{"op": "optional", "cost": [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "up_to": True,
                                                                   "amount": 2}}],
            "ops": heal}], ScriptedChooser([[True]]))
    assert g.fighters["abe"].hp == 10


def test_op_for_each_players_and_fighters_in_chosen_order(g):
    n0, n1 = len(g.players[0].hand), len(g.players[1].hand)
    run, _ = go(g, [{"op": "for_each", "over": {"players": "all"}, "as": "p",
                     "ops": [{"op": "draw", "player": "$p", "amount": 1}]}])
    assert (len(g.players[0].hand), len(g.players[1].hand)) == (n0 + 1, n1 + 1)
    assert run.done
    chooser = ScriptedChooser([["agent3", "agent1", "agent2"]])
    g.log.clear()
    go(g, [{"op": "for_each", "over": {"fighters": {"side": "own", "name": "B.P.R.D. Agent", "pick": "all"}},
            "as": "f", "ops": [{"op": "damage", "target": "$f", "amount": 0.5}]}], chooser)
    assert chooser.requests[0].kind == "order"
    order = [line.split()[0] for line in g.log if line.startswith("agent")]
    assert order == ["agent3", "agent1", "agent2"]
    go(g, [{"op": "for_each", "over": {"fighters": {"side": "enemy", "name": "Nobody", "pick": "all"}}, "as": "f",
            "ops": [{"op": "heal", "target": "hero", "amount": 1}]}])
    nested = [{"op": "for_each", "over": {"players": "all"}, "as": "p", "ops": [
        {"op": "if", "condition": {"test": "compare", "left": 1, "op": "==", "right": 1},
         "then": [{"op": "draw", "player": "$p", "amount": 1}]}]}]
    n0 = len(g.players[0].hand)
    go(g, nested)
    assert len(g.players[0].hand) == n0 + 1


def test_plugin_registry_and_unregistered_plugin(g):
    calls = []

    @ops_core.plugin("test:echo")
    def echo(run, game, spec):
        calls.append(spec["args"]["x"])

    @ops_core.plugin_condition("test:always")
    def always(game, run, key):
        return key == "yes"
    try:
        g.fighters["abe"].hp = 1
        go(g, [{"op": "plugin", "id": "test:echo", "args": {"x": 7}},
               {"op": "if", "condition": {"test": "plugin", "id": "test:always", "key": "yes"},
                "then": [{"op": "heal", "target": "hero", "amount": 1}]}])
        assert calls == [7] and g.fighters["abe"].hp == 2
        with pytest.raises(NotImplementedError, match="test:never"):
            go(g, [{"op": "plugin", "id": "test:never"}])
        with pytest.raises(NotImplementedError, match="test:never"):
            go(g, [{"op": "if", "condition": {"test": "plugin", "id": "test:never", "key": "k"}, "then": []}])
    finally:
        ops_core.PLUGINS.pop("test:echo")
        ops_core.PLUGIN_TESTS.pop("test:always")


# ---------------------------------------------------------------- data and pending ops

def all_effect_files():
    return sorted(p for p in EFFECTS_DIR.glob("*.json") if p.name != "schema.json")


def test_every_op_in_the_data_is_known_to_the_registry():
    names = set()
    for path in all_effect_files():
        names |= {o["op"] for o in walk_ops(json.loads(path.read_text(encoding="utf-8")))}
    assert names and names <= set(OPS), sorted(names - set(OPS))
    assert not names & set(PENDING_PHASES), sorted(names & set(PENDING_PHASES))   # every op of the data has a handler


def test_every_card_moment_and_trigger_of_the_box_parses():
    n = 0
    for path in all_effect_files():
        fx = load_effects(path.stem)
        for card in fx.cards.values():
            for moment, ops in card.moments.items():
                EffectRun(ops, Ctx(owner=0), label=moment)
                n += 1
        for t in fx.triggers:
            EffectRun(t["ops"], Ctx(owner=0), label=t["id"])
    assert n > 100


@pytest.mark.parametrize("name,phase", sorted(PENDING_PHASES.items()))
def test_pending_ops_raise_naming_their_phase(g, name, phase):
    with pytest.raises(NotImplementedError, match=f"^{name}: {phase}$"):
        go(g, [{"op": name}])


def test_for_card_loads_the_moment_ops_of_a_real_card(g):
    run = EffectRun.for_card("abe-sapien", "Faster. Stronger.", "after", Ctx(owner=0, this_fid="abe"))
    assert run.label == "after" and run.ctx.moment == "after"
    go_actions = g.actions_left
    run.run(g, ScriptedChooser())
    assert g.actions_left == go_actions + 1
    with pytest.raises(EffectError):
        EffectRun.for_card("abe-sapien", "No Such Card", "after", Ctx(owner=0))
    with pytest.raises(EffectError):
        EffectRun.for_card("abe-sapien", "Faster. Stronger.", "tomorrow", Ctx(owner=0))
    with pytest.raises(EffectError):
        load_effects("nobody")
    assert load_effects("abe-sapien").trigger("intuition_activate")["id"] == "intuition_activate"
    with pytest.raises(EffectError):
        load_effects("abe-sapien").trigger("nope")
    with pytest.raises(EffectError):
        load_effects("abe-sapien").counter_range("rage")


# ---------------------------------------------------------------- choosers

def test_choice_request_validation_and_roundtrip():
    req = ChoiceRequest("cards", 1, [5, 6, 7], 1, 2, 99, "k", "p", {"zone": "hand"})
    assert ChoiceRequest.from_dict(json.loads(json.dumps(req.to_dict()))) == req
    assert req.validate((5, 7)) == [5, 7]
    for bad in ([], [5, 6, 7], [5, 5], [9], "5"):
        with pytest.raises(ValueError):
            req.validate(bad)


def test_pending_choice_matches_the_combat_flow_shape():
    pc = PendingChoice("effect", 1, 77, False, {"key": "after/0:0"})
    assert pc.to_dict() == {"kind": "effect", "player": 1, "card": 77, "deck": False, "key": "after/0:0"}
    from sparring import combat_flow
    assert PendingChoice is combat_flow.PendingChoice and Await is combat_flow.Await


def test_panel_chooser_pauses_and_controller_chooser_uses_the_controller(g):
    req = ChoiceRequest("fighter", 1, ["a", "b"], 1, 1, 5, "fx/0:0")
    pending = PanelChooser().choose(g, req)
    assert isinstance(pending, Await) and pending.choice.kind == "effect" and pending.choice.player == 1
    assert pending.choice.extra["request"]["options"] == ["a", "b"]

    class Picky(Controller):
        def choose_effect(self, game, req):
            return [req.options[-1]]
    g.controllers[1] = Picky()
    assert ControllerChooser().choose(g, req) == ["b"]
    g.controllers.pop(1)
    assert ControllerChooser().choose(g, req) == ["a"]


def test_controller_chooser_falls_back_to_the_legacy_controller_methods(g):
    abe = g.fighters["abe"]
    dests = sorted(g.legal_moves(abe, 2))
    g.controllers[0].moves["abe"] = dests[1]
    go(g, [{"op": "move", "target": "hero", "amount": 2, "up_to": True}], ControllerChooser())
    assert abe.pos == dests[1]
    g.controllers[0].placement = None
    n = len(g.players[0].hand)
    last = g.players[0].hand[-1]
    go(g, [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "amount": 1}}], ControllerChooser())
    assert len(g.players[0].hand) == n - 1 and last in g.players[0].discard
    k = g.fighters["koschei"]
    g.controllers[0].placement = 12
    go(g, [{"op": "place", "target": {"side": "enemy", "name": "Koschei"}, "where": {"any": True}}],
       ControllerChooser())
    assert k.pos == 12
    g.controllers[0].moves.clear()
    pos = abe.pos
    go(g, [{"op": "move", "target": "hero", "amount": 2, "up_to": True}], ControllerChooser())
    assert abe.pos == pos
    run, _ = go(g, [{"op": "draw", "player": "owner", "amount": 3, "up_to": True}], ControllerChooser())
    assert run.done


def test_synthetic_chooser_first_and_random(g):
    req = ChoiceRequest("cards", 0, [1, 2, 3, 4], 0, 3, None, "k")
    assert SyntheticChooser().choose(g, req) == [1, 2, 3]
    rng = random.Random(4)
    picks = {tuple(SyntheticChooser(rng, "random").choose(g, req)) for _ in range(30)}
    assert len(picks) > 3 and all(req.validate(list(p)) == list(p) for p in picks)
    assert SyntheticChooser(rng, "random").choose(g, ChoiceRequest("optional", 0, [True, False], 1, 1)) == [True]
    with pytest.raises(ValueError):
        SyntheticChooser(policy="clever")


def test_scripted_chooser_by_key_and_queue(g):
    ops = [{"op": "draw", "player": "owner", "amount": 3, "up_to": True},
           {"op": "draw", "player": "owner", "amount": 3, "up_to": True}]
    n = len(g.players[0].hand)
    go(g, ops, ScriptedChooser(by_key={"fx/1:0": [2]}, queue=[[1]]))
    assert len(g.players[0].hand) == n + 3


def test_run_without_chooser_raises(g):
    run = EffectRun([{"op": "draw", "player": "owner", "amount": 2, "up_to": True}], Ctx(owner=0))
    with pytest.raises(EffectError):
        run.run(g, None)


# ---------------------------------------------------------------- re-entrancy

ROUNDTRIP_OPS = [
    {"op": "draw", "player": "owner", "amount": 1},
    {"op": "choose_effect", "amount": 2, "distinct": True, "options": [
        {"label": "move", "ops": [{"op": "move", "target": "hero", "amount": 2, "up_to": True}]},
        {"label": "hurt", "ops": [{"op": "if", "condition": {"test": "compare", "left": 1, "op": "==", "right": 1},
                                  "then": [{"op": "damage", "target": {"side": "enemy", "kind": "hero"},
                                            "amount": 2}]}]}]},
    {"op": "for_each", "over": {"players": "all"}, "as": "p",
     "ops": [{"op": "discard", "cards": {"zone": "hand", "player": "$p", "amount": 1, "chooser": "$p"}}]},
    {"op": "optional", "chooser": "opponent", "ops": [{"op": "heal", "target": "hero", "amount": 1}],
     "else": [{"op": "damage", "target": "hero", "amount": 1}]},
]


def test_run_roundtrip_mid_op(bprd):
    """Run to an Await, serialize run and game, reload both into a fresh twin, resume: same result as one run."""
    straight = mk(bprd)
    recorder = ScriptedChooser()
    EffectRun(ROUNDTRIP_OPS, Ctx(owner=0, this_fid="abe")).run(straight, recorder)
    answers = [default_answer(r) for r in recorder.requests]
    assert len(answers) >= 4

    game = mk(bprd)
    run = EffectRun(ROUNDTRIP_OPS, Ctx(owner=0, this_fid="abe"))
    panel = PanelChooser()
    pauses = 0
    while (pending := run.run(game, panel)) is not None:
        assert pending.choice.kind == "effect"
        saved_run = json.dumps(run.to_dict())
        saved_game = json.dumps(persist.game_to_dict(game))
        game = mk(bprd)                            # another process: a new Game with the saved state applied
        persist.apply_game(game, json.loads(saved_game))
        run = EffectRun.from_dict(json.loads(saved_run))
        assert run.awaiting.key == pending.choice.extra["key"]
        run.resume(answers[pauses])
        pauses += 1
    assert pauses == len(answers)
    assert snap(game) == snap(straight)


def test_resume_rejects_bad_answers_and_a_run_that_is_not_waiting(g):
    run = EffectRun([{"op": "draw", "player": "owner", "amount": 3, "up_to": True}], Ctx(owner=0))
    with pytest.raises(EffectError):
        run.resume([1])
    assert run.run(g, PanelChooser()) is not None
    with pytest.raises(ValueError):
        run.resume([9])
    assert run.awaiting is not None
    again = run.step(g, PanelChooser())
    assert again.choice.extra["key"] == run.awaiting.key
    run.resume([2])
    n = len(g.players[0].hand)
    assert run.run(g, PanelChooser()) is None and len(g.players[0].hand) == n + 2


ATOMIC_CASES = {
    "damage": [{"op": "damage", "target": {"side": "enemy"}, "amount": 1}],
    "heal": [{"op": "heal", "target": {"side": "own"}, "amount": 1}],
    "set_hp": [{"op": "set_hp", "target": {"side": "own"}, "amount": 1}],
    "draw": [{"op": "draw", "player": "owner", "amount": 2, "up_to": True}],
    "discard": [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "amount": 2}}],
    "choose": [{"op": "choose", "cards": {"zone": "hand", "player": "owner", "amount": 2}, "as": "x"}],
    "choose_effect": [{"op": "choose_effect", "amount": 1, "options": [{"label": "a", "ops": []},
                                                                      {"label": "b", "ops": []}]}],
    "move": [{"op": "move", "target": {"side": "own"}, "amount": 2, "up_to": True}],
    "place": [{"op": "place", "target": {"side": "own"}, "where": {"any": True}}],
    "swap": [{"op": "swap", "target": {"side": "own"}, "with": {"side": "enemy"}}],
    "optional": [{"op": "optional", "ops": [{"op": "draw", "player": "owner", "amount": 1}]}],
    "for_each": [{"op": "for_each", "over": {"fighters": {"side": "own", "pick": "all"}}, "as": "f", "ops": []}],
}


@pytest.mark.parametrize("name", sorted(ATOMIC_CASES))
def test_op_atomic_no_mutation_before_await(bprd, name):
    g = mk(bprd)
    before = snap(g)
    run = EffectRun(ATOMIC_CASES[name], Ctx(owner=0, this_fid="abe"))
    pending = run.run(g, PanelChooser())
    assert pending is not None and snap(g) == before
    assert g.rng.getstate() == mk(bprd).rng.getstate()


class PauseOnSecondAsk:
    """Answers the first request, pauses on the second: the first answer must not leak into the game."""

    def __init__(self):
        self.n = 0

    def choose(self, game, req):
        self.n += 1
        return req.to_await() if self.n == 2 else [req.options[0]]


def test_atomic_when_the_pause_comes_after_a_planned_choice(bprd):
    g = mk(bprd)
    before = snap(g)
    pos = {fid: f.pos for fid, f in g.fighters.items()}
    ops = [{"op": "move", "target": {"side": "own", "pick": "all"}, "amount": 2, "up_to": True}]
    run = EffectRun(ops, Ctx(owner=0, this_fid="abe"))
    assert run.run(g, PauseOnSecondAsk()) is not None
    assert snap(g) == before and {fid: f.pos for fid, f in g.fighters.items()} == pos
    assert list(run.answers) == ["fx/0:0"]


@ops_core.plugin("test:roll_then_ask")
def _roll_then_ask(run, game, spec):
    picked = run.random_sample(list(range(1000)), 3)
    got = run.ask(game, "optional", run.ctx.owner, [True, False], 1, 1, "go?")
    game.fighters["abe"].hp = picked[0] + (1000 if got[0] else 0)


def test_random_picks_are_not_rerolled_when_an_op_reruns_after_an_await(bprd):
    straight, paused = mk(bprd), mk(bprd)
    ops = [{"op": "plugin", "id": "test:roll_then_ask"}]
    EffectRun(ops, Ctx(owner=0)).run(straight, ScriptedChooser([[True]]))
    run = EffectRun(ops, Ctx(owner=0))
    assert run.run(paused, PanelChooser()) is not None
    run.resume([True])
    assert run.run(paused, PanelChooser()) is None
    assert paused.fighters["abe"].hp == straight.fighters["abe"].hp
    assert paused.rng.getstate() == straight.rng.getstate()


def test_answers_are_dropped_once_the_op_completes_and_keys_include_loop_position(bprd):
    g = mk(bprd)
    ops = [{"op": "for_each", "over": {"players": "all"}, "as": "p",
            "ops": [{"op": "draw", "player": "$p", "amount": 2, "up_to": True, "chooser": "$p"}]}]
    chooser = ScriptedChooser()
    run = EffectRun(ops, Ctx(owner=0))
    run.run(g, chooser)
    assert [r.key for r in chooser.requests] == ["fx/0/ops@0/0:0", "fx/0/ops@1/0:0"]
    assert run.answers == {}


# ---------------------------------------------------------------- state, hooks, persistence

def test_fx_is_empty_by_default_and_cloned_independently(g):
    assert g.fx.is_empty() and g.fx.dsl_heroes == set()
    g.fx.dsl_heroes.add("medusa")
    g.fx.set_ongoing(0, 5)
    g.fx.set_counter(1, "rage", 2)
    g.fx.statuses.append({"name": "x"})
    g.fx.modifiers.append({"kind": "rule"})
    g.fx.turn_start_pos["abe"] = 3
    g.fx.attacked.append("abe")
    c = g.clone()
    assert c.fx.to_dict() == g.fx.to_dict() and c.fx is not g.fx
    c.fx.dsl_heroes.add("x")
    c.fx.statuses[0]["name"] = "y"
    c.fx.counters[1]["rage"] = 0
    assert g.fx.dsl_heroes == {"medusa"} and g.fx.statuses[0]["name"] == "x" and g.fx.counter_value(1, "rage") == 2
    assert g.fx.set_ongoing(0, 6) == 5 and g.fx.take_ongoing(0) == 6 and g.fx.take_ongoing(0) is None


def test_fx_persistence_omits_the_key_when_empty_and_roundtrips(bprd):
    g = mk(bprd)
    assert "fx" not in persist.game_to_dict(g)
    g.fx.dsl_heroes.add("abe-sapien")
    g.fx.set_ongoing(1, 9)
    g.fx.set_counter(0, "intuition", 2)
    g.fx.statuses.append({"name": "cannot_draw", "player": 0})
    g.fx.modifiers.append({"kind": "rule", "rule": "max_hand_size", "amount": 3})
    g.fx.turn_start_pos["abe"] = 3
    g.fx.attacked.append("abe")
    saved = json.loads(json.dumps(persist.game_to_dict(g)))
    other = mk(bprd)
    persist.apply_game(other, saved)
    assert other.fx.to_dict() == g.fx.to_dict()
    old = dict(saved)
    del old["fx"]
    persist.apply_game(other, old)
    assert other.fx.is_empty()


class SpyFx(EffectState):
    def __init__(self):
        super().__init__()
        self.events = []
        self.block_draw = False
        self.block_actions = False
        self.damage_delta = 0

    def emit(self, name, *args):
        self.events.append(name)

    def adjust_damage(self, fighter, n, source):
        return n + self.damage_delta

    def can_draw(self, player):
        return not self.block_draw

    def can_gain_actions(self, player):
        return not self.block_actions


def test_engine_calls_every_hook(game, ctl):
    spy = game.fx = SpyFx()
    game.begin_turn()
    game.end_turn()
    game.turn = 0
    assert spy.events == ["start_of_turn", "end_of_turn"]
    spy.events.clear()
    card = give(game, 0, "Dash")
    game.discard_card(0, card)
    assert spy.events == ["card_discarded"]
    spy.events.clear()
    give(game, 0, "Snipe")
    game.force_discard(0, 1, "test")
    assert spy.events == ["force_discard", "card_discarded"]
    spy.events.clear()
    game.maneuver(0, {})
    assert spy.events == ["after_maneuver"]
    spy.events.clear()
    harpy = game.fighters["harpy1"]
    game.damage(harpy, 99)
    assert spy.events == ["fighter_defeated"] and not harpy.alive


def test_attack_hook_fires_before_the_defense_is_chosen(game, ctl):
    spy = game.fx = SpyFx()
    medusa, hellboy = game.hero(0), game.hero(1)
    place(game, hellboy=sorted(game.board.adj[medusa.pos])[0])
    for f in game.fighters.values():
        if f is not hellboy and f.pos == hellboy.pos:
            f.pos = 31
    attack = next(c for c in game.players[0].full_set if c.can_attack and c.usable_by("Medusa"))
    game.players[0].hand.append(attack)
    seen = []
    ctl[1].choose_defense = lambda g, a, t: seen.append(list(spy.events)) or None
    game.attack(medusa, hellboy, attack)
    assert seen == [["attacked"]]


def test_damage_draw_and_action_hooks_can_change_the_outcome(game):
    spy = game.fx = SpyFx()
    f = game.fighters["hellboy"]
    hp = f.hp
    spy.damage_delta = 1
    game.damage(f, 2)
    assert f.hp == hp - 3
    spy.damage_delta = -5
    assert game.damage(f, 2) == 0 and f.hp == hp - 3
    spy.block_draw = True
    assert game.draw(0, 2) == [] and game.players[0].hand == []
    spy.block_actions = True
    game.grant_actions(2)
    assert game.actions_left == 2


def test_default_hooks_are_inert():
    fx = EffectState()
    assert fx.adjust_damage(None, 3, "effect") == 3 and fx.can_draw(0) and fx.can_gain_actions(1)
    assert fx.emit("anything", 1, 2) is None


def test_hiss_and_slither_in_defense_reports_medusas_owner_as_the_source(game):
    """Medusa defends on Hellboy's turn: the forcing player is Medusa (0), not the turn player (1)."""
    calls = []

    class Spy(SpyFx):
        def can_force_discard(self, player, source_player):
            calls.append((player, source_player))
            return True
    game.fx = Spy()
    place(game, medusa=3, hellboy=4)
    game.turn = 1
    game.begin_turn()
    hiss = give(game, 0, "Hiss and Slither")
    pistol = give(game, 1, "Service Pistol")
    game.players[1].hand.extend(game.players[1].deck[:2])
    game.attack(game.fighters["hellboy"], game.fighters["medusa"], pistol, def_card=hiss)
    assert calls == [(1, 0)]
    calls.clear()
    game.turn = 0
    give(game, 0, "Dash")
    game.force_discard(0, 1, "hand limit")
    assert calls == [(0, 0)]
