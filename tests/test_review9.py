"""Review 9: deck identity, old snapshots, "Processing..." and details.

The Lua tests run the generated scripts with lupa on a minimal table (`lua_stub.lua`); without lupa they are skipped
(`uv run --with pytest --with lupa pytest`)."""
import json
import math
import os

import pytest

from fake_tts import FakeTTS
from sparring.tts import lua, ui
from sparring.tts.client import TTSClient
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_session import Table

lupa = pytest.importorskip("lupa")
from lupa import lua54  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STUB = open(os.path.join(HERE, "lua_stub.lua"), encoding="utf-8").read()
BOT_ID = (("https://img.test/medusa/face", "https://img.test/medusa/back"),)
HUMAN_ID = (("https://img.test/hellboy/face", "https://img.test/hellboy/back"),)
SCOPE = lua.Scope(("Green", "White"), ("906a7a", "b7a0b8"), ((6.0, -18.0), (-2.0, -18.0), (11.5, 12.0)))


def conv(x):
    if lua54.lua_type(x) == "table":
        keys = list(x.keys())
        if not keys:
            return []                       # like TTS's JSON.encode: an empty table is a list
        if all(isinstance(k, int) for k in keys):
            return [conv(x[k]) for k in sorted(keys)]
        return {str(k): conv(x[k]) for k in keys}
    return x


@pytest.fixture
def rt():
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: json.dumps(conv(v))})
    runtime.execute("""
mkobj({guid = '906a7a', type = 'Scripting', cx = 15, cz = 0, hw = 5, hd = 12})
mkobj({guid = 'b7a0b8', type = 'Scripting', cx = -12.5, cz = 0, hw = 6, hd = 12})
""")
    return runtime


def run(runtime, script, rid=1):
    n = len(runtime.globals().SENT)
    runtime.execute(lua.request(script, rid))
    sent = runtime.globals().SENT
    assert len(sent) == n + 1, "one reply per script"
    reply = conv(sent[n + 1])
    assert "err" not in reply, reply
    return json.loads(reply["value"])


def owners(runtime, guid):
    d = runtime.globals().getObjectFromGUID(guid)
    return sorted(d.cards[i].owner for i in range(1, len(d.cards) + 1))


def medusa_table(runtime):
    """Medusa's deck spread over the table and, mixed with it, foreign cards that share its CardIDs."""
    runtime.execute("""
local cards = {}
for i = 0, 19 do table.insert(cards, {cid = 17600 + i, guid = 'm' .. i, owner = 'medusa'}) end
mkobj({guid = 'd42056', type = 'Deck', cards = cards, pos = {x = 11.5, y = 1, z = 12}})
for i = 20, 24 do mkobj({guid = 'h' .. i, type = 'Card', cid = 17600 + i, owner = 'medusa', hand = 'Green'}) end
for i = 25, 27 do mkobj({guid = 'h' .. i, type = 'Card', cid = 17600 + i, owner = 'medusa', pos = {x = 13, y = 1, z = 0}}) end
mkobj({guid = 'h28', type = 'Card', cid = 17628, owner = 'medusa', pos = {x = 6, y = 1, z = -18}})
mkobj({guid = 'h29', type = 'Card', cid = 17629, owner = 'medusa', pos = {x = -10, y = 1, z = 3}})
mkobj({guid = 'alice5', type = 'Card', cid = 17605, owner = 'alice', pos = {x = 14, y = 1, z = 2}})
mkobj({guid = 'alice6', type = 'Card', cid = 17606, owner = 'alice', hand = 'White'})
local rosie = {}
for i = 0, 29 do table.insert(rosie, {cid = 17600 + i, guid = 'r' .. i, owner = 'rosie'}) end
mkobj({guid = 'rosie1', type = 'Deck', cards = rosie, pos = {x = 13, y = 1, z = 4}})
mkobj({guid = 'rosie2', type = 'Deck', cards = rosie, pos = {x = 70, y = 1, z = -40}})
mkobj({guid = 'mix1', type = 'Deck', pos = {x = 14, y = 1, z = -3},
       cards = {{cid = 17601, guid = 'x1', owner = 'medusa'}, {cid = 4203, guid = 'x2', owner = 'other'}}})
""")


