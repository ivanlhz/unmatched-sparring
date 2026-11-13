"""George Washington's life dial and Bullseye's share one GUID in the save (`166320`, both 14 hit points). TTS keeps GUIDs unique, so with both on the
table one of the two dials has a new GUID; the session tells them apart by the dial's NAME (`session_pieces.resolve_dials`), as for Lobster Johnson and The
Jackalope (tests/test_dial_identity.py). Here the table holds two NAMED dials, in both seats and both ways round."""
from __future__ import annotations

import pytest

from test_d3_table_effects import build
from test_donatello_session import SPOTS, AsideTable

SHARED = "166320"
OTHER = SHARED + "x"
NAMES = {"washington": "George Washington", "bullseye": "Bullseye"}


def make(tmp_path, bot, human, washington_keeps):
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    assert session.cfg.dials["washington"] == session.cfg.dials["bullseye"] == SHARED
    rows = {"washington": SHARED if washington_keeps else OTHER, "bullseye": OTHER if washington_keeps else SHARED}
    table.dials.pop(SHARED, None)
    for fid, guid in rows.items():
        hp = game.fighters[fid].hp
        table.dials[guid] = {"found": True, "name": NAMES[fid], "value": hp, "max": hp}
        session.dials_written[guid] = hp
    return session, table, game, fake, client, rows


@pytest.mark.parametrize("bot,human", [("george-washington", "bullseye"), ("bullseye", "george-washington")])
@pytest.mark.parametrize("washington_keeps", [True, False])
def test_each_dial_is_written_with_its_own_value_by_name(tmp_path, bot, human, washington_keeps):
    session, table, game, fake, client, rows = make(tmp_path, bot, human, washington_keeps)
    try:
        game.fighters["washington"].hp, game.fighters["bullseye"].hp = 5, 9
        assert session._write_dials() is True
        assert table.dials[rows["washington"]]["value"] == 5 and table.dials[rows["bullseye"]]["value"] == 9
        assert session.cfg.dials["washington"] == rows["washington"] and session.cfg.dials["bullseye"] == rows["bullseye"]
        assert session.resolved_dials == {fid: g for fid, g in rows.items() if g != SHARED}
    finally:
        client.close()
        fake.close()
