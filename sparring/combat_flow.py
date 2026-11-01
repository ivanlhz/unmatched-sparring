"""Combat as a serializable state machine. See docs/combat-flow.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .cards import Card
from .combat import (ON_EARTH, PLANNED, CombatCtx, CombatResult, _check_boost, _side_cards, can_boost, deck_boost,
                     is_medusa_card)
from .effects import inventions
from .i18n import t
from .state import ANUNG, Fighter, Game, RuleError


def _dsl(flow: "CombatFlow", side: "Side") -> bool:
    """The card's owner plays a hero the effects interpreter resolves (`game.fx.dsl_heroes`): legacy rules step aside."""
    return flow.game.fx.interprets(side.fighter.owner)


def _is_bot(game: Game, player: int) -> bool:
    return player == game.bot_player


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
    kind: str                    # "boost" (a card to put on the table) | "effect" (a DSL decision: extra has key+request)
                                 # | "table" (AFTER gate: the human does a step on their hand before the next side's effect)
    player: int                  # who decides
    card_id: int                 # card whose effect asks
    deck: bool = False           # Flame Lash: the boost is the bottom card of the deck
    extra: dict = field(default_factory=dict)    # caller-owned JSON-safe data (session: guid, baseline, hand, stuck)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "player": self.player, "card": self.card_id, "deck": self.deck, **self.extra}

    @classmethod
    def from_dict(cls, raw, *, default_player: int, deck_of: Callable[[int], bool]) -> "PendingChoice":
        """Also reads the old format (no "kind"/"player"): a boost of `default_player`, `deck` recomputed from the
        card. An "effect" pause keeps its key and request. KeyError if the structure is invalid."""
        if not isinstance(raw, dict):
            raise KeyError("pending choice")
        kind, player, card = raw.get("kind", "boost"), raw.get("player", default_player), raw.get("card")
        if kind == "effect":
            if not _is_int(player) or not (card is None or _is_int(card)) or not isinstance(raw.get("key"), str) \
                    or not isinstance(raw.get("request"), dict):
                raise KeyError("pending choice")
            return cls(kind, player, card, False, {k: v for k, v in raw.items() if k not in _RESERVED})
        if kind == "table":
            if not _is_int(player) or not _is_int(card):
                raise KeyError("pending choice")
            return cls(kind, player, card, False, {k: v for k, v in raw.items() if k not in _RESERVED})
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
        # state of the effects interpreter (all empty unless a hero is in game.fx.dsl_heroes)
        self.runs: dict[str, object] = {}            # "moment:side" -> EffectRun, finished ones too
        self.printed_set: dict[str, int] = {}        # side -> printed value after a "value becomes N" effect
        self.mods: dict[str, list[list]] = {"atk": [], "def": []}     # [delta, label] applied by value ops
        self.redirects: list[dict] = []              # combat damage redirections registered this combat
        self.choosers: dict | None = None            # player -> effects Chooser; None = the controllers decide

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
        if self.phase is Phase.AFTER and (gate := self._table_gate(side)) is not None:
            self.pending = gate
            return Await(gate)
        handler = self._handler(side)
        if handler is not None:
            self.await_key = f"{self.phase.value}:{side.name}:{handler.name}"
            if (wait := handler.run(self, side)) is not None:
                self.pending = wait.choice
                return wait
        self.side_idx += 1
        return None

    def _table_gate(self, side: Side) -> PendingChoice | None:
        """Ivan, 31/10 (Glimpse Of Hell, then Fleeting Moments): AFTER effects go one after the other, the defender's
        first. When the previous side's effect left the human a step on their own hand (a card to put back in the
        deck, a discard they owe), the next side's effect waits for it: it may read that hand (a random discard) and
        the cards the first one drew. The gate is answered once the table has been read again (`resume(None)`)."""
        if self.side_idx == 0 or self.runs.get(f"after:{self.sides[self.side_idx - 1].name}") is None:
            return None
        prev = self.sides[self.side_idx - 1]
        key = f"after_gate:{prev.name}"
        if key in self.answers or side.name in self.ctx.cancelled:
            return None
        from .effects import table
        from .effects.model import load_effects
        owner = side.fighter.owner
        if not _dsl(self, side) or not table.hand_step_pending(self.runs[f"after:{prev.name}"])                 or not load_effects(self.game.players[owner].hero.slug).moment_ops(side.card.title, "after"):
            return None
        self.await_key = key
        return PendingChoice("table", prev.fighter.owner, prev.card.card_id)

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
                inventions.settle_played(self.game, owner, card)

    # ---------- decisions ----------
    def resume(self, choice: "Card | list | None") -> None:
        """Answers the current pause: a card (or None) for a boost, the chosen option list for an effect decision."""
        if self.pending is not None and self.pending.kind == "effect":
            self.awaiting_run.resume(choice)
        else:
            self.answers[self.await_key] = None if choice is None else choice.card_id
        self.pending = None

    @property
    def awaiting_run(self):
        """The EffectRun stopped at the current "effect" pause (None for a boost pause or no pause at all)."""
        if self.pending is None or self.pending.kind != "effect":
            return None
        return self.runs[self.await_key.rsplit(":", 1)[0]]

    def answer(self, rule_name: str) -> tuple[bool, Card | None]:
        """(answered, card) for the decision the running handler asks; the key is phase:side:rule."""
        key = f"{self.phase.value}:{self.sides[self.side_idx].name}:{rule_name}"
        if key not in self.answers:
            return False, None
        card_id = self.answers[key]
        return True, None if card_id is None else self.card_by_id(card_id, self.sides[self.side_idx].fighter.owner)

    def _owner_of(self, card: Card) -> int:
        return next(i for i, p in enumerate(self.game.players) if any(c is card for c in p.full_set))

    def card_by_id(self, card_id: int, owner: int) -> Card:
        """The card of `owner` with that id. Ids repeat across players in a mirror match, so the owner is required."""
        for c in self.game.players[owner].full_set:
            if c.card_id == card_id:
                return c
        raise KeyError(card_id)

    # ---------- engine hooks (code moved from combat.resolve_combat) ----------
    def _declare(self) -> None:
        game, tgt, def_card = self.game, self.tgt, self.def_card
        if def_card is not None:
            game.check_defense_card(tgt, def_card)
            if def_card not in game.players[tgt.owner].hand:
                raise RuleError(t("err.not_in_hand", title=def_card.title, fid=tgt.fid))
        pa, pd = self.att.owner, tgt.owner
        game.take_from_hand(pa, self.atk_card)
        if def_card is not None:
            game.take_from_hand(pd, def_card)
        self.played = [(pa, self.atk_card)] + ([(pd, def_card)] if def_card else [])

    def _reveal(self) -> None:
        game, att, tgt, atk_card, def_card, values = self.game, self.att, self.tgt, self.atk_card, self.def_card, self.values
        bonus_parts = game.attack_bonus_parts(att)   # hero passives (Hellboy in ANUNG UN RAMA: +2)
        if game.fx.statuses:
            from .effects.modifiers import take_next_attack_bonus
            bonus_parts = bonus_parts + take_next_attack_bonus(game.fx, att.owner)
        atk_value = (atk_card.value or 0) + values[0] + sum(n for n, _ in bonus_parts)
        def_value = (def_card.value or 0) if def_card else 0
        def_value += values[1]
        # the defender's ONGOING adds to its card value (even at 0 or cancelled); no card, no value to add to
        self.def_bonus_parts = game.defense_bonus_parts(tgt.owner) if def_card is not None else []
        def_value += self.def_bonus
        self.ctx = CombatCtx(att, tgt, atk_card, def_card, atk_value, def_value, set())
        self.result = CombatResult(att.fid, tgt.fid, atk_card, def_card, atk_value, def_value, 0, False)
        self.result.atk_parts = [f"{atk_card.title} ({atk_card.value or 0})"]
        self.result.atk_parts += [f"{label} (+{n})" for n, label in bonus_parts if n]
        if values[0]:
            self.result.atk_parts.append(t("cf.extra", n=values[0]))
        self.sides = [Side(*s) for s in _side_cards(self.ctx)]

    @property
    def def_bonus(self) -> int:
        return sum(n for n, _ in self.def_bonus_parts)

    def _damage(self) -> None:
        ctx, result, values = self.ctx, self.result, self.values
        if self.def_card is not None:
            printed = ctx.def_value - values[1] - self.def_bonus - sum(n for n, _ in self.mods["def"])
            result.def_parts = [f"{self.def_card.title} ({printed})"]
            if "def" in ctx.cancelled:
                result.def_parts[0] += t("cf.cancelled")
            result.def_parts += [f"{label} (+{n})" for n, label in self.def_bonus_parts if n]
            result.def_parts += [f"{label} ({n:+d})" for n, label in self.mods["def"]]
        if values[1]:
            result.def_parts.append(t("cf.extra", n=values[1]))
        damage = max(0, ctx.atk_value - ctx.def_value)
        victim = self.tgt
        if self.redirects:
            from .effects.modifiers import combat_redirect_target
            victim = combat_redirect_target(self)
            if victim is not self.tgt and damage:
                result.applied.append(t("cf.redirect", victim=victim.fid, target=self.tgt.fid))
        self.game.damage(victim, damage, "combat")
        result.atk_value, result.def_value, result.damage, result.attacker_won = ctx.atk_value, ctx.def_value, damage, damage >= 1
        result.cancelled = set(ctx.cancelled)

    # ---------- serialization ----------
    def to_dict(self) -> dict:
        out = self._base_dict(self.ctx, self.result)
        if self.runs or self.printed_set or self.mods["atk"] or self.mods["def"] or self.redirects:
            out["dsl"] = {"runs": {k: r.to_dict() for k, r in self.runs.items()}, "printed_set": dict(self.printed_set),
                          "mods": {k: [list(m) for m in v] for k, v in self.mods.items()},
                          "redirects": [dict(r) for r in self.redirects]}
        return out

    def _base_dict(self, ctx, res) -> dict:
        return {
            "phase": self.phase.value, "side_idx": self.side_idx, "after_open": self.after_open,
            "values": list(self.values), "fids": [self.att.fid, self.tgt.fid],
            "atk_card": self.atk_card.card_id, "def_card": None if self.def_card is None else self.def_card.card_id,
            "played": [[owner, card.card_id] for owner, card in self.played],
            "def_bonus_parts": [[n, label] for n, label in self.def_bonus_parts],
            "answers": dict(self.answers), "await_key": self.await_key,
            "pending": None if self.pending is None else self.pending.to_dict(),
            "ctx": None if ctx is None else {"atk_value": ctx.atk_value, "def_value": ctx.def_value,
                                             "cancelled": sorted(ctx.cancelled),
                                             **({"cancelled_after": sorted(ctx.cancelled_after)} if ctx.cancelled_after else {})},
            "result": None if res is None else {
                "atk_value": res.atk_value, "def_value": res.def_value, "damage": res.damage,
                "attacker_won": res.attacker_won, "cancelled": sorted(res.cancelled),
                "boost_card": None if res.boost_card is None else res.boost_card.card_id,
                "boost_owner": None if res.boost_card is None else self._owner_of(res.boost_card),
                "atk_parts": list(res.atk_parts), "def_parts": list(res.def_parts), "applied": list(res.applied),
                "bot_notes": list(res.bot_notes), "human_effects": list(res.human_effects)},
        }

    @classmethod
    def from_dict(cls, game: Game, raw: dict) -> "CombatFlow":
        def card(card_id, owner):
            return None if card_id is None else flow.card_by_id(card_id, owner)
        att, tgt = (game.fighters[fid] for fid in raw["fids"])
        flow = cls.__new__(cls)
        flow.game, flow.att, flow.tgt, flow.values = game, att, tgt, tuple(raw["values"])
        flow.atk_card, flow.def_card = card(raw["atk_card"], att.owner), card(raw["def_card"], tgt.owner)
        flow.phase, flow.side_idx, flow.after_open = Phase(raw["phase"]), raw["side_idx"], raw["after_open"]
        flow.played = [(owner, card(card_id, owner)) for owner, card_id in raw["played"]]
        flow.def_bonus_parts = [(n, label) for n, label in raw["def_bonus_parts"]]
        flow.answers, flow.await_key = dict(raw["answers"]), raw["await_key"]
        flow.pending = None if raw["pending"] is None else PendingChoice.from_dict(
            raw["pending"], default_player=att.owner, deck_of=lambda _: False)
        flow.ctx = flow.result = None
        flow.sides = []
        flow.runs, flow.printed_set, flow.redirects, flow.choosers = {}, {}, [], None
        flow.mods = {"atk": [], "def": []}
        if "dsl" in raw:
            from .effects.run import EffectRun
            d = raw["dsl"]
            for key, saved in d["runs"].items():
                flow.runs[key] = run = EffectRun.from_dict(saved)
                run.flow = flow
            flow.printed_set = dict(d["printed_set"])
            flow.mods = {k: [list(m) for m in v] for k, v in d["mods"].items()}
            flow.redirects = [dict(r) for r in d["redirects"]]
        if raw["ctx"] is not None:
            c, r = raw["ctx"], raw["result"]
            flow.ctx = CombatCtx(att, tgt, flow.atk_card, flow.def_card, c["atk_value"], c["def_value"],
                                 set(c["cancelled"]), set(c.get("cancelled_after", ())))
            flow.result = CombatResult(att.fid, tgt.fid, flow.atk_card, flow.def_card, r["atk_value"], r["def_value"],
                                       r["damage"], r["attacker_won"], set(r["cancelled"]), card(r["boost_card"], _boost_owner(flow, r)),
                                       list(r["human_effects"]), list(r["atk_parts"]), list(r["def_parts"]),
                                       list(r["applied"]), list(r["bot_notes"]))
            flow.sides = [Side(*s) for s in _side_cards(flow.ctx)]
        return flow


