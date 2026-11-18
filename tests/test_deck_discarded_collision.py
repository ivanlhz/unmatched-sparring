"""`Game.fx.deck_discarded` (the human's deck cards that went to their pile, never owed from the hand) holds bare CardIDs, and heroes of
one sheet share them (Daredevil, Medusa and Donatello: ids 17600-17621). Only the table player's own deck discards may enter it."""
from __future__ import annotations

from test_donatello_effects import adjacent, attack, give, make


def test_a_bot_deck_discard_never_marks_the_card_id_of_the_human(bprd):
    g = make(bprd, human="daredevil")
    adjacent(g, b="daredevil")
    g.controllers[1].human = True                           # the human sits at the table; Donatello is the bot
    u = give(g, "Untested enhancements")
    bottom = g.players[0].deck[-1]
    attack(g, u)
    assert bottom in g.players[0].discard, "the bot's card came off its own deck"
    assert g.fx.deck_discarded == set()
