"""The bot's Raptors (ISMCTS, what the live bot runs; `make_bot_ai({"ai": "ismcts"})`): super aggressive and a pack.

Iván's requirements: (1) they swarm and attack every turn they can, and they set up pack attacks (Raptors adjacent to the defender, the
+1 of their ability); (2) careful with the zone damage of a rival hero (F-RIVAL-ZONE-DAMAGE: Medusa's gaze), priced per fighter because
they are three fighters of 7 life each, and still attacking a rival with no zone damage. The search is deterministic for a seed and an
iteration cap, so the scenes below are reproducible."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import pack
from sparring.ai_hazards import zone_cover_factor, zone_damage, zone_exposed
from sparring.board import Board
from sparring.hellboy_script import ScriptedHellboy
from sparring.search.adapter import EngineState, PACK, attack_values, sidekick_plan
from sparring.search.controller import make_bot_ai
from sparring.state import Game

BOARD = "bprd-hq"
ATTACK_HAND = ("Eviscerate", "Eviscerate", "They Remember", "Clever Girl", "Pack Hunters")
TEAM = ("blue", "delta", "echo")


@pytest.fixture(autouse=True)
def raptors_are_interpreted(monkeypatch):
    """Until `INTERPRETED_HEROES` lists the Raptors (a shared file) the tests list them themselves."""
    from sparring.effects import state
    monkeypatch.setattr(state, "INTERPRETED_HEROES", state.INTERPRETED_HEROES | {"raptors"})


def scene(seed: int, foe: str = "hellboy", hand=ATTACK_HAND, iterations: int = 150, bot: str = "raptors"):
    """The bot's turn with `hand`, the rival's hand empty; every piece wherever the board's setup put it (the caller places them)."""
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": iterations, "ai_time_budget": 60, "ai_seed": seed}, 0)
    g = Game.new(Board.load(BOARD), seed, controllers={0: ai, 1: ScriptedHellboy(1, seed)}, heroes=(bot, foe), bot_player=0)
    g.turn, g.turn_no = 0, 3
    g.begin_turn()
    st = g.players[0]
    st.deck.extend(st.hand)
    st.hand.clear()
    for i, title in enumerate(hand):
        give(g, 0, title, nth=hand[:i].count(title))
    g.players[1].hand.clear()
    return g, ai


def arrange(g, rival_pos: int, beside: tuple, two_away: tuple, far=None):
    """The rival hero on `rival_pos`, the fighters of `beside` on spaces next to it, those of `two_away` two spaces from it (so one
    Maneuver closes them up), every other piece of the rival far away."""
    b = g.board
    taken = {rival_pos}
    rival = g.hero(1)
    rival.pos = rival_pos
    ring1 = [s for s in sorted(b.adj[rival_pos])]
    ring2 = [s for s in sorted(b.spaces) if b.distance(rival_pos, s) == 2 and s not in b.adj[rival_pos]]
    for fid in beside:
        s = next(s for s in ring1 if s not in taken)
        g.fighters[fid].pos = s
        taken.add(s)
    for fid in two_away:
        s = next(s for s in ring2 if s not in taken)
        g.fighters[fid].pos = s
        taken.add(s)
    farthest = sorted((s for s in b.spaces if s not in taken), key=lambda s: -b.distance(rival_pos, s))
    for f in g.foes(0):
        if f is not rival:
            f.pos = farthest.pop(0)
    return g


def play_the_turn(g, ai):
    """The bot's whole turn; (attacks it made as (attacker, target, other Raptors beside the target), the board it ends on)."""
    made = []
    attack = g.attack

    def watch(att, tgt, *a, **k):
        made.append((att.fid, tgt.fid, len(pack.mates_adjacent(g, att, tgt))))
        return attack(att, tgt, *a, **k)

    g.attack = watch
    ai.take_turn(g)
    assert ai.fallbacks == 0, "the search fell back to the heuristic AI: the test would not be measuring it"
    return made, {f.fid: f.pos for f in g.own(0)}


