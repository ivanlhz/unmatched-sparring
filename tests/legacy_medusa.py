"""Verbatim copies of the engine's Medusa code as of f4c26ca (the last commit before C5), kept as the oracle of
tests/test_medusa_dsl_diff.py: `_medusa_after` and `_optional_move` (sparring/combat.py), the Medusa branch of
`resolve_scheme` with `check_scheme`, `Game.medusa_ability` and `Game.play_scheme` (sparring/state.py) and the three
combat-flow rules `feint`, `second_shot`, `medusa_after` (sparring/combat_flow.py).

`legacy(monkeypatch)` turns a test into the pre-C5 engine: nobody in `fx.dsl_heroes` by default (E2 put the box heroes
of both sides there) and the legacy rules and methods installed, the human's after-combat path of 32e0221 included
(`human_card_after`, `_hellboy_after`, `_liz_after`, `after_text`); everything else is the production code."""
from __future__ import annotations

from contextlib import contextmanager

from sparring import combat, combat_flow
from sparring.cards import Card
from sparring.combat import (GAZE_DAMAGE, GLANCE_DAMAGE, ON_EARTH, PLANNED, SECOND_SHOT, FEINT, CombatResult, _check_boost,
                             can_boost, is_medusa_card)
from sparring.combat_flow import Await, CombatFlow, PendingChoice, Phase, Rule, Side, _add_boost, _cancel_rival, _dsl, _i_won
from sparring.effects import state as fx_state
from sparring.state import Fighter, Game, RuleError

FRENZY_STEPS = 3
DASH_STEPS = 3
HOUNDS_STEPS = 3
_production_play_scheme = Game.play_scheme


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
    if not is_medusa_card(card) and self.players[player].hero.slug in self.fx.dsl_heroes:
        return _production_play_scheme(self, player, fighter, card, **opts)    # E2: a box hero kept interpreted (`keep`)
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


# ---------------------------------------------------------------- sparring/combat.py @ 32e0221 (deleted by E2)

def after_text(card: Card) -> str:
    """Only the AFTER COMBAT part of the card text (IMMEDIATELY and DURING are already resolved by the calculation)."""
    head, sep, tail = card.text.partition("AFTER COMBAT:")
    return tail.strip() if sep else ""


def _liz_after(game: Game, card: Card, result: CombatResult) -> bool:
    """The human's Flame Lash (legacy path until E2): AFTER COMBAT gains 1 action (always the attacker's card)."""
    if card.title == "Flame Lash":
        game.grant_actions(1)
        result.applied.append(f"{card.title}: ganas 1 accion")
        return True
    return False


def _hellboy_after(game: Game, me: Fighter, card: Card, i_won: bool, result: CombatResult) -> bool:
    """The human's Hellboy after-combat effects that need no decision nor hidden information (legacy path until E2):
    applied here. The rest (draws, moves, choices) stay with the human. True if something was applied."""
    if card.title == "Horseshoes And Hand Grenades" and me.alive:
        hit = [f for f in game.zone_mates(me)]
        for f in hit:
            game.damage(f, 1)
        names = ", ".join(f.fid for f in hit) or "nadie"
        result.applied.append(f"{card.title}: 1 de dano a cada otro luchador de la zona ({names})")
        return True
    if card.title == ON_EARTH:
        if not i_won:
            hb = game.hero_named("Hellboy")
            before = hb.hp
            game.heal(hb, 2)
            result.applied.append(f"{card.title}: Hellboy recupera {hb.hp - before:g} PV (perdio el combate)")
        else:
            result.applied.append(f"{card.title}: no recupera (no perdio el combate)")
        return True
    return False


# ---------------------------------------------------------------- sparring/combat_flow.py @ 32e0221 (deleted by E2)

def human_card_after(flow: CombatFlow, side: Side) -> None:
    """The human's card of a hero outside the interpreter (the box until E2): the engine applies what needs no
    decision of theirs, the rest of the text is returned for them to resolve on the table."""
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
          medusa_after), "bot_card_outside_the_interpreter"),      # D1 replaced bot_card_after at the same spot
    (Rule("human_card_after", Phase.AFTER, "any", lambda flow, side: not _dsl(flow, side), human_card_after),
     "human_card_outside_the_interpreter"),                          # E2 reduced it to the text-only rule
]


@contextmanager
def legacy(monkeypatch, keep=()):
    """Inside: games are built with Medusa OUT of `fx.dsl_heroes` (and every other hero but `keep`) and her legacy
    rules and methods are in force."""
    with monkeypatch.context() as m:
        m.setattr(fx_state, "INTERPRETED_HEROES", frozenset(keep))
        rules = list(combat_flow.RULES)
        for rule, before in LEGACY_RULES:
            rules.insert(next(i for i, r in enumerate(rules) if r.name == before), rule)
        rules = [r for r in rules if r.name != "human_card_outside_the_interpreter"]
        m.setattr(combat_flow, "RULES", rules)
        m.setattr(Game, "play_scheme", play_scheme)
        m.setattr(Game, "use_ability", use_ability)
        yield
