"""F1 bridge pieces: set_state, token faces, pings, deck moves, token copies, bag placement and the read-only probe.

The Lua runs on the minimal table of `lua_stub.lua` (needs lupa); the batching is checked against FakeTTS."""
import functools
import json
import os

import pytest

from fake_tts import FakeTTS
from sparring import play
from sparring.board import Board
from sparring.tts import effects_bridge as eb
from sparring.tts import lua
from sparring.tts.client import TTSClient
from sparring.tts.hero_table import HeroTableError, load_hero_table

lupa = pytest.importorskip("lupa")
from lupa import lua54  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STUB = open(os.path.join(HERE, "lua_stub.lua"), encoding="utf-8").read()
MINI_STATES = {1: "f9789a", 2: "e6f06e"}
# The stub derives a card's images from its `owner`: owner 'x' is the bot's deck, anything else is foreign.
X_IDENT = (("https://img.test/x/face", "https://img.test/x/back"),)
X_IDS = (100, 600)
to_top = functools.partial(lua.card_to_deck_top, id_range=X_IDS, identity=X_IDENT)
to_bottom = functools.partial(lua.card_to_deck_bottom, id_range=X_IDS, identity=X_IDENT)
deal_row = functools.partial(lua.deal_row, id_range=X_IDS, identity=X_IDENT)


def conv(x):
    if lua54.lua_type(x) == "table":
        keys = list(x.keys())
        if not keys:
            return []
        if all(isinstance(k, int) for k in keys):
            return [conv(x[k]) for k in sorted(keys)]
        return {str(k): conv(x[k]) for k in keys}
    return x


@pytest.fixture
def rt():
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: json.dumps(conv(v))})
    return runtime


def run(rt, script):
    return json.loads(rt.execute(script))


def table_py(rt, expr):
    return conv(rt.eval(expr))


def mini(rt, state=1):
    rt.execute(f"""mkobj({{guid = '{MINI_STATES[state]}', type = 'Figurine', pos = Vector(3, 1, 4),
                        states = {{[1] = 'f9789a', [2] = 'e6f06e'}}, state_id = {state}}})""")


# ---------- set_state ----------
def test_set_state_swaps_hellboy_and_returns_the_new_guid(rt):
    mini(rt)
    assert run(rt, lua.set_state("f9789a", 2)) == {"guid": "e6f06e", "state": 2, "moved": "e6f06e"}
    assert rt.eval('getObjectFromGUID("f9789a")') is None
    new = rt.eval('getObjectFromGUID("e6f06e")')
    assert (new.pos.x, new.pos.z) == (3, 4)
    assert run(rt, lua.set_state("e6f06e", 1)) == {"guid": "f9789a", "state": 1, "moved": "f9789a"}


def test_set_state_to_the_state_it_is_in_does_nothing(rt):
    mini(rt, state=2)
    assert run(rt, lua.set_state("e6f06e", 2)) == {"guid": "e6f06e", "state": 2, "same": True}


def test_set_state_unknown_guid_and_bad_index(rt):
    assert run(rt, lua.set_state("nope", 2)) == {"changed": False}
    for bad in (0, 21, True, "2"):
        with pytest.raises(ValueError):
            lua.set_state("f9789a", bad)


def test_set_state_returning_nil_is_reported_as_not_changed(rt):
    mini(rt)
    rt.execute('getObjectFromGUID("f9789a").setState = function() return nil end')
    assert run(rt, lua.set_state("f9789a", 2)) == {"changed": False}
    assert rt.eval('getObjectFromGUID("f9789a")') is not None


def test_set_state_moved_makes_the_composite_wait_for_the_new_object(rt):
    mini(rt)
    script = lua.composite([lua.set_state("f9789a", 2)])
    assert 'type(r.moved) == "string"' in script          # the slow path keys off `moved`
    sent = []
    rt.globals().JSON = rt.table_from({"encode": lambda v: sent.append(json.dumps(conv(v))) or ""})
    rt.execute("DEFER = true")
    rt.execute(script)
    assert sent == [] and rt.eval("#PENDING") == 1          # waits on the condition instead of finishing at once
    rt.execute("PENDING[1].f()")
    assert json.loads(sent[0])["ops"][0]["moved"] == "e6f06e"


# ---------- token faces ----------
def token(rt, rot_z):
    rt.execute(f"mkobj({{guid = '1644a3', type = 'Custom_Token', rot = Vector(0, 90, {rot_z})}})")


