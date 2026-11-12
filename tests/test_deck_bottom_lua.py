"""A card sent to the BOTTOM of a draw deck (F-STRANGE-PACT-DRAW, live 12/11: DARK PACT's card lay on TOP and the pact's own draw
took it back). `putObject` lays a card on the draw top whatever the deck's facing, so the bottom is reached by rebuilding the deck
from its data, on a later frame: whatever the same script deals meanwhile comes off the untouched deck.

The Lua runs on `lua_stub.lua` (needs lupa); FRAME_MODE makes the stub keep frames like live TTS does."""
import functools
import json

import pytest

from sparring.tts import lua
from test_effects_bridge import STUB, X_IDENT, X_IDS, conv, run, table_py

lupa = pytest.importorskip("lupa")
from lupa import lua54  # noqa: E402

SPOT = (0.0, 0.0)
to_bottom = functools.partial(lua.card_to_deck_bottom, id_range=X_IDS, identity=X_IDENT, spot=SPOT)
to_top = functools.partial(lua.card_to_deck_top, id_range=X_IDS, identity=X_IDENT, spot=SPOT)
hand_to_deck = functools.partial(lua.hand_to_deck, id_range=X_IDS, identity=X_IDENT, spot=SPOT)
deal = functools.partial(lua.deal_cards, id_range=X_IDS, identity=X_IDENT, spot=SPOT)


@pytest.fixture
def rt():
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: json.dumps(conv(v))})
    return runtime


def deck(rt, n=3):
    rt.execute(f"""local cs = {{}}
for i = 1, {n} do cs[i] = {{cid = 100 + i, guid = 'c' .. i, owner = 'x'}} end
mkobj({{guid = 'deck01', type = 'Deck', cards = cs, pos = Vector(0, 1, 0), rot = Vector(0, 90, 180)}})""")


def loose(rt, guid="loose1", cid=555):
    rt.execute(f"mkobj({{guid = '{guid}', type = 'Card', cid = {cid}, owner = 'x', pos = Vector(9, 1, 9), is_face_down = false}})")


def lone(rt):
    rt.execute("mkobj({guid = 'last01', type = 'Card', cid = 101, owner = 'x', pos = Vector(0, 1, 0), rot = Vector(0, 90, 180), is_face_down = true})")


def the_deck(rt):
    """The face-down deck (or lone card) of the table: its type, GUID, CardIDs (top first), place and turn."""
    found = table_py(rt, """(function()
  local out = {}
  for _, o in ipairs(getObjects()) do
    if (o.type == "Deck" or o.type == "Card") and o.is_face_down and not o.hand then
      local ids = {}
      if o.type == "Deck" then for i, c in ipairs(o.cards) do ids[i] = c.cid end else ids[1] = o.cid end
      out[#out + 1] = {type = o.type, guid = o.guid, ids = ids, x = o.pos.x, z = o.pos.z, turn = o.getRotation().y}
    end
  end
  return out
end)()""")
    assert len(found) == 1, found
    return found[0]


def hand(rt, color="Blue"):
    return table_py(rt, f"""(function()
  local ids = {{}}
  for _, o in ipairs(Player["{color}"].getHandObjects()) do ids[#ids + 1] = o.cid end
  return ids
end)()""")


def in_frames(rt, ops, frames=240):
    """Runs the ops as ONE composite on a table that keeps frames. Returns the reply, the frame it came in, the deck the table
    showed at that moment and how many objects it had."""
    sent = []

    def reply(v):
        sent.append((json.loads(json.dumps(conv(v))), rt.eval("NOW"), the_deck(rt), rt.eval("#getObjects()")))
        return ""
    rt.execute("FRAME_MODE = true")
    rt.globals().JSON = rt.table_from({"encode": reply})
    rt.execute(lua.composite(ops))
    for _ in range(frames):
        if sent:
            break
        rt.execute("tick()")
    assert len(sent) == 1, "the composite replied once"
    return sent[0]


