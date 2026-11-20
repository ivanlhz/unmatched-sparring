"""Yennenga played BY THE HUMAN through the panel (FakeTTS, batch mode): the ability (the panel asks how much of the damage meant for
her each Archer in her zone takes, for the bot's blow and for its effect damage), the choices surviving a resume, and Surprise
Volley and Shield Formation from the table. The bot's side of the same cards is in tests/test_yennenga_effects.py.

Her deck is sheet 176 like Medusa's, the turtles', Doctor Strange's and Bigfoot's: every id the table reports is resolved against the
human's deck. Her Archers have 2 life and no life dial in the save (`no_dial` in data/tts/yennenga.json): their life lives in the
engine and the chat, never in a dial."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, said
from test_e2_human_cards import press, put_adjacent, rig, with_rig  # noqa: F401

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def archers_beside(game, table, cfg):
    """Yennenga's two Archers next to her (one zone), nobody else near."""
    yen = game.fighters["yennenga"]
    for fid in ("archer1", "archer2"):
        spot = next(s for s in sorted(game.board.spaces) if game.board.share_zone(yen.pos, s) and s != yen.pos
                    and all(f.pos != s for f in game.fighters.values() if f.alive))
        game.fighters[fid].pos = spot
        table.positions[cfg.nicknames[fid]] = spot


def bot_attacks(session, table, game, title, target, human_title=None):
    card = next(c for c in game.players[0].hand if c.title == title)
    bot_turn(session, table, [Act("attack", fid="hellboy", target=target, card=card)])
    table.face_down = []
    if human_title is not None:
        cid = card_ids(game, 1, human_title)[0]
        table.face_down = [{"id": cid, "guid": f"h{cid}"}]
        table.human_hand.remove(cid)
        table.human_count -= 1
    return click(session, table, Event.REVEAL)


# ---------------------------------------------------------------- the ability

@with_rig("hellboy", "yennenga", "Excalibur", TRAINING)
def test_the_panel_asks_each_archer_how_much_of_the_blow_it_takes(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "yennenga")
    archers_beside(game, table, cfg)
    human_hand(table, game, "Point Blank", "Point Blank")
    yen, a1, a2 = game.fighters["yennenga"], game.fighters["archer1"], game.fighters["archer2"]
    msgs = bot_attacks(session, table, game, "Excalibur", "yennenga")
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "amount" and req.extra["assign"] == "archer1" and req.options == [0, 1, 2], msgs
    msgs = click(session, table, Event.CHOICE, {"i": 3})                   # button 3: two points to the first Archer
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.extra["assign"] == "archer2" and req.extra["left"] == 6 - 2, msgs
    msgs = click(session, table, Event.CHOICE, {"i": 2})                   # one point to the second
    assert not a1.alive and a2.hp == 1 and yen.hp == 15 - (6 - 3), msgs
    assert session.pending is None


@with_rig("hellboy", "yennenga", "Excalibur", TRAINING)
def test_assigning_nothing_leaves_the_blow_on_yennenga(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "yennenga")
    archers_beside(game, table, cfg)
    human_hand(table, game, "Point Blank", "Point Blank")
    bot_attacks(session, table, game, "Excalibur", "yennenga")
    click(session, table, Event.CHOICE, {"i": 1})
    click(session, table, Event.CHOICE, {"i": 1})
    assert game.fighters["yennenga"].hp == 15 - 6 and game.fighters["archer1"].hp == 2 and game.fighters["archer2"].hp == 2


@with_rig("hellboy", "yennenga", "Excalibur", TRAINING)
def test_the_question_survives_a_resume(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "yennenga")
    archers_beside(game, table, cfg)
    human_hand(table, game, "Point Blank", "Point Blank")
    bot_attacks(session, table, game, "Excalibur", "yennenga")
    saved = session.to_dict()
    session._restore(saved)                                                # what --resume does
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "amount" and req.extra["assign"] == "archer1"
    click(session, table, Event.CHOICE, {"i": 2})
    click(session, table, Event.CHOICE, {"i": 1})
    assert game.fighters["archer1"].hp == 1 and game.fighters["yennenga"].hp == 15 - 5