# ---------- 1. deck identity ----------
def test_reset_deck_gathers_exactly_the_30_cards_of_the_bot_and_moves_no_foreign_card(rt):
    medusa_table(rt)
    res = run(rt, lua.reset_deck("d42056", (11.5, 12.0), lua.BOT_CARD_IDS, identity=BOT_ID, scope=SCOPE))
    assert res == {"deck": True, "quantity": 30}
    assert owners(rt, "d42056") == ["medusa"] * 30
    g = rt.globals()
    for guid in ("alice5", "alice6", "rosie1", "rosie2", "mix1"):
        o = g.getObjectFromGUID(guid)
        assert o is not None and o.moved_count is None, f"{guid} is foreign and is not touched"
    assert len(owners(rt, "rosie1")) == 30 and len(owners(rt, "mix1")) == 2


def test_reset_deck_never_looks_outside_the_hands_zones_and_card_spots(rt):
    medusa_table(rt)
    rt.execute("mkobj({guid = 'far1', type = 'Card', cid = 17603, owner = 'medusa', pos = {x = 60, y = 1, z = 30}})")
    res = run(rt, lua.reset_deck("d42056", (11.5, 12.0), lua.BOT_CARD_IDS, identity=BOT_ID, scope=SCOPE))
    assert res["quantity"] == 30 and rt.globals().getObjectFromGUID("far1") is not None, \
        "a card of the side outside the scope is not picked up (and the deck stays at 30 with those in scope)"


def test_discard_cards_moves_only_cards_of_the_bot_identity_inside_the_scope(rt):
    medusa_table(rt)
    wanted = [17605, 17606, 17620, 17625, 17628, 17629]
    res = run(rt, lua.discard_cards(wanted, [(1.0, 2.0, 3.0 + i) for i in range(6)], 90,
                                    identity=BOT_ID, scope=SCOPE))
    # 17605/17606 come out of the bot's Deck (one per pass, two passes: live 2/11, two BLIND BOOST cards of the draw deck);
    # 17620 from the hand, 17625 loose in the zone, 17628 at the combat spot and 17629 in the human's zone
    assert sorted(res["moved"]) == [17605, 17606, 17620, 17625, 17628, 17629]
    g = rt.globals()
    assert g.getObjectFromGUID("alice5").moved_count is None and g.getObjectFromGUID("alice6").moved_count is None
    assert g.getObjectFromGUID("alice5").pos.x == 14
    assert len(owners(rt, "rosie1")) == 30 and len(owners(rt, "rosie2")) == 30 and len(owners(rt, "mix1")) == 2
    assert len(owners(rt, "d42056")) == 18


def test_discard_cards_ignores_a_foreign_card_even_when_it_is_the_only_one_with_that_id(rt):
    rt.execute("mkobj({guid = 'a', type = 'Card', cid = 17605, owner = 'alice', pos = {x = 14, y = 1, z = 2}})")
    res = run(rt, lua.discard_cards([17605], [(1.0, 2.0, 3.0)], identity=BOT_ID, scope=SCOPE))
    assert res["moved"] == []


def test_deal_cards_and_deck_search_refuse_a_foreign_deck(rt):
    rt.execute("""
local rosie = {}
for i = 0, 29 do table.insert(rosie, {cid = 17600 + i, guid = 'r' .. i, owner = 'rosie'}) end
mkobj({guid = 'd42056', type = 'Deck', cards = rosie, pos = {x = 11.5, y = 1, z = 12}})
mkobj({guid = 'rosie9', type = 'Deck', cards = rosie, pos = {x = 11.6, y = 1, z = 12}})
d = nil
""")
    rt.execute("getObjectFromGUID('d42056').deal = function() DEALT = true end")
    res = run(rt, lua.deal_cards("d42056", 2, "Green", spot=(11.5, 12.0), identity=BOT_ID))
    assert res == {"dealt": 0} and rt.globals().DEALT is None


def test_deal_cards_deals_from_the_deck_with_the_bot_identity(rt):
    rt.execute("""
local cards = {}
for i = 0, 29 do table.insert(cards, {cid = 17600 + i, guid = 'm' .. i, owner = 'medusa'}) end
mkobj({guid = 'd42056', type = 'Deck', cards = cards})
getObjectFromGUID('d42056').deal = function(k, color) DEALT = k end
""")
    assert run(rt, lua.deal_cards("d42056", 2, "Green", identity=BOT_ID)) == {"dealt": 2}
    assert rt.globals().DEALT == 2


