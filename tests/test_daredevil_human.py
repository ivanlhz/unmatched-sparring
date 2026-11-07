"""Daredevil played BY THE HUMAN through the panel (FakeTTS, batch mode): the special ability's BLIND BOOST declaration (only with
2 or fewer cards in hand, never greyed buttons otherwise), the order choice, Take A Knee's one button and the card the bot moves,
Devil of Hell's Kitchen's shuffle back, Through Adversity by hand, Breather, and the saved choices after a restore. The bot's side
of the same cards is in tests/test_daredevil_effects.py.

His deck is sheet 176 like Medusa's and the turtles': every id the table reports is resolved against the human's deck."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build, human_attack, human_hand, said
from test_donatello_session import SPOTS
from test_doctor_strange_human import StrangeTable, attack, done, no_defense, on_deck, pause_labels, sid
from test_e2_human_cards import human_scheme, labels, press, put_adjacent

DEVIL = "Devil of Hell's Kitchen"


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


def with_rig(*bot_hand, bot="hellboy", human="daredevil"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


def hit(session, table, game, title, hand):
    """The human holds `hand` (the card they play included) and attacks Hellboy with `title`; the bot defends with nothing."""
    human_hand(table, game, *hand)
    return attack(session, table, game, title, attacker="daredevil", target="hellboy")


# ---------------------------------------------------------------- the special ability

@with_rig()
def test_the_ability_offers_zero_or_one_blind_boost_when_two_or_fewer_cards_stay_in_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    on_deck(table, game, "Breather")
    msgs = hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather"])
    req = session.effect_run.awaiting
    assert req.kind == "amount" and req.options == [0, 1] and req.extra["blind_count"] and req.extra["ability"]
    assert pause_labels(session) == ["0", "1"] and said(msgs, "IMPULSO A CIEGAS")
    assert table.top_discards == [], "nothing moves until they declare"


@with_rig()
def test_declaring_one_moves_the_top_card_to_the_pile_and_adds_its_boost_naming_the_ability(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, second = on_deck(table, game, DEVIL, "Feint")                               # boost 3
    hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather"])
    hp = game.fighters["hellboy"].hp
    msgs = done(session, table, 2)                                                    # "1"
    assert table.top_discards == [1] and table.human_discard == [top] and table.human_deck == [second]
    assert said(msgs, "la habilidad especial de Daredevil: descarto las 1 de arriba de tu mazo, boca arriba: Devil of Hell's Kitchen. +3 al valor")
    assert game.fighters["hellboy"].hp == hp - 6 or hp - game.fighters["hellboy"].hp >= 6      # 3 + 3 against no defense
    assert len(game.players[1].hand) == table.human_count


@with_rig()
def test_declaring_zero_takes_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    on_deck(table, game, DEVIL)
    hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather"])
    msgs = done(session, table, 1)                                                    # "0"
    assert table.top_discards == [] and said(msgs, "la habilidad especial de Daredevil: no potencias")


@with_rig()
def test_with_three_cards_left_in_hand_the_ability_asks_nothing_and_no_button_is_shown(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    on_deck(table, game, DEVIL)
    hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather", "Son Of A Boxer"])
    assert session.effect_run is None or session.effect_run.awaiting is None
    assert table.top_discards == [] and visible_none(session)


def visible_none(session):
    from test_choice_infra import visible_choices
    return visible_choices(session) == []


@with_rig()
def test_a_card_with_its_own_during_effect_asks_the_order_first_then_each_declaration(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    first, second = on_deck(table, game, "Breather", "Feint")
    hit(session, table, game, "Man Without Fear", ["Man Without Fear", "Feint", "Breather"])
    req = session.effect_run.awaiting
    assert req.kind == "effect" and req.extra["during_order"] and len(req.options) == 2
    assert labels(session) == ["ability first, then the card", "card first, then the ability"]
    press(session, table, 1)                                                          # the card first
    req = session.effect_run.awaiting
    assert req.kind == "amount" and req.extra["blind_count"] and not req.extra.get("ability")
    done(session, table, 2)                                                           # 1 from the card
    req = session.effect_run.awaiting
    assert req.extra["ability"] is True
    done(session, table, 2)                                                           # 1 from the ability
    assert table.human_discard == [first, second] and table.top_discards == [1, 1]


# ---------------------------------------------------------------- Take A Knee

@with_rig()
def test_take_a_knee_shows_one_button_then_the_bot_discards_the_top_card_and_daredevil_recovers_its_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, _ = on_deck(table, game, DEVIL, "Feint")                                    # boost 3
    game.fighters["daredevil"].hp = 10
    hit(session, table, game, "Take A Knee", ["Take A Knee", "Feint", "Breather", "Son Of A Boxer"])
    req = session.effect_run.awaiting
    assert req.kind == "amount" and req.options == [1] and req.extra["top_discard"] and pause_labels(session) == ["1"]
    assert table.top_discards == [] and game.fighters["daredevil"].hp == 10
    msgs = done(session, table, 1)
    assert table.top_discards == [1] and table.human_discard == [top]
    assert said(msgs, "Take A Knee: descarto la carta de arriba de tu mazo, boca arriba: Devil of Hell's Kitchen")
    assert game.fighters["daredevil"].hp == 13 and table.dials[cfg.session_config().dials["daredevil"]]["value"] == 13
    assert session.effect_run is None and len(game.players[1].hand) == table.human_count


@with_rig()
def test_take_a_knee_with_an_empty_deck_asks_and_moves_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    from sparring.effects.ops_core import PLUGINS
    real = PLUGINS["daredevil:take_a_knee"]

    def empty_first(run, g, spec):                         # the engine's copy of their deck is rebuilt as the table is read
        g.players[1].deck.clear()
        return real(run, g, spec)
    monkeypatch.setitem(PLUGINS, "daredevil:take_a_knee", empty_first)
    hit(session, table, game, "Take A Knee", ["Take A Knee", "Feint", "Breather", "Son Of A Boxer"])
    assert (session.effect_run is None or session.effect_run.awaiting is None) and table.top_discards == []


@with_rig()
def test_take_a_knee_falls_back_to_laying_the_card_by_hand_when_the_table_refuses(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, _ = on_deck(table, game, DEVIL, "Feint")
    table.top_discard_fail = "deck"
    game.fighters["daredevil"].hp = 10
    hit(session, table, game, "Take A Knee", ["Take A Knee", "Feint", "Breather", "Son Of A Boxer"])
    msgs = done(session, table, 1)
    req = session.effect_run.awaiting
    assert said(msgs, "No he podido mover las cartas de arriba de tu mazo") and req.kind == "cards" and req.extra["pile_mode"] == "blind"
    table.human_discard += [top]
    done(session, table)
    assert game.fighters["daredevil"].hp == 13


@with_rig()
def test_the_one_button_waiting_at_the_panel_survives_a_save_and_a_restore(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, _ = on_deck(table, game, DEVIL, "Feint")
    game.fighters["daredevil"].hp = 10
    hit(session, table, game, "Take A Knee", ["Take A Knee", "Feint", "Breather", "Son Of A Boxer"])
    session._restore(session.to_dict())
    game = session.game
    assert session.effect_run.awaiting.extra["top_discard"] and pause_labels(session) == ["1"] and table.top_discards == []
    done(session, table, 1)
    assert table.human_discard == [top] and game.fighters["daredevil"].hp == 13


# ---------------------------------------------------------------- Devil of Hell's Kitchen

@with_rig()
def test_the_devil_puts_itself_and_the_last_three_cards_of_the_pile_back_in_the_deck(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    old = [sid(game, "Feint", 2), sid(game, "Breather", 2), sid(game, "Grappling Hook", 0), sid(game, "Take A Knee", 0)]       # none is in their hand
    table.human_discard += old
    for c in game.players[1].full_set:
        if c.card_id in old and c not in game.players[1].discard:
            for zone in (game.players[1].deck, game.players[1].hand):
                if c in zone:
                    zone.remove(c)
            game.players[1].discard.append(c)
    on_deck(table, game, "Man Without Fear")
    msgs = hit(session, table, game, DEVIL, [DEVIL, "Feint", "Breather", "Son Of A Boxer"])
    ids = [i for _, moved in table.deck_moves for i in moved]
    devil = sid(game, DEVIL)
    assert sorted(ids) == sorted([devil, *old[1:]]), (ids, msgs)                     # itself + the last 3 (Breather, Knee, Hook)
    assert old[0] in table.human_discard and all(i not in table.human_discard for i in old[1:])
    assert [kind for kind, _ in table.deck_moves] == ["shuffle", "shuffle"]
    assert said(msgs, "Meto Devil of Hell's Kitchen de tu zona de combate en tu mazo y lo barajo")


# ---------------------------------------------------------------- Through Adversity and Breather

@with_rig()
def test_through_adversity_by_hand_asks_which_rivals_he_passed_and_each_named_one_takes_one_damage(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Through Adversity", "Feint")
    human_scheme(session, table, game, "Through Adversity")
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and req.min == 0 and req.max == 2 and req.extra["op"] == "damage", req
    assert labels(session) == ["Hellboy", "Lobster Johnson", "Ninguna"]
    hp = {f: game.fighters[f].hp for f in ("hellboy", "lobster")}
    press(session, table, "hellboy")
    assert session.effect_run is not None, "a multi-pick: it waits for the confirm button"
    press(session, table, "lobster")
    assert game.fighters["hellboy"].hp == hp["hellboy"] and game.fighters["lobster"].hp == hp["lobster"]
    click(session, table, Event.CHOICE, {"i": 3})                                      # the confirm slot
    assert session.effect_run is None
    assert game.fighters["hellboy"].hp == hp["hellboy"] - 1 and game.fighters["lobster"].hp == hp["lobster"] - 1


@with_rig()
def test_through_adversity_by_hand_naming_only_one_rival_hits_only_that_one(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Through Adversity", "Feint")
    human_scheme(session, table, game, "Through Adversity")
    hp = {f: game.fighters[f].hp for f in ("hellboy", "lobster")}
    press(session, table, "hellboy")
    click(session, table, Event.CHOICE, {"i": 3})
    assert game.fighters["hellboy"].hp == hp["hellboy"] - 1 and game.fighters["lobster"].hp == hp["lobster"]


@with_rig()
def test_through_adversity_by_hand_passing_nobody_deals_nothing(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Through Adversity", "Feint")
    human_scheme(session, table, game, "Through Adversity")
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.CHOICE, {"i": len(labels(session))})                   # "None"
    assert game.fighters["hellboy"].hp == hp and session.effect_run is None


@with_rig()
def test_breather_lets_them_pick_a_non_scheme_card_from_their_discard_pile(rig):
    session, table, game, fake, cfg = rig
    a, b = sid(game, "Son Of A Boxer", 0), sid(game, "Feint", 0)
    table.human_discard += [a, b]
    human_hand(table, game, "Breather", "Grappling Hook")
    human_scheme(session, table, game, "Breather")
    req = session.effect_run.awaiting
    assert req.kind == "cards" and sorted(req.options) == sorted([a, b])
    press(session, table, a)
    assert session.effect_run is None and a in [c.card_id for c in game.players[1].hand]
