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

from . import table
from ..i18n import t
from .model import EffectError, load_effects
from .select import (_ref_fighter, Picked, amount, condition, fighter_candidates, find_card, locate, pick_fighters, player_of,
                     players_of, card_candidates, card_ref, select_cards, space_options)

OPS: dict[str, Callable] = {}
PLUGINS: dict[str, Callable] = {}
PLUGIN_TESTS: dict[str, Callable] = {}

PENDING_PHASES: dict[str, str] = {}


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
    n = amount(game, run, spec["amount"])
    targets = pick_fighters(game, run, spec["target"], _chooser(game, run, spec), op="damage", amount=n)
    hit = [f.fid for f in targets if game.damage(f, n, "effect") > 0]
    if "as" in spec:
        run.bind("fighters", spec["as"], hit)


@op("heal")
def _heal(run, game, spec):
    n = amount(game, run, spec["amount"])
    targets = pick_fighters(game, run, spec["target"], _chooser(game, run, spec), op="heal", amount=n)
    for f in targets:
        game.heal(f, n)


@op("set_hp")
def _set_hp(run, game, spec):
    n = amount(game, run, spec["amount"])
    targets = pick_fighters(game, run, spec["target"], _chooser(game, run, spec), op="set_hp", amount=n)
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


def _cards_of(game, run, cards, purpose: str, prompt: str | None = None, in_combat: bool = False,
              **extra) -> list[Picked]:
    """`in_combat`: a card ref may also name a card being played in this combat (zone "combat", held by the flow)."""
    if isinstance(cards, str):
        found = []
        flow = getattr(run, "flow", None) if in_combat else None
        for c in card_ref(game, run, cards):
            where = locate(game, c)
            if where is not None:
                found.append(Picked(where[0], where[1], c))
            elif flow is not None and any(card is c for _, card in flow.played):
                found.append(Picked(next(o for o, card in flow.played if card is c), "combat", c))
        return found
    return select_cards(game, run, cards, purpose, prompt, **extra)


def _card_title(game, run) -> str:
    card = find_card(game, run.ctx.card_id, run.ctx.owner) if run.ctx.card_id is not None else None
    return card.title if card else t("fx.cause_default")


def _random_positions_text(game, run, player: int, n: int, title: str) -> str:
    """A random discard from the table player's hand: the engine draws the POSITIONS with the game rng (it only knows
    how many cards they hold, never which) and the human discards those, counted from the left (Ivan, 29/10). The
    draw is memoized in the run so a rerun after a pause names the same positions."""
    size = len(game.players[player].hand)
    key = f"random_positions:{run.frames[-1].path}:{run.frames[-1].idx}"
    picked = run.flags.get(key)
    if picked is None:
        picked = sorted(game.rng.sample(range(1, size + 1), min(n, size))) if size else []
        run.flags[key] = picked
    if not picked:
        return title
    which = t("ops.random_one" if len(picked) == 1 else "ops.random_many") + t("common.and").join(str(p) for p in picked)
    return t("ops.random_positions", title=title, which=which)


@op("discard")
def _discard(run, game, spec):
    sel = spec["cards"]
    if table.hand_pick_is_physical(game, run, sel):
        # the human discards from their own hand at their own choice, at random or all of it: the engine never picks
        # those cards for them (its copy of the hand is placeholders), the table does (`Game.force_discard` -> the
        # human's controller owes the discard, settled at "End action")
        player = player_of(game, run, sel["player"])
        frame = run.frames[-1]
        voluntary = bool(frame.path) and frame.path[-1] == "cost"      # a price the human chose to pay
        n = len(card_candidates(game, run, sel)) if sel.get("pick") == "all" else int(amount(game, run, sel.get("amount", 1)))
        reason = _card_title(game, run)
        if sel.get("pick") == "random":
            reason = _random_positions_text(game, run, player, n, reason)
        game.fx.whole_hand = sel.get("pick") == "all"      # the table translator may move a whole hand itself
        try:
            chosen = game.force_discard(player, n, reason, player if voluntary else run.ctx.owner)
        finally:
            game.fx.whole_hand = False
        run.flags["physical_discard"] = True
        if "as" in spec:
            run.bind("cards", spec["as"], [c.card_id for c in chosen])
        return
    items = _cards_of(game, run, sel, "discard", _card_title(game, run))     # the reason a bot's choose_discard sees
    for player, zone, card in items:
        if zone == "hand":
            game.discard_card(player, card)
        elif zone == "deck":
            game.players[player].deck.remove(card)
            game.players[1 - player].known.drop_top(card.card_id)
            game.players[player].discard.append(card)
            run.flags.setdefault("deck_discards", []).append(card.card_id)     # the narration: not a hand discard
            game.fx.emit("card_discarded", player, card, "deck")
        elif zone == "in_play":
            game.fx.take_ongoing(player)
            if card not in game.players[player].discard:
                game.players[player].discard.append(card)
            table.intent(game, op="discard", zone="in_play", player=player, card=card.card_id)
    if "as" in spec:
        run.bind("cards", spec["as"], [c.card_id for _, _, c in items])