def test_return_hand_to_deck_only_takes_cards_with_the_bot_identity(rt):
    rt.execute("""
mkobj({guid = 'd1', type = 'Deck', cards = {{cid = 17600, guid = 'm0', owner = 'medusa'}, {cid = 17601, guid = 'm1', owner = 'medusa'}}})
mkobj({guid = 'c2', type = 'Card', cid = 17602, owner = 'medusa', hand = 'Green'})
mkobj({guid = 'c3', type = 'Card', cid = 17603, owner = 'alice', hand = 'Green'})
""")
    res = run(rt, lua.return_hand_to_deck("Green", "d1", identity=BOT_ID))
    assert res == {"returned": 1, "deck": True} and rt.globals().getObjectFromGUID("c3") is not None


def test_deck_identities_reads_the_images_from_the_deck_object(rt):
    medusa_table(rt)
    res = run(rt, lua.deck_identities([("d42056", (11.5, 12.0), lua.BOT_CARD_IDS),
                                       ("nope01", (50.0, 50.0), lua.HUMAN_CARD_IDS)]))
    assert res[0]["found"] and res[0]["pairs"] == [{"face": "https://img.test/medusa/face",
                                                      "back": "https://img.test/medusa/back"}]
    assert not res[1]["found"] and res[1]["pairs"] == []


@pytest.mark.parametrize("bad", [(), (("http://x", "y"),), (("https://a/b", 'https://c"); os.exit() --'),),
                                 (("https://a/b",),), "https://a/b", (("https://a/b", "https://c/d"),) * 9])
def test_identity_and_scope_arguments_are_validated(bad):
    with pytest.raises((ValueError, TypeError)):
        lua.discard_cards([1], [(0, 0, 0)], identity=bad, scope=SCOPE)


@pytest.mark.parametrize("scope", [lua.Scope(("Verde",), ("abc",), ((0.0, 0.0),)),
                                   lua.Scope(("Green",), ('a"); x --',), ((0.0, 0.0),)),
                                   lua.Scope(("Green",), ("abc",), ()), lua.Scope(("Green",), ("abc",), ((0.0,),)),
                                   lua.Scope(("Green",), ("abc",), ((0.0, 0.0),), radius=float("inf")),
                                   lua.Scope(("Green",), ("abc",), ((0.0, 0.0),), radius=99.0), "todo"])
def test_scope_arguments_are_validated(scope):
    with pytest.raises((ValueError, TypeError)):
        lua.reset_deck("abc", (0.0, 0.0), lua.BOT_CARD_IDS, identity=BOT_ID, scope=scope)


def test_session_reads_the_identity_at_start_and_uses_it_in_every_card_write(brig):  # noqa: F811
    session, table, game, fake = brig
    session._deck_ident.clear()
    session.load_identities()
    assert session._deck_ident["bot"] == (("https://img.test/face", "https://img.test/back"),)
    session._deck_ident.clear()
    table.scripts.clear()
    game.draw(0)
    session.dirty = True
    session._reconcile_bot()
    session._flush()
    dealt = [s for s in table.scripts if s.startswith("-- sparring:deal_cards")]
    assert dealt, [x.split(chr(10))[0] for x in table.scripts]
    assert all("https://img.test/face|https://img.test/back" in s for s in dealt)
    assert session._deck_ident["bot"] == (("https://img.test/face", "https://img.test/back"),)


# ---------- 2. the 20 s timer and old snapshots ----------
def make_panel_runtime():
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: json.dumps(conv(v))})
    runtime.execute("UI = {setValue = function(id, v) UIVAL = v end, setAttribute = function() end}")
    runtime.execute(ui.handler_script(None, ["btn_end"]))
    return runtime


def test_only_the_timer_of_the_latest_click_can_unlock_the_panel():
    rt = make_panel_runtime()
    g = rt.globals()
    g.onManeuver()                     # click A: timer A
    g.busy = False                     # the bot releases the panel
    g.onEndAction()                    # click B: timer B
    g.TIMERS[1]()                      # at 20 s A expires while B is processed
    assert g.busy is True, "the old timer does not unblock a later click"
    g.TIMERS[2]()                      # B's can
    assert g.busy is False and "Sin respuesta" in g.UIVAL


def test_panel_stamps_its_snapshot_with_the_last_write_it_was_told_about(brig):  # noqa: F811
    session, table, game, fake = brig
    spec = session.snapshot_spec()
    script = ui.handler_script(lua.snapshot_lua(spec, "wseq"), ["btn_end"])
    assert "snap.seq = wseq" in script and "wseq = 0" in script
    lua54.LuaRuntime().execute("return function() " + script + "\nend")
    with pytest.raises(ValueError):
        lua.snapshot_lua(spec, "os.exit()")


