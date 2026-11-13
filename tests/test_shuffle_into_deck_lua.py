"""The Lua builders that put cards INTO a draw deck, with NO deck on the table, run on the TTS stub.

Real TTS destroys a Deck object when its last card is drawn, so an empty draw deck is nothing at all. Every writer used to answer
`deck = false` and move nothing (the cards stayed on the table while the engine counted them in the deck: Devil of Hell's Kitchen's
AFTER, which only ever runs with the deck empty when the card was worth 8). Now the first card is laid face down where the deck
lay (`home`: the Scripting zone's centre, else the deck spot) and IS the deck; the rest go into it. With no zone and no spot there
is no place to lay it and the writers refuse as before. A lone Card (the last card of a deck) is a deck too, and TTS answers
`getQuantity() = -1` for it: the writers report 1."""
import functools

import pytest

from sparring.tts import lua
from test_effects_bridge import X_IDENT, X_IDS, conv, rt, run  # noqa: F401  (rt is a fixture)

SPOT = (0.0, 3.0)
shuffle = functools.partial(lua.shuffle_into_deck, id_range=X_IDS, identity=X_IDENT)
to_top = functools.partial(lua.card_to_deck_top, id_range=X_IDS, identity=X_IDENT)
to_bottom = functools.partial(lua.card_to_deck_bottom, id_range=X_IDS, identity=X_IDENT)
hand_to_deck = functools.partial(lua.hand_to_deck, id_range=X_IDS, identity=X_IDENT)
return_hand = functools.partial(lua.return_hand_to_deck, id_range=X_IDS, identity=X_IDENT)
hand_row = functools.partial(lua.resolve_hand_row, identity=X_IDENT, id_range=X_IDS)


def loose(rt, *cids, face_up=True):
    """Loose cards of ours on the pile / combat spot (face up), GUIDs `p<cid>`; and a foreign one that must never move."""
    for cid in cids:
        rt.execute(f"mkobj({{guid = 'p{cid}', type = 'Card', cid = {cid}, owner = 'x', pos = Vector({cid % 7}, 1, -2), "
                   f"rot = Vector(0, 0, {0 if face_up else 180}), is_face_down = {str(not face_up).lower()}}})")
    rt.execute("mkobj({guid = 'foreign', type = 'Card', cid = 150, owner = 'h', pos = Vector(0, 1, -5), rot = Vector(0, 0, 0), is_face_down = false})")


def hand(rt, *cids):
    for cid in cids:
        rt.execute(f"mkobj({{guid = 'h{cid}', type = 'Card', cid = {cid}, owner = 'x', hand = 'Blue', is_face_down = false, rot = Vector(0, 0, 0)}})")


def decks(rt):
    """Every deck-like object of ours on the table: (type, cards in it, x, y, z, face down, shuffled, [CardIDs top to bottom])."""
    return conv(rt.eval("""(function() local t = {} for _, o in ipairs(OBJECTS) do
      if (o.type == 'Deck' or o.type == 'Card') and o.owner ~= 'h' then
        local ids = {}
        if o.type == 'Deck' then for _, c in ipairs(o.cards) do ids[#ids + 1] = c.cid end else ids[1] = o.cid end
        t[#t + 1] = {type = o.type, x = o.pos.x, y = o.pos.y, z = o.pos.z, down = o.is_face_down, shuffled = o.shuffled, ids = ids}
      end end return t end)()"""))


def the_new_deck(rt):
    (one,) = [d for d in decks(rt) if d["x"] == 0.0 and d["z"] == 3.0]
    return one


def test_a_shuffle_into_no_deck_lays_the_first_card_down_where_the_deck_lay_and_puts_the_rest_in(rt):
    loose(rt, 160, 161, 162, 163, 164)
    out = run(rt, shuffle("deadguid", ["p160", "p161", "p162", "p163", "p164"], spot=SPOT))
    assert out["added"] == 5 and out["moved"] == ["p160", "p161", "p162", "p163", "p164"] and out["quantity"] == 5
    deck = the_new_deck(rt)
    assert deck["type"] == "Deck" and deck["down"] is True and deck["shuffled"] is True and deck["y"] == 1.5
    assert sorted(deck["ids"]) == [160, 161, 162, 163, 164]
    assert rt.eval('getObjectFromGUID("foreign").moved_count') is None


