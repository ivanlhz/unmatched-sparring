"""Third live run of the pre-game gate: Iván emptied both inner bags onto the table by hand and left the decks in clusters
away from the deck spots. One press must gather them (the real Lua runs under lupa on the shape of the real save)."""
from __future__ import annotations

import dataclasses

import pytest

from sparring import table_reset
from sparring.i18n import t
from sparring.tts import lua
from test_review10 import BDECK, BOT, HDECK, HUMAN, SCOPE, rt, run  # noqa: F401

EVERYWHERE = dataclasses.replace(SCOPE, everywhere=True)


def dump_by_hand(rt, guid="00dc9a", new_guid="hand01", x=-9.0, z=1.0, face_down=True):
    """The deck as TTS leaves it when it is taken out of a bag by hand: elsewhere, with a GUID of its own."""
    rt.execute(f"""
local d = getObjectFromGUID('{guid}')
d.guid = '{new_guid}'
d.pos = {{x = {x}, y = 1, z = {z}}}
d.is_face_down = {'true' if face_down else 'false'}
d.flip = function() d.is_face_down = not d.is_face_down end
""")


def test_a_deck_dumped_far_from_its_spot_is_seen_by_the_plan(rt):
    dump_by_hand(rt)
    plan = run(rt, lua.reset_plan([(*HDECK[:3], HUMAN)], scope=EVERYWHERE))
    assert plan == [{"deck": False, "loose": 1, "total": 30}]


def test_a_deck_dumped_far_from_its_spot_is_gathered_face_down_at_the_spot_and_shuffled(rt):
    dump_by_hand(rt)
    res = run(rt, lua.reset_deck(HDECK[0], HDECK[1], lua.HUMAN_CARD_IDS, identity=HUMAN, scope=EVERYWHERE))
    assert res == {"deck": True, "quantity": 30}
    d = rt.globals().getObjectFromGUID("hand01")
    assert (d.pos.x, d.pos.z) == (HDECK[1][0], HDECK[1][1]) and d.is_face_down is True and d.shuffled is True


def test_a_face_up_deck_dumped_by_hand_is_turned_face_down(rt):
    dump_by_hand(rt, face_down=False)
    res = run(rt, lua.reset_deck(HDECK[0], HDECK[1], lua.HUMAN_CARD_IDS, identity=HUMAN, scope=EVERYWHERE))
    assert res == {"deck": True, "quantity": 30}
    assert rt.globals().getObjectFromGUID("hand01").is_face_down is True


def test_a_deck_and_loose_cards_dumped_in_a_cluster_become_one_deck_at_the_spot(rt):
    dump_by_hand(rt)
    rt.execute("""
local d = getObjectFromGUID('hand01')
for k = 1, 4 do
  local c = table.remove(d.cards, 1)
  realshape(mkobj({guid = c.guid, type = 'Card', cid = c.cid, owner = 'hellboy', cd = c.cd, pos = {x = -9 + k, y = 1, z = 2}}))
end
""")
    res = run(rt, lua.reset_deck(HDECK[0], HDECK[1], lua.HUMAN_CARD_IDS, identity=HUMAN, scope=EVERYWHERE))
    assert res == {"deck": True, "quantity": 30}
    assert [o.guid for o in rt.globals().getObjects().values() if o.type == "Card"] == []


def test_a_deck_at_its_spot_is_not_moved(rt):
    res = run(rt, lua.reset_deck(*HDECK[:3], identity=HUMAN, scope=SCOPE))
    assert res == {"deck": True, "quantity": 30}
    assert rt.globals().getObjectFromGUID("00dc9a").moved_count is None


def test_the_other_side_is_gathered_too_from_its_own_cluster(rt):
    dump_by_hand(rt, guid="d42056", new_guid="hand02", x=14.0, z=-8.0)
    res = run(rt, lua.reset_deck(BDECK[0], BDECK[1], lua.BOT_CARD_IDS, identity=BOT, scope=EVERYWHERE))
    assert res == {"deck": True, "quantity": 30}
    d = rt.globals().getObjectFromGUID("hand02")
    assert (d.pos.x, d.pos.z) == BDECK[1]


def test_the_failure_in_the_gate_names_the_gate_button_not_the_restart_one():
    from sparring.session import Session
    assert t("err.reset_gather", button=table_reset.CleaningSession._reset_button(None), n=30, side="x", found=0).endswith(
        t("panel.prep"))
    assert Session._reset_button(None) == t("panel.restart")
    assert t("panel.prep") != t("panel.restart")
