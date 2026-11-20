"""Who wins a combat when the combat damage is redirected (Ivan 2026-11-20, W3): the attacker wins only if the DEFENDING fighter took
combat damage. Sun Wukong's Golden Chain Mail sends it to the attacker, so the attacker LOST and the defender WON, and every "if you
won / lost the combat" reads it that way (Hellboy's Confront Any Demon or God). Damage that stays on the defender's side (Yennenga's
Archers) is not changed: see docs/heroes/yennenga.md, Pending Ivan."""
from __future__ import annotations

from conftest import give
from sparring.state import Game
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, human_hand, said
from test_e2_human_cards import press, put_adjacent, rig, with_rig  # noqa: F401
from test_sun_wukong_effects import foe_card, mk
from test_sun_wukong_human import bot_attacks, start
from test_effects_combat import pair

CONFRONT = "Confront Any Demon or God"


def boosted(monkeypatch, bonus=2):
    """Hellboy's attacks carry +2 (ANUNG UN RAMA): Confront's 3 becomes 5 against Golden Chain Mail's 4, a blow of 1."""
    monkeypatch.setattr(Game, "attack_bonus_parts", lambda self, f, target=None: [(bonus, "test")] if f.fid == "hellboy" else [])


def test_the_attacker_that_sends_its_damage_back_lost_the_combat_and_confronts_discard_fires(bprd, monkeypatch):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    boosted(monkeypatch)
    confront = foe_card(g, lambda c: c.title == CONFRONT)
    g.players[0].hand.clear()
    foe_card(g, lambda c: c.title == "Wily Fighting", player=0)
    hp_h = h.hp
    pile = len(g.players[0].discard)
    res = g.attack(h, w, confront, give(g, 0, "Golden Chain Mail"))
    assert res.damage == 1 and h.hp == hp_h - 1 and w.hp == 17            # the blow went to the attacker
    assert res.attacker_won is False
    assert len(g.players[0].discard) == pile + 2                          # Golden Chain Mail, plus the card Confront made Wukong discard


def test_a_blow_that_lands_on_the_defender_is_still_won_by_the_attacker(bprd, monkeypatch):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    boosted(monkeypatch, 3)
    confront = foe_card(g, lambda c: c.title == CONFRONT)
    pile = len(g.players[0].discard)
    res = g.attack(h, w, confront, give(g, 0, "Tortoise Form"))            # 6 against 5, no redirection
    assert res.attacker_won is True and w.hp == 16 and len(g.players[0].discard) == pile + 1


@with_rig("hellboy", "sun-wukong", CONFRONT, "B.P.R.D. Training", "Service Pistol", "Right Hand Of Doom")
def test_the_bots_confront_looks_at_the_humans_hand_when_golden_chain_mail_sends_the_damage_back(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    start(rig)
    put_adjacent(game, table, cfg, "wukong", "hellboy")
    boosted(monkeypatch)
    human_hand(table, game, "Golden Chain Mail", "Sly Monkey", "Bewilderment")
    msgs = bot_attacks(session, table, game, CONFRONT, "hellboy", "wukong", "Golden Chain Mail")
    assert game.fighters["hellboy"].hp == 17 and game.fighters["wukong"].hp == 17, msgs
    assert said(msgs, "mira tu mano"), msgs
    assert said(msgs, f"Confront Any Demon or God: roba 1; descartas"), msgs
    assert len(session.pending_discard["cards"]) == 1, session.pending_discard


def lost_events(g, monkeypatch):
    """The `combat_lost` events the engine emits, as (player, fighter id)."""
    from sparring.effects.state import EffectState
    seen, emit = [], EffectState.emit
    def spy(self, name, player=None, *rest, **kw):
        if name == "combat_lost":
            seen.append((player, rest[0].fid))
        return emit(self, name, player, *rest, **kw)
    monkeypatch.setattr(EffectState, "emit", spy)
    return seen


def test_the_attacker_that_took_its_own_blow_is_the_one_who_lost_the_combat(bprd, monkeypatch):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    boosted(monkeypatch)
    seen = lost_events(g, monkeypatch)
    g.attack(h, w, foe_card(g, lambda c: c.title == CONFRONT), give(g, 0, "Golden Chain Mail"))
    assert seen == [(1, "hellboy")]                   # Hellboy's owner lost; Wukong's side won


def test_the_defender_that_took_the_blow_is_the_one_who_lost_the_combat(bprd, monkeypatch):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    boosted(monkeypatch, 3)
    seen = lost_events(g, monkeypatch)
    g.attack(h, w, foe_card(g, lambda c: c.title == CONFRONT), give(g, 0, "Tortoise Form"))
    assert seen == [(0, "wukong")]
