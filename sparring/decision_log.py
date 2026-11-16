"""Decision journal: one JSON line per bot decision (turn plan and defence) in `decisions.jsonl`, next to `session.log`.

Each decision line says which AI decided (heuristic or ISMCTS, with its budget), the size of both players' hands, decks and
discards, the rival's cards known in hand, every alternative the AI weighed (visits and mean value for the search, score for
the heuristic), what it chose and whether the heuristic fallback decided. When the decision has resolved (the next decision,
the turn change or the end of the game) a linked `outcome` line says what really happened: damage dealt and taken, cards
spent, what the rival played in public and the evaluation of the position, to compare with what the bot expected.

This only observes: nothing here feeds back into a decision. Writing never breaks the game: an I/O or encoding error is
warned about once and the game goes on."""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Callable

JOURNAL_NAME = "decisions.jsonl"
TOP_ALTERNATIVES = 12


def decisions_path(state_path: Path | None) -> Path | None:
    """Same folder as the state file and the game log (so the launcher's %LOCALAPPDATA% folder too)."""
    return None if state_path is None else Path(state_path).with_name(JOURNAL_NAME)


def ai_info(ai) -> dict:
    """Which AI is playing and with what budget. The ISMCTS controller carries its `SearchConfig`."""
    config = getattr(ai, "config", None)
    if config is None:
        return {"ai": "heuristic"}
    return {"ai": "ismcts", "time_budget": config.time_budget, "iterations_cap": config.iterations, "seed": config.seed}


def ai_label(ai) -> str:
    """The same, as the short text of the game header in session.log."""
    info = ai_info(ai)
    if info["ai"] == "heuristic":
        return "heuristic"
    cap = "" if info["iterations_cap"] is None else f", max {info['iterations_cap']} iterations"
    return f"ismcts ({info['time_budget']:g} s per decision{cap})"


def describe_act(act) -> dict:
    out: dict = {"kind": act.kind}
    for key in ("fid", "target", "variant"):
        if getattr(act, key, None):
            out[key] = getattr(act, key)
    for key in ("card", "boost"):
        card = getattr(act, key, None)
        if card is not None:
            out[key] = card.title
    if act.moves:
        out["moves"] = dict(act.moves)
    if act.spot is not None:
        out["spot"] = act.spot
    return out


def _side(game, p: int) -> dict:
    st = game.players[p]
    return {"hand": len(st.hand), "deck": len(st.deck), "discard": len(st.discard), "hero_hp": game.hero(p).hp}


def _snapshot(game, me: int) -> dict:
    rival = 1 - me
    hp = {p: sum(max(0, f.hp) for f in game.fighters.values() if f.owner == p) for p in (0, 1)}
    return {"turn": (game.turn_no, game.turn), "hp": hp, "hero_hp": {p: game.hero(p).hp for p in (0, 1)},
            "discard": {p: [c.title for c in game.players[p].discard] for p in (0, 1)},
            "hand": {p: len(game.players[p].hand) for p in (0, 1)}, "rival": rival}


def _added(before: list[str], after: list[str]) -> list[str]:
    """Titles that entered a discard pile between two snapshots (a pile that was shuffled back shows as everything new)."""
    if len(after) >= len(before) and after[:len(before)] == before:
        return after[len(before):]
    return list(after)


def _evaluation(game, me: int) -> float | None:
    """The search's evaluation of the position for `me`, on the same [0, 1] scale as the mean values of the alternatives."""
    from .search.adapter import EngineState, EvalWeights, Knowledge, hero_weights
    weights = hero_weights(EvalWeights(), game.players[me].hero.slug)
    state = EngineState(game, observer=me, knowledge=Knowledge.from_game(game, me), weights=weights)
    return round(state.evaluate(me), 4)


