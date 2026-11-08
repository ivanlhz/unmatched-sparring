"""Jill Trent's gadget token is a real piece on the table (Iván, 2026-11-08): it is double-sided, with ONE resting spot per side. Face up
(rot Z 0) is the Ultrabiotic Tonic, flipped (rot Z 180) the Hypnoray Blaster, and face up turned 90 degrees means no gadget yet. The bot
moves it (setPosition / setRotation through `lua.move_token`) whenever the engine's counter `gadget` changes, whoever plays Jill. Sessions run against FakeTTS
(batch mode, `FxTable.do_move_token`); the Lua of the moves, the layout and the table cleaning run on the lupa stub of TTS."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sparring import ai_effects, player_setup, session_gadget, table_layout, table_reset
from sparring.effects.select import counter_value
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build
from test_review9 import rt, run  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
RAW = json.loads((ROOT / "config" / "table.json").read_text(encoding="utf-8"))
SETUPS = json.loads((ROOT / "config" / "map_setups.json").read_text(encoding="utf-8"))
JILL = load_hero_table("jill-trent")
TOKEN = "8af285"
BLASTER, TONIC = 0, 1                     # index of the answer in the panel: Hypnoray Blaster, Ultrabiotic Tonic
NONE, BLASTER_UP, TONIC_UP = 0, 1, 2      # the engine's counter `gadget`


def place(side: str) -> tuple:
    """(position, rotation) of the single resting spot as the data gives it."""
    slots = table_layout.own_token_slots(side, JILL, "gadget")
    assert len(slots) == 1, "one resting spot per side"
    return slots[0].pos, slots[0].rot


def last_move(table):
    assert table.token_moves, "the token was never moved"
    guid, pos, rot = table.token_moves[-1]
    assert guid == TOKEN
    return pos, rot


def at(table, side: str, gadget: int) -> bool:
    """The last write put the token on `side`'s spot, lifted, turned as the counter value `gadget` says."""
    pos, rot = last_move(table)
    (x, y, z), (rx, ry, rz) = place(side)
    want = {TONIC_UP: (rx, ry, 0), BLASTER_UP: (rx, ry, 180), NONE: (rx, (ry + session_gadget.NONE_TURN) % 360, 0)}[gadget]
    return (pos[0], round(pos[1], 2), pos[2]) == (x, round(y + table_layout.SETTLE_LIFT, 2), z) and tuple(rot) == want


@pytest.fixture
def rig(request, tmp_path):
    bot, human = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, ())
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def jill_rig(bot, human):
    return pytest.mark.parametrize("rig", [(bot, human)], indirect=True)


# ---------------------------------------------------------------- the data

def test_the_token_is_a_hero_token_with_one_place_per_side_and_the_bag_is_still_recognised():
    assert JILL.tokens == {"gadget": TOKEN} and JILL.ignored_tokens == ()
    assert TOKEN in JILL.all_guids() and ("token", (TOKEN,)) in JILL.unpack_items()
    tables = {"jill-trent": JILL, "abe-sapien": load_hero_table("abe-sapien")}
    everything = [JILL.deck_guid, *JILL.fighters["jill"].pieces, TOKEN]
    assert player_setup._bag_hero(everything, tables) == "jill-trent"
    assert player_setup._bag_hero([TOKEN], tables) == "jill-trent"


@pytest.mark.parametrize("layout", [RAW["layout"], *(e["layout"] for e in SETUPS.values())])
@pytest.mark.parametrize("side", ["bot", "human"])
def test_the_place_comes_from_the_character_card_spot_of_every_calibrated_layout(layout, side):
    """Past the deck (z + 2.7), away from the map, in the card's column (measured live on B.P.R.D. HQ, 2026-11-08: the first guess,
    2.6 toward lower z, lay under the board). The card's Y rotation, X and Z 0."""
    (bx, by, bz), (brx, bry, brz) = place(side)
    card = layout[side]["character_card"]
    cx, cy, cz = card["pos"]
    assert abs(bx - cx) < 0.5 and bz > cz + 2.7 + 1.5 and by > cy
    assert (brx, brz) == (0, 0) and bry == pytest.approx(card["rot"][1])


# ---------------------------------------------------------------- set-up: at the resting spot

@pytest.mark.parametrize("side", ["bot", "human"])
def test_the_layout_puts_the_token_at_its_single_spot(side):
    plan = table_layout.plan(RAW, side, JILL)
    token = next(p for p in plan.placements if p.guids == (TOKEN,))
    assert token.role == "tokens" and (token.slot.pos, token.slot.rot) == place(side) and TOKEN not in plan.unplaced


