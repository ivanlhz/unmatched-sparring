"""Bot against bot: how much stronger is AI configuration A than B? Same seeds, swapped seats, several processes.

    python tools/ai_duel.py --a ismcts:iterations=200 --b heuristic --matchup raptors:liz-sherman --games 100 --jobs 6
    python tools/ai_duel.py --a ismcts:time=3 --b ismcts:time=3,eval=old --matchup liz-sherman:raptors hellboy:liz-sherman \
        --games 50 --sequential --out new.json
    python tools/ai_duel.py --compare master.json branch.json

A configuration is `heuristic` or `ismcts[:key=value,...]` with `iterations` (per decision; default 200, which makes the
games reproducible), `time` (seconds per decision; then the iterations only cap it), `seed` (default: the game seed) and `eval`
(`old`, the evaluation as the table has it, or `new`, the one of F-AI-EVAL-RESOLUTION: the weights of `search.adapter.RESOLUTION`;
default `old`). Any weight can be set on top with `w.NAME=value` (`ismcts:eval=new,w.fighter_threat=0` leaves a term out).
Both sides are the same engine controller type the table uses (`MedusaAI`, `IsmctsMedusa`), so what is measured is what runs.

`--matchup H0:H1` puts hero H0 on player 0 and H1 on player 1. Each seed is played twice: A drives player 0 and B player 1,
then the other way round, from the same shuffles and the same first player, so the only thing that differs between the two
games is who drives which hero. The result is A's score (a win is 1, a draw 0.5) with a 95 % Wilson interval.

`--sequential` stops a matchup early with a sequential probability ratio test on A's score: it decides "A better" or "A worse"
as soon as the evidence for a difference of `--delta` (default 0.10) reaches `--alpha`/`--beta` (default 0.05), or "no difference
of that size" when both directions are ruled out; the seeds are consumed in batches of `--jobs`, up to `--games`.

Two checkouts are compared by running this tool in each with the same arguments and `--out`, then `--compare a.json b.json`
(it imports the `sparring` next to it). `--journal-dir` writes the decision journal of every game there (tools/review_decisions.py)."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sparring.ai_medusa import MedusaAI                       # noqa: E402
from sparring.board import Board                              # noqa: E402
from sparring.decision_log import DecisionJournal             # noqa: E402
from sparring.search.adapter import RESOLUTION, EvalWeights   # noqa: E402
from sparring.search.controller import IsmctsMedusa           # noqa: E402
from sparring.search.ismcts import SearchConfig               # noqa: E402
from sparring.state import Game                               # noqa: E402

MAX_TURNS = 120
DEFAULT_BOARD = "bprd-hq"
DEFAULT_ITERATIONS = 200
Z95 = 1.959964
GAMES_PER_WORKER = 6        # a worker is replaced after this many games: the engine caches (reach, moves) grow with every game and 18 workers filled 20 GB


def parse_config(spec: str) -> dict:
    """`heuristic` or `ismcts[:iterations=N,time=S,seed=N]` as a dict (validated here, not inside a worker)."""
    kind, _, rest = spec.partition(":")
    if kind not in ("heuristic", "ismcts"):
        raise ValueError(f"unknown AI {kind!r} in {spec!r} (heuristic | ismcts)")
    opts = dict(item.split("=", 1) for item in rest.split(",") if item)
    unknown = {k for k in opts if k not in ("iterations", "time", "seed", "eval") and not k.startswith("w.")}
    if unknown or (kind == "heuristic" and opts) or opts.get("eval", "old") not in ("old", "new"):
        raise ValueError(f"bad options in {spec!r}: {sorted(unknown) or 'the heuristic takes none, and eval is old or new'}")
    cfg: dict = {"ai": kind, "spec": spec}
    if kind == "ismcts":
        cfg["iterations"] = int(opts["iterations"]) if "iterations" in opts else (None if "time" in opts else DEFAULT_ITERATIONS)
        cfg["time"] = float(opts.get("time", 3600.0))
        cfg["seed"] = int(opts["seed"]) if "seed" in opts else None
        weights = dict(RESOLUTION) if opts.get("eval") == "new" else {}
        weights.update({k[2:]: float(v) for k, v in opts.items() if k.startswith("w.")})
        cfg["weights"] = weights
    return cfg


def make_ai(cfg: dict, me: int, game_seed: int):
    if cfg["ai"] == "heuristic":
        return MedusaAI(me)
    seed = game_seed if cfg["seed"] is None else cfg["seed"]
    return IsmctsMedusa(me, SearchConfig(time_budget=cfg["time"], iterations=cfg["iterations"], seed=seed),
                        EvalWeights(**cfg["weights"]), frozenset(cfg["weights"]))


def wilson(score: float, n: int) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    centre = (score + Z95 ** 2 / (2 * n)) / (1 + Z95 ** 2 / n)
    half = Z95 * math.sqrt(score * (1 - score) / n + Z95 ** 2 / (4 * n * n)) / (1 + Z95 ** 2 / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def play(job: tuple) -> dict:
    """One game: AI A on player `a_seat`, AI B on the other. The seed fixes the shuffles and who moves first."""
    seed, heroes, board, a_cfg, b_cfg, a_seat, journal_dir = job
    started = time.perf_counter()
    cfgs = {a_seat: a_cfg, 1 - a_seat: b_cfg}
    ctl = {p: make_ai(cfgs[p], p, seed) for p in (0, 1)}
    if journal_dir:
        for p in (0, 1):
            ctl[p].journal = DecisionJournal(Path(journal_dir) / f"{heroes[0]}-{heroes[1]}-seed{seed}-A{a_seat}-P{p}.jsonl")
    game = Game.new(Board.load(board), seed, ctl, bot_player=0, heroes=heroes)
    if journal_dir:
        for p in (0, 1):
            ctl[p].journal.new_game(game, p, ctl[p], game_id=f"{heroes[0]}-{heroes[1]}-{seed}-A{a_seat}")
    fallbacks = 0
    while game.winner is None and game.turn_no <= MAX_TURNS:
        game.begin_turn()
        ctl[game.turn].take_turn(game)
        game.log.clear()
        if game.winner is None:
            game.end_turn()
        if journal_dir:
            for p in (0, 1):
                ctl[p].journal.settle(game)         # the outcome closes when the turn changes, as at the table
    for p in (0, 1):
        if ctl[p].journal is not None:
            ctl[p].journal.settle(game, force=True)
        fallbacks += getattr(ctl[p], "fallbacks", 0)
    score = 0.5 if game.winner is None else float(game.winner == a_seat)
    return dict(seed=seed, a_seat=a_seat, score=score, turns=game.turn_no, fallbacks=fallbacks, secs=time.perf_counter() - started)


class Sprt:
    """Sequential probability ratio test on A's score (draws count as half a win) against 0.5, in both directions."""

    def __init__(self, delta: float, alpha: float, beta: float):
        self.up, self.down = 0.5 + delta, 0.5 - delta
        self.accept = math.log((1 - beta) / alpha)
        self.reject = math.log(beta / (1 - alpha))
        self.llr_up = self.llr_down = 0.0

    def add(self, score: float) -> None:
        for name, p1 in (("llr_up", self.up), ("llr_down", self.down)):
            setattr(self, name, getattr(self, name) + score * math.log(p1 / 0.5) + (1 - score) * math.log((1 - p1) / 0.5))

    def verdict(self) -> str | None:
        if self.llr_up >= self.accept:
            return "A better"
        if self.llr_down >= self.accept:
            return "A worse"
        if self.llr_up <= self.reject and self.llr_down <= self.reject:
            return "no difference of that size"
        return None


