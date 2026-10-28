"""F09 cableada en play.py: seleccion de la IA, sesion con IsmctsMedusa en todos los caminos y caida a MedusaAI."""
import json
import logging

import pytest

import sparring.search.controller as controller
from sparring import play
from sparring.ai_medusa import Act, MedusaAI
from sparring.search.controller import IsmctsMedusa, make_bot_ai
from sparring.search.ismcts import SearchConfig
from sparring.session import Session
from sparring.state import Game
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401  (brig es una fixture)
from test_panel_restart import prepared, with_cfg
from test_session import human_plays, rig, set_bot_hand, start_human_attack  # noqa: F401

SMALL = SearchConfig(time_budget=5.0, iterations=200, seed=1)   # con 40 la jugada de la raiz era ruido (11 visitas contra 10)


def ismcts() -> IsmctsMedusa:
    return IsmctsMedusa(0, SMALL)


# ---------- seleccion ----------
def test_cli_picks_the_ai_and_beats_the_config_file():
    assert play.parse_args([]).ai is None and play.parse_args([]).ai_time is None
    args = play.parse_args(["--ai", "ismcts", "--ai-time", "0.5"])
    assert args.ai == "ismcts" and args.ai_time == 0.5
    cfg = play.load_config(play.DEFAULT_CONFIG)
    assert make_bot_ai(play.ai_config(cfg, None, None), 0).__class__ is MedusaAI           # por defecto, heuristica
    ai = make_bot_ai(play.ai_config(cfg, "ismcts", 0.5), 0)
    assert isinstance(ai, IsmctsMedusa) and ai.config.time_budget == 0.5
    cfg.raw["ai"] = "ismcts"
    by_config = make_bot_ai(play.ai_config(cfg, None, None), 0)
    assert isinstance(by_config, IsmctsMedusa) and by_config.config.time_budget == controller.DEFAULT_TIME_BUDGET
    assert make_bot_ai(play.ai_config(cfg, "heuristic", None), 0).__class__ is MedusaAI    # la CLI manda
    assert cfg.raw["ai"] == "ismcts", "ai_config no toca la configuracion cargada"


# ---------- caminos de la sesion ----------
def test_bot_turn_with_several_actions_and_a_defense(rig):
    session, table, game = rig
    session.ai = ai = ismcts()
    game.actions_left = 0
    session.handle(Event.END_ACTION)                           # turno del bot con busqueda
    assert ai.fallbacks == 0 and ai.last_report is not None
    assert game.turn == 0 or session.pending is not None or game.winner is not None


def test_defense_on_reveal_with_the_search_ai(rig):
    session, table, game = rig
    session.ai = ai = ismcts()
    start_human_attack(session, table, game)
    session.handle(Event.REVEAL)
    assert ai.fallbacks == 0 and ai.last_report is not None
    assert session.pending is None or session.pending.defended


def test_start_mulligan_and_setup_with_the_search_ai(rig):
    from test_review5_fixes import setup_rig
    session, table, game = rig
    session.ai = ai = ismcts()
    setup_rig(session, table, game, first=0)
    msgs = session.start()
    assert msgs and ai.fallbacks == 0 and session.setup is not None


def test_restart_keeps_the_search_ai_and_the_new_game_knows_nothing(brig, tmp_path):  # noqa: F811
    session, table, game, clock = prepared(brig, tmp_path)
    session.ai = ai = ismcts()
    game.observe_hand(0, game.players[1].full_set[:3])
    with_cfg(session, setup=True)
    click(session, table, Event.RESTART)
    click(session, table, Event.RESTART)
    assert session.game is not game and session.ai is ai
    assert ai.knowledge(session.game).known_in_hand == {1: ()}


