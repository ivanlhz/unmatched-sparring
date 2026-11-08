"""Golden Bat's Sight Beyond Sight played by the bot against the human at the live table (FakeTTS): the bot reads the real top three
through the table reader, tells the human how to arrange them by hand, never moves the deck and remembers the cards only until
they are drawn. Same rig as tests/test_jill_trent_human.py."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_hand, said
from test_jill_trent_human import JillTable, TRAINING


@pytest.fixture
def rig(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "golden-bat", "hellboy", ("Sight Beyond Sight", "Super Strength", "Skirmish"),
                                                    table_cls=JillTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def test_the_bot_reads_your_top_three_tells_you_the_order_and_never_names_them_as_revealed(rig):
    session, table, game, fake, cfg = rig
    bat, foe = game.fighters["bat"], game.fighters["hellboy"]
    foe.pos = next(s for s in sorted(game.board.adj[bat.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = foe.pos
    table.human_deck = card_ids(game, 1, "Excalibur", "Right Hand Of Doom", "Service Pistol")
    human_hand(table, game, TRAINING)
    card = next(c for c in game.players[0].hand if c.title == "Sight Beyond Sight")
    bot_turn(session, table, [Act("attack", fid="bat", target="hellboy", card=card)])
    cid = card_ids(game, 1, TRAINING)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    before = list(table.human_deck)
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "pon estas cartas encima de tu mazo") and said(msgs, "Hazlo a mano"), msgs
    assert not said(msgs, "Reveladas arriba"), msgs
    assert table.human_deck == before, "the real deck is theirs: the bot never moves it"
    top = game.players[0].known.top_of_deck
    assert sorted(top) == sorted(before[:3])
    game.draw(1, 1)
    assert game.players[0].known.top_of_deck == []
