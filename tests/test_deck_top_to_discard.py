"""`lua.deck_top_to_discard`: the top cards of a draw deck onto the discard pile of a zone, face up (Doctor Strange's BLIND BOOST of the human).

The Lua runs on the minimal table of `lua_stub.lua` (needs lupa)."""
import functools

import pytest

from sparring.tts import lua
from test_effects_bridge import X_IDENT, X_IDS, deck, dissolving_deck, rt, run  # noqa: F401

pytest.importorskip("lupa")

to_discard = functools.partial(lua.deck_top_to_discard, id_range=X_IDS, identity=X_IDENT)


def pile(rt, x=10, z=10, turn=90):
    """A scripting zone with a face-up discard card in it."""
    rt.execute(f"""mkobj({{guid = 'zone1', type = 'Scripting', cx = {x}, cz = {z}, hw = 3, hd = 3}})
mkobj({{guid = 'pile1', type = 'Card', cid = 190, owner = 'x', is_face_down = false, pos = Vector({x}, 1, {z}), rot = Vector(0, {turn}, 0)}})""")


def where(rt, guid):
    return rt.eval(f'getObjectFromGUID("{guid}").pos.x'), rt.eval(f'getObjectFromGUID("{guid}").pos.y')


def test_the_top_cards_land_above_the_pile_in_order_and_their_card_ids_come_back(rt):
    deck(rt, n=4)
    pile(rt)
    out = run(rt, to_discard("deck01", 2, "zone1"))
    assert out == {"moved": [101, 102], "count": 2, "deck": True, "zone": True}
    assert rt.eval('getObjectFromGUID("deck01").getQuantity()') == 2
    assert where(rt, "c1") == (10, 2.0) and where(rt, "c2") == (10, 2.25)


def test_one_card_less_than_asked_is_what_the_deck_gives_and_the_last_card_is_found_loose(rt):
    dissolving_deck(rt, n=2)
    pile(rt)
    out = run(rt, to_discard("deck01", 3, "zone1"))
    assert out["moved"] == [101, 102] and out["count"] == 2


def test_a_deck_that_is_not_ours_or_a_missing_zone_moves_nothing(rt):
    deck(rt, n=3)
    rt.execute("mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 201, guid = 'h1', owner = 'h'}}})")
    assert run(rt, to_discard("hdeck", 1, "zone1")) == {"moved": [], "count": 0, "deck": False, "zone": True}
    assert run(rt, to_discard("deck01", 1, "nozone")) == {"moved": [], "count": 0, "deck": True, "zone": False}
    assert rt.eval('getObjectFromGUID("deck01").getQuantity()') == 3


def test_a_card_count_outside_the_bounds_is_refused():
    for n in (0, 13, True):
        with pytest.raises(ValueError):
            lua.deck_top_to_discard("abc", n, "def", identity=X_IDENT)