@op("remove_from_game")
def _remove_from_game(run, game, spec):
    """Cards of a discard pile leave the game for good (`PlayerState.removed`): public, and no effect brings them back."""
    sel = spec["cards"]
    if sel["zone"] != "discard":
        raise EffectError("remove_from_game: only cards of a discard pile can be removed")
    items = _cards_of(game, run, sel, "remove", _card_title(game, run))
    for player, _, card in items:
        game.remove_from_game(player, card)
    for player in sorted({p for p, _, _ in items}):
        table.intent(game, op="remove", player=player, cards=[c.card_id for p, _, c in items if p == player])
    if "as" in spec:
        run.bind("cards", spec["as"], [c.card_id for _, _, c in items])


@op("choose")
def _choose(run, game, spec):
    sel = spec["cards"]
    if table.hand_pick_is_physical(game, run, sel):      # the human keeps the cards in their hand: nothing is named
        run.bind("cards", spec["as"], [])
        table.note(run, op="choose", amount=int(amount(game, run, sel.get("amount", 1))))
        return
    items = select_cards(game, run, sel, "choose")
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
        k = run.ask(game, "effect", chooser, pool, 1, 1, "choose an effect", labels=labels,
                    **({"during_order": True} if spec.get("order") else {}))[0]
        picked.append(k)
        if spec.get("distinct"):
            left.remove(k)
    return [(("options", k, "ops"), None) for k in sorted(picked)]     # resolved in printed order, not choice order


# ---------------------------------------------------------------- board

def _one_after_another(fighters) -> list:
    """Several fighters whose destinations are asked one by one go in fighter id order (sidekicks before the hero:
    the order Winged Frenzy and the maneuver have always used), each seeing where the previous ones ended."""
    return sorted(fighters, key=lambda f: f.fid)


@op("move")
def _move(run, game, spec):
    chooser = _chooser(game, run, spec)
    steps, through, up_to = int(amount(game, run, spec["amount"])), spec.get("through_enemies", False), spec["up_to"]
    targets = pick_fighters(game, run, spec["target"], chooser, op="move", amount=steps, through=through)
    plan, by_hand = [], []
    with _trial() as set_attrs:
        for f in _one_after_another(targets):
            if not f.alive or f.pos is None or not game.fx.can_move(f):
                continue
            dests = sorted(game.legal_moves(f, steps, through))
            if not up_to:       # exactly N: with no space exactly N away the move is cancelled (Iván, 2026-11-07)
                dests = [d for d in dests if game.board.distance(f.pos, d) == steps]
                if not dests:
                    table.note(run, op="move_none", fid=f.fid, amount=steps)
                    continue
            if table.piece_is_physical(game, chooser, f) and not spec.get("await_destination"):     # the human moves their own miniature by hand
                by_hand.append(f)
                continue
            got = run.ask(game, "space", chooser, dests, 0 if up_to else 1, 1, "move to",
                          fighter=f.fid, op="move", steps=steps, through=through, up_to=up_to)
            if got:
                plan.append((f, got[0]))
                set_attrs(f, pos=got[0])
    passed = run.flags.setdefault("passed", {})
    for f, dest in plan:
        origin = f.pos
        passed[f.fid] = _passed_through(game, f, origin, dest, steps, through)
        game.move_fighter(f, dest, steps, through)
        if f.pos != origin:
            table.intent(game, op="move", fid=f.fid, owner=f.owner)
    for f in by_hand:
        passed[f.fid] = None                      # the human walks their own miniature: the engine never sees the path
        table.note(run, op="move", fid=f.fid, amount=steps, up_to=up_to, through=through)
    if "as" in spec:
        run.bind("fighters", spec["as"], [f.fid for f, _ in plan] + [f.fid for f in by_hand])


