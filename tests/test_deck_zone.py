"""Where the bot looks for a hero's physical deck: in its Scripting zone (`bot_deck_zone` / `human_deck_zone`) or, without
one, the nearest face-down deck around the deck spot; and the GUID the table shows now is adopted (TTS gives a re-formed
deck a new one). The Lua tests run the generated scripts with lupa; the session ones use the fake table."""
from __future__ import annotations

import dataclasses
import json

import pytest

from sparring.hero_detect import TableReading, detect_heroes, detected_decks, hero_slugs
from sparring.session import Session, SessionConfig, SessionError, deck_where
from sparring.ai_medusa import MedusaAI
from sparring.state import Game
from sparring.tts import lua
from test_review10 import BDECK, BOT, HDECK, HUMAN, SCOPE, rt, run  # noqa: F401
from test_session import rig  # noqa: F401

pytest.importorskip("lupa")

SPOT = BDECK[1]
RADIUS = lua.DECK_RADIUS


def move_deck(runtime, guid, x, z, new_guid=None, face_down=True):
    runtime.execute(f"""
local d = getObjectFromGUID('{guid}')
d.pos = {{x = {x}, y = 1, z = {z}}}
d.is_face_down = {"true" if face_down else "false"}
{f"d.guid = '{new_guid}'" if new_guid else ""}
d.deal = function(k, color) DEALT = k; DEALT_FROM = d.guid end
""")


def zone(runtime, guid, cx, cz, hw=2.0, hd=2.0):
    runtime.execute(f"mkobj({{guid = '{guid}', type = 'Zone', cx = {cx}, cz = {cz}, hw = {hw}, hd = {hd}}})")


def dealt(runtime):
    return runtime.eval("DEALT"), runtime.eval("DEALT_FROM")


def reset_deal(runtime):
    runtime.execute("DEALT, DEALT_FROM = nil, nil")


# ---------- zones ----------
def test_a_deck_in_its_zone_is_found_though_far_from_the_spot_and_with_a_new_guid(rt):
    zone(rt, "bdz", 20, 20)
    move_deck(rt, "d42056", 20.5, 19.5, new_guid="963448")
    res = run(rt, lua.deal_cards("a3afc4", 5, "Green", spot=SPOT, identity=BOT, zone="bdz"))
    assert res == {"dealt": 5} and dealt(rt) == (5, "963448")


def test_with_a_zone_the_spot_is_not_searched(rt):
    zone(rt, "bdz", 20, 20)
    move_deck(rt, "d42056", SPOT[0] + 1, SPOT[1], new_guid="963448")      # near the spot, outside the zone
    reset_deal(rt)
    assert run(rt, lua.deal_cards("a3afc4", 5, "Green", spot=SPOT, identity=BOT, zone="bdz")) == {"dealt": 0}
    assert dealt(rt) == (None, None)


def test_a_deck_found_by_guid_outside_its_zone_does_not_count(rt):
    zone(rt, "bdz", 20, 20)
    move_deck(rt, "d42056", 0, 0)
    assert run(rt, lua.deal_cards("d42056", 5, "Green", spot=SPOT, identity=BOT, zone="bdz")) == {"dealt": 0}


def test_a_missing_zone_is_the_same_as_an_empty_one(rt):
    assert run(rt, lua.deal_cards("d42056", 5, "Green", spot=SPOT, identity=BOT, zone="nozone")) == {"dealt": 0}


def test_the_zone_takes_a_foreign_card_for_nothing_and_the_last_loose_card_for_the_deck(rt):
    zone(rt, "bdz", 20, 20)
    rt.execute("getObjectFromGUID('d42056').destruct()")
    rt.execute("""
realshape(mkobj({guid = 'foreignc', type = 'Card', cid = 17605, owner = 'x', is_face_down = true,
                 cd = {["176"] = {FaceURL = FF, BackURL = FB}}, pos = {x = 20, y = 1, z = 20}}))
realshape(mkobj({guid = 'lastone', type = 'Card', cid = 17606, owner = 'medusa', is_face_down = true,
                 cd = {["176"] = {FaceURL = MF, BackURL = MB}}, pos = {x = 21, y = 1, z = 20}}))
""")
    rt.execute("getObjectFromGUID('lastone').setRotation = function() end")
    res = run(rt, lua.deal_cards("gone01", 1, "Green", spot=SPOT, identity=BOT, zone="bdz"))
    assert res == {"dealt": 1}
    assert rt.eval("getObjectFromGUID('lastone').moved_count") == 1
    assert rt.eval("getObjectFromGUID('foreignc').moved_count") is None


