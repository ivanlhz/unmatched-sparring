"""The HUMAN's Abe Sapien: the engine counts his Intuition tokens; the bot turns the physical tokens on the table (active
face when one is activated, inactive when one is spent), pings them and says the count in chat. When the tokens cannot
be found or turned the chat asks the human to do it. A bot attack on an Abe with an active token spends the token and
deals the drawn card BEFORE the defense is chosen.

FakeTTS sessions; Ivan saw it live on 3/11: two active tokens in play and not a word in the chat."""
from __future__ import annotations

import json

from sparring import i18n
from sparring.ai_medusa import Act, MedusaAI
from sparring.session import Session
from sparring.state import Game
from sparring.tts import lua
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, human_attack, human_hand, said
from test_e2_human_cards import HELLBOY_VS_ABE, bot_defends_with_nothing, put_adjacent, rig, with_rig  # noqa: F401

HAND = ("Service Pistol", "Right Hand Of Doom", "Excalibur", "Second Shot", "Pancakes!")


def human_abe_hits_hellboy(session, table, game, cfg, monkeypatch):
    bot_turn(session, table, [])
    human_hand(table, game, "Faster. Stronger.", "Leap Away")
    put_adjacent(game, table, cfg, "hellboy", "abe")
    bot_defends_with_nothing(session, monkeypatch)
    human_attack(session, table, game, "abe", "hellboy", "Faster. Stronger.")
    return click(session, table, Event.REVEAL)                  # combat damage to an adjacent fighter


