"""The bot's Houdini on the live session (FakeTTS, batch mode): ESCAPE ARTIST on the table, the BOOSTED WITH of the boost cards the bot
spends (said, dealt, projected), the look at your hand that Set the Stage's boost takes, Smoke And Mirrors and All Part of the Show
on the bot's pieces. The engine side of the same cards is in tests/test_houdini_effects.py."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, human_reads, said
from test_e2_human_cards import bot_defends_with, bot_defends_with_nothing, put_adjacent, rig, with_rig  # noqa: F401

BOT_HAND = ("Flourish", "Sleight of Hand", "Misdirection", "And the Beautiful Bess!", "Grand Escape")


def far_space(game, fid):
    taken = {f.pos for f in game.fighters.values() if f.alive}
    return max((s for s in game.board.spaces if s not in taken), key=lambda s: game.board.distance(game.fighters[fid].pos, s))


def bot_card(game, title):
    return next(c for c in game.players[0].hand if c.title == title)


def human_attacks(session, table, game, target, title="Excalibur"):
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    click(session, table, Event.ATTACK, {"target": target})
    cid = card_ids(game, 1, title)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    return click(session, table, Event.REVEAL)


# ---------------------------------------------------------------- ESCAPE ARTIST on the table

@with_rig("houdini", "hellboy", *BOT_HAND)
def test_a_boosted_maneuver_puts_the_bots_houdini_on_any_space_and_the_table_follows(rig):
    session, table, game, fake, cfg = rig
    far = far_space(game, "houdini")
    msgs = bot_turn(session, table, [Act("maneuver", moves={"houdini": far}, boost=bot_card(game, "Sleight of Hand"))])
    houdini = game.fighters["houdini"]
    assert houdini.pos == far and table.positions[cfg.nicknames["houdini"]] == far
    assert game.board.distance(game.fighters["bess"].pos, far) > 2         # he left Bess behind: a placement, not a move
    assert any("boost de maniobra" in m for m in msgs) and not any("ilegal" in m.lower() for m in msgs)


@with_rig("houdini", "hellboy", *BOT_HAND)
def test_the_boosted_with_of_the_maneuver_boost_is_said_and_its_cards_are_dealt(rig):
    session, table, game, fake, cfg = rig
    msgs = bot_turn(session, table, [Act("maneuver", moves={}, boost=bot_card(game, "Flourish"))])
    line = next(m for m in msgs if "boost de maniobra" in m)
    assert "Flourish, gastada como boost: roba 1" in line, line
    assert len(game.players[0].hand) == len(table.bot_hand)                  # the engine and the table agree on the hand


@with_rig("houdini", "hellboy", *BOT_HAND)
def test_a_maneuver_boost_that_gains_an_action_says_so_and_the_bot_acts_again(rig):
    session, table, game, fake, cfg = rig
    plan = [Act("maneuver", moves={}, boost=bot_card(game, "And the Beautiful Bess!"))]
    msgs = bot_turn(session, table, plan)
    assert any("Flourish" not in m and "gana 1 accion" in m for m in msgs), msgs


# ---------------------------------------------------------------- a boost in a combat

@with_rig("houdini", "hellboy", *BOT_HAND)
def test_the_bots_boost_in_a_combat_runs_its_boosted_with_and_the_table_discards_both_cards(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, "Excalibur", "Service Pistol")
    grand = bot_card(game, "Grand Escape")
    bot_defends_with(session, game, "Grand Escape", monkeypatch)
    flourish = bot_card(game, "Flourish")
    monkeypatch.setattr(session.ai, "choose_combat_boost", lambda g, ctx: flourish)
    msgs = human_attacks(session, table, game, "houdini")
    assert said(msgs, "Aplicado: Flourish: roba 1") or said(msgs, "Flourish: roba 1"), msgs
    discarded = set(table.bot_discard)
    assert grand.card_id in discarded and flourish.card_id in discarded
    assert len(game.players[0].hand) == len(table.bot_hand)


@with_rig("houdini", "hellboy", "Set the Stage", "Flourish", "Misdirection", "Grand Escape")
def test_the_bots_set_the_stage_boost_reads_your_hand_once_and_makes_you_discard_the_card_it_names(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, "Excalibur", "Service Pistol", "Horseshoes And Hand Grenades")
    bot_defends_with(session, game, "Grand Escape", monkeypatch)
    stage = bot_card(game, "Set the Stage")
    monkeypatch.setattr(session.ai, "choose_combat_boost", lambda g, ctx: stage)
    reads = len(human_reads(table))
    msgs = human_attacks(session, table, game, "houdini")
    assert len(human_reads(table)) == reads + 1, "the bot reads your hand exactly when the boost says so"
    assert said(msgs, "Aplicado: Set the Stage: descartas") and said(msgs, "mira tu mano"), msgs
    assert said(msgs, "El bot descarta Set the Stage por boost de combate")          # a defense's boost is told as a boost too
    assert session.pending_discard is not None and session.pending_discard["kind"] == "cards" and len(session.pending_discard["cards"]) == 1


def _stage_look_with_two_right_hands(session, table, game, monkeypatch):
    """The bot's Set the Stage names a Right Hand Of Doom out of a hand that holds two copies; returns (named, other)."""
    put_adjacent(game, table, session.cfg, "hellboy", "houdini")
    human_hand(table, game, "Excalibur", "Right Hand Of Doom", "Right Hand Of Doom")
    bot_defends_with(session, game, "Grand Escape", monkeypatch)
    stage = bot_card(game, "Set the Stage")
    monkeypatch.setattr(session.ai, "choose_combat_boost", lambda g, ctx: stage)
    human_attacks(session, table, game, "houdini")
    named = session.pending_discard["cards"][0]
    copies = card_ids(game, 1, "Right Hand Of Doom", "Right Hand Of Doom")
    assert named in copies
    return named, next(i for i in copies if i != named)


