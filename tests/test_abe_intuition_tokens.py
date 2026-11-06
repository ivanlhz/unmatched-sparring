"""Abe Sapien's Intuition tokens at Preparar. The default human `tokens` slot of config/table.json is Hellboy's ability token
spot (-6.96, 15.01), on the character card, with rot Z 180, which is Abe's ACTIVE face; the layout ran AFTER the face op, so
the tokens ended active. Abe now has his own resting places (data/tts/abe-sapien.json `token_slots`, confirmed live on 6/11),
the layout runs before the face ops, and the final face is the starting one whatever rotation the slot has."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sparring import play, player_setup, table_layout, table_reset
from sparring.play import build_game, load_config
from sparring.session import Session
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from test_review9 import conv, rt, run  # noqa: F401

REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "table.json"
ABE = load_hero_table("abe-sapien")
FIRST, SECOND = ((-3.12, 1.76, 17.99), (0.0, 90.0, 0.0)), ((-3.11, 1.76, 20.62), (0.0, 90.0, 0.0))


def raw() -> dict:
    return json.loads(REAL_CONFIG.read_text(encoding="utf-8"))


def abe_session(side_human: bool = True) -> Session:
    cfg = load_config(REAL_CONFIG, "medusa", "abe-sapien") if side_human else load_config(REAL_CONFIG, "abe-sapien", "hellboy")
    return Session(build_game(cfg, "human", 1), None, play.make_bot_ai(play.ai_config(cfg, None, None), play.BOT),
                   cfg.session_config(), bot=play.BOT)


def test_the_data_says_the_start_face_was_confirmed_live_and_gives_the_two_places():
    spec = ABE.token_faces["intuition"]
    assert spec["verify_live"] is False and spec["faces"] == {"inactive": 0, "active": 180} and "6/11" in spec["note"]
    assert ABE.token_slots["intuition"]["human"] == (FIRST, SECOND)


def test_abes_token_lands_in_his_own_place_while_hellboys_keeps_the_layout_slot():
    plan = table_layout.plan(raw(), "human", ABE)
    token = next(p for p in plan.placements if p.role == "tokens")
    assert (token.slot.pos, token.slot.rot) == FIRST and token.guids == ("5a17e9",)
    hellboy = next(p for p in table_layout.plan(raw(), "human", load_hero_table("hellboy")).placements if p.role == "tokens")
    assert hellboy.slot.pos == (-6.96, 1.67, 15.01) and hellboy.slot.rot == (0.0, 90.0, 180.0)


def test_on_the_bot_half_the_places_are_the_ones_measured_on_the_table():
    """Measured on the user's save 'abe bot' (TS_Save_9): beside the bot dial (2.49, 14.83), rotY 270."""
    slots = table_layout.own_token_slots("bot", ABE, "intuition")
    assert [(s.pos, s.rot) for s in slots] == [((1.75, 1.64, 18.0), (0.0, 270.0, 0.0)), ((1.67, 1.64, 20.37), (0.0, 270.0, 0.0))]
    plan = table_layout.plan(raw(), "bot", ABE)
    assert next(p for p in plan.placements if p.role == "tokens").slot == slots[0]


def test_the_second_token_is_looked_for_by_nickname_and_placed_or_split_into_its_own_place():
    ops, _ = table_reset.layout_ops(abe_session(), raw())
    assert [name for name, _ in ops] == ["layout", "token stacks"]
    split = dict(ops)["token stacks"]
    assert lua.is_sendable(split) and "5a17e9" in split and "Intuition Token" in split and "-3.11" in split and "20.62" in split


STACK = """
local stack = mkobj({guid = '5a17e9', type = 'Custom_Token_Stack', name = 'Intuition Token', pos = {x = -3.12, y = 1.76, z = 17.99}})
stack.qty = 2
stack.getQuantity = function() return stack.qty end
stack.takeObject = function(t)
  stack.qty = stack.qty - 1
  return mkobj({guid = 'new1', type = 'Custom_Token', name = 'Intuition Token', pos = t.position, rot = t.rotation})
end
"""
SPLIT_ROW = (("5a17e9", "Intuition Token", (-3.11, 1.96, 20.62), (0, 90, 0)),)


