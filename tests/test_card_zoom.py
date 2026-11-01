"""The bot shows the human a BIG copy of the cards it plays (like Alt+hover, triggered by the bot) and, at game over, a
modal with the verdict. Builders on lupa (tests/lua_stub.lua) and sessions against FakeTTS; never the real TTS."""
import json
import re

import pytest

from sparring import i18n
from sparring.ai_medusa import Act
from sparring.tts import lua
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401  (fixture)
from test_effects_bridge import STUB, X_IDENT, X_IDS, conv

lupa = pytest.importorskip("lupa")
from lupa import lua54  # noqa: E402

ZOOM = lua.ZoomSpec((1.0, 12.0, 2.0), (0.0, 90.0, 0.0), 4.0, 6.0)


@pytest.fixture
def rt():
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: json.dumps(conv(v))})
    return runtime


def card(rt, guid="c1", cid=150, **kw):
    rt.execute(f'mkobj({{guid = "{guid}", type = "Card", cid = {cid}, owner = "x", pos = Vector(5, 1, 5)}})')


def zoomed(rt):
    return rt.eval('(function() local t = {} for _, o in ipairs(getObjects()) do '
                   'if o.name == "SparringZoom" then t[#t + 1] = o end end return t end)()')


# ---------- the builders ----------
def test_a_flip_with_zoom_spawns_one_locked_big_copy_and_never_touches_the_real_card(rt):
    card(rt)
    rt.execute(lua.flip_card("c1", 90, True, X_IDS, identity=X_IDENT, zoom=ZOOM))
    copies = list(zoomed(rt).values())
    assert len(copies) == 1
    assert rt.eval('getObjectFromGUID("c1").pos.x') == 5 and rt.eval('getObjectFromGUID("c1").moved_count') in (None, 0)
    assert rt.eval('(function() for _, o in ipairs(getObjects()) do if o.name == "SparringZoom" then '
                   'return o.cid, o.scale.x, o.locked, o.interactable, o.gm, o.pos.y, o.rot.y end end end)()') \
        == (99950, 4.0, True, False, "sparring", 12.0, 90.0)


def test_the_copy_is_not_a_card_of_any_side_by_range_image_or_name(rt):
    card(rt)
    rt.execute(lua.flip_card("c1", 90, True, X_IDS, identity=X_IDENT, zoom=ZOOM))
    assert rt.eval('(function() for _, o in ipairs(getObjects()) do if o.name == "SparringZoom" then '
                   'local d = o.getData() return d.CardID, (next(d.CustomDeck)) end end end)()') == (99950, "999")
    for pair in ((100, 600), (17600, 17629), (19700, 19729), (0, 99899)):
        probe = lua._ours_lua(X_IDENT, pair)
        assert rt.execute(probe + 'local n = 0 for _, o in ipairs(getObjects()) do '
                                  'if o.name == "SparringZoom" and ours(o) then n = n + 1 end end return n') == 0


def test_only_one_copy_at_a_time_and_it_destroys_itself(rt):
    card(rt, "c1", 150)
    card(rt, "c2", 151)
    rt.execute(lua.flip_card("c1", 0, True, X_IDS, identity=X_IDENT, zoom=ZOOM))
    rt.execute(lua.flip_card("c2", 0, True, X_IDS, identity=X_IDENT, zoom=ZOOM))
    assert len(zoomed(rt)) == 1 and rt.eval("#TIMERS") == 2
    assert rt.eval('(function() for _, o in ipairs(getObjects()) do if o.name == "SparringZoom" then return o.cid end end end)()') == 99951
    rt.execute("for _, f in ipairs(TIMERS) do f() end")
    assert len(zoomed(rt)) == 0, "after the seconds it is gone, and the stale timer of the first did not fail"
    assert rt.eval('getObjectFromGUID("c1") ~= nil and getObjectFromGUID("c2") ~= nil')


def test_hiding_a_card_again_shows_no_zoom(rt):
    card(rt)
    rt.execute(lua.flip_card("c1", 0, False, X_IDS, identity=X_IDENT, zoom=ZOOM))
    assert len(zoomed(rt)) == 0


def test_the_ongoing_placed_face_up_is_zoomed(rt):
    rt.execute('mkobj({guid = "h1", type = "Card", cid = 150, owner = "x", hand = "Blue"})')
    out = json.loads(rt.execute(lua.place_card_face_up(150, "Blue", 1, 2, 3, 0, X_IDS, identity=X_IDENT, zoom=ZOOM)))
    assert out == {"placed": "h1"} and len(zoomed(rt)) == 1


