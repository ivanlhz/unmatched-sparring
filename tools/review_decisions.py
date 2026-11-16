"""Reads the decision journal (state/decisions.jsonl) of one game and lists the decisions worth a second look.

    python tools/review_decisions.py                          # last game in state/decisions.jsonl
    python tools/review_decisions.py path/to/decisions.jsonl --game 20261116-173144-1a2b --list

- surprises: the outcome was far from what the bot expected. For the search the chosen move's mean value is compared with the
  evaluation of the position after it resolved (same [0, 1] scale, `--gap`); for the heuristic the expected damage of a
  chosen attack is compared with the damage it really did (`--damage-gap`).
- coin flips: the two best alternatives were within noise (`--noise` of mean value for the search, a relative 2 % of score for the
  heuristic), so the choice between them says little.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent.parent / "state" / "decisions.jsonl"


def read_games(path: Path) -> dict[str, dict]:
    """game id -> {"header", "decisions": {seq: decision}, "outcomes": {seq: outcome}}; a line that does not parse is skipped."""
    games: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        game = games.setdefault(rec.get("game"), {"header": None, "decisions": {}, "outcomes": {}})
        if rec.get("t") == "game":
            game["header"] = rec
        elif rec.get("t") == "decision":
            game["decisions"][rec["seq"]] = rec
        elif rec.get("t") == "outcome":
            game["outcomes"][rec["seq"]] = rec
    return games


def move_text(move) -> str:
    if isinstance(move, dict):
        text = " ".join(str(v) for k, v in move.items() if k in ("kind", "fid", "target", "card", "boost"))
        return f"{text} {move['moves']}" if move.get("moves") else text
    return " ".join("-" if m is None else str(m) for m in move) if isinstance(move, list) else str(move)


def chosen_text(dec: dict) -> str:
    chosen = dec["chosen"]
    return f"defend with {chosen['card'] or 'nothing'}" if dec["kind"] == "defense" else move_text(chosen)


def expected_damage(dec: dict) -> float | None:
    """What the heuristic expected its chosen attack to do (its own candidate list carries `exp_damage`)."""
    if dec["ai"] != "heuristic" or dec["kind"] != "plan" or dec["chosen"].get("kind") != "attack":
        return None
    return next((a["exp_damage"] for a in dec["alternatives"] if a["move"] == dec["chosen"]), None)


def surprises(game: dict, gap: float, damage_gap: float) -> list[tuple[dict, dict, str]]:
    out = []
    for seq, dec in game["decisions"].items():
        res = game["outcomes"].get(seq)
        if res is None:
            continue
        if dec["ai"] == "ismcts" and dec.get("expected") is not None and res.get("evaluation_after") is not None:
            diff = res["evaluation_after"] - dec["expected"]
            if abs(diff) >= gap:
                out.append((dec, res, f"expected {dec['expected']:.3f}, position worth {res['evaluation_after']:.3f} afterwards ({diff:+.3f})"))
        exp = expected_damage(dec)
        if exp is not None and abs(res["damage_dealt"] - exp) >= damage_gap:
            out.append((dec, res, f"expected {exp:.1f} damage, dealt {res['damage_dealt']}"))
    return out


def coin_flips(game: dict, noise: float) -> list[tuple[dict, str]]:
    out = []
    for dec in game["decisions"].values():
        alts = dec["alternatives"]
        if len(alts) < 2:
            continue
        if dec["ai"] == "ismcts":
            ranked = sorted((a for a in alts if a.get("value") is not None), key=lambda a: -a["visits"])
            if len(ranked) >= 2 and abs(ranked[0]["value"] - ranked[1]["value"]) <= noise:
                out.append((dec, f"{move_text(ranked[0]['move'])} {ranked[0]['value']:.3f} ({ranked[0]['visits']} visits) vs "
                                 f"{move_text(ranked[1]['move'])} {ranked[1]['value']:.3f} ({ranked[1]['visits']} visits)"))
        else:
            ranked = sorted(alts, key=lambda a: -a["score"])
            a, b = ranked[0], ranked[1]
            if abs(a["score"] - b["score"]) <= 0.02 * max(1.0, abs(a["score"])):
                out.append((dec, f"{move_text(a['move'])} {a['score']:.2f} vs {move_text(b['move'])} {b['score']:.2f}"))
    return out


def report(game: dict, gap: float, damage_gap: float, noise: float, out=None) -> tuple[int, int]:
    out = out or sys.stdout
    head = game["header"] or {}
    budget = "" if head.get("time_budget") is None else ", " + format(head["time_budget"], "g") + " s per decision"
    print(f"game {head.get('game')}: {head.get('bot_hero')} (bot, {head.get('ai')}{budget}) vs "
          f"{head.get('rival_hero')}; {len(game['decisions'])} decisions", file=out)
    surprised, flips = surprises(game, gap, damage_gap), coin_flips(game, noise)
    print(f"\nOutcome far from the expectation: {len(surprised)}", file=out)
    for dec, res, why in surprised:
        print(f"  turn {dec['turn']} #{dec['seq']} {dec['kind']}: {chosen_text(dec)} | {why} | dealt {res['damage_dealt']} taken {res['damage_taken']}"
              f" spent {res['own_cards_spent']} rival played {res['rival_cards_played']}", file=out)
    print(f"\nTop two alternatives within noise: {len(flips)}", file=out)
    for dec, why in flips:
        print(f"  turn {dec['turn']} #{dec['seq']} {dec['kind']}: chose {chosen_text(dec)} | {why}", file=out)
    return len(surprised), len(flips)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--game", help="game id (default: the last one in the file)")
    ap.add_argument("--list", action="store_true", help="list the games in the file and stop")
    ap.add_argument("--gap", type=float, default=0.15, help="search: |evaluation after - expected value| to flag")
    ap.add_argument("--damage-gap", type=float, default=3.0, help="heuristic: |damage dealt - expected damage| to flag")
    ap.add_argument("--noise", type=float, default=0.01, help="search: difference of mean value between the top two that counts as a tie")
    args = ap.parse_args(argv)
    if not args.file.exists():
        print(f"no journal at {args.file}", file=sys.stderr)
        return 1
    games = read_games(args.file)
    games.pop(None, None)
    if not games:
        print("the journal has no games", file=sys.stderr)
        return 1
    if args.list:
        for gid, g in games.items():
            print(gid, (g["header"] or {}).get("bot_hero"), "vs", (g["header"] or {}).get("rival_hero"), len(g["decisions"]), "decisions")
        return 0
    gid = args.game or list(games)[-1]
    if gid not in games:
        print(f"game {gid} is not in the journal (--list shows them)", file=sys.stderr)
        return 1
    report(games[gid], args.gap, args.damage_gap, args.noise)
    return 0


if __name__ == "__main__":
    sys.exit(main())
