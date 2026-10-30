"""Revision 5: arranque, guardado, miniaturas con varios GUID, rejilla del descarte, repartos tardios,
puntos de control del turno del bot y salidas de los estados pendientes."""
from conftest import t_discard_cards, t_play_card_face_down, t_return_hand_to_deck, t_shuffle_deck
import dataclasses
import json
import math
import re
import threading
import time

import pytest

from conftest import assert_dir_untouched, snapshot_dir, place
from sparring import persist, play
from sparring.ai_medusa import Act, MedusaAI
from sparring.session import Session, SessionError
from sparring.spaces import describe, zone_text
from sparring.state import ANUNG, DETECTIVE, Game
from sparring.tts import lua
from sparring.tts.client import TTSClient
from sparring.tts.ui import Event
import test_session
from test_play import REAL_CONFIG, cfg_file, live, free_port  # noqa: F401
from test_session import NICK, PIECES, card, human_plays, ids, rig  # noqa: F401

LIVE_START = {"medusa": 30, "harpy1": 19, "harpy2": 18, "harpy3": 29, "hellboy": 3, "lobster": 0}


def fresh(session, cfg=None):
    g = Game.new(session.game.board, seed=99, controllers={})
    return Session(g, session.client, MedusaAI(0), cfg or session.cfg)


def attack_plan(session, monkeypatch, fid="medusa", target="hellboy", title="Snipe"):
    c = card(session.game, 0, title)
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("attack", fid=fid, target=target, card=c))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    return c


# ---------- 1. casillas de salida ----------
def test_start_spaces_come_from_the_config_when_given(rig):
    session, table, game = rig
    cfg = dataclasses.replace(session.cfg, start_spaces={"medusa": 30, "hellboy": 3})
    assert fresh(session, cfg).game.start_spaces == {0: 30, 1: 3}


def test_start_derives_the_start_spaces_from_the_table_when_not_configured(rig):
    session, table, game = rig
    table.positions = {NICK[f]: s for f, s in LIVE_START.items()}
    out = session.start()
    assert game.start_spaces == {0: 30, 1: 3}
    assert not any("salida rival" in m for m in out)          # Hellboy esta en SU salida, no en la rival


def test_detective_draw_is_announced_on_the_real_rival_start_space(rig):
    session, table, game = rig
    cfg = dataclasses.replace(session.cfg, start_spaces={"medusa": 30, "hellboy": 3})
    s = fresh(session, cfg)
    s.game.turn = 1
    s.game.fighters["hellboy"].pos = 30
    s.game.begin_turn()                                       # the engine asks on the panel; the session announces it
    s.messages = []
    s._announce_human_start()
    assert any("salida rival" in m for m in s.messages) and s.effect_run is not None


def test_revive_suggests_the_configured_start_space_of_the_side(rig):
    session, table, game = rig
    cfg = dataclasses.replace(session.cfg, start_spaces={"medusa": 30, "hellboy": 3})
    s = fresh(session, cfg)
    s.game.fighters["hellboy"].alive = False
    s.game.fighters["hellboy"].pos = None
    table.positions.pop("Hellboy")
    s.messages = []
    s._revive(s.game.fighters["hellboy"], force=True)
    assert any(zone_text(s.game, 3) in m for m in s.messages)


def test_real_config_leaves_the_start_spaces_to_the_first_player_rule():
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    assert "start_spaces" not in raw and raw["setup"] is True and raw["mulligan_bot"] is True and raw["mulligan_human"] is True
    scfg = play.load_config(REAL_CONFIG).session_config()
    assert scfg.start_spaces == {} and scfg.setup and scfg.mulligan_bot and scfg.mulligan_human


# ---------- 2. el guardado real no se toca; huella ----------
def test_guard_detects_a_write_under_a_watched_directory(tmp_path):
    before = snapshot_dir(tmp_path)
    assert_dir_untouched(tmp_path, before)
    (tmp_path / "sesion.json").write_text("{}", encoding="utf-8")
    with pytest.raises(AssertionError, match="sesion.json"):
        assert_dir_untouched(tmp_path, before)


def test_default_state_of_main_is_redirected_to_tmp_in_tests(tmp_path):
    assert str(play.DEFAULT_STATE).startswith(str(tmp_path))
    assert play.parse_args([]).state == str(play.DEFAULT_STATE)


def test_the_save_carries_a_fingerprint(rig):
    session, table, game = rig
    fp = session.to_dict()["fingerprint"]
    assert re.fullmatch(r"[0-9a-f]{32}", fp["game_id"]) and re.fullmatch(r"[0-9a-f]{64}", fp["config_hash"])
    assert set(PIECES.values()) <= set(fp["guids"]) and "DECK1" in fp["guids"]


def test_game_id_survives_a_save_and_load(rig, tmp_path):
    session, table, game = rig
    session.state_path = tmp_path / "s.json"
    session.handle(Event.VALUE, {"value": 1})
    other = fresh(session)
    other.load_dict(persist.load(session.state_path))
    assert other.game_id == session.game_id


def test_resume_refuses_a_save_made_with_another_configuration(rig, tmp_path):
    session, table, game = rig
    session.state_path = tmp_path / "s.json"
    session.handle(Event.VALUE, {"value": 1})
    other_cfg = dataclasses.replace(session.cfg, bot_deck_guid="OTHERDECK")
    with pytest.raises(persist.StateError, match="otra configuracion"):
        fresh(session, other_cfg).load_dict(persist.load(session.state_path))


def test_resume_names_the_guids_that_differ(rig, tmp_path):
    session, table, game = rig
    session.state_path = tmp_path / "s.json"
    session.handle(Event.VALUE, {"value": 1})
    other_cfg = dataclasses.replace(session.cfg, pieces={**PIECES, "medusa": "otraMedusa"})
    with pytest.raises(persist.StateError, match="otraMedusa"):
        fresh(session, other_cfg).load_dict(persist.load(session.state_path))


def test_resume_refuses_a_save_without_fingerprint(rig):
    session, table, game = rig
    d = json.loads(json.dumps(session.to_dict()))
    del d["fingerprint"]
    with pytest.raises(persist.StateError, match="huella"):
        fresh(session).load_dict(d)


def test_tuning_knobs_do_not_invalidate_a_save(rig):
    session, table, game = rig
    d = json.loads(json.dumps(session.to_dict()))
    fresh(session, dataclasses.replace(session.cfg, off_board_dist=9.0, settle_tries=9)).load_dict(d)


def test_main_resume_with_a_foreign_save_is_refused_with_a_message(live, cfg_file, tmp_path, capsys):
    table, fake, ports = live
    state = tmp_path / "foreign.json"
    foreign = {"version": persist.VERSION, "game": {},
               "fingerprint": {"game_id": "a" * 32, "config_hash": "0" * 64, "guids": ["zzz"]}}
    state.write_text(json.dumps(foreign), encoding="utf-8")
    assert play.main(["--config", str(cfg_file()), "--resume", "--state", str(state), *ports]) == 2
    assert "otra configuracion" in capsys.readouterr().err
    assert table.count("create_panel") == 0


# ---------- 3. miniatura con varios GUID ----------
@pytest.fixture
def two_guid_rig(rig, monkeypatch):
    session, table, game = rig
    monkeypatch.setitem(test_session.GUID_NAME, "pcheb2", "Hellboy")
    session.cfg = dataclasses.replace(session.cfg, pieces={**PIECES, "hellboy": ["pchellboy", "pcheb2"]})
    return session, table, game


@pytest.mark.skipif(bool(__import__("os").environ.get("SPARRING_BATCH")), reason="inspecciona scripts sueltos: en modo rapido salen dentro de un compuesto (ver test_batch.py)")
def test_sync_resolves_whichever_guid_of_a_multi_state_piece_exists(two_guid_rig):
    session, table, game = two_guid_rig
    table.missing_pieces = {"pchellboy"}                   # el humano le dio la vuelta: el GUID viejo ya no existe
    table.positions["Hellboy"] = 7
    out = session.handle(Event.END_ACTION)
    assert game.fighters["hellboy"].pos == 7
    assert not any("No encuentro" in m for m in out)


def test_sync_warns_only_when_none_of_the_guids_exists(two_guid_rig):
    session, table, game = two_guid_rig
    table.missing_pieces = {"pchellboy", "pcheb2"}
    out = session.handle(Event.END_ACTION)
    assert any("No encuentro la pieza de Hellboy" in m for m in out)


def test_move_piece_tries_each_guid_until_one_exists(rig, monkeypatch):
    session, table, game = rig
    monkeypatch.setitem(test_session.GUID_NAME, "pcmed2", "Medusa")
    session.cfg = dataclasses.replace(session.cfg, pieces={**PIECES, "medusa": ["pcmedusa", "pcmed2"]})
    table.missing_pieces = {"pcmedusa"}
    game.fighters["medusa"].pos = 5
    session._project({"medusa": (0, True)})
    assert table.moves == [("Medusa", 5)]


def test_reload_check_needs_one_guid_of_each_multi_state_piece(two_guid_rig):
    session, table, game = two_guid_rig
    targets = [f.fid for f in game.own(0)]
    table.missing_guids = {"pchellboy"}
    assert play.recover_after_reload(session, session.client, targets, (0, 1, -14))[0] == "ok"
    table.missing_guids = {"pchellboy", "pcheb2"}
    status, msgs = play.recover_after_reload(session, session.client, targets, (0, 1, -14))
    assert status == "stop" and "pchellboy" in msgs[0] and "pcheb2" in msgs[0]


def test_real_config_lists_both_hellboy_states_and_builds():
    raw = play.load_config(REAL_CONFIG).raw          # las piezas de cada heroe salen de data/tts/<slug>.json
    assert raw["pieces"]["hellboy"] == ["f9789a", "e6f06e"]
    assert play.load_config(REAL_CONFIG).session_config().pieces["hellboy"] == ["f9789a", "e6f06e"]


@pytest.mark.parametrize("bad", [[], ["ok", 5], 7, ['x"); --']])
def test_config_rejects_a_piece_entry_that_is_not_a_guid_or_a_list_of_guids(cfg_file, bad):
    with pytest.raises(play.ConfigError):
        play.load_config(cfg_file(pieces={**PIECES, "hellboy": bad})).session_config()


def test_read_only_report_lists_every_guid_of_a_multi_state_piece(live, cfg_file, capsys, monkeypatch):
    table, fake, ports = live
    monkeypatch.setitem(test_session.GUID_NAME, "pcheb2", "Hellboy")
    table.missing_pieces = {"pchellboy"}
    assert play.main(["--config", str(cfg_file(pieces={**PIECES, "hellboy": ["pchellboy", "pcheb2"]})),
                      "--read-only", *ports]) == 0
    out = capsys.readouterr().out
    assert "hellboy" in out and "pcheb2" in out
    assert not any("miniatura hellboy" in line and "NO existe" in line for line in out.splitlines())


def test_hellboy_is_anung_un_rama_exactly_from_six_destiny_cards(rig):
    session, table, game = rig
    destiny = [c for c in game.players[1].full_set if c.destiny]
    game.players[1].discard[:] = destiny[:5]
    assert game.form(1) == DETECTIVE
    game.players[1].discard[:] = destiny[:6]
    assert game.form(1) == ANUNG


