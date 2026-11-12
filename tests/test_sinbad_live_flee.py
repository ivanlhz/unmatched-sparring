"""F-FLEE-CHASER: a hero next to a rival that chases it strikes before it steps back.

The states are the bot's own decisions in the first live game of 11/11 (Sinbad, the bot, against a Hellboy played by a person, on
Baskerville Manor), rebuilt from the session log: positions, hit points, hands and both discard piles. Sinbad attacked once in
nine turns: every other action was a maneuver away from a Hellboy that reached him anyway. The second game of that day (King
Solomon's Mine) is not rebuilt here."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import sparring.ai_medusa as ai_medusa
from sparring.ai_medusa import MedusaAI
from sparring.board import Board
from sparring.hellboy_script import ChasingHellboy, ScriptedHellboy
from sparring.state import Game
from sparring import persist, sim

FATE, REGROUP, TOIL = "By Fortune and Fate", "Regroup", "Toil and Danger"
APES, CANNIBALS, WHALE, COALS = (
    "Voyage to the City of the Man-Eating Apes", "Voyage to the Cannibals With the Root of Madness",
    "Voyage to the Island That Was a Whale", "Voyage to the Creature With Eyes Like Coals of Fire")
CROWN, HORSESHOES, CONFRONT, DOOM, TRAINING, SHOT, GLIMPSE, EXCALIBUR, EARTH = (
    "And Upon His Brow Is Set A Crown Of Flame", "Horseshoes And Hand Grenades", "Confront Any Demon or God", "Right Hand Of Doom",
    "B.P.R.D. Training", "Second Shot", "Glimpse Of Hell", "Excalibur", "On Earth As It Is In Hell")
MANOR = "baskerville-manor"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
PILE_T6 = ["Exploit", "Commanding Impact", COALS, TOIL, "Feint"]
RIVAL_T6 = [CROWN, HORSESHOES, CONFRONT, DOOM, TRAINING]

# name: the turn of the live game; `rival_hand`: cards the person held (counted from the log's draws and discards)
LIVE = {
    "manor_t6": dict(board=MANOR, hand=[FATE, REGROUP, FATE, REGROUP, APES], pos=dict(sinbad=8, porter=0, hellboy=9, lobster=4),
                     hp=dict(sinbad=12, porter=5, hellboy=16, lobster=6), pile=PILE_T6, rival_pile=RIVAL_T6, rival_hand=4),
    "manor_t8": dict(board=MANOR, hand=[FATE, FATE, REGROUP, APES, CANNIBALS], pos=dict(sinbad=3, porter=0, hellboy=10, lobster=9),
                     hp=dict(sinbad=11, porter=4, hellboy=16, lobster=6), pile=PILE_T6 + [REGROUP, TOIL],
                     rival_pile=RIVAL_T6 + [HORSESHOES], rival_hand=4),
    "manor_t10": dict(board=MANOR, hand=[FATE, FATE, REGROUP, APES, CANNIBALS, WHALE], pos=dict(sinbad=4, porter=0, hellboy=5, lobster=10),
                      hp=dict(sinbad=9, porter=4, hellboy=16, lobster=6), pile=PILE_T6 + [REGROUP, TOIL, "Feint"],
                      rival_pile=RIVAL_T6 + [HORSESHOES, DOOM], rival_hand=4),
    "manor_t12": dict(board=MANOR, hand=[FATE, FATE, APES, CANNIBALS, WHALE, REGROUP], pos=dict(sinbad=7, porter=0, hellboy=5, lobster=9),
                      hp=dict(sinbad=7, porter=4, hellboy=16, lobster=6), pile=PILE_T6 + [REGROUP, TOIL, "Feint", REGROUP, "Momentous Shift"],
                      rival_pile=RIVAL_T6 + [HORSESHOES, DOOM, SHOT, GLIMPSE], rival_hand=3),
    "manor_t16": dict(board=MANOR, hand=[FATE, APES, CANNIBALS, WHALE, REGROUP, TOIL], pos=dict(sinbad=6, porter=4, hellboy=5, lobster=10),
                      hp=dict(sinbad=5, porter=4, hellboy=16, lobster=3),
                      pile=PILE_T6 + [REGROUP, TOIL, "Feint", REGROUP, "Momentous Shift", FATE, "Leap Away", "Momentous Shift", "Exploit"],
                      rival_pile=RIVAL_T6 + [HORSESHOES, DOOM, SHOT, GLIMPSE, DOOM, GLIMPSE, EXCALIBUR], rival_hand=5),
}


def live(name: str) -> Game:
    """The live state `name` at the start of the bot's turn (two actions)."""
    s = LIVE[name]
    g = Game.new(Board.load(s["board"]), 3, {0: MedusaAI(0), 1: ScriptedHellboy(1)}, bot_player=0, heroes=("sinbad", "hellboy"))
    for player, hand, pile in ((0, s["hand"], s["pile"]), (1, None, s["rival_pile"])):
        st = g.players[player]
        st.deck = list(st.full_set)
        take = lambda title: st.deck.pop(next(i for i, c in enumerate(st.deck) if c.title == title))
        st.discard = [take(t) for t in pile]
        st.hand = [take(t) for t in hand] if hand is not None else [st.deck.pop() for _ in range(s["rival_hand"])]
    for fid, space in s["pos"].items():
        g.fighters[fid].pos = space
    for fid, hp in s["hp"].items():
        g.fighters[fid].hp = hp
    g.turn, g.turn_no = 0, 6
    g.begin_turn(emit=False)
    g.fx.turn_start_pos = {f.fid: f.pos for f in g.fighters.values() if f.alive}
    return g