def test_composite_stamps_the_state_and_the_panel_after_settling(rt):
    spec = _spec(rt)
    rt.execute("""
mkobj({guid = 'ec6f27', type = 'Board'})
mkobj({guid = '04b2c9', type = 'Figurine'})
mkobj({guid = 'pnl', type = 'BlockSquare', name = 'SparringPanel', gm = 'sparring'})
""")
    from sparring.board import Board
    board = Board.load("bprd-hq")
    ops = [lua.move_piece(board, "04b2c9", 30), lua.set_panel("ok", {"btn_end": (True, True)}, release_busy=False)]
    res = run(rt, lua.composite(ops, spec, None, seq=7))
    assert res["state"]["seq"] == 7
    assert conv(rt.globals().getObjectFromGUID("pnl").vars) == {"busy": False, "wseq": 7}


# ---------- 3 and 4. release after settling; isSmoothMoving ----------
def _spec(rt):
    rt.execute("""
mkobj({guid = 'ec6f27', type = 'Board'})
mkobj({guid = '04b2c9', type = 'Figurine'})
""")
    return lua.SnapSpec(_board(), "Green", "White", "906a7a", (), (), "b7a0b8", (), (), 1.5, (6.0, -18.0),
                        (-2.0, -18.0), 2.0, ("04b2c9",), ())


def _board():
    from sparring.board import Board
    return Board.load("bprd-hq")


def _composite_with_panel(rt, **piece):
    spec = _spec(rt)
    rt.execute("mkobj({guid = 'pnl', type = 'BlockSquare', name = 'SparringPanel', gm = 'sparring'})")
    for k, v in piece.items():
        rt.execute(f"getObjectFromGUID('04b2c9').{k} = {v}")
    rt.execute("DEFER = true")
    ops = [lua.move_piece(_board(), "04b2c9", 30), lua.set_panel("ok", {"btn_end": (True, True)}, release_busy=False)]
    rt.execute(lua.request(lua.composite(ops, spec, None, seq=3), 5))
    return rt.globals()


def test_busy_is_cleared_only_after_the_pieces_settle(rt):
    g = _composite_with_panel(rt, smooth="true")
    pnl = g.getObjectFromGUID("pnl")
    assert len(g.SENT) == 0 and pnl.vars is None, "while it moves, nothing is released or answered"
    assert g.PENDING[1].cond() is False
    g.getObjectFromGUID("04b2c9").smooth = False
    assert g.PENDING[1].cond() is True
    g.PENDING[1].f()
    assert conv(pnl.vars)["busy"] is False and len(g.SENT) == 1


def test_a_resting_false_piece_also_blocks_and_missing_methods_do_not_break_the_check(rt):
    g = _composite_with_panel(rt, resting="false")
    assert g.PENDING[1].cond() is False
    g.getObjectFromGUID("04b2c9").resting = True
    assert g.PENDING[1].cond() is True
    rt2 = lua54.LuaRuntime()
    rt2.execute(STUB)
    rt2.globals().JSON = rt2.table_from({"encode": lambda v: json.dumps(conv(v))})
    rt2.execute("mkobj({guid = 'ec6f27', type = 'Board'})\nmkobj({guid = '04b2c9', type = 'Figurine', no_smooth = true})")
    rt2.execute("getObjectFromGUID('04b2c9').resting = nil\nDEFER = true")
    rt2.execute(lua.request(lua.composite([lua.move_piece(_board(), "04b2c9", 30)], _spec(rt2), None), 6))
    assert rt2.globals().PENDING[1].cond() is True, "without isSmoothMoving or resting there is nothing to wait for"


def test_set_panel_releases_busy_itself_unless_a_composite_does_it(rt):
    rt.execute("mkobj({guid = 'pnl', type = 'BlockSquare', name = 'SparringPanel', gm = 'sparring'})")
    run(rt, lua.set_panel("ok", {"btn_end": (True, True)}))
    assert conv(rt.globals().getObjectFromGUID("pnl").vars) == {"busy": False}
    assert 'setVar("busy"' not in lua.set_panel("ok", {"btn_end": (True, True)}, release_busy=False)
    with pytest.raises(TypeError):
        lua.set_panel("ok", {}, release_busy="si")


