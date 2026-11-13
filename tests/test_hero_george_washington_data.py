"""George Washington's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with the real cards
of sheet 187 of the tournament save (read tile by tile from the image on 2026-11-13, and checked against unmatched-memory's transcription of
Ivan's screenshots: no difference), and his deck is told apart from every other hero's by CardID range and image. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.combat import is_medusa_card
from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.heroes import HEROES_DIR, available_heroes, load_hero
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading
from tools.validate_effects import validate_file

OVERLAY = HEROES_DIR / "overlay" / "george-washington.json"
EFFECTS = HEROES_DIR / "effects" / "george-washington.json"
TTS = HEROES_DIR.parent / "tts" / "george-washington.json"
OTHERS = [h for h in available_heroes() if h != "george-washington"]
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
W = "George Washington"

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Lead Astray": (2, W, "attack", 5, 2),
    "Agent 711": (2, W, "attack", 4, 3),
    "Allies Everywhere": (3, W, "attack", 1, 3),
    "Circumvent": (2, "any", "attack", 3, 2),
    "Sabotage": (2, "any", "attack", 3, 3),
    "Network Of Spies": (2, W, "versatile", 2, 2),
    "Make A Stand": (3, "any", "versatile", 3, 1),
    "Recruit To The Ring": (2, "any", "versatile", 2, 1),
    "Misinformation": (3, "any", "versatile", 4, 2),
    "Feint": (3, "any", "versatile", 2, 3),
    "Undercover Agent": (2, W, "defense", 1, 2),
    "Gather Information": (2, W, "scheme", None, 2),
    "Sympathetic Stain": (2, "Spy", "scheme", None, 3),
}
# idx order of the sheet, as read from the image
SHEET_ORDER = (["Lead Astray"] * 2 + ["Agent 711"] * 2 + ["Allies Everywhere"] * 3 + ["Circumvent"] * 2 + ["Sabotage"] * 2
               + ["Network Of Spies"] * 2 + ["Make A Stand"] * 3 + ["Recruit To The Ring"] * 2 + ["Misinformation"] * 3 + ["Feint"] * 3
               + ["Undercover Agent"] * 2 + ["Gather Information"] * 2 + ["Sympathetic Stain"] * 2)
RUSE_CARDS = {"Agent 711", "Circumvent", "Sabotage", "Allies Everywhere"}


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (18700, 187, 404)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert [e["title"] for e in sheet] == SHEET_ORDER
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert {e["title"] for e in sheet if e.get("tags") == ["ruse"]} == RUSE_CARDS and not [e for e in sheet if e.get("tags") not in (None, ["ruse"])]
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_the_sidekick_is_called_spy_because_the_cards_and_the_band_say_so(overlay):
    spies, = overlay["sidekicks"]
    assert (spies["fid"], spies["name"], spies["count"], spies["hp"], spies["start_on_board"]) == ("spy", "Spy", 3, 1, 3)
    assert spies["tts_tokens"] == ["Anna Strong", "Pompey Lamb", "Austin Roe"]
    assert [e["fighter"] for e in overlay["deck"]["sheet"] if e["title"] == "Sympathetic Stain"] == ["Spy", "Spy"]


def test_generated_herodef_is_a_melee_hero_with_three_spies_and_deals_a_real_deck():
    h = load_hero("george-washington")
    assert (h.name, h.fid, h.hp, h.move, h.ranged, h.reach_spaces) == (W, "washington", 14, 2, False, 0)
    spies, = h.sidekicks
    assert (spies.fid, spies.name, spies.count, spies.hp, spies.move, spies.ranged, spies.start_on_board) == ("spy", "Spy", 3, 1, 2, False, 3)
    assert [f.fid for f in h.fighters()] == ["washington", "spy1", "spy2", "spy3"]
    assert h.ability.startswith("ESPIONAGE\nYou start with 4 ruse tokens.")
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(18700, 18730))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
        assert ("ruse" in c.tags) == (c.title in RUSE_CARDS), c.title
        assert ("[RUSE]" in c.text) == (c.title in RUSE_CARDS), c.title
    by = {c.title: c for c in deck}
    assert by["Undercover Agent"].text == "DURING COMBAT: Washington may swap spaces with an adjacent Spy. If he does, that Spy is now the defender."
    assert by["Sympathetic Stain"].text.startswith("Choose an opponent and look at their hand. If a Spy is adjacent to one of their fighters")


def test_the_ai_profile_comes_from_the_data():
    profile = load_hero("george-washington").ai_profile
    assert set(profile) == {"washington", "spy"} and profile["washington"]["role"] == "hero" and not profile["washington"]["ranged"]
    assert profile["spy"]["count"] == 3 and profile["spy"]["max_hp"] == 1


def test_effects_validate_and_every_card_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "george-washington"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    assert not [c["title"] for c in effects["cards"] if c.get("ongoing") or c.get("may_boost") or c.get("uncancelable")]


def test_the_ruse_effects_are_exactly_the_cards_with_the_ruse_tag_and_read_the_counter(effects):
    reading_ruse = {"test": "counter", "name": "ruse", "min": 1}
    uses = {c["title"] for c in effects["cards"] if reading_ruse in list(_nodes(c["effects"]))}
    assert uses == RUSE_CARDS


def _nodes(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _nodes(v)


def test_espionage_is_three_triggers_on_two_counters_and_three_plugins(effects):
    ability = effects["ability"]
    assert ability["counters"] == {"ruse_tokens": {"min": 0, "max": 4, "start": 4}, "ruse": {"min": 0, "max": 1, "start": 0}}
    assert [t["id"] for t in ability["triggers"]] == ["espionage", "espionage_remove", "espionage_clear"]
    assert [t["when"]["event"] for t in ability["triggers"]] == ["attacked", "attacked", "after_attack"]
    assert [p["id"] for p in effects["plugins"]] == ["washington:use_ruse", "washington:offer_removal", "washington:replace_combatant"]
    assert ability["text"] == load_hero("george-washington").ability


def test_card_effects_say_what_the_real_cards_say(effects):
    by = {c["title"]: c for c in effects["cards"]}
    assert by["Agent 711"]["effects"]["after"][0]["then"] == [{"op": "damage", "target": "opposing", "amount": 7}]
    assert by["Circumvent"]["effects"]["during"][0]["then"] == [{"op": "set_value", "card": "opponent_card", "ignore": True}]
    assert by["Sabotage"]["effects"]["after"][0]["then"] == [
        {"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 2}}]
    assert by["Allies Everywhere"]["effects"]["after"][0] == {"op": "gain_action", "amount": 1}
    assert by["Allies Everywhere"]["effects"]["after"][1]["then"] == [{"op": "heal", "target": {"side": "own", "kind": "hero"}, "amount": 3}]
    assert by["Misinformation"]["effects"]["after"][0]["then"] == [{"op": "counter", "name": "ruse_tokens", "delta": 1}]
    assert by["Feint"]["effects"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card"}]
    assert by["Gather Information"]["effects"]["scheme"] == [
        {"op": "draw", "player": "owner", "amount": 3},
        {"op": "move", "target": {"side": "own", "pick": "all"}, "amount": 3, "up_to": True, "through_enemies": True, "chooser": "owner"}]
    assert by["Make A Stand"]["effects"]["during"][0]["then"] == [{"op": "set_value", "card": "this", "amount": 5}]


def test_feint_is_the_shared_card_worded_as_everyones(effects):
    mine = next(c for c in effects["cards"] if c["title"] == "Feint")
    for slug in ("bigfoot", "golden-bat", "yennefer-triss"):
        theirs = next((c for c in json.loads((HEROES_DIR / "effects" / f"{slug}.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Feint"), None)
        if theirs is not None:
            assert mine["effects"] == theirs["effects"] and mine["text"] == theirs["text"], slug


def test_table_data_names_the_pieces_the_dial_the_deck_range_and_its_own_images():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "george-washington" and tts["deck"]["card_ids"] == [18700, 18729] and tts["deck"]["character_card_id"] == 404
    assert set(tts["fighters"]) == {"washington", "spy1", "spy2", "spy3"} and tts["fighters"]["washington"]["dial_max"] == 14
    assert (tts["bag"]["guid"], tts["deck"]["guid"], tts["fighters"]["washington"]["piece"], tts["fighters"]["washington"]["dial"]) == (
        "a6447e", "15548c", "b4ab68", "166320")
    assert {k: v["nickname"] for k, v in tts["fighters"].items() if k != "washington"} == {
        "spy1": "Anna Strong", "spy2": "Pompey Lamb", "spy3": "Austin Roe"}
    assert all("dial" not in v for k, v in tts["fighters"].items() if k != "washington")        # a Spy has 1 hit point: no dial
    assert tts["tokens"] == {"ruse": "1c7d18"} and tts["counter_dials"] == {}


# ---------------------------------------------------------------- his own CardID range

@pytest.mark.parametrize("other", OTHERS)
def test_washington_shares_neither_card_ids_nor_images_with_any_other_deck(other):
    washington, theirs = load_hero_table("george-washington"), load_hero_table(other)
    assert washington.card_ids == (18700, 18729)
    assert theirs.card_ids[1] < 18700 or theirs.card_ids[0] > 18729
    assert not set(washington.identity) & set(theirs.identity)
    for bot, human in (("george-washington", other), (other, "george-washington")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_card_ids"] == list(load_hero_table(bot).card_ids) and defaults["human_card_ids"] == list(load_hero_table(human).card_ids)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", OTHERS)
def test_no_card_of_washington_equals_a_card_of_another_deck(other):
    assert not set(load_hero("george-washington").deck()) & set(load_hero(other).deck())


def test_washington_cards_are_never_medusas_and_medusas_never_his():
    assert not any(is_medusa_card(c) for c in load_hero("george-washington").deck())
    assert all(c not in set(load_hero("george-washington").deck()) for c in load_hero("medusa").deck())


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("george-washington", "george-washington")


def test_washington_is_detected_on_either_side_against_any_hero():
    for other in OTHERS:
        assert detect_heroes(reading(at_bot("george-washington"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("george-washington", other), other
        assert detect_heroes(reading(at_bot(other), at_human("george-washington")), BOT_SPOT, HUMAN_SPOT) == (other, "george-washington"), other


def test_the_catalog_names_washington_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("george-washington") == W
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("george-washington").identity]).slug == "george-washington"


def test_washington_shares_one_guid_with_bullseye_the_life_dial_and_none_with_any_other_hero():
    """Bag, deck, miniature, the three Spy tokens (Custom_Token in the save, which real TTS reports as "Tile") and the Ruse stack are his own. His
    life dial (Custom_Model 166320, 'George Washington') has the GUID of Bullseye's, as Tomoe Gozen's has Donatello's: the session tells them apart
    by the dial's name (`session_pieces.resolve_dials`; tests/test_piece_identity.py pins it, tests/test_george_washington_matrix.py plays the pair)."""
    mine = set(load_hero_table("george-washington").all_guids())
    assert len(mine) == 7
    shared = {}
    for slug in [p.stem for p in HEROES_DIR.parent.joinpath("tts").glob("*.json") if p.stem != "george-washington"]:
        common = mine & set(load_hero_table(slug).all_guids())
        if common:
            shared[slug] = sorted(common)
    assert shared == {"bullseye": ["166320"]}
    dial = load_hero_table("george-washington").fighters["washington"].dial
    assert dial == load_hero_table("bullseye").fighters["bullseye"].dial == "166320"