def test_set_token_face_turns_only_when_needed(rt):
    token(rt, 180)
    assert run(rt, lua.set_token_face("1644a3", 0)) == {"rot_z": 0, "flipped": True}
    assert rt.eval('getObjectFromGUID("1644a3").rot.z') == 0
    assert rt.eval('getObjectFromGUID("1644a3").rot.y') == 90
    assert run(rt, lua.set_token_face("1644a3", 0)) == {"rot_z": 0, "flipped": False}
    assert run(rt, lua.set_token_face("1644a3", 360.0))["flipped"] is False


def test_flip_token_twice_comes_back(rt):
    token(rt, 180)
    assert run(rt, lua.flip_token("1644a3"))["rot_z"] == 0
    assert run(rt, lua.flip_token("1644a3"))["rot_z"] == 180
    assert run(rt, lua.flip_token("zzzz")) == {"flipped": False, "found": False}


def test_hellboy_token_faces_are_data_flagged_verify_live():
    t = load_hero_table("hellboy")
    assert eb.token_rot_z(t, "ability", "occult_detective") == 180
    assert eb.token_rot_z(t, "ability", "anung_un_rama") == 0
    assert t.token_faces["ability"]["verify_live"] is True and t.token_faces["ability"]["child"] == "30d50e"
    with pytest.raises(HeroTableError):
        eb.token_rot_z(t, "ability", "green")
    assert eb.state_guid(t, "hellboy", 1) == "f9789a" and eb.state_guid(t, "hellboy", 2) == "e6f06e"
    with pytest.raises(HeroTableError):
        eb.state_guid(t, "hellboy", 3)


# ---------- pings ----------
def ping_table(rt):
    rt.execute("""PLAYERS = {"Blue"}; SEATED = {Blue = true}
mkobj({guid = 'tok', type = 'Custom_Token', pos = Vector(1, 1, 1)})
mkobj({guid = 'e6f06e', type = 'Figurine', pos = Vector(5, 1, 6)})""")


def test_ping_objects_pings_each_group_in_order_with_a_gap(rt):
    ping_table(rt)
    assert run(rt, lua.ping_objects(["Blue"], [["tok"], ["f9789a", "e6f06e"]])) == {"queued": 2}
    assert rt.eval("#TIMERS") == 2 and rt.eval("PINGS") is None
    rt.execute("for _, f in ipairs(TIMERS) do f() end")
    pings = table_py(rt, "PINGS")
    assert [(p["x"], p["z"]) for p in pings] == [(1, 1), (5, 6)] and {p["color"] for p in pings} == {"Blue"}


def test_ping_objects_survives_a_missing_object(rt):
    ping_table(rt)
    run(rt, lua.ping_objects(["Blue"], [["gone"], ["tok"]]))
    rt.execute("for _, f in ipairs(TIMERS) do f() end")
    assert len(table_py(rt, "PINGS")) == 1


def test_ping_points_and_validation(rt):
    ping_table(rt)
    run(rt, lua.ping_points(["Blue"], [(2, 1, 3), (4, 1, 5)]))
    rt.execute("for _, f in ipairs(TIMERS) do f() end")
    assert [(p["x"], p["z"]) for p in table_py(rt, "PINGS")] == [(2, 3), (4, 5)]
    for bad in (lambda: lua.ping_objects([], [["a"]]), lambda: lua.ping_objects(["Blue"], []),
                lambda: lua.ping_objects(["Blue"], [[]]), lambda: lua.ping_objects(["Mauve"], [["a"]]),
                lambda: lua.ping_points(["Blue"], [])):
        with pytest.raises(ValueError):
            bad()


# ---------- decks ----------
def deck(rt, n=3, rot_z=180):
    rt.execute(f"""local cs = {{}}
for i = 1, {n} do cs[i] = {{cid = 100 + i, guid = 'c' .. i, owner = 'x'}} end
mkobj({{guid = 'deck01', type = 'Deck', cards = cs, pos = Vector(0, 1, 0), rot = Vector(0, 0, {rot_z})}})
mkobj({{guid = 'loose1', type = 'Card', cid = 555, owner = 'x'}})""")


def test_card_to_deck_top_does_not_turn_the_deck(rt):
    deck(rt)
    assert run(rt, to_top("loose1", "deck01")) == {"placed": True, "deck": "deck01", "quantity": 4}
    assert table_py(rt, "PUT_LOG") == [{"deck": "deck01", "card": "loose1", "rot_z": 180}]


