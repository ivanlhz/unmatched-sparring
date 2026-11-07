"""Donatello's plugin: `donatello:future_of_ninjutsu`.

"Look at the top card of any deck. You may put it on the bottom." (rule confirmed by Ivan on 7/11 with a rules video:
the deck may be the rival's). The plugin asks WHICH deck. The owner's own deck is left to the `if` that follows it in the card
(`own_deck`: look, then the optional move to the bottom, the flow that existed before); the rival's is looked at here:

- the rival is the engine's player (the bot): its deck order is the engine's, so the card looked at is its real top
  card. The owner (the human) is shown that card on the table by the session (the request carries `extra["top"]`), and
  answers `0` leave it on top or `1` put it at the bottom.
- the rival is the table player (the human): their engine deck is virtual, so the real top card is read from the
  table through `Game.deck_reader`. A clone, a table that cannot be read or a card that is not theirs is a failed read
  and the owner's own deck is used instead. The bot decides (`EffectAI`) and `future_look` tells the session what to do
  to the real deck. What the bot saw is remembered only as `KnownHand.top_of_deck`, which the rival's next draw erases.

Every decision is asked before the first mutation (the handler may run again after a pause), and the question about the
deck never carries the rival's top card: the bot chooses the deck before it can know what is on it."""
from __future__ import annotations

from ..i18n import t
from . import table
from .model import EffectError
from .ops_core import plugin, plugin_condition

OWN, RIVAL = 0, 1
LEAVE, BOTTOM = 0, 1


def _rival_top(game, rival: int):
    """The card on top of the rival's deck: the engine's own for the bot, the one read from the table for the human.
    None when it cannot be known."""
    st = game.players[rival]
    if not table.physical(game, rival):
        return st.deck[0] if st.deck else None
    reader = game.deck_reader
    card_id = None if reader is None else reader(rival)
    return next((c for c in st.full_set if c.card_id == card_id), None)


def _can_look_at_rival(game, rival: int) -> bool:
    if not game.players[rival].deck:
        return False
    return not table.physical(game, rival) or game.deck_reader is not None


@plugin("donatello:future_of_ninjutsu")
def _future_of_ninjutsu(run, game, spec):
    """Asks which deck. The owner's own deck sets `own_deck` and the card's `if` runs the printed text on it; the rival's is
    looked at here."""
    owner = run.ctx.owner
    rival = 1 - owner
    run.flags["future_own_deck"] = True
    if not _can_look_at_rival(game, rival):
        return
    mine = game.players[owner]
    extra = {} if table.physical(game, owner) or not mine.deck else {"own_top": mine.deck[0].card_id}
    which = run.ask(game, "effect", owner, [OWN, RIVAL], 1, 1, "which deck to look at", future="deck",
                    labels=[t("fx.future.own_deck"), t("fx.future.rival_deck")], **extra)[0]
    if which == OWN:
        return
    top_id = run.flags.get("future_top")             # a rerun after a pause keeps the card the owner was shown
    if top_id is None:
        seen = _rival_top(game, rival)
        if seen is None:
            return
        run.flags["future_top"] = seen.card_id
    else:
        seen = game.card_of(top_id, rival)
    put = run.ask(game, "effect", owner, [LEAVE, BOTTOM], 1, 1, "leave it on top or put it at the bottom", future="peek",
                  labels=[t("fx.future.leave"), t("fx.future.bottom")], top=seen.card_id, deck_of=rival)[0]
    run.flags["future_own_deck"] = False
    watcher = game.players[owner].known
    if put == BOTTOM:
        if not table.physical(game, rival):
            game.players[rival].deck.remove(seen)
            game.players[rival].deck.append(seen)
        watcher.clear_top()
    else:
        watcher.set_top([seen.card_id])
    table.intent(game, op="future_look", player=rival, card=seen.card_id, position="bottom" if put == BOTTOM else "top")


@plugin_condition("donatello:future_of_ninjutsu")
def _own_deck(game, run, key: str) -> bool:
    """`own_deck`: the plugin left the look to the owner's own deck (the rival's was not chosen, not offered or not readable)."""
    if key != "own_deck":
        raise EffectError(f"donatello:future_of_ninjutsu: unknown key {key!r}")
    return bool(run.flags.get("future_own_deck", True))
