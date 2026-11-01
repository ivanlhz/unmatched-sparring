"""F08 phase F-B: the bot plays any hero of the Hellboy box (and Medusa) without breaking, with heuristic and ISMCTS."""
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
        assert out.turns >= 1 and ai.fallbacks == 0      # the search did not fall back to the heuristic because of a failure


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


def test_an_after_combat_of_a_box_bot_is_applied_by_the_interpreter_and_never_left_to_the_human(bprd):
    """D1: Abe's Advanced Psychometry (adjacent rival: look at their hand) is resolved and said in `applied`."""
    from sparring.combat import resolve_combat
    g, abe, foe, card = _bot_attacks_with_abe(bprd, "hellboy")
    g.players[1].hand.extend(g.players[1].deck[:2])
    res = resolve_combat(g, abe, foe, card, None)
    assert res.human_effects == [] and res.bot_notes == []
    assert res.applied == [f"{card.title}: mira tu mano"]
    assert [c.card_id for c in g.players[0].known.cards(g.players[1])] == [c.card_id for c in g.players[1].hand]
    assert res.atk_value == card.value


def test_the_humans_own_after_combat_still_goes_to_the_human(bprd):
    from sparring.combat import resolve_combat
    g, abe, foe, _ = _bot_attacks_with_abe(bprd, "hellboy")
    right_hand = next(c for c in g.players[1].full_set if c.title == "Right Hand Of Doom")
    g.players[1].hand.append(right_hand)
    res = resolve_combat(g, foe, abe, right_hand, None)
    assert [e.split(":")[0] for e in res.human_effects] == ["Right Hand Of Doom"] and res.bot_notes == []


def test_a_box_bot_card_with_a_moment_the_interpreter_cannot_apply_now_says_no_effect_not_ignored(bprd):
    """D1: nothing of a bot card is ever "ignored" or left to the human; a moment with nothing to do says so."""
    from conftest import Scripted
    from sparring.combat import resolve_combat
    from sparring.state import Game
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()}, bot_player=0, heroes=("baba-yaga", "medusa"))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for pl in g.players:
        pl.hand.clear()
    me, foe = g.hero(0), g.hero(1)
    spaces = sorted(g.board.spaces)
    me.pos, foe.pos = spaces[0], spaces[-1]
    g.fighters["koschei"].pos = spaces[-2]
    card = next(c for c in g.players[0].full_set if c.title == "Iron Teeth")      # nobody adjacent, no ONGOING
    g.players[0].hand.append(card)
    res = resolve_combat(g, me, foe, card, None)
    assert res.human_effects == [] and res.bot_notes == []
    assert res.applied == ["Iron Teeth: sin efecto"]


def test_the_bots_hero_switched_off_in_a_save_is_said_so_and_never_left_to_the_human(bprd):
    from conftest import Scripted
    from sparring.combat import resolve_combat
    from sparring.state import Game
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()}, bot_player=0, heroes=("liz-sherman", "hellboy"))
    g.fx.dsl_heroes = set()
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    me, foe = g.hero(0), g.hero(1)
    spaces = sorted(g.board.spaces)
    me.pos, foe.pos = spaces[0], spaces[1]
    card = next(c for c in g.players[0].full_set if c.title == "Incinerate")
    g.players[0].hand.append(card)
    res = resolve_combat(g, me, foe, card, None)
    assert res.human_effects == [] and res.applied == []
    assert res.bot_notes == [f"Incinerate: el bot no resuelve este efecto (interprete apagado): {card.text}"]