def _passed_through(game, mover, origin: int, dest: int, steps: int, through: bool) -> list[str]:
    """Fighters `mover` may have moved through on its way from `origin` to `dest`: those on some path of at most `steps`
    spaces (the board has no fixed path, the mover's owner chooses it). The fighters that oppose the mover count when it
    may cross them (`through_enemies`); its own side always does (a mover crosses its friends: Power Man hits them)."""
    if origin == dest:
        return []
    dist = game.board.distance
    crossed = (game.own(1 - mover.owner) if through else []) + [f for f in game.own(mover.owner) if f is not mover]
    return [e.fid for e in crossed
            if e.pos not in (origin, dest) and dist(origin, e.pos) + dist(e.pos, dest) <= steps]


def _where_refs(game, run, where: dict) -> dict:
    """A SpaceSel with its fighter references resolved to fighter ids (JSON-safe): what the human is told when they
    place a piece by hand."""
    out = {}
    if where.get("any"):
        out["any"] = True
    if where.get("other"):
        out["other"] = True
    if "next_to_nearest_foe" in where:
        out["next_to_nearest_foe"] = True
    for key in ("zone_of", "no_zone_of", "adjacent_to", "nearest_to"):
        if key in where:
            ref = _ref_fighter(game, run, where[key])
            if ref is not None:
                out[key] = ref.fid
    return out


def _note_where(game, run, where: dict) -> dict:
    """The SpaceSel for the chat line the human reads: the references resolved to who they are NOW (the owner's hero stays
    "hero"; any other fighter, `this` included, is named), so "this fighter's zone" of a sidekick is not "your hero's zone"."""
    out = dict(where)
    for key in ("zone_of", "no_zone_of", "adjacent_to", "nearest_to"):
        if key in where:
            ref = _ref_fighter(game, run, where[key])
            if ref is not None:
                out[key] = "hero" if ref is game.hero(run.ctx.owner) else ref.name
    return out


def _plan_spots(game, run, fighters, where: dict, chooser: int, op_name: str, hp=None, **becomes) -> list[tuple]:
    """(fighter, spot, by_hand): `by_hand` marks the table player's own piece, which they place themselves; its spot
    is provisional (the first legal one) until the table sync reads where they put it."""
    plan = []
    with _trial() as set_attrs:
        for f in _one_after_another(fighters):
            options = space_options(game, run, where, mover=f)
            if not options:                              # no space to choose from: nothing happens
                continue
            by_hand = table.piece_is_physical(game, chooser, f)
            stays = [f.died_at] if f.hero and f.died_at in options else options[:1]     # a hero put back by hand: where his miniature already stands
            got = stays if by_hand else run.ask(game, "space", chooser, options, 1, 1, f"{op_name} to",
                                                      fighter=f.fid, op=op_name, where=_where_refs(game, run, where),
                                                      **({} if hp is None else {"hp": hp}))
            if got:
                plan.append((f, got[0], by_hand))
                set_attrs(f, pos=got[0], **becomes)
    return plan


def _return_to_board(run, game, spec, op_name: str, targets, hp) -> None:
    chooser = _chooser(game, run, spec)
    for f, spot, by_hand in _plan_spots(game, run, targets, spec["where"], chooser, op_name, hp=hp, alive=True):
        f.alive, f.pos, f.hp = True, spot, min(hp, f.max_hp)
        if by_hand:
            game.placing.add(f.fid)
            table.note(run, op=op_name, fid=f.fid, where=_note_where(game, run, spec["where"]), hp=f.hp)
        else:
            table.intent(game, op=op_name, fid=f.fid, owner=f.owner)


@op("place")
def _place(run, game, spec):
    chooser = _chooser(game, run, spec)
    targets = [f for f in pick_fighters(game, run, spec["target"], chooser, op="place")
               if f.alive and game.fx.can_move(f)]
    for f, spot, by_hand in _plan_spots(game, run, targets, spec["where"], chooser, "place"):
        if by_hand:
            game.placing.add(f.fid)
            table.note(run, op="place", fid=f.fid, where=_note_where(game, run, spec["where"]))
        elif spot != f.pos:
            f.pos = spot
            table.intent(game, op="place", fid=f.fid, owner=f.owner)


@op("swap")
def _swap(run, game, spec):
    chooser = _chooser(game, run, spec)
    a = pick_fighters(game, run, spec["target"], chooser, op="swap")
    b = pick_fighters(game, run, spec["with"], chooser, op="swap")
    swapped = []
    if a and b and a[0] is not b[0] and a[0].alive and b[0].alive and game.fx.can_move(a[0]) and game.fx.can_move(b[0]):
        first, second = a[0], b[0]
        swapped = [first.fid, second.fid]
        if table.piece_is_physical(game, chooser, first) and table.piece_is_physical(game, chooser, second):
            game.placing.update((first.fid, second.fid))
            table.note(run, op="swap", fid=first.fid, other=second.fid)      # the table player swaps their miniatures by hand
        else:
            first.pos, second.pos = second.pos, first.pos
            for f in (first, second):
                table.intent(game, op="swap", fid=f.fid, owner=f.owner)
    if "as" in spec:
        run.bind("fighters", spec["as"], swapped)


