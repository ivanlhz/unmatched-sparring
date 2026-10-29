"""Verbatim copies of the engine's Medusa code as of f4c26ca (the last commit before C5), kept as the oracle of
tests/test_medusa_dsl_diff.py: `_medusa_after` and `_optional_move` (sparring/combat.py), the Medusa branch of
`resolve_scheme` with `check_scheme`, `Game.medusa_ability` and `Game.play_scheme` (sparring/state.py) and the three
combat-flow rules `feint`, `second_shot`, `medusa_after` (sparring/combat_flow.py).

`legacy(monkeypatch)` turns a test into the pre-C5 engine: Medusa out of `fx.dsl_heroes` by default and the legacy
rules and methods installed; everything else is the production code."""
from __future__ import annotations

from contextlib import contextmanager

from sparring import combat, combat_flow
from sparring.cards import Card
from sparring.combat import GAZE_DAMAGE, GLANCE_DAMAGE, SECOND_SHOT, FEINT, _check_boost, is_medusa_card
from sparring.combat_flow import Await, CombatFlow, PendingChoice, Phase, Rule, Side, _add_boost, _cancel_rival, _dsl, _i_won
from sparring.effects import state as fx_state
from sparring.state import Fighter, Game, RuleError

FRENZY_STEPS = 3
DASH_STEPS = 3
HOUNDS_STEPS = 3


# ---------------------------------------------------------------- sparring/combat.py @ f4c26ca

def _medusa_after(game: Game, me: Fighter, foe: Fighter, card: Card, i_won: bool) -> None:
    ctrl = game.controllers[me.owner]
    t = card.title
    if t == "Gaze of Stone" and i_won:
        game.damage(foe, GAZE_DAMAGE)
    elif t == "Regroup":
        game.draw(me.owner, 2 if i_won else 1)
    elif t == "Dash" and me.alive:
        _optional_move(game, ctrl, me, DASH_STEPS)
    elif t == "Snipe":
        game.draw(me.owner, 1)
    elif t == "The Hounds of Mighty Zeus":
        for h in game.own(me.owner):
            if h.name == "Harpy":
                _optional_move(game, ctrl, h, HOUNDS_STEPS)
    elif t in ("Clutching Claws", "Hiss and Slither"):
        game.force_discard(foe.owner, 1, t, me.owner)


def _optional_move(game: Game, ctrl, fighter: Fighter, steps: int, through: bool = False) -> None:
    dest = ctrl.choose_move(game, fighter, steps, through)
    if dest is not None:
        game.move_fighter(fighter, dest, steps, through)


def check_scheme(game: Game, fighter: Fighter, card: Card, target: Fighter | None = None) -> None:
    if is_medusa_card(card) and card.title == "A Momentary Glance":
        if target is None or not target.alive or not game.board.share_zone(fighter.pos, target.pos):
            raise RuleError("A Momentary Glance necesita un luchador en la zona de Medusa")


def resolve_scheme(game: Game, player: int, fighter: Fighter, card: Card, target: Fighter | None = None) -> list[str]:
    if not is_medusa_card(card):
        return combat.resolve_scheme(game, player, fighter, card)
    ctrl = game.controllers[player]
    if card.title == "A Momentary Glance":
        game.damage(target, GLANCE_DAMAGE)
    elif card.title == "Winged Frenzy":
        for f in sorted(game.own(player), key=lambda x: x.fid):
            _optional_move(game, ctrl, f, FRENZY_STEPS, through=True)
        dead = [f for f in game.own(player, alive_only=False) if f.name == "Harpy" and not f.alive]
        medusa = game.hero(player)
        if dead:
            taken = {f.pos for f in game.fighters.values() if f.alive}
            options = sorted(s for s in game.board.spaces if s not in taken and game.board.share_zone(medusa.pos, s))
            spot = ctrl.choose_placement(game, dead[0], options)
            if spot is not None:
                dead[0].alive, dead[0].hp, dead[0].pos = True, 1, spot
    return []


# ---------------------------------------------------------------- sparring/state.py @ f4c26ca

def play_scheme(self: Game, player: int, fighter: Fighter, card: Card, **opts) -> None:
    if not card.is_scheme or not card.usable_by(fighter.name) or card not in self.players[player].hand:
        raise RuleError(f"{card.title} no se puede jugar con {fighter.fid}")
    check_scheme(self, fighter, card, **opts)
    self.use_action()
    self.discard_card(player, card, played=True)
    resolve_scheme(self, player, fighter, card, **opts)


def medusa_ability(self: Game, target: Fighter) -> None:
    medusa = self.hero_named("Medusa")
    if target.owner == medusa.owner or not target.alive or not self.board.share_zone(medusa.pos, target.pos):
        raise RuleError("objetivo invalido para la habilidad")
    self.damage(target, 1)


def use_ability(self: Game, player: int, trigger_id: str, target: Fighter | None = None) -> None:
    """The C5 entry point, answered the old way (the ability was only ever Medusa's gaze on a chosen target)."""
    assert trigger_id == "medusa_gaze" and target is not None
    medusa_ability(self, target)


# ---------------------------------------------------------------- sparring/combat_flow.py @ f4c26ca

def _is(card: Card, title: str, medusa: bool) -> bool:
    return card.title == title and is_medusa_card(card) == medusa


def feint(flow: CombatFlow, side: Side) -> None:
    _cancel_rival(flow, side)


def second_shot(flow: CombatFlow, side: Side) -> Await | None:
    answered, boost = flow.answer("second_shot")
    if not answered:
        return Await(PendingChoice("boost", side.fighter.owner, side.card.card_id))
    if boost is not None:
        _check_boost(boost)
        _add_boost(flow, side, boost)


def medusa_after(flow: CombatFlow, side: Side) -> None:
    _medusa_after(flow.game, side.fighter, side.rival, side.card, _i_won(flow, side))


# (rule, the production rule it went right before)
LEGACY_RULES = [
    (Rule("feint", Phase.IMMEDIATELY, "any", lambda flow, side: _is(side.card, FEINT, medusa=True) and not _dsl(flow, side),
          feint), "planned_recklessness"),
    (Rule("second_shot", Phase.DURING, "atk", lambda flow, side: _is(side.card, SECOND_SHOT, medusa=True) and not _dsl(flow, side),
          second_shot), "boost_this_attack"),
    (Rule("medusa_after", Phase.AFTER, "any", lambda flow, side: is_medusa_card(side.card) and not _dsl(flow, side),
          medusa_after), "bot_card_after"),
]


@contextmanager
def legacy(monkeypatch):
    """Inside: games are built with Medusa OUT of `fx.dsl_heroes` and her legacy rules and methods are in force."""
    with monkeypatch.context() as m:
        m.setattr(fx_state, "INTERPRETED_HEROES", frozenset())
        rules = list(combat_flow.RULES)
        for rule, before in LEGACY_RULES:
            rules.insert(next(i for i, r in enumerate(rules) if r.name == before), rule)
        m.setattr(combat_flow, "RULES", rules)
        m.setattr(Game, "play_scheme", play_scheme)
        m.setattr(Game, "use_ability", use_ability)
        yield
