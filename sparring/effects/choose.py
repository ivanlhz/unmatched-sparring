"""Decisions inside effects: what is asked (ChoiceRequest) and who answers (Chooser).

An op never decides by itself: it builds a ChoiceRequest and the chooser of `req.player` answers, or pauses the
run with an Await. Answers are lists of option values (fighter ids, space ids, card ids, option indexes,
[True]/[False] for optional, [n] for amount); `[]` means "none" when `min` is 0.

PendingChoice / Await are the combat flow's (sparring/combat_flow.py): an effect pause is
`Await(PendingChoice(kind="effect", ..., extra={"key", "request"}))`."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

from ..combat_flow import Await, PendingChoice
from ..i18n import t
from ..state import RuleError

KINDS = ("fighter", "space", "cards", "effect", "optional", "order", "amount")


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
    extra: dict = field(default_factory=dict)   # bots: fighter, op, amount, steps, through, cost_cards, at_stake, hp
    card_owner: int | None = None   # whose deck `card_id` is from (a CardID alone is ambiguous: docs/card-identity.md)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "player": self.player, "options": list(self.options), "min": self.min,
                "max": self.max, "card_id": self.card_id, "key": self.key, "prompt": self.prompt,
                "extra": dict(self.extra), **({} if self.card_owner is None else {"card_owner": self.card_owner})}

    @classmethod
    def from_dict(cls, raw: dict) -> "ChoiceRequest":
        return cls(raw["kind"], raw["player"], list(raw["options"]), raw["min"], raw["max"], raw.get("card_id"),
                   raw.get("key", ""), raw.get("prompt", ""), dict(raw.get("extra") or {}), raw.get("card_owner"))

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
        return [not req.extra.get("pact")]      # a price in hit points (DARK PACT) is never paid without an opinion
    if req.kind == "amount":
        return [req.max]
    if req.kind == "space":
        return list(req.options[:req.min])
    if req.extra.get("purpose") in ("bonus", "swap_attack"):    # a free-count discard that adds value (Unbridled rage), a card played instead (Sleight Of Hand): none by default
        return []
    if req.min == req.max:
        return list(req.options[:req.min])
    return list(req.options[:req.max])


def worth_paying(req: ChoiceRequest) -> bool:
    """A bot's default for an optional that costs cards: pay only when the damage the decision swings (`at_stake`:
    avoided by the defender, unblocked by the attacker; `ops_core._cost_context`) is at least 3 per card, or when it
    decides a kill (`hp`). Without a combat in sight (no `at_stake`) it does not pay."""
    stake = req.extra.get("at_stake", 0)
    return stake >= 3 * req.extra["cost_cards"] or (stake > 0 and stake >= req.extra.get("hp", float("inf")))


class ControllerChooser:
    """The bot: `Controller.choose_effect`, falling back to choose_move / choose_discard / choose_placement."""

    def choose(self, game, req: ChoiceRequest) -> list:
        ctrl = game.controllers.get(req.player)
        if ctrl is None:
            return default_answer(req)
        if req.kind == "cards" and req.extra.get("zone") == "hand" and req.extra.get("of", req.player) != req.player:
            return self._from_rival_hand(game, req, req.extra["of"])    # the controller never sees these options
        answer = ctrl.choose_effect(game, req)
        if answer is not None:
            return answer
        if req.kind == "optional" and "cost_cards" in req.extra:
            return [worth_paying(req)]
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
        elif req.kind == "cards":
            picked = self._choose_cards(game, ctrl, req)
            if picked is not None:
                return picked
        return default_answer(req)

    def _choose_cards(self, game, ctrl, req: ChoiceRequest) -> list | None:
        zone, purpose = req.extra.get("zone"), req.extra.get("purpose")
        of = req.extra.get("of", req.player)
        if purpose == "bonus":
            return []
        if zone == "hand" and purpose in ("discard", "return"):       # the cards to give up are the least useful ones
            n = min(req.max, len(req.options))
            picked = [c.card_id for c in ctrl.choose_discard(game, req.player, n, req.prompt)
                      if c.card_id in req.options][:req.max]
            return picked if len(picked) >= req.min else None
        if of == req.player and zone in ("deck", "discard") and purpose in ("search", "return", "recover"):  # own piles
            from ..search.adapter import card_worth
            by_id = {c.card_id: c for c in game.players[of].full_set}
            ranked = sorted(req.options, key=lambda i: (-card_worth(by_id[i]), i))
            return ranked[:max(req.min, min(req.max, len(ranked)))]
        return None

    @staticmethod
    def _from_rival_hand(game, req: ChoiceRequest, of: int) -> list:
        """A choice among the RIVAL's hand cards. The bot only knows the ones its own `look_hand` showed it
        (`KnownHand`): it takes the most valuable of those, since that is what hurts the rival most. Anything it
        needs beyond what it has seen is picked by position, never by looking at identities."""
        from ..search.adapter import card_worth
        seen = {c.card_id: c for c in game.players[req.player].known.cards(game.players[of])}
        ranked = sorted((i for i in req.options if i in seen), key=lambda i: (-card_worth(seen[i]), i))
        picked = ranked[:max(req.min, min(req.max, len(ranked)))]
        blind = [i for i in req.options if i not in picked]
        short = req.min - len(picked)
        if short > 0:
            picked += [blind[k] for k in sorted(game.rng.sample(range(len(blind)), short))]
        return picked


class TableChooser:
    """The human, when the combat cannot stop and ask at the panel (the synchronous facade): every optional is
    declined, an optional pick is left empty, and a forced pick is refused - the engine never pays a cost or picks a
    card out of the human's hand for them; the table does that (E1/E2)."""

    def choose(self, game, req: ChoiceRequest) -> list:
        if req.kind == "optional":
            return [False]
        if req.extra.get("blind_count"):             # BLIND BOOST: no declaration without the panel, so none is made
            return [0]
        if req.extra.get("confirm"):                 # Take A Knee: the one option is the effect itself
            return list(req.options)
        if req.min == 0:
            return []
        raise NotImplementedError(f"{req.prompt or req.kind}: a forced choice of the human needs the panel (E1)")


