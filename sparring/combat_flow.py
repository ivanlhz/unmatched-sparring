"""Combat as a serializable state machine. See docs/combat-flow.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .cards import Card
from .combat import (FEINT, ON_EARTH, PLANNED, SECOND_SHOT, CombatCtx, CombatResult, _announce_bot_card,
                     _check_boost, _hellboy_after, _liz_after, _medusa_after, _side_cards, after_text, can_boost,
                     deck_boost, is_medusa_card)
from .state import ANUNG, Fighter, Game, RuleError


class Phase(str, Enum):
    DECLARED = "declared"
    CARDS_SET = "cards_set"
    REVEALED = "revealed"
    IMMEDIATELY = "immediately"
    DURING = "during"
    DAMAGE = "damage"
    AFTER = "after"
    DONE = "done"


_RESERVED = {"kind", "player", "card", "deck"}


@dataclass
class PendingChoice:
    """A decision the flow is waiting for. The flat dict form is the save format of `Pending.boost_wait`."""
    kind: str                    # only "boost" in this delivery
    player: int                  # who decides
    card_id: int                 # card whose effect asks
    deck: bool = False           # Flame Lash: the boost is the bottom card of the deck
    extra: dict = field(default_factory=dict)    # caller-owned JSON-safe data (session: guid, baseline, hand, stuck)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "player": self.player, "card": self.card_id, "deck": self.deck, **self.extra}

    @classmethod
    def from_dict(cls, raw, *, default_player: int, deck_of: Callable[[int], bool]) -> "PendingChoice":
        """Also reads the old format (no "kind"/"player"): a boost of `default_player`, `deck` recomputed from the
        card. KeyError if the structure is invalid."""
        if not isinstance(raw, dict):
            raise KeyError("pending choice")
        kind, player, card = raw.get("kind", "boost"), raw.get("player", default_player), raw.get("card")
        if kind != "boost" or not _is_int(player) or not _is_int(card):
            raise KeyError("pending choice")
        deck = raw.get("deck") is True or deck_of(card)
        return cls(kind, player, card, deck, {k: v for k, v in raw.items() if k not in _RESERVED})


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


@dataclass(frozen=True)
class Await:
    choice: PendingChoice


@dataclass(frozen=True)
class Side:
    name: str                 # "def" | "atk"
    fighter: Fighter
    card: Card
    rival: Fighter


@dataclass(frozen=True)
class Rule:
    name: str
    phase: Phase
    side: str                 # "def" | "atk" | "any"
    match: Callable[["CombatFlow", Side], bool]
    run: Callable[["CombatFlow", Side], "Await | None"]
    when_cancelled: bool = False


RULES: list[Rule] = []
_SIDED = (Phase.IMMEDIATELY, Phase.DURING, Phase.AFTER)
_NEXT = dict(zip(Phase, list(Phase)[1:]))


def rule(phase: Phase, *, side: str = "any", when_cancelled: bool = False, match: Callable[["CombatFlow", Side], bool]):
    """Registers a phase handler. Per phase and side the first matching rule wins, in declaration order. A cancelled
    side is skipped unless the rule says `when_cancelled`."""
    def register(run):
        RULES.append(Rule(run.__name__, phase, side, match, run, when_cancelled))
        return run
    return register


class CombatFlow:
    """One combat advanced in small steps, so it can stop at a decision (`Await`) and be saved. Handlers return an
    `Await` BEFORE mutating anything; after `resume` the same handler runs again and finds its answer."""

    def __init__(self, game: Game, att: Fighter, tgt: Fighter, atk_card: Card, def_card: Card | None,
                 values: tuple[int, int] = (0, 0)):
        self.game, self.att, self.tgt = game, att, tgt
        self.atk_card, self.def_card, self.values = atk_card, def_card, tuple(values)
        self.phase, self.side_idx = Phase.DECLARED, 0
        self.ctx: CombatCtx | None = None
        self.result: CombatResult | None = None
        self.played: list[tuple[int, Card]] = []
        self.answers: dict[str, int | None] = {}     # "phase:side:rule" -> chosen card id (None: no card)
        self.pending: PendingChoice | None = None
        self.await_key: str | None = None
        self.after_open: bool | None = None          # decided once, on entering AFTER
        self.def_bonus_parts: list[tuple[int, str]] = []
        self.sides: list[Side] = []                  # resolution order: defender first

    @property
    def done(self) -> bool:
        return self.phase is Phase.DONE

    # ---------- advancing ----------
    def run(self) -> Await | None:
        while not self.done:
            if (wait := self.step()) is not None:
                return wait
        return None

    def drive(self, choose: Callable[[PendingChoice], Card | None]) -> None:
        """Run to the end, answering every decision with `choose` (the synchronous callers)."""
        while (wait := self.run()) is not None:
            self.resume(choose(wait.choice))

    def step(self) -> Await | None:
        """One unit of work: a phase hook, or the handler of the current side."""
        if self.done:
            return None
        if self.phase not in _SIDED:
            hook = _HOOKS.get(self.phase)
            if hook is not None:
                hook(self)
            self._enter(_NEXT[self.phase])
            return None
        if self.side_idx >= len(self.sides) or (self.phase is Phase.AFTER and not self.after_open):
            self._enter(_NEXT[self.phase])
            return None
        side = self.sides[self.side_idx]
        handler = self._handler(side)
        if handler is not None:
            self.await_key = f"{self.phase.value}:{side.name}:{handler.name}"
            if (wait := handler.run(self, side)) is not None:
                self.pending = wait.choice
                return wait
        self.side_idx += 1
        return None

    def _handler(self, side: Side) -> Rule | None:
        cancelled = side.name in self.ctx.cancelled
        for r in RULES:
            if r.phase is self.phase and r.side in ("any", side.name) and (r.when_cancelled or not cancelled) \
                    and r.match(self, side):
                return r
        return None

    def _enter(self, phase: Phase) -> None:
        self.phase, self.side_idx = phase, 0
        if phase is Phase.AFTER:
            self.after_open = self.game.winner is None
        elif phase is Phase.DONE:
            for owner, card in self.played:
                self.game.players[owner].discard.append(card)

    # ---------- decisions ----------
    def resume(self, choice: Card | None) -> None:
        self.answers[self.await_key] = None if choice is None else choice.card_id
        self.pending = None

    def answer(self, rule_name: str) -> tuple[bool, Card | None]:
        """(answered, card) for the decision the running handler asks; the key is phase:side:rule."""
        key = f"{self.phase.value}:{self.sides[self.side_idx].name}:{rule_name}"
        if key not in self.answers:
            return False, None
        card_id = self.answers[key]
        return True, None if card_id is None else self.card_by_id(card_id)

    def card_by_id(self, card_id: int) -> Card:
        for p in self.game.players:
            for c in p.full_set:
                if c.card_id == card_id:
                    return c
        raise KeyError(card_id)

    # ---------- engine hooks (code moved from combat.resolve_combat) ----------
    def _declare(self) -> None:
        game, tgt, def_card = self.game, self.tgt, self.def_card
        if def_card is not None:
            game.check_defense_card(tgt, def_card)
            if def_card not in game.players[tgt.owner].hand:
                raise RuleError(f"{def_card.title} no esta en la mano de {tgt.fid}")
        pa, pd = self.att.owner, tgt.owner
        game.take_from_hand(pa, self.atk_card)
        if def_card is not None:
            game.take_from_hand(pd, def_card)
        self.played = [(pa, self.atk_card)] + ([(pd, def_card)] if def_card else [])

    def _reveal(self) -> None:
        game, att, tgt, atk_card, def_card, values = self.game, self.att, self.tgt, self.atk_card, self.def_card, self.values
        bonus_parts = game.attack_bonus_parts(att)   # hero passives (Hellboy in ANUNG UN RAMA: +2)
        atk_value = (atk_card.value or 0) + values[0] + sum(n for n, _ in bonus_parts)
        def_value = (def_card.value or 0) if def_card else 0
        def_value += values[1]
        # the defender's ONGOING adds to its card value (even at 0 or cancelled); no card, no value to add to
        self.def_bonus_parts = game.combat_bonus_parts(tgt.owner) if def_card is not None else []
        def_value += self.def_bonus
        self.ctx = CombatCtx(att, tgt, atk_card, def_card, atk_value, def_value, set())
        self.result = CombatResult(att.fid, tgt.fid, atk_card, def_card, atk_value, def_value, 0, False)
        self.result.atk_parts = [f"{atk_card.title} ({atk_card.value or 0})"]
        self.result.atk_parts += [f"{label} (+{n})" for n, label in bonus_parts if n]
        if values[0]:
            self.result.atk_parts.append(f"valor extra ({values[0]:+d})")
        self.sides = [Side(*s) for s in _side_cards(self.ctx)]

    @property
    def def_bonus(self) -> int:
        return sum(n for n, _ in self.def_bonus_parts)

    def _damage(self) -> None:
        ctx, result, values = self.ctx, self.result, self.values
        if self.def_card is not None:
            result.def_parts = [f"{self.def_card.title} ({ctx.def_value - values[1] - self.def_bonus})"]
            if "def" in ctx.cancelled:
                result.def_parts[0] += " cancelada"
            result.def_parts += [f"{label} (+{n})" for n, label in self.def_bonus_parts if n]
        if values[1]:
            result.def_parts.append(f"valor extra ({values[1]:+d})")
        damage = max(0, ctx.atk_value - ctx.def_value)
        self.game.damage(self.tgt, damage, "combat")
        result.atk_value, result.def_value, result.damage, result.attacker_won = ctx.atk_value, ctx.def_value, damage, damage >= 1
        result.cancelled = set(ctx.cancelled)

    # ---------- serialization ----------
    def to_dict(self) -> dict:
        ctx, res = self.ctx, self.result
        return {
            "phase": self.phase.value, "side_idx": self.side_idx, "after_open": self.after_open,
            "values": list(self.values), "fids": [self.att.fid, self.tgt.fid],
            "atk_card": self.atk_card.card_id, "def_card": None if self.def_card is None else self.def_card.card_id,
            "played": [[owner, card.card_id] for owner, card in self.played],
            "def_bonus_parts": [[n, label] for n, label in self.def_bonus_parts],
            "answers": dict(self.answers), "await_key": self.await_key,
            "pending": None if self.pending is None else self.pending.to_dict(),
            "ctx": None if ctx is None else {"atk_value": ctx.atk_value, "def_value": ctx.def_value,
                                             "cancelled": sorted(ctx.cancelled)},
            "result": None if res is None else {
                "atk_value": res.atk_value, "def_value": res.def_value, "damage": res.damage,
                "attacker_won": res.attacker_won, "cancelled": sorted(res.cancelled),
                "boost_card": None if res.boost_card is None else res.boost_card.card_id,
                "atk_parts": list(res.atk_parts), "def_parts": list(res.def_parts), "applied": list(res.applied),
                "bot_notes": list(res.bot_notes), "human_effects": list(res.human_effects)},
        }

    @classmethod
    def from_dict(cls, game: Game, raw: dict) -> "CombatFlow":
        def card(card_id):
            return None if card_id is None else flow.card_by_id(card_id)
        att, tgt = (game.fighters[fid] for fid in raw["fids"])
        flow = cls.__new__(cls)
        flow.game, flow.att, flow.tgt, flow.values = game, att, tgt, tuple(raw["values"])
        flow.atk_card, flow.def_card = card(raw["atk_card"]), card(raw["def_card"])
        flow.phase, flow.side_idx, flow.after_open = Phase(raw["phase"]), raw["side_idx"], raw["after_open"]
        flow.played = [(owner, card(card_id)) for owner, card_id in raw["played"]]
        flow.def_bonus_parts = [(n, label) for n, label in raw["def_bonus_parts"]]
        flow.answers, flow.await_key = dict(raw["answers"]), raw["await_key"]
        flow.pending = None if raw["pending"] is None else PendingChoice.from_dict(
            raw["pending"], default_player=att.owner, deck_of=lambda _: False)
        flow.ctx = flow.result = None
        flow.sides = []
        if raw["ctx"] is not None:
            c, r = raw["ctx"], raw["result"]
            flow.ctx = CombatCtx(att, tgt, flow.atk_card, flow.def_card, c["atk_value"], c["def_value"],
                                 set(c["cancelled"]))
            flow.result = CombatResult(att.fid, tgt.fid, flow.atk_card, flow.def_card, r["atk_value"], r["def_value"],
                                       r["damage"], r["attacker_won"], set(r["cancelled"]), card(r["boost_card"]),
                                       list(r["human_effects"]), list(r["atk_parts"]), list(r["def_parts"]),
                                       list(r["applied"]), list(r["bot_notes"]))
            flow.sides = [Side(*s) for s in _side_cards(flow.ctx)]
        return flow


_HOOKS = {Phase.DECLARED: CombatFlow._declare, Phase.CARDS_SET: CombatFlow._reveal, Phase.DAMAGE: CombatFlow._damage}


# ---------- rules, in the order of the old if/elif chains ----------
def _is(card: Card, title: str, medusa: bool) -> bool:
    return card.title == title and is_medusa_card(card) == medusa


@rule(Phase.IMMEDIATELY, match=lambda flow, side: _is(side.card, FEINT, medusa=True))
def feint(flow: CombatFlow, side: Side) -> None:
    flow.ctx.cancelled.add(_other(side))


@rule(Phase.IMMEDIATELY, match=lambda flow, side: _is(side.card, PLANNED, medusa=False))
def planned_recklessness(flow: CombatFlow, side: Side) -> None:
    flow.game.effect_shield[side.fighter.owner] = flow.game.turn_no
    if flow.game.form(side.fighter.owner) != ANUNG:
        flow.ctx.cancelled.add(_other(side))


def _other(side: Side) -> str:
    return "atk" if side.name == "def" else "def"


@rule(Phase.DURING, side="def", when_cancelled=True, match=lambda flow, side: _is(side.card, ON_EARTH, medusa=False))
def on_earth_value(flow: CombatFlow, side: Side) -> None:
    base = flow.values[1] + flow.def_bonus
    flow.ctx.def_value = base if "def" in flow.ctx.cancelled else flow.game.destiny_count(side.fighter.owner) + base


def _add_boost(flow: CombatFlow, side: Side, boost: Card) -> None:
    flow.game.discard_card(side.fighter.owner, boost)
    flow.ctx.atk_value += boost.boost
    flow.result.boost_card = boost
    flow.result.atk_parts.append(f"potencia con {boost.title} (+{boost.boost})")


@rule(Phase.DURING, side="atk", match=lambda flow, side: _is(side.card, SECOND_SHOT, medusa=True))
def second_shot(flow: CombatFlow, side: Side) -> Await | None:
    answered, boost = flow.answer("second_shot")
    if not answered:
        return Await(PendingChoice("boost", side.fighter.owner, side.card.card_id))
    if boost is not None:
        _check_boost(boost)
        _add_boost(flow, side, boost)


@rule(Phase.DURING, side="atk", match=lambda flow, side: can_boost(side.card))
def boost_this_attack(flow: CombatFlow, side: Side) -> Await | None:
    answered, boost = flow.answer("boost_this_attack")
    if not answered:
        return Await(PendingChoice("boost", side.fighter.owner, side.card.card_id, deck_boost(side.card)))
    if boost is not None:
        if not deck_boost(side.card):          # Flame Lash: the bottom deck card adds whatever it is worth, even 0
            _check_boost(boost)
        _add_boost(flow, side, boost)


@rule(Phase.AFTER, match=lambda flow, side: is_medusa_card(side.card))
def medusa_after(flow: CombatFlow, side: Side) -> None:
    _medusa_after(flow.game, side.fighter, side.rival, side.card, _i_won(flow, side))


@rule(Phase.AFTER, match=lambda flow, side: side.fighter.owner == flow.game.bot_player)
def bot_card_after(flow: CombatFlow, side: Side) -> None:
    """Never ask the human to resolve an effect of the bot's card."""
    _hellboy_after(flow.game, side.fighter, side.card, _i_won(flow, side), flow.result)
    _liz_after(flow.game, side.card, flow.result)
    _announce_bot_card(side.card, flow.result)


