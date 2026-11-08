"""The read of the top N cards of a deck (Jill Trent's Insightful Deduction against the human's deck), run on the Lua stub: the same
`peek_deck_top` as The future of Ninjutsu's, with a `count`."""
import functools

from sparring.tts import lua
from test_effects_bridge import X_IDENT, X_IDS, deck, rt, run  # noqa: F401  (rt is a fixture)

peek = functools.partial(lua.peek_deck_top, id_range=X_IDS, identity=X_IDENT)


def test_the_default_read_is_the_one_card_script_of_before():
    assert "ids" not in peek("deck01") and peek("deck01", count=1) == peek("deck01")


def test_the_top_three_cards_are_read_top_first_and_nothing_moves(rt):
    deck(rt, n=5)
    assert run(rt, peek("deck01", count=3)) == {"found": True, "id": 101, "ids": [101, 102, 103], "quantity": 5}
    assert rt.eval('getObjectFromGUID("deck01").getQuantity()') == 5, "reading moves nothing"


def test_a_short_deck_gives_what_it_holds_and_a_single_card_is_its_own_top(rt):
    deck(rt, n=2)
    assert run(rt, peek("deck01", count=3)) == {"found": True, "id": 101, "ids": [101, 102], "quantity": 2}
    rt.execute("mkobj({guid = 'last', type = 'Card', cid = 105, owner = 'x', is_face_down = true})")
    assert run(rt, peek("last", count=3)) == {"found": True, "id": 105, "ids": [105], "quantity": 1}


def test_a_missing_deck_and_a_foreign_deck_read_nothing(rt):
    assert run(rt, peek("nodeck", count=3)) == {"found": False, "deck": False}
    rt.execute("mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 201, guid = 'h1', owner = 'h'}, {cid = 202, guid = 'h2', owner = 'h'}}})")
    out = run(rt, peek("hdeck", count=3))
    assert out["found"] is False and not out.get("ids")
