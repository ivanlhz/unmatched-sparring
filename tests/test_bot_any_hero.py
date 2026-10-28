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
    assert res.bot_notes == [f"{card.title}: el bot ignora este efecto (AFTER COMBAT): {after_text(card)}"]
    assert res.atk_value == card.value                       # se juega por valor


def test_the_humans_own_after_combat_still_goes_to_the_human(bprd):
    from sparring.combat import resolve_combat
    g, abe, foe, _ = _bot_attacks_with_abe(bprd, "hellboy")
    right_hand = next(c for c in g.players[1].full_set if c.title == "Right Hand Of Doom")
    g.players[1].hand.append(right_hand)
    res = resolve_combat(g, foe, abe, right_hand, None)
    assert [e.split(":")[0] for e in res.human_effects] == ["Right Hand Of Doom"] and res.bot_notes == []


def _box_cards():
    from sparring.combat import text_parts
    from sparring.heroes import load_hero
    out = []
    for slug in ("hellboy", "abe-sapien", "baba-yaga", "liz-sherman"):
        seen = set()
        for c in load_hero(slug).deck():
            if c.title not in seen and not c.is_scheme:
                seen.add(c.title)
                out.append((slug, c.title))
    return out


@pytest.mark.parametrize("slug,title", _box_cards())
def test_every_uncoded_moment_of_a_bot_card_is_announced_and_never_left_to_the_human(bprd, slug, title):
    from conftest import Scripted
    from sparring.combat import CODED_MOMENTS, text_parts, resolve_combat
    from sparring.state import Game
    human = "medusa"
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()}, bot_player=0, heroes=(slug, human))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for pl in g.players:
        pl.hand.clear()
    me, foe = g.hero(0), g.hero(1)
    spaces = sorted(g.board.spaces)
    me.pos, foe.pos = spaces[0], spaces[1]
    card = next(c for c in g.players[0].full_set if c.title == title)
    g.players[0].hand.append(card)
    res = resolve_combat(g, me, foe, card, None)
    assert res.human_effects == []
    said = res.bot_notes + res.applied
    for moment, text in text_parts(card):
        if moment in CODED_MOMENTS.get(title, set()):
            assert not any(text in n for n in res.bot_notes), (title, moment)
        else:
            assert any(text in n and (moment in n) for n in res.bot_notes), (title, moment, said)
    assert not any("Resuelve a mano" in n for n in said)


def test_a_rival_option_is_announced_as_the_humans_option_not_as_ignored(bprd):
    from conftest import Scripted
    from sparring.combat import resolve_combat
    from sparring.state import Game
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()}, bot_player=0, heroes=("liz-sherman", "hellboy"))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    me, foe = g.hero(0), g.hero(1)
    spaces = sorted(g.board.spaces)
    me.pos, foe.pos = spaces[0], spaces[1]
    card = next(c for c in g.players[0].full_set if c.title == "Incinerate")
    g.players[0].hand.append(card)
    res = resolve_combat(g, me, foe, card, None)
    option = [n for n in res.bot_notes if "Your opponent may" in n]
    assert len(option) == 1 and "tu opcion" in option[0] and "ignora" not in option[0]
