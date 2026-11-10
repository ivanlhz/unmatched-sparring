"""F-YT-BAG, the cases around the nine-object bag: a bag without its deck and the shared deck loose, the hero miniature already out on the
table, the same box twice, what the configuration fixes, the calibration tool, and the guard that keeps the gate from destroying a bag
that is not the player's drop. Same real GUIDs as `test_yennefer_triss_bag`."""
from __future__ import annotations

import pytest

from sparring import hero_detect, player_setup
from sparring.i18n import t
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from test_official_save_setup import tts  # noqa: F401
from test_player_setup import bag_row, decide, run, seen
from test_yennefer_triss_bag import (DECK, INNER_BAG, OUTER_BAG, REAL_BAG, TY, TY_ONLY, YT, YT_ONLY, bag_left, family_bag, family_deck,
                                     real_bag)

NO_FILE = "none.json"
HUMAN = player_setup.HUMAN


def seen_with_pieces(bags=(), piles=(), pieces=None):
    """`seen` with loose miniatures on the table ({guid: x}): the gate's reading carries them (`hero_detect.table_script`)."""
    tables = {s: load_hero_table(s) for s in hero_detect.hero_slugs()}
    read = hero_detect.TableReading(list(piles), {g: (x, 0.0) for g, x in (pieces or {}).items()}, hero_detect.hero_slugs())
    return player_setup.Scan(seen([]).boards, player_setup._sightings(list(bags), read, tables, set()))


@pytest.mark.parametrize("x", [-7, 7])
def test_a_bag_of_eight_with_the_shared_deck_loose_is_one_box_like_any_heros_bag_and_deck(tmp_path, x):
    without_deck = sorted(set(REAL_BAG) - {DECK})
    found = seen([family_bag(x, guids=without_deck), bag_row("bigfoot", -x)], [family_deck(x)])
    boxes = [s for s in found.sightings if s.variants]
    assert len(boxes) == 1 and boxes[0].kind == "bag" and boxes[0].items == 8, "the loose deck is not a second box"
    if x < 0:
        assert player_setup.question(found) == (YT, TY)
    for pick in (YT, TY):
        setup, problems = player_setup.decide(found, tmp_path / NO_FILE, picks={HUMAN: pick})
        if x < 0:
            assert problems == [] and (setup.human, setup.bags[pick]) == (pick, "copyyt")
        else:
            assert problems == [] and (setup.bot, setup.bags[YT]) == (YT, "copyyt"), "the bot's half resolves the same way"


def test_a_bag_with_only_one_variants_pieces_and_the_shared_deck_loose_is_that_variant(tmp_path):
    found = seen([family_bag(-7, guids=sorted(TY_ONLY)), bag_row("bigfoot", 7)], [family_deck(-9)])
    assert player_setup.question(found) is None
    setup, problems = player_setup.decide(found, tmp_path / NO_FILE)
    assert problems == [] and setup.human == TY and setup.bags[TY] == "copyyt"


def test_the_same_box_twice_on_a_half_is_a_duplicate_not_a_nameless_pair(tmp_path):
    found = seen([family_bag(-7, "copyA"), family_bag(-9, "copyB"), bag_row("bigfoot", 7)])
    setup, problems = decide(found, tmp_path / NO_FILE)
    assert setup is None and problems == t("setup.duplicated", name="Yennefer y Triss", side=t("setup.side.human")), problems


@pytest.mark.parametrize("out, expected", [("cd27f6", YT), ("d1b3b9", TY)])
def test_the_hero_miniature_out_on_the_table_says_which_heroine_leads_and_nothing_is_asked(tmp_path, out, expected):
    found = seen_with_pieces([bag_row("bigfoot", 7)], [family_deck(-9)], {out: -8.0})
    assert player_setup.question(found) is None
    for pick in (None, YT, TY):
        setup, problems = player_setup.decide(found, tmp_path / NO_FILE, picks={HUMAN: pick} if pick else None)
        assert problems == [] and setup.human == expected, "a prepared table is not asked again and the answer cannot contradict the miniature"


def test_a_miniature_on_the_other_half_or_both_miniatures_out_do_not_decide():
    other_half = seen_with_pieces([bag_row("bigfoot", 7)], [family_deck(-9)], {"cd27f6": 8.0})
    both = seen_with_pieces([bag_row("bigfoot", 7)], [family_deck(-9)], {"cd27f6": -8.0, "d1b3b9": -8.5})
    assert player_setup.question(other_half) == (YT, TY) and player_setup.question(both) == (YT, TY)


def test_the_calibration_tool_cannot_ask_on_a_panel_and_says_what_to_do_at_the_console(tmp_path):
    found = seen([family_bag(-7), bag_row("bigfoot", 7)])
    setup, problems = player_setup.decide(found, tmp_path / NO_FILE, console=True)
    assert setup is None and problems == [t("setup.family_unchosen_console", names="Yennefer y Triss")]
    assert "panel" not in problems[0].lower()
    resolved = seen_with_pieces([family_bag(-7), bag_row("bigfoot", 7)], pieces={"d1b3b9": -8.0})
    assert player_setup.decide(resolved, tmp_path / NO_FILE, console=True)[0].human == TY, "a miniature out settles it without a question"


def test_a_hero_the_configuration_fixes_from_the_box_answers_the_question_and_beats_the_panel(tmp_path):
    found = seen([family_bag(-7), bag_row("bigfoot", 7)])
    assert player_setup.question(found, TY) is None and player_setup.question(found, "houdini") == (YT, TY)
    setup, problems = player_setup.decide(found, tmp_path / NO_FILE, picks={HUMAN: YT}, human_hero=TY)
    assert problems == [] and setup.human == TY and setup.bags == {"bigfoot": "copybigfoot", TY: "copyyt"}
    setup, _ = player_setup.decide(found, tmp_path / NO_FILE, picks={HUMAN: YT}, human_hero="houdini")
    assert setup.human == YT, "a fixed hero outside the box changes nothing"


def test_a_bag_that_is_not_the_players_drop_is_never_destroyed_for_holding_only_spare_objects(tts):  # noqa: F811
    """A loose copy reused from an earlier press (not adopted) with the other heroine's four left is not the gate's to destroy."""
    real_bag(tts, "loosecopy", x=-24.0)
    tts.execute("getObjectFromGUID('loosecopy').pos = Vector(-24, 1.6, 10.5)")        # where an earlier press left it: at the first item's spot
    rows = [(kind, guids, INNER_BAG, (-24.0, 2.5, 10.5 + 3 * n), None) for n, (kind, guids) in enumerate(load_hero_table(YT).unpack_items())]
    outers = {INNER_BAG: (OUTER_BAG, "Yennefer", "", tuple(REAL_BAG))}
    res = run(tts, lua.unpack_from_bags(rows, outers, (), tuple(sorted(TY_ONLY))))
    assert res["reused"] == [INNER_BAG] and sorted(res["taken"]) == sorted(YT_ONLY | {DECK}), res
    assert bag_left(tts, "loosecopy") == sorted(TY_ONLY)
