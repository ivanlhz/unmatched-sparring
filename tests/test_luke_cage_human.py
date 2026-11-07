"""Luke Cage played BY THE HUMAN through the panel (FakeTTS, batch mode): his ability on the dial the bot moves, Power Man and
Pushback (the bot's piece goes where the human says, by hand), Got My Back? (Yes / No, the swap of the human's miniatures), Where's
My Money? (a placement by hand next to the nearest foe), Still Standing (two cards chosen from the human's discard pile) and the
choices surviving a resume. The bot's side of the same cards is in tests/test_luke_cage_effects.py.

His deck is sheet 176 like Medusa's, the turtles', Doctor Strange's and Bigfoot's: every id the table reports is resolved against the
human's deck."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with_nothing, by_hand, human_scheme, press, put_adjacent, rig, with_rig  # noqa: F401

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def attack(session, table, game, attacker, title, target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def bot_attacks(session, table, game, title, target, human_title):
    """The bot's Hellboy attacks `target` with `title`; the human answers with `human_title` face down; the reveal resolves it."""
    card = next(c for c in game.players[0].hand if c.title == title)
    bot_turn(session, table, [Act("attack", fid="hellboy", target=target, card=card)])
    cid = card_ids(game, 1, human_title)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    return click(session, table, Event.REVEAL)


def dial(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


# ---------------------------------------------------------------- the ability

@with_rig("hellboy", "luke-cage", "Excalibur", TRAINING)
def test_the_bots_blow_on_your_luke_is_two_lighter_and_the_dial_follows(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "luke")
    human_hand(table, game, "Sweet Christmas!", "Regroup")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="luke", card=next(c for c in game.players[0].hand if c.title == "Excalibur"))])
    table.face_down = []
    msgs = click(session, table, Event.REVEAL)
    assert game.fighters["luke"].hp == 13 - (6 - 2) and said(msgs, "luke recibe 2 de dano de combate menos"), msgs
    assert dial(session, cfg, table, "luke") == 13 - 4


# ---------------------------------------------------------------- Power Man

