"""Immediate wins with a known direct-damage scheme and, if needed, one maneuver."""
from __future__ import annotations

import random
from functools import lru_cache

from ..ai_medusa import scheme_fighter
from ..cards import can_be_boost
from ..effects.model import load_effects


@lru_cache(maxsize=None)
def _scheme_zone_damage(slug: str, title: str) -> int:
    effects = load_effects(slug).cards.get(title)
    ops = effects.moments.get("scheme", []) if effects else []
    if len(ops) != 1:
        return 0
    op = ops[0]
    target = op.get("target")
    amount = op.get("amount")
    if (op["op"] == "damage" and isinstance(amount, int) and isinstance(target, dict)
            and target.get("side") in ("any", "enemy") and target.get("where") == {"zone_of": "hero"}):
        return amount
    return 0


def _probe(state):
    trial = state.clone()
    trial.game.rng = random.Random(0)
    trial.game.rng.setstate(state.game.rng.getstate())
    return trial


def _lethal_scheme(state, titles):
    game = state.game
    attacker = game.turn
    if game.paid_actions < 1 or not game.board.share_zone(game.hero(attacker).pos, game.hero(state.observer).pos):
        return None
    for move in state._scheme_moves(attacker):
        if move[1] in titles:
            trial = _probe(state)
            trial.apply(move)
            if trial.game.winner == attacker:
                return move
    return None


def _lethal_placement(state, titles):
    if not titles:
        return None
    game = state.game
    attacker = game.turn
    hero = game.hero(attacker)
    victim = game.hero(state.observer)
    for dest in sorted(state._hero_options(hero)):
        if not game.board.share_zone(dest, victim.pos):
            continue
        move = ("place", dest, "stay")
        trial = _probe(state)
        trial.apply(move)
        if trial.game.turn == attacker and trial.phase == "action" and not trial.is_terminal():
            if _lethal_scheme(trial, titles):
                return move
    return None


def known_lethal_reply(state):
    """First move of a verified win. A card drawn by the maneuver cannot supply the scheme or its boost."""
    game = state.game
    attacker = game.turn
    if attacker == state.observer or state.pending or game.paid_actions < 1:
        return None
    if state.phase not in ("action", "maneuver_place"):
        return None
    if game.effect_shield.get(state.observer) == game.turn_no:
        return None
    rival = game.players[attacker]
    seen = game.players[state.observer].known
    if not seen.seen or not game.fx.interprets(attacker):
        return None
    known = [card for card in seen.cards(rival) if card in rival.hand]
    victim = game.hero(state.observer)
    schemes = [card for card in known if card.is_scheme and _scheme_zone_damage(rival.hero.slug, card.title) >= victim.hp
               and scheme_fighter(game, attacker, card) is not None]
    if not schemes:
        return None
    titles = {card.title for card in schemes}
    if state.phase == "maneuver_place":
        if game.paid_actions < 2:
            return None
        spent = next((card for card in rival.hand if card.title == state.partial[0]), None)
        return _lethal_placement(state, {card.title for card in schemes if card != spent})
    move = _lethal_scheme(state, titles)
    if move or game.paid_actions < 2:
        return move
    for boost in (None, *(card for card in known if can_be_boost(card))):
        remaining = {card.title for card in schemes if card != boost}
        if not remaining:
            continue
        move = ("maneuver", boost.title if boost else None)
        trial = _probe(state)
        trial.apply(move)
        if trial.game.turn != attacker or trial.is_terminal():
            continue
        if trial.phase == "maneuver_place" and _lethal_placement(trial, remaining):
            return move
        if trial.phase == "action" and _lethal_scheme(trial, remaining):
            return move
    return None
