"""The human's effects that move a fighter (his own or the bot's) are done by hand and validated at Hecho
(`sparring/session_moves.py`, Ivan 30/10: "the spaces are not numbered, 'casilla 0', 'casilla 1' tell me nothing").

Effects of the human that ask a space on the panel before this change (the ops `move`, `place`, `revive` and `summon`
of the DSL with the human as chooser on a piece that is not his, because his own miniatures were always by hand):
  * move up to N      Right Hand Of Doom (Hellboy), Concussion Device (Abe, after the damage), Hellboy's "move any
                      fighter up to 3", Abe's Leap Away style "move a combatant";
  * place anywhere    Pact Of Freedom, Foul Journey (Baba);
  * revive in a zone  Pact Of Mortality (Baba reviving a defeated fighter of either side).
Each type is covered below with FakeTTS sessions; the invalid cases (too far, occupied, another piece moved, not
moved, off the board) change nothing and say why; "No mover" answers an optional move with zero steps."""
from __future__ import annotations

import json

import pytest

from sparring.effects.choose import ChoiceRequest
from sparring.spaces import describe
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import human_attack, human_hand, said, twin_session
from test_e2_human_cards import (ABE_VS_HELLBOY, BABA_VS_LIZ, HELLBOY_VS_ABE, bot_defends_with_nothing, human_scheme,
                                 press, put_adjacent, rig, with_rig)  # noqa: F401
from sparring import session_moves as moves

BABA_VS_ABE = ("abe-sapien", "baba-yaga", "Faster. Stronger.", "Arcane Dampener", "Cold Iron And Holy Water",
               "Leap Away", "Shock And Awe")


def hecho(session, table, i=1):
    return click(session, table, Event.CHOICE, {"i": i})


def drop(table, cfg, fid, space):
    table.positions[cfg.nicknames[fid]] = space


def rhod_asks_for_abe(session, table, game, cfg, monkeypatch):
    """Right Hand Of Doom won by the human: the panel asks where Abe (the bot's piece) goes. Returns the request."""
    put_adjacent(game, table, cfg, "hellboy", "abe")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Right Hand Of Doom", "Excalibur")
    human_attack(session, table, game, "hellboy", "abe", "Right Hand Of Doom")
    put_adjacent(game, table, cfg, "lobster", "hellboy")
    click(session, table, Event.REVEAL)
    press(session, table, "abe")
    return session.effect_run.awaiting


def far_from(game, fid, at_least):
    f = game.fighters[fid]
    taken = {o.pos for o in game.fighters.values() if o.alive}
    return next(s for s in sorted(game.board.spaces) if s not in taken and game.board.distance(f.pos, s) >= at_least)


# ---------------------------------------------------------------- move up to N (Right Hand Of Doom)

