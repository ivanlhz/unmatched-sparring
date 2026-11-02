"""Houdini's plugins (docs/effects-dsl.md, section "Houdini"): `houdini:replace_combatant`, `houdini:return_boosted`
and `houdini:sleight_of_hand`.

All need the running combat (`run.flow`, a CombatFlow): the first changes who is in it, the second reads the cards
the combat was boosted with, which the flow keeps (`CombatFlow.boosted`), the third swaps the attacker's card."""
from __future__ import annotations

from . import table
from .model import EffectError
from .ops_core import OPS, plugin
from .plugins_strange import _unplayed


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


@plugin("houdini:sleight_of_hand")
def _sleight_of_hand(run, game, spec):
    """Sleight Of Hand, IMMEDIATELY: "You may return this card to your hand and choose a different card to play. Resolve all effects on
    that card as normal." It runs in the attacker's own IMMEDIATELY (the defender's has already run, house rule), so the rival's card is
    face up and the owner decides knowing it. The card goes back to the hand and the chosen one is played in its place
    (`CombatFlow.replace_attack_card(back_to_hand=True)`): its value replaces the 1, the bonuses already applied stay and its own
    IMMEDIATELY runs next. Only an attack or versatile card the attacking fighter may play, and not another Sleight Of Hand: a second
    copy would return itself and offer the same cards again (a loop with nothing to gain).
    The bot (and a game with no table player) answers one `cards` request, an empty answer keeps the card. The table player's hand
    is virtual: a yes/no question, then they take the card back and put the new one face up on their combat spot
    (`pile_mode: play`, `sleight: true`) and the session reads it."""
    flow = _flow(run, "houdini:sleight_of_hand")
    old = flow.atk_card
    if run.ctx.played_as != "attack" or old.card_id != run.ctx.card_id:
        return
    owner, attacker = run.ctx.owner, flow.att
    st = game.players[owner]
    physical = table.physical(game, owner)
    pool = [game.card_of(i, owner) for i in _unplayed(st)] if physical else list(st.hand)
    options = [c.card_id for c in pool if c.can_attack and c.usable_by(attacker.name) and c.title != old.title]
    if not options:
        return
    info = {"fighter": attacker.fid, "target": flow.tgt.fid, "old": old.card_id,
            "atk_value": flow.ctx.atk_value, "def_value": flow.ctx.def_value}
    if physical:
        if not run.ask(game, "optional", owner, [True, False], 1, 1, "return it and play another card?", sleight=info)[0]:
            return
        got = run.ask(game, "cards", owner, options, 0, 1, "play another card", zone="discard", purpose="swap_attack",
                      of=owner, table_discard=True, pile_mode="play", sleight=True, old=old.card_id, attacker=attacker.fid)
    else:
        got = run.ask(game, "cards", owner, options, 0, 1, "play another card", zone="hand", purpose="swap_attack",
                      of=owner, sleight=info)
    if not got:
        return
    new = game.card_of(got[0], owner)
    if physical:
        table.make_known(game, owner, new)
    flow.replace_attack_card(new, back_to_hand=True)
    run.flags["swapped"] = {"old": old.card_id, "new": new.card_id}