@op("revive")
def _revive(run, game, spec):
    chooser = _chooser(game, run, spec)
    targets = [f for f in pick_fighters(game, run, spec["target"], chooser) if not f.alive]
    _return_to_board(run, game, spec, "revive", targets, amount(game, run, spec["hp"]))


@op("summon")
def _summon(run, game, spec):
    reserve = sorted((f for f in game.own(run.ctx.owner, alive_only=False)
                      if f.name == spec["name"] and not f.alive and f.died_at is None), key=lambda f: f.fid)
    if not reserve:
        return
    hp = amount(game, run, spec["hp"]) if "hp" in spec else reserve[0].max_hp
    _return_to_board(run, game, spec, "summon", reserve[:1], hp)


# ---------------------------------------------------------------- counters and turn

@op("counter")
def _counter(run, game, spec):
    for player in players_of(game, run, spec.get("player", "owner")):
        rng = load_effects(game.players[player].hero.slug).counter_range(spec["name"])
        now = game.fx.counter_value(player, spec["name"], rng.start)
        value = spec["set"] if "set" in spec else now + spec["delta"]
        value = max(rng.min, min(rng.max, value))
        game.fx.set_counter(player, spec["name"], value)
        if value != now:
            table.intent(game, op="counter", player=player, name=spec["name"])


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
    """Conservative: a discard (or a card put back in the deck) cost needs enough cards; any other cost is assumed payable."""
    for c in cost:
        if c["op"] in ("discard", "return_to_deck") and isinstance(c["cards"], dict):
            sel = c["cards"]
            need = 0 if sel.get("up_to") else min(int(amount(game, run, sel.get("amount", 1))), 1 << 30)
            if len(card_candidates(game, run, sel)) < need:
                return False
    return True


def _cost_context(game, run, cost: list[dict], chooser: int) -> dict:
    """What a bot needs to judge an optional cost (`choose.worth_paying`): how many cards it discards and, inside a
    combat, the damage the decision swings (`at_stake`) and the hit points that damage must reach to kill (`hp`).
    For the defender that is the damage it takes as things stand and its own hit points; for the attacker, the
    damage the defense is blocking and what the target would still have left."""
    ctx = {}
    cards = sum(int(c["cards"].get("amount", 1)) for c in cost
                if c["op"] == "discard" and isinstance(c["cards"], dict) and isinstance(c["cards"].get("amount", 1), int))
    if cards:
        ctx["cost_cards"] = cards
    flow = getattr(run, "flow", None)
    if flow is None or flow.ctx is None:
        return ctx
    atk, dfn, dealt = flow.ctx.atk_value, flow.ctx.def_value, max(0, flow.ctx.atk_value - flow.ctx.def_value)
    if flow.tgt.owner == chooser:
        ctx["at_stake"], ctx["hp"] = dealt, flow.tgt.hp
    elif flow.att.owner == chooser:
        ctx["at_stake"], ctx["hp"] = min(atk, dfn), max(0, flow.tgt.hp - dealt)
    return ctx


