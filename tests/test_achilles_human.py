"""Achilles played BY THE HUMAN through the panel (FakeTTS, batch mode). The bot's side of the same cards is in
tests/test_achilles_effects.py.

His deck is sheet 176 like Medusa's, the turtles' and the other decks of the range: every id the table reports is resolved against the
human's deck."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with_nothing, by_hand, human_scheme, labels, press, put_adjacent, rig, with_rig  # noqa: F401

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def attack(session, table, game, attacker, title, target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def bot_attacks(session, table, game, title, target, human_title=None):
    """The bot's Hellboy attacks `target` with `title`; the human answers with `human_title` face down (None: no card); the reveal resolves it."""
    card = next(c for c in game.players[0].hand if c.title == title)
    bot_turn(session, table, [Act("attack", fid="hellboy", target=target, card=card)])
    if human_title is None:
        table.face_down = []
    else:
        cid = card_ids(game, 1, human_title)[0]
        table.face_down = [{"id": cid, "guid": f"h{cid}"}]
        table.human_hand.remove(cid)
        table.human_count -= 1
    return click(session, table, Event.REVEAL)


def dial(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


# ---------------------------------------------------------------- the ability

@with_rig("hellboy", "achilles", "Excalibur", TRAINING)
def test_when_the_bot_defeats_patroclus_the_engine_names_two_random_positions_of_your_hand(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "patroclus")
    game.fighters["patroclus"].hp = 1
    human_hand(table, game, "Skirmish", "Feint", "Feint", "Feint", "Wily Fighting")
    msgs = bot_attacks(session, table, game, "Excalibur", "patroclus")
    assert not game.fighters["patroclus"].alive
    assert said(msgs, "al azar: las cartas") and said(msgs, "Patroclus cae"), msgs


@with_rig("hellboy", "achilles", "Excalibur", TRAINING)
def test_your_attacks_get_plus_two_after_patroclus_fell(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    game.fighters["patroclus"].hp = 0
    game.fighters["patroclus"].alive = False
    game.fighters["patroclus"].pos = None
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Brothers In Arms", "Feint")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "achilles", "Brothers In Arms")
    assert game.fighters["hellboy"].hp == hp - 6 and said(msgs, "VENGEANCE (+2)") and said(msgs, "robas 1"), msgs


@with_rig("hellboy", "achilles", "Excalibur", TRAINING)
def test_under_achilles_helm_yes_swaps_your_miniatures_and_patroclus_takes_the_blow(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    patroclus, achilles = game.fighters["patroclus"], game.fighters["achilles"]
    far = next(s for s in sorted(game.board.spaces, reverse=True) if all(f.pos != s for f in game.fighters.values() if f.alive))
    patroclus.pos = far
    table.positions[cfg.nicknames["patroclus"]] = far
    human_hand(table, game, "Under Achilles' Helm", "Feint")
    msgs = bot_attacks(session, table, game, "Excalibur", "achilles", "Under Achilles' Helm")
    assert session.effect_run.awaiting.kind == "optional", msgs
    msgs = press(session, table, True)
    assert said(msgs, "intercambia las casillas de achilles y patroclus"), msgs
    assert patroclus.hp == 6 - max(0, 6 - 2) and achilles.hp == 18


@with_rig("hellboy", "achilles", "Excalibur", TRAINING)
def test_under_achilles_helm_no_leaves_achilles_to_take_it(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    human_hand(table, game, "Under Achilles' Helm", "Feint")
    bot_attacks(session, table, game, "Excalibur", "achilles", "Under Achilles' Helm")
    press(session, table, False)
    assert game.fighters["achilles"].hp == 18 - 4 and game.fighters["patroclus"].hp == 6


@with_rig("hellboy", "achilles", TRAINING)
def test_the_day_of_your_doom_yes_costs_patroclus_two_and_hits_for_five(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "patroclus")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "The Day of Your Doom", "Feint")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "patroclus", "The Day of Your Doom")
    assert session.effect_run.awaiting.kind == "optional", msgs
    press(session, table, True)
    assert game.fighters["patroclus"].hp == 4 and game.fighters["hellboy"].hp == hp - 5
    assert dial(session, cfg, table, "patroclus") == 4


@with_rig("hellboy", "achilles", TRAINING)
def test_the_day_of_your_doom_no_is_a_plain_three(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "patroclus")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "The Day of Your Doom", "Feint")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "patroclus", "The Day of Your Doom")
    press(session, table, False)
    assert game.fighters["patroclus"].hp == 6 and game.fighters["hellboy"].hp == hp - 3


@with_rig("hellboy", "achilles", TRAINING)
def test_spear_throw_hits_the_opposing_fighter_in_achilles_zone(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    human_hand(table, game, "Spear Throw", "Feint")
    hp = game.fighters["hellboy"].hp
    msgs = human_scheme(session, table, game, "Spear Throw")
    assert game.fighters["hellboy"].hp == hp - 2 and session.effect_run is None, msgs


@with_rig("hellboy", "achilles", TRAINING)
def test_battle_hardened_takes_the_only_card_of_your_pile_back_and_tells_you_to_pick_it_up(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Battle Hardened", "Feint")
    gone = card_ids(game, 1, "Skirmish")[0]
    c = next(c for c in game.players[1].full_set if c.card_id == gone)
    game.players[1].hand.remove(c) if c in game.players[1].hand else game.players[1].deck.remove(c)
    game.players[1].discard.append(c)
    table.human_discard.append(gone)
    msgs = attack(session, table, game, "achilles", "Battle Hardened")
    assert said(msgs, "Recoge Skirmish de tu descarte a tu mano"), msgs
    assert gone in [c.card_id for c in game.players[1].hand] and "Battle Hardened" not in [c.title for c in game.players[1].hand]
