"""F-STRANGE-WONG-ADJ: the bot's Doctor Strange keeps Wong next to him, where Master of Kamar-Taj is worth 4 and The Rings of
Raggadorr / No, Really, I'm a Doctor heal Wong too."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import MedusaAI, Model, beside_stake
from sparring.board import Board
from sparring.hellboy_script import ScriptedHellboy
from sparring.state import Game

MANOR = "baskerville-manor"
MASTER, RINGS, REALLY = "Master of Kamar-Taj", "The Rings of Raggadorr", "No, Really, I'm a Doctor"


def table(hand: list[str], strange: int, wong: int, hellboy: int) -> Game:
    g = Game.new(Board.load(MANOR), 3, {0: MedusaAI(0), 1: ScriptedHellboy(1)}, bot_player=0, heroes=("doctor-strange", "hellboy"))
    st = g.players[0]
    st.deck = list(st.full_set)
    st.hand = [st.deck.pop(next(i for i, c in enumerate(st.deck) if c.title == t)) for t in hand]
    for fid, space in dict(strange=strange, wong=wong, hellboy=hellboy).items():
        g.fighters[fid].pos = space
    g.turn, g.turn_no = 0, 4
    g.begin_turn(emit=False)
    return g


def setup(hand):
    """Wong three spaces from Strange (he can close to one in his move), Hellboy as far from both as the board allows."""
    g = table(hand, 3, 3, 3)
    strange = 3
    far = max(g.board.spaces, key=lambda s: g.board.distance(s, strange))
    wong = next(s for s in g.board.spaces if g.board.distance(s, strange) == 3 and g.board.distance(s, far) > 3)
    return table(hand, strange, wong, far)


def adjacent(g: Game, moves: dict) -> bool:
    return moves["wong"] in g.board.adj[moves["strange"]]


@pytest.mark.parametrize("hand", [[MASTER, MASTER, RINGS, REALLY, "Eye of Agamotto"], [RINGS, "Eye of Agamotto", "Bolts of Balthakk", "Cloak of Levitation", "The Winds of Watoomb"],
    ["Eye of Agamotto", "Bolts of Balthakk", "Cloak of Levitation", "The Winds of Watoomb", "Seven Suns of Cinnibus"]])
def test_wong_walks_to_a_space_next_to_strange(hand):
    g = setup(hand)
    wong, strange = g.fighters["wong"], g.fighters["strange"]
    dest = g.controllers[0].choose_move(g, wong, wong.move)
    assert dest in g.board.adj[strange.pos], (wong.pos, strange.pos, dest)


def test_the_maneuver_ends_with_wong_next_to_strange():
    g = setup([MASTER, MASTER, RINGS, REALLY, "Eye of Agamotto"])
    act = g.controllers[0].plan(g)
    assert act.kind == "maneuver" and adjacent(g, act.moves), act.moves


def test_wong_that_can_shoot_does_not_give_the_shot_up_to_stand_beside_strange():
    """Strange 10 / Wong 28 / Hellboy 25 (live-checked board): the bot attacks with Rings instead of maneuvering twice."""
    g = table([MASTER, MASTER, RINGS, REALLY, "Steadfast Disciple"], 10, 28, 25)
    act = g.controllers[0].plan(g)
    assert act.kind == "attack", (act.kind, act.fid, act.moves)


def test_a_sidekick_move_keeps_a_strike_over_the_space_beside_strange():
    g = table([MASTER, MASTER, RINGS, REALLY, "Steadfast Disciple"], 10, 28, 25)
    wong, hellboy = g.fighters["wong"], g.fighters["hellboy"]
    dest = g.controllers[0].choose_move(g, wong, wong.move)
    assert g.board.can_reach_target(dest, hellboy.pos, wong.ranged, wong.reach)


@pytest.mark.parametrize("board", ["marmoreal", "fayrlund-forest", "pandemonium"])
def test_setup_places_wong_beside_strange(board, monkeypatch):
    """On these boards the stake decides: without it Wong is set up away from Strange."""
    def setup_on(stake_off: bool) -> dict:
        g = Game.new(Board.load(board), 3, {0: MedusaAI(0), 1: ScriptedHellboy(1)}, bot_player=0, heroes=("doctor-strange", "hellboy"))
        ai = g.controllers[0]
        if stake_off:
            monkeypatch.setattr(MedusaAI, "beside_hero_stake", lambda self, game: 0.0)
        plan = ai.choose_setup(g, g.players[0].hand)
        monkeypatch.undo()
        return plan, g
    (plan, g), (plain, _) = setup_on(False), setup_on(True)
    assert plan["wong"] in g.board.adj[plan["strange"]], plan
    assert plain["wong"] not in g.board.adj[plain["strange"]], "the stake must be what decides here"


def test_the_stake_is_zero_for_a_hero_without_those_cards():
    g = Game.new(Board.load(MANOR), 3, {0: MedusaAI(0), 1: ScriptedHellboy(1)}, bot_player=0, heroes=("sinbad", "hellboy"))
    assert beside_stake(g, 0) == 0.0 and g.controllers[0].beside_hero_stake(g) == 0.0


def test_strange_does_not_step_toward_hellboy_because_of_wong():
    """Strange 26 / Wong 25 / Hellboy 29: staying with Wong never takes him next to Hellboy."""
    g = table([MASTER, MASTER, RINGS, REALLY, "Eye of Agamotto"], 26, 25, 29)
    ai, strange = g.controllers[0], g.fighters["strange"]
    dest = ai.best_dest(g, Model(g, 0), strange, strange.move, False)
    before = ai.beside_hero_stake
    ai.beside_hero_stake = lambda game: 0.0
    try:
        without = ai.best_dest(g, Model(g, 0), strange, strange.move, False)
    finally:
        ai.beside_hero_stake = before
    assert g.board.distance(dest, 29) >= g.board.distance(without, 29)


# ---------- the search AI (what the live bot runs): ISMCTS ----------
HAND = [MASTER, MASTER, RINGS, REALLY, "Steadfast Disciple"]


def search_plan(strange: int, wong: int, hellboy: int, seed: int):
    from conftest import give
    from sparring.search.controller import make_bot_ai
    ai = make_bot_ai({"ai": "ismcts", "ai_time_budget": 60, "ai_iterations": 300, "ai_seed": seed}, 0)
    g = Game.new(Board.load(MANOR), seed, controllers={0: ai}, heroes=("doctor-strange", "hellboy"), bot_player=0)
    g.turn, g.turn_no = 0, 3
    g.begin_turn()
    st = g.players[0]
    st.deck.extend(st.hand)
    st.hand.clear()
    for i, title in enumerate(HAND):
        give(g, 0, title, nth=HAND[:i].count(title))      # a second copy is another card, never the same object twice
    assert len({id(c) for c in st.hand}) == len(st.hand)
    g.fighters["strange"].pos, g.fighters["wong"].pos, g.hero(1).pos = strange, wong, hellboy
    g.actions_left = 2
    act = ai.plan(g)
    assert ai.fallbacks == 0, "the search fell back to the heuristic AI: the test would not be measuring it"
    return g, act


@pytest.mark.xfail(reason="EvalWeights.beside is 0: any weight that closes Wong up under ISMCTS cost the bot attacks "
                          "(24 attack turns: 39 attacks at 0, 27 at 0.15, 24 at 0.3); pending a tuning that keeps both", strict=False)
def test_ismcts_maneuver_ends_with_wong_beside_strange_in_the_clear_majority():
    """Wong three spaces off, no attack to make, rival far: the live bot's maneuver (before: about 1 in 12) closes up."""
    cases = [(14, 18, 1), (5, 7, 16), (19, 30, 6), (12, 15, 2)]
    plans = [search_plan(*c, seed=n) for n, c in enumerate(cases)]
    maneuvers = [(g, a) for g, a in plans if a.kind == "maneuver"]
    beside = [a for g, a in maneuvers if adjacent(g, a.moves)]
    assert len(maneuvers) >= 3 and len(beside) / len(maneuvers) >= 0.75, [a.moves for _, a in maneuvers]


def test_ismcts_still_attacks_when_it_can():
    for n, case in enumerate([(2, 4, 17), (2, 6, 14)]):
        _, act = search_plan(*case, seed=n)
        assert act.kind == "attack", (case, act.kind, act.moves)
