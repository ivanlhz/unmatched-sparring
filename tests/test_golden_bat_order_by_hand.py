"""The human's Sight Beyond Sight orders the BOT's top cards on the table (FakeTTS, batch mode; Ivan, 2026-11-08): the bot lays its
engine's top three face up in a row (not in the human's hand), the panel shows only Done, the human stacks them on the bot's deck
(the last one dropped ends on top) and the bot reads the deck top, checks it is exactly the cards it laid and records the order. A
wrong table changes nothing and says what is wrong; a resume says it again and never lays the cards twice. The Lua of the laying and
of the read is `deck_card_to_spot` / `peek_deck_top`, covered on the Lua stub in test_donatello_future_lua.py and test_jill_trent_lua.py."""
from __future__ import annotations

import json

import pytest

from sparring.tts import lua
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build, human_attack, human_hand, said, twin_session
from test_e2_human_cards import bot_defends_with_nothing, labels, put_adjacent
from test_jill_trent_human import JillTable


def table_rig(tmp_path, **over):
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", "golden-bat", ("Right Hand Of Doom", "Excalibur"),
                                                    table_cls=JillTable, **over)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


@pytest.fixture
def by_hand(tmp_path):
    yield from table_rig(tmp_path)


@pytest.fixture
def panel_rig(tmp_path):
    yield from table_rig(tmp_path, order_by_hand=False)