SPOTS = [3, 7, 10, 17, 22, 26]


# ---------------------------------------------------------------- the swarm: a policy of its own

def test_the_pack_policy_is_offered_to_the_raptors_and_to_no_other_hero():
    g, _ = scene(0)
    assert PACK in EngineState(g, observer=0)._policies(0)
    other, _ = scene(0, bot="sinbad", hand=())
    assert PACK not in EngineState(other, observer=0)._policies(0)


def test_the_followers_of_the_pack_policy_end_beside_the_rival_the_hero_stands_next_to():
    g, _ = scene(1)
    arrange(g, 7, beside=("blue",), two_away=("delta", "echo"))
    hellboy, blue = g.hero(1), g.fighters["blue"]
    plan = dict(sidekick_plan(g, 0, 0, PACK, hero_dest=blue.pos))
    assert set(plan) == {"delta", "echo"} and plan["delta"] != plan["echo"]
    assert all(plan[fid] in g.board.adj[hellboy.pos] for fid in plan)
    assert all(g.board.distance(g.fighters[fid].pos, plan[fid]) <= g.fighters[fid].move for fid in plan)


def test_a_follower_that_cannot_get_beside_the_rival_gets_as_close_as_it_can():
    g, _ = scene(1)
    arrange(g, 7, beside=("blue",), two_away=("delta",))
    far = max((s for s in g.board.spaces if s not in {f.pos for f in g.fighters.values() if f.alive}), key=lambda s: g.board.distance(7, s))
    g.fighters["echo"].pos = far
    plan = dict(sidekick_plan(g, 0, 0, PACK, hero_dest=g.fighters["blue"].pos))
    assert g.board.distance(plan["echo"], 7) < g.board.distance(far, 7)


# ---------------------------------------------------------------- attacks every turn it can

def test_with_a_blow_to_land_the_last_action_is_never_a_maneuver():
    g, _ = scene(0)
    arrange(g, 7, beside=("blue",), two_away=("delta", "echo"))
    for left, walks in ((1, False), (2, True)):
        g.actions_left = left
        moves = EngineState(g, observer=0).legal_moves()
        assert any(m[0] == "attack" for m in moves)
        assert any(m[0] == "maneuver" for m in moves) == walks, (left, moves)


def test_any_other_hero_keeps_its_maneuver_on_the_last_action():
    g, _ = scene(0, bot="bigfoot", hand=("Larger Than Life", "Savagery", "Crash Through the Trees"))
    hero, rival = g.hero(0), g.hero(1)
    rival.pos = 7
    hero.pos = sorted(g.board.adj[7])[0]
    g.actions_left = 1
    moves = EngineState(g, observer=0).legal_moves()
    assert any(m[0] == "attack" for m in moves) and any(m[0] == "maneuver" for m in moves)


@pytest.mark.parametrize("seed", range(6))
def test_ismcts_attacks_every_turn_it_can_against_a_rival_with_no_zone_damage(seed):
    g, ai = scene(seed)
    arrange(g, SPOTS[seed], beside=("blue",), two_away=("delta", "echo"))
    assert zone_damage(g, 1) == 0.0
    made, _ = play_the_turn(g, ai)
    assert made, "a Raptor with a rival beside it and five attack cards did not attack"


@pytest.mark.parametrize("seed", range(6))
def test_ismcts_still_attacks_the_rival_hero_that_deals_zone_damage(seed):
    """Medusa's gaze costs the Raptors standing in her zone, and an attack on her is made from her zone: the price never stops the blow."""
    g, ai = scene(seed, foe="medusa")
    arrange(g, SPOTS[seed], beside=("blue",), two_away=("delta", "echo"))
    assert zone_damage(g, 1) == pytest.approx(1.0)
    made, _ = play_the_turn(g, ai)
    assert made, "the Raptors held back from the rival hero because of her zone damage"


# ---------------------------------------------------------------- the pack: Raptors beside the defender

