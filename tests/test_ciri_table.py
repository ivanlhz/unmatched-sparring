"""Ciri's Source dial at the table (FakeTTS, batch mode): the dial of the bag mirrors the Source cards of her discard pile on either side
(`session_source`), alone and next to Hellboy's destiny dial, and the bot's Ciri takes the card Searching strike finds out of its real
deck. The cards and tiers themselves are in tests/test_ciri_effects.py and tests/test_ciri_human.py."""
from __future__ import annotations

import re

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from conftest import TEST_IDENT
from test_d3_table_effects import FxTable, bot_turn, build, human_attack, human_hand, said, set_hand, to_bot_discard
from test_e2_human_cards import put_adjacent

TRAINING = "B.P.R.D. Training"


class CiriTable(FxTable):
    """The fake table plus `deck_card_to_hand`: the card named by CardID leaves the bot's deck for its hand (like real TTS, which reports a
    `Deck` or a loose `Card` there and never the top card unless it is the one asked for)."""

    def do_deck_card_to_hand(self, s):
        i = int(re.search(r"CardID (?:~=|==) (\d+)", s).group(1))
        if i not in self.bot_deck:
            return {"taken": False}
        self.bot_deck.remove(i)
        self.bot_hand.append(i)
        self.taken_from_deck.append(i)
        return {"taken": True, "guid": f"g{i}"}

    taken_from_deck: list = []


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=CiriTable)
    table.taken_from_deck = []
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def rigged(bot, human, *hand):
    return pytest.mark.parametrize("rig", [(bot, human, hand)], indirect=True)


def source_ids(game, player, n):
    return [c.card_id for c in game.players[player].full_set if "source" in c.tags][:n]


def test_the_source_dial_is_in_the_table_data_and_the_session_config(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "ciri", "hellboy", ("Blink",))
    try:
        dial = cfg.session_config().source_dial
        assert dial == "46aa92" and cfg.session_config().destiny_dial is not None      # Hellboy's own dial is a different one
        assert dial in session.guids_in_use() and [dial] in session.guid_groups()
        assert table.dials[dial]["value"] == 0
    finally:
        client.close()
        fake.close()


@rigged("hellboy", "abe-sapien", "Service Pistol")
def test_a_game_without_ciri_has_no_source_dial(rig):
    session, table, game, fake, cfg = rig
    assert cfg.session_config().source_dial is None
    assert session._write_dials()


@rigged("ciri", "hellboy", "Blink", "Lion cub of Cintra")
def test_the_bots_source_dial_follows_its_discard_pile_up_and_down(rig):
    session, table, game, fake, cfg = rig
    dial = cfg.session_config().source_dial
    to_bot_discard(session, table, game, ids=source_ids(game, 0, 3))
    assert session._write_dials()
    assert table.dials[dial]["value"] == 3 and session.source_seen == 3
    st = game.players[0]
    gone = next(c for c in st.discard if "source" in c.tags)
    st.discard.remove(gone)                                     # back to the hand, on the table and in the engine
    st.hand.append(gone)
    table.bot_discard.remove(gone.card_id)
    table.bot_hand.append(gone.card_id)
    session.bot_discarded.discard(gone.card_id)
    bot_turn(session, table, [])
    assert table.dials[dial]["value"] == game.counter(0, "source") == 2


@rigged("ciri", "hellboy", "Lion cub of Cintra", "Blink")
def test_the_bots_source_dial_counts_the_source_card_it_just_played(rig):
    session, table, game, fake, cfg = rig
    dial = cfg.session_config().source_dial
    put_adjacent(game, table, cfg, "hellboy", "ciri")
    lion = next(c for c in game.players[0].hand if c.title == "Lion cub of Cintra")
    human_hand(table, game, TRAINING)
    bot_turn(session, table, [Act("attack", fid="ciri", target="hellboy", card=lion)])
    click(session, table, Event.REVEAL)                          # the human defends with nothing
    assert game.counter(0, "source") >= 1 and table.dials[dial]["value"] == game.counter(0, "source")


@rigged("hellboy", "ciri", "Service Pistol")
def test_the_humans_source_dial_follows_the_pile_they_play_to(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    dial = cfg.session_config().source_dial
    put_adjacent(game, table, cfg, "ciri", "hellboy")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)
    human_hand(table, game, "Lion cub of Cintra", "Zireael", "Blink")
    human_attack(session, table, game, "ciri", "hellboy", "Lion cub of Cintra")
    click(session, table, Event.REVEAL)
    assert game.counter(1, "source") == 1 and table.dials[dial]["value"] == 1
    click(session, table, Event.END_ACTION)
    assert table.dials[dial]["value"] == game.counter(1, "source")


