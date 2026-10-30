"""Bot play quality over N simulated games (scripted Hellboy by default), for before/after comparisons of the AI.

    python tools/bot_play_metrics.py --bot-hero liz-sherman --games 40

Per bot turn it counts: attacks, maneuvers, turns where the hero never left its space and did not attack ("idle"),
turns that ended over the hand limit ("end discards" = cards forced out at end of turn), schemes played, Searing Clarity
played with no non-scheme card in the discard pile ("wasted": its shuffle took nothing), turns where Fight Or Flight
was played with an action left and the hero still ended out of reach of every rival without attacking, and the win rate."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sparring.ai_medusa import MedusaAI                      # noqa: E402
from sparring.board import Board                              # noqa: E402
from sparring.hellboy_script import ScriptedHellboy           # noqa: E402
from sparring.state import HAND_LIMIT, Game                   # noqa: E402

BOT, HUMAN = 0, 1
MAX_TURNS = 200


class HoldingHellboy(ScriptedHellboy):
    """Never walks towards the bot (maneuvers only to draw): it attacks only what comes to it, like a player who
    keeps his distance and waits."""

    def closer(self, game, f, options):
        return None


def play(seed: int, bot_hero: str, human_hero: str, rival=ScriptedHellboy, board: str = "bprd-hq") -> dict:
    controllers = {BOT: MedusaAI(BOT), HUMAN: rival(HUMAN, seed)}
    game = Game.new(Board.load(board), seed, controllers, bot_player=BOT, heroes=(bot_hero, human_hero))
    stats = dict(turns=0, attacks=0, maneuvers=0, idle=0, end_discards=0, schemes=0, searing=0, searing_wasted=0,
                 fof=0, fof_out_of_reach=0, won=0, lost=0)
    attack, maneuver, play_scheme = game.attack, game.maneuver, game.play_scheme
    turn_flags = {"fof": False}

    def counted_scheme(player, fighter, card, *a, **k):
        if game.turn == BOT:
            stats["schemes"] += 1
            if card.title == "Searing Clarity":
                stats["searing"] += 1
                stats["searing_wasted"] += not any(not c.is_scheme for c in game.players[BOT].discard)
            if card.title == "Fight Or Flight":
                stats["fof"] += 1
                turn_flags["fof"] |= game.actions_left >= 2        # played with an action left to use the move
        return play_scheme(player, fighter, card, *a, **k)

    def counted_attack(*a, **k):
        if game.turn == BOT:
            stats["attacks"] += 1
        return attack(*a, **k)

    def counted_maneuver(*a, **k):
        if game.turn == BOT:
            stats["maneuvers"] += 1
        return maneuver(*a, **k)

    game.attack, game.maneuver, game.play_scheme = counted_attack, counted_maneuver, counted_scheme
    while game.winner is None and game.turn_no <= MAX_TURNS:
        game.begin_turn()
        hero = game.hero(BOT)
        pos0, atk0 = hero.pos, stats["attacks"]
        turn_flags["fof"] = False
        controllers[game.turn].take_turn(game)
        if game.turn == BOT:
            stats["turns"] += 1
            stats["fof_out_of_reach"] += (turn_flags["fof"] and hero.alive and stats["attacks"] == atk0
                                          and not any(game.can_attack(hero, e) for e in game.foes(BOT)))
            stats["idle"] += hero.pos == pos0 and stats["attacks"] == atk0
            stats["end_discards"] += max(0, len(game.players[BOT].hand) - HAND_LIMIT)
        game.log.clear()
        if game.winner is None:
            game.end_turn()
    stats["won"], stats["lost"] = game.winner == BOT, game.winner == HUMAN
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--bot-hero", default="liz-sherman")
    ap.add_argument("--human-hero", default="hellboy")
    ap.add_argument("--hold", action="store_true", help="the rival never approaches")
    args = ap.parse_args(argv)
    rival = HoldingHellboy if args.hold else ScriptedHellboy
    runs = [play(s, args.bot_hero, args.human_hero, rival) for s in range(args.seed, args.seed + args.games)]
    n, mode = len(runs), " (holding)" if args.hold else ""
    tot = {k: sum(r[k] for r in runs) for k in runs[0]}
    print(f"{args.bot_hero} vs {args.human_hero}{mode}, {n} games: win rate {tot['won'] / n:.0%} (lost {tot['lost']}, "
          f"unfinished {n - tot['won'] - tot['lost']}); per game: bot turns {tot['turns'] / n:.1f}, "
          f"attacks {tot['attacks'] / n:.1f}, maneuvers {tot['maneuvers'] / n:.1f}, "
          f"idle turns {tot['idle'] / n:.1f}, end-of-turn discards {tot['end_discards'] / n:.2f}, "
          f"schemes {tot['schemes'] / n:.1f}, Searing Clarity {tot['searing'] / n:.2f} (wasted {tot['searing_wasted'] / n:.2f}), "
          f"Fight Or Flight {tot['fof'] / n:.2f} (turn ended out of reach {tot['fof_out_of_reach'] / n:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
