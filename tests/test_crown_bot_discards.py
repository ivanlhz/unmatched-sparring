"""Crown Of Flame played by the HUMAN (30/10): the bot moves their whole remaining hand to their discard pile itself,
face up, and only then deals the 2 new cards (so the new ones are never discarded). The engine follows with the cards
the table reports; when the table cannot do it the old manual flow (`pending_discard`) is the fallback."""
from __future__ import annotations

import json

from sparring.ai_medusa import MedusaAI
from sparring.session import Session
from sparring.state import Game
from sparring.tts import lua
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, human_hand, said
from test_e2_human_cards import HELLBOY_VS_ABE, human_scheme, rig, with_rig  # noqa: F401
from conftest import TEST_IDENT

CROWN = "And Upon His Brow Is Set A Crown Of Flame"


def op_order(table) -> list[str]:
    """The table writes of the step that matter here, in the order they reached TTS."""
    tags = ("hand_to_discard", "deal_cards")
    return [t for t in (s.split("\n", 1)[0].removeprefix("-- sparring:") for s in table.scripts) if t in tags]


@with_rig(*HELLBOY_VS_ABE)
def test_the_bot_discards_the_whole_hand_first_then_deals_two(rig):
    session, table, game, fake, cfg = rig
    old = human_hand(table, game, CROWN, "Excalibur", "Service Pistol")[1:]
    msgs = human_scheme(session, table, game, CROWN)
    assert op_order(table) == ["hand_to_discard", "deal_cards"], "the old hand goes first: the new cards are never discarded"
    assert table.hand_discards == [2] and table.human_deals == [2]
    assert set(old) <= set(table.human_discard) and table.human_count == 2
    assert session.pending_discard is None and not said(msgs, "Descarta ")
    said_at = [i for i, m in enumerate(msgs) if "Descarto tu mano (2 cartas) por " + CROWN in m]
    dealt_at = [i for i, m in enumerate(msgs) if "Te he dado 2 cartas" in m]
    assert said_at and dealt_at and said_at[0] < dealt_at[0]
    assert not said(msgs, "Lo que te toca descartar")


@with_rig(*HELLBOY_VS_ABE)
def test_the_engine_matches_the_table_and_the_bot_forgets_the_hand_it_had_seen(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, CROWN, "Excalibur", "Service Pistol")
    excalibur = next(c for c in game.players[1].full_set if c.title == "Excalibur")
    game.players[0].known.add(excalibur, game.turn_no)
    assert excalibur.card_id in game.players[0].known.seen
    human_scheme(session, table, game, CROWN)
    st = game.players[1]
    titles = {c.title for c in st.discard}
    assert {"Excalibur", "Service Pistol"} <= titles, "the discarded hand is public"
    assert excalibur.card_id not in game.players[0].known.seen
    assert len(st.hand) == table.human_count == 2
    click(session, table, Event.HP, {"fighter": "hellboy", "delta": 0})        # the next reading leaves it as it is
    assert {"Excalibur", "Service Pistol"} <= {c.title for c in st.discard}
    assert len(st.hand) == table.human_count == 2 and session.pending_discard is None


@with_rig(*HELLBOY_VS_ABE)
def test_an_empty_hand_says_no_discard_and_only_deals(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, CROWN)
    msgs = human_scheme(session, table, game, CROWN)
    assert table.hand_discards == [] and table.human_deals == [2]
    assert not said(msgs, "Descarto tu mano") and not said(msgs, "Descarta ") and session.pending_discard is None
    assert said(msgs, "Te he dado 2 cartas")


@with_rig(*HELLBOY_VS_ABE)
def test_a_resume_never_discards_or_deals_twice(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, CROWN, "Excalibur", "Service Pistol")
    human_scheme(session, table, game, CROWN)
    saved = json.loads(json.dumps(session.to_dict()))
    other = Session(Game.new(game.board, seed=3, controllers={}, heroes=cfg.heroes), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    other.snap = None
    other.resume()
    click(other, table, Event.HP, {"fighter": "hellboy", "delta": 0})
    assert table.hand_discards == [2] and table.human_deals == [2]
    assert other.pending_discard is None and len(other.game.players[1].hand) == table.human_count == 2


@with_rig(*HELLBOY_VS_ABE)
def test_a_table_that_moves_fewer_cards_falls_back_to_asking_for_the_rest(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, CROWN, "Excalibur", "Service Pistol")
    plain = table.do_hand_to_discard

    def one_stays(s):
        res = plain(s)
        stays = res["moved"][1]
        table.human_discard.remove(stays)
        table.human_hand, table.human_count = [stays], 1
        return {"moved": res["moved"][:1], "count": 1, "zone": True}
    table.do_hand_to_discard = one_stays
    msgs = human_scheme(session, table, game, CROWN)
    assert said(msgs, "No he podido descartar tu mano (he movido 1 de 2)")
    assert session.pending_discard is not None and session.pending_discard["n"] == 1
    assert said(msgs, "Descarta 1 carta(s) (" + CROWN + ")") and not said(msgs, "Descarto tu mano")
    assert table.human_deals == [2], "the game goes on: the two cards are dealt anyway"


@with_rig(*HELLBOY_VS_ABE)
def test_a_table_error_falls_back_to_the_manual_discard(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, CROWN, "Excalibur", "Service Pistol")
    table.hand_discard_fails = True
    msgs = human_scheme(session, table, game, CROWN)
    assert said(msgs, "No he podido descartar tu mano") and said(msgs, "Descarta 2 carta(s) (" + CROWN + ")")
    assert session.pending_discard["n"] == 2 and table.human_deals == [2]
    table.human_discard += card_ids(game, 1, "Excalibur", "Service Pistol")
    table.human_count -= 2
    click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and len(game.players[1].hand) == table.human_count == 2


def test_the_script_takes_only_the_seat_hand_and_lays_the_cards_face_up_on_the_pile():
    script = lua.hand_to_discard("Red", "906a7a", (1000, 1029), identity=TEST_IDENT)
    assert script.startswith("-- sparring:hand_to_discard") and lua.is_sendable(script)
    assert 'Player["Red"].getHandObjects(1)' in script and 'getObjectFromGUID("906a7a")' in script
    assert "cardOurs" in script and "Vector(0, turn, 0)" in script       # face up (z = 0), turned like the pile
    assert "setPositionSmooth" not in script, "a smooth move does not take a card out of a hand"