def test_card_to_deck_bottom_turns_the_deck_over_for_the_put_and_back(rt):
    deck(rt)
    assert run(rt, to_bottom("loose1", "deck01"))["quantity"] == 4
    assert table_py(rt, "PUT_LOG")[0]["rot_z"] == 0      # 180 + 180 while the card went in
    assert rt.eval('getObjectFromGUID("deck01").rot.z') == 180


def test_card_to_deck_by_card_id_and_missing_pieces(rt):
    deck(rt)
    assert run(rt, to_top(555, "deck01"))["placed"] is True
    assert run(rt, to_top(9999, "deck01")) == {"placed": False}
    assert run(rt, to_bottom("loose1", "nodeck")) == {"placed": False, "deck": False}
    with pytest.raises(TypeError):
        lua.card_to_deck_top("loose1", "deck01")           # identity is mandatory


def test_card_to_deck_never_takes_a_card_from_a_hand_zone(rt):
    # Mirror match: the human's hand (Blue) holds the same CardID, listed BEFORE the loose card on the table.
    rt.execute("mkobj({guid = 'inhand', type = 'Card', cid = 555, owner = 'x', hand = 'Blue'})")
    deck(rt)
    assert run(rt, to_top(555, "deck01"))["placed"] is True
    assert table_py(rt, "PUT_LOG") == [{"deck": "deck01", "card": "loose1", "rot_z": 180}]
    assert rt.eval('getObjectFromGUID("inhand").hand') == "Blue"
    # Only the hand has it: nothing is taken, by CardID or by GUID.
    assert run(rt, to_top(555, "deck01")) == {"placed": False}
    assert run(rt, to_bottom("inhand", "deck01")) == {"placed": False}
    assert len(table_py(rt, "PUT_LOG")) == 1


def test_card_to_deck_refuses_a_deck_or_a_card_that_is_not_the_bots(rt):
    deck(rt)
    rt.execute("""mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 201, guid = 'h1', owner = 'h'}}})
mkobj({guid = 'hcard', type = 'Card', cid = 202, owner = 'h'})""")
    assert run(rt, to_top("loose1", "hdeck")) == {"placed": False, "deck": False}
    assert run(rt, to_bottom(555, "hdeck")) == {"placed": False, "deck": False}
    assert run(rt, to_top("hcard", "deck01")) == {"placed": False}
    assert run(rt, to_top(202, "deck01")) == {"placed": False}
    # Right image, CardID outside the bot's range: not ours either.
    assert run(rt, lua.card_to_deck_top("loose1", "deck01", id_range=(100, 200), identity=X_IDENT)) == {"placed": False}
    assert rt.eval("PUT_LOG") is None


def test_shuffle_into_deck_adds_and_shuffles(rt):
    deck(rt)
    rt.execute("mkobj({guid = 'loose2', type = 'Card', cid = 556, owner = 'x'})")
    out = run(rt, lua.shuffle_into_deck("deck01", ["loose1", "loose2", "ghost"]))
    assert out == {"added": 2, "moved": ["loose1", "loose2"], "deck": "deck01", "quantity": 5}
    assert rt.eval('getObjectFromGUID("deck01").shuffled') is True
    with pytest.raises(ValueError):
        lua.shuffle_into_deck("deck01", [])


def test_shuffle_into_deck_with_identity_never_takes_a_hand_card_nor_a_foreign_one(rt):
    # The human's own discard pile card shuffled into the human's deck (Ivan 29/10): same guards as the top/bottom puts.
    deck(rt)
    rt.execute("""mkobj({guid = 'inhand', type = 'Card', cid = 557, owner = 'x', hand = 'Blue'})
mkobj({guid = 'foreign', type = 'Card', cid = 558, owner = 'h'})
mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 201, guid = 'h1', owner = 'h'}}})""")
    shuffle = functools.partial(lua.shuffle_into_deck, id_range=X_IDS, identity=X_IDENT)
    out = run(rt, shuffle("deck01", ["loose1", "inhand", "foreign"]))
    assert out["added"] == 1 and out["deck"] == "deck01"
    assert rt.eval('getObjectFromGUID("inhand").hand') == "Blue"
    assert run(rt, shuffle("hdeck", ["loose1"])) == {"added": 0, "deck": False, "moved": []}     # a deck that is not ours


