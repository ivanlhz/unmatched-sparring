"""Loki's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards of
sheet 176 of the tournament save (read from the images on 2026-11-22), and his deck is told apart from the other decks of the sheet (same
CardIDs 17600-17629) by image and owner. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading

OVERLAY = HEROES_DIR / "overlay" / "loki.json"
EFFECTS = HEROES_DIR / "effects" / "loki.json"
TTS = HEROES_DIR.parent / "tts" / "loki.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen", "ciri", "eredin", "sinbad", "yennefer-triss", "chupacabra"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

BALDR, FREYJA, SINDRI, LURE = "Trick: Baldr's Downfall", "Trick: Freyja's Rescue", "Trick: Sindri's Bet", "Trick: Svadilfari's Lure"
TRICKS = (BALDR, FREYJA, SINDRI, LURE)

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Ragnarök": (2, "Loki", "attack", 0, 3),
    "Shapeshifter": (4, "Loki", "attack", 0, 2),                   # unmatched-memory says BOOST 3; the card prints 2
    "Looking For Trouble": (3, "Loki", "attack", 4, 3),
    BALDR: (3, "any", "attack", 4, 0),
    "God Of Mischief": (3, "Loki", "versatile", 2, 3),
    "Malicious Flyting": (3, "Loki", "versatile", 3, 3),
    "Underhanded": (3, "Loki", "versatile", 3, 2),
    "Laevateinn": (3, "Loki", "versatile", 2, 3),
    FREYJA: (2, "any", "versatile", 2, 0),
    SINDRI: (2, "any", "defense", 3, 0),
    LURE: (2, "any", "scheme", None, 0),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Ragnarök"] * 2 + ["Shapeshifter"] * 4 + ["Looking For Trouble"] * 3 + [BALDR] * 3 + ["God Of Mischief"] * 3
               + ["Malicious Flyting"] * 3 + ["Underhanded"] * 3 + ["Laevateinn"] * 3 + [FREYJA] * 2 + [SINDRI] * 2 + [LURE] * 2)


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 361)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [] and overlay["forms"] is None
    assert overlay["counters"] == {"trick_in_rival_hand": {"pile": "rival_hand", "tag": "trick"}}


def test_the_four_tricks_carry_the_tag_the_band_any_and_the_scheme_prints_no_value(overlay):
    tagged = {e["title"] for e in overlay["deck"]["sheet"] if "trick" in e.get("tags", ())}
    assert tagged == set(TRICKS) and sum(1 for e in overlay["deck"]["sheet"] if "trick" in e.get("tags", ())) == 9
    assert {e["title"] for e in overlay["deck"]["sheet"] if "value" in e and e["value"] is None} == {LURE}


def test_generated_herodef_is_a_melee_hero_without_sidekicks_and_deals_a_real_deck():
    h = load_hero("loki")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == ("Loki", "loki", 16, 2, False, 0)
    assert not h.sidekicks and h.forms is None
    assert h.ability.startswith("MISCHIEF-MONGER\nAfter you play a TRICK")
    assert set(h.counters) == {"trick_in_rival_hand"} and h.counters["trick_in_rival_hand"].pile == "rival_hand"
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    assert [c.title for c in deck] == SHEET_ORDER
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
        assert ("trick" in c.tags) == (c.title in TRICKS), c.title
    assert next(c for c in deck if c.title == SINDRI).text == (
        "LOKI: DURING COMBAT: Your opponent may discard a card. If they don't, subtract 3 from their card's value. "
        "NOT LOKI: AFTER COMBAT: Loki returns the top card of their discard pile to their hand.")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("loki").ai_profile
    assert set(profile) == {"loki"} and profile["loki"]["role"] == "hero" and not profile["loki"]["ranged"]


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "loki"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None and not card.get("may_boost")
        assert bool(card.get("lent")) == (card["title"] in TRICKS)
    assert [p["id"] for p in effects["plugins"]] == ["loki:swap_values", "loki:laevateinn", "loki:looking_for_trouble", "loki:return_trick"]


def test_the_ability_is_one_trigger_and_one_move_rule(effects):
    assert effects["ability"]["passives"] == [{"id": "trick_reach", "kind": "rule", "rule": "maneuver_move_per_counter", "counter": "trick_in_rival_hand"}]
    assert effects["ability"]["triggers"] == [{
        "id": "mischief_return", "when": {"event": "card_discarded", "player": "opponent", "from": ["hand"], "filter": {"tag": "trick"}},
        "ops": [{"op": "plugin", "id": "loki:return_trick"}]}]


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Ragnarök"]["during"] == [{"op": "modify_value", "card": "this", "amount": {"count_cards": {"zone": "hand", "player": "opponent", "filter": {"tag": "trick"}}, "times": 3}}]
    assert next(c for c in effects["cards"] if c["title"] == "Ragnarök")["uncancelable"] is True
    assert by["Looking For Trouble"]["immediately"] == [{"op": "plugin", "id": "loki:looking_for_trouble"}]
    assert by["Laevateinn"]["during"] == [{"op": "plugin", "id": "loki:laevateinn"}]
    god = by["God Of Mischief"]["immediately"][0]
    assert god["condition"] == {"test": "card", "card": "opponent_card", "filter": {"tag": "trick"}}
    assert god["then"] == [{"op": "set_value", "card": "opponent_card", "ignore": True}]
    assert god["else"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    flyting = by["Malicious Flyting"]["after"][0]
    assert [o["amount"] for o in (*flyting["then"], *flyting["else"])] == [2, 1]
    assert by["Underhanded"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 6}]
    assert [o["label"] for o in by["Shapeshifter"]["during"][0]["options"]] == ["+1 per card in their hand", "gain 1 action"]


def test_the_two_parts_of_a_trick_are_told_by_the_players_hero(effects):
    loki = {"test": "exists", "fighters": {"side": "own", "kind": "hero", "name": "Loki"}}
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by[BALDR]["after"][0]["condition"] == loki
    assert by[BALDR]["after"][0]["then"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert by[BALDR]["after"][0]["else"] == [{"op": "damage", "target": "hero", "amount": 2}]
    assert by[FREYJA]["during"][0]["condition"] == loki and by[FREYJA]["after"][0]["condition"] == {"not": loki}
    assert by[FREYJA]["after"][0]["then"] == [{"op": "heal", "target": {"side": "enemy", "kind": "hero"}, "amount": 3}]
    assert by[SINDRI]["during"][0]["condition"] == loki and by[SINDRI]["after"][0]["condition"] == {"not": loki}
    sindri = by[SINDRI]["during"][0]["then"][0]
    assert sindri["chooser"] == "opponent" and sindri["else"] == [{"op": "modify_value", "card": "opponent_card", "amount": -3}]
    assert by[SINDRI]["after"][0]["then"] == [{"op": "put_in_hand", "cards": {"zone": "discard", "player": "opponent", "pick": "last", "amount": 1}}]
    lure = by[LURE]["scheme"][0]
    assert lure["condition"] == loki and lure["then"][0]["op"] == "place" and lure["then"][0]["where"] == {"adjacent_to": "hero"}
    assert lure["else"] == [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "pick": "random", "amount": 1}}]


def test_every_other_hero_finds_the_lent_tricks_and_nothing_else_of_lokis():
    from sparring.effects.model import EffectError, load_effects, lent_cards
    assert set(lent_cards()) == set(TRICKS)
    for slug in ("medusa", "hellboy", "bloody-mary"):
        fx = load_effects(slug)
        for title in TRICKS:
            assert fx.card(title) is lent_cards()[title] and fx.find(title) is not None
        with pytest.raises(EffectError):
            fx.card("Ragnarök")
        assert fx.find("Ragnarök") is None


def test_table_data_names_the_piece_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "loki" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 361
    assert set(tts["fighters"]) == {"loki"} and tts["fighters"]["loki"]["dial_max"] == 16
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("213b55", "1d7bfd", "83366b")
    assert (tts["fighters"]["loki"]["piece"], tts["fighters"]["loki"]["dial"]) == ("c55ac8", "bcd809")
    assert tts["tokens"] == {} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_loki_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    mine, theirs = load_hero_table("loki"), load_hero_table(other)
    top = 17621 if other == "daredevil" else 17629                 # Daredevil's deck has 22 cards
    assert mine.card_ids == (17600, 17629) and theirs.card_ids == (17600, top)
    assert not set(mine.identity) & set(theirs.identity)
    for bot, human in (("loki", other), (other, "loki")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_loki_equals_a_card_of_the_other_decks_of_the_range(other):
    """A TRICK in the opponent's hand is told from the opponent's own card of the same CardID by value (docs/heroes/loki.md)."""
    assert not set(load_hero("loki").deck()) & set(load_hero(other).deck())


def test_loki_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("loki").deck())
    assert all(c not in set(load_hero("loki").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("loki", "loki")


def test_loki_is_detected_on_either_side_against_any_hero():
    for other in EVERYONE:
        assert detect_heroes(reading(at_bot("loki"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("loki", other)
        assert detect_heroes(reading(at_bot(other), at_human("loki")), BOT_SPOT, HUMAN_SPOT) == (other, "loki")


def test_the_catalog_names_loki_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("loki") == "Loki"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("loki").identity]).slug == "loki"


def test_only_the_life_dial_guid_is_shared_with_another_hero_and_only_with_medusa():
    """The save gives Loki's life dial the GUID of Medusa's (each Custom_Model is named after its hero, so `session_pieces.resolve_dials`
    tells them apart); no other GUID of his is anyone else's."""
    mine = set(load_hero_table("loki").all_guids())
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "loki"]:
        common = mine & set(load_hero_table(slug).all_guids())
        assert common == ({"bcd809"} if slug == "medusa" else set()), slug
