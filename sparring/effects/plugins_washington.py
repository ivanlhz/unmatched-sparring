"""George Washington's plugins (docs/heroes/george-washington.md): `washington:use_ruse`, `washington:offer_removal` and `washington:replace_combatant` and the test `washington:started_here`.

ESPIONAGE: "When you attack, you may use a ruse token, placing it next to the card." The trigger `espionage` of the effects file runs
`use_ruse` when an enemy fighter is attacked. The question goes to the attacker only for a card that carries a ruse effect (the card tag
`ruse`, set in the overlay on the four cards whose text has the ruse triangle): a token on any other card changes nothing for the
attacker and only costs the opponent a decision. The request carries the attack card, so the bot weighs the ruse of THAT card
(`ai_washington.use_ruse`); the human's answer is given at Reveal, before the opponent defends (`session_espionage`).

"Before your opponent chooses whether or not to defend, they may discard 1 random card to remove the ruse token": the trigger
`espionage_remove` runs `offer_removal`, which asks the OPPONENT. The price is a random card of their own hand, so it is paid as a
voluntary discard (`discard` with `voluntary`: nothing that stops the rival's forced discards stops a price the player chose). The token
they remove is gone: it does not go back to the supply (Pending Ivan 3).

Undercover Agent: after Washington swapped with an adjacent Spy, the Spy takes his place as the defender in the running combat, which is
what Eredin's Portal Defense and Houdini's Smoke And Mirrors do too (`houdini:replace_combatant`)."""
from __future__ import annotations

from . import table
from .ops_core import OPS, plugin, plugin_condition
from .plugins_houdini import _replace_combatant

RUSE_TAG = "ruse"
USE_KEY = "use"
REMOVE_KEY = "remove"


def has_ruse_effect(card) -> bool:
    """The card carries an effect printed after the ruse-triangle icon."""
    return card is not None and RUSE_TAG in card.tags


@plugin("washington:use_ruse")
def _use_ruse(run, game, spec):
    """Asks the attacker whether to spend a ruse token on the attack card of the event; yes: the supply loses one and the token
    lies next to the card (`ruse`). Atomic like every op: the question first, the counters after."""
    ctx = run.ctx
    card = None if ctx.attack_card_id is None else game.card_of(ctx.attack_card_id, ctx.owner)
    if not has_ruse_effect(card):
        return
    asked = run.ask(game, "optional", ctx.owner, [True, False], 1, 1, "use a ruse token on this attack?",
                    washington=USE_KEY, attack_card=card.card_id, attacker=ctx.attacker_fid, target=ctx.defender_fid)
    if not asked[0]:
        return
    OPS["counter"](run, game, {"op": "counter", "name": "ruse_tokens", "delta": -1})
    OPS["counter"](run, game, {"op": "counter", "name": "ruse", "set": 1})


@plugin("washington:offer_removal")
def _offer_removal(run, game, spec):
    """Asks the opponent of the attacker whether to discard 1 random card to take the ruse token off the attack. Nothing to
    discard, no question. Yes: the card goes (the table's own route for a table player's hand) and the token is gone."""
    ctx = run.ctx
    opponent = 1 - ctx.owner
    if len(game.players[opponent].hand) - table.discards_owed(game, opponent) < 1:
        return
    asked = run.ask(game, "optional", opponent, [True, False], 1, 1, "discard 1 random card to remove the ruse token?",
                    washington=REMOVE_KEY, attacker=ctx.attacker_fid, target=ctx.defender_fid)
    if not asked[0]:
        return
    OPS["discard"](run, game, {"op": "discard", "voluntary": True,
                               "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 1}})
    OPS["counter"](run, game, {"op": "counter", "name": "ruse", "set": 0})


@plugin("washington:replace_combatant")
def _undercover_agent(run, game, spec):
    """When Washington and the Spy did swap (`args.swapped` binds both), the Spy takes his place in this combat."""
    return _replace_combatant(run, game, spec)


@plugin_condition("washington:started_here")
def _started_here(game, run, key: str) -> bool:
    """Make A Stand: the fighter that plays the card is on the space it had at the start of the turn (it may have left and come back).
    A fighter with no space recorded for the start of the turn (a Spy placed this turn) did not start anywhere."""
    from .select import _ref_fighter
    fighter = _ref_fighter(game, run, key)
    start = None if fighter is None else game.fx.turn_start_pos.get(fighter.fid)
    return start is not None and fighter.pos == start
