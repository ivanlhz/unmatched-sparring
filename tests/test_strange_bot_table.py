"""Doctor Strange as the BOT on the table (live 2/11 15:39, bot Strange vs human Hellboy): an attack with two BLIND BOOSTs whose
combat stops at the human's Confront Any Demon or God (look at the hand), and DARK PACT afterwards.

Live: Seven Suns of Cinnibus (CardID 17610; 17600 is The Winds of Watoomb) stayed on the bot's combat spot, the pact's "puts it at
the bottom of its deck" was never said, and 'I did not find the bot's cards [17600]' came up because two boosts of the same draw
Deck were discarded in one script that takes one card per Deck."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, said
from test_e2_human_cards import put_adjacent, rig, with_rig  # noqa: F401

HAND = ("Seven Suns of Cinnibus", "Feint", "Cloak of Levitation", "Eye of Agamotto", "Bolts of Balthakk")


def attack_lost_to_confront(session, table, game, cfg):
    """The bot attacks with Seven Suns (two blind boosts: both Winds of Watoomb) and Hellboy defends with Confront."""
    put_adjacent(game, table, cfg, "strange", "hellboy")
    human_hand(table, game, "Confront Any Demon or God", "Excalibur", "Service Pistol")
    suns = next(c for c in game.players[0].hand if c.title == "Seven Suns of Cinnibus")
    bot_turn(session, table, [Act("attack", fid="strange", target="hellboy", card=suns)])
    confront = card_ids(game, 1, "Confront Any Demon or God")[0]
    table.face_down = [{"id": confront, "guid": f"h{confront}"}]
    table.human_hand.remove(confront)
    table.human_count -= 1
    return suns, click(session, table, Event.REVEAL)


def human_picks_cloak(session, table, game):
    cloak = card_ids(game, 0, "Cloak of Levitation")[0]
    table.bot_hand.remove(cloak)
    table.bot_discard.append(cloak)
    return click(session, table, Event.CHOICE, {"i": 1})              # Done


@with_rig("doctor-strange", "hellboy", *HAND)
def test_both_blind_boosts_of_the_same_draw_deck_reach_the_pile_in_one_write(rig):
    session, table, game, fake, cfg = rig
    suns, msgs = attack_lost_to_confront(session, table, game, cfg)
    winds = card_ids(game, 0, "The Winds of Watoomb", "The Winds of Watoomb")
    assert sorted(table.bot_discard) == sorted(winds), "no second write needed for the second boost card"
    assert not said(msgs, "no encontre en la mesa") and not said(session.messages, "no coincide")


@with_rig("doctor-strange", "hellboy", *HAND)
def test_dark_pact_after_a_combat_paused_at_the_look_puts_the_played_card_at_the_bottom_of_the_deck(rig):
    session, table, game, fake, cfg = rig
    suns, _ = attack_lost_to_confront(session, table, game, cfg)
    assert table.bot_play == [suns.card_id], "while the combat waits at the human's choice the card stays on its spot"
    msgs = human_picks_cloak(session, table, game)
    st = game.players[0]
    assert suns in st.deck and suns not in st.discard and game.fighters["strange"].hp == 13   # the pact was paid
    assert table.bot_play == [] and table.bot_deck[-1] == suns.card_id, "the table moved the card, not just the engine"
    assert ("bottom", [suns.card_id]) in table.deck_moves
    assert said(msgs, "El bot pone Seven Suns of Cinnibus de su descarte en el fondo de su mazo")
    assert not said(msgs, "No he podido mover") and not said(session.messages, "no coincide")


@with_rig("doctor-strange", "hellboy", *HAND)
def test_the_table_and_the_engine_agree_on_the_bot_zones_after_the_paused_pact(rig):
    session, table, game, fake, cfg = rig
    attack_lost_to_confront(session, table, game, cfg)
    human_picks_cloak(session, table, game)
    click(session, table, Event.END_ACTION)
    st = game.players[0]
    assert sorted(table.bot_hand) == sorted(c.card_id for c in st.hand)
    assert sorted(table.bot_discard) == sorted(c.card_id for c in st.discard)
    assert sorted(table.bot_deck) == sorted(c.card_id for c in st.deck)



@with_rig("doctor-strange", "hellboy", "The Winds of Watoomb", "Feint", "Cloak of Levitation", "Eye of Agamotto", "Bolts of Balthakk")
def test_dark_pact_after_a_winds_of_watoomb_combat_paused_at_the_placement_moves_the_card_too(rig):
    """Live 2/11 15:47: Strange attacks with The Winds of Watoomb, the combat waits for the placement by hand, DARK PACT is paid at the end."""
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "strange", "hellboy")
    human_hand(table, game, "Service Pistol", "Excalibur")
    winds = next(c for c in game.players[0].hand if c.title == "The Winds of Watoomb")
    bot_turn(session, table, [Act("attack", fid="strange", target="hellboy", card=winds)])
    click(session, table, Event.REVEAL)                                # no defense
    req = session._paused()[2].awaiting
    table.positions[cfg.nicknames["strange"]] = req.options[0]          # the human places Doctor Strange by hand
    click(session, table, Event.CHOICE, {"i": 1})                      # Done
    st = game.players[0]
    assert winds in st.deck and winds not in st.discard, "the pact was paid"
    assert winds.card_id not in table.bot_play and table.bot_deck[-1] == winds.card_id
    assert not said(session.messages, "no coincide")
