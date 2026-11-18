"""Decision journal: one JSON line per bot decision (turn plan and defence) in `decisions.jsonl`, next to `session.log`.

Each decision line says which AI decided (heuristic or ISMCTS, with its budget), the size of both players' hands, decks and
discards, the rival's cards known in hand, every alternative the AI weighed (visits and mean value for the search, score for
the heuristic), what it chose and whether the heuristic fallback decided. When the decision has resolved (the next decision,
the turn change or the end of the game) a linked `outcome` line says what really happened: damage dealt and taken, cards
spent, what the rival played in public and the evaluation of the position, to compare with what the bot expected.

This only observes: nothing here feeds back into a decision, and nothing is computed unless a journal is attached. Writing
never breaks the game: any error, also while building a line, is warned about once on stderr and the game goes on."""
from __future__ import annotations

import json
import sys
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Callable

JOURNAL_NAME = "decisions.jsonl"
MAX_ALTERNATIVES = 60        # a longer list is cut to this many (best first) plus the chosen one; `alternatives_total` says so


def decisions_path(state_path: Path | None) -> Path | None:
    """Same folder as the state file and the game log (so the launcher's %LOCALAPPDATA% folder too)."""
    return None if state_path is None else Path(state_path).with_name(JOURNAL_NAME)


def eval_label(weights) -> str:
    """`new` (the evaluation of F-AI-EVAL-RESOLUTION, `RESOLUTION`), `old` (the default weights) or `custom`."""
    from .search.adapter import RESOLUTION, EvalWeights
    if weights == EvalWeights(**RESOLUTION):
        return "new"
    return "old" if weights == EvalWeights() else "custom"


def ai_info(ai) -> dict:
    """Which AI is playing and with what budget. The ISMCTS controller carries its `SearchConfig`."""
    config = getattr(ai, "config", None)
    if config is None:
        return {"ai": "heuristic"}
    return {"ai": "ismcts", "time_budget": config.time_budget, "iterations_cap": config.iterations, "seed": config.seed,
            "eval": eval_label(ai.weights)}


def ai_label(ai) -> str:
    """The same, as the short text of the game header in session.log."""
    info = ai_info(ai)
    if info["ai"] == "heuristic":
        return "heuristic"
    cap = "" if info["iterations_cap"] is None else f", max {info['iterations_cap']} iterations"
    return f"ismcts ({info['time_budget']:g} s per decision{cap}, eval={info['eval']})"


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


def played_titles(chosen) -> list[str]:
    """The cards the decision itself puts into play (an attack or scheme card, a boost, a defence card)."""
    if not isinstance(chosen, dict):
        return []
    return [chosen[k] for k in ("card", "boost") if isinstance(chosen.get(k), str)]


def _side(game, p: int) -> dict:
    st = game.players[p]
    return {"hand": len(st.hand), "deck": len(st.deck), "discard": len(st.discard), "hero_hp": game.hero(p).hp,
            "fighters": {f.fid: max(0, f.hp) if f.alive else 0 for f in game.own(p, alive_only=False)}}      # a team's hero is whoever stands: every fighter's own HP (0 once fallen)


def _snapshot(game) -> dict:
    return {"turn": (game.turn_no, game.turn),
            "hp": {p: sum(max(0, f.hp) for f in game.fighters.values() if f.owner == p) for p in (0, 1)},
            "discard": {p: [(c.card_id, c.title) for c in game.players[p].discard] for p in (0, 1)},
            "deck": {p: [c.card_id for c in game.players[p].deck] for p in (0, 1)},
            "hand": {p: len(game.players[p].hand) for p in (0, 1)}}


def _entered_discard(before: list, after: list) -> list:
    """Cards that entered a discard pile between two snapshots (a pile that was shuffled back shows as everything new)."""
    if len(after) >= len(before) and after[:len(before)] == before:
        return after[len(before):]
    return list(after)


def _split(before: dict, now: dict, p: int) -> tuple[list[str], list[str]]:
    """(played or discarded from the hand, taken off the bottom of the own deck by Wildfire or Flame Lash). The bottom cards
    are the run of cards that were at the end of the deck before and entered the discard; several in one window are told apart."""
    entered = _entered_discard(before["discard"][p], now["discard"][p])
    ids = {card_id for card_id, _ in entered}
    run = 0
    while run < len(before["deck"][p]) and before["deck"][p][-1 - run] in ids:
        run += 1
    from_bottom = set(before["deck"][p][len(before["deck"][p]) - run:])
    hand, bottom = [], []
    for card_id, title in entered:
        (bottom if card_id in from_bottom else hand).append(title)
    return hand, bottom


def _with_played(entered: list[str], played: list[str]) -> list[str]:
    """The discard pile misses a card that stays in play (an ONGOING scheme): add what the decision played and is not there."""
    missing = Counter(played) - Counter(entered)
    return entered + list(missing.elements())


