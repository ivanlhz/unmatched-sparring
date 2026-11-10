"""F-YT-BAG through the pre-game gate: the player drops the REAL nine-object Yennefer & Triss bag (GUIDs and types of the tournament
save, `test_yennefer_triss_bag.REAL_BAG`), Prepare asks on the panel which heroine leads, and the setup takes only that variant's five
objects out of the nine. The fake table is the one of `test_player_setup` (its unpack follows the real script's rules, including the
list of objects a dropped bag may still hold when it is destroyed)."""
from __future__ import annotations

import pytest

from sparring import table_reset
from sparring.tts.hero_table import load_hero_table
from test_play import live  # noqa: F401
from test_player_setup import Obj, SetupTable, live_with, prepared_ok, start
from test_table_reset import cfg_file, finish, press, run_main, shown, wait_for  # noqa: F401
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
        other = TY if human == YT else YT
        mine, theirs = (load_hero_table(s).character_card_id for s in (human, other))
        assert not any(table.deck_chars.values()), "the 32-card shared deck ends as the 30 cards of the range"
        assert mine in table.chars_laid and theirs not in table.chars_laid, "ONE character card of the shared deck lies out: the chosen one"
        assert table.chars_destroyed == [theirs], "the other heroine's card is destroyed, not left in the deck or on the table"
        assert hidden(table, "btn_choice_1") and hidden(table, "btn_choice_2"), "the question is gone from the panel"
    finally:
        finish(stop, thread, result)


def answer(fake, i):
    fake.push({"messageID": 4, "customMessage": {"event": "choice", "i": i}})


def test_clean_table_cancels_an_open_question(live, monkeypatch, cfg_file, tmp_path):  # noqa: F811
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
        answer(fake, 1)
        assert not wait_for(lambda: table.unpacked, 1.0), "an answer with no question open does nothing"
    finally:
        finish(stop, thread, result)


def test_an_answer_with_no_question_open_does_not_prepare_a_table_that_could_be_prepared(live, monkeypatch, cfg_file, tmp_path):  # noqa: F811
    table, fake, ports = gate_with(live, monkeypatch, tmp_path, human="houdini")
    table.drop_bag("bigfoot", 7)
    table.drop_bag("houdini", -7)
    stop, thread, result = start((table, fake, ports), cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        answer(fake, 1)
        assert not wait_for(lambda: table.unpacked or shown(table, "btn_start") == (True, True), 1.5), "a stray click prepared the table"
        press(fake, "prepare_table")
        assert prepared_ok(table, fake), "the same table does prepare when Prepare is pressed"
    finally:
        finish(stop, thread, result)


def test_an_answer_outside_the_buttons_keeps_the_question_open(live, monkeypatch, cfg_file, tmp_path):  # noqa: F811
    table, fake, ports = gate_with(live, monkeypatch, tmp_path, human=TY)
    table.drop_bag("bigfoot", 7)
    drop_real_bag(table, -7)
    stop, thread, result = start((table, fake, ports), cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_choice_1") == (True, True))
        for bad in (3, 0, "x"):
            answer(fake, bad)
        assert not wait_for(lambda: table.unpacked, 1.0)
        answer(fake, 2)
        assert prepared_ok(table, fake), "the question was still open for the real answer"
    finally:
        finish(stop, thread, result)


def test_the_bot_leads_with_the_variant_the_configuration_fixes_not_the_last_hero_it_played(live, monkeypatch, cfg_file, tmp_path):  # noqa: F811
    table, fake, ports = live_with(SetupTable(TY, "bigfoot"), live, monkeypatch, tmp_path)
    table.drop_map("bprd-hq")
    real = table_reset.Gate.on_prepare

    def after_a_game_with_someone_else(self, *a, **k):
        self.cfg.raw["bot_hero"] = "bigfoot"                      # what the resolved configuration says after a previous Prepare
        return real(self, *a, **k)
    monkeypatch.setattr(table_reset.Gate, "on_prepare", after_a_game_with_someone_else)
    drop_real_bag(table, 7)
    table.drop_bag("bigfoot", -7)
    stop, thread, result = run_main((table, fake, ports), cfg_file, tmp_path, bot_hero=TY, human_hero="auto")
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert prepared_ok(table, fake), table.broadcasts[-6:]
        assert "Bot: Triss" in " ".join(table.broadcasts) and hidden(table, "btn_choice_1"), "the bot's half is never asked"
    finally:
        finish(stop, thread, result)


def test_a_hero_of_the_box_fixed_in_the_configuration_is_not_asked_and_is_the_one_that_starts(live, monkeypatch, cfg_file, tmp_path):  # noqa: F811
    table, fake, ports = gate_with(live, monkeypatch, tmp_path, human=TY)
    table.drop_bag("bigfoot", 7)
    drop_real_bag(table, -7)
    stop, thread, result = run_main((table, fake, ports), cfg_file, tmp_path, bot_hero="auto", human_hero=TY)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert prepared_ok(table, fake), table.broadcasts[-6:]
        assert hidden(table, "btn_choice_1") and "Tu: Triss" in " ".join(table.broadcasts)
        assert {o.guid for o in table.world if o.guid in REAL_BAG} == set(load_hero_table(TY).all_guids())
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
