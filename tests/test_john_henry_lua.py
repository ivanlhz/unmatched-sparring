"""John Henry's track tokens on the table, run on the Lua stub: a copy of the stack laid on a space (`place_token_at_space`) and the read
of every track token by its picture (`read_tokens_by_image`)."""
import pytest

from sparring.board import Board
from sparring.tts import lua
from test_effects_bridge import rt, run  # noqa: F401  (rt is a fixture)

BOARD = Board.load("bprd-hq")
KEY = "7E9563244F2F4DA4659AA9164EC339BCDC766607"


def setup_board(rt):
    rt.execute(f"mkobj({{guid = '{lua.board_guid(BOARD)}', type = 'Board', locked = true}})")


def anchor(space):
    x, z = BOARD.spaces[space].local
    return x, z


def token(rt, guid, space, key=KEY, dx=0.0, qty=None):
    x, z = anchor(space)
    extra = f"o.getQuantity = function() return {qty} end;" if qty else ""
    rt.execute(f"local o = mkobj({{guid = '{guid}', type = 'Tile', pos = Vector({x + dx}, 1, {z})}});"
               f"o.getCustomObject = function() return {{image = 'https://x.test/ugc/1/{key}/'}} end; {extra}")


def test_a_copy_of_the_stack_is_laid_on_the_space(rt):
    setup_board(rt)
    rt.execute("mkobj({guid = '8ba84f', type = 'Bag', items = {{guid = 't1'}}, pos = Vector(50, 1, 50)})")
    out = run(rt, lua.place_token_at_space(BOARD, "8ba84f", 3))
    assert out["taken"] == "t1" and out["via"] == "takeObject"
    x, z = anchor(3)
    pos = rt.eval("getObjectFromGUID('t1').getPosition()")
    assert (pos.x, pos.z) == (x, z) and pos.y > 1, "on the space's anchor point, lifted a little"


def test_a_single_token_is_cloned_and_a_missing_source_gives_nothing(rt):
    setup_board(rt)
    rt.execute("mkobj({guid = '8ba84f', type = 'Tile', pos = Vector(50, 1, 50)})")
    assert run(rt, lua.place_token_at_space(BOARD, "8ba84f", 0))["via"] == "clone"
    assert run(rt, lua.place_token_at_space(BOARD, "zzz", 0)) == {"taken": False}


def test_an_unknown_space_is_refused():
    with pytest.raises(ValueError):
        lua.place_token_at_space(BOARD, "8ba84f", 999)


def test_every_track_token_is_read_with_its_space(rt):
    setup_board(rt)
    token(rt, "a1", 2)
    token(rt, "a2", 5, dx=0.05)
    out = run(rt, lua.read_tokens_by_image(BOARD, KEY))
    got = {t["guid"]: t["space"] for t in out["tokens"]}
    assert got == {"a1": 2, "a2": 5} and out["stacks"] == 0
    assert all(t["dist"] < 0.1 for t in out["tokens"])


def test_the_supply_stack_is_counted_and_not_read_as_a_token(rt):
    setup_board(rt)
    token(rt, "supply", 0, qty=9)
    token(rt, "t1", 4)
    out = run(rt, lua.read_tokens_by_image(BOARD, KEY))
    assert [t["guid"] for t in out["tokens"]] == ["t1"] and out["stacks"] == 1


def test_other_pictures_cards_and_bags_are_ignored(rt):
    setup_board(rt)
    token(rt, "other", 1, key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    rt.execute("mkobj({guid = 'bag1', type = 'Bag', pos = Vector(1, 1, 1)})")
    rt.execute("mkobj({guid = 'card1', type = 'Card', cid = 1, owner = 'x', pos = Vector(1, 1, 1)})")
    assert run(rt, lua.read_tokens_by_image(BOARD, KEY)) == {"tokens": [], "stacks": 0}


def test_no_board_on_the_table_reads_nothing(rt):
    assert run(rt, lua.read_tokens_by_image(BOARD, KEY)) == {"no_board": True}


def test_the_image_key_is_validated():
    for bad in ("", "xyz", KEY[:-1], KEY + "0", "G" * 40):
        with pytest.raises(ValueError):
            lua.read_tokens_by_image(BOARD, bad)


def test_both_scripts_are_sendable():
    assert lua.is_sendable(lua.read_tokens_by_image(BOARD, KEY)) and lua.is_sendable(lua.place_token_at_space(BOARD, "8ba84f", 1))