# ---------- 2 (Python). an old snapshot is never adopted ----------
def test_a_snapshot_older_than_the_last_table_write_is_dropped_not_adopted(brig, monkeypatch):  # noqa: F811
    from sparring.ai_medusa import Act
    session, table, game, fake = brig
    game.actions_left = 0                                   # the next End action runs the bot's turn
    stale = json.dumps(table.snapshot_state())               # click taken before the bot's writes
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 5}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    session.handle(Event.END_ACTION, {"snapshot": stale})
    assert game.fighters["medusa"].pos == 5 and table.positions["Medusa"] == 5
    session.handle(Event.END_ACTION, {"snapshot": stale})    # duplicate after the unblock, with the old table
    assert game.fighters["medusa"].pos == 5, "the old snapshot does not rewind the engine"
    assert session._snap_stale(json.loads(stale))


def test_take_snapshot_requires_a_stamp_not_older_than_the_last_write(brig):  # noqa: F811
    session, table, game, fake = brig
    session._write_seq = 4
    snap = table.snapshot_state()
    for seq in (3, None):
        session._take_snapshot(json.dumps({**snap, "seq": seq}))
        assert session.snap is None
    session._take_snapshot(json.dumps({**snap, "seq": 4}))
    assert session.snap is not None and session._trusted


def test_events_that_arrive_while_the_client_is_inside_call_lua_lose_their_snapshot():
    table = Table()
    fake = FakeTTS(return_value=table)
    client = TTSClient(send_port=fake.port, listen_port=0)
    fake.reply_port = client.start_listening().port
    try:
        client.listener.messages.put({"messageID": 4, "customMessage": {"event": "end_action", "snapshot": "{}"}})
        client.call_lua(lua.broadcast("hola"))
        client.listener.messages.put({"messageID": 4, "customMessage": {"event": "maneuver", "snapshot": "{}"}})
        events = client.poll_events()
        assert events[0] == {"event": "end_action"}, "it arrived inside call_lua: its snapshot predates the write"
        assert events[1].get("snapshot") == "{}", "one that arrives with the client free keeps its own (the seal judges it)"
    finally:
        client.close()
        fake.close()


# ---------- 5. Reveal: what is discarded is not turned ----------
def test_reveal_does_not_flip_the_bot_card_that_the_same_composite_discards(brig):  # noqa: F811
    from test_session import human_plays
    session, table, game, fake = brig
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    bot_guid = session.pending.bot_card_guid
    human_plays(table, game, "Service Pistol")
    click(session, table, Event.REVEAL)
    assert bot_guid not in table.flips and len(table.flips) == 1


# ---------- 6. validations ----------
@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), 1e308, "7", True, 101, [1]])
def test_a_bad_value_is_refused_without_an_uncaught_error_and_the_panel_is_released(brig, bad):  # noqa: F811
    session, table, game, fake = brig
    msgs = click(session, table, Event.VALUE, {"value": bad})
    assert session.pending_value == 0 and any("Valor no valido" in m for m in msgs)
    assert table.panels, "the button's closing releases the panel"


def test_a_good_value_is_registered(brig):  # noqa: F811
    session, table, game, fake = brig
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    click(session, table, Event.VALUE, {"value": 4})
    assert session.pending_value == 4


def test_click_snapshot_types_and_ranges_are_validated(brig):  # noqa: F811
    session, table, game, fake = brig
    good = {**table.snapshot_state(), "seq": 0}
    spaces = set(game.board.spaces)
    assert session._parse_snap(dict(good), spaces) is not None
    first_piece = next(iter(good["pieces"]))
    bads = [
        {"human_count": -1}, {"human_count": "5"}, {"human_count": math.inf}, {"human_count": True},
        {"bot_hand": [{"id": "17600", "guid": "g"}]}, {"bot_hand": [{"id": 1.5, "guid": "g"}]},
        {"bot_hand": [{"id": 17600}]}, {"bot_hand": ["x"]}, {"bot_discard": [{"id": -3, "guid": "g"}]},
        {"bot_hand": [{"id": 1, "guid": "g"}] * 301}, {"seq": -1}, {"seq": "3"}, {"human_deck_qty": 9999},
        {"pieces": {first_piece: {"found": True, "space": 9999, "dist": 0.1}}},
        {"pieces": {first_piece: {"found": True, "space": 3, "dist": float("nan")}}},
        {"pieces": {first_piece: {"found": "yes"}}}, {"pieces": {first_piece: 3}},
        {"dials": {"DM": {"found": True, "value": "16"}}}, {"dials": {"DM": {"found": True, "value": 1e30}}},
    ]
    for patch in bads:
        assert session._parse_snap({**good, **patch}, spaces) is None, patch


