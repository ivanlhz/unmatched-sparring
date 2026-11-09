"""Michelangelo's data: the overlay is sheet 176 of the tournament save read card by card, the generated HeroDef deals
the 30 real cards with the values printed on them, and data/heroes/effects/michelangelo.json covers every one in DSL v1
(docs/effects-dsl.md, section "Michelangelo"). No FakeTTS or sockets."""
import json
from collections import Counter

import pytest

from sparring.heroes import HEROES_DIR, load_hero
from tools.import_hero import build, memory_dir
from tools.validate_effects import validate_file

OVERLAY = HEROES_DIR / "overlay" / "michelangelo.json"
EFFECTS = HEROES_DIR / "effects" / "michelangelo.json"

# (copies, type, value, boost, restriction) read from the card images of sheet 176
SHEET = {
    "Hi-Yaaaaah!!": (3, "attack", 4, 3, "Michelangelo"),
    "Boisterous Beatdown": (3, "attack", 2, 1, "Michelangelo"),
    "Turtle Power!!": (2, "attack", 3, 3, "Michelangelo"),
    "Hard-Hitting Investigation": (3, "attack", 0, 3, "April O'Neil"),
    "Cowabunga!!": (3, "versatile", 3, 2, "Michelangelo"),
    "Let's Go!!": (3, "versatile", 3, 2, "any"),
    "Guaranteed Delivery": (3, "versatile", 3, 1, "any"),
    "Heroes In A Half Shell": (2, "defense", 5, 2, "Michelangelo"),
    "Back For Seconds": (2, "defense", 2, 1, "any"),
    "Nunchaku": (2, "scheme", None, 2, "Michelangelo"),
    "Michelangelo Is A Party Dude!!": (2, "scheme", None, 2, "Michelangelo"),
    "Shell Insertion": (2, "scheme", None, 3, "April O'Neil"),
}


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def ops_in(node):
    if isinstance(node, dict):
        yield from ([node["op"]] if "op" in node else [])
        for v in node.values():
            yield from ops_in(v)
    elif isinstance(node, list):
        for v in node:
            yield from ops_in(v)


def test_overlay_is_sheet_176_with_30_cards_in_the_order_of_the_image():
    ov = load(OVERLAY)
    assert ov["fid"] == "mikey" and ov["forms"] is None and ov["counters"] == {}
    assert ov["deck"]["card_base"] == 17600 and ov["deck"]["sheet_id"] == 176 and ov["deck"]["hero_card_id"] == 366
    sheet = ov["deck"]["sheet"]
    assert [e["idx"] for e in sheet] == list(range(30))
    assert Counter(e["title"] for e in sheet) == {t: n for t, (n, *_) in SHEET.items()}
    assert [e["title"] for e in sheet][:5] == ["Hi-Yaaaaah!!"] * 3 + ["Boisterous Beatdown"] * 2     # idx 0..4 as printed
    assert {e["fighter"] for e in sheet if e["title"] in ("Hard-Hitting Investigation", "Shell Insertion")} == {"April O'Neil"}


def test_generated_herodef_has_the_hero_the_sidekick_and_the_real_cards():
    h = load_hero("michelangelo")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Michelangelo", "mikey", 14, 3, False)
    april, = h.sidekicks
    assert (april.name, april.fid, april.count, april.hp, april.ranged) == ("April O'Neil", "april", 1, 6, True)
    deck = h.deck()
    assert [c.card_id for c in deck] == list(range(17600, 17630))
    for c in deck:
        copies, kind, value, boost, who = SHEET[c.title]
        assert (c.type, c.value, c.boost, c.fighter) == (kind, value, boost, who), c.title
    assert sum(1 for _ in deck) == sum(n for n, *_ in SHEET.values()) == 30


def test_pizza_party_hand_sizes_are_in_the_herodef_and_the_default_for_every_other_hero():
    h = load_hero("michelangelo")
    assert (h.hand_start, h.hand_max) == (3, 3) and "PIZZA PARTY" in h.ability
    for slug in ("medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"):
        assert (load_hero(slug).hand_start, load_hero(slug).hand_max) == (5, 7)


def test_the_cards_where_the_real_card_and_unmatched_memory_disagree_follow_the_card():
    by_title = {c.title: c for c in load_hero("michelangelo").deck()}
    assert by_title["Nunchaku"].text == "Add +1 to the value of Michelangelo's attacks this turn. Gain 1 action."
    assert "Bruce Lee" not in " ".join(c.text for c in by_title.values())
    assert by_title["Shell Insertion"].text.startswith("Choose two different effects")
    assert by_title["Heroes In A Half Shell"].text == "" and by_title["Hard-Hitting Investigation"].fighter == "April O'Neil"


@pytest.mark.skipif(not (memory_dir() / "data" / "heroes" / "michelangelo.json").is_file(),
                    reason="needs the unmatched-memory repo next to this one (absent in CI)")
def test_the_generated_file_is_what_the_importer_builds_today():
    built = build("michelangelo", memory_dir())
    assert built == load(HEROES_DIR / "michelangelo.json")


def test_effects_validate_and_cover_every_deck_card_without_plugins():
    assert validate_file(EFFECTS) == []
    eff = load(EFFECTS)
    assert eff["schema"] == 1 and eff["hero"] == "michelangelo"
    by_title = {c["title"]: c for c in eff["cards"]}
    assert set(by_title) == {c.title for c in load_hero("michelangelo").deck()}
    assert {t: c["copies"] for t, c in by_title.items()} == {t: n for t, (n, *_) in SHEET.items()}
    assert all(c["effects"][m] is not None for c in eff["cards"] for m in ("immediately", "during", "after", "scheme", "boost"))
    assert eff["plugins"] == [] and "plugin" not in set(ops_in(eff["cards"])) | set(ops_in(eff["ability"]))
    assert eff["hidden_info"] and eff["open_questions"]
    assert by_title["Turtle Power!!"]["may_boost"] is True


def test_pizza_party_is_a_draw_after_an_attack_and_after_a_scheme():
    ab = load(EFFECTS)["ability"]
    attack, scheme = ab["triggers"]
    assert attack["when"] == {"event": "after_attack", "fighter": {"side": "own"}}
    assert scheme["when"] == {"event": "after_scheme", "player": "owner"}
    assert attack["ops"] == scheme["ops"] == [{"op": "draw", "player": "owner", "amount": 1}]
    assert ab["passives"] == []


def test_the_shell_insertion_offers_four_effects_and_picks_two_different_ones():
    card = {c["title"]: c for c in load(EFFECTS)["cards"]}["Shell Insertion"]
    choose, = card["effects"]["scheme"]
    assert choose["op"] == "choose_effect" and choose["amount"] == 2 and choose["distinct"] is True
    assert len(choose["options"]) == 4
    discard = choose["options"][0]["ops"][0]
    assert discard["cards"]["player"] == "opponent" and discard["cards"]["chooser"] == "opponent"


def test_nunchaku_is_a_fighter_status_on_the_hero_until_the_end_of_the_turn():
    card = {c["title"]: c for c in load(EFFECTS)["cards"]}["Nunchaku"]
    status, action = card["effects"]["scheme"]
    assert status == {"op": "status", "name": "attack_bonus", "target": "hero", "amount": 1, "until": {"event": "end_of_turn"}}
    assert action == {"op": "gain_action", "amount": 1} and card.get("ongoing") is None
