"""Achilles played BY THE HUMAN through the panel (FakeTTS, batch mode). The bot's side of the same cards is in
tests/test_achilles_effects.py.

His deck is sheet 176 like Medusa's, the turtles' and the other decks of the range: every id the table reports is resolved against the
human's deck."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with, bot_defends_with_nothing, by_hand, human_scheme, labels, press, put_adjacent, rig, with_rig  # noqa: F401

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
    achilles_at = achilles.pos
    human_hand(table, game, "Under Achilles' Helm", "Feint")
    msgs = bot_attacks(session, table, game, "Excalibur", "achilles", "Under Achilles' Helm")
    assert session.effect_run.awaiting.kind == "optional", msgs
    msgs = press(session, table, True)
    assert said(msgs, "he intercambiado yo las miniaturas"), msgs
    assert not said(msgs, "en la mesa: intercambia"), msgs
    assert (achilles.pos, patroclus.pos) == (far, achilles_at)                     # the engine swapped them at once
    assert (table.positions[cfg.nicknames["achilles"]], table.positions[cfg.nicknames["patroclus"]]) == (far, achilles_at)   # and the bot moved the miniatures
    assert not session.game.placing and not session.hand_moved
    assert patroclus.hp == 6 - max(0, 6 - 2) and achilles.hp == 18


@with_rig("hellboy", "achilles", "Right Hand Of Doom", TRAINING)
def test_the_bots_after_move_reads_the_swapped_positions_and_the_table_is_never_read_as_hand_moves(rig):
    """Live game 21/11: the by-hand swap left the engine on the old spaces, Right Hand Of Doom moved Achilles from his old one and the
    table read then overwrote it. Now the swap is in the engine before the AFTER runs."""
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    patroclus, achilles = game.fighters["patroclus"], game.fighters["achilles"]
    far = next(s for s in sorted(game.board.spaces, reverse=True) if all(f.pos != s for f in game.fighters.values() if f.alive))
    patroclus.pos = far
    table.positions[cfg.nicknames["patroclus"]] = far
    achilles_at = achilles.pos
    human_hand(table, game, "Under Achilles' Helm", "Feint")
    bot_attacks(session, table, game, "Right Hand Of Doom", "achilles", "Under Achilles' Helm")
    msgs = press(session, table, True)
    assert patroclus.hp < 6 and achilles.hp == 18, msgs                        # Patroclus is the defender
    assert achilles.pos == far and patroclus.pos != far, msgs                  # Right Hand Of Doom moved Patroclus from his swapped space, never Achilles from his old one
    for fid in ("achilles", "patroclus"):
        assert table.positions[cfg.nicknames[fid]] == game.fighters[fid].pos, (fid, msgs)
    assert not session.game.placing and not session.hand_moved, msgs


@with_rig("hellboy", "achilles", "Planned Recklessness", TRAINING)
def test_wily_fighting_says_the_damage_was_stopped_by_the_bots_planned_recklessness(rig, monkeypatch):
    """Live game 21/11: the chat only said the draw of VENGEANCE and Ivan thought Wily Fighting was not applied."""
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    put_adjacent(game, table, cfg, "lobster", "achilles")
    patroclus = game.fighters["patroclus"]
    patroclus.hp, patroclus.alive, patroclus.pos = 0, False, None
    bot_defends_with(session, game, "Planned Recklessness", monkeypatch)
    human_hand(table, game, "Skirmish", "Wily Fighting", "Feint")
    attack(session, table, game, "achilles", "Skirmish")
    click(session, table, Event.END_ACTION)
    bot_defends_with_nothing(session, monkeypatch)
    lobster = game.fighters["lobster"].hp
    msgs = attack(session, table, game, "achilles", "Wily Fighting")
    assert game.fighters["lobster"].hp == lobster, msgs
    assert said(msgs, "Wily Fighting: hellboy y lobster no reciben dano de efectos (Planned Recklessness: no reciben dano de efectos este turno)"), msgs


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


# ---------------------------------------------------------------- Test For Weakness (the double attack at the table)

@with_rig("hellboy", "achilles", TRAINING)
def test_test_for_weakness_you_attack_the_bot_defends_the_second_part_and_the_hit_points_follow(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    asked = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)
    monkeypatch.setattr(session.ai, "choose_second_defense",
                        lambda g, att, tgt, value, card: asked.append((att.fid, tgt.fid, value, card.title)) or None)
    human_hand(table, game, "Test For Weakness", "Feint")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "achilles", "Test For Weakness")
    assert session.pending is None and session.second_next is not None, "the second part waits for End action"
    click(session, table, Event.END_ACTION)
    assert session.pending is not None and session.pending.second["value"] == 3 and game.fighters["hellboy"].hp == hp - 1
    assert asked == [("achilles", "hellboy", 3, "Test For Weakness")]
    click(session, table, Event.REVEAL)
    assert session.pending is None and game.fighters["hellboy"].hp == hp - 1 - 3


@with_rig("achilles", "hellboy", "Test For Weakness", "Brothers In Arms", "Feint", "Skirmish", "Wily Fighting")
def test_test_for_weakness_the_bot_attacks_and_you_defend_the_second_part_with_a_new_card(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "achilles", "hellboy")
    card = next(c for c in game.players[0].hand if c.title == "Test For Weakness")
    human_hand(table, game, "B.P.R.D. Training", "Service Pistol")
    bot_turn(session, table, [Act("attack", fid="achilles", target="hellboy", card=card)])
    hellboy = game.fighters["hellboy"]
    hp = hellboy.hp
    table.face_down = []
    click(session, table, Event.REVEAL)
    click(session, table, Event.END_ACTION)
    p = session.pending
    assert p is not None and p.kind == "bot_attacks" and p.second["value"] == 3 and hellboy.hp == hp - 1
    block = card_ids(game, 1, "B.P.R.D. Training")[0]
    table.face_down = [{"id": block, "guid": f"h{block}"}]
    table.human_hand.remove(block)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    assert session.pending is None and hellboy.hp == hp - 1               # Training (3) stops the 3


@with_rig("hellboy", "achilles", TRAINING)
def test_winning_both_parts_of_test_for_weakness_draws_two_at_the_table(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    patroclus = game.fighters["patroclus"]
    patroclus.hp, patroclus.alive, patroclus.pos = 0, False, None
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)
    monkeypatch.setattr(session.ai, "choose_second_defense", lambda g, att, tgt, value, card: None)
    human_hand(table, game, "Test For Weakness", "Feint")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "achilles", "Test For Weakness")
    msgs += click(session, table, Event.END_ACTION)
    msgs += click(session, table, Event.REVEAL)
    assert game.fighters["hellboy"].hp == hp - 3 - 5, msgs               # 1+2 then 3+2, both undefended
    assert sum("robas 1" in m for m in msgs) == 2, msgs


# ---------------------------------------------------------------- save and resume with a question open

def resumed(session):
    """What --resume does: the saved session is loaded again and the paused effect is the same question."""
    session._restore(session.to_dict())
    return session._paused()[2] if session.effect_run is None else session.effect_run


@with_rig("hellboy", "achilles", "Excalibur", TRAINING)
@pytest.mark.parametrize("answer", [True, False])
def test_under_achilles_helm_survives_a_resume_and_either_answer(rig, answer):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    patroclus, achilles = game.fighters["patroclus"], game.fighters["achilles"]
    far = next(s for s in sorted(game.board.spaces, reverse=True) if all(f.pos != s for f in game.fighters.values() if f.alive))
    patroclus.pos = far
    table.positions[cfg.nicknames["patroclus"]] = far
    human_hand(table, game, "Under Achilles' Helm", "Feint")
    bot_attacks(session, table, game, "Excalibur", "achilles", "Under Achilles' Helm")
    assert session.effect_run.awaiting.kind == "optional"
    assert resumed(session).awaiting.kind == "optional"
    press(session, table, answer)
    patroclus, achilles = session.game.fighters["patroclus"], session.game.fighters["achilles"]          # the resume rebuilt the game
    assert (patroclus.hp == 6 - 4) is answer and (achilles.hp == 18 - 4) is (not answer)


@with_rig("hellboy", "achilles", TRAINING)
@pytest.mark.parametrize("answer", [True, False])
def test_the_day_of_your_doom_question_survives_a_resume_and_either_answer(rig, monkeypatch, answer):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "patroclus")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "The Day of Your Doom", "Feint")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "patroclus", "The Day of Your Doom")
    assert session.effect_run.awaiting.kind == "optional"
    assert resumed(session).awaiting.kind == "optional"
    press(session, table, answer)
    game = session.game
    assert game.fighters["patroclus"].hp == (4 if answer else 6) and game.fighters["hellboy"].hp == hp - (5 if answer else 3)


@with_rig("chupacabra", "achilles", "The More They Struggle")
def test_a_human_achilles_who_defends_without_a_card_and_wins_draws_one_before_the_bots_after(rig):
    """The cardless draw runs before the attacker's AFTER (defender first). No gate is needed: a draw leaves the human no step on their hand
    (`table.hand_step_pending` only counts choose / return_to_deck / search_deck and discards), the table deals the card at once, so a bot
    AFTER that reads the human's hand after it already sees the new count."""
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "chupacabra", "achilles")
    patroclus = game.fighters["patroclus"]
    patroclus.hp, patroclus.alive, patroclus.pos = 0, False, None
    human_hand(table, game, "Feint")
    card = next(c for c in game.players[0].hand if c.title == "The More They Struggle")
    bot_turn(session, table, [Act("attack", fid="chupacabra", target="achilles", card=card)])
    table.face_down = []
    before = len(game.players[1].hand)
    msgs = click(session, table, Event.REVEAL)
    assert game.fighters["achilles"].hp == 18 and said(msgs, "robas 1"), msgs
    assert len(game.players[1].hand) == before + 1 and session.pending is None
