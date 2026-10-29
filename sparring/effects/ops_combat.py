"""Combat ops and their driver (docs/effects-dsl.md sections 3 and 4).

Ops here talk to the running combat through `run.flow` (a CombatFlow, set by `run_moment`): they change the values
of the two cards, cancel effects, register a redirection of the combat damage. Statuses are stored in `Game.fx`
and interpreted by effects/modifiers.py. `damage`, `move`, `place`, `swap` and `discard` are re-registered here
to tell the hooks whose effect is running (`fx.acting`) and to honour redirections and the forced-discard veto.

`run_moment` is what the three `dsl_*` rules of combat_flow.py call: it builds (or continues) the EffectRun of one
card moment, so a pause inside an effect survives `CombatFlow.to_dict`."""
from __future__ import annotations

from . import modifiers, narrate
from .choose import ControllerChooser, TableChooser
from .model import EffectError, load_effects
from .ops_core import OPS, op, plugin, plugin_condition
from .select import amount, card_ref, find_card, pick_fighters, player_of, players_of, fighter_candidates


def _flow(run, name: str):
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError(f"{name}: only inside a combat")
    return flow


def _side(run, game, ref) -> str | None:
    """The combat side ("atk" | "def") a CardRef designates, or None when that card is not in this combat."""
    cards = card_ref(game, run, ref)
    return modifiers.side_of(_flow(run, "card op"), cards[0]) if cards else None


def _label(run, game) -> str:
    card = find_card(game, run.ctx.card_id) if run.ctx.card_id is not None else None
    return card.title if card else "efecto"


# ---------------------------------------------------------------- card values

def _named_side(run, ref) -> str | None:
    """The combat side a CardRef names by role, card or no card: a Feint against a defense that was never played
    still marks the defending side cancelled (the record the engine has always kept)."""
    own = "atk" if run.ctx.played_as == "attack" else "def"
    other = "def" if own == "atk" else "atk"
    return {"this": own, "opponent_card": other, "attack_card": "atk", "defense_card": "def"}.get(ref)


@op("cancel_effects")
def _cancel_effects(run, game, spec):
    flow = _flow(run, "cancel_effects")
    side = _side(run, game, spec["card"])
    if side is None:
        side = _named_side(run, spec["card"])
    card = None if side is None else (flow.atk_card if side == "atk" else flow.def_card)
    if side is not None and (card is None or not modifiers.is_uncancelable(card)):
        flow.ctx.cancelled.add(side)


@op("modify_value")
def _modify_value(run, game, spec):
    flow = _flow(run, "modify_value")
    side = _side(run, game, spec["card"])
    if side is not None:
        modifiers.add_value(flow, side, int(amount(game, run, spec["amount"])), _label(run, game))


@op("set_value")
def _set_value(run, game, spec):
    flow = _flow(run, "set_value")
    side = _side(run, game, spec["card"])
    if side is not None:
        n = 0 if spec.get("ignore") else int(amount(game, run, spec["amount"]))
        modifiers.set_value(flow, side, n, _label(run, game), bool(spec.get("ignore")))


@op("boost")
def _boost(run, game, spec):
    """Boosts the card now: the top card of the card owner's deck is discarded and its BOOST value added (even 0)."""
    flow = _flow(run, "boost")
    side = _side(run, game, spec["card"])
    if side is None:
        return
    owner = flow.att.owner if side == "atk" else flow.tgt.owner
    player = game.players[owner]
    if not player.deck:
        return
    top = player.deck.pop(0)
    player.discard.append(top)
    run.flags.setdefault("deck_discards", []).append(top.card_id)
    game.fx.emit("card_discarded", owner, top)
    modifiers.add_value(flow, side, top.boost, f"impulso {top.title}")


# ---------------------------------------------------------------- statuses

@op("status")
def _status(run, game, spec):
    n = int(amount(game, run, spec["amount"])) if "amount" in spec else 0
    label = _label(run, game)
    if "target" in spec:
        chooser = player_of(game, run, spec.get("chooser", "owner"))
        for f in pick_fighters(game, run, spec["target"], chooser, op="status", amount=n):
            modifiers.add_status(game.fx, spec["name"], owner=run.ctx.owner, until=spec["until"], fid=f.fid,
                                 amount=n, label=label)
    else:
        for player in players_of(game, run, spec["player"]):
            modifiers.add_status(game.fx, spec["name"], owner=run.ctx.owner, until=spec["until"], player=player,
                                 amount=n, label=label)


# ---------------------------------------------------------------- redirected damage

@op("redirect_damage")
def _redirect_damage(run, game, spec):
    """Registers a redirection for THIS combat (it is a DURING op). Resolved when the damage is dealt."""
    flow = _flow(run, "redirect_damage")
    from_fighters = fighter_candidates(game, run, spec["from"])[0]
    if not from_fighters:
        return
    flow.redirects.append({"from": from_fighters[0].fid, "to": spec["to"], "damage": spec["damage"],
                           "condition": spec.get("condition"), "optional": bool(spec.get("optional")),
                           "owner": run.ctx.owner})


def _damage_victim(run, game, fighter, n):
    """`fighter`, or whoever takes its `n` effect damage instead (FATEFUL BARGAINS); an optional redirection asks
    its owner, telling it the blow."""
    target, src = modifiers.redirect_target(game, fighter, "effect")
    if target is None:
        return fighter
    if src.get("optional"):
        chooser = {"owner": src["owner"], "opponent": 1 - src["owner"]}[src.get("chooser", "owner")]
        if not run.ask(game, "optional", chooser, [True, False], 1, 1, f"{target.fid} takes the damage instead?",
                       fighter=fighter.fid, to=target.fid, amount=n)[0]:
            return fighter
    return target


