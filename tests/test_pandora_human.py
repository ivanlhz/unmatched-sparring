"""Pandora on the table through the panel (FakeTTS, batch mode), both seats. The human's Box is the real deck of seven MISERIES: the panel asks which
one came up, then whether to keep revealing; a Kakodaemon from Woe is put on the table by hand and read from it, the damage at three feathers is
written on the dial, and Greed's card is dealt by the human. The bot's Box is virtual: the chat names each Misery it reveals, the Kakodaemon comes
out of the bag by the bot's own hand and the dial follows. The bot's side of the same cards is in tests/test_pandora_effects.py.

The Kakodaemons are two Custom_Token in the save (Thanatos and Olethros), which real TTS may report as "Tile": nothing that reads or moves a piece
looks at the type."""
from __future__ import annotations

import pytest

from sparring import ai_pandora
from sparring.effects.run import EffectRun
from sparring.i18n import t
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, said
from test_e2_human_cards import by_hand, labels, press, with_rig, rig  # noqa: F401

HAND = ("Excalibur", "B.P.R.D. Training", "Service Pistol", "Right Hand Of Doom")      # the bot Hellboy's
BOT_HAND = ("Hindsight", "Hera's Curiosity", "Feint", "Forged by Hephaestus")
IDX = {"Woe": 0, "Toil": 1, "Pain": 2, "Misfortune": 3, "Hope": 4, "Greed": 5, "Confusion": 6}
KAKO = ["kakodaemon1", "kakodaemon2"]


