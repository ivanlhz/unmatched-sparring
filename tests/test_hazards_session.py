"""A piece the human moved by hand across a hazard edge: the engine charges it and the chat says so."""
from __future__ import annotations

from sparring.board import edge_key
from test_session import rig  # noqa: F401  (the fixture)


def test_a_human_move_across_a_hazard_is_charged_and_announced(rig, monkeypatch):    # noqa: F811
    session, table, game = rig
    monkeypatch.setattr(game.board, "hazards", {edge_key(1, 2): 1, edge_key(1, 0): 1, edge_key(1, 15): 1})
    hb = game.fighters["hellboy"]
    hp = hb.hp
    table.positions["Hellboy"] = 15
    session.snap = None
    session.sync_positions()
    assert hb.pos == 15 and hb.hp == hp - 1
    said = [str(m) for m in session.messages]
    assert any("(1-15)" in m and "de 18 a 17" in m for m in said), said
    table.positions["Hellboy"] = 1                                        # back over the same edge: free this turn
    session.snap = None
    session.sync_positions()
    assert hb.pos == 1 and hb.hp == hp - 1
