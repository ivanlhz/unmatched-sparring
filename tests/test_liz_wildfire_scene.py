"""Bot-Liz's WILDFIRE seen on the table, step by step (Ivan, 30/10): the bottom card goes face up onto the bot's
discard and stays there while TTS waits (inside the same script), then the card goes back to the hand and does
1 damage, or Liz moves. Session against FakeTTS plus the composite's Lua on lupa; never the real TTS."""
import json

import pytest

from conftest import place
from sparring.session import Session
from sparring.tts import lua
from test_multihero_bridge import build, config_for  # noqa: F401  (config_for: same overrides as the bridge tests)
from test_session import Table  # noqa: F401

lupa = pytest.importorskip("lupa")
from lupa import lua54  # noqa: E402

GOLD, ORANGE, LIGHT_BLUE = (1.0, 0.82, 0.15), (1.0, 0.6, 0.2), (0.45, 0.75, 1.0)


def liz_session(tmp_path, monkeypatch, burning: bool, hold: float = 3.0, together: bool = True):
    """Liz (bot) with her deck's bottom card chosen: a burning one or not; Hellboy shares her zone when `together`."""
    session, table, game, fake, cfg, client = build(tmp_path, "liz-sherman", "hellboy")
    session.cfg.wildfire_hold = hold
    st = game.players[0]
    pick = next(c for c in st.deck if ("burning" in c.tags) == burning)
    st.deck.remove(pick)
    st.deck.append(pick)                          # the bottom card is the last one
    table.bot_deck = [c.card_id for c in st.deck]
    liz, hell = game.hero(0), game.hero(1)
    spaces = sorted(game.board.spaces)
    place(game, liz=3, hellboy=4 if together else spaces[-1])
    table.positions = {cfg.nicknames[f]: g.pos for f, g in game.fighters.items()}
    monkeypatch.setattr(session.ai, "plan", lambda g: __import__("sparring.ai_medusa", fromlist=["Act"]).Act(
        "maneuver", moves={"liz": game.hero(0).pos}))
    game.actions_left = 0
    game.turn = 0
    return session, table, game, fake, cfg, pick, client


def start_bot_turn(session, game):
    session.start_bot_turn()


def said(table):
    return list(zip(table.broadcasts, table.broadcast_colors))


def test_a_burning_card_is_shown_then_returns_to_the_hand_and_hurts_the_one_in_her_zone(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=True)
    start_bot_turn(session, game)
    heads = [h for ops in table.msglog for h in ops]
    assert heads.index("discard_cards") < heads.index("hold") < heads.index("return_card_to_hand")
    assert table.holds == [3.0]
    first = next(ops for ops in table.msglog if "hold" in ops)
    assert first[0] == "discard_cards" and first[-1] == "hold" and set(first[1:-1]) == {"broadcast"},         "step 1, its announcement and the wait travel in one message"
    assert card.card_id in table.bot_hand and card.card_id not in table.bot_discard
    lines = [t for t, _ in said(table)]
    wf = [i for i, t in enumerate(lines) if t.startswith("Wildfire:")]
    assert lines[wf[0]] == f"Wildfire: {cfg.nicknames['liz']} descarta la carta del fondo: {card.title} (fuego)" or \
        lines[wf[0]].startswith("Wildfire: ")
    assert lines.index("Es de fuego: vuelve a la mano de " + cfg.nicknames["liz"]) > wf[0]
    hit = f"{cfg.nicknames['liz']} hace 1 de dano a {cfg.nicknames['hellboy']}"
    assert lines.index(hit) > lines.index("Es de fuego: vuelve a la mano de " + cfg.nicknames["liz"])
    colors = dict(said(table))
    assert colors[hit] == ORANGE and colors[lines[wf[0]]] == GOLD
    hell_dial = session.cfg.dials["hellboy"]
    assert table.dials[hell_dial]["value"] == game.hero(1).hp == 17
    client.close()


