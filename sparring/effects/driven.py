"""Effects the engine's callers drive with decisions taken up front (C5).

The AI planner, the session and the search decide when Medusa's gaze fires and on whom, and which fighter a scheme
hits, before the card runs (`Act.target`, the search move). Those answers reach the interpreter as presets
(`PresetChooser`) instead of being asked back, so the controller is called exactly as often as before. A preset
answers the first request of its kind (the op `fighter_options` validated against); later picks of the same card
go to the normal chooser. A preset fighter that the effect could not pick is a RuleError raised before anything is
spent."""
from __future__ import annotations

from ..state import Fighter, RuleError
from . import events, ongoing
from .choose import PresetChooser
from .model import load_effects, walk_ops
from .run import Ctx, EffectRun
from .select import fighter_candidates

_PICKING = ("damage", "heal", "set_hp", "status", "move", "place", "swap", "revive")


def fighter_options(game, owner: int, ops: list, this_fid: str, card_id: int | None = None) -> list[Fighter]:
    """The fighters the first fighter-picking op of `ops` may take right now: what a preset target must be among."""
    view = EffectRun([], Ctx(owner=owner, this_fid=this_fid, card_id=card_id))
    for op in walk_ops(ops):
        if op["op"] in _PICKING and "target" in op:          # a player-scoped status picks nobody
            return fighter_candidates(game, view, op["target"])[0]
    return []


def _check_target(game, owner: int, ops: list, this_fid: str, card_id: int | None, target: Fighter | None,
                  what: str) -> None:
    if target is not None and target not in fighter_options(game, owner, ops, this_fid, card_id):
        raise RuleError(f"{what}: {target.fid} no es un objetivo valido")


def preset_choosers(game, owner: int, by_kind: dict, base: dict | None = None) -> dict:
    """`base` (D2: the search's SyntheticChoosers, the bot executing what the search chose) replaces the default
    choosers; the presets, when any, still answer first."""
    choosers = dict(base or events.default_choosers(game))
    if by_kind:
        choosers[owner] = PresetChooser(choosers[owner], by_kind)
    return choosers


def use_ability(game, owner: int, trigger_id: str, target: Fighter | None = None):
    """Runs one ability trigger of `owner`'s hero now, accepting its "you may" and aiming it at `target` (when the
    trigger picks a fighter). Returns the Await of a paused chooser, None when done."""
    trig = load_effects(game.players[owner].hero.slug).trigger(trigger_id)
    hero = game.hero(owner)
    _check_target(game, owner, trig["ops"], hero.fid, None, target, trigger_id)
    presets = {"optional": [True]}
    if target is not None:
        presets["fighter"] = [target.fid]
    return events.run_trigger(game, owner, trigger_id, preset_choosers(game, owner, presets))


def play_scheme(game, player: int, fighter: Fighter, card, target: Fighter | None = None, choosers: dict | None = None):
    """Plays a DSL scheme: the action, then its ops with `target` answering the fighter it hits and `choosers`
    (player -> Chooser; default: the controllers / the panel) deciding the rest. Returns the Await of a paused
    chooser (the card is then left to the caller to finish), None when done."""
    ops = load_effects(game.players[player].hero.slug).moment_ops(card.title, "scheme")
    _check_target(game, player, ops, fighter.fid, card.card_id, target, card.title)
    presets = {"fighter": [target.fid]} if target is not None else {}
    game.use_action()
    _, pending = ongoing.resolve_scheme(game, player, fighter, card, preset_choosers(game, player, presets, choosers))
    return pending