# ---------- the live bug: DARK PACT sends the card to the bottom and draws, in one script ----------
def test_a_card_sent_to_the_bottom_is_not_the_card_the_same_script_deals(rt):
    deck(rt)
    loose(rt)
    out, _, _, _ = in_frames(rt, [to_bottom(555, "deck01"), deal("deck01", 1, "Blue")])
    assert out["ops"][1] == {"dealt": 1}
    assert hand(rt) == [101], "the draw is the card that was on top, not the one just sent to the bottom"
    assert the_deck(rt)["ids"] == [102, 103, 555]
    assert out["ops"][0]["placed"] is True and out["ops"][0]["quantity"] == 3
    assert out["ops"][0]["deck"] == the_deck(rt)["guid"] and out["ops"][0]["asked"] == "deck01"


def test_the_composite_answers_only_when_the_deck_is_whole_again(rt):
    deck(rt)
    loose(rt)
    _, frame, seen, objects = in_frames(rt, [to_bottom(555, "deck01")])
    assert frame > 0, "it waited for the deck"
    assert seen["ids"] == [101, 102, 103, 555], "the reply already reads the rebuilt deck"
    assert objects == 1, "neither the old deck nor the loose card is on the table any more: the snapshot reads no stray card"
    assert rt.eval("sparringBury.busy") == 0


def test_cards_sent_to_the_bottom_one_after_another_end_in_that_order_with_one_rebuild(rt):
    deck(rt)
    loose(rt)
    loose(rt, "loose2", 556)
    out, _, _, _ = in_frames(rt, [to_bottom("loose1", "deck01"), to_bottom("loose2", "deck01")])
    assert the_deck(rt)["ids"] == [101, 102, 103, 555, 556] and rt.eval("SPAWNED") == 1
    assert [o["placed"] for o in out["ops"]] == [True, True] and {o["quantity"] for o in out["ops"]} == {5}


def test_a_card_put_on_top_in_the_same_script_stays_on_top(rt):
    deck(rt)
    loose(rt)
    loose(rt, "loose2", 556)
    in_frames(rt, [to_bottom("loose1", "deck01"), to_top("loose2", "deck01")])
    assert the_deck(rt)["ids"] == [556, 101, 102, 103, 555]


def test_the_deal_that_empties_the_deck_leaves_the_buried_card_as_the_deck(rt):
    deck(rt, n=2)
    loose(rt)
    out, _, _, _ = in_frames(rt, [to_bottom(555, "deck01"), deal("deck01", 2, "Blue")])
    assert sorted(hand(rt)) == [101, 102]
    d = the_deck(rt)
    assert d["ids"] == [555] and d["type"] == "Card" and (d["x"], d["z"]) == SPOT
    assert out["ops"][0]["placed"] is True and out["ops"][0]["quantity"] == 1


def test_a_card_that_is_gone_when_the_deck_is_rebuilt_is_reported_not_placed(rt):
    deck(rt)
    loose(rt)
    rt.execute("FRAME_MODE = true")
    sent = []
    rt.globals().JSON = rt.table_from({"encode": lambda v: sent.append(json.loads(json.dumps(conv(v)))) or ""})
    rt.execute(lua.composite([to_bottom("loose1", "deck01")]))
    rt.execute("getObjectFromGUID('loose1').getData = function() error('destroyed') end")
    rt.execute("tick(240)")
    assert sent[0]["ops"][0]["placed"] is False and the_deck(rt)["ids"] == [101, 102, 103] and the_deck(rt)["guid"] == "deck01"


# ---------- card_to_deck_bottom alone (on the plain stub everything deferred runs at once) ----------
def test_bottom_of_a_deck_of_several_cards(rt):
    deck(rt)
    loose(rt)
    out = run(rt, to_bottom("loose1", "deck01"))
    d = the_deck(rt)
    assert d["ids"] == [101, 102, 103, 555] and (d["x"], d["z"], d["turn"]) == (0, 0, 90)
    assert out == {"placed": True, "asked": "deck01", "deck": d["guid"], "quantity": 4}
    assert rt.eval("getObjectFromGUID('loose1')") is None and rt.eval("PUT_LOG") is None, "no putObject: it only knows the top"


