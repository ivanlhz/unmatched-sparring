"""Simulacion en terminal: Medusa (IA) contra un Hellboy guionizado.

    python -m sparring.sim --games 100 --seed 0
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
         medusa: MedusaAI | None = None, trace: list[str] | None = None) -> Outcome:
    """`trace`: si se da, recibe una linea por turno con el registro del motor (lo que imprime `-v`)."""
    controllers = {MEDUSA: medusa or MedusaAI(MEDUSA), HELLBOY: ScriptedHellboy(HELLBOY, seed)}
    game = Game.new(Board.load(board_key), seed, controllers, medusa_player=MEDUSA)
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
    winner = {None: "draw", MEDUSA: "Medusa", HELLBOY: "Hellboy"}[game.winner]
    return Outcome(seed, winner, game.turn_no, game.hero(MEDUSA).hp, game.hero(HELLBOY).hp)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sparring.sim")
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0, help="semilla de la primera partida; las demas suman 1")
    ap.add_argument("--map", default="bprd-hq")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    t0, outcomes, errors = time.time(), [], []
    for seed in range(args.seed, args.seed + args.games):
        try:
            outcomes.append(play(seed, args.map, args.verbose))
        except Exception:
            errors.append((seed, traceback.format_exc()))
    wins = {k: sum(o.winner == k for o in outcomes) for k in ("Medusa", "Hellboy", "draw")}
    avg_turns = sum(o.turns for o in outcomes) / max(1, len(outcomes))
    print(f"partidas={len(outcomes)} errores={len(errors)} Medusa={wins['Medusa']} Hellboy={wins['Hellboy']} "
          f"sin_final={wins['draw']} turnos_medios={avg_turns:.1f} tiempo={time.time() - t0:.0f}s")
    for seed, tb in errors[:3]:
        print(f"--- seed {seed}\n{tb}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
