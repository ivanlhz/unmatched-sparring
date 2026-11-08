"""She-Hulk on the real table (FakeTTS, batch mode), both seats: Lady Justice mills the top card of the OTHER player's deck (the bot
moves the human's real card after one button; the bot's own deck follows the engine), The Savage She-Hulk's additional action
asked on the panel, her start-of-turn ability (the human's is theirs on the table, the bot's is said in the chat) and Jennifer
Walters, Esq. placing the human's miniature by hand. The engine side of the same cards is in tests/test_she_hulk_effects.py.

Her deck is sheet 176 like Medusa's, the turtles' and the Hell's Kitchen heroes': every id the table reports is resolved against
the owner's deck."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_attack, human_hand, said
from test_doctor_strange_human import StrangeTable, no_defense, on_deck, pause_labels
from test_donatello_session import SPOTS
from test_e2_human_cards import human_scheme, put_adjacent


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=StrangeTable, **SPOTS)
    table.human_card_spot = tuple(cfg.session_config().human_card_spot)
    table.human_deck = []
    table.hand_returns = []
    table.top_discards = []
    put_adjacent(game, table, cfg, game.hero(1).fid, game.hero(0).fid)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(*bot_hand, bot="hellboy", human="she-hulk"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


def dial(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


def bot_attacks(session, table, game, title, target, human_title):
    """The bot attacks `target` with `title`; the human answers with `human_title` face down; the reveal resolves it."""
    card = next(c for c in game.players[0].hand if c.title == title)
    bot_turn(session, table, [Act("attack", fid=game.hero(0).fid, target=target, card=card)])
    cid = card_ids(game, 1, human_title)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    return click(session, table, Event.REVEAL)


# ---------------------------------------------------------------- Lady Justice: the human's, the bot's deck is milled

@with_rig("Service Pistol", "Excalibur")
def test_the_humans_lady_justice_discards_the_bots_top_card_and_adds_twice_its_boost(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Lady Justice", "Cease and Desist")
    top = game.players[0].deck[0]
    boost_before = len(table.bot_discard)
    msgs = bot_attacks(session, table, game, "Service Pistol", "shehulk", "Lady Justice")
    assert top.card_id in table.bot_discard and len(table.bot_discard) > boost_before, msgs        # the real card went to the bot's pile
    assert top in game.players[0].discard
    assert game.fighters["shehulk"].hp == 20 - max(0, 5 - 2 * top.boost), msgs


# ---------------------------------------------------------------- Lady Justice: the bot's, the human's deck is milled

@with_rig("Lady Justice", "Cease and Desist", bot="she-hulk", human="hellboy")
def test_the_bots_lady_justice_asks_for_one_button_and_the_bot_moves_your_top_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    lady = next(c for c in game.players[0].hand if c.title == "Lady Justice")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: lady)
    top, second = on_deck(table, game, "Glimpse Of Hell", "Excalibur")                          # BOOST 3 on top
    human_hand(table, game, "Service Pistol", "Excalibur")
    human_attack(session, table, game, "hellboy", "shehulk", "Service Pistol")
    msgs = click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "amount" and req.extra["top_discard"] and req.extra["rival_deck"] and req.options == [1], msgs
    assert pause_labels(session) == ["1"] and table.top_discards == [], "nothing moves until they press"
    assert said(session.messages, "Pulsa para que el bot descarte la carta de arriba de tu mazo")
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert table.top_discards == [1] and table.human_discard[-1:] == [top] and table.human_deck == [second]
    assert said(msgs, "Lady Justice: descarto la carta de arriba de tu mazo, boca arriba: Glimpse Of Hell"), msgs
    boost = next(c for c in game.players[1].full_set if c.card_id == top).boost
    assert game.fighters["shehulk"].hp == 20 - max(0, 5 - 2 * boost)


@with_rig("Lady Justice", bot="she-hulk", human="hellboy")
def test_the_bots_lady_justice_falls_back_to_your_hands_when_the_table_refuses(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    lady = next(c for c in game.players[0].hand if c.title == "Lady Justice")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: lady)
    on_deck(table, game, "Glimpse Of Hell", "Excalibur")
    table.top_discard_fail = "deck"
    human_hand(table, game, "Service Pistol", "Excalibur")
    human_attack(session, table, game, "hellboy", "shehulk", "Service Pistol")
    click(session, table, Event.REVEAL)
    click(session, table, Event.CHOICE, {"i": 1})
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "cards" and req.extra["pile_mode"] == "blind" and req.extra["rival_deck"]
    assert said(session.messages, "no ha podido mover la carta de arriba de tu mazo, hazlo tu")


# ---------------------------------------------------------------- The Savage She-Hulk: the additional action on the panel

@with_rig("Service Pistol", "Excalibur")
def test_the_humans_savage_she_hulk_asks_for_the_additional_action_and_spends_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "The Savage She-Hulk", "Cease and Desist")
    hp = game.fighters["hellboy"].hp
    assert game.actions_left == 2
    human_attack(session, table, game, "shehulk", "hellboy", "The Savage She-Hulk")
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "optional" and pause_labels(session) == ["Si", "No"]
    assert game.actions_left == 1
    click(session, table, Event.CHOICE, {"i": 1})
    assert game.actions_left == 0 and game.fighters["hellboy"].hp == hp - 9


@with_rig("Service Pistol", "Excalibur")
def test_declining_the_additional_action_leaves_a_three(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "The Savage She-Hulk", "Cease and Desist")
    hp = game.fighters["hellboy"].hp
    human_attack(session, table, game, "shehulk", "hellboy", "The Savage She-Hulk")
    click(session, table, Event.REVEAL)
    click(session, table, Event.CHOICE, {"i": 2})
    assert game.actions_left == 1 and game.fighters["hellboy"].hp == hp - 3


@with_rig("Service Pistol", "Excalibur")
def test_with_no_action_left_the_additional_action_is_not_offered(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "The Savage She-Hulk", "Cease and Desist")
    game.actions_left = 1
    human_attack(session, table, game, "shehulk", "hellboy", "The Savage She-Hulk")
    click(session, table, Event.REVEAL)
    assert session.effect_run is None or session.effect_run.awaiting is None
    assert game.actions_left == 0


# ---------------------------------------------------------------- JUST THROW SOMETHING

@with_rig("Service Pistol", "Excalibur")
def test_your_just_throw_something_waits_for_you_when_a_rival_is_in_your_zone(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Lady Justice", "Cease and Desist")
    msgs = bot_turn(session, table, [])
    assert game.turn == 1 and session.ability_wait is not None
    assert said(msgs, "LANZA ALGO: si hay un luchador rival en la zona de She-Hulk"), msgs
    foe_hp = game.fighters["hellboy"].hp
    for _ in range(2):
        click(session, table, Event.HP, {"fighter": "hellboy", "delta": -1})         # the damage, by hand, on the dial
    msgs = click(session, table, Event.END_ACTION)
    assert session.ability_wait is None and said(msgs, "Habilidad de inicio de turno hecha")
    assert game.fighters["hellboy"].hp == foe_hp - 2


@with_rig("Service Pistol", "Excalibur")
def test_no_rival_in_your_zone_means_no_ability_to_wait_for(rig):
    session, table, game, fake, cfg = rig
    sh = game.fighters["shehulk"]
    out = sorted((s for s in game.board.spaces if not game.board.share_zone(sh.pos, s)), reverse=True)
    for f, space in zip(game.own(0), out):
        f.pos = space
        table.positions[cfg.nicknames[f.fid]] = space
    assert not any(game.board.share_zone(sh.pos, f.pos) for f in game.own(0))
    human_hand(table, game, "Lady Justice", "Cease and Desist")
    bot_turn(session, table, [])
    assert game.turn == 1 and session.ability_wait is None and session.panel_view()[1]["btn_maneuver"] == (True, True)


@with_rig("The Savage She-Hulk", "Green Energy", "Nerve Cluster Strike", bot="she-hulk", human="hellboy")
def test_the_bots_just_throw_something_says_what_it_discarded_and_hurts_a_fighter_in_its_zone(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur", "Service Pistol")
    put_adjacent(game, table, cfg, "hellboy", "shehulk")
    hellboy = game.fighters["hellboy"]
    savage = next(c for c in game.players[0].hand if c.title == "The Savage She-Hulk")             # BOOST 3, the card it needs least
    hp = hellboy.hp
    session.ai.plan = lambda g: Act("maneuver", moves={})
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    assert savage in game.players[0].discard and savage.card_id in table.bot_discard
    assert hellboy.hp == hp - 3 and dial(session, cfg, table, "hellboy") == hp - 3
    assert said(session.messages, "LANZA ALGO: el bot descarta The Savage She-Hulk (POTENCIA 3) y hace 3 de dano")


# ---------------------------------------------------------------- Jennifer Walters, Esq.

@with_rig("Service Pistol", "Excalibur")
def test_jennifer_walters_asks_you_to_place_she_hulk_on_a_starting_space_draws_and_gives_the_action_back(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Jennifer Walters, Esq.", "Cease and Desist")
    actions = game.actions_left
    msgs = human_scheme(session, table, game, "Jennifer Walters, Esq.")
    assert said(msgs, "coloca a shehulk en una casilla de salida"), msgs
    assert game.actions_left == actions and said(msgs, "ganas 1 accion"), msgs