def test_the_deck_is_laid_in_the_centre_of_its_scripting_zone_when_it_has_one(rt):
    loose(rt, 160, 161)
    rt.execute("mkobj({guid = 'bzone', type = 'Scripting', cx = 5, cz = 6, hw = 2, hd = 2, pos = Vector(5, 1, 6)})")
    out = run(rt, shuffle("deadguid", ["p160", "p161"], spot=SPOT, zone="bzone"))
    assert out["added"] == 2
    (deck,) = [d for d in decks(rt) if d["type"] == "Deck"]
    assert (deck["x"], deck["z"]) == (5, 6) and deck["down"] is True


def test_a_second_shuffle_finds_the_deck_the_first_one_laid(rt):
    loose(rt, 160, 161, 162)
    run(rt, shuffle("deadguid", ["p160", "p161"], spot=SPOT))
    out = run(rt, shuffle("deadguid", ["p162"], spot=SPOT))
    assert out["added"] == 1 and out["quantity"] == 3
    assert sorted(the_new_deck(rt)["ids"]) == [160, 161, 162]


def test_a_shuffle_into_the_last_card_of_a_deck_makes_a_deck_of_it_and_reports_the_count(rt):
    loose(rt, 160)
    rt.execute("mkobj({guid = 'last', type = 'Card', cid = 170, owner = 'x', pos = Vector(0, 1, 3), rot = Vector(0, 0, 180), is_face_down = true})")
    out = run(rt, shuffle("deadguid", ["p160"], spot=SPOT))
    assert out["added"] == 1 and out["quantity"] == 2
    assert sorted(the_new_deck(rt)["ids"]) == [160, 170]


def test_the_quantity_of_a_lone_card_is_one_not_the_minus_one_tts_gives(rt):
    rt.execute("mkobj({guid = 'last', type = 'Card', cid = 170, owner = 'x', pos = Vector(0, 1, 3), rot = Vector(0, 0, 180), is_face_down = true})")
    out = run(rt, shuffle("deadguid", ["nobody"], spot=SPOT))
    assert out["added"] == 0 and out["quantity"] == 1


def test_with_no_zone_and_no_spot_there_is_no_place_to_lay_the_deck_and_nothing_moves(rt):
    loose(rt, 160)
    assert run(rt, shuffle("deadguid", ["p160"])) == {"added": 0, "deck": False, "moved": []}
    assert run(rt, to_top("p160", "deadguid")) == {"placed": False, "deck": False}
    assert run(rt, to_bottom("p160", "deadguid")) == {"placed": False, "deck": False}
    hand(rt, 201)
    assert run(rt, hand_to_deck("Blue", [201], "deadguid")) == {"placed": [], "deck": False}
    assert run(rt, return_hand("Blue", "deadguid")) == {"returned": 0, "deck": False}
    assert rt.eval('getObjectFromGUID("p160").moved_count') is None and rt.eval('getObjectFromGUID("h201").hand') == "Blue"


def test_no_wanted_card_on_the_table_and_no_deck_is_a_clean_refusal(rt):
    loose(rt, 160)
    out = run(rt, shuffle("deadguid", ["nope1", "nope2"], spot=SPOT))
    assert out["added"] == 0 and out["deck"] is False and out["moved"] == []


@pytest.mark.parametrize("builder,name", [(to_top, "top"), (to_bottom, "bottom")])
def test_a_card_put_on_top_or_bottom_of_no_deck_is_the_deck(rt, builder, name):
    loose(rt, 160)
    want = {"placed": True, "deck": "p160", "quantity": 1}
    if name == "bottom":    # bury reports the GUID that was asked for, so the session follows the card that IS the deck now
        want["asked"] = "deadguid"
    assert run(rt, builder("p160", "deadguid", spot=SPOT)) == want
    deck = the_new_deck(rt)
    assert deck["type"] == "Card" and deck["down"] is True and deck["ids"] == [160]
    loose(rt, 161)
    out = run(rt, to_top("p161", "deadguid", spot=SPOT))        # and the next card goes into it, found by the spot
    assert out["placed"] is True and out["quantity"] == 2


