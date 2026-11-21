"""The bot swaps the human's two miniatures itself (Under Achilles' Helm); when the table cannot move them, the engine keeps the swap
and the human puts the pieces there by hand as a placement: a stale table read never undoes the swap, nor reads departures / hazards."""
from __future__ import annotations

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import human_hand, said
from test_e2_human_cards import press, put_adjacent, rig, with_rig  # noqa: F401
from test_achilles_human import bot_attacks, TRAINING


def _failed_swap(session, table, game, cfg):
    put_adjacent(game, table, cfg, "hellboy", "achilles")
    patroclus, achilles = game.fighters["patroclus"], game.fighters["achilles"]
    far = next(s for s in sorted(game.board.spaces, reverse=True) if all(f.pos != s for f in game.fighters.values() if f.alive))
    patroclus.pos = far
    table.positions[cfg.nicknames["patroclus"]] = far
    at = achilles.pos
    table.move_fails.update(cfg.session_config().pieces[f] for f in ("achilles", "patroclus"))
    events = []
    orig = session._departed_by_hand
    session._departed_by_hand = lambda f, frm, moved=True: (events.append((f.fid, frm, moved)), orig(f, frm, moved=moved))[1]
    human_hand(table, game, "Under Achilles' Helm", "Feint")
    msgs = bot_attacks(session, table, game, "Excalibur", "achilles", "Under Achilles' Helm")
    msgs = press(session, table, True)
    return achilles, patroclus, far, at, events, msgs


@with_rig("hellboy", "achilles", "Excalibur", TRAINING)
def test_failed_table_swap_survives_an_early_sync_and_the_hand_swap_is_silent(rig):
    session, table, game, fake, cfg = rig
    achilles, patroclus, far, at, events, msgs = _failed_swap(session, table, game, cfg)
    assert said(msgs, "no he podido mover su miniatura"), msgs
    assert (achilles.pos, patroclus.pos) == (far, at)
    hp = (achilles.hp, patroclus.hp)
    click(session, table, Event.END_ACTION)                       # a sync before the human swaps by hand
    session.sync_positions()
    assert (achilles.pos, patroclus.pos) == (far, at), "the stale table undid the engine swap"
    assert not events and not session.illegal_hand_moves
    assert (achilles.hp, patroclus.hp) == hp                      # no hazard charge
    table.move_fails.clear()                                       # the human swaps them by hand
    table.positions[cfg.nicknames["achilles"]] = far
    table.positions[cfg.nicknames["patroclus"]] = at
    session.sync_positions()
    assert (achilles.pos, patroclus.pos) == (far, at)
    assert not events and not session.table_stale and (achilles.hp, patroclus.hp) == hp


@with_rig("hellboy", "achilles", "Excalibur", TRAINING)
def test_failed_table_swap_then_a_wrong_space_is_a_placement_not_a_departure(rig):
    session, table, game, fake, cfg = rig
    achilles, patroclus, far, at, events, msgs = _failed_swap(session, table, game, cfg)
    other = next(s for s in sorted(game.board.spaces) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["achilles"]] = other
    session.sync_positions()
    assert achilles.pos == other and not any(moved for _, _, moved in events)      # placement semantics: nothing is a hand move