# ---------- 6. size of the composite ----------
def test_composite_size_is_capped_in_bytes(rt):
    big = lua.broadcast("x" * 60)
    assert len(big) < 300
    many = [lua.name_pieces({f"g{i:03d}": "Harpy 1" for i in range(200)}) for _ in range(30)]
    assert sum(len(m) for m in many) > lua.MAX_COMPOSITE_BYTES
    with pytest.raises(ValueError, match="too large"):
        lua.composite(many)
    assert len(lua.composite(many[:2]).encode()) < lua.MAX_COMPOSITE_BYTES


def test_flush_splits_a_queue_that_would_exceed_the_cap(brig):  # noqa: F811
    session, table, game, fake = brig
    scripts = [lua.name_pieces({f"g{i:03d}": "Harpy 1" for i in range(200)}) for _ in range(40)]
    ops = [session._w(s, "misc") for s in scripts]
    session._flush()
    assert all(o.done for o in ops)
    assert fake.lua_messages >= 2 and all(len(m["script"].encode()) <= lua.MAX_COMPOSITE_BYTES
                                          for m in fake.received if m.get("messageID") == 3)


# ---------- 6. the status line is computed after the closings ----------
def test_status_line_is_computed_after_the_closing_checks(brig, monkeypatch):  # noqa: F811
    session, table, game, fake = brig
    real = session._maneuver

    def maneuver(payload):
        real(payload)
        session._post.append(lambda: setattr(session, "moving", False))
    monkeypatch.setattr(session, "_maneuver", maneuver)
    click(session, table, Event.MANEUVER)
    status, _ = table.panels[-1]
    assert status.endswith("esperando tu accion") and (status, table.panels[-1][1]) == (
        session.panel_view()[0], session.panel_view()[1])


def test_the_readme_states_the_real_batch_defaults():
    text = open(os.path.join(HERE, "..", "README.md"), encoding="utf-8").read()
    row = next(line for line in text.splitlines() if line.startswith("| `batch`, `live_ui`"))
    from sparring import play
    from sparring.session import SessionConfig
    raw = json.loads(open(os.path.join(HERE, "..", "config", "table.json"), encoding="utf-8").read())
    for key in ("batch", "live_ui"):
        raw.pop(key, None)                                        # the file does not mention them
    built = play.build_config(raw, (play.SRC_CONFIG, play.SRC_CONFIG))
    session_cfg = built.session_config()
    assert session_cfg.batch is True and session_cfg.live_ui is True        # what the table file gives when silent
    assert "Both are `true` when the file does not mention them" in row
    assert SessionConfig.__dataclass_fields__["batch"].default is False and "`false` only in the bare `SessionConfig`" in row


# ---------- game 5: panel, labels, setup ----------
def _real_cfg():
    from sparring import play
    return play.load_config(os.path.join(HERE, "..", "config", "table.json"))


def test_real_config_puts_the_panel_right_of_the_discard_zone_and_nothing_sits_under_it():
    from sparring import play
    cfg = _real_cfg()
    assert list(cfg.panel_position) == [-12.5, 1.8, -24.5] and list(cfg.panel_scale) == [4.5, 4.5, 4.5]
    assert list(cfg.raw["human_dead_spot"]) == [-24, 2.5, 22]
    assert play.floor_layout_warnings(cfg) == []


def test_the_old_panel_position_is_flagged_for_covering_the_combat_boxes_and_their_labels():
    from sparring import play
    cfg = _real_cfg()
    cfg.raw["panel_position"], cfg.raw["panel_scale"] = [2, 1.8, -24], [6, 6, 6]
    names = " | ".join(play.floor_layout_warnings(cfg))
    for what in ("caja de combate MEDUSA", "caja de combate HELLBOY", "etiqueta MEDUSA", "etiqueta HELLBOY"):
        assert what in names, names


def test_play_warns_at_startup_when_a_marking_would_sit_under_the_panel(monkeypatch):
    from sparring import play
    cfg = _real_cfg()
    cfg.raw["panel_position"] = [0, 1.8, -18]
    assert len(play.floor_layout_warnings(cfg)) >= 2