# ---------- 4. rejilla del descarte ----------
ZONE = (14.97, 0.74, 35.43, 8.55, 269.1)      # centro x, z, tamano x, z y rotY de la zona 906a7a (live.json)


def inside(zone, x, z):
    cx, cz, sx, sz, rot = zone
    t = math.radians(rot)
    dx, dz = x - cx, z - cz
    lx, lz = dx * math.cos(t) - dz * math.sin(t), dx * math.sin(t) + dz * math.cos(t)
    return abs(lx) <= sx / 2 + 1e-9 and abs(lz) <= sz / 2 + 1e-9


def real_grid_session(session):
    cfg = dataclasses.replace(session.cfg, bot_discard_spot=(15.0, 2.0, -14.0), bot_deck_spot=(11.5, 12.0),
                              bot_discard_bounds=ZONE)
    return fresh(session, cfg)


def test_every_discard_slot_is_inside_the_zone_even_far_past_the_grid(rig):
    session, table, game = rig
    s = real_grid_session(session)
    spots = [s._discard_slot(k) for k in range(120)]
    assert all(inside(ZONE, x, z) for x, _, z in spots)
    assert 20 <= len({(x, z) for x, _, z in spots}) < 40


def test_a_full_grid_wraps_and_stacks_onto_the_first_slots_in_order(rig):
    session, table, game = rig
    s = real_grid_session(session)
    n = len({(x, z) for x, _, z in (s._discard_slot(k) for k in range(120))})
    first, lap = s._discard_slot(0), s._discard_slot(n)
    assert (lap[0], lap[2]) == (first[0], first[2]) and lap[1] > first[1]       # misma casilla, mas arriba
    assert s._discard_slot(n + 1)[::2] == s._discard_slot(1)[::2]


def test_thirty_discards_end_up_inside_the_zone(rig):
    session, table, game = rig
    s = real_grid_session(session)
    st = s.game.players[0]
    table.bot_hand = [c.card_id for c in st.full_set]
    table.bot_deck = []
    st.hand[:] = []
    st.deck[:] = []
    st.discard[:] = list(st.full_set)
    s._reconcile_bot()
    assert len(table.discard_spots) == 30
    assert all(inside(ZONE, x, z) for x, _, z in table.discard_spots.values())


def test_config_with_no_slot_inside_the_zone_is_refused(rig):
    session, table, game = rig
    cfg = dataclasses.replace(session.cfg, bot_discard_bounds=(100.0, 100.0, 4.0, 4.0, 0.0))
    with pytest.raises(SessionError, match="descarte"):
        fresh(session, cfg).start()


def test_real_config_has_the_zone_bounds_and_they_hold_the_grid():
    scfg = play.load_config(REAL_CONFIG).session_config()
    assert scfg.bot_discard_bounds is not None
    s = Session.__new__(Session)
    s.cfg = scfg
    assert all(inside(scfg.bot_discard_bounds, x, z) for x, _, z in (s._discard_slot(k) for k in range(100)))


# ---------- 5. repartos y jugadas con respuesta tardia ----------
def flaky_after_execution(session, monkeypatch, tag):
    real, state = session.client.call_lua, {"once": True}

    def flaky(script, *a, **k):
        out = real(script, *a, **k)
        if script.startswith(f"-- sparring:{tag}") and state["once"]:
            state["once"] = False
            raise TimeoutError("TTS no devolvio valor")      # TTS lo ejecuto; la respuesta llego tarde
        return out
    monkeypatch.setattr(session.client, "call_lua", flaky)


def test_a_late_deal_reply_is_not_dealt_twice(rig, monkeypatch):
    session, table, game = rig
    flaky_after_execution(session, monkeypatch, "deal_cards")
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.actions_left = 0
    hand0 = len(table.bot_hand)
    for _ in range(5):
        session.handle(Event.END_ACTION)
    assert game.turn == 1 and len(table.bot_hand) == hand0 + 2
    assert len(table.bot_hand) == len(game.players[0].hand) and game.drawn[0] == 0
    assert sum(table.deal_calls) == 2


@pytest.mark.skipif(bool(__import__("os").environ.get("SPARRING_BATCH")), reason="inspecciona scripts sueltos: en modo rapido salen dentro de un compuesto (ver test_batch.py)")
def test_a_late_face_down_play_is_recovered_as_played_not_replayed(rig, monkeypatch):
    session, table, game = rig
    flaky_after_execution(session, monkeypatch, "play_card_face_down")
    snipe = attack_plan(session, monkeypatch)
    place(game, medusa=0, hellboy=1)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    game.turn, game.actions_left, session.bot_stage = 0, 2, None
    session.handle(Event.END_ACTION)
    assert session.pending is None and table.bot_play == [snipe.card_id]
    out = session.handle(Event.END_ACTION)
    assert session.pending and session.pending.kind == "bot_attacks"
    assert session.pending.bot_card.card_id == snipe.card_id and session.pending.bot_card_guid == f"g{snipe.card_id}"
    assert table.bot_play == [snipe.card_id], "no se juega una segunda carta"
    assert any("Revelar" in m for m in out)


@pytest.mark.skipif(bool(__import__("os").environ.get("SPARRING_BATCH")), reason="inspecciona scripts sueltos: en modo rapido salen dentro de un compuesto (ver test_batch.py)")
def test_a_late_face_down_play_for_a_human_attack_is_recovered_too(rig, monkeypatch):
    session, table, game = rig
    flaky_after_execution(session, monkeypatch, "play_card_face_down")
    place(game, hellboy=1, medusa=0)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    table.human_hand = ids(game, 1, "Service Pistol")
    session.handle(Event.ATTACKER, {"attacker": "att_hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Service Pistol")
    session.handle(Event.REVEAL)
    assert session.pending is not None and not session.pending.defended and len(table.bot_play) == 1
    played = table.bot_play[0]
    out = session.handle(Event.REVEAL)
    assert session.pending is None and table.count("play_card_face_down") == 1 and played in table.bot_discard
    assert any("Combate" in m for m in out) and any(session.game.players[0].discard)


def test_a_play_that_never_reached_the_table_is_simply_replanned(rig, monkeypatch):
    session, table, game = rig
    real, state = session.client.call_lua, {"once": True}

    def drop_before(script, *a, **k):
        if script.startswith("-- sparring:play_card_face_down") and state["once"]:
            state["once"] = False
            raise TimeoutError("TTS no devolvio valor")      # y no llego a ejecutarse
        return real(script, *a, **k)
    monkeypatch.setattr(session.client, "call_lua", drop_before)
    snipe = attack_plan(session, monkeypatch)
    place(game, medusa=0, hellboy=1)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    game.turn, game.actions_left, session.bot_stage = 0, 2, None
    session.handle(Event.END_ACTION)
    session.handle(Event.END_ACTION)
    assert session.pending and table.bot_play == [snipe.card_id] and session.placing is None


# ---------- 6. puntos de control del turno del bot ----------
def crash_rig(session, table, monkeypatch, tmp_path, crash_on):
    game = session.game
    session.state_path = tmp_path / "s.json"
    game.actions_left = 0
    place(game, medusa=0, hellboy=1)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    session.handle(Event.VALUE, {"value": 0})
    calls = {"n": 0}
    real = session.ai.execute

    def boom(g, act):
        calls["n"] += 1
        if calls["n"] == crash_on:
            raise KeyboardInterrupt                      # Ctrl+C a mitad del turno del bot
        real(g, act)
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: g.fighters["hellboy"])
    monkeypatch.setattr(session.ai, "execute", boom)
    return calls


def resumed(session, monkeypatch):
    s2 = fresh(session)
    s2.state_path = session.state_path
    s2.load_dict(persist.load(session.state_path))
    monkeypatch.setattr(s2.ai, "plan", lambda g: Act("maneuver", moves={}))
    monkeypatch.setattr(s2.ai, "pick_ability_target", lambda g: g.fighters["hellboy"])
    return s2


def test_resume_after_a_crash_does_not_apply_medusas_ability_twice(rig, monkeypatch, tmp_path):
    session, table, game = rig
    crash_rig(session, table, monkeypatch, tmp_path, crash_on=1)
    hb0 = game.fighters["hellboy"].hp
    with pytest.raises(KeyboardInterrupt):
        session.handle(Event.END_ACTION)
    saved = json.loads(session.state_path.read_text(encoding="utf-8"))
    assert saved["bot_stage"] is None and saved["game"]["fighters"]["hellboy"]["hp"] == hb0 - 1
    s2 = resumed(session, monkeypatch)
    out = s2.resume()
    assert s2.game.fighters["hellboy"].hp == hb0 - 1
    assert not any("Habilidad de Medusa" in m or "Fin de tu turno" in m for m in out)
    assert s2.game.turn == 1


def test_each_bot_action_is_a_checkpoint(rig, monkeypatch, tmp_path):
    session, table, game = rig
    crash_rig(session, table, monkeypatch, tmp_path, crash_on=2)
    with pytest.raises(KeyboardInterrupt):
        session.handle(Event.END_ACTION)
    assert json.loads(session.state_path.read_text(encoding="utf-8"))["game"]["actions_left"] == 1
    s2 = resumed(session, monkeypatch)
    ran, real = [], s2.ai.execute
    monkeypatch.setattr(s2.ai, "execute", lambda g, act: (ran.append(act), real(g, act)))
    s2.resume()
    assert len(ran) == 1 and s2.game.turn == 1             # solo falta una accion; no se rehace la primera


def test_the_start_of_the_bot_turn_is_checkpointed_before_any_table_io(rig, monkeypatch, tmp_path):
    session, table, game = rig
    session.state_path = tmp_path / "s.json"
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))

    def interrupted():
        raise KeyboardInterrupt
    real = session.sync_positions
    monkeypatch.setattr(session, "sync_positions", lambda: interrupted() if game.turn == 0 else real())
    game.actions_left = 0
    with pytest.raises(KeyboardInterrupt):
        session.handle(Event.END_ACTION)
    saved = json.loads(session.state_path.read_text(encoding="utf-8"))
    assert saved["game"]["turn"] == 0 and saved["bot_stage"] == "start"


# ---------- 7. salidas con un combate pendiente cuyo luchador desaparece ----------
def bot_attack_on(session, table, game, monkeypatch, target):
    place(game, medusa=0, hellboy=1, lobster=2)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    c = attack_plan(session, monkeypatch, target=target)
    game.turn, game.actions_left, session.bot_stage = 0, 2, None
    session._bot_continue()
    assert session.pending and session.pending.target.fid == target
    return c


def test_removing_the_target_of_a_pending_bot_attack_cancels_it_and_returns_the_card(rig, monkeypatch):
    session, table, game = rig
    snipe = bot_attack_on(session, table, game, monkeypatch, "lobster")
    out = session.handle(Event.REMOVE, {"fighter": "lobster"})
    assert session.pending is None and snipe.card_id in table.bot_hand and game.actions_left == 2
    assert any("cancelado" in m.lower() for m in out)


def test_the_frozen_path_of_review_5_p3_now_exits(rig, monkeypatch):
    session, table, game = rig
    bot_attack_on(session, table, game, monkeypatch, "lobster")
    session.handle(Event.REMOVE, {"fighter": "lobster"})
    del table.positions["Lobster Johnson"]
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
    session.handle(Event.END_ACTION)
    assert session.pending is None and game.turn == 1


