"""Hero-vs-hero heuristic-bot games on shared seeds, to compare two checkouts of the AI (e.g. master vs a branch).

    uv run python tools/style_matchups.py --hero houdini --rivals medusa hellboy raphael --games 60 --out a.json
    uv run python tools/style_matchups.py --heroes houdini medusa bigfoot --rivals all --boards bprd-hq soho venice yukon \
        --games 20 --swap-seats --table --out grid.json
    uv run python tools/style_matchups.py --compare master.json branch.json

Both sides use the heuristic MedusaAI. The hero under test is ALWAYS player 0 (it starts on space "1"; the rival never plays
the tested hero's seat), with seeds 0..games-1: two runs differ only by the AI code, so run it from each checkout (it imports
the `sparring` next to it). Who moves first is drawn by the seed in `Game.new`, so by default it is a coin flip per seed;
`--swap-seats` plays every seed twice, forcing the tested hero to move first and then second. `--boards` picks the maps
(`all`: every data/maps/*.json but the catalog). A matchup that raises is recorded as `error` in its row and the run goes on.
Per matchup:
- win / loss rate of the tested hero;
- `in_reach`: share of the hero's turns that END where a rival hero can strike it NEXT turn (it moves up to its Move onto a
  free space from which its attack reaches the hero, then attacks; no boost counted). This is the reach the AI fears;
- `attackable_now`: share that end with a rival hero already able to attack it without moving (the old, stricter metric);
- finishers: how many times the hero played the card titled `--finisher` (default The Big Reveal) and the rival HP it took;
- per-card counters (Houdini): All Part of the Show spent as a boost / played as a defense / times it saved the hero; Sleight of
  Hand used as the opener of a Big Reveal (swapped into it, or boosting it) / spent as a Maneuver boost / played otherwise;
  A Magician Never Reveals His Secrets played as a scheme / spent as a boost of a Big Reveal / spent as any other boost;
  Flourish and An Illusion of My Own Design attacks, by the hero and by a sidekick (summed in `--compare`);
- average game length in turns.

The seeds are spread over `--jobs` worker processes (same numbers as `--jobs 1`, only faster)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sparring.ai_medusa import MedusaAI          # noqa: E402
from sparring.board import Board                  # noqa: E402
from sparring.state import Game                   # noqa: E402

ME, RIVAL = 0, 1
MAX_TURNS = 120
DEFAULT_BOARD = "bprd-hq"
ROOT = Path(__file__).resolve().parent.parent
APS, SLEIGHT, BIG_REVEAL, MAGICIAN = "All Part of the Show", "Sleight of Hand", "The Big Reveal", "A Magician Never Reveals His Secrets"
SHORT = {APS: "aps", SLEIGHT: "sleight", BIG_REVEAL: "big_reveal", MAGICIAN: "magician", "Flourish": "flourish",
         "An Illusion of My Own Design": "illusion"}
CARD_COUNTERS = ("aps_boost", "aps_defense", "aps_saved", "sleight_big_reveal", "sleight_boosts_big_reveal", "sleight_other",
                 "magician_scheme", "magician_big_reveal", "magician_other_boost", "flourish_hero", "flourish_sidekick",
                 "illusion_hero", "illusion_sidekick", "big_reveal_boost",
                 *(f"maneuver_boost_{k}" for k in SHORT.values()), *(f"hand_limit_{k}" for k in SHORT.values()))

_HOOKS: dict = {}       # id(effects state) -> callback(name, *args): the games being measured


def install_emit_spy(fx_class) -> None:
    """Event spy on the class (the effects state has read-only slots, so an instance cannot be patched and a proxy would change
    what the engine reads): one wrapper, called only for the states registered in `_HOOKS`."""
    if getattr(fx_class.emit, "_spy", False):
        return
    real = fx_class.emit

    def emit(self, name, *args):
        hook = _HOOKS.get(id(self))
        if hook is not None:
            hook(name, *args)
        return real(self, name, *args)
    emit._spy = True
    fx_class.emit = emit


def next_turn_reach(game: Game, me, rival_hero) -> bool:
    """A free space within the rival's Move from which its attack reaches `me` (or the space it already stands on)."""
    board = game.board
    taken = {f.pos for f in game.fighters.values() if f.alive}
    return any(s == rival_hero.pos or s not in taken
               for s in board.spaces
               if board.can_reach_target(s, me.pos, rival_hero.ranged, rival_hero.reach) and board.distance(rival_hero.pos, s) <= rival_hero.move)


