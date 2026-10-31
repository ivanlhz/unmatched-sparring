"""E1 review: one pause mechanism for the human's effect choices.

A combat stopped inside a C2 card effect (Posthumous Power's AFTER `choose_effect`, Hellboy's side through the
interpreter) lives in `Pending.flow` and is answered through the same choice buttons as a free-standing effect or a
parked trigger; a rollback restores the saved-game snapshot; Cold Iron And Holy Water and a pinned fighter are
refused at the panel; the look at the bot's hand is granted by the card that allows it and revoked afterwards."""
import copy
import json

import pytest

from sparring import persist
from sparring.ai_medusa import MedusaAI
from sparring.effects import modifiers
from sparring.effects.choose import ControllerChooser, PanelChooser
from sparring.effects.ops_core import OPS
from sparring.effects.run import Ctx, EffectRun
from sparring.session import CROWN, Session
from sparring.state import Game, RuleError
from sparring.tts import ui
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_choice_infra import pancakes, visible_choices
from test_golden import jsonable
from test_session import human_plays

CHOICE = ui.CHOICE_BUTTONS
UNTIL = {"event": "end_of_turn"}


def lobster_attacks_with_posthumous_power(session, table, game):
    """The Lobster (DSL side) attacks Medusa with Posthumous Power and the combat stops at its AFTER choice."""
    game.fx.dsl_heroes = {"hellboy"}
    spot = next(s for s in sorted(game.board.adj[0]) if all(f.pos != s for f in game.fighters.values()))
    game.fighters["lobster"].pos = spot
    table.positions["Lobster Johnson"] = spot
    session.snap = None
    click(session, table, Event.ATTACKER, {"attacker": "att_lobster"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Posthumous Power")
    table.human_count -= 1                        # the card left the human's hand on the table
    click(session, table, Event.REVEAL)
    p = session.pending
    assert p is not None and p.flow is not None and p.flow.pending.kind == "effect" and p.wait is None
    assert session.effect_run.awaiting.kind == "effect" and game.actions_left == 1
    return p


def twin(session, saved):
    other = Session(Game.new(session.game.board, seed=3, controllers={}), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(json.loads(json.dumps(saved)))
    return other


def test_a_combat_pauses_at_the_human_effect_choice_with_the_buttons_and_everything_else_greyed(brig):
    session, table, game, _ = brig
    lobster_attacks_with_posthumous_power(session, table, game)
    assert visible_choices(session) == list(CHOICE[:3])
    assert session.panel_labels()["btn_choice_2"].startswith("deal 1 damage")
    states = session.panel_view()[1]
    assert states["btn_reveal"][0] is False and states["btn_end"][0] is False and states["btn_cancel"][0] is False
    assert "Elige un efecto" in session.panel_view()[0]
    click(session, table, Event.END_ACTION)
    assert session.pending is not None and any("eleccion de efecto pendiente" in m for m in session.messages)


def test_resume_mid_effect_inside_a_combat(brig):
    session, table, game, fake = brig
    lobster_attacks_with_posthumous_power(session, table, game)
    assert any("Combate:" in m for m in session.messages), "the result is said at the pause (AFTER), not after the choice"
    saved = session.to_dict()
    assert saved["pending"]["flow"]["pending"]["kind"] == "effect" and set(saved["pending"]["combat"]) >= {"flip", "boost"}
    buttons = (session.panel_view(), session.panel_labels())
    table_copy = copy.deepcopy(table)

    # uninterrupted: damage to Medusa (a second pause asks the target), then the combat closes
    click(session, table, Event.CHOICE, {"i": 2})
    assert session.pending is not None and session.effect_run.awaiting.kind == "fighter"
    target = session.effect_run.awaiting.options.index("medusa") + 1
    click(session, table, Event.CHOICE, {"i": target})
    assert session.pending is None and session.moving and session.effect_run is None
    assert game.fighters["medusa"].hp == 15 and not any("Combate:" in m for m in session.messages)
    bot = game.players[0]
    assert not set(bot.hand) & set(bot.discard) and not set(bot.deck) & set(bot.discard)    # the held card went to one pile
    final = jsonable(persist.game_to_dict(game))

    # interrupted: saved at the first pause, reloaded, resumed, answered the same way
    other = twin(session, saved)
    fake.return_value = table_copy
    p = other.pending
    assert p.flow is not None and p.flow.pending.kind == "effect" and p.flow.awaiting_run.awaiting.kind == "effect"
    assert (other.panel_view(), other.panel_labels()) == buttons
    other.snap = None
    other.resume()
    assert any("eleccion de efecto pendiente" in m for m in other.messages) and visible_choices(other) == list(CHOICE[:3])
    click(other, table_copy, Event.CHOICE, {"i": 2})
    click(other, table_copy, Event.CHOICE, {"i": target})
    assert other.pending is None and other.moving
    assert jsonable(persist.game_to_dict(other.game)) == final


def test_an_effect_that_fails_halfway_inside_a_combat_leaves_the_game_as_it_was(brig, monkeypatch):
    session, table, game, _ = brig
    lobster_attacks_with_posthumous_power(session, table, game)
    before = jsonable(session.to_dict())
    key = session.effect_run.awaiting.key

    def boom(run, game_, spec):
        game_.fighters["hellboy"].hp -= 3                 # mutates, then fails: nothing of it may stay
        raise RuleError("fallo simulado")
    monkeypatch.setitem(OPS, "heal", boom)
    click(session, table, Event.CHOICE, {"i": 1})
    assert any("Accion ilegal: fallo simulado" in m for m in session.messages)
    assert jsonable(session.to_dict()) == before
    assert session.pending.flow.awaiting_run.awaiting.key == key and visible_choices(session) == list(CHOICE[:3])
    monkeypatch.setitem(OPS, "heal", _real_heal)
    click(session, table, Event.CHOICE, {"i": 1})
    assert session.pending is None and game.fighters["hellboy"].hp == 18


_real_heal = OPS["heal"]


def test_a_free_effect_that_fails_halfway_is_rolled_back_and_a_crash_is_rolled_back_and_raised(brig, monkeypatch):
    session, table, game, _ = brig
    game.fighters["hellboy"].hp -= 4
    before = jsonable(session.to_dict())
    ops = [{"op": "heal", "target": {"side": "own", "pick": "all"}, "amount": 1},
           {"op": "draw", "player": "owner", "amount": 1}]

    def run():
        return EffectRun(ops, Ctx(owner=1, this_fid="hellboy", card_id=None), label="test")
    monkeypatch.setitem(OPS, "draw", lambda *_: (_ for _ in ()).throw(RuleError("fallo simulado")))
    session.play_effect(run())
    assert any("Accion ilegal: fallo simulado" in m for m in session.messages)
    assert jsonable(session.to_dict()) == before and session.effect_run is None
    monkeypatch.setitem(OPS, "draw", lambda *_: (_ for _ in ()).throw(RuntimeError("crash")))
    with pytest.raises(RuntimeError):
        session.play_effect(run())
    assert jsonable(session.to_dict()) == before and session.effect_run is None


def test_a_parked_trigger_is_saved_shown_and_answered(brig):
    session, table, game, _ = brig
    run = pancakes(game)
    assert run.run(game, {0: ControllerChooser(), 1: PanelChooser()}) is not None
    game.fx.parked.append(run)
    assert session.effect_run is run and visible_choices(session) == list(CHOICE[:3])
    saved = session.to_dict()
    assert len(saved["game"]["fx"]["parked"]) == 1
    other = twin(session, saved)
    assert other.effect_run.awaiting.key == run.awaiting.key and other.game.fx.parked[0] is other.effect_run
    other.snap = None
    click(other, table, Event.CHOICE, {"i": 1})
    click(other, table, Event.CHOICE, {"i": 2})
    assert other.game.fx.parked == [] and other.effect_run is None
    assert any("Efecto resuelto" in m for m in other.messages)


def test_an_old_save_with_a_pending_combat_but_no_flow_loads(brig):
    session, table, game, _ = brig
    from test_golden import GOLDEN
    fixture = json.loads((GOLDEN / "session_batch.json").read_text(encoding="utf-8"))["save"]
    assert fixture["pending"] is not None and "flow" not in fixture["pending"]
    session.load_dict(fixture)
    assert session.pending.flow is None and session.pending.combat is None and session.effect_run is None
    assert jsonable(session.to_dict()) == fixture


def test_cold_iron_blocks_the_draw_and_the_action_gain_with_a_chat_line(brig):
    session, table, game, _ = brig
    modifiers.add_status(game.fx, "cannot_draw", owner=0, until=UNTIL, player=1)
    modifiers.add_status(game.fx, "cannot_gain_actions", owner=0, until=UNTIL, player=1)
    hand = len(game.players[1].hand)
    click(session, table, Event.MANEUVER)
    assert len(game.players[1].hand) == hand and session.moving
    assert any("Cold Iron" in m for m in session.messages) and any("robar" in m for m in session.messages)
    assert any("ganar acciones" in m for m in session.messages)
    actions = game.actions_left
    crown = next(c for c in game.players[1].full_set if c.title == CROWN)
    session.messages = []
    session._apply_human_scheme(crown)
    assert game.actions_left == actions and any("no ganas" in m for m in session.messages)


def test_a_pinned_fighter_keeps_the_engine_space_when_the_table_moves_it(brig):
    session, table, game, _ = brig
    modifiers.add_status(game.fx, "cannot_leave_space", owner=0, until=UNTIL, fid="hellboy")
    table.positions["Hellboy"] = 5
    click(session, table, Event.END_ACTION)
    assert game.fighters["hellboy"].pos == 1
    assert any("no puede dejar su sitio" in m for m in session.messages)
    assert any("deje su casilla" in m for m in session.messages)        # the restriction, told once


def hellboy_attacks_with_confront(session, table, game):
    game.fx.dsl_heroes.discard("hellboy")        # the E1 button is the legacy route; interpreted, the card itself looks (E3)
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Confront Any Demon or God")
    click(session, table, Event.REVEAL)
    assert session.pending is None


def test_confront_grants_the_look_and_the_next_action_revokes_it(brig):
    session, table, game, _ = brig
    assert session.panel_view()[1]["btn_look"] == (False, False)
    hellboy_attacks_with_confront(session, table, game)
    assert session.look_granted and any("te deja mirar la mano del bot" in m for m in session.messages)
    assert session.panel_view()[1]["btn_look"][1] is True
    click(session, table, Event.END_ACTION)                     # closes the attack action: the look is still open
    assert session.look_granted and session.panel_view()[1]["btn_look"][1] is True
    click(session, table, Event.MANEUVER)                       # a new action: the card's window is over
    assert not session.look_granted and session.panel_view()[1]["btn_look"] == (False, False)


def test_taking_the_look_uses_up_the_grant(brig):
    session, table, game, _ = brig
    hellboy_attacks_with_confront(session, table, game)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.LOOK)
    assert session.look is not None and not session.look_granted


def test_a_card_without_look_hand_grants_nothing(brig):
    session, table, game, _ = brig
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Service Pistol")
    click(session, table, Event.REVEAL)
    assert session.pending is None and not session.look_granted
