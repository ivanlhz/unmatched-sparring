"""Piece identity: a miniature is found by GUID and checked by name (docs/card-identity.md, "Piece identity").

The tournament save gives Abe Sapien's and Donatello's miniatures the same GUID (4fdf31). TTS keeps GUIDs unique: the second
one out of its bag gets a new one. `build` models that (tests/test_d3_table_effects.py, `reassigned_guid`): the data still
says 4fdf31 for both, the table has one of them under another GUID."""
from __future__ import annotations

import json
from collections import defaultdict

import pytest

from sparring import session_pieces as piece_id
from sparring.tts.hero_table import TTS_DIR, load_hero_table
from test_d3_table_effects import build
from test_donatello_session import SPOTS, AsideTable

SHARED = "4fdf31"
PAIR = [("abe-sapien", "donatello"), ("donatello", "abe-sapien")]


def reassigned_fid(session, table, cfg) -> str:
    """The fighter whose piece TTS gave a new GUID: its configured GUID is the other's."""
    return next(fid for fid, v in table.pieces.items() if v != session.cfg.pieces[fid])


def make(tmp_path, bot, human, **kw):
    return build(tmp_path, bot, human, (), table_cls=AsideTable, **SPOTS, **kw)


def check(session) -> None:
    """What start / resume / adopt do: arm the check; the step's first table read carries it out."""
    session._check_pieces()
    session._table_pieces()


def test_every_guid_in_the_hero_data_belongs_to_one_hero_except_the_known_collision():
    """Pieces, dials, decks, tokens and counter dials of all the heroes."""
    owners = defaultdict(set)
    for path in TTS_DIR.glob("*.json"):
        for g in load_hero_table(path.stem).all_guids():
            owners[g].add(path.stem)
    shared = {g: sorted(s) for g, s in owners.items() if len(s) > 1}
    assert shared == {SHARED: ["abe-sapien", "donatello"]}


def test_plain_name_strips_tts_colour_tags():
    assert piece_id.plain_name("[6f2176]Donatello") == "donatello"
    assert piece_id.plain_name("[b][ff0000]Abe  Sapien[-][/b]") == "abe sapien"
    assert piece_id.plain_name(None) == ""


@pytest.mark.parametrize("bot,human", PAIR)
def test_the_start_up_check_follows_the_piece_that_carries_the_name(tmp_path, bot, human):
    session, table, game, fake, cfg, client = make(tmp_path, bot, human)
    try:
        table.name_prefix = "[6f2176]"
        other = reassigned_fid(session, table, cfg)
        wrong = session.cfg.pieces[other]
        assert wrong == SHARED and table.pieces[other] != SHARED
        owner = next(f for f in session.cfg.pieces if f != other and session.cfg.pieces[f] == SHARED)
        assert piece_id.problems(session, piece_id.read(session)) == {other: owner}
        session.messages = []
        check(session)
        assert session.cfg.pieces[other] == table.pieces[other] != SHARED
        assert session.cfg.pieces[owner] == SHARED
        assert session.resolved_pieces == {other: [table.pieces[other]]}
        said = [str(m) for m in session.messages]
        assert sum(table.pieces[other] in m for m in said) == 1, said                     # one line for the resolution
        assert sum(SHARED in m and "piece" not in m.lower() for m in said) >= 1           # and the shared-GUID warning
        assert piece_id.problems(session, piece_id.read(session)) == {}
        # both pieces are tracked apart: moving one never moves the other
        session.sync_positions()
        assert {f: game.fighters[f].pos for f in (other, owner)} == {f: table.positions[cfg.nicknames[f]] for f in (other, owner)}
        free = sorted(game.board.spaces)[7]
        table.positions[cfg.nicknames[other]] = free
        session.snap = None
        session.sync_positions()
        assert game.fighters[other].pos == free and game.fighters[owner].pos != free
        assert session.configured_pieces[other] == [SHARED]                               # the data side is untouched
    finally:
        client.close()
        fake.close()


def test_a_collision_met_in_mid_game_is_resolved_on_the_first_table_read(tmp_path):
    session, table, game, fake, cfg, client = make(tmp_path, "abe-sapien", "donatello")
    try:
        other = reassigned_fid(session, table, cfg)
        found = session._table_pieces()
        assert found[other]["guid"] == table.pieces[other] and found[other]["name"] == cfg.nicknames[other]
        assert table.count("find_pieces_by_name") == 1
        session._table_pieces()
        assert table.count("find_pieces_by_name") == 1, "a resolved piece is not looked for again"
        assert any(table.pieces[other] in str(m) for m in session.messages)
    finally:
        client.close()
        fake.close()


def test_a_piece_nobody_can_name_is_not_guessed(tmp_path):
    """The other hero's miniature sits at the GUID and no loose object carries this hero's name (still in its bag):
    the GUID stays, one warning, no second search."""
    session, table, game, fake, cfg, client = make(tmp_path, "abe-sapien", "donatello")
    try:
        other = reassigned_fid(session, table, cfg)
        table.positions.pop(cfg.nicknames[other])                                          # not out of its bag yet
        check(session)
        assert session.cfg.pieces[other] == SHARED and session.resolved_pieces == {}
        assert sum("candidat" in str(m) for m in session.messages) == 1
        session.messages = []
        session._table_pieces()
        session._table_pieces()
        assert table.count("find_pieces_by_name") == 1 and not session.messages
    finally:
        client.close()
        fake.close()


@pytest.mark.parametrize("bot,human", PAIR)
def test_resume_keeps_the_resolved_guid(tmp_path, bot, human):
    first, table, game, fake, cfg, client = make(tmp_path, bot, human)
    try:
        other = reassigned_fid(first, table, cfg)
        check(first)
        saved = json.loads(json.dumps(first._to_dict(None)))
        assert saved["resolved_pieces"] == {other: [table.pieces[other]]}
        (tmp_path / "again").mkdir()
        resumed, table2, _, fake2, cfg2, client2 = make(tmp_path / "again", bot, human)
        try:
            table2.pieces, table2.guid_name = table.pieces, table.guid_name
            table2.positions = table.positions
            assert resumed.cfg.pieces[other] == SHARED
            resumed.load_dict(saved)                                  # same table (configured GUIDs), so the fingerprint matches
            assert resumed.cfg.pieces[other] == table.pieces[other]
            searches = table2.count("find_pieces_by_name")
            check(resumed)
            assert table2.count("find_pieces_by_name") == searches, "the saved GUID already holds the right piece"
            assert resumed.resolved_pieces == {other: [table.pieces[other]]}
            assert resumed.fingerprint()["config_hash"] == first.fingerprint()["config_hash"]
        finally:
            client2.close()
            fake2.close()
    finally:
        client.close()
        fake.close()


def test_an_untouched_pair_is_not_searched_for(tmp_path):
    session, table, game, fake, cfg, client = make(tmp_path, "medusa", "donatello")
    try:
        check(session)
        assert table.count("find_pieces_by_name") == 0 and session.resolved_pieces == {}
        assert not any(SHARED in str(m) for m in session.messages)
    finally:
        client.close()
        fake.close()


def test_the_name_search_builder_is_read_only_and_safe():
    from sparring import play
    from sparring.tts import lua
    s = lua.find_pieces_by_name(["abe sapien", "donatello"])
    assert lua.is_sendable(s) and s.startswith("-- sparring:find_pieces_by_name") and "find_pieces_by_name" in play.READ_ONLY_TAGS
    with pytest.raises(ValueError):
        lua.find_pieces_by_name(['x"]=true} os.exit() --'])