@rule(Phase.AFTER, match=lambda flow, side: True)
def human_card_after(flow: CombatFlow, side: Side) -> None:
    card, result = side.card, flow.result
    if _hellboy_after(flow.game, side.fighter, card, _i_won(flow, side), result) or _liz_after(flow.game, card, result):
        return
    after = after_text(card)
    if after:
        result.human_effects.append(f"{card.title}: {after}")
    elif card.title == PLANNED:
        result.applied.append(f"{card.title}: aplicado ({card.text})")
    elif card.text.strip() and not can_boost(card):   # the BOOST of Second Shot was already resolved in DURING
        result.human_effects.append(f"{card.title}: {card.text}")
    # a card without text (Excalibur, Service Pistol) has no effect to resolve


def _i_won(flow: CombatFlow, side: Side) -> bool:
    return flow.result.attacker_won == (side.name == "atk")


# ---------- synchronous driver ----------
def legacy_chooser(game: Game, flow: CombatFlow, boost: Card | None) -> Callable[[PendingChoice], Card | None]:
    """Answers boost choices the way the pre-flow resolve_combat did: a Medusa card asks its owner's controller (with
    the live CombatCtx); any other card uses the boost the caller already put on the table."""
    def choose(choice: PendingChoice) -> Card | None:
        if is_medusa_card(flow.card_by_id(choice.card_id)):
            return game.controllers[choice.player].choose_combat_boost(game, flow.ctx)
        return boost
    return choose
