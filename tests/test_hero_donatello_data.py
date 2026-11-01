"""Donatello (TMNT Adventures): the HeroDef, the effects file and the table data agree with the real cards (sheet 176)."""
from collections import Counter

from sparring.combat import is_medusa_card
from sparring.effects.model import load_effects
from sparring.heroes import load_hero
from sparring.tts.hero_table import load_hero_table, table_defaults

CARDS = {   # title: (type, value, boost, copies, restriction)
    "Turtle power!": ("attack", 3, 3, 2, "any"),
    "Thinking ahead": ("attack", 3, 2, 3, "any"),
    "Shift focus": ("versatile", 2, 2, 3, "Donatello"),
    "Short circuit": ("versatile", 3, 2, 3, "any"),
    "Quick strike": ("versatile", 3, 1, 3, "any"),
    "Untested enhancements": ("versatile", 3, 2, 3, "Metalhead"),
    "Heroes in a half shell": ("defense", 5, 1, 2, "Donatello"),
    "Bo staff": ("defense", 3, 2, 2, "Donatello"),
    "Donatello does machines": ("scheme", None, 3, 2, "Donatello"),
    "Party wagon!": ("scheme", None, 2, 2, "Donatello"),
    "The future of Ninjutsu": ("scheme", None, 1, 2, "Metalhead"),
    "Electro grenade": ("attack", 2, 3, 1, "Donatello"),
    "Self defense grid": ("defense", 2, 3, 1, "Donatello"),
    "Smoke bomb": ("scheme", None, 3, 1, "Donatello"),
}


def test_the_hero_sheet_and_fighters():
    h = load_hero("donatello")
    assert (h.name, h.fid, h.hp, h.move, h.ranged) == ("Donatello", "donatello", 14, 2, False)
    assert [(s.fid, s.name, s.hp, s.move, s.ranged) for s in h.sidekicks] == [("metalhead", "Metalhead", 7, 2, False)]
    assert "tuck it under this card" in h.ability and "INVENTIVE" in h.ability


def test_the_deck_is_the_real_one_card_by_card():
    deck = load_hero("donatello").deck()
    assert len(deck) == 30 and [c.card_id for c in deck] == list(range(17600, 17630))
    got = Counter((c.title, c.type, c.value, c.boost, c.fighter) for c in deck)
    want = Counter()
    for title, (kind, value, boost, copies, who) in CARDS.items():
        want[(title, kind, value, boost, who)] = copies
    assert got == want


def test_inventions_are_tagged_and_have_a_bonus_in_the_effects_file():
    deck = load_hero("donatello").deck()
    assert {c.title for c in deck if "invention" in c.tags} == {"Electro grenade", "Self defense grid", "Smoke bomb"}
    fx = load_effects("donatello")
    assert {t for t, c in fx.cards.items() if c.invention} == {"Electro grenade", "Self defense grid", "Smoke bomb"}


def test_table_data_matches_the_save_and_coexists_with_medusa_on_the_same_card_ids():
    t = load_hero_table("donatello")
    assert t.card_ids == (17600, 17629) and t.character_card_id == 364
    assert set(t.fighters) == {"donatello", "metalhead"} and t.fighters["metalhead"].dial_max == 7
    medusa = load_hero_table("medusa")
    assert medusa.card_ids == t.card_ids and not set(medusa.identity) & set(t.identity)
    assert table_defaults("donatello", "medusa")["bot_card_ids"] == [17600, 17629]


def test_donatellos_cards_are_not_mistaken_for_medusas_even_with_her_card_ids():
    deck = load_hero("donatello").deck()
    assert not any(is_medusa_card(c) for c in deck)
    assert all(is_medusa_card(c) for c in load_hero("medusa").deck())
