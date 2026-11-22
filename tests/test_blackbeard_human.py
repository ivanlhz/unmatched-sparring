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


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_avast_ye_names_the_position_of_the_random_card_before_the_ransom(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch, held=2, treasury=1)
    msgs = bot_attacks(session, table, game, "Avast Ye!", "blackbeard", "hellboy", None)
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.extra["ransom"] == 1 and req.extra["effect"]["what"] == "random_discard"
    assert "which" in req.extra["effect"] and "contando desde la izquierda" in req.extra["effect"]["which"]
    assert said(msgs, "RESCATE") and said(msgs, "al azar"), msgs


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_avast_ye_paying_keeps_the_card_and_the_hand_untouched(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch, held=2, treasury=1)
    bot_attacks(session, table, game, "Avast Ye!", "blackbeard", "hellboy", None)
    hand = len(table.human_hand)
    msgs = press(session, table, True)
    assert coins(game, 0) == (3, 0) and len(table.human_hand) == hand and not game.players[1].discard
    assert said(msgs, "Blackbeard recibe 1 doblon del Tesoro (tiene 3, el Tesoro 0)"), msgs


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_avast_ye_declining_owes_the_named_card_to_the_discard_pile(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch, held=2, treasury=1)
    bot_attacks(session, table, game, "Avast Ye!", "blackbeard", "hellboy", None)
    msgs = press(session, table, False)
    assert coins(game, 0) == (2, 1)
    assert said(msgs, "Descarta 1 carta(s) (Avast Ye!, al azar: la carta ") and said(msgs, "contando desde la izquierda"), msgs
    assert said(msgs, "DESCARTE AL AZAR"), msgs
    assert session.pending_discard == {"n": 1, "baseline": 0, "kind": "cards", "hand": True}


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_fearsome_and_calculating_reads_the_hand_and_the_ransom_names_the_card(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch, held=2, treasury=1)
    msgs = bot_attacks(session, table, game, "Fearsome and Calculating", "blackbeard", "hellboy", None)
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.extra["ransom"] == 1 and req.extra["effect"]["what"] == "discard"
    named, = req.extra["effect"]["cards"]
    title = next(c.title for c in game.players[1].full_set if c.card_id == named)
    assert said(msgs, f"descartas {title}"), msgs
    msgs = press(session, table, False)
    assert said(msgs, f"Pon {title} de tu mano en tu descarte"), msgs
    assert coins(game, 0) == (2, 1)


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_fearsome_and_calculating_paying_keeps_the_named_card_in_the_hand(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch, held=2, treasury=1)
    bot_attacks(session, table, game, "Fearsome and Calculating", "blackbeard", "hellboy", None)
    msgs = press(session, table, True)
    assert coins(game, 0) == (3, 0) and session.effect_run is None and not game.players[1].discard, msgs


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_parley_asks_the_human_two_doubloons_to_keep_the_effects_of_their_card(rig, monkeypatch):
    session, table, game, fake, cfg = bot_blackbeard(rig, monkeypatch, held=1, treasury=2)
    human_hand(table, game, "Excalibur", "B.P.R.D. Training", "Service Pistol", "Glimpse Of Hell", "Right Hand Of Doom")
    bot_attacks(session, table, game, "Parley", "blackbeard", "hellboy", "B.P.R.D. Training")
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.extra["ransom"] == 2 and req.extra["effect"]["what"] == "cancel"
    press(session, table, True)
    assert coins(game, 0) == (3, 0)


# ---------------------------------------------------------------- the human's own cards

