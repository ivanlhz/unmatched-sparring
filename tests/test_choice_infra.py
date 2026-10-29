"""E1: effect-choice buttons, hidden look button, panel-blocked actions and the save/resume of a paused effect.

The human is Hellboy (player 1); the card played is a real one (Pancakes!, `choose_effect` twice, distinct) run by an
`EffectRun` whose human choices pause through the panel. Sessions run against FakeTTS (batch mode)."""
import json

from sparring import persist
from sparring.ai_medusa import MedusaAI
from sparring.effects.choose import ScriptedChooser
from sparring.effects.state import EffectState
from sparring.effects.run import Ctx, EffectRun
from sparring.session import Session
from sparring.state import Game
from sparring.tts import lua, ui
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_golden import GOLDEN, jsonable

CHOICE = ui.CHOICE_BUTTONS


class NoAttack(EffectState):
    """Stands for the C3 rule queries: `may_attack(player)` is read with getattr, so the base class lacks it."""

    def may_attack(self, player):
        return False


class NoDraw(EffectState):
    def can_draw(self, player):
        return False


def pancakes(game):
    card = next(c for c in game.players[1].full_set if c.title == "Pancakes!")
    return EffectRun.for_card("hellboy", "Pancakes!", "scheme", Ctx(owner=1, this_fid="hellboy", card_id=card.card_id))


def hurt(game):
    game.fighters["hellboy"].hp -= 4


def visible_choices(session):
    states = session.panel_view()[1]
    return [i for i in CHOICE if states[i][1]]


def start(session, table):
    session.messages = []
    session.snap = None
    session.play_effect(pancakes(session.game))


def twin_after(bprd, saved_game, answers):
    ref = Game.new(bprd, seed=3, controllers={})
    persist.apply_game(ref, json.loads(json.dumps(saved_game)))
    EffectRun_ = pancakes(ref)
    assert EffectRun_.run(ref, ScriptedChooser(answers)) is None
    return persist.game_to_dict(ref)


def test_choice_buttons_hidden_without_pending(brig):
    session, table, game, _ = brig
    states = session.panel_view()[1]
    assert all(states[i] == (False, False) for i in CHOICE)
    start(session, table)
    assert visible_choices(session) == list(CHOICE[:3])


def test_choice_buttons_exist_in_the_panel_xml_hidden_and_the_script_sends_the_event():
    xml = ui.panel_xml(["medusa"])
    for i in CHOICE:
        assert f'<Button active="false"' in xml and f'id="{i}" onClick="onChoice"' in xml
    script = ui.handler_script(None, ui.element_ids(["medusa"]), "White")
    assert "function onChoice(player, btn, id)" in script and 'event = "choice"' in script
    assert set(CHOICE) <= set(ui.element_ids(["medusa"]))


def test_choice_answer_resumes_effect(brig, bprd):
    session, table, game, fake = brig
    hurt(game)
    before = persist.game_to_dict(game)
    start(session, table)
    labels = session.panel_labels()
    assert labels["btn_choice_1"].startswith("Hellboy recovers 2 health") and session.effect_run is not None
    n = fake.lua_messages
    click(session, table, Event.CHOICE, {"i": 1})
    assert fake.lua_messages - n == 1                       # one message per button
    assert visible_choices(session) == list(CHOICE[:2])     # distinct: the second ask has two options left
    click(session, table, Event.CHOICE, {"i": 2})           # the pool is [1, 2]: button 2 is "draw 2 cards"
    assert session.effect_run is None and visible_choices(session) == []
    assert jsonable(persist.game_to_dict(game)) == jsonable(twin_after(bprd, before, [[0], [2]]))


def test_choice_status_and_chat_are_spanish(brig):
    session, table, game, _ = brig
    start(session, table)
    assert any("Elige un efecto" in m and "Pancakes!" in m for m in session.messages)
    assert "Elige" in session.panel_view()[0]


def test_other_buttons_are_refused_while_a_choice_is_pending(brig):
    session, table, game, _ = brig
    start(session, table)
    click(session, table, Event.MANEUVER)
    assert session.effect_run is not None and any("eleccion" in m for m in session.messages)
    states = session.panel_view()[1]
    assert states["btn_maneuver"][0] is False and states["btn_end"][0] is False


