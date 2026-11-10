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
    your_card = next(i for i, m in enumerate(msgs) if "Tu carta: Glimpse Of Hell: robas 2; en la mesa: pon 1 carta de tu "
                                                      "mano en tu mazo y baraja" in m)
    ask = next(i for i, m in enumerate(msgs) if "pulsa Fin de accion: despues se resuelve Fleeting Moments" in m)
    assert your_card < ask and msgs[-1] == msgs[ask]


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
    assert table.human_deals[-1] == 2 and len(table.human_deals) == 3, "Fleeting's draw is not dealt with the request"
    assert said(msgs, "Cuando hayas descartado y pulses Fin de accion te doy 1 carta")
    assert not said(msgs, "no estas") and not said(msgs, "Te he dado 1 carta")
    # the random discard is done on the table, then End action deals the card
    table.human_discard += [table.human_hand[0]] if table.human_hand else []
    table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and table.human_deals[-1] == 1 and len(table.human_deals) == 4
    assert said(msgs, "Te he dado 1 carta (") and not said(msgs, "no estas")
    assert len(game.players[1].hand) == table.human_count


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


@with_rig(*LIZ_VS_HELLBOY)
def test_a_plain_fleeting_moments_deals_its_card_after_the_discard(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    human_hand(table, game, "Excalibur", "Service Pistol", "Second Shot")
    fleeting = next(c for c in game.players[0].hand if c.title == "Fleeting Moments")
    bot_turn(session, table, [Act("attack", fid="liz", target="hellboy", card=fleeting)])
    table.face_down = []
    deals = len(table.human_deals)
    msgs = click(session, table, Event.REVEAL)
    assert len(table.human_deals) == deals and session.pending_discard["n"] == 1
    assert said(msgs, "Descarta 1 carta(s) (Fleeting Moments, al azar") and not said(msgs, "no estas")
    saved = json.loads(json.dumps(session.to_dict()))     # a save mid-discard keeps the owed card
    twin = twin_session(session, cfg, saved)
    table.human_discard.append(table.human_hand[0] if table.human_hand else 0)
    table.human_count -= 1
    msgs = click(twin, table, Event.END_ACTION)
    assert twin.pending_discard is None and len(table.human_deals) == deals + 1 and table.human_deals[-1] == 1
    assert said(msgs, "Te he dado 1 carta (")


MEDUSA_VS_LIZ = ("medusa", "liz-sherman", "Clutching Claws", "Gaze of Stone", "Dash", "Second Shot", "Dash")


def evade_against_clutching(session, table, game, cfg):
    """Bot Medusa's harpy attacks with Clutching Claws; the human Liz defends with Evade (draw 1) and holds three more cards."""
    put_adjacent(game, table, cfg, "harpy1", "liz")
    human_hand(table, game, "Evade", "Fireball", "Pyrotechnics", "Rekindle")
    claws = next(c for c in game.players[0].hand if c.title == "Clutching Claws")
    bot_turn(session, table, [Act("attack", fid="harpy1", target="liz", card=claws)])
    evade = card_ids(game, 1, "Evade")[0]
    table.face_down = [{"id": evade, "guid": f"h{evade}"}]
    table.human_hand.remove(evade)
    table.human_count -= 1
    table.deals_before = len(table.human_deals)
    return click(session, table, Event.REVEAL)


@with_rig(*MEDUSA_VS_LIZ)
def test_a_draw_before_the_discard_is_dealt_with_the_request_and_nothing_waits_after_it(rig):
    """Evade (defender, first) draws, then Clutching Claws makes him discard: he may discard the new card."""
    session, table, game, fake, cfg = rig
    msgs = evade_against_clutching(session, table, game, cfg)
    deals = table.deals_before
    assert len(table.human_deals) == deals + 1 and table.human_deals[-1] == 1
    dealt = next(i for i, m in enumerate(msgs) if "Te he dado 1 carta" in m)
    ask = next(i for i, m in enumerate(msgs) if "Descarta 1 carta(s) (Clutching Claws" in m)
    assert dealt < ask and not said(msgs, "no estas") and not said(msgs, "Cuando hayas descartado")
    assert session.pending_discard["n"] == 1 and session._undealt_draws() == 0
    twin = twin_session(session, cfg, json.loads(json.dumps(session.to_dict())))
    table.human_discard.append(table.human_hand[0])
    table.human_count -= 1
    click(twin, table, Event.END_ACTION)
    assert twin.pending_discard is None and len(table.human_deals) == deals + 1, "nothing was owed after the discard"


def owing_into_glimpse(session, table, game, cfg, owed):
    """`fleeting_into_glimpse` with `owed` cards already owed from earlier in the bot's turn; stops at the AFTER gate."""
    put_adjacent(game, table, cfg, "liz", "hellboy")
    human_hand(table, game, "Glimpse Of Hell", "Excalibur", "Service Pistol", "Second Shot")
    fleeting = next(c for c in game.players[0].hand if c.title == "Fleeting Moments")
    bot_turn(session, table, [Act("attack", fid="liz", target="hellboy", card=fleeting)])
    session._owe_discard(owed, "earlier")
    glimpse = card_ids(game, 1, "Glimpse Of Hell")[0]
    table.face_down = [{"id": glimpse, "guid": f"h{glimpse}"}]
    table.human_hand.remove(glimpse)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    assert session._table_gate(session.pending) and session.pending_discard["n"] == owed
    return glimpse


@with_rig(*LIZ_VS_HELLBOY)
def test_a_discard_owed_before_the_combat_and_paid_at_the_gate_is_not_asked_again_when_the_combat_ends(rig):
    """One card is owed from earlier in the bot's turn. At the AFTER gate the human takes it to the pile and End action reads
    it; Fleeting Moments then asks for one more. The end of the combat restarts the count from the pile: one card is owed
    (Fleeting's), not two, and one more card settles it."""
    session, table, game, fake, cfg = rig
    owing_into_glimpse(session, table, game, cfg, 1)
    table.human_discard.append(table.human_hand.pop())            # the card owed from before
    table.human_count -= 2                                        # ... and Glimpse's card back to the deck
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending is None and said(msgs, "Descarta 1 carta(s) (Fleeting Moments")
    assert session.pending_discard["n"] == 1 and session._hand_discards_owed() == 1
    table.human_discard.append(table.human_hand.pop())
    table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and not said(msgs, "Aun falta descartar"), msgs


@with_rig(*LIZ_VS_HELLBOY)
def test_the_defense_card_tidied_onto_the_pile_at_the_gate_pays_no_discard(rig):
    """One card is owed from earlier. At the AFTER gate the human only moves the Glimpse Of Hell they defended with onto
    their pile: the engine has not discarded it yet, so the table read lands it, but it is the combat's card, not a
    payment. Two cards are owed when the combat ends (the earlier one and Fleeting's)."""
    session, table, game, fake, cfg = rig
    glimpse = owing_into_glimpse(session, table, game, cfg, 1)
    assert glimpse not in [c.card_id for c in game.players[1].discard], "the played card is not on the engine's pile yet"
    table.human_discard.append(glimpse)
    table.human_count -= 1                                        # Glimpse's card back to the deck
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending is None and said(msgs, "Descarta 1 carta(s) (Fleeting Moments")
    assert session.pending_discard["n"] == 2 and session._hand_discards_owed() == 2, session.pending_discard
    for _ in range(2):
        table.human_discard.append(table.human_hand.pop())
        table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and not said(msgs, "Aun falta descartar"), msgs


@with_rig(*LIZ_VS_HELLBOY)
def test_the_cards_paid_at_the_gate_survive_a_save_and_a_save_without_the_count_still_loads(rig):
    session, table, game, fake, cfg = rig
    owing_into_glimpse(session, table, game, cfg, 2)
    table.human_discard.append(table.human_hand.pop())            # one of the two, read at the gate
    table.human_count -= 1
    session.sync_human()
    saved = json.dumps(session.to_dict())
    assert json.loads(saved)["pending_discard"]["landed"] == 1
    twin = twin_session(session, cfg, json.loads(saved))
    twin._rebase_discard_debt()
    assert twin.pending_discard["n"] == 1 and twin._hand_discards_owed() == 1
    # a game saved before the count existed: nothing is credited, nothing breaks
    before = json.loads(saved)
    del before["pending_discard"]["landed"]
    old = twin_session(session, cfg, before)
    old._rebase_discard_debt()
    assert old.pending_discard["n"] == 2 and old._hand_discards_owed() == 2


@with_rig(*LIZ_VS_HELLBOY)
def test_a_card_paid_at_the_gate_is_credited_once_not_again_when_a_later_combat_ends(rig):
    """Two owed, one paid at the gate, Fleeting asks one more: two are owed when the combat ends. The bot waits for a
    debt before it acts again, so the end of a later combat is its rebase alone: it finds no credit left to take."""
    session, table, game, fake, cfg = rig
    owing_into_glimpse(session, table, game, cfg, 2)
    table.human_discard.append(table.human_hand.pop())
    table.human_count -= 2                                        # ... and Glimpse's card back to the deck
    click(session, table, Event.END_ACTION)
    assert session.pending is None and session.pending_discard["n"] == 2
    session._rebase_discard_debt()
    assert session.pending_discard["n"] == 2 and session._hand_discards_owed() == 2, session.pending_discard
    for _ in range(2):
        table.human_discard.append(table.human_hand.pop())
        table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and not said(msgs, "Aun falta descartar"), msgs