def test_the_search_sets_up_pack_attacks_with_the_other_raptors_beside_the_defender():
    """Blue beside the rival, Delta and Echo two spaces off: over the six scenes the blows land with a mate beside the defender in most of them
    and the three end the turn next to the same rival (the pack did not exist before: 19 % of the blows had a mate)."""
    packed, pack_total, ends = 0, 0, 0
    for seed in range(6):
        g, ai = scene(seed)
        arrange(g, SPOTS[seed], beside=("blue",), two_away=("delta", "echo"))
        made, board = play_the_turn(g, ai)
        packed += any(mates for _, _, mates in made)
        pack_total += sum(mates for _, _, mates in made)
        ends += len([fid for fid in TEAM if board[fid] in g.board.adj[SPOTS[seed]]]) >= 2
    assert packed >= 5 and pack_total >= 8, (packed, pack_total)
    assert ends >= 4, ends


def test_a_pack_beside_the_same_rival_is_worth_more_to_the_search_than_the_same_fighters_spread_out():
    g, _ = scene(0)
    arrange(g, 7, beside=("blue", "delta", "echo"), two_away=())
    joined = EngineState(g, observer=0)
    assert joined._pack_ready(0) == 2
    spread, _ = scene(0)
    arrange(spread, 7, beside=("blue",), two_away=("delta", "echo"))
    apart = EngineState(spread, observer=0)
    assert apart._pack_ready(0) == 0
    assert joined._side_value(0) > apart._side_value(0)
    other, _ = scene(0, bot="sinbad", hand=())
    assert EngineState(other, observer=0)._pack_ready(0) == 0           # no other hero is paid for standing together


# ---------------------------------------------------------------- the zone damage of a rival hero, per fighter

def medusa_scene(inside: int, order=TEAM):
    """Medusa on 7 and the first `inside` Raptors of `order` in her zone (far from her, nothing to attack), the others outside it; hands empty."""
    g, _ = scene(0, foe="medusa", hand=())
    b = g.board
    rival = g.hero(1)
    rival.pos = 7
    taken = {7}
    for f in g.foes(0):
        if f is not rival:
            f.pos = None
            f.alive = False
    zone = [s for s in sorted(b.spaces) if b.share_zone(7, s) and b.distance(7, s) >= 3 and s not in taken]
    out = [s for s in sorted(b.spaces, reverse=True) if not b.share_zone(7, s) and s not in taken]
    for i, fid in enumerate(order):
        g.fighters[fid].pos = zone[i] if i < inside else out[i]
    return g


def test_the_zone_damage_is_priced_per_raptor_standing_in_the_zone():
    prices = []
    for inside in range(4):
        g = medusa_scene(inside)
        assert len(zone_exposed(g, 0, g.hero(1))) == inside
        prices.append(EngineState(g, observer=0)._zone_exposure(0, g.hero(0)))
    assert prices[0] == (0.0, 0.0)
    one = prices[1][0]
    assert one == pytest.approx(1 / 7)                                    # 1 damage on a fighter of 7 life, no defense in hand
    assert [p[0] for p in prices] == pytest.approx([0, one, 2 * one, 3 * one])
    assert all(p[1] == 0.0 for p in prices)                               # no Raptor dies of it, and the game is lost only with the last one


def test_the_search_threat_grows_with_each_follower_in_the_zone():
    """Delta and Echo in the gaze (Blue, the hero the rival's attacks are measured on, outside her reach): each adds its own share."""
    values = []
    for inside in range(3):
        g = medusa_scene(inside, order=("delta", "echo", "blue"))
        values.append(EngineState(g, observer=0).threat(0, urgent=True)[0])
    assert values == sorted(values) and len(set(values)) == 3
    assert values[2] - values[0] == pytest.approx(2 * (values[1] - values[0])) and values[1] - values[0] == pytest.approx(1 / 7)