def test_hand_cards_into_no_deck_on_top_come_out_in_the_order_they_were_put(rt):
    hand(rt, 201, 202, 203)
    out = run(rt, hand_to_deck("Blue", [201, 202, 203], "deadguid", spot=SPOT))
    assert out["placed"] == [201, 202, 203] and out["quantity"] == 3
    deck = the_new_deck(rt)
    assert deck["down"] is True and deck["ids"] == [203, 202, 201], "each card goes on top of the one before"


def test_hand_cards_into_no_deck_at_the_bottom_keep_the_first_on_top_and_the_last_at_the_very_bottom(rt):
    hand(rt, 201, 202, 203)
    out = run(rt, hand_to_deck("Blue", [201, 202, 203], "deadguid", spot=SPOT, bottom=True))
    assert out["placed"] == [201, 202, 203]
    deck = the_new_deck(rt)
    assert deck["ids"] == [201, 202, 203] and deck["down"] is True, "turned back face down after the puts"


def test_hand_cards_into_no_deck_are_shuffled_when_asked(rt):
    hand(rt, 201, 202)
    run(rt, hand_to_deck("Blue", [201, 202], "deadguid", spot=SPOT, shuffle=True))
    assert the_new_deck(rt)["shuffled"] is True


def test_a_single_hand_card_into_no_deck_with_shuffle_does_not_call_shuffle_on_a_card(rt):
    hand(rt, 201)
    out = run(rt, hand_to_deck("Blue", [201], "deadguid", spot=SPOT, shuffle=True))
    assert out == {"placed": [201], "deck": "h201", "quantity": 1}


def test_the_mulligan_hand_goes_into_no_deck(rt):
    hand(rt, 201, 202, 203)
    out = run(rt, return_hand("Blue", "deadguid", spot=SPOT))
    assert out == {"returned": 3, "deck": True}
    assert sorted(the_new_deck(rt)["ids"]) == [201, 202, 203]


def test_the_card_a_hand_row_puts_on_the_deck_becomes_the_deck_when_there_is_none(rt):
    rt.execute("""mkobj({guid = 'r1', type = 'Card', cid = 301, owner = 'x', is_face_down = false, rot = Vector(0, 0, 0)})
mkobj({guid = 'r2', type = 'Card', cid = 302, owner = 'x', is_face_down = false, rot = Vector(0, 0, 0)})""")
    out = run(rt, hand_row(["r1", "r2"], "Blue", discard="r1", deck_guid="deadguid", deck_spot=SPOT))
    assert out["discarded"] == 301 and out["returned"] == [302] and "deck" not in out
    deck = the_new_deck(rt)
    assert deck["ids"] == [301] and deck["down"] is True


def test_a_hand_row_with_no_deck_and_no_place_to_lay_one_moves_nothing(rt):
    rt.execute("mkobj({guid = 'r1', type = 'Card', cid = 301, owner = 'x', is_face_down = false, rot = Vector(0, 0, 0)})")
    out = run(rt, hand_row(["r1"], "Blue", discard="r1", deck_guid="deadguid"))
    assert out["discarded"] is False and out["deck"] is False
    assert rt.eval('getObjectFromGUID("r1").moved_count') is None


def test_with_a_deck_on_the_table_nothing_changes(rt):
    rt.execute("""local cs = {}
for i = 1, 3 do cs[i] = {cid = 100 + i, guid = 'c' .. i, owner = 'x'} end
mkobj({guid = 'deck01', type = 'Deck', cards = cs, pos = Vector(0, 1, 3), rot = Vector(0, 0, 180)})""")
    loose(rt, 160, 161)
    assert run(rt, to_top("p160", "deck01", spot=SPOT)) == {"placed": True, "deck": "deck01", "quantity": 4}
    out = run(rt, shuffle("deck01", ["p161"], spot=SPOT))
    assert out["added"] == 1 and out["quantity"] == 5 and out["deck"] == "deck01"
