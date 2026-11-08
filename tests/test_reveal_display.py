"""Revealed cards on the table (Ivan, 2026-11-08, every hero): a card text that says "reveal" shows the cards LARGE to every player until
the human presses "Stop revealing". Builders on lupa (tests/lua_stub.lua), the intents of every wired card on the engine, and the Jill Trent
sessions against FakeTTS (the shared fake table imitates the script: copies replace each other, `reveal_clear` and a cleaning remove them).
The cards of Doctor Strange and Houdini at the session are in tests/test_doctor_strange_human.py and tests/test_houdini_human.py."""
from __future__ import annotations

import json

import pytest

from conftest import give
from sparring.i18n import t
from sparring.tts import lua, ui
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import human_hand, said
from test_effects_bridge import STUB, conv
from test_jill_trent_effects import mk as jill_mk, on_top, wall
from test_jill_trent_effects import pair as jill_pair
from test_jill_trent_human import JillTable, TRAINING, attack, choose_gadget, rig, with_rig  # noqa: F401

lupa = pytest.importorskip("lupa")
from lupa import lua54  # noqa: E402

BOT_IDENT = (("https://img.test/bot/face", "https://img.test/bot/back"),)
HUM_IDENT = (("https://img.test/hum/face", "https://img.test/hum/back"),)
BOT_IDS, HUM_IDS = (100, 129), (200, 229)
SPEC = lua.RevealSpec((0.0, 14.0, 0.0), (0.0, 270.0, 0.0), 2.5, 6.2)
ZOOM = lua.ZoomSpec((1.0, 12.0, 2.0), (0.0, 90.0, 0.0), 4.0, 6.0)


@pytest.fixture
def rt():
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: json.dumps(conv(v))})
    runtime.execute("""
mkobj({guid = "botdeck", type = "Deck", owner = "bot", pos = Vector(-5, 1, 0), cards = {
  {cid = 101, guid = "b101", owner = "bot"}, {cid = 105, guid = "b105", owner = "bot"}, {cid = 107, guid = "b107", owner = "bot"}}})
mkobj({guid = "humdeck", type = "Deck", owner = "hum", pos = Vector(5, 1, 0), cards = {
  {cid = 201, guid = "h201", owner = "hum"}, {cid = 205, guid = "h205", owner = "hum"}, {cid = 207, guid = "h207"}}})
mkobj({guid = "pile", type = "Card", cid = 110, owner = "bot", pos = Vector(9, 1, 9), is_face_down = false})
mkobj({guid = "inhand", type = "Card", cid = 210, owner = "hum", hand = "Red", pos = Vector(50, 1, 50)})
""")
    return runtime


def reveal(rt, *groups, seats=("Red",)):
    return json.loads(rt.execute(lua.reveal_show(list(groups), SPEC, seats)))


def group(side, *ids):
    return lua.RevealGroup(tuple(ids), BOT_IDS if side == "bot" else HUM_IDS, BOT_IDENT if side == "bot" else HUM_IDENT)


def copies(rt):
    return list(rt.eval('(function() local t = {} for _, o in ipairs(getObjects()) do '
                        'if o.name == "SparringZoom" and o.gm == "sparring-reveal" then t[#t + 1] = o end end return t end)()').values())


def deck_state(rt):
    return rt.eval('(function() local o = {} for _, d in ipairs({getObjectFromGUID("botdeck"), getObjectFromGUID("humdeck")}) do '
                   'for _, c in ipairs(d.cards) do o[#o + 1] = c.guid end end return table.concat(o, ",") end)()')


