"""Yennenga's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 176 of the tournament save (read from the images on 2026-11-20), and her deck is told apart from the other decks of
the range (CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, available_heroes, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, parse_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_card_identity import SHARING, SHEET_187
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "yennenga.json"
EFFECTS = HEROES_DIR / "effects" / "yennenga.json"
TTS = HEROES_DIR.parent / "tts" / "yennenga.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SAME_SHEET = [s for s in SHARING if s not in SHEET_187 and s != "yennenga"]

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Rain of Arrows": (3, "Yennenga", "attack", 3, 3),
    "Surprise Volley": (3, "any", "attack", 3, 3),
    "Point Blank": (3, "Yennenga", "versatile", 2, 2),
    "Stallion Charge": (3, "Yennenga", "versatile", 3, 3),
    "Jaws of the Beast": (3, "Yennenga", "versatile", 3, 3),
    "Skirmish": (2, "any", "versatile", 4, 2),
    "Momentous Shift": (3, "any", "versatile", 3, 2),
    "Pin the Prey": (2, "Archer", "versatile", 1, 2),
    "Divide and Conquer": (2, "Archer", "versatile", 2, 1),
    "Shield Formation": (2, "Yennenga", "defense", 3, 3),
    "One With The Land": (2, "Yennenga", "scheme", None, 2),
    "Master of the Hunt": (2, "Yennenga", "scheme", None, 3),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Rain of Arrows"] * 3 + ["Surprise Volley"] * 3 + ["Point Blank"] * 3 + ["Stallion Charge"] * 3
               + ["Jaws of the Beast"] * 3 + ["Skirmish"] * 2 + ["Momentous Shift"] * 3 + ["Pin the Prey"] * 2
               + ["Divide and Conquer"] * 2 + ["Shield Formation"] * 2 + ["One With The Land"] * 2 + ["Master of the Hunt"] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 319)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [{"fid": "archer", "name": "Archer"}] and overlay["fid"] == "yennenga"
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []
    assert overlay["tts"] == {"no_dial": ["archer1", "archer2"], "life_faces": {"2": 0, "1": 180}}


def test_generated_herodef_deals_a_real_deck():
    h = load_hero("yennenga")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Yennenga", "yennenga", 15, 2, True)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("archer", "Archer", 2, 2, 2, True)]
    assert [f.fid for f in h.fighters()] == ["yennenga", "archer1", "archer2"]
    assert h.ability.startswith("If Yennenga would take damage, you may assign any amount of that damage to one or more Archers in her zone")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
    assert sum(1 for c in deck if c.fighter == "Archer") == 4
    assert next(c for c in deck if c.title == "Point Blank").text == (
        "AFTER COMBAT: If the opposing fighter is adjacent to Yennenga, deal 2 damage to that fighter.")        # the card, not unmatched-memory


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("yennenga").ai_profile
    assert profile["yennenga"]["role"] == "hero" and profile["archer"]["name"] == "Archer"
    assert {"Pin the Prey", "Divide and Conquer"} <= {e["title"] for e in profile["archer"]["exclusive"]}
    assert {"Stallion Charge", "Shield Formation", "Master of the Hunt"} <= {e["title"] for e in profile["yennenga"]["exclusive"]}


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "yennenga"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None
    assert [p["id"] for p in effects["plugins"]] == ["yennenga:assign_damage", "yennenga:surprise_volley"]


def test_the_ability_is_a_plugin_passive_read_by_the_damage_code(effects):
    assert effects["ability"]["triggers"] == []
    assert effects["ability"]["passives"] == [{"id": "archers_take_it", "kind": "plugin", "plugin": "yennenga:assign_damage"}]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Rain of Arrows"]["after"] == [{"op": "second_attack", "amount": 3}]
    assert by["Surprise Volley"]["immediately"] == [{"op": "plugin", "id": "yennenga:surprise_volley"}]
    assert by["Point Blank"]["after"][0]["condition"] == {"test": "fighter_at", "fighter": "opposing", "space": {"adjacent_to": "hero"}}
    assert by["Point Blank"]["after"][0]["then"] == [{"op": "damage", "target": "opposing", "amount": 2}]
    move, hit = by["Stallion Charge"]["after"]
    assert (move["amount"], move["up_to"], move["through_enemies"], move["target"]) == (5, True, True, "hero")
    assert hit["target"]["filter"] == {"passed_by": "$charger"} and hit["amount"] == 1
    assert by["Jaws of the Beast"]["during"] == [{"op": "modify_value", "card": "this", "amount": {"stat": "zones", "fighter": "opposing"}}]
    assert by["Momentous Shift"]["during"][0]["condition"] == {"test": "moved_this_turn", "fighter": "this"}
    assert by["Momentous Shift"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 5}]
    assert by["Divide and Conquer"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 4}]
    assert [o["op"] for o in by["Pin the Prey"]["after"]] == ["move", "discard"] and by["Pin the Prey"]["after"][0]["amount"] == 4
    shield, = by["Shield Formation"]["immediately"]
    assert shield["chooser"] == "opponent" and shield["cost"][0]["op"] == "discard" and shield["else"][0]["op"] == "revive"
    assert by["Master of the Hunt"]["scheme"] == [{"op": "gain_action", "amount": 2}]
    assert [o["op"] for o in by["One With The Land"]["scheme"]] == ["move", "heal", "draw"]


def test_table_data_names_the_pieces_the_deck_range_and_that_the_archers_have_no_dial():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "yennenga" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 319
    assert set(tts["fighters"]) == {"yennenga", "archer1", "archer2"}
    assert tts["fighters"]["yennenga"]["dial_max"] == 15 and tts["fighters"]["yennenga"]["piece"] == "3ec3d1"
    assert all(tts["fighters"][a]["no_dial"] is True and "dial" not in tts["fighters"][a] for a in ("archer1", "archer2"))
    assert all(tts["fighters"][a]["faces"] == {"2": 0, "1": 180} and tts["fighters"][a]["verify_live"] for a in ("archer1", "archer2"))      # Ivan 2026-11-20: the token is flipped
    assert tts["tokens"] == {} and tts["counter_dials"] == {}                  # hasTokens: true in unmatched-memory, but her bag holds no token


def test_an_archer_with_two_life_needs_the_no_dial_flag():
    raw = json.loads(TTS.read_text(encoding="utf-8"))
    parse_hero_table(raw, load_hero("yennenga"))
    del raw["fighters"]["archer1"]["no_dial"]
    with pytest.raises(HeroTableError, match="no dial"):
        parse_hero_table(raw, load_hero("yennenga"))


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SAME_SHEET)
def test_yennenga_shares_the_card_range_but_not_the_images_with_the_other_sheet_176_decks(other):
    mine, theirs = load_hero_table("yennenga"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert mine.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(mine.identity) & set(theirs.identity)
    for bot, human in (("yennenga", other), (other, "yennenga")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SAME_SHEET)
def test_no_card_of_yennenga_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("yennenga").deck()) & set(load_hero(other).deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("yennenga", "yennenga")


def test_yennenga_is_detected_on_either_side_against_any_hero():
    for other in [s for s in available_heroes() if s != "yennenga"]:
        assert detect_heroes(reading(at_bot("yennenga"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("yennenga", other)
        assert detect_heroes(reading(at_bot(other), at_human("yennenga")), BOT_SPOT, HUMAN_SPOT) == (other, "yennenga")


def test_the_catalog_names_yennenga_and_her_deck_is_her_own():
    catalog = load_catalog()
    assert catalog.name_of("yennenga") == "Yennenga"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("yennenga").identity]).slug == "yennenga"


def test_the_only_piece_guid_she_shares_is_houdinis_miniature():
    """The save gives her miniature (3ec3d1) to Houdini's as well: told apart by the piece's name (docs/card-identity.md, "Piece identity")."""
    mine = set(load_hero_table("yennenga").all_guids())
    shared = {}
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "yennenga"]:
        for g in mine & set(load_hero_table(slug).all_guids()):
            shared.setdefault(g, []).append(slug)
    assert shared == {"3ec3d1": ["houdini"]}
