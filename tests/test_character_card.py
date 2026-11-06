"""The deck that comes out of a hero's bag holds the 30 cards of the deck PLUS the character card (31, face up, the
character card on top). `ours` needs every card of a Deck in range, so the cleaning takes the character card out first and
leaves it face up beside the deck. The Lua tests run the builder with lupa on the stub table; the gate tests go through
`play.main` against the fake table, whose bag decks hold the character card like the real ones."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from sparring import map_setup, table_layout, table_reset
from sparring.play import load_config
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from test_official_table_gate import drag_prepared_pair, official  # noqa: F401
from test_player_setup import medusa_hellboy_out, medusa_live, write_setups  # noqa: F401
from test_play import live  # noqa: F401
from test_review9 import BOT_ID, SCOPE, rt, run  # noqa: F401
from test_table_reset import cfg_file, client_for, codes, finish, gate_live, press, run_main, session_for, shown, wait_for  # noqa: F401

MEDUSA = load_hero_table("medusa")
DEST = (5.28, 1.81, 15.0)
SIDE = ("d42056", lua.BOT_CARD_IDS, BOT_ID, MEDUSA.character_card_id, DEST, (0, 90, 0))
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


# ---------- the layout ----------
def config_raw() -> dict:
    return json.loads((Path(__file__).resolve().parent.parent / "config" / "table.json").read_text(encoding="utf-8"))


def character_slots():
    return [table_layout.character_slot(config_raw(), side) for side in ("bot", "human")]


def lifted(slot):
    return (slot.pos[0], slot.pos[1] + table_layout.SETTLE_LIFT, slot.pos[2]), slot.rot


def expected_layout(raw=None, pair=("medusa", "hellboy")):
    """{first GUID: (position, rotation)} the gate must leave, from the configuration and the hero data."""
    raw = raw or config_raw()
    out = {}
    for side, slug in zip(("bot", "human"), pair):
        for p in table_layout.plan(raw, side, load_hero_table(slug)).placements:
            out[p.guids[0]] = lifted(p.slot)
    return out


IVAN = {  # the table as Ivan arranged it by hand (TS_AutoSave 5/11 09:37): GUID -> (pos, rot)
    "d42056": ((5.13, 1.76, 17.71), (0, 90, 180)), "bcd809": ((2.49, 1.66, 14.83), (0, 90, 0)),
    "04b2c9": ((4.90, 2.89, 25.91), (0, 0, 0)), "328e52": ((2.18, 1.72, 22.73), (0, 0, 0)),
    "33c5ec": ((3.85, 1.72, 23.05), (0, 0, 0)), "01eb1f": ((5.77, 1.72, 22.21), (0, 0, 0)),
    "00dc9a": ((-6.70, 1.76, 17.55), (0, 270, 180)), "046660": ((-3.96, 1.66, 15.12), (0, 270, 0)),
    "18c384": ((-3.77, 1.66, 17.68), (0, 270, 0)), "e17c66": ((-4.28, 1.66, 20.19), (0, 270, 0)),
    "1644a3": ((-6.96, 1.67, 15.01), (0, 90, 180)), "f9789a": ((-3.57, 1.59, 25.33), (0, 0, 0)),
    "e33604": ((-5.50, 1.72, 26.69), (0, 0, 0)),
}


def test_the_layout_in_the_configuration_is_the_table_ivan_arranged():
    got = expected_layout()
    assert sorted(got) == sorted(IVAN)
    for guid, (pos, rot) in IVAN.items():
        assert got[guid] == ((pos[0], pos[1] + table_layout.SETTLE_LIFT, pos[2]), tuple(float(v) for v in rot)), guid
    raw = config_raw()
    assert raw["bot_deck_spot"] == [5.13, 17.71] and raw["human_deck_spot"] == [-6.7, 17.55], "the decks are found where they lie"
    bprd = map_setup.setup_for("bprd-hq")
    assert bprd.position == (0.07, 1.64, -1.93) and bprd.scale == 1.10 and bprd.layout == raw["layout"]
    assert [s.pos for s in character_slots()] == [(5.28, 1.61, 15.0), (-6.73, 1.61, 15.07)]
    assert [s.rot for s in character_slots()] == [(0.0, 90.0, 0.0), (0.0, 270.0, 0.0)]


def test_another_pair_on_the_same_sides_lands_in_the_same_slots():
    raw = config_raw()
    plan = table_layout.plan(raw, "bot", load_hero_table("hellboy"))
    assert [(p.role, p.guids[0]) for p in plan.placements] == [
        ("deck", "00dc9a"), ("dial", "046660"), ("sidekick_dials", "18c384"), ("counter_dials", "e17c66"),
        ("tokens", "1644a3"), ("pieces", "f9789a"), ("pieces", "e33604")]
    assert plan.placements[0].slot == table_layout.slots(raw, "bot")["deck"]
    assert plan.unplaced == [], "the live bug: Hellboy's extra dials and tile had no slot on the half Medusa was calibrated on"
    by_role = {p.role: p.slot for p in plan.placements}
    human = table_layout.slots(raw, "human")
    side_dial = by_role["sidekick_dials"]
    assert side_dial.pos == pytest.approx((2.30, 1.66, 17.39)), "at the human sidekick's offset from its dial, x flipped"
    assert side_dial.rot == (0.0, 90.0, 0.0)
    deck = table_layout.slots(raw, "bot")["deck"].pos
    assert abs(side_dial.pos[0] - deck[0]) > 2.5, "the live bug: Bess's dial landed on Houdini's deck"
    assert by_role["tokens"].rot == table_layout.mirrored(human["tokens"][0]).rot == (0.0, 270.0, 180.0)


def test_a_side_with_its_own_slots_does_not_borrow():
    raw = config_raw()
    plan = table_layout.plan(raw, "human", load_hero_table("hellboy"))
    assert plan.unplaced == []
    assert [p.slot for p in plan.placements if p.role == "sidekick_dials"] == table_layout.slots(raw, "human")["sidekick_dials"]


def test_a_slot_that_is_not_three_numbers_is_refused():
    raw = {"layout": {"bot": {"deck": {"pos": [1, 2], "rot": [0, 0, 0]}}}}
    with pytest.raises(ValueError):
        table_layout.slots(raw, "bot")


def test_arrange_objects_lays_the_first_guid_that_exists_at_the_exact_transform(rt):  # noqa: F811
    rt.execute("mkobj({guid = 'e6f06e', type = 'Custom_Token', pos = {x = 0, y = 1, z = 0}})\n"
               "mkobj({guid = 'held', type = 'Custom_Token', held_by_color = 'White'})")
    res = run(rt, lua.arrange_objects([(("f9789a", "e6f06e"), (-3.57, 1.79, 25.33), (0, 0, 0)),
                                       (("held",), (1, 1, 1), (0, 0, 0)), (("gone",), (1, 1, 1), (0, 0, 0))]))
    assert res == {"placed": ["e6f06e"], "missing": ["held", "gone"]}
    o = rt.globals().getObjectFromGUID("e6f06e")
    assert (o.pos.x, o.pos.y, o.pos.z) == (-3.57, 1.79, 25.33)
    assert lua.is_sendable(lua.arrange_objects([(("a",), (0, 0, 0), (0, 0, 0))]))


# ---------- the gate ----------
@pytest.mark.gate
def test_a_fresh_table_from_the_bags_ends_ready_with_30_card_face_down_decks_and_the_character_card_loose_beside_each(
        official, cfg_file, tmp_path):  # noqa: F811
    table, fake, _ = official
    drag_prepared_pair(table)
    stop, t, result = run_main(official, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True)), table.broadcasts[-5:]
        assert table.bag_decks_seen and not table.char_in_deck and not table.deck_face_up
        assert len(table.bot_deck) == 30
        assert sorted(table.char_loose) == sorted(lifted(slot) for slot in character_slots())
        assert "take_character_cards" in table.sent
        assert table.arranged == expected_layout(), "every object ends at its slot, rotation included"
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_decks_already_unpacked_with_31_cards_face_up_are_fixed_by_pressing_prepare(medusa_live, cfg_file, tmp_path):  # noqa: F811
    table, fake, _ = medusa_live
    medusa_hellboy_out(table)
    table.hero_bag_decks()
    stop, t, result = run_main(medusa_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True)), "31 cards face up is not a ready table"
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True)), table.broadcasts[-5:]
        assert not table.char_in_deck and not table.deck_face_up and len(table.bot_deck) == 30
        assert table.arranged == expected_layout()
        assert sorted(table.char_loose) == sorted(lifted(slot) for slot in character_slots())
    finally:
        finish(stop, t, result)


def test_the_audit_does_not_flag_the_loose_character_cards(gate_live, cfg_file):  # noqa: F811
    table, fake, ports = gate_live
    table.make_ready()
    table.char_loose = [lifted(slot) for slot in character_slots()]
    client = client_for(gate_live)
    session = session_for(client, cfg_file())
    assert codes(table_reset.audit(client, session)) == []


@pytest.mark.gate
def test_an_object_without_a_slot_stays_and_the_chat_names_it(medusa_live, cfg_file, tmp_path):  # noqa: F811
    table, fake, _ = medusa_live
    medusa_hellboy_out(table)
    table.hero_bag_decks()
    raw = config_raw()
    layout = json.loads(json.dumps(raw["layout"]))
    layout["human"]["pieces"] = layout["human"]["pieces"][:1]
    layout["bot"]["pieces"] = layout["bot"]["pieces"][:1]     # else the human half borrows the bot's mirrored
    write_setups(map_setup.SETUPS_PATH, **{"bprd-hq": {"scale": 1.1, "position": [0.07, 1.64, -1.93], "rot_y": 270.0, "layout": layout}})
    stop, t, result = run_main(medusa_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True)), table.broadcasts[-5:]
        assert "e33604" not in table.arranged and "f9789a" in table.arranged
        assert "No he colocado estos objetos" in " ".join(table.broadcasts) and "e33604" in " ".join(table.broadcasts)
    finally:
        finish(stop, t, result)
