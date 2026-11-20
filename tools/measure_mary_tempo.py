"""Share of Bloody Mary's turn starts that have exactly 3 cards in hand (so a third action), with the tempo term of the AI off and on.

    python tools/measure_mary_tempo.py --seeds 6 --iterations 150

ISMCTS Bloody Mary against the scripted Hellboy of `sim.play`, 30 turns a game; only the live game's turn starts are counted (the search clones
its own). The second arm uses `ai_mary.EXTRA_ACTION_CARDS`; the first sets it to 0. Docs: docs/heroes/bloody-mary.md, AI."""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sparring import ai_mary, sim  # noqa: E402
import sparring.state as st  # noqa: E402


def run(weight: float, seeds: range, iterations: int) -> tuple[int, int]:
    default, ai_mary.EXTRA_ACTION_CARDS = ai_mary.EXTRA_ACTION_CARDS, weight
    starts, live, original = collections.Counter(), set(), st.Game.begin_turn
    make = st.Game.new.__func__

    def new(cls, *a, **k):
        game = make(cls, *a, **k)
        live.add(id(game))
        return game

    def record(self, *a, **k):
        if id(self) in live and self.players[self.turn].hero.slug == "bloody-mary" and self.turn_no > 2:
            starts[len(self.players[self.turn].hand)] += 1
        return original(self, *a, **k)
    st.Game.new, st.Game.begin_turn = classmethod(new), record
    try:
        for seed in seeds:
            sim.play(seed, bot_hero="bloody-mary", human_hero="hellboy", medusa=sim.make_bot("ismcts", iterations=iterations, seed=seed), max_turns=30)
    finally:
        st.Game.begin_turn, st.Game.new = original, classmethod(make)
        ai_mary.EXTRA_ACTION_CARDS = default
    return sum(starts.values()), starts[3]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--iterations", type=int, default=150)
    args = ap.parse_args()
    for label, weight in (("off", 0.0), ("on", ai_mary.EXTRA_ACTION_CARDS)):
        total, three = run(weight, range(1, args.seeds + 1), args.iterations)
        print(f"tempo {label} (weight {weight}): {three}/{total} turn starts with exactly 3 cards = {three / max(1, total):.1%}")