def test_reveal_with_a_dead_target_drops_the_combat_instead_of_freezing(rig, monkeypatch):
    session, table, game = rig
    snipe = bot_attack_on(session, table, game, monkeypatch, "lobster")
    game.fighters["lobster"].alive = False                      # murio por algo que el bot no vio
    out = session.handle(Event.REVEAL)
    assert session.pending is None and snipe.card_id in table.bot_hand
    assert not any("ilegal" in m.lower() for m in out)


def test_cancel_works_on_a_bot_attack_whose_fighter_is_gone(rig, monkeypatch):
    session, table, game = rig
    bot_attack_on(session, table, game, monkeypatch, "lobster")
    game.fighters["lobster"].alive = False
    session.handle(Event.CANCEL)
    assert session.pending is None


def test_end_action_with_a_dead_target_gets_out_and_the_bot_goes_on(rig, monkeypatch):
    session, table, game = rig
    bot_attack_on(session, table, game, monkeypatch, "lobster")
    game.fighters["lobster"].alive = False
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
    session.handle(Event.END_ACTION)
    assert session.pending is None and game.turn == 1


def test_a_human_attack_whose_attacker_is_retired_is_cancelled_without_spending_the_action(rig):
    session, table, game = rig
    place(game, lobster=1, medusa=0, hellboy=30)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    table.human_hand = ids(game, 1, "Second Shot")
    session.handle(Event.ATTACKER, {"attacker": "att_lobster"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    assert session.pending
    session.handle(Event.REMOVE, {"fighter": "lobster"})
    assert session.pending is None and game.actions_left == 2


def test_a_pending_combat_between_living_fighters_is_untouched_by_an_hp_change(rig, monkeypatch):
    session, table, game = rig
    bot_attack_on(session, table, game, monkeypatch, "lobster")
    session.handle(Event.HP, {"fighter": "lobster", "delta": -1})
    assert session.pending is not None


# ---------- 8. manos iniciales ----------
def test_start_with_both_hands_empty_deals_the_bot_five_and_tells_the_human_to_draw(rig):
    session, table, game = rig
    table.bot_deck = [c.card_id for c in game.players[0].full_set]
    table.bot_hand, table.human_count = [], 0
    out = session.start()
    assert len(table.bot_hand) == 5 and table.deal_calls == [5] and len(game.players[0].hand) == 5
    assert any("Roba tus 5 cartas" in m for m in out)


def test_start_with_hands_already_dealt_does_not_deal(rig):
    session, table, game = rig
    table.human_count = 5
    out = session.start()
    assert table.deal_calls == [] and not any("Roba tus 5" in m for m in out)


def test_start_deals_the_bot_even_when_the_human_already_drew(rig):
    session, table, game = rig
    table.bot_deck = [c.card_id for c in game.players[0].full_set]
    table.bot_hand, table.human_count = [], 5
    out = session.start()
    assert len(table.bot_hand) == 5 and not any("Roba tus 5" in m for m in out)


# ---------- 9. doble clic ----------
def test_double_click_on_maneuver_spends_one_action(rig):
    session, table, game = rig
    session.handle(Event.MANEUVER)
    out = session.handle(Event.MANEUVER)
    assert game.actions_left == 1 and any("abierta" in m for m in out)
    session.handle(Event.END_ACTION)
    session.handle(Event.MANEUVER)
    assert game.actions_left == 0


def test_double_click_on_scheme_spends_one_action(rig):
    session, table, game = rig
    session.handle(Event.SCHEME)
    session.handle(Event.SCHEME)
    assert game.actions_left == 1


# ---------- 10. respuestas tardias ----------
def test_poll_events_drops_late_sparring_replies_silently():
    c = TTSClient(send_port=free_port(), listen_port=0)
    c.start_listening()
    try:
        c.listener.messages.put({"messageID": 4, "customMessage": {"sparring_reply": 123.0, "value": "[]"}})
        c.listener.messages.put({"messageID": 4, "customMessage": {"event": "maneuver"}})
        assert c.poll_events() == [{"event": "maneuver"}]
        assert c.stale_replies == 1
    finally:
        c.close()


def test_a_late_reply_never_reaches_the_loop_as_an_unknown_event(rig):
    session, table, game = rig
    session.client.listener.messages.put({"messageID": 4, "customMessage": {"sparring_reply": 5.0, "err": "x"}})
    said, stop = [], threading.Event()
    threading.Timer(0.2, stop.set).start()
    play.run_loop(session, session.client, stop, said.extend, poll=0.01)
    assert said == []


# ---------- 11. limpieza de objetos propios ----------
def test_clear_markings_can_remove_the_panel_and_only_ours():
    s = lua.clear_markings(remove_panel=True)
    assert lua.is_sendable(s)
    assert f'o.getGMNotes() == "{lua.MARKER}"' in s and 'o.getName() == "SparringPanel"' in s
    assert s.index("setName") < s.index("destruct"), "se renombra antes de destruir para que nadie lo reencuentre"
    assert "Global" not in s
    assert "destruct" not in lua.clear_markings().split("elseif")[0]      # por defecto el panel no se destruye


@pytest.mark.parametrize("remove_panel", [False, True])
def test_cleanup_only_destroys_what_carries_our_marker(remove_panel):
    script = lua.clear_markings(remove_panel=remove_panel)
    assert f'getGMNotes() == "{lua.MARKER}"' in script
    assert script.count("destruct()") <= script.count("ours and")


def test_panel_and_labels_carry_the_marker_and_are_found_only_with_it():
    for s in (lua.create_panel(["medusa"]), lua.draw_markings([("A", "abc")], [("B", 0, 0)])):
        assert f'setGMNotes("{lua.MARKER}")' in s
        assert f'getGMNotes() == "{lua.MARKER}"' in s
    s = lua.create_panel(["medusa"])
    assert 'if o.getName() == "SparringPanel" and o.getGMNotes() == "sparring" then' in s


@pytest.mark.parametrize("bad", ["si", 1, None])
def test_clear_markings_rejects_a_non_boolean_flag(bad):
    with pytest.raises(TypeError):
        lua.clear_markings(remove_panel=bad)


def test_play_cleans_leftovers_before_creating_the_panel_and_removes_everything_on_exit(live, cfg_file, tmp_path):
    table, fake, ports = live
    stop = threading.Event()
    t = threading.Thread(target=lambda: play.main(["--config", str(cfg_file()), "--poll", "0.02", "--first", "human", *ports, "--state",
                                                   str(tmp_path / "s.json")], stop=stop))
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline and not table.markings:
        time.sleep(0.02)
    stop.set()
    t.join(5)
    tags = [re.match(r"-- sparring:(\w+)", s).group(1) for s in table.scripts]
    assert tags.index("clear_markings") < tags.index("create_panel")
    assert tags[-1] == "clear_markings" and tags.count("clear_markings") == 2
    assert 'o.getName() == "SparringPanel"' in table.scripts[-1] and "destruct" in table.scripts[-1]


# ---------- 12. posicion del panel ----------
def test_panel_default_position_is_above_the_mats(tmp_path):
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    assert raw["panel_position"] == [-12.5, 1.8, -24.5]  # a la derecha del descarte del humano
    raw.pop("panel_position")
    p = tmp_path / "c.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    assert play.load_config(p).panel_position == (2.0, 1.8, -24.0)
    assert "{2.0, 1.8, -24.0}" in lua.create_panel(["medusa"])


# ---------- 13. mutantes M5 y M9 ----------
def test_read_discard_skips_the_draw_decks_by_guid():
    s = lua.read_discard("ZONE1", ["DECKA", "DECKB"], [(1.0, 2.0)], 1.5)
    assert '["DECKA"]=true' in s and '["DECKB"]=true' in s
    assert "if not skip[o.getGUID()] and not near then" in s


def test_the_floor_labels_are_locked_so_nobody_drags_them():
    s = lua.draw_markings([("A", "abc")], [("B", 0, 0)])
    callback = re.search(r"callback_function = function\(o\)(.*?)end\}\)", s, re.DOTALL).group(1)
    assert "o.setLock(true)" in callback and "setText(o, r.label)" in callback


# ---------- prueba en vivo: panel legible y etiquetas que no revientan ----------
def test_panel_xml_is_rotated_scaled_and_its_texts_are_white():
    from sparring.tts import ui
    x = ui.panel_xml(["medusa"])
    assert 'rotation="0 0 270"' in x and 'scale="6 6 6"' in x
    import re
    texts = re.findall(r"<Text [^>]*>", x)
    assert len(texts) >= 1 + 3 + 3 and all('color="#FFFFFF"' in t for t in texts)   # secciones, estado y filas de PV
    assert all('textColor="#FFFFFF"' in b for b in re.findall(r"<Button [^>]*>", x))
    custom = ui.panel_xml(["medusa"], rotation=(0, 0, 90), scale=(2.5, 2.5, 2.5))
    assert 'rotation="0 0 90"' in custom and 'scale="2.5 2.5 2.5"' in custom


@pytest.mark.parametrize("kw", [{"rotation": "0 0 1\" onClick=\"x"}, {"scale": (1, 1)}, {"scale": (1, 1, True)},
                                {"rotation": (0, 0, "9")}, {"scale": (1, 1, float("inf"))}])
def test_panel_rotation_and_scale_reject_injection_and_bad_shapes(kw):
    from sparring.tts import ui
    with pytest.raises((TypeError, ValueError)):
        ui.panel_xml(["medusa"], **kw)
    with pytest.raises((TypeError, ValueError)):
        lua.create_panel(["medusa"], **kw)


def test_create_panel_carries_the_orientation_and_play_reads_it_from_the_config(tmp_path):
    assert 'rotation="0 0 270" scale="6 6 6"' in lua.create_panel(["medusa"])
    assert 'rotation="0 0 90"' in lua.create_panel(["medusa"], rotation=(0, 0, 90))
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    p = tmp_path / "c.json"
    p.write_text(json.dumps({**raw, "panel_rotation": [0, 0, 90], "panel_scale": [3, 3, 3]}), encoding="utf-8")
    cfg = play.load_config(p)
    assert cfg.panel_rotation == (0.0, 0.0, 90.0) and cfg.panel_scale == (3.0, 3.0, 3.0)
    default = play.load_config(REAL_CONFIG)
    assert default.panel_rotation == (0.0, 0.0, 270.0) and default.panel_scale == (4.5, 4.5, 4.5)


def test_floor_labels_never_call_the_text_api_unprotected():
    """En vivo, draw_markings reventaba con 'attempt to call a nil value' al poner el texto: toda llamada a la
    API del 3DText va en pcall, con setValue del objeto como alternativa, y nombre, marca y bloqueo van antes."""
    s = lua.draw_markings([("A", "abc")], [("B", 0, 0)])
    helper = re.search(r"local function setText\(o, text\)(.*?)^end$", s, re.DOTALL | re.MULTILINE).group(1)
    assert "pcall(function() o.TextTool.setValue(text) end)" in helper and "o.setValue(text)" in helper
    assert "pcall(function() o.TextTool.setFontSize(30.0) end)" in helper
    outside = s.replace(helper, "")
    assert "TextTool" not in outside
    callback = re.search(r"callback_function = function\(o\)(.*?)end\}\)", s, re.DOTALL).group(1)
    assert callback.index("setName") < callback.index("setGMNotes") < callback.index("setLock") < callback.index("setText")


# ---------- prueba en vivo: una mano no suelta una carta con movimiento suave ----------
def test_cards_leaving_a_hand_move_instantly_never_smoothly():
    play_s = t_play_card_face_down(17601, "Green", 6.0, 1.6, -18.0, 0.0)
    assert play_s.index("o.setRotation(") < play_s.index("o.setPosition(") and "Smooth" not in play_s
    disc = t_discard_cards([17601], [(1.0, 2.0, 3.0)], 90.0)
    card_branch = disc.split('elseif o.type == "Deck"')[0]
    assert "o.setPosition(" in card_branch and "o.setRotation(" in card_branch and "Smooth" not in card_branch


def test_a_placement_the_builder_claims_but_the_table_does_not_show_is_refused(rig, monkeypatch):
    """Live: `played = guid` volvio con la carta aun en la mano. Se verifica leyendo el punto de carta."""
    session, table, game = rig
    snipe = attack_plan(session, monkeypatch)
    place(game, medusa=0, hellboy=1)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    table.do_play_card_face_down = lambda s: {"played": f"g{snipe.card_id}"}     # miente: no mueve nada
    game.turn, game.actions_left, session.bot_stage = 0, 2, None
    out = session.handle(Event.END_ACTION)
    assert session.pending is None and session.placing is None and snipe.card_id in table.bot_hand
    assert any("no ha salido de la mano" in m for m in out)


# ---------- prueba en vivo: la carta del ataque pendiente sigue siendo del bot tras --resume ----------
def test_pending_bot_card_stays_the_bots_through_read_hand_resume_and_adoption(rig, monkeypatch, tmp_path):
    session, table, game = rig
    session.state_path = tmp_path / "s.json"
    c = bot_attack_on(session, table, game, monkeypatch, "hellboy")
    session._persist()
    assert c.card_id in table.bot_play and c.card_id not in table.bot_hand       # boca abajo en la mesa
    s2 = fresh(session)                                                          # el bot muere y se reanuda
    s2.state_path = session.state_path
    s2.load_dict(persist.load(session.state_path))
    s2.resume()
    assert s2.pending is not None and c in s2.game.players[0].hand
    s2.read_bot_hand()
    assert c in s2.game.players[0].hand and c not in s2.game.players[0].deck
    s2.adopt_table()
    assert c in s2.game.players[0].hand and c not in s2.game.players[0].discard
    out = s2.handle(Event.REVEAL)                                                # el humano no defiende
    assert s2.pending is None and not any("ilegal" in m.lower() for m in out)
    assert c in s2.game.players[0].discard and s2.game.actions_left == 1


# ---------- prueba en vivo 2: descartes instantaneos, diales automaticos, anuncio de cartas ----------
from conftest import give  # noqa: E402
from sparring.tts.client import UnsafeMessage  # noqa: E402
from test_review3 import maneuver_plan  # noqa: E402

DIALS = {"medusa": "dM", "hellboy": "dH", "lobster": "dL"}


def dial_rig(session, table):
    session.cfg = dataclasses.replace(session.cfg, dials=DIALS)
    table.dials = {g: {"found": True, "value": v, "max": v} for g, v in (("dM", 16), ("dH", 18), ("dL", 6))}


def test_discard_cards_takes_cards_out_of_decks_without_smoothing_too():
    s = t_discard_cards([17601], [(1.0, 2.0, 3.0)], 90.0)
    assert "smooth = false" in s and "smooth = true" not in s and "Smooth" not in s


def test_set_health_dials_uses_the_dials_own_script():
    s = lua.set_health_dials({"bcd809": 12, "046660": 18})
    assert lua.is_sendable(s) and s.startswith("-- sparring:set_health_dials")
    assert '["046660"]=18' in s and '["bcd809"]=12' in s
    assert 'o.getTable("CONFIG")' in s and 'o.setTable("CONFIG", cfg)' in s and 'o.call("updateVal")' in s
    assert "cfg.MIN_VALUE" in s and "cfg.MAX_VALUE" in s and "Global" not in s


@pytest.mark.parametrize("bad", [{"a b": 3}, {'x"); os.exit() --': 3}, {"abc": 1.5}, {"abc": True}, {"abc": "3"},
                                 [("abc", 3)], None])
def test_set_health_dials_rejects_bad_input(bad):
    with pytest.raises((TypeError, ValueError)):
        lua.set_health_dials(bad)


def test_set_health_dials_is_a_write_and_the_read_only_wrapper_refuses_it():
    class Boom:
        def call_lua(self, *a, **k):
            raise AssertionError("no debia llegar")
    assert "set_health_dials" not in play.READ_ONLY_TAGS
    with pytest.raises(play.ReadOnlyViolation):
        play.ReadOnlyClient(Boom()).call_lua(lua.set_health_dials({"abc": 3}))


def human_attack_reveal(session, table, game, monkeypatch, card_title="Service Pistol", defense=None):
    place(game, hellboy=1, medusa=0)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    table.human_hand = ids(game, 1, card_title)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: defense)
    session.handle(Event.ATTACKER, {"attacker": "att_hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    c = next(c for c in game.players[1].full_set if c.card_id == table.human_hand[0])
    table.face_down = [{"id": c.card_id, "guid": f"h{c.card_id}"}]
    return session.handle(Event.REVEAL)


def test_combat_damage_is_written_to_the_dials_and_read_back(rig, monkeypatch):
    session, table, game = rig
    dial_rig(session, table)
    human_attack_reveal(session, table, game, monkeypatch)
    assert game.fighters["medusa"].hp == 11
    assert table.dials["dM"]["value"] == 11 and table.dials["dH"]["value"] == 18 and table.dials["dL"]["value"] == 6
    assert ("dM", 11) in table.dial_writes


def test_a_dial_that_does_not_take_the_write_is_reported_not_fatal(rig, monkeypatch):
    session, table, game = rig
    dial_rig(session, table)
    table.dial_ignores_writes = True
    out = human_attack_reveal(session, table, game, monkeypatch)
    assert any("No pude comprobar los diales" in m and "Medusa deberia marcar 11" in m for m in out)
    assert session.moving, "el combate se resolvio igual"


def test_hp_buttons_move_the_dials_too(rig):
    session, table, game = rig
    dial_rig(session, table)
    session.handle(Event.HP, {"fighter": "hellboy", "delta": -1})
    assert table.dials["dH"]["value"] == 17
    session.handle(Event.REMOVE, {"fighter": "lobster"})
    assert table.dials["dL"]["value"] == 0


def test_a_dead_human_fighter_is_announced_and_its_dial_goes_to_zero(rig, monkeypatch):
    session, table, game = rig
    dial_rig(session, table)
    game.fighters["lobster"].hp = 1
    bot_attack_on(session, table, game, monkeypatch, "lobster")
    out = session.handle(Event.REVEAL)
    assert not game.fighters["lobster"].alive and table.dials["dL"]["value"] == 0
    assert any("Lobster Johnson (tuyo) cae" in m for m in out)


def test_the_bots_ability_and_actions_also_update_the_dials(rig, monkeypatch):
    session, table, game = rig
    dial_rig(session, table)
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: g.fighters["hellboy"])
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert table.dials["dH"]["value"] == 17


def test_the_combat_message_says_where_every_total_comes_from(rig, monkeypatch):
    session, table, game = rig
    out = human_attack_reveal(session, table, game, monkeypatch)
    assert "Combate: Hellboy ataca con Service Pistol (5): total 5. Medusa no defiende: total 0. Dano 5." in out


def test_the_combat_message_names_the_boost_and_the_defense(rig, monkeypatch):
    session, table, game = rig
    test_session.set_bot_hand(table, game, "Second Shot", "Dash")
    session.read_bot_hand()
    dash = card(game, 0, "Dash")
    monkeypatch.setattr(session.ai, "choose_combat_boost", lambda g, ctx: dash)
    place(game, medusa=0, hellboy=1, lobster=2)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    ss = card(game, 0, "Second Shot")
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("attack", fid="medusa", target="hellboy", card=ss))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.turn, game.actions_left, session.bot_stage = 0, 2, None
    session._bot_continue()
    table.human_hand = ids(game, 1, "Glimpse Of Hell")
    gl = card(game, 1, "Glimpse Of Hell")
    table.face_down = [{"id": gl.card_id, "guid": f"h{gl.card_id}"}]
    out = session.handle(Event.REVEAL)
    text = next(m for m in out if m.startswith("Combate:"))
    assert "Medusa ataca con Second Shot (3) y potencia con Dash (+1): total 4." in text
    assert "Hellboy defiende con Glimpse Of Hell (2): total 2." in text


def test_the_bot_announces_the_cards_it_discards(rig, monkeypatch):
    session, table, game = rig
    dash = card(game, 0, "Dash")
    maneuver_plan(session, monkeypatch, boost=dash)
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.actions_left = 0
    out = session.handle(Event.END_ACTION)
    assert any(m.startswith("El bot maniobra (descarta Dash por boost de maniobra)") for m in out)


# ---------- D: efectos de despues del combate que el bot aplica solo ----------
def test_horseshoes_damage_is_applied_by_the_bot_not_left_to_the_human(game):
    place(game, medusa=0, hellboy=1, harpy1=2, lobster=27)
    hb, med, harpy = game.fighters["hellboy"], game.fighters["medusa"], game.fighters["harpy1"]
    r = game.attack(hb, med, give(game, 1, "Horseshoes And Hand Grenades"), def_card=None)
    assert not harpy.alive and any("Horseshoes" in e for e in r.human_effects)      # E2: narrated to the human
    assert not any("Horseshoes" in a for a in r.applied)
    assert med.hp == 16 - 2 - 1                       # combate (2) y efecto (1) al otro luchador de la zona


def test_on_earth_heals_hellboy_when_he_loses_and_the_bot_applies_it(game):
    place(game, medusa=0, hellboy=1)
    hb = game.fighters["hellboy"]
    hb.hp = 10
    r = game.attack(game.fighters["medusa"], hb, give(game, 0, "Snipe"),
                    def_card=give(game, 1, "On Earth As It Is In Hell"))
    assert hb.hp == 10 - 3 + 2 and any("recupera 2" in e for e in r.human_effects)
    assert not any("On Earth" in a for a in r.applied)


def test_effects_that_need_a_decision_of_the_human_are_resolved_by_the_interpreter_and_narrated(game):
    """E2: the human's card is interpreted (here the Scripted controller answers; at the table, the panel)."""
    place(game, medusa=0, hellboy=1)
    r = game.attack(game.fighters["hellboy"], game.fighters["medusa"], give(game, 1, "Right Hand Of Doom"),
                    def_card=None)
    assert any(e.startswith("Right Hand Of Doom: ") for e in r.human_effects) and r.applied == []


# ---------- nombres de miniaturas y botones ----------
def test_name_pieces_builder_is_by_guid_only_and_allowlisted():
    s = lua.name_pieces({"328e52": "Harpy 1", "33c5ec": "Harpy 2"})
    assert lua.is_sendable(s) and s.startswith("-- sparring:name_pieces")
    assert '["328e52"]="Harpy 1"' in s and 'getObjectFromGUID(g)' in s and "o.setName(name)" in s
    assert "getObjects" not in s and "Global" not in s
    assert "name_pieces" not in play.READ_ONLY_TAGS


@pytest.mark.parametrize("bad", [{"a b": "x"}, {"abc": 'x"); os.exit() --'}, {"abc": 5}, {"abc": "a" * 80},
                                 {'x"]=1 --': "x"}, [("abc", "x")], None])
def test_name_pieces_rejects_bad_input(bad):
    with pytest.raises((TypeError, ValueError)):
        lua.name_pieces(bad)


def test_read_only_client_refuses_to_name_pieces():
    class Boom:
        def call_lua(self, *a, **k):
            raise AssertionError("no debia llegar")
    with pytest.raises(play.ReadOnlyViolation):
        play.ReadOnlyClient(Boom()).call_lua(lua.name_pieces({"abc": "Harpy 1"}))


def test_start_and_resume_name_every_piece_by_its_config_key(rig):
    session, table, game = rig
    session.start()
    assert table.piece_names == {PIECES[fid]: NICK[fid] for fid in NICK}
    table.piece_names.clear()
    session.resume()
    assert table.piece_names["pcharpy3"] == "Harpy 3"


def test_every_guid_of_a_multi_state_piece_gets_the_name(two_guid_rig):
    session, table, game = two_guid_rig
    session.start()
    assert table.piece_names["pchellboy"] == table.piece_names["pcheb2"] == "Hellboy"


@pytest.mark.skipif(bool(__import__("os").environ.get("SPARRING_BATCH")), reason="inspecciona scripts sueltos: en modo rapido salen dentro de un compuesto (ver test_batch.py)")
def test_a_failure_naming_the_pieces_does_not_stop_the_game(rig, monkeypatch):
    session, table, game = rig
    real = session.client.call_lua

    def flaky(script, *a, **k):
        if script.startswith("-- sparring:name_pieces"):
            raise TimeoutError("sin respuesta")
        return real(script, *a, **k)
    monkeypatch.setattr(session.client, "call_lua", flaky)
    out = session.start()
    assert any("no pude poner nombre" in m for m in out) and any("Tu turno" in m for m in out)


def test_read_only_never_names_pieces(live, cfg_file):
    table, fake, ports = live
    assert play.main(["--config", str(cfg_file()), "--read-only", *ports]) == 0
    assert table.count("name_pieces") == 0


def test_panel_buttons_use_the_readable_names():
    from sparring.tts import ui
    names = {"harpy1": "Harpy 1", "hellboy": "Hellboy"}
    x = ui.panel_xml(["medusa", "harpy1"], names=names)
    assert 'id="harpy1" onClick="onAttack">Atacar a Harpy 1<' in x
    assert 'id="att_hellboy" onClick="onAttacker">Ataca Hellboy<' in x
    assert ">Harpy 1</Text>" in x and 'id="hpm_harpy1"' in x          # los ids no cambian
    assert "Atacar a medusa" in x                                      # sin nombre, el id
    assert 'Atacar a Harpy 1' in lua.create_panel(["harpy1"], names=names)


@pytest.mark.parametrize("bad", [{"harpy1": '<x onClick="evil">'}, {"harpy1": "a" * 80}, {"harpy1": 5},
                                 {"harpy1": ""}, ["Harpy 1"]])
def test_panel_names_reject_markup_and_bad_shapes(bad):
    from sparring.tts import ui
    with pytest.raises((TypeError, ValueError)):
        ui.panel_xml(["harpy1"], names=bad)


def test_play_gives_the_panel_the_config_nicknames(live, cfg_file, tmp_path):
    table, fake, ports = live
    stop = threading.Event()
    t = threading.Thread(target=lambda: play.main(["--config", str(cfg_file()), "--poll", "0.02", "--first", "human", *ports, "--state",
                                                   str(tmp_path / "s.json")], stop=stop))
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline and table.count("create_panel") == 0:
        time.sleep(0.02)
    stop.set()
    t.join(5)
    panel = next(s for s in table.scripts if s.startswith("-- sparring:create_panel"))
    assert "Atacar a Harpy 1" in panel and "Atacar a Medusa" in panel


# ---------- dial de destinos ----------
def destiny_ids(game, n):
    return [c.card_id for c in game.players[1].full_set if c.destiny][:n]


def destiny_rig(session, table, dead_spot=(24.0, 2.5, -20.0)):
    session.cfg = dataclasses.replace(session.cfg, destiny_dial="dD", dead_spot=dead_spot)
    table.dials = {"dD": {"found": True, "value": 0, "max": 18}}


def test_only_cards_marked_destiny_count_and_there_are_eleven():
    from sparring.cards import load_hellboy_deck
    deck = load_hellboy_deck()
    assert sum(c.destiny for c in deck) == 11
    assert {c.title for c in deck if c.destiny} == {"Excalibur", "Right Hand Of Doom", "Confront Any Demon or God",
                                                    "On Earth As It Is In Hell",
                                                    "And Upon His Brow Is Set A Crown Of Flame"}


def test_the_destiny_dial_follows_the_human_discard_and_announces_changes(rig):
    session, table, game = rig
    destiny_rig(session, table)
    nondestiny = next(c.card_id for c in game.players[1].full_set if not c.destiny)
    table.human_discard = destiny_ids(game, 2) + [nondestiny]
    out = session.handle(Event.END_ACTION)
    assert table.dials["dD"]["value"] == 2 and game.destiny_count(1) == 2
    table.human_discard = destiny_ids(game, 3) + [nondestiny]
    out = session.handle(Event.END_ACTION)
    assert table.dials["dD"]["value"] == 3 and "Destinos de Hellboy: 3 (en su descarte)." in out
    out = session.handle(Event.END_ACTION)
    assert not any("Destinos de Hellboy" in m for m in out), "sin cambio no se repite"


def test_six_destinies_announce_anung_un_rama_and_the_engine_uses_the_same_count(rig):
    session, table, game = rig
    destiny_rig(session, table)
    table.human_discard = destiny_ids(game, 5)
    session.handle(Event.END_ACTION)
    assert game.form(1) == DETECTIVE
    table.human_discard = destiny_ids(game, 6)
    out = session.handle(Event.END_ACTION)
    assert game.form(1) == ANUNG and table.dials["dD"]["value"] == 6
    assert any("ANUNG UN RAMA" in m and "dale la vuelta" in m for m in out)
    table.human_discard = destiny_ids(game, 5)
    out = session.handle(Event.END_ACTION)
    assert game.form(1) == ANUNG and table.dials["dD"]["value"] == 6, "una sola lectura sin la carta no baja el contador"
    out = session.handle(Event.END_ACTION)
    assert game.form(1) == DETECTIVE and any("vuelve a OCCULT DETECTIVE" in m for m in out)
    assert table.dials["dD"]["value"] == 5


def test_a_destiny_card_played_in_combat_updates_the_dial_at_once(rig, monkeypatch):
    session, table, game = rig
    destiny_rig(session, table)
    out = human_attack_reveal(session, table, game, monkeypatch, card_title="Excalibur")
    assert table.dials["dD"]["value"] == 1 and "Destinos de Hellboy: 1 (en su descarte)." in out


def test_the_destiny_count_is_remembered_across_a_resume(rig, tmp_path):
    session, table, game = rig
    destiny_rig(session, table)
    session.state_path = tmp_path / "s.json"
    table.human_discard = destiny_ids(game, 4)
    session.handle(Event.END_ACTION)
    other = fresh(session, session.cfg)
    other.load_dict(persist.load(session.state_path))
    assert other.destiny_seen == (4, DETECTIVE)
    assert not any("Destinos de Hellboy" in m for m in other.resume())


def test_hp_dials_are_not_rewritten_just_by_reading_the_table(rig):
    session, table, game = rig
    destiny_rig(session, table)
    session.cfg = dataclasses.replace(session.cfg, dials={"medusa": "dM"})
    table.dials["dM"] = {"found": True, "value": 14, "max": 16}
    table.human_discard = destiny_ids(game, 1)
    out = session.handle(Event.END_ACTION)
    assert table.dials["dM"]["value"] == 14 and any("dial de Medusa marca 14" in m for m in out)


def test_a_destiny_dial_that_does_not_take_the_write_is_reported(rig):
    session, table, game = rig
    destiny_rig(session, table)
    table.dial_ignores_writes = True
    table.human_discard = destiny_ids(game, 2)
    out = session.handle(Event.END_ACTION)
    assert any("el dial de destinos deberia marcar 2" in m for m in out)


def test_the_real_config_has_the_destiny_dial_and_dry_builds():
    cfg = play.load_config(REAL_CONFIG)
    assert cfg.raw["destiny_dial"] == "e17c66"
    assert cfg.session_config().destiny_dial == "e17c66"


def test_read_only_report_reads_the_destiny_dial(live, cfg_file, capsys):
    table, fake, ports = live
    table.dials = {"dd1": {"found": True, "name": "Destiny Dial", "value": 0, "max": 18}}
    assert play.main(["--config", str(cfg_file(destiny_dial="dd1")), "--read-only", *ports]) == 0
    out = capsys.readouterr().out
    assert "destinos" in out and "dd1" in out and "vida 0 de 18" in out
    assert {s.split("\n")[0] for s in table.scripts} <= {f"-- sparring:{t}" for t in play.READ_ONLY_TAGS}


def test_destiny_dial_belongs_to_the_save_fingerprint_and_the_reload_check(rig, tmp_path):
    session, table, game = rig
    destiny_rig(session, table)
    assert "dD" in session.guids_in_use() and ["dD"] in session.guid_groups()
    session.state_path = tmp_path / "s.json"
    session.handle(Event.VALUE, {"value": 1})
    with pytest.raises(persist.StateError):
        fresh(session, dataclasses.replace(session.cfg, destiny_dial="otro")).load_dict(
            persist.load(session.state_path))


# ---------- caidos y alcance del dano automatico ----------
def test_place_piece_builder_is_by_guid_and_validated():
    s = lua.place_piece("328e52", 24.0, 2.5, -20.0)
    assert lua.is_sendable(s) and "getObjectFromGUID(\"328e52\")" in s and "Vector(24.0, 2.5, -20.0)" in s
    for bad in (("a b", 1, 1, 1), ('x"); os.exit() --', 1, 1, 1), ("abc", float("inf"), 1, 1), ("abc", "1", 1, 1),
                ("abc", True, 1, 1)):
        with pytest.raises((TypeError, ValueError)):
            lua.place_piece(*bad)
    with pytest.raises(play.ReadOnlyViolation):
        class Boom:
            def call_lua(self, *a, **k):
                raise AssertionError("no debia llegar")
        play.ReadOnlyClient(Boom()).call_lua(s)


def test_a_dead_harpy_is_moved_off_the_board_by_the_bot(rig):
    session, table, game = rig
    destiny_rig(session, table)
    game.damage(game.fighters["harpy2"], 1, "combat")
    session._project({"harpy2": (21, True)})
    assert table.placed == [("Harpy 2", 24.0 + 1.5, 2.5, -20.0)]
    assert any("Harpy 2 cae: la he apartado" in m for m in session.messages)


def test_without_a_dead_spot_or_if_it_fails_the_human_is_told(rig):
    session, table, game = rig
    destiny_rig(session, table, dead_spot=None)
    game.damage(game.fighters["harpy1"], 1, "combat")
    session._project({"harpy1": (20, True)})
    assert "Harpy 1 cae: retira su miniatura de la mesa (no he podido apartarla yo)." in session.messages
    destiny_rig(session, table)
    table.move_fails = {"pcharpy3"}
    session.messages.clear()
    game.damage(game.fighters["harpy3"], 1, "combat")
    session._project({"harpy3": (22, True)})
    assert "Harpy 3 cae: retira su miniatura de la mesa (no he podido apartarla yo)." in session.messages and table.placed == []


def test_horseshoes_hurts_every_other_fighter_in_the_zone_allies_included(game):
    place(game, medusa=0, hellboy=1, lobster=2, harpy1=27)
    hb, lob, med = game.fighters["hellboy"], game.fighters["lobster"], game.fighters["medusa"]
    r = game.attack(hb, med, give(game, 1, "Horseshoes And Hand Grenades"), def_card=None)
    assert lob.hp == 5 and hb.hp == 18 and game.fighters["harpy1"].hp == 1     # Lobster (aliado) si; fuera de zona, no
    assert any("lobster" in e for e in r.human_effects)                        # E2: the human's card, narrated to them


# ---------- planes (schemes) del humano y del bot ----------
def card_id(game, player, title):
    return next(c.card_id for c in game.players[player].full_set if c.title == title)


CROWN = "And Upon His Brow Is Set A Crown Of Flame"


@pytest.mark.parametrize("title,n", [(CROWN, 2), ("Fight Or Flight", 1)])
def test_a_scheme_of_a_hero_outside_the_interpreter_draws_and_the_bot_deals_it(rig, monkeypatch, title, n):
    session, table, game = rig
    monkeypatch.setattr(type(game.fx), "interprets", lambda self, player: False)         # the legacy branches of _apply_human_scheme
    card = dataclasses.replace(next(c for c in game.players[1].full_set if c.title == CROWN), title=title)
    out_before = len(session.messages)
    session._apply_human_scheme(card)
    assert game.drawn[1] == n and not any("robar" in m.lower() and "tu:" in m.lower() for m in session.messages[out_before:])
    session.cfg = dataclasses.replace(session.cfg, human_deck_guid="HDECK", human_deck_spot=(-4.6, 13.67))
    session._deal_owed_draws(title)
    session._commit()
    assert table.human_deals == [n] and session.human_dealt == game.drawn[1] == n


def test_a_scheme_played_after_pressing_plan_is_recognised_at_fin_de_accion(rig):
    session, table, game = rig
    destiny_rig(session, table)
    out = session.handle(Event.SCHEME)
    assert game.actions_left == 1 and any("deja tu carta de plan" in m for m in out)
    table.human_discard = [card_id(game, 1, CROWN)]
    table.human_hand = [c.card_id for c in game.players[1].hand]                       # the five cards the bot moves
    out = session.handle(Event.END_ACTION)
    assert any(f"Aplico {CROWN}: robas 2; descartas " in m and "; ganas 2 acciones." in m for m in out)   # E2: the interpreter
    assert any(f"Descarto tu mano (5 cartas) por {CROWN}" in m for m in out)           # your hand: the bot discards it
    assert game.actions_left == 3 and session.scheme_baseline is None
    destinies = 1 + sum(c.destiny for c in game.players[1].discard if c.title != CROWN)   # the Crown and the moved hand
    assert table.dials["dD"]["value"] == destinies >= 1, "la corona y las cartas de destino que se descartan: el dial las cuenta"
    assert any(f"Destinos de Hellboy: {destinies - 1} (en su descarte)" in m for m in out)   # the moved hand, before the Crown lands


@pytest.mark.skipif(bool(__import__("os").environ.get("SPARRING_BATCH")), reason="en modo rapido Plan no espera: la carta la reconoce Fin de accion")
def test_the_bot_waits_for_the_scheme_card_to_appear_while_pressing_plan(rig, monkeypatch):
    session, table, game = rig
    calls = {"n": 0}
    real = session.sync_human

    def late_card():
        calls["n"] += 1
        if calls["n"] == 3:
            table.human_discard = [card_id(game, 1, CROWN)]
        real()
    monkeypatch.setattr(session, "sync_human", late_card)
    out = session.handle(Event.SCHEME)
    assert any("Aplico" in m for m in out) and game.actions_left == 3
    assert session.scheme_baseline is None


def test_a_scheme_that_needs_a_choice_is_left_to_the_human_through_the_panel(rig):
    session, table, game = rig
    session.handle(Event.SCHEME)
    table.human_discard = [card_id(game, 1, "Pancakes!")]
    out = session.handle(Event.END_ACTION)
    assert any("Detecto Pancakes!: la carta te pide una eleccion." in m for m in out)      # E2: the panel asks
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "effect"
    assert game.actions_left == 1


def test_fin_de_accion_without_a_scheme_card_has_an_exit(rig):
    session, table, game = rig
    session.handle(Event.SCHEME)
    out = session.handle(Event.END_ACTION)
    assert any("No he visto ninguna carta de plan" in m for m in out)
    assert session.scheme_baseline is None and not session.moving


def test_the_scheme_wait_survives_a_restart(rig, tmp_path):
    session, table, game = rig
    session.state_path = tmp_path / "s.json"
    session.handle(Event.SCHEME)
    other = fresh(session)
    other.load_dict(persist.load(session.state_path))
    assert other.scheme_baseline == session.scheme_baseline == []


def test_the_bot_names_the_scheme_it_plays_and_the_damage(rig, monkeypatch):
    session, table, game = rig
    test_session.set_bot_hand(table, game, "A Momentary Glance", "Dash")
    session.read_bot_hand()
    glance = card(game, 0, "A Momentary Glance")
    place(game, medusa=0, hellboy=1)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    monkeypatch.setattr(session.ai, "plan", maneuver_once(Act("glance", fid="medusa", target="hellboy", card=glance)))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.actions_left = 0
    out = session.handle(Event.END_ACTION)
    assert any(m.startswith("El bot juega A Momentary Glance: 2 de dano a Hellboy") for m in out)
    assert game.fighters["hellboy"].hp == 16


def maneuver_once(first):
    acts = iter([first])
    return lambda g: next(acts, None) or Act("maneuver", moves={})


def test_a_revived_harpy_is_moved_by_the_bot_and_the_card_is_named(rig, monkeypatch):
    session, table, game = rig
    test_session.set_bot_hand(table, game, "Winged Frenzy", "Dash")
    session.read_bot_hand()
    frenzy = card(game, 0, "Winged Frenzy")
    h3 = game.fighters["harpy3"]
    h3.alive, h3.pos, h3.hp = False, None, 0
    table.positions.pop("Harpy 3")
    monkeypatch.setattr(session.ai, "plan", maneuver_once(Act("frenzy", card=frenzy, moves={}, spot=2)))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.actions_left = 0
    out = session.handle(Event.END_ACTION)
    assert any(m.startswith("El bot juega Winged Frenzy") for m in out)
    assert ("Harpy 3", 2) in table.moves and h3.alive
    assert f"Harpy 3 vuelve al juego: la he colocado yo en {describe(game, 2, ('harpy3',), session._name)}." in out


# ---------- efectos del bot: dial, anuncio, y solo entonces seguir ----------
def lobster_glance(session, table, game, monkeypatch, ability=False):
    dial_rig(session, table)
    test_session.set_bot_hand(table, game, "A Momentary Glance", "Dash")
    session.read_bot_hand()
    glance = card(game, 0, "A Momentary Glance")
    place(game, medusa=0, hellboy=30, lobster=1)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    monkeypatch.setattr(session.ai, "plan", maneuver_once(Act("glance", fid="medusa", target="lobster", card=glance)))
    monkeypatch.setattr(session.ai, "pick_ability_target",
                        (lambda g: g.fighters["lobster"]) if ability else (lambda g: None))
    game.actions_left = 0


@pytest.mark.skipif(bool(__import__("os").environ.get("SPARRING_BATCH")), reason="inspecciona scripts sueltos: en modo rapido salen dentro de un compuesto (ver test_batch.py)")
def test_a_glance_on_lobster_updates_the_dial_names_the_card_and_shows_the_hp(rig, monkeypatch):
    session, table, game = rig
    lobster_glance(session, table, game, monkeypatch)
    order = []
    real_say, real_call = session.say, session.client.call_lua
    monkeypatch.setattr(session, "say", lambda m, *k: (order.append(("say", m)), real_say(m, *k))[1])
    monkeypatch.setattr(session.client, "call_lua", lambda s, *a, **k: (
        order.append(("lua", s.split("\n")[0])), real_call(s, *a, **k))[1])
    session.handle(Event.END_ACTION)
    said = [m for kind, m in order if kind == "say"]
    text = next(m for m in said if m.startswith("El bot juega A Momentary Glance"))
    assert "2 de dano a Lobster Johnson (PV de 6 a 4)" in text
    assert table.dials["dL"]["value"] == 4
    dial_i = next(i for i, (k, m) in enumerate(order) if k == "lua" and "set_health_dials" in m)
    say_i = next(i for i, (k, m) in enumerate(order) if k == "say" and m == text)
    assert dial_i < say_i, "primero el dial, luego el anuncio"


def test_medusas_ability_writes_the_dial_and_shows_the_hp(rig, monkeypatch):
    session, table, game = rig
    lobster_glance(session, table, game, monkeypatch, ability=True)
    out = session.handle(Event.END_ACTION)
    assert "Habilidad de Medusa: 1 de dano a Lobster Johnson (PV de 6 a 5)." in out
    assert table.dials["dL"]["value"] == 3, "5 tras la habilidad y 3 tras el Glance (2 de dano)"


def test_a_dial_that_cannot_be_written_pauses_the_bot_turn_until_fin_de_accion(rig, monkeypatch, tmp_path):
    session, table, game = rig
    session.state_path = tmp_path / "s.json"
    lobster_glance(session, table, game, monkeypatch, ability=True)
    table.dial_ignores_writes = True
    out = session.handle(Event.END_ACTION)
    assert game.turn == 0 and game.actions_left == 2 and session.dial_debt
    assert any("Habilidad de Medusa" in m for m in out) and any("deberia marcar 5" in m for m in out)
    assert any("Turno del bot en pausa" in m for m in out)
    assert not any(m.startswith("El bot ") for m in out), "no siguio con su siguiente accion"
    assert json.loads(session.state_path.read_text(encoding="utf-8"))["dial_debt"] is True
    table.dial_ignores_writes = False                     # el humano arregla la mesa
    out = session.handle(Event.END_ACTION)
    assert not session.dial_debt and any(m.startswith("El bot juega A Momentary Glance") for m in out)
    assert game.fighters["lobster"].hp == 3 and table.dials["dL"]["value"] == 3
    assert not any("Habilidad de Medusa" in m for m in out), "la habilidad no se repite al reanudar"
    assert game.turn == 1


def test_a_dial_failure_after_an_action_pauses_before_the_next_action(rig, monkeypatch):
    session, table, game = rig
    lobster_glance(session, table, game, monkeypatch)
    table.dial_ignores_writes = True
    out = session.handle(Event.END_ACTION)
    assert any(m.startswith("El bot juega A Momentary Glance") for m in out)
    assert game.turn == 0 and game.actions_left == 1 and session.dial_debt
    assert not any(m.startswith("El bot hace") for m in out)


def test_a_dial_that_still_fails_after_the_human_was_asked_does_not_deadlock(rig, monkeypatch):
    session, table, game = rig
    lobster_glance(session, table, game, monkeypatch)
    table.dial_ignores_writes = True
    session.handle(Event.END_ACTION)
    out = session.handle(Event.END_ACTION)
    assert any("siguen sin coincidir" in m for m in out)


def test_cards_without_text_have_no_effect_to_resolve_by_hand(rig, monkeypatch):
    session, table, game = rig
    out = human_attack_reveal(session, table, game, monkeypatch, card_title="Excalibur")
    assert not any("Resuelve a mano" in m for m in out)


def test_every_hellboy_and_lobster_card_has_its_text_from_the_source_except_the_vanilla_ones():
    from sparring.cards import load_hellboy_deck
    deck = load_hellboy_deck()
    empty = {c.title for c in deck if not c.text.strip()}
    assert empty == {"Excalibur", "Service Pistol"}          # en la carta real no llevan texto
    assert sum(1 for c in deck if c.fighter == "Lobster Johnson") == 5
    assert all(c.text.strip() for c in deck if c.title not in empty)


def test_after_combat_text_is_split_from_the_rest():
    from sparring.cards import load_hellboy_deck
    from legacy_medusa import after_text            # the oracle's copy (E2 deleted the production helper)
    by = {c.title: c for c in load_hellboy_deck()}
    assert after_text(by["Right Hand Of Doom"]).startswith("Move an adjacent fighter")
    assert after_text(by["Planned Recklessness"]) == "" and after_text(by["Excalibur"]) == ""


# ---------- el descarte del bot se lee como una linea de tiempo ----------
def slot_index(session, spot):
    return next(k for k in range(60) if session._discard_slot(k) == tuple(spot))


def test_every_combat_discard_is_announced_with_its_reason_and_lands_in_order(rig, monkeypatch):
    session, table, game = rig
    test_session.set_bot_hand(table, game, "Second Shot", "Dash")
    session.read_bot_hand()
    dash, ss = card(game, 0, "Dash"), card(game, 0, "Second Shot")
    monkeypatch.setattr(session.ai, "choose_combat_boost", lambda g, ctx: dash)
    place(game, medusa=0, hellboy=1)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("attack", fid="medusa", target="hellboy", card=ss))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.turn, game.actions_left, session.bot_stage = 0, 2, None
    session._bot_continue()
    out = session.handle(Event.REVEAL)
    assert "El bot descarta Dash por boost de combate, Second Shot por ataque." in out
    assert slot_index(session, table.discard_spots[dash.card_id]) == 0
    assert slot_index(session, table.discard_spots[ss.card_id]) == 1