def test_a_zoom_failure_never_breaks_the_write(rt):
    rt.execute('mkobj({guid = "h1", type = "Card", cid = 150, owner = "x", hand = "Blue"})')
    rt.execute("spawnObjectData = function() error('no spawn') end")
    out = json.loads(rt.execute(lua.place_card_face_up(150, "Blue", 1, 2, 3, 0, X_IDS, identity=X_IDENT, zoom=ZOOM)))
    assert out == {"placed": "h1"}


def test_discard_zooms_only_the_card_asked_for(rt):
    scope = lua.Scope(("Blue",), ("ZN",), ((0.0, 0.0),))
    rt.execute('mkobj({guid = "h1", type = "Card", cid = 150, owner = "x", hand = "Blue"})')
    rt.execute('mkobj({guid = "h2", type = "Card", cid = 151, owner = "x", hand = "Blue"})')
    rt.execute('mkobj({guid = "ZN", type = "Zone", cx = 99, cz = 99, hw = 1, hd = 1})')
    script = lua.discard_cards([150, 151], [(1.0, 2.0, 3.0), (4.0, 2.0, 3.0)], 90, identity=X_IDENT, scope=scope,
                               id_range=X_IDS, zoom=ZOOM, zoom_id=151)
    assert json.loads(rt.execute(script))["moved"] == [150, 151]
    assert rt.eval('(function() for _, o in ipairs(getObjects()) do if o.name == "SparringZoom" then return o.cid end end end)()') == 99951


def test_a_script_without_zoom_carries_no_zoom_code():
    assert "sparringZoom" not in lua.flip_card("c1", 0, True, X_IDS, identity=X_IDENT)
    assert "sparringZoom" not in lua.place_card_face_up(150, "Blue", 1, 2, 3, 0, X_IDS, identity=X_IDENT)


def test_zoom_scripts_are_allowlisted_ascii_and_validated():
    for script in (lua.flip_card("c1", 0, True, X_IDS, identity=X_IDENT, zoom=ZOOM),
                   lua.place_card_face_up(150, "Blue", 1, 2, 3, 0, X_IDS, identity=X_IDENT, zoom=ZOOM),
                   lua.info_dialog("White", "You win! Baba Yaga has fallen.")):
        assert lua.is_sendable(script) and script.isascii()
        assert lua.is_sendable(lua.composite([script]))
    for bad in (lua.ZoomSpec((0, 12, 0), (0, 0, 0), 0, 6), lua.ZoomSpec((0, 12, 0), (0, 0, 0), 4, 0),
                lua.ZoomSpec((0, 12, 0), (0, 0, 0), 99, 6), lua.ZoomSpec((0, 12, 0), (0, 0, 0), 4, 999),
                lua.ZoomSpec((0, 12), (0, 0, 0), 4, 6)):
        with pytest.raises((ValueError, TypeError)):
            lua.flip_card("c1", 0, True, X_IDS, identity=X_IDENT, zoom=bad)


def test_info_dialog_shows_the_text_to_that_seat_and_fails_silently_without_the_api(rt):
    assert json.loads(rt.execute(lua.info_dialog("White", "You win! Medusa has fallen."))) == {"dialog": True}
    assert rt.eval('DIALOGS[1].color') == "White" and rt.eval('DIALOGS[1].text') == "You win! Medusa has fallen."
    rt.execute("NO_DIALOG = true")
    assert json.loads(rt.execute(lua.info_dialog("White", "x"))) == {"dialog": False}
    for bad in ('say "hi"', "a\\b", "", "x" * 300):
        with pytest.raises(ValueError):
            lua.info_dialog("White", bad)
    with pytest.raises(ValueError):
        lua.info_dialog("Nobody", "x")


# ---------- sessions against FakeTTS ----------
def zoom_scripts(table):
    return [s for s in table.scripts if "sparringZoom(" in s and "local function sparringZoom" in s]


def zoom_calls(table):
    return [s for s in zoom_scripts(table) if re.search(r"^\s*sparringZoom\(\w+\)", s, re.M) or "if id == zoomId then" in s]


def attack_and_reveal(session, table, game):
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    card = next(c for c in game.players[1].full_set if c.can_attack and c.value is not None
                and c.usable_by(game.hero(1).name))
    table.face_down = [{"id": card.card_id, "guid": "hcard"}]
    return click(session, table, Event.REVEAL)


