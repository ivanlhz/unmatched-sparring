"""George Washington on the table through the panel (FakeTTS, batch mode), both seats: the human's ESPIONAGE (the question at Reveal, the token
the bot takes off by discarding a random card, the supply said in chat), the human's cards (Gather Information, Undercover Agent, Recruit To
The Ring) and the bot's Washington (a ruse token laid on the table, the human asked on the panel whether to discard a random card to remove it,
the token taken away when the combat ends). The bot's side of the same cards is in tests/test_george_washington_effects.py.

His deck is sheet 187 and nobody else's (CardIDs 18700-18729). The three Culper Spies are Custom_Token in the save, which real TTS reports as
"Tile": nothing that reads or moves a piece filters on the type."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with, bot_defends_with_nothing, by_hand, human_scheme, labels, press, put_adjacent, rig, with_rig  # noqa: F401
from test_review9 import rt, run  # noqa: F401

SPIES = ["spy1", "spy2", "spy3"]
TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3
HAND = ("Excalibur", TRAINING, "Service Pistol", "Right Hand Of Doom")
BOT_HAND = ("Agent 711", "Sabotage", "Make A Stand", "Feint", "Lead Astray")


def supply(game, player):
    """(tokens in the supply, 1 while a token lies on the attack card)."""
    return game.fx.counter_value(player, "ruse_tokens", 4), game.fx.counter_value(player, "ruse", 0)


def attack(session, table, game, title, attacker="washington", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def bot_removes(session, monkeypatch, remove: bool):
    """The bot, the opponent of the human's Washington, answers the question of the ruse token."""
    monkeypatch.setattr(session.ai, "choose_effect", lambda g, req: [remove] if req.extra.get("washington") == "remove" else None)


def bot_ruse(session, monkeypatch, use: bool):
    """The bot decides whether to put a token on its attack."""
    monkeypatch.setattr(session.ai, "choose_effect", lambda g, req: [use] if req.extra.get("washington") == "use" else None)


def bot_attacks(session, table, game, title, fid, target):
    """The bot's `fid` attacks `target` with `title`; the human has not answered yet."""
    card = next(c for c in game.players[0].hand if c.title == title)
    return bot_turn(session, table, [Act("attack", fid=fid, target=target, card=card)])


def human_defends(session, table, game, title=None):
    if title:
        cid = card_ids(game, 1, title)[0]
        table.face_down = [{"id": cid, "guid": f"h{cid}"}]
        table.human_hand.remove(cid)
        table.human_count -= 1
    else:
        table.face_down = []
    return click(session, table, Event.REVEAL)


def hellboy_hp(game):
    return game.fighters["hellboy"].hp


# ---------------------------------------------------------------- the rig

@with_rig("hellboy", "george-washington", *HAND)
def test_the_rig_builds_with_washington_at_the_table(rig):
    session, table, game, fake, cfg = rig
    assert game.hero(1).name == "George Washington" and [f.fid for f in game.own(1)] == ["washington", *SPIES]
    assert supply(game, 1) == (4, 0)
    assert {cfg.nicknames[s] for s in SPIES} == {"Anna Strong", "Pompey Lamb", "Austin Roe"}


# ---------------------------------------------------------------- the human is Washington

@with_rig("hellboy", "george-washington", *HAND)
def test_a_card_with_a_ruse_effect_asks_at_reveal_before_the_bot_defends(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "washington", "hellboy")
    seen = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: seen.append(1))
    human_hand(table, game, "Agent 711", "Lead Astray", "Feint")
    msgs = attack(session, table, game, "Agent 711")
    assert said(msgs, "Agent 711: pones una ficha de engano en este ataque? Te quedan 4 fichas"), msgs
    assert session._paused()[0] == "predict" and labels(session) == ["Si", "No"]
    assert seen == [] and session.pending is not None and not session.pending.defended          # the bot has not chosen its defense yet
    assert supply(game, 1) == (4, 0)


