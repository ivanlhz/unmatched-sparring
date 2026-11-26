"""Elektra's first life (docs/heroes/elektra.md, "The new engine state"): fighters taken off the board that are NOT defeated.

`Game._fall` (the one place every defeat goes through) asks `intercept_defeat` first. For Elektra's hero fighter in her first life it removes
her and every Hand on the board instead of defeating her: `Fighter.off_board`, `alive` False, `pos` None, no `fighter_defeated` event, no
winner. The ability counter `life` (`data/heroes/effects/elektra.json`) says where she is: 0 first life, 1 off the board, 2 resurrected.
The Resurrect itself is the trigger `resurrect` of her effects file; `release` is its first step."""
from __future__ import annotations

from .effects import table

SLUG = "elektra"
LIFE = "life"
FIRST_LIFE, OFF_BOARD, RESURRECTED = 0, 1, 2
RESURRECTED_HEALTH = 9


def is_elektra(game, player: int) -> bool:
    return game.players[player].hero.slug == SLUG


def life(game, player: int) -> int:
    return game.fx.counter_value(player, LIFE)


def intercept_defeat(game, fighter) -> bool:
    """True when `fighter` was about to be defeated and is removed from the board instead (her first life only)."""
    owner = fighter.owner
    if not fighter.hero or not is_elektra(game, owner) or life(game, owner) != FIRST_LIFE:
        return False
    game.fx.set_counter(owner, LIFE, OFF_BOARD)
    removed = [fighter] + [f for f in game.own(owner) if f is not fighter]
    for f in removed:
        f.died_at = f.pos if f.pos is not None else f.died_at       # the space it left; `select.defeated` still says "not defeated" while `off_board`
        f.alive, f.pos, f.off_board = False, None, True
    fighter.hp = 0
    game.log.append(f"{fighter.fid} removed from the board (not defeated)")
    table.intent(game, op="off_board", owner=owner, fids=[f.fid for f in removed])
    return True


def release(game, player: int) -> list:
    """Resurrect, first step: the dial flips (`life` 2, nine health at most) and the removed fighters can be returned by `revive`."""
    game.fx.set_counter(player, LIFE, RESURRECTED)
    hero = game.hero(player)
    hero.max_hp = RESURRECTED_HEALTH
    freed = [f for f in game.own(player, alive_only=False) if f.off_board]
    for f in freed:
        f.off_board = False
    table.intent(game, op="flip_dial", owner=player, fid=hero.fid, hp=RESURRECTED_HEALTH)
    return freed


def is_off_board(game, player: int) -> bool:
    return is_elektra(game, player) and life(game, player) == OFF_BOARD