@with_rig(*HELLBOY_VS_ABE)
def test_the_chat_says_what_to_move_and_the_panel_has_no_space_buttons(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    req = rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    assert req.kind == "space" and req.extra["fighter"] == "abe"
    assert said(session.messages, f"Right Hand Of Doom: Mueve a {cfg.nicknames['abe']} hasta 1 casilla y pulsa Hecho")
    assert not said(session.messages, "pulsa una de las opciones del panel")      # the option list is gone
    assert session.panel_labels() == {"btn_choice_1": "Hecho", "btn_choice_2": "No mover"}
    assert session.panel_view()[0] == f"Mueve a {cfg.nicknames['abe']} en la mesa y pulsa Hecho"


@with_rig(*HELLBOY_VS_ABE)
def test_chat_line_names_the_fighter_the_limit_and_where_it_is_now(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    req = rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    abe = game.fighters["abe"]
    text = moves.instruction(session, req)
    assert text.startswith(f"Right Hand Of Doom: Mueve a {cfg.nicknames['abe']} hasta 1 casilla y pulsa Hecho")
    assert "No mover" in text and f"Ahora esta en {describe(game, abe.pos, ('abe',), session._name)}" in text
    assert "casilla " + str(abe.pos) not in text


@with_rig(*HELLBOY_VS_ABE)
def test_a_valid_move_is_applied_announced_and_the_bot_does_not_touch_the_piece(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    req = rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    dest = req.options[0]
    drop(table, cfg, "abe", dest)
    msgs = hecho(session, table)
    assert game.fighters["abe"].pos == dest and session.effect_run is None
    assert said(msgs, f"{cfg.nicknames['abe']} queda en ") and not any(m[0] == cfg.nicknames["abe"] for m in table.moves)
    assert not any("casilla " + str(dest) in m for m in msgs)


@with_rig(*HELLBOY_VS_ABE)
def test_too_far_changes_nothing_says_the_maximum_and_waits_for_hecho_again(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    req = rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    abe = game.fighters["abe"]
    before, far = abe.pos, far_from(game, "abe", 3)
    d = game.board.distance(before, far)
    drop(table, cfg, "abe", far)
    msgs = hecho(session, table)
    assert said(msgs, f"{cfg.nicknames['abe']} se ha movido {d} casillas; el maximo es 1")
    assert abe.pos == before and session.effect_run.awaiting.key == req.key
    drop(table, cfg, "abe", req.options[0])
    hecho(session, table)
    assert abe.pos == req.options[0] and session.effect_run is None


@with_rig(*HELLBOY_VS_ABE)
def test_an_occupied_space_is_refused(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    req = rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    abe, hb = game.fighters["abe"], game.fighters["hellboy"]
    before = abe.pos
    drop(table, cfg, "abe", hb.pos)
    msgs = hecho(session, table)
    assert said(msgs, "Esa casilla esta ocupada por ") and abe.pos == before and session.effect_run is not None


@with_rig(*HELLBOY_VS_ABE)
def test_another_piece_that_moved_is_named_and_must_go_back(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    req = rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    hb = game.fighters["hellboy"]
    home = hb.pos
    drop(table, cfg, "abe", req.options[0])
    drop(table, cfg, "hellboy", far_from(game, "hellboy", 4))
    msgs = hecho(session, table)
    assert said(msgs, f"Se ha movido tambien {cfg.nicknames['hellboy']}: devuelvelo a su sitio")
    assert game.fighters["abe"].pos != req.options[0] and hb.pos == home
    drop(table, cfg, "hellboy", home)
    hecho(session, table)
    assert game.fighters["abe"].pos == req.options[0]


@with_rig(*HELLBOY_VS_ABE)
def test_hecho_without_moving_asks_to_move_or_press_no_mover(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    msgs = hecho(session, table)
    assert said(msgs, f"{cfg.nicknames['abe']} no se ha movido: muevela o pulsa No mover") and session.effect_run is not None


@with_rig(*HELLBOY_VS_ABE)
def test_optional_move_with_zero_steps_is_the_no_mover_button(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    abe = game.fighters["abe"]
    before = abe.pos
    msgs = hecho(session, table, 2)
    assert said(msgs, f"{cfg.nicknames['abe']} se queda donde esta") and abe.pos == before and session.effect_run is None
    assert not any(m[0] == cfg.nicknames["abe"] for m in table.moves)


@with_rig(*HELLBOY_VS_ABE)
def test_a_piece_dropped_off_the_board_is_rejected(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    table.piece_dist[cfg.nicknames["abe"]] = 9.0
    msgs = hecho(session, table)
    assert said(msgs, f"{cfg.nicknames['abe']} esta fuera del tablero") and session.effect_run is not None


@with_rig(*HELLBOY_VS_ABE)
def test_a_save_taken_while_waiting_for_hecho_reprompts_on_resume(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    req = rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    twin = twin_session(session, cfg, json.loads(json.dumps(session.to_dict())))
    twin.snap = None
    msgs = twin.resume()
    assert said(msgs, f"Sigue pendiente: Right Hand Of Doom: Mueve a {cfg.nicknames['abe']} hasta 1 casilla")
    assert twin.panel_labels() == {"btn_choice_1": "Hecho", "btn_choice_2": "No mover"}
    drop(table, cfg, "abe", req.options[0])
    hecho(twin, table)
    assert twin.game.fighters["abe"].pos == req.options[0]


@with_rig(*HELLBOY_VS_ABE)
def test_hecho_costs_no_more_messages_than_a_button(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    req = rhod_asks_for_abe(session, table, game, cfg, monkeypatch)
    drop(table, cfg, "abe", req.options[0])
    n = fake.lua_messages
    hecho(session, table)
    assert fake.lua_messages - n <= 3, "the bot writes dials and cards at most; it never moves the miniature"


# ---------------------------------------------------------------- push after damage (Concussion Device)

@with_rig(*ABE_VS_HELLBOY)
def test_concussion_device_pushes_the_bots_piece_by_hand_up_to_three(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "abe", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Concussion Device", "Faster. Stronger.")
    human_attack(session, table, game, "abe", "hellboy", "Concussion Device")
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    hb = game.fighters["hellboy"]
    assert req.kind == "space" and req.extra["steps"] == 3 and session.panel_labels()["btn_choice_1"] == "Hecho"
    before, far = hb.pos, far_from(game, "hellboy", 5)
    drop(table, cfg, "hellboy", far)
    msgs = hecho(session, table)
    assert said(msgs, f"{cfg.nicknames['hellboy']} se ha movido {game.board.distance(before, far)} casillas; el maximo es 3")
    dest = req.options[-1]
    drop(table, cfg, "hellboy", dest)
    msgs = hecho(session, table)
    assert hb.pos == dest and not any(m[0] == "Hellboy" for m in table.moves)


# ---------------------------------------------------------------- place anywhere (Pact Of Freedom)

@with_rig(*BABA_VS_LIZ)
def test_pact_of_freedom_place_is_by_hand_and_a_legal_space_is_free_and_anywhere(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Pact Of Freedom", "Deathless")
    human_scheme(session, table, game, "Pact Of Freedom")
    press(session, table, "liz")
    req = session.effect_run.awaiting
    liz, baba = game.fighters["liz"], game.fighters["baba"]
    assert req.kind == "space" and req.extra["where"] == {"any": True}
    assert session.panel_labels() == {"btn_choice_1": "Hecho"}          # a placement is not optional: no No mover
    assert f"Coloca a {cfg.nicknames['liz']} en cualquier casilla libre" in moves.instruction(session, req)
    drop(table, cfg, "liz", baba.pos)
    assert said(hecho(session, table), "Esa casilla esta ocupada por ")
    dest = req.options[1]
    drop(table, cfg, "liz", dest)
    hecho(session, table)
    assert liz.pos == dest and session.effect_run is None and not any(m[0] == cfg.nicknames["liz"] for m in table.moves)


# ---------------------------------------------------------------- revive in a zone (Pact Of Mortality)

@with_rig(*BABA_VS_ABE)
def test_pact_of_mortality_revives_the_bots_defeated_fighter_where_the_human_puts_it(rig):
    session, table, game, fake, cfg = rig
    agent = game.fighters["agent1"]
    agent.died_at, agent.alive, agent.pos, agent.hp = agent.pos, False, None, 0
    human_hand(table, game, "Pact Of Mortality", "Deathless")
    human_scheme(session, table, game, "Pact Of Mortality")
    req = session.effect_run.awaiting
    baba = game.fighters["baba"]
    assert req.kind == "space" and req.extra["op"] == "revive" and req.extra["where"] == {"zone_of": "baba"}
    text = moves.instruction(session, req)
    assert text.startswith(f"Pact Of Mortality: Pon en el tablero a {cfg.nicknames['agent1']} en la zona de {cfg.nicknames['baba']}")
    assert session.panel_labels() == {"btn_choice_1": "Hecho"}
    outside = next(s for s in sorted(game.board.spaces) if s not in req.options and s not in
                   {f.pos for f in game.fighters.values() if f.alive})
    drop(table, cfg, "agent1", outside)
    msgs = hecho(session, table)
    assert said(msgs, f"{cfg.nicknames['agent1']} tiene que quedar en la zona de {cfg.nicknames['baba']}") and not agent.alive
    dest = req.options[0]
    drop(table, cfg, "agent1", dest)
    hecho(session, table)
    assert agent.alive and agent.pos == dest and agent.hp == agent.max_hp
    assert not any(m[0] == cfg.nicknames["agent1"] for m in table.moves), "revived by hand: the bot does not place it"


# ---------------------------------------------------------------- texts and the space descriptions

def test_the_instruction_mentions_passing_through_fighters_only_when_the_card_allows(rig_free=None):
    from types import SimpleNamespace
    texts = []
    for through in (False, True):
        req = ChoiceRequest("space", 1, [3, 4], 0, 1, None, "k", "move to",
                            {"fighter": "x", "op": "move", "steps": 2, "through": through, "up_to": True})
        fake = SimpleNamespace(game=SimpleNamespace(fighters={"x": SimpleNamespace(pos=None)},
                                                    players=[]), _name=lambda f: "Liz Sherman")
        texts.append(moves.instruction(fake, req))
    assert "puede atravesar" not in texts[0] and "(puede atravesar luchadores rivales)" in texts[1]
    assert texts[1].startswith("Mueve a Liz Sherman hasta 2 casillas (puede atravesar luchadores rivales) y pulsa Hecho")


def test_a_space_is_described_by_zone_colours_and_the_nearest_fighter(bprd):
    from conftest import Scripted
    from sparring.state import Game
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()}, bot_player=0)
    hb = g.fighters["hellboy"]
    near = next(iter(sorted(g.board.adj[hb.pos])))
    assert describe(g, near, ()).startswith("zona") and "pegada a" in describe(g, near, ())
    assert "casilla " + str(near) not in describe(g, near, ())
    assert all(z in describe(g, near, ()) for z in g.board.zones(near))
