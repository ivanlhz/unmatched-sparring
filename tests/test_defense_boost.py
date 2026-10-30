"""A human defense with a free BOOST (Out Of Time: "DURING COMBAT: You may BOOST this card") lets the human boost
before the damage is computed (Ivan, 30/10: the bot resolved Liz's attack and Koschei fell without the chance)."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, said
from test_e2_human_cards import put_adjacent, rig, with_rig  # noqa: F401

LIZ_HAND = ("B.P.R.D. Training", "Evade", "Pyrotechnics", "Rekindle", "Searing Clarity")


def liz_attacks_koschei(session, table, game, cfg):
    put_adjacent(game, table, cfg, "koschei", "liz")
    human_hand(table, game, "Out Of Time", "Exploit", "Iron Teeth")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
    bot_turn(session, table, [Act("attack", fid="liz", target="koschei", card=training)])
    oot = card_ids(game, 1, "Out Of Time")[0]
    table.face_down = [{"id": oot, "guid": f"h{oot}"}]
    table.human_hand.remove(oot)
    table.human_count -= 1
    return click(session, table, Event.REVEAL)


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND)
def test_a_boost_on_your_defense_is_asked_before_the_damage_and_counts(rig):
    session, table, game, fake, cfg = rig
    koschei = game.fighters["koschei"]
    msgs = liz_attacks_koschei(session, table, game, cfg)
    assert session.pending is not None and session.pending.wait is not None and koschei.hp == 3
    assert said(msgs, "Out Of Time revelado: si quieres potenciar") and not said(msgs, "Combate:")
    exploit = card_ids(game, 1, "Exploit")[0]
    table.human_hand.remove(exploit)
    table.human_discard.append(exploit)
    table.human_count -= 1
    msgs = click(session, table, Event.BOOST)
    combat = next(m for m in msgs if m.startswith("Combate:"))
    assert "total 5" in combat and "Dano 0" in combat, combat
    assert koschei.hp == 3 and koschei.alive and session.pending is None
    assert exploit in [c.card_id for c in game.players[1].discard]


@with_rig("liz-sherman", "baba-yaga", *LIZ_HAND)
def test_declining_the_boost_on_your_defense_resolves_the_combat_as_before(rig):
    session, table, game, fake, cfg = rig
    liz_attacks_koschei(session, table, game, cfg)
    assert session.pending.wait is not None
    msgs = click(session, table, Event.NO_BOOST)
    combat = next(m for m in msgs if m.startswith("Combate:"))
    assert "Dano 1" in combat and game.fighters["koschei"].hp == 2 and session.pending is None
