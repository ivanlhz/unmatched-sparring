"""Rosie the Riveter on the table through the panel (FakeTTS, batch mode), both seats: the human's cards (We Can Do It!, Full Metal, the
schemes' choice between activating and deactivating, Overrun's move by hand, Cavity Magnetron's optional draw), the start-of-turn
activation and the end-of-turn reset of the human's upgrades as the chat says them, and the bot's Rosie playing the same cards against a
human. The bot's side of the same cards is in tests/test_rosie_the_riveter_effects.py.

Her deck is sheet 176 like the other decks: every id the table reports is resolved against the owner's deck. The four upgrade tokens are
not moved by the bot (docs/heroes/rosie-the-riveter.md): the chat says each change and the order of the row."""
from __future__ import annotations

import pytest

from sparring import upgrades
from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, human_hand, said
from test_d3_table_effects import human_attack as human_plays_attack
from test_e2_human_cards import bot_defends_with_nothing, human_scheme, press, put_adjacent  # noqa: F401
from test_human_pile_to_hand import HandTable

SLUG = "rosie-the-riveter"
FILLER = "Full Metal"


def attack(session, table, game, title, attacker="rosie", target="hellboy"):
    human_plays_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def counters(game, player=1):
    return game.fx.counter_value(player, "upgrades"), game.fx.counter_value(player, "upgrade_shift")


@pytest.fixture
def mine(tmp_path):
    """Hellboy is the bot, Rosie the human; it is the human's turn and the start of it has already activated the first upgrade."""
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", SLUG, (), table_cls=HandTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


@pytest.fixture
def bots(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, SLUG, "hellboy", ("We Can Do It!", FILLER), table_cls=HandTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


# ---------------------------------------------------------------- the human's turn: start, end and what the chat says

def test_the_start_of_the_humans_turn_activated_the_first_upgrade(mine):
    session, table, game, fake, cfg = mine
    assert counters(game) == (1, 0) and [u["id"] for u in upgrades.active(game, 1)] == ["merlin_engine"]


def test_the_chat_says_the_row_when_the_game_starts_and_each_change_after_it(mine):
    session, table, game, fake, cfg = mine
    from sparring import session_rosie
    said_before = []
    session.say = lambda text, kind=None: said_before.append(text)
    session_rosie.forget(session)
    session_rosie.track(session, announce=True)
    assert said(said_before, "FREEDOM XK-II MECH SUIT") and said(said_before, "Merlin Engine"), said_before
    said_before.clear()
    upgrades.activate(game, 1)
    session_rosie.track(session)
    assert said(said_before, "activa Cavity Magnetron") and said(said_before, "2 de 4"), said_before
    said_before.clear()
    session_rosie.track(session)
    assert said_before == []                                      # nothing changed: nothing said
    upgrades.deactivate(game, 1)
    session_rosie.track(session)
    assert said(said_before, "desactiva Merlin Engine") and said(said_before, "final de la fila"), said_before
    upgrades.activate(game, 1, 4)
    session_rosie.track(session)
    said_before.clear()
    game.fx.set_counter(1, "upgrades", 0)             # the reset at the end of the turn: four deactivations, the row keeps its order
    session_rosie.track(session)
    assert said(said_before, "desactiva las 4 mejoras"), said_before


def test_after_the_bots_turn_the_humans_next_start_of_turn_activates_the_next_upgrade_and_says_it(mine):
    session, table, game, fake, cfg = mine
    msgs = bot_turn(session, table, [])
    assert counters(game) == (2, 0) and said(msgs, "activa Cavity Magnetron"), msgs


def test_with_all_four_active_at_the_end_of_the_humans_turn_they_are_all_deactivated_and_the_chat_says_so(mine):
    session, table, game, fake, cfg = mine
    upgrades.activate(game, 1, 3)
    assert counters(game) == (4, 0)
    msgs = bot_turn(session, table, [])               # two maneuvers end the turn; the bot plays; the human's next turn starts
    assert said(msgs, "desactiva las 4 mejoras"), msgs
    assert counters(game) == (1, 0)                   # the reset, then the new turn's activation


# ---------------------------------------------------------------- the human plays her cards

def test_we_can_do_it_activates_the_next_upgrade_and_the_chat_says_it(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "rosie", "hellboy")
    human_hand(table, game, "We Can Do It!", FILLER)
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "We Can Do It!")
    assert counters(game) == (2, 0) and game.fighters["hellboy"].hp == hp - 4, msgs
    assert said(msgs, "activa Cavity Magnetron"), msgs


def test_full_metal_is_worth_one_more_for_each_active_upgrade_on_the_table_too(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "rosie", "hellboy")
    upgrades.activate(game, 1, 1)                      # two active: merlin and cavity
    human_hand(table, game, "Full Metal", FILLER)
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "Full Metal")
    assert game.fighters["hellboy"].hp == hp - (1 + 2)


def test_sedgley_fist_gun_adds_its_one_to_the_humans_attack(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "rosie", "hellboy")
    upgrades.activate(game, 1, 2)                      # merlin, cavity, sedgley
    human_hand(table, game, "Technological Superiority", FILLER)
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "Technological Superiority")
    assert game.fighters["hellboy"].hp == hp - (3 + 1)


