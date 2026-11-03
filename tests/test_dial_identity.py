"""Life dials that share a GUID: the tournament save gives Lobster Johnson's dial (Hellboy's bag) and The Jackalope's (Bigfoot's bag) the
same GUID, `18c384`. TTS keeps GUIDs unique, so with both heroes on the table one of the two dials has a new one; the session tells them
apart by the dial's name (`session_pieces.resolve_dials`), writes and verifies both, and does not claim what it cannot do."""
from __future__ import annotations

import json

import pytest

from sparring.session import Session
from test_d3_table_effects import build
from test_donatello_session import SPOTS, AsideTable

SHARED = "18c384"
OTHER = SHARED + "x"


def split_shared_dials(session, table, game, jackalope_keeps=False):
    """What TTS does with the two dials of `18c384`: the first one out of its bag keeps the GUID and the second gets a new one;
    both carry their name. Returns {fid: (name, guid on the table)}."""
    assert session.cfg.dials["lobster"] == session.cfg.dials["jackalope"] == SHARED
    rows = {"lobster": ("Lobster Johnson", SHARED if not jackalope_keeps else OTHER),
            "jackalope": ("The Jackalope", OTHER if not jackalope_keeps else SHARED)}
    table.dials.pop(SHARED, None)
    for fid, (name, guid) in rows.items():
        hp = game.fighters[fid].hp
        table.dials[guid] = {"found": True, "name": name, "value": hp, "max": hp}
        session.dials_written[guid] = hp
    return rows


def make(tmp_path, bot, human, jackalope_keeps=False):
    """Hellboy and Bigfoot: both sidekick dials are configured with the shared GUID; the table has the first one out of its bag at
    that GUID and the second under a new one (`jackalope_keeps`: the other way round)."""
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS)
    rows = split_shared_dials(session, table, game, jackalope_keeps)
    return session, table, game, fake, cfg, client, rows


@pytest.mark.parametrize("bot,human", [("hellboy", "bigfoot"), ("bigfoot", "hellboy")])
@pytest.mark.parametrize("jackalope_keeps", [False, True])
def test_both_dials_are_written_with_their_own_values(tmp_path, bot, human, jackalope_keeps):
    session, table, game, fake, cfg, client, rows = make(tmp_path, bot, human, jackalope_keeps)
    try:
        game.fighters["lobster"].hp, game.fighters["jackalope"].hp = 3, 4
        assert session._write_dials() is True
        assert table.dials[rows["lobster"][1]]["value"] == 3 and table.dials[rows["jackalope"][1]]["value"] == 4
        written = dict(table.dial_writes)
        assert written[rows["lobster"][1]] == 3 and written[rows["jackalope"][1]] == 4
        assert session.cfg.dials["lobster"] == rows["lobster"][1] and session.cfg.dials["jackalope"] == rows["jackalope"][1]
        assert session.resolved_dials == {fid: g for fid, (_, g) in rows.items() if g != SHARED}
        assert table.count("find_dials_by_name") == 1
        session._write_dials()
        assert table.count("find_dials_by_name") == 1, "a resolved dial is not looked for again"
    finally:
        client.close()
        fake.close()


def test_a_dial_that_does_not_show_what_was_written_is_caught(tmp_path):
    session, table, game, fake, cfg, client, rows = make(tmp_path, "hellboy", "bigfoot")
    try:
        game.fighters["jackalope"].hp = 2
        table.dial_ignores_writes = True                         # the table keeps both dials as they are
        session.messages = []
        assert session._write_dials() is False
        said = " ".join(str(m) for m in session.messages)
        assert "Jackalope deberia marcar 2" in said, said
    finally:
        client.close()
        fake.close()


def test_the_mismatch_of_only_one_of_the_two_is_named(tmp_path):
    session, table, game, fake, cfg, client, rows = make(tmp_path, "hellboy", "bigfoot")
    try:
        game.fighters["lobster"].hp, game.fighters["jackalope"].hp = 3, 4
        real = table.do_set_health_dials

        def stubborn(s):                                          # the Jackalope's dial refuses the write
            out = real(s)
            table.dials[OTHER]["value"] = 99
            return out
        table.do_set_health_dials = stubborn
        session.messages = []
        assert session._write_dials() is False
        said = " ".join(str(m) for m in session.messages)
        assert "Jackalope deberia marcar 4" in said and "Lobster deberia" not in said, said
        assert table.dials[SHARED]["value"] == 3
    finally:
        client.close()
        fake.close()


def test_a_dial_that_cannot_be_told_apart_is_said_and_not_written(tmp_path):
    """The second dial is not on the table (still in its bag): the shared GUID holds Lobster's, the Jackalope's is not guessed."""
    session, table, game, fake, cfg, client, rows = make(tmp_path, "hellboy", "bigfoot")
    try:
        del table.dials[OTHER]
        game.fighters["lobster"].hp, game.fighters["jackalope"].hp = 3, 4
        session.messages = []
        session._write_dials()
        said = [str(m) for m in session.messages]
        assert sum("I do not write or check it" in m or "no lo escribo" in m for m in said) == 1, said
        assert table.dials[SHARED]["value"] == 3 and "jackalope" in session._dial_unresolved
        assert all(g != OTHER for g, _ in table.dial_writes)
        session.messages = []
        session._write_dials()
        assert not any("no lo escribo" in str(m) for m in session.messages), "said once"
    finally:
        client.close()
        fake.close()


def test_two_candidates_by_name_are_not_guessed(tmp_path):
    session, table, game, fake, cfg, client, rows = make(tmp_path, "hellboy", "bigfoot")
    try:
        table.dials[OTHER + "y"] = dict(table.dials[OTHER])          # a second object named The Jackalope
        session._write_dials()
        assert "jackalope" in session._dial_unresolved and session.cfg.dials["jackalope"] == SHARED
        assert all(g == SHARED for g, _ in [w for w in table.dial_writes if w[0] in (SHARED, OTHER, OTHER + "y")])
    finally:
        client.close()
        fake.close()


def test_the_resolution_is_saved_and_does_not_change_the_identity_of_the_save(tmp_path):
    session, table, game, fake, cfg, client, rows = make(tmp_path, "hellboy", "bigfoot")
    try:
        before = session.fingerprint()
        session._write_dials()
        saved = session.to_dict()
        assert saved["resolved_dials"] == {"jackalope": OTHER} or saved["resolved_dials"] == {"lobster": OTHER}
        assert session.fingerprint() == before
        json.dumps(saved)
    finally:
        client.close()
        fake.close()
