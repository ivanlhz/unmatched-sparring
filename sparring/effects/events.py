"""Event dispatch (docs/effects-dsl.md 2.10 and 4): hero ability triggers, ongoing triggers and `until` expiry.

`EffectState.emit` / `on_damage` land here, only when the game has heroes in `fx.dsl_heroes`. One event does, in order:
  1. bookkeeping the DSL reads (who attacked this turn, where fighters started the turn, actions taken);
  2. expiry: an ongoing card whose `until` matches goes to the discard pile (so Fight Or Flight is gone before the
     Wildfire discard of the same start of turn);
  3. triggers: for the player whose turn it is first, the hero's ability triggers, then the triggers of the ongoing card.
A trigger's decisions go to `fx.choosers` (default: both players' Controllers, i.e. the bots' policy); a run a chooser
pauses is parked in `fx.parked`."""
from __future__ import annotations

from functools import lru_cache

from . import inventions, narrate, table
from .choose import ControllerChooser
from .model import EffectError, load_effects, walk_ops
from .ongoing import leave_play, spec_of
from .run import Ctx, EffectRun
from .select import _matches, condition, fighter_candidates

# Ability triggers the dispatcher leaves to the engine's callers, who decide when and on whom with the cards already
# chosen (Medusa's gaze: `Game.use_ability` from the AI, the session and the search). Skipped here so nothing fires
# twice; `run_trigger` runs them on request.
DRIVEN_BY_THE_ENGINE = frozenset({"medusa_gaze"})

_BOTS = ControllerChooser()

# Turn bookkeeping and the words of an effects file that read it: a hero whose data never names them does not get
# it recorded, so a game of such heroes saves exactly as it did before the interpreter.
TRACKS = {"attacked": ("attacked_this_turn", "combat_damage_dealt"),
          "turn_start_pos": ("moved_this_turn",),
          "taken": ("actions_taken_this_turn", "no_attack_as_first_action")}