def _acting(game, owner: int):
    """Marks whose effect is resolving; returns the previous mark so the caller restores it in `finally`."""
    previous, game.fx.acting = game.fx.acting, owner
    return previous


@op("damage")
def _damage(run, game, spec):
    n = amount(game, run, spec["amount"])
    targets = pick_fighters(game, run, spec["target"], player_of(game, run, spec.get("chooser", "owner")),
                            op="damage", amount=n)
    victims = [_damage_victim(run, game, f, n) for f in targets] if n > 0 else []
    previous = _acting(game, run.ctx.owner)
    try:
        hit = [f.fid for f in victims if game.damage(f, n, "effect") > 0]
    finally:
        game.fx.acting = previous
    if "as" in spec:
        run.bind("fighters", spec["as"], hit)


def _with_acting(name: str, veto=None):
    inner = OPS[name]

    def wrapped(run, game, spec):
        if veto is not None and veto(run, game, spec):
            return None
        previous = _acting(game, run.ctx.owner)
        try:
            return inner(run, game, spec)
        finally:
            game.fx.acting = previous
    OPS[name] = wrapped


def _forced_discard_blocked(run, game, spec) -> bool:
    """The rival's effect makes a player discard from hand (not as the cost that player chose to pay)."""
    cards = spec["cards"]
    if not isinstance(cards, dict) or cards["zone"] != "hand":
        return False
    frame = run.frames[-1]
    if frame.path and frame.path[-1] == "cost":
        return False
    victim = player_of(game, run, cards["player"])
    return victim != run.ctx.owner and not game.fx.can_force_discard(victim, run.ctx.owner)


for _name in ("move", "place", "swap"):
    _with_acting(_name)
_with_acting("discard", _forced_discard_blocked)


# ---------------------------------------------------------------- Perfect Shot (Abe)

@plugin("abe:perfect_shot")
def _perfect_shot(run, game, spec):
    """`predict`: the prediction belongs to the moment the card is played, before the defense is chosen, which the
    DSL has no moment for. E3 wires it (the bot announces its prediction, the human gets buttons) by leaving the
    printed value in this run's `flags["prediction"]`; until then the card is played face down: no +2."""
    run.flags.setdefault("prediction", None)


@plugin_condition("abe:perfect_shot")
def _perfect_shot_hit(game, run, key: str) -> bool:
    """`predicted_correctly`: the prediction recorded at IMMEDIATELY equals the printed value of the rival's card;
    no card played against it is never a hit (Ivan, 28/10)."""
    if key != "predicted_correctly":
        raise EffectError(f"abe:perfect_shot: unknown key {key!r}")
    flow = getattr(run, "flow", None)
    if flow is None:
        return False
    side = "atk" if run.ctx.played_as == "attack" else "def"
    first = flow.runs.get(f"immediately:{side}")
    rival = flow.def_card if side == "atk" else flow.atk_card
    prediction = None if first is None else first.flags.get("prediction")
    return prediction is not None and rival is not None and (rival.value or 0) == prediction


# ---------------------------------------------------------------- driver for CombatFlow

def run_moment(flow, side, moment: str):
    """Runs (or continues) one card moment of one side. Returns the Await of a paused effect, else None.
    `flow.runs` keeps every run, finished ones included, so a rerun after a pause never starts it again. A run says
    what it did when it ends (`narrate`), once: the bot's in `result.applied`, the rival's in `result.human_effects`."""
    from .run import Ctx, EffectRun
    game, key = flow.game, f"{moment}:{side.name}"
    run = flow.runs.get(key)
    if run is None:
        owner = side.fighter.owner
        ops = load_effects(game.players[owner].hero.slug).moment_ops(side.card.title, moment)
        if not ops:
            return None
        rival = side.rival
        ctx = Ctx(owner=owner, this_fid=side.fighter.fid, card_id=side.card.card_id, moment=moment,
                  attacker_fid=flow.att.fid, defender_fid=flow.tgt.fid,
                  opp_card_id=_rival_card_id(flow, side), attack_card_id=flow.atk_card.card_id,
                  defense_card_id=None if flow.def_card is None else flow.def_card.card_id,
                  played_as="attack" if side.name == "atk" else "defense")
        if moment == "after":
            won = flow.result.attacker_won == (side.name == "atk")
            ctx.combat_result = "won" if won else "lost"
            dealt = flow.result.damage if flow.result.attacker_won == (side.name == "atk") else 0
            ctx.damage_dealt, ctx.damage_taken = (dealt, 0) if won else (0, flow.result.damage)
        run = flow.runs[key] = EffectRun(ops, ctx, label=moment)
        run.flow = flow
        run.flags["before"] = narrate.snapshot(game, flow)
    wait = run.run(game, flow.choosers)
    if wait is None and "before" in run.flags:
        # the bot's card in `applied` ("Aplicado: ..."); the other player's in `human_effects` (E2: with what they
        # do on the table themselves)
        lines = flow.result.applied if narrate.applies(game, run.ctx.owner) else flow.result.human_effects
        narrate.record(lines, narrate.describe(game, run.flags.pop("before"), run, flow))
    return wait


def _rival_card_id(flow, side) -> int | None:
    card = flow.def_card if side.name == "atk" else flow.atk_card
    return None if card is None else card.card_id


def default_choosers(game) -> dict:
    """Who answers the decisions of each player in a synchronous combat: the controller of a bot, but never the
    engine for a human (`Controller.human`): the table does that."""
    def chooser(player):
        ctrl = game.controllers.get(player)
        return TableChooser() if getattr(ctrl, "human", False) else ControllerChooser()
    return {0: chooser(0), 1: chooser(1)}
