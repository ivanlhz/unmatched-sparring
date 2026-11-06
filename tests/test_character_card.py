"""The deck that comes out of a hero's bag holds the 30 cards of the deck PLUS the character card (31, face up, the
character card on top). `ours` needs every card of a Deck in range, so the cleaning takes the character card out first and
leaves it face up beside the deck. The Lua tests run the builder with lupa on the stub table; the gate tests go through
`play.main` against the fake table, whose bag decks hold the character card like the real ones."""
from __future__ import annotations

import dataclasses
import json

import pytest

from sparring import table_reset
from sparring.cards import repo_toplevel
from sparring.play import load_config
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from test_official_table_gate import official  # noqa: F401
from test_play import live  # noqa: F401
from test_review9 import BOT_ID, SCOPE, rt, run  # noqa: F401
from test_table_reset import cfg_file, client_for, codes, finish, gate_live, press, run_main, session_for, shown, wait_for  # noqa: F401

MEDUSA = load_hero_table("medusa")
DEST = (7.28, 2.5, 18.93)
SIDE = ("d42056", lua.BOT_CARD_IDS, BOT_ID, MEDUSA.character_card_id, DEST)
EVERYWHERE = dataclasses.replace(SCOPE, everywhere=True)
PLAN = ("d42056", (7.28, 13.93), lua.BOT_CARD_IDS, BOT_ID, None)


def bag_deck(rt, top=True, face_down=False):
    """Medusa's deck as it leaves the bag: 30 cards and the character card (on top or in the middle), face up."""
    rt.execute(f"""
local cards = {{}}
for i = 0, 29 do table.insert(cards, {{cid = 17600 + i, guid = 'm' .. i, owner = 'medusa'}}) end
local char = {{cid = {MEDUSA.character_card_id}, guid = 'char1', owner = 'medusachar'}}
if {str(top).lower()} then table.insert(cards, 1, char) else table.insert(cards, 15, char) end
mkobj({{guid = 'd42056', type = 'Deck', cards = cards, is_face_down = {str(face_down).lower()}, rot = {{x = 0, y = 90, z = 0}},
       pos = {{x = 7.28, y = 1, z = 13.93}}}})
""")


def deck_ids(rt):
    d = rt.globals().getObjectFromGUID("d42056")
    return [d.cards[i].cid for i in range(1, len(d.cards) + 1)]


def test_a_31_card_deck_is_foreign_to_every_card_write_until_the_character_card_is_out(rt):  # noqa: F811
    bag_deck(rt, face_down=True)
    assert run(rt, lua.reset_plan([PLAN], scope=EVERYWHERE))[0]["deck"] is False, "the live bug: the deck is not found"
    assert run(rt, lua.take_character_cards([SIDE])) == [{"found": True, "taken": True}]
    assert run(rt, lua.reset_plan([PLAN], scope=EVERYWHERE)) == [{"deck": True, "loose": 0, "total": 30}]


@pytest.mark.parametrize("top", [True, False])
def test_the_character_card_is_found_on_top_or_anywhere_and_laid_face_up_at_the_offset(rt, top):  # noqa: F811
    bag_deck(rt, top=top)
    run(rt, lua.take_character_cards([SIDE]))
    assert len(deck_ids(rt)) == 30 and MEDUSA.character_card_id not in deck_ids(rt)
    card = rt.globals().getObjectFromGUID("char1")
    assert card.type == "Card" and card.cid == MEDUSA.character_card_id
    assert (card.pos.x, card.pos.y, card.pos.z) == DEST


def test_a_second_press_finds_the_character_card_gone_and_changes_nothing(rt):  # noqa: F811
    bag_deck(rt)
    run(rt, lua.take_character_cards([SIDE]))
    moved = rt.globals().getObjectFromGUID("char1").moved_count
    assert run(rt, lua.take_character_cards([SIDE])) == [{"found": True, "taken": False}]
    assert len(deck_ids(rt)) == 30 and rt.globals().getObjectFromGUID("char1").moved_count == moved