def summarize(heroes: tuple[str, str], board: str, a_cfg: dict, b_cfg: dict, rows: list[dict], verdict: str | None = None) -> dict:
    n = len(rows)
    score = sum(r["score"] for r in rows) / n if n else 0.0
    lo, hi = wilson(score, n)
    by_seat = {s: [r["score"] for r in rows if r["a_seat"] == s] for s in (0, 1)}
    return dict(heroes=list(heroes), board=board, a=a_cfg["spec"], b=b_cfg["spec"], games=n,
                a_wins=sum(r["score"] == 1.0 for r in rows), b_wins=sum(r["score"] == 0.0 for r in rows),
                unfinished=sum(r["score"] == 0.5 for r in rows), score=score, ci95=[lo, hi],
                a_as_p0=sum(by_seat[0]) / len(by_seat[0]) if by_seat[0] else None,
                a_as_p1=sum(by_seat[1]) / len(by_seat[1]) if by_seat[1] else None,
                avg_turns=sum(r["turns"] for r in rows) / n if n else 0.0, fallbacks=sum(r["fallbacks"] for r in rows),
                avg_secs=sum(r["secs"] for r in rows) / n if n else 0.0, verdict=verdict)


def run_matchup(heroes: tuple[str, str], board: str, a_cfg: dict, b_cfg: dict, games: int, first_seed: int, pool,
                sprt: Sprt | None, batch: int, journal_dir: str | None) -> dict:
    Board.load(board)                       # a map that does not load fails here, once, not in every worker
    seeds = list(range(first_seed, first_seed + games))
    rows: list[dict] = []
    verdict = None
    for i in range(0, len(seeds), batch if sprt else len(seeds)):
        jobs = [(s, heroes, board, a_cfg, b_cfg, seat, journal_dir) for s in seeds[i:i + (batch if sprt else len(seeds))] for seat in (0, 1)]
        done = list(pool.map(play, jobs)) if pool is not None else [play(j) for j in jobs]
        rows += done
        if sprt is not None:
            for r in done:
                sprt.add(r["score"])
            verdict = sprt.verdict()
            if verdict:
                break
    return summarize(heroes, board, a_cfg, b_cfg, rows, verdict)


