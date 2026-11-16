"""Raptors on the table through the panel (FakeTTS, batch mode), both seats: the human's attacks with the BONO DE MANADA in the combat line,
Pack Hunters (the dials follow), the schemes (Working Things Out moves all three by hand, Coordinated Attack Pattern names the three
miniatures), Decoy as a defense; and the bot's Raptors: the same attack against a human, the loss only when the last Raptor falls. The
bot's side of the same cards is in tests/test_raptors_effects.py.

Their deck is sheet 176 like Medusa's and the turtles': every id the table reports is resolved against the owner's deck. The three Raptors
are three miniatures (Custom_Assetbundle) with a life dial each, found by their names (Raptor Blue, Raptor Delta, Raptor Echo)."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.lua import ChatKind
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with_nothing, human_scheme, labels, press, put_adjacent, rig, with_rig  # noqa: F401

TEAM = ["blue", "delta", "echo"]


@pytest.fixture(autouse=True)
def raptors_are_interpreted(monkeypatch):
    """The effects of the Raptors run on the interpreter; until `INTERPRETED_HEROES` lists them (a shared file) the tests list them themselves."""
    from sparring.effects import state
    monkeypatch.setattr(state, "INTERPRETED_HEROES", state.INTERPRETED_HEROES | {"raptors"})
HAND = ("Excalibur", "B.P.R.D. Training", "Service Pistol", "Right Hand Of Doom")        # the bot's Hellboy
BOT_HAND = ("Pack Hunters", "Eviscerate", "Working Things Out", "Coordinated Attack Pattern", "Decoy", "Eaten Alive")


def dial(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


def bot_attacks(session, table, game, title, fid, target, human_title=None):
    """The bot's `fid` attacks `target` with `title`; the human answers with `human_title` face down (None: no defense)."""
    card = next(c for c in game.players[0].hand if c.title == title)
    bot_turn(session, table, [Act("attack", fid=fid, target=target, card=card)])
    if human_title:
        cid = card_ids(game, 1, human_title)[0]
        table.face_down = [{"id": cid, "guid": f"h{cid}"}]
        table.human_hand.remove(cid)
        table.human_count -= 1
    else:
        table.face_down = []
    return click(session, table, Event.REVEAL)


def around(game, table, cfg, target, fids):
    for fid in fids:
        put_adjacent(game, table, cfg, fid, target)


# ---------------------------------------------------------------- the human attacks

