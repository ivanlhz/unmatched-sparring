"""Eredin's KING OF THE WILD HUNT and the two card tags that hang from it (docs/heroes/eredin.md).

A hero whose HeroDef carries a passive `{"effect": "enraged", "combat_bonus": 1, "move": 3}` is ENRAGED while none of his
sidekicks is alive ("While all of your Red Riders are defeated, Eredin is ENRAGED"). Then
  - every combat card of his owner is worth `combat_bonus` more (`bonus_parts`, read by `Game.attack_bonus_parts`,
    `Game.defense_bonus_parts` and `Game.attack_bonus`, the three places the engine adds a hero's passive value);
  - the hero's move value is `move` (`sync_move`: the fighter's `move` follows the roster, called wherever a fighter falls or
    returns: `Game.defeat`, `Game.damage`, the `revive` op, a save loaded, a fighter put back by hand);
  - the cards tagged `attack_if_enraged` (Implacable) may be played as an attack and those tagged `any_space_if_enraged`
    (Foul Purpose) may target a fighter in any space (`may_attack_with`, `reaches_any_space`).

The condition itself ("If Eredin is ENRAGED" in card texts) is plain DSL (`not exists` own sidekick) so the data stays readable;
this module is the engine's half of the same definition."""
from __future__ import annotations

ATTACK_TAG = "attack_if_enraged"
ANY_SPACE_TAG = "any_space_if_enraged"


def passive(game, player: int) -> dict | None:
    """The `enraged` passive of `player`'s hero, None for any other hero."""
    for p in game.players[player].hero.passives:
        if p.get("effect") == "enraged":
            return p
    return None


def is_enraged(game, player: int) -> bool:
    """The hero has the passive and every one of his sidekicks is defeated (a reserve sidekick is not alive either)."""
    return passive(game, player) is not None and not any(f.alive for f in game.own(player, alive_only=False) if not f.hero)


def bonus_parts(game, player: int) -> list[tuple[int, str]]:
    """(bonus, label) the passive adds to every combat card of `player` right now."""
    p = passive(game, player)
    if p is None or not is_enraged(game, player):
        return []
    return [(int(p["combat_bonus"]), p["id"].replace("_", " ").upper())]


def bonus_total(game, player: int) -> int:
    return sum(n for n, _ in bonus_parts(game, player))


def sync_move(game, player: int | None = None) -> None:
    """The hero fighter's move value is the printed one, or the passive's while he is enraged."""
    for who in (0, 1) if player is None else (player,):
        p = passive(game, who)
        if p is None:
            continue
        hero = game.hero(who)
        printed = game.players[who].hero.move
        hero.move = max(printed, int(p["move"])) if is_enraged(game, who) else printed


def may_attack_with(game, player: int, card) -> bool:
    """`card` may be played as an attack by `player`: an attack or versatile card, or a card that says "if ENRAGED you may
    play this card as an attack" while the hero is enraged."""
    return card.can_attack or (ATTACK_TAG in card.tags and is_enraged(game, player))


def reaches_any_space(game, player: int, card) -> bool:
    """`card` targets a fighter in any space (Foul Purpose, face up) while the hero is enraged."""
    return ANY_SPACE_TAG in card.tags and is_enraged(game, player)


def may_name_any_space(game, player: int) -> bool:
    """The hero is enraged and his deck holds a card that targets any space: he may name a far target before the card is on the table."""
    return is_enraged(game, player) and any(ANY_SPACE_TAG in c.tags for c in game.players[player].full_set)


def far_shot(game, attacker, target, card) -> bool:
    """`card` is played against a target out of the attacker's usual reach: it lies face up (Foul Purpose)."""
    return (reaches_any_space(game, attacker.owner, card) and attacker.pos is not None and target.pos is not None
            and not game.board.can_reach_target(attacker.pos, target.pos, attacker.ranged, attacker.reach))


def reach_combat(run, game, player: int) -> None:
    """The hero became enraged in the middle of a combat (a Red Rider paid for Icy Guile's DURING): the bonus the combat added at
    the reveal did not include it, so the card `player` has in play gets it now."""
    flow = getattr(run, "flow", None)
    if flow is None or flow.ctx is None:
        return
    from .effects.modifiers import add_value
    for side, fighter, card in (("atk", flow.att, flow.atk_card), ("def", flow.tgt, flow.def_card)):
        if fighter.owner == player and card is not None:
            for n, label in bonus_parts(game, player):
                add_value(flow, side, n, label)