def _evaluation(game, me: int, weights=None, explicit: frozenset = frozenset()) -> float | None:
    """The search's evaluation of the position for `me`, on the same [0, 1] scale as the mean values of the alternatives,
    with the weights the deciding controller used."""
    from .search.adapter import EngineState, EvalWeights, Knowledge, hero_weights
    weights = hero_weights(weights or EvalWeights(), game.players[me].hero.slug, explicit)
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
        """One notice per journal: the next lines are still tried (a locked file may free up) but not announced again."""
        if not self._warned:
            self._warned = True
            print(f"[warning] decision journal problem ({what}): {error!r}; the game goes on, later lines are still tried", file=sys.stderr)

    def _write(self, record: dict) -> None:
        if self.path is None:
            return
        try:
            with open(self.path, "a", encoding="utf-8", errors="replace") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except Exception as e:                          # the journal must never break the game
            self._warn(f"cannot write {self.path}", e)

    def _stamp(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.clock()))

    def new_game(self, game, bot: int, ai, game_id: str | None = None, resumed: bool = False) -> None:
        """Header of a fresh game: it names the AI and its budget. The outcome still pending of the previous game is dropped."""
        try:
            self._pending = None
            self.seq = 0
            when = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.clock()))
            self.game_id = game_id or f"{when}-{uuid.uuid4().hex[:4]}"
            self._write({"t": "game", "game": self.game_id, "when": self._stamp(), "bot": bot, "bot_hero": game.hero_def(bot).name,
                         "rival_hero": game.hero_def(1 - bot).name, **({"resumed": True} if resumed else {}), **ai_info(ai)})
        except Exception as e:
            self._warn("game header", e)

    def resume(self, game, bot: int, ai) -> None:
        """The game goes on from a saved state: the same id and numbering when this process already journaled it, else
        a header of a new id marked `resumed` (the id is not saved with the game)."""
        if self.game_id is None:
            self.new_game(game, bot, ai, resumed=True)
            return
        try:
            self._write({"t": "resume", "game": self.game_id, "when": self._stamp(), "seq": self.seq, **ai_info(ai)})
        except Exception as e:
            self._warn("resume line", e)

    def decision(self, game, me: int, kind: str, ai, chosen, alternatives: list[dict], *, iterations: int | None = None,
                 elapsed: float | None = None, fallback: bool = False, error: str | None = None, expected: float | None = None, via: str | None = None, plans: dict | None = None) -> None:
        """One line per decision. `alternatives`: dicts with `move` and `visits`/`value`/`score`, the chosen one flagged
        `chosen`; `expected`: the chosen move's own value, to compare with the outcome;
        `via`: how the heuristic chose (ranked, lethal or two_actions), which says on what scale the scores are."""
        try:
            self.settle(game, force=True)
            if self.game_id is None:
                self.new_game(game, me, ai)
            self.seq += 1
            rival = 1 - me
            known = [c.title for c in game.players[me].known.cards(game.players[rival])]
            kept = alternatives
            if len(alternatives) > MAX_ALTERNATIVES:
                kept = alternatives[:MAX_ALTERNATIVES] + [a for a in alternatives[MAX_ALTERNATIVES:] if a.get("chosen")]
            record = {"t": "decision", "game": self.game_id, "seq": self.seq, "turn": game.turn_no, "player": me, "kind": kind,
                      **ai_info(ai), "iterations": iterations, "elapsed": None if elapsed is None else round(elapsed, 3),
                      "actions_left": game.actions_left, "own": _side(game, me), "rival": _side(game, rival),
                      "rival_known_in_hand": known, "alternatives_total": len(alternatives), "alternatives": kept, "chosen": chosen,
                      "expected": None if expected is None else round(expected, 4), "fallback": fallback}
            if via:
                record["via"] = via
            if error:
                record["error"] = error
            if plans:
                record["plans"] = plans
            self._write(record)
            self._pending = {"seq": self.seq, "me": me, "kind": kind, "expected": record["expected"], "before": _snapshot(game),
                             "played": played_titles(chosen), "weights": getattr(ai, "weights", None),
                             "explicit": getattr(ai, "explicit", frozenset())}
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
            now = _snapshot(game)
            try:
                value = (_evaluation(game, me, pending["weights"], pending["explicit"]) if game.winner is None
                         else (1.0 if game.winner == me else 0.0))
            except Exception as e:                  # an evaluation that cannot be computed leaves the rest of the line
                value = None
                self._warn("evaluation", e)
            own, own_bottom = _split(before, now, me)
            theirs, their_bottom = _split(before, now, rival)
            self._write({"t": "outcome", "game": self.game_id, "seq": pending["seq"], "turn": before["turn"][0], "kind": pending["kind"],
                         "damage_dealt": max(0, before["hp"][rival] - now["hp"][rival]),
                         "damage_taken": max(0, before["hp"][me] - now["hp"][me]),
                         "own_cards_spent": _with_played(own, pending["played"]), "own_deck_bottom_discards": own_bottom,
                         "rival_cards_played": theirs, "rival_deck_bottom_discards": their_bottom,
                         "hand_after": {"own": now["hand"][me], "rival": now["hand"][rival]},
                         "expected": pending["expected"], "evaluation_after": value, "winner": game.winner})
        except Exception as e:
            self._warn("outcome", e)


def emit(ai, game, kind: str, build: Callable[[], dict]) -> None:
    """Called by an AI after it decided. Nothing is computed without a journal; `build` (which describes the act and lists
    the alternatives) runs inside the same protection as the write: a failure there is a warning, never a broken turn.
    It returns the keyword arguments of `DecisionJournal.decision` (`chosen`, `alternatives`, and optionally the rest)."""
    journal = getattr(ai, "journal", None)
    if journal is None:
        return
    try:
        parts = build()
        journal.decision(game, ai.me, kind, ai, parts.pop("chosen"), parts.pop("alternatives"), **parts)
    except Exception as e:
        journal._warn(f"building the {kind} line", e)