# ---------- the builders ----------
def test_the_reveal_lays_large_face_up_locked_copies_side_by_side_and_touches_no_original(rt):
    before = deck_state(rt)
    out = reveal(rt, group("bot", 101, 105), group("human", 205))
    assert out == {"shown": 3, "missing": []}
    spots = rt.eval('(function() local t = {} for _, o in ipairs(getObjects()) do if o.gm == "sparring-reveal" then '
                    't[#t + 1] = {o.cid, o.scale.x, o.locked, o.interactable, o.pos.x, o.pos.y, o.pos.z, o.rot.x, o.rot.y, o.rot.z} end end '
                    'return t end)()')
    rows = sorted((tuple(r.values()) for r in spots.values()), key=lambda r: r[6])
    assert [r[1:5] for r in rows] == [(2.5, True, False, 0.0)] * 3
    assert [r[5:6] for r in rows] == [(14.0,)] * 3
    assert [round(r[6], 1) for r in rows] == [-6.2, 0.0, 6.2], "centred on the spot, one step apart along z"
    assert all(r[7:10] == (0.0, 270.0, 0.0) for r in rows), "face up (z 0) and turned to the human's seat"
    assert deck_state(rt) == before and rt.eval("MOVES") in (None, 0), "no original moved, no deck order touched"
    assert rt.eval("#TIMERS") == 0, "nothing destroys them by itself: only the human does"