def _boost_owner(flow: CombatFlow, saved_result: dict) -> int | None:
    """Owner of the saved boost card; saves from before "boost_owner" existed fall back to the first deck that has it."""
    if saved_result["boost_card"] is None:
        return None
    if saved_result.get("boost_owner") is not None:
        return saved_result["boost_owner"]
    return next(i for i, p in enumerate(flow.game.players) if any(c.card_id == saved_result["boost_card"] for c in p.full_set))


_HOOKS = {Phase.DECLARED: CombatFlow._declare, Phase.CARDS_SET: CombatFlow._reveal, Phase.DAMAGE: CombatFlow._damage}


# ---------- rules, in the order of the old if/elif chains (Medusa's own rules left with C5: her cards are DSL) ----------
@rule(Phase.IMMEDIATELY, match=lambda flow, side: side.card.title == PLANNED and not _dsl(flow, side))
def planned_recklessness(flow: CombatFlow, side: Side) -> None:
    flow.game.effect_shield[side.fighter.owner] = flow.game.turn_no
    if flow.game.form(side.fighter.owner) != ANUNG:
        _cancel_rival(flow, side)


def _cancel_rival(flow: CombatFlow, side: Side) -> None:
    """Cancels the other card's effects unless that card says they cannot be canceled (Incinerate)."""
    from .effects.modifiers import is_uncancelable
    target = _other(side)
    card = flow.atk_card if target == "atk" else flow.def_card
    if card is None or not is_uncancelable(card):
        flow.ctx.cancelled.add(target)