def _choice_context(game, run, spec: dict) -> dict:
    """What the two answers mean, for a panel that names them: `discards` (the cards the yes branch discards, when
    that is all it does: Remove A Painful Memory's "discard it") and `else_damage` (a plain damage in the else branch:
    "or take 2"). For a bot, what a card paid from the hand buys: `gains_action` (Hi-Yaaaaah!!) or `cancels` (Guaranteed
    Delivery: how many moments of the rival's card have effects to cancel)."""
    ctx = {}
    ops, other = spec.get("ops") or [], spec.get("else") or []
    if any(o["op"] == "plugin" and o["id"] in ("houdini:replace_combatant", "luke:replace_combatant") for o in ops):      # Smoke And Mirrors: a bot weighs the swap
        ctx["replaces_combatant"] = {"this": run.ctx.this_fid, "role": run.ctx.played_as}
    if len(ops) == 1 and ops[0]["op"] == "return_to_deck" and isinstance(ops[0]["cards"], dict) \
            and ops[0]["cards"]["zone"] == "deck" and ops[0]["cards"].get("pick") == "top":
        owner = player_of(game, run, ops[0]["cards"]["player"])      # putting the top card at the bottom (The future of Ninjutsu)
        if not table.physical(game, owner):                          # the human's deck is virtual: nothing true to name
            ctx["bury"] = [c.card_id for c in game.players[owner].deck[:int(amount(game, run, ops[0]["cards"].get("amount", 1)))]]
    if any(o["op"] == "return_to_deck" for o in spec.get("cost") or []):
        if any(o["op"] == "gain_action" for o in ops):
            ctx["gains_action"] = True
        if any(o["op"] == "cancel_effects" for o in ops):
            ctx["cancels"] = _cancellable_moments(game, run)
    if len(ops) == 1 and ops[0]["op"] == "discard" and isinstance(ops[0]["cards"], str):
        ctx["discards"] = [c.card_id for c in card_ref(game, run, ops[0]["cards"])]
    pact = _pact_context(game, run, ops)
    if pact is not None:
        ctx["pact"] = pact
    if not spec.get("cost") and ops and all(o["op"] == "draw" and o.get("player") == "owner" and isinstance(o.get("amount"), int) for o in ops):
        ctx["draws"] = sum(o["amount"] for o in ops)         # a free draw; `draws_at`: the event of the trigger that offers it
        ctx["draws_at"] = run.ctx.moment
    if len(other) == 1 and other[0]["op"] == "damage" and isinstance(other[0].get("amount"), int):
        ctx["else_damage"] = other[0]["amount"]
        cands, _ = fighter_candidates(game, run, other[0]["target"])
        if len(cands) == 1:
            ctx["else_fighter"] = cands[0].fid       # who takes it: the answer's price in hit points
    return ctx


def _pact_context(game, run, ops: list[dict]) -> dict | None:
    """An optional that costs the owner's own fighter hit points and sends a card to the bottom of the deck for a draw
    (DARK PACT): `fighter`, `damage`, the `card` that goes and the cards it `draws`. A bot weighs these with `EffectAI`."""
    hurt = next((o for o in ops if o["op"] == "damage" and isinstance(o.get("amount"), int)), None)
    back = next((o for o in ops if o["op"] == "return_to_deck" and isinstance(o["cards"], str)
                 and o.get("position") == "bottom"), None)
    if hurt is None or back is None:
        return None
    cands, _ = fighter_candidates(game, run, hurt["target"])
    if len(cands) != 1 or cands[0].owner != run.ctx.owner:
        return None
    cards = card_ref(game, run, back["cards"])
    draws = sum(int(o["amount"]) for o in ops if o["op"] == "draw" and isinstance(o.get("amount"), int))
    return {"fighter": cands[0].fid, "damage": hurt["amount"], "card": cards[0].card_id if cards else None, "draws": draws}


def _cancellable_moments(game, run) -> int:
    """Moments (immediately, during, after) of the rival's card that have effects a `cancel_effects` would erase."""
    from .modifiers import card_effects, is_uncancelable
    cards = card_ref(game, run, "opponent_card")
    fx = card_effects(cards[0]) if cards else None
    if fx is None or is_uncancelable(cards[0]):
        return 0
    return sum(1 for m in ("immediately", "during", "after") if fx.moments.get(m))


@op("optional")
def _optional(run, game, spec):
    cost = spec.get("cost") or []
    chooser = _chooser(game, run, spec)
    ctx = _cost_context(game, run, cost, chooser)
    can_pay = _can_pay(game, run, cost)
    yes = can_pay and run.ask(game, "optional", chooser, [True, False], 1, 1, "do it?", **ctx,
                              **_choice_context(game, run, spec))[0]
    if cost and chooser != run.ctx.owner and chooser == game.bot_player:
        run.flags["bot_priced"] = {"paid": bool(yes), "can_pay": can_pay, "cards": ctx.get("cost_cards", 0),
                                   "stake": ctx.get("at_stake", 0), "hp": ctx.get("hp")}
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
from . import ops_info  # noqa: E402,F401  (registers look_hand, reveal, look_deck, search_deck, return_to_deck, put_in_hand)
from . import plugins_raphael  # noqa: E402,F401  (registers raphael:unbridled_rage)
from . import plugins_strange  # noqa: E402,F401  (registers strange:blind_boost, strange:mists_of_munnopor, strange:reveal_to_top)
from . import plugins_houdini  # noqa: E402,F401  (registers houdini:replace_combatant, houdini:return_boosted)
from . import plugins_daredevil  # noqa: E402,F401  (registers daredevil:take_a_knee)
from . import plugins_donatello  # noqa: E402,F401  (registers donatello:future_of_ninjutsu)
from . import plugins_luke  # noqa: E402,F401  (registers luke:replace_combatant)
