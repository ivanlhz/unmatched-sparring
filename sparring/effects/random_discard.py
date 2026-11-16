"""A random discard from a player's hand whose card the effect then READS (Ambush: "discards 1 random card, add its BOOST value").

The engine knows a bot's hand and a simulation's: the card is drawn and discarded here. The table player's hand is placeholders: the
engine draws the POSITION from the hand size (`ops_core._random_positions_text`, "the card N of your hand counting from the left"),
the human discards that card by hand onto their discard pile and presses Done, and the bot DETECTS the card on the table by its
identity (`session_rage`, `pile_mode: reveal`, `ambush`). Ivan, 2026-11-13: one flow for every Ambush."""
from __future__ import annotations

from . import table
from .ops_core import _card_title, _random_positions_text


def discard_random_known(run, game, victim: int):
    """Discards one random card of `victim`'s hand and returns it (None with an empty hand). For the table player the engine asks them
    to lay the named position on their discard pile and reads which card it was; the question is asked once even if the op reruns."""
    st = game.players[victim]
    if not st.hand:
        return None
    if not table.physical(game, victim):
        card = run.random_sample(list(st.hand), 1)[0]
        game.discard_card(victim, card)
        return card
    from .plugins_strange import _unplayed
    which = _random_positions_text(game, run, victim, 1, _card_title(game, run))
    got = run.ask(game, "cards", victim, _unplayed(st), 1, 1, "put the card in your discard pile", zone="discard", purpose="bonus",
                  of=victim, table_discard=True, pile_mode="reveal", ambush=True, which=which)
    game.fx.random_notice = None            # still set only if a forced answer skipped the request: nobody was shown it
    card = {c.card_id: c for c in st.full_set}[got[0]]
    table.make_known(game, victim, card)
    game.discard_card(victim, card)
    return card
