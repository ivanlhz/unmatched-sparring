"""AFTER effects of both sides go one after the other, the defender's first, and wait between them when the first one
left the human a step on their own hand (Ivan, 31/10: Fleeting Moments attacks, Glimpse Of Hell defends). The random
discard is placed over the hand the human holds once they have drawn and put their card back."""
from __future__ import annotations

import json

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, said, twin_session
from test_e2_human_cards import bot_defends_with, human_attack, put_adjacent, rig, with_rig  # noqa: F401

LIZ_VS_HELLBOY = ("liz-sherman", "hellboy", "Fleeting Moments", "Evade", "Fireball", "Pyrotechnics", "Rekindle")


def fleeting_into_glimpse(session, table, game, cfg):
    """Bot Liz attacks with Fleeting Moments; the human Hellboy defends with Glimpse Of Hell and holds three more cards."""
    put_adjacent(game, table, cfg, "liz", "hellboy")
    human_hand(table, game, "Glimpse Of Hell", "Excalibur", "Service Pistol", "Second Shot")
    fleeting = next(c for c in game.players[0].hand if c.title == "Fleeting Moments")
    bot_turn(session, table, [Act("attack", fid="liz", target="hellboy", card=fleeting)])
    glimpse = card_ids(game, 1, "Glimpse Of Hell")[0]
    table.face_down = [{"id": glimpse, "guid": f"h{glimpse}"}]
    table.human_hand.remove(glimpse)
    table.human_count -= 1
    return click(session, table, Event.REVEAL)


@with_rig(*LIZ_VS_HELLBOY)
def test_the_defenders_effect_comes_first_and_the_attackers_waits_for_the_step_on_your_hand(rig):
    session, table, game, fake, cfg = rig
    msgs = fleeting_into_glimpse(session, table, game, cfg)
    assert session._table_gate(session.pending)
    assert table.human_deals[-1] == 2 and len(table.human_deals) == 3, "Glimpse drew 2; Fleeting has not drawn yet"
    assert not said(msgs, "Descarta 1 carta(s)") and not said(msgs, "Fleeting Moments:")
    assert session.pending_discard is None and not said(msgs, "no estas")
    tu_carta = next(i for i, m in enumerate(msgs) if "Tu carta: Glimpse Of Hell: robas 2; en la mesa: pon 1 carta de tu "
                                                      "mano en tu mazo y baraja" in m)
    ask = next(i for i, m in enumerate(msgs) if "pulsa Fin de accion: despues se resuelve Fleeting Moments" in m)
    assert tu_carta < ask and msgs[-1] == msgs[ask]


@with_rig(*LIZ_VS_HELLBOY)
def test_the_random_position_is_drawn_over_the_hand_after_glimpse(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    fleeting_into_glimpse(session, table, game, cfg)
    sizes = []
    real = game.rng.sample
    monkeypatch.setattr(game.rng, "sample", lambda pop, k: (sizes.append(len(pop)), real(pop, k))[1])
    bot_hand = len(game.players[0].hand)
    # the table dealt Glimpse's two cards (3 + 2); he puts one back in the deck and shuffles
    table.human_count -= 1
    held = table.human_count
    msgs = click(session, table, Event.END_ACTION)
    assert not session._table_gate(session.pending) and sizes == [bot_hand, held], "his own hand, then the cards you really hold"
    line = next(m for m in msgs if "Descarta 1 carta(s) (Fleeting Moments, al azar: la carta " in m)
    assert 1 <= int(line.split("la carta ")[1].split(" ")[0]) <= held
    assert session.pending_discard["n"] == 1 and said(msgs, "Aplicado: Fleeting Moments")
    assert table.human_deals[-1] == 1 and said(msgs, "Lo que te toca descartar es lo que tenias antes, no estas")


@with_rig(*LIZ_VS_HELLBOY)
def test_a_resume_at_the_gate_keeps_waiting_and_then_goes_on(rig):
    session, table, game, fake, cfg = rig
    fleeting_into_glimpse(session, table, game, cfg)
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    assert twin._table_gate(twin.pending)
    table.human_count -= 1
    msgs = click(twin, table, Event.END_ACTION)
    assert not twin._table_gate(twin.pending) and said(msgs, "Descarta 1 carta(s) (Fleeting Moments, al azar")
    assert not said(msgs, "Combate:") and not said(msgs, "Tu carta: Glimpse")


@with_rig(*LIZ_VS_HELLBOY)
def test_other_buttons_wait_at_the_gate(rig):
    session, table, game, fake, cfg = rig
    fleeting_into_glimpse(session, table, game, cfg)
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Haz primero en la mesa") and session._table_gate(session.pending)
    states = session.panel_view()[1]
    assert states["btn_end"][0] and not states["btn_reveal"][0] and not states["btn_cancel"][0]


@with_rig("hellboy", "liz-sherman", "Glimpse Of Hell", "Right Hand Of Doom", "Excalibur", "Second Shot", "Pancakes!")
def test_a_bot_defender_runs_both_effects_at_once(rig, monkeypatch):
    """The bot's Glimpse leaves no step on the human's hand: Liz's Fleeting Moments follows without a gate."""
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    human_hand(table, game, "Fireball", "Evade", "Rekindle", "Fleeting Moments")
    bot_defends_with(session, game, "Glimpse Of Hell", monkeypatch)
    human_attack(session, table, game, "liz", "hellboy", "Fleeting Moments")
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is None and not session._table_gate(session.pending)
    assert said(msgs, "Descarta 1 carta(s) (Fleeting Moments, al azar")
