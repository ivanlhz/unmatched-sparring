"""Blackbeard on the table through the panel (FakeTTS, batch mode), both seats. The human as Blackbeard: the question about the doubloon for an action at
the start of the turn, the payment when he takes combat damage, the Treasury and his own cards at the panel. The human as the OPPONENT of the bot's
Blackbeard: the ransom ("unless N doubloons") is a yes/no on the panel that names the effect, and Queen Anne's Revenge asks how many doubloons to pay.

The doubloons are counters of the engine, not read from the tokens on the table: the chat says every change with who holds how many, so the table
player can move the tokens and follow the bot's side. The bot's side of the same cards is in tests/test_blackbeard_effects.py."""
from __future__ import annotations

from sparring.effects.select import counter_value
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with, bot_defends_with_nothing, labels, press, put_adjacent, rig, with_rig  # noqa: F401

BOT_HAND = ("A Brace of Primed Pistols", "Avast Ye!", "Queen Anne's Revenge", "Parley", "Give No Quarter", "Fearsome and Calculating")
HELLBOY_HAND = ("Excalibur", "B.P.R.D. Training", "Service Pistol", "Right Hand Of Doom", "Second Shot")
LEO_HAND = ("Katana", "Heroes in a half shell", "Quick strike", "Fearless leader", "Wise beyond his years")


def coins(game, player=0):
    return counter_value(game, player, "doubloons"), counter_value(game, player, "treasury")


def set_coins(game, player, held, treasury):
    game.fx.set_counter(player, "doubloons", held)
    game.fx.set_counter(player, "treasury", treasury)