@pytest.mark.parametrize("side", ["bot", "human"])
def test_preparar_lays_the_token_at_its_spot_face_up_on_the_table(rt, side):  # noqa: F811
    rt.execute(f"mkobj({{guid = '{TOKEN}', type = 'Custom_Token', pos = {{x = 0, y = 1, z = 0}}, rot = {{x = 0, y = 0, z = 0}}}})")
    plan = table_layout.plan(RAW, side, JILL)
    items = [(p.guids, *table_reset._lifted(p.slot)) for p in plan.placements]
    assert run(rt, lua.arrange_objects(items))["missing"]            # the deck and the miniatures are not on this fake table
    obj = rt.globals().getObjectFromGUID(TOKEN)
    (x, y, z), rot = place(side)
    y = round(y + table_layout.SETTLE_LIFT, 2)
    assert (round(obj.pos.x, 2), round(obj.pos.y, 2), round(obj.pos.z, 2)) == (x, y, z) and obj.rot.y == rot[1] and obj.rot.z == 0


@jill_rig("jill-trent", "hellboy")
def test_the_first_step_of_a_game_turns_the_token_for_no_gadget_for_the_bot_seat(rig):
    session, table, game, fake, cfg = rig
    click(session, table, Event.MANEUVER)
    assert counter_value(game, 0, "gadget") == 0 and at(table, "bot", NONE) and len(table.token_moves) == 1


@jill_rig("hellboy", "jill-trent")
def test_the_first_step_of_a_game_turns_the_token_for_no_gadget_for_the_human_seat(rig):
    session, table, game, fake, cfg = rig
    click(session, table, Event.MANEUVER)
    assert counter_value(game, 1, "gadget") == 0 and at(table, "human", NONE)


@jill_rig("hellboy", "medusa")
def test_a_game_without_jill_never_touches_a_gadget_token(rig):
    session, table, game, fake, cfg = rig
    click(session, table, Event.MANEUVER)
    assert table.token_moves == []


# ---------------------------------------------------------------- the bot plays Jill

def bot_chooses(monkeypatch, answer: int) -> None:
    monkeypatch.setattr(ai_effects.EffectAI, "_gadget", lambda self, game, req: answer)


@jill_rig("jill-trent", "hellboy")
@pytest.mark.parametrize("answer, expected", [(TONIC, TONIC_UP), (BLASTER, BLASTER_UP)])
def test_the_bots_choice_leaves_the_token_face_up_for_the_tonic_and_flipped_for_the_blaster(rig, monkeypatch, answer, expected):
    session, table, game, fake, cfg = rig
    bot_chooses(monkeypatch, answer)
    bot_turn(session, table, [])
    assert counter_value(game, 0, "gadget") == answer + 1
    assert at(table, "bot", expected)
    assert not session._paused() and not [m for m in session.messages if "cannot find" in m]