@rigged("hellboy", "ciri", "Service Pistol")
def test_hellboys_destiny_dial_and_ciris_source_dial_are_two_dials(rig):
    session, table, game, fake, cfg = rig
    scfg = cfg.session_config()
    assert scfg.destiny_dial and scfg.source_dial and scfg.destiny_dial != scfg.source_dial
    destiny = [c for c in game.players[0].full_set if "destiny" in c.tags]
    to_bot_discard(session, table, game, ids=[c.card_id for c in destiny[:3]])
    source = [c for c in game.players[1].full_set if "source" in c.tags][:2]
    for c in source:
        game.players[1].discard.append(c)
        table.human_discard.append(c.card_id)
    assert session._write_dials()
    assert table.dials[scfg.destiny_dial]["value"] == 3 and table.dials[scfg.source_dial]["value"] == 2


@rigged("ciri", "hellboy", "Blink")
def test_a_new_game_puts_the_source_dial_back_to_zero(rig):
    session, table, game, fake, cfg = rig
    dial = cfg.session_config().source_dial
    to_bot_discard(session, table, game, ids=source_ids(game, 0, 4))
    session._write_dials()
    assert table.dials[dial]["value"] == 4
    game.players[0].discard.clear()
    assert session._write_dials() and table.dials[dial]["value"] == 0


@rigged("ciri", "hellboy", "Searching strike", "Blink")
def test_the_bots_searching_strike_takes_the_source_card_it_found_out_of_its_real_deck_and_says_it(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "ihuarraquax", "hellboy")
    strike = next(c for c in game.players[0].hand if c.title == "Searching strike")
    human_hand(table, game, TRAINING)
    bot_turn(session, table, [Act("attack", fid="ihuarraquax", target="hellboy", card=strike)])
    msgs = click(session, table, Event.REVEAL)                  # the human defends with nothing: she wins
    by_id = {c.card_id: c for c in game.players[0].full_set}
    assert len(table.taken_from_deck) == 1, msgs
    found = by_id[table.taken_from_deck[0]]
    assert "source" in found.tags and found in game.players[0].hand and found.card_id in table.bot_hand
    assert said(msgs, f"revela {found.title}"), msgs


@rigged("ciri", "hellboy", "Searching strike", "Blink")
def test_a_table_that_refuses_the_search_take_is_told_to_the_human(rig):
    session, table, game, fake, cfg = rig
    table.do_deck_card_to_hand = lambda s: {"taken": False}
    put_adjacent(game, table, cfg, "ihuarraquax", "hellboy")
    strike = next(c for c in game.players[0].hand if c.title == "Searching strike")
    human_hand(table, game, TRAINING)
    bot_turn(session, table, [Act("attack", fid="ihuarraquax", target="hellboy", card=strike)])
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "No pude sacar"), msgs


def test_the_deck_search_builder_is_sendable_composable_and_refuses_what_is_not_ours():
    from sparring.tts import lua, lua_search
    ident = TEST_IDENT
    script = lua_search.deck_card_to_hand(17610, "abc123", "Blue", identity=ident)
    assert script.startswith("-- sparring:deck_card_to_hand" + chr(10)) and lua.is_sendable(script)
    assert "getHandTransform" in script and "takeObject" in script and "17610" in script
    assert lua.is_sendable(lua.composite([script]))
    for bad in (dict(card_id="1"), dict(deck_guid="not a guid!"), dict(seat_color="Mauve")):
        args = dict(card_id=17610, deck_guid="abc123", seat_color="Blue", identity=ident)
        args.update(bad)
        with pytest.raises((ValueError, TypeError)):
            lua_search.deck_card_to_hand(**args)


@pytest.mark.parametrize("kind", ["Custom_Model", "Custom_Token", "Tile", "Token", "Figurine"])
def test_ihuarraquaxs_token_is_a_piece_whatever_type_real_tts_reports_for_it(kind):
    """The bag holds Ihuarraquax as a `Custom_Token`; spawned, TTS reports a "Tile" (or "Token"). A resolution by name must accept it."""
    from sparring.session_pieces import is_piece_type
    assert is_piece_type(kind)
    assert not is_piece_type("Deck") and not is_piece_type("Card") and not is_piece_type(None)


@rigged("ciri", "hellboy", "Zireael", "Blink")
def test_the_bots_zireael_at_source_five_names_a_random_position_of_the_humans_hand(rig):
    """The same rule as Fleeting Moments (Iván 29/10): the engine draws the position, the human discards that card and the bot never reads the hand."""
    session, table, game, fake, cfg = rig
    to_bot_discard(session, table, game, ids=source_ids(game, 0, 5))
    zireael = next(c for c in game.players[0].hand if c.title == "Zireael")
    put_adjacent(game, table, cfg, "hellboy", "ciri")
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    bot_turn(session, table, [Act("attack", fid="ciri", target="hellboy", card=zireael)])
    table.face_down = []
    msgs = click(session, table, Event.REVEAL)
    assert session.pending_discard["n"] == 1, msgs
    line = next(m for m in msgs if "Descarta 1 carta(s) (Zireael, al azar: la carta " in m)
    assert 1 <= int(line.split("la carta ")[1].split(" ")[0]) <= len(game.players[1].hand)
    assert game.counter(0, "source") == 6                          # the 5 it had and the Zireael it just played
