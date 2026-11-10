"""F-YT-BAG through the pre-game gate: the player drops the REAL nine-object Yennefer & Triss bag (GUIDs and types of the tournament
save, `test_yennefer_triss_bag.REAL_BAG`), Prepare asks on the panel which heroine leads, and the setup takes only that variant's five
objects out of the nine. The fake table is the one of `test_player_setup` (its unpack follows the real script's rules, including the
list of objects a dropped bag may still hold when it is destroyed)."""
from __future__ import annotations

import pytest

from sparring.tts.hero_table import load_hero_table
from test_play import live  # noqa: F401
from test_player_setup import Obj, SetupTable, live_with, prepared_ok, start
from test_table_reset import cfg_file, finish, press, shown, wait_for  # noqa: F401
from test_yennefer_triss_bag import REAL_BAG, TY, YT

pytestmark = pytest.mark.gate


def drop_real_bag(table, x: float, guid: str = "copyyt") -> Obj:
    obj = Obj("bag", guid, slug=YT, x=x, z=30.0, guids=list(REAL_BAG))
    table.world.append(obj)
    return obj


def gate_with(live, monkeypatch, tmp_path, human=TY):  # noqa: F811
    """The fake table for Bigfoot (bot) against `human`; its panel writes are also kept as scripts, to read the button captions."""
    table, fake, ports = live_with(SetupTable("bigfoot", human), live, monkeypatch, tmp_path)
    table.panel_scripts = []
    real = table.do_set_panel
    table.do_set_panel = lambda s: (table.panel_scripts.append(s), real(s))[1]
    table.drop_map("bprd-hq")
    return table, fake, ports


def hidden(table, button) -> bool:
    return shown(table, button) in (None, (False, False))


@pytest.mark.parametrize("answer, human", [(1, YT), (2, TY)])
def test_the_panel_asks_which_heroine_leads_and_the_setup_takes_only_her_five(live, monkeypatch, cfg_file, tmp_path, answer, human):  # noqa: F811
    table, fake, ports = gate_with(live, monkeypatch, tmp_path, human)
    table.drop_bag("bigfoot", 7)
    drop_real_bag(table, -7)
    stop, thread, result = start((table, fake, ports), cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_choice_1") == (True, True)), table.broadcasts[-4:]
        assert shown(table, "btn_choice_2") == (True, True) and hidden(table, "btn_choice_3")
        assert shown(table, "btn_prep") == (False, False) and shown(table, "btn_start") == (False, False)
        captions = " ".join(table.panel_scripts)
        assert '"btn_choice_1", "text", "Lidera Yennefer"' in captions and '"btn_choice_2", "text", "Lidera Triss"' in captions
        assert table.unpacked == 0 and sorted(o.guid for o in table.world if o.kind == "bag") == ["copybigfoot", "copyyt"], \
            "nothing is taken from any bag until the player answers"
        fake.push({"messageID": 4, "customMessage": {"event": "choice", "i": float(answer)}})
        assert prepared_ok(table, fake), table.broadcasts[-6:]
        assert f"Tu: {'Yennefer' if human == YT else 'Triss'}" in " ".join(table.broadcasts)
        placed = {o.guid for o in table.world if o.guid in REAL_BAG}
        assert placed == set(load_hero_table(human).all_guids()), "exactly the chosen variant's five of the nine are out"
        assert not [o for o in table.world if o.guid == "copyyt"], "the dropped copy goes once only the other heroine is left in it"
        assert hidden(table, "btn_choice_1") and hidden(table, "btn_choice_2"), "the question is gone from the panel"
    finally:
        finish(stop, thread, result)


def test_clean_table_cancels_an_open_question_and_a_stray_answer_does_nothing(live, monkeypatch, cfg_file, tmp_path):  # noqa: F811
    table, fake, ports = gate_with(live, monkeypatch, tmp_path)
    table.drop_bag("bigfoot", 7)
    drop_real_bag(table, -7)
    stop, thread, result = start((table, fake, ports), cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_choice_1") == (True, True))
        press(fake, "clean_table")
        assert wait_for(lambda: hidden(table, "btn_choice_1") and table.cleared == 1)
        fake.push({"messageID": 4, "customMessage": {"event": "choice", "i": 1}})
        assert not wait_for(lambda: shown(table, "btn_start") == (True, True), 1.0)
        assert table.unpacked == 0
    finally:
        finish(stop, thread, result)


def test_the_box_on_both_halves_is_refused_in_the_chat_and_nothing_is_asked_or_touched(live, monkeypatch, cfg_file, tmp_path):  # noqa: F811
    table, fake, ports = gate_with(live, monkeypatch, tmp_path)
    drop_real_bag(table, 7, "copyA")
    drop_real_bag(table, -7, "copyB")
    stop, thread, result = start((table, fake, ports), cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: "mazo compartido" in " ".join(table.broadcasts)), table.broadcasts[-4:]
        assert hidden(table, "btn_choice_1") and table.unpacked == 0
        assert len([o for o in table.world if o.kind == "bag"]) == 2
    finally:
        finish(stop, thread, result)