@jill_rig("jill-trent", "hellboy")
def test_the_token_follows_the_counter_turn_after_turn(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_chooses(monkeypatch, TONIC)
    bot_turn(session, table, [])
    assert at(table, "bot", TONIC_UP)
    game.fx.set_counter(0, "gadget", 1)                           # the next choice is the Blaster
    click(session, table, Event.MANEUVER)
    assert at(table, "bot", BLASTER_UP)
    moved = len(table.token_moves)
    click(session, table, Event.MANEUVER)
    assert len(table.token_moves) == moved, "an unchanged counter writes nothing"


# ---------------------------------------------------------------- the human plays Jill

@jill_rig("hellboy", "jill-trent")
def test_the_panel_choice_moves_the_token_for_the_human_seat(rig):
    session, table, game, fake, cfg = rig
    bot_turn(session, table, [])
    assert session._paused() is not None
    click(session, table, Event.CHOICE, {"i": 2})              # Ultrabiotic Tonic
    assert counter_value(game, 1, "gadget") == 2 and at(table, "human", TONIC_UP)
    game.fx.set_counter(1, "gadget", 1)                        # the next turn's choice: Hypnoray Blaster
    click(session, table, Event.MANEUVER)
    assert at(table, "human", BLASTER_UP)


# ---------------------------------------------------------------- resume

@jill_rig("jill-trent", "hellboy")
def test_resume_puts_the_token_back_where_the_saved_counter_says(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(0, "gadget", 2)
    session.resume()
    assert at(table, "bot", TONIC_UP) and len(table.token_moves) == 1


@jill_rig("hellboy", "jill-trent")
def test_resume_with_no_gadget_active_turns_the_token(rig):
    session, table, game, fake, cfg = rig
    session.resume()
    assert at(table, "human", NONE)


# ---------------------------------------------------------------- a missing token

@jill_rig("jill-trent", "hellboy")
def test_a_token_the_player_removed_is_said_once_and_the_game_goes_on(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    table.missing_tokens.add(TOKEN)
    told, say = [], session.say
    session.say = lambda text, *a, **k: (told.append(text), say(text, *a, **k))[1]
    bot_chooses(monkeypatch, TONIC)
    bot_turn(session, table, [])
    game.fx.set_counter(0, "gadget", 1)
    click(session, table, Event.MANEUVER)
    warnings = [m for m in told if "no encuentro la ficha del Ultrabiotic Tonic" in m]
    assert len(warnings) == 1, told
    assert counter_value(game, 0, "gadget") == 1 and game.turn == 1 and not session._paused()


@jill_rig("jill-trent", "hellboy")
def test_a_failed_write_is_not_a_missing_token_and_is_retried_at_the_next_step(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    told, say = [], session.say
    session.say = lambda text, *a, **k: (told.append(text), say(text, *a, **k))[1]
    real = table.do_move_token
    monkeypatch.setattr(table, "do_move_token", lambda s: {"__error__": "TTS refused the script"})
    click(session, table, Event.MANEUVER)
    assert [m for m in told if "no he podido mover la ficha" in m] and not [m for m in told if "no encuentro la ficha" in m]
    assert session._gadget_shown is None and not table.token_moves
    monkeypatch.setattr(table, "do_move_token", real)
    click(session, table, Event.MANEUVER)
    assert at(table, "bot", NONE) and session._gadget_shown == 0
    assert len([m for m in told if "no he podido mover la ficha" in m]) == 1


# ---------------------------------------------------------------- the Lua of the move

def token(rt, name="", kind="Custom_Token", extra=""):  # noqa: F811
    rt.execute(f"mkobj({{guid = '{TOKEN}', type = '{kind}', name = '{name}', pos = {{x = 9, y = 1, z = 9}}, rot = {{x = 0, y = 180, z = 180}}{extra}}})")


def test_move_token_sets_position_and_rotation_instantly(rt):  # noqa: F811
    token(rt)
    assert run(rt, lua.move_token(TOKEN, (5.28, 1.93, 15.0), (0.0, 90.0, 0.0))) == {"found": True, "moved": True}
    obj = rt.globals().getObjectFromGUID(TOKEN)
    assert (obj.pos.x, obj.pos.y, obj.pos.z) == (5.28, 1.93, 15.0) and (obj.rot.x, obj.rot.y, obj.rot.z) == (0, 90, 0)


@pytest.mark.parametrize("kind", ["Tile", "Token"])
def test_move_token_moves_the_types_tts_really_reports_for_this_token(rt, kind):  # noqa: F811
    """Seen on the real table: the gadget token is a "Tile", not a "Custom_Token"."""
    token(rt, kind=kind)
    assert run(rt, lua.move_token(TOKEN, (5.28, 1.93, 15.0), (0.0, 90.0, 180.0))) == {"found": True, "moved": True}
    obj = rt.globals().getObjectFromGUID(TOKEN)
    assert (obj.pos.x, obj.rot.z) == (5.28, 180)


def test_move_token_says_so_when_the_token_is_not_on_the_table_and_never_moves_a_card(rt):  # noqa: F811
    assert run(rt, lua.move_token("zzzzzz", (0.0, 1.0, 0.0), (0.0, 0.0, 0.0))) == {"found": False, "moved": False}
    token(rt, kind="Card")
    assert run(rt, lua.move_token(TOKEN, (0.0, 1.0, 0.0), (0.0, 0.0, 0.0))) == {"found": True, "moved": False, "type": "Card"}
    assert rt.globals().getObjectFromGUID(TOKEN).pos.x == 9


def test_the_script_is_a_plain_message_3_write_with_no_smooth_move_and_no_ui():
    script = lua.move_token(TOKEN, (1.0, 2.0, 3.0), (0.0, 90.0, 0.0))
    assert lua.is_sendable(script) and "setPosition(" in script and "setRotation(" in script
    assert "Smooth" not in script and "UI." not in script and "messageID" not in script


# ---------------------------------------------------------------- clean table

def test_clean_table_removes_the_token_like_the_other_hero_pieces(rt):  # noqa: F811
    token(rt)
    assert TOKEN in player_setup.clear_script(RAW)
    res = run(rt, player_setup.clear_script(RAW))
    assert res["objects"] >= 1 and rt.globals().getObjectFromGUID(TOKEN) is None


# ---------------------------------------------------------------- a re-import keeps it

def test_a_reimport_files_the_nameless_token_as_the_gadget_and_keeps_its_places():
    from tools import import_save
    assert import_save.expected_token_keys({"token_names": {TOKEN: "gadget"}}) == {"gadget"}
    assert "token_slots" in import_save.KEPT_FIELDS
    overlay = json.loads((ROOT / "data" / "heroes" / "overlay" / "jill-trent.json").read_text(encoding="utf-8"))
    hero = json.loads((ROOT / "data" / "heroes" / "jill-trent.json").read_text(encoding="utf-8"))
    assert overlay["token_names"] == hero["token_names"] == {TOKEN: "gadget"} and "ignored_tokens" not in hero
