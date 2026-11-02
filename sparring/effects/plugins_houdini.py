"""Houdini's plugins (docs/effects-dsl.md, section "Houdini"): `houdini:replace_combatant` and `houdini:return_boosted`.

Both need the running combat (`run.flow`, a CombatFlow): the first changes who is in it, the second reads the cards
the combat was boosted with, which the flow keeps (`CombatFlow.boosted`)."""
from __future__ import annotations

from .model import EffectError
from .ops_core import OPS, plugin


def _flow(run, name: str):
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError(f"{name}: only inside a combat")
    return flow


@plugin("houdini:replace_combatant")
def _replace_combatant(run, game, spec):
    """Smoke And Mirrors: when Houdini and Bess did swap (`args.swapped` binds both), the one that did not play the
    card takes the place of the one that did, in this combat."""
    flow = _flow(run, "houdini:replace_combatant")
    swapped = run.bound(spec["args"]["swapped"].removeprefix("$"), "fighters")
    if len(swapped) != 2 or run.ctx.this_fid not in swapped:
        return
    other = game.fighters[next(f for f in swapped if f != run.ctx.this_fid)]
    old = game.fighters[run.ctx.this_fid]
    if flow.replace_combatant(old, other):
        run.ctx.this_fid = other.fid
        if run.ctx.attacker_fid == old.fid:
            run.ctx.attacker_fid = other.fid
        elif run.ctx.defender_fid == old.fid:
            run.ctx.defender_fid = other.fid


@plugin("houdini:return_boosted")
def _return_boosted(run, game, spec):
    """The Big Reveal: the owner chooses one of the cards this card's side was boosted with that are still in their
    discard pile and takes it back to their hand (`put_in_hand`, so the table translators see an ordinary recovery)."""
    flow = _flow(run, "houdini:return_boosted")
    owner = run.ctx.owner
    side = "atk" if run.ctx.played_as == "attack" else "def"
    in_pile = {c.card_id for c in game.players[owner].discard}
    options = [i for i in flow.boosted.get(side, []) if i in in_pile]
    if not options:
        return
    got = run.ask(game, "cards", owner, options, 1, 1, "return a boosted card", zone="discard", purpose="recover", of=owner)
    run.bind("cards", "returned", got)
    OPS["put_in_hand"](run, game, {"op": "put_in_hand", "cards": "$returned"})
