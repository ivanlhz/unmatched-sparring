"""Every draw an effect gives the HUMAN is dealt by the bot from their physical deck to their hand (30/10), through the
same path as the Maniobra's: the engine counts the draw, the session deals exactly that many cards at the close of
the button (`Session._deal_owed_draws`), never reads the hand, and the next reading of the table settles the count.

The human keeps doing what is theirs: which discard cards go to the bottom of the deck, the discard of their own
hand (Crown of Flame), their own miniatures."""
from __future__ import annotations

import dataclasses
import json

import pytest

from sparring.ai_medusa import Act, MedusaAI
from sparring.session import Session
from sparring.state import EXHAUST_DAMAGE, Game
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_hand, said
from test_e2_human_cards import (HELLBOY_VS_ABE, bot_defends_with_nothing, human_scheme, press, put_adjacent, rig,  # noqa: F401
                                 with_rig)

CROWN = "And Upon His Brow Is Set A Crown Of Flame"
MANEUVERS = [1, 1]                  # the two Maniobras with which `bot_turn` ends the human turn


def settle(session, table, game):
    """The next reading of the table: the engine's hand must match what the table holds."""
    session.snap = None
    click(session, table, Event.HP, {"fighter": "hellboy", "delta": 0})
    assert len(game.players[1].hand) == table.human_count


# ---------------------------------------------------------------- Pancakes!, the case Ivan played live

