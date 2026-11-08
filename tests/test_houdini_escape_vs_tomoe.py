"""A human Houdini who PLACES himself with ESCAPE ARTIST (boosted Maneuver) out of the bot Tomoe's zone: a placement is no departure,
so ATTACK OF OPPORTUNITY must not fire (Iván, 2026-11-08), whichever order the boost and End action come in."""
from __future__ import annotations

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import human_hand, said
from test_e2_human_cards import rig, with_rig  # noqa: F401
from test_houdini_human import spend
from test_tomoe_gozen_human import put_at, zone_exit


def stage(rig):
    session, table, game, fake, cfg = rig
    tomoe, houdini = game.fighters["tomoe"], game.fighters["houdini"]
    inside, outside = zone_exit(game, tomoe.pos)
    put_at(game, table, cfg, "houdini", inside)
    human_hand(table, game, "Flourish", "Sleight of Hand")
    return session, table, game, cfg, houdini, outside


@with_rig("tomoe-gozen", "houdini")
def test_boost_button_then_end_action_places_without_attack_of_opportunity(rig):
    session, table, game, cfg, houdini, outside = stage(rig)
    hp = houdini.hp
    click(session, table, Event.MANEUVER)
    spend(table, game, "Flourish")
    msgs = click(session, table, Event.MANEUVER_BOOST)
    assert said(msgs, "ESCAPE ARTIST"), msgs
    table.positions[cfg.nicknames["houdini"]] = outside
    msgs = click(session, table, Event.END_ACTION)
    assert houdini.pos == outside and houdini.hp == hp and not said(msgs, "OPPORTUNITY"), msgs


@with_rig("tomoe-gozen", "houdini")
def test_boost_card_in_the_pile_then_end_action_places_without_attack_of_opportunity(rig):
    session, table, game, cfg, houdini, outside = stage(rig)
    hp = houdini.hp
    click(session, table, Event.MANEUVER)
    spend(table, game, "Flourish")
    table.positions[cfg.nicknames["houdini"]] = outside               # no Boost button: End action reads positions first
    msgs = click(session, table, Event.END_ACTION)
    assert houdini.pos == outside and houdini.hp == hp and not said(msgs, "OPPORTUNITY"), msgs
