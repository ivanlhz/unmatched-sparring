"""Verbatim copy of resolve_combat as of ff6fa3c, kept as the oracle of the differential tests
(tests/test_combat_flow_diff.py). Helpers are imported from sparring.combat."""
from __future__ import annotations

from sparring.cards import Card
from sparring.combat import (FEINT, ON_EARTH, PLANNED, SECOND_SHOT, CombatCtx, CombatResult, _announce_bot_card,
                             _check_boost, _hellboy_after, _liz_after, _medusa_after, _side_cards, after_text,
                             can_boost, deck_boost, is_medusa_card)
from sparring.state import ANUNG, Fighter, Game, RuleError


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
        if is_medusa_card(card) and card.title == FEINT:
            ctx.cancelled.add(other)
        elif not is_medusa_card(card) and card.title == PLANNED:
            game.effect_shield[fighter.owner] = game.turn_no
            if game.form(fighter.owner) != ANUNG:
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
