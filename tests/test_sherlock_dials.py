"""Sherlock Holmes' and Dr. Watson's life dials share their GUIDs with Achilles' and Patroclus' in the save (`feaa22` Holmes / Achilles, `ec605e` Watson /
Patroclus; each is a Custom_Model named after its fighter). TTS keeps GUIDs unique, so with both heroes on the table two of the four dials have new GUIDs; the
session tells them apart by the dial's NAME (`session_pieces.resolve_dials`), as for Robin Hood and Yennenga (tests/test_robin_hood_dials.py). Here the table
holds four NAMED dials, in both seats and every way round."""
from __future__ import annotations

import pytest

from test_d3_table_effects import build
from test_donatello_session import SPOTS, AsideTable

HOLMES_GUID, WATSON_GUID = "feaa22", "ec605e"
NAMES = {"holmes": "Sherlock Holmes", "watson": "Dr. Watson", "achilles": "Achilles", "patroclus": "Patroclus"}
SHARED = {"holmes": HOLMES_GUID, "achilles": HOLMES_GUID, "watson": WATSON_GUID, "patroclus": WATSON_GUID}


def make(tmp_path, bot, human, sherlock_keeps):
    """`sherlock_keeps`: the fighters of Sherlock that keep the configured GUID (the other hero's dial got a new one)."""
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    assert all(session.cfg.dials[fid] == guid for fid, guid in SHARED.items())
    rows = {}
    twin = {"achilles": "holmes", "patroclus": "watson"}
    for fid, guid in SHARED.items():
        keeps = fid in sherlock_keeps if fid in ("holmes", "watson") else twin[fid] not in sherlock_keeps
        rows[fid] = guid if keeps else guid + "x"
    for guid in (HOLMES_GUID, WATSON_GUID):
        table.dials.pop(guid, None)
    for fid, guid in rows.items():
        hp = game.fighters[fid].hp
        table.dials[guid] = {"found": True, "name": NAMES[fid], "value": hp, "max": hp}
        session.dials_written[guid] = hp
    return session, table, game, fake, client, rows


@pytest.mark.parametrize("bot,human", [("sherlock-holmes", "achilles"), ("achilles", "sherlock-holmes")])
@pytest.mark.parametrize("sherlock_keeps", [("holmes", "watson"), (), ("holmes",), ("watson",)])
def test_each_dial_is_written_with_its_own_value_by_name(tmp_path, bot, human, sherlock_keeps):
    session, table, game, fake, client, rows = make(tmp_path, bot, human, sherlock_keeps)
    try:
        values = {"holmes": 5, "watson": 3, "achilles": 9, "patroclus": 2}
        for fid, hp in values.items():
            game.fighters[fid].hp = hp
        assert session._write_dials() is True
        for fid, hp in values.items():
            assert table.dials[rows[fid]]["value"] == hp, fid
            assert session.cfg.dials[fid] == rows[fid]
        assert session.resolved_dials == {fid: g for fid, g in rows.items() if g != SHARED[fid]}
    finally:
        client.close()
        fake.close()