def test_a_defense_is_announced_as_such(rig, monkeypatch):
    session, table, game = rig
    test_session.set_bot_hand(table, game, "Dash", "Snipe")
    session.read_bot_hand()
    dash = card(game, 0, "Dash")
    out = human_attack_reveal(session, table, game, monkeypatch, defense=dash)
    assert "El bot descarta Dash por defensa." in out


def test_the_maneuver_boost_and_the_hand_limit_are_announced_and_slots_keep_counting(rig, monkeypatch):
    session, table, game = rig
    st = game.players[0]
    table.bot_hand = [c.card_id for c in st.full_set][:7]
    table.bot_deck = [c.card_id for c in st.full_set][7:]
    session.read_bot_hand()
    boost = st.hand[0]
    maneuver_plan(session, monkeypatch, boost=boost)
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.actions_left = 0
    out = session.handle(Event.END_ACTION)
    assert any(m.startswith(f"El bot maniobra (descarta {boost.title} por boost de maniobra)") for m in out)
    limit = next(m for m in out if m.startswith("El bot descarta ") and "por limite de mano" in m)
    assert limit.count("por limite de mano") == len(st.discard) - 1
    order = [c.card_id for c in st.discard]
    slots = [slot_index(session, table.discard_spots[i]) for i in order]
    assert slots == list(range(len(order))), "una carta por hueco, en el orden de juego, sin saltos ni repeticiones"


