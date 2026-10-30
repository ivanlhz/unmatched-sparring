"""Remove A Painful Memory played by the human against Liz Sherman, who defends with Pyrotechnics (live, 30/10).

Pyrotechnics (AFTER COMBAT, the defender's, resolved first) puts cards of the bot's hand on the bottom of its deck. The
write rides the `fx` queue domain, which no `cards` read flushes: when the human's card then pauses the combat for the
pick, the reconciliation compared the engine's hand with a table that had not received the write yet, the check failed
(warning, `dirty`, one more failure towards `adopt_after`) and the panel said the bot was paused.
"""
from __future__ import annotations

from test_e3_hidden_info import (LIZ_HAND, answers, attack, click, defend_with, human_hand, row_ids, with_rig, rig,
                                 Event)

LIZ_BOT = ("liz-sherman", "baba-yaga", LIZ_HAND)


def pact_of_freedom(game):
    """The human's active ongoing scheme, as in the live game (this attack is their second action of the turn)."""
    st = game.players[1]
    pact = next(c for c in st.deck if c.title == "Pact Of Freedom")
    st.deck.remove(pact)
    game.fx.set_ongoing(1, pact.card_id)
    game.fx.taken, game.actions_left = 1, 1


def play_memory(session, table, game, monkeypatch, scheme):
    defend_with(session, game, monkeypatch, "Pyrotechnics")
    monkeypatch.setattr(session.ai, "choose_effect", answers(optional=[True], cards=lambda r: list(r.options)[:1]))
    if scheme:
        pact_of_freedom(game)
    human_hand(table, game, "Remove A Painful Memory", "Exploit")
    attack(session, table, game, "baba", "liz", "Remove A Painful Memory")
    return click(session, table, Event.REVEAL)


@with_rig(*LIZ_BOT)
def test_the_hand_shown_after_pyrotechnics_is_clean_and_waits_for_the_human(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    msgs = play_memory(session, table, game, monkeypatch, scheme=True)
    st = game.players[0]
    assert session.look is not None and session.look["mode"] == "pick"
    assert sorted(row_ids(session)) == sorted(c.card_id for c in st.hand) == sorted(table.look_row)
    assert not any("aun no coincide" in m for m in msgs), msgs
    assert not session.dirty and session.flush_failures == 0
    assert game.turn == 1 and session.pending is not None            # the bot takes no turn while the pick is open


@with_rig(*LIZ_BOT)
def test_the_human_picks_and_the_bot_answers_then_the_row_is_returned(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    play_memory(session, table, game, monkeypatch, scheme=True)
    st = game.players[0]
    chosen = next(c.card_id for c in st.hand if "burning" not in c.tags)     # Wildfire would bounce a burning card
    msgs = click(session, table, Event.LOOK_PING, {"guid": f"g{chosen}"})
    assert session.look is None and session.pending is None and table.look_row == []
    assert not session.dirty and session.flush_failures == 0 and game.turn == 1
    assert chosen in [c.card_id for c in st.discard] and chosen in table.bot_discard
    assert sorted(table.bot_hand) == sorted(c.card_id for c in st.hand)
    assert any("El bot descarta" in m for m in msgs)


@with_rig(*LIZ_BOT)
def test_without_an_ongoing_scheme_the_hand_is_only_shown(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    msgs = play_memory(session, table, game, monkeypatch, scheme=False)
    assert session.look is not None and session.look["mode"] == "reveal"
    assert not any("aun no coincide" in m for m in msgs) and not session.dirty
    end = click(session, table, Event.END_ACTION)
    assert session.look is None and sorted(table.bot_hand) == sorted(c.card_id for c in game.players[0].hand)
    assert any("Mano del bot devuelta" in m for m in end)