def play_sight_beyond_sight(session, table, game, cfg, monkeypatch):
    """The human attacks with Sight Beyond Sight and presses Reveal: the AFTER asks for the order of the bot's top three, engine order."""
    put_adjacent(game, table, cfg, "bat", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Sight Beyond Sight", "Skirmish")
    human_attack(session, table, game, "bat", "hellboy", "Sight Beyond Sight")
    top = [c.card_id for c in game.players[0].deck[:3]]
    table.bot_deck.sort(key=lambda i: i in top)           # the table's order is not the engine's: the three are not on its top
    return top, click(session, table, Event.REVEAL)


def test_the_three_cards_lie_face_up_in_a_row_off_the_human_hand_and_the_panel_shows_only_done(by_hand, monkeypatch):
    session, table, game, fake, cfg = by_hand
    top, msgs = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    assert table.row == top and not set(top) & set(table.bot_deck), "the engine's top three, by CardID, out of the physical deck"
    assert said(msgs, "he puesto mis 3 cartas de arriba boca arriba en la mesa")
    assert said(msgs, "la primera que pongas quedara debajo de las otras y la ultima, arriba")
    assert said(msgs, "pulsa Hecho"), msgs
    assert labels(session) == ["Hecho"] and not any("pulsa una de las opciones" in m for m in msgs)
    assert not set(top) & set(table.human_hand), "the cards are on the table, never in the human's hand (the bot reads it)"
    assert not any(s.startswith("-- sparring:deal_cards") for s in table.scripts)
    lays = [s for s in table.scripts if s.startswith("-- sparring:deck_card_to_spot")]
    wanted = [lua._xyz(at) for at in __import__("sparring.session_order", fromlist=["spots"]).spots(cfg.session_config(), 3)]
    assert len(lays) == 3 and all(w in s for w, s in zip(wanted, lays)), "one card per spot of the row at order_spot"
    assert session.order_row == {"key": session.effect_run.awaiting.key, "ids": top}


def test_the_last_card_dropped_ends_on_top_and_done_records_that_order_in_the_engine_and_its_pins(by_hand, monkeypatch):
    session, table, game, fake, cfg = by_hand
    top, _ = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    first, second, third = top
    table.stack(third, first, second)                    # dropped in the order: second, first, third (top)
    assert table.bot_deck[:3] == [third, first, second]
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert session.effect_run is None and session.order_row is None
    assert [c.card_id for c in game.players[0].deck[:3]] == [third, first, second], "the engine's deck is in the table's order"
    assert game.players[1].known.top_of_deck == [third, first, second]
    assert said(msgs, "Anoto el orden")
    session.read_bot_hand()
    assert [c.card_id for c in game.players[0].deck[:3]] == [third, first, second], "a reread of the table keeps the decided order"
    assert session.peek_pins["top"] == [third, first, second]


def test_a_card_left_on_the_table_is_named_and_nothing_moves_until_the_top_is_right(by_hand, monkeypatch):
    session, table, game, fake, cfg = by_hand
    top, _ = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    first, second, third = top
    table.stack(second, first)                           # the third stays on the table
    deck_before, row_before = list(table.bot_deck), list(table.row)
    titles = {c.card_id: c.title for c in game.players[0].full_set}
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert said(msgs, "Faltan encima de mi mazo: " + titles[third]) and said(msgs, "pulsa Hecho"), msgs
    assert session.effect_run is not None and session.order_row is not None, "the request keeps waiting"
    assert table.bot_deck == deck_before and table.row == row_before == [third], "the bot moved nothing"
    table.stack(third)                                   # corrected: the third goes on top of the two
    click(session, table, Event.CHOICE, {"i": 1})
    assert session.effect_run is None and [c.card_id for c in game.players[0].deck[:3]] == [third, second, first]


def test_an_extra_card_on_top_is_counted_but_never_named(by_hand, monkeypatch):
    session, table, game, fake, cfg = by_hand
    top, _ = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    first, second, third = top
    titles = {c.card_id: c.title for c in game.players[0].full_set}
    stray = next(i for i in table.bot_deck if titles[i] not in {titles[t] for t in top})     # a card of the deck, face down: its name would leak it
    table.bot_deck.remove(stray)
    table.stack(first, second)
    table.bot_deck.insert(0, stray)
    table.row.remove(third)                               # and the third is put somewhere else
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert said(msgs, "Faltan encima de mi mazo") and said(msgs, "Hay 1 carta(s) mas encima que no son las que puse"), msgs
    assert not said(msgs, titles[stray]), "a face-down card of the deck is counted, never named"
    assert session.effect_run is not None


def test_a_foreign_card_on_top_of_the_stack_is_a_mismatch_too(by_hand, monkeypatch):
    session, table, game, fake, cfg = by_hand
    top, _ = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    table.stack(*top)
    table.foreign = frozenset({99999})
    table.bot_deck.insert(0, 99999)                       # something that is not one of the bot's cards lies on the deck
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert said(msgs, "no estan justo las 3 cartas que puse en la mesa"), msgs
    assert session.effect_run is not None


def test_other_buttons_do_not_answer_while_the_cards_lie_on_the_table(by_hand, monkeypatch):
    session, table, game, fake, cfg = by_hand
    top, _ = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    msgs = click(session, table, Event.CHOICE, {"i": 2})
    assert said(msgs, "Ese boton no corresponde"), msgs
    assert session.effect_run is not None and table.row == top


def test_a_resume_says_it_again_and_never_lays_the_cards_twice(by_hand, monkeypatch):
    session, table, game, fake, cfg = by_hand
    top, _ = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["order_row"] == {"key": session.effect_run.awaiting.key, "ids": top}
    lays = len([s for s in table.scripts if s.startswith("-- sparring:deck_card_to_spot")])
    twin = twin_session(session, cfg, saved)
    msgs = twin.resume()
    assert said(msgs, "he puesto mis 3 cartas de arriba boca arriba en la mesa") and said(msgs, "Sigue pendiente"), msgs
    assert len([s for s in table.scripts if s.startswith("-- sparring:deck_card_to_spot")]) == lays, "nothing is dealt again"
    assert table.row == top and labels(twin) == ["Hecho"]
    table.stack(*top)
    msgs = click(twin, table, Event.CHOICE, {"i": 1})
    assert twin.effect_run is None and [c.card_id for c in twin.game.players[0].deck[:3]] == top


def test_cards_the_table_does_not_give_fall_back_to_the_panel_buttons(by_hand, monkeypatch):
    session, table, game, fake, cfg = by_hand
    table.bot_deck_fails = True
    top, msgs = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    assert session.order_row is None and table.row == []
    assert said(msgs, "No he podido sacar mis cartas de arriba") and said(msgs, "pulsa una de las opciones del panel"), msgs
    assert len(labels(session)) == 4          # three names and Confirm
    click(session, table, Event.CHOICE, {"i": 1})
    click(session, table, Event.CHOICE, {"i": 2})
    click(session, table, Event.CHOICE, {"i": 3})
    click(session, table, Event.CHOICE, {"i": 4})
    assert session.effect_run is None and [c.card_id for c in game.players[0].deck[:3]] == [top[0], top[1], top[2]]


def test_an_undone_answer_keeps_the_cards_on_the_table(by_hand, monkeypatch):
    session, table, game, fake, cfg = by_hand
    top, _ = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    table.stack(*top)
    from sparring.state import RuleError

    def pin_then_refuse(flow, value):
        session.peek_pins["top"][:0] = value          # what the answer did before the engine refused it
        raise RuleError("no")
    monkeypatch.setattr(session, "_answer_flow", pin_then_refuse)
    click(session, table, Event.CHOICE, {"i": 1})
    assert session.effect_run is not None and session.order_row is not None and table.row == []
    assert session.peek_pins == {"top": [], "bottom": []}, "rolled back with the save"


def test_with_order_by_hand_off_the_panel_buttons_stay_and_the_order_is_still_pinned(panel_rig, monkeypatch):
    session, table, game, fake, cfg = panel_rig
    top, msgs = play_sight_beyond_sight(session, table, game, cfg, monkeypatch)
    assert session.order_row is None and table.row == [] and len(labels(session)) == 4
    for i in (3, 1, 2, 4):                               # the third first, then the first, then the second; Confirm
        click(session, table, Event.CHOICE, {"i": i})
    expected = [top[2], top[0], top[1]]
    assert [c.card_id for c in game.players[0].deck[:3]] == expected
    session.read_bot_hand()
    assert [c.card_id for c in game.players[0].deck[:3]] == expected, "the panel order survives a reread of the table"
