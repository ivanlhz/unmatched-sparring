"""Pandora's Misery deck on the table (Ivan, 22/11/2026): when the HUMAN plays Pandora the real deck of seven Miseries is her Box,
so Prepare takes it out of the bag next to her other pieces; when the bot plays her the Box is virtual and the deck stays in
the bag. Clean table removes a loose Misery deck like any other hero piece."""
from __future__ import annotations

import json

from sparring import play, player_setup
from sparring.tts.hero_table import load_hero_table
from test_jill_gadget_token import RAW
from test_multihero_bridge import config_for
from test_review10 import rt  # noqa: F401
from test_review9 import run

MISERIES = "4581f8"


def _taken(plan):
    return [guids for kind, guids, *_ in plan if MISERIES in guids]


def test_the_human_pandora_gets_her_misery_deck_unpacked(tmp_path):
    plan = play.unpack_plan(config_for(tmp_path, "medusa", "pandora"))
    assert _taken(plan) == [(MISERIES,)]
    row = next(r for r in plan if MISERIES in r[1])
    assert row[0] == "token" and row[2] == load_hero_table("pandora").inner_bag and row[3][0] < 0    # the human's half


def test_the_bot_pandora_leaves_the_box_in_the_bag(tmp_path):
    assert _taken(play.unpack_plan(config_for(tmp_path, "pandora", "medusa"))) == []


def test_clean_table_removes_a_loose_misery_deck(rt):  # noqa: F811
    rt.execute(f"""
local cards = {{}}
for i = 0, 6 do table.insert(cards, {{cid = 17700 + i, guid = 'm' .. i}}) end
realshape(mkobj({{guid = '{MISERIES}', type = 'Deck', name = '', cards = cards, pos = {{x = -9, y = 1, z = 9}},
                 deckcd = {{["177"] = {{FaceURL = 'https://img.test/misery/', BackURL = 'https://img.test/misery-back/'}}}}}}))
""")
    assert rt.globals().getObjectFromGUID(MISERIES) is not None
    run(rt, player_setup.clear_script(RAW))
    assert rt.globals().getObjectFromGUID(MISERIES) is None