def _other(side: Side) -> str:
    return "atk" if side.name == "def" else "def"


@rule(Phase.DURING, side="def", when_cancelled=True,
      match=lambda flow, side: side.card.title == ON_EARTH and not _dsl(flow, side))
def on_earth_value(flow: CombatFlow, side: Side) -> None:
    base = flow.values[1] + flow.def_bonus
    flow.ctx.def_value = base if "def" in flow.ctx.cancelled else flow.game.destiny_count(side.fighter.owner) + base


def _add_boost(flow: CombatFlow, side: Side, boost: Card) -> None:
    flow.game.discard_card(side.fighter.owner, boost)
    flow.ctx.atk_value += boost.boost
    flow.result.boost_card = boost
    flow.result.atk_parts.append(t("cf.boost_with", title=boost.title, boost=boost.boost))


@rule(Phase.DURING, side="atk", match=lambda flow, side: can_boost(side.card) and not _dsl(flow, side))
def boost_this_attack(flow: CombatFlow, side: Side) -> Await | None:
    answered, boost = flow.answer("boost_this_attack")
    if not answered:
        return Await(PendingChoice("boost", side.fighter.owner, side.card.card_id, deck_boost(side.card)))
    if boost is not None:
        if not deck_boost(side.card):          # Flame Lash: the bottom deck card adds whatever it is worth, even 0
            _check_boost(boost)
        _add_boost(flow, side, boost)