def test_bottom_of_a_deck_that_is_one_last_card(rt):
    lone(rt)
    loose(rt)
    out = run(rt, to_bottom(555, "last01"))
    d = the_deck(rt)
    assert d["type"] == "Deck" and d["ids"] == [101, 555] and (d["x"], d["z"], d["turn"]) == (0, 0, 90)
    assert out["placed"] is True and out["deck"] == d["guid"] and out["quantity"] == 2
    assert rt.eval("#getObjects()") == 1


def test_bottom_of_a_deck_that_is_not_there_lays_the_card_as_the_deck(rt):
    loose(rt)
    out = run(rt, to_bottom(555, "gone01"))
    d = the_deck(rt)
    assert d["type"] == "Card" and d["ids"] == [555] and (d["x"], d["z"]) == SPOT
    assert out == {"placed": True, "asked": "gone01", "deck": "loose1", "quantity": 1}
    rt.execute("getObjectFromGUID('loose1').destruct()")
    loose(rt)
    assert run(rt, lua.card_to_deck_bottom(555, "gone01", id_range=X_IDS, identity=X_IDENT)) == {"placed": False, "deck": False}


def test_the_rebuilt_deck_is_still_the_bots_and_takes_the_next_card(rt):
    deck(rt)
    loose(rt)
    loose(rt, "loose2", 556)
    run(rt, to_bottom(555, "deck01"))
    out = run(rt, to_bottom(556, "deck01"))               # the GUID asked for is stale now: found where the deck lies
    assert the_deck(rt)["ids"] == [101, 102, 103, 555, 556] and out["placed"] is True and out["quantity"] == 5
    assert run(rt, deal("deck01", 1, "Blue")) == {"dealt": 1} and hand(rt) == [101]


# ---------- hand_to_deck(bottom=True) ----------
def hand_cards(rt, *cids):
    for cid in cids:
        rt.execute(f"mkobj({{guid = 'h{cid}', type = 'Card', cid = {cid}, owner = 'x', hand = 'Blue', is_face_down = false}})")


def test_hand_cards_to_the_bottom_of_a_deck_in_the_order_given(rt):
    deck(rt)
    hand_cards(rt, 201, 202, 203)
    out = run(rt, hand_to_deck("Blue", [203, 201, 999], "deck01", bottom=True))
    d = the_deck(rt)
    assert d["ids"] == [101, 102, 103, 203, 201] and hand(rt) == [202]
    assert out == {"placed": [203, 201], "asked": "deck01", "deck": d["guid"], "quantity": 5}
    assert rt.eval("PUT_LOG") is None


def test_hand_cards_to_the_bottom_of_a_last_card_and_of_no_deck(rt):
    lone(rt)
    hand_cards(rt, 201, 202)
    assert run(rt, hand_to_deck("Blue", [201], "last01", bottom=True))["quantity"] == 2
    assert the_deck(rt)["ids"] == [101, 201]
    rt.execute(f"getObjectFromGUID('{the_deck(rt)['guid']}').destruct()")
    hand_cards(rt, 203)
    out = run(rt, hand_to_deck("Blue", [202, 203], "gone01", bottom=True))
    d = the_deck(rt)
    assert d["type"] == "Deck" and d["ids"] == [202, 203] and (d["x"], d["z"]) == SPOT and hand(rt) == []
    assert out["placed"] == [202, 203] and out["deck"] == d["guid"] and out["quantity"] == 2


def test_hand_cards_to_the_bottom_with_nothing_to_move_or_nowhere_to_lay(rt):
    deck(rt)
    hand_cards(rt, 201)
    assert run(rt, hand_to_deck("Blue", [999], "deck01", bottom=True)) == {"placed": [], "deck": "deck01", "quantity": 3}
    rt.execute("getObjectFromGUID('deck01').destruct()")
    assert run(rt, lua.hand_to_deck("Blue", [201], "gone01", id_range=X_IDS, identity=X_IDENT, bottom=True)) == {"placed": [], "deck": False}
    assert hand(rt) == [201]


