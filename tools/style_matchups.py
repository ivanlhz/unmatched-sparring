"""Hero-vs-hero heuristic-bot games on shared seeds, to compare two checkouts of the AI (e.g. master vs a branch).

    uv run python tools/style_matchups.py --hero houdini --rivals medusa hellboy raphael --games 60 --out a.json
    uv run python tools/style_matchups.py --compare master.json branch.json

Both sides use the heuristic MedusaAI; the hero under test is player 0 and also alternates nothing: same seeds, same
board, so two runs differ only by the AI code. Run it from each checkout (it imports the `sparring` next to it).
Per matchup: win rate of the hero, share of its turns that end inside a rival hero's reach, Big-Reveal-like finishers
(any card with more than one boost slot is not guessed: `--finisher` names the card title), damage and count, game length."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sparring.ai_medusa import MedusaAI          # noqa: E402
from sparring.board import Board                  # noqa: E402
from sparring.state import Game                   # noqa: E402

ME, RIVAL = 0, 1
MAX_TURNS = 120


def play(seed: int, hero: str, rival: str, finisher: str, board: str = "bprd-hq") -> dict:
    ctl = {ME: MedusaAI(ME), RIVAL: MedusaAI(RIVAL)}
    game = Game.new(Board.load(board), seed, ctl, bot_player=ME, heroes=(hero, rival))
    out = dict(won=0, lost=0, turns=0, my_turns=0, in_reach=0, finisher_n=0, finisher_dmg=0.0, attacks=0)
    real_attack = game.attack

    def attack(att, tgt, card, *a, **k):
        hp = tgt.hp
        res = real_attack(att, tgt, card, *a, **k)
        if game.turn == ME and att.fid == game.hero(ME).fid:
            out["attacks"] += 1
            if card.title == finisher:
                out["finisher_n"] += 1
                out["finisher_dmg"] += max(0, hp - tgt.hp)
        return res
    game.attack = attack
    while game.winner is None and game.turn_no <= MAX_TURNS:
        game.begin_turn()
        ctl[game.turn].take_turn(game)
        if game.turn == ME:
            me = game.hero(ME)
            out["my_turns"] += 1
            out["in_reach"] += me.alive and any(game.can_attack(e, me) for e in game.foes(ME) if e.hero)
        game.log.clear()
        if game.winner is None:
            game.end_turn()
    out["won"], out["lost"], out["turns"] = int(game.winner == ME), int(game.winner == RIVAL), game.turn_no
    return out


def run(hero: str, rival: str, games: int, finisher: str) -> dict:
    rows = [play(s, hero, rival, finisher) for s in range(games)]
    n = len(rows)
    tot = lambda k: sum(r[k] for r in rows)
    return dict(hero=hero, rival=rival, games=n, win=tot("won") / n, loss=tot("lost") / n,
                in_reach=tot("in_reach") / max(1, tot("my_turns")), finisher_n=tot("finisher_n"),
                finisher_dmg=tot("finisher_dmg"), avg_turns=tot("turns") / n)


def compare(a_path: str, b_path: str) -> None:
    a, b = json.load(open(a_path)), json.load(open(b_path))
    print("matchup | win A -> B | in-reach turns A -> B | finisher n A -> B | finisher dmg A -> B | game length A -> B")
    for x, y in zip(a, b):
        print(f"{x['hero']} vs {x['rival']} | {x['win']:.0%} -> {y['win']:.0%} | {x['in_reach']:.0%} -> {y['in_reach']:.0%} | "
              f"{x['finisher_n']} -> {y['finisher_n']} | {x['finisher_dmg']:.0f} -> {y['finisher_dmg']:.0f} | "
              f"{x['avg_turns']:.1f} -> {y['avg_turns']:.1f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hero")
    ap.add_argument("--rivals", nargs="+", default=[])
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--finisher", default="The Big Reveal")
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs=2)
    args = ap.parse_args()
    if args.compare:
        return compare(*args.compare)
    res = []
    for r in args.rivals:
        res.append(run(args.hero, r, args.games, args.finisher))
        print(res[-1], flush=True)
    if args.out:
        json.dump(res, open(args.out, "w"), indent=1)


if __name__ == "__main__":
    main()
