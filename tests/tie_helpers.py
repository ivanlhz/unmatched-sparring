"""Shared by the new heroes' tests: a combat tied on purpose. The rule (Iván, 2026-11-07/08): the DEFENDER wins when its defense
value is >= the attack value; the attacker wins only if it deals combat damage. Every "if you won / lost" reads the engine's result."""
from __future__ import annotations

import dataclasses

from sparring.effects import ops_combat


def plain_rival_card(g, value: int, as_type: str):
    """A text-less card of the rival's hero (Service Pistol), set to `value` and to `as_type` ("attack" or "defense"), in its hand."""
    base = next(c for c in g.players[1].deck if c.title == "Service Pistol")
    g.players[1].deck.remove(base)
    tied = dataclasses.replace(base, value=value, type=as_type)
    g.players[1].hand.append(tied)
    return tied


def record_after_results(monkeypatch) -> list[tuple[int, str]]:
    """Every AFTER run that starts records (owner, result) as the engine hands it to the card: "won" or "lost"."""
    seen: list[tuple[int, str]] = []
    start = ops_combat._start

    def spy(flow, side, ops, moment, card_id):
        run = start(flow, side, ops, moment, card_id)
        if moment == "after":
            seen.append((run.ctx.owner, run.ctx.combat_result))
        return run

    monkeypatch.setattr(ops_combat, "_start", spy)
    return seen
