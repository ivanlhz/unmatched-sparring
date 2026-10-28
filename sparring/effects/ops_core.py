"""The op registry and the core ops (docs/effects-dsl.md section 3).

An op handler is `fn(run, game, op) -> pushes | None`. It must ask EVERY decision (`run.ask`, selectors) before
the first mutation: a chooser may pause the run and the handler is then executed again from the top. Control ops
(`if`, `optional`, `for_each`, `choose_effect`) mutate nothing; they return the sub-lists to run next as
`(subpath, loop)` pairs, where subpath is relative to the op (e.g. `("then",)`).

Ops the DSL defines but later phases implement are registered as stubs that raise NotImplementedError naming the
phase ("cancel_effects: C2"), so data using them loads and fails loudly only when such an op actually runs."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable

from .model import EffectError, load_effects
from .select import (Picked, amount, condition, fighter_candidates, locate, pick_fighters, player_of, players_of,
                     card_candidates, card_ref, select_cards, space_options)

OPS: dict[str, Callable] = {}
PLUGINS: dict[str, Callable] = {}
PLUGIN_TESTS: dict[str, Callable] = {}

PENDING_PHASES = {
    "look_hand": "C4", "reveal": "C4", "look_deck": "C4", "search_deck": "C4", "return_to_deck": "C4",
    "put_in_hand": "C4",
}


def op(name: str):
    def deco(fn):
        OPS[name] = fn
        return fn
    return deco


def plugin(plugin_id: str):
    """Registers the handler of `{"op": "plugin", "id": plugin_id}`."""
    def deco(fn):
        PLUGINS[plugin_id] = fn
        return fn
    return deco


def plugin_condition(plugin_id: str):
    """Registers the evaluator of `{"test": "plugin", "id": plugin_id, "key": ...}`: fn(game, run, key) -> bool."""
    def deco(fn):
        PLUGIN_TESTS[plugin_id] = fn
        return fn
    return deco


def plugin_test(game, run, cond: dict) -> bool:
    try:
        return PLUGIN_TESTS[cond["id"]](game, run, cond["key"])
    except KeyError:
        raise NotImplementedError(f"plugin condition {cond['id']}: not registered") from None


def _pending(name: str, phase: str):
    def stub(run, game, spec):
        raise NotImplementedError(f"{name}: {phase}")
    OPS[name] = stub


for _name, _phase in PENDING_PHASES.items():
    _pending(_name, _phase)


def check_op(spec: dict) -> None:
    if spec.get("op") not in OPS:
        raise EffectError(f"unknown op {spec.get('op')!r}")


def _chooser(game, run, spec: dict) -> int:
    return player_of(game, run, spec.get("chooser", "owner"))


@contextmanager
def _trial():
    """Temporarily applies (fighter, attrs) while planning so later choices see earlier ones; always restored."""
    saved = []
    try:
        yield lambda f, **attrs: (saved.append((f, {k: getattr(f, k) for k in attrs})),
                                  [setattr(f, k, v) for k, v in attrs.items()])
    finally:
        for f, before in reversed(saved):
            for k, v in before.items():
                setattr(f, k, v)


# ---------------------------------------------------------------- fighter state

@op("damage")
def _damage(run, game, spec):
    targets = pick_fighters(game, run, spec["target"], _chooser(game, run, spec))
    n = amount(game, run, spec["amount"])
    hit = [f.fid for f in targets if game.damage(f, n, "effect") > 0]
    if "as" in spec:
        run.bind("fighters", spec["as"], hit)


@op("heal")
def _heal(run, game, spec):
    targets = pick_fighters(game, run, spec["target"], _chooser(game, run, spec))
    n = amount(game, run, spec["amount"])
    for f in targets:
        game.heal(f, n)


@op("set_hp")
def _set_hp(run, game, spec):
    targets = pick_fighters(game, run, spec["target"], _chooser(game, run, spec))
    n = amount(game, run, spec["amount"])
    for f in targets:
        if n >= f.hp:
            f.hp = min(f.max_hp, n)
        else:
            game.damage(f, f.hp - n, "set_hp")


# ---------------------------------------------------------------- cards

@op("draw")
def _draw(run, game, spec):
    chooser = _chooser(game, run, spec)
    top = amount(game, run, spec["amount"])
    plan = []
    for player in players_of(game, run, spec["player"]):
        n = top
        if spec.get("up_to"):
            n = run.ask(game, "amount", chooser, list(range(top + 1)), 1, 1, "draw how many")[0]
        plan.append((player, n))
    drawn = [c.card_id for player, n in plan for c in game.draw(player, n)]
    if "as" in spec:
        run.bind("cards", spec["as"], drawn)


def _cards_of(game, run, cards, purpose: str) -> list[Picked]:
    if isinstance(cards, str):
        found = []
        for c in card_ref(game, run, cards):
            where = locate(game, c)
            if where is not None:
                found.append(Picked(where[0], where[1], c))
        return found
    return select_cards(game, run, cards, purpose)


@op("discard")
def _discard(run, game, spec):
    items = _cards_of(game, run, spec["cards"], "discard")
    for player, zone, card in items:
        if zone == "hand":
            game.discard_card(player, card)
        elif zone == "deck":
            game.players[player].deck.remove(card)
            game.players[player].discard.append(card)
            game.fx.emit("card_discarded", player, card)
        elif zone == "in_play":
            game.fx.take_ongoing(player)
            if card not in game.players[player].discard:
                game.players[player].discard.append(card)
    if "as" in spec:
        run.bind("cards", spec["as"], [c.card_id for _, _, c in items])


@op("choose")
def _choose(run, game, spec):
    items = select_cards(game, run, spec["cards"], "choose")
    run.bind("cards", spec["as"], [c.card_id for _, _, c in items])


@op("choose_effect")
def _choose_effect(run, game, spec):
    options, chooser = spec["options"], _chooser(game, run, spec)
    labels = [o["label"] for o in options]
    left, picked = list(range(len(options))), []
    for _ in range(int(amount(game, run, spec["amount"]))):
        if not left:
            break
        pool = left if spec.get("distinct") else list(range(len(options)))
        k = run.ask(game, "effect", chooser, pool, 1, 1, "choose an effect", labels=labels)[0]
        picked.append(k)
        if spec.get("distinct"):
            left.remove(k)
    return [(("options", k, "ops"), None) for k in sorted(picked)]     # resolved in printed order, not choice order


# ---------------------------------------------------------------- board

@op("move")
def _move(run, game, spec):
    chooser = _chooser(game, run, spec)
    targets = pick_fighters(game, run, spec["target"], chooser)
    steps, through, up_to = int(amount(game, run, spec["amount"])), spec.get("through_enemies", False), spec["up_to"]
    plan = []
    with _trial() as set_attrs:
        for f in targets:
            if not f.alive or f.pos is None or not game.fx.can_move(f):
                continue
            dests = sorted(game.legal_moves(f, steps, through))
            if not up_to:       # exactly N: the farthest spaces when some are exactly N away
                exact = [d for d in dests if game.board.distance(f.pos, d) == steps]
                dests = exact or dests
            got = run.ask(game, "space", chooser, dests, 0 if up_to else 1, 1, "move to",
                          fighter=f.fid, op="move", steps=steps, through=through)
            if got:
                plan.append((f, got[0]))
                set_attrs(f, pos=got[0])
    for f, dest in plan:
        game.move_fighter(f, dest, steps, through)


def _plan_spots(game, run, fighters, where: dict, chooser: int, op_name: str, **becomes) -> list[tuple]:
    plan = []
    with _trial() as set_attrs:
        for f in fighters:
            options = space_options(game, run, where, mover=f)
            got = run.ask(game, "space", chooser, options, 1, 1, f"{op_name} to", fighter=f.fid, op=op_name)
            if got:
                plan.append((f, got[0]))
                set_attrs(f, pos=got[0], **becomes)
    return plan


@op("place")
def _place(run, game, spec):
    chooser = _chooser(game, run, spec)
    targets = [f for f in pick_fighters(game, run, spec["target"], chooser) if f.alive and game.fx.can_move(f)]
    for f, spot in _plan_spots(game, run, targets, spec["where"], chooser, "place"):
        f.pos = spot


@op("swap")
def _swap(run, game, spec):
    chooser = _chooser(game, run, spec)
    a = pick_fighters(game, run, spec["target"], chooser)
    b = pick_fighters(game, run, spec["with"], chooser)
    if a and b and a[0] is not b[0] and a[0].alive and b[0].alive and game.fx.can_move(a[0]) and game.fx.can_move(b[0]):
        a[0].pos, b[0].pos = b[0].pos, a[0].pos


@op("revive")
def _revive(run, game, spec):
    chooser = _chooser(game, run, spec)
    hp = amount(game, run, spec["hp"])
    targets = [f for f in pick_fighters(game, run, spec["target"], chooser) if not f.alive]
    for f, spot in _plan_spots(game, run, targets, spec["where"], chooser, "revive", alive=True):
        f.alive, f.pos, f.hp = True, spot, min(hp, f.max_hp)


@op("summon")
def _summon(run, game, spec):
    chooser = _chooser(game, run, spec)
    reserve = sorted((f for f in game.own(run.ctx.owner, alive_only=False)
                      if f.name == spec["name"] and not f.alive and f.died_at is None), key=lambda f: f.fid)
    if not reserve:
        return
    hp = amount(game, run, spec["hp"]) if "hp" in spec else reserve[0].max_hp
    for f, spot in _plan_spots(game, run, reserve[:1], spec["where"], chooser, "summon", alive=True):
        f.alive, f.pos, f.hp = True, spot, min(hp, f.max_hp)


# ---------------------------------------------------------------- counters and turn

@op("counter")
def _counter(run, game, spec):
    for player in players_of(game, run, spec.get("player", "owner")):
        rng = load_effects(game.players[player].hero.slug).counter_range(spec["name"])
        now = game.fx.counter_value(player, spec["name"], rng.start)
        value = spec["set"] if "set" in spec else now + spec["delta"]
        game.fx.set_counter(player, spec["name"], max(rng.min, min(rng.max, value)))


@op("gain_action")
def _gain_action(run, game, spec):
    n = int(amount(game, run, spec["amount"]))
    for player in players_of(game, run, spec.get("player", "owner")):
        if player == game.turn:
            game.grant_actions(n)


@op("end_turn")
def _end_turn(run, game, spec):
    run.flags["end_turn"] = game.turn      # the CURRENT turn ends, whoever owns the card (a defense can end the attacker's)
    game.actions_left = 0


# ---------------------------------------------------------------- control

@op("if")
def _if(run, game, spec):
    branch = "then" if condition(game, run, spec["condition"]) else "else"
    return [((branch,), None)] if spec.get(branch) else []


def _can_pay(game, run, cost: list[dict]) -> bool:
    """Conservative: a discard cost needs enough cards; any other cost is assumed payable."""
    for c in cost:
        if c["op"] == "discard" and isinstance(c["cards"], dict):
            sel = c["cards"]
            need = 0 if sel.get("up_to") else min(int(amount(game, run, sel.get("amount", 1))), 1 << 30)
            if len(card_candidates(game, run, sel)) < need:
                return False
    return True


@op("optional")
def _optional(run, game, spec):
    cost = spec.get("cost") or []
    yes = _can_pay(game, run, cost) and run.ask(
        game, "optional", _chooser(game, run, spec), [True, False], 1, 1, "do it?")[0]
    if yes:
        return ([(("cost",), None)] if cost else []) + [(("ops",), None)]
    return [(("else",), None)] if spec.get("else") else []


@op("for_each")
def _for_each(run, game, spec):
    over = spec["over"]
    if "players" in over:
        kind, items = "players", players_of(game, run, over["players"])
    else:
        kind = "fighters"
        cands, _ = fighter_candidates(game, run, over["fighters"])
        items = run.ask(game, "order", player_of(game, run, spec.get("chooser", "owner")),
                        [f.fid for f in cands], len(cands), len(cands), "order", ordered=True)
    return [(("ops",), {"var": spec["as"], "kind": kind, "items": list(items), "pos": 0})]


@op("plugin")
def _plugin(run, game, spec):
    try:
        handler = PLUGINS[spec["id"]]
    except KeyError:
        raise NotImplementedError(f"plugin {spec['id']}: not registered") from None
    return handler(run, game, spec)


from . import ops_combat  # noqa: E402,F401  (registers the combat ops over the registry above)
