"""Reproducible measurements behind the search leaf of Achilles' VENGEANCE (`ai_achilles.LEAF_HP`, `search.adapter.EngineState._vengeance`).

    python tools/measure_achilles_ai.py leaf                       # what a fall of a 2-HP Patroclus is worth in the leaf, both seats
    python tools/measure_achilles_ai.py games 8 40 3.0 0           # 8 games, 40 iterations, leaf edges 3.0 and 0 hit points, both seats

`leaf`: Achilles stands next to Hellboy with 4 cards in hand and Patroclus at 2 hit points. The position is evaluated by the search leaf
before and after Patroclus falls (the engine discards the two cards, so the hand term is in the number), with the default weights and the
normalized ones (`RESOLUTION`). "Achilles' side" is `EngineState._advantage(Achilles)`; "rival's search" is the leaf value the rival's
search reads for the same two positions (`evaluate(rival)`, 0..1). A kill of Patroclus must look good to the rival (rival delta > 0) and
cost Achilles' side no more than the trade is worth (side delta in hit points close to FALL_EDGE minus the hit points, the alive term and
the two cards Patroclus takes with him).

`games`: the search AI with `iterations` per decision plays N seeded games on the B.P.R.D. table against the scripted chasing rival, in
both seats: `achilles-bot` (the bot is Achilles, the rival Hellboy) and `rival-bot` (the bot is Hellboy, the scripted rival plays
Achilles the way a person who walks up and attacks does). For each leaf edge it prints, per seat, the games the bot won and the games in
which Patroclus fell. The edge only moves the leaf: the heuristic prices (`fall_net`) are unchanged."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sparring import ai_achilles, sim  # noqa: E402
from sparring.board import Board  # noqa: E402
from sparring.search.adapter import REFERENCE_HP, RESOLUTION, EngineState, EvalWeights, Knowledge, hero_weights  # noqa: E402
from sparring.state import Game  # noqa: E402


def _state(g: Game, observer: int, weights: EvalWeights) -> EngineState:
    return EngineState(g, observer=observer, knowledge=Knowledge.from_game(g, observer), weights=hero_weights(weights, g.players[observer].hero.slug, frozenset(RESOLUTION)))


def _position() -> Game:
    g = Game.new(Board.load("bprd-hq"), 3, heroes=("achilles", "hellboy"), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
        for c in p.deck[:4]:
            p.deck.remove(c)
            p.hand.append(c)
    a, h = g.fighters["achilles"], g.fighters["hellboy"]
    a.pos = min(g.board.spaces)
    h.pos = sorted(g.board.adj[a.pos])[0]
    far = sorted((s for s in g.board.spaces if s not in (a.pos, h.pos) and not g.board.share_zone(a.pos, s)), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.fid not in ("achilles", "hellboy")], far):
        f.pos = s
    g.fighters["patroclus"].hp = 2
    return g


def leaf() -> None:
    before = _position()
    after = before.clone()
    after.damage(after.fighters["patroclus"], 2, "effect")          # the fall: the engine discards the two cards and starts the vengeance
    assert not after.fighters["patroclus"].alive and len(after.players[0].hand) == 2
    hero = before.hero(0)
    print(f"Patroclus 2 HP falls; Achilles' hand {len(before.players[0].hand)} -> {len(after.players[0].hand)}; FALL_EDGE {ai_achilles.FALL_EDGE}, LEAF_HP {ai_achilles.LEAF_HP}")
    for name, weights, unit in (("default (not normalized)", EvalWeights(), 1.0 / hero.max_hp),
                                ("normalized (RESOLUTION)", EvalWeights(**RESOLUTION), 1.0 / (2.0 * REFERENCE_HP))):
        side = _state(after, 0, weights)._advantage(0) - _state(before, 0, weights)._advantage(0)
        rival_after, rival_before = _state(after, 1, weights).evaluate(1), _state(before, 1, weights).evaluate(1)
        achilles_after, achilles_before = _state(after, 0, weights).evaluate(0), _state(before, 0, weights).evaluate(0)
        print(f"  {name}: Achilles' advantage {side:+.3f} = {side / unit:+.1f} hit points; leaf for Achilles' search {achilles_before:.3f} -> {achilles_after:.3f} ({achilles_after - achilles_before:+.3f});"
              f" leaf for the rival's search {rival_before:.3f} -> {rival_after:.3f} ({rival_after - rival_before:+.3f})")


def games(n: int, iterations: int, edges: list[float]) -> None:
    for edge in edges:
        ai_achilles.LEAF_HP = edge
        for seat, bot, human in (("achilles-bot", "achilles", "hellboy"), ("rival-bot", "hellboy", "achilles")):
            won = fell = 0
            for seed in range(n):
                ai = sim.make_bot("ismcts", iterations=iterations, seed=seed)
                ctl = {sim.MEDUSA: ai, sim.HELLBOY: sim.RIVALS["chaser"](sim.HELLBOY, seed)}
                g = Game.new(Board.load("bprd-hq"), seed, ctl, bot_player=sim.MEDUSA, heroes=(bot, human))
                fell_here = False
                while g.winner is None and g.turn_no <= 40:
                    g.begin_turn()
                    ctl[g.turn].take_turn(g)
                    fell_here = fell_here or not g.fighters["patroclus"].alive
                    g.log.clear()
                    if g.winner is None:
                        g.end_turn()
                won += g.winner == sim.MEDUSA
                fell += fell_here
            print(f"leaf edge {edge:>4} HP  {seat:<12} bot won {won}/{n}  games where Patroclus fell {fell}/{n}", flush=True)


if __name__ == "__main__":
    if sys.argv[1] == "leaf":
        leaf()
    else:
        games(int(sys.argv[2]), int(sys.argv[3]), [float(x) for x in sys.argv[4:]])