def test_hand_cards_to_the_bottom_then_a_draw_in_one_composite(rt):
    deck(rt)
    hand_cards(rt, 201, 202)
    out, _, _, _ = in_frames(rt, [hand_to_deck("Blue", [201, 202], "deck01", bottom=True), deal("deck01", 2, "Blue")])
    assert hand(rt) == [101, 102] and the_deck(rt)["ids"] == [103, 201, 202]
    assert out["ops"][0]["placed"] == [201, 202] and out["ops"][0]["quantity"] == 3


# ---------- the two other writers that reach the bottom: the top card sent under (peek) and the blind reorder ----------
def test_the_top_card_sent_under_and_a_draw_in_one_composite(rt):
    deck(rt, n=4)
    under = lua.deck_top_to_bottom("deck01", 101, id_range=X_IDS, identity=X_IDENT, spot=SPOT)
    out, _, seen, objects = in_frames(rt, [under, deal("deck01", 1, "Blue")])
    assert hand(rt) == [102] and seen["ids"] == [103, 104, 101] and objects == 2, "the deck and the card drawn: nothing left above it"
    assert out["ops"][0] == {"moved": True, "asked": "deck01", "deck": seen["guid"]}


def test_a_blind_reorder_reads_the_bottom_card_back_from_the_rebuilt_deck(rt):
    deck(rt, n=6)
    reorder = lua.deck_reorder("deck01", [101, 102, 103], [103, 101], [102], id_range=X_IDS, identity=X_IDENT, spot=SPOT)
    out, _, seen, objects = in_frames(rt, [reorder])
    assert seen["ids"] == [103, 101, 104, 105, 106, 102] and objects == 1
    res = out["ops"][0]
    assert res["reordered"] is True and res["order"] == [103, 101] and res["last"] == 102 and res["quantity"] == res["was"] == 6
    assert res["deck"] == seen["guid"] and res["asked"] == "deck01"


def test_a_blind_reorder_whose_bottom_card_is_lost_says_so(rt):
    deck(rt, n=6)
    reorder = lua.deck_reorder("deck01", [101, 102, 103], [103, 101], [102], id_range=X_IDS, identity=X_IDENT, spot=SPOT)
    rt.execute("FRAME_MODE = true")
    sent = []
    rt.globals().JSON = rt.table_from({"encode": lambda v: sent.append(json.loads(json.dumps(conv(v)))) or ""})
    rt.execute(lua.composite([reorder]))
    rt.execute("getObjectFromGUID('c2').getData = function() error('destroyed') end")
    rt.execute("tick(240)")
    res = sent[0]["ops"][0]
    assert res["reordered"] is False and res["quantity"] == 5 and res["last"] == 106, "the session's check fails and says it"


def test_a_card_waiting_above_the_deck_is_never_taken_for_the_deck(rt):
    """The top card of a deck of two is lifted to go under the other: until the rebuild both are face-down cards at the deck's
    place, and a draw that looks for the deck there (its GUID is gone) must take the one that lies, not the one that waits,
    whichever the table lists first."""
    for zone in (None, "dzone1"):
        rt.execute("""for i = #OBJECTS, 1, -1 do table.remove(OBJECTS, i) end
WAITS, sparringBury = {}, nil
mkobj({guid = 'dzone1', type = 'Scripting', cx = 0, cz = 0, hw = 2, hd = 2})""")
        deck(rt, n=2)
        rt.execute("FRAME_MODE = true")
        out = run(rt, lua.deck_top_to_bottom("deck01", 101, id_range=X_IDS, identity=X_IDENT, spot=SPOT, zone=zone))
        assert out["moved"] is True and rt.eval("getObjectFromGUID('c1').locked") is True
        rt.execute("""local waiting = getObjectFromGUID('c1')
for i, o in ipairs(OBJECTS) do if o == waiting then table.remove(OBJECTS, i) break end end
table.insert(OBJECTS, 1, waiting)""")
        assert run(rt, lua.deal_cards("gone01", 1, "Blue", id_range=X_IDS, identity=X_IDENT, spot=SPOT, zone=zone)) == {"dealt": 1}
        assert rt.eval("getObjectFromGUID('c2').is_face_down") is False, "the card that lay as the deck is the one drawn"
        assert rt.eval("getObjectFromGUID('c1').is_face_down") is True
        rt.execute("FRAME_MODE = false")
