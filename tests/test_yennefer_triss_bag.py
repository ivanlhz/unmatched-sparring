"""F-YT-BAG: the Yennefer & Triss bag of the tournament save holds NINE objects (one shared deck, two hero miniatures, two sidekick
tokens, four life dials) and serves two variants (`yennefer-triss`, `triss-yennefer`), each of which is a five-object HeroTable.
Every test here uses that real bag: the GUIDs and TTS types below were read from the save (inner bag `eaf05e` of the infinite bag
`2b339c`) and `test_the_nine_objects_...` checks them against the save itself when it is on this machine. Never a five-object fake."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sparring import hero_detect, player_setup
from sparring.i18n import t
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table, variants_of
from test_official_save_setup import tts  # noqa: F401
from test_player_setup import bag_row, decide, reading, run, seen

lupa = pytest.importorskip("lupa")

YT, TY = "yennefer-triss", "triss-yennefer"
INNER_BAG, OUTER_BAG = "eaf05e", "2b339c"
# GUID -> TTS type of the nine objects inside the inner bag, as the save lists them
REAL_BAG = {"de2677": "Custom_Token", "905f88": "Custom_Token", "d1b3b9": "Custom_Model", "cd27f6": "Custom_Model",
            "4dbc76": "Custom_Model", "799107": "Custom_Model", "00da50": "Custom_Model", "d4701d": "Custom_Model",
            "7b2a33": "DeckCustom"}
ROOT = Path(__file__).resolve().parents[1]
SAVE_NAME = "Unmatched Official Tournament Table October 2026 (Hellboy).json"
YT_ONLY = {"cd27f6", "d4701d", "905f88", "00da50"}          # the Yennefer-leads variant's own pieces (hero miniature, dial, sidekick token, dial)
TY_ONLY = {"d1b3b9", "799107", "de2677", "4dbc76"}
DECK = "7b2a33"


def the_save() -> Path | None:
    """The tournament save, read only: in this checkout's saves/ or, for a worktree, in the main checkout's."""
    for base in (ROOT, *ROOT.parents):
        if (base / "saves" / SAVE_NAME).is_file():
            return base / "saves" / SAVE_NAME
    return None


def family_bag(x: float, guid: str = "copyyt", guids=None) -> dict:
    return bag_row(YT, x, guid, guids if guids is not None else list(REAL_BAG))


def family_deck(x: float, guid: str = "deckyt") -> dict:
    slugs = hero_detect.hero_slugs()
    return {"type": "Deck", "guid": guid, "x": x, "z": 17.0, "name": "", "size": 32, "pairs": [], "down": True,
            "counts": [30 if s in (YT, TY) else 0 for s in slugs]}


# ---------- the data ----------
def test_the_nine_objects_are_the_union_of_both_variants_and_match_the_save():
    union = {g for slug in (YT, TY) for g in load_hero_table(slug).all_guids()}
    assert union == set(REAL_BAG) and len(REAL_BAG) == 9
    assert {*load_hero_table(YT).all_guids()} == YT_ONLY | {DECK} and {*load_hero_table(TY).all_guids()} == TY_ONLY | {DECK}
    path = the_save()
    if path is None:
        pytest.skip("the tournament save is not on this machine")
    raw = json.loads(path.read_text(encoding="utf-8"))
    inner = next(o for o in _walk(raw["ObjectStates"]) if o["GUID"] == INNER_BAG)
    assert {o["GUID"]: o["Name"] for o in inner["ContainedObjects"]} == \
        {g: ("DeckCustom" if ty == "DeckCustom" else ty) for g, ty in REAL_BAG.items()}


def _walk(objects):
    for o in objects:
        yield o
        yield from _walk(o.get("ContainedObjects") or [])


def test_the_two_variants_are_one_family_ordered_by_their_character_card():
    assert variants_of(YT) == variants_of(TY) == (YT, TY)
    assert variants_of("bigfoot") == ("bigfoot",)


# ---------- recognising the bag ----------
def test_the_real_nine_object_bag_is_the_family_and_not_a_bag_i_do_not_recognise():
    tables = {s: load_hero_table(s) for s in hero_detect.hero_slugs()}
    assert player_setup._bag_hero(list(REAL_BAG), tables) is None, "it fits neither variant's five objects"
    found = seen([family_bag(-7), bag_row("bigfoot", 7)])
    mine = next(s for s in found.sightings if s.side == "human")
    assert (mine.kind, mine.slug, mine.variants) == ("bag", None, (YT, TY)) and mine.items == 9


@pytest.mark.parametrize("held, slug", [(YT_ONLY | {DECK}, YT), (TY_ONLY | {DECK}, TY), (YT_ONLY, YT), ({"cd27f6", DECK}, YT), ({"de2677"}, TY)])
def test_a_bag_that_holds_only_one_variants_pieces_is_that_variant_and_asks_nothing(held, slug):
    found = seen([family_bag(-7, guids=sorted(held)), bag_row("bigfoot", 7)])
    mine = next(s for s in found.sightings if s.side == "human")
    assert (mine.slug, mine.variants) == (slug, ())
    assert player_setup.question(found) is None


def test_a_bag_with_the_shared_deck_and_pieces_of_both_variants_still_asks():
    found = seen([family_bag(-7, guids=[DECK, "cd27f6", "d1b3b9", "4dbc76"]), bag_row("bigfoot", 7)])
    assert player_setup.question(found) == (YT, TY)


def test_a_bag_of_the_family_with_a_foreign_object_is_nobodys():
    tables = {s: load_hero_table(s) for s in hero_detect.hero_slugs()}
    assert player_setup._bag_hero([*REAL_BAG, "zzz999"], tables) is None
    assert player_setup._bag_hero([DECK, *load_hero_table("bigfoot").all_guids()[1:3]], tables) is None


def test_a_loose_shared_deck_is_the_family_and_not_two_heroes_on_a_half():
    found = seen(piles=[family_deck(-9), {**family_deck(7, "deckbf"), "counts": [30 if s == "bigfoot" else 0 for s in hero_detect.hero_slugs()]}])
    mine = [s for s in found.sightings if s.side == "human"]
    assert [(s.kind, s.slug, s.variants) for s in mine] == [("deck", None, (YT, TY))]


# ---------- the question and the decision ----------
def test_the_human_side_is_asked_which_heroine_leads_and_the_answer_makes_the_setup(tmp_path):
    found = seen([family_bag(-7), bag_row("bigfoot", 7)])
    assert player_setup.question(found) == (YT, TY)
    setup, problems = decide(found, tmp_path / "none.json")
    assert setup is None and t("setup.family_unchosen", names=t("common.and").join(("Yennefer", "Triss"))) in problems
    for pick in (YT, TY):
        setup, problems = player_setup.decide(found, tmp_path / "none.json", picks={player_setup.HUMAN: pick})
        assert problems == [] and (setup.bot, setup.human) == ("bigfoot", pick)
        assert setup.bags == {"bigfoot": "copybigfoot", pick: "copyyt"}, "the chosen variant owns the bag the player dropped"


def test_an_answer_that_is_not_one_of_the_family_is_ignored_and_asked_again(tmp_path):
    found = seen([family_bag(-7), bag_row("bigfoot", 7)])
    setup, problems = player_setup.decide(found, tmp_path / "none.json", picks={player_setup.HUMAN: "bigfoot"})
    assert setup is None and problems


def test_the_bot_leads_with_yennefer_unless_the_configuration_fixes_the_other(tmp_path):
    found = seen([family_bag(7), bag_row("bigfoot", -7)])
    assert player_setup.question(found) is None, "only the human is asked"
    setup, problems = player_setup.decide(found, tmp_path / "none.json")
    assert problems == [] and (setup.bot, setup.human) == (YT, "bigfoot") and setup.bags[YT] == "copyyt"
    setup, _ = player_setup.decide(found, tmp_path / "none.json", bot_hero=TY)
    assert setup.bot == TY
    setup, _ = player_setup.decide(found, tmp_path / "none.json", bot_hero="bigfoot")
    assert setup.bot == YT, "a configured hero outside the family changes nothing"


def test_the_box_on_both_halves_is_refused_with_one_clear_line(tmp_path):
    found = seen([family_bag(7, "copyA"), family_bag(-7, "copyB")])
    setup, problems = player_setup.decide(found, tmp_path / "none.json", picks={player_setup.HUMAN: YT})
    assert setup is None and len(problems) == 1
    assert problems[0] == t("setup.same_family", names=t("common.and").join(("Yennefer", "Triss")))
    assert "Yennefer" in problems[0] and "Triss" in problems[0] and "same hero" not in problems[0]


def test_two_variants_of_the_family_on_the_two_halves_are_the_same_refusal(tmp_path):
    found = seen([family_bag(7, "copyA", guids=sorted(YT_ONLY | {DECK})), family_bag(-7, "copyB", guids=sorted(TY_ONLY | {DECK}))])
    setup, problems = player_setup.decide(found, tmp_path / "none.json")
    assert setup is None and problems == [t("setup.same_family", names=t("common.and").join(("Yennefer", "Triss")))]


def test_a_family_bag_plus_another_hero_on_the_same_half_is_refused_before_any_question(tmp_path):
    found = seen([family_bag(-7), bag_row("houdini", -9), bag_row("bigfoot", 7)])
    assert player_setup.question(found) is None
    setup, problems = decide(found, tmp_path / "none.json")
    assert setup is None and "dos heroes" in problems


def test_the_family_is_asked_once_even_when_the_map_is_missing_is_not_the_questions_business(tmp_path):
    found = seen([family_bag(-7), bag_row("bigfoot", 7)], board=None)
    assert player_setup.question(found) == (YT, TY)
    setup, problems = player_setup.decide(found, tmp_path / "none.json", picks={player_setup.HUMAN: TY})
    assert setup is None and any("mapa" in p.lower() for p in problems)


# ---------- the Lua: the second character card and the leftover bag ----------
def yt_deck(tts, with_cards=(351, 352), x=-9.0):  # noqa: F811
    """The shared deck as it leaves the bag: the 30 cards of the range plus both character cards, face up."""
    table = load_hero_table(YT)
    cards = ", ".join(f"{{cid = {table.card_ids[0] + i}, guid = 'y{i}', owner = '{YT}'}}" for i in range(30))
    chars = ", ".join(f"{{cid = {cid}, guid = 'char{cid}', owner = 'sheet3'}}" for cid in with_cards)
    tts.execute(f"mkobj({{guid = '{DECK}', type = 'Deck', is_face_down = false, pos = Vector({x}, 1.5, 17), "
                f"cards = {{{chars}{', ' if chars else ''}{cards}}}}})")


def side(character: int, spare: tuple = ()):
    table = load_hero_table(YT)
    identity = tuple((f"https://img.test/{YT}/face", f"https://img.test/{YT}/back") for _ in table.identity)
    return (DECK, table.card_ids, identity, character, (-5.0, 1.8, 15.0), (0, 90, 0), *([spare] if spare else []))


def deck_cids(tts):  # noqa: F811
    deck = tts.globals().getObjectFromGUID(DECK)
    return [deck.cards[i].cid for i in range(1, len(deck.cards) + 1)]


@pytest.mark.parametrize("chosen, other", [(351, 352), (352, 351)])
def test_the_variants_character_card_goes_out_and_the_other_heroines_is_destroyed(tts, chosen, other):  # noqa: F811
    yt_deck(tts)
    assert run(tts, lua.take_character_cards([side(chosen, (other,))])) == [{"found": True, "taken": True, "spared": 1}]
    assert len(deck_cids(tts)) == 30 and chosen not in deck_cids(tts) and other not in deck_cids(tts)
    assert tts.globals().getObjectFromGUID(f"char{chosen}").type == "Card"
    assert tts.globals().getObjectFromGUID(f"char{other}") is None, "the spare card is out of play"


def test_without_the_spare_the_shared_deck_is_not_recognised_which_was_the_hole(tts):  # noqa: F811
    yt_deck(tts)
    assert run(tts, lua.take_character_cards([side(351)])) == [{"found": False, "taken": False}]
    assert len(deck_cids(tts)) == 32


def test_a_second_press_changes_nothing(tts):  # noqa: F811
    yt_deck(tts)
    run(tts, lua.take_character_cards([side(351, (352,))]))
    assert run(tts, lua.take_character_cards([side(351, (352,))])) == [{"found": True, "taken": False}]
    assert len(deck_cids(tts)) == 30


def test_a_deck_that_kept_only_the_other_heroines_card_is_still_cleaned(tts):  # noqa: F811
    yt_deck(tts, with_cards=(352,))
    assert len(deck_cids(tts)) == 31
    assert run(tts, lua.take_character_cards([side(351, (352,))])) == [{"found": True, "taken": False, "spared": 1}]
    assert len(deck_cids(tts)) == 30


def real_bag(tts, guid="copyyt", x=-7.0):  # noqa: F811
    items = ", ".join(f"{{guid = '{g}', type = '{ty}'}}" for g, ty in REAL_BAG.items())
    tts.execute(f"mkobj({{guid = '{guid}', type = 'Bag', pos = Vector({x}, 1.6, 30), items = {{{items}}}}})")


def bag_left(tts, guid="copyyt"):  # noqa: F811
    bag = tts.globals().getObjectFromGUID(guid)
    return None if bag is None else sorted(bag["items"][i]["guid"] for i in range(1, len(bag["items"]) + 1))


def unpack_rows(slug):
    table = load_hero_table(slug)
    return [(kind, guids, "copyyt", (-24.0 + 3 * n, 2.5, 10.5), None) for n, (kind, guids) in enumerate(table.unpack_items())]


@pytest.mark.parametrize("slug, own, other", [(YT, YT_ONLY, TY_ONLY), (TY, TY_ONLY, YT_ONLY)])
def test_only_the_chosen_variants_five_objects_come_out_of_the_nine_and_the_bag_goes(tts, slug, own, other):  # noqa: F811
    real_bag(tts)
    spare = tuple(sorted(other))
    res = run(tts, lua.unpack_from_bags(unpack_rows(slug), None, ("copyyt",), spare))
    assert sorted(res["taken"]) == sorted(own | {DECK}) and res["missing"] == []
    for g in own | {DECK}:
        assert tts.globals().getObjectFromGUID(g) is not None, g
    for g in other:
        assert tts.globals().getObjectFromGUID(g) is None, f"{g} of the other heroine is not placed"
    assert bag_left(tts) is None, "the dropped copy is destroyed once only the other heroine's four are left"


def test_a_bag_with_anything_else_left_is_not_destroyed(tts):  # noqa: F811
    real_bag(tts)
    tts.execute("getObjectFromGUID('copyyt').items[#getObjectFromGUID('copyyt').items + 1] = {guid = 'keepme', type = 'Custom_Model'}")
    run(tts, lua.unpack_from_bags(unpack_rows(YT), None, ("copyyt",), tuple(sorted(TY_ONLY))))
    assert bag_left(tts) == sorted([*TY_ONLY, "keepme"])


def test_without_a_spare_list_the_old_rule_holds_and_a_bag_with_leftovers_stays(tts):  # noqa: F811
    real_bag(tts)
    run(tts, lua.unpack_from_bags(unpack_rows(YT), None, ("copyyt",)))
    assert bag_left(tts) == sorted(TY_ONLY)