def turn_plan(g: Game) -> list:
    """The two actions the bot plans, the second on the state it expects after the first."""
    ai = g.controllers[0]
    first = ai.plan(g)
    after = ai.apply_expected(g, first)
    return [first] + ([ai.plan(after)] if after.actions_left and after.winner is None else [])


def hero_strikes(g: Game, acts) -> bool:
    return any(a.kind == "attack" and a.fid == "sinbad" for a in acts)


def test_the_rebuilt_states_are_the_ones_of_the_log():
    """Hellboy is next to Sinbad on turns 6, 10 and 16, three spaces away on turn 8 and two on turn 12."""
    for name, steps in (("manor_t6", 1), ("manor_t8", 3), ("manor_t10", 1), ("manor_t12", 2), ("manor_t16", 1)):
        g = live(name)
        assert g.board.distance(g.fighters["sinbad"].pos, g.fighters["hellboy"].pos) == steps, name
    assert live("manor_t16").form(1) == "ANUNG UN RAMA" and live("manor_t10").form(1) == "OCCULT DETECTIVE"
    assert live("manor_t10").counter(0, "voyage") == 1


@pytest.mark.parametrize("name", ["manor_t6", "manor_t10", "manor_t16"])
def test_next_to_the_chaser_sinbad_strikes_first(name):
    """Live he walked away with both actions (turn 10: a hand of six attacks at 9 hit points). The blow comes first; the
    second action is free to step back. Turn 6 was already won back by F-SINBAD-AI-AFTER (the Apes' AFTER priced)."""
    g = live(name)
    first = g.controllers[0].plan(g)
    assert (first.kind, first.fid, first.target) == ("attack", "sinbad", "hellboy")


@pytest.mark.parametrize("name", ["manor_t10", "manor_t16"])
def test_without_the_blow_in_the_plan_he_walks_away_again(name, monkeypatch):
    """The mutation: with no attack added to the first actions the plan looks at, the live flight is back."""
    monkeypatch.setattr(ai_medusa, "BLOW_FIRSTS", 0)
    g = live(name)
    assert not hero_strikes(g, turn_plan(g))


