"""Bullseye played BY THE HUMAN through the panel (FakeTTS, batch mode): an attack from up to 5 spaces away, out of every shared zone,
is accepted by the attack validation (and one from 6 is refused), the free BOOST of I Never Miss and the card it draws when the
human declines it, the tally of combats won this turn behind Study The Target, the placement and the moves the human makes by hand
(Tactical Retreat, Master Strategist), "considered to have won", and a choice parked at the panel that survives a restore. The bot's
side of the same cards is in tests/test_bullseye_effects.py.

His deck is sheet 176 like Medusa's, the turtles', Doctor Strange's and Bigfoot's: every id the table reports is resolved against
the human's deck."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import (adjacent_free, bot_defends_with, bot_defends_with_nothing, human_scheme, press,  # noqa: F401
                                 put_adjacent, rig, with_rig)

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def attack(session, table, game, title, attacker="bullseye", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def put_at(game, table, cfg, fid, space):
    game.fighters[fid].pos = space
    table.positions[cfg.nicknames[fid]] = space


def far_from(game, table, cfg, fid, rival, spaces_apart, shares_zone=False):
    """`fid` on a free space exactly `spaces_apart` spaces (along the adjacency) from `rival`, sharing a zone with it or not."""
    board, there = game.board, game.fighters[rival].pos
    taken = {f.pos for f in game.fighters.values() if f.alive and f.fid != fid}
    spot = next(s for s in sorted(board.spaces) if s not in taken and board.spaces_apart(there, s) == spaces_apart
                and board.share_zone(there, s) == shares_zone)
    put_at(game, table, cfg, fid, spot)
    return spot


def combat_line(msgs):
    return next(m for m in msgs if m.startswith("Combate:"))


# ---------------------------------------------------------------- the reach

@with_rig("hellboy", "bullseye", TRAINING)
def test_an_attack_from_five_spaces_out_of_every_shared_zone_is_accepted(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    far_from(game, table, cfg, "bullseye", "hellboy", 5)
    assert not game.board.share_zone(game.fighters["bullseye"].pos, game.fighters["hellboy"].pos)
    human_hand(table, game, "World's Greatest Assassin", "Feint")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "World's Greatest Assassin")
    assert game.fighters["hellboy"].hp == hp - 4 and not said(msgs, "no alcanza"), msgs
    assert combat_line(msgs)


@with_rig("hellboy", "bullseye", TRAINING)
def test_an_attack_from_six_spaces_is_refused(rig):
    session, table, game, fake, cfg = rig
    far_from(game, table, cfg, "bullseye", "hellboy", 6)
    human_hand(table, game, "World's Greatest Assassin", "Feint")
    click(session, table, Event.ATTACKER, {"attacker": "att_bullseye"})
    msgs = click(session, table, Event.ATTACK, {"target": "hellboy"})
    assert said(msgs, "no alcanza a hellboy"), msgs
    assert session.pending is None


@with_rig("hellboy", "bullseye", TRAINING)
def test_an_attack_on_a_same_zone_target_six_or_more_spaces_away_is_accepted(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    board = game.board
    taken = {f.pos for f in game.fighters.values() if f.alive and f.fid not in ("bullseye", "hellboy")}
    there, spot = next((a, c) for a in sorted(board.spaces) for c in sorted(board.spaces) if a not in taken and c not in taken
                       and board.share_zone(a, c) and board.spaces_apart(a, c) >= 6)
    put_at(game, table, cfg, "hellboy", there)
    put_at(game, table, cfg, "bullseye", spot)
    human_hand(table, game, "World's Greatest Assassin", "Feint")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "World's Greatest Assassin")
    assert game.fighters["hellboy"].hp == hp - 4 and not said(msgs, "no alcanza"), msgs


@with_rig("bullseye", "hellboy")
def test_the_human_cannot_hit_a_bullseye_that_stands_out_of_their_reach_but_the_bot_shoots_from_five(rig):
    session, table, game, fake, cfg = rig
    far_from(game, table, cfg, "bullseye", "hellboy", 5)
    bullseye, hellboy = game.fighters["bullseye"], game.fighters["hellboy"]
    assert game.can_attack(bullseye, hellboy) and not game.can_attack(hellboy, bullseye)


# ---------------------------------------------------------------- I Never Miss

@with_rig("hellboy", "bullseye", TRAINING)
def test_declining_the_boost_of_i_never_miss_deals_you_a_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    human_hand(table, game, "I Never Miss", "Master Strategist")
    msgs = attack(session, table, game, "I Never Miss")
    assert session.pending is not None and session.pending.wait is not None
    assert said(msgs, "I Never Miss revelado: si quieres potenciar") and not said(msgs, "Combate:")
    msgs = click(session, table, Event.NO_BOOST)
    assert "total 3" in combat_line(msgs) and said(msgs, "robas 1"), msgs
    assert table.human_deals == [1] and len(game.players[1].hand) == table.human_count
    assert session.pending is None


@with_rig("hellboy", "bullseye", TRAINING)
def test_boosting_i_never_miss_deals_no_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    human_hand(table, game, "I Never Miss", "Master Strategist")
    attack(session, table, game, "I Never Miss")
    boost = card_ids(game, 1, "Master Strategist")[0]                 # BOOST 3
    table.human_hand.remove(boost)
    table.human_discard.append(boost)
    table.human_count -= 1
    msgs = click(session, table, Event.BOOST)
    assert "total 6" in combat_line(msgs), combat_line(msgs)
    assert table.human_deals == [] and not said(msgs, "robas 1")


# ---------------------------------------------------------------- the tally of the turn

@with_rig("hellboy", "bullseye", TRAINING)
def test_study_the_target_deals_two_cards_with_no_win_this_turn_and_three_after_one(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Study The Target", "Study The Target", "Feint")
    msgs = human_scheme(session, table, game, "Study The Target")
    assert table.human_deals == [2] and game.fx.won == [0, 0], msgs
    assert game.actions_left == 1


@with_rig("hellboy", "bullseye", TRAINING)
def test_study_the_target_after_a_won_combat_deals_three_and_gives_the_action_back(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    human_hand(table, game, "Feint", "Study The Target")
    attack(session, table, game, "Feint")
    assert game.fx.won[1] == 1
    click(session, table, Event.END_ACTION)
    left = game.actions_left
    msgs = human_scheme(session, table, game, "Study The Target")
    assert table.human_deals[-1] == 3 and said(msgs, "robas 3"), msgs
    assert game.actions_left == left, "one action spent on the scheme and one gained"


@with_rig("hellboy", "bullseye", TRAINING)
def test_the_tally_of_wins_survives_a_save_and_a_restore(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    human_hand(table, game, "Feint", "Study The Target")
    attack(session, table, game, "Feint")
    session._restore(session.to_dict())                                # what --resume does
    assert session.game.fx.won == [0, 1]


# ---------------------------------------------------------------- moves and placements by hand

@with_rig("hellboy", "bullseye", TRAINING)
def test_master_strategist_leaves_the_exact_four_space_move_of_your_miniature_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    human_hand(table, game, "Master Strategist", "Feint")
    msgs = attack(session, table, game, "Master Strategist")
    assert session.effect_run is None and session.pending is None
    assert said(msgs, "en la mesa: mueve a bullseye exactamente 4 casillas (puede atravesar rivales)"), msgs


@with_rig("hellboy", "bullseye", TRAINING)
def test_master_strategist_with_no_space_exactly_four_away_is_skipped_and_the_chat_says_so(rig, monkeypatch):
    """Iván, 2026-11-07: no exact space means the move is cancelled; the human is not asked to move (no stall)."""
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    start = game.fighters["bullseye"].pos
    monkeypatch.setattr(game, "legal_moves", lambda f, steps, through: {s for s in game.board.spaces if 0 < game.board.distance(start, s) < 4})
    human_hand(table, game, "Master Strategist", "Feint")
    msgs = attack(session, table, game, "Master Strategist")
    assert session.effect_run is None and session.pending is None and game.fighters["bullseye"].pos == start
    assert said(msgs, "no puede moverse exactamente 4 casillas") and not said(msgs, "mueve a bullseye exactamente"), msgs


@with_rig("hellboy", "bullseye", TRAINING)
def test_arrogant_but_effective_says_it_counts_as_a_win_and_leaves_the_move_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    card = next(c for c in game.players[0].hand if c.title == TRAINING)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: card)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    human_hand(table, game, "Arrogant But Effective", "Feint")
    msgs = attack(session, table, game, "Arrogant But Effective")                 # 2 against Training's 3: lost on the damage
    assert game.fx.won[1] == 1, msgs
    assert said(msgs, "cuentas como ganador del combate") and said(msgs, "mueve a bullseye hasta 2 casillas"), msgs


@with_rig("hellboy", "bullseye", TRAINING)
def test_tactical_retreat_names_the_space_that_shares_no_zone_and_leaves_the_placement_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    human_hand(table, game, "Tactical Retreat", "Feint")
    attacker = next(c for c in game.players[0].hand if c.can_attack and (c.value or 0) <= 3)
    bot_turn(session, table, [Act("attack", fid="hellboy", target="bullseye", card=attacker)])
    cid = card_ids(game, 1, "Tactical Retreat")[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "en la mesa: coloca a bullseye en una casilla que no comparta zona con la de tu heroe"), msgs
    assert session.effect_run is None and session.pending is None


# ---------------------------------------------------------------- a choice that waits at the panel survives --resume

@with_rig("hellboy", "bullseye", TRAINING)
def test_ricochet_asks_which_fighter_takes_the_damage_and_the_question_survives_a_restore(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    put_adjacent(game, table, cfg, "lobster", "hellboy")
    human_hand(table, game, "Ricochet", "Feint")
    attack(session, table, game, "Ricochet")
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and {"hellboy", "lobster"} <= set(req.options)
    session._restore(session.to_dict())
    game = session.game
    assert session._paused() is not None and session._paused()[2].awaiting.kind == "fighter"
    hp = game.fighters["lobster"].hp
    press(session, table, "lobster")
    assert game.fighters["lobster"].hp == hp - 1 and session.pending is None
    assert cfg.session_config().dials["lobster"] in {g for g, _ in table.dial_writes}


@with_rig("hellboy", "bullseye", TRAINING)
def test_right_between_the_eyes_makes_the_bot_discard_after_a_win_and_nothing_before(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    human_hand(table, game, "Right Between The Eyes", "Right Between The Eyes", "Feint")
    bot_hand = len(game.players[0].hand)
    attack(session, table, game, "Right Between The Eyes")
    assert len(game.players[0].hand) == bot_hand                                      # no win yet: nothing to discard
    click(session, table, Event.END_ACTION)
    msgs = attack(session, table, game, "Right Between The Eyes")
    assert len(game.players[0].hand) == bot_hand - 1, msgs


# ---------------------------------------------------------------- I Planned To Be Here

@with_rig("hellboy", "bullseye", TRAINING)
def test_i_planned_to_be_here_is_five_for_you_only_if_your_miniature_has_not_moved_this_turn(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "bullseye", "hellboy")
    human_hand(table, game, "I Planned To Be Here", "I Planned To Be Here")
    game.fx.turn_start_pos = {"bullseye": game.fighters["bullseye"].pos}            # where the turn began
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "I Planned To Be Here")
    assert game.fighters["hellboy"].hp == hp - 5
    click(session, table, Event.END_ACTION)
    game.fx.turn_start_pos = {"bullseye": adjacent_free(game, "bullseye")}          # he began the turn somewhere else
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "I Planned To Be Here")
    assert game.fighters["hellboy"].hp == hp - 2
