"""`lua.deck_reorder`: the blind reorder of the top cards of a deck (Golden Bat's Sight Beyond Sight and Jill Trent's Insightful Deduction
against the human's real deck), run on the Lua stub. The stub imitates live TTS where it matters here: a card put into a face-down deck
lies on top, the last card of a deck is a loose Card with a GUID of its own, a Card that receives a card becomes a Deck."""
import functools
import json

import pytest

from sparring.tts import lua
from test_effects_bridge import X_IDENT, X_IDS, deck, rt, run  # noqa: F401  (rt is a fixture)

reorder = functools.partial(lua.deck_reorder, id_range=X_IDS, identity=X_IDENT)
peek = functools.partial(lua.peek_deck_top, id_range=X_IDS, identity=X_IDENT)

LAYOUT = """
function ids_of_deck()
  for _, o in ipairs(OBJECTS) do
    if o.type == "Deck" and o.owner_side == nil and o.cards[1] ~= nil and o.cards[1].owner == "x" then
      local t = {}
      for _, c in ipairs(o.cards) do t[#t + 1] = c.cid end
      return t
    end
  end
  for _, o in ipairs(OBJECTS) do
    if o.type == "Card" and o.owner == "x" and o.guid ~= "loose1" then return {o.cid} end
  end
  return {}
end
function ours_facing()
  local down, up = 0, 0
  for _, o in ipairs(OBJECTS) do
    if (o.type == "Deck" or o.type == "Card") and o.owner ~= "h" and o.guid ~= "loose1" and o.is_face_down ~= false then down = down + 1 end
    if (o.type == "Deck" or o.type == "Card") and o.owner ~= "h" and o.guid ~= "loose1" and o.is_face_down == false then up = up + 1 end
  end
  return {down, up}
end
"""


@pytest.fixture
def table(rt):
    rt.execute(LAYOUT)
    rt.execute("""mkobj({guid = 'hdeck', type = 'Deck', pos = Vector(1, 1, 0), rot = Vector(0, 0, 180),
                         cards = {{cid = 201, guid = 'h1', owner = 'h'}, {cid = 202, guid = 'h2', owner = 'h'}}})""")
    return rt


def order_now(rt) -> list[int]:
    return list(rt.eval("ids_of_deck()").values())


def untouched(rt):
    """The loose card and the foreign deck never moved, and the foreign deck still holds its two cards."""
    assert rt.eval('getObjectFromGUID("loose1").moved_count') is None
    assert rt.eval('getObjectFromGUID("hdeck").moved_count') is None and rt.eval('#getObjectFromGUID("hdeck").cards') == 2
    assert rt.eval('getObjectFromGUID("hdeck").pos.x') == 1


def face_down_only(rt):
    down, up = rt.eval("ours_facing()").values()
    assert up == 0 and down >= 1, "nothing was turned over or laid face up"


def test_the_top_three_come_back_in_the_new_order_on_the_real_deck_face_down(table):
    rt = table
    deck(rt, n=6)
    out = run(rt, reorder("deck01", [101, 102, 103], [103, 101, 102]))
    assert out["reordered"] is True and out["moved"] is True and out["order"] == [103, 101, 102]
    assert out["quantity"] == out["was"] == 6
    assert order_now(rt) == [103, 101, 102, 104, 105, 106]
    assert rt.eval('getObjectFromGUID("deck01").pos.y') == 1 and rt.eval('getObjectFromGUID("deck01").is_face_down') is True
    face_down_only(rt)
    untouched(rt)


def test_one_card_goes_to_the_bottom_and_the_others_on_top(table):
    rt = table
    deck(rt, n=6)
    out = run(rt, reorder("deck01", [101, 102, 103], [103, 101], [102]))
    assert out["order"] == [103, 101] and out["last"] == 102 and out["quantity"] == out["was"] == 6
    assert order_now(rt) == [103, 101, 104, 105, 106, 102]
    face_down_only(rt)
    untouched(rt)


def test_the_reply_names_no_card_it_was_not_given(table):
    rt = table
    deck(rt, n=6)
    out = run(rt, reorder("deck01", [101, 102, 103], [102, 103, 101]))
    shown = json.dumps(out)
    assert "104" not in shown and "105" not in shown and "106" not in shown, "only the readback of the cards it moved"
    assert "last" not in out, "the bottom card is read back only when the bot buried one"


def test_a_top_that_is_not_what_was_read_changes_nothing(table):
    rt = table
    deck(rt, n=6)
    assert run(rt, reorder("deck01", [102, 101, 103], [101, 102, 103], [])) == {"reordered": False, "mismatch": True}
    assert run(rt, reorder("deck01", [101, 102, 107], [107, 102, 101])) == {"reordered": False, "mismatch": True}
    assert order_now(rt) == [101, 102, 103, 104, 105, 106]
    assert rt.eval("PUT_LOG") is None and rt.eval('getObjectFromGUID("deck01").moved_count') is None and rt.eval('#getObjectFromGUID("deck01").cards') == 6, "not a card was taken out"
    untouched(rt)


def test_a_top_that_has_fewer_cards_than_read_changes_nothing(table):
    rt = table
    deck(rt, n=2)
    assert run(rt, reorder("deck01", [101, 102, 103], [103, 102, 101]))["mismatch"] is True
    assert order_now(rt) == [101, 102]