@pytest.mark.parametrize("name", ["manor_t8", "manor_t12"])
def test_known_gap_away_from_the_chaser_he_still_only_maneuvers(name):
    """Not fixed, pinned so a change shows: with Hellboy two or three spaces away (turn 8; turn 12 at 7 hit points against 16
    with a Regroup as his only defense) both actions are still maneuvers, as they were live. When this fails because he
    attacks, the test goes and F-FLEE-CHASER's open list shrinks."""
    g = live(name)
    assert [a.kind for a in turn_plan(g)] == ["maneuver", "maneuver"]


def test_the_blow_to_open_with_is_not_always_the_best_ranked_attack(monkeypatch):
    """A state of a simulated game (Jill Trent at 9 hit points against the chasing Hellboy, King Solomon's Mine, saved with
    `persist`): outside the top acts the best ranked attack is Daisy's Ace Fighter on Lobster Johnson, the second Jill's
    Battle of Wits on Hellboy, and that second one is the turn's opening. With a single attack added she walks away."""
    def opening(extra):
        monkeypatch.setattr(ai_medusa, "BLOW_FIRSTS", extra)
        g = Game.new(Board.load("king-solomons-mine"), 0, {0: MedusaAI(0), 1: ChasingHellboy(1)}, bot_player=0,
                     heroes=("jill-trent", "hellboy"))
        persist.apply_game(g, json.loads((FIXTURES / "jill_second_best_blow.json").read_text(encoding="utf-8")))
        act = g.controllers[0].plan(g)
        return act.kind, act.fid, act.target
    assert opening(ai_medusa.BLOW_FIRSTS) == opening(2) == ("attack", "jill", "hellboy")
    assert opening(1)[0] == "maneuver"


def test_the_blow_does_not_cost_the_step_back():
    """Turn 10: after the attack the second action still leaves Hellboy's reach (hit, then move: the kiting is kept)."""
    g = live("manor_t10")
    first, second = turn_plan(g)
    assert first.kind == "attack" and second.kind == "maneuver"
    assert not g.board.can_reach_target(second.moves["sinbad"], g.fighters["hellboy"].pos, False, 0)


# ---------- the yardstick: a scripted rival that chases and defends like a person ----------
def chaser_game(pos: dict, hand: list[str], actions: int = 2) -> Game:
    g = Game.new(Board.load(MANOR), 3, {0: MedusaAI(0), 1: ChasingHellboy(1)}, bot_player=0, heroes=("sinbad", "hellboy"))
    st = g.players[1]
    st.deck = list(st.full_set)
    st.hand = [st.deck.pop(next(i for i, c in enumerate(st.deck) if c.title == t)) for t in hand]
    for fid, space in pos.items():
        g.fighters[fid].pos = space
    g.turn, g.turn_no = 1, 5
    g.begin_turn(emit=False)
    g.actions_left = actions
    return g


FAR = dict(sinbad=13, porter=14, hellboy=5, lobster=4)        # Hellboy (move 2) three steps from the nearest space next to Sinbad


def test_the_chaser_boosts_only_to_get_in_reach_with_its_cheapest_card():
    g = chaser_game(FAR, [EXCALIBUR, DOOM, HORSESHOES])
    ctl = g.controllers[1]
    assert not ctl.reaches(g, 0) and ctl.reaches(g, 1)
    assert ctl.reach_boost(g).title == HORSESHOES            # boost 1 is enough, and it is the lesser card of the two that have it
    near = chaser_game(dict(sinbad=3, porter=14, hellboy=5, lobster=6), [EXCALIBUR, DOOM, HORSESHOES])
    assert near.controllers[1].reaches(near, 0) and near.controllers[1].reach_boost(near) is None


def test_the_chaser_never_boosts_with_its_last_attack():
    alone = chaser_game(FAR, [DOOM])
    assert alone.controllers[1].reach_boost(alone) is None
    spare = chaser_game(FAR, [DOOM, EARTH])
    assert spare.controllers[1].reach_boost(spare).title == EARTH


