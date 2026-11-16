"""Regression positions taken from live games: rebuilt with `persist.apply_game` from a short description
(tests/fixtures/ai_positions.json) and handed to whichever AI is under test.

A position names the hands by card title (the real decks are not in the log, so the rest of each full set forms the deck),
the spaces and hit points that matter, whose turn it is, and `good_player`: what a good player does there and why."""
from __future__ import annotations

import json
from pathlib import Path

from sparring import persist
from sparring.board import Board
from sparring.search.controller import make_bot_ai
from sparring.state import Game

POSITIONS = json.loads((Path(__file__).parent / "fixtures" / "ai_positions.json").read_text(encoding="utf-8"))
ISMCTS_ITERATIONS = 300


def make_ai(kind: str):
    return make_bot_ai({"ai": kind, "ai_iterations": ISMCTS_ITERATIONS, "ai_seed": 0}, 0)


def _ids(player, titles: list[str], taken: set[int]) -> list[int]:
    out = []
    for title in titles:
        card = next(c for c in player.full_set if c.title == title and c.card_id not in taken)
        taken.add(card.card_id)
        out.append(card.card_id)
    return out


def build(name: str, ai) -> Game:
    """The position `name` with the bot (player 0) driven by `ai`; the other seat is a plain heuristic controller."""
    spec = POSITIONS[name]
    game = Game.new(Board.load(spec["board"]), spec["seed"], {0: ai, 1: make_ai("heuristic")}, bot_player=0, heroes=tuple(spec["heroes"]))
    state = persist.game_to_dict(game)
    state.update(turn=spec["turn"], turn_no=spec["turn_no"], actions_left=spec["actions_left"], winner=None)
    for fid, change in spec.get("fighters", {}).items():
        state["fighters"][fid].update(change)
    for p, saved in enumerate(state["players"]):
        taken: set[int] = set()
        player = game.players[p]
        saved["hand"] = _ids(player, spec["hands"][str(p)], taken) if str(p) in spec.get("hands", {}) else saved["hand"]
        taken.update(saved["hand"])
        saved["discard"] = _ids(player, spec.get("discard", {}).get(str(p), []), taken)
        in_play = set(saved["hand"]) | set(saved["discard"])
        saved["deck"] = [c.card_id for c in player.full_set if c.card_id not in in_play]
    persist.apply_game(game, state)
    return game
