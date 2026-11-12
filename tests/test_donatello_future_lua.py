"""The three table builders of The future of Ninjutsu ("look at the top card of any deck"), run on the Lua stub:
a card taken out of a deck by CardID, the top card read, and the top card moved to the bottom."""
import functools
import json

import pytest

from sparring.tts import lua
from test_effects_bridge import X_IDENT, X_IDS, deck, rt, run, table_py  # noqa: F401  (rt is a fixture)

to_spot = functools.partial(lua.deck_card_to_spot, id_range=X_IDS, identity=X_IDENT)
peek = functools.partial(lua.peek_deck_top, id_range=X_IDS, identity=X_IDENT)
to_bottom = functools.partial(lua.deck_top_to_bottom, id_range=X_IDS, identity=X_IDENT)
home = functools.partial(lua.card_home, id_range=X_IDS, identity=X_IDENT)


def test_a_card_is_taken_out_of_the_middle_of_the_deck_by_its_card_id_and_laid_face_up(rt):
    deck(rt, n=3)
    rt.execute("""local d = getObjectFromGUID('deck01')
local take = d.takeObject
d.takeObject = function(t) TAKEN = {guid = t.guid, rot = t.rotation, smooth = t.smooth}; return take(t) end""")
    out = run(rt, to_spot(102, "deck01", (7, 2, 9), 90))
    assert out == {"taken": True, "guid": "c2"}
    card = rt.eval('getObjectFromGUID("c2")')
    assert (card.pos.x, card.pos.z) == (7, 9)
    assert table_py(rt, "TAKEN") == {"guid": "c2", "rot": {"x": 0, "y": 90, "z": 0}, "smooth": False}
    assert rt.eval('getObjectFromGUID("deck01").getQuantity()') == 2


def test_a_card_the_deck_does_not_hold_or_a_foreign_deck_is_not_touched(rt):
    deck(rt, n=3)
    assert run(rt, to_spot(555, "deck01", (7, 2, 9))) == {"taken": False}
    rt.execute("mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 102, guid = 'h1', owner = 'h'}}})")
    assert run(rt, to_spot(102, "hdeck", (7, 2, 9))) == {"taken": False, "deck": False}
    assert run(rt, to_spot(102, "nodeck", (7, 2, 9))) == {"taken": False, "deck": False}
    assert rt.eval('getObjectFromGUID("deck01").getQuantity()') == 3


def test_the_last_loose_card_of_a_deck_is_moved_as_it_is_and_remembers_where_it_lay(rt):
    rt.execute("mkobj({guid = 'last', type = 'Card', cid = 105, owner = 'x', is_face_down = true, pos = Vector(4, 1, 5), rot = Vector(0, 90, 180)})")
    assert run(rt, to_spot(106, "last", (1, 2, 3), 0)) == {"taken": False}
    out = run(rt, to_spot(105, "last", (1, 2, 3), 0))
    assert out == {"taken": True, "guid": "last", "single": True, "home": [4, 1, 5], "rot": [0, 90, 180]}
    assert rt.eval('getObjectFromGUID("last").pos.x') == 1
    assert rt.eval('getObjectFromGUID("last").is_face_down') is False


def test_a_face_up_last_card_is_no_deck_for_the_deck_builders_so_it_goes_home_face_down(rt):
    rt.execute("mkobj({guid = 'last', type = 'Card', cid = 105, owner = 'x', is_face_down = true, pos = Vector(4, 1, 5), rot = Vector(0, 90, 180)})")
    out = run(rt, to_spot(105, "last", (1, 2, 3), 0))
    assert run(rt, lua.card_to_deck_top("last", "last", id_range=X_IDS, identity=X_IDENT)) == {"placed": False, "deck": False},         "the old way back: a face-up card is never found as the deck"
    assert run(rt, home("last", out["home"], out["rot"])) == {"placed": True, "guid": "last"}
    card = rt.eval('getObjectFromGUID("last")')
    assert (card.pos.x, card.pos.z) == (4, 5) and card.is_face_down is True
    assert run(rt, peek("last")) == {"found": True, "id": 105, "quantity": 1}, "the deck exists again for the next deal"


def test_card_home_never_takes_a_foreign_card_or_one_in_a_hand(rt):
    rt.execute("""mkobj({guid = 'foreign', type = 'Card', cid = 105, owner = 'h'})
mkobj({guid = 'inhand', type = 'Card', cid = 106, owner = 'x', hand = 'Blue'})""")
    assert run(rt, home("foreign", (1, 1, 1), (0, 0, 180))) == {"placed": False}
    assert run(rt, home("inhand", (1, 1, 1), (0, 0, 180))) == {"placed": False}
    with pytest.raises(TypeError):
        home("foreign", (1, 1), (0, 0, 180))


def test_to_spot_needs_an_identity_and_a_real_position():
    with pytest.raises(TypeError):
        lua.deck_card_to_spot(102, "deck01", (1, 2, 3))
    with pytest.raises(TypeError):
        to_spot(102, "deck01", (1, 2))