@with_rig("hellboy", "luke-cage", "Service Pistol", TRAINING)
def test_power_man_moves_the_bots_piece_where_you_say_and_hurts_it_and_the_fighter_it_crossed(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "luke")
    hellboy, lobster = game.fighters["hellboy"], game.fighters["lobster"]
    human_hand(table, game, "Power Man", "Regroup")
    start = hellboy.pos
    crossed = next(s for s in sorted(game.board.adj[start]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    lobster.pos = crossed
    table.positions[cfg.nicknames["lobster"]] = crossed
    beyond = next(s for s in sorted(game.board.adj[crossed]) if s != start and all(f.pos != s for f in game.fighters.values() if f.alive)
                  and 0 < game.board.distance(start, s) <= 3)
    hp = (hellboy.hp, lobster.hp)
    msgs = bot_attacks(session, table, game, "Service Pistol", "luke", "Power Man")
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "hellboy" and req.extra["steps"] == 3 and beyond in req.options, msgs
    msgs = by_hand(session, table, cfg, "hellboy", beyond)
    assert hellboy.pos == beyond and (hellboy.hp, lobster.hp) == (hp[0] - 1, hp[1] - 1)
    assert game.fighters["luke"].hp == 13 - (5 - 2 - 2) and session.pending is None      # a 5 against his 2 and his ability


# ---------------------------------------------------------------- Got My Back?

def misty_defends(session, table, game, cfg, answer):
    put_adjacent(game, table, cfg, "hellboy", "misty")
    luke = game.fighters["luke"]
    far = next(s for s in sorted(game.board.spaces, reverse=True) if all(f.pos != s for f in game.fighters.values() if f.alive))
    luke.pos = far
    table.positions[cfg.nicknames["luke"]] = far
    human_hand(table, game, "Got My Back?", "Regroup")
    msgs = bot_attacks(session, table, game, "Service Pistol", "misty", "Got My Back?")
    req = session.effect_run.awaiting
    assert req.kind == "optional", msgs
    return press(session, table, answer)


@with_rig("hellboy", "luke-cage", "Service Pistol", TRAINING)
def test_got_my_back_yes_swaps_your_miniatures_and_luke_takes_the_blow(rig):
    session, table, game, fake, cfg = rig
    misty, luke = game.fighters["misty"], game.fighters["luke"]
    msgs = misty_defends(session, table, game, cfg, True)
    assert said(msgs, "intercambia las casillas de misty y luke"), msgs                  # the two miniatures are yours
    assert game.fighters["luke"].hp == 13 - max(0, 5 - 1 - 2) and misty.hp == 6
    assert said(msgs, "luke defiende con Got My Back?") or said(msgs, "Luke Cage defiende con Got My Back?"), msgs


@with_rig("hellboy", "luke-cage", "Service Pistol", TRAINING)
def test_got_my_back_no_leaves_misty_to_take_it(rig):
    session, table, game, fake, cfg = rig
    misty, luke = game.fighters["misty"], game.fighters["luke"]
    misty_defends(session, table, game, cfg, False)
    assert misty.hp == 6 - (5 - 1) and luke.hp == 13


# ---------------------------------------------------------------- Where's My Money?

@with_rig("hellboy", "luke-cage", TRAINING)
def test_wheres_my_money_asks_for_a_placement_next_to_the_nearest_foe_and_gains_the_action(rig):
    session, table, game, fake, cfg = rig
    luke, hellboy = game.fighters["luke"], game.fighters["hellboy"]
    far = max(game.board.spaces, key=lambda s: game.board.distance(hellboy.pos, s))
    if all(f.pos != far for f in game.fighters.values() if f.alive):
        luke.pos = far
        table.positions[cfg.nicknames["luke"]] = far
    human_hand(table, game, "Where's My Money?", "Regroup")
    actions = game.actions_left
    msgs = human_scheme(session, table, game, "Where's My Money?")
    assert said(msgs, "coloca a luke en una casilla junto al rival mas cercano"), msgs        # your miniature: you place it by hand
    assert session.effect_run is None and "luke" in game.placing
    assert game.actions_left == actions and said(msgs, "ganas 1 accion"), msgs               # the scheme spent one, the card gave one back


# ---------------------------------------------------------------- Still Standing and the resume

@with_rig("hellboy", "luke-cage", TRAINING)
def test_still_standing_asks_for_two_cards_of_your_discard_pile_and_survives_a_resume(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "luke")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Still Standing", "Regroup", "Regroup", "Regroup")
    junk = card_ids(game, 1, "Regroup", "Regroup", "Sweet Christmas!")
    for i in junk:                                                  # two cards already in the human's discard pile, here and on the table
        c = next(c for c in game.players[1].full_set if c.card_id == i)
        game.players[1].hand.remove(c) if c in game.players[1].hand else game.players[1].deck.remove(c)
        game.players[1].discard.append(c)
        table.human_discard.append(i)
    attack(session, table, game, "luke", "Still Standing")
    req = session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting
    assert req.kind == "cards" and req.min == 2 and req.max == 2 and set(junk) <= set(req.options)
    saved = session.to_dict()
    session._restore(saved)                                         # what --resume does
    req = session._paused()[2].awaiting if session.effect_run is None else session.effect_run.awaiting
    assert req.kind == "cards" and req.min == 2
    table.human_discard.remove(junk[0])                             # you take the two cards out of your discard pile and shuffle them in yourself
    table.human_discard.remove(junk[1])
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    deck = [c.card_id for c in game.players[1].deck]
    assert junk[0] in deck and junk[1] in deck and junk[2] in [c.card_id for c in game.players[1].discard], msgs
    assert session.effect_run is None or session.effect_run.awaiting is None