@with_rig("hellboy", "george-washington", *HAND)
def test_yes_puts_the_token_on_the_attack_the_bot_keeps_its_hand_and_the_seven_damage_lands(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "washington", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    bot_removes(session, monkeypatch, False)
    human_hand(table, game, "Agent 711", "Lead Astray", "Feint")
    attack(session, table, game, "Agent 711")
    hand = len(game.players[0].hand)
    msgs = press(session, table, True)
    assert said(msgs, "ESPIONAGE: pones una ficha de engano en tu ataque. Coloca una junto a la carta."), msgs
    assert said(msgs, "la ficha de engano de George Washington se queda en Agent 711") and said(msgs, "te quedan 3 en tu reserva"), msgs
    assert said(msgs, "Agent 711: hellboy -7 PV"), msgs
    assert hellboy_hp(game) == 18 - 4 - 7 and supply(game, 1) == (3, 0) and session.pending is None
    assert len(game.players[0].hand) == hand


@with_rig("hellboy", "george-washington", *HAND)
def test_the_bot_discards_a_random_card_to_take_the_token_off_and_the_effect_is_lost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "washington", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    bot_removes(session, monkeypatch, True)
    human_hand(table, game, "Agent 711", "Lead Astray", "Feint")
    attack(session, table, game, "Agent 711")
    hand, pile = len(game.players[0].hand), len(game.players[0].discard)
    msgs = press(session, table, True)
    assert said(msgs, "el bot descarto una carta al azar para quitar tu ficha de engano: retirala de la carta"), msgs
    assert len(game.players[0].hand) == hand - 1 and len(game.players[0].discard) == pile + 1
    assert len(table.bot_discard) == pile + 1                                                  # the card reached the table's discard pile
    assert hellboy_hp(game) == 18 - 4 and supply(game, 1) == (3, 0)                            # the token is spent, the effect is gone
    assert not said(msgs, "hellboy -7 PV")


@with_rig("hellboy", "george-washington", *HAND)
def test_no_keeps_the_supply_and_the_bot_is_not_asked(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "washington", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    asked = []
    monkeypatch.setattr(session.ai, "choose_effect", lambda g, req: asked.append(req) or None)
    human_hand(table, game, "Agent 711", "Lead Astray", "Feint")
    attack(session, table, game, "Agent 711")
    msgs = press(session, table, False)
    assert said(msgs, "ESPIONAGE: sin ficha de engano en este ataque."), msgs
    assert supply(game, 1) == (4, 0) and hellboy_hp(game) == 18 - 4 and asked == []


@with_rig("hellboy", "george-washington", *HAND)
def test_a_card_without_a_ruse_effect_goes_straight_to_the_bot(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "washington", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Lead Astray", "Agent 711", "Feint")
    msgs = attack(session, table, game, "Lead Astray")
    assert not said(msgs, "ficha de engano") and session._paused() is not None                    # Lead Astray's move is asked, the token is not
    assert session._paused()[0] != "predict" and supply(game, 1) == (4, 0)


@with_rig("hellboy", "george-washington", *HAND)
def test_with_no_token_left_nothing_is_asked(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(1, "ruse_tokens", 0)
    put_adjacent(game, table, cfg, "washington", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Agent 711", "Lead Astray", "Feint")
    msgs = attack(session, table, game, "Agent 711")
    assert not said(msgs, "ficha de engano") and hellboy_hp(game) == 18 - 4


@with_rig("hellboy", "george-washington", *HAND)
def test_the_save_taken_at_the_question_resumes_with_the_buttons_up(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "washington", "hellboy")
    human_hand(table, game, "Agent 711", "Lead Astray", "Feint")
    attack(session, table, game, "Agent 711")
    saved = session.to_dict()
    assert saved["pending"]["predict"]["key"] == "ruse"
    session.load_dict(saved)
    assert session._paused()[0] == "predict" and labels(session) == ["Si", "No"]


# ---------------------------------------------------------------- the human's other cards

@with_rig("hellboy", "george-washington", *HAND)
def test_gather_information_draws_three_and_leaves_every_move_to_the_human(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Gather Information", "Lead Astray", "Feint")
    msgs = human_scheme(session, table, game, "Gather Information")
    assert said(msgs, "Aplico Gather Information: robas 3"), msgs
    for fid in ["washington", *SPIES]:
        assert said(msgs, f"mueve a {fid} hasta 3 casillas (puede atravesar rivales)"), msgs
    assert game.actions_left == 1 and session.effect_run is None


@with_rig("hellboy", "george-washington", *HAND)
def test_recruit_to_the_ring_won_tells_the_human_to_put_the_spy_on_any_space(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "washington", "hellboy")
    game.defeat(game.fighters["spy2"])
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Recruit To The Ring", "Lead Astray", "Feint")
    msgs = attack(session, table, game, "Recruit To The Ring")
    assert said(msgs, "pon a Pompey Lamb en el tablero (cualquier casilla) con 1 PV"), msgs      # the Spy is named by its miniature
    assert game.fighters["spy2"].alive and game.fighters["spy2"].hp == 1


@with_rig("hellboy", "george-washington", *HAND)
def test_recruit_to_the_ring_lost_brings_the_spy_back_next_to_washington(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "washington", "hellboy")
    game.defeat(game.fighters["spy2"])
    bot_defends_with(session, game, TRAINING, monkeypatch)                                      # a 3 against the 2: the combat is lost
    human_hand(table, game, "Recruit To The Ring", "Lead Astray", "Feint")
    msgs = attack(session, table, game, "Recruit To The Ring")
    assert said(msgs, "pon a Pompey Lamb en el tablero (una casilla adyacente) con 1 PV"), msgs
    assert game.fighters["spy2"].alive and game.fighters["spy2"].pos in game.board.adj[game.fighters["washington"].pos]


# ---------------------------------------------------------------- the bot is Washington

@with_rig("george-washington", "hellboy", *BOT_HAND)
def test_the_bots_token_is_laid_on_the_table_and_the_human_is_asked_whether_to_discard_a_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_ruse(session, monkeypatch, True)
    put_adjacent(game, table, cfg, "washington", "hellboy")
    human_hand(table, game, "Right Hand Of Doom", TRAINING, "Service Pistol", "Excalibur")
    bot_attacks(session, table, game, "Agent 711", "washington", "hellboy")
    assert supply(game, 0) == (3, 1) and table.tokens == ["tok1"] and session.token_copies == {"ruse": ["tok1"]}
    said_now = " ".join(session.messages)
    assert "George Washington (bot) pone una ficha de engano en su ataque, Agent 711: le quedan 3 en su reserva" in said_now, session.messages
    assert session._paused()[0] == "parked" and labels(session) == ["Si", "No"]
    assert session.effect_run.awaiting.player == 1 and session.pending.kind == "bot_attacks"
    assert "hay una ficha de engano en el ataque. Descartas 1 carta al azar de tu mano" in said_now


@with_rig("george-washington", "hellboy", *BOT_HAND)
def test_while_the_question_is_open_no_other_button_works(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_ruse(session, monkeypatch, True)
    put_adjacent(game, table, cfg, "washington", "hellboy")
    human_hand(table, game, "Right Hand Of Doom", TRAINING, "Service Pistol", "Excalibur")
    bot_attacks(session, table, game, "Agent 711", "washington", "hellboy")
    msgs = human_defends(session, table, game, TRAINING)
    assert session._paused() is not None and hellboy_hp(game) == 18 and session.pending is not None, msgs


@with_rig("george-washington", "hellboy", *BOT_HAND)
def test_declining_the_discard_lets_the_token_stay_the_seven_damage_lands_and_the_token_leaves_the_table(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_ruse(session, monkeypatch, True)
    put_adjacent(game, table, cfg, "washington", "hellboy")
    human_hand(table, game, "Right Hand Of Doom", TRAINING, "Service Pistol", "Excalibur")
    bot_attacks(session, table, game, "Agent 711", "washington", "hellboy")
    press(session, table, False)
    assert session.pending is not None and session.pending_discard is None
    msgs = human_defends(session, table, game, TRAINING)
    assert said(msgs, "Aplicado: Agent 711: hellboy -7 PV"), msgs                               # 4 against 3: the bot wins, the 7 lands
    assert hellboy_hp(game) == 18 - 1 - 7 and supply(game, 0) == (3, 0)
    assert table.tokens == [] and session.token_copies == {"ruse": []}                          # the copy left the table with the combat
    assert said(msgs, "George Washington (bot) gasta 1 ficha de ruse"), msgs


@with_rig("george-washington", "hellboy", *BOT_HAND)
def test_accepting_the_discard_tells_which_card_and_the_token_effect_is_lost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_ruse(session, monkeypatch, True)
    put_adjacent(game, table, cfg, "washington", "hellboy")
    human_hand(table, game, "Right Hand Of Doom", TRAINING, "Service Pistol", "Excalibur")
    bot_attacks(session, table, game, "Agent 711", "washington", "hellboy")
    msgs = press(session, table, True)
    assert said(msgs, "Descarta 1 carta(s) (efecto, al azar: la carta"), msgs
    assert session.pending_discard is not None and session.pending is not None
    msgs = human_defends(session, table, game, TRAINING)
    assert said(msgs, "Aplicado: Agent 711: sin efecto"), msgs
    assert hellboy_hp(game) == 18 - 1 and supply(game, 0) == (3, 0) and table.tokens == []


@with_rig("george-washington", "hellboy", *BOT_HAND)
def test_a_bot_attack_with_no_token_asks_the_human_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_ruse(session, monkeypatch, False)
    put_adjacent(game, table, cfg, "washington", "hellboy")
    human_hand(table, game, "Right Hand Of Doom", TRAINING, "Service Pistol", "Excalibur")
    bot_attacks(session, table, game, "Agent 711", "washington", "hellboy")
    assert session._paused() is None and supply(game, 0) == (4, 0) and table.tokens == []
    msgs = human_defends(session, table, game, TRAINING)
    assert hellboy_hp(game) == 18 - 1 and not said(msgs, "-7 PV")


@with_rig("george-washington", "hellboy", *BOT_HAND)
def test_a_bot_card_without_a_ruse_effect_asks_the_human_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    asked = []
    monkeypatch.setattr(session.ai, "choose_effect", lambda g, req: asked.append(req) or None)
    put_adjacent(game, table, cfg, "washington", "hellboy")
    human_hand(table, game, "Right Hand Of Doom", TRAINING, "Service Pistol", "Excalibur")
    bot_attacks(session, table, game, "Make A Stand", "washington", "hellboy")
    assert session._paused() is None and asked == [] and supply(game, 0) == (4, 0)


@with_rig("george-washington", "hellboy", *BOT_HAND)
def test_the_save_taken_while_the_question_is_open_resumes_with_the_buttons_up(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_ruse(session, monkeypatch, True)
    put_adjacent(game, table, cfg, "washington", "hellboy")
    human_hand(table, game, "Right Hand Of Doom", TRAINING, "Service Pistol", "Excalibur")
    bot_attacks(session, table, game, "Agent 711", "washington", "hellboy")
    saved = session.to_dict()
    session.load_dict(saved)
    assert session._paused()[0] == "parked" and labels(session) == ["Si", "No"]
    assert supply(game, 0) == (3, 1) and session.pending.declared["counters"] == {"ruse_tokens": 3, "ruse": 1}


# ---------------------------------------------------------------- Undercover Agent, played by the human

@with_rig("hellboy", "george-washington", *HAND)
def test_undercover_agent_swaps_the_humans_miniatures_by_hand_and_the_spy_takes_the_blow(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "washington")
    put_adjacent(game, table, cfg, "spy1", "washington")
    human_hand(table, game, "Undercover Agent", "Lead Astray", "Feint")
    bot_card = next(c for c in game.players[0].hand if c.title == "Excalibur")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="washington", card=bot_card)])
    msgs = human_defends(session, table, game, "Undercover Agent")
    paused = session._paused()
    assert paused is not None and paused[2].awaiting.kind == "optional", msgs
    msgs = press(session, table, True)
    if session._paused() is not None:
        msgs += press(session, table, session.effect_run.awaiting.options[0])
    assert said(msgs, "intercambia las casillas de washington y spy1"), msgs
    assert not game.fighters["spy1"].alive and game.fighters["washington"].hp == 14


# ---------------------------------------------------------------- Sympathetic Stain, played by a Spy

@with_rig("hellboy", "george-washington", *HAND)
def test_sympathetic_stain_with_a_spy_next_to_a_rival_asks_which_card_of_the_bots_hand_to_discard(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "spy1", "hellboy")
    game.fx.set_counter(1, "ruse_tokens", 2)
    human_hand(table, game, "Sympathetic Stain", "Lead Astray", "Feint")
    msgs = human_scheme(session, table, game, "Sympathetic Stain")
    assert said(msgs, "Detecto Sympathetic Stain: la carta te pide una eleccion."), msgs
    req = session.effect_run.awaiting
    assert req.kind == "cards" and req.extra["purpose"] == "discard" and req.extra["of"] == 0 and req.player == 1
    assert game.fighters["spy1"].alive and supply(game, 1) == (2, 0)                        # the token comes when the discard is done


@with_rig("hellboy", "george-washington", *HAND)
def test_sympathetic_stain_with_no_spy_next_to_a_rival_only_looks_and_gives_no_token(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(1, "ruse_tokens", 2)
    for spy in SPIES:
        game.fighters[spy].pos = 40 + SPIES.index(spy)
        table.positions[cfg.nicknames[spy]] = 40 + SPIES.index(spy)
    human_hand(table, game, "Sympathetic Stain", "Lead Astray", "Feint")
    msgs = human_scheme(session, table, game, "Sympathetic Stain")
    assert not said(msgs, "te pide una eleccion"), msgs
    assert session._paused() is None or session._paused()[2].awaiting.kind != "cards"
    assert supply(game, 1) == (2, 0) and len(game.players[0].hand) == 4
