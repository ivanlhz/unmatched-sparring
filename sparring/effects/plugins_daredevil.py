"""Daredevil's plugins (docs/effects-dsl.md, section 29): `daredevil:blind_boost` (the plugin of Doctor Strange under the id a
Daredevil file may declare: a plugin id carries its hero's fid) and `daredevil:take_a_knee`.

Take A Knee discards the top card of the owner's deck and heals by that card's BOOST value, so the engine has to know
WHICH card it was. For the engine's player (the bot, a simulation, a search clone) the deck is known and the card comes
off it. For the table player the deck is physical: they press the one button the panel shows, the session's bot moves
the real top card to their discard pile (`session_blind`, Lua `deck_top_to_discard`) and the plugin reads its CardID, exactly
as the human's BLIND BOOST does (`plugins_strange.discard_top`, which this reuses)."""
from __future__ import annotations

from . import table
from .ops_core import plugin
from .plugins_strange import _blind_boost, discard_top

plugin("daredevil:blind_boost")(_blind_boost)       # Daredevil's BLIND BOOST is Doctor Strange's (same declaration, same table moves)


@plugin("daredevil:take_a_knee")
def _take_a_knee(run, game, spec):
    """"Discard the top card of your deck": it is bound (`args.as`) for the heal that follows. An empty deck discards
    nothing and binds nothing, so there is nothing to recover. The table player confirms with one button (a single
    forced option would otherwise be taken without asking, and the table needs the press to move the card)."""
    owner, name = run.ctx.owner, spec["args"]["as"]
    st = game.players[owner]
    if not st.deck:
        run.bind("cards", name, [])
        return
    if table.physical(game, owner):
        run.ask(game, "amount", owner, [1], 1, 1, "discard the top card", top_discard=True, confirm=True)
    cards = discard_top(run, game, owner, 1)
    run.bind("cards", name, [c.card_id for c in cards])
