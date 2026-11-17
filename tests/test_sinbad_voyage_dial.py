"""Sinbad's Voyage dial on the table (FakeTTS, batch mode): the dial of the bag (`counter_dials.voyage`, `session_counters`) shows the VOYAGE
cards of Sinbad's discard pile after ANY change of it, not only after an effect of the bot: a hand-limit discard, an attack, an effect
of the rival (Fleeting Moments) and Voyage Home taking cards back. Live bug 17/11: the dial was never written (only Hellboy's destiny
and Ciri's Source were), so it stayed at 0 with four VOYAGE cards in the discard."""
from __future__ import annotations

import json

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, human_attack, human_hand
from test_e2_human_cards import put_adjacent
from test_sinbad_human import TRAINING, VOYAGES, bot_defends_with_nothing_plain, bots_attack, pile, run_bot_attack
from test_human_pile_to_hand import HandTable

VOYAGE = "voyage"
DIAL = "10bbcb"


def shown(table):
    return table.dials[DIAL]["value"]


def voyages_in_discard(game):
    return sum(1 for c in game.players[0].discard if VOYAGE in c.tags)


def test_the_voyage_dial_is_in_the_session_config_and_starts_at_zero(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "sinbad", "hellboy", ("Exploit",), table_cls=HandTable)
    try:
        assert cfg.session_config().counter_dials == {VOYAGE: DIAL}
        assert DIAL in session.guids_in_use() and [DIAL] in session.guid_groups()
        assert shown(table) == 0 and session.counter_seen == {}
        assert session._write_dials() and shown(table) == 0 and session.counter_seen == {VOYAGE: 0}
    finally:
        client.close()
        fake.close()


def test_a_hand_limit_discard_of_voyage_cards_moves_the_dial(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "sinbad", "hellboy", ("Exploit",), table_cls=HandTable)
    try:
        st = game.players[0]
        voyage = [c for c in st.full_set if VOYAGE in c.tags]
        assert len(voyage) == 7
        table.bot_hand = [c.card_id for c in voyage]
        table.bot_deck = [c.card_id for c in st.full_set if c.card_id not in table.bot_hand]
        session.read_bot_hand()
        session.snap = None
        assert shown(table) == 0
        bot_turn(session, table, [])
        assert voyages_in_discard(game) >= 1                         # the hand limit sent some to the pile
        assert shown(table) == game.counter(0, VOYAGE) == voyages_in_discard(game)
        assert session.counter_seen[VOYAGE] == voyages_in_discard(game)
    finally:
        client.close()
        fake.close()


def test_a_voyage_card_played_in_an_attack_moves_the_dial(tmp_path):
    title = "Voyage to the Island That Was a Whale"
    session, table, game, fake, cfg, client = bots_attack(tmp_path, title)
    try:
        pile(session, table, game, 0, VOYAGES[1], VOYAGES[5])
        run_bot_attack(session, table, game, title)
        assert game.counter(0, VOYAGE) == 3
        assert shown(table) == 3
    finally:
        client.close()
        fake.close()


def test_voyage_cards_taken_back_by_voyage_home_lower_the_dial(tmp_path):
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "Voyage Home")
    try:
        pile(session, table, game, 0, VOYAGES[1], VOYAGES[5])
        session._write_dials()
        assert shown(table) == 2
        run_bot_attack(session, table, game, "Voyage Home")
        assert game.counter(0, VOYAGE) == 1                         # only Voyage Home itself is left on the pile
        assert shown(table) == 1
    finally:
        client.close()
        fake.close()


def test_a_rivals_random_discard_of_a_voyage_card_moves_the_dial(tmp_path):
    """Fleeting Moments of the human's Liz: the bot, holding only VOYAGE cards, discards one of them."""
    session, table, game, fake, cfg, client = build(tmp_path, "sinbad", "liz-sherman", (VOYAGES[1], VOYAGES[2], VOYAGES[3]),
                                                    table_cls=HandTable)
    try:
        put_adjacent(game, table, cfg, "liz", "sinbad")
        human_hand(table, game, "Fleeting Moments", "Pyrotechnics")
        human_attack(session, table, game, "liz", "sinbad", "Fleeting Moments")
        click(session, table, Event.REVEAL)
        assert voyages_in_discard(game) == 1, [c.title for c in game.players[0].discard]
        assert shown(table) == 1
    finally:
        client.close()
        fake.close()


