"""TTS renumbers the DeckID of a deck that spawns beside another with the same one: Medusa and Michelangelo both ship
DeckID 176, and on the live table (TS_AutoSave_3) Michelangelo's deck carries CardIDs 17700-17729 with CustomDeck keys
"177" (its face) and "3" (the character card's sheet). The image identity is the deck's real key; the bot reads the
DeckID the deck really has and uses the shifted CardID range everywhere."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from sparring import persist, play, table_reset
from sparring.hero_detect import deck_shifts, detect_heroes, hero_slugs, parse_table, table_script
from sparring.heroes import load_hero
from sparring.play import build_game, load_config, rescan_deck_shifts, resolve_heroes, saved_card_shifts, with_deck_shifts
from sparring.session import Session, SessionError
from sparring.tts import lua
from sparring.tts.hero_table import card_shift, load_hero_table
from test_review9 import SCOPE, conv, rt, run  # noqa: F401

REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "table.json"
MEDUSA, MICHELANGELO = load_hero_table("medusa"), load_hero_table("michelangelo")
BOT_SPOT, HUMAN_SPOT = (7.28, 13.93), (-4.6, 13.67)
EVERYWHERE = dataclasses.replace(SCOPE, everywhere=True)
CHAR_SHEET = ("https://steamusercontent-a.akamaihd.net/ugc/1/CHARFACE/", "https://steamusercontent-a.akamaihd.net/ugc/1/CHARBACK/")
EFFECTIVE = (17700, 17729)


def table_with_renumbered_michelangelo(rt):  # noqa: F811
    """The live shape: Medusa's deck at DeckID 176; Michelangelo's, 30 cards at 177xx plus his character card 366 (sheet "3")."""
    (mf, mb), (nf, nb) = MEDUSA.identity[0], MICHELANGELO.identity[0]
    g = rt.globals()
    g.MF, g.MB, g.NF, g.NB = mf, mb, nf, nb
    g.CF, g.CB = CHAR_SHEET
    rt.execute(f"""
local function realshape(o)
  o.getData = function()
    local co = {{}}
    for _, c in ipairs(o.cards or {{}}) do table.insert(co, {{CardID = c.cid, GUID = c.guid}}) end
    return {{ContainedObjects = co, CustomDeck = o.deckcd}}
  end
  return o
end
local mc = {{}}
for i = 0, 29 do table.insert(mc, {{cid = 17600 + i, guid = 'm' .. i, owner = 'medusa'}}) end
realshape(mkobj({{guid = 'd42056', type = 'Deck', cards = mc, pos = {{x = {BOT_SPOT[0]}, y = 1, z = {BOT_SPOT[1]}}},
                 is_face_down = true, deckcd = {{["176"] = {{FaceURL = MF, BackURL = MB}}}}}}))
local nc = {{{{cid = {MICHELANGELO.character_card_id}, guid = 'char366', owner = 'michelangelochar'}}}}
for i = 0, 29 do table.insert(nc, {{cid = 17700 + i, guid = 'n' .. i, owner = 'michelangelo'}}) end
realshape(mkobj({{guid = '1b5094', type = 'Deck', cards = nc, pos = {{x = {HUMAN_SPOT[0]}, y = 1, z = {HUMAN_SPOT[1]}}},
                 is_face_down = true, deckcd = {{["177"] = {{FaceURL = NF, BackURL = NB}}, ["3"] = {{FaceURL = CF, BackURL = CB}}}}}}))
