"""Yennefer & Triss' data: overlay, generated HeroDefs (one per variant), structured effects (DSL v1) and table data agree with each other
and with the real cards of sheet 176 and the two character cards of the tournament save (read from the images on 2026-11-09), and the
deck is told apart from the other decks of the sheet by image and owner. The two variants are one deck: the hero miniature on the table
tells which one is meant. No engine, no TTS, no sockets."""
import json

import pytest

from sparring.hero_catalog import load_catalog
from sparring.hero_detect import HeroDetectionError, detect_heroes
from sparring.heroes import HEROES_DIR, load_hero
from sparring.tts.hero_table import load_hero_table, table_defaults
from tools.validate_effects import validate_file
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, SLUGS, TableReading, at_bot, at_human

VARIANTS = {"yennefer-triss": ("Yennefer", "Triss", 351), "triss-yennefer": ("Triss", "Yennefer", 352)}
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
SHARING = ["medusa", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent", "she-hulk", "tomoe-gozen"]
EVERYONE = SHARING + ["hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "houdini"]

# (copies, band, type, value, boost) as printed on the cards.
REAL_CARDS = {
    "Incinerate": (3, "Yennefer", "attack", 7, 2),
    "Echoing blast": (3, "any", "attack", 3, 1),
    "Portal to anywhere": (3, "any", "attack", 1, 2),
    "Merigold's Hailstorm": (2, "Triss", "attack", 4, 3),
    "Telepathy": (3, "any", "versatile", 3, 1),
    "Quick and ready": (2, "any", "versatile", 2, 2),
    "Ball lightning": (3, "any", "versatile", 3, 1),
    "Paralyzing fetters": (3, "any", "defense", 2, 2),
    "Magical barrier": (3, "any", "defense", 4, 3),
    "Advisor to the king": (3, "any", "scheme", None, 2),
    "Lodge of sorceresses": (2, "any", "scheme", None, 2),
}
SHEET_ORDER = (["Incinerate"] * 3 + ["Echoing blast"] * 3 + ["Portal to anywhere"] * 3 + ["Merigold's Hailstorm"] * 2 + ["Telepathy"] * 3
               + ["Quick and ready"] * 2 + ["Ball lightning"] * 3 + ["Paralyzing fetters"] * 3 + ["Magical barrier"] * 3
               + ["Advisor to the king"] * 3 + ["Lodge of sorceresses"] * 2)


def overlay(slug):
    return json.loads((HEROES_DIR / "overlay" / f"{slug}.json").read_text(encoding="utf-8"))


def effects(slug):
    return json.loads((HEROES_DIR / "effects" / f"{slug}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("slug", VARIANTS)
def test_overlay_sheet_matches_the_real_cards_and_the_save_numbering(slug):
    ov = overlay(slug)
    deck = ov["deck"]
    assert (deck["card_base"], deck["sheet_id"], deck["hero_card_id"]) == (17600, 176, VARIANTS[slug][2])
    assert [e["idx"] for e in deck["sheet"]] == list(range(30)) and [e["title"] for e in deck["sheet"]] == SHEET_ORDER
    for title, (copies, band, *_) in REAL_CARDS.items():
        entries = [e for e in deck["sheet"] if e["title"] == title]
        assert len(entries) == copies and {e["fighter"] for e in entries} == {band}, title
    assert ov["tts"]["character_cards"] == [351, 352] and ov["tts"]["bag_name"] == "Yennefer & Triss"


@pytest.mark.parametrize("slug,hero,side,card", [(s, *v) for s, v in VARIANTS.items()])
def test_generated_herodef_is_a_14_life_hero_with_one_6_life_sidekick_and_the_real_deck(slug, hero, side, card):
    h = load_hero(slug)
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == (hero, hero.lower(), 14, 2, True)
    assert [(s.fid, s.name, s.count, s.hp, s.move, s.ranged) for s in h.sidekicks] == [(side.lower(), side, 1, 6, 2, True)]
    assert [(f.fid, f.hero) for f in h.fighters()] == [(hero.lower(), True), (side.lower(), False)]
    for c in h.deck():
        copies, band, kind, value, boost = REAL_CARDS[c.title]
        assert (c.fighter, c.type, c.value, c.boost) == ({"any": "any"}.get(band, band), kind, value, boost), c.title
    assert [c.card_id for c in h.deck()] == list(range(17600, 17630))
    advisor = next(c for c in h.deck() if c.title == "Advisor to the king")
    assert "ONGOING: Your BOOST values are +1" in advisor.text and "if you didn't attack" in advisor.text


def test_each_variant_carries_only_its_heroines_ability():
    y, t = load_hero("yennefer-triss"), load_hero("triss-yennefer")
    assert y.ability.startswith("SORCERESS OF VENGERBERG") and "BOOST her attack" in y.ability
    assert t.ability.startswith("MERIGOLD THE FEARLESS") and "2 damage to a fighter adjacent to Triss" in t.ability


@pytest.mark.parametrize("slug", VARIANTS)
def test_effects_validate_and_every_card_has_ops(slug):
    path = HEROES_DIR / "effects" / f"{slug}.json"
    assert validate_file(path) == []
    fx = effects(slug)
    assert fx["hero"] == slug and sorted(c["title"] for c in fx["cards"]) == sorted(REAL_CARDS)
    for card in fx["cards"]:
        assert card["copies"] == REAL_CARDS[card["title"]][0]
        assert any(card["effects"].get(m) for m in MOMENTS), card["title"]
        assert (REAL_CARDS[card["title"]][2] == "scheme") == bool(card["effects"]["scheme"])
    prefix = VARIANTS[slug][0].lower()
    assert [p["id"] for p in fx["plugins"]] == [f"{prefix}:mill", f"{prefix}:lodge"]


def test_the_abilities_in_the_data():
    y, t = effects("yennefer-triss")["ability"], effects("triss-yennefer")["ability"]
    assert y["triggers"] == [] and y["passives"] == [{"id": "sorceress_of_vengerberg", "kind": "may_boost", "fighter": {"side": "own", "name": "Yennefer"}}]
    assert t["passives"] == [] and t["triggers"][0]["when"] == {"event": "after_scheme", "player": "owner"}
    assert t["triggers"][0]["ops"][0]["amount"] == 2 and t["triggers"][0]["ops"][0]["target"]["where"] == {"adjacent_to": "this"}


def test_card_effects_say_what_the_real_cards_say():
    by = {c["title"]: c for c in effects("yennefer-triss")["cards"]}
    assert by["Incinerate"]["uncancelable"] and by["Incinerate"]["effects"]["during"][0]["chooser"] == "opponent"
    assert by["Paralyzing fetters"]["effects"]["immediately"] == [{"op": "lock_value", "card": "opponent_card"}]
    assert by["Magical barrier"]["effects"]["immediately"] == [{"op": "heal", "target": "this", "amount": 1}]
    assert [o["label"] for o in by["Merigold's Hailstorm"]["effects"]["after"][0]["options"]] == [
        "You discard 2 cards", "Your hero takes 3 damage", "Discard the top 4 cards of your deck"]
    adv = by["Advisor to the king"]["ongoing"]
    assert adv["modifiers"] == [{"kind": "rule", "rule": "boost_bonus", "amount": 1}] and "until_condition" in adv
    assert by["Quick and ready"]["effects"]["after"][0]["where"] == {"zone_of": "opposing"}


def test_incinerate_is_word_for_word_liz_shermans():
    mine = next(c for c in effects("yennefer-triss")["cards"] if c["title"] == "Incinerate")
    liz = next(c for c in json.loads((HEROES_DIR / "effects" / "liz-sherman.json").read_text(encoding="utf-8"))["cards"] if c["title"] == "Incinerate")
    assert mine["text"] == liz["text"] and mine["effects"] == liz["effects"] and mine["uncancelable"] == liz["uncancelable"]


@pytest.mark.parametrize("slug,hero,side,card", [(s, *v) for s, v in VARIANTS.items()])
def test_table_data_names_the_pieces_dials_deck_and_character_card_of_the_variant(slug, hero, side, card):
    tts = json.loads((HEROES_DIR.parent / "tts" / f"{slug}.json").read_text(encoding="utf-8"))
    assert tts["slug"] == slug and tts["deck"]["card_ids"] == [17600, 17629] and tts["deck"]["character_card_id"] == card
    assert (tts["bag"]["guid"], tts["bag"]["inner"], tts["deck"]["guid"]) == ("2b339c", "eaf05e", "7b2a33")
    f = tts["fighters"]
    assert f[hero.lower()]["dial_max"] == 14 and f[side.lower()]["dial_max"] == 6
    pieces = {"yennefer-triss": {"yennefer": ("cd27f6", "d4701d"), "triss": ("905f88", "00da50")},
              "triss-yennefer": {"triss": ("d1b3b9", "799107"), "yennefer": ("de2677", "4dbc76")}}[slug]
    assert {k: (v["piece"], v["dial"]) for k, v in f.items()} == pieces


def test_the_two_variants_share_the_deck_and_nothing_else():
    y, t = load_hero_table("yennefer-triss"), load_hero_table("triss-yennefer")
    assert (y.bag, y.deck_guid, y.card_ids, y.identity) == (t.bag, t.deck_guid, t.card_ids, t.identity)
    assert y.character_card_id == 351 and t.character_card_id == 352
    own = lambda tb: {g for f in tb.fighters.values() for g in (*f.pieces, f.dial)}
    assert not own(y) & own(t)


# ---------------------------------------------------------------- the shared CardID range

@pytest.mark.parametrize("other", SHARING)
def test_the_deck_shares_the_card_range_but_not_the_images_with_the_other_decks_of_the_sheet(other):
    mine, theirs = load_hero_table("yennefer-triss"), load_hero_table(other)
    assert mine.card_ids == (17600, 17629) and not set(mine.identity) & set(theirs.identity)
    for bot, human in (("yennefer-triss", other), (other, "triss-yennefer")):
        defaults = table_defaults(bot, human)
        assert defaults["bot_identity"] != defaults["human_identity"]


@pytest.mark.parametrize("other", SHARING)
def test_no_card_of_the_deck_equals_a_card_of_the_other_decks_of_the_range(other):
    assert not set(load_hero("yennefer-triss").deck()) & set(load_hero(other).deck())


def test_the_two_variants_cannot_be_the_two_sides_of_a_table():
    from sparring.tts.hero_table import HeroTableError
    with pytest.raises(HeroTableError):
        table_defaults("yennefer-triss", "yennefer-triss")


def test_the_catalog_names_the_deck():
    catalog = load_catalog()
    assert catalog.name_of("yennefer-triss") == "Yennefer & Triss"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("yennefer-triss").identity]).slug == "yennefer-triss"


# ---------------------------------------------------------------- detection: the hero miniature tells the variant

def both(side_pile):
    """The pile of a table that holds this deck: its cards count for both variants (same images and CardIDs)."""
    counts = [30 if s in VARIANTS else 0 for s in SLUGS]
    return {**side_pile, "counts": counts}


def reading_of(*piles, pieces=()):
    return TableReading(list(piles), {g: (0.0, 0.0) for g in pieces}, SLUGS)


@pytest.mark.parametrize("slug,hero_piece", [("yennefer-triss", "cd27f6"), ("triss-yennefer", "d1b3b9")])
@pytest.mark.parametrize("other", EVERYONE)
def test_the_variant_whose_hero_miniature_is_out_is_detected_on_either_side(slug, hero_piece, other):
    r = lambda *piles: reading_of(*piles, pieces=(hero_piece,))
    assert detect_heroes(r(both(at_bot("medusa")), at_human(other)), BOT_SPOT, HUMAN_SPOT, (None, other))[0] == slug
    assert detect_heroes(r(at_bot(other), both(at_human("medusa"))), BOT_SPOT, HUMAN_SPOT, (other, None))[1] == slug


def test_the_sidekick_token_alone_does_not_decide_and_neither_does_nothing_nor_both():
    deck = both(at_bot("medusa"))
    for pieces in ((), ("905f88",), ("cd27f6", "d1b3b9")):
        with pytest.raises(HeroDetectionError, match="No puedo saber que heroina"):
            detect_heroes(reading_of(deck, at_human("hellboy"), pieces=pieces), BOT_SPOT, HUMAN_SPOT)
