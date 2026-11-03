"""Review of the deck zones: a stacked discard Deck next to a draw deck must never be taken for it (by hint, by GUID or by
spot), a deck zone only claims what is face down, and a zone GUID that is no zone is refused."""
from __future__ import annotations

import dataclasses

import pytest

from sparring.hero_detect import TableReading, detected_decks
from sparring.session import SessionConfig, SessionError
from sparring.tts import lua
from test_deck_zone import SLUGS, SPOT, _pile, dealt, zone  # noqa: F401
from test_review10 import BOT, HDECK, HUMAN, rt, run  # noqa: F401
from test_session import rig  # noqa: F401

pytest.importorskip("lupa")


def discard_stack(runtime, x, z):
    runtime.execute(f"""
local c = {{}}
for i = 0, 14 do table.insert(c, {{cid = 17640 + i, guid = 'dd' .. i, owner = 'medusa'}}) end
realshape(mkobj({{guid = 'discdk', type = 'Deck', cards = c, is_face_down = false, pos = {{x = {x}, y = 1, z = {z}}},
                 deckcd = {{["176"] = {{FaceURL = MF, BackURL = MB}}}}}}))
getObjectFromGUID('discdk').deal = function(k, color) DEALT = k; DEALT_FROM = 'discdk' end
""")


def test_a_face_up_stacked_discard_is_not_found_by_guid_or_by_spot_on_the_bot_side(rt):
    rt.execute("getObjectFromGUID('d42056').destruct()")
    discard_stack(rt, 15, 8)
    res = run(rt, lua.deck_identities([(["a3afc4", "discdk"], SPOT, lua.BOT_CARD_IDS)]))
    assert res[0]["found"] is False
    assert run(rt, lua.deal_cards("discdk", 5, "Green", spot=SPOT, identity=BOT)) == {"dealt": 0}
    assert dealt(rt) == (None, None)


def test_a_face_up_stacked_discard_next_to_the_human_deck_is_not_found_either(rt):
    rt.execute("getObjectFromGUID('00dc9a').destruct()")
    rt.execute("""
local c = {}
for i = 0, 14 do table.insert(c, {cid = 19700 + i, guid = 'hd' .. i, owner = 'hellboy', cd = {["197"] = {FaceURL = HF, BackURL = HB}}}) end
realshape(mkobj({guid = 'hdisc', type = 'Deck', cards = c, is_face_down = false, pos = {x = -6.0, y = 1, z = 13.67},
                 deckcd = {["197"] = {FaceURL = HF, BackURL = HB}}}))
""")
    res = run(rt, lua.deck_identities([(["00dc9a", "hdisc"], HDECK[1], lua.HUMAN_CARD_IDS)]))
    assert res[0]["found"] is False
    assert run(rt, lua.deal_cards("hdisc", 1, "White", spot=HDECK[1], id_range=lua.HUMAN_CARD_IDS,
                                  identity=HUMAN)) == {"dealt": 0}


def test_the_configured_guid_wins_over_a_hint_when_it_is_a_face_down_deck(rt):
    rt.execute("""
local c = {}
for i = 0, 7 do table.insert(c, {cid = 17650 + i, guid = 'hh' .. i, owner = 'medusa'}) end
realshape(mkobj({guid = 'hint01', type = 'Deck', cards = c, pos = {x = 8, y = 1, z = 14},
                 deckcd = {["176"] = {FaceURL = MF, BackURL = MB}}}))
""")
    assert run(rt, lua.deck_identities([(["d42056", "hint01"], SPOT, lua.BOT_CARD_IDS)]))[0]["guid"] == "d42056"
    assert run(rt, lua.deck_identities([(["gone01", "hint01"], SPOT, lua.BOT_CARD_IDS)]))[0]["guid"] == "hint01"


