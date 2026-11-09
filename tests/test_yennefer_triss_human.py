"""Yennefer & Triss on the table through the panel (FakeTTS, batch mode), both variants and both seats: the human Yennefer's free BOOST
(SORCERESS OF VENGERBERG: asked at Reveal whatever the card, never for Triss), the human Triss's MERIGOLD THE FEARLESS after a
scheme (2 damage to a fighter next to her, the bot's hero loses the life), the human's Lodge of sorceresses (the panel asks which
card they reveal), the bot's Lodge and Merigold's Hailstorm played against the human (the human chooses one of the three, and the
deck option has the bot move their four real top cards), and the bot's Echoing blast going back to its hand. The bot's side of
the same cards is in tests/test_yennefer_triss_effects.py.

Their deck is sheet 176 like the other ten: every id the table reports is resolved against the owner's deck."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_attack, human_hand, said
from test_doctor_strange_human import StrangeTable, on_deck, pause_labels
from test_donatello_session import SPOTS
from test_e2_human_cards import human_scheme, press, put_adjacent


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


def with_rig(*bot_hand, bot="hellboy", human="yennefer-triss"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


def no_defense(session, monkeypatch):
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)


def attack(session, table, game, attacker, title, target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def combat_line(msgs):
    return next(m for m in msgs if m.startswith("Combate:"))


def spend(table, game, title):
    """The human puts a card of their hand in their discard pile: a boost."""
    by_id = {c.card_id: c for c in game.players[1].full_set}
    i = next(i for i in table.human_hand if by_id[i].title == title)
    table.human_hand.remove(i)
    table.human_discard.append(i)
    table.human_count -= 1


def dial(cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


# ---------------------------------------------------------------- the human Yennefer boosts

@with_rig()
def test_the_human_yennefer_is_asked_for_a_boost_whatever_the_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Echoing blast", "Telepathy")
    msgs = attack(session, table, game, "yennefer", "Echoing blast")
    assert session.pending is not None and session.pending.wait is not None
    assert said(msgs, "Echoing blast revelado: si quieres potenciar") and not said(msgs, "Combate:")
    spend(table, game, "Telepathy")                                   # BOOST 1
    msgs = click(session, table, Event.BOOST)
    assert "total 4" in combat_line(msgs) and session.pending is None, combat_line(msgs)


@with_rig()
def test_declining_the_boost_resolves_the_attack_as_printed(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Echoing blast", "Telepathy")
    attack(session, table, game, "yennefer", "Echoing blast")
    msgs = click(session, table, Event.NO_BOOST)
    assert "total 3" in combat_line(msgs) and session.pending is None


@with_rig(human="triss-yennefer")
def test_the_human_triss_as_the_hero_has_no_boost_ability(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Echoing blast", "Telepathy")
    msgs = attack(session, table, game, "triss", "Echoing blast")
    assert session.pending is None and "total 3" in combat_line(msgs)


@with_rig(human="yennefer-triss")
def test_the_boost_is_asked_even_when_the_bots_card_cancels_the_effects(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)
    human_hand(table, game, "Incinerate", "Telepathy")
    msgs = attack(session, table, game, "yennefer", "Incinerate")
    assert session.pending is not None and session.pending.wait is not None, msgs


# ---------------------------------------------------------------- the human Triss: Merigold the Fearless

@with_rig(human="triss-yennefer")
def test_after_the_human_triss_plays_a_scheme_the_fighter_next_to_her_takes_two(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Advisor to the king", "Telepathy")
    hp = game.fighters["hellboy"].hp
    msgs = human_scheme(session, table, game, "Advisor to the king")
    assert game.fighters["hellboy"].hp == hp - 2, msgs
    assert not said(msgs, "ilegal")


@with_rig(human="triss-yennefer")
def test_with_two_fighters_next_to_her_the_panel_asks_which_one(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "yennefer", "triss")
    put_adjacent(game, table, cfg, "lobster", "triss")
    human_hand(table, game, "Advisor to the king", "Telepathy")
    hp, lobster = game.fighters["hellboy"].hp, game.fighters["lobster"].hp
    human_scheme(session, table, game, "Advisor to the king")
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "fighter"
    assert set(session.effect_run.awaiting.options) >= {"hellboy", "lobster", "yennefer"}
    press(session, table, "lobster")
    assert game.fighters["lobster"].hp == lobster - 2 and game.fighters["hellboy"].hp == hp


# ---------------------------------------------------------------- Lodge of sorceresses

@with_rig("Excalibur", "Service Pistol")
def test_the_humans_lodge_asks_which_card_they_reveal_and_both_draw_its_boost(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Lodge of sorceresses", "Incinerate", "Telepathy")
    hero = game.fighters["yennefer"].hp
    human_scheme(session, table, game, "Lodge of sorceresses")
    req = session.effect_run.awaiting
    assert req.kind == "cards" and req.extra["purpose"] == "lodge"
    titles = {game.card_of(i, 1).title for i in req.options}
    assert len(titles) == len(req.options), "one button per title"
    before = len(game.players[0].hand)
    press(session, table, next(i for i in req.options if game.card_of(i, 1).title == "Incinerate"))      # BOOST 2
    assert session.effect_run is None or session.effect_run.awaiting is None
    assert table.human_deals[-1:] == [2]
    bot_drew = len(game.players[0].hand) - before
    assert bot_drew >= 0
    foe = game.fighters["hellboy"]
    assert game.fighters["yennefer"].hp == hero - (2 if bot_drew <= 2 else 0)        # the one who drew more (both on a tie) takes that much
    assert foe.hp == foe.max_hp - (bot_drew if bot_drew >= 2 else 0)


@with_rig("Lodge of sorceresses", "Telepathy", "Echoing blast", bot="yennefer-triss", human="hellboy")
def test_the_bots_lodge_asks_the_human_which_card_they_reveal(rig):
    session, table, game, fake, cfg = rig
    lodge = next(c for c in game.players[0].hand if c.title == "Lodge of sorceresses")
    human_hand(table, game, "Excalibur", "Service Pistol")
    bot_turn(session, table, [Act("scheme", fid="yennefer", card=lodge)])
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "cards" and req.extra["purpose"] == "lodge" and req.player == 1
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert session._paused() is None and not said(msgs, "ilegal")


# ---------------------------------------------------------------- Merigold's Hailstorm played by the bot against the human

def bot_hailstorm(session, table, game, monkeypatch):
    hail = next(c for c in game.players[0].hand if c.title == "Merigold's Hailstorm")
    human_hand(table, game, "B.P.R.D. Training", "Excalibur")
    bot_turn(session, table, [Act("attack", fid=game.hero(0).fid, target="hellboy", card=hail)])
    table.face_down = []
    return click(session, table, Event.REVEAL)


@with_rig("Merigold's Hailstorm", "Echoing blast", bot="triss-yennefer", human="hellboy")
def test_the_bots_hailstorm_lets_the_human_choose_damage(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hp = game.fighters["hellboy"].hp
    msgs = bot_hailstorm(session, table, game, monkeypatch)
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "effect" and len(req.options) == 3, msgs
    assert any("3" in lab for lab in pause_labels(session)) or len(pause_labels(session)) == 3
    click(session, table, Event.CHOICE, {"i": 2})                      # "Your hero takes 3 damage"
    assert game.fighters["hellboy"].hp == hp - 4 - 3
    assert dial(cfg, table, "hellboy") == hp - 4 - 3


@with_rig("Merigold's Hailstorm", "Echoing blast", bot="triss-yennefer", human="hellboy")
def test_the_bots_hailstorm_deck_option_has_the_bot_move_the_real_top_four(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    tops = on_deck(table, game, "Glimpse Of Hell", "Excalibur", "Service Pistol", "B.P.R.D. Training", "Right Hand Of Doom")
    bot_hailstorm(session, table, game, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 3})                      # "Discard the top 4 cards of your deck"
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "amount" and req.extra["top_discard"] and req.options == [4]
    click(session, table, Event.CHOICE, {"i": 1})
    assert table.top_discards == [4] and table.human_discard[-4:] == tops[:4]
    assert said(session.messages, "descarto las 4 de arriba de tu mazo")


@with_rig("Merigold's Hailstorm", "Echoing blast", bot="triss-yennefer", human="hellboy")
def test_the_bots_hailstorm_discard_option_is_yours_to_do_on_the_table(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    msgs = bot_hailstorm(session, table, game, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 1})                      # "You discard 2 cards"
    assert any("Descarta 2" in m or "descartar" in m.lower() or "2 carta" in m for m in session.messages), session.messages[-6:]


# ---------------------------------------------------------------- the bot's Echoing blast comes back to its hand

@with_rig("Echoing blast", "Telepathy", bot="yennefer-triss", human="hellboy")
def test_the_bots_echoing_blast_goes_back_to_its_hand_when_it_wins(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    blast = next(c for c in game.players[0].hand if c.title == "Echoing blast")
    put_adjacent(game, table, cfg, "yennefer", "hellboy")
    human_hand(table, game, "Excalibur")
    bot_turn(session, table, [Act("attack", fid="yennefer", target="hellboy", card=blast)])
    table.face_down = []
    msgs = click(session, table, Event.REVEAL)
    assert blast in game.players[0].hand and blast.card_id in table.bot_hand, msgs         # the engine's hand AND the table's
    assert blast.card_id not in table.bot_discard and blast.card_id not in table.bot_play
    assert any(sc.startswith("-- sparring:return_card_to_hand") for sc in table.scripts), "the card was never taken from its combat spot"
    assert not said(session.messages, "vuelve a la mano del bot"), "the table refused: card_back.bot_manual"


# ---------------------------------------------------------------- save and resume keep the variant, the ONGOING and a pause

@pytest.mark.parametrize("rig", [("hellboy", "yennefer-triss", ("Excalibur", "Service Pistol")),
                                 ("hellboy", "triss-yennefer", ("Excalibur", "Service Pistol"))], indirect=True)
def test_a_save_keeps_which_heroine_is_the_hero_and_the_advisor_in_play(rig):
    from test_d3_table_effects import twin_session
    session, table, game, fake, cfg = rig
    hero, side = game.hero(1).fid, next(f.fid for f in game.own(1) if not f.hero)
    human_hand(table, game, "Advisor to the king", "Telepathy")
    human_scheme(session, table, game, "Advisor to the king")
    assert game.fx.ongoing_card_id(1) is not None
    twin = twin_session(session, cfg, session.to_dict())
    assert twin.game.hero_def(1).slug == game.hero_def(1).slug
    assert (twin.game.hero(1).fid, twin.game.hero(1).hp) == (hero, game.hero(1).hp)
    assert twin.game.fighters[side].max_hp == 6 and not twin.game.fighters[side].hero
    assert twin.game.fx.ongoing_card_id(1) == game.fx.ongoing_card_id(1) and twin.game.fx.boost_bonus(1) == 1


@with_rig("Excalibur", "Service Pistol")
def test_a_save_taken_at_the_lodge_question_resumes_and_the_answer_goes_on(rig):
    from test_d3_table_effects import twin_session
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Lodge of sorceresses", "Incinerate", "Telepathy")
    human_scheme(session, table, game, "Lodge of sorceresses")
    assert session.effect_run.awaiting.extra["purpose"] == "lodge"
    twin = twin_session(session, cfg, session.to_dict())
    req = twin.effect_run.awaiting if twin.effect_run is not None else twin._paused()[2].awaiting
    assert req.kind == "cards" and req.extra["purpose"] == "lodge"
    click(twin, table, Event.CHOICE, {"i": 1})
    assert twin._paused() is None and len(table.human_deals) >= 1


# ---------------------------------------------------------------- the boost no cancel removes, and the Advisor's +1 told in a Maneuver

@with_rig("Feint", bot="medusa", human="yennefer-triss")
def test_the_boost_is_asked_and_counts_against_the_bots_feint(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "yennefer", "medusa")
    feint = next(c for c in game.players[0].hand if c.title == "Feint")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: feint)
    human_hand(table, game, "Echoing blast", "Telepathy")
    msgs = attack(session, table, game, "yennefer", "Echoing blast", target="medusa")
    assert session.pending is not None and session.pending.wait is not None, msgs
    assert said(msgs, "Echoing blast revelado: si quieres potenciar") and not said(msgs, "Combate:")
    spend(table, game, "Telepathy")                                   # BOOST 1
    msgs = click(session, table, Event.BOOST)
    assert "total 4" in combat_line(msgs), combat_line(msgs)


@with_rig("Excalibur", "Service Pistol", human="yennefer-triss")
def test_a_maneuver_boost_with_the_advisor_in_play_is_announced_one_higher(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Advisor to the king", "Telepathy", "Echoing blast")
    human_scheme(session, table, game, "Advisor to the king")
    click(session, table, Event.MANEUVER)
    spend(table, game, "Telepathy")                                   # BOOST 1, +1 from the ONGOING
    msgs = click(session, table, Event.MANEUVER_BOOST)
    assert said(msgs, "(BOOST 2)") and said(msgs, "+2 al movimiento"), msgs
