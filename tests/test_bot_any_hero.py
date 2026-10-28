"""F08 fase F-B: el bot juega cualquier heroe de la caja Hellboy (y Medusa) sin romperse, con heuristica e ISMCTS."""
from __future__ import annotations

import itertools

import pytest

from sparring import sim

SLUGS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]
PAIRS = list(itertools.permutations(SLUGS, 2))
SEEDS = range(5)


@pytest.mark.parametrize("bot,human", PAIRS)
def test_heuristic_bot_matrix(bot, human):
    for seed in SEEDS:
        out = sim.play(seed, bot_hero=bot, human_hero=human)
        assert out.turns >= 1


@pytest.mark.parametrize("bot,human", PAIRS)
def test_ismcts_bot_matrix(bot, human):
    for seed in SEEDS:
        ai = sim.make_bot("ismcts", iterations=6, seed=seed)
        out = sim.play(seed, bot_hero=bot, human_hero=human, medusa=ai, max_turns=30)
        assert out.turns >= 1 and ai.fallbacks == 0      # la busqueda no cayo a la heuristica por un fallo


def test_a_sidekick_that_starts_in_reserve_is_off_the_board_and_not_placed_by_the_bot(monkeypatch):
    import json
    from sparring import heroes
    from sparring.ai_medusa import MedusaAI
    from sparring.board import Board
    from sparring.state import Game

    raw = json.loads((heroes.HEROES_DIR / "abe-sapien.json").read_text(encoding="utf-8"))
    raw["sidekicks"][0]["start_on_board"] = 2
    custom = heroes.parse_hero(raw)
    real = heroes.load_hero
    monkeypatch.setattr("sparring.state.load_hero", lambda slug: custom if slug == "abe-sapien" else real(slug))
    game = Game.new(Board.load("bprd-hq"), 1, bot_player=0, heroes=("abe-sapien", "hellboy"))
    assert [(f.fid, f.alive) for f in game.own(0, alive_only=False)] == [
        ("abe", True), ("agent1", True), ("agent2", True), ("agent3", False)]
    plan = MedusaAI(0).choose_setup(game, game.players[0].hand)
    assert set(plan) == {"abe", "agent1", "agent2"}


def _bot_attacks_with_abe(bprd, human):
    from conftest import Scripted
    from sparring.state import Game
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()}, bot_player=0, heroes=("abe-sapien", human))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for pl in g.players:
        pl.hand.clear()
    abe, foe = g.hero(0), g.hero(1)
    spaces = sorted(g.board.spaces)
    abe.pos, foe.pos = spaces[0], spaces[1]
    card = next(c for c in g.players[0].full_set if c.title == "Advanced Psychometry")
    g.players[0].hand.append(card)
    return g, abe, foe, card


def test_an_after_combat_of_a_non_medusa_bot_is_announced_as_ignored_and_never_left_to_the_human(bprd):
    from sparring.combat import after_text, resolve_combat
    g, abe, foe, card = _bot_attacks_with_abe(bprd, "hellboy")
    res = resolve_combat(g, abe, foe, card, None)
    assert res.human_effects == []
    assert res.bot_ignored == [f"{card.title}: el bot ignora este efecto: {after_text(card)}"]
    assert res.atk_value == card.value                       # se juega por valor


def test_the_humans_own_after_combat_still_goes_to_the_human(bprd):
    from sparring.combat import resolve_combat
    g, abe, foe, _ = _bot_attacks_with_abe(bprd, "hellboy")
    right_hand = next(c for c in g.players[1].full_set if c.title == "Right Hand Of Doom")
    g.players[1].hand.append(right_hand)
    res = resolve_combat(g, foe, abe, right_hand, None)
    assert [e.split(":")[0] for e in res.human_effects] == ["Right Hand Of Doom"] and res.bot_ignored == []