def test_deal_row_puts_the_top_cards_face_up_on_the_spots(rt):
    deck(rt, n=3)
    out = run(rt, deal_row("deck01", [(1, 2, 3), (4, 2, 3)], rot_y=90))
    assert out["dealt"] == ["c1", "c2"]
    assert rt.eval('getObjectFromGUID("c2").pos.x') == 4
    assert rt.eval('getObjectFromGUID("deck01").getQuantity()') == 1
    with pytest.raises(ValueError):
        deal_row("deck01", [])


def dissolving_deck(rt, n):
    """A deck that, like TTS, turns into a loose Card (same spot) when one card is left after a takeObject."""
    deck(rt, n=n)
    rt.execute("""getObjectFromGUID('loose1').destruct()
local d = getObjectFromGUID('deck01')
local take = d.takeObject
d.takeObject = function(t)
  local c = take(t)
  if d.getQuantity() == 1 then
    local last = d.cards[1]
    d.destruct()
    mkobj({guid = last.guid, type = 'Card', cid = last.cid, owner = last.owner, pos = d.getPosition()})
  end
  return c
end""")


def test_deal_row_last_card_is_found_loose_near_the_deck_and_a_foreign_card_there_is_ignored(rt):
    rt.execute("mkobj({guid = 'hcard', type = 'Card', cid = 202, owner = 'h', pos = Vector(0.5, 1, 0.5)})")
    dissolving_deck(rt, n=2)
    out = run(rt, deal_row("deck01", [(1, 2, 3), (4, 2, 3), (7, 2, 3)]))
    assert out["dealt"] == ["c1", "c2"]                        # the third spot stays empty: nothing of ours is left
    assert rt.eval('getObjectFromGUID("c2").pos.x') == 4
    assert rt.eval('getObjectFromGUID("hcard").pos.x') == 0.5


def test_deal_row_refuses_a_deck_that_is_not_the_bots(rt):
    rt.execute("mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 201, guid = 'h1', owner = 'h'}}})")
    assert run(rt, deal_row("hdeck", [(1, 2, 3)])) == {"dealt": [], "deck": False}
    assert rt.eval('getObjectFromGUID("hdeck").getQuantity()') == 1


# ---------- token copies, removal, bags ----------
def test_take_token_copy_from_an_infinite_bag_uses_take_object(rt):
    rt.execute("mkobj({guid = '5a17e9', type = 'Infinite', infinite = true, items = {{guid = 'tk', name = 'Intuition'}}})")
    out = run(rt, lua.take_token_copy("5a17e9", (1, 1, 1)))
    assert out["via"] == "takeObject" and out["taken"] == "tkx" and out["moved"] == "tkx"
    assert rt.eval("CLONES") is None


def test_take_token_copy_from_a_stack_uses_take_object(rt):
    rt.execute("mkobj({guid = '5a17e9', type = 'Custom_Token', cards = {{cid = 1, guid = 'a'}, {cid = 2, guid = 'b'}}})")
    assert run(rt, lua.take_token_copy("5a17e9", (1, 1, 1)))["via"] == "takeObject"


def test_take_token_copy_of_a_single_token_clones_it(rt):
    rt.execute("mkobj({guid = '5a17e9', type = 'Custom_Token', pos = Vector(9, 1, 9)})")
    out = run(rt, lua.take_token_copy("5a17e9", (2, 1, 2)))
    assert out["via"] == "clone" and out["taken"].startswith("clone")
    assert rt.eval("CLONES") == 1
    assert run(rt, lua.take_token_copy("zzz", (0, 0, 0))) == {"taken": False}


def test_remove_token(rt):
    token(rt, 0)
    assert run(rt, lua.remove_token("1644a3")) == {"removed": True}
    assert rt.eval('getObjectFromGUID("1644a3")') is None
    assert run(rt, lua.remove_token("1644a3")) == {"removed": False}


def test_remove_token_refuses_anything_that_is_not_a_token(rt):
    deck(rt)
    rt.execute(f"""mkobj({{guid = 'panel1', type = 'Custom_Tile', name = '{lua.PANEL_NAME}', gm = '{lua.MARKER}'}})
mkobj({{guid = 'bag001', type = 'Bag', items = {{}}}})
mkobj({{guid = 'scripted', type = 'Custom_Token', getLuaScript = function() return 'function onLoad() end' end}})""")
    assert run(rt, lua.remove_token("deck01")) == {"removed": False, "type": "Deck"}
    assert run(rt, lua.remove_token("loose1")) == {"removed": False, "type": "Card"}
    assert run(rt, lua.remove_token("panel1")) == {"removed": False, "type": "Custom_Tile"}
    assert run(rt, lua.remove_token("bag001")) == {"removed": False, "type": "Bag"}
    assert run(rt, lua.remove_token("scripted")) == {"removed": False, "type": "Custom_Token"}
    for g in ("deck01", "loose1", "panel1", "bag001", "scripted"):
        assert rt.eval(f'getObjectFromGUID("{g}")') is not None