def test_a_later_discard_takes_the_slot_after_the_cards_already_on_the_pile(rig, monkeypatch):
    session, table, game = rig
    st = game.players[0]
    set_hand = test_session.set_bot_hand
    set_hand(table, game, "Snipe", "Dash", "Feint")
    session.read_bot_hand()
    for title in ("Snipe", "Dash"):
        c = card(game, 0, title)
        game.discard_card(0, c)
        session._mark_dirty()
        session._flush_table()
    assert [slot_index(session, table.discard_spots[c.card_id]) for c in st.discard] == [0, 1]
    feint = card(game, 0, "Feint")
    game.discard_card(0, feint)
    session._mark_dirty()
    session._flush_table()
    assert slot_index(session, table.discard_spots[feint.card_id]) == 2


# ---------- preparacion de la partida: sorteo, mano, mulligan y colocacion ----------
HIND = ("Hiss and Slither", "Hiss and Slither", "Hiss and Slither", "A Momentary Glance", "Winged Frenzy")
GOODH = ("Second Shot", "Dash", "Snipe", "Feint", "Regroup")


def deck_with_first(game, titles):
    """Mazo fisico cuyas 5 primeras cartas son `titles` y despues el resto."""
    full = game.players[0].full_set
    first, used = [], set()
    for t in titles:
        c = next(x for x in full if x.title == t and x.card_id not in used)
        used.add(c.card_id)
        first.append(c.card_id)
    return first + [c.card_id for c in full if c.card_id not in used]