@pytest.mark.parametrize("build", [
    lambda z: lua.shuffle_deck("gone01", SPOT, identity=BOT, zone=z),
    lambda z: lua.return_hand_to_deck("Green", "gone01", identity=BOT, spot=SPOT, zone=z),
    lambda z: lua.reset_plan([("gone01", SPOT, lua.BOT_CARD_IDS, BOT, z)], scope=SCOPE),
])
def test_the_other_builders_use_the_zone_too(rt, build):
    zone(rt, "bdz", 20, 20)
    move_deck(rt, "d42056", 20, 20, new_guid="963448")
    rt.execute("getObjectFromGUID('963448').shuffle = function() SHUFFLED = true end")
    res = run(rt, build("bdz"))
    if isinstance(res, list):
        assert res == [{"deck": True, "loose": 0, "total": 30}]
    elif "shuffled" in res:
        assert res == {"shuffled": True, "quantity": 30}
    else:
        assert res["deck"] is True


def test_a_loose_card_goes_into_the_deck_found_in_the_zone(rt):
    zone(rt, "bdz", 20, 20)
    move_deck(rt, "d42056", 20, 20, new_guid="963448")
    rt.execute("realshape(mkobj({guid = 'lc1', type = 'Card', cid = 17609, owner = 'medusa', cd = {[\"176\"] = {FaceURL = MF, BackURL = MB}}, pos = {x = 0, y = 1, z = 0}}))")
    res = run(rt, lua.card_to_deck_top("lc1", "gone01", identity=BOT, spot=SPOT, zone="bdz"))
    assert res["placed"] is True and res["deck"] == "963448"
    assert run(rt, lua.card_to_deck_top("lc1", "gone01", identity=BOT, spot=SPOT, zone="nozone")) == {"placed": False, "deck": False}


# ---------- without zones ----------
def test_a_deck_with_a_new_guid_just_outside_the_old_radius_is_found_by_the_spot(rt):
    move_deck(rt, "d42056", SPOT[0] + 2.08, SPOT[1], new_guid="963448")         # the live case: 2.08 from the spot
    assert run(rt, lua.deal_cards("a3afc4", 5, "Green", spot=SPOT, identity=BOT)) == {"dealt": 5}
    assert dealt(rt) == (5, "963448")


def test_a_deck_at_2_5_is_found_and_one_past_the_radius_is_not(rt):
    move_deck(rt, "d42056", SPOT[0] + 2.5, SPOT[1], new_guid="963448")
    assert run(rt, lua.deal_cards("a3afc4", 5, "Green", spot=SPOT, identity=BOT)) == {"dealt": 5}
    reset_deal(rt)
    move_deck(rt, "963448", SPOT[0] + RADIUS + 0.3, SPOT[1])
    assert run(rt, lua.deal_cards("a3afc4", 5, "Green", spot=SPOT, identity=BOT)) == {"dealt": 0}


def test_the_nearest_candidate_wins(rt):
    move_deck(rt, "d42056", SPOT[0] + 2.5, SPOT[1], new_guid="far")
    rt.execute("""
local c = {}
for i = 0, 4 do table.insert(c, {cid = 17610 + i, guid = 'n' .. i, owner = 'medusa'}) end
realshape(mkobj({guid = 'near', type = 'Deck', cards = c, is_face_down = true, pos = {x = SPOT_X + 1.0, y = 1, z = SPOT_Z},
                 deckcd = {["176"] = {FaceURL = MF, BackURL = MB}}}))
getObjectFromGUID('near').deal = function(k, color) DEALT = k; DEALT_FROM = 'near' end
""".replace("SPOT_X", str(SPOT[0])).replace("SPOT_Z", str(SPOT[1])))
    run(rt, lua.deal_cards("gone01", 1, "Green", spot=SPOT, identity=BOT))
    assert dealt(rt) == (1, "near")


def test_discard_pile_cards_are_never_grabbed_as_the_deck(rt):
    """The discard grid starts `deck_clear` (3.0) from the deck and its cards lie face up: with the deck gone, nothing of
    it is dealt, however close it is, and none of it moves."""
    rt.execute("getObjectFromGUID('d42056').destruct()")
    rt.execute(f"""
local c = {{}}
for i = 0, 3 do table.insert(c, {{cid = 17620 + i, guid = 'dc' .. i, owner = 'medusa'}}) end
realshape(mkobj({{guid = 'pile', type = 'Deck', cards = c, is_face_down = false, pos = {{x = {SPOT[0] + 3.0}, y = 1, z = {SPOT[1]}}},
                 deckcd = {{["176"] = {{FaceURL = MF, BackURL = MB}}}}}}))
realshape(mkobj({{guid = 'slot', type = 'Card', cid = 17630, owner = 'medusa', is_face_down = false,
                 pos = {{x = {SPOT[0] + 1.0}, y = 1, z = {SPOT[1]}}}}}))
""")
    assert run(rt, lua.deal_cards("gone01", 5, "Green", spot=SPOT, identity=BOT)) == {"dealt": 0}
    assert rt.eval("getObjectFromGUID('slot').moved_count") is None and rt.eval("getObjectFromGUID('pile').moved_count") is None