@rule(Phase.AFTER, match=lambda flow, side: _is_bot(flow.game, side.fighter.owner) and not _dsl(flow, side))
def bot_card_outside_the_interpreter(flow: CombatFlow, side: Side) -> None:
    """The bot's hero is interpreted by default (D1); only a save that switched it off gets here. The text is not
    resolved and the human is never asked to resolve a card of the bot: it is said so."""
    if side.card.text.strip():
        flow.result.bot_notes.append(t("cf.bot_no_resolve", title=side.card.title, text=side.card.text))


@rule(Phase.AFTER, match=lambda flow, side: not _dsl(flow, side))
def human_card_outside_the_interpreter(flow: CombatFlow, side: Side) -> None:
    """The human's hero is interpreted by default (E2, table mode); only a save that switched it off gets here and
    the text of the card is left to them, as the legacy path always did."""
    card, result = side.card, flow.result
    if card.title == PLANNED:
        result.applied.append(t("cf.planned", title=card.title, text=card.text))
    elif card.text.strip() and not can_boost(card):   # the BOOST of Second Shot was already resolved in DURING
        result.human_effects.append(f"{card.title}: {card.text}")


# ---------------------------------------------------------------- DSL cards (docs/effects-dsl.md section 4)
def _run_moment(flow: CombatFlow, side: Side, moment: str) -> Await | None:
    from .effects.ops_combat import default_choosers, run_moment
    if flow.choosers is None:
        flow.choosers = default_choosers(flow.game)
    return run_moment(flow, side, moment)


