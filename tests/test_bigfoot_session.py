"""The bot's Bigfoot on the live session (FakeTTS, batch mode): the end-of-turn draw dealt on the table, Jackalope Horns played by the
Jackalope and its miniature moved, Savagery's damage to the fighters next to Bigfoot with the dials following. The engine side of the same
cards is in tests/test_bigfoot_effects.py and the human side in tests/test_bigfoot_human.py."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_bigfoot_human import centre, isolate_bot
from test_d3_table_effects import bot_turn, human_hand, said
from test_e2_human_cards import put_adjacent, with_rig
from test_bigfoot_human import rig  # noqa: F401

BOT_HAND = ("Jackalope Horns", "Savagery", "Hoax", "Feint", "Regroup")


def bot_card(game, title):
    return next(c for c in game.players[0].hand if c.title == title)


@with_rig("bigfoot", "hellboy", "Jackalope Horns", "Savagery", "Hoax")
def test_the_bots_end_of_turn_draw_is_dealt_on_the_table_when_no_rival_is_in_its_zone(rig):
    session, table, game, fake, cfg = rig
    isolate_bot_rivals(game, table, cfg)
    bot_turn(session, table, [])
    assert game.turn == 1
    assert len(game.players[0].hand) == len(table.bot_hand), "the engine and the table disagree on the bot's hand"
    assert len(game.players[0].hand) == 3 + 2 + 1                       # the two maneuvers drew one card each and the ability one


@with_rig("bigfoot", "hellboy", "Jackalope Horns", "Savagery", "Hoax", "Feint", "Regroup")
def test_the_bot_does_not_draw_at_the_end_of_its_turn_with_its_hand_at_the_limit(rig):
    session, table, game, fake, cfg = rig
    isolate_bot_rivals(game, table, cfg)
    bot_turn(session, table, [])
    assert len(game.players[0].hand) == len(table.bot_hand) == 7        # 5 + the two maneuvers: no room for the ability's card


@with_rig("bigfoot", "hellboy", "Jackalope Horns", "Savagery", "Hoax")
def test_the_bot_does_not_draw_at_the_end_of_its_turn_with_a_rival_in_its_zone(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    hand = len(game.players[0].hand)
    bot_turn(session, table, [])
    assert len(game.players[0].hand) == len(table.bot_hand) and len(game.players[0].hand) == hand + 2     # the two maneuvers drew, nothing else


@with_rig("bigfoot", "hellboy", *BOT_HAND)
def test_the_bots_jackalope_plays_jackalope_horns_moves_on_the_table_and_hits_for_two(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    horns = bot_card(game, "Jackalope Horns")
    hp = game.fighters["hellboy"].hp
    msgs = bot_turn(session, table, [Act("scheme", 5.0, "jackalope", "", horns)])
    jackalope = game.fighters["jackalope"]
    assert (cfg.nicknames["jackalope"], jackalope.pos) in table.moves and table.positions[cfg.nicknames["jackalope"]] == jackalope.pos
    assert game.board.distance(jackalope.pos, game.fighters["hellboy"].pos) == 1
    assert game.fighters["hellboy"].hp == hp - 2 and cfg.session_config().dials["hellboy"] in {g for g, _ in table.dial_writes}
    assert said(msgs, "El bot juega Jackalope Horns. Mueve") and horns.card_id in table.bot_discard and not any("ilegal" in m.lower() for m in msgs), msgs


@with_rig("bigfoot", "hellboy", *BOT_HAND)
def test_the_bots_savagery_hurts_everyone_next_to_bigfoot_and_the_dials_follow(rig):
    session, table, game, fake, cfg = rig
    centre(game, table, cfg)
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    put_adjacent(game, table, cfg, "lobster", "bigfoot")
    put_adjacent(game, table, cfg, "jackalope", "bigfoot")
    savagery = bot_card(game, "Savagery")
    hp = {fid: game.fighters[fid].hp for fid in ("hellboy", "lobster", "jackalope")}
    bot_turn(session, table, [Act("attack", fid="bigfoot", target="hellboy", card=savagery)])
    table.face_down = []                                                # the human does not defend
    click(session, table, Event.REVEAL)
    assert game.fighters["hellboy"].hp == hp["hellboy"] - 4 - 1
    assert game.fighters["lobster"].hp == hp["lobster"] - 1 and game.fighters["jackalope"].hp == hp["jackalope"] - 1
    written = {g for g, _ in table.dial_writes}
    assert {session.cfg.dials[f] for f in ("hellboy", "lobster", "jackalope")} <= written


def isolate_bot_rivals(game, table, cfg):
    """The human's fighters (Hellboy and Lobster) outside Bigfoot's zone."""
    bigfoot = game.fighters["bigfoot"]
    far = [s for s in sorted(game.board.spaces, reverse=True) if not game.board.share_zone(bigfoot.pos, s)]
    for f, s in zip([f for f in game.fighters.values() if f.alive and f.owner == 1], far):
        f.pos = s
        table.positions[cfg.nicknames[f.fid]] = s