def test_revealing_the_combat_makes_one_zoom_in_the_same_message(brig):
    session, table, game, fake = brig
    session.cfg.card_zoom = True
    session.cfg.card_zoom_spot = (0.0, 12.0, 0.0)
    attack_and_reveal(session, table, game)
    assert zoom_scripts(table), "the bot's combat card is zoomed when revealed or discarded"
    assert sum(s.count("sparringZoom(c)") + s.count("if id == zoomId then sparringZoom(o) end") for s in zoom_scripts(table)) >= 1
    assert all("spawnObjectData" in s for s in zoom_scripts(table))


def test_zoom_off_by_config_sends_no_zoom_code(brig):
    session, table, game, fake = brig
    session.cfg.card_zoom = False
    attack_and_reveal(session, table, game)
    assert not any("sparringZoom" in s for s in table.scripts)


def test_a_combat_step_adds_no_message_for_the_zoom(brig):
    session, table, game, fake = brig
    session.cfg.card_zoom = True
    n, sent = fake.lua_messages, len(table.sent)
    attack_and_reveal(session, table, game)
    step = table.sent[sent:]
    assert fake.lua_messages - n == len(step) and set(step) == {"composite"}, "no standalone zoom message"
    assert zoom_scripts(table), "and the zoom rode in those composites"


def bot_scheme_turn(session, table, game, title):
    card = next(c for c in game.players[0].full_set if c.title == title)
    table.bot_hand = [card.card_id]
    session.read_bot_hand()
    plan = [Act("scheme", card=card)]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    return card, click(session, table, Event.END_ACTION)


# ---------- game over ----------
def dialogs(table):
    return [s for s in table.scripts if s.startswith("-- sparring:info_dialog")]


def test_the_human_wins_and_sees_the_modal_in_spanish(brig):
    session, table, game, fake = brig
    msgs = click(session, table, Event.REMOVE, {"fighter": "medusa"})
    assert game.winner == 1
    shown = dialogs(table)
    assert len(shown) == 1 and 'Player["Red"].showInfoDialog("Has ganado! Medusa ha caido.")' in shown[0]
    assert any("Fin de partida" in m for m in msgs), "the chat line stays"


def test_the_bot_wins_and_the_modal_is_in_english_when_the_language_is_english(brig):
    session, table, game, fake = brig
    i18n.set_language("en")
    try:
        click(session, table, Event.REMOVE, {"fighter": "hellboy"})
        assert game.winner == 0
        assert 'showInfoDialog("The bot wins: Hellboy has fallen.")' in dialogs(table)[0]
    finally:
        i18n.set_language("es")


def test_the_modal_goes_in_the_game_over_message_and_only_once(brig):
    session, table, game, fake = brig
    click(session, table, Event.REMOVE, {"fighter": "medusa"})
    carrying = [ops for ops in table.msglog if "info_dialog" in ops]
    assert len(carrying) == 1 and len(carrying[0]) > 1, "the modal rides in a composite with the other writes"
    assert len(dialogs(table)) == 1
    click(session, table, Event.HP, {"fighter": "medusa", "delta": 0})
    assert len(dialogs(table)) == 1, "a second reading does not repeat it"
    click(session, table, Event.UNDO_GAME_OVER)
    assert game.winner is None


def test_no_modal_when_there_is_no_game_over(brig):
    session, table, game, fake = brig
    click(session, table, Event.MANEUVER)
    assert not dialogs(table)


def test_position_reads_skip_the_copy_even_when_it_floats_over_the_spot(rt):
    near = lua.ZoomSpec((5.0, 12.0, 5.0), (0.0, 90.0, 0.0), 4.0, 6.0)
    card(rt)
    rt.execute(lua.flip_card("c1", 0, True, X_IDS, identity=X_IDENT, zoom=near))
    assert len(zoomed(rt)) == 1
    seen = json.loads(rt.execute(lua.read_cards_at(5.0, 5.0)))
    assert [c["guid"] for c in seen] == ["c1"], "only the real card is read"


def schemes_of(game, player=0):
    return [c.title for c in game.players[player].full_set if c.type == "scheme"]


