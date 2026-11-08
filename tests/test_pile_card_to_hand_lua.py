"""`lua.pile_card_to_hand`: one card of a discard pile into a seat's hand (Insight Of The Ancients on the human's side).

Runs on the minimal table of `lua_stub.lua` (needs lupa). Owner 'x' is the deck the identity names; any other owner is foreign."""
import functools

import pytest

from sparring.tts import lua
from test_effects_bridge import X_IDENT, X_IDS, pile, rt, run  # noqa: F401  (rt is a fixture)

to_hand = functools.partial(lua.pile_card_to_hand, id_range=X_IDS, identity=X_IDENT)


def test_a_loose_card_goes_to_the_hand_transform(rt):
    rt.execute("mkobj({guid = 'loose1', type = 'Card', cid = 305, owner = 'x', pos = Vector(9, 1, 9)})")
    assert run(rt, to_hand("loose1", 305, "Red")) == {"moved": True, "guid": "loose1"}
    card = rt.eval('getObjectFromGUID("loose1")')
    assert (card.pos.x, card.pos.y, card.pos.z) == (0, 1, 0), "the seat's hand transform"


def test_one_card_of_a_stacked_pile_is_taken_out_and_the_rest_stays(rt):
    pile(rt, n=4)
    assert run(rt, to_hand("p3", 303, "Red")) == {"moved": True, "guid": "p3"}
    assert rt.eval('getObjectFromGUID("p3").pos.x') == 0
    assert rt.eval('getObjectFromGUID("pile01").getQuantity()') == 3


def test_it_keeps_going_when_the_pile_is_down_to_two_cards(rt):
    pile(rt, n=2)
    assert run(rt, to_hand("p1", 301, "Red"))["moved"] is True
    assert rt.eval('getObjectFromGUID("p2").type') == "Card", "the last card of a pile is a loose card, as in live TTS"


@pytest.mark.parametrize("guid, cid, owner", (
    ("p2", 302, "h"),        # another deck's image: a shared CardID never names the card
    ("p1", 399, "x"),        # right GUID, another card than the one the engine meant
    ("ghost", 301, "x"),     # not on the table at all
))
def test_it_refuses_what_is_not_the_card_asked_for(rt, guid, cid, owner):
    pile(rt, n=3, owner=owner)
    assert run(rt, to_hand(guid, cid, "Red")) == {"moved": False}
    assert rt.eval('getObjectFromGUID("pile01").getQuantity()') == 3


def test_it_does_not_take_a_card_that_is_already_in_a_hand(rt):
    rt.execute("mkobj({guid = 'inhand', type = 'Card', cid = 305, owner = 'x', hand = 'Blue'})")
    assert run(rt, to_hand("inhand", 305, "Red")) == {"moved": False}