def test_a_hero_with_no_team_is_still_priced_by_its_hero_alone():
    g, _ = scene(0, foe="medusa", bot="bigfoot", hand=())
    rival = g.hero(1)
    rival.pos = 7
    b = g.board
    zone = [s for s in sorted(b.spaces) if b.share_zone(7, s) and b.distance(7, s) >= 3]
    g.fighters["jackalope"].pos = zone[0]                                # the sidekick stands in the gaze: not priced
    g.hero(0).pos = next(s for s in sorted(b.spaces, reverse=True) if not b.share_zone(7, s))
    assert zone_exposed(g, 0, rival) == []
    g.hero(0).pos = zone[1]
    assert zone_exposed(g, 0, rival) == [g.hero(0)]


def test_a_rival_with_no_zone_damage_costs_the_raptors_nothing_for_standing_beside_it():
    g, _ = scene(0, hand=())
    arrange(g, 7, beside=("blue", "delta", "echo"), two_away=())
    assert EngineState(g, observer=0)._zone_exposure(0, g.hero(0)) == (0.0, 0.0)


def test_a_wounded_raptor_in_the_gaze_costs_more_than_a_healthy_one_and_the_last_one_may_die_of_it():
    g = medusa_scene(1)
    exposed, = zone_exposed(g, 0, g.hero(1))
    healthy = EngineState(g, observer=0)._zone_exposure(0, g.hero(0))
    exposed.hp = 1
    hurt = EngineState(g, observer=0)._zone_exposure(0, g.hero(0))
    assert hurt[0] > healthy[0] and hurt[0] == pytest.approx(1.0) and hurt[1] == 0.0
    for fid in TEAM:                                                      # only that Raptor is left
        if g.fighters[fid] is not exposed:
            g.defeat(g.fighters[fid])
    assert EngineState(g, observer=0)._zone_exposure(0, exposed)[1] == 1.0


def test_defenses_in_hand_ease_the_hit_points_of_every_raptor_in_the_zone():
    g = medusa_scene(2)
    bare = EngineState(g, observer=0)._zone_exposure(0, g.hero(0))[0]
    give(g, 0, "Decoy")
    give(g, 0, "Decoy", nth=1)
    covered = EngineState(g, observer=0)._zone_exposure(0, g.hero(0))[0]
    values = attack_values(g.players[1], g.hero(1).name)
    assert covered == pytest.approx(bare * zone_cover_factor([3, 3], sum(values) / len(values)))
    assert covered < bare


def test_ismcts_plays_a_defense_against_the_raptors_ambush_without_falling_back_to_the_heuristic():
    """Regression: a rival's Counterhex Shield vetoed Ambush's discard in a rollout, `$burnt` stayed unbound and the whole search
    fell back (the Abe Sapien matrix pair). Abe defends with the ONGOING in play against an Ambush."""
    from sparring.effects import modifiers
    from sparring.effects.model import load_effects
    ai = make_bot_ai({"ai": "ismcts", "ai_iterations": 40, "ai_time_budget": 60, "ai_seed": 1}, 0)
    g = Game.new(Board.load(BOARD), 1, controllers={0: ai, 1: ScriptedHellboy(1, 1)}, heroes=("abe-sapien", "raptors"), bot_player=0)
    g.turn, g.turn_no = 1, 3
    g.begin_turn()
    for m in load_effects("abe-sapien").card("Counterhex Shield").ongoing["modifiers"]:
        modifiers.add_modifier(g.fx, 0, 999, m)
    arrange_pair = g.fighters["blue"], g.hero(0)
    blue, abe = arrange_pair
    blue.pos = sorted(g.board.adj[abe.pos])[0] if abe.pos is not None else blue.pos
    ambush = give(g, 1, "Ambush")
    g.players[0].hand.clear()
    for c in [c for c in g.players[0].full_set if c.can_defend][:3]:
        g.players[0].hand.append(c)
    ai.choose_defense(g, blue, abe, ambush)
    assert ai.fallbacks == 0
