"""Forms and counters from data (F07 step 3): a synthetic hero with another counter, another threshold, another passive and
another start-of-turn trigger changes the engine's behavior without touching code."""
import json

from sparring.heroes import HEROES_DIR, parse_hero
from sparring.state import ANUNG, DETECTIVE
from conftest import give, place


def blazing_hero(draw_n: int = 1):
    """Hellboy with another form rule: counts 'burning' cards in the discard; COLD below 3, BLAZING from 3
    (+3 to the hero's attack); in COLD draws `draw_n` when starting on the rival start space."""
    raw = json.loads((HEROES_DIR / "hellboy.json").read_text(encoding="utf-8"))
    for c in raw["deck"]["cards"]:
        c["tags"] = ["burning"] if c["title"] in ("Service Pistol", "Excalibur", "Second Shot", "Pancakes!") else []
    raw["counters"] = {"fire": {"pile": "discard", "tag": "burning"}}
    raw["forms"] = {"counter": "fire", "threshold": 3, "below": "COLD", "at_or_above": "BLAZING"}
    raw["passives"] = [{"id": "blaze", "form": "BLAZING", "effect": "attack_bonus", "n": 3, "fighter": "hero"}]
    raw["triggers"] = [{"id": "cold_draw", "when": "start_of_turn", "form": "COLD", "condition": "hero_on_rival_start",
                        "optional": True, "effect": "draw", "n": draw_n}]
    return parse_hero(raw, "blazing")


def swap_hero(game, player, hero):
    p = game.players[player]
    p.hero, p.full_set = hero, hero.deck()
    p.deck, p.hand, p.discard = list(p.full_set), [], []


def burning(game, player, n):
    return [c for c in game.players[player].full_set if "burning" in c.tags][:n]


def test_form_and_counter_follow_the_synthetic_rule(game):
    swap_hero(game, 1, blazing_hero())
    assert game.form(1) == "COLD" and game.counter(1, "fire") == 0 and game.destiny_count(1) == 0
    assert game.counters(1) == {"fire": 0}
    game.players[1].discard = burning(game, 1, 2)
    assert game.form(1) == "COLD" and game.attack_bonus(game.fighters["hellboy"]) == 0
    game.players[1].discard = burning(game, 1, 3)
    assert game.form(1) == "BLAZING" and game.counters(1) == {"fire": 3}
    assert game.attack_bonus(game.fighters["hellboy"]) == 3 and game.attack_bonus(game.fighters["lobster"]) == 0
    assert game.form(0) is None and game.counters(0) == {}


def test_combat_breakdown_names_the_data_form(game):
    swap_hero(game, 1, blazing_hero())
    game.players[1].discard = burning(game, 1, 3)
    place(game, hellboy=1, medusa=2)
    card = give(game, 1, "Right Hand Of Doom")
    game.turn = 1
    res = game.attack(game.fighters["hellboy"], game.fighters["medusa"], card, None)
    assert res.atk_value == 7 and res.atk_parts == ["Right Hand Of Doom (4)", "BLAZING (+3)"]


def test_a_passive_without_a_form_is_labelled_by_its_id_in_the_breakdown(game):
    hero = blazing_hero()
    hero = type(hero)(**{**hero.__dict__, "passives": hero.passives + (
        {"id": "iron_fist", "effect": "attack_bonus", "n": 1, "fighter": "hero"},)})
    swap_hero(game, 1, hero)
    assert game.attack_bonus_parts(game.fighters["hellboy"]) == [(1, "iron_fist")]
    place(game, hellboy=1, medusa=2)
    card = give(game, 1, "Right Hand Of Doom")
    game.turn = 1
    res = game.attack(game.fighters["hellboy"], game.fighters["medusa"], card, None)
    assert res.atk_value == 5 and res.atk_parts == ["Right Hand Of Doom (4)", "iron_fist (+1)"]
    game.players[1].discard = burning(game, 1, 3)
    assert game.attack_bonus_parts(game.fighters["hellboy"]) == [(3, "BLAZING"), (1, "iron_fist")]


def test_start_of_turn_triggers_are_filtered_by_form_and_their_numbers_come_from_data(game):
    game.fx.dsl_heroes.discard("hellboy")        # the wrappers drive the legacy path (interpreted: test_effects_events)
    swap_hero(game, 1, blazing_hero(draw_n=3))
    assert [t["id"] for t in game.triggers(1, "start_of_turn")] == ["cold_draw"]
    place(game, hellboy=game.start_spaces[0])
    game.players[1].hand = []
    assert game.hellboy_detective_draw(1) is True and len(game.players[1].hand) == 3
    game.players[1].discard = burning(game, 1, 3)                 # BLAZING: the COLD trigger is not active
    assert game.triggers(1, "start_of_turn") == []
    game.players[1].hand = []
    assert game.hellboy_detective_draw(1) is False and game.players[1].hand == []


def test_hellboy_data_still_gives_two_cards_in_detective_and_the_anung_start(game):
    game.fx.dsl_heroes.discard("hellboy")        # the wrappers drive the legacy path (interpreted: test_effects_events)
    assert [t["id"] for t in game.triggers(1, "start_of_turn")] == ["detective_draw"]
    place(game, hellboy=game.start_spaces[0])
    game.players[1].hand = []
    assert game.hellboy_detective_draw(1) is True and len(game.players[1].hand) == 2
    game.players[1].discard = [c for c in game.players[1].full_set if c.destiny][:6]
    assert game.form(1) == ANUNG and [t["id"] for t in game.triggers(1, "start_of_turn")] == ["anung_discard_move"]
    assert game.hellboy_detective_draw(1) is False
    game.players[1].discard = game.players[1].discard[:5]
    assert game.form(1) == DETECTIVE
    assert game.triggers(0, "start_of_turn")[0]["id"] == "medusa_gaze"