@with_rig("hellboy", "yennenga", "Excalibur", TRAINING)
def test_the_question_counts_the_blow_that_is_left_after_her_defense(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "yennenga")
    archers_beside(game, table, cfg)
    human_hand(table, game, "Shield Formation", "Point Blank")
    bot_attacks(session, table, game, "Excalibur", "yennenga", "Shield Formation")
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.extra["damage"] == 6 - 3 and req.extra["left"] == 3 and req.extra["source"] == "combat"


# ---------------------------------------------------------------- Surprise Volley, Shield Formation, Stallion Charge

def human_attacks(session, table, game, attacker, title, target="hellboy"):
    from test_d3_table_effects import human_attack
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def waiting(session):
    return session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting


@with_rig("hellboy", "yennenga", TRAINING)
def test_surprise_volley_asks_yes_no_and_the_returned_archer_attacks_and_is_placed_by_hand(rig, monkeypatch):
    from test_e2_human_cards import bot_defends_with_nothing
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "yennenga", "hellboy")
    game.defeat(game.fighters["archer1"])
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Surprise Volley", "Point Blank")
    msgs = human_attacks(session, table, game, "yennenga", "Surprise Volley")
    req = waiting(session)
    assert req.kind == "optional" and req.prompt == "return a defeated Archer?", msgs
    msgs = press(session, table, True)
    hellboy = game.fighters["hellboy"]
    assert said(msgs, "Archer 1 ataca con Surprise Volley"), msgs                      # the Archer, not Yennenga, is the attacker
    assert said(msgs, "pon a Archer 1 en el tablero"), msgs                           # your miniature: you place it by hand
    assert game.placing == {"archer1"} and game.fighters["archer1"].hp == 2 and game.board.share_zone(game.fighters["archer1"].pos, hellboy.pos)
    assert hellboy.hp == hellboy.max_hp - 3


@with_rig("hellboy", "yennenga", TRAINING)
def test_surprise_volley_with_no_defeated_archer_gives_the_action_back(rig, monkeypatch):
    from test_e2_human_cards import bot_defends_with_nothing
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "yennenga", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Surprise Volley", "Point Blank")
    actions = game.actions_left
    msgs = human_attacks(session, table, game, "yennenga", "Surprise Volley")
    assert session.pending is None and game.actions_left == actions - 1 + 1, msgs


@with_rig("hellboy", "yennenga", "Excalibur", TRAINING)
def test_the_bot_may_discard_against_your_shield_formation_or_let_the_archer_come_back(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "yennenga")
    game.defeat(game.fighters["archer1"])
    human_hand(table, game, "Shield Formation", "Point Blank")
    hand = len(game.players[0].hand)
    bot_attacks(session, table, game, "Excalibur", "yennenga", "Shield Formation")
    if game.fighters["archer1"].alive:                                  # the bot let it return: you place your miniature by hand
        assert game.placing == {"archer1"} and len(game.players[0].hand) == hand - 1
    else:                                                               # the bot paid with a card
        assert not game.placing and len(game.players[0].hand) == hand - 2


@with_rig("hellboy", "yennenga", TRAINING)
def test_stallion_charge_has_you_move_her_by_hand_and_name_who_you_passed(rig, monkeypatch):
    from test_e2_human_cards import bot_defends_with_nothing, by_hand
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "yennenga", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Stallion Charge", "Point Blank")
    hellboy, lobster = game.fighters["hellboy"], game.fighters["lobster"]
    before = (hellboy.hp, lobster.hp)
    msgs = human_attacks(session, table, game, "yennenga", "Stallion Charge")
    req = waiting(session)
    assert req.kind == "fighter" and set(req.options) == {"hellboy", "lobster"} and req.min == 0 and req.max == 2, msgs
    assert game.hand_moves["yennenga"] == {"steps": 5, "up_to": True, "through": True}          # you walk her yourself, through the bot's fighters
    click(session, table, Event.CHOICE, {"i": 1})                                                 # you name Hellboy ...
    msgs = click(session, table, Event.CHOICE, {"i": 3})                                          # ... and confirm
    assert hellboy.hp == before[0] - 3 - 1 and lobster.hp == before[1], msgs                      # the blow, then 1 for each fighter you named