def _strings(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _strings(v)
    elif isinstance(node, str):
        yield node


@lru_cache(maxsize=None)
def tracked(slugs: frozenset) -> frozenset:
    """Which of `TRACKS` the heroes in `slugs` need, read from their effects files."""
    words = set()
    for slug in slugs:
        fx = load_effects(slug)
        words |= set(_strings([fx.triggers, fx.passives, [(c.moments, c.ongoing) for c in fx.cards.values()]]))
    return frozenset(name for name, needles in TRACKS.items() if words & set(needles))


def default_choosers(game) -> dict:
    return game.fx.choosers or {0: _BOTS, 1: _BOTS}


# ------------------------------------------------------------------ entry points

def dispatch(game, name: str, args: tuple) -> None:
    ev = _normalize(game, name, args)
    if ev is not None:
        _handle(game, ev)


def damage_dealt(game, fighter, n, source: str, by) -> None:
    """A fighter lost `n` hp. Combat damage is also `combat_damage_dealt` by whoever dealt it (the attacker when the
    engine did not say: Game.attack records it)."""
    _handle(game, {"name": "damage_taken", "fighter": fighter, "amount": n, "source": source})
    if source == "combat":
        if by is None and game.fx.attacked:
            by = game.fighters.get(game.fx.attacked[-1])
        if by is not None:
            _handle(game, {"name": "combat_damage_dealt", "by": by, "to": fighter, "amount": n})


def run_trigger(game, owner: int, trigger_id: str, choosers=None):
    """Runs one ability trigger of `owner`'s hero now (condition included). Returns the Await, if a chooser paused it."""
    trig = load_effects(game.players[owner].hero.slug).trigger(trigger_id)
    return _fire(game, owner, trig, {"name": trig["when"]["event"], "player": owner}, trig["id"], None, choosers)


# ------------------------------------------------------------------ normalizing what the engine emits

def _normalize(game, name: str, args: tuple) -> dict | None:
    if name in ("start_of_turn", "end_of_turn", "after_maneuver"):
        return {"name": name, "player": args[0]}
    if name == "attacked":
        return {"name": name, "attacker": args[0], "target": args[1], "card": args[2]}
    if name == "after_attack":
        return {"name": name, "attacker": args[0], "target": args[1]}
    if name == "card_discarded":
        return {"name": name, "player": args[0], "card": args[1], "zone": args[2] if len(args) > 2 else "hand",
                "cause": args[3] if len(args) > 3 else None}
    if name == "card_played":
        return {"name": name, "player": args[0], "card": args[1]}
    if name == "fighter_defeated":
        return {"name": name, "fighter": args[0]}
    return None          # force_discard and the like: hooks for other phases, not DSL events


def _bookkeeping(game, ev: dict) -> None:
    fx = game.fx
    keep = tracked(frozenset(fx.dsl_heroes))
    if ev["name"] == "start_of_turn":
        fx.attacked.clear()
        fx.taken = 0
        fx.turn_start_pos = ({fid: f.pos for fid, f in game.fighters.items() if f.alive}
                             if "turn_start_pos" in keep else {})
    elif ev["name"] == "attacked" and "attacked" in keep:
        fx.attacked.append(ev["attacker"].fid)


# ------------------------------------------------------------------ matching

def _handle(game, ev: dict) -> None:
    _bookkeeping(game, ev)
    order = (game.turn, 1 - game.turn)
    for player in order:
        spec = spec_of(game, player)
        if spec is not None and matches(game, player, spec["until"], ev):
            leave_play(game, player)
    todo = []
    for player in order:
        slug = game.players[player].hero.slug
        if slug not in game.fx.dsl_heroes:
            continue
        for trig in load_effects(slug).triggers:
            if trig["id"] not in DRIVEN_BY_THE_ENGINE and not table.start_of_turn_is_physical(game, player, trig):
                todo.append((player, trig, None))
        todo += [(player, trig, card_id) for trig, card_id in inventions.triggers(game, player)]
        spec = spec_of(game, player)
        if spec is not None:
            todo += [(player, trig, game.fx.ongoing_card_id(player)) for trig in spec.get("triggers", ())]
    for player, trig, card_id in todo:
        if matches(game, player, trig["when"], ev):
            _fire(game, player, trig, ev, trig["id"], card_id)


def attack_revealed(game, target) -> bool:
    """`target`'s hero has an ability that, attacked now, turns the attack card face up: an `attacked` trigger on
    the hero with a `reveal` of `attack_card` whose condition holds (UNCANNY INTUITION with an active token).
    Read from the trigger, never from a name; False for a hero outside the interpreter (no engine trigger)."""
    owner = target.owner
    if not game.fx.interprets(owner) or target is not game.hero(owner):
        return False
    try:
        triggers = load_effects(game.players[owner].hero.slug).triggers
    except EffectError:
        return False
    run = EffectRun([], Ctx(owner=owner, this_fid=target.fid))
    for t in triggers:
        when = t.get("when") or {}
        if when.get("event") != "attacked" or when.get("target", "hero") != "hero":
            continue
        if not any(o["op"] == "reveal" and o.get("cards") == "attack_card" for o in walk_ops(t.get("ops") or [])):
            continue
        cond = t.get("condition")
        if cond is None or condition(game, run, cond):
            return True
    return False


def _fighter_ok(game, owner: int, sel, fighter, defeated: bool = False) -> bool:
    if sel is None:
        return True
    sel = {"role": sel} if isinstance(sel, str) else dict(sel)
    if defeated:
        sel.setdefault("state", "defeated")
    run = EffectRun([], Ctx(owner=owner, this_fid=game.hero(owner).fid))
    return fighter in fighter_candidates(game, run, sel)[0]


def _player_ok(want: str, player: int, owner: int) -> bool:
    return want == "any" or (player == owner) == (want == "owner")


def matches(game, owner: int, when: dict, ev: dict) -> bool:
    """Does the event `ev` satisfy the Event `when` of something `owner` has (docs 2.10)?"""
    if when["event"] != ev["name"]:
        return False
    name = ev["name"]
    if name in ("start_of_turn", "after_maneuver"):
        return _player_ok(when.get("player", "owner"), ev["player"], owner)
    if name == "end_of_turn":
        return _player_ok(when.get("player", "any"), ev["player"], owner)
    if name == "attacked":
        return _fighter_ok(game, owner, when.get("target"), ev["target"])
    if name == "after_attack":
        return _fighter_ok(game, owner, when.get("fighter"), ev["attacker"])
    if name == "combat_damage_dealt":
        return _fighter_ok(game, owner, when.get("by"), ev["by"])
    if name == "damage_taken":
        kind = when.get("damage", "any")
        is_combat = ev["source"] == "combat"
        if kind == "combat" and not is_combat or kind == "effect" and (is_combat or ev["source"] == "exhaustion"):
            return False
        return ev["amount"] >= when.get("min", 1) and _fighter_ok(game, owner, when.get("target"), ev["fighter"])
    if name in ("card_discarded", "card_played"):
        if not _player_ok(when.get("player", "owner"), ev["player"], owner):
            return False
        if "from" in when and ev.get("zone") not in when["from"]:
            return False
        if when.get("cause_not") is not None and ev.get("cause") == when["cause_not"]:
            return False
        return _matches(ev["card"], when.get("filter") or {})
    if name == "fighter_defeated":
        return _fighter_ok(game, owner, when.get("fighter"), ev["fighter"], defeated=True)
    return False


# ------------------------------------------------------------------ running a trigger

def _fire(game, owner: int, trig: dict, ev: dict, label: str, card_id: int | None, choosers=None):
    ctx = Ctx(owner=owner, this_fid=game.hero(owner).fid, card_id=card_id, moment=trig["when"]["event"])
    run = EffectRun(trig["ops"], ctx, label=label)
    _bind_event(run, ev)
    if ev["name"] == "end_of_turn":
        run.flags["attacked"] = list(game.fx.attacked)       # the next turn begins while a choice of this run waits (FATEFUL BARGAINS)
    if "condition" in trig and not condition(game, run, trig["condition"]):
        return None
    before = narrate.snapshot(game) if table.physical(game, owner) else None     # the human is told what it did
    pending = run.run(game, choosers or default_choosers(game))
    if pending is not None:
        if before is not None:
            run.flags["said_before"] = before                # the line is written when the human's choice is answered
        game.fx.parked.append(run)
    elif before is not None:
        _say(game, run, before)
    return pending


def _say(game, run: EffectRun, before: dict) -> None:
    card_id = run.ctx.card_id
    line = narrate.describe(game, before, run, title=None if card_id is not None else run.label.replace("_", " ").upper())
    if not line.endswith(": " + narrate.NOTHING):
        game.fx.said.append(("card" if card_id is not None else "ability", line))


def say_parked(game, run: EffectRun) -> bool:
    """A trigger the human's choice had parked is done: the line `_fire` owed for it. True if it owed one."""
    before = run.flags.pop("said_before", None)
    if before is not None:
        _say(game, run, before)
    return before is not None


def _bind_event(run: EffectRun, ev: dict) -> None:
    """The event's variables (docs 2.10): $attacker, $target, $by, $to, $fighter, $card, $amount."""
    ctx = run.ctx
    for key in ("attacker", "target", "by", "to", "fighter"):
        if key in ev:
            run.bind("fighters", key, [ev[key].fid])
    if "card" in ev:
        run.bind("cards", "card", [ev["card"].card_id])
    if "amount" in ev:
        run.bind("num", "amount", ev["amount"])
    if ev["name"] == "attacked":
        ctx.attacker_fid, ctx.defender_fid = ev["attacker"].fid, ev["target"].fid
        ctx.attack_card_id = ev["card"].card_id
