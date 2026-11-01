"""Raphael's data: overlay, generated HeroDef, structured effects (DSL v1) and table data agree with each other and with
the real cards of sheet 176 of the tournament save (read from the images on 2026-11-01). No engine, no TTS, no sockets."""
import json

import pytest

from sparring.heroes import HEROES_DIR, load_hero
from tools.validate_effects import validate_file

OVERLAY = HEROES_DIR / "overlay" / "raphael.json"
EFFECTS = HEROES_DIR / "effects" / "raphael.json"
TTS = HEROES_DIR.parent / "tts" / "raphael.json"
MOMENTS = ("immediately", "during", "after", "scheme", "boost")

# (copies, restriction, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Unbridled rage": (2, "Raphael", "attack", 3, 4),
    "Let's do this!": (3, "Raphael", "attack", 1, 3),
    "Turtle power!": (2, "Raphael", "attack", 3, 3),
    "Crowd control": (3, "any", "attack", 2, 1),
    "Batter up!": (3, "Casey Jones", "attack", 3, 2),
    "Sai": (2, "Raphael", "versatile", 4, 2),
    "Break something": (3, "Raphael", "versatile", 2, 1),
    "Payback time!": (3, "any", "versatile", 2, 1),
    "Relentless": (2, "any", "versatile", 3, 1),
    "Slapshot": (3, "Casey Jones", "versatile", 2, 2),
    "Heroes in a half shell": (2, "Raphael", "defense", 5, 2),
    "Raphael is cool but rude": (2, "Raphael", "scheme", None, 2),
}
VANILLA = {"Sai", "Heroes in a half shell"}


@pytest.fixture(scope="module")
def overlay():
    return json.loads(OVERLAY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def effects():
    return json.loads(EFFECTS.read_text(encoding="utf-8"))


def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(overlay):
    deck = overlay["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, 368)
    sheet = deck["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    for title, (copies, fighter, *_) in REAL_CARDS.items():
        entries = [e for e in sheet if e["title"] == title]
        assert len(entries) == copies, title
        assert {e["fighter"] for e in entries} == {fighter}, title
    assert sum(c for c, *_ in REAL_CARDS.values()) == 30
    assert overlay["sidekicks"] == [{"fid": "casey", "name": "Casey Jones"}]
    assert overlay["forms"] is None and overlay["counters"] == {} and overlay["triggers"] == [] and overlay["passives"] == []


def test_generated_herodef_deals_a_real_deck():
    h = load_hero("raphael")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Raphael", "raphael", 17, 2, False)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("casey", "Casey Jones", 1, 8, 2, True)]
    assert h.ability == "ANGER ISSUES\nOn each of your turns, the first time you lose combat, gain 1 action."
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, fighter, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == (fighter, kind, value, boost), c.title
        assert (c.text == "") == (c.title in VANILLA), c.title
    assert sum(1 for c in deck if c.fighter == "Casey Jones") == 6
    # the real text of the card (overlay `text`) wins over unmatched-memory's typos
    assert all("COMBAR" not in c.text and "canceled this way" in c.text for c in deck if c.title == "Break something")
    assert all("into your deck" in c.text for c in deck if c.title == "Relentless")


def test_the_ai_profile_knows_casey_is_a_ranged_striker():
    profile = load_hero("raphael").ai_profile
    assert profile["raphael"]["role"] == "hero" and profile["casey"]["role"] == "striker" and profile["casey"]["ranged"]
    assert {e["title"] for e in profile["casey"]["exclusive"]} == {"Batter up!", "Slapshot"}


def test_effects_validate_and_every_card_with_text_has_ops(effects):
    assert validate_file(EFFECTS) == []
    assert effects["schema"] == 1 and effects["hero"] == "raphael"
    titles = [c["title"] for c in effects["cards"]]
    assert sorted(titles) == sorted(REAL_CARDS) and len(titles) == len(set(titles))
    for card in effects["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        has_ops = bool(any(card["effects"][m] for m in MOMENTS) or card.get("may_boost"))
        assert has_ops == (card["title"] not in VANILLA), card["title"]
        assert (card["title"] == "Raphael is cool but rude") == bool(card["effects"]["scheme"])
        assert card.get("ongoing") is None


def test_anger_issues_is_a_trigger_on_the_first_lost_combat_of_the_turn(effects):
    trig, = effects["ability"]["triggers"]
    assert trig["when"] == {"event": "combat_lost", "player": "owner"}
    assert trig["condition"] == {"test": "compare", "left": {"stat": "combats_lost_this_turn", "player": "owner"},
                                 "op": "==", "right": 1}
    assert trig["ops"] == [{"op": "gain_action", "amount": 1}]
    assert effects["ability"]["passives"] == [] and [p["id"] for p in effects["plugins"]] == ["raphael:unbridled_rage"]


def test_card_effects_use_the_new_ops_the_way_the_docs_say(effects):
    by = {c["title"]: c["effects"] for c in effects["cards"]}
    assert by["Break something"]["immediately"] == [{"op": "cancel_effects", "card": "opponent_card", "moments": ["during", "after"]}]
    assert by["Break something"]["after"][0]["condition"] == {"not": {"test": "effects_canceled", "card": "opponent_card"}}
    assert by["Relentless"]["after"][0] == {"op": "return_to_deck", "cards": "this", "position": "shuffle"}
    assert by["Raphael is cool but rude"]["scheme"][0]["target"]["filter"] == {"adjacent_to_any": {"side": "own"}}
    payback, = by["Payback time!"]["during"]
    assert payback["then"] == [{"op": "set_value", "card": "this", "amount": 5}]
    slap, = by["Slapshot"]["during"]
    assert slap["then"] == [{"op": "set_value", "card": "this", "amount": 6}]
    assert next(c for c in effects["cards"] if c["title"] == "Turtle power!")["may_boost"] is True


def test_table_data_names_both_pieces_and_the_deck_range():
    tts = json.loads(TTS.read_text(encoding="utf-8"))
    assert tts["slug"] == "raphael" and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == 368
    assert set(tts["fighters"]) == {"raphael", "casey"}
    assert (tts["fighters"]["raphael"]["dial_max"], tts["fighters"]["casey"]["dial_max"]) == (17, 8)
    assert tts["tokens"] == {} and tts["counter_dials"] == {}
