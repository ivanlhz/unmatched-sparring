"""Plain-text game log next to the session state file, for reviewing a game afterwards.

The chat helper (`Session.say`) feeds every message here; `Session._done` feeds the state changes the chat does not
say (moves, draws, discards, turn starts). Logging never breaks the game: an I/O error is swallowed after one warning."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

LOG_NAME = "session.log"
LEGACY_LOG_NAME = "partida.log"


def log_path(state_path: Path | None) -> Path | None:
    """The log lives in the same directory as the state file; a game whose log is still the old `partida.log` keeps
    appending to it."""
    if state_path is None:
        return None
    legacy = Path(state_path).with_name(LEGACY_LOG_NAME)
    current = Path(state_path).with_name(LOG_NAME)
    return legacy if legacy.exists() and not current.exists() else current


class GameLog:
    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time):
        self.path = path
        self.clock = clock
        self._warned = False
        self._prev: dict | None = None

    def _warn(self, what: str, error: Exception) -> None:
        if not self._warned:
            self._warned = True
            print(f"[warning] game log disabled for this problem ({what}): {error!r}", file=sys.stderr)

    def _write(self, text: str) -> None:
        if self.path is None:
            return
        try:
            with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                f.write(text + "\n")
        except Exception as e:                       # the log must never break the game
            self._warn(f"cannot write {self.path}", e)

    def line(self, text: str) -> None:
        try:
            stamp = time.strftime("%H:%M:%S", time.localtime(self.clock()))
            self._write(f"{stamp} {text}")
        except Exception as e:
            self._warn("line", e)

    def new_game(self, heroes: tuple[str, str]) -> None:
        """Separator header of a fresh game (also after Restart game)."""
        self._prev = None
        try:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock()))
            self._write(f"\n==== New game {when} | bot: {heroes[0]} vs human: {heroes[1]} ====")
        except Exception as e:
            self._warn("header", e)

    def resumed(self) -> None:
        self._prev = None
        self.line("---- Game resumed from the saved state ----")

    def chat(self, text: str) -> None:
        self.line(str(text))

    def observe(self, game, name: Callable) -> None:
        """Logs what changed in `game` since the previous call (the first call only takes the baseline)."""
        if self.path is None:
            return
        try:
            now = snapshot(game)
            prev, self._prev = self._prev, now
            if prev is not None:
                for text in changes(prev, now, game, name):
                    self.line(text)
        except Exception as e:
            self._warn("state changes", e)


def snapshot(game) -> dict:
    return {
        "turn": (game.turn_no, game.turn), "winner": game.winner, "draws": tuple(game.draw_events),
        "fighters": {fid: (f.pos, f.hp, f.alive) for fid, f in game.fighters.items()},
        "discard": [{c.card_id for c in p.discard} for p in game.players],
    }


def changes(prev: dict, now: dict, game, name: Callable) -> list[str]:
    out: list[str] = []
    if now["turn"] != prev["turn"]:
        n, who = now["turn"]
        out.append(f"TURN {n}: {game.hero_def(who).name} (P{who}) starts, {game.actions_left} actions")
    for fid, (pos, hp, alive) in now["fighters"].items():
        o_pos, o_hp, o_alive = prev["fighters"].get(fid, (pos, hp, alive))
        label = name(game.fighters[fid])
        if hp != o_hp:
            verb = "damage" if hp < o_hp else "healing"
            out.append(f"{verb.upper()}: {label} {o_hp:g} -> {hp:g} HP ({abs(hp - o_hp):g} {verb})")
        if alive != o_alive:
            out.append(f"{'REVIVED' if alive else 'DEFEATED'}: {label}")
        if pos != o_pos and pos is not None:
            out.append(f"MOVE: {label} {'off board' if o_pos is None else o_pos} -> {pos}")
    for p in (0, 1):
        # the engine's own draw events, not `Game.drawn`: the table deal resets that counter between two observations
        draws = now["draws"][p] - prev["draws"][p]
        if draws > 0:
            out.append(f"DRAW: P{p} draws {draws}")
        for card in game.players[p].discard:
            if card.card_id not in prev["discard"][p]:
                out.append(f"DISCARD: P{p} {card.title}")
    if now["winner"] is not None and now["winner"] != prev["winner"]:
        out.append(f"GAME OVER: {game.hero_def(now['winner']).name} (P{now['winner']}) wins")
    return out
