"""Remove A Painful Memory played by the human against Liz Sherman (live, 30/10, second pass).

The spec: the bot lays its hand face up in a row on free table next to ITS ongoing and combat zones (`bot_row_spot`,
not Mirar mano's `look_spot`), the human pings one card (with an ongoing scheme), the BOT decides to discard it or to
keep it and take 2 (announced in the chat, damage included), and only then the card goes to the discard pile, the rest
returns to the hand and the dial is updated.
"""
from __future__ import annotations

import pytest

from test_e3_hidden_info import LIZ_HAND, human_hand, attack, click, defend_with, rig_for, said, Event
from test_painful_memory_liz import pact_of_freedom


@pytest.fixture
def liz(tmp_path):
    session, table, game, fake, cfg, client = rig_for(tmp_path, "liz-sherman", "baba-yaga", LIZ_HAND)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def open_pick(session, table, game, monkeypatch, defense, hp=None, scheme=True):
    defend_with(session, game, monkeypatch, defense)
    if scheme:
        pact_of_freedom(game)
    if hp is not None:
        game.fighters["liz"].hp = hp
    human_hand(table, game, "Remove A Painful Memory", "Exploit")
    attack(session, table, game, "baba", "liz", "Remove A Painful Memory")
    return click(session, table, Event.REVEAL)


def ping(session, table, game, title):
    card = next(c for c in game.players[0].hand if c.title == title)
    assert card.card_id in session.look["ids"], "the card must be in the row"
    return click(session, table, Event.LOOK_PING, {"guid": f"g{card.card_id}"}), card


@pytest.mark.parametrize("defense", ["Pyrotechnics", "Evade"])
def test_the_bot_discards_a_card_rather_than_take_a_lethal_2(liz, monkeypatch, defense):
    session, table, game, fake, cfg = liz
    open_pick(session, table, game, monkeypatch, defense, hp=3)
    msgs, card = ping(session, table, game, "Feint")
    assert game.winner is None and game.fighters["liz"].alive
    assert card in game.players[0].discard
    assert said(msgs, "El bot descarta Feint")


def liz_dial(session, table):
    return table.dials[session.cfg.dials["liz"]]["value"]


def test_the_bot_keeps_a_card_it_values_and_takes_2_announced_with_the_dial_updated(liz, monkeypatch):
    session, table, game, fake, cfg = liz
    open_pick(session, table, game, monkeypatch, "Pyrotechnics")
    st, hp = game.players[0], game.fighters["liz"].hp
    monkeypatch.setattr(session.ai.effect_ai(), "_discard_or_take", lambda g, req: False)
    msgs, card = ping(session, table, game, "Evade")
    assert card in st.hand and card.card_id in table.bot_hand and card not in st.discard
    assert game.fighters["liz"].hp == hp - 2 and liz_dial(session, table) == hp - 2
    assert said(msgs, f"El bot se queda {card.title} y Liz Sherman recibe 2 de dano")
    assert sorted(table.bot_hand) == sorted(c.card_id for c in st.hand) and table.look_row == []
    assert session.look is None and session.pending is None and not session.dirty


def test_the_bot_discards_a_plain_card_to_save_the_2(liz, monkeypatch):
    session, table, game, fake, cfg = liz
    open_pick(session, table, game, monkeypatch, "Pyrotechnics")
    st, hp = game.players[0], game.fighters["liz"].hp
    monkeypatch.setattr(session.ai.effect_ai(), "_discard_or_take", lambda g, req: True)
    msgs, card = ping(session, table, game, "Feint")
    assert card in st.discard and card.card_id in table.bot_discard and card.card_id not in table.bot_hand
    assert game.fighters["liz"].hp == hp and liz_dial(session, table) == hp
    assert said(msgs, f"El bot descarta {card.title}") and not said(msgs, "recibe")
    assert sorted(table.bot_hand) == sorted(c.card_id for c in st.hand) and table.look_row == []


def test_a_burning_card_the_bot_discards_comes_back_to_its_hand_by_wildfire_without_damage(liz, monkeypatch):
    session, table, game, fake, cfg = liz
    open_pick(session, table, game, monkeypatch, "Evade")
    st, hp = game.players[0], game.fighters["liz"].hp
    fire = next(c for c in st.hand if "burning" in c.tags)
    monkeypatch.setattr(session.ai.effect_ai(), "_discard_or_take", lambda g, req: True)
    msgs, _ = ping(session, table, game, fire.title)
    assert fire in st.hand and fire not in st.discard and fire.card_id in table.bot_hand
    assert game.fighters["liz"].hp == hp
    assert said(msgs, f"El bot descarta {fire.title} (Wildfire la devuelve a su mano)")
    assert sorted(table.bot_hand) == sorted(c.card_id for c in st.hand) and table.look_row == []


def test_the_row_opens_at_bot_row_spot_not_at_the_look_spot(liz, monkeypatch):
    session, table, game, fake, cfg = liz
    open_pick(session, table, game, monkeypatch, "Pyrotechnics")
    x, _, z = session.cfg.bot_row_spot
    n = len(session.look["spots"])
    assert n and all(abs(sx - x) < 1e-6 for sx, _ in session.look["spots"])
    zs = [sz for _, sz in session.look["spots"]]
    assert abs(sum(zs) / n - z) < 1e-6
    assert (x, z) != tuple(session.cfg.look_spot[::2])


def test_no_scheme_only_reveals_the_row_at_the_bot_row_spot_and_returns_it(liz, monkeypatch):
    session, table, game, fake, cfg = liz
    open_pick(session, table, game, monkeypatch, "Pyrotechnics", scheme=False)
    hp = game.fighters["liz"].hp
    assert session.look["mode"] == "reveal" and abs(session.look["spots"][0][0] - session.cfg.bot_row_spot[0]) < 1e-6
    click(session, table, Event.END_ACTION)
    assert session.look is None and game.fighters["liz"].hp == hp and table.look_row == []
    assert sorted(table.bot_hand) == sorted(c.card_id for c in game.players[0].hand)


def test_nothing_else_happens_on_the_bots_side_while_the_pick_is_pending(liz, monkeypatch):
    session, table, game, fake, cfg = liz
    open_pick(session, table, game, monkeypatch, "Pyrotechnics")
    discard, hand = list(table.bot_discard), sorted(table.look_row)
    assert session.pending is not None and session.look["mode"] == "pick" and game.turn == 1
    assert list(table.bot_discard) == discard and sorted(table.look_row) == hand


def test_a_resume_mid_pick_still_announces_the_damage_the_bot_took(liz, monkeypatch):
    import json
    from test_e3_hidden_info import twin_session
    session, table, game, fake, cfg = liz
    open_pick(session, table, game, monkeypatch, "Pyrotechnics")
    twin = twin_session(session, cfg, json.loads(json.dumps(session.to_dict())))
    assert twin.look["hp"] == session.look["hp"]
    monkeypatch.setattr(twin.ai.effect_ai(), "_discard_or_take", lambda g, req: False)
    card = next(c for c in twin.game.players[0].hand if c.title == "Evade")
    msgs = click(twin, table, Event.LOOK_PING, {"guid": f"g{card.card_id}"})
    assert said(msgs, f"El bot se queda Evade y Liz Sherman recibe 2 de dano")
