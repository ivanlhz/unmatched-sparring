"""Robin Hood's life dial and Yennenga's share one GUID in the save (`1fc8df`, the Custom_Model called "Hero Health" in each bag; Nikola Tesla's miniature
has it too, but he is not in the project). TTS keeps GUIDs unique, so with both on the table one of the two dials has a new GUID; the session tells them
apart by the dial's NAME (`session_pieces.resolve_dials`), as for Washington and Bullseye (tests/test_george_washington_dials.py). Here the table holds two
NAMED dials, in both seats and both ways round."""
from __future__ import annotations

import pytest

from test_d3_table_effects import build
from test_donatello_session import SPOTS, AsideTable

SHARED = "1fc8df"
OTHER = SHARED + "x"
NAMES = {"robin": "Robin Hood", "yennenga": "Yennenga"}


def make(tmp_path, bot, human, robin_keeps):
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    assert session.cfg.dials["robin"] == session.cfg.dials["yennenga"] == SHARED
    rows = {"robin": SHARED if robin_keeps else OTHER, "yennenga": OTHER if robin_keeps else SHARED}
    table.dials.pop(SHARED, None)
    for fid, guid in rows.items():
        hp = game.fighters[fid].hp
        table.dials[guid] = {"found": True, "name": NAMES[fid], "value": hp, "max": hp}
        session.dials_written[guid] = hp
    return session, table, game, fake, client, rows


@pytest.mark.parametrize("bot,human", [("robin-hood", "yennenga"), ("yennenga", "robin-hood")])
@pytest.mark.parametrize("robin_keeps", [True, False])
def test_each_dial_is_written_with_its_own_value_by_name(tmp_path, bot, human, robin_keeps):
    session, table, game, fake, client, rows = make(tmp_path, bot, human, robin_keeps)
    try:
        game.fighters["robin"].hp, game.fighters["yennenga"].hp = 5, 9
        assert session._write_dials() is True
        assert table.dials[rows["robin"]]["value"] == 5 and table.dials[rows["yennenga"]]["value"] == 9
        assert session.cfg.dials["robin"] == rows["robin"] and session.cfg.dials["yennenga"] == rows["yennenga"]
        assert session.resolved_dials == {fid: g for fid, g in rows.items() if g != SHARED}
    finally:
        client.close()
        fake.close()


@pytest.mark.parametrize("bot,human", [("robin-hood", "yennenga"), ("yennenga", "robin-hood")])
def test_a_dial_that_cannot_be_told_apart_is_said_and_not_written(tmp_path, bot, human):
    """The second dial is not on the table (still in its bag): the shared GUID holds the first one's, the other is not guessed."""
    session, table, game, fake, client, rows = make(tmp_path, bot, human, True)
    try:
        del table.dials[OTHER]
        game.fighters["robin"].hp, game.fighters["yennenga"].hp = 5, 9
        session.messages = []
        session._write_dials()
        said = [str(m) for m in session.messages]
        assert sum("no lo escribo" in m for m in said) == 1, said
        assert table.dials[SHARED]["value"] == 5 and "yennenga" in session._dial_unresolved
        assert all(g != OTHER for g, _ in table.dial_writes)
    finally:
        client.close()
        fake.close()