def setup_rig(session, table, game, first, titles=GOODH, mulligan=True, mode="random"):
    session.cfg = dataclasses.replace(session.cfg, setup=True, mulligan_bot=mulligan)
    session.first_mode = mode
    game.turn = first
    table.bot_hand = []
    table.bot_deck = deck_with_first(game, titles)
    table.human_count = 0
    table.positions = {NICK[f]: 10 + i for i, f in enumerate(NICK)}      # todo desordenado, fuera de las salidas
    table.dial_ignores_writes = False


def place_human(table, hellboy=3, lobster=1, count=5):
    table.positions["Hellboy"], table.positions["Lobster Johnson"] = hellboy, lobster
    table.human_count = count


def idle_bot(session, monkeypatch):
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)


def test_first_player_defaults_to_a_random_draw_with_a_random_seed():
    args = play.parse_args([])
    assert args.first == "random" and args.seed is None
    assert play.parse_args(["--first", "bot", "--seed", "3"]).first == "bot"


def test_the_draw_is_announced_and_the_first_player_takes_start_space_one(rig):
    session, table, game = rig
    setup_rig(session, table, game, first=1)
    out = session.start()
    assert "Sorteo: empieza Hellboy." in out
    assert game.start_spaces == {1: 3, 0: 30}
    session2, table2, game2 = session, table, game
    setup_rig(session2, table2, game2, first=0)
    session2.setup = None
    session2.start()
    assert game2.start_spaces == {0: 3, 1: 30}