def dial(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


def bot_attacks(session, table, game, title, fid, target, human_title=None):
    """The bot's `fid` attacks `target` with `title`; the human answers with `human_title` face down (None: no defense)."""
    from sparring.ai_medusa import Act
    from test_d3_table_effects import bot_turn
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


def next_to_the_human(session, table, game, cfg, bot_fid="blackbeard", human_fid="hellboy"):
    h = game.fighters[human_fid]
    spot = next(s for s in sorted(game.board.adj[h.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    game.fighters[bot_fid].pos = spot
    table.positions[cfg.nicknames[bot_fid]] = spot


# ---------------------------------------------------------------- the human as Blackbeard

@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_humans_turn_opens_with_the_doubloon_question(rig):
    session, table, game, fake, cfg = rig
    req = session.effect_run.awaiting
    assert game.turn == 1 and req.kind == "optional" and req.extra["doubloon_action"] == 1
    assert (req.extra["held"], req.extra["treasury"]) == (2, 1) and coins(game, 1) == (2, 1)
    assert labels(session)[0] == "1: Pagar 1 doblon" or "doblon" in " ".join(labels(session)).lower()


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_yes_pays_one_doubloon_to_the_treasury_for_an_action_and_the_chat_says_who_holds_how_many(rig):
    session, table, game, fake, cfg = rig
    before = game.actions_left
    msgs = press(session, table, True)
    assert coins(game, 1) == (1, 2) and game.actions_left == before + 1 and session.effect_run is None
    assert said(msgs, "Blackbeard paga 1 doblon al Tesoro (tiene 1, el Tesoro 2)"), msgs


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_no_keeps_the_doubloons_and_the_actions(rig):
    session, table, game, fake, cfg = rig
    before = game.actions_left
    msgs = press(session, table, False)
    assert coins(game, 1) == (2, 1) and game.actions_left == before and session.effect_run is None
    assert not said(msgs, "doblon"), msgs


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_when_the_bot_hurts_blackbeard_the_chat_says_he_paid_a_doubloon(rig):
    from sparring.ai_medusa import Act
    from test_d3_table_effects import bot_turn
    session, table, game, fake, cfg = rig
    press(session, table, False)
    h, b = game.fighters["hellboy"], game.fighters["blackbeard"]
    spot = next(s for s in sorted(game.board.adj[b.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    h.pos = spot
    table.positions[cfg.nicknames["hellboy"]] = spot
    human_hand(table, game, "Intimidating Visage", "Show a Leg!")
    msgs = bot_attacks(session, table, game, "Service Pistol", "hellboy", "blackbeard", None)
    assert b.hp < 13 and coins(game, 1) == (1, 2)
    assert said(msgs, "Blackbeard paga 1 doblon al Tesoro"), msgs
    assert dial(session, cfg, table, "blackbeard") == b.hp


# ---------------------------------------------------------------- the bot's Blackbeard against the human

def bot_blackbeard(rig, monkeypatch, held=1, treasury=2):
    """The bot's Blackbeard next to Hellboy, the doubloons set and his own start-of-turn action not bought (that policy is tested in tests/test_blackbeard_ai.py)."""
    from sparring import ai_blackbeard
    monkeypatch.setattr(ai_blackbeard, "action_pays", lambda ai, game, req: False)
    session, table, game, fake, cfg = rig
    next_to_the_human(session, table, game, cfg)
    set_coins(game, 0, held, treasury)
    human_hand(table, game, "B.P.R.D. Training", "Excalibur", "Service Pistol", "Glimpse Of Hell", "Right Hand Of Doom")
    return session, table, game, fake, cfg


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_the_bots_brace_asks_the_human_for_the_ransom_and_names_the_damage(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch)
    msgs = bot_attacks(session, table, game, "A Brace of Primed Pistols", "blackbeard", "hellboy", None)
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.extra["ransom"] == 2 and req.extra["effect"]["what"] == "damage"
    assert req.extra["effect"]["amount"] == 3 and req.extra["treasury"] == 2
    text = " ".join(labels(session))
    assert "Pagar 2 del Tesoro" in text and "Que pase" in text, text
    assert said(msgs, "RESCATE") and said(msgs, "3 de dano"), msgs


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_paying_the_ransom_moves_two_doubloons_to_blackbeard_and_the_damage_is_ignored(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch)
    bot_attacks(session, table, game, "A Brace of Primed Pistols", "blackbeard", "hellboy", None)
    victim = session.effect_run.awaiting.extra["effect"]["fighters"][0]
    hp = game.fighters[victim].hp
    msgs = press(session, table, True)
    assert game.fighters[victim].hp == hp and coins(game, 0) == (3, 0) and session.effect_run is None
    assert said(msgs, "Blackbeard recibe 2 doblones del Tesoro (tiene 3, el Tesoro 0)"), msgs


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_declining_the_ransom_lets_the_three_damage_happen_on_the_dial(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch)
    bot_attacks(session, table, game, "A Brace of Primed Pistols", "blackbeard", "hellboy", None)
    victim = session.effect_run.awaiting.extra["effect"]["fighters"][0]
    hp = game.fighters[victim].hp
    press(session, table, False)
    assert game.fighters[victim].hp == hp - 3 and coins(game, 0) == (1, 2) and session.effect_run is None
    if victim == "hellboy":
        assert dial(session, cfg, table, victim) == hp - 3


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_with_one_doubloon_in_the_treasury_there_is_no_question_and_the_damage_happens(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch, held=2, treasury=1)
    msgs = bot_attacks(session, table, game, "A Brace of Primed Pistols", "blackbeard", "hellboy", None)
    assert session.effect_run is None and coins(game, 0) == (2, 1)
    assert not said(msgs, "RESCATE"), msgs
    assert any(game.fighters[f].hp < game.fighters[f].max_hp for f in ("hellboy", "lobster")), msgs


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_queen_annes_revenge_asks_the_human_how_many_doubloons_to_pay(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch, held=0, treasury=3)
    msgs = bot_attacks(session, table, game, "Queen Anne's Revenge", "blackbeard", "hellboy", None)
    req = session.effect_run.awaiting
    assert req.kind == "amount" and list(req.options) == [0, 1, 2, 3] and req.extra["queens"] == 2
    assert said(msgs, "QUEEN ANNE'S REVENGE") and said(msgs, "tiene 3"), msgs
    msgs = press(session, table, 2)
    assert coins(game, 0) == (2, 1) and session.effect_run is None
    assert said(msgs, "Blackbeard recibe 2 doblones del Tesoro"), msgs
    assert game.fighters["hellboy"].hp == 18 - (7 - 4)          # 7 less two doubloons of 2, and no defense


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_the_bot_blackbeard_taking_a_blow_pays_a_doubloon_and_says_so(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch, held=2, treasury=1)
    human_hand(table, game, "Excalibur", "Service Pistol", "Glimpse Of Hell")
    bot_defends_with_nothing(session, monkeypatch)
    human_attack(session, table, game, "hellboy", "blackbeard", "Excalibur")
    msgs = click(session, table, Event.REVEAL)
    assert game.fighters["blackbeard"].hp < 13 and coins(game, 0) == (1, 2)
    assert said(msgs, "Blackbeard paga 1 doblon al Tesoro (tiene 1, el Tesoro 2)"), msgs