def play(seed: int, hero: str, rival: str, finisher: str, board: str = DEFAULT_BOARD, first: int | None = None) -> dict:
    """`first`: the player who moves first (ME or RIVAL); None keeps what the seed drew. `Game.new` draws it after the
    shuffles and nothing else reads it, so overriding `game.turn` before the first turn changes only the tempo."""
    started = time.perf_counter()
    ctl = {ME: MedusaAI(ME), RIVAL: MedusaAI(RIVAL)}
    game = Game.new(Board.load(board), seed, ctl, bot_player=ME, heroes=(hero, rival))
    if first is not None:
        game.turn = first
    out = dict(won=0, lost=0, turns=0, my_turns=0, in_reach=0, attackable_now=0, finisher_n=0, finisher_dmg=0.0, attacks=0, **dict.fromkeys(CARD_COUNTERS, 0))
    real_attack, real_maneuver, real_scheme, real_discard = game.attack, game.maneuver, game.play_scheme, game.discard_card
    spent = []       # the titles the tested hero spent as boosts since the last action was settled

    def on_event(name, *args):
        if name == "card_boosted" and args[0] == ME:
            spent.append(args[1].title)

    def settle(into_big_reveal: bool, in_maneuver: bool = False) -> None:
        """Classify the boosts of the action that just ended: into a Big Reveal, in a Maneuver, or any other."""
        for title in spent:
            out["aps_boost"] += title == APS
            out["big_reveal_boost"] += title == BIG_REVEAL
            out["sleight_boosts_big_reveal"] += title == SLEIGHT and into_big_reveal
            out["magician_big_reveal"] += title == MAGICIAN and into_big_reveal
            out["magician_other_boost"] += title == MAGICIAN and not into_big_reveal
            if in_maneuver and title in SHORT:
                out[f"maneuver_boost_{SHORT[title]}"] += 1
        spent.clear()

    def maneuver(player, moves, boost_card=None):
        res = real_maneuver(player, moves, boost_card)
        settle(False, in_maneuver=True)
        return res

    def play_scheme(player, fighter, card, *a, **k):
        out["magician_scheme"] += player == ME and card.title == MAGICIAN
        return real_scheme(player, fighter, card, *a, **k)

    def discard_card(player, card, played=False, cause=None):
        if player == ME and cause == "hand_limit" and card.title in SHORT:
            out[f"hand_limit_{SHORT[card.title]}"] += 1
        return real_discard(player, card, played, cause)

    def count_cards(att, tgt, card, hp, res):
        """The per-card counters of one combat the tested hero's side took part in."""
        settle(att.owner == ME and res.atk_card.title == BIG_REVEAL)
        if att.owner == ME:
            side = "hero" if att.hero else "sidekick"
            for title, key in (("Flourish", "flourish"), ("An Illusion of My Own Design", "illusion")):
                out[f"{key}_{side}"] += card.title == title
            if card.title == SLEIGHT:
                out["sleight_big_reveal" if res.atk_card.title == BIG_REVEAL else "sleight_other"] += 1
        elif tgt.owner == ME and res.def_card is not None and res.def_card.title == APS:
            out["aps_defense"] += 1
            out["aps_saved"] += tgt.hero and tgt.alive and res.damage >= hp

    def attack(att, tgt, card, *a, **k):
        hp = tgt.hp
        res = real_attack(att, tgt, card, *a, **k)
        count_cards(att, tgt, card, hp, res)
        if game.turn == ME and att.fid == game.hero(ME).fid:
            out["attacks"] += 1
            if res.atk_card.title == finisher:      # also a Big Reveal launched through Sleight of Hand
                out["finisher_n"] += 1
                out["finisher_dmg"] += max(0, hp - tgt.hp)
        return res
    game.attack, game.maneuver, game.play_scheme, game.discard_card = attack, maneuver, play_scheme, discard_card
    install_emit_spy(type(game.fx))
    _HOOKS[id(game.fx)] = on_event
    while game.winner is None and game.turn_no <= MAX_TURNS:
        game.begin_turn()
        ctl[game.turn].take_turn(game)
        if game.turn == ME:
            me = game.hero(ME)
            out["my_turns"] += 1
            rivals = [e for e in game.foes(ME) if e.hero and e.alive]
            out["in_reach"] += me.alive and any(next_turn_reach(game, me, e) for e in rivals)
            out["attackable_now"] += me.alive and any(game.can_attack(e, me) for e in rivals)
        game.log.clear()
        if game.winner is None:
            game.end_turn()
    _HOOKS.pop(id(game.fx), None)
    out["won"], out["lost"], out["turns"] = int(game.winner == ME), int(game.winner == RIVAL), game.turn_no
    out["secs"] = time.perf_counter() - started
    return out