def test_a_forced_first_player_is_announced_as_such(rig):
    session, table, game = rig
    setup_rig(session, table, game, first=0, mode="bot")
    assert "Empieza Medusa (elegido con --first bot)." in session.start()


def test_bot_first_the_bot_places_then_asks_the_human_and_waits_for_listo(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=0)
    idle_bot(session, monkeypatch)
    out = session.start()
    assert session.setup["stage"] == "wait_human"
    assert table.positions["Medusa"] == 3
    zone = {0, 1, 2, 3, 4}
    assert {table.positions[f"Harpy {i}"] for i in (1, 2, 3)} <= zone - {3}
    assert any(m.startswith(f"El bot coloca: Medusa en {zone_text(game, 3)}") for m in out)
    assert any(f"coloca a Lobster Johnson en tu casilla de salida ({zone_text(game, 30)})" in m for m in out)
    assert table.positions["Hellboy"] == 30 and table.positions["Lobster Johnson"] == 15, "el bot solo coloca al heroe del humano"
    assert game.turn == 0 and game.actions_left == 2
    blocked = session.handle(Event.MANEUVER)
    assert any("se esta preparando" in m for m in blocked) and game.actions_left == 2
    out = session.handle(Event.READY)
    assert any(f"Falta colocar a Lobster Johnson en tu casilla de salida ({zone_text(game, 30)})" in m for m in out) and session.setup is not None
    place_human(table, hellboy=30, lobster=29, count=0)
    assert any("Roba tus 5 cartas antes de pulsar Listo" in m for m in session.handle(Event.READY))
    table.human_count = 5
    out = session.handle(Event.READY)
    assert session.setup is None and any("Preparacion terminada" in m for m in out)
    assert any(m.startswith("El bot maniobra") for m in out) and game.turn == 1


def test_human_first_the_bot_waits_reads_the_human_pieces_and_then_places(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=1)
    idle_bot(session, monkeypatch)
    seen = {}
    real = session.ai.choose_setup

    def spy(g, hand):
        seen["lobster"], seen["hellboy"] = g.fighters["lobster"].pos, g.fighters["hellboy"].pos
        seen["table_moves_before"] = list(table.moves)
        return real(g, hand)
    monkeypatch.setattr(session.ai, "choose_setup", spy)
    out = session.start()
    assert session.setup["stage"] == "wait_human_first"
    assert table.moves == [("Hellboy", 3)] and table.positions["Medusa"] == 10, "solo el heroe del humano; sus piezas esperan"
    assert any("Empiezas tu" in m and zone_text(game, 3) in m for m in out)
    place_human(table, hellboy=3, lobster=4)
    out = session.handle(Event.READY)
    assert seen["lobster"] == 4 and seen["hellboy"] == 3, "la eleccion de las Harpias usa las casillas reales"
    assert seen["table_moves_before"] == [("Hellboy", 3)]
    assert table.positions["Medusa"] == 30
    assert {table.positions[f"Harpy {i}"] for i in (1, 2, 3)} <= {18, 19, 28, 29, 31}
    assert session.setup is None and game.turn == 1 and any("Tu turno" in m for m in out)


def test_the_harpy_choice_depends_on_the_hand_and_the_actual_sidekick_position(rig):
    session, table, game = rig
    ai = session.ai

    def plan(titles, lobster):
        g = Game.new(game.board, seed=1, controllers={})
        g.start_spaces = {0: 30, 1: 3}
        place(g, hellboy=3, lobster=lobster)
        hand = [next(c for c in g.players[0].full_set if c.title == t) for t in titles]
        return ai.choose_setup(g, hand)
    back = plan(("Dash", "Snipe"), lobster=4)
    forward = plan(("Clutching Claws", "Dash"), lobster=4)
    forward_hounds = plan(("The Hounds of Mighty Zeus", "Dash"), lobster=4)
    assert back["medusa"] == forward["medusa"] == 30
    assert forward == forward_hounds != back
    dist = lambda p: sum(game.board.distance(p[h], 3) for h in ("harpy1", "harpy2", "harpy3"))
    assert dist(forward) < dist(back), "con Claws o Hounds se adelantan; sin ellas se quedan atras"
    taken_by_lobster = plan(("Clutching Claws",), lobster=29)
    assert 29 not in taken_by_lobster.values(), "nunca encima de una pieza rival"


