"""Rosie the Riveter's FREEDOM XK-II MECH SUIT: the row of four upgrades (docs/heroes/rosie-the-riveter.md).

A hero whose HeroDef carries a passive `{"effect": "upgrades", "row": [...]}` has that row of upgrade tokens. The upgrades start in
the order of `row`, all inactive. To ACTIVATE one, the leftmost inactive upgrade is flipped; to DEACTIVATE one, the leftmost active
upgrade is flipped down and moved to the end of the row (the rules card of the bag). The active upgrades are therefore always the
first of the row, and the whole state is two numbers, kept as the hero's ability counters of the effects file:

  - `upgrades`: how many are active (0..4); the cards that only count upgrades read it with the plain DSL `counter`;
  - `upgrade_shift`: how many times the row has turned (0..3); `row` rotated left by it is the order on the table.

What each upgrade does is data too: the `grants` of its row entry, read here.
  - `attack_bonus` (Sedgley Fist Gun): added to the value of the hero's attacks in DURING (`attack_bonus_parts`, the plugin `rosie:attack_bonus`);
  - `ranged` (Whizbang): the hero is a ranged hero while it is active (`sync` keeps `Fighter.ranged` in step with the counters);
  - `maneuver_move` (Merlin Engine): spaces added to the hero's move value, which only a Maneuver reads (`sync` keeps `Fighter.move` in step);
  - `draw_after_attack` (Cavity Magnetron): the trigger `cavity_magnetron` of the effects file reads it through the plugin test
    `rosie:upgrade`.
Only the hero fighter has them, never the sidekick ("Rosie is a ranged hero", "Rosie's attacks")."""
from __future__ import annotations

PASSIVE = "upgrades"
COUNT = "upgrades"
SHIFT = "upgrade_shift"


def passive(game, player: int) -> dict | None:
    """The `upgrades` passive of `player`'s hero, None for any other hero."""
    for p in game.players[player].hero.passives:
        if p.get("effect") == PASSIVE:
            return p
    return None


def has(game, player: int) -> bool:
    return passive(game, player) is not None


def size(game, player: int) -> int:
    p = passive(game, player)
    return len(p["row"]) if p else 0


def count(game, player: int) -> int:
    """How many upgrades are active."""
    return game.fx.counter_value(player, COUNT) if has(game, player) else 0


def row(game, player: int) -> list[dict]:
    """The upgrades in the order they lie on the table now (left to right)."""
    p = passive(game, player)
    if p is None:
        return []
    r = list(p["row"])
    k = game.fx.counter_value(player, SHIFT) % len(r)
    return r[k:] + r[:k]


def active(game, player: int) -> list[dict]:
    return row(game, player)[:count(game, player)]


def inactive(game, player: int) -> list[dict]:
    return row(game, player)[count(game, player):]


def is_active(game, player: int, upgrade_id: str) -> bool:
    return any(u["id"] == upgrade_id for u in active(game, player))


def granted(game, player: int, key: str) -> list:
    """The values of `grants[key]` of every active upgrade that has one."""
    return [u["grants"][key] for u in active(game, player) if key in (u.get("grants") or {})]


def attack_bonus_parts(game, fighter) -> list[tuple[int, str]]:
    """(bonus, label) the active upgrades add to the value of `fighter`'s attacks: only the hero's own (`rosie:attack_bonus` adds them in DURING)."""
    if not fighter.hero or not has(game, fighter.owner):
        return []
    return [(int(u["grants"]["attack_bonus"]), u["name"].upper()) for u in active(game, fighter.owner) if "attack_bonus" in (u.get("grants") or {})]


def sync(game, player: int | None = None) -> None:
    """The hero fighter is ranged when its printed attack is, or while an active upgrade makes it so (Whizbang), and its move value is the
    printed one plus what the active upgrades add to a Maneuver (Merlin Engine: "when you maneuver, Rosie may move 1 additional space").
    The move value is only read where a Maneuver is planned or done, so it is the one place that bonus has to live. Called wherever the
    counters change (`EffectState.set_counter`) and when a save is loaded."""
    for who in (0, 1) if player is None else (player,):
        if not has(game, who):
            continue
        hero, printed = game.hero(who), game.players[who].hero
        hero.ranged = printed.ranged or any(granted(game, who, "ranged"))
        hero.move = printed.move + sum(int(n) for n in granted(game, who, "maneuver_move"))


def activate(game, player: int, amount: int = 1) -> list[dict]:
    """Flips the `amount` leftmost inactive upgrades up. Returns the ones flipped (none when all are active)."""
    flipped = inactive(game, player)[:amount]
    game.fx.set_counter(player, COUNT, count(game, player) + len(flipped))
    return flipped


def deactivate(game, player: int) -> dict | None:
    """Flips the leftmost active upgrade down and moves it to the end of the row. Returns it, None when none is active."""
    now = count(game, player)
    if now <= 0:
        return None
    flipped = row(game, player)[0]
    game.fx.set_counter(player, COUNT, now - 1)
    game.fx.set_counter(player, SHIFT, (game.fx.counter_value(player, SHIFT) + 1) % size(game, player))
    return flipped


def names(game, player: int, upgrades: list[dict]) -> str:
    return ", ".join(u["name"] for u in upgrades)
