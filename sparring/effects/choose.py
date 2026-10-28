"""Decisions inside effects: what is asked (ChoiceRequest) and who answers (Chooser).

An op never decides by itself: it builds a ChoiceRequest and the chooser of `req.player` answers, or pauses the
run with an Await. Answers are lists of option values (fighter ids, space ids, card ids, option indexes,
[True]/[False] for optional, [n] for amount); `[]` means "none" when `min` is 0.

PendingChoice / Await mirror the types of sparring/combat_flow.py (same field names and (de)serialization) so the
effect runner can return `Await(PendingChoice(kind="effect", ...))` through the combat flow. They are unified with
combat_flow's classes when both branches merge; until then this module owns a compatible copy."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Protocol

KINDS = ("fighter", "space", "cards", "effect", "optional", "order", "amount")


@dataclass
class PendingChoice:
    kind: str                 # "boost" (combat flow) or "effect" (this package)
    player: int               # who decides
    card_id: int | None       # card whose effect asks
    deck: bool = False        # Flame Lash: the boost is the bottom card of the deck
    extra: dict = field(default_factory=dict)     # caller-owned JSON-safe data

    def to_dict(self) -> dict:
        return {"kind": self.kind, "player": self.player, "card": self.card_id, "deck": self.deck, **self.extra}

    @classmethod
    def from_dict(cls, raw: dict, *, default_player: int, deck_of: Callable[[int], bool]) -> "PendingChoice":
        card = raw["card"]
        extra = {k: v for k, v in raw.items() if k not in ("kind", "player", "card", "deck")}
        return cls(raw.get("kind", "effect"), raw.get("player", default_player), card,
                   raw.get("deck", False if card is None else deck_of(card)), extra)


@dataclass(frozen=True)
class Await:
    choice: PendingChoice


@dataclass
class ChoiceRequest:
    kind: str                       # one of KINDS
    player: int                     # who answers
    options: list                   # JSON-safe values the answer is made of
    min: int = 1
    max: int = 1
    card_id: int | None = None      # the card whose effect asks
    key: str = ""                   # op path + ask index: where the answer is stored
    prompt: str = ""
    extra: dict = field(default_factory=dict)     # context for bots (fighter, op, steps, through, reason)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "player": self.player, "options": list(self.options), "min": self.min,
                "max": self.max, "card_id": self.card_id, "key": self.key, "prompt": self.prompt,
                "extra": dict(self.extra)}

    @classmethod
    def from_dict(cls, raw: dict) -> "ChoiceRequest":
        return cls(raw["kind"], raw["player"], list(raw["options"]), raw["min"], raw["max"], raw.get("card_id"),
                   raw.get("key", ""), raw.get("prompt", ""), dict(raw.get("extra") or {}))

    def to_await(self) -> Await:
        return Await(PendingChoice("effect", self.player, self.card_id, False,
                                   {"key": self.key, "request": self.to_dict()}))

    def validate(self, answer: list) -> list:
        """The answer as a clean list, or ValueError if it is not a legal answer to this request."""
        if not isinstance(answer, (list, tuple)):
            raise ValueError(f"{self.key}: answer must be a list, got {answer!r}")
        answer = list(answer)
        if not self.min <= len(answer) <= self.max:
            raise ValueError(f"{self.key}: expected {self.min}..{self.max} values, got {len(answer)}")
        if len(set(map(repr, answer))) != len(answer):
            raise ValueError(f"{self.key}: repeated values in {answer!r}")
        for a in answer:
            if a not in self.options:
                raise ValueError(f"{self.key}: {a!r} is not one of {self.options!r}")
        return answer


class Suspend(Exception):
    """Raised by EffectRun.ask when a chooser pauses the run; nothing has been mutated yet."""

    def __init__(self, request: ChoiceRequest, pause: Await):
        super().__init__(request.key)
        self.request, self.pause = request, pause


class Chooser(Protocol):
    def choose(self, game, req: ChoiceRequest) -> list | Await: ...


def default_answer(req: ChoiceRequest) -> list:
    """The neutral answer: forced picks are taken, optional is accepted, an amount is the maximum, an optional
    move or placement stays put."""
    if req.kind == "optional":
        return [True]
    if req.kind == "amount":
        return [req.max]
    if req.kind == "space":
        return list(req.options[:req.min])
    if req.min == req.max:
        return list(req.options[:req.min])
    return list(req.options[:req.max])


class ControllerChooser:
    """The bot: `Controller.choose_effect`, falling back to choose_move / choose_discard / choose_placement."""

    def choose(self, game, req: ChoiceRequest) -> list:
        ctrl = game.controllers.get(req.player)
        if ctrl is None:
            return default_answer(req)
        answer = ctrl.choose_effect(game, req)
        if answer is not None:
            return answer
        if req.kind == "space":
            fighter = game.fighters.get(req.extra.get("fighter"))
            if fighter is not None:
                if req.extra.get("op") == "move":
                    dest = ctrl.choose_move(game, fighter, req.extra["steps"], req.extra.get("through", False))
                else:
                    dest = ctrl.choose_placement(game, fighter, list(req.options))
                if dest in req.options:
                    return [dest]
                if req.min == 0:
                    return []
        elif req.kind == "cards" and req.extra.get("zone") == "hand" and req.extra.get("purpose") == "discard":
            n = min(req.max, len(req.options))
            picked = [c.card_id for c in ctrl.choose_discard(game, req.player, n, req.prompt)
                      if c.card_id in req.options][:req.max]
            if len(picked) >= req.min:
                return picked
        return default_answer(req)


class SyntheticChooser:
    """Search and rollouts: no controller, no table. `policy="first"` is deterministic; `"random"` draws from its
    own `rng` (never the game's, so the search does not disturb the real shuffle)."""

    def __init__(self, rng: random.Random | None = None, policy: str = "first"):
        if policy not in ("first", "random"):
            raise ValueError(f"unknown policy {policy!r}")
        self.rng, self.policy = rng or random.Random(0), policy

    def choose(self, game, req: ChoiceRequest) -> list:
        if self.policy == "first" or req.kind in ("optional", "amount"):
            return default_answer(req)
        n = self.rng.randint(req.min, min(req.max, len(req.options)))
        return self.rng.sample(list(req.options), n)


class PanelChooser:
    """The human at the panel: always pauses; the answer arrives through EffectRun.resume."""

    def choose(self, game, req: ChoiceRequest) -> Await:
        return req.to_await()


class ScriptedChooser:
    """Tests: answers by key (`by_key`) or in order (`queue`); anything else gets the default answer. Every request
    seen is kept in `requests`."""

    def __init__(self, queue: list | None = None, by_key: dict | None = None):
        self.queue, self.by_key = list(queue or ()), dict(by_key or {})
        self.requests: list[ChoiceRequest] = []

    def choose(self, game, req: ChoiceRequest) -> list:
        self.requests.append(req)
        if req.key in self.by_key:
            return self.by_key[req.key]
        if self.queue:
            return self.queue.pop(0)
        return default_answer(req)
