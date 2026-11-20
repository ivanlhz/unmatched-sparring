"""The DOUBLE ATTACK in the AIs (docs/combat-flow.md "Double attack").

The second attack of a card is the `second_attack` op of its AFTER (docs/effects-dsl.md section 45). The AIs read that data: the
value of the second part given the printed value of the defense card the rival played against the first (`second_value`), what the
card is expected to add (`second_part`, used by the heuristic's `attack_outcome`; the search needs no estimate, its rollouts play the second
attack through the engine) and how to defend the second part (`greedy_defense`, the rollouts' defender). The live bot defends the second part with the heuristic's own
defense choice, fed the exact value (`MedusaAI.choose_second_defense`): the value is public, so there is nothing to sample.

A condition inside the card's AFTER is read for the only shape the box has (`test: card` on the rival's card: "if your opponent played a
defense card"); any other condition counts as not met, so an unknown card is never overvalued."""
from __future__ import annotations

from typing import Callable

from .effects.model import EffectError, load_effects, walk_ops


def _second_ops(slug: str, title: str) -> tuple:
    """The `after` ops of the card that hold a `second_attack`, as the data wrote them (empty: not a double-attack card)."""
    try:
        ops = load_effects(slug).moment_ops(title, "after")
    except EffectError:
        return ()
    return tuple(ops) if any(o["op"] == "second_attack" for o in walk_ops(ops)) else ()


def has_second(game, owner: int, card) -> bool:
    return bool(_second_ops(game.players[owner].hero.slug, card.title))


def second_value(game, owner: int, card, defense_value: int | None) -> int:
    """What the card's second attack is worth when the rival answered the first part with a card of printed value `defense_value`
    (None: no card). 0 when the card has none or its condition is not met."""
    return _value(_second_ops(game.players[owner].hero.slug, card.title), defense_value)


def _value(ops, defense_value: int | None) -> int:
    for op in ops:
        if op["op"] == "second_attack":
            amount = op["amount"]
            if isinstance(amount, dict) and amount.get("attr") == "value" and amount.get("of") == "opponent_card":
                return max(0, defense_value or 0) * amount.get("times", 1)
            return int(amount) if isinstance(amount, int) and not isinstance(amount, bool) else 0
        if op["op"] == "if" and _holds(op["condition"], defense_value):
            if n := _value(op.get("then", ()), defense_value):
                return n
    return 0


def _holds(condition: dict, defense_value: int | None) -> bool:
    if condition.get("test") == "card" and condition.get("card") == "opponent_card":
        return defense_value is not None
    return False


def second_part(game, attacker, target, card, defense_value: int | None, spent: float,
                dist: list[tuple[float, int | None]]) -> tuple[float, float]:
    """(expected extra damage, probability of killing) the second attack adds once the first part left `target` with `spent` damage taken
    (`hp - spent` is what it still has). `dist`: the (probability, printed value) of the card the rival may defend the second part with,
    the same one the first part was weighed against."""
    n = second_value(game, attacker.owner, card, defense_value)
    left = target.hp - spent
    if n <= 0 or left <= 0:
        return 0.0, 0.0
    atk = n + second_bonus(game, attacker, target)
    damage = kill = 0.0
    for p, dv in dist:
        net = game.combat_damage_taken(target, max(0, atk - (dv or 0)))
        damage += p * min(net, left)
        kill += p * (net >= left)
    return damage, kill


def second_bonus(game, attacker, target) -> int:
    """What the attacker adds to the second attack: its hero passives and the fighter's persistent attack bonus, as `CombatFlow._reveal` adds
    them for a second attack (never the "your next attack" bonus: the first part used it)."""
    bonus = sum(n for n, _ in game.attack_bonus_parts(attacker, target))
    if game.fx.statuses:
        from .effects.modifiers import fighter_attack_bonus
        bonus += sum(n for n, _ in fighter_attack_bonus(game.fx, attacker.fid))
    return bonus


def greedy_defense(game, hand, attacker, target, value: int, worth: Callable) -> object | None:
    """The card of `hand` that spares the most damage against a second attack of `value`, less what the card is worth (the search's rollouts:
    cheap and deterministic). None when no card pays for itself."""
    atk = value + second_bonus(game, attacker, target)
    now = min(game.combat_damage_taken(target, atk), target.hp)
    best, best_gain = None, 0.0
    for c in hand:
        if not (c.can_defend and c.usable_by(target.name)):
            continue
        net = min(game.combat_damage_taken(target, max(0, atk - (c.value or 0))), target.hp)
        gain = (now - net) - 0.3 * worth(c)
        if gain > best_gain:
            best, best_gain = c, gain
    return best


def journal_note(game, owner: int, act) -> dict:
    """What the decision journal adds to the line of an attack with a double-attack card: the value of its second part against no defense
    and against a defense card of 2 and of 4 (a condition or a printed value makes it differ)."""
    card = getattr(act, "card", None)
    if act.kind != "attack" or card is None or not has_second(game, owner, card):
        return {}
    return {"second_attack": {"value": {"no_defense": second_value(game, owner, card, None),
                                        "defense_2": second_value(game, owner, card, 2),
                                        "defense_4": second_value(game, owner, card, 4)}}}


def possible_double_titles(game, owner: int) -> list[str]:
    """Titles of the double-attack cards `owner` may still play (its deck list minus the public piles): what a bot defending a face-down
    attack weighs, and what its decision journal says it weighed."""
    st = game.players[owner]
    return sorted({c.title for c in st.full_set if c not in st.gone and c.can_attack and has_second(game, owner, c)})
