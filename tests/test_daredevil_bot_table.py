"""Daredevil as the BOT, Devil of Hell's Kitchen with the draw deck empty, on the table (FakeTTS).

Real TTS has no Deck object once the last card is drawn, so the Devil's AFTER ("shuffle this card and the top four cards of your
discard pile into your deck") had no deck to write to: the cards stayed on the table while the engine counted them in the deck.
The table deck then ran dry while the engine still saw cards in it, and the next Devil stayed at 4 instead of 8 (player report,
v0.5.0). The fake table refuses a shuffle into an empty deck unless the script lays the first card down as the new deck."""
from __future__ import annotations


from sparring.ai_medusa import Act
from sparring.tts import lua
from test_d3_table_effects import bot_turn, build, card_ids, said, set_hand, to_bot_discard
from test_donatello_session import SPOTS, AsideTable
from test_batch import click
from sparring.tts.ui import Event

DEVIL = "Devil of Hell's Kitchen"
IDENT = (("https://x.test/f.jpg", "https://x.test/b.jpg"),)


def devil_with_an_empty_deck(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "daredevil", "hellboy", (DEVIL, "Feint"), table_cls=AsideTable, **SPOTS)
    st = game.players[0]
    held = set(card_ids(game, 0, DEVIL, "Feint"))
    to_bot_discard(session, table, game, ids=[c.card_id for c in st.full_set if c.card_id not in held])
    set_hand(session, table, game, DEVIL, "Feint")
    assert not st.deck and not table.bot_deck, "both the engine and the table have no deck"
    return session, table, game, fake, cfg, client


def bot_plays_the_devil(session, table, game, cfg):
    from test_e2_human_cards import put_adjacent
    put_adjacent(game, table, cfg, "daredevil", "hellboy")
    devil = next(c for c in game.players[0].hand if c.title == DEVIL)
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    bot_turn(session, table, [Act("attack", fid="daredevil", target="hellboy", card=devil)])
    return click(session, table, Event.REVEAL), devil


def test_the_devil_is_worth_8_with_the_deck_empty_and_goes_back_into_the_deck_the_table_no_longer_has(tmp_path):
    session, table, game, fake, cfg, client = devil_with_an_empty_deck(tmp_path)
    try:
        msgs, devil = bot_plays_the_devil(session, table, game, cfg)
        assert said(msgs, "Devil of Hell's Kitchen (8): total 8")
        assert not said(msgs, "hazlo tu"), msgs
        engine = {c.card_id for c in game.players[0].deck}
        assert devil.card_id in engine and len(engine) == 5
        assert set(table.bot_deck) == engine, "the table deck is the engine's deck: the Devil and the last four cards of the pile"
        assert devil.card_id not in table.bot_play and devil.card_id not in table.bot_discard
    finally:
        client.close()
        fake.close()


def test_the_shuffle_script_lays_the_first_card_down_as_the_deck_when_there_is_none():
    script = lua.shuffle_into_deck("deck1", ["g1", "g2"], (17600, 17621), identity=IDENT, spot=(3.0, 4.0))
    assert "-- an empty draw deck is no object in TTS" in script and "if deck == nil and home == nil" in script
    assert "x = 3.0" in script and "z = 4.0" in script
    bare = lua.shuffle_into_deck("deck1", ["g1"], (17600, 17621), identity=IDENT)
    assert "local home = nil" in bare, "no place to lay it: the old refusal stays (the human is told)"
