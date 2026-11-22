"""Reproducible measurements behind the doubloon policies of `sparring/ai_blackbeard.py` (docs/heroes/blackbeard.md, AI).

    python tools/measure_blackbeard_ai.py action 40      # the bot is Blackbeard: the start-of-turn action by policy / always / never
    python tools/measure_blackbeard_ai.py ransom 40      # the bot is Hellboy against a Blackbeard that walks up and attacks: ransoms by policy / always / never
    python tools/measure_blackbeard_ai.py caps 60        # the bot is Blackbeard: the action policy with other caps (Treasury after paying, cards to play)

Each cell is the games the bot won out of N seeded games on the B.P.R.D. table against the scripted chasing rival (`sim.play(rival="chaser")`,
heuristic AI), 40 turns at most. The variants replace `ai_blackbeard.action_pays` / `ransom_pays` for the run; `queens_amount` keeps the policy."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sparring import ai_blackbeard, sim  # noqa: E402

VARIANTS = {"policy": None, "always": lambda ai, game, req: True, "never": lambda ai, game, req: False}


def wins(bot: str, human: str, n: int) -> int:
    won = 0
    for seed in range(n):
        out = sim.play(seed, bot_hero=bot, human_hero=human, rival="chaser", max_turns=40)
        won += out.winner == bot_name(bot)
    return won


def bot_name(slug: str) -> str:
    from sparring.heroes import load_hero
    return load_hero(slug).name


CAPS = ((2, 2), (3, 2), (3, 1), (3, 0))       # (TREASURY_CAP, USEFUL_ACTIONS): (3, 0) buys the action every turn


def caps(n: int) -> None:
    cap, useful = ai_blackbeard.TREASURY_CAP, ai_blackbeard.USEFUL_ACTIONS
    for c, u in CAPS:
        ai_blackbeard.TREASURY_CAP, ai_blackbeard.USEFUL_ACTIONS = c, u
        print(f"caps    cap {c} useful {u}  the bot (blackbeard) won {wins('blackbeard', 'hellboy', n)}/{n}", flush=True)
    ai_blackbeard.TREASURY_CAP, ai_blackbeard.USEFUL_ACTIONS = cap, useful


def main(kind: str, n: int) -> None:
    if kind == "caps":
        return caps(n)
    attr, bot, human = ("action_pays", "blackbeard", "hellboy") if kind == "action" else ("ransom_pays", "hellboy", "blackbeard")
    original = getattr(ai_blackbeard, attr)
    for name, replacement in VARIANTS.items():
        setattr(ai_blackbeard, attr, original if replacement is None else replacement)
        print(f"{kind:<7} {name:<7} the bot ({bot}) won {wins(bot, human, n)}/{n}", flush=True)
    setattr(ai_blackbeard, attr, original)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
