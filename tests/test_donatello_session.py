"""Donatello at the live table (FakeTTS, batch mode): inventions tucked, cards removed from the game, INVENTIVE, both sides.

The bot side moves its own cards (a `discard_cards` write to `bot_tuck_spot` / `bot_removed_spot`); the human side is
told what to move and the table sync never takes a tucked or removed card back into their discard pile."""
from __future__ import annotations

import json

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_choice_infra import visible_choices
from test_d3_table_effects import (FxTable, build, bot_turn, card_ids, human_attack, human_hand, said, set_hand,
                                   to_bot_discard, twin_session)
from test_e2_human_cards import by_hand, labels, press, put_adjacent

TUCK, REMOVED = [10.0, 1.7, -23.0], [14.0, 1.7, -23.0]
SPOTS = {"bot_tuck_spot": TUCK, "bot_removed_spot": REMOVED}


class AsideTable(FxTable):
    """The fake table where a `discard_cards` write aimed at the tuck / removed spots sets the card aside instead."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.tucked: list[int] = []
        self.removed: list[int] = []

    def do_discard_cards(self, s):
        import re
        wanted = {int(i): tuple(float(v) for v in xyz.split(",")) for i, xyz in re.findall(r"\[(\d+)\]=\{([^}]*)\}", s)}
        aside = {i: xyz for i, xyz in wanted.items() if abs(xyz[2] - TUCK[2]) < 0.01 and xyz[0] >= TUCK[0]}
        if not aside:
            return super().do_discard_cards(s)
        moved = []
        for i, xyz in aside.items():
            for zone in (self.bot_hand, self.bot_play, self.bot_ongoing, self.bot_discard):
                if i in zone:
                    zone.remove(i)
            (self.removed if xyz[0] >= REMOVED[0] else self.tucked).append(i)
            moved.append(i)
        return {"moved": moved}


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand, over = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=AsideTable, **{**SPOTS, **over})
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(bot, human, *hand, **over):
    return pytest.mark.parametrize("rig", [(bot, human, hand, over)], indirect=True)


def bot_defends_with(session, game, title, monkeypatch):
    card = next(c for c in game.players[0].hand if c.title == title)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: card)
    return card


DON_VS_HELLBOY = ("donatello", "hellboy", "Self defense grid", "Heroes in a half shell", "Quick strike", "Smoke bomb",
                  "Electro grenade")


# ---------------------------------------------------------------- the bot is Donatello

@with_rig(*DON_VS_HELLBOY)
def test_the_bots_defense_invention_is_tucked_in_its_zone_and_its_removed_cards_are_set_aside(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "metalhead", "hellboy")
    to_bot_discard(session, table, game, "Thinking ahead", "Quick strike")      # a Quick strike is versatile: removable
    sdg = bot_defends_with(session, game, "Self defense grid", monkeypatch)
    human_hand(table, game, "Service Pistol", "Excalibur")
    human_attack(session, table, game, "hellboy", "donatello", "Service Pistol")
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)
    st = game.players[0]
    assert sdg in st.tucked and sdg not in st.discard and sdg.card_id not in table.bot_discard
    assert [c.title for c in st.removed] == ["Quick strike"]
    assert table.tucked == [sdg.card_id] and table.removed == [c.card_id for c in st.removed]
    assert sorted(table.bot_discard) == sorted(c.card_id for c in st.discard)
    assert said(msgs, "El bot mete Self defense grid bajo su heroe") and said(msgs, "El bot saca Quick strike de la partida")
    assert fake.lua_messages - n <= 4
    assert game.defense_bonus_parts(0) == [(1, "Self defense grid")]
    click(session, table, Event.END_ACTION)
    assert not said(session.messages, "no coincide") and sdg.card_id not in table.bot_hand


@with_rig(*DON_VS_HELLBOY)
def test_the_bots_smoke_bomb_scheme_is_tucked_gains_the_actions_and_the_saved_game_keeps_it(rig):
    session, table, game, fake, cfg = rig
    to_bot_discard(session, table, game, "Party wagon!", "Party wagon!")
    sb = next(c for c in game.players[0].hand if c.title == "Smoke bomb")
    human_hand(table, game, "Service Pistol", "Excalibur")
    bot_turn(session, table, [Act("scheme", card=sb)])
    st = game.players[0]
    assert sb in st.tucked and len(st.removed) == 2
    assert table.tucked == [sb.card_id] and sorted(table.removed) == sorted(c.card_id for c in st.removed)
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    assert [c.card_id for c in twin.game.players[0].tucked] == [sb.card_id]
    assert len(twin.game.players[0].removed) == 2
    twin.read_bot_hand()                                                    # the table never sends them back as hand or deck
    assert sb not in twin.game.players[0].hand + twin.game.players[0].deck
    assert not {c.card_id for c in twin.game.players[0].removed} & {c.card_id for c in twin.game.players[0].deck}


@with_rig(*DON_VS_HELLBOY, bot_tuck_spot=None, bot_removed_spot=None)
def test_without_spots_the_bot_only_tells_you_what_to_move(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    sb = next(c for c in game.players[0].hand if c.title == "Smoke bomb")
    human_hand(table, game, "Service Pistol", "Excalibur")
    bot_turn(session, table, [Act("scheme", card=sb)])
    assert sb in game.players[0].tucked and table.tucked == []
    assert said(session.messages, "El bot mete Smoke bomb bajo la carta de su heroe")


@with_rig(*DON_VS_HELLBOY)
def test_the_bots_maneuver_uses_inventive_and_puts_a_card_at_the_bottom_of_its_deck(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Service Pistol", "Excalibur")
    hand0 = len(game.players[0].hand)
    bot_turn(session, table, [Act("maneuver", moves={})])
    assert any(kind == "bottom" and len(ids) == 1 for kind, ids in table.hand_moves)


# ---------------------------------------------------------------- the human is Donatello

HELLBOY_VS_DON = ("hellboy", "donatello", "Service Pistol", "Excalibur", "Right Hand Of Doom")


@with_rig(*HELLBOY_VS_DON)
def test_the_humans_inventive_maneuver_asks_on_the_panel_and_the_card_to_the_bottom_is_theirs(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Quick strike", "Thinking ahead", "Bo staff")
    msgs = click(session, table, Event.MANEUVER)
    assert session._paused() is not None and labels(session) == ["Si", "No"]
    assert "INVENTIVE" in session._status_text() or any("INVENTIVE" in m for m in session.messages + msgs)
    n = len(game.players[1].hand)
    msgs = press(session, table, True)
    assert session._paused() is None and len(game.players[1].hand) == n + 1
    assert said(msgs, "pon 1 carta de arriba de tu mazo en el fondo") or said(msgs, "en el fondo de tu mazo"), msgs


@with_rig(*HELLBOY_VS_DON)
def test_declining_inventive_is_a_plain_maneuver(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Quick strike", "Thinking ahead", "Bo staff")
    click(session, table, Event.MANEUVER)
    n = len(game.players[1].hand)
    press(session, table, False)
    assert session._paused() is None and len(game.players[1].hand) == n


@with_rig(*HELLBOY_VS_DON)
def test_the_humans_electro_grenade_removes_cards_you_pick_and_is_tucked_not_discarded(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "donatello", "hellboy")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: None)
    old = card_ids(game, 1, "Thinking ahead", "Quick strike")
    table.human_discard = list(old)
    st = game.players[1]
    for i in old:
        c = next(c for c in st.full_set if c.card_id == i)
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)
    human_hand(table, game, "Electro grenade", "Bo staff")
    human_attack(session, table, game, "donatello", "hellboy", "Electro grenade")
    msgs = click(session, table, Event.REVEAL)
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "cards"
    req = session.effect_run.awaiting
    assert req.min == 0 and req.max == 2 and set(req.options) == set(old)
    for k in range(1, len(old) + 1):
        click(session, table, Event.CHOICE, {"i": k})
    msgs = click(session, table, Event.CHOICE, {"i": next(k for k, text in enumerate(labels(session), 1) if text.startswith("Confirmar"))})
    assert session._paused() is None
    grenade = next(c for c in st.full_set if c.title == "Electro grenade")
    assert grenade in st.tucked and {c.card_id for c in st.removed} == set(old) and not st.discard
    assert said(msgs, "Mete Electro grenade bajo la carta de tu heroe") and said(msgs, "Saca Thinking ahead")
    table.human_discard = [grenade.card_id]                 # you have not moved them yet: the sync does not take them back
    click(session, table, Event.END_ACTION)
    assert grenade not in st.discard and not st.discard


@with_rig(*HELLBOY_VS_DON)
def test_the_humans_smoke_bomb_scheme_asks_the_schemes_to_remove_is_tucked_and_survives_a_resume(rig):
    session, table, game, fake, cfg = rig
    st = game.players[1]
    old = card_ids(game, 1, "Party wagon!", "Party wagon!")
    table.human_discard = list(old)
    for i in old:
        c = next(c for c in st.full_set if c.card_id == i)
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)
    human_hand(table, game, "Smoke bomb", "Bo staff")
    from test_e2_human_cards import human_scheme
    left = game.actions_left
    human_scheme(session, table, game, "Smoke bomb")
    req = session.effect_run.awaiting
    assert req.kind == "cards" and set(req.options) == set(old)
    for k in (1, 2):
        click(session, table, Event.CHOICE, {"i": k})
    msgs = click(session, table, Event.CHOICE, {"i": next(k for k, text in enumerate(labels(session), 1) if text.startswith("Confirmar"))})
    bomb = next(c for c in st.full_set if c.title == "Smoke bomb")
    assert bomb in st.tucked and {c.card_id for c in st.removed} == set(old) and game.actions_left == left - 1 + 2
    assert said(msgs, "Mete Smoke bomb bajo la carta de tu heroe")
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    assert [c.card_id for c in twin.game.players[1].tucked] == [bomb.card_id]
    table.human_discard = [bomb.card_id, *old]              # still on their pile until they move them: never taken back
    twin.sync_human()
    assert not twin.game.players[1].discard