def test_place_from_bag_by_name_and_by_guid(rt):
    rt.execute("mkobj({guid = 'bag001', type = 'Bag', items = {{guid = 'u1', name = 'Harpy'}, {guid = 'u2', name = 'Rat'}}})")
    assert run(rt, lua.place_from_bag("bag001", "Rat", (1, 1, 1))) == {"taken": "u2", "moved": "u2"}
    assert run(rt, lua.place_from_bag("bag001", "u1", (2, 1, 2)))["taken"] == "u1"
    assert run(rt, lua.place_from_bag("bag001", "Rat", (1, 1, 1))) == {"taken": False}
    assert run(rt, lua.place_from_bag("nobag", "Rat", (1, 1, 1))) == {"taken": False}
    with pytest.raises(ValueError):
        lua.place_from_bag("bag001", 'x"); os.exit() --', (0, 0, 0))


def test_move_human_piece_reuses_the_existing_piece_movement():
    board = Board.load("bprd-hq")
    space = next(iter(board.spaces))
    assert eb.move_human_piece(board, "e33604", space) == lua.move_piece(board, "e33604", space)


# ---------- batching: a whole effect is one message ----------
def test_form_change_is_three_ops_in_one_composite_that_runs(rt):
    t = load_hero_table("hellboy")
    mini(rt)
    token(rt, 180)
    rt.execute('PLAYERS = {"Blue"}; SEATED = {Blue = true}')
    ops = eb.form_change_ops(t, "hellboy", 1, 2, "ability", "anung_un_rama", ["Blue"])
    assert [o.split("\n")[0] for o in ops] == ["-- sparring:set_state", "-- sparring:set_token_face",
                                                 "-- sparring:ping_objects"]
    sent = []
    rt.globals().JSON = rt.table_from({"encode": lambda v: sent.append(json.dumps(conv(v))) or ""})
    rt.execute(lua.composite(ops))
    out = json.loads(sent[0])
    assert out["ops"][0] == {"guid": "e6f06e", "state": 2, "moved": "e6f06e"}
    assert out["ops"][1] == {"rot_z": 0, "flipped": True}
    rt.execute("for _, f in ipairs(TIMERS) do f() end")
    assert len(table_py(rt, "PINGS")) == 2        # the token, then the new miniature


def test_form_change_costs_one_lua_message():
    fake = FakeTTS()
    client = TTSClient(send_port=fake.port, listen_port=0)
    try:
        t = load_hero_table("hellboy")
        client.execute_lua(lua.composite(eb.form_change_ops(t, "hellboy", 1, 2, "ability", "anung_un_rama", ["Blue"])))
        import time
        for _ in range(100):
            if fake.received:
                break
            time.sleep(0.02)
        assert fake.lua_messages == 1 and {m["messageID"] for m in fake.received} == {3}
    finally:
        client.close()
        fake.close()


def test_reveal_hand_ops_show_the_hand_and_ping_the_spots():
    ops = eb.reveal_hand_ops([17600], [(1.0, 2.0, 3.0)], 0, "Green", identity=(("https://img.test/f", "https://img.test/b"),), id_range=(17600, 17629),
                             ping_seats=["Blue"])
    assert [o.split("\n")[0] for o in ops] == ["-- sparring:show_hand_row", "-- sparring:ping_points"]
    assert lua.composite(ops)


def test_take_token_copy_op_uses_the_token_guid_from_the_data():
    t = load_hero_table("abe-sapien")
    assert t.token_sources["intuition"]["verify_live"] is True
    assert eb.take_token_copy_op(t, "intuition", (0, 1, 0)) == lua.take_token_copy("5a17e9", (0, 1, 0))
    with pytest.raises(HeroTableError):
        eb.take_token_copy_op(t, "nothing", (0, 1, 0))


