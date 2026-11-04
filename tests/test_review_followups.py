"""Follow-ups of the review of secret passages / high ground / one-way edges: wording of one space away, which way
fleeing and placement walk, the rival's threat with high ground, and what `nearest_to` means."""
from __future__ import annotations

import pytest

from conftest import Scripted
from sparring import i18n
from sparring.ai_medusa import MedusaAI
from sparring.board import Board
from sparring.effects import select
from sparring.effects.choose import ChoiceRequest, SyntheticChooser
from sparring.search.adapter import EngineState, nearest, nearest_walk_from
from sparring.spaces import describe
from sparring.state import Game

from test_high_ground import duel


@pytest.fixture(scope="module")
def kaer():
    return Board.load("kaer-morhen")


def kaer_game(kaer, placed: dict[str, int]):
    g = Game.new(kaer, seed=3, controllers={0: MedusaAI(0), 1: Scripted()}, heroes=("medusa", "hellboy"))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    free = iter(s for s in sorted(kaer.spaces) if s not in (10, 11, 12, 13, 24) and s not in placed.values())
    for f in g.fighters.values():
        f.pos = placed[f.fid] if f.fid in placed else next(free)
    return g


# ---------- N1: "1 space from" ----------
@pytest.mark.parametrize("lang, text", [("en", "1 space from Hellboy"), ("es", "a 1 casilla de Hellboy")])
def test_a_passage_partner_one_step_away_is_not_plural(lang, text):
    board = Board.load("baskerville-manor")
    g = Game.new(board, seed=3, controllers={0: Scripted(), 1: Scripted()})
    free = iter(s for s in sorted(board.spaces) if board.span(0, s) >= 2)
    for f in g.fighters.values():
        f.pos = next(free)
    g.fighters["hellboy"].pos = 10
    assert not board.adjacent(0, 10) and board.span(0, 10) == 1
    i18n.set_language(lang)
    assert text in describe(g, 0)
    assert ("casillas" if lang == "es" else "spaces from") not in describe(g, 0)


# ---------- N3: the foe walks to the fleeing piece / the relocated piece walks to the hero ----------
def test_walking_distance_helpers_follow_who_walks(kaer):
    assert nearest(kaer, 12, (11,)) == kaer.distance(12, 11) == 4          # my own walk towards the foe
    assert nearest_walk_from(kaer, 12, (11,)) == kaer.distance(11, 12) == 1      # the foe walks 11 -> 12


def test_a_fleeing_piece_counts_the_foes_walk_not_its_own(kaer):
    g = kaer_game(kaer, {"medusa": 10, "hellboy": 11})
    req = ChoiceRequest("space", 0, [10, 12], extra={"fighter": "medusa"})
    # 12 is far from 11 only for someone walking 12 -> 11; Hellboy walks 11 -> 12 in one step
    assert SyntheticChooser(policy="safe").choose(g, req) == [10]


def test_a_relocated_rival_piece_is_sent_where_it_walks_furthest_to_the_hero(kaer):
    g = kaer_game(kaer, {"medusa": 11, "hellboy": 13})
    req = ChoiceRequest("space", 0, [10, 12], extra={"fighter": "hellboy"})
    # the piece walks s -> 11: from 12 the way back is closed (4 steps), from 10 it is one
    assert SyntheticChooser(policy="safe").choose(g, req) == [12]


# ---------- N4: high ground in the rival's threat ----------
def test_the_rivals_threat_counts_high_ground_over_my_hero():
    g, med, hb = duel({})
    flat = EngineState(g, 0).threat(0)
    g, med, hb = duel({(1, 0): 3})              # Hellboy on 1 hits Medusa on 0 from the high ground
    assert EngineState(g, 0).threat(0)[0] > flat[0]


def test_rescue_urgency_counts_the_rivals_high_ground():
    from sparring.ai_medusa import rescue_urgency
    g, med, hb = duel({})
    flat = rescue_urgency(g, 0)
    g, med, hb = duel({(1, 0): 3})
    assert rescue_urgency(g, 0) > flat


# ---------- N5: "nearest" is spatial ----------
def test_nearest_to_uses_the_span_not_the_walk(kaer, monkeypatch):
    g = kaer_game(kaer, {"medusa": 12, "hellboy": 0})
    monkeypatch.setattr(select, "_ref_fighter", lambda game, run, ref: g.fighters["medusa"])
    got = select.space_options(g, None, {"nearest_to": "x"})
    assert got == [11, 13, 24]                  # 12 -> 11 is closed to walkers, but it is as near as the others