MAX_BOOST = 3             # the highest BOOST value a deck card carries: a blind boost may add this much
PACT_SAFE_HP = 8          # a rollout pays DARK PACT only while the hero keeps at least this many hit points
SCHEME_VARIANTS = ("greedy", "safe")    # the two lines the search tries for a scheme that asks something (D2)
HIT_OPS = ("damage", "set_hp")
RELOCATE_OPS = ("move", "place", "swap", "revive", "summon")
GIVE_UP = ("discard", "return", "reveal")


class SyntheticChooser:
    """Search and rollouts: no controller, no table. `policy="first"` is deterministic; `"random"` draws from its
    own `rng` (never the game's, so the search does not disturb the real shuffle). `"greedy"` and `"safe"` (D2) are
    the two lines the search enumerates for a scheme, cheap and deterministic, each from the point of view of the
    player who answers: greedy brings pieces closer to combat (own piece towards a strike, a rival piece within
    reach), pays costs and takes the first options; safe moves apart (own piece away, a rival piece out of reach),
    declines costs and takes the last options. Both hit the enemy that pays most, heal who needs it most, give up
    the cheapest cards and take the best. It sees only what the game it is given holds: in the search that game is
    determinized, so a rival hand it ranks is the sampled one, never the real one."""

    def __init__(self, rng: random.Random | None = None, policy: str = "first"):
        if policy not in ("first", "random", *SCHEME_VARIANTS):
            raise ValueError(f"unknown policy {policy!r}")
        self.rng, self.policy = rng or random.Random(0), policy

    def choose(self, game, req: ChoiceRequest) -> list:
        if self.policy == "first":
            return default_answer(req)
        if self.policy == "random":
            if req.kind in ("optional", "amount"):
                return default_answer(req)
            n = self.rng.randint(req.min, min(req.max, len(req.options)))
            return self.rng.sample(list(req.options), n)
        answer = getattr(self, f"_{req.kind}")(game, req)
        return default_answer(req) if answer is None else answer

    @property
    def greedy(self) -> bool:
        return self.policy == "greedy"

    def _optional(self, game, req: ChoiceRequest) -> list:
        if "pact" in req.extra:                      # DARK PACT in a rollout: while the hero can spare the hit points
            pact = req.extra["pact"]
            hero = game.fighters[pact["fighter"]]
            return [self.greedy and hero.hp - pact["damage"] >= PACT_SAFE_HP]
        return [self.greedy or "cost_cards" not in req.extra]

    def _amount(self, game, req: ChoiceRequest) -> list:
        if req.extra.get("blind_count"):             # BLIND BOOST: as many as cannot push a card that ignores a value above its limit over it
            limit = req.extra.get("limit")
            safe = [n for n in req.options if limit is None or req.extra["value"] + n * MAX_BOOST <= limit]
            return [max(safe, default=min(req.options))]
        top = max(req.options)
        if req.extra.get("zone") in (None, "deck"):            # a draw: never into exhaustion
            top = max(min(req.options), min(top, len(game.players[req.player].deck)))
        return [top]

    def _effect(self, game, req: ChoiceRequest) -> list:
        """The options that do something first (`_option_worth`); among equals greedy takes the first printed, safe the
        last. Taking the first two options blindly played Pancakes! as heal + a return of nothing."""
        from ..ai_effects import EffectAI
        n = min(req.max, len(req.options))
        found = EffectAI._locate(game, req)
        options = found[0].get("options") or [] if found else []
        worth = {k: self._option_worth(game, req.player, options[k]) if k < len(options) else 1 for k in req.options}
        sign = 1 if self.greedy else -1
        return sorted(req.options, key=lambda k: (-worth[k], sign * k))[:n]

    @staticmethod
    def _option_worth(game, me: int, option: dict) -> int:
        """0 when the option would change nothing now (a heal at full health, a draw from an empty deck, a return with
        nothing to return), 3 for a draw, 2 for a heal, 1 for anything else."""
        mine = game.players[me]
        for o in option.get("ops", []):
            kind = o["op"]
            if kind == "draw":
                return 3 if mine.deck else 0
            if kind == "heal":
                return 2 if any(f.hp < f.max_hp for f in game.own(me)) else 0
            if kind == "return_to_deck":
                sel = o["cards"]
                pile = mine.discard if sel.get("zone") == "discard" else mine.hand
                banned = sel.get("filter", {}).get("type_not")
                return 1 if any(c.type != banned for c in pile) else 0
        return 1

    def _fighter(self, game, req: ChoiceRequest) -> list | None:
        me, op = req.player, req.extra.get("op")
        cands = [game.fighters[i] for i in req.options if i in game.fighters]
        if not cands:
            return None
        foes, mine = [f for f in cands if f.owner != me], [f for f in cands if f.owner == me]
        if op in HIT_OPS:
            n = req.extra.get("amount")
            dmg = n if op == "damage" and isinstance(n, (int, float)) else 1
            if foes:            # a kill first, then the hero, then the weakest
                return [min(foes, key=lambda f: (f.hp > dmg, not f.hero, f.hp, f.fid)).fid]
            if req.min == 0:
                return []
            return [max(mine, key=lambda f: (not f.hero, f.hp, f.fid)).fid]      # the own piece that loses least
        if op == "heal":
            pool = mine or cands
            return [max(pool, key=lambda f: (f.max_hp - f.hp, f.hero, f.fid)).fid]
        if op in RELOCATE_OPS:
            pool = (mine or foes) if self.greedy else (foes or mine)
            return [min(pool, key=lambda f: (not f.hero, f.fid)).fid]
        return None

    def _space(self, game, req: ChoiceRequest) -> list | None:
        f = game.fighters.get(req.extra.get("fighter"))
        if f is None:
            return None
        me, board = req.player, game.board
        options = list(req.options)
        foes = [e for e in game.own(1 - me) if e is not f]
        hero = game.hero(me)
        if not foes:
            return None
        if f.owner == me:
            near = lambda s: min(board.distance(s, e.pos) for e in foes)
            strikes_from = lambda s: any(board.can_reach_target(s, e.pos, f.ranged, f.reach) for e in foes)
            may_stay = req.min == 0 and f.pos is not None
            if self.greedy:
                strikes = [s for s in options if strikes_from(s)]
                if strikes:
                    return [] if may_stay and strikes_from(f.pos) else [min(strikes, key=lambda s: (near(s), s))]
                best = min(options, key=lambda s: (near(s), s))
                return [] if may_stay and near(f.pos) <= near(best) else [best]
            away = lambda s: min(board.distance(e.pos, s) for e in foes)      # fleeing: it is the foe that walks to s
            best = max(options, key=lambda s: (away(s), -s))
            return [] if may_stay and away(f.pos) >= away(best) else [best]
        ref = hero.pos if hero.alive and hero.pos is not None else None
        if ref is None:
            return None
        if self.greedy:         # a rival piece where the own hero strikes it
            within = [s for s in options if board.can_reach_target(ref, s, hero.ranged, hero.reach)]
            return [min(within or options, key=lambda s: (board.distance(ref, s), s))]
        return [max(options, key=lambda s: (board.distance(s, ref), -s))]       # away from the hero: the piece walks s -> hero

    def _cards(self, game, req: ChoiceRequest) -> list:
        from ..search.adapter import card_worth
        of = req.extra.get("of", req.player)
        if req.extra.get("zone") == "hand" and of != req.player:     # only what a look showed (C4), as every bot
            return ControllerChooser._from_rival_hand(game, req, of)
        if req.extra.get("purpose") in ("bonus", "swap_attack"):
            return []
        cards = game.cards_by_id(of)
        worth = lambda i: card_worth(cards[i]) if i in cards else 0.0
        n = min(req.max, len(req.options))
        if req.extra.get("purpose") == "return" and req.extra.get("zone") == "discard" and of == req.player:
            # own discard cards back into the deck: a gain, at least one when it may be more (Pancakes!); destiny
            # cards last, they are what keeps Hellboy ANUNG UN RAMA
            return sorted(req.options, key=lambda i: (i in cards and cards[i].destiny, -worth(i), i))[:n]
        if req.extra.get("purpose") == "remove":                      # out of the own discard pile: as many as allowed, the cheapest
            return sorted(req.options, key=lambda i: (worth(i), i))[:n]
        if req.extra.get("purpose") in GIVE_UP:
            return sorted(req.options, key=lambda i: (worth(i), i))[:req.min]
        return sorted(req.options, key=lambda i: (-worth(i), i))[:n]

    def _order(self, game, req: ChoiceRequest) -> list:
        from ..search.adapter import card_worth
        cards = game.cards_by_id(req.extra.get("of", req.player))
        if set(req.options) <= set(cards):
            return sorted(req.options, key=lambda i: (-card_worth(cards[i]), i))
        return list(req.options)


class PresetChooser:
    """Answers the engine's caller decided up front (the AI's planned target, the search's enumerated move):
    `by_kind` maps a request kind to the answer of the FIRST request of that kind; it is used once, so a card that
    picks twice (B.P.R.D. Utility Belt: heal one, move one) asks `inner` for the second pick instead of repeating
    the preset. Anything else goes to `inner`. A preset that is not among the options is a RuleError: the caller
    asked for something the effect does not allow."""

    def __init__(self, inner: Chooser, by_kind: dict[str, list]):
        self.inner, self.by_kind = inner, dict(by_kind)

    def choose(self, game, req: ChoiceRequest) -> list | Await:
        if req.kind not in self.by_kind:
            return self.inner.choose(game, req)
        answer = list(self.by_kind.pop(req.kind))
        if not all(a in req.options for a in answer):
            raise RuleError(t("err.not_option", prompt=req.prompt or req.kind, answer=repr(answer), options=repr(req.options)))
        return answer


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
