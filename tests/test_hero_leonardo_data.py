"""Leonardo's data (TMNT box): the overlay is the sheet read from the real cards, the generated HeroDef deals 30 cards with
the real values, the effects cover every card in DSL v1 with no plugin, the table data matches the savegame and the
hero is recognised on the table by the images of its deck (it shares Medusa's DeckID 176). No FakeTTS or sockets,
except the Lua stub for the detection script."""
import json
from collections import Counter

import pytest

from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from test_hero_detect import at_bot, at_human, detect, reading
from test_review10 import conv, rt  # noqa: F401
from tools.validate_effects import validate_file

OVERLAY = HEROES_DIR / "overlay" / "leonardo.json"
EFFECTS = HEROES_DIR / "effects" / "leonardo.json"

# (copies, value, boost, type, restriction) read from sheet 176 of the Leonardo deck in the tournament save
SHEET = {
    "Katana": (2, 6, 2, "attack", "Leonardo"),
    "Turtle power!": (2, 3, 2, "attack", "Leonardo"),
    "For Sensei": (2, 4, 1, "attack", "any"),
    "Fearless leader": (3, 3, 2, "attack", "any"),
    "Wise beyond his years": (3, 2, 2, "versatile", "Leonardo"),
    "Quick strike": (3, 3, 3, "versatile", "any"),
    "Eat, sleep, and breathe ninjutsu": (3, 3, 1, "versatile", "any"),
    "I have a plan": (3, 2, 1, "versatile", "any"),
    "Spatial awareness": (3, 3, 3, "versatile", "Splinter"),
    "Heroes in a half shell": (2, 5, 3, "defense", "Leonardo"),
    "Leonardo leads": (2, None, 4, "scheme", "Leonardo"),
    "Protective father": (2, None, 2, "scheme", "Splinter"),
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_overlay_is_the_sheet_176_read_card_by_card():
    ov = load(OVERLAY)
    assert ov["fid"] == "leonardo" and ov["forms"] is None and ov["counters"] == {}
    assert ov["deck"]["card_base"] == 17600 and ov["deck"]["sheet_id"] == 176
    sheet = ov["deck"]["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert Counter(e["title"] for e in sheet) == {t: n for t, (n, *_) in SHEET.items()}
    assert {e["title"]: e["fighter"] for e in sheet} == {t: r for t, (*_, r) in SHEET.items()}
    assert [s["name"] for s in ov["sidekicks"]] == ["Splinter"]


def test_generated_herodef_deals_30_cards_with_the_real_values():
    h = load_hero("leonardo")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Leonardo", "leonardo", 16, 2, False)
    (splinter,) = h.sidekicks
    assert (splinter.name, splinter.fid, splinter.count, splinter.hp, splinter.move, splinter.ranged) == ("Splinter", "splinter", 1, 9, 2, False)
    assert [f.fid for f in h.fighters()] == ["leonardo", "splinter"]
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, value, boost, kind, who = SHEET[c.title]
        assert (c.value, c.boost, c.type, c.fighter) == (value, boost, kind, who), c.title
    assert h.ability == "TEAM TACTICS\nAt the start of your turn, you may move any fighter 1 space."


def test_the_texts_are_the_real_cards_not_the_misspelt_source():
    by_title = {c.title: c.text for c in load_hero("leonardo").deck()}
    assert "Eat, sleep, and breathe ninjutsu" in by_title                       # unmatched-memory: "breath"
    assert by_title["I have a plan"].startswith("IMMEDIATELY: You may discard 1 card. If you do,")
    assert "this card's value" in by_title["Fearless leader"]
    assert by_title["Katana"] == "" and by_title["Heroes in a half shell"] == ""


def test_effects_validate_and_cover_every_deck_card_without_plugins():
    assert validate_file(EFFECTS) == []
    eff = load(EFFECTS)
    assert eff["schema"] == 1 and eff["hero"] == "leonardo" and eff["plugins"] == []
    titles = {c.title for c in load_hero("leonardo").deck()}
    by_title = {c["title"]: c for c in eff["cards"]}
    assert set(by_title) == titles
    assert {t: c["copies"] for t, c in by_title.items()} == {t: n for t, (n, *_) in SHEET.items()}
    with_ops = sorted(t for t, c in by_title.items() if any(c["effects"].values()) or c.get("ongoing"))
    assert with_ops == sorted(set(SHEET) - {"Katana", "Turtle power!", "Heroes in a half shell"})
    assert by_title["Turtle power!"]["may_boost"] is True
    assert all(c["effects"]["scheme"] for c in by_title.values() if SHEET[c["title"]][3] == "scheme")


def test_team_tactics_is_an_optional_move_of_any_fighter_one_space_at_the_start_of_your_turn():
    (trigger,) = load(EFFECTS)["ability"]["triggers"]
    assert trigger["id"] == "team_tactics" and trigger["when"] == {"event": "start_of_turn", "player": "owner"}
    (optional,) = trigger["ops"]
    assert optional["op"] == "optional" and optional["chooser"] == "owner"
    assert optional["ops"] == [{"op": "move", "target": {"side": "any"}, "amount": 1, "up_to": True, "chooser": "owner"}]


def test_ai_profile_knows_splinter_carries_the_cards_only_he_can_play():
    h = load_hero("leonardo")
    splinter = h.fighter_profile("Splinter")
    assert {e["title"] for e in splinter["exclusive"]} == {"Spatial awareness", "Protective father"}
    assert h.fighter_profile("Leonardo")["role"] in ("hero", "striker")
    assert splinter["role"] == "striker"                                 # melee with 9 life: worth sending forward


# ---------------------------------------------------------------- the table

def test_table_data_matches_the_savegame():
    t = load_hero_table("leonardo")
    assert t.card_ids == (17600, 17629)
    raw = load(HEROES_DIR.parent / "tts" / "leonardo.json")
    assert raw["bag"] == {"guid": "80f94d", "inner": "69b878"} and raw["deck"]["character_card_id"] == 363
    assert raw["fighters"] == {"leonardo": {"piece": "729fb1", "dial": "88f451", "dial_max": 16},
                               "splinter": {"piece": "663c11", "dial": "8e70c6", "dial_max": 9}}
    assert raw["tokens"] == {} and raw["counter_dials"] == {}


def test_leonardo_and_medusa_share_the_card_range_but_not_the_deck_images():
    leo, med = load_hero_table("leonardo"), load_hero_table("medusa")
    assert leo.card_ids == med.card_ids == (17600, 17629)
    assert not set(leo.identity) & set(med.identity)


@pytest.mark.parametrize("other", ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"])
def test_auto_detection_recognises_leonardo_in_either_seat(other):
    assert detect(reading(at_bot("leonardo"), at_human(other))) == ("leonardo", other)
    assert detect(reading(at_bot(other), at_human("leonardo"))) == (other, "leonardo")


def test_the_table_script_tells_leonardos_deck_from_medusas_by_its_images(rt):      # noqa: F811
    leo, med = load_hero_table("leonardo"), load_hero_table("medusa")

    def deck(guid, slug, x):
        face, back = load_hero_table(slug).identity[0]
        return (f"realshape(mkobj({{guid = '{guid}', type = 'Deck', name = '', cards = rc, pos = {{x = {x}, y = 1, z = 14}}, "
                f"deckcd = {{[\"176\"] = {{FaceURL = '{face}', BackURL = '{back}'}}}}}}))\n")

    rt.execute("local rc = {}\nfor i = 0, 29 do table.insert(rc, {cid = 17600 + i, guid = 'x' .. i}) end\n"
               + deck("leodeck", "leonardo", 7.0) + deck("meddeck", "medusa", -5.0))
    script = lua.table_heroes([leo.card_ids, med.card_ids], [], [leo.identity, med.identity], 5)
    rt.execute(lua.request(script, 1))
    res = json.loads(conv(rt.globals().SENT[1])["value"])
    by_guid = {p["guid"]: p for p in res["piles"]}
    assert by_guid["leodeck"]["counts"] == [30, 0] and by_guid["meddeck"]["counts"] == [0, 30]


def test_overlapping_card_ranges_are_accepted_only_when_the_deck_images_differ(monkeypatch):
    from dataclasses import replace

    from sparring.tts import hero_table
    from sparring.tts.hero_table import HeroTableError, table_defaults
    assert table_defaults("leonardo", "medusa") and table_defaults("medusa", "leonardo")
    real = hero_table.load_hero_table
    same_images = replace(real("leonardo"), identity=real("medusa").identity)
    monkeypatch.setattr(hero_table, "load_hero_table", lambda slug: same_images if slug == "leonardo" else real(slug))
    with pytest.raises(HeroTableError, match="overlap"):
        table_defaults("leonardo", "medusa")
