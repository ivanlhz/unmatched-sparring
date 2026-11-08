"""Golden Bat's Sight Beyond Sight played by the bot against the human at the live table (FakeTTS): the bot reads the real top three
through the table reader and reorders them itself, blind (Ivan, 2026-11-08): the chat says how many cards it reordered and never
which, the deck keeps its size, nothing is revealed and the bot remembers the cards only until they are drawn. Same rig as
tests/test_jill_trent_human.py."""
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


def play_sight_beyond_sight(session, table, game, cfg):
    """The bot attacks with Sight Beyond Sight against a human whose real deck starts with three known cards; returns the chat."""
    bat, foe = game.fighters["bat"], game.fighters["hellboy"]
    foe.pos = next(s for s in sorted(game.board.adj[bat.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = foe.pos
    table.human_deck = [c.card_id for c in game.players[1].deck[5:8]]     # none of them in the engine's virtual hand
    human_hand(table, game, TRAINING)
    card = next(c for c in game.players[0].hand if c.title == "Sight Beyond Sight")
    bot_turn(session, table, [Act("attack", fid="bat", target="hellboy", card=card)])
    cid = card_ids(game, 1, TRAINING)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1


def test_the_bot_reorders_your_real_top_three_blind_and_names_no_card(rig):
    session, table, game, fake, cfg = rig
    play_sight_beyond_sight(session, table, game, cfg)
    before = list(table.human_deck)
    titles = [c.title for c in game.players[1].full_set if c.card_id in before]
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "he reordenado las 3 cartas superiores de tu mazo"), msgs
    assert not said(msgs, "Hazlo a mano") and not said(msgs, "pon estas cartas") and not said(msgs, "Reveladas arriba"), msgs
    assert not [t for t in titles if said(msgs, t)], "no card of the human's deck is named"
    assert len(table.reorders) == 1 and table.reorders[0][:3] == (before, table.reorders[0][1], []) and table.reorders[0][3],         "one op, inside the step's composite, with the cards as they were read"
    top = game.players[0].known.top_of_deck
    assert sorted(top) == sorted(before) and table.human_deck == top, "the real deck is in the order the bot chose and it remembers it"
    assert len(table.human_deck) == len(before) and table.row == [] and table.homes == [], "same count, nothing laid out"
    game.draw(1, 1)
    assert game.players[0].known.top_of_deck == []


def test_a_top_that_changed_since_it_was_read_aborts_the_reorder_and_the_bot_forgets_it(rig):
    session, table, game, fake, cfg = rig
    play_sight_beyond_sight(session, table, game, cfg)
    before = list(table.human_deck)
    titles = [c.title for c in game.players[1].full_set if c.card_id in before]
    read = table.do_peek_deck_top

    def read_then_drift(s):
        out = read(s)
        table.human_deck.insert(0, table.human_deck.pop(2))      # someone moves a card between the read and the move
        return out
    table.do_peek_deck_top = read_then_drift
    drifted = [before[2], before[0], before[1]]
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "no he podido reordenar tu mazo"), msgs
    assert table.human_deck == drifted, "nothing moved"
    assert game.players[0].known.top_of_deck == []
    assert not [t for t in titles if said(msgs, t)] and not said(msgs, "cartas superiores"), msgs


@pytest.mark.parametrize("events", [
    [Event.END_ACTION, Event.END_ACTION, Event.END_ACTION],
    [Event.MANEUVER, Event.END_ACTION, Event.MANEUVER, Event.END_ACTION],
])
def test_later_buttons_never_name_the_cards_the_bot_read(rig, events):
    """Regression (review of b0040f5): the next button used to print "Pon X, Y de tu mano en tu mazo" with the cards read blind."""
    session, table, game, fake, cfg = rig
    play_sight_beyond_sight(session, table, game, cfg)
    titles = [c.title for c in game.players[1].full_set if c.card_id in table.human_deck]
    click(session, table, Event.REVEAL)
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    later = [str(m) for ev in events for m in click(session, table, ev)]
    assert not [(t, m) for m in later for t in titles if t in m]