@with_rig(*HELLBOY_VS_ABE)
def test_pancakes_draw_two_deals_two_cards_to_the_human_seat(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    assert table.human_deals == []                                   # nothing is dealt before he chooses
    press(session, table, "Hellboy recovers")
    msgs = press(session, table, "draw 2")
    assert table.human_deals == [2] and said(msgs, "Te he dado 2 cartas (efecto de Pancakes!)")
    assert not said(msgs, "Robas 2") and not said(msgs, "hazlo en la mesa")
    assert table.human_count == 1 + 2
    script = next(s for s in table.scripts if s.startswith("-- sparring:deal_cards"))
    assert '"Red"' in script and "getHandObjects" not in script      # the human seat; the hand is never read
    settle(session, table, game)


@with_rig(*HELLBOY_VS_ABE)
def test_pancakes_without_the_draw_option_deals_nothing(rig):
    session, table, game, fake, cfg = rig
    game.fighters["hellboy"].hp = 10
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    press(session, table, "Hellboy recovers")
    press(session, table, "put up to 2")
    assert table.human_deals == []


@with_rig(*HELLBOY_VS_ABE)
def test_pancakes_discard_to_deck_choice_is_yours_and_only_the_draw_is_dealt(rig):
    """The cards of the discard that go to the bottom of the deck are the human's choice: nothing is dealt for them."""
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    press(session, table, "put up to 2")
    msgs = press(session, table, "draw 2")
    assert table.human_deals == [2] and not said(msgs, "Te he dado 3")


# ---------------------------------------------------------------- the other effects of the human

@with_rig(*HELLBOY_VS_ABE)
def test_confront_any_demon_or_god_deals_its_card_after_the_combat(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Confront Any Demon or God", "Excalibur")
    from test_d3_table_effects import human_attack
    human_attack(session, table, game, "hellboy", "abe", "Confront Any Demon or God")
    msgs = click(session, table, Event.REVEAL)
    assert table.human_deals == [1] and said(msgs, "Te he dado 1 carta (efectos del combate)")
    settle(session, table, game)


@with_rig(*HELLBOY_VS_ABE)
def test_glimpse_of_hell_deals_two_and_the_shuffle_back_stays_yours(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Glimpse Of Hell", "Excalibur", "Service Pistol")
    from test_d3_table_effects import human_attack
    human_attack(session, table, game, "hellboy", "abe", "Glimpse Of Hell")
    msgs = click(session, table, Event.REVEAL)
    assert table.human_deals == [2] and said(msgs, "en la mesa: pon 1 carta de tu mano en tu mazo y baraja")


@with_rig(*HELLBOY_VS_ABE)
def test_crown_of_flame_deals_two_and_the_discard_of_the_old_hand_stays_manual(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, CROWN, "Excalibur", "Service Pistol")
    msgs = human_scheme(session, table, game, CROWN)
    assert table.human_deals == [2] and said(msgs, "Te he dado 2 cartas")
    assert said(msgs, "Lo que te toca descartar es lo que tenias antes, no estas")
    assert session.pending_discard["n"] == 2 and not said(msgs, "Robas 2")
    table.human_discard += card_ids(game, 1, "Excalibur", "Service Pistol")
    table.human_count -= 2
    click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and len(game.players[1].hand) == table.human_count == 2


@with_rig("liz-sherman", "hellboy", "Pyrotechnics", "Rekindle", "Fleeting Moments", "Evade", "Fireball")
def test_the_human_side_of_fleeting_moments_deals_one_card(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    fleeting = next(c for c in game.players[0].hand if c.title == "Fleeting Moments")
    bot_turn(session, table, [Act("attack", fid="liz", target="hellboy", card=fleeting)])
    table.face_down = []
    msgs = click(session, table, Event.REVEAL)
    assert table.human_deals == MANEUVERS + [1] and said(msgs, "Te he dado 1 carta")


@with_rig("hellboy", "abe-sapien", "Service Pistol", "Right Hand Of Doom", "Excalibur", "Second Shot", "Pancakes!")
def test_uncanny_intuition_of_the_human_abe_deals_its_card(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(1, "intuition", 1)
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    human_hand(table, game, "Leap Away", "Ward And Prepare")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="abe", card=pistol)])
    table.face_down = []
    click(session, table, Event.REVEAL)
    assert table.human_deals == MANEUVERS + [1]


# ---------------------------------------------------------------- OCCULT DETECTIVE: optional, dealt after the choice

def detective_turn(session, table, game, cfg):
    """The human's Hellboy stands on the bot's start space at the start of his turn."""
    start = game.fighters["hellboy"].pos
    game.start_spaces = {0: start, 1: game.start_spaces.get(1, start)}
    return bot_turn(session, table, [])


@with_rig(*HELLBOY_VS_ABE)
def test_occult_detective_asks_on_the_panel_and_deals_two_when_he_accepts(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur", "Service Pistol")
    msgs = detective_turn(session, table, game, cfg)
    assert session.ability_wait is None and session.effect_run is not None
    assert said(msgs, "OCCULT DETECTIVE: estas en la salida rival") and table.human_deals == MANEUVERS
    msgs = press(session, table, True)
    assert table.human_deals == MANEUVERS + [2] and said(msgs, "Te he dado 2 cartas (OCCULT DETECTIVE)")
    assert session.effect_run is None and game.actions_left == 2
    settle(session, table, game)


@with_rig(*HELLBOY_VS_ABE)
def test_occult_detective_declined_deals_nothing(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur", "Service Pistol")
    detective_turn(session, table, game, cfg)
    press(session, table, False)
    assert table.human_deals == MANEUVERS and session.effect_run is None
    settle(session, table, game)


# ---------------------------------------------------------------- resume, empty deck, failures, message budget

@with_rig(*HELLBOY_VS_ABE)
def test_a_resume_after_the_deal_never_deals_twice_and_one_at_the_pause_deals_once(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    paused = json.loads(json.dumps(session.to_dict()))
    assert "human_dealt" not in paused and game.drawn[1] == 0       # saved only when owed differs
    press(session, table, "Hellboy recovers")
    press(session, table, "draw 2")
    assert table.human_deals == [2]
    done = json.loads(json.dumps(session.to_dict()))
    assert "human_dealt" not in done and done["game"]["drawn"][1] == 2      # all counted draws were dealt

    def reborn(saved):
        other = Session(Game.new(game.board, seed=3, controllers={}, heroes=cfg.heroes), session.client, MedusaAI(0),
                        session.cfg)
        other.game_id = session.game_id
        other.load_dict(saved)
        other.snap = None
        return other
    again = reborn(done)
    again.resume()
    click(again, table, Event.HP, {"fighter": "hellboy", "delta": 0})
    assert table.human_deals == [2], "the deal that was already made is not made again"
    earlier = reborn(paused)                          # resumed at the pause: the answer deals once
    earlier.snap = None
    press(earlier, table, "Hellboy recovers")
    press(earlier, table, "draw 2")
    assert table.human_deals == [2, 2]


@with_rig(*HELLBOY_VS_ABE)
def test_an_empty_deck_exhausts_the_human_fighters_and_deals_only_what_exists(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    st = game.players[1]
    st.discard.extend(st.deck[1:])                    # one card left in the deck
    del st.deck[1:]
    hp0 = {f.fid: f.hp for f in game.own(1)}
    press(session, table, "Hellboy recovers")
    msgs = press(session, table, "draw 2")
    assert table.human_deals == [1], "the bot deals the card that exists"
    assert game.drawn[1] == 1 and game.fighters["lobster"].hp == hp0["lobster"] - EXHAUST_DAMAGE
    assert said(msgs, "Te he dado 1 carta")


@with_rig(*HELLBOY_VS_ABE)
def test_a_failed_deal_says_so_in_spanish_and_gives_the_cards_back_to_the_engine(rig):
    session, table, game, fake, cfg = rig
    table.human_deal_fails = True
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    hand0 = len(game.players[1].hand)
    press(session, table, "Hellboy recovers")
    msgs = press(session, table, "draw 2")
    assert said(msgs, "No he podido darte 2 de las 2 cartas") and said(msgs, "Roba 2 a mano")
    assert len(game.players[1].hand) == hand0 and game.drawn[1] == 0 and session.human_dealt == 0
    click(session, table, Event.END_ACTION)
    assert table.human_deals == [2], "a failed deal is not repeated"


@with_rig(*HELLBOY_VS_ABE)
def test_a_deal_that_never_reaches_the_hand_is_flagged_once(rig):
    session, table, game, fake, cfg = rig
    table.do_deal_cards = lambda s: {"dealt": 2}      # TTS says it dealt them and the hand does not grow
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    press(session, table, "Hellboy recovers")
    press(session, table, "draw 2")
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "Las 2 cartas que te di no han llegado a tu mano")


@with_rig(*HELLBOY_VS_ABE)
def test_an_unreadable_identity_deals_nothing_and_asks_to_draw_by_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    from sparring.session import SessionError

    def identity(side="bot"):
        raise SessionError("sin identidad")
    monkeypatch.setattr(session, "_identity", identity)
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    press(session, table, "Hellboy recovers")
    msgs = press(session, table, "draw 2")
    assert table.human_deals == [] and said(msgs, "No he podido darte 2 cartas") and said(msgs, "Roba 2 cartas a mano")


@with_rig(*HELLBOY_VS_ABE)
def test_without_a_human_deck_the_draw_is_still_announced_for_the_table(rig):
    session, table, game, fake, cfg = rig
    session.cfg = dataclasses.replace(session.cfg, human_deck_guid=None)
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    press(session, table, "Hellboy recovers")
    msgs = press(session, table, "draw 2")
    assert table.human_deals == [] and said(msgs, "Robas 2 cartas (efecto de Pancakes!): hazlo en la mesa")


def final_press_cost(tmp_path, deck: bool) -> tuple[int, list]:
    session, table, game, fake, cfg, client = build(tmp_path, "abe-sapien", "hellboy", ("Faster. Stronger.",))
    try:
        if not deck:
            session.cfg = dataclasses.replace(session.cfg, human_deck_guid=None)
        human_hand(table, game, "Pancakes!", "Excalibur")
        human_scheme(session, table, game, "Pancakes!")
        press(session, table, "Hellboy recovers")
        n = fake.lua_messages
        press(session, table, "draw 2")
        return fake.lua_messages - n, list(table.human_deals)
    finally:
        client.close()
        fake.close()


def test_the_deal_rides_in_the_composite_of_the_button_it_adds_no_message(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_deal, deals = final_press_cost(tmp_path / "a", True)
    without, none = final_press_cost(tmp_path / "b", False)
    assert deals == [2] and none == []
    assert with_deal == without