class DecisionJournal:
    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time):
        self.path = path
        self.clock = clock
        self.game_id: str | None = None
        self.seq = 0
        self._warned = False
        self._pending: dict | None = None

    def _warn(self, what: str, error: BaseException) -> None:
        if not self._warned:
            self._warned = True
            print(f"[warning] decision journal disabled for this problem ({what}): {error!r}", file=sys.stderr)

    def _write(self, record: dict) -> None:
        if self.path is None:
            return
        try:
            with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:                          # the journal must never break the game
            self._warn(f"cannot write {self.path}", e)

    def new_game(self, game, bot: int, ai, game_id: str | None = None) -> None:
        """Header of a fresh game: it names the AI and its budget. Closes the outcome of the previous game's last decision."""
        try:
            self._pending = None
            self.seq = 0
            when = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.clock()))
            self.game_id = game_id or f"{when}-{uuid.uuid4().hex[:4]}"
            self._write({"t": "game", "game": self.game_id, "when": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock())),
                         "bot": bot, "bot_hero": game.hero_def(bot).name, "rival_hero": game.hero_def(1 - bot).name,
                         **ai_info(ai)})
        except Exception as e:
            self._warn("game header", e)

    def decision(self, game, me: int, kind: str, ai, chosen, alternatives: list[dict], *, iterations: int | None = None,
                 elapsed: float | None = None, fallback: bool = False, error: str | None = None, expected: float | None = None) -> None:
        """One line per decision. `alternatives`: dicts with `move` and `visits`/`value`/`score`; `expected`: the chosen
        move's own value, to compare with the outcome."""
        try:
            self.settle(game, force=True)
            if self.game_id is None:
                self.new_game(game, me, ai)
            self.seq += 1
            rival = 1 - me
            known = [c.title for c in game.players[me].known.cards(game.players[rival])]
            record = {"t": "decision", "game": self.game_id, "seq": self.seq, "turn": game.turn_no, "player": me, "kind": kind,
                      **ai_info(ai), "iterations": iterations, "elapsed": None if elapsed is None else round(elapsed, 3),
                      "actions_left": game.actions_left, "own": _side(game, me), "rival": _side(game, rival),
                      "rival_known_in_hand": known, "alternatives": alternatives[:TOP_ALTERNATIVES], "chosen": chosen,
                      "expected": None if expected is None else round(expected, 4), "fallback": fallback}
            if error:
                record["error"] = error
            self._write(record)
            self._pending = {"seq": self.seq, "me": me, "kind": kind, "expected": record["expected"], "before": _snapshot(game, me)}
        except Exception as e:
            self._warn("decision", e)

    def settle(self, game, force: bool = False) -> None:
        """Writes the outcome of the last decision once it resolved: forced by the next decision, or on its own when the
        turn changed or the game ended."""
        pending = self._pending
        if pending is None:
            return
        try:
            before = pending["before"]
            if not force and game.winner is None and (game.turn_no, game.turn) == before["turn"]:
                return
            self._pending = None
            me, rival = pending["me"], 1 - pending["me"]
            now = _snapshot(game, me)
            try:
                value = _evaluation(game, me) if game.winner is None else (1.0 if game.winner == me else 0.0)
            except Exception as e:                  # an evaluation that cannot be computed leaves the rest of the line
                value = None
                self._warn("evaluation", e)
            self._write({"t": "outcome", "game": self.game_id, "seq": pending["seq"], "turn": before["turn"][0], "kind": pending["kind"],
                         "damage_dealt": max(0, before["hp"][rival] - now["hp"][rival]),
                         "damage_taken": max(0, before["hp"][me] - now["hp"][me]),
                         "own_cards_spent": _added(before["discard"][me], now["discard"][me]),
                         "rival_cards_played": _added(before["discard"][rival], now["discard"][rival]),
                         "hand_after": {"own": now["hand"][me], "rival": now["hand"][rival]},
                         "expected": pending["expected"], "evaluation_after": value,
                         "winner": game.winner})
        except Exception as e:
            self._warn("outcome", e)


def emit(ai, game, kind: str, chosen, alternatives: list[dict], **extra) -> None:
    """Called by an AI after it decided; does nothing unless a journal is attached (`ai.journal`)."""
    journal = getattr(ai, "journal", None)
    if journal is not None:
        journal.decision(game, ai.me, kind, ai, chosen, alternatives, **extra)
