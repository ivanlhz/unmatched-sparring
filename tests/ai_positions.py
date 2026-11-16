"""Regression positions taken from live games: rebuilt with `persist.apply_game` from a short description
(tests/fixtures/ai_positions.json) and handed to whichever AI is under test.

A position names the hands by card title (the real decks are not in the log, so the rest of each full set forms the deck),
the spaces and hit points that matter, whose turn it is, and `good_player`: what a good player does there and why."""
from __future__ import annotations

import json
import random
from pathlib import Path

from sparring import persist
from sparring.board import Board
from sparring.search.controller import make_bot_ai
from sparring.state import Game

POSITIONS = json.loads((Path(__file__).parent / "fixtures" / "ai_positions.json").read_text(encoding="utf-8"))
ISMCTS_ITERATIONS = 300


def make_ai(kind: str, me: int = 0):
    return make_bot_ai({"ai": kind, "ai_iterations": ISMCTS_ITERATIONS, "ai_seed": 0}, me)


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
    game = Game.new(Board.load(spec["board"]), spec["seed"], {0: ai, 1: make_ai("heuristic", 1)}, bot_player=0, heroes=tuple(spec["heroes"]))
    state = persist.game_to_dict(game)
    state.update(turn=spec["turn"], turn_no=spec["turn_no"], actions_left=spec["actions_left"], winner=None)
    for fid, change in spec.get("fighters", {}).items():
        state["fighters"][fid].update(change)
    rng = random.Random(spec["seed"])
    for p, saved in enumerate(state["players"]):
        taken: set[int] = set()
        player = game.players[p]
        if str(p) in spec.get("hands", {}):
            saved["hand"] = _ids(player, spec["hands"][str(p)], taken)
            fill = spec.get("hand_sizes", {}).get(str(p), len(saved["hand"])) - len(saved["hand"])
        else:
            fill = spec.get("hand_sizes", {}).get(str(p), len(saved["hand"])) - len(saved["hand"])
        taken.update(saved["hand"])
        saved["discard"] = _ids(player, spec.get("discard", {}).get(str(p), []), taken)
        if fill > 0:       # the cards the bot does not see: drawn from the pool that is neither in the hand nor in a public pile
            hidden = [c.card_id for c in player.full_set if c.card_id not in taken]
            saved["hand"] += rng.sample(hidden, fill)
        in_play = set(saved["hand"]) | set(saved["discard"])
        rest = [c for c in player.full_set if c.card_id not in in_play]
        top = _ids(player, spec.get("deck_top", {}).get(str(p), []), set(in_play))
        saved["deck"] = top + [c.card_id for c in rest if c.card_id not in top]
    persist.apply_game(game, state)
    for p, titles in spec.get("known_in_hand", {}).items():       # what the bot (player p) saw of the rival's hand
        rival = game.players[1 - int(p)]
        for title in titles:
            game.players[int(p)].known.add(next(c for c in rival.hand if c.title == title), game.turn_no)
    return game