# ---------- read-only diagnostics ----------
def test_inspect_objects_is_read_only_and_the_mutators_are_not():
    assert "inspect_objects" in play.READ_ONLY_TAGS
    for tag in ("set_state", "set_token_face", "flip_token", "ping_objects", "card_to_deck_top", "card_to_deck_bottom",
                "shuffle_into_deck", "deal_row", "take_token_copy", "remove_token", "place_from_bag"):
        assert tag not in play.READ_ONLY_TAGS


def test_inspect_objects_reports_type_rotation_states_and_children(rt):
    mini(rt)
    rt.execute("mkobj({guid = '1644a3', type = 'Custom_Token', rot = Vector(0, 0, 180), "
               "attached = {{guid = '30d50e', name = 'OCCULT DETECTIVE'}}})")
    out = run(rt, lua.inspect_objects(["f9789a", "1644a3", "ghost1"]))
    assert out["ghost1"] == {"found": False}
    assert out["f9789a"]["state_id"] == 1 and out["f9789a"]["state_ids"] == [1, 2]
    assert out["1644a3"]["type"] == "Custom_Token" and out["1644a3"]["rot_z"] == 180
    assert out["1644a3"]["attached"] == [{"guid": "30d50e", "name": "OCCULT DETECTIVE"}]


def test_bridge_objects_report_lists_hellboy_and_abe_objects():
    assert play._bridge_objects("hellboy") == {
        "hellboy hellboy state 1": "f9789a", "hellboy hellboy state 2": "e6f06e", "hellboy token ability": "1644a3",
        "hellboy token ability child": "30d50e"}
    assert play._bridge_objects("abe-sapien") == {"abe-sapien token intuition (source)": "5a17e9"}
    assert play._bridge_objects("medusa") == {}

    class Cfg:
        heroes = ("medusa", "hellboy")

    seen = []

    def read(label, builder):
        seen.append(builder())
        return {"1644a3": {"found": True, "type": "Custom_Token", "name": "x", "rot_x": 0, "rot_y": 0, "rot_z": 180,
                           "attached": [{"guid": "30d50e", "name": "blue"}]}}
    lines = play._bridge_objects_report(read, Cfg)
    assert len(seen) == 1 and seen[0].startswith("-- sparring:inspect_objects")
    assert any("1644a3" in ln and "Custom_Token" in ln and "rot (0, 0, 180)" in ln and "30d50e" in ln for ln in lines)
    assert any("f9789a" in ln and "not found" in ln for ln in lines)


# ---------- hand_to_deck (D3): the bot's hand cards into its deck, the one route out of a hand zone ----------
hand_to_deck = functools.partial(lua.hand_to_deck, id_range=X_IDS, identity=X_IDENT)


def hand_table(rt):
    deck(rt, n=2)
    rt.execute("""mkobj({guid = 'h1', type = 'Card', cid = 201, owner = 'x', hand = 'Blue'})
mkobj({guid = 'h2', type = 'Card', cid = 202, owner = 'x', hand = 'Blue'})
mkobj({guid = 'h3', type = 'Card', cid = 203, owner = 'x', hand = 'Blue'})
mkobj({guid = 'alien', type = 'Card', cid = 204, owner = 'h', hand = 'Blue'})
mkobj({guid = 'theirs', type = 'Card', cid = 205, owner = 'x', hand = 'Red'})""")


def test_hand_to_deck_puts_the_listed_hand_cards_on_top_in_order_and_nothing_else(rt):
    hand_table(rt)
    out = run(rt, hand_to_deck("Blue", [202, 201, 555, 205, 204], "deck01"))
    assert out == {"placed": [202, 201], "deck": "deck01", "quantity": 4}
    assert [p["card"] for p in table_py(rt, "PUT_LOG")] == ["h2", "h1"]
    assert all(p["rot_z"] == 180 for p in table_py(rt, "PUT_LOG"))      # the deck was not turned over
    assert rt.eval('getObjectFromGUID("h3").hand') == "Blue" and rt.eval('getObjectFromGUID("loose1")') is not None
    assert rt.eval('getObjectFromGUID("alien").hand') == "Blue" and rt.eval('getObjectFromGUID("theirs").hand') == "Red"
    assert rt.eval('getObjectFromGUID("deck01").shuffled') is None