def test_if_tts_gives_other_cards_than_the_ones_reported_they_all_go_back_as_they_were(table):
    rt = table
    deck(rt, n=4)
    rt.execute("""local d = getObjectFromGUID('deck01')
local data = d.getData
d.getData = function()                       -- the data lists the top two the other way round from how TTS really gives them
  local x = data()
  x.ContainedObjects[1], x.ContainedObjects[2] = x.ContainedObjects[2], x.ContainedObjects[1]
  return x
end""")
    out = run(rt, reorder("deck01", [102, 101], [101, 102]))
    assert out == {"reordered": False, "mismatch": True}
    assert order_now(rt) == [101, 102, 103, 104], "put back in the order they came off"
    face_down_only(rt)


def test_a_deck_of_exactly_the_cards_read_is_rebuilt_where_it_lay(table):
    rt = table
    deck(rt, n=3)
    out = run(rt, reorder("deck01", [101, 102, 103], [103, 101], [102]))
    assert out["reordered"] is True and out["quantity"] == out["was"] == 3 and out["order"] == [103, 101] and out["last"] == 102
    assert order_now(rt) == [103, 101, 102]
    new = rt.eval("(function() for _, o in ipairs(OBJECTS) do if o.type == 'Deck' and o.guid ~= 'hdeck' then return o end end end)()")
    assert (new.pos.x, new.pos.y, new.pos.z) == (0, 1, 0) and new.is_face_down is True and new.rot.z == 180
    face_down_only(rt)
    untouched(rt)


def test_a_deck_of_two_cards_swaps_without_leaving_a_loose_card(table):
    rt = table
    deck(rt, n=2)
    out = run(rt, reorder("deck01", [101, 102], [102, 101]))
    assert out["reordered"] is True and out["quantity"] == 2 and out["order"] == [102, 101]
    assert order_now(rt) == [102, 101]
    assert rt.eval("(function() local n = 0 for _, o in ipairs(OBJECTS) do if o.type == 'Card' and o.guid ~= 'loose1' then n = n + 1 end end return n end)()") == 0
    face_down_only(rt)


def test_a_deck_of_two_cards_with_one_sent_to_the_bottom_is_a_swap_too(table):
    rt = table
    deck(rt, n=2)
    out = run(rt, reorder("deck01", [101, 102], [102], [101]))
    assert order_now(rt) == [102, 101] and out["order"] == [102] and out["last"] == 101


def test_a_deck_of_one_card_is_its_own_top_and_bottom(table):
    rt = table
    rt.execute("mkobj({guid = 'last', type = 'Card', cid = 105, owner = 'x', is_face_down = true, pos = Vector(4, 1, 5), rot = Vector(0, 0, 180)})")
    assert run(rt, reorder("last", [105], [105]))["moved"] is False
    out = run(rt, reorder("last", [105], [], [105]))
    assert out["reordered"] is True and out["moved"] is False and out["order"] == [] and out["last"] == 105
    assert run(rt, reorder("last", [106], [106]))["mismatch"] is True
    assert rt.eval('getObjectFromGUID("last").moved_count') is None and rt.eval('getObjectFromGUID("last").is_face_down') is True


def test_the_remainder_left_as_a_loose_card_still_gets_the_bottom_card(table):
    rt = table
    deck(rt, n=4)                                   # taking three leaves one loose Card, which must be turned over for the bottom
    out = run(rt, reorder("deck01", [101, 102, 103], [102, 103], [101]))
    assert out["reordered"] is True and out["quantity"] == out["was"] == 4 and out["last"] == 101
    assert order_now(rt) == [102, 103, 104, 101]
    face_down_only(rt)
    untouched(rt)


def test_a_card_in_a_hand_is_never_taken_as_the_remainder(table):
    rt = table
    deck(rt, n=4)
    rt.execute("mkobj({guid = 'inhand', type = 'Card', cid = 150, owner = 'x', is_face_down = true, pos = Vector(0.5, 1, 0), hand = 'Blue'})")
    out = run(rt, reorder("deck01", [101, 102, 103], [103, 102, 101]))
    assert out["reordered"] is True
    assert rt.eval('getObjectFromGUID("inhand").moved_count') is None and rt.eval('getObjectFromGUID("inhand").hand') == "Blue"


def test_a_missing_or_foreign_deck_is_not_touched(table):
    rt = table
    deck(rt, n=2)
    assert run(rt, reorder("nodeck", [101], [101])) == {"reordered": False, "deck": False}
    assert run(rt, reorder("hdeck", [201, 202], [202, 201])) == {"reordered": False, "deck": False}
    untouched(rt)


def test_what_the_reader_gives_is_what_the_reorder_expects(table):
    rt = table
    deck(rt, n=5)
    ids = run(rt, peek("deck01", count=3))["ids"]
    out = run(rt, reorder("deck01", ids, list(reversed(ids))))
    assert out["reordered"] is True and run(rt, peek("deck01", count=3))["ids"] == list(reversed(ids))


def test_arguments_are_checked():
    with pytest.raises(ValueError):
        reorder("abc", [1, 2], [1, 3])                 # not a permutation
    with pytest.raises(ValueError):
        reorder("abc", [1, 1], [1, 1])                 # a card twice
    with pytest.raises(ValueError):
        reorder("abc", [], [])
    with pytest.raises(TypeError):
        reorder("abc", ["1"], ["1"])
    with pytest.raises(TypeError):
        lua.deck_reorder("abc", [1], [1])              # no identity
    with pytest.raises(ValueError):
        reorder("a b", [1], [1])
