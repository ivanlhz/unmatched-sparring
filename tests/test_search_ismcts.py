"""ISMCTS sobre juegos de juguete: el buscador no sabe nada de Unmatched, solo del Protocol."""
import random

import pytest

from sparring.search.ismcts import ISMCTS, SearchConfig
from sparring.search.protocol import SearchState


class PickBest:
    """Un jugador, una jugada: elegir el numero mas alto. Sirve para la mecanica basica."""

    def __init__(self, options=(0, 1, 2), chosen=None):
        self.options = tuple(options)
        self.chosen = chosen

    def clone(self):
        return PickBest(self.options, self.chosen)

    def player_to_move(self):
        return 0

    def turn_owner(self):
        return 0

    def legal_moves(self):
        return list(self.options)

    def apply(self, move):
        self.chosen = move

    def is_terminal(self):
        return self.chosen is not None

    def winner(self):
        return None

    def evaluate(self, player):
        return self.chosen / max(self.options)

    def observe(self, move, viewer):
        return move

    def rollout_move(self, rng):
        return rng.choice(self.legal_moves())

    def determinize(self, observer, rng):
        pass


class HiddenDuel:
    """Dos jugadores: el 0 ataca con una carta que el 1 no ve (A o B); el 1 defiende alto o bajo.
    Pagos para el 0: (A,alto)=0 (A,bajo)=1 (B,alto)=1 (B,bajo)=0. Sin informacion el 1 no puede contrarrestar."""

    PAYOFF = {("A", "alto"): 0.0, ("A", "bajo"): 1.0, ("B", "alto"): 1.0, ("B", "bajo"): 0.0}

    def __init__(self):
        self.atk = None
        self.dfn = None

    def clone(self):
        c = HiddenDuel()
        c.atk, c.dfn = self.atk, self.dfn
        return c

    def player_to_move(self):
        return 0 if self.atk is None else 1

    def turn_owner(self):
        return self.player_to_move()

    def legal_moves(self):
        return ["A", "B"] if self.atk is None else ["alto", "bajo"]

    def apply(self, move):
        if self.atk is None:
            self.atk = move
        else:
            self.dfn = move

    def is_terminal(self):
        return self.dfn is not None

    def winner(self):
        return None

    def evaluate(self, player):
        v = self.PAYOFF[(self.atk, self.dfn)]
        return v if player == 0 else 1 - v

    def observe(self, move, viewer):
        if move in ("A", "B") and viewer != 0:
            return "?"
        return move

    def rollout_move(self, rng):
        return rng.choice(self.legal_moves())

    def determinize(self, observer, rng):
        pass


def test_picks_the_best_move_with_iteration_budget():
    move, report = ISMCTS(SearchConfig(iterations=200, seed=1)).search(PickBest(), root_player=0)
    assert move == 2
    assert report.iterations == 200
    assert sum(report.visits.values()) == 200


def test_same_seed_same_result_and_report():
    a = ISMCTS(SearchConfig(iterations=100, seed=7)).search(PickBest(options=(0, 5, 3, 4)), root_player=0)
    b = ISMCTS(SearchConfig(iterations=100, seed=7)).search(PickBest(options=(0, 5, 3, 4)), root_player=0)
    assert a[0] == b[0] == 5
    assert (a[1].visits, a[1].values) == (b[1].visits, b[1].values)


def test_time_budget_stops_the_search():
    cfg = SearchConfig(iterations=None, time_budget=0.05, seed=0)
    move, report = ISMCTS(cfg).search(PickBest(), root_player=0)
    assert move == 2
    assert report.elapsed < 0.5 and report.iterations >= 1


def test_single_legal_move_returns_it_without_searching():
    move, report = ISMCTS(SearchConfig(iterations=50, seed=0)).search(PickBest(options=(4,)), root_player=0)
    assert move == 4 and report.iterations == 0


def test_no_legal_move_is_an_error():
    with pytest.raises(ValueError):
        ISMCTS(SearchConfig(iterations=5)).search(PickBest(options=()), root_player=0)


def test_multiple_observer_trees_hide_the_attack_card_from_the_defender():
    s = ISMCTS(SearchConfig(iterations=300, seed=3))
    s.search(HiddenDuel(), root_player=0)
    attacker_tree, defender_tree = s.trees[0], s.trees[1]
    assert set(attacker_tree.edges) == {"A", "B"}, "el atacante distingue sus dos cartas"
    assert set(defender_tree.edges) == {"?"}, "el defensor solo ve 'una carta boca abajo'"
    hidden = defender_tree.edges["?"].node
    assert set(hidden.edges) == {"alto", "bajo"}
    # las estadisticas del defensor se reparten entre las dos cartas: no puede contrarrestar ninguna
    assert all(e.visits > 50 for e in attacker_tree.edges.values())


def test_principal_variation_starts_at_the_returned_move():
    s = ISMCTS(SearchConfig(iterations=200, seed=3))
    move, _ = s.search(HiddenDuel(), root_player=0)
    pv = s.principal_variation(0, start=move)
    assert pv[0] == move and pv[1] in ("alto", "bajo")
    other = "A" if move == "B" else "B"
    assert s.principal_variation(0, start=other)[0] == other
    assert s.principal_variation(0, start="no existe") == []


def test_rewards_are_from_the_movers_perspective():
    """Con el defensor ciego, al atacante le sale ~0.5 en las dos cartas; el valor medio de las aristas lo refleja."""
    s = ISMCTS(SearchConfig(iterations=400, seed=5))
    s.search(HiddenDuel(), root_player=0)
    for e in s.trees[0].edges.values():
        assert 0.2 < e.reward / e.visits < 0.8
