"""Bigfoot played BY THE HUMAN through the panel (FakeTTS, batch mode): the end-of-turn ability's Yes / No (asked only when no
opposing fighter is in Bigfoot's zone) and what the table is told to do for the draw, and the cards that ask the panel or leave
something to the table (Skirmish, Hoax, Disengage, Savagery, Regroup, Crash Through the Trees, Jackalope Horns). The bot's side of
the same cards is in tests/test_bigfoot_effects.py.

His deck is sheet 176 like Medusa's, the turtles' and Doctor Strange's: every id the table reports is resolved against the
human's deck."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, human_attack, human_hand, said
from test_d3_table_effects import build
from test_dial_identity import split_shared_dials
from test_e2_human_cards import adjacent_free, bot_defends_with_nothing, human_scheme, press, put_adjacent, with_rig

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


@pytest.fixture
def rig(request, tmp_path):
    """The e2 rig, with the two dials the save gives one GUID (Lobster Johnson's and the Jackalope's) told apart on the table as TTS does."""
    bot, human, hand, over = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, **over)
    if {bot, human} == {"hellboy", "bigfoot"}:
        split_shared_dials(session, table, game)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def attack(session, table, game, attacker, title, target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def isolate_bot(game, table, cfg):
    """Every fighter of the bot outside Bigfoot's zone (on the board and on the table)."""
    bigfoot = game.fighters["bigfoot"]
    far = [s for s in sorted(game.board.spaces, reverse=True) if not game.board.share_zone(bigfoot.pos, s)]
    for f, s in zip([f for f in game.fighters.values() if f.alive and f.owner == 0], far):
        f.pos = s
        table.positions[cfg.nicknames[f.fid]] = s


def end_turn(session, table):
    """Two maneuvers and End action; the bot then maneuvers too. Returns the messages of the last click."""
    plan = []
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    return click(session, table, Event.END_ACTION)


# ---------------------------------------------------------------- the ability

@with_rig("hellboy", "bigfoot", TRAINING)
def test_the_ability_asks_yes_or_no_at_the_end_of_your_turn_when_no_rival_is_in_your_zone(rig):
    session, table, game, fake, cfg = rig
    isolate_bot(game, table, cfg)
    msgs = end_turn(session, table)
    req = session.effect_run.awaiting
    assert req is not None and req.kind == "optional" and session.pending is None
    assert said(msgs, "robas 1 carta") and game.turn == 0, msgs                  # the question is on the panel; the draw is yours to confirm
    assert session.panel_labels()["btn_choice_1"] and session.panel_labels()["btn_choice_2"]


@with_rig("hellboy", "bigfoot", TRAINING)
def test_yes_deals_the_card_and_no_does_not(rig):
    session, table, game, fake, cfg = rig
    isolate_bot(game, table, cfg)
    hand = len(game.players[1].hand)
    end_turn(session, table)
    assert table.human_deals == [1, 1]                                   # the two maneuvers drew one card each
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert table.human_deals == [1, 1, 1] and len(game.players[1].hand) == hand + 3, msgs
    assert said(msgs, "Tu habilidad: BIGFOOT DRAW: robas 1") and said(msgs, "Te he dado 1 carta")
    assert session.effect_run is None or session.effect_run.awaiting is None


@with_rig("hellboy", "bigfoot", TRAINING)
def test_saying_no_draws_nothing(rig):
    session, table, game, fake, cfg = rig
    isolate_bot(game, table, cfg)
    hand = len(game.players[1].hand)
    end_turn(session, table)
    msgs = click(session, table, Event.CHOICE, {"i": 2})
    assert table.human_deals == [1, 1] and len(game.players[1].hand) == hand + 2 and not said(msgs, "Te he dado")