def test_a_card_that_is_not_burning_stays_on_the_discard_and_liz_moves(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=False, together=False)
    start = game.hero(0).pos
    start_bot_turn(session, game)
    assert table.holds == [3.0] and "return_card_to_hand" not in [h for ops in table.msglog for h in ops]
    assert card.card_id in table.bot_discard and card.card_id not in table.bot_hand
    moved = game.hero(0).pos
    lines = dict(said(table))
    steps = game.board.distance(start, moved)
    expected = (f"No es de fuego: {cfg.nicknames['liz']} se mueve {steps} casilla{'s' if steps != 1 else ''}"
                if steps else f"No es de fuego: {cfg.nicknames['liz']} se queda donde esta")
    assert lines[expected] == LIGHT_BLUE
    assert table.positions[cfg.nicknames["liz"]] == moved
    client.close()


def test_nobody_in_her_zone_means_no_damage_line(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=True, together=False)
    start_bot_turn(session, game)
    assert not [t for t, _ in said(table) if " de dano a " in t]
    assert "Es de fuego: vuelve a la mano de " + cfg.nicknames["liz"] in [t for t, _ in said(table)]
    client.close()


def test_the_scene_lines_are_not_announced_twice(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=True)
    start_bot_turn(session, game)
    lines = [t for t, _ in said(table)]
    assert len([t for t in lines if t.startswith("Wildfire:")]) == 1
    assert len([t for t in lines if t.startswith("Es de fuego")]) == 1
    client.close()


def test_without_a_hold_the_old_behaviour_stays(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=True, hold=0.0)
    start_bot_turn(session, game)
    assert not getattr(table, "holds", []) and "hold" not in [h for ops in table.msglog for h in ops]
    assert not [t for t, _ in said(table) if t.startswith("Wildfire:")]
    client.close()


def test_medusa_never_gets_a_scene(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = build(tmp_path, "medusa", "hellboy")
    session.cfg.wildfire_hold = 3.0
    assert session._wildfire_probe() is None
    client.close()


def test_the_client_timeout_covers_the_hold(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=True)
    calls = []
    real = client.call_lua
    client.call_lua = lambda script, *a, **k: (calls.append((script.split("\n", 1)[0], k.get("timeout"))),
                                               real(script, *a, **k))[1]
    start_bot_turn(session, game)
    composites = [t for head, t in calls if head == "-- sparring:composite"]
    held = [t for t in composites if t is not None]
    assert len(held) == 1 and held[0] >= client.timeout + 3.0, "the default wait would give up before the hold ends"
    assert len(composites) > 1 and composites.count(None) == len(composites) - 1, "only the held message is stretched"
    client.close()


# ---------- the Lua of the hold (lupa, on the minimal table of lua_stub) ----------
@pytest.fixture
def rt():
    from test_effects_bridge import STUB, conv
    runtime = lua54.LuaRuntime()
    runtime.execute(STUB)
    sent = []
    runtime.globals().JSON = runtime.table_from({"encode": lambda v: sent.append(json.dumps(conv(v))) or ""})
    return runtime, sent


def test_the_composite_holds_its_reply_until_the_wait_is_over(rt):
    rt, sent = rt
    script = lua.composite([lua.broadcast("Wildfire"), lua.hold(3)])
    rt.execute("DEFER = true")
    rt.execute(script)
    assert sent == [] and rt.eval("#PENDING") == 1 and rt.eval("#TIMERS") == 1, "the table is not read mid-pause"
    assert rt.eval("PENDING[1].cond()") is False
    rt.execute("TIMERS[1]()")
    assert rt.eval("PENDING[1].cond()") is True
    rt.execute("PENDING[1].f()")
    assert json.loads(sent[0])["ops"][1] == {"held": 3}


def test_the_hold_extends_the_condition_timeout_and_a_plain_composite_is_unchanged():
    script = lua.composite([lua.broadcast("hi"), lua.hold(2.5)])
    assert "ready, 2.5 + holdFor," in script
    plain = lua.composite([lua.broadcast("hi")])
    assert "holdFor" not in plain and "ready, 2.5," in plain


@pytest.mark.parametrize("bad", [0, -1, 11, True, "3"])
def test_a_hold_outside_its_bounds_is_refused(bad):
    with pytest.raises(ValueError):
        lua.hold(bad)