def test_no_floor_label_overlaps_another_marking_and_labels_float_above_the_discard_piles():
    from sparring import play
    cfg = _real_cfg()
    rects = play.floor_layout(cfg)
    for name, (a0, a1, b0, b1) in rects:
        if not name.startswith("etiqueta"):
            continue
        for other, (c0, c1, d0, d1) in rects:
            if other != name:
                assert not (a0 < c1 and a1 > c0 and b0 < d1 and b1 > d0), (name, other)
    assert "DESCARTE MEDUSA" in " ".join(n for n, _ in rects)
    top = cfg.raw["bot_discard_spot"][1] + 15 * 0.15
    assert lua.LABEL_Y > top
    script = lua.draw_markings([("DESCARTE MEDUSA", "906a7a")], [("MEDUSA", 6.0, -18.0)])
    assert f"{{r.x, {lua.LABEL_Y}, r.z}}" in script and "{r.x, 2.0, r.z}" not in script


def test_undo_game_over_is_only_visible_when_the_game_is_over(brig):  # noqa: F811
    session, table, game, fake = brig
    assert session.panel_view()[1]["btn_undo"] == (False, False)
    game.winner = 1
    assert session.panel_view()[1]["btn_undo"] == (True, True)


def test_the_panel_carrier_is_tinted_dark(rt):
    script = lua.create_panel(["medusa"])
    assert "setColorTint" in script and lua.is_sendable(script)


def test_no_off_board_warning_while_the_game_is_being_set_up(brig):  # noqa: F811
    session, table, game, fake = brig
    for name in table.positions:
        table.piece_dist[name] = 99.0
    session.setup = {"stage": "wait_human", "mull_done": True, "mull_decision": None, "mull_step": "start",
                     "human_mull": False}
    session.messages.clear()
    session.sync_positions()
    assert not [m for m in session.messages if "fuera del tablero" in m or "Retirar" in m]
    session.setup = None
    session.sync_positions()
    assert [m for m in session.messages if "fuera del tablero" in m]


def test_resume_writes_and_verifies_every_dial_in_the_resume_messages(brig):  # noqa: F811
    session, table, game, fake = brig
    game.fighters["medusa"].hp = 13                       # the engine has 13 and the save's dial shows 16
    session.dials_written["DM"] = 16
    n = fake.lua_messages
    session.resume()
    assert table.dials["DM"]["value"] == 13 and table.dial_writes, "the dial now shows the engine's life"
    assert session.dials_written["DM"] == 13
    assert fake.lua_messages - n <= 3, "the piece-identity check rides the resume's own table read"