def resumed(tmp_path, saved, dial_now):
    """A new process (a second session on a fresh table) loads `saved` through `load_dict`; the table shows `dial_now`; one read follows."""
    (tmp_path / "b").mkdir(exist_ok=True)
    session, table, game, fake, cfg, client = build(tmp_path / "b", "sinbad", "hellboy", ("Exploit",), table_cls=HandTable)
    try:
        session.load_dict(saved)
        game = session.game                                         # the saved game, four VOYAGE cards in the bot's discard
        table.bot_discard = [c.card_id for c in game.players[0].discard]
        table.bot_hand = [c.card_id for c in game.players[0].hand]
        table.bot_deck = [c.card_id for c in game.players[0].deck]
        table.dials[DIAL]["value"] = dial_now
        bot_turn(session, table, [])
        return shown(table), dict(session.counter_seen)
    finally:
        client.close()
        fake.close()


def saved_with_four(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "sinbad", "hellboy", ("Exploit",), table_cls=HandTable)
    try:
        pile(session, table, game, 0, VOYAGES[0], VOYAGES[1], VOYAGES[2], VOYAGES[3])
        assert session._write_dials() and shown(table) == 4
        return json.loads(json.dumps(session.to_dict()))
    finally:
        client.close()
        fake.close()


def test_a_resumed_save_made_before_the_dial_existed_writes_the_count(tmp_path):
    saved = saved_with_four(tmp_path)
    saved["dials_written"].pop(DIAL, None)                         # the old save knows nothing of the dial
    assert resumed(tmp_path, saved, 0) == (4, {VOYAGE: 4})


def test_a_resumed_save_that_already_has_the_dial_in_dials_written_rewrites_it(tmp_path):
    saved = saved_with_four(tmp_path)
    assert saved["dials_written"][DIAL] == 4
    assert resumed(tmp_path, saved, 4) == (4, {VOYAGE: 4})         # the table already shows it: counter_seen is rebuilt
    assert resumed(tmp_path, saved, 0) == (0, {})                  # the dial shows 0, neither what the save wrote (4) nor what is due (4): a hand edit, respected like any other dial


def test_the_chat_names_the_dials_in_the_catalog_without_accents():
    from sparring import session_counters
    assert session_counters.name_of("source") == "Source" and session_counters.name_of("voyage") == "Viajes"
    assert session_counters.name_of("other") == "Other"            # no catalog entry: the counter's own name


def test_the_humans_sinbad_dial_follows_his_own_pile(tmp_path):
    """Sinbad on the human's side: the dial counts the VOYAGE cards of the pile the human plays to; Voyage Home takes them back."""
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", "sinbad", (TRAINING,), table_cls=HandTable)
    try:
        assert cfg.session_config().counter_dials == {VOYAGE: DIAL}
        bot_defends_with_nothing_plain(session)
        put_adjacent(game, table, cfg, "sinbad", "hellboy")
        human_hand(table, game, "Voyage Home", "Exploit")
        pile(session, table, game, 1, VOYAGES[1], VOYAGES[5])
        assert session._write_dials() and shown(table) == game.counter(1, VOYAGE) == 2
        human_attack(session, table, game, "sinbad", "hellboy", "Voyage Home")
        click(session, table, Event.REVEAL)
        click(session, table, Event.END_ACTION)
        assert game.counter(1, VOYAGE) == 1 and shown(table) == 1
    finally:
        client.close()
        fake.close()



def test_the_table_snapshot_reads_the_voyage_dial(tmp_path):
    """Live bug 17/11 (game 4): Prepare always failed with "the reset did not leave the table clean". In batch mode the reset
    checks the dials from the snapshot, which only read the life and destiny dials: the Voyage dial came back as not found."""
    session, table, game, fake, cfg, client = build(tmp_path, "sinbad", "hellboy", ("Exploit",), table_cls=HandTable)
    try:
        assert DIAL in session.snapshot_spec().dials
    finally:
        client.close()
        fake.close()
