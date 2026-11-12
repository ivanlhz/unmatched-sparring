"""Bot Doctor Strange pays DARK PACT in a combat that is not paused: the card goes to the BOTTOM of its deck and the draw
the pact owes comes from the TOP (live 12/11: the bot kept drawing the card it had just put at the bottom)."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, human_hand
from test_e2_human_cards import put_adjacent, rig, with_rig  # noqa: F401

HAND = ("Feint", "Cloak of Levitation", "Eye of Agamotto", "Master of Kamar-Taj", "Steadfast Disciple")


@with_rig("doctor-strange", "hellboy", *HAND)
def test_the_pact_draw_is_the_top_card_not_the_one_just_sent_to_the_bottom(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "strange", "hellboy")
    human_hand(table, game, "Service Pistol", "Excalibur")
    feint = next(c for c in game.players[0].hand if c.title == "Feint")
    top = game.players[0].deck[0].card_id
    assert table.bot_deck[0] == top
    bot_turn(session, table, [Act("attack", fid="strange", target="hellboy", card=feint)])
    click(session, table, Event.REVEAL)
    st = game.players[0]
    assert game.fighters["strange"].hp == 13, "the pact was paid"
    assert table.bot_deck[-1] == feint.card_id, "the card went to the bottom"
    assert feint.card_id not in table.bot_hand, "and was not the card drawn"
    assert top in table.bot_hand, "the draw is the old top card"
    assert sorted(table.bot_hand) == sorted(c.card_id for c in st.hand)


@with_rig("doctor-strange", "hellboy", *HAND)
def test_the_pact_after_a_defense_also_draws_the_top_card(rig, monkeypatch):
    from test_d3_table_effects import human_attack
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "strange", "hellboy")
    human_hand(table, game, "Service Pistol", "Excalibur")
    feint = next(c for c in game.players[0].hand if c.title == "Feint")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: feint)
    top = game.players[0].deck[0].card_id
    human_attack(session, table, game, "hellboy", "strange", "Service Pistol")
    click(session, table, Event.REVEAL)
    assert game.fighters["strange"].hp <= 13 and feint in game.players[0].deck
    assert table.bot_deck[-1] == feint.card_id and feint.card_id not in table.bot_hand
    assert top in table.bot_hand


@with_rig("doctor-strange", "hellboy", *HAND)
def test_the_session_follows_the_deck_the_table_rebuilt_under_the_card(rig):
    """The bottom of a deck is reached by rebuilding it (lua_deck.BURY_LUA): TTS gives the new deck another GUID and the reply
    carries it next to the one that was asked for."""
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "strange", "hellboy")
    human_hand(table, game, "Service Pistol", "Excalibur")
    feint = next(c for c in game.players[0].hand if c.title == "Feint")
    configured, plain = session.cfg.bot_deck_guid, table._deck_insert
    asked = []

    def rebuilt(s, kind):
        asked.append(configured if f'findDeck("{configured}")' in s else None)
        return {**plain(s, kind), "asked": asked[-1], "deck": "new0d1"}
    table._deck_insert = rebuilt
    bot_turn(session, table, [Act("attack", fid="strange", target="hellboy", card=feint)])
    click(session, table, Event.REVEAL)
    assert asked == [configured] and table.bot_deck[-1] == feint.card_id
    assert session.cfg.bot_deck_guid == "new0d1", "the next deal asks for the deck that is there"
    assert session.configured_decks["bot_deck_guid"] == configured, "the identity of the table keeps the configured one"