def dial(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


def reveal(session, table, name):
    """The human turns up `name` from the real Box: the panel's answer."""
    return press(session, table, IDX[name])


def free_in_zone(game, fid):
    """Empty spaces of `fid`'s zone."""
    taken = {f.pos for f in game.fighters.values() if f.alive}
    pos = game.fighters[fid].pos
    return [s for s in sorted(game.board.spaces) if s not in taken and game.board.share_zone(pos, s)]


@pytest.fixture
def order(monkeypatch):
    """What the bot's Box turns up, in order (the engine draws the Miseries at random when they are revealed): a list to extend."""
    seq: list[int] = []
    monkeypatch.setattr(EffectRun, "random_sample", lambda self, items, n: [seq.pop(0)])
    return seq


# ---------------------------------------------------------------- the human's Box

@with_rig("hellboy", "pandora", *HAND)
def test_the_turn_opens_by_asking_which_misery_the_human_revealed(rig):
    session, table, game, fake, cfg = rig
    req = session.effect_run.awaiting
    assert game.turn == 1 and req.kind == "effect" and req.extra["tag"] == "misery" and req.options == list(range(7))
    assert labels(session)[:5] == ["Woe", "Toil", "Pain", "Misfortune", "Hope"]          # six buttons: the last two on a second page
    assert dial(session, cfg, table, "pandora") == 14 and not any(game.fighters[k].alive for k in KAKO)


@with_rig("hellboy", "pandora", *HAND)
def test_the_first_reveal_is_followed_by_the_choice_to_keep_going_and_stopping_costs_nothing(rig):
    session, table, game, fake, cfg = rig
    reveal(session, table, "Toil")
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.extra["box"] == "open" and req.extra["unrevealed"] == [0, 2, 3, 4, 5, 6]
    press(session, table, False)
    assert session.effect_run is None and dial(session, cfg, table, "pandora") == 14 and game.fighters["pandora"].hp == 14
    assert game.fx.counter_value(1, "revealed") == 1


@with_rig("hellboy", "pandora", *HAND)
def test_three_feathers_stop_the_human_and_the_damage_is_written_on_the_dial(rig):
    session, table, game, fake, cfg = rig
    reveal(session, table, "Toil")
    press(session, table, True)
    reveal(session, table, "Pain")
    press(session, table, True)
    msgs = reveal(session, table, "Misfortune")                      # 1 + 1 + 2 feathers
    assert session.effect_run is None, msgs                          # nothing more is asked
    assert game.fighters["pandora"].hp == 14 - 3 and dial(session, cfg, table, "pandora") == 11
    assert said(msgs, "Pandora -3 PV (11)") and said(msgs, t("narr.notice.pandora_three_feathers")), msgs
    assert said(msgs, t("trigger.title.pandora_box")), msgs


@with_rig("hellboy", "pandora", *HAND)
def test_the_misery_the_human_names_is_not_offered_again(rig):
    session, table, game, fake, cfg = rig
    reveal(session, table, "Hope")
    press(session, table, True)
    req = session.effect_run.awaiting
    assert req.kind == "effect" and IDX["Hope"] not in req.options and len(req.options) == 6


@with_rig("hellboy", "pandora", *HAND)
def test_woe_asks_the_human_to_put_a_kakodaemon_in_their_zone_and_reads_it_from_the_table(rig):
    session, table, game, fake, cfg = rig
    reveal(session, table, "Woe")
    k = game.fighters["kakodaemon1"]
    assert k.alive and k.hp == 1 and game.placing == {"kakodaemon1"}
    msgs = press(session, table, False)
    assert said(msgs, "pon a Thanatos en el tablero") and said(msgs, "con 1 PV"), msgs
    spot = free_in_zone(game, "pandora")[-1]
    table.positions[cfg.nicknames["kakodaemon1"]] = spot             # the human takes Thanatos out of the bag and puts it there
    click(session, table, Event.END_ACTION)
    assert k.pos == spot and game.placing == set() and game.board.share_zone(k.pos, game.fighters["pandora"].pos)


@with_rig("hellboy", "pandora", *HAND)
def test_greed_is_a_card_the_human_draws(rig):
    session, table, game, fake, cfg = rig
    reveal(session, table, "Greed")
    msgs = press(session, table, False)
    assert said(msgs, "Robas 1 carta") or said(msgs, "roba 1 carta") or said(msgs, "1 carta"), msgs


@with_rig("hellboy", "pandora", *HAND)
def test_the_miseries_go_back_into_the_box_when_the_human_ends_the_turn(rig):
    session, table, game, fake, cfg = rig
    reveal(session, table, "Toil")
    press(session, table, False)
    assert game.fx.counter_value(1, "box_mask") != 0
    bot_turn(session, table, [])
    assert [game.fx.counter_value(1, n) for n in ("box_mask", "revealed", "box_top", "box_done", "box_current")] == [0, 0, 0, 0, 0]


# ---------------------------------------------------------------- the bot's Box

def keeps(monkeypatch, *answers):
    """The bot's answers to "keep revealing?", in order (False when they run out)."""
    left = list(answers)
    monkeypatch.setattr(ai_pandora, "keep_revealing", lambda ai, game, req: left.pop(0) if left else False)


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_the_bots_box_names_each_misery_it_reveals_and_the_dial_follows_the_damage(rig, order, monkeypatch):
    session, table, game, fake, cfg = rig
    order.extend([IDX["Toil"], IDX["Pain"], IDX["Greed"]])
    keeps(monkeypatch, True, True)
    msgs = bot_turn(session, table, [])
    p = game.fighters["pandora"]
    assert said(msgs, t("tr.pandora.reveal", hero="Pandora", misery=t("pandora.misery.toil"), feathers=1)), msgs
    assert said(msgs, t("tr.pandora.reveal", hero="Pandora", misery=t("pandora.misery.greed"), feathers=3)), msgs
    assert said(msgs, t("tr.pandora.stop_damage", hero="Pandora", feathers=3, damage=3)), msgs
    assert p.hp == 14 - 3 and dial(session, cfg, table, "pandora") == 11


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_the_bot_may_stop_and_says_so(rig, order, monkeypatch):
    session, table, game, fake, cfg = rig
    order.extend([IDX["Toil"]])
    keeps(monkeypatch, False)
    msgs = bot_turn(session, table, [])
    assert said(msgs, t("tr.pandora.stop", hero="Pandora")), msgs
    assert game.fighters["pandora"].hp == 14 and dial(session, cfg, table, "pandora") == 14


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_the_bots_woe_takes_a_kakodaemon_out_of_the_bag_and_puts_it_on_the_table(rig, order, monkeypatch):
    session, table, game, fake, cfg = rig
    order.extend([IDX["Woe"]])
    keeps(monkeypatch, False)
    msgs = bot_turn(session, table, [])
    k = game.fighters["kakodaemon1"]
    assert k.alive and k.hp == 1 and game.board.share_zone(k.pos, game.fighters["pandora"].pos)
    assert table.positions[cfg.nicknames["kakodaemon1"]] == k.pos, msgs           # the table follows the engine: the bot moved it itself
    assert said(msgs, t("tr.pandora.reveal", hero="Pandora", misery=t("pandora.misery.woe"), feathers=0)), msgs


@with_rig("pandora", "hellboy", *BOT_HAND)
def test_the_bots_hope_is_said(rig, order, monkeypatch):
    session, table, game, fake, cfg = rig
    order.extend([IDX["Hope"], IDX["Greed"]])               # Hope looks at Greed and the bot stops
    keeps(monkeypatch, False)
    msgs = bot_turn(session, table, [])
    assert said(msgs, t("tr.pandora.hope_bot", hero="Pandora")), msgs


# ---------------------------------------------------------------- save and resume

def reload(session, table):
    """The session as a save brings it back: a fresh Session loaded from the saved dict, then resumed against the same table."""
    import json
    from sparring.ai_medusa import MedusaAI
    from sparring.session import Session
    from sparring.state import Game
    saved = json.loads(json.dumps(session.to_dict()))
    other = Session(Game.new(session.game.board, seed=3, controllers={}, bot_player=session.bot,
                             heroes=tuple(p.hero.slug for p in session.game.players)), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    other.snap = None
    other.resume()
    return other


@with_rig("hellboy", "pandora", *HAND)
def test_resume_while_the_box_asks_which_misery_asks_it_again(rig):
    session, table, game, fake, cfg = rig
    other = reload(session, table)
    req = other.effect_run.awaiting
    assert req.kind == "effect" and req.extra["tag"] == "misery"
    reveal(other, table, "Pain")
    assert other.effect_run.awaiting.kind == "optional" and other.game.fx.counter_value(1, "box_mask") == 1 << IDX["Pain"]


@with_rig("hellboy", "pandora", *HAND)
def test_resume_in_the_middle_of_the_box_keeps_the_revealed_miseries_and_finishes_the_count(rig):
    session, table, game, fake, cfg = rig
    reveal(session, table, "Toil")
    press(session, table, True)
    reveal(session, table, "Greed")
    assert session.effect_run.awaiting.kind == "optional"             # 2 feathers out, deciding
    other = reload(session, table)
    assert other.game.fx.counter_value(1, "box_mask") == 1 << IDX["Toil"] | 1 << IDX["Greed"]
    assert other.effect_run.awaiting.kind == "optional" and other.effect_run.awaiting.extra["feathers"] == 2
    press(other, table, True)
    reveal(other, table, "Misfortune")
    assert other.effect_run is None and other.game.fighters["pandora"].hp == 14 - 3