def test_rapid_development_asks_activate_or_deactivate_and_deals_the_cards(mine):
    session, table, game, fake, cfg = mine
    human_hand(table, game, "Rapid Development", FILLER)
    human_scheme(session, table, game, "Rapid Development")
    req = session.effect_run.awaiting
    assert req.kind == "effect" and req.extra["tag"] == "upgrade"
    press(session, table, 0)
    assert counters(game) == (2, 0) and table.human_deals == [2] and game.actions_left == 2 - 1 + 1


def test_e_award_deactivates_an_upgrade_and_the_row_turns(mine):
    session, table, game, fake, cfg = mine
    upgrades.activate(game, 1)
    human_hand(table, game, '"E" Award', FILLER)
    human_scheme(session, table, game, '"E" Award')
    press(session, table, 1)
    assert counters(game) == (1, 1) and [u["id"] for u in upgrades.active(game, 1)] == ["cavity_magnetron"]


def test_cavity_magnetron_asks_the_human_whether_to_draw_after_her_attack(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "rosie", "hellboy")
    upgrades.activate(game, 1)                          # merlin, cavity
    human_hand(table, game, FILLER, FILLER)
    attack(session, table, game, FILLER)
    req = session.effect_run.awaiting
    assert req.kind == "optional"
    press(session, table, True)
    assert table.human_deals == [1]


def test_overrun_by_hand_asks_which_rivals_she_passed_and_each_named_one_takes_one_damage(mine, monkeypatch):
    """The engine cannot see the path the human walks her miniature along: the panel asks which opposing fighters she went through."""
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "rosie", "hellboy")
    human_hand(table, game, "Overrun", FILLER)
    attack(session, table, game, "Overrun")
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and req.min == 0 and req.max == 2 and req.extra["op"] == "damage", req
    hp = {f: game.fighters[f].hp for f in ("hellboy", "lobster")}
    press(session, table, "lobster")
    click(session, table, Event.CHOICE, {"i": 3})                                      # the confirm slot
    assert session.effect_run is None
    assert game.fighters["lobster"].hp == hp["lobster"] - 1 and game.fighters["hellboy"].hp == hp["hellboy"]


def test_overrun_by_hand_passing_nobody_deals_nothing(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "rosie", "hellboy")
    human_hand(table, game, "Overrun", FILLER)
    attack(session, table, game, "Overrun")
    hp = {f: game.fighters[f].hp for f in ("hellboy", "lobster")}
    click(session, table, Event.CHOICE, {"i": 3})
    assert session.effect_run is None and (game.fighters["lobster"].hp, game.fighters["hellboy"].hp) == (hp["lobster"], hp["hellboy"])


def test_arc_welding_by_wendy_asks_which_option_and_the_damage_option_hits_each_adjacent_rival(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "wendy", "hellboy")
    put_adjacent(game, table, cfg, "lobster", "wendy")
    human_hand(table, game, "Arc Welding", FILLER)
    hp = game.fighters["lobster"].hp
    attack(session, table, game, "Arc Welding", attacker="wendy")
    req = session.effect_run.awaiting
    assert req.kind == "effect" and req.extra["tag"] == "upgrade" and len(req.options) == 2
    press(session, table, 1)
    assert session.effect_run is None and game.fighters["lobster"].hp == hp - 1 and counters(game) == (1, 0)


def test_arc_welding_by_wendy_can_activate_an_upgrade_instead(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "wendy", "hellboy")
    human_hand(table, game, "Arc Welding", FILLER)
    attack(session, table, game, "Arc Welding", attacker="wendy")
    press(session, table, 0)
    assert counters(game) == (2, 0)


def test_whizbang_lets_the_humans_rosie_attack_from_across_a_zone(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    a, b = next((a, b) for a in sorted(game.board.spaces) for b in sorted(game.board.spaces)
                if a != b and game.board.share_zone(a, b) and b not in game.board.adj[a])
    game.fighters["rosie"].pos, game.fighters["hellboy"].pos = a, b
    for f in game.fighters.values():
        if f.alive and f.fid not in ("rosie", "hellboy"):
            f.pos = max(game.board.spaces)
    assert not game.can_attack(game.fighters["rosie"], game.fighters["hellboy"])
    upgrades.activate(game, 1, 3)
    assert game.fighters["rosie"].ranged and game.can_attack(game.fighters["rosie"], game.fighters["hellboy"])


# ---------------------------------------------------------------- the bot plays Rosie against the human

def run_bot_attack(session, table, game, title):
    card = next(c for c in game.players[0].hand if c.title == title)
    first = bot_turn(session, table, [Act("attack", fid="rosie", target="hellboy", card=card)])
    return [*first, *click(session, table, Event.REVEAL)]


def test_the_bots_we_can_do_it_activates_an_upgrade_and_the_chat_tells_the_human(bots):
    session, table, game, fake, cfg = bots
    put_adjacent(game, table, cfg, "rosie", "hellboy")
    human_hand(table, game, "Excalibur")
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    before = counters(game, 0)
    msgs = run_bot_attack(session, table, game, "We Can Do It!")
    assert counters(game, 0)[0] > before[0], msgs
    assert said(msgs, "FREEDOM XK-II MECH SUIT") and said(msgs, "activa"), msgs


def test_the_bots_row_is_said_when_its_turn_starts(bots):
    session, table, game, fake, cfg = bots
    human_hand(table, game, "Excalibur")
    msgs = bot_turn(session, table, [])
    assert counters(game, 0)[0] >= 1 and said(msgs, "FREEDOM XK-II MECH SUIT"), msgs