@with_rig("hellboy", "abe-sapien", *HAND)
def test_activating_a_token_turns_it_on_the_table_and_says_the_count(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    msgs = human_abe_hits_hellboy(session, table, game, cfg, monkeypatch)
    assert game.fx.counter_value(1, "intuition") == 1
    assert table.intuition == {"total": 2, "active": 1} and table.intuition_turns == [(True, 1)]
    assert said(msgs, "UNCANNY INTUITION: Abe Sapien activa 1 ficha (1 de 2 activas): he girado 1 ficha a su cara activa y he hecho ping")


@with_rig("hellboy", "abe-sapien", *HAND)
def test_the_spend_is_declared_and_dealt_before_the_defense_and_turns_the_token_back(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(1, "intuition", 2)
    session._track_intuition(announce=True)
    table.intuition["active"] = 2
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    human_hand(table, game, "Leap Away", "Ward And Prepare")
    msgs = bot_turn(session, table, [Act("attack", fid="hellboy", target="abe", card=pistol)])
    # still before Reveal: the token is spent, the card dealt, the token turned and the attack named
    assert session.pending is not None and session.pending.declared is not None
    assert game.fx.counter_value(1, "intuition") == 1 and table.human_deals == [1, 1, 1]
    assert table.intuition == {"total": 2, "active": 1} and table.intuition_turns[-1] == (False, 1)
    assert said(msgs, "UNCANNY INTUITION: Abe Sapien gasta 1 ficha (1 de 2 activas): he girado 1 ficha a su cara oscura")
    assert said(msgs, "el ataque del bot se juega boca arriba: Service Pistol")
    table.face_down = []
    msgs = click(session, table, Event.REVEAL)
    assert game.fx.counter_value(1, "intuition") == 1, "nothing fires twice"
    assert table.human_deals == [1, 1, 1] and len(table.intuition_turns) == 1
    assert not said(msgs, "miras la mano del bot")


@with_rig("hellboy", "abe-sapien", *HAND)
def test_the_spend_summary_says_the_attack_is_face_up_not_a_look_at_the_hand(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(1, "intuition", 1)
    session._track_intuition(announce=True)
    table.intuition["active"] = 1
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    human_hand(table, game, "Leap Away", "Ward And Prepare")
    msgs = bot_turn(session, table, [Act("attack", fid="hellboy", target="abe", card=pistol)])
    line = next(m for m in msgs if "INTUITION SPEND" in m or "intuition_spend" in m)
    assert "mano" not in line and "boca arriba" in line


@with_rig("hellboy", "abe-sapien", *HAND)
def test_tokens_that_are_not_on_the_table_are_asked_of_the_human(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    table.intuition["total"] = 0
    msgs = human_abe_hits_hellboy(session, table, game, cfg, monkeypatch)
    assert game.fx.counter_value(1, "intuition") == 1
    assert said(msgs, "gira 1 ficha de Intuicion a su cara activa (verde con rayas amarillas) (no encuentro tus fichas de Intuicion en la mesa)")


@with_rig("hellboy", "abe-sapien", *HAND)
def test_a_table_that_disagrees_with_the_engine_is_warned_and_the_engine_stays(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    table.intuition["active"] = 1                               # the engine counted 0 before the hit
    msgs = human_abe_hits_hellboy(session, table, game, cfg, monkeypatch)
    assert said(msgs, "en la mesa hay 1 ficha(s) de Intuicion activa(s) y yo conte 0: me fio de mi cuenta")
    assert game.fx.counter_value(1, "intuition") == 1
    assert table.intuition["active"] == 1 and table.intuition_turns == [], "absolute target: nothing pushed to 2"


@with_rig("hellboy", "abe-sapien", *HAND)
def test_the_count_is_announced_once_and_only_when_it_changes(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(1, "intuition", 2)
    session.messages = []
    session._track_intuition(announce=True)
    assert said(session.messages, "Abe Sapien tiene 2 de 2 fichas de Intuicion activas; el resto (0 fichas)")
    session.messages = []
    session._track_intuition()
    session._done()
    assert not said(session.messages, "UNCANNY INTUITION")


@with_rig("hellboy", "abe-sapien", *HAND)
def test_resume_announces_the_current_count(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(1, "intuition", 1)
    saved = json.loads(json.dumps(session.to_dict()))
    other = Session(Game.new(game.board, seed=3, controllers={}, heroes=cfg.heroes), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    other.snap = None
    msgs = other.resume()
    assert said(msgs, "Abe Sapien tiene 1 de 2 fichas de Intuicion activas; el resto (1 ficha)")


@with_rig(*HELLBOY_VS_ABE)
def test_a_human_without_intuition_hears_nothing(rig):
    session, table, game, fake, cfg = rig
    session.messages = []
    session._track_intuition(announce=True)
    assert session.messages == []


@with_rig("hellboy", "abe-sapien", *HAND)
def test_the_english_line_carries_the_same_numbers(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(1, "intuition", 1)
    session._intuition_said = 0
    session.messages = []
    with i18n.using("en"):
        session._track_intuition()
        session._done()
    assert said(session.messages, "UNCANNY INTUITION: Abe Sapien activates 1 token (1 of 2 active): I turned 1 token to the active side")


def test_the_lua_op_finds_the_tokens_by_name_and_turns_a_stack_one_by_one():
    script = lua.set_intuition_tokens("Intuition Token", "5a17e9", 180, 0, 2, ["Red", "Blue"])
    assert "-- sparring:set_intuition_tokens" in script and 'o.getName() == NAME' in script
    assert "local TARGET = 2" in script and "takeObject" in script and "pingTable" in script


@with_rig("hellboy", "abe-sapien", *HAND)
def test_the_starting_count_is_said_when_the_setup_ends_and_again_after_a_restart(rig):
    session, table, game, fake, cfg = rig
    session._intuition_said = 0                                 # the silent first look the setup's steps make
    session.messages = []
    session.setup = {"stage": "wait_human", "mull_done": False, "mull_decision": None, "mull_step": "start", "human_mull": False}
    session._setup_begin()
    assert said(session.messages, "Abe Sapien tiene 0 de 2 fichas de Intuicion activas")
    session._intuition_said = 2                                 # the old game's value
    session.messages = []
    session._begin_game()
    assert said(session.messages, "Abe Sapien tiene 0 de 2 fichas de Intuicion activas")


@with_rig("hellboy", "abe-sapien", *HAND)
def test_a_failed_write_is_not_reported_as_tokens_not_found(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    monkeypatch.setattr(type(table), "do_set_intuition_tokens", lambda self, s: (_ for _ in ()).throw(OSError("boom")))
    msgs = human_abe_hits_hellboy(session, table, game, cfg, monkeypatch)
    assert game.fx.counter_value(1, "intuition") == 1
    assert not said(msgs, "no encuentro tus fichas")