def test_hand_to_deck_bottom_turns_the_deck_over_for_the_puts_and_back(rt):
    hand_table(rt)
    out = run(rt, hand_to_deck("Blue", [201, 203], "deck01", bottom=True))
    assert out["placed"] == [201, 203] and out["quantity"] == 4
    assert [p["rot_z"] for p in table_py(rt, "PUT_LOG")] == [0, 0]       # 180 + 180 while the cards went in
    assert rt.eval('getObjectFromGUID("deck01").rot.z') == 180


def test_hand_to_deck_shuffle_shuffles_after_the_puts(rt):
    hand_table(rt)
    out = run(rt, hand_to_deck("Blue", [201], "deck01", shuffle=True))
    assert out["placed"] == [201] and rt.eval('getObjectFromGUID("deck01").shuffled') is True


def test_hand_to_deck_refuses_a_deck_that_is_not_the_bots_and_bad_arguments(rt):
    hand_table(rt)
    rt.execute("mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 301, guid = 'x1', owner = 'h'}}})")
    assert run(rt, hand_to_deck("Blue", [201], "hdeck")) == {"placed": [], "deck": False}
    assert run(rt, hand_to_deck("Blue", [201], "nodeck")) == {"placed": [], "deck": False}
    assert rt.eval('getObjectFromGUID("h1").hand') == "Blue"
    for bad in (lambda: hand_to_deck("Blue", [], "deck01"), lambda: hand_to_deck("Mauve", [201], "deck01"),
                lambda: hand_to_deck("Blue", [201], "deck01", bottom="yes")):
        with pytest.raises((ValueError, TypeError)):
            bad()
    with pytest.raises(TypeError):
        lua.hand_to_deck("Blue", [201], "deck01")                        # identity is mandatory
    assert lua.is_sendable(hand_to_deck("Blue", [201], "deck01"))



# ---------- cards inside a stacked pile (Rekindle, Ivan 31/10) ----------
def pile(rt, n=4, owner="x"):
    """A discard pile stacked as a Deck: its cards are not loose objects, `getObjectFromGUID` only finds the Deck."""
    rt.execute(f"""local cs = {{}}
for i = 1, {n} do cs[i] = {{cid = 300 + i, guid = 'p' .. i, owner = '{owner}'}} end
mkobj({{guid = 'pile01', type = 'Deck', cards = cs, pos = Vector(9, 1, 9)}})""")


def test_shuffle_into_deck_takes_the_cards_out_of_a_stacked_pile(rt):
    deck(rt)
    pile(rt, n=4)
    out = run(rt, lua.shuffle_into_deck("deck01", ["p1", "p3", "p4"], id_range=X_IDS, identity=X_IDENT))
    assert out["added"] == 3 and out["moved"] == ["p1", "p3", "p4"] and out["deck"] == "deck01"
    assert out["quantity"] == 6 and rt.eval('getObjectFromGUID("deck01").shuffled') is True
    assert rt.eval('getObjectFromGUID("pile01").getQuantity()') == 1


def test_shuffle_into_deck_reports_only_the_cards_that_moved(rt):
    deck(rt)
    pile(rt, n=3)
    rt.execute("mkobj({guid = 'foreign', type = 'Card', cid = 558, owner = 'h'})")
    out = run(rt, lua.shuffle_into_deck("deck01", ["p2", "ghost", "foreign"], id_range=X_IDS, identity=X_IDENT))
    assert out["added"] == 1 and out["moved"] == ["p2"]


def test_shuffle_into_deck_keeps_going_when_the_pile_dissolves_into_a_card(rt):
    deck(rt)
    pile(rt, n=2)
    rt.execute("""local d = getObjectFromGUID('pile01')
local take = d.takeObject
d.takeObject = function(t)
  local c = take(t)
  if d.getQuantity() == 1 then
    local last = d.cards[1]
    d.destruct()
    mkobj({guid = last.guid, type = 'Card', cid = last.cid, owner = last.owner, pos = d.getPosition()})
  end
  return c
end""")
    out = run(rt, lua.shuffle_into_deck("deck01", ["p1", "p2"], id_range=X_IDS, identity=X_IDENT))
    assert out["moved"] == ["p1", "p2"]


def test_a_card_inside_a_foreign_pile_is_not_taken(rt):
    deck(rt)
    pile(rt, n=2, owner="h")
    out = run(rt, lua.shuffle_into_deck("deck01", ["p1"], id_range=X_IDS, identity=X_IDENT))
    assert out["moved"] == [] and out["added"] == 0
    assert rt.eval('getObjectFromGUID("pile01").getQuantity()') == 2
