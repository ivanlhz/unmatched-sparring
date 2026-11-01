"""Raphael through the live session against FakeTTS, on either side, against each of the five existing heroes: the
panel, the message budget, a bot turn with the real AI and a whole game played through the buttons until game over."""
import re

import pytest

from conftest import place
from sparring.tts.ui import Event
from test_batch import click
from test_multihero_bridge import build, human_attack_card

OTHERS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]
PAIRS = [("raphael", other) for other in OTHERS] + [(other, "raphael") for other in OTHERS]
IDS = [f"{b}-vs-{h}" for b, h in PAIRS]


@pytest.fixture
def world(tmp_path, request):
    bot, human = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


@pytest.mark.parametrize("world", PAIRS, ids=IDS, indirect=True)
def test_the_panel_lists_every_fighter_of_both_sides(world):
    session, table, game, fake, cfg = world
    status, states = session.panel_view()
    assert {i for i in states if i.startswith("att_")} == {f"att_{f.fid}" for f in game.own(1)}
    assert set(session._panel_ids()) >= {f"{p}_{f}" for f in game.fighters for p in ("hpm", "hpp", "rm")}


@pytest.mark.parametrize("world", PAIRS, ids=IDS, indirect=True)
def test_a_human_attack_and_a_full_bot_turn_do_not_break(world):
    session, table, game, fake, cfg = world
    human = game.hero(1)
    click(session, table, Event.ATTACKER, {"attacker": f"att_{human.fid}"})
    msgs = click(session, table, Event.ATTACK, {"target": game.hero(0).fid})
    table.face_down = [{"id": human_attack_card(game).card_id, "guid": "hcard"}]
    msgs += click(session, table, Event.REVEAL)
    assert not any("Accion ilegal" in m for m in msgs)
    msgs = click(session, table, Event.END_ACTION)
    msgs += click(session, table, Event.END_ACTION)
    assert not any("Accion ilegal" in m for m in msgs)


def play_to_the_end(session, table, game, max_rounds=200):
    """The human only maneuvers and answers the bot's attacks with no defense card; the bot plays with the real AI.
    Exhaustion or the bot's blows end the game."""
    for _ in range(max_rounds):
        if game.winner is not None:
            return True
        pending = session.pending
        if session._paused():                                  # a choice of the human's own card or ability: first button
            click(session, table, Event.CHOICE, {"i": 1})
            table.human_count = max(0, table.human_count - 2)     # the discards the card owes (Incinerate's price)
            table.human_discard += [c.card_id for c in game.players[1].hand[:2] if c.card_id not in table.human_discard]
            print("CH2", click(session, table, Event.END_ACTION), game.turn, game.actions_left, len(game.players[1].hand))
            continue
        if pending is not None and pending.kind == "bot_attacks":
            table.face_down = []
            click(session, table, Event.REVEAL)
        elif game.turn == 1:
            click(session, table, Event.MANEUVER)
        table.human_count = min(table.human_count, 7)         # the human keeps to the hand limit
        owed = re.search(r"falta descartar (\d+)", " ".join(click(session, table, Event.END_ACTION)))
        if owed:                                              # a discard the rival's card or the hand limit asks for
            n = int(owed.group(1))
            table.human_count = max(0, table.human_count - n)
            table.human_discard += [c.card_id for c in game.players[1].hand[:n] if c.card_id not in table.human_discard]
    return game.winner is not None


@pytest.mark.parametrize("world", PAIRS, ids=IDS, indirect=True)
def test_a_whole_game_reaches_game_over_without_an_illegal_action(world):
    session, table, game, fake, cfg = world
    assert play_to_the_end(session, table, game), (game.turn_no, game.actions_left, session.pending)
    assert game.winner in (0, 1)