def own_turn(rig, monkeypatch, held=1, treasury=2):
    """The human's Blackbeard next to Hellboy, the start-of-turn question declined, the bot defending with nothing."""
    session, table, game, fake, cfg = rig
    press(session, table, False)
    put_adjacent(game, table, cfg, "blackbeard", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    set_coins(game, 1, held, treasury)
    return rig


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_humans_show_a_leg_brings_a_defeated_sea_dog_back_and_asks_to_place_it(rig, monkeypatch):
    session, table, game, fake, cfg = own_turn(rig, monkeypatch)
    human_hand(table, game, "Show a Leg!", "Give No Quarter")
    game.defeat(game.fighters["seadog2"])
    table.positions.pop(cfg.nicknames["seadog2"], None)
    human_attack(session, table, game, "blackbeard", "hellboy", "Show a Leg!")
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "seadog2 vuelve al tablero") and said(msgs, "pon a Caesar en el tablero (la zona de tu heroe"), msgs
    assert game.placing == {"seadog2"} and game.fighters["seadog2"].alive and game.fighters["seadog2"].hp == 1


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_bot_ransoms_the_humans_brace_and_the_chat_says_it_in_doubloons_not_cards(rig, monkeypatch):
    from sparring import ai_blackbeard
    session, table, game, fake, cfg = own_turn(rig, monkeypatch)
    monkeypatch.setattr(ai_blackbeard, "ransom_pays", lambda ai, g, req: True)
    human_hand(table, game, "A Brace of Primed Pistols", "Give No Quarter")
    human_attack(session, table, game, "blackbeard", "hellboy", "A Brace of Primed Pistols")
    msgs = click(session, table, Event.REVEAL)
    assert coins(game, 1) == (3, 0) and game.fighters["lobster"].hp == 6 and game.fighters["hellboy"].hp == 18 - 2, msgs
    assert said(msgs, "Blackbeard recibe 2 doblones del Tesoro (tiene 3, el Tesoro 0)"), msgs
    assert not said(msgs, "paga 0 cartas") and not said(msgs, "0 carta"), msgs


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_bot_declining_the_ransom_lets_the_humans_brace_hurt_the_chosen_fighter(rig, monkeypatch):
    from sparring import ai_blackbeard
    session, table, game, fake, cfg = own_turn(rig, monkeypatch)
    monkeypatch.setattr(ai_blackbeard, "ransom_pays", lambda ai, g, req: False)
    human_hand(table, game, "A Brace of Primed Pistols", "Give No Quarter")
    human_attack(session, table, game, "blackbeard", "hellboy", "A Brace of Primed Pistols")
    msgs = click(session, table, Event.REVEAL)
    assert coins(game, 1) == (1, 2)
    assert game.fighters["hellboy"].hp == 18 - 2 - 3 or game.fighters["lobster"].hp == 6 - 3, msgs
    assert not said(msgs, "paga 0 cartas"), msgs


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_scourge_with_no_sea_dog_defeated_asks_whether_to_move_one_and_says_what_it_is_for(rig, monkeypatch):
    from sparring import ai_blackbeard
    from test_e2_human_cards import human_scheme
    session, table, game, fake, cfg = own_turn(rig, monkeypatch, held=0, treasury=3)
    monkeypatch.setattr(ai_blackbeard, "ransom_pays", lambda ai, g, req: False)
    human_hand(table, game, "Scourge of the Seven Seas", "Give No Quarter")
    msgs = human_scheme(session, table, game, "Scourge of the Seven Seas")
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.extra == {"reposition": "any"}
    assert said(msgs, "no hay ningun Sea Dog derrotado") and said(msgs, "cualquier casilla vacia"), msgs
    assert game.hero(1).hp == 13 and coins(game, 1) == (0, 3)


@with_rig("blackbeard", "hellboy", *BOT_HAND)
def test_the_bot_buys_the_action_at_the_start_of_its_turn_and_the_chat_says_it(rig):
    from test_d3_table_effects import bot_turn
    session, table, game, fake, cfg = rig
    set_coins(game, 0, 2, 1)
    msgs = bot_turn(session, table, [])
    assert coins(game, 0) == (1, 2)
    assert said(msgs, "Blackbeard paga 1 doblon al Tesoro (tiene 1, el Tesoro 2)"), msgs
    assert not any("take_token_copy" in script for script in table.scripts), "the Treasury tile is not cloned for each doubloon in it"