def _play_job(job: tuple) -> dict:
    return play(*job)


def run(hero: str, rival: str, games: int, finisher: str, first_seed: int = 0, pool=None, board: str = DEFAULT_BOARD,
        swap_seats: bool = False) -> dict:
    """`pool`: an executor to spread the seeds over processes. A game depends only on its seed and `map` keeps the seed
    order, so the result is the same as the serial run. `swap_seats`: every seed is played twice, the tested hero moving
    first and then second; `games` counts the seeds, the row's `games` the games played."""
    Board.load(board)           # a map that does not load fails here, once, not in every worker
    firsts = (ME, RIVAL) if swap_seats else (None,)
    jobs = [(s, hero, rival, finisher, board, f) for s in range(first_seed, first_seed + games) for f in firsts]
    rows = list(pool.map(_play_job, jobs)) if pool is not None else [_play_job(j) for j in jobs]
    n = len(rows)
    tot = lambda k: sum(r[k] for r in rows)
    res = dict(hero=hero, rival=rival, board=board, games=n, cards={k: tot(k) for k in CARD_COUNTERS}, win=tot("won") / n,
               loss=tot("lost") / n, in_reach=tot("in_reach") / max(1, tot("my_turns")),
               attackable_now=tot("attackable_now") / max(1, tot("my_turns")), finisher_n=tot("finisher_n"),
               finisher_dmg=tot("finisher_dmg"), avg_turns=tot("turns") / n, avg_secs=tot("secs") / n)
    if swap_seats:
        for key, who in (("win_first", ME), ("win_second", RIVAL)):
            sub = [r for j, r in zip(jobs, rows) if j[5] == who]
            res[key] = sum(r["won"] for r in sub) / len(sub)
    return res


def all_boards() -> list[str]:
    return sorted(p.stem for p in (ROOT / "data" / "maps").glob("*.json") if p.stem != "catalog")


def all_heroes() -> list[str]:
    return sorted(p.stem for p in (ROOT / "data" / "heroes").glob("*.json"))


def row_key(row: dict) -> tuple:
    return row["hero"], row["rival"], row.get("board", DEFAULT_BOARD)     # files from before `--boards` have no board


def print_tables(res: list[dict]) -> None:
    """One markdown table per tested hero: rows = rival, columns = board, cells = win rate in %, with the means."""
    for hero in dict.fromkeys(r["hero"] for r in res):
        rows = [r for r in res if r["hero"] == hero]
        rivals = list(dict.fromkeys(r["rival"] for r in rows))
        boards = list(dict.fromkeys(r["board"] for r in rows))
        cell = {(r["rival"], r["board"]): r for r in rows}
        pct = lambda rv, b: 100 * cell[rv, b]["win"] if (rv, b) in cell and "error" not in cell[rv, b] else None
        mean = lambda vals: f"{sum(vals) / len(vals):.0f}" if vals else "-"
        show = lambda rv, b: "" if (rv, b) not in cell else "err" if pct(rv, b) is None else f"{pct(rv, b):.0f}"
        print(f"\n### {hero}: win rate % by rival and board\n")
        print("| rival | " + " | ".join(boards) + " | mean |")
        print("|---|" + "---:|" * (len(boards) + 1))
        for rv in rivals:
            print(f"| {rv} | " + " | ".join(show(rv, b) for b in boards)
                  + f" | {mean([v for b in boards if (v := pct(rv, b)) is not None])} |")
        cols = [[v for rv in rivals if (v := pct(rv, b)) is not None] for b in boards]
        print("| mean | " + " | ".join(mean(c) for c in cols) + f" | {mean([v for c in cols for v in c])} |")