def test_cards_are_found_in_a_deck_a_pile_and_a_hand_and_the_order_asked_is_kept(rt):
    out = reveal(rt, group("bot", 107, 110), group("human", 210, 201))
    assert out["shown"] == 4 and out["missing"] == []
    ordered = [o.cid for o in sorted(copies(rt), key=lambda o: o.pos.z)]
    assert [c % 100 for c in ordered] == [7, 10, 10, 1]
    assert len({c // 100 for c in ordered}) == 4, "every copy has a deck key of its own: two sides never share an image sheet"


def test_a_card_that_is_not_there_or_of_the_other_side_is_missing_not_guessed(rt):
    out = reveal(rt, group("bot", 101, 150), group("human", 101))
    assert out["shown"] == 1 and out["missing"] == [150, 101]


def test_a_new_reveal_replaces_the_copies_on_show(rt):
    reveal(rt, group("bot", 101, 105, 107))
    reveal(rt, group("human", 205))
    assert len(copies(rt)) == 1


def test_the_copies_are_not_cards_of_any_side_and_the_table_reads_skip_them(rt):
    reveal(rt, group("bot", 101), group("human", 201))
    for ident, rng in ((BOT_IDENT, BOT_IDS), (HUM_IDENT, HUM_IDS), (BOT_IDENT, (0, 99899)), (HUM_IDENT, (0, 99899)),
                       (BOT_IDENT, (0, 99999)), (HUM_IDENT, (0, 99999))):
        probe = lua._ours_lua(ident, rng)
        n = rt.execute(probe + 'local n = 0 for _, o in ipairs(getObjects()) do '
                               'if o.gm == "sparring-reveal" and ours(o) then n = n + 1 end end return n')
        assert n == 0
    assert all(o.cid >= 100000 for o in copies(rt))
    rt.execute('mkobj({guid = "loose", type = "Card", cid = 150, owner = "x", pos = Vector(0, 14, 0)})')
    seen = json.loads(rt.execute(lua.read_cards_at(0.0, 0.0)))
    assert [c["guid"] for c in seen] == ["loose"], "a position read at the very spot sees only the real card"
    again = reveal(rt, group("bot", 101))
    assert again["shown"] == 1 and len(copies(rt)) == 1, "a copy is never taken for the card to copy"


def test_zoom_and_reveal_copies_coexist_and_neither_cleaning_touches_the_other(rt):
    rt.execute('mkobj({guid = "c1", type = "Card", cid = 150, owner = "x", pos = Vector(5, 1, 5)})')
    reveal(rt, group("bot", 101))
    rt.execute(lua.flip_card("c1", 90, True, (100, 600), identity=(("https://img.test/x/face", "https://img.test/x/back"),), zoom=ZOOM))
    assert len(copies(rt)) == 1, "a zoom does not destroy the reveal copies"
    reveal(rt, group("human", 201))
    zooms = [o for o in rt.eval('getObjects()').values() if o.name == "SparringZoom" and o.gm == "sparring"]
    assert len(zooms) == 1, "a reveal does not destroy the zoom copy"
    rt.execute(lua.reveal_clear())
    assert copies(rt) == [] and len([o for o in rt.eval('getObjects()').values() if o.gm == "sparring"]) == 1


def test_reveal_clear_destroys_only_the_copies(rt):
    reveal(rt, group("bot", 101, 105))
    n = rt.eval("#getObjects()")
    assert json.loads(rt.execute(lua.reveal_clear())) == {"removed": 2}
    assert rt.eval("#getObjects()") == n - 2 and deck_state(rt).count("b10") == 3


def test_the_cleaning_of_the_table_removes_the_copies_only_when_it_removes_the_panel(rt):
    reveal(rt, group("bot", 101))
    rt.execute(lua.clear_markings())
    assert len(copies(rt)) == 1
    out = json.loads(rt.execute(lua.clear_markings(remove_panel=True)))
    assert copies(rt) == [] and out["removed"] == 1


def test_the_reveal_builders_are_allowlisted_ascii_and_validated():
    for script in (lua.reveal_show([group("bot", 1, 2)], SPEC, ("Red",)), lua.reveal_clear()):
        assert lua.is_sendable(script) and script.isascii() and lua.is_sendable(lua.composite([script]))
    for bad in ([], [group("bot")], [group("bot", *range(9))]):
        with pytest.raises((ValueError, TypeError)):
            lua.reveal_show(bad, SPEC)
    for spec in (lua.RevealSpec((0, 14, 0), (0, 0, 0), 0, 6), lua.RevealSpec((0, 14, 0), (0, 0, 0), 99, 6),
                 lua.RevealSpec((0, 14), (0, 0, 0), 2, 6), lua.RevealSpec((0, 14, 0), (0, 0, 0), 2, 0)):
        with pytest.raises((ValueError, TypeError)):
            lua.reveal_show([group("bot", 1)], spec)
    with pytest.raises(ValueError):
        lua.reveal_show([group("bot", 1)], SPEC, ("Nobody",))


def test_the_panel_has_a_born_hidden_stop_button_wired_to_its_event():
    xml = ui.panel_xml(["medusa"])
    assert 'id="btn_unreveal" onClick="onStopReveal">' + t("panel.stop_reveal") in xml and 'active="false" ' in xml.split('id="btn_unreveal"')[0][-200:]
    assert "btn_unreveal" in ui.element_ids(["medusa"]) and "function onStopReveal() send({event = \"stop_reveal\"})" in ui.handler_script(ids=["btn_unreveal"])
    assert ui.parse_event({"event": "stop_reveal"})[0] is Event.STOP_REVEAL


# ---------- the intents of every wired card, on the engine ----------
def revealed(g):
    from sparring import session_reveal
    class S:  # the side of a holder is all `revealed_by` needs
        bot = 0
    return session_reveal.revealed_by(S, g.fx.intents)


def test_jill_hypnoray_reveals_the_rivals_top_card(bprd):
    g = jill_mk(bprd)
    jill, foe = jill_pair(g, "jill", "hellboy")
    top = on_top(g, 1, "Second Shot")
    g.fx.intents = []
    g.attack(jill, foe, give(g, 0, "Battle of Wits"), wall(g))
    assert top.card_id in dict(revealed(g))["human"], "the top card of the rival's deck (the card's own AFTER reveals more)"


def test_jill_battle_of_wits_reveals_both_top_cards(bprd):
    g = jill_mk(bprd, gadget=0)
    jill, foe = jill_pair(g, "jill", "hellboy")
    attack, defense = give(g, 0, "Battle of Wits"), wall(g)
    mine = g.players[0].deck[0]
    g.fx.intents = []
    g.attack(jill, foe, attack, defense)
    shown = revealed(g)
    assert [side for side, _ in shown] == ["bot", "human"] and shown[0][1] == [mine.card_id] and len(shown[1][1]) == 1


def test_jill_insightful_deduction_reveals_the_top_three_before_the_owner_decides(bprd):
    g = jill_mk(bprd, gadget=0)
    jill, foe = jill_pair(g, "jill", "hellboy")
    top3 = [c.card_id for c in g.players[1].deck[:3]]
    g.fx.intents = []
    g.attack(jill, foe, give(g, 0, "Insightful Deduction"), None)
    ops = [i["op"] for i in g.fx.intents]
    assert ops == ["reveal_top", "deck_order"], "reveal first, once; then the reorder"
    assert revealed(g) == [("human", top3)]


def test_strange_mists_of_the_human_reveals_the_bots_deck_from_the_top(bprd):
    from test_doctor_strange_effects import decline_pact, mk
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    g.turn, g.actions_left = 1, 2
    s, liz = jill_pair(g, "strange", "liz")
    g.fx.intents = []
    res = g.attack(liz, s, give(g, 1, "Flame Lash"), give(g, 0, "The Mists of Munnopor"))
    (shown,) = [i for i in g.fx.intents if i["op"] == "reveal_deck"]
    assert shown["revealed"] and shown["player"] == 1 and res.atk_card is not None
    assert revealed(g) == [] , "that was the human's deck: they reveal it by hand"


def test_the_mists_intent_of_the_bots_own_deck_is_shown_in_the_order_it_was_revealed():
    class Bot:
        bot = 0
    from sparring import session_reveal
    intents = [{"op": "reveal_deck", "player": 0, "revealed": [11, 12, 13], "found": 13, "source": 5},
               {"op": "reveal_deck", "player": 1, "revealed": [40], "found": None, "source": 5}]
    assert session_reveal.revealed_by(Bot, intents) == [("bot", [11, 12, 13])]


def test_strange_no_really_reveals_the_card_it_puts_on_top(bprd):
    from test_doctor_strange_effects import mk
    g = mk(bprd, "liz-sherman")
    g.fighters["strange"].hp = 6
    doc, high = give(g, 0, "No, Really, I'm a Doctor"), give(g, 0, "Bolts of Balthakk")
    g.controllers[0].choose_effect = lambda game, req: [high.card_id] if req.kind == "cards" else None
    g.actions_left = 2
    g.fx.intents = []
    assert g.play_scheme(0, g.fighters["strange"], doc) is None
    assert revealed(g) == [("bot", [high.card_id])]


def test_houdini_reveals_the_magician_that_cancels_a_look(bprd):
    from test_houdini_effects import confront, mk
    g = mk(bprd, turn=1)
    g.fx.intents = []
    shield, _, res = confront(g, ["Flourish"], True)
    assert revealed(g) == [("bot", [shield.card_id])]


def test_houdini_keeps_the_magician_hidden_when_it_is_not_revealed(bprd):
    from test_houdini_effects import confront, mk
    g = mk(bprd, turn=1)
    g.fx.intents = []
    confront(g, ["Flourish"], False)
    assert revealed(g) == []


# ---------- sessions: Jill Trent against FakeTTS ----------
def stop_button(session):
    return session.panel_view()[1]["btn_unreveal"]


def adjacent(session, table, game, cfg):
    jill, hellboy = game.fighters["jill"], game.fighters["hellboy"]
    hellboy.pos = next(s for s in sorted(game.board.adj[jill.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = hellboy.pos


@with_rig("hellboy", "jill-trent", TRAINING)
def test_hypnoray_lays_the_bots_revealed_card_and_the_button_shows(rig, monkeypatch):
    from test_e2_human_cards import bot_defends_with
    session, table, game, fake, cfg = rig
    choose_gadget(session, table, 1)
    adjacent(session, table, game, cfg)
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Battle of Wits", "Laser Pen")
    assert table.reveal_copies == [] and stop_button(session) == (True, False), "hidden, never greyed out, with nothing revealed"
    top = game.players[0].deck[0]
    msgs = attack(session, table, game, "jill", "Battle of Wits")
    assert top.card_id in table.reveal_copies and stop_button(session) == (True, True)
    assert said(msgs, f"Reveladas arriba de mi mazo: {top.title}") and said(msgs, "Dejar de revelar")
    assert table.panels[-1][1]["btn_unreveal"] == (True, True), "the panel written to TTS shows it"


@with_rig("hellboy", "jill-trent", TRAINING)
def test_battle_of_wits_lays_both_top_cards_in_one_row(rig, monkeypatch):
    from test_e2_human_cards import bot_defends_with
    session, table, game, fake, cfg = rig
    choose_gadget(session, table, 2)                                   # no Hypnoray: the card's own reveal
    adjacent(session, table, game, cfg)
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Battle of Wits", "Laser Pen")
    table.human_deck = [c.card_id for c in game.players[1].deck[5:9]]
    mine = table.human_deck[0]
    attack(session, table, game, "jill", "Battle of Wits")
    assert mine in table.reveal_copies and len(table.reveal_copies) == 2 and stop_button(session) == (True, True)
    reveals = [s for s in table.scripts if s.startswith("-- sparring:reveal_show")]
    assert len(reveals) == 1, "both decks in ONE write: the second never replaces the first"


@with_rig("hellboy", "jill-trent", TRAINING)
def test_insightful_deduction_of_the_human_shows_the_three_before_they_choose_and_keeps_them(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    choose_gadget(session, table, 1)
    adjacent(session, table, game, cfg)
    game.fx.set_counter(1, "gadget", 0)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: None)
    human_hand(table, game, "Insightful Deduction", "Laser Pen")
    top3 = [c.card_id for c in game.players[0].deck[:3]]
    attack(session, table, game, "jill", "Insightful Deduction")
    assert session.effect_run.awaiting.extra["purpose"] == "bottom", "the human is still deciding"
    assert table.reveal_copies == top3 and stop_button(session) == (True, True), "already on the table, in the order they lay"
    click(session, table, Event.CHOICE, {"i": 2})
    click(session, table, Event.CHOICE, {"i": 2})
    click(session, table, Event.CHOICE, {"i": 1})
    assert session.effect_run is None and table.reveal_copies == top3, "they stay after the decision"
    assert len([s for s in table.scripts if s.startswith("-- sparring:reveal_show")]) == 1, "shown once, not on every rerun of the op"


def bot_insightful(session, table, game, cfg):
    from sparring.ai_medusa import Act
    from test_d3_table_effects import bot_turn, card_ids
    game.fx.set_counter(0, "gadget", 0)
    adjacent(session, table, game, cfg)
    table.human_deck = [c.card_id for c in game.players[1].deck[5:9]]
    human_hand(table, game, TRAINING)
    card = next(c for c in game.players[0].hand if c.title == "Insightful Deduction")
    bot_turn(session, table, [Act("attack", fid="jill", target="hellboy", card=card)])
    cid = card_ids(game, 1, TRAINING)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    return list(table.human_deck)


@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_the_bot_reveals_your_top_three_then_reorders_blind_and_the_copies_stay(rig):
    session, table, game, fake, cfg = rig
    before = bot_insightful(session, table, game, cfg)
    msgs = click(session, table, Event.REVEAL)
    assert table.reveal_copies == before[:3] and stop_button(session) == (True, True)
    heads = [s.split("\n", 1)[0] for s in table.scripts]
    assert heads.index("-- sparring:reveal_show") < heads.index("-- sparring:deck_reorder"), "reveal and display first, the blind reorder after"
    assert len(table.reorders) == 1 and said(msgs, "he reordenado las 3 cartas superiores")
    order_line = next(m for m in msgs if "reordenado" in m)
    assert "Pancakes" not in order_line and "debajo" not in order_line.split("fondo")[0], "the reorder line is still only a count"
    assert table.reveal_copies == before[:3], "the copies show the cards as they were (public), never the new order"


@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_a_failed_reveal_write_does_not_leave_the_button_on(rig):
    session, table, game, fake, cfg = rig
    table.do_reveal_show = lambda s: {"shown": 0, "missing": [1, 2, 3]}
    bot_insightful(session, table, game, cfg)
    click(session, table, Event.REVEAL)
    assert stop_button(session) == (True, False)


# ---------- the button and the cleaning ----------
@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_the_button_destroys_the_copies_and_hides_itself_in_every_state(rig):
    session, table, game, fake, cfg = rig
    bot_insightful(session, table, game, cfg)
    click(session, table, Event.REVEAL)
    assert table.reveal_copies and session.reveal_shown
    click(session, table, Event.STOP_REVEAL)
    assert table.reveal_copies == [] and not session.reveal_shown and stop_button(session) == (True, False)
    assert table.panels[-1][1]["btn_unreveal"] == (True, False)
    sent = len(table.scripts)
    click(session, table, Event.STOP_REVEAL)
    assert not [s for s in table.scripts[sent:] if s.startswith("-- sparring:reveal_clear")], "a second press has nothing to remove and sends nothing"


@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_play_carries_on_with_the_copies_on_show_until_the_human_dismisses_them(rig):
    session, table, game, fake, cfg = rig
    bot_insightful(session, table, game, cfg)
    click(session, table, Event.REVEAL)
    shown = list(table.reveal_copies)
    session.ai.plan = lambda g: __import__("sparring.ai_medusa", fromlist=["Act"]).Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    assert table.reveal_copies == shown and stop_button(session) == (True, True)


@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_a_new_reveal_replaces_the_copies_on_show(rig):
    from sparring import session_reveal
    session, table, game, fake, cfg = rig
    bot_insightful(session, table, game, cfg)
    click(session, table, Event.REVEAL)
    session_reveal.show(session, [("bot", [game.players[0].deck[0].card_id])])
    session._flush()
    assert table.reveal_copies == [game.players[0].deck[0].card_id]


@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_new_game_restart_and_resume_remove_the_copies(rig):
    session, table, game, fake, cfg = rig
    bot_insightful(session, table, game, cfg)
    click(session, table, Event.REVEAL)
    assert table.reveal_copies
    click(session, table, Event.NEW_GAME)
    click(session, table, Event.NEW_GAME)
    assert table.reveal_copies == [] and not session.reveal_shown and session.back_to_gate

    session.reveal_shown = True
    table.reveal_copies = [1, 2]
    click(session, table, Event.RESTART)
    click(session, table, Event.RESTART)
    assert table.reveal_copies == [] and not session.reveal_shown

    table.reveal_copies = [7]                       # a run that died left a copy: the session does not know of it
    session.reveal_shown = False
    session.resume()
    assert table.reveal_copies == [], "no orphan copy after --resume"


@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_clean_table_removes_the_copies(rig):
    session, table, game, fake, cfg = rig
    bot_insightful(session, table, game, cfg)
    click(session, table, Event.REVEAL)
    assert table.reveal_copies
    fake.received.clear()
    session.client.call_lua(lua.clear_markings(remove_panel=True))
    assert table.reveal_copies == []


@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_the_display_can_be_switched_off_by_config(rig):
    session, table, game, fake, cfg = rig
    session.cfg.reveal_display = False
    bot_insightful(session, table, game, cfg)
    click(session, table, Event.REVEAL)
    assert table.reveal_copies == [] and not [s for s in table.scripts if s.startswith("-- sparring:reveal_show")]


@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_the_chat_line_about_the_copies_comes_after_the_lines_naming_the_cards(rig):
    session, table, game, fake, cfg = rig
    bot_insightful(session, table, game, cfg)
    msgs = [str(m) for m in click(session, table, Event.REVEAL)]
    named = next(i for i, m in enumerate(msgs) if "Reveladas arriba de tu mazo" in m)
    button = next(i for i, m in enumerate(msgs) if "Dejar de revelar" in m)
    assert named < button


@with_rig("jill-trent", "hellboy", "Insightful Deduction", "Laser Pen", "Energizing Spray")
def test_more_cards_than_the_table_holds_show_the_first_ones_and_count_the_rest(rig):
    from sparring import session_reveal
    session, table, game, fake, cfg = rig
    ids = [c.card_id for c in game.players[0].deck[:11]]
    session.messages = []
    check = session_reveal.show(session, [("bot", ids)])
    session._flush()
    check()
    assert table.reveal_copies == ids[:8] and session.reveal_shown
    assert any("3 carta(s) revelada(s) mas no caben" in str(m) for m in session.messages)


def test_discard_zone_read_skips_a_copy_lying_in_the_zone(rt):
    rt.execute('mkobj({guid = "ZN", type = "Scripting", cx = 0, cz = 0, hw = 30, hd = 30})')
    reveal(rt, group("bot", 101))
    rt.execute('mkobj({guid = "real", type = "Card", cid = 150, owner = "x", pos = Vector(1, 1, 1), is_face_down = false})')
    rows = json.loads(rt.execute(lua.read_discard("ZN")))
    assert "real" in [r["guid"] for r in rows] and not [r for r in rows if r["id"] >= 100000], "the copy is not a discard card"
