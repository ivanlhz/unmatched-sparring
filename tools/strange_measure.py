"""Doctor Strange under ISMCTS against a scripted or chasing rival, one matchup per run, for before/after comparisons of
his search weights (F-STRANGE-AGGRO).

    python tools/strange_measure.py base  script hellboy 60 30     # no hero profile (the old weights)
    python tools/strange_measure.py profile chase medusa 60 30     # adapter.HERO_EVAL as shipped
    python tools/strange_measure.py caution=0.1,pack=0.2 script hellboy 60 30   # the shipped profile with other weights

Prints one JSON line: wins, bot turns, attacks, attacks per turn, blows given up per game and schemes per game, over the
seeds `first .. first + games - 1` (200 search iterations per decision, board bprd-hq). Pool the cells to compare."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bot_play_metrics as metrics                       # noqa: E402
from sparring.hellboy_script import ChasingHellboy, ScriptedHellboy   # noqa: E402
from sparring.search import adapter                      # noqa: E402
from sparring.search.controller import make_bot_ai       # noqa: E402


def main(argv: list[str]) -> int:
    mode, rival, human, first, games = argv[0], argv[1], argv[2], int(argv[3]), int(argv[4])
    if mode == "base":
        adapter.HERO_EVAL.clear()
    elif "=" in mode:                # e.g. caution=0.1,scheme_cost=0.2: the shipped profile with these weights changed
        adapter.HERO_EVAL["doctor-strange"] = {**adapter.HERO_EVAL.get("doctor-strange", {}),
                                               **{k: float(v) for k, v in (kv.split("=") for kv in mode.split(","))}}
    elif mode != "profile":
        raise SystemExit("mode: base | profile | <weight>=<x>[,<weight>=<x>]")
    metrics.MedusaAI = lambda bot: make_bot_ai({"ai": "ismcts", "ai_time_budget": 60, "ai_iterations": 200, "ai_seed": 0}, bot)
    rival_class = ChasingHellboy if rival == "chase" else ScriptedHellboy
    runs = [metrics.play(s, "doctor-strange", human, rival_class, "bprd-hq") for s in range(first, first + games)]
    t = {k: sum(r[k] for r in runs) for k in runs[0]}
    print(json.dumps(dict(mode=mode, rival=rival, human=human, seeds=[first, games], won=t["won"], games=games, turns=t["turns"],
                          attacks=t["attacks"], attacks_per_turn=round(t["attacks"] / t["turns"], 3),
                          given_up=round(t["blows_given_up"] / games, 2), schemes=round(t["schemes"] / games, 2))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
