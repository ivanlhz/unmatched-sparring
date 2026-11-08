"""She-Hulk's plugins (docs/effects-dsl.md, section 34): `shehulk:throw` (JUST THROW SOMETHING) and `shehulk:mill` (Lady Justice).

Throw: the owner picks the card of their hand to discard, or none, and it is bound for the damage that follows (its BOOST
value). It only runs for a hand the engine knows (the bot's, a simulation's, a search clone's): at the real table the human's
start-of-turn ability reads their real hand, so it is theirs to do by hand (`table.start_of_turn_is_physical`).

Mill: "Discard the top card of your opponent's deck". The bot's deck is the engine's (the card comes off it). The human's is on the
table: they press the one button the panel shows and the session's bot moves their real top card to their discard pile, face up
(`session_blind`, Lua `deck_top_to_discard`), then the plugin reads its CardID: Take A Knee's machinery with the deck of the RIVAL
(`plugins_strange.discard_top`)."""
from __future__ import annotations

from . import table
from .ops_core import plugin
from .plugins_strange import discard_top
from .select import fighter_candidates

IN_HER_ZONE = {"side": "enemy", "where": {"zone_of": "hero"}}


@plugin("shehulk:throw")
def _throw(run, game, spec):
    """Binds (`args.as`) the card discarded, or nothing. Every decision is asked before the hand changes (ops are atomic)."""
    owner, name = run.ctx.owner, spec["args"]["as"]
    hand = game.players[owner].hand
    targets = [f.fid for f in fighter_candidates(game, run, IN_HER_ZONE)[0]]
    if not hand or not targets:
        run.bind("cards", name, [])
        return
    got = run.ask(game, "cards", owner, [c.card_id for c in hand], 0, 1, "throw a card", zone="hand", purpose="throw",
                  of=owner, targets=targets)
    if not got:
        run.bind("cards", name, [])
        return
    card = next(c for c in hand if c.card_id == got[0])
    game.discard_card(owner, card)
    run.bind("cards", name, [card.card_id])


@plugin("shehulk:mill")
def _mill(run, game, spec):
    """Binds (`args.as`) the card discarded from the top of the opponent's deck; an empty deck discards nothing and binds nothing."""
    rival, name = 1 - run.ctx.owner, spec["args"]["as"]
    if not game.players[rival].deck:
        run.bind("cards", name, [])
        return
    if table.physical(game, rival):
        run.ask(game, "amount", rival, [1], 1, 1, "discard the top card", top_discard=True, confirm=True, rival_deck=True)
    cards = discard_top(run, game, rival, 1, rival_deck=True)
    run.bind("cards", name, [c.card_id for c in cards])