def test_a_seen_rival_hand_is_pinned_in_determinization_and_discounted_when_played(rig):
    """Flujo de la sesion: el motor guarda lo visto (`observe_hand`), la IA lo lee de ahi y la busqueda lo respeta."""
    import random
    from sparring.search.adapter import EngineState
    session, table, game = rig
    session.ai = ai = ismcts()
    seen = [c for c in game.players[1].full_set if c.title in ("Excalibur", "Service Pistol")][:2]
    game.players[1].hand[:] = list(seen) + [c for c in game.players[1].full_set if c not in seen][:2]
    game.observe_hand(0, seen)
    know = ai.knowledge(game)
    assert set(know.known_in_hand[1]) == set(seen)
    st = EngineState(game, observer=0, knowledge=know)
    for seed in range(4):
        st.determinize(0, random.Random(seed))
        assert all(c in st.game.players[1].hand for c in seen) and len(st.game.players[1].hand) == 4
    game.discard_card(1, seen[0])
    left = ai.knowledge(game).known_in_hand[1]
    assert seen[0] not in left and seen[1] in left
    ai.plan(game)
    assert ai.fallbacks == 0


def test_resume_a_saved_game_with_the_search_ai(rig, tmp_path):
    session, table, game = rig
    session.ai = ismcts()
    session.state_path = tmp_path / "s.json"
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    saved = json.loads(session.state_path.read_text(encoding="utf-8"))
    other = Session(Game.new(game.board, seed=99, controllers={}), session.client, ismcts(), session.cfg)
    other.load_dict(saved)
    assert other.resume()[0].startswith("Partida reanudada") and other.ai.fallbacks == 0


# ---------- mensajes a TTS ----------
def test_the_search_ai_costs_no_more_messages_than_the_heuristic(brig):  # noqa: F811
    """Mismo presupuesto por boton que `test_message_budget_per_button` (heuristica); el turno del bot lo marca
    lo que la busqueda elija, asi que se mide por accion: una maniobra cuesta 1 y el resto, lo que cuesta atacar."""
    session, table, game, fake = brig
    session.ai = ai = ismcts()
    spent = {}

    def run(label, fn):
        n = fake.lua_messages
        fn()
        spent[label] = fake.lua_messages - n
    run("maniobra", lambda: click(session, table, Event.MANEUVER))
    run("fin de accion", lambda: click(session, table, Event.END_ACTION))
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    run("atacar", lambda: click(session, table, Event.ATTACK, {"target": "medusa"}))
    human_plays(table, game, "Service Pistol")
    run("revelar", lambda: click(session, table, Event.REVEAL))
    session.ai.pick_ability_target = lambda g: None
    acts = []
    real_plan = ai.plan
    ai.plan = lambda g: acts.append(real_plan(g)) or acts[-1]
    run("turno del bot", lambda: click(session, table, Event.END_ACTION))
    assert ai.fallbacks == 0
    assert {k: v for k, v in spent.items() if k != "turno del bot"} == {
        "maniobra": 1, "fin de accion": 1, "atacar": 2, "revelar": 3}, spent
    assert acts and all(a.kind != "maneuver" or c == 1 for a, c in
                        zip(acts, [c for label, c, _ in session.cost_log if label == "accion del bot"]))


# ---------- caida a la heuristica ----------
def test_a_search_failure_falls_back_to_medusa_ai_with_a_warning(rig, monkeypatch, caplog):
    session, table, game = rig
    session.ai = ai = ismcts()

    def boom(self, *a, **k):
        raise RuntimeError("busqueda rota")
    monkeypatch.setattr(controller.ISMCTS, "search", boom)
    game.actions_left = 0
    turn_no = game.turn_no
    with caplog.at_level(logging.WARNING):
        session.handle(Event.END_ACTION)
    assert ai.fallbacks >= 1 and any(r.levelno == logging.WARNING and "ISMCTS" in r.getMessage() for r in caplog.records)
    assert game.turn_no > turn_no + 1 or session.pending is not None, "el turno del bot siguio adelante"
    n = ai.fallbacks
    f = game.fighters
    assert ai.choose_defense(game, f["hellboy"], f["medusa"]) in (None, *game.players[0].hand)
    assert ai.fallbacks == n + 1
