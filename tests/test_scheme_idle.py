"""A scheme counts as idle ("sin efecto, solo recupera la accion", worth no action credit) only when it changed nothing
at all: a status, a modifier, a counter or the rival's cards are changes (reviewer finding on bede8f1). Plus the
Wildfire "already said" flag never outliving a failed flush."""
import pytest

from sparring.ai_medusa import Act, MedusaAI, play_signature
from sparring.board import Board
from sparring.hellboy_script import ScriptedHellboy
from sparring.state import Game
from test_d3_table_effects import build as d3_build

BOT, HUMAN = 0, 1


def abe_hand(*titles):
    ai = MedusaAI(BOT)
    game = Game.new(Board.load("bprd-hq"), 1, {BOT: ai, HUMAN: ScriptedHellboy(HUMAN, 0)}, bot_player=BOT,
                    heroes=("abe-sapien", "baba-yaga"))
    me = game.players[BOT]
    me.hand[:] = [next(c for c in me.full_set if c.title == t) for t in titles]
    me.deck[:] = [c for c in me.full_set if c not in me.hand]
    me.discard.clear()
    game.turn, game.actions_left = BOT, 2
    return game, ai


def test_utility_belt_adds_a_status_so_it_is_not_idle():
    game, ai = abe_hand("B.P.R.D. Utility Belt", "B.P.R.D. Training")
    card = game.players[BOT].hand[0]
    after = ai.effect_ai().scheme_outcome(game, card, BOT)
    assert after is not None and after.fx.statuses
    assert not ai.scheme_changed_nothing(game, after, card)
    act = ai.scheme_act(game, card)
    assert act.value > -0.4, "the action it hands back is credited: it did something"


def test_every_possible_angle_is_not_idle():
    game, ai = abe_hand("Every Possible Angle", "B.P.R.D. Training")
    card = game.players[BOT].hand[0]
    after = ai.effect_ai().scheme_outcome(game, card, BOT)
    assert after is not None
    assert not ai.scheme_changed_nothing(game, after, card)


def test_the_signature_sees_statuses_modifiers_counters_and_the_rivals_cards():
    game, ai = abe_hand("B.P.R.D. Training", "B.P.R.D. Training")
    card = game.players[BOT].hand[0]
    base = play_signature(game, BOT, card)
    assert play_signature(game, BOT, card) == base
    game.fx.statuses.append({"name": "next_attack_bonus", "player": BOT, "amount": 1})
    assert play_signature(game, BOT, card) != base
    game.fx.statuses.clear()
    game.fx.modifiers.append({"kind": "x"})
    assert play_signature(game, BOT, card) != base
    game.fx.modifiers.clear()
    game.fx.counters[BOT]["c"] = 1
    assert play_signature(game, BOT, card) != base
    game.fx.counters[BOT].clear()
    rival = game.players[HUMAN]
    rival.deck.append(rival.deck.pop(0))
    assert play_signature(game, BOT, card) != base


def test_the_chat_does_not_call_a_status_scheme_empty(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = d3_build(tmp_path, "abe-sapien", "baba-yaga", ["B.P.R.D. Utility Belt", "B.P.R.D. Training"])
    belt = next(c for c in game.players[BOT].hand if c.title == "B.P.R.D. Utility Belt")
    pos = game.hero(BOT).pos
    plans = iter([Act("scheme", 0, "abe", "", belt)] + [Act("maneuver", moves={"abe": pos})] * 4)
    monkeypatch.setattr(session.ai, "plan", lambda g: next(plans))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.turn, game.actions_left, session.bot_stage = BOT, 2, None
    session.messages = []
    session._bot_continue()
    client.close()
    played = [m for m in session.messages if m.startswith("El bot juega B.P.R.D. Utility Belt")]
    assert len(played) == 1 and "sin efecto" not in played[0]


def test_a_failed_wildfire_flush_does_not_leave_the_already_said_flag(tmp_path, monkeypatch):
    from test_liz_wildfire_scene import liz_session, start_bot_turn
    session, table, game, fake, cfg, card_back, client = liz_session(tmp_path, monkeypatch, burning=True)

    def boom(*a, **k):
        raise RuntimeError("flush failed")
    monkeypatch.setattr(session, "_flush_table_stage", boom)
    with pytest.raises(RuntimeError):
        start_bot_turn(session, game)
    client.close()
    assert not session.said_returns
