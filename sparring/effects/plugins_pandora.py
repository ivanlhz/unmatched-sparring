"""Pandora's Box (docs/heroes/pandora.md): the plugins `pandora:reveal`, `pandora:look`, `pandora:close` and `pandora:shuffle`.

The Box is a deck of seven MISERIES that is shuffled back at the end of her turn, so the only thing that has to be remembered is WHICH
ones are revealed: a bit mask in the ability counter `box_mask`, and `revealed` for the count the cards read ("for each revealed MISERY").
The next Misery is drawn at random among the unrevealed ones WHEN IT IS REVEALED, with the game's rng: no order is stored, so nobody
(the search included) can peek at what no one has seen. The one exception is HOPE, which looks at the top card before it is revealed: that
fixes the top (`box_top`, 1 + index) until it is revealed.

The trigger `pandora_box` (data/heroes/effects/pandora.json) is `reveal`, the effect of the Misery just revealed (`box_current`, 1 + index),
`close`, and `close` sends the run back to its first op while the Box is open: a loop written with the one thing the DSL has, an op that
rewinds its own frame. At the table the human reveals the physical cards, so the engine ASKS which Misery came up instead of drawing it."""
from __future__ import annotations

from . import table
from .ops_core import plugin

NAMES = ("Woe", "Toil", "Pain", "Misfortune", "Hope", "Greed", "Confusion")
FEATHERS = (0, 1, 1, 2, 0, 1, 0)
STOP_AT = 3                                 # with this many feathers revealed she must stop


def mask_of(game, owner: int) -> int:
    return game.fx.counter_value(owner, "box_mask")


def revealed(mask: int) -> list[int]:
    return [i for i in range(len(NAMES)) if mask >> i & 1]


def unrevealed(mask: int) -> list[int]:
    return [i for i in range(len(NAMES)) if not mask >> i & 1]


def feathers(mask: int) -> int:
    return sum(FEATHERS[i] for i in revealed(mask))


def top_known(game, owner: int) -> int | None:
    """The index of the Misery on top of the Box when HOPE has looked at it, else None."""
    top = game.fx.counter_value(owner, "box_top")
    return top - 1 if top and not mask_of(game, owner) >> (top - 1) & 1 else None       # a top card already revealed is no longer the top


def reveal_now(game, owner: int, idx: int) -> int:
    """Marks the Misery `idx` as revealed and makes it the current one. Returns the new mask."""
    fx = game.fx
    mask = mask_of(game, owner) | 1 << idx
    fx.set_counter(owner, "box_mask", mask)
    fx.set_counter(owner, "revealed", len(revealed(mask)))
    fx.set_counter(owner, "box_top", 0)
    fx.set_counter(owner, "box_current", idx + 1)
    return mask


def _labels() -> list[str]:
    return list(NAMES)


@plugin("pandora:reveal")
def _reveal(run, game, spec):
    """One pass of the loop: the decision to keep revealing (the first reveal is mandatory), then the next Misery."""
    owner, fx = run.ctx.owner, game.fx
    mask = mask_of(game, owner)
    left = unrevealed(mask)
    if fx.counter_value(owner, "box_done") or not left:
        fx.set_counter(owner, "box_current", 0)
        return
    if mask:
        keep = run.ask(game, "optional", owner, [True, False], 1, 1, "keep revealing?", box="open",
                       revealed=len(revealed(mask)), feathers=feathers(mask), unrevealed=left, top=top_known(game, owner))[0]
        if not keep:
            fx.set_counter(owner, "box_done", 1)
            fx.set_counter(owner, "box_current", 0)
            table.intent(game, op="pandora_stop", owner=owner, damage=0, feathers=feathers(mask))
            return
    top = top_known(game, owner)
    if top is not None and not table.physical(game, owner):
        idx = top
    elif table.physical(game, owner):             # the human's real Box: a top card they looked at (HOPE) is still taken from it and read back
        idx = run.ask(game, "effect", owner, left, 1, 1, "which Misery?", labels=_labels(), tag="misery")[0]
    else:
        idx = run.random_sample(left, 1)[0]
    reveal_now(game, owner, idx)
    run.flags.setdefault("miseries", []).append(idx)
    mask = mask_of(game, owner)
    table.intent(game, op="pandora_reveal", owner=owner, idx=idx, feathers=feathers(mask), out=len(revealed(mask)))


@plugin("pandora:shuffle")
def _shuffle(run, game, spec):
    """End of her turn: the revealed Miseries go back into the Box. The counters are emptied by the trigger's next ops; this tells the table
    (the bot puts the cards it laid out back in the deck and shuffles it)."""
    owner = run.ctx.owner
    if mask_of(game, owner):
        table.intent(game, op="pandora_shuffle", owner=owner)


@plugin("pandora:look")
def _look(run, game, spec):
    """HOPE: look at the top card of the Box. The bot reads it from its own Box; the human looks at the real one."""
    owner, fx = run.ctx.owner, game.fx
    left = unrevealed(mask_of(game, owner))
    if not left or top_known(game, owner) is not None or table.physical(game, owner):
        return
    fx.set_counter(owner, "box_top", run.random_sample(left, 1)[0] + 1)
    table.intent(game, op="pandora_look", owner=owner)


@plugin("pandora:close")
def _close(run, game, spec):
    """With three feathers revealed she stops and takes 1 damage per revealed Misery (the one that reached three included); otherwise the
    loop goes round again (the decision to keep revealing comes first in the next pass)."""
    owner, fx = run.ctx.owner, game.fx
    mask = mask_of(game, owner)
    if fx.counter_value(owner, "box_done"):
        return
    if feathers(mask) >= STOP_AT or game.winner is not None:
        fx.set_counter(owner, "box_done", 1)
        if feathers(mask) >= STOP_AT:
            run.flags.setdefault("notices", []).append("pandora_three_feathers")       # the human's line for the trigger says why she stopped
        n = len(revealed(mask))
        hero = game.hero(owner)
        if hero.alive and game.winner is None:
            game.damage(hero, n, "effect")
        table.intent(game, op="pandora_stop", owner=owner, damage=n, feathers=feathers(mask))
        return
    run.frames[-1].idx = -1                  # `step` adds one: the first op again