@with_rig("hellboy", "bigfoot", TRAINING)
def test_with_an_opposing_fighter_in_your_zone_nothing_is_asked(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    assert game.board.share_zone(game.fighters["bigfoot"].pos, game.fighters["hellboy"].pos)
    msgs = end_turn(session, table)
    assert session.effect_run is None or session.effect_run.awaiting is None
    assert not said(msgs, "robas 1 carta") and table.human_deals == [1, 1]


# ---------------------------------------------------------------- the cards

def centre(game, table, cfg):
    """Bigfoot on the space with the most neighbours of its zone, so three fighters can stand next to him."""
    best = max(game.board.spaces, key=lambda s: (sum(1 for n in game.board.adj[s] if game.board.share_zone(s, n)), -s))
    for f in game.fighters.values():
        if f.fid != "bigfoot" and f.pos == best:
            f.pos = next(sp for sp in sorted(game.board.spaces, reverse=True) if all(o.pos != sp for o in game.fighters.values()))
            table.positions[cfg.nicknames[f.fid]] = f.pos
    game.fighters["bigfoot"].pos = best
    table.positions[cfg.nicknames["bigfoot"]] = best


def by_hand(session, table, cfg, fid, space):
    """The human puts the miniature of `fid` on `space` by hand and presses Done (button 1)."""
    table.positions[cfg.nicknames[fid]] = space
    return click(session, table, Event.CHOICE, {"i": 1})


@with_rig("hellboy", "bigfoot", TRAINING)
def test_savagery_won_hurts_every_fighter_next_to_bigfoot_and_the_dials_follow(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    centre(game, table, cfg)
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    put_adjacent(game, table, cfg, "lobster", "bigfoot")
    put_adjacent(game, table, cfg, "jackalope", "bigfoot")
    human_hand(table, game, "Savagery", "Hoax")
    hp = {fid: game.fighters[fid].hp for fid in ("hellboy", "lobster", "jackalope")}
    msgs = attack(session, table, game, "bigfoot", "Savagery")
    assert game.fighters["hellboy"].hp == hp["hellboy"] - 4 - 1
    assert game.fighters["lobster"].hp == hp["lobster"] - 1 and game.fighters["jackalope"].hp == hp["jackalope"] - 1
    assert said(msgs, "Tu carta: Savagery")
    written = {g for g, _ in table.dial_writes}
    assert {session.cfg.dials[f] for f in ("hellboy", "lobster", "jackalope")} <= written


@with_rig("hellboy", "bigfoot", TRAINING)
def test_regroup_won_deals_two_cards(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    human_hand(table, game, "Regroup", "Hoax")
    msgs = attack(session, table, game, "bigfoot", "Regroup")
    assert table.human_deals == [2] and said(msgs, "robas 2"), msgs
    assert len(game.players[1].hand) == table.human_count


@with_rig("hellboy", "bigfoot", TRAINING)
def test_skirmish_won_asks_which_fighter_and_leaves_the_move_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    human_hand(table, game, "Skirmish", "Hoax")
    attack(session, table, game, "bigfoot", "Skirmish")
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and set(req.options) == {"bigfoot", "hellboy"}
    press(session, table, "hellboy")
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "hellboy" and req.extra["steps"] == 2
    dest = req.options[0]
    by_hand(session, table, cfg, "hellboy", dest)
    assert session.pending is None and game.fighters["hellboy"].pos == dest


@with_rig("hellboy", "bigfoot", TRAINING)
def test_hoax_leaves_the_five_space_move_of_your_own_miniature_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    human_hand(table, game, "Hoax", "Skirmish")
    msgs = attack(session, table, game, "bigfoot", "Hoax")
    assert session.effect_run is None and session.pending is None
    assert said(msgs, "en la mesa: mueve a bigfoot hasta 5 casillas (puede atravesar rivales)"), msgs


@with_rig("hellboy", "bigfoot", TRAINING)
def test_disengage_leaves_the_placement_of_your_own_miniature_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    human_hand(table, game, "Disengage", "Skirmish")
    msgs = attack(session, table, game, "bigfoot", "Disengage")
    assert session.effect_run is None and session.pending is None
    assert said(msgs, "en la mesa: coloca a bigfoot en la zona de tu heroe"), msgs


@with_rig("hellboy", "bigfoot", TRAINING)
def test_crash_through_the_trees_leaves_bigfoots_move_to_you(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Crash Through the Trees", "Hoax")
    msgs = human_scheme(session, table, game, "Crash Through the Trees")
    assert session.effect_run is None and said(msgs, "en la mesa: mueve a bigfoot hasta 5 casillas (puede atravesar rivales)"), msgs


@with_rig("hellboy", "bigfoot", TRAINING)
def test_jackalope_horns_is_played_by_the_jackalope_you_move_it_first_and_then_name_who_takes_two(rig):
    """The scheme is the Jackalope's. The chat first tells you to move the Jackalope by hand (Done), and only then does the damage
    question come, naming the Jackalope and offering the fighters next to where you put it."""
    session, table, game, fake, cfg = rig
    centre(game, table, cfg)
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    human_hand(table, game, "Jackalope Horns", "Hoax")
    hp = {fid: game.fighters[fid].hp for fid in ("hellboy", "bigfoot")}
    msgs = human_scheme(session, table, game, "Jackalope Horns")
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "jackalope" and req.extra["steps"] == 5 and req.extra["through"] is True
    assert said(msgs, "Jackalope Horns: mueve a Jackalope") or said(msgs, "Mueve"), msgs
    assert game.fighters["hellboy"].hp == hp["hellboy"] and game.fighters["bigfoot"].hp == hp["bigfoot"]
    spot = next(s for s in sorted(game.board.adj[game.fighters["hellboy"].pos])
                if s in req.options and s in game.board.adj[game.fighters["bigfoot"].pos])
    msgs = by_hand(session, table, cfg, "jackalope", spot)
    assert game.fighters["jackalope"].pos == spot
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and set(req.options) == {"hellboy", "bigfoot"} and req.min == 1
    assert said(msgs, "Elige un luchador adyacente a The Jackalope"), msgs
    press(session, table, "hellboy")
    assert game.fighters["hellboy"].hp == hp["hellboy"] - 2 and game.fighters["bigfoot"].hp == hp["bigfoot"] and session.pending is None
    assert cfg.session_config().dials["hellboy"] in {g for g, _ in table.dial_writes}


@with_rig("hellboy", "bigfoot", TRAINING)
def test_jackalope_horns_with_nobody_next_to_where_you_put_it_asks_nothing(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Jackalope Horns", "Hoax")
    hp = {f.fid: f.hp for f in game.fighters.values()}
    human_scheme(session, table, game, "Jackalope Horns")
    req = session.effect_run.awaiting
    lonely = next(o for o in req.options if all(game.board.distance(o, f.pos) > 1 for f in game.fighters.values()
                                                if f.alive and f.fid != "jackalope"))
    by_hand(session, table, cfg, "jackalope", lonely)
    assert session.effect_run is None and session.pending is None and {f.fid: f.hp for f in game.fighters.values()} == hp


@with_rig("hellboy", "bigfoot", TRAINING)
def test_disengage_played_by_the_jackalope_names_the_jackalopes_zone_not_the_heros(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "jackalope", "hellboy")
    human_hand(table, game, "Disengage", "Skirmish")
    msgs = attack(session, table, game, "jackalope", "Disengage")
    assert said(msgs, "en la mesa: coloca a jackalope en la zona de jackalope"), msgs
    assert not said(msgs, "zona de tu heroe")


@with_rig("hellboy", "bigfoot", TRAINING)
def test_a_scheme_of_a_dead_sidekick_is_refused_not_played_by_the_hero(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "bigfoot")
    game.fighters["jackalope"].alive, game.fighters["jackalope"].hp = False, 0
    human_hand(table, game, "Jackalope Horns", "Hoax")
    hp = {f.fid: f.hp for f in game.fighters.values()}
    bigfoot_at = game.fighters["bigfoot"].pos
    msgs = human_scheme(session, table, game, "Jackalope Horns")
    assert said(msgs, "Jackalope Horns solo puede jugarla The Jackalope, que no esta en el tablero"), msgs
    assert session.effect_run is None and {f.fid: f.hp for f in game.fighters.values()} == hp
    assert game.fighters["bigfoot"].pos == bigfoot_at and not said(msgs, "mueve a bigfoot")