def test_the_chaser_reaches_the_hero_that_stepped_out_of_its_plain_move():
    """One space beyond Hellboy's move: he boosts, walks next to Sinbad and strikes with his best card in the same turn. The
    random script walks towards the nearest piece and boosts on a coin flip."""
    g = chaser_game(FAR, [EXCALIBUR, DOOM, HORSESHOES])
    g.controllers[1].take_turn(g)
    assert g.fighters["hellboy"].pos in g.board.adj[13]
    assert [c.title for c in g.players[1].discard] == [HORSESHOES, EXCALIBUR]
    assert g.actions_left == 0


def test_the_chaser_walks_past_the_sidekick_to_the_hero():
    """The Porter stands next to Hellboy, Sinbad one move away: the random script hits the Porter (the nearest piece, already
    in reach); the chaser walks next to Sinbad and hits him."""
    spots = dict(sinbad=7, porter=4, hellboy=5, lobster=20)
    g = chaser_game(spots, [DOOM, TRAINING])
    g.controllers[1].take_turn(g)
    assert g.fighters["hellboy"].pos in g.board.adj[7]
    assert g.fighters["porter"].hp == 6 and len(g.players[1].discard) == 1 and g.actions_left == 0     # one maneuver, one blow at Sinbad
    script = chaser_game(spots, [DOOM, TRAINING])
    script.controllers[1] = ScriptedHellboy(1)
    script.controllers[1].take_turn(script)
    assert script.fighters["hellboy"].pos == 5 and script.fighters["sinbad"].hp == 15


def test_the_chaser_always_defends_its_hero_with_its_best_card():
    g = chaser_game(dict(sinbad=4, porter=0, hellboy=5, lobster=10), [GLIMPSE, CONFRONT, DOOM])
    ctl = g.controllers[1]
    for _ in range(20):
        assert ctl.choose_defense(g, g.fighters["sinbad"], g.fighters["hellboy"]).title == CONFRONT
    g.players[1].hand = [c for c in g.players[1].hand if c.title == DOOM]
    assert ctl.choose_defense(g, g.fighters["sinbad"], g.fighters["hellboy"]) is None


def test_the_chasers_shooter_keeps_its_distance():
    """Lobster Johnson already reaches Sinbad: he backs off to the farthest space that still does, where the random script
    walks him next to the rival."""
    g = chaser_game(dict(sinbad=7, porter=0, hellboy=12, lobster=9), [DOOM])
    lobster, board = g.fighters["lobster"], g.board
    assert g.can_attack(lobster, g.fighters["sinbad"])
    options = g.legal_moves(lobster, lobster.move) | {lobster.pos}
    spot = g.controllers[1].firing_spot(g, lobster, options)
    assert board.can_reach_target(spot, 7, True, 0)
    assert board.distance(spot, 7) == max(board.distance(d, 7) for d in options if board.can_reach_target(d, 7, True, 0))
    assert board.distance(ScriptedHellboy(1).closer(g, lobster, options - {lobster.pos}), 7) < board.distance(spot, 7)


def test_the_simulator_plays_against_either_rival():
    a = sim.play(1, MANOR, bot_hero="sinbad", human_hero="hellboy", rival="chaser")
    b = sim.play(1, MANOR, bot_hero="sinbad", human_hero="hellboy", rival="chaser")
    assert (a.winner, a.turns, a.medusa_hp) == (b.winner, b.turns, b.medusa_hp)      # no randomness of its own
    assert sim.play(1, MANOR, bot_hero="sinbad", human_hero="hellboy").winner in ("Sinbad", "Hellboy", "draw")
    assert sim.main(["--games", "1", "--bot-hero", "sinbad", "--map", MANOR, "--rival", "chaser"]) == 0