def show(res: dict) -> str:
    lo, hi = res["ci95"]
    seats = " ".join(f"A as P{s}: {res[k]:.0%}" for s, k in ((0, "a_as_p0"), (1, "a_as_p1")) if res[k] is not None)
    stop = f" | stopped early: {res['verdict']}" if res["verdict"] else ""
    return (f"{res['heroes'][0]} vs {res['heroes'][1]} @ {res['board']}: A={res['a']} B={res['b']} | {res['games']} games | "
            f"A {res['a_wins']} B {res['b_wins']} unfinished {res['unfinished']} | A score {res['score']:.1%} "
            f"[{lo:.1%}, {hi:.1%}] | {seats} | {res['avg_turns']:.1f} turns, {res['avg_secs']:.1f} s/game, "
            f"{res['fallbacks']} search fallbacks{stop}")


def compare(a_path: str, b_path: str) -> None:
    a, b = json.load(open(a_path)), json.load(open(b_path))
    key = lambda r: (tuple(r["heroes"]), r["board"], r["a"], r["b"])
    by_key = {key(r): r for r in b}
    print("matchup | A score before -> after (95 % interval) | verdict")
    for x in a:
        y = by_key.get(key(x))
        if y is None:
            continue
        d = y["score"] - x["score"]
        lo_x, hi_x = x["ci95"]
        lo_y, hi_y = y["ci95"]
        apart = "better" if lo_y > hi_x else "worse" if hi_y < lo_x else "within the interval"
        print(f"{x['heroes'][0]} vs {x['heroes'][1]} @ {x['board']} ({x['a']} vs {x['b']}) | {x['score']:.1%} [{lo_x:.1%}, {hi_x:.1%}] -> "
              f"{y['score']:.1%} [{lo_y:.1%}, {hi_y:.1%}] ({d:+.1%}) | {apart}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", default="ismcts", help="configuration A (the one measured)")
    ap.add_argument("--b", default="heuristic", help="configuration B (the reference)")
    ap.add_argument("--matchup", nargs="+", default=[], metavar="H0:H1", help="hero on player 0 : hero on player 1")
    ap.add_argument("--board", default=DEFAULT_BOARD)
    ap.add_argument("--games", type=int, default=100, help="seeds per matchup (each is played twice, with the AIs swapped)")
    ap.add_argument("--first-seed", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2), help="worker processes; 1 plays in this process")
    ap.add_argument("--sequential", action="store_true", help="stop each matchup early with a sequential probability ratio test")
    ap.add_argument("--delta", type=float, default=0.10, help="sequential test: the difference of score worth detecting")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--beta", type=float, default=0.05)
    ap.add_argument("--journal-dir", help="write the decision journal of every game into this folder")
    ap.add_argument("--out", help="write the results as JSON")
    ap.add_argument("--compare", nargs=2, metavar=("A_JSON", "B_JSON"), help="compare two --out files (two checkouts) and stop")
    args = ap.parse_args(argv)
    if args.compare:
        compare(*args.compare)
        return 0
    if args.games < 1:
        ap.error("--games must be at least 1")
    if not args.matchup:
        ap.error("give at least one --matchup H0:H1")
    a_cfg, b_cfg = parse_config(args.a), parse_config(args.b)
    matchups = [tuple(m.split(":", 1)) for m in args.matchup]
    if args.journal_dir:
        Path(args.journal_dir).mkdir(parents=True, exist_ok=True)
    pool = ProcessPoolExecutor(max_workers=args.jobs, max_tasks_per_child=GAMES_PER_WORKER) if args.jobs > 1 else None
    results, failed = [], 0
    try:
        for heroes in matchups:
            try:
                sprt = Sprt(args.delta, args.alpha, args.beta) if args.sequential else None
                results.append(run_matchup(heroes, args.board, a_cfg, b_cfg, args.games, args.first_seed, pool, sprt,
                                           max(1, args.jobs), args.journal_dir))
                print(show(results[-1]), flush=True)
            except Exception as exc:        # one pairing that cannot be set up must not stop the others
                failed += 1
                print(f"{heroes[0]} vs {heroes[1]} @ {args.board}: ERROR {type(exc).__name__}: {exc}"[:300], file=sys.stderr, flush=True)
    finally:
        if pool is not None:
            pool.shutdown()
    if args.out:
        json.dump(results, open(args.out, "w"), indent=1)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
