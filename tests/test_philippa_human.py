"""Philippa played BY THE HUMAN through the panel (FakeTTS, batch mode) and against the human when the bot plays her: TWO STEPS AHEAD's
Yes / No at the end of the turn (the table deals the cards), Owlform (the human lays the cards they discard on their pile), Backup plan,
Polymorphy (the human places the miniature by hand and the move becomes 5), Spymaster's ruse in both directions (the human names the four
cards they reveal; the bot discards the two the human picks of its own) and the bot's Do my bidding and Spymaster's ruse against a human.
The engine side of the same cards is in tests/test_philippa_effects.py."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_attack, human_hand, said
from test_doctor_strange_human import StrangeTable
from test_donatello_session import SPOTS
from test_e2_human_cards import human_scheme, labels, press, put_adjacent

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


@pytest.fixture
def rig(request, tmp_path):
    bot, human, bot_hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, bot_hand, table_cls=StrangeTable, **SPOTS)
    table.human_card_spot = tuple(cfg.session_config().human_card_spot)
    table.human_deck = []
    table.hand_returns = []
    table.top_discards = []
    put_adjacent(game, table, cfg, game.hero(1).fid, game.hero(0).fid)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def rigged(*bot_hand, bot="hellboy", human="philippa"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


def defends(session, game, monkeypatch, title=None):
    card = None if title is None else next(c for c in game.players[0].hand if c.title == title)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: card)
    return card


def attack(session, table, game, attacker, title, target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def give_up(table, game, *titles):
    """The human puts these cards of their hand on their discard pile (what Owlform waits for)."""
    ids = []
    for title in titles:
        cid = next(i for i in card_ids(game, 1, title) if i in table.human_hand)
        ids.append(cid)
        table.human_hand.remove(cid)
        table.human_discard.append(cid)
        table.human_count -= 1
    return ids


def done(session, table):
    return click(session, table, Event.CHOICE, {"i": 1})


def end_turn(session, table):
    """Two maneuvers and End action; the bot then maneuvers too."""
    plan = []
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    return click(session, table, Event.END_ACTION)


# ---------------------------------------------------------------- TWO STEPS AHEAD

@rigged(TRAINING)
def test_with_fewer_than_four_cards_the_end_of_the_turn_asks_yes_or_no_and_yes_deals_the_rest(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Owlform")
    end_turn(session, table)                                          # the two maneuvers draw one card each: three in hand
    req = session.effect_run.awaiting
    assert req is not None and req.kind == "optional" and len(game.players[1].hand) == 3
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert table.human_deals == [1, 1, 1] and len(game.players[1].hand) == 4, msgs


@rigged(TRAINING)
def test_saying_no_keeps_the_hand_as_it_is(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Owlform")
    end_turn(session, table)
    click(session, table, Event.CHOICE, {"i": 2})
    assert table.human_deals == [1, 1] and len(game.players[1].hand) == 3


@rigged(TRAINING)
def test_with_four_cards_after_the_maneuvers_nothing_is_asked(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Owlform", "Regicide")
    msgs = end_turn(session, table)
    assert session.effect_run is None or session.effect_run.awaiting is None
    assert table.human_deals == [1, 1] and len(game.players[1].hand) == 4


# ---------------------------------------------------------------- Owlform

@pytest.mark.parametrize("given,bonus", [(0, 0), (2, 2)])
@rigged(TRAINING)
def test_owlform_waits_for_the_cards_the_human_lays_on_their_pile_and_adds_one_each(rig, monkeypatch, given, bonus):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    human_hand(table, game, "Owlform", "Regicide", "Cunning", "Spellbreaker")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "philippa", "Owlform")
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "cards" and req.extra["tag"] == "any" and req.extra["pile_mode"] if False else req.kind == "cards"
    assert said(msgs, "las cartas de tu mano que quieras descartar") or said(msgs, "descartar"), msgs
    give_up(table, game, *["Regicide", "Cunning"][:given])
    done(session, table)
    assert game.fighters["hellboy"].hp == hp - 3 - bonus
    assert len(game.players[1].discard) >= given


# ---------------------------------------------------------------- Backup plan and Polymorphy

@rigged(TRAINING)
def test_backup_plan_sets_the_health_to_five_and_the_dial_follows(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Backup plan", "Owlform")
    msgs = human_scheme(session, table, game, "Backup plan")
    press(session, table, 0)
    assert game.fighters["philippa"].hp == 5
    assert table.dials[cfg.session_config().dials["philippa"]]["value"] == 5, msgs


@rigged(TRAINING)
def test_backup_plan_may_draw_three_instead(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Backup plan", "Owlform")
    human_scheme(session, table, game, "Backup plan")
    press(session, table, 1)
    assert table.human_deals == [3] and game.fighters["philippa"].hp == 12


@rigged(TRAINING)
def test_polymorphy_leaves_the_placement_of_the_miniature_to_the_human_and_the_move_becomes_five(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Polymorphy", "Owlform")
    msgs = human_scheme(session, table, game, "Polymorphy")
    ph = game.fighters["philippa"]
    assert session.effect_run is None and said(msgs, "en la mesa: coloca a philippa en cualquier casilla"), msgs
    assert ph.move == 5 and game.fx.ongoing_card_id(1) is not None


# ---------------------------------------------------------------- Spymaster's ruse

def pick_card(session, table, title):
    """Presses the panel button of the card titled `title`, turning the pages of the list until it shows."""
    for _ in range(12):
        labs = labels(session)
        k = next((k for k, text in enumerate(labs, 1) if text == title), None)
        if k is not None:
            return click(session, table, Event.CHOICE, {"i": k})
        more = next(k for k, text in enumerate(labs, 1) if text.startswith("Mas "))
        click(session, table, Event.CHOICE, {"i": more})
    raise AssertionError(f"{title} never showed on the panel")


def awaiting(session):
    return session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting


@rigged(TRAINING, "Service Pistol", "Right Hand Of Doom", "Excalibur", "Glimpse Of Hell", "Second Shot")
def test_the_humans_ruse_makes_the_bot_reveal_four_the_human_picks_two_and_the_bot_draws_two(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Spymaster's ruse", "Owlform")
    hand0, pile0 = len(game.players[0].hand), len(table.bot_discard)
    msgs = human_scheme(session, table, game, "Spymaster's ruse")
    req = awaiting(session)
    assert req.kind == "cards" and req.extra["purpose"] == "ruse" and len(req.options) == 4 and (req.min, req.max) == (2, 2), msgs
    shown = {c.card_id: c.title for c in game.players[0].full_set if c.card_id in req.options}
    assert said(session.messages, "Elige cartas (2)"), session.messages[-5:]            # the chat names the four the bot revealed
    first, second = list(shown.values())[:2]
    pick_card(session, table, first)
    pick_card(session, table, second)                                                    # the second pick reaches the maximum: it answers
    assert len(game.players[0].hand) == hand0 - 2 + 2
    assert len(table.bot_discard) == pile0 + 2


@rigged("Spymaster's ruse", "Owlform", bot="philippa", human="hellboy")
def test_the_bots_ruse_asks_the_human_for_four_cards_then_names_two_to_discard(rig):
    session, table, game, fake, cfg = rig
    ruse = next(c for c in game.players[0].hand if c.title == "Spymaster's ruse")
    human_hand(table, game, "Excalibur", "Service Pistol", "Right Hand Of Doom", "Glimpse Of Hell", "Second Shot")
    bot_turn(session, table, [Act("scheme", fid="dijkstra", card=ruse)])
    req = awaiting(session)
    assert req.kind == "cards" and req.extra["purpose"] == "ruse_reveal" and req.player == 1 and (req.min, req.max) == (4, 4)
    for title in ("Excalibur", "Service Pistol", "Right Hand Of Doom", "Glimpse Of Hell"):
        pick_card(session, table, title)
    assert session.effect_run is None or session.effect_run.awaiting is None
    assert len(game.players[1].discard) >= 2 and len(game.players[0].hand) >= 0, session.messages[-8:]
    assert said(session.messages, "de tu mano en tu descarte (efecto del bot)"), session.messages[-8:]    # the two cards the bot chose are yours to move


# ---------------------------------------------------------------- Do my bidding, played by the bot against the human

@rigged("Do my bidding", "Owlform", bot="philippa", human="hellboy")
def test_the_bots_do_my_bidding_tells_the_human_which_card_to_play_instead(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur", "Service Pistol", "Right Hand Of Doom", "Glimpse Of Hell")
    bidding = next(c for c in game.players[0].hand if c.title == "Do my bidding")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: bidding)
    attack(session, table, game, "hellboy", "Excalibur", target="philippa")
    req = awaiting(session)
    by_id = {c.card_id: c for c in game.players[1].full_set}
    assert req.kind == "cards" and req.extra["bidding"] and req.extra["pile_mode"] == "play" and len(req.options) == 1
    old, new = req.extra["old"], req.options[0]
    assert by_id[old].title == "Excalibur" and new != old
    assert said(session.messages, "ha elegido") or said(session.messages, "he elegido"), session.messages[-4:]     # bidding.instruction names the card
    table.face_down = [{"id": old, "guid": f"h{old}"}, {"id": new, "guid": f"h{new}"}]     # the chosen card lies beside Excalibur, which the bot takes back
    done(session, table)
    assert session.effect_run is None or session.effect_run.awaiting is None
    assert any("Do my bidding" in m for m in session.messages)
    assert by_id[old] in game.players[1].hand                                            # the card that went back to the hand
    assert said(session.messages, f"juegas {by_id[new].title} en su lugar")


@rigged("Service Pistol", "Excalibur", "Right Hand Of Doom")
def test_the_humans_do_my_bidding_lets_them_choose_the_card_the_bot_plays_and_the_bot_swaps_it_on_the_table(rig):
    session, table, game, fake, cfg = rig
    from test_session import human_plays
    human_hand(table, game, "Do my bidding", "Owlform")
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="philippa", card=pistol)])
    played = human_plays(table, game, "Do my bidding")
    table.human_hand.remove(played.card_id)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    req = awaiting(session)
    assert req.kind == "cards" and req.extra["purpose"] == "bidding" and req.player == 1 and (req.min, req.max) == (0, 1)     # none = the same card
    assert sorted(req.options) == sorted(c.card_id for c in game.players[0].hand) and len(req.options) == 2
    other = next(c for c in game.players[0].hand if c.title == "Excalibur")
    pick_card(session, table, "Excalibur")
    assert session.effect_run is None or session.effect_run.awaiting is None
    flow = session.pending.flow if session.pending is not None else None
    assert flow is None or flow.atk_card.card_id == other.card_id
    assert pistol in game.players[0].hand and other not in game.players[0].hand or other in game.players[0].discard
    assert any(sc.startswith("-- sparring:place_card_face_up") or "place_card_face_up" in sc for sc in table.scripts), "the bot never put the chosen card on its spot"