def test_the_search_radius_stays_below_the_discard_clearance():
    assert lua.DECK_RADIUS < SessionConfig.deck_clear
    assert SessionConfig.deck_radius == lua.DECK_RADIUS


# ---------- reading the discard and the detection ----------
def test_read_discard_leaves_out_what_lies_in_the_deck_zone(rt):
    zone(rt, "bdz", 15, 5, hw=2, hd=2)
    rt.execute("""
getObjectFromGUID('d42056').pos = {x = 15, y = 1, z = 5}
getObjectFromGUID('d42056').is_face_down = true
realshape(mkobj({guid = 'dcard', type = 'Card', cid = 17631, owner = 'medusa', pos = {x = 12, y = 1, z = -6}}))
""")
    with_deck = run(rt, lua.read_discard("906a7a", [], [], 1.5))
    assert 17631 in [r["id"] for r in with_deck] and len(with_deck) == 31, "without the zone the deck would count as discard"
    only_discard = run(rt, lua.read_discard("906a7a", [], [], 1.5, exclude_zones=["bdz"]))
    assert [r["id"] for r in only_discard] == [17631]


def test_deck_identities_returns_the_guid_found_and_follows_the_zone(rt):
    zone(rt, "bdz", 20, 20)
    move_deck(rt, "d42056", 20, 20, new_guid="963448")
    res = run(rt, lua.deck_identities([("a3afc4", SPOT, lua.BOT_CARD_IDS, "bdz"), ("00dc9a", HDECK[1], lua.HUMAN_CARD_IDS)]))
    assert res[0]["found"] and res[0]["guid"] == "963448" and res[0]["pairs"]
    assert res[1]["found"] and res[1]["guid"] == "00dc9a"
    res = run(rt, lua.deck_identities([("a3afc4", SPOT, lua.BOT_CARD_IDS)]))
    assert res[0]["found"] is False, "a face-down deck 15 units away is not within the radius"
    zone(rt, "emptyz", -30, -30)
    assert run(rt, lua.deck_identities([("963448", SPOT, lua.BOT_CARD_IDS, "emptyz")]))[0]["found"] is False


def test_table_heroes_tags_the_pile_inside_a_deck_zone(rt):
    zone(rt, "bdz", 20, 20)
    move_deck(rt, "d42056", 20, 20)
    res = run(rt, lua.table_heroes([lua.BOT_CARD_IDS], [], [BOT], deck_zones={"bot": "bdz"}))
    sides = {p["guid"]: p.get("side") for p in res["piles"]}
    assert sides["d42056"] == "bot"


SLUGS = hero_slugs()


def _pile(slug, guid, x, z, side=None):
    return {"type": "Deck", "guid": guid, "x": x, "z": z, "counts": [30 if s == slug else 0 for s in SLUGS],
            **({"side": side} if side else {})}


def test_a_pile_in_a_deck_zone_belongs_to_that_side_whatever_its_distance():
    reading = TableReading([_pile("medusa", "p1", -4.0, 13.0, side="bot"), _pile("hellboy", "p2", 7.0, 13.0, side="human")],
                           {}, SLUGS)
    assert detect_heroes(reading, (7.28, 13.93), (-4.6, 13.67)) == ("medusa", "hellboy")


def test_detected_decks_gives_the_guid_the_table_shows():
    reading = TableReading([_pile("medusa", "963448", 8.58, 15.56), _pile("hellboy", "00dc9a", -4.6, 13.67),
                            _pile("medusa", "stray", 7.0, 14.0)], {}, SLUGS)
    reading.piles[2]["counts"] = [2 if s == "medusa" else 0 for s in SLUGS]
    assert detected_decks(reading, ("medusa", "hellboy"), (7.28, 13.93), (-4.6, 13.67)) == {
        "bot": "963448", "human": "00dc9a"}