def compare(a_path: str, b_path: str) -> None:
    a, b = json.load(open(a_path)), json.load(open(b_path))
    by_key = {row_key(y): y for y in b if "error" not in y}
    pairs = [(x, by_key[row_key(x)]) for x in a if "error" not in x and row_key(x) in by_key]
    a, b = [x for x, _ in pairs], [y for _, y in pairs]
    print("matchup | win A -> B | next-turn reach A -> B | attackable now A -> B | finisher n A -> B | finisher dmg A -> B | game length A -> B")
    for x, y in pairs:
        where = f" @ {x['board']}" if "board" in x else ""
        print(f"{x['hero']} vs {x['rival']}{where} | {x['win']:.0%} -> {y['win']:.0%} | {x['in_reach']:.0%} -> {y['in_reach']:.0%} | "
              f"{x['attackable_now']:.0%} -> {y['attackable_now']:.0%} | "
              f"{x['finisher_n']} -> {y['finisher_n']} | {x['finisher_dmg']:.0f} -> {y['finisher_dmg']:.0f} | "
              f"{x['avg_turns']:.1f} -> {y['avg_turns']:.1f}")
    print("\nsummed over the matchups (A -> B)")
    for label, key in (("win rate", "win"), ("next-turn reach", "in_reach"), ("Big Reveals", "finisher_n")):
        total = lambda rows: sum(r[key] for r in rows)
        print(f"{label}: {total(a) / len(a):.3f} -> {total(b) / len(b):.3f}" if key != "finisher_n" else f"{label}: {total(a)} -> {total(b)}")
    for k in CARD_COUNTERS:
        print(f"{k}: {sum(x.get('cards', {}).get(k, 0) for x in a)} -> {sum(y.get('cards', {}).get(k, 0) for y in b)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hero")
    ap.add_argument("--heroes", nargs="+", help="several tested heroes in one run (instead of --hero)")
    ap.add_argument("--rivals", nargs="+", default=[], help="hero slugs, or `all`: every data/heroes/*.json but the tested one")
    ap.add_argument("--boards", nargs="+", default=[DEFAULT_BOARD], help="map keys, or `all`: every data/maps/*.json")
    ap.add_argument("--swap-seats", action="store_true", help="play each seed twice, the tested hero moving first and second")
    ap.add_argument("--table", action="store_true", help="print a markdown win-rate table per tested hero at the end")
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--first-seed", type=int, default=0, help="seeds first..first+games-1")
    ap.add_argument("--finisher", default="The Big Reveal")
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs=2)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2),
                    help="worker processes (default: the CPU count minus 2); 1 plays the games in this process")
    args = ap.parse_args()
    if args.compare:
        return compare(*args.compare)
    if bool(args.hero) == bool(args.heroes):
        ap.error("give the tested hero with --hero, or several with --heroes (one of the two)")
    heroes = args.heroes or [args.hero]
    boards = all_boards() if args.boards == ["all"] else args.boards
    rivals = all_heroes() if args.rivals == ["all"] else args.rivals
    plan = [(h, r, b) for h in heroes for r in rivals if r != h for b in boards]
    res = []
    pool = ProcessPoolExecutor(max_workers=args.jobs) if args.jobs > 1 else None
    try:
        for i, (hero, rival, board) in enumerate(plan, 1):
            try:
                res.append(run(hero, rival, args.games, args.finisher, args.first_seed, pool, board, args.swap_seats))
                print(res[-1], flush=True)
                note = f"win {res[-1]['win']:.0%}, {res[-1]['avg_secs']:.1f}s/game"
            except Exception as exc:      # one bad pairing (map without starts, same-fighter clash...) must not stop the batch
                res.append(dict(hero=hero, rival=rival, board=board, games=0, error=f"{type(exc).__name__}: {exc}"[:200]))
                note = f"ERROR {res[-1]['error']}"
            print(f"[{i}/{len(plan)}] {hero} vs {rival} @ {board}: {note}", file=sys.stderr, flush=True)
    finally:
        if pool is not None:
            pool.shutdown()
    if args.out:
        json.dump(res, open(args.out, "w"), indent=1)
    if args.table:
        print_tables(res)
    failed = [r for r in res if "error" in r]
    if failed:
        print(f"\n{len(failed)} failed matchup(s):")
        for r in failed:
            print(f"  {r['hero']} vs {r['rival']} @ {r['board']}: {r['error']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