def test_a_bad_opening_hand_triggers_one_mulligan_announced_without_the_cards(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=0, titles=HIND)
    idle_bot(session, monkeypatch)
    bad = list(table.bot_deck[:5])
    out = session.start()
    assert "Medusa hace mulligan." in out and table.shuffles == 1
    assert len(table.bot_hand) == 5 and not set(table.bot_hand) & set(bad)
    assert len(table.bot_deck) == 25 and len(game.players[0].hand) == 5
    assert not any("Hiss" in m or "Frenzy" in m or "Glance" in m for m in out), "no revela la mano"
    assert session.setup["mull_done"] is True


def test_a_good_hand_is_kept(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=0)
    idle_bot(session, monkeypatch)
    out = session.start()
    assert "Medusa se queda la mano." in out and table.shuffles == 0


def test_the_mulligan_can_be_switched_off(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=0, titles=HIND, mulligan=False)
    idle_bot(session, monkeypatch)
    out = session.start()
    assert table.shuffles == 0 and not any("mulligan" in m for m in out)


def test_the_hand_evaluation_flags_no_attackers_or_three_dead_cards(rig):
    session, table, game = rig
    full = game.players[0].full_set

    def hand(*titles):
        return [next(c for c in full if c.title == t) for t in titles]
    ai = session.ai
    assert ai.should_mulligan(game, hand(*HIND))                                       # sin ataques
    assert ai.should_mulligan(game, hand("Dash", "Snipe", "Hiss and Slither", "A Momentary Glance", "Winged Frenzy"))
    assert not ai.should_mulligan(game, hand(*GOODH))
    assert not ai.should_mulligan(game, hand("Dash", "Snipe", "Feint", "Hiss and Slither", "A Momentary Glance"))


def test_the_setup_stage_is_persisted_and_a_failed_placement_is_retried_with_listo(rig, monkeypatch, tmp_path):
    session, table, game = rig
    setup_rig(session, table, game, first=0)
    idle_bot(session, monkeypatch)
    session.state_path = tmp_path / "s.json"
    real, state = session._move_piece, {"fail": True}

    def flaky(fid, space):
        if state["fail"]:
            state["fail"] = False
            raise TimeoutError("TTS no devolvio valor")
        return real(fid, space)
    monkeypatch.setattr(session, "_move_piece", flaky)
    out = session.start()
    assert session.setup["stage"] == "place_bot" and any("Pulsa Listo para reintentar" in m for m in out)
    assert json.loads(session.state_path.read_text(encoding="utf-8"))["setup"]["stage"] == "place_bot"
    session.handle(Event.READY)
    assert session.setup["stage"] == "wait_human" and table.positions["Medusa"] == 3


def test_resume_continues_the_setup_from_its_saved_stage(rig, monkeypatch, tmp_path):
    session, table, game = rig
    setup_rig(session, table, game, first=1)
    session.state_path = tmp_path / "s.json"
    session.start()
    assert session.setup["stage"] == "wait_human_first"
    other = fresh(session)
    other.state_path = session.state_path
    other.load_dict(persist.load(session.state_path))
    assert other.setup["stage"] == "wait_human_first" and other.game.start_spaces == {1: 3, 0: 30}
    out = other.resume()
    assert any("etapa 'wait_human_first'" in m for m in out) and table.moves == [("Hellboy", 3)], "reanudar no coloca de nuevo al heroe"
    place_human(table, hellboy=3, lobster=1)
    idle_bot(other, monkeypatch)
    other.handle(Event.READY)
    assert other.setup is None and table.positions["Medusa"] == 30


def test_a_resume_in_an_automatic_stage_finishes_it(rig, monkeypatch, tmp_path):
    session, table, game = rig
    setup_rig(session, table, game, first=0)
    idle_bot(session, monkeypatch)
    session.state_path = tmp_path / "s.json"
    monkeypatch.setattr(session, "_move_piece", lambda fid, space: (_ for _ in ()).throw(TimeoutError("x")))
    session.start()
    assert session.setup["stage"] == "place_bot"
    other = fresh(session)
    other.state_path = session.state_path
    other.load_dict(persist.load(session.state_path))
    other.resume()
    assert other.setup["stage"] == "wait_human" and table.positions["Medusa"] == 3


def test_the_listo_button_exists_in_the_panel_and_is_parsed():
    from sparring.tts import ui
    assert 'onClick="onReady"' in ui.panel_xml(["medusa"]) and "function onReady()" in ui.handler_script()
    assert ui.parse_event({"event": "ready"}) == (Event.READY, {})


def test_mulligan_builders_are_allowlisted_validated_and_never_read_only():
    a = t_return_hand_to_deck("Green", "d42056")
    b = t_shuffle_deck("d42056", (11.5, 12.0))
    for s in (a, b):
        assert lua.is_sendable(s)
    assert "putObject" in a and "getHandObjects(1)" in a and "d.shuffle()" in b and "d.getQuantity()" in b
    assert "17600" in a and "17629" in a
    for bad in (lambda: t_return_hand_to_deck("Verde", "abc"), lambda: t_return_hand_to_deck("Green", 'x"); --'),
                lambda: t_return_hand_to_deck("Green", "abc", id_range=(1,)),
                lambda: t_shuffle_deck("a b"), lambda: t_shuffle_deck("abc", (1,)),
                lambda: t_shuffle_deck("abc", (0, 0), id_range="x"), lambda: t_shuffle_deck("abc", (0, float("inf")))):
        with pytest.raises((TypeError, ValueError)):
            bad()
    assert {"return_hand_to_deck", "shuffle_deck"}.isdisjoint(play.READ_ONLY_TAGS)
    class Boom:
        def call_lua(self, *a, **k):
            raise AssertionError("no debia llegar")
    for s in (a, b):
        with pytest.raises(play.ReadOnlyViolation):
            play.ReadOnlyClient(Boom()).call_lua(s)


# ---------- sesion de juego en vivo 2: Revelar, destinos que parpadean, etiquetas ----------
def test_a_card_the_engine_thinks_is_discarded_is_accepted_when_it_lies_face_down_in_combat(rig, monkeypatch):
    """Mulligan humano + maniobras: la lectura del descarte metio una carta que en realidad esta en la mano."""
    session, table, game = rig
    st = game.players[1]
    excalibur = next(c for c in st.full_set if c.title == "Excalibur")
    for pile in (st.hand, st.deck):
        if excalibur in pile:
            pile.remove(excalibur)
    st.discard.append(excalibur)
    out = human_attack_reveal(session, table, game, monkeypatch, card_title="Excalibur")
    assert not any("Carta ilegal" in m for m in out), out
    assert excalibur in st.discard and excalibur not in st.hand and session.moving


def test_a_card_missing_from_every_pile_is_still_accepted_at_reveal(rig, monkeypatch):
    session, table, game = rig
    st = game.players[1]
    card = next(c for c in st.full_set if c.title == "Excalibur")
    for pile in (st.hand, st.deck, st.discard):
        if card in pile:
            pile.remove(card)
    out = human_attack_reveal(session, table, game, monkeypatch, card_title="Excalibur")
    assert not any("Carta ilegal" in m for m in out), out


def test_a_destiny_that_shows_for_one_read_only_is_not_announced(rig):
    session, table, game = rig
    destiny_rig(session, table)
    session.cfg = dataclasses.replace(session.cfg, settle_wait=0)
    base = destiny_ids(game, 2)
    table.human_discard = base
    session.handle(Event.END_ACTION)
    reads = iter([base + destiny_ids(game, 3)[2:], base])         # aparece 1 lectura y desaparece
    orig = table.do_read_discard
    def flicker(s):
        if '"BOTZ"' in s:
            return orig(s)
        table._tick()
        return [{"id": i, "guid": f"g{i}"} for i in next(reads, base)]
    table.do_read_discard = flicker
    out = session.handle(Event.END_ACTION)
    assert game.destiny_count(1) == 2 and table.dials["dD"]["value"] == 2
    assert not any("Destinos de Hellboy" in m for m in out)


def test_a_card_just_played_stays_counted_while_it_travels_to_the_discard(rig, monkeypatch):
    session, table, game = rig
    destiny_rig(session, table)
    human_attack_reveal(session, table, game, monkeypatch, card_title="Excalibur")
    assert game.destiny_count(1) == 1
    session.sync_human()                       # la carta aun no ha llegado a la zona
    assert game.destiny_count(1) == 1
    excalibur = next(c.card_id for c in game.players[1].full_set if c.title == "Excalibur")
    table.human_discard = [excalibur]
    session.sync_human()
    assert game.destiny_count(1) == 1 and excalibur not in session._transit


def test_markings_reuse_path_is_guarded_and_respawns_a_stale_label():
    s = lua.draw_markings([("D", "abc")], [("C", 0.0, 0.0)])
    assert lua.is_sendable(s)
    assert "if found ~= nil then" in s and "found.setPosition == nil" in s and "pcall(function()" in s
    assert "found.destruct()" in s and s.index("found = nil") < s.index("if found == nil then")
    assert "\n    found.setPosition(" not in s.replace("      found.setPosition(", "")


def test_bot_first_the_bot_also_places_the_human_hero_on_his_start_space(rig, monkeypatch):
    session, table, game = rig
    setup_rig(session, table, game, first=0)
    idle_bot(session, monkeypatch)
    out = session.start()
    assert session.setup["stage"] == "wait_human"
    assert ("Hellboy", 30) in table.moves and table.positions["Hellboy"] == 30
    assert game.fighters["hellboy"].pos == 30 and session.setup["hero_placed"]
    assert any(f"coloca a Hellboy (tu heroe) en su casilla de salida ({zone_text(game, 30)})" in m for m in out)
    assert not any(m == ("Lobster Johnson", 30) for m in table.moves)


def test_human_first_the_bot_places_the_hero_as_soon_as_the_human_setup_begins(rig):
    session, table, game = rig
    setup_rig(session, table, game, first=1)
    out = session.start()
    assert session.setup["stage"] == "wait_human_first"
    assert ("Hellboy", 3) in table.moves and table.positions["Hellboy"] == 3
    assert any(f"coloca a Hellboy (tu heroe) en su casilla de salida ({zone_text(game, 3)})" in m for m in out)
    assert not any(n == "Medusa" for n, _ in table.moves), "el bot sigue sin colocar sus piezas"
    moves = len(table.moves)
    session.handle(Event.MULLIGAN)
    table.positions["Lobster Johnson"], table.human_count = 1, 5
    session.handle(Event.READY)
    assert [m for m in table.moves[:moves] if m[0] == "Hellboy"] == [("Hellboy", 3)]
    assert sum(n == "Hellboy" for n, _ in table.moves) == 1, "no se vuelve a colocar"