@rule(Phase.IMMEDIATELY, match=_dsl)
def dsl_immediately(flow: CombatFlow, side: Side) -> Await | None:
    return _run_moment(flow, side, "immediately")


@rule(Phase.DURING, match=_dsl)
def dsl_during(flow: CombatFlow, side: Side) -> Await | None:
    """The card's DURING ops, then its free BOOST if the data says `may_boost` (either side: Out Of Time defends)."""
    from .effects.modifiers import add_value, may_boost
    if (wait := _run_moment(flow, side, "during")) is not None:
        return wait
    if not may_boost(side.card):
        return None
    owner = side.fighter.owner
    answered, boost = flow.answer("dsl_during")
    if not answered:
        return Await(PendingChoice("boost", owner, side.card.card_id))
    if boost is not None:
        _check_boost(boost)
        flow.game.discard_card(owner, boost)
        add_value(flow, side.name, boost.boost, t("cf.boost_with_plain", title=boost.title))
        if side.name == "atk":
            flow.result.boost_card = boost


@rule(Phase.AFTER, match=_dsl)
def dsl_after(flow: CombatFlow, side: Side) -> Await | None:
    if side.name in flow.ctx.cancelled_after:
        return None
    return _run_moment(flow, side, "after")


def _i_won(flow: CombatFlow, side: Side) -> bool:
    return flow.result.attacker_won == (side.name == "atk")


# ---------- synchronous driver ----------
def legacy_chooser(game: Game, flow: CombatFlow, boost: Card | None, human: int | None = None) -> Callable[[PendingChoice], Card | None]:
    """Answers boost choices the way the pre-flow resolve_combat did: a Medusa card, a defender's card or a card of
    the bot's interpreted hero asks its owner's controller (with the live CombatCtx); the human's card (`human`: the
    live session's seat; the attacker's, or the defender's when it may boost, Out Of Time) uses the boost the caller
    already read from the table."""
    def choose(choice: PendingChoice):
        if choice.kind == "table":          # a human table step between AFTER sides: nothing to wait for here
            return None
        if choice.kind == "effect":         # a panel chooser paused an effect inside a synchronous combat
            from .effects.choose import ChoiceRequest
            from .effects.ops_combat import default_choosers
            return default_choosers(game)[choice.player].choose(game, ChoiceRequest.from_dict(choice.extra["request"]))
        player = choice.player
        bot_dsl = _is_bot(game, player) and game.fx.interprets(player)
        if player == human and not is_medusa_card(flow.card_by_id(choice.card_id, player)):
            return boost
        if bot_dsl or player != flow.att.owner or is_medusa_card(flow.card_by_id(choice.card_id, player)):
            return game.controllers[player].choose_combat_boost(game, flow.ctx)
        return boost
    return choose