# ---------- game 5: the human's BOOST (Second Shot) ----------
def _boost_rig(brig):
    from test_session import card, human_plays
    session, table, game, fake = brig
    game.fighters["lobster"].pos = 2
    table.positions["Lobster Johnson"] = 2
    click(session, table, Event.ATTACKER, {"attacker": "att_lobster"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None, "Lobster alcanza a Medusa"
    second = human_plays(table, game, "Second Shot")
    return session, table, game, fake, second, card


def test_second_shot_reveals_both_cards_and_waits_for_the_boost_without_resolving(brig):  # noqa: F811
    session, table, game, fake, second, card = _boost_rig(brig)
    hp, actions = game.fighters["medusa"].hp, game.actions_left
    msgs = click(session, table, Event.REVEAL)
    p = session.pending
    assert p is not None and p.boost_wait is not None and p.boost_wait["card"] == second.card_id
    assert game.actions_left == actions and game.fighters["medusa"].hp == hp, "nothing has been resolved yet"
    assert len(table.flips) == 2, "the two cards turned"
    assert any("Second Shot revelado" in m and "Continuar" in m and "Sin boost" in m for m in msgs)
    status, states = table.panels[-1]
    assert status == "Second Shot revelado: pon una carta en tu descarte y pulsa Continuar o Sin boost"
    assert states["btn_boost"] == (True, True) and states["btn_noboost"] == (True, True)
    assert states["btn_reveal"] == (False, False) and states["btn_cancel"] == (False, False)


def test_continue_reads_the_new_discard_card_boost_and_announces_the_total(brig):  # noqa: F811
    session, table, game, fake, second, card = _boost_rig(brig)
    click(session, table, Event.REVEAL)
    booster = card(game, 1, "Service Pistol")
    table.human_discard = [booster.card_id]
    table.human_count -= 1                                # the boost card left the hand
    msgs = click(session, table, Event.BOOST)
    assert session.pending is None and session.pending_value == 0
    text = next(m for m in msgs if m.startswith("Combate"))
    assert f"Lobster Johnson ataca con Second Shot (2) y potencia con Service Pistol (+{booster.boost})" in text
    assert f"total {2 + booster.boost}" in text
    assert booster in game.players[1].discard and second in game.players[1].discard
    assert not any("Resuelve a mano: Second Shot" in m or "DURING COMBAT" in m for m in msgs)
    assert table.panels[-1][1]["btn_boost"] == (False, False)


def test_continue_without_a_new_discard_card_waits_and_no_boost_resolves_with_no_boost(brig):  # noqa: F811
    session, table, game, fake, second, card = _boost_rig(brig)
    click(session, table, Event.REVEAL)
    msgs = click(session, table, Event.BOOST)
    assert session.pending is not None and any("No veo ninguna carta nueva" in m for m in msgs)
    msgs = click(session, table, Event.NO_BOOST)
    assert session.pending is None
    assert any(m.startswith("Combate") and "potencia" not in m and "total 2" in m for m in msgs)


def test_two_new_discard_cards_are_ambiguous(brig):  # noqa: F811
    session, table, game, fake, second, card = _boost_rig(brig)
    click(session, table, Event.REVEAL)
    table.human_discard = [card(game, 1, "Service Pistol").card_id, card(game, 1, "Excalibur").card_id]
    msgs = click(session, table, Event.BOOST)
    assert session.pending is not None and any("2 cartas nuevas" in m for m in msgs)


def test_cards_in_the_discard_before_the_reveal_are_not_the_boost(brig):  # noqa: F811
    session, table, game, fake, second, card = _boost_rig(brig)
    old = card(game, 1, "Excalibur")
    table.human_discard = [old.card_id]
    click(session, table, Event.REVEAL)
    msgs = click(session, table, Event.BOOST)
    assert session.pending is not None and any("No veo ninguna carta nueva" in m for m in msgs)


def test_cancel_reveal_and_end_action_are_refused_while_waiting_for_the_boost(brig):  # noqa: F811
    session, table, game, fake, second, card = _boost_rig(brig)
    click(session, table, Event.REVEAL)
    for event, word in ((Event.CANCEL, "no se puede cancelar"), (Event.REVEAL, "ya estan reveladas"),
                        (Event.END_ACTION, "Termina primero el boost")):
        msgs = click(session, table, event)
        assert any(word in m for m in msgs), (event, msgs)
        assert session.pending is not None and session.pending.boost_wait is not None


def test_a_boost_wait_survives_a_save_and_resume(brig):  # noqa: F811
    session, table, game, fake, second, card = _boost_rig(brig)
    click(session, table, Event.REVEAL)
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["pending"]["boost_wait"]["card"] == second.card_id
    session.pending = None
    session.load_dict(saved)
    assert session.pending.boost_wait == {**saved["pending"]["boost_wait"]}
    assert session.panel_view()[1]["btn_boost"] == (True, True)
    table.human_discard = [card(game, 1, "Service Pistol").card_id]
    table.human_count -= 1
    click(session, table, Event.BOOST)
    assert session.pending is None and game.players[1].discard
    from sparring import persist
    bad = json.loads(json.dumps(saved))
    bad["pending"]["boost_wait"] = {"card": "x"}
    with pytest.raises(persist.StateError):
        session.load_dict(bad)


def test_a_late_value_is_refused_and_never_carries_over_to_the_next_combat(brig):  # noqa: F811
    session, table, game, fake, second, card = _boost_rig(brig)
    click(session, table, Event.REVEAL)
    click(session, table, Event.NO_BOOST)
    msgs = click(session, table, Event.VALUE, {"value": 4})
    assert session.pending_value == 0 and any("No hay combate pendiente" in m for m in msgs)


def test_value_is_not_the_way_to_boost_while_waiting(brig):  # noqa: F811
    session, table, game, fake, second, card = _boost_rig(brig)
    click(session, table, Event.REVEAL)
    msgs = click(session, table, Event.VALUE, {"value": 4})
    assert session.pending_value == 0 and any("Continuar" in m for m in msgs)


def test_the_panel_has_the_two_boost_buttons_hidden_by_default():
    xml = ui.panel_xml(["medusa"])
    for ident in ("btn_boost", "btn_noboost"):
        assert f'active="false" fontSize="18"' in xml and f'id="{ident}"' in xml
    assert "function onBoost" in ui.handler_script() and "function onNoBoost" in ui.handler_script()
    assert ui.parse_event({"event": "boost"}) == (Event.BOOST, {}) and ui.Event("no_boost") is Event.NO_BOOST