def test_detection_only_offers_a_pile_that_is_the_draw_deck():
    stack = _pile("medusa", "discdk", 14.0, 8.0)
    stack["counts"] = [15 if s == "medusa" else 0 for s in SLUGS]
    deck = _pile("medusa", "drawdk", 8.58, 15.56)
    deck["counts"] = [8 if s == "medusa" else 0 for s in SLUGS]
    heroes, spots = ("medusa", "hellboy"), ((7.28, 13.93), (-4.6, 13.67))
    assert detected_decks(TableReading([stack, deck], {}, SLUGS), heroes, *spots) == {"bot": "drawdk"}
    assert detected_decks(TableReading([stack], {}, SLUGS), heroes, *spots) == {}, "a pile far from the spot is no deck"
    assert detected_decks(TableReading([{**deck, "down": False}], {}, SLUGS), heroes, *spots) == {}, "face up is no deck"
    zoned = {**stack, "side": "bot"}
    assert detected_decks(TableReading([zoned, deck], {}, SLUGS), heroes, *spots, zones={"bot": "bdz"}) == {"bot": "discdk"}
    assert detected_decks(TableReading([deck], {}, SLUGS), heroes, *spots, zones={"bot": "bdz"}) == {}
    hell = _pile("hellboy", "hdisc", -12.0, 13.67)
    assert detected_decks(TableReading([hell], {}, SLUGS), heroes, *spots) == {}, "the human's stacked discard"


def test_a_face_up_discard_inside_a_deck_zone_is_still_discard(rt):
    zone(rt, "bdz", 15, 5, hw=2, hd=2)
    rt.execute("""
getObjectFromGUID('d42056').pos = {x = 15, y = 1, z = 5}
realshape(mkobj({guid = 'upc', type = 'Card', cid = 17632, owner = 'medusa', is_face_down = false, pos = {x = 15.5, y = 1, z = 5}}))
""")
    ids = [r["id"] for r in run(rt, lua.read_discard("906a7a", [], [], 1.5, exclude_zones=["bdz"]))]
    assert ids == [17632], "the face-down deck is left out, the face-up card is read"


def test_a_deck_zone_that_is_a_bag_has_no_objects_and_is_reported_as_not_a_zone(rt):
    rt.execute("mkobj({guid = 'bag001', type = 'Bag', items = {{guid = 'x1', name = 'x'}}})")
    assert run(rt, lua.deal_cards("d42056", 5, "Green", spot=SPOT, identity=BOT, zone="bag001")) == {"dealt": 0}
    zone(rt, "bdz", 20, 20)
    over = run(rt, lua.zone_overlaps(["bag001", "bdz", "nozone"], ["906a7a"]))
    assert over["bag001"]["zone"] is False and over["nozone"] == {"found": False}
    assert over["bdz"]["found"] and over["bdz"]["zone"] is True


def _cfg(**kw):
    return dataclasses.replace(SessionConfig("Blue", "Red", {}, (0.0, 1.0, 5.0), (0.0, -5.0), (5.0, 1.0, 5.0), "BOTZ",
                                             "DECK1", "HUMZ", (0.0, 3.0), {}), **kw)


class Client:
    def __init__(self, answer):
        self.answer = answer

    def call_lua(self, script):
        return self.answer


def test_the_start_up_check_refuses_a_missing_or_non_zone_deck_zone_and_warns_on_overlap():
    from sparring.play import check_deck_zones
    check_deck_zones(Client({}), _cfg())
    with pytest.raises(SessionError, match="bot_deck_zone"):
        check_deck_zones(Client({}), _cfg(bot_deck_zone="bdz906"))
    with pytest.raises(SessionError, match="human_deck_zone"):
        check_deck_zones(Client({"hdz906": {"found": True, "zone": False, "type": "Bag"}}), _cfg(human_deck_zone="hdz906"))
    said = []
    check_deck_zones(Client({"bdz906": {"found": True, "zone": True, "hands": [], "zones": ["BOTZ"]}}),
                     _cfg(bot_deck_zone="bdz906"), said.append)
    assert said and "BOTZ" in said[0]


def test_deck_zones_are_part_of_the_guids_that_must_exist(rig):
    session, table, game = rig
    session.cfg.bot_deck_zone = "bdz906"
    assert "bdz906" in session.guids_in_use() and ["bdz906"] in session.guid_groups()
