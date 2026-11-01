"""Raphael is recognised on the table from data/tts/raphael.json. His deck is sheet 176 like Medusa's, so the images tell
them apart, never the CardID range alone."""
import pytest

from sparring.hero_catalog import load_catalog
from sparring.hero_detect import detect_heroes
from sparring.play import ConfigError
from sparring.tts.hero_table import HeroTableError, load_hero_table, table_defaults
from test_hero_detect import BOT_SPOT, HUMAN_SPOT, at_bot, at_human, reading


def test_raphael_is_detected_on_either_side_against_any_hero():
    for other in ("medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"):
        assert detect_heroes(reading(at_bot("raphael"), at_human(other)), BOT_SPOT, HUMAN_SPOT) == ("raphael", other)
        assert detect_heroes(reading(at_bot(other), at_human("raphael")), BOT_SPOT, HUMAN_SPOT) == (other, "raphael")


def test_raphael_and_medusa_share_the_card_range_but_not_the_images():
    medusa, raphael = load_hero_table("medusa"), load_hero_table("raphael")
    assert medusa.card_ids == raphael.card_ids == (17600, 17629)
    assert not set(medusa.identity) & set(raphael.identity)
    defaults = table_defaults("raphael", "medusa")
    assert defaults["bot_card_ids"] == defaults["human_card_ids"] == [17600, 17629]
    assert defaults["bot_identity"] != defaults["human_identity"]


def test_two_decks_with_the_same_images_are_still_refused():
    with pytest.raises(HeroTableError):
        table_defaults("raphael", "raphael")


def test_the_catalog_names_raphael_and_his_deck_is_his_own():
    catalog = load_catalog()
    assert catalog.name_of("raphael") == "Raphael"
    assert catalog.identify([f"{f}|{b}" for f, b in load_hero_table("raphael").identity]).slug == "raphael"
