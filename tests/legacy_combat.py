"""Copy of resolve_combat as of ff6fa3c (plus the uncancelable rule of the C2 review), kept as the oracle of the differential tests
(tests/test_combat_flow_diff.py). Helpers are imported from sparring.combat; the Medusa ones C5 deleted come from
tests/legacy_medusa.py (verbatim copies); the bot's announcement path D1 deleted (`_announce_bot_card`, `text_parts`,
`CODED_MOMENTS`, as of 71e43bb) lives below."""
from __future__ import annotations

import re

from legacy_medusa import _medusa_after
from sparring.cards import Card
from sparring.combat import (FEINT, ON_EARTH, PLANNED, SECOND_SHOT, CombatCtx, CombatResult,
                             _check_boost, _hellboy_after, _liz_after, _side_cards, after_text,
                             can_boost, deck_boost, is_medusa_card)
from sparring.effects.modifiers import is_uncancelable
from sparring.state import ANUNG, Fighter, Game, RuleError


# ---------------------------------------------------------------- sparring/combat.py @ 71e43bb (deleted by D1)

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


# ---------------------------------------------------------------- sparring/combat.py @ ff6fa3c


def resolve_combat(game: Game, att: Fighter, tgt: Fighter, atk_card: Card, def_card: Card | None,
                   values: tuple[int, int] = (0, 0), boost: Card | None = None) -> CombatResult:
    """`boost`: carta de impulso que el humano ha puesto en su descarte para el BOOST de su ataque (Second Shot); el
    bot la lee de la mesa en el paso "Continuar" y entra aqui, tras el DURING del defensor."""
    if def_card is not None:
        game.check_defense_card(tgt, def_card)
        if def_card not in game.players[tgt.owner].hand:
            raise RuleError(f"{def_card.title} no esta en la mano de {tgt.fid}")
    pa, pd = att.owner, tgt.owner
    game.take_from_hand(pa, atk_card)
    if def_card is not None:
        game.take_from_hand(pd, def_card)
    played = [(pa, atk_card)] + ([(pd, def_card)] if def_card else [])

    bonus_parts = game.attack_bonus_parts(att)   # pasivas del heroe (Hellboy en ANUNG UN RAMA: +2)
    bonus = sum(n for n, _ in bonus_parts)
    atk_value = (atk_card.value or 0) + values[0] + bonus
    def_value = (def_card.value or 0) if def_card else 0
    def_value += values[1]
    # ONGOING del defensor: suma al valor de su carta (tambien si vale 0 o se cancela); sin carta no hay valor al que sumar
    def_bonus_parts = game.combat_bonus_parts(pd) if def_card is not None else []
    def_bonus = sum(n for n, _ in def_bonus_parts)
    def_value += def_bonus
    ctx = CombatCtx(att, tgt, atk_card, def_card, atk_value, def_value, set())
    result = CombatResult(att.fid, tgt.fid, atk_card, def_card, atk_value, def_value, 0, False)
    result.atk_parts = [f"{atk_card.title} ({atk_card.value or 0})"]
    result.atk_parts += [f"{label} (+{n})" for n, label in bonus_parts if n]
    if values[0]:
        result.atk_parts.append(f"valor extra ({values[0]:+d})")

    # IMMEDIATELY: primero el defensor; lo cancelado no llega a resolver
    for side, fighter, card, _ in _side_cards(ctx):
        if side in ctx.cancelled:
            continue
        other = "atk" if side == "def" else "def"
        other_card = atk_card if other == "atk" else def_card
        uncancelable = other_card is not None and is_uncancelable(other_card)      # review of C2: Incinerate
        if is_medusa_card(card) and card.title == FEINT:
            if not uncancelable:
                ctx.cancelled.add(other)
        elif not is_medusa_card(card) and card.title == PLANNED:
            game.effect_shield[fighter.owner] = game.turn_no
            if game.form(fighter.owner) != ANUNG and not uncancelable:
                ctx.cancelled.add(other)

    # DURING
    if def_card is not None and "def" not in ctx.cancelled and not is_medusa_card(def_card) and def_card.title == ON_EARTH:
        ctx.def_value = game.destiny_count(pd) + values[1] + def_bonus
    elif def_card is not None and "def" in ctx.cancelled and def_card.title == ON_EARTH and not is_medusa_card(def_card):
        ctx.def_value = values[1] + def_bonus
    if def_card is not None:
        result.def_parts = [f"{def_card.title} ({ctx.def_value - values[1] - def_bonus})"]
        if "def" in ctx.cancelled:
            result.def_parts[0] += " cancelada"
        result.def_parts += [f"{label} (+{n})" for n, label in def_bonus_parts if n]
    if values[1]:
        result.def_parts.append(f"valor extra ({values[1]:+d})")
    if "atk" not in ctx.cancelled and is_medusa_card(atk_card) and atk_card.title == SECOND_SHOT:
        boost = game.controllers[pa].choose_combat_boost(game, ctx)
        if boost is not None:
            _check_boost(boost)
            game.discard_card(pa, boost)
            ctx.atk_value += boost.boost
            result.boost_card = boost
            result.atk_parts.append(f"potencia con {boost.title} (+{boost.boost})")

    if boost is not None and "atk" not in ctx.cancelled and can_boost(atk_card):
        if not deck_boost(atk_card):          # Flame Lash: the bottom deck card adds whatever it is worth, even 0
            _check_boost(boost)
        game.discard_card(pa, boost)
        ctx.atk_value += boost.boost
        result.boost_card = boost
        result.atk_parts.append(f"potencia con {boost.title} (+{boost.boost})")

    damage = max(0, ctx.atk_value - ctx.def_value)
    game.damage(tgt, damage, "combat")
    won = damage >= 1
    result.atk_value, result.def_value, result.damage, result.attacker_won = ctx.atk_value, ctx.def_value, damage, won
    result.cancelled = set(ctx.cancelled)

    # AFTER COMBAT: primero el defensor
    if game.winner is None:
        for side, fighter, card, rival in _side_cards(ctx):
            if side in ctx.cancelled:
                continue
            i_won = won == (side == "atk")
            if is_medusa_card(card):
                _medusa_after(game, fighter, rival, card, i_won)
            elif fighter.owner == game.bot_player:    # nunca se le pide al humano resolver un efecto del bot
                _hellboy_after(game, fighter, card, i_won, result)
                _liz_after(game, card, result)
                _announce_bot_card(card, result)
            elif not (_hellboy_after(game, fighter, card, i_won, result) or _liz_after(game, card, result)):
                after = after_text(card)
                if after:
                    result.human_effects.append(f"{card.title}: {after}")
                elif card.title == PLANNED:
                    result.applied.append(f"{card.title}: aplicado ({card.text})")
                elif card.text.strip() and not can_boost(card):   # el BOOST de Second Shot ya se resolvio en el DURING
                    result.human_effects.append(f"{card.title}: {card.text}")
                # una carta sin texto (Excalibur, Service Pistol) no tiene efecto que resolver
    for owner, card in played:
        game.players[owner].discard.append(card)
    return result