def tokens(rt):  # noqa: F811
    return sorted(o.guid for o in rt.globals().getObjects().values() if o.name == "Intuition Token")


def test_a_second_preparar_places_the_token_that_is_already_loose_instead_of_splitting_again(rt):  # noqa: F811
    rt.execute(STACK)
    first = run(rt, lua.split_token_stack(list(SPLIT_ROW)))
    assert first == {"split": ["new1"], "placed": []} and tokens(rt) == ["5a17e9", "new1"]
    rt.execute("getObjectFromGUID('new1').setPosition({x = 9, y = 1, z = 9})")             # the player moved it away
    again = run(rt, lua.split_token_stack(list(SPLIT_ROW)))
    assert again == {"split": [], "placed": ["new1"]}, "no third token is created"
    spot = rt.globals().getObjectFromGUID("new1").pos
    assert (round(spot.x, 2), round(spot.z, 2)) == (-3.11, 20.62) and tokens(rt) == ["5a17e9", "new1"]
    assert rt.globals().getObjectFromGUID("5a17e9").qty == 1


def test_a_stack_of_one_with_nothing_loose_changes_nothing(rt):  # noqa: F811
    rt.execute(STACK + "stack.qty = 1")
    assert run(rt, lua.split_token_stack(list(SPLIT_ROW))) == {"split": [], "placed": []}


def test_cleaning_the_table_destroys_the_token_split_off_the_stack(rt):  # noqa: F811
    """Its GUID is new, so the cleaning knows it by nickname."""
    rt.execute(STACK)
    run(rt, lua.split_token_stack(list(SPLIT_ROW)))
    assert tokens(rt) == ["5a17e9", "new1"]
    res = run(rt, player_setup.clear_script(raw()))
    assert res["objects"] >= 1 and "new1" not in tokens(rt), "no stray Intuition token after Limpiar mesa"


def test_the_layout_goes_before_the_face_ops_in_the_closing_batch(monkeypatch):
    names = []
    monkeypatch.setattr(table_reset, "take_character_cards", lambda *a: None)
    monkeypatch.setattr(table_reset, "_facing_args", lambda s: [])
    monkeypatch.setattr(table_reset.lua, "flip_decks_down", lambda *a: "flip")
    monkeypatch.setattr(table_reset, "layout_ops", lambda s, r: ([("layout", "L")], []))
    monkeypatch.setattr(table_reset, "start_face_ops", lambda c, s: [("intuition tokens", "F")])
    monkeypatch.setattr(table_reset, "batch", lambda client, named, *a: names.extend(n for n, _ in named) or {})

    class FakeSession:
        cfg = type("C", (), {"deck_radius": 1.0})()

        def resolve_pieces(self): pass
        def load_identities(self): pass
        def _reset_table(self, g): pass
        def _fresh_game(self): return None

    class Client:
        def call_lua(self, *a, **k): return {}
    table_reset.reset_cards_and_pieces(Client(), FakeSession(), {}, True)
    assert names == ["decks", "layout", "intuition tokens"], "the slot's rotation must not decide the face: the face op is last"


@pytest.mark.parametrize("slot_z, start", [(0, 0), (180, 0), (180, 180)])
def test_the_final_face_is_the_start_face_whatever_rotation_the_slot_has(rt, slot_z, start):  # noqa: F811
    """Lays the token at a slot with rot Z `slot_z` and then runs the face op: it ends at the START face (inactive 0)."""
    rt.execute(f"mkobj({{guid = '5a17e9', type = 'Custom_Token', name = 'Intuition Token', pos = {{x = 0, y = 1, z = 0}}, rot = {{x = 0, y = 90, z = {start}}}}})")
    run(rt, lua.arrange_objects([(("5a17e9",), (-3.12, 1.96, 17.99), (0, 90, slot_z))]))
    assert rt.globals().getObjectFromGUID("5a17e9").rot.z == slot_z
    faces = ABE.token_faces["intuition"]["faces"]
    run(rt, lua.set_intuition_tokens(table_reset.INTUITION_TOKEN, "5a17e9", float(faces["active"]), float(faces["inactive"]), 0, ["White"]))
    assert rt.globals().getObjectFromGUID("5a17e9").rot.z % 360 == faces["inactive"]
