"""Review 10: identity with the REAL shape of the save, atomic restart, BOOST without jams and details.

The Lua tests run the generated scripts with lupa (skipped without it); the session ones use the fake table."""
import json
import os

import pytest

from conftest import TEST_IDENT, t_flip_card, t_play_card_face_down
from sparring.session import SessionError
from sparring.tts import lua
from sparring.tts.client import TTSLuaError
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_session import card, human_plays, set_bot_hand

lupa = pytest.importorskip("lupa")
from lupa import lua54  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STUB = open(os.path.join(HERE, "lua_stub.lua"), encoding="utf-8").read()
M = ("https://steamusercontent-a.akamaihd.net/ugc/1/MFACE/", "https://steamusercontent-a.akamaihd.net/ugc/1/MBACK/")
H = ("https://steamusercontent-a.akamaihd.net/ugc/2/HFACE/", "https://steamusercontent-a.akamaihd.net/ugc/2/HBACK/")
F = ("https://steamusercontent-a.akamaihd.net/ugc/9/FFACE/", "https://steamusercontent-a.akamaihd.net/ugc/9/FBACK/")
SCOPE = lua.Scope(("Green", "White"), ("906a7a", "b7a0b8"), ((6.0, -18.0), (-2.0, -18.0), (7.28, 13.93), (-4.6, 13.67)))


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
    """A table with the shape of the real save (TS_AutoSave_2.json, 27/10): Medusa's deck carries the CustomDeck only
    on the deck; Hellboy's, 20 cards with a CustomDeck of key "187" although their CardID is 197xx and 10 with "197"."""
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: json.dumps(conv(v))})
    runtime.execute(f"""
MF, MB, HF, HB, FF, FB = "{M[0]}", "{M[1]}", "{H[0]}", "{H[1]}", "{F[0]}", "{F[1]}"
function realshape(o)
  o.getData = function()
    if o.type == "Card" then return {{CardID = o.cid, CustomDeck = o.cd}} end
    local co = {{}}
    for _, c in ipairs(o.cards or {{}}) do table.insert(co, {{CardID = c.cid, GUID = c.guid, CustomDeck = c.cd}}) end
    return {{ContainedObjects = co, CustomDeck = o.deckcd}}
  end
  return o
end
mkobj({{guid = '906a7a', type = 'Scripting', cx = 15, cz = 0, hw = 5, hd = 12}})
mkobj({{guid = 'b7a0b8', type = 'Scripting', cx = -12.5, cz = 0, hw = 6, hd = 12}})
local mc = {{}}
for i = 0, 29 do table.insert(mc, {{cid = 17600 + i, guid = 'm' .. i, owner = 'medusa'}}) end
realshape(mkobj({{guid = 'd42056', type = 'Deck', cards = mc, pos = {{x = 7.28, y = 1, z = 13.93}},
                 deckcd = {{["176"] = {{FaceURL = MF, BackURL = MB}}}}}}))
local hc = {{}}
for i = 0, 29 do
  local key = (i < 20) and "187" or "197"
  table.insert(hc, {{cid = 19700 + i, guid = 'hb' .. i, owner = 'hellboy', cd = {{[key] = {{FaceURL = HF, BackURL = HB}}}}}})
end
realshape(mkobj({{guid = '00dc9a', type = 'Deck', cards = hc, pos = {{x = -4.6, y = 1, z = 13.67}},
                 deckcd = {{["197"] = {{FaceURL = HF, BackURL = HB}}}}}}))
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


def identity(*pairs):
    return tuple(pairs)


HUMAN = identity(H)
BOT = identity(M)
HDECK = ("00dc9a", (-4.6, 13.67), lua.HUMAN_CARD_IDS)
BDECK = ("d42056", (7.28, 13.93), lua.BOT_CARD_IDS)


def spill_hellboy(runtime, n=3, start=0):
    """Takes n cards from Hellboy's deck to the discard: loose ones keep their CustomDeck of key "187"."""
    runtime.execute(f"""
local d = getObjectFromGUID('00dc9a')
for k = 1, {n} do
  local c = table.remove(d.cards, {start + 1})
  realshape(mkobj({{guid = c.guid, type = 'Card', cid = c.cid, owner = 'hellboy', cd = c.cd, pos = {{x = -12, y = 1, z = k}}}}))
end
""")


def foreign(runtime):
    """Foreign cards with a Hellboy CardID: with their own key 197 and with key 187 of another image; and a mixed Deck."""
    runtime.execute("""
realshape(mkobj({guid = 'fx1', type = 'Card', cid = 19705, owner = 'x', cd = {["197"] = {FaceURL = FF, BackURL = FB}},
                 pos = {x = -12, y = 1, z = 6}}))
realshape(mkobj({guid = 'fx2', type = 'Card', cid = 19706, owner = 'x', cd = {["187"] = {FaceURL = FF, BackURL = FB}},
                 pos = {x = -12, y = 1, z = 7}}))
realshape(mkobj({guid = 'fx3', type = 'Card', cid = 19707, owner = 'x', pos = {x = -12, y = 1, z = 8}}))
realshape(mkobj({guid = 'fxd', type = 'Deck', pos = {x = -12, y = 1, z = 9}, deckcd = {["197"] = {FaceURL = HF, BackURL = HB}},
   cards = {{cid = 19710, guid = 'fd1', cd = {["187"] = {FaceURL = HF, BackURL = HB}}},
            {cid = 19711, guid = 'fd2', cd = {["197"] = {FaceURL = FF, BackURL = FB}}}}}))
""")


# ---------- 1. the real shape of the save ----------
def test_the_identity_of_the_real_hellboy_deck_is_read_from_all_its_cards(rt):
    res = run(rt, lua.deck_identities([BDECK, HDECK]))
    assert [r["found"] for r in res] == [True, True]
    assert res[0]["pairs"] == [{"face": M[0], "back": M[1]}] and res[1]["pairs"] == [{"face": H[0], "back": H[1]}]


def test_reset_gathers_all_30_hellboy_cards_even_when_20_carry_a_187_custom_deck(rt):
    spill_hellboy(rt, 3)                                  # 3 with "187" out of the deck, already loose
    res = run(rt, lua.reset_deck(HDECK[0], HDECK[1], lua.HUMAN_CARD_IDS, identity=HUMAN, scope=SCOPE))
    assert res == {"deck": True, "quantity": 30}
    assert len(rt.globals().getObjectFromGUID("00dc9a").cards) == 30
    assert [o.guid for o in rt.globals().getObjects().values() if o.type == "Card"] == []


def test_reset_gathers_the_cards_of_a_deck_the_human_broke_in_two(rt):
    rt.execute("""
local d = getObjectFromGUID('00dc9a')
local half = {}
for k = 1, 12 do table.insert(half, table.remove(d.cards, 1)) end
realshape(mkobj({guid = 'half01', type = 'Deck', cards = half, pos = {x = -12, y = 1, z = 4}, deckcd = {["187"] = {FaceURL = HF, BackURL = HB}}}))
""")
    res = run(rt, lua.reset_deck(HDECK[0], HDECK[1], lua.HUMAN_CARD_IDS, identity=HUMAN, scope=SCOPE))
    assert res == {"deck": True, "quantity": 30}


def test_foreign_cards_with_the_same_card_ids_are_still_rejected_in_every_shape(rt):
    spill_hellboy(rt, 2)
    foreign(rt)
    res = run(rt, lua.reset_deck(HDECK[0], HDECK[1], lua.HUMAN_CARD_IDS, identity=HUMAN, scope=SCOPE))
    g = rt.globals()
    for guid in ("fx1", "fx2", "fx3", "fxd"):
        o = g.getObjectFromGUID(guid)
        assert o is not None and o.moved_count is None, f"{guid} is foreign (or mixes a foreign one) and is not touched"
    assert res == {"deck": True, "quantity": 30}


def test_reset_plan_counts_without_moving_anything_and_sees_a_missing_card(rt):
    spill_hellboy(rt, 3)
    plan = run(rt, lua.reset_plan([(*HDECK[:3], HUMAN), (*BDECK, BOT)], scope=SCOPE))
    assert plan == [{"deck": True, "loose": 3, "total": 30}, {"deck": True, "loose": 0, "total": 30}]
    g = rt.globals()
    assert all(g.getObjectFromGUID(f"hb{i}").moved_count is None for i in range(3)), "the plan moves nothing"
    assert len(g.getObjectFromGUID("00dc9a").cards) == 27
    rt.execute("getObjectFromGUID('hb1').destruct()")      # a card out of scope or lost
    assert run(rt, lua.reset_plan([(*HDECK[:3], HUMAN)], scope=SCOPE))[0]["total"] == 29


def test_deal_and_discard_work_on_the_real_shaped_medusa_deck(rt):
    rt.execute("getObjectFromGUID('d42056').deal = function(k, color) DEALT = k end")
    assert run(rt, lua.deal_cards("d42056", 5, "Green", spot=BDECK[1], identity=BOT)) == {"dealt": 5}


def test_deck_identities_only_reads_cards_inside_the_range_and_checks_every_card_for_the_position_fallback(rt):
    rt.execute("""
realshape(mkobj({guid = 'mixd1', type = 'Deck', pos = {x = 30, y = 1, z = 30}, deckcd = {["197"] = {FaceURL = HF, BackURL = HB}},
   cards = {{cid = 19701, guid = 'a'}, {cid = 4203, guid = 'b', cd = {["42"] = {FaceURL = FF, BackURL = FB}}}}}))
realshape(mkobj({guid = 'okd1', type = 'Deck', pos = {x = 40, y = 1, z = 40}, deckcd = {["197"] = {FaceURL = HF, BackURL = HB}},
   cards = {{cid = 19701, guid = 'c'}, {cid = 4203, guid = 'd', cd = {["42"] = {FaceURL = FF, BackURL = FB}}}}}))
""")
    res = run(rt, lua.deck_identities([("gone01", (30.0, 30.0), lua.HUMAN_CARD_IDS),
                                       ("okd1", (40.0, 40.0), lua.HUMAN_CARD_IDS)]))
    assert res[0]["found"] is False, "a deck with a card outside the range is not accepted by position"
    assert res[1]["found"] and res[1]["pairs"] == [{"face": H[0], "back": H[1]}], "the out-of-range image does not enter"


def test_hand_identities_reads_only_our_range_from_the_hand(rt):
    rt.execute("""
mkobj({guid = 'hc1', type = 'Card', cid = 17603, owner = 'medusa', hand = 'Green'})
realshape(mkobj({guid = 'hc2', type = 'Card', cid = 1203, owner = 'x', hand = 'Green', cd = {["12"] = {FaceURL = FF, BackURL = FB}}}))
""")
    res = run(rt, lua.hand_identities("Green", lua.BOT_CARD_IDS))
    assert res == {"pairs": [{"face": "https://img.test/medusa/face", "back": "https://img.test/medusa/back"}]}
    assert run(rt, lua.hand_identities("White", lua.BOT_CARD_IDS)) == {"pairs": []}


def test_play_card_face_down_skips_a_foreign_card_with_the_same_card_id(rt):
    rt.execute("""
realshape(mkobj({guid = 'fh', type = 'Card', cid = 17605, owner = 'x', hand = 'Green', cd = {["176"] = {FaceURL = FF, BackURL = FB}}}))
realshape(mkobj({guid = 'oh', type = 'Card', cid = 17605, owner = 'medusa', hand = 'Green', cd = {["176"] = {FaceURL = MF, BackURL = MB}}}))
""")
    res = run(rt, lua.play_card_face_down(17605, "Green", 6.0, 1.6, -18.0, 0.0, identity=BOT))
    assert res == {"played": "oh"}
    assert rt.globals().getObjectFromGUID("fh").moved_count is None


def test_play_card_face_down_finds_nothing_when_only_a_foreign_card_matches(rt):
    rt.execute("realshape(mkobj({guid = 'fh', type = 'Card', cid = 17605, owner = 'x', hand = 'Green', "
               "cd = {['176'] = {FaceURL = FF, BackURL = FB}}}))")
    assert run(rt, lua.play_card_face_down(17605, "Green", 6.0, 1.6, -18.0, 0.0, identity=BOT)) == {"played": False}


def test_flip_card_refuses_a_foreign_or_missing_card(rt):
    rt.execute("""
realshape(mkobj({guid = 'ff', type = 'Card', cid = 19705, owner = 'x', cd = {["197"] = {FaceURL = FF, BackURL = FB}}}))
realshape(mkobj({guid = 'oc', type = 'Card', cid = 19705, owner = 'hellboy', cd = {["187"] = {FaceURL = HF, BackURL = HB}}}))
""")
    n = len(rt.globals().SENT)
    rt.execute(lua.request(lua.flip_card("ff", 0, True, lua.HUMAN_CARD_IDS, identity=HUMAN), 7))
    reply = conv(rt.globals().SENT[n + 1])
    assert "err" in reply and rt.globals().getObjectFromGUID("ff").rot is None
    rt.execute(lua.request(lua.flip_card("nope01", 0, True, lua.HUMAN_CARD_IDS, identity=HUMAN), 8))
    assert "err" in conv(rt.globals().SENT[n + 2])
    assert run(rt, lua.flip_card("oc", 0, True, lua.HUMAN_CARD_IDS, identity=HUMAN), 9) == {"flipped": "oc"}


# ---------- BAD: changed builder arguments ----------
@pytest.mark.parametrize("build", [
    lambda: lua.play_card_face_down(17600, "Blue", 0, 0, 0),                                   # without identity
    lambda: lua.play_card_face_down(17600, "Blue", 0, 0, 0, identity=()),
    lambda: lua.play_card_face_down(17600, "Blue", 0, 0, 0, identity=(("http://x", "y"),)),
    lambda: lua.play_card_face_down(17600, "Blue", 0, 0, 0, id_range=(1,), identity=TEST_IDENT),
    lambda: lua.play_card_face_down(17600, "Blue", 0, 0, 0, id_range=("a", 2), identity=TEST_IDENT),
    lambda: lua.play_card_face_down(17600, "Blue", 0, 0, 0, identity=(("https://a/b", 'https://c"); os.exit() --'),)),
    lambda: lua.flip_card("abc"),
    lambda: lua.flip_card('x"); os.exit() --', identity=TEST_IDENT),
    lambda: lua.flip_card("abc", identity="https://a/b"),
    lambda: lua.flip_card("abc", id_range=(1, 2, 3), identity=TEST_IDENT),
    lambda: lua.flip_card("abc", rot_y="0) UI.hide('x') --", identity=TEST_IDENT),
    lambda: lua.hand_identities("Verde", lua.BOT_CARD_IDS),
    lambda: lua.hand_identities('Green"] x --', lua.BOT_CARD_IDS),
    lambda: lua.hand_identities("Green", (1,)),
    lambda: lua.hand_identities("Green", ("a", "b")),
    lambda: lua.hand_identities("Green", None),
    lambda: lua.deck_identities([("abc", None, (1,))]),
    lambda: lua.deck_identities([("abc", None, ("a", 2))]),
    lambda: lua.deck_identities([]),
    lambda: lua.reset_plan([], scope=SCOPE),
    lambda: lua.reset_plan([("abc", (0.0, 0.0), lua.BOT_CARD_IDS, ())], scope=SCOPE),
    lambda: lua.reset_plan([("abc", (0.0, 0.0), lua.BOT_CARD_IDS, TEST_IDENT)] * 3, scope=SCOPE),
    lambda: lua.reset_plan([('a"); x --', (0.0, 0.0), lua.BOT_CARD_IDS, TEST_IDENT)], scope=SCOPE),
    lambda: lua.reset_plan([("abc", (0.0, 0.0), (1,), TEST_IDENT)], scope=SCOPE),
    lambda: lua.reset_plan([("abc", (0.0, float("nan")), lua.BOT_CARD_IDS, TEST_IDENT)], scope=SCOPE),
    lambda: lua.reset_plan([("abc", (0.0, 0.0), lua.BOT_CARD_IDS, TEST_IDENT)], scope="todo"),
    lambda: lua.reset_plan([("abc", (0.0, 0.0), lua.BOT_CARD_IDS, TEST_IDENT)],
                           scope=lua.Scope(("Verde",), ("abc",), ((0.0, 0.0),))),
    lambda: lua.reset_plan("abc", scope=SCOPE),
])
def test_changed_builders_reject_bad_arguments(build):
    with pytest.raises((ValueError, TypeError)):
        build()


def test_the_new_scripts_have_no_global_ui_lines_or_decals():
    scripts = [t_play_card_face_down(1, "Blue", 0, 0, 0), t_flip_card("abc"), lua.hand_identities("Blue", lua.BOT_CARD_IDS),
               lua.reset_plan([("abc", (0.0, 0.0), lua.BOT_CARD_IDS, TEST_IDENT)], scope=SCOPE)]
    for s in scripts:
        assert lua.is_sendable(s)
        assert not [w for w in ("UI.", "Global", "setVectorLines", "Decal", "decal") if w in s], s[:40]


# ---------- session: BOOST ----------
def rig(brig, defense=None):
    session, table, game, fake = brig
    if defense:
        set_bot_hand(table, game, *defense)
        session.read_bot_hand()
        session.snap = None
    game.fighters["lobster"].pos = 2
    table.positions["Lobster Johnson"] = 2
    click(session, table, Event.ATTACKER, {"attacker": "att_lobster"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None
    second = human_plays(table, game, "Second Shot")
    return session, table, game, fake, second


def test_no_boost_wait_when_the_bot_card_cancels_the_attackers_effects(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig, defense=("Feint",))
    assert session.pending.bot_card is None and table.bot_play == []
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is None, msgs
    assert second in game.players[1].discard and not game.players[1].hand.count(second)
    assert any("cancela los efectos" in m for m in msgs) and any(m.startswith("Combate") for m in msgs)
    assert table.flips == [f"h{second.card_id}"], "your card is turned; the bot's is discarded"


def test_a_rule_error_after_resume_leaves_cancelar_as_the_way_out(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    click(session, table, Event.REVEAL)
    assert session.pending.boost_wait
    saved = json.loads(json.dumps(session.to_dict()))
    table.positions["Lobster Johnson"] = 27             # while he was down, the miniature was moved
    session.pending = None
    session.load_dict(saved)
    session.resume()
    msgs = click(session, table, Event.NO_BOOST)
    assert session.pending is not None and session.pending.boost_wait["stuck"] is True
    assert any("No se puede resolver el combate" in m and "Cancelar" in m for m in msgs)
    assert not any("Revelar otra vez" in m for m in msgs), "while waiting for a boost, Reveal is not asked again"
    status, states = table.panels[-1]
    assert states["btn_cancel"] == (True, True) and "Cancelar" in status
    # the stuck state survives a save
    again = json.loads(json.dumps(session.to_dict()))
    assert again["pending"]["boost_wait"]["stuck"] is True
    unflips = len(table.unflips)
    actions = game.actions_left
    msgs = click(session, table, Event.CANCEL)
    assert session.pending is None and game.actions_left == actions
    assert len(table.unflips) == unflips + 2, "both cards are left face down again"
    assert second not in game.players[1].discard
    assert any("Combate cancelado" in m for m in msgs)


def test_moving_the_piece_back_before_continuing_resolves_the_combat(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    click(session, table, Event.REVEAL)
    table.positions["Lobster Johnson"] = 27
    click(session, table, Event.NO_BOOST)
    assert session.pending is not None and session.pending.boost_wait["stuck"]
    table.positions["Lobster Johnson"] = 2
    click(session, table, Event.NO_BOOST)
    assert session.pending is None and second in game.players[1].discard


def test_cancelar_is_still_refused_while_a_boost_wait_is_healthy(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    click(session, table, Event.REVEAL)
    msgs = click(session, table, Event.CANCEL)
    assert session.pending is not None and any("no se puede cancelar" in m for m in msgs)


def test_the_boost_card_has_to_come_from_the_hand(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    table.human_count = 4
    click(session, table, Event.REVEAL)
    assert session.pending.boost_wait["hand"] == 4
    table.human_discard = [card(game, 1, "Service Pistol").card_id]     # the hand has NOT gone down: it came from elsewhere
    msgs = click(session, table, Event.BOOST)
    assert session.pending is not None and any("tiene que salir de tu mano" in m for m in msgs)
    table.human_count = 3
    click(session, table, Event.BOOST)
    assert session.pending is None
    assert card(game, 1, "Service Pistol") in game.players[1].discard


def test_a_hand_that_dropped_by_two_is_not_a_boost_either(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    table.human_count = 4
    click(session, table, Event.REVEAL)
    table.human_discard = [card(game, 1, "Service Pistol").card_id]
    table.human_count = 2
    msgs = click(session, table, Event.BOOST)
    assert session.pending is not None and any("tenias 4" in m and "ahora tienes 2" in m for m in msgs)


def test_resume_in_boost_wait_shows_the_boost_prompt_not_the_reveal_one(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    click(session, table, Event.REVEAL)
    saved = json.loads(json.dumps(session.to_dict()))
    session.pending = None
    session.load_dict(saved)
    msgs = session.resume()
    assert any("Continuar" in m and "Sin boost" in m for m in msgs)
    assert not any("pulsa Revelar" in m for m in msgs)


def test_reveal_in_boost_wait_answers_even_though_no_card_is_face_down(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    click(session, table, Event.REVEAL)
    table.face_down = []                                  # the real table already has it face up
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is not None and any("Continuar" in m for m in msgs)
    assert not any("ninguna carta tuya boca abajo" in m for m in msgs)


def test_the_boost_wait_is_saved_with_the_hand_count(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    click(session, table, Event.REVEAL)
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["pending"]["boost_wait"]["hand"] == table.human_count
    session.pending = None
    session.load_dict(saved)
    assert session.pending.boost_wait["hand"] == table.human_count and session.pending.boost_wait["stuck"] is False
    bad = json.loads(json.dumps(saved))
    bad["pending"]["boost_wait"]["hand"] = "x"
    from sparring import persist
    with pytest.raises(persist.StateError):
        session.load_dict(bad)


def test_flips_use_the_identity_of_each_side(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    session._deck_ident["bot"] = (("https://img.test/bot-face", "https://img.test/bot-back"),)
    session._deck_ident["human"] = (("https://img.test/hum-face", "https://img.test/hum-back"),)
    table.scripts.clear()
    table.do_flip_card = lambda s: {"flipped": "x"}
    click(session, table, Event.REVEAL)
    flips = [s for s in table.scripts if s.startswith("-- sparring:flip_card")]
    assert len(flips) == 2
    assert "bot-face" in flips[0] and f"id < {lua.BOT_CARD_IDS[0]}" in flips[0]
    assert "hum-face" in flips[1] and f"id < {lua.HUMAN_CARD_IDS[0]}" in flips[1]


# ---------- session: identity ----------
def test_identities_are_saved_and_used_when_the_table_cannot_be_read(brig):  # noqa: F811
    session, table, game, fake = brig
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["deck_ident"]["bot"] == [list(TEST_IDENT[0])]
    session._deck_ident.clear()
    session.load_dict(saved)
    table.do_deck_identities = lambda s: {"__error__": "boom"}
    assert session._identity("bot") == TEST_IDENT and session._identity("human") == TEST_IDENT


def test_a_save_with_junk_identities_is_loaded_without_them(brig):  # noqa: F811
    session, table, game, fake = brig
    saved = json.loads(json.dumps(session.to_dict()))
    saved["deck_ident"] = {"bot": [["http://x", "y"], "z", None, ["https://a/b"]], "human": "no"}
    session.load_dict(saved)
    assert session._saved_ident == {}


def test_without_table_or_save_the_identity_comes_from_the_bots_hand_cards(brig):  # noqa: F811
    session, table, game, fake = brig
    session._deck_ident.clear()
    table.do_deck_identities = lambda s: {"__error__": "boom"}
    hand = [{"face": "https://img.test/h/face", "back": "https://img.test/h/back"},
            {"face": "not a url", "back": "https://img.test/h/back"}]
    table.do_hand_identities = lambda s: {"pairs": hand}
    assert session._identity("bot") == (("https://img.test/h/face", "https://img.test/h/back"),)


def test_with_no_source_at_all_the_identity_is_a_clear_error(brig):  # noqa: F811
    session, table, game, fake = brig
    session._deck_ident.clear()
    table.do_deck_identities = lambda s: [{"found": False, "pairs": []}]
    table.do_hand_identities = lambda s: {"pairs": []}
    with pytest.raises(SessionError, match="identidad"):
        session._identity("bot")


@pytest.mark.parametrize("bad", [[None], ["x"], [[1, 2]], {"a": 1}, None, "texto", [], [{"found": True}, None]])
def test_a_malformed_identity_reply_is_a_table_error_not_a_crash(brig, bad):  # noqa: F811
    session, table, game, fake = brig
    session._deck_ident.clear()
    table.do_deck_identities = lambda s, b=bad: b
    with pytest.raises(TTSLuaError):
        session.load_identities()


@pytest.mark.parametrize("bad", [[{"found": True, "pairs": "abc"}], [{"found": True}], [{"found": True, "pairs": [None, 3]}]])
def test_an_entry_without_usable_pairs_just_leaves_the_identity_unset(brig, bad):  # noqa: F811
    session, table, game, fake = brig
    session._deck_ident.clear()
    table.do_deck_identities = lambda s, b=bad: b
    session.load_identities()
    assert "bot" not in session._deck_ident


def test_unreadable_identity_writes_no_card_at_all(brig):  # noqa: F811
    session, table, game, fake = brig
    session._deck_ident.clear()
    table.do_deck_identities = lambda s: [{"found": False, "pairs": []}] * 2
    table.do_hand_identities = lambda s: {"pairs": []}
    table.scripts.clear()
    game.draw(0)
    session.dirty = True
    click(session, table, Event.END_ACTION)
    sent = {s.split("\n")[0] for s in table.scripts}
    assert not sent & {f"-- sparring:{t}" for t in ("deal_cards", "discard_cards", "reset_deck", "return_hand_to_deck",
                                                    "shuffle_deck", "play_card_face_down", "flip_card")}


# ---------- atomic restart ----------
def _restart_rig(brig, tmp_path):
    from test_panel_restart import prepared, with_cfg
    session, table, game, clock = prepared(brig, tmp_path)
    with_cfg(session, human_deck_guid="HDECK", human_deck_spot=(-4.6, 13.67))
    return session, table, game, clock


def test_a_restart_that_cannot_gather_the_human_deck_touches_nothing(brig, tmp_path):  # noqa: F811
    session, table, game, clock = _restart_rig(brig, tmp_path)
    table.do_reset_plan = lambda s: [{"deck": True, "loose": 0, "total": 30}, {"deck": False, "loose": 0, "total": 0}]
    click(session, table, Event.RESTART)
    msgs = click(session, table, Event.RESTART)
    assert session.game is game
    assert any("no puedo reunir las 30 cartas del mazo tuyo" in m and "no he movido nada" in m for m in msgs), msgs
    assert not any(s.startswith(("-- sparring:reset_deck", "-- sparring:place_piece", "-- sparring:set_health_dials"))
                   for s in table.scripts), "no side restarted half-way"
    assert table.resets == [] if hasattr(table, "resets") and isinstance(table.resets, list) else True


def test_a_restart_with_a_card_short_on_the_bot_side_is_refused_before_resetting_the_human(brig, tmp_path):  # noqa: F811
    session, table, game, clock = _restart_rig(brig, tmp_path)
    table.do_reset_plan = lambda s: [{"deck": True, "loose": 0, "total": 29}, {"deck": True, "loose": 0, "total": 30}]
    click(session, table, Event.RESTART)
    msgs = click(session, table, Event.RESTART)
    assert session.game is game and any("del bot" in m and "29" in m for m in msgs)
    assert not any(s.startswith("-- sparring:reset_deck") for s in table.scripts)


def test_a_complete_plan_lets_the_restart_go_ahead(brig, tmp_path):  # noqa: F811
    session, table, game, clock = _restart_rig(brig, tmp_path)
    click(session, table, Event.RESTART)
    click(session, table, Event.RESTART)
    assert session.game is not game
    sent = [s.split("\n")[0] for s in table.scripts]
    assert sent.index("-- sparring:reset_plan") < sent.index("-- sparring:reset_deck")


# ---------- Flame Lash (Liz): the BOOST is the card at the bottom of the deck ----------
FLAME = "DURING COMBAT: Discard the bottom card of your deck. Add its BOOST value to this card's value. AFTER COMBAT: Gain 1 action."


def flame_rig(brig):
    session, table, game, fake = brig
    game.fx.dsl_heroes.discard("hellboy")            # the legacy boost wait of the session (the real Flame Lash: test_e2_human_cards)
    shot = card(game, 1, "Second Shot")              # the rig is Hellboy's: Second Shot stands in for Flame Lash
    object.__setattr__(shot, "title", "Flame Lash")
    object.__setattr__(shot, "text", FLAME)
    game.fighters["lobster"].pos = 2
    table.positions["Lobster Johnson"] = 2
    click(session, table, Event.ATTACKER, {"attacker": "att_lobster"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    flame = human_plays(table, game, "Flame Lash")
    return session, table, game, flame


def test_flame_lash_waits_for_the_bottom_card_and_adds_its_boost(brig):  # noqa: F811
    session, table, game, flame = flame_rig(brig)
    table.human_count = 4
    msgs = click(session, table, Event.REVEAL)
    assert session.pending.boost_wait["deck"] and any("FONDO de tu mazo" in m for m in msgs)
    pistol = card(game, 1, "Service Pistol")
    table.human_discard = [pistol.card_id]           # it comes out of the deck: the hand stays at 4
    hp, actions = game.fighters["medusa"].hp, game.actions_left
    msgs = click(session, table, Event.BOOST)
    assert session.pending is None, msgs
    assert any(f"+{pistol.boost}" in m for m in msgs)
    assert game.fighters["medusa"].hp <= hp - (flame.value + pistol.boost) + 4   # her defense at most subtracts
    assert pistol in game.players[1].discard
    assert game.actions_left == actions - 1          # the legacy route resolves no AFTER (the real card: test_e2)


def test_second_shot_still_requires_the_boost_from_the_hand(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    table.human_count = 4
    click(session, table, Event.REVEAL)
    assert not session.pending.boost_wait["deck"]
    table.human_discard = [card(game, 1, "Service Pistol").card_id]
    msgs = click(session, table, Event.BOOST)                # the hand did not go down: not valid
    assert session.pending is not None and any("tiene que salir de tu mano" in m for m in msgs)
    table.human_count = 3
    click(session, table, Event.BOOST)
    assert session.pending is None


@pytest.mark.parametrize("old_save", [False, True])
def test_flame_lash_boost_wait_survives_resume(brig, old_save):  # noqa: F811
    session, table, game, flame = flame_rig(brig)
    table.human_count = 4
    click(session, table, Event.REVEAL)
    saved = json.loads(json.dumps(session.to_dict()))
    if old_save:                                             # save from before Flame Lash: without the key
        del saved["pending"]["boost_wait"]["deck"]
    session.pending = None
    session.load_dict(saved)
    assert session.pending.boost_wait["deck"] is True
    table.human_discard = [card(game, 1, "Service Pistol").card_id]
    msgs = click(session, table, Event.BOOST)
    assert session.pending is None, msgs
