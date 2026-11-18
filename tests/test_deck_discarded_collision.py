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


def _run_boost(monkeypatch, g, owner):
    """The `boost` op for `owner`'s side, with the combat plumbing stubbed: it only needs the side and the owner."""
    from types import SimpleNamespace as NS
    from sparring.effects import modifiers, ops_combat
    flow = NS(att=NS(owner=owner), tgt=NS(owner=1 - owner))
    monkeypatch.setattr(ops_combat, "_flow", lambda run, name: flow)
    monkeypatch.setattr(ops_combat, "_side", lambda run, game, ref: "atk")
    monkeypatch.setattr(ops_combat, "_label", lambda run, game: "x")
    monkeypatch.setattr(modifiers, "add_value", lambda *a, **k: None)
    run = NS(flags={})
    top = g.players[owner].deck[0]
    ops_combat._boost(run, g, {"card": "this"})
    return top, run


def test_the_boost_op_marks_the_table_players_card_only(bprd, monkeypatch):
    g = make(bprd, human="daredevil")
    g.controllers[1].human = True
    top, run = _run_boost(monkeypatch, g, 1)
    assert top in g.players[1].discard and g.fx.deck_discarded == {top.card_id} and run.flags["deck_discards"] == [top.card_id]


def test_the_boost_op_of_the_bot_marks_nothing(bprd, monkeypatch):
    g = make(bprd, human="daredevil")
    g.controllers[1].human = True
    top, run = _run_boost(monkeypatch, g, 0)
    assert top in g.players[0].discard and g.fx.deck_discarded == set() and run.flags["deck_discards"] == [top.card_id]