def test_a_bot_scheme_is_zoomed_when_it_goes_to_its_discard(brig):
    session, table, game, fake = brig
    session.cfg.card_zoom = True
    title = schemes_of(game)[0]
    bot_scheme_turn(session, table, game, title)
    assert zoom_scripts(table) and any("if id == zoomId then sparringZoom(o) end" in s for s in zoom_scripts(table))


def test_a_bot_scheme_with_zoom_off_sends_nothing_extra(brig):
    session, table, game, fake = brig
    session.cfg.card_zoom = False
    bot_scheme_turn(session, table, game, schemes_of(game)[0])
    assert not any("sparringZoom" in s for s in table.scripts)


# ---------- the ONGOING scheme through the real configuration ----------
from test_e2_human_cards import ONGOING_SPOTS, rig, with_rig  # noqa: E402,F401
from test_d3_table_effects import bot_turn, human_hand  # noqa: E402

FOF = ("liz-sherman", "hellboy", "Fight Or Flight", "Evade", "Fireball", "Rekindle", "Pyrotechnics")


def place_ongoing(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur", "Service Pistol")
    fof = next(c for c in game.players[0].hand if c.title == "Fight Or Flight")
    bot_turn(session, table, [Act("frenzy", card=fof)])
    return table


@with_rig(*FOF, **ONGOING_SPOTS)
def test_the_bots_ongoing_scheme_placed_face_up_is_zoomed_by_default_config(rig):
    assert rig[0].cfg.card_zoom is True
    table = place_ongoing(rig)
    placed = [s for s in table.scripts if s.startswith("-- sparring:place_card_face_up")]
    assert len(placed) == 1 and "sparringZoom(o)" in placed[0] and "spawnObjectData" in placed[0]


@with_rig(*FOF, card_zoom=False, **ONGOING_SPOTS)
def test_the_ongoing_is_not_zoomed_when_the_config_turns_it_off(rig):
    table = place_ongoing(rig)
    placed = [s for s in table.scripts if s.startswith("-- sparring:place_card_face_up")]
    assert len(placed) == 1 and "sparringZoom" not in placed[0]


def test_the_real_config_documents_and_validates_the_zoom_keys(tmp_path):
    from test_multihero_bridge import REAL_CONFIG, config_for
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    assert raw["card_zoom"] is True and raw["card_zoom_seconds"] == 6.0 and raw["card_zoom_scale"] == 4.0
    assert any(n.startswith("card_zoom:") for n in raw["_notes"])
    scfg = config_for(tmp_path).session_config()
    assert (scfg.card_zoom, scfg.card_zoom_spot, scfg.card_zoom_rot) == (True, (0.0, 12.0, 0.0), None)
    from sparring.session import zoom_spec
    assert zoom_spec(scfg).rot == (0.0, scfg.bot_discard_rot_y, 0.0)
    from sparring.play import ConfigError
    for over in ({"card_zoom_seconds": 0}, {"card_zoom_scale": 50}, {"card_zoom_spot": [1, 2]}):
        with pytest.raises(ConfigError):
            config_for(tmp_path, **over).session_config()


# ---------- review round: odd deck keys, the Deck path, clean-up, more triggers ----------
def test_a_card_whose_deck_key_is_not_its_id_div_100_is_still_zoomed(rt):
    rt.execute('mkobj({guid = "c1", type = "Card", cid = 150, owner = "x", deck_key = "7", pos = Vector(5, 1, 5)})')
    rt.execute(lua.flip_card("c1", 0, True, X_IDS, identity=X_IDENT, zoom=ZOOM))
    assert len(zoomed(rt)) == 1
    assert rt.eval('(function() for _, o in ipairs(getObjects()) do if o.name == "SparringZoom" then '
                   'local d = o.getData() return d.CardID, (next(d.CustomDeck)) end end end)()') == (99950, "999")


def test_a_card_taken_out_of_a_deck_is_zoomed_with_an_odd_key_too(rt):
    scope = lua.Scope(("Blue",), ("ZN",), ((0.0, 0.0),))
    rt.execute('mkobj({guid = "ZN", type = "Zone", cx = 0, cz = 0, hw = 5, hd = 5})')
    rt.execute('mkobj({guid = "D1", type = "Deck", pos = Vector(0, 1, 0), cards = {'
               '{cid = 150, guid = "k1", owner = "x", deck_key = "7"}, {cid = 151, guid = "k2", owner = "x"}}})')
    script = lua.discard_cards([150], [(1.0, 2.0, 3.0)], 90, identity=X_IDENT, scope=scope, id_range=X_IDS,
                               zoom=ZOOM, zoom_id=150)
    assert json.loads(rt.execute(script))["moved"] == [150]
    assert len(zoomed(rt)) == 1
    assert rt.eval('(function() for _, o in ipairs(getObjects()) do if o.name == "SparringZoom" then return o.cid end end end)()') == 99950


def test_start_and_exit_clean_remove_a_leftover_copy_but_a_plain_redraw_does_not(rt):
    card(rt)
    rt.execute(lua.flip_card("c1", 0, True, X_IDS, identity=X_IDENT, zoom=ZOOM))
    rt.execute('mkobj({guid = "mine", type = "Card", cid = 160, name = "SparringZoom", gm = "someone else"})')
    rt.execute(lua.clear_markings())
    assert len(zoomed(rt)) == 2
    rt.execute(lua.clear_markings(remove_panel=True))
    left = zoomed(rt)
    assert len(left) == 1 and rt.eval('getObjectFromGUID("mine") ~= nil'), "only ours (name + marker) goes"


def test_read_face_down_cards_skips_the_copy(rt):
    card(rt)
    rt.execute(lua.flip_card("c1", 0, True, X_IDS, identity=X_IDENT,
                             zoom=lua.ZoomSpec((5.0, 12.0, 5.0), (0.0, 0.0, 0.0), 4.0, 6.0)))
    rt.execute('for _, o in ipairs(getObjects()) do o.is_face_down = true end')
    assert [c["guid"] for c in json.loads(rt.execute(lua.read_face_down_cards(5.0, 5.0)))] == ["c1"]


def test_a_glance_is_zoomed_when_it_goes_to_the_discard(brig):
    session, table, game, fake = brig
    session.cfg.card_zoom = True
    from test_session import card as card_of, set_bot_hand
    set_bot_hand(table, game, "A Momentary Glance", "Dash")
    session.read_bot_hand()
    glance = card_of(game, 0, "A Momentary Glance")
    acts = iter([Act("glance", fid="medusa", target="hellboy", card=glance)])
    session.ai.plan = lambda g: next(acts, None) or Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert any("if id == zoomId then sparringZoom(o) end" in x for x in zoom_scripts(table))


def test_a_frenzy_is_zoomed_when_it_goes_to_the_discard(brig):
    session, table, game, fake = brig
    session.cfg.card_zoom = True
    from test_session import card as card_of, set_bot_hand
    set_bot_hand(table, game, "Winged Frenzy", "Dash")
    session.read_bot_hand()
    frenzy = card_of(game, 0, "Winged Frenzy")
    acts = iter([Act("frenzy", card=frenzy, moves={}, spot=2)])
    session.ai.plan = lambda g: next(acts, None) or Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert any("if id == zoomId then sparringZoom(o) end" in x for x in zoom_scripts(table))


def test_the_humans_cards_and_face_down_cards_are_never_zoomed(brig):
    session, table, game, fake = brig
    session.cfg.card_zoom = True
    attack_and_reveal(session, table, game)
    flips = [x for x in table.scripts if x.startswith("-- sparring:flip_card")]
    human_flips = [x for x in flips if 'getObjectFromGUID("hcard")' in x]
    assert human_flips and not any("sparringZoom" in x for x in human_flips)
    assert not any("sparringZoom" in x for x in table.scripts if x.startswith("-- sparring:play_card_face_down"))
    hide = lua.flip_card("g1", 0, False, X_IDS, identity=X_IDENT, zoom=ZOOM)
    assert "sparringZoom" not in hide


def test_a_second_game_over_after_undo_shows_the_dialog_again(brig):
    session, table, game, fake = brig
    click(session, table, Event.REMOVE, {"fighter": "medusa"})
    assert len(dialogs(table)) == 1
    click(session, table, Event.UNDO_GAME_OVER)
    assert game.winner is None
    click(session, table, Event.REMOVE, {"fighter": "medusa"})
    assert game.winner == 1 and len(dialogs(table)) == 2


def test_a_combat_card_already_flipped_is_not_zoomed_again_on_the_discard(brig):
    session, table, game, fake = brig
    session.cfg.card_zoom = True
    attack_and_reveal(session, table, game)
    shown = [x for x in table.scripts if re.search(r"^sparringZoom\(c\)", x, re.M) or re.search(r"local zoomId = \d+", x)]
    assert len(shown) <= 1, "one combat card, one zoom: flipped or discarded, never both"