@with_rig("houdini", "hellboy", "Set the Stage", "Flourish", "Misdirection", "Grand Escape")
def test_the_owed_discard_of_a_look_is_met_by_the_other_copy_of_the_same_title(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    named, other = _stage_look_with_two_right_hands(session, table, game, monkeypatch)
    table.human_discard.append(other)               # the human put the OTHER Right Hand Of Doom on the pile
    table.human_hand.remove(other)
    table.human_count -= 1
    destinies = game.destiny_count(1)
    msgs = click(session, table, Event.END_ACTION)
    assert not said(msgs, "Aun no veo en tu descarte"), msgs
    assert session.pending_discard is None
    assert game.destiny_count(1) == destinies, "one discard, counted once"
    assert [c.card_id for c in game.players[1].discard if c.title == "Right Hand Of Doom"] == [other]
    assert named in {c.card_id for c in game.players[1].hand}
    msgs = click(session, table, Event.END_ACTION)
    assert not said(msgs, "Aun no veo en tu descarte")


@with_rig("houdini", "hellboy", "Set the Stage", "Flourish", "Misdirection", "Grand Escape")
def test_the_owed_discard_met_by_the_named_copy_itself_still_works(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    named, other = _stage_look_with_two_right_hands(session, table, game, monkeypatch)
    table.human_discard.append(named)
    table.human_hand.remove(named)
    table.human_count -= 1
    destinies = game.destiny_count(1)
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and not said(msgs, "Aun no veo")
    assert game.destiny_count(1) == destinies


@with_rig("houdini", "hellboy", *BOT_HAND)
def test_a_combat_without_a_set_the_stage_boost_never_reads_your_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, "Excalibur", "Service Pistol")
    bot_defends_with(session, game, "Grand Escape", monkeypatch)
    monkeypatch.setattr(session.ai, "choose_combat_boost", lambda g, ctx: bot_card(game, "Flourish"))
    reads = len(human_reads(table))
    human_attacks(session, table, game, "houdini")
    assert len(human_reads(table)) == reads


# ---------------------------------------------------------------- the other cards on the bot's pieces

@with_rig("houdini", "hellboy", "Smoke and Mirrors", "Flourish", "Misdirection", "Grand Escape")
def test_the_bots_smoke_and_mirrors_swaps_its_pieces_on_the_table_and_bess_takes_the_blow(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, "Excalibur", "Service Pistol")
    where_h, where_b = game.fighters["houdini"].pos, game.fighters["bess"].pos
    bot_defends_with(session, game, "Smoke and Mirrors", monkeypatch)
    msgs = human_attacks(session, table, game, "houdini")
    assert game.fighters["houdini"].pos == where_b and game.fighters["bess"].pos == where_h
    assert table.positions[cfg.nicknames["houdini"]] == where_b and table.positions[cfg.nicknames["bess"]] == where_h
    combat = next(m for m in msgs if m.startswith("Combate:"))
    assert "Bess defiende con Smoke and Mirrors" in combat, combat
    assert game.fighters["houdini"].hp == 14


@with_rig("houdini", "hellboy", "All Part of the Show", "Flourish", "Misdirection", "Grand Escape")
def test_the_bots_all_part_of_the_show_brings_houdini_back_and_the_game_goes_on(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    houdini = game.fighters["houdini"]
    houdini.hp = 2
    guid = cfg.session_config().dials["houdini"]
    table.dials[guid]["value"] = session.dials_written[guid] = 2
    human_hand(table, game, "Excalibur", "Service Pistol")
    bot_defends_with(session, game, "All Part of the Show", monkeypatch)
    msgs = human_attacks(session, table, game, "houdini")
    assert game.winner is None and houdini.alive and houdini.hp == 4
    assert table.dials[guid]["value"] == 4 and table.positions[cfg.nicknames["houdini"]] == houdini.pos
    assert said(msgs, "All Part of the Show: houdini vuelve al tablero")
    assert not any("Fin de la partida" in m or "Game over" in m for m in msgs)


@with_rig("houdini", "hellboy", "Flourish", "Misdirection", "Grand Escape", "Sleight of Hand")
def test_without_all_part_of_the_show_the_same_blow_ends_the_game(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    game.fighters["houdini"].hp = 2
    guid = cfg.session_config().dials["houdini"]
    table.dials[guid]["value"] = session.dials_written[guid] = 2
    human_hand(table, game, "Excalibur", "Service Pistol")
    bot_defends_with_nothing(session, monkeypatch)
    human_attacks(session, table, game, "houdini")
    assert game.winner == 1