def test_peek_reads_the_first_card_of_the_deck(rt):
    deck(rt, n=3)
    assert run(rt, peek("deck01")) == {"found": True, "id": 101, "quantity": 3}
    assert rt.eval('getObjectFromGUID("deck01").getQuantity()') == 3, "reading moves nothing"


def test_peek_of_a_single_card_missing_deck_and_foreign_deck(rt):
    rt.execute("mkobj({guid = 'last', type = 'Card', cid = 105, owner = 'x', is_face_down = true})")
    assert run(rt, peek("last")) == {"found": True, "id": 105, "quantity": 1}
    assert run(rt, peek("nodeck")) == {"found": False, "deck": False}
    rt.execute("mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 201, guid = 'h1', owner = 'h'}}})")
    assert run(rt, peek("hdeck")) == {"found": False, "deck": False}
    with pytest.raises(TypeError):
        lua.peek_deck_top("deck01")


def test_the_top_card_goes_to_the_bottom_by_rebuilding_the_deck_under_it(rt):
    """`putObject` only knows the top, whatever the deck's facing (live 12/11): the card waits locked and the deck is rebuilt."""
    deck(rt, n=3)
    out = run(rt, to_bottom("deck01", 101))
    assert out["moved"] is True and out["asked"] == "deck01"
    rebuilt = rt.eval(f'getObjectFromGUID("{out["deck"]}")')
    assert [c["guid"] for c in table_py(rt, f'getObjectFromGUID("{out["deck"]}").cards')] == ["c2", "c3", "c1"]
    assert rebuilt.rot.z == 180 and rebuilt.is_face_down is True, "never turned over"
    assert rt.eval("PUT_LOG") is None and rt.eval('getObjectFromGUID("c1")') is None, "the lifted card is in the deck, not above it"


def test_the_top_card_of_a_deck_of_two_goes_under_the_last_card(rt):
    deck(rt, n=2)
    out = run(rt, to_bottom("deck01", 101))
    assert out["moved"] is True
    assert [c["guid"] for c in table_py(rt, f'getObjectFromGUID("{out["deck"]}").cards')] == ["c2", "c1"]


def test_the_top_card_is_only_moved_if_it_is_the_one_that_was_read(rt):
    deck(rt, n=3)
    assert run(rt, to_bottom("deck01", 102)) == {"moved": False}
    assert [c["guid"] for c in table_py(rt, 'getObjectFromGUID("deck01").cards')] == ["c1", "c2", "c3"]
    assert run(rt, to_bottom("nodeck", 101)) == {"moved": False, "deck": False}


def test_a_single_card_is_already_at_the_bottom(rt):
    rt.execute("mkobj({guid = 'last', type = 'Card', cid = 105, owner = 'x', is_face_down = true})")
    assert run(rt, to_bottom("last", 105)) == {"moved": True, "single": True}
    assert run(rt, to_bottom("last", 106)) == {"moved": False, "single": True}


def test_a_foreign_deck_is_never_reordered(rt):
    rt.execute("mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 101, guid = 'h1', owner = 'h'}, {cid = 102, guid = 'h2', owner = 'h'}}})")
    assert run(rt, to_bottom("hdeck", 101)) == {"moved": False, "deck": False}
    assert rt.eval("PUT_LOG") is None


def test_a_top_card_that_is_not_the_one_that_was_read_goes_back_and_nothing_moves(rt):
    deck(rt, n=3)
    rt.execute("""local d = getObjectFromGUID('deck01')
local take = d.takeObject
d.takeObject = function(t) t.guid = d.cards[#d.cards].guid; return take(t) end""")      # TTS's top is the other end
    out = run(rt, to_bottom("deck01", 101))
    assert out["moved"] is False and out["mismatch"] is True
    assert sorted(c["guid"] for c in table_py(rt, 'getObjectFromGUID("deck01").cards')) == ["c1", "c2", "c3"], "all three still in the deck"


def test_laying_every_card_of_a_short_deck_in_a_row_one_by_one_empties_it_and_each_card_lands_at_its_own_spot(rt):
    """The order-by-hand flow (Sight Beyond Sight) lays the engine's top N by CardID one call after another in a single message:
    with a deck of exactly N cards the last card becomes a loose Card with a GUID of its own (the stub models live TTS), which the call
    finds at the deck's spot, as the session's calls always pass it."""
    deck(rt, n=3)
    outs = [run(rt, to_spot(cid, "deck01", (x, 2, 9), 90, spot=(0, 0))) for cid, x in ((103, -3), (101, 0), (102, 3))]
    assert [o["taken"] for o in outs] == [True, True, True] and outs[2].get("single") is True
    for guid, x in (("c3", -3), ("c1", 0), ("c2", 3)):
        card = rt.eval(f'getObjectFromGUID("{guid}")')
        assert (card.pos.x, card.pos.z) == (x, 9)
