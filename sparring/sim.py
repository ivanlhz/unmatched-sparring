"""Terminal simulation: the bot (AI, Medusa by default) against a scripted rival (Hellboy by default).

    python -m sparring.sim --games 100 --seed 0
    python -m sparring.sim --games 20 --bot-hero abe-sapien --human-hero baba-yaga --ai ismcts
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from dataclasses import dataclass

from .ai_medusa import MedusaAI
from .board import Board
from .hellboy_script import ScriptedHellboy
from .heroes import load_hero
from .state import Game

MEDUSA, HELLBOY = 0, 1
MAX_TURNS = 200


@dataclass
class Outcome:
    seed: int
    winner: str
    turns: int
    medusa_hp: float
    hellboy_hp: float


def play(seed: int, board_key: str = "bprd-hq", verbose: bool = False, max_turns: int = MAX_TURNS,
         medusa: MedusaAI | None = None, trace: list[str] | None = None,
         bot_hero: str = "medusa", human_hero: str = "hellboy") -> Outcome:
    """`trace`: if given, it receives one line per turn with the engine log (what `-v` prints).
    `bot_hero`/`human_hero`: slugs in data/heroes; `medusa` is the bot's controller (any, not only Medusa).
    In the result, `medusa_hp`/`hellboy_hp` are the HP of the bot's and the human's hero (names kept from the goldens)."""
    controllers = {MEDUSA: medusa or MedusaAI(MEDUSA), HELLBOY: ScriptedHellboy(HELLBOY, seed)}
    game = Game.new(Board.load(board_key), seed, controllers, bot_player=MEDUSA, heroes=(bot_hero, human_hero))
    while game.winner is None and game.turn_no <= max_turns:
        game.begin_turn()
        controllers[game.turn].take_turn(game)
        line = f"T{game.turn_no} P{game.turn}: " + "; ".join(game.log)
        if verbose:
            print(line)
        if trace is not None:
            trace.append(line)
        game.log.clear()
        if game.winner is None:
            game.end_turn()
    winner = "draw" if game.winner is None else game.hero(game.winner).name
    return Outcome(seed, winner, game.turn_no, game.hero(MEDUSA).hp, game.hero(HELLBOY).hp)


def make_bot(kind: str = "heuristic", iterations: int = 30, seed: int = 0) -> MedusaAI | None:
    """The bot controller: None (the default heuristic of `play`) or ISMCTS with a small budget."""
    if kind == "heuristic":
        return None
    from .search.controller import IsmctsMedusa
    from .search.ismcts import SearchConfig
    return IsmctsMedusa(MEDUSA, SearchConfig(time_budget=60.0, iterations=iterations, seed=seed))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sparring.sim")
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0, help="seed of the first game; the others add 1")
    ap.add_argument("--map", default="bprd-hq")
    ap.add_argument("--bot-hero", default="medusa")
    ap.add_argument("--human-hero", default="hellboy")
    ap.add_argument("--ai", choices=("heuristic", "ismcts"), default="heuristic")
    ap.add_argument("--iterations", type=int, default=30, help="ISMCTS iterations per decision")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    t0, outcomes, errors = time.time(), [], []
    for seed in range(args.seed, args.seed + args.games):
        try:
            outcomes.append(play(seed, args.map, args.verbose, bot_hero=args.bot_hero, human_hero=args.human_hero,
                                 medusa=make_bot(args.ai, args.iterations, seed)))
        except Exception:
            errors.append((seed, traceback.format_exc()))
    bot_name, human_name = load_hero(args.bot_hero).name, load_hero(args.human_hero).name
    wins = {k: sum(o.winner == k for o in outcomes) for k in (bot_name, human_name, "draw")}
    avg_turns = sum(o.turns for o in outcomes) / max(1, len(outcomes))
    print(f"{bot_name}(bot) vs {human_name}: games={len(outcomes)} errors={len(errors)} "
          f"{bot_name}={wins[bot_name]} {human_name}={wins[human_name]} "
          f"unfinished={wins['draw']} avg_turns={avg_turns:.1f} time={time.time() - t0:.0f}s")
    for seed, tb in errors[:3]:
        print(f"--- seed {seed}\n{tb}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
