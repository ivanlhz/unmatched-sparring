"""Combat facade and the schemes of the path without the interpreter. Every hero of the box and Medusa is in
`game.fx.dsl_heroes` by default (E2), whoever plays it: their cards resolve with sparring/effects. Only a save that
switched the interpreter off keeps the legacy path: Planned Recklessness and the value of On Earth As It Is In Hell
applied by the flow's legacy rules, the ONGOING bonus and the actions of a scheme by `resolve_scheme`."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cards import MEDUSA_BASE, Card, can_be_boost
from .state import Fighter, Game, RuleError

GAZE_DAMAGE = 8          # Gaze of Stone and A Momentary Glance: the AI weighs them; the effects data applies them
GLANCE_DAMAGE = 2

SECOND_SHOT = "Second Shot"
FEINT = "Feint"
PLANNED = "Planned Recklessness"
ON_EARTH = "On Earth As It Is In Hell"
FIGHT_OR_FLIGHT = "Fight Or Flight"
FIGHT_OR_FLIGHT_BONUS = 1


def is_medusa_card(card: Card) -> bool:
    return MEDUSA_BASE <= card.card_id < MEDUSA_BASE + 100


@dataclass
class CombatResult:
    attacker: str
    target: str
    atk_card: Card
    def_card: Card | None
    atk_value: int
    def_value: int
    damage: int
    attacker_won: bool
    cancelled: set[str] = field(default_factory=set)
    boost_card: Card | None = None
    human_effects: list[str] = field(default_factory=list)
    atk_parts: list[str] = field(default_factory=list)      # de donde sale el total del atacante (para anunciarlo)
    def_parts: list[str] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)        # efectos de despues del combate que el motor ya aplico
    bot_notes: list[str] = field(default_factory=list)      # lo que el bot no resuelve de sus cartas (se anuncia)


@dataclass
class CombatCtx:
    attacker: Fighter
    target: Fighter
    atk_card: Card
    def_card: Card | None
    atk_value: int
    def_value: int
    cancelled: set[str]


def _side_cards(ctx: CombatCtx):
    """(lado, luchador, carta, rival) en orden de resolucion: primero el defensor."""
    out = []
    if ctx.def_card is not None:
        out.append(("def", ctx.target, ctx.def_card, ctx.attacker))
    out.append(("atk", ctx.attacker, ctx.atk_card, ctx.target))
    return out


def resolve_combat(game: Game, att: Fighter, tgt: Fighter, atk_card: Card, def_card: Card | None,
                   values: tuple[int, int] = (0, 0), boost: Card | None = None) -> CombatResult:
    """Synchronous facade over CombatFlow. `boost`: the card the human put on the table for the BOOST of their attack
    (Second Shot); the bot reads it at "Continuar" and it arrives here after the defender's DURING."""
    from .combat_flow import CombatFlow, legacy_chooser
    flow = CombatFlow(game, att, tgt, atk_card, def_card, values)
    flow.drive(legacy_chooser(game, flow, boost))
    return flow.result


def can_boost(card: Card) -> bool:
    """The card lets its owner BOOST it for free in DURING COMBAT: from the hand (`may_boost` in the effects data:
    Second Shot, Out Of Time) or the bottom of the deck (Flame Lash)."""
    from .effects.modifiers import may_boost
    return not is_medusa_card(card) and (may_boost(card) or deck_boost(card))


def _check_boost(boost: Card) -> None:
    if not can_be_boost(boost):
        raise RuleError(f"{boost.title} no tiene valor de impulso: no se puede impulsar con ella")


def deck_boost(card: Card) -> bool:
    """Flame Lash: the BOOST is the card at the bottom of the deck, not one from the hand."""
    from .effects.modifiers import draws_bottom_for_boost
    return draws_bottom_for_boost(card)


_GAIN_ACTIONS = re.compile(r"\bGain (\d+|an?|one|two) actions?\b", re.IGNORECASE)
_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2}


def scheme_gain_actions(card: Card) -> int:
    """Acciones que da un plan al jugarlo: los «Gain N action(s)» fuera de un AFTER COMBAT (ese es de la carta de combate)."""
    text = card.text.split("AFTER COMBAT:")[0]
    return sum(int(w) if w.isdigit() else _WORDS[w.lower()] for w in _GAIN_ACTIONS.findall(text))


def resolve_scheme(game: Game, player: int, fighter: Fighter, card: Card) -> list[str]:
    """A scheme of a hero outside `fx.dsl_heroes`: the engine applies the ONGOING bonus and the actions it grants;
    the human resolves the rest of the text (returned)."""
    if card.title == FIGHT_OR_FLIGHT:
        game.add_combat_bonus(player, FIGHT_OR_FLIGHT_BONUS, FIGHT_OR_FLIGHT)
    game.grant_actions(scheme_gain_actions(card))
    return [f"{card.title}: {card.text}"]
