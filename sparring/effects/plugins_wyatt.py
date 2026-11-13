"""Wyatt Earp's plugins (docs/heroes/wyatt-earp.md): the free action that can only attack, You Die First, Better Swear Me In and
Bring 'Em To Justice.

  * `wyatt:free_attack` (`args.target` optional, a fighter reference): "gain 1 free action to attack" (SHOWDOWN, In Vino Veritas) and
    "... to attack that fighter" (You Die First). The action is an ordinary extra action (`Game.actions_left`) that
    `Game.free_attacks` marks as attack-only (and, with a target, attack-that-fighter-only): a Maneuver or a scheme cannot spend it.
    Only the player whose turn it is can gain it, and the `cannot_gain_actions` blocks hold, as for any other action.
  * `wyatt:you_die_first`: "Move an opposing fighter up to 1 space. Gain 1 free action to attack that fighter." The owner picks the
    fighter, moves it (the interpreter's `move`, so the table, the reach and the chooser's rules are the usual ones) and the free
    attack is bound to that fighter. The bot's `EffectAI` answers the two requests (`op: move` on a rival piece).
  * `wyatt:swear_me_in`: "Reveal the top card of your opponent's deck. You may put it on the bottom of their deck." Jill Trent's
    reveal (`plugins_jill`), then a yes/no the owner answers (request `optional`, `bury` = the revealed card).
  * `wyatt:bring_to_justice`: "Reveal the top card of your opponent's deck. Increase the value of this card by twice that card's
    BOOST value." `jill:hypnoray` with a factor of two.

The deck of the table player is read through `Game.deck_reader` and the bot reads it only when one of these effects says so, at
the moment it resolves (plugins_jill explains how)."""
from __future__ import annotations

from ..i18n import t
from . import modifiers, table
from .model import EffectError
from .ops_core import OPS, plugin
from .plugins_jill import show, top_cards
from .select import _ref_fighter, pick_fighters

JUSTICE_FACTOR = 2


@plugin("wyatt:free_attack")
def _free_attack(run, game, spec):
    """One free action to attack (anyone, or `args.target` only) for the owner, when it is their turn and nothing forbids it."""
    if run.ctx.owner != game.turn:
        return
    ref = (spec.get("args") or {}).get("target")
    target = None
    if ref is not None:
        foe = _ref_fighter(game, run, ref)
        if foe is None:
            return
        target = foe.fid
    game.grant_free_attack(target)


@plugin("wyatt:you_die_first")
def _you_die_first(run, game, spec):
    """The owner picks an opposing fighter and moves it up to 1 space; then the free attack against it is granted. Every
    decision is asked before the first mutation of each step (a step that pauses runs again and finds its answers)."""
    owner = run.ctx.owner
    victim = pick_fighters(game, run, {"side": "enemy"}, owner, op="move", amount=1)
    if not victim:
        return
    run.bind("fighters", "victim", [victim[0].fid])
    OPS["move"](run, game, {"op": "move", "target": {"role": "$victim"}, "amount": 1, "up_to": True})
    if owner == game.turn:
        game.grant_free_attack(victim[0].fid)


@plugin("wyatt:swear_me_in")
def _swear_me_in(run, game, spec):
    """Reveal the top card of the opponent's deck (once, whatever the pauses) and let the owner bury it. An empty deck reveals
    nothing."""
    owner, rival = run.ctx.owner, 1 - run.ctx.owner
    seen = top_cards(game, rival, 1)
    if not seen:
        return
    card = seen[0]
    if not run.flags.get("revealed_top"):
        run.flags["revealed_top"] = True
        show(game, owner, rival, seen)
    if not run.ask(game, "optional", owner, [True, False], 1, 1, "put it on the bottom", bury=card.card_id, of=rival,
                   title=card.title)[0]:
        return
    if not table.physical(game, rival):
        st = game.players[rival]
        st.deck.remove(card)
        st.deck.append(card)
    game.players[owner].known.clear_top()
    table.intent(game, op="deck_order", player=rival, seen=[card.card_id], top=[], bottom=card.card_id, owner=owner)


@plugin("wyatt:bring_to_justice")
def _bring_to_justice(run, game, spec):
    """Reveal the top card of the opponent's deck; this defense is worth twice its BOOST value more in this combat."""
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError("wyatt:bring_to_justice: only inside a combat")
    seen = top_cards(game, 1 - run.ctx.owner, 1)
    if not seen:
        return
    show(game, run.ctx.owner, 1 - run.ctx.owner, seen)
    side = "atk" if run.ctx.played_as == "attack" else "def"
    modifiers.add_value(flow, side, JUSTICE_FACTOR * seen[0].boost, t("fx.wyatt.justice", title=seen[0].title))
