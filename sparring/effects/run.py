"""EffectRun: a re-entrant interpreter for one ops list (one card moment, one trigger).

The run is a stack of frames, each (path to an ops list, index of the next op, optional for_each loop). It never
holds the game: `step(game, chooser)` executes ONE op. Ops are atomic: they ask every decision first and only
then mutate, so when a chooser pauses the run (`Await`) nothing has changed and, after `resume`, only the current
op runs again. Decisions already obtained inside that op are kept in `answers` (keyed by op path plus ask index)
so a rerun never asks, or rolls the dice, twice. Everything serializes to JSON: bindings travel as card ids,
fighter ids and player numbers.

Typical use:
    run = EffectRun(ops, Ctx(owner=0, this_fid="medusa", card_id=17612), label="after")
    pending = run.run(game, {0: ControllerChooser(), 1: PanelChooser()})     # Await | None
    ...
    run.resume([answer]); pending = run.run(game, choosers)                  # same game, or a reloaded copy
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .choose import Await, Chooser, ChoiceRequest, Suspend
from .model import EffectError, load_effects, walk_ops
from .ops_core import OPS, check_op


@dataclass
class Ctx:
    """What the effect knows about where it runs (all ids, JSON-safe)."""
    owner: int
    this_fid: str | None = None
    card_id: int | None = None
    moment: str | None = None
    attacker_fid: str | None = None
    defender_fid: str | None = None
    opp_card_id: int | None = None
    attack_card_id: int | None = None
    defense_card_id: int | None = None
    combat_result: str | None = None       # "won" | "lost" for the owner
    played_as: str | None = None           # "attack" | "defense"
    damage_dealt: int = 0
    damage_taken: int = 0


@dataclass
class Frame:
    path: list                              # keys from the root ops list to this ops list
    idx: int = 0
    loop: dict | None = None                # for_each: {"var", "kind", "items", "pos"}


class EffectRun:
    def __init__(self, ops: list[dict], ctx: Ctx, label: str = "fx", bindings: dict | None = None):
        for o in walk_ops(ops):
            check_op(o)
        self.ops, self.ctx, self.label = ops, ctx, label
        self.frames: list[Frame] = [Frame([])] if ops else []
        self.bindings: dict[str, dict] = dict(bindings or {})
        self.answers: dict[str, list] = {}
        self.flags: dict[str, object] = {}
        self.awaiting: ChoiceRequest | None = None
        self._choosers: Chooser | dict | None = None
        self._op_key = ""
        self._asks = 0
        self._game = None

    @classmethod
    def for_card(cls, slug: str, title: str, moment: str, ctx: Ctx) -> "EffectRun":
        ctx.moment = moment
        return cls(load_effects(slug).moment_ops(title, moment), ctx, label=moment)

    @property
    def done(self) -> bool:
        return not self.frames

    # ------------------------------------------------------------ bindings
    def bind(self, kind: str, name: str, values) -> None:
        self.bindings[name] = {"t": kind, "v": list(values) if kind != "num" else values}

    def bound(self, name: str, kind: str):
        b = self.bindings.get(name)
        if b is None or b["t"] != kind:
            have = "nothing" if b is None else b["t"]
            raise EffectError(f"${name} is {have}, expected {kind}")
        return b["v"]

    # ------------------------------------------------------------ decisions
    def ask(self, game, kind: str, player: int, options: list, lo: int, hi: int, prompt: str = "",
            ordered: bool = False, **extra) -> list:
        """A decision of `player`. Forced answers (nothing to choose) are taken without asking, except an
        `ordered` pick of all, where the order itself is the decision."""
        if not options:
            return []
        if lo >= len(options) and not (ordered and len(options) > 1):
            return list(options)
        key = f"{self._op_key}:{self._asks}"
        self._asks += 1
        if key in self.answers:
            return self.answers[key]
        req = ChoiceRequest(kind, player, list(options), lo, min(hi, len(options)), self.ctx.card_id, key, prompt, extra, self.ctx.owner)
        answer = self._chooser(player).choose(game, req)
        if isinstance(answer, Await):
            raise Suspend(req, answer)
        self.answers[key] = req.validate(answer)
        return self.answers[key]

    def random_sample(self, items: list, n: int) -> list:
        """`n` of `items` by the game's rng; drawn once per op even if the op reruns after an Await."""
        key = f"{self._op_key}:r{self._asks}"
        self._asks += 1
        if key not in self.answers:
            self.answers[key] = self._game.rng.sample(range(len(items)), n)
        return [items[i] for i in self.answers[key]]

    def _chooser(self, player: int) -> Chooser:
        c = self._choosers
        if isinstance(c, dict):
            return c[player]
        if c is None:
            raise EffectError("no chooser given")
        return c

    # ------------------------------------------------------------ running
    def step(self, game, choosers) -> Await | None:
        """Executes one op (or closes one finished list). Returns the Await when a chooser paused the run."""
        if not self.frames:
            return None
        self._choosers, self._game = choosers, game
        fr = self.frames[-1]
        ops = self._ops_at(fr.path)
        if fr.idx >= len(ops):
            self._close(fr)
            return None
        op = ops[fr.idx]
        self._op_key, self._asks = self._key(), 0
        try:
            pushes = OPS[op["op"]](self, game, op)
        except Suspend as s:
            self.awaiting = s.request
            return s.pause
        prefix = self._op_key + ":"
        for k in [k for k in self.answers if k.startswith(prefix)]:
            del self.answers[k]
        here = fr.path + [fr.idx]
        fr.idx += 1
        for sub, loop in reversed(pushes or ()):
            self._push(here + list(sub), loop)
        return None

    def run(self, game, choosers) -> Await | None:
        while self.frames:
            pending = self.step(game, choosers)
            if pending is not None:
                return pending
        return None

    def resume(self, answer: list) -> None:
        if self.awaiting is None:
            raise EffectError("resume: the run is not waiting for an answer")
        self.answers[self.awaiting.key] = self.awaiting.validate(answer)
        self.awaiting = None

    # ------------------------------------------------------------ frames
    def _ops_at(self, path: list) -> list:
        node = self.ops
        for seg in path:
            node = node[seg]
        return node

    def _key(self) -> str:
        top = self.frames[-1]
        segs = [str(s) for s in top.path + [top.idx]]
        for fr in self.frames:
            if fr.loop is not None:
                segs[len(fr.path) - 1] += f"@{fr.loop['pos']}"
        return "/".join([self.label, *segs])

    def _push(self, path: list, loop: dict | None) -> None:
        if loop is not None:
            if not loop["items"]:
                return
            self._set_loop_var(loop)
        if self._ops_at_or_none(path):
            self.frames.append(Frame(path, 0, loop))

    def _ops_at_or_none(self, path: list):
        try:
            return self._ops_at(path)
        except (KeyError, IndexError):
            return None

    def _close(self, fr: Frame) -> None:
        loop = fr.loop
        if loop is not None and loop["pos"] + 1 < len(loop["items"]):
            loop["pos"] += 1
            fr.idx = 0
            self._set_loop_var(loop)
            return
        self.frames.pop()

    def _set_loop_var(self, loop: dict) -> None:
        item = loop["items"][loop["pos"]]
        self.bind(loop["kind"], loop["var"], [item])

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {"ops": self.ops, "label": self.label, "ctx": asdict(self.ctx),
                "frames": [{"path": f.path, "idx": f.idx, "loop": f.loop} for f in self.frames],
                "bindings": self.bindings, "answers": self.answers, "flags": self.flags,
                "awaiting": None if self.awaiting is None else self.awaiting.to_dict()}

    @classmethod
    def from_dict(cls, raw: dict) -> "EffectRun":
        run = cls(raw["ops"], Ctx(**raw["ctx"]), raw["label"], raw["bindings"])
        run.frames = [Frame(list(f["path"]), f["idx"], f["loop"]) for f in raw["frames"]]
        run.answers = {k: list(v) for k, v in raw["answers"].items()}
        run.flags = dict(raw["flags"])
        run.awaiting = None if raw["awaiting"] is None else ChoiceRequest.from_dict(raw["awaiting"])
        return run