def test_resume_mid_effect(brig, bprd):
    session, table, game, _ = brig
    hurt(game)
    before = persist.game_to_dict(game)
    start(session, table)
    click(session, table, Event.CHOICE, {"i": 1})
    buttons = session.panel_view()
    saved = json.loads(json.dumps(session.to_dict()))

    other = Session(Game.new(bprd, seed=3, controllers={}), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    assert other.effect_run is not None and other.effect_run.awaiting.key == session.effect_run.awaiting.key
    assert other.panel_view() == buttons and other.panel_labels() == session.panel_labels()
    other.snap = None
    other.resume()
    assert any("Elige un efecto" in m for m in other.messages)
    click(other, table, Event.CHOICE, {"i": 2})
    assert other.effect_run is None
    assert jsonable(persist.game_to_dict(other.game)) == jsonable(twin_after(bprd, before, [[0], [2]]))


def test_a_free_effect_is_saved_at_top_level_only_while_it_waits(brig):
    session, table, game, _ = brig
    assert "effect" not in session.to_dict()
    start(session, table)
    assert session.to_dict()["effect"]["label"] == "scheme"


def test_old_save_loads(brig):
    session, table, game, _ = brig
    fixture = json.loads((GOLDEN / "session_batch.json").read_text(encoding="utf-8"))["save"]
    assert "effect" not in fixture and "look_granted" not in fixture
    session.load_dict(fixture)
    assert session.effect_run is None and session.look_granted is False
    assert jsonable(session.to_dict()) == fixture
    assert all(session.panel_view()[1][i] == (False, False) for i in CHOICE)


def test_look_button_hidden_by_default(brig):
    session, table, game, _ = brig
    assert session.panel_view()[1]["btn_look"] == (False, False)
    session.grant_look()
    assert session.panel_view()[1]["btn_look"][1] is True
    session.revoke_look()
    assert session.panel_view()[1]["btn_look"] == (False, False)
    assert 'id="btn_look" onClick="onLook">' in ui.panel_xml(["medusa"])


def test_look_is_refused_without_a_granting_card(brig):
    session, table, game, _ = brig
    click(session, table, Event.LOOK)
    assert session.look is None and any("mirar" in m.lower() for m in session.messages)


def test_look_grant_is_saved_only_when_set(brig):
    session, table, game, _ = brig
    assert "look_granted" not in session.to_dict()
    session.grant_look()
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["look_granted"] is True
    session.revoke_look()
    session.load_dict(saved)
    assert session.look_granted is True


def test_blocked_action_hidden_with_reason(brig, monkeypatch):
    session, table, game, _ = brig
    states = session.panel_view()[1]
    assert states["att_hellboy"] == (True, True)
    monkeypatch.setattr(game, "fx", NoAttack())
    states = session.panel_view()[1]
    assert states["att_hellboy"] == (False, False) and states["btn_maneuver"][0] is True
    click(session, table, Event.END_ACTION)                    # any button: the chat explains the block once
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    assert session.chosen_attacker is None and any("Accion ilegal" in m for m in session.messages)


def test_blocked_reason_is_announced_once(brig, monkeypatch):
    session, table, game, _ = brig
    monkeypatch.setattr(game, "fx", NoAttack())
    click(session, table, Event.CANCEL)
    first = [m for m in session.messages if "impide atacar" in m]
    click(session, table, Event.CANCEL)
    assert len(first) == 1 and not [m for m in session.messages if "impide atacar" in m]


def test_query_missing_means_allowed(brig):
    from sparring.session_choices import fx_query
    session, table, game, _ = brig
    assert not hasattr(game.fx, "no_such_query") and fx_query("no_such_query")(game, 1) is True
    assert session.panel_view()[1]["att_hellboy"] == (True, True)


def test_blocked_draw_skips_the_maneuver_card(brig, monkeypatch):
    session, table, game, _ = brig
    monkeypatch.setattr(game, "fx", NoDraw())
    hand = len(game.players[1].hand)
    click(session, table, Event.MANEUVER)
    assert len(game.players[1].hand) == hand and not any("deal_cards" in ops for ops in table.msglog)
    assert any("robar" in m for m in session.messages) and session.moving


def test_set_panel_labels_and_hidden_flag():
    script = lua.set_panel("Elige", {"btn_choice_1": (True, True), "btn_choice_2": (False, False)},
                           labels={"btn_choice_1": "Curar 2"})
    assert 'panel.UI.setValue("btn_choice_1", "Curar 2")' in script
    assert 'setValue("btn_choice_2"' not in script
    plain = lua.set_panel("Elige", {"btn_choice_1": (True, True)})
    assert "setValue(id" not in plain.split('panel.UI.setValue("status"')[1].split("pairs")[0]
    try:
        lua.set_panel("x", {"btn_choice_1": (True, True)}, labels={"btn_choice_1": 'a"b'})
    except ValueError:
        pass
    else:
        raise AssertionError("an unsafe label must be refused")


def test_many_options_page_and_multi_pick_confirms(brig):
    from sparring.effects.choose import ChoiceRequest
    from sparring.session_choices import ChoiceUI, layout, press
    session, table, game, _ = brig
    ui_ = ChoiceUI()
    req = ChoiceRequest("space", 1, list(range(1, 13)), 1, 1, None, "k")
    slots = layout(game, req, ui_)
    assert [s.action for s in slots] == ["pick"] * 5 + ["page"]
    assert press(game, req, ui_, 6) == ("update", None) and ui_.page == 1
    assert layout(game, req, ui_)[0].value == 6
    assert press(game, req, ui_, 1) == ("answer", [6])
    multi = ChoiceRequest("cards", 1, [10, 11, 12], 0, 2, None, "m")
    ui2 = ChoiceUI()
    assert layout(game, multi, ui2)[-1].label == "Ninguna"
    assert press(game, multi, ui2, 1) == ("update", None) and press(game, multi, ui2, 2) == ("update", None)
    assert layout(game, multi, ui2)[0].label == "1. Carta 10" and press(game, multi, ui2, 4) == ("answer", [10, 11])
    assert press(game, multi, ui2, 9)[0] == "error"