@with_rig("hellboy", "raptors", *HAND)
def test_the_human_attack_adds_one_for_each_other_raptor_next_to_the_defender_and_the_line_says_so(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    around(game, table, cfg, "hellboy", TEAM)
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Eviscerate", "Pack Hunters")
    human_attack(session, table, game, "blue", "hellboy", "Eviscerate")
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Raptor Blue ataca con Eviscerate (5) y BONO DE MANADA (+2): total 7"), msgs
    assert game.fighters["hellboy"].hp == 18 - 7 and dial(session, cfg, table, "hellboy") == 11


@with_rig("hellboy", "raptors", *HAND)
def test_alone_beside_the_defender_a_raptor_gets_no_bonus(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "blue", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Eviscerate", "Pack Hunters")
    human_attack(session, table, game, "blue", "hellboy", "Eviscerate")
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Raptor Blue ataca con Eviscerate (5): total 5") and not said(msgs, "BONO DE MANADA"), msgs


@with_rig("hellboy", "raptors", *HAND)
def test_pack_hunters_deals_one_for_each_raptor_beside_the_defender_and_the_dial_follows(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    around(game, table, cfg, "hellboy", TEAM)
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Pack Hunters", "Eviscerate")
    human_attack(session, table, game, "blue", "hellboy", "Pack Hunters")
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "BONO DE MANADA (+2): total 6") and said(msgs, "Tu carta: Pack Hunters: hellboy -3 PV (9)"), msgs
    assert game.fighters["hellboy"].hp == 18 - 6 - 3 and dial(session, cfg, table, "hellboy") == 9


# ---------------------------------------------------------------- the human's schemes

@with_rig("hellboy", "raptors", *HAND)
def test_working_things_out_leaves_the_three_moves_to_the_human_and_gives_the_action_back(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Working Things Out", "Eviscerate")
    msgs = human_scheme(session, table, game, "Working Things Out")
    for fid in TEAM:
        assert said(msgs, f"mueve a {fid} hasta 3 casillas (puede atravesar rivales)"), msgs
    assert said(msgs, "ganas 1 accion") and game.actions_left == 2 and session.effect_run is None


@with_rig("hellboy", "raptors", *HAND)
def test_coordinated_attack_pattern_asks_for_the_chosen_raptor_by_the_name_of_its_miniature(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Coordinated Attack Pattern", "Eviscerate")
    msgs = human_scheme(session, table, game, "Coordinated Attack Pattern")
    assert session.effect_run.awaiting.kind == "fighter" and labels(session) == ["Raptor Blue", "Raptor Delta", "Raptor Echo"], labels(session)
    assert said(msgs, "1: Raptor Blue, 2: Raptor Delta, 3: Raptor Echo"), msgs          # ONE question: which Raptor
    msgs = press(session, table, "Raptor Delta")
    assert session.effect_run is None and game.actions_left == 1
    for fid in ("blue", "echo"):
        assert said(msgs, f"coloca a {fid}"), msgs                                    # the others go by hand, into the chosen Raptor's zone


# ---------------------------------------------------------------- Decoy, played by the human as a defense

@with_rig("hellboy", "raptors", *HAND)
def test_decoy_asks_which_other_raptor_and_tells_the_human_to_place_her_beside_the_attacker(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "blue")
    human_hand(table, game, "Decoy", "Eviscerate")
    msgs = bot_attacks(session, table, game, "Excalibur", "hellboy", "blue", "Decoy")
    assert session.effect_run.awaiting.kind == "optional" and said(msgs, "Usas el efecto de Decoy"), msgs
    msgs = press(session, table, True)
    assert labels(session) == ["Raptor Delta", "Raptor Echo"], labels(session)             # the other Raptors, never the one who defends
    msgs = press(session, table, "Raptor Delta")
    assert said(msgs, "Tu carta: Decoy: en la mesa: coloca a delta en una casilla adyacente"), msgs
    assert game.fighters["blue"].hp == 7 - 3 and dial(session, cfg, table, "blue") == 4


# ---------------------------------------------------------------- the bot plays the Raptors against the human

@with_rig("raptors", "hellboy", *BOT_HAND)
def test_the_bots_pack_hunters_carries_the_bonus_and_hurts_for_each_raptor_beside_the_human_hero(rig):
    session, table, game, fake, cfg = rig
    around(game, table, cfg, "hellboy", ["blue", "delta"])
    human_hand(table, game, "B.P.R.D. Training", "Right Hand Of Doom", "Service Pistol")
    msgs = bot_attacks(session, table, game, "Pack Hunters", "blue", "hellboy")
    assert said(msgs, "Raptor Blue ataca con Pack Hunters (4) y BONO DE MANADA (+1): total 5"), msgs
    assert said(msgs, "Aplicado: Pack Hunters: hellboy -2 PV (11)"), msgs
    assert dial(session, cfg, table, "hellboy") == 11


@with_rig("raptors", "hellboy", *BOT_HAND)
def test_the_bots_raptors_are_beaten_only_when_the_third_one_falls(rig):
    session, table, game, fake, cfg = rig
    game.defeat(game.fighters["blue"])
    game.defeat(game.fighters["delta"])
    assert game.winner is None and game.hero(0).fid == "echo"
    game.defeat(game.fighters["echo"])
    assert game.winner == 1


@with_rig("raptors", "hellboy", *BOT_HAND)
def test_the_three_miniatures_and_their_dials_are_the_ones_of_the_data(rig):
    session, table, game, fake, cfg = rig
    sc = cfg.session_config()
    assert {fid: sc.pieces[fid] for fid in TEAM} == {"blue": "1a2945", "delta": "4573de", "echo": "b5c3d5"}
    assert {fid: sc.dials[fid] for fid in TEAM} == {"blue": "950174", "delta": "c93049", "echo": "deff03"}
    assert {fid: cfg.nicknames[fid] for fid in TEAM} == {"blue": "Raptor Blue", "delta": "Raptor Delta", "echo": "Raptor Echo"}


# ---------------------------------------------------------------- Ambush: the bot names a position, the human discards it, the bot reads it

def awaiting(session):
    return session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting


def lay_on_pile(table, game, title):
    """The human discards the named card of their hand onto their discard pile by hand (what the bot's Ambush waits for)."""
    by_id = {c.card_id: c for c in game.players[1].full_set}
    i = next(i for i in table.human_hand if by_id[i].title == title)
    table.human_hand.remove(i)
    table.human_discard.append(i)
    table.human_count -= 1
    return i


def ambush(session, table, game, cfg, *human_cards):
    around(game, table, cfg, "hellboy", ["blue"])
    human_hand(table, game, *human_cards)
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    card = next(c for c in game.players[0].hand if c.title == "Ambush")
    first = bot_turn(session, table, [Act("attack", fid="blue", target="hellboy", card=card)])
    return [*first, *click(session, table, Event.REVEAL)]


@with_rig("raptors", "hellboy", "Ambush", "Eviscerate", "Pack Hunters", "Decoy")
def test_the_bots_ambush_names_a_position_and_reads_the_card_the_human_lays_on_their_pile_to_add_its_boost(rig):
    session, table, game, fake, cfg = rig
    msgs = ambush(session, table, game, cfg, "B.P.R.D. Training", "Excalibur", "Service Pistol")
    assert said(msgs, "al azar: la carta"), msgs
    loud = [m for m in msgs if m.startswith("DESCARTE AL AZAR: CARTA ")]
    assert len(loud) == 1 and loud[0].endswith(" DE 5 (DESDE LA IZQUIERDA)") and loud[0].kind == ChatKind.WARNING, msgs
    req = awaiting(session)
    assert req.kind == "cards" and req.extra["pile_mode"] == "reveal" and req.extra["ambush"] and (req.min, req.max) == (1, 1)
    hp = game.fighters["hellboy"].hp
    lay_on_pile(table, game, "Excalibur")                                  # BOOST 3
    click(session, table, Event.CHOICE, {"i": 1})                          # Done
    assert session.pending is None
    assert game.fighters["hellboy"].hp == hp - (2 + 3)                    # the printed 2 and the BOOST of the card they laid down
    assert any(c.title == "Excalibur" for c in game.players[1].discard)


@with_rig("raptors", "hellboy", "Ambush", "Eviscerate", "Pack Hunters", "Decoy")
def test_the_bots_ambush_waits_while_the_pile_shows_no_new_card(rig):
    session, table, game, fake, cfg = rig
    ambush(session, table, game, cfg, "B.P.R.D. Training", "Excalibur")
    msgs = click(session, table, Event.CHOICE, {"i": 1})                   # Done with nothing laid down
    assert awaiting(session).kind == "cards" and said(msgs, "no veo"), msgs


@with_rig("raptors", "hellboy", "Ambush", "Eviscerate", "Pack Hunters", "Decoy")
def test_an_ambush_against_an_empty_human_hand_asks_nothing_and_adds_nothing(rig):
    from sparring.effects.random_discard import discard_random_known
    session, table, game, fake, cfg = rig
    game.players[1].hand.clear()

    class Run:
        def ask(self, *a, **k):
            raise AssertionError("asked about an empty hand")
    assert discard_random_known(Run(), game, 1) is None


@with_rig("raptors", "hellboy", "Ambush", "Eviscerate", "Pack Hunters", "Decoy")
def test_the_bots_ambush_question_survives_a_save_and_is_answered_after_the_resume(rig):
    from test_d3_table_effects import twin_session
    session, table, game, fake, cfg = rig
    ambush(session, table, game, cfg, "B.P.R.D. Training", "Excalibur", "Service Pistol")
    assert awaiting(session).extra["ambush"]
    twin = twin_session(session, cfg, session.to_dict())
    assert awaiting(twin).extra["ambush"] and awaiting(twin).extra["which"] == awaiting(session).extra["which"]
    hp = game.fighters["hellboy"].hp
    lay_on_pile(table, game, "Service Pistol")                             # BOOST 2
    twin.client = session.client
    click(twin, table, Event.CHOICE, {"i": 1})
    assert twin.game.fighters["hellboy"].hp == hp - (2 + 2)