# ---------- the session ----------
class NewGuidTable:
    """The rig's table, answering `deck_identities` with the GUID the deck has now."""

    def __init__(self, table, guid):
        self.original, self.guid = table.do_deck_identities, guid
        self.asked: list[str] = []

    def __call__(self, s):
        out = self.original(s)
        self.asked.append(s)
        return [{**e, "guid": self.guid} for e in out]


def test_the_session_adopts_the_deck_guid_and_keeps_the_configured_one_as_identity(rig):
    session, table, game = rig
    before = (session._config_hash(), session.fingerprint()["guids"])
    table.do_deck_identities = NewGuidTable(table, "963448")
    session.load_identities()
    assert session.cfg.bot_deck_guid == "963448"
    assert (session._config_hash(), session.fingerprint()["guids"]) == before, "the save is still this table"
    assert session.guids_in_use() != session.guids_in_use(configured=True)
    assert "963448" in session.guids_in_use() and "DECK1" in session.guids_in_use(configured=True)
    assert session.to_dict()["deck_live"] == {"bot": "963448"}


def test_a_resume_trusts_the_live_guid_it_saved_and_accepts_the_save(rig):
    session, table, game = rig
    table.do_deck_identities = NewGuidTable(table, "963448")
    session.load_identities()
    saved = json.loads(json.dumps(session.to_dict()))
    fresh_cfg = dataclasses.replace(session.cfg, bot_deck_guid="DECK1")
    other = Session(Game.new(game.board, seed=3, controllers={}), session.client, MedusaAI(0), fresh_cfg)
    other.game_id = session.game_id
    other.load_dict(saved)                                    # the fingerprint holds the configured GUID: no StateError
    asked = NewGuidTable(table, "963448")
    table.do_deck_identities = asked
    other.load_identities()
    assert '{"963448", {' in asked.asked[0], "the saved live GUID is the first candidate"
    assert other.cfg.bot_deck_guid == "963448"


def test_a_resume_whose_saved_guid_is_gone_adopts_the_new_one(rig):
    session, table, game = rig
    session._saved_decks = {"bot": "gone99"}
    table.do_deck_identities = NewGuidTable(table, "777777")
    session.load_identities()
    assert session.cfg.bot_deck_guid == "777777"
    assert session.to_dict()["deck_live"] == {"bot": "777777"}


def test_the_detected_guid_is_tried_first(rig):
    session, table, game = rig
    session.cfg.bot_deck_hint = "963448"
    table.do_deck_identities = asked = NewGuidTable(table, "963448")
    session.load_identities()
    assert '{"963448", {' in asked.asked[0] and session.cfg.bot_deck_guid == "963448"


def test_the_deck_lookups_carry_the_zone_and_the_spot(rig):
    session, table, game = rig
    session.cfg.bot_deck_zone = "bdz906"
    assert session._deck_kw() == {"spot": (0.0, 3.0), "zone": "bdz906", "radius": lua.DECK_RADIUS}
    assert session._deck_kw("human") == {"spot": None, "zone": None, "radius": lua.DECK_RADIUS}
    assert session._skip_zones("bot") == ("bdz906",) and session._skip_zones("human") == ()
    assert "bdz906" in lua.snapshot_lua(session.snapshot_spec())


def test_the_error_when_the_deck_is_not_found_says_where_it_looked(rig):
    session, table, game = rig
    assert "(0, 3)" in session.deck_where() and "2.9" in session.deck_where()
    session.cfg.bot_deck_zone = "bdz906"
    assert "bdz906" in session.deck_where()
    assert "bdz906" in deck_where("bdz906", (0, 3), 2.9)


@pytest.mark.parametrize("language,word", [("en", "looked"), ("es", "buscado")])
def test_the_not_found_messages_say_where_they_looked_and_what_to_do(rig, language, word):
    from sparring import i18n
    session, table, game = rig
    with i18n.using(language):
        for zone_guid, shown in ((None, "2.9"), ("bdz906", "bdz906")):
            session.cfg.bot_deck_zone = zone_guid
            where = session.deck_where()
            dealt_msg = i18n.t("err.deck_dealt", dealt=0, n=5, where=where)
            assert word in dealt_msg and shown in dealt_msg and "bot_deck_zone" in dealt_msg
            assert shown in i18n.t("err.mull_no_deck", where=where)
        assert "bot_deck_zone" in i18n.t("ro.w.deck_not_found", role="bot", where=where)


def test_a_radius_that_reaches_the_discard_slots_is_refused(rig):
    session, table, game = rig
    session.cfg.deck_radius = session.cfg.deck_clear
    with pytest.raises(SessionError, match="deck_radius"):
        session._check_config()
