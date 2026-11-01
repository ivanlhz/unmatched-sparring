"""Whole games through the session on FakeTTS: Donatello against each existing hero, on either side, until game over.

The human is a script that only maneuvers (two actions a turn, INVENTIVE declined or taken alternately, no defense), so
the bot's real AI does everything else; the game ends by exhaustion or by the bot's attacks. What is checked is that
no step raises, the engine never reports an illegal action and the game really ends."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build, human_hand
from test_donatello_session import AsideTable, SPOTS
from test_e2_human_cards import press

OTHERS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]
PAIRS = [("donatello", o) for o in OTHERS] + [(o, "donatello") for o in OTHERS]
MAX_BUTTONS = 900


def play_to_the_end(session, table, game) -> int:
    buttons = 0
    toggle = False
    while game.winner is None and buttons < MAX_BUTTONS:
        buttons += 1
        if session._paused() is not None:
            req = session.effect_run.awaiting
            msgs = (press(session, table, toggle) if req.kind == "optional"
                    else click(session, table, Event.CHOICE, {"i": 1}))
            toggle = not toggle
        elif session.pending is not None:
            msgs = click(session, table, Event.REVEAL)
        elif game.turn == session.human:
            for fid, f in game.fighters.items():
                if f.alive and f.owner == session.human and f.pos is not None:
                    table.positions[session.cfg.nicknames[fid]] = f.pos
            owed = session.pending_discard
            if owed is not None:                          # the hand limit: they put the cards on the pile
                for c in [c for c in game.players[session.human].hand if c.card_id not in table.human_discard][-owed["n"]:]:
                    table.human_discard.append(c.card_id)
                    table.human_count -= 1
            # END_ACTION closes the start-of-turn ability, an open action and the turn itself
            ends = session.ability_wait or session.moving or game.actions_left == 0
            msgs = click(session, table, Event.END_ACTION if ends else Event.MANEUVER)
        else:                                             # the bot's combat waits for them to settle its after-combat effects
            msgs = click(session, table, Event.END_ACTION)
        assert not any("Accion ilegal" in m for m in msgs), msgs
    return buttons


@pytest.mark.parametrize("bot,human", PAIRS, ids=[f"{b}-vs-{h}" for b, h in PAIRS])
def test_a_whole_game_reaches_game_over(tmp_path, bot, human):
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    try:
        game.turn = session.human
        game.begin_turn()
        table.human_hand = [c.card_id for c in game.players[session.human].hand]
        table.human_count = len(table.human_hand)
        buttons = play_to_the_end(session, table, game)
        assert game.winner is not None, f"no game over after {buttons} buttons"
    finally:
        client.close()
        fake.close()
