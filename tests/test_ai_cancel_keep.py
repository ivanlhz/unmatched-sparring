"""Matchup-aware keep value: a card that cancels the rival's card effects (Misdirection, Feint) is kept in proportion to how much
the rival's deck lives on effects, and a BOOSTED WITH hit that does not kill is worth less on a healthy target."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.ai_medusa import MedusaAI, boost_effect_value, cancels_effects, effect_reliance, keep_value
from test_houdini_ai import mk


def test_cancel_cards_are_read_from_the_effects_data(bprd):
    g = mk(bprd)
    assert cancels_effects(give(g, 0, "Misdirection"))
    assert not cancels_effects(give(g, 0, "Flourish"))


def test_reliance_follows_the_rival_deck(bprd):
    assert effect_reliance(mk(bprd, "hellboy"), 0) > 0.6
    assert effect_reliance(mk(bprd, "leonardo"), 0) < 0.2


def test_misdirection_is_kept_against_effect_heavy_decks_only(bprd):
    heavy, vanilla = mk(bprd, "hellboy"), mk(bprd, "leonardo")
    h, v = give(heavy, 0, "Misdirection"), give(vanilla, 0, "Misdirection")
    assert keep_value(h, [h], effect_reliance(heavy, 0)) > keep_value(v, [v], effect_reliance(vanilla, 0)) + 1.0
    assert keep_value(v, [v], effect_reliance(vanilla, 0)) < keep_value(v, [v]) + 0.2


def test_chip_damage_boost_is_worth_less_at_high_hp_but_a_kill_keeps_full_value(bprd):
    g = mk(bprd)
    card = give(g, 0, "Misdirection")
    hb = g.fighters["hellboy"]
    healthy = boost_effect_value(g, 0, card)
    hb.hp = 6
    hurt = boost_effect_value(g, 0, card)
    hb.hp = 2
    lethal = boost_effect_value(g, 0, card)
    assert healthy < hurt < lethal
    assert lethal > 2 * healthy


def test_the_bot_keeps_misdirection_instead_of_a_chip_maneuver_boost_vs_hellboy(bprd):
    g = mk(bprd, "hellboy")
    give(g, 0, "Misdirection")
    for c in ("Excalibur", "Service Pistol"):
        give(g, 1, c)
    act = MedusaAI(0).plan(g)
    assert act.boost is None or act.boost.title != "Misdirection"


def test_the_bot_still_spends_misdirection_for_the_lethal_blow(bprd):
    g = mk(bprd, "hellboy")
    card = give(g, 0, "Misdirection")
    g.fighters["hellboy"].hp = 2
    ai = MedusaAI(0)
    assert boost_effect_value(g, 0, card) - keep_value(card, g.players[0].hand, effect_reliance(g, 0)) > 0