def test_a_deck_with_a_foreign_card_is_never_opened_even_if_it_holds_the_character_card_id(rt):  # noqa: F811
    rt.execute("""
mkobj({guid = 'alien', type = 'Deck', pos = {x = 7.28, y = 1, z = 13.93},
       cards = {{cid = 302, guid = 'a1', owner = 'other'}, {cid = 17601, guid = 'a2', owner = 'other'},
                {cid = 17602, guid = 'a3', owner = 'medusa'}}})
""")
    assert run(rt, lua.take_character_cards([SIDE])) == [{"found": False, "taken": False}]
    assert len(rt.globals().getObjectFromGUID("alien").cards) == 3


def test_a_loose_character_card_is_not_part_of_any_count_and_the_gathering_never_takes_it(rt):  # noqa: F811
    bag_deck(rt, face_down=True)
    run(rt, lua.take_character_cards([SIDE]))
    plan = run(rt, lua.reset_plan([PLAN], scope=EVERYWHERE))
    assert plan == [{"deck": True, "loose": 0, "total": 30}], "the loose character card is not a loose card of the deck"
    res = run(rt, lua.reset_deck("d42056", (7.28, 13.93), lua.BOT_CARD_IDS, identity=BOT_ID, scope=EVERYWHERE))
    assert res == {"deck": True, "quantity": 30}
    card = rt.globals().getObjectFromGUID("char1")
    assert card.type == "Card" and (card.pos.x, card.pos.z) == (DEST[0], DEST[2]) and card.moved_count is None


def test_the_new_script_is_a_registered_builder_and_asks_for_one_or_two_sides():
    assert lua.is_sendable(lua.take_character_cards([SIDE]))
    for bad in ([], [SIDE, SIDE, SIDE]):
        with pytest.raises(TypeError):
            lua.take_character_cards(bad)


def test_the_character_card_offset_leaves_the_deck_radius_and_both_discard_zones():
    raw = json.loads((repo_toplevel() / "config" / "table.json").read_text(encoding="utf-8"))
    dx, dz = table_reset.CHARACTER_CARD_OFFSET
    assert (dx * dx + dz * dz) ** 0.5 > raw.get("deck_radius", lua.DECK_RADIUS) + 2.0
    cx, cz, sx, sz, _ = raw["bot_discard_bounds"]
    hz = raw["human_discard_zone_spawn"]
    zones = [(cx, cz, sz / 2, sx / 2), (hz["position"][0], hz["position"][2], hz["scale"][2] / 2, hz["scale"][0] / 2)]
    for key in ("bot_deck_spot", "human_deck_spot"):
        x, z = raw[key][0] + dx, raw[key][1] + dz
        assert not any(abs(x - zx) <= hw and abs(z - zz) <= hd for zx, zz, hw, hd in zones), key


# ---------- the gate ----------
@pytest.mark.gate
def test_a_fresh_table_from_the_bags_ends_ready_with_30_card_face_down_decks_and_the_character_card_loose_beside_each(
        official, cfg_file, tmp_path):  # noqa: F811
    table, fake, _ = official
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True)), table.broadcasts[-5:]
        assert table.bag_decks_seen and not table.char_in_deck and not table.deck_face_up
        assert len(table.bot_deck) == 30
        dx, dz = table_reset.CHARACTER_CARD_OFFSET
        cfg = load_config(cfg_file())
        spots = (cfg.raw["bot_deck_spot"], cfg.raw["human_deck_spot"])
        assert sorted(table.char_loose) == sorted((x + dx, 2.5, z + dz) for x, z in spots)
        assert "take_character_cards" in table.sent
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_decks_already_unpacked_with_31_cards_face_up_are_fixed_by_pressing_again(gate_live, cfg_file, tmp_path):  # noqa: F811
    table, fake, _ = gate_live
    table.hero_bag_decks()
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True)), "31 cards face up is not a ready table"
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True)), table.broadcasts[-5:]
        assert not table.char_in_deck and not table.deck_face_up and len(table.bot_deck) == 30
        assert len(table.char_loose) == 2
    finally:
        finish(stop, t, result)


def test_the_audit_does_not_flag_the_loose_character_cards(gate_live, cfg_file):  # noqa: F811
    table, fake, ports = gate_live
    table.make_ready()
    table.char_loose = [(7.28, 2.5, 18.93), (-4.6, 2.5, 18.67)]
    client = client_for(gate_live)
    session = session_for(client, cfg_file())
    assert codes(table_reset.audit(client, session)) == []