@with_rig("blackbeard", "hellboy", "Intimidating Visage", "Show a Leg!")
def test_the_bot_keeps_its_doubloons_when_it_has_nothing_to_spend_the_action_on(rig):
    from test_d3_table_effects import bot_turn
    session, table, game, fake, cfg = rig
    set_coins(game, 0, 2, 1)
    msgs = bot_turn(session, table, [])
    assert coins(game, 0) == (2, 1) and not said(msgs, "doblon"), msgs


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_humans_avast_ye_makes_the_bot_discard_a_random_card_unless_it_pays(rig, monkeypatch):
    from sparring import ai_blackbeard
    session, table, game, fake, cfg = own_turn(rig, monkeypatch, held=2, treasury=1)
    monkeypatch.setattr(ai_blackbeard, "ransom_pays", lambda ai, g, req: False)
    human_hand(table, game, "Avast Ye!", "Give No Quarter")
    bot_hand = len(game.players[0].hand)
    human_attack(session, table, game, "blackbeard", "hellboy", "Avast Ye!")
    msgs = click(session, table, Event.REVEAL)
    assert len(game.players[0].hand) == bot_hand - 1 and len(game.players[0].discard) == 1, msgs
    assert coins(game, 1) == (2, 1)


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_humans_avast_ye_the_bot_may_pay_the_doubloon_to_keep_its_card(rig, monkeypatch):
    from sparring import ai_blackbeard
    session, table, game, fake, cfg = own_turn(rig, monkeypatch, held=2, treasury=1)
    monkeypatch.setattr(ai_blackbeard, "ransom_pays", lambda ai, g, req: True)
    human_hand(table, game, "Avast Ye!", "Give No Quarter")
    bot_hand = len(game.players[0].hand)
    human_attack(session, table, game, "blackbeard", "hellboy", "Avast Ye!")
    msgs = click(session, table, Event.REVEAL)
    assert len(game.players[0].hand) == bot_hand and coins(game, 1) == (3, 0), msgs
    assert said(msgs, "Blackbeard recibe 1 doblon del Tesoro (tiene 3, el Tesoro 0)"), msgs


def humans_fearsome(rig, monkeypatch, bot_pays):
    """The human's Fearsome and Calculating: the bot shows its hand, the human chooses a card (the first button), then the bot decides on the ransom."""
    from sparring import ai_blackbeard
    session, table, game, fake, cfg = own_turn(rig, monkeypatch, held=2, treasury=1)
    monkeypatch.setattr(ai_blackbeard, "ransom_pays", lambda ai, g, req: bot_pays)
    human_hand(table, game, "Fearsome and Calculating", "Give No Quarter")
    human_attack(session, table, game, "blackbeard", "hellboy", "Fearsome and Calculating")
    click(session, table, Event.REVEAL)
    assert session.look["mode"] == "pick"
    return session, table, game, click(session, table, Event.CHOICE, {"i": 1})


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_humans_fearsome_and_calculating_discards_the_chosen_card_unless_the_bot_pays(rig, monkeypatch):
    session, table, game, msgs = humans_fearsome(rig, monkeypatch, False)
    assert [c.title for c in game.players[0].discard] == ["Excalibur"] and coins(game, 1) == (2, 1)
    assert said(msgs, "El bot descarta Excalibur"), msgs


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_humans_fearsome_and_calculating_the_bot_may_pay_a_doubloon_to_keep_the_chosen_card(rig, monkeypatch):
    session, table, game, msgs = humans_fearsome(rig, monkeypatch, True)
    assert game.players[0].discard == [] and len(game.players[0].hand) == 5 and coins(game, 1) == (3, 0)
    assert said(msgs, "Blackbeard recibe 1 doblon del Tesoro (tiene 3, el Tesoro 0)"), msgs


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_humans_queen_annes_revenge_the_bot_pays_what_its_policy_says_and_the_value_follows(rig, monkeypatch):
    from sparring import ai_blackbeard
    session, table, game, fake, cfg = own_turn(rig, monkeypatch, held=0, treasury=3)
    monkeypatch.setattr(ai_blackbeard, "queens_amount", lambda ai, g, req: 2)
    human_hand(table, game, "Queen Anne's Revenge", "Give No Quarter")
    human_attack(session, table, game, "blackbeard", "hellboy", "Queen Anne's Revenge")
    msgs = click(session, table, Event.REVEAL)
    assert coins(game, 1) == (2, 1) and game.fighters["hellboy"].hp == 18 - (7 - 4), msgs
    assert said(msgs, "Blackbeard recibe 2 doblones del Tesoro (tiene 2, el Tesoro 1)"), msgs


@with_rig("hellboy", "blackbeard", *HELLBOY_HAND)
def test_the_humans_plunder_steals_a_doubloon_and_says_so(rig, monkeypatch):
    from test_e2_human_cards import human_scheme
    session, table, game, fake, cfg = own_turn(rig, monkeypatch, held=2, treasury=1)
    human_hand(table, game, "Plunder", "Give No Quarter")
    msgs = human_scheme(session, table, game, "Plunder")
    assert coins(game, 1) == (3, 0), msgs
    assert said(msgs, "Blackbeard recibe 1 doblon del Tesoro (tiene 3, el Tesoro 0)"), msgs
