"""Combate y esquemas de la ruta sin interprete. Los heroes de `game.fx.dsl_heroes` (Medusa) resuelven sus cartas con
sparring/effects; de los demas, el humano resuelve el texto (se devuelve en `human_effects`), salvo Planned
Recklessness y el valor de On Earth As It Is In Hell, que alteran el calculo del combate."""
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


_MOMENT = re.compile(r"(IMMEDIATELY|DURING COMBAT|AFTER COMBAT):")
_RIVAL_OPTION = re.compile(r"(your|the) opponent may", re.IGNORECASE)
# momentos de las cartas no-Medusa que el motor ya resuelve solo, por titulo (lo demas del texto no esta codificado)
CODED_MOMENTS = {"Horseshoes And Hand Grenades": {"AFTER COMBAT"}, ON_EARTH: {"DURING COMBAT", "AFTER COMBAT"},
                 "Flame Lash": {"AFTER COMBAT"}, PLANNED: {"IMMEDIATELY"}}


def text_parts(card: Card) -> list[tuple[str, str]]:
    """(momento, texto) de cada parte del texto de la carta; el texto suelto antes del primer momento va con ''."""
    pieces = _MOMENT.split(card.text)
    out = [("", pieces[0].strip())] if pieces[0].strip() else []
    out += [(pieces[i], pieces[i + 1].strip()) for i in range(1, len(pieces) - 1, 2)]
    return out


def _announce_bot_card(card: Card, result: CombatResult) -> None:
    """Toda parte del texto de una carta del bot que el motor no resuelve se anuncia con su momento: como efecto que
    el bot ignora, o como opcion del humano si el texto se la da al rival (Incinerate)."""
    coded = CODED_MOMENTS.get(card.title, set())
    if coded and card.title == PLANNED:
        result.applied.append(f"{card.title}: aplicado ({card.text})")
    for moment, text in text_parts(card):
        if moment in coded or not text:
            continue
        label = f" ({moment})" if moment else ""
        if _RIVAL_OPTION.search(text):
            result.bot_notes.append(f"{card.title}: tu opcion{label}: {text} Resuelvela a mano.")
        else:
            result.bot_notes.append(f"{card.title}: el bot ignora este efecto{label}: {text}")


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


def after_text(card: Card) -> str:
    """Solo la parte AFTER COMBAT del texto de la carta (lo de IMMEDIATELY y DURING ya lo resuelve el calculo)."""
    head, sep, tail = card.text.partition("AFTER COMBAT:")
    return tail.strip() if sep else ""


def _liz_after(game: Game, card: Card, result: CombatResult) -> bool:
    """Flame Lash: AFTER COMBAT gana 1 accion (siempre es la carta del atacante, en su turno)."""
    if card.title == "Flame Lash":
        game.grant_actions(1)
        result.applied.append(f"{card.title}: ganas 1 accion")
        return True
    return False


def _hellboy_after(game: Game, me: Fighter, card: Card, i_won: bool, result: CombatResult) -> bool:
    """Efectos de despues del combate de Hellboy que no necesitan ninguna decision ni informacion oculta del
    humano: se aplican aqui. Los demas (robar, mover, elegir) siguen siendo del humano. True si se aplico."""
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


def resolve_scheme(game: Game, player: int, fighter: Fighter, card: Card) -> list[str]:
    """A scheme of a hero outside `fx.dsl_heroes`: the engine applies the ONGOING bonus and the actions it grants;
    the human resolves the rest of the text (returned)."""
    if card.title == FIGHT_OR_FLIGHT:
        game.add_combat_bonus(player, FIGHT_OR_FLIGHT_BONUS, FIGHT_OR_FLIGHT)
    game.grant_actions(scheme_gain_actions(card))
    return [f"{card.title}: {card.text}"]
