"""Live game (Hellboy bot vs human Raphael): with 6 HP and no card that defends, the bot kept maneuvering beside the
rival's fighters and took two undefended blows (Crowd control, Unbridled rage) in one turn. When it cannot defend and
the rival can kill it with the two actions of its turn, it must not end the turn in reach: at 4 hit points or fewer it
only runs (the maneuver away, then Pancakes!); at 5 or 6 its blow may come first and the last action walks away
(F-FLEE-CHASER); with the rival hero one blow from falling it finishes it."""
import pytest

from conftest import Scripted, give
from sparring.ai_medusa import MedusaAI
from sparring.state import Game

RAPHAEL, CASEY = 30, 19
BESIDE_RAPHAEL = 29          # adjacent to Raphael (same zone as Casey's line)
ATTACK_ONLY = ["Excalibur", "Right Hand Of Doom", "Second Shot", "Pancakes!"]


def scene(bprd, hand, hp=6, hellboy=BESIDE_RAPHAEL, raphael_hp=17, anung=False):
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()}, bot_player=0, heroes=("hellboy", "raphael"))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    seen = {}
    for title in hand:
        seen[title] = seen.get(title, -1) + 1
        give(g, 0, title, seen[title])
    f = g.fighters
    f["hellboy"].pos, f["hellboy"].hp = hellboy, hp
    f["lobster"].pos, f["raphael"].pos, f["casey"].pos = 6, RAPHAEL, CASEY
    f["raphael"].hp = raphael_hp
    rival = g.players[1]
    while len(rival.hand) < 5:
        rival.hand.append(rival.deck.pop(0))
    return g


def gap(g, a="hellboy", b="raphael"):
    return g.board.distance(g.fighters[a].pos, g.fighters[b].pos)


@pytest.mark.parametrize("hp", [6, 5, 4, 3])
def test_defenseless_and_low_never_ends_the_turn_in_reach(bprd, hp):
    g = scene(bprd, ATTACK_ONLY, hp=hp)
    before = gap(g)
    MedusaAI(0).take_turn(g)
    hb, rival = g.fighters["hellboy"], g.fighters["raphael"]
    assert hb.alive and g.actions_left == 0
    assert g.drawn[0] >= 1, "it maneuvered (drew): the last action walks away"
    assert gap(g) > before
    assert not g.board.can_reach_target(rival.pos, hb.pos, False), "out of Raphael's reach"
    assert not g.board.can_reach_target(g.fighters["casey"].pos, hb.pos, True), "out of Casey's line (ranged)"


@pytest.mark.parametrize("hp", [4, 3])
def test_defenseless_and_very_low_runs_without_striking(bprd, hp):
    """The lesson as it was learnt: no attack, Pancakes! for the two hit points and the maneuver away."""
    g = scene(bprd, ATTACK_ONLY, hp=hp)
    MedusaAI(0).take_turn(g)
    assert g.fighters["raphael"].hp == 17, "no attack was made"
    assert [c.title for c in g.players[0].discard] == ["Pancakes!"] and g.fighters["hellboy"].hp == hp + 2
    assert gap(g) == 6


def test_at_six_hit_points_the_blow_comes_before_the_run(bprd):
    """Excalibur on Raphael (who does not defend here), then out of his reach: as far as the two actions get him."""
    g = scene(bprd, ATTACK_ONLY)
    MedusaAI(0).take_turn(g)
    assert g.fighters["raphael"].hp == 11 and [c.title for c in g.players[0].discard] == ["Excalibur"]
    assert gap(g) == 3


def test_defenseless_with_lethal_available_attacks(bprd):
    g = scene(bprd, ATTACK_ONLY, raphael_hp=1)
    act = MedusaAI(0).plan(g)
    assert act.kind == "attack" and act.target == "raphael"


def test_with_a_defense_card_it_keeps_normal_play(bprd):
    """Same board, but two cards that defend: no card is burnt to run, the kiting is the usual one."""
    g = scene(bprd, ["Excalibur", "Right Hand Of Doom", "B.P.R.D. Training", "Planned Recklessness"], hp=9)
    act = MedusaAI(0).plan(g)
    assert act.boost is None


def test_free_move_prefers_safety_when_defenseless(bprd):
    """ANUNG UN RAMA's start-of-turn move (choose_move) used to be restricted to squares that reach a rival whenever
    the hand held an attack: that walked a 6 HP Hellboy next to the fighters that killed it."""
    g = scene(bprd, ATTACK_ONLY, hellboy=27)
    hb, rival = g.fighters["hellboy"], g.fighters["raphael"]
    dest = MedusaAI(0).choose_move(g, hb, 3)
    assert dest is not None
    assert not g.board.can_reach_target(dest, rival.pos, False)
    assert not g.board.can_reach_target(dest, g.fighters["casey"].pos, True)


def test_free_move_still_goes_for_the_attack_when_healthy(bprd):
    g = scene(bprd, ["Excalibur", "Right Hand Of Doom", "B.P.R.D. Training", "Planned Recklessness"], hp=18, hellboy=27)
    hb, rival = g.fighters["hellboy"], g.fighters["raphael"]
    dest = MedusaAI(0).choose_move(g, hb, 3)
    assert g.board.can_reach_target(dest, rival.pos, False) or g.board.can_reach_target(dest, g.fighters["casey"].pos, True)