""")


class Table:
    """Fake client that runs every script it is sent on the Lua stub."""

    def __init__(self, rt):  # noqa: F811
        self.rt = rt

    def call_lua(self, script, *a, **k):
        sent = self.rt.globals().SENT
        n = len(sent)
        self.rt.execute(lua.request(script, 7))
        return json.loads(conv(sent[n + 1])["value"])


def test_the_shift_is_the_deck_id_distance_in_hundreds():
    assert card_shift(MICHELANGELO, 177) == 100 and card_shift(MEDUSA, 176) == 0 and card_shift(MEDUSA, 0) == 0
    assert card_shift(load_hero_table("hellboy"), 197) == 0 and card_shift(load_hero_table("houdini"), 179) == 100


def test_detection_finds_both_heroes_by_image_and_reads_the_real_deck_id(rt):  # noqa: F811
    table_with_renumbered_michelangelo(rt)
    reading = parse_table(Table(rt).call_lua(table_script()))
    assert detect_heroes(reading, BOT_SPOT, HUMAN_SPOT) == ("medusa", "michelangelo")      # was: "un mazo desconocido"
    assert deck_shifts(reading, ("medusa", "michelangelo")) == (0, 100)
    assert deck_shifts(reading, ("michelangelo", "medusa")) == (100, 0)


def test_resolving_the_heroes_gives_the_effective_ranges_and_the_cards_with_the_shifted_ids(rt, tmp_path):  # noqa: F811
    table_with_renumbered_michelangelo(rt)
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    raw.update(bot_hero="auto", human_hero="auto")
    path = tmp_path / "c.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    cfg = resolve_heroes(Table(rt), load_config(path), echo=lambda _: None)
    assert cfg.heroes == ("medusa", "michelangelo") and cfg.card_shifts == (0, 100)
    assert cfg.raw["bot_card_ids"] == [17600, 17629] and cfg.raw["human_card_ids"] == list(EFFECTIVE)
    scfg = cfg.session_config()
    assert (scfg.bot_card_ids, scfg.human_card_ids) == ((17600, 17629), EFFECTIVE)
    assert (scfg.bot_card_shift, scfg.human_card_shift) == (0, 100)
    game = build_game(cfg, "human", 1)
    assert {c.card_id for c in game.players[1].full_set} == set(range(17700, 17730))
    assert {c.card_id for c in game.players[0].full_set} == set(range(17600, 17630))
    assert game.players[1].full_set[0].title == load_hero("michelangelo").deck()[0].title


def test_a_fixed_hero_pair_gets_its_shift_from_the_rescan(rt):  # noqa: F811
    table_with_renumbered_michelangelo(rt)
    cfg = resolve_heroes(Table(rt), load_config(REAL_CONFIG, "medusa", "michelangelo"), echo=lambda _: None)
    assert cfg.card_shifts == (0, 0) and not cfg.shifts_read             # both fixed: resolving does not read the table
    cfg = rescan_deck_shifts(Table(rt), cfg)
    assert cfg.card_shifts == (0, 100) and cfg.shifts_read and cfg.raw["human_card_ids"] == list(EFFECTIVE)


def test_the_session_state_keeps_the_shifts_and_an_old_save_without_them_still_loads(tmp_path):
    path = tmp_path / "s.json"
    persist.save_atomic(path, {"heroes": ["medusa", "michelangelo"], "card_shifts": [0, 100]})
    assert saved_card_shifts(path) == (0, 100)
    persist.save_atomic(path, {"heroes": ["medusa", "michelangelo"]})
    assert saved_card_shifts(path) is None and saved_card_shifts(tmp_path / "missing.json") is None
    persist.save_atomic(path, {"card_shifts": "no"})
    assert saved_card_shifts(path) is None


def test_a_session_built_on_a_shifted_config_writes_the_shifts_in_its_save():
    cfg = with_deck_shifts(load_config(REAL_CONFIG, "medusa", "michelangelo"), (0, 100))
    session = Session(build_game(cfg, "human", 1), None, play.make_bot_ai(play.ai_config(cfg, None, None), play.BOT),
                      cfg.session_config(), bot=play.BOT)
    assert session._to_dict(None)["card_shifts"] == [0, 100]


def test_resuming_with_the_heroes_saved_does_not_read_the_table_and_the_saved_shift_applies():
    class Silent:
        def call_lua(self, *a, **k):
            raise AssertionError("the table must not be read")

    cfg = resolve_heroes(Silent(), load_config(REAL_CONFIG, "medusa", "michelangelo"), ("medusa", "michelangelo"),
                         echo=lambda _: None)
    assert cfg.card_shifts == (0, 0) and not cfg.shifts_read
    cfg = with_deck_shifts(cfg, (0, 100))
    assert cfg.card_shifts == (0, 100) and cfg.raw["human_card_ids"] == list(EFFECTIVE)


def test_documentation_of_the_bug_the_base_range_loses_the_renumbered_deck_and_the_effective_one_finds_it(rt):  # noqa: F811
    # documents the failure mode (the base range misses the 177xx deck); the fix is exercised by the tests around it
    table_with_renumbered_michelangelo(rt)
    ident = MICHELANGELO.identity
    lost = run(rt, lua.reset_plan([("1b5094", HUMAN_SPOT, MICHELANGELO.card_ids, ident, None)], scope=EVERYWHERE))
    assert lost[0]["deck"] is False, "the live bug: 'a mi alcance hay 0'"
    side = ("1b5094", EFFECTIVE, ident, MICHELANGELO.character_card_id, (5.0, 1.8, 15.0), (0, 90, 0))
    assert run(rt, lua.take_character_cards([side])) == [{"found": True, "taken": True}]
    found = run(rt, lua.reset_plan([("1b5094", HUMAN_SPOT, EFFECTIVE, ident, None)], scope=EVERYWHERE))
    assert found == [{"deck": True, "loose": 0, "total": 30}]


def test_the_cleaning_recognizes_a_renumbered_deck_as_the_heros(rt):  # noqa: F811
    table_with_renumbered_michelangelo(rt)
    script = lua.clear_setup([(MICHELANGELO.card_ids, MICHELANGELO.identity, MICHELANGELO.character_card_id)], [], [], [],
                             (50.0, 50.0))
    res = run(rt, script)
    assert res["cards"] == 1 and res["mixed"] == [], "Michelangelo's deck (177xx + his character card) is cleaned as his"
    assert rt.globals().getObjectFromGUID("d42056") is not None, "Medusa's deck is not Michelangelo's: untouched"


# ---------- Preparar: the decks spawn (renumbered) AFTER the unpack script has answered ----------
class SpawningTable:
    """Fake client for the Preparar ordering: Michelangelo's deck is not on the table until the `appears_at`-th read of it, and
    then it lies there at DeckID 177. Records every script it is sent."""

    def __init__(self, appears_at: int):
        self.appears_at, self.reads, self.scripts = appears_at, 0, []

    def call_lua(self, script, *a, **k):
        self.scripts.append(script)
        if script.split("\n")[0] != "-- sparring:table_heroes":
            return {}
        self.reads += 1
        slugs = hero_slugs()

        def pile(guid, slug, deck_id, spot):
            return {"type": "Deck", "guid": guid, "x": spot[0], "z": spot[1], "down": True, "size": 30,
                    "counts": [30 if s == slug else 0 for s in slugs], "deck_ids": [deck_id if s == slug else 0 for s in slugs]}
        piles = [pile("d42056", "medusa", 176, BOT_SPOT)]
        if self.reads >= self.appears_at:
            piles.append(pile("1b5094", "michelangelo", 177, HUMAN_SPOT))
        return {"piles": piles, "pieces": {}}


def prepare_with(client, monkeypatch):
    """`prepare_session` as the gate runs it, with the table-writing steps replaced by a spy that takes the character cards."""
    seen = {}

    def reset_spy(client_, session, raw, arrange=False):
        seen["sides"] = [(side, rng) for side, _, _, rng, _, _ in table_reset._deck_sides(session)]
        table_reset.take_character_cards(client_, session, raw)
        return []

    monkeypatch.setattr(table_reset, "reset_cards_and_pieces", reset_spy)
    monkeypatch.setattr(Session, "prepare_table", lambda self, *a: None)
    monkeypatch.setattr(Session, "_say_startup_notes", lambda self: None)
    cfg = load_config(REAL_CONFIG, "medusa", "michelangelo")
    unpacked = []

    def make_session(on):
        return Session(build_game(on, "random", 0), client, play.make_bot_ai(play.ai_config(on, None, None), play.BOT),
                       on.session_config(), bot=play.BOT)
    lines, session, used = table_reset.prepare_session(
        client, make_session, cfg, lambda c, on, echo: unpacked.append(on) or [], print,
        lambda on: rescan_deck_shifts(client, on, lambda: None, require=True, tries=5))
    return seen, session, used, unpacked


def test_preparar_rescans_after_the_unpack_so_a_deck_that_spawns_renumbered_is_found(monkeypatch):
    client = SpawningTable(appears_at=3)                     # the first reads come back before TTS has spawned the deck
    seen, session, used, unpacked = prepare_with(client, monkeypatch)
    assert unpacked[0].card_shifts == (0, 0), "the unpack ran on the configuration read before the deck existed"
    assert client.reads == 3, "it waited and read again until both decks were there"
    assert used.card_shifts == (0, 100) and session.cfg.human_card_ids == EFFECTIVE
    assert seen["sides"] == [("bot", (17600, 17629)), ("human", EFFECTIVE)]
    taken = next(sc for sc in client.scripts if sc.startswith("-- sparring:take_character_cards"))
    assert "17700" in taken and "17729" in taken, "the character cards are taken from the deck found by the shifted range"
    plan = lua.reset_plan([("1b5094", session.cfg.human_deck_spot, session.cfg.human_card_ids, MICHELANGELO.identity, None)],
                          scope=EVERYWHERE)
    assert "17700" in plan and "17729" in plan, "and reset_plan, built from the session's ranges, searches the shifted ones"


def test_preparar_fails_clearly_when_a_deck_never_appears_instead_of_assuming_shift_zero(monkeypatch):
    client = SpawningTable(appears_at=10 ** 6)
    with pytest.raises(SessionError, match="Michelangelo"):
        prepare_with(client, monkeypatch)
    assert client.reads == 5, "it read the table the allowed number of times, no more"
    assert not any(sc.startswith("-- sparring:take_character_cards") for sc in client.scripts), "nothing was touched"


def test_a_read_that_fails_while_preparing_is_not_swallowed():
    class Broken:
        def call_lua(self, *a, **k):
            raise ValueError("bad reply")

    with pytest.raises(ValueError):
        rescan_deck_shifts(Broken(), load_config(REAL_CONFIG, "medusa", "michelangelo"), lambda: None, require=True)


def test_without_require_a_deck_not_yet_on_the_table_keeps_shift_zero():
    cfg = rescan_deck_shifts(SpawningTable(appears_at=10 ** 6), load_config(REAL_CONFIG, "medusa", "michelangelo"))
    assert cfg.card_shifts == (0, 0) and cfg.shifts_read


def test_the_missing_decks_message_exists_in_both_languages():
    from sparring import i18n
    try:
        for lang in ("es", "en"):
            i18n.set_language(lang)
            assert "Michelangelo" in i18n.t("gate.decks_not_seen", heroes="Michelangelo")
    finally:
        i18n.set_language("es")
