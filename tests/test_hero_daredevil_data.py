"""Daredevil's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real
cards of sheet 176 of the tournament save (read from the images on 2026-11-07). His deck has 22 playing cards (23 objects in the
save with the character card: CONFIRMED by Ivan) and shares CardIDs 17600-17621 with the other sheet-176 decks, told apart by
image. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import DECK_SIZE, HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "daredevil.json"
EFFECTS = HEROES_DIR / "effects" / "daredevil.json"
TTS = HEROES_DIR.parent / "tts" / "daredevil.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "luke-cage", "bullseye"]

# (copies, type, value, boost) as printed on the cards; every card carries the DAREDEVIL band.
REAL_CARDS = {
    "Devil of Hell's Kitchen": (2, "attack", 4, 3),
    "Man Without Fear": (2, "attack", 2, 3),
    "Feint": (3, "versatile", 2, 1),
    "Grappling Hook": (3, "versatile", 3, 2),
    "Take A Knee": (3, "versatile", 3, 2),
    "Son Of A Boxer": (3, "defense", 3, 2),
    "Through Adversity": (3, "scheme", None, 2),
    "Breather": (3, "scheme", None, 2),
}


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 338)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(22))
    for title, (copies, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {"Daredevil"}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 22
    assert overlay["sidekicks"] == [] and overlay["forms"] is None and overlay["counters"] == {}


def test_generated_herodef_deals_a_22_card_deck():
    h = load_hero("daredevil")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.sidekicks) == ("Daredevil", "daredevil", 17, 3, False, ())
    assert h.deck_size == 22 != DECK_SIZE and "BLIND BOOST your attack or defense" in h.ability
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17622))
    for c in deck:
        copies, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == ("Daredevil", kind, value, boost), c.title
    devil = next(c for c in deck if c.title == "Devil of Hell's Kitchen")
    assert "the value of this card is 8 instead" in devil.text and "top four cards of your discard pile" in devil.text


def test_every_other_hero_keeps_the_usual_30_cards():
    for slug in SHARING:
        assert load_hero(slug).deck_size == DECK_SIZE and len(load_hero(slug).deck()) == DECK_SIZE, slug


def test_the_ai_profile_has_one_fighter_the_hero():
    profile = load_hero("daredevil").ai_profile
    assert list(profile) == ["daredevil"] and profile["daredevil"]["role"] == "hero" and not profile["daredevil"]["ranged"]


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "daredevil"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"][m] for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][1] == "scheme") == bool(card["effects"]["scheme"])
    assert sorted(p["id"] for p in effects["plugins"]) == ["daredevil:blind_boost", "daredevil:take_a_knee"]


def test_the_ability_is_a_conditional_during_effect_not_a_trigger(effects):
    ab = effects["ability"]
    assert ab["triggers"] == [] and ab["passives"] == []
    (eff,) = ab["during"]
    assert eff["condition"] == {"test": "compare", "left": {"stat": "hand_size", "player": "owner"}, "op": "<=", "right": 2}
    assert eff["ops"] == [{"op": "plugin", "id": "daredevil:blind_boost", "args": {"times": 1, "ability": True}}]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    devil = by["Devil of Hell's Kitchen"]
    assert devil["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 8}]
    assert devil["after"] == [
        {"op": "return_to_deck", "cards": {"zone": "discard", "player": "owner", "pick": "last", "amount": 4}, "position": "shuffle"},
        {"op": "return_to_deck", "cards": "this", "position": "shuffle"}]        # itself + the top 4 of the pile: 5 in all (Ivan, 2026-11-07)
    assert by["Man Without Fear"]["during"] == [{"op": "plugin", "id": "daredevil:blind_boost", "args": {"times": 1}}]
    assert by["Through Adversity"]["scheme"][0] == {"op": "move", "target": "hero", "amount": 4, "up_to": True, "through_enemies": True, "as": "mover"}
    assert by["Through Adversity"]["scheme"][1]["target"] == {"side": "enemy", "filter": {"passed_by": "$mover"}, "pick": "all"}
    assert by["Through Adversity"]["scheme"][1]["amount"] == 1
    assert by["Feint"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]


def test_table_data_names_the_piece_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "daredevil" and tts["deck"]["card_ids"] == [17600, 17621] and tts["deck"]["character_card_id"] == 338
    assert set(tts["fighters"]) == {"daredevil"} and tts["fighters"]["daredevil"]["dial_max"] == 17
    assert tts["tokens"] == {} and tts["counter_dials"] == {}
    assert load_hero_table("daredevil").card_ids == (17600, 17621)


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_daredevil_shares_the_card_range_but_not_the_images_with_the_other_sheet_176_decks(other):
    mine, theirs = load_hero_table("daredevil"), load_hero_table(other)
    assert mine.card_ids == (17600, 17621) and theirs.card_ids == (17600, 17629)
    assert not set(mine.identity) & set(theirs.identity)
    for bot, human in (("daredevil", other), (other, "daredevil")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_daredevil_equals_a_card_of_another_sheet_176_deck(other):
    assert not set(load_hero("daredevil").deck()) & set(load_hero(other).deck())


def test_daredevil_cards_are_never_medusas():
    assert not any(is_medusa_card(c) for c in load_hero("daredevil").deck())


def test_two_daredevil_decks_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("daredevil", "daredevil")


def test_daredevil_is_detected_on_either_side_against_any_hero():
    for other in ("medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael",
                  "doctor-strange", "bigfoot"):
        assert detect_heroes(reading(at_bot("daredevil"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("daredevil", other)
        assert detect_heroes(reading(at_bot(other), at_human("daredevil")), BOT_SPOT, HUMAN_SPOT) == (other, "daredevil")


def test_the_catalog_says_23_cards_and_names_his_deck():
    catalog = load_catalog()
    assert catalog.name_of("daredevil") == "Daredevil"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("daredevil").identity]).slug == "daredevil"
    raw = json.loads((HEROES_DIR.parent / "catalog" / "heroes.json").read_text(encoding="utf-8"))
    entry = next(h for h in raw["heroes"] if h["slug"] == "daredevil")
    assert (entry["card_count"], entry["card_ids"]) == (23, [338, 17621])      # 22 playing cards + the character card: correct


def test_no_piece_guid_of_daredevil_is_shared_with_another_hero():
    mine = set(load_hero_table("daredevil").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "daredevil"]:
        assert not mine & set(load_hero_table(slug).all_guids()), slug


def test_the_table_reader_has_room_for_every_playable_hero():
    """The detection script takes one CardID range per hero; a cap below the roster makes every start-up fall back to Medusa / Hellboy."""
    from sparring.heroes import available_heroes
    from sparring.tts import lua
    assert len(available_heroes()) <= lua.MAX_HERO_RANGES
