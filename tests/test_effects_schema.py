"""The effects DSL (docs/effects-dsl.md): the five files of data/heroes/effects validate against schema.json and the
semantic rules of tools/validate_effects.py, every card of every deck has its entry, what the engine detects
by text (own BOOST) is marked in data, and the validator rejects what it should with a clear message.
No engine, no TTS, no sockets."""
import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from sparring.heroes import HEROES_DIR, load_hero
from tools.validate_effects import EFFECTS_DIR, SCHEMA_PATH, effect_files, load_schema, validate, validate_file

DOC = Path(__file__).resolve().parent.parent / "docs" / "effects-dsl.md"
BOX = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael"]


@pytest.fixture(scope="module")
def schema():
    return load_schema()


def load_effects(slug: str) -> dict:
    return json.loads((EFFECTS_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def load_hero_raw(slug: str) -> dict:
    return json.loads((HEROES_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def op_names(schema: dict) -> set[str]:
    return {b["properties"]["op"]["const"] for b in schema["$defs"]["Op"]["oneOf"]}


# ---------------------------------------------------------------- the box files plus Medusa

def test_the_five_effect_files_exist_and_validate():
    assert set(BOX) <= {p.stem for p in effect_files()}
    for path in effect_files():
        assert validate_file(path) == [], path.name


@pytest.mark.parametrize("slug", BOX)
def test_every_deck_card_has_an_entry_with_its_copies_and_real_text(slug):
    deck = load_hero(slug).deck()
    cards = load_effects(slug)["cards"]
    assert Counter(c["title"] for c in cards) == {t: 1 for t in {c.title for c in deck}}   # one entry per title
    assert {c["title"]: c["copies"] for c in cards} == Counter(c.title for c in deck)
    texts = {c.title: c.text for c in deck}
    for card in cards:
        assert card["text"] == texts[card["title"]], card["title"]
        assert set(card["effects"]) == {"immediately", "during", "after", "scheme", "boost"}, card["title"]


@pytest.mark.parametrize("slug", BOX)
def test_schemes_are_the_only_cards_with_scheme_ops_or_ongoing(slug):
    types = {c.title: c.type for c in load_hero(slug).deck()}
    for card in load_effects(slug)["cards"]:
        is_scheme = types[card["title"]] == "scheme"
        assert bool(card["effects"]["scheme"]) <= is_scheme, card["title"]
        assert bool(card.get("ongoing")) <= is_scheme, card["title"]
        if is_scheme:
            assert not (card["effects"]["immediately"] or card["effects"]["during"] or card["effects"]["after"]), card["title"]


def test_may_boost_marks_in_data_what_combat_can_boost_detects_by_text():
    """combat.can_boost looks for 'boost this attack' in the text; Out Of Time says 'BOOST this card' and escapes it.
    The may_boost datum covers both forms, and nothing else."""
    flagged, by_text = {}, {}
    for slug in BOX:
        for card in load_effects(slug)["cards"]:
            if card.get("may_boost"):
                flagged[(slug, card["title"])] = True
            low = card["text"].lower()
            if "boost this attack" in low or "boost this card" in low:
                by_text[(slug, card["title"])] = True
    assert flagged == by_text
    assert set(flagged) == {("medusa", "Second Shot"), ("hellboy", "Second Shot"), ("baba-yaga", "Out Of Time"),
                           ("donatello", "Turtle power!"), ("michelangelo", "Turtle Power!!"), ("raphael", "Turtle power!")}
    for slug, title in flagged:
        card = next(c for c in load_effects(slug)["cards"] if c["title"] == title)
        assert not any(op["op"] == "boost" for op in card["effects"]["during"]), "may_boost is not duplicated as an op"


def test_all_damage_is_effect_damage_and_no_old_vocabulary_survives(schema):
    """No source/kind in damage, no bind/ref/self_player/this_card/push/choose_n/persistent_scheme."""
    old = re.compile(r'"(bind|ref|self_player|self_hero|this_card|self_card|push|choose_n|persistent_scheme|'
                     r'primitives_needed|recover_from_discard|trigger_when|up_to": [0-9])')
    for path in effect_files():
        text = path.read_text(encoding="utf-8")
        assert not old.search(text), f"{path.name}: {old.search(text).group(0)}"
    for name in ("push", "choose_n", "persistent_scheme", "recover_from_discard", "rule", "trigger"):
        assert name not in op_names(schema)


def test_hidden_information_cards_are_listed_and_only_look_hand_opens_a_rival_hand():
    for slug in BOX:
        ef = load_effects(slug)
        listed = " ".join(json.dumps(h, ensure_ascii=False) for h in ef["hidden_info"])
        for card in ef["cards"]:
            if "look_hand" in json.dumps(card["effects"]):
                assert card["title"] in listed, (slug, card["title"])
    confront = next(c for c in load_effects("hellboy")["cards"] if c["title"] == "Confront Any Demon or God")
    branch = confront["effects"]["after"][1]["then"]
    assert [op["op"] for op in branch] == ["look_hand", "discard"]
    assert branch[1]["cards"] == {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "owner"}


# ---------------------------------------------------------------- the schema and the documentation

def test_schema_ops_match_the_documented_closed_list(schema):
    doc = DOC.read_text(encoding="utf-8")
    section = doc.split("## 3. Ops (closed list)")[1].split("### Statuses")[0]
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", section, flags=re.M))
    assert documented == op_names(schema)
    statuses = set(re.findall(r"^\| `([a-z_]+)` \| (?:fighter|player)", doc.split("### Statuses")[1].split("### Modifiers")[0], flags=re.M))
    assert statuses == set(schema["$defs"]["StatusName"]["enum"])
    events = set(re.findall(r"^\| `([a-z_]+)` \|", doc.split("### 2.10 Events (Event)")[1].split("As expiry")[0], flags=re.M))
    assert events == {b["properties"]["event"]["const"] for b in schema["$defs"]["Event"]["oneOf"]}
    tests = set(re.findall(r"^\| `([a-z_]+)` \|", doc.split("### 2.9 Conditions (Condition)")[1].split("There are never conditions")[0], flags=re.M))
    assert tests == {b["properties"]["test"]["const"] for b in schema["$defs"]["Test"]["oneOf"]}


def test_schema_is_closed_everywhere(schema):
    """Every op, event, test and modifier forbids unknown fields and requires 'up_to' in move."""
    for group in ("Op", "Event", "Test", "Modifier"):
        for branch in schema["$defs"][group]["oneOf"]:
            assert branch["additionalProperties"] is False, group
    move = next(b for b in schema["$defs"]["Op"]["oneOf"] if b["properties"]["op"]["const"] == "move")
    assert "up_to" in move["required"]
    assert schema["properties"]["schema"] == {"const": 1}
    assert SCHEMA_PATH.name == "schema.json" and SCHEMA_PATH not in effect_files()


# ---------------------------------------------------------------- the validator rejects what it should

def broken(slug: str, mutate):
    doc = copy.deepcopy(load_effects(slug))
    mutate(doc)
    return validate(doc, load_schema(), load_hero_raw(slug))


def card(doc, title):
    return next(c for c in doc["cards"] if c["title"] == title)


def test_validator_rejects_unknown_ops_fields_and_string_conditions():
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append({"op": "teleport"}))
    assert len(errs) == 1 and "unknown op 'teleport'" in errs[0] and "(Snipe)" not in errs[0] and "cards[4]" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"][0].update(times=2))
    assert errs == ["$.cards[4].effects.after[0]: unknown field 'times' (valid: op, player, amount, up_to, chooser, as)"]
    errs = broken("medusa", lambda d: card(d, "Gaze of Stone")["effects"]["after"][0].update(condition="won_combat"))
    assert len(errs) == 1 and "condition" in errs[0] and "fits no alternative" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Dash")["effects"]["after"][0].pop("up_to"))
    assert errs == ["$.cards[3].effects.after[0]: missing required field 'up_to'"]


def test_validator_enforces_the_hidden_information_rule():
    def peek_without_look(d):
        card(d, "Snipe")["effects"]["after"].append(
            {"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "owner"}})
    errs = broken("medusa", peek_without_look)
    assert len(errs) == 1 and "without a prior look_hand" in errs[0] and "(discard)" in errs[0]

    def look_inside_branch_only(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "if", "condition": {"test": "combat_result", "result": "won"}, "then": [{"op": "look_hand", "player": "opponent"}]})
        after.append({"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "owner"}})
    assert any("without a prior look_hand" in e for e in broken("medusa", look_inside_branch_only))

    def rival_chooses_or_random(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "opponent"}})
        after.append({"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random"}})
    assert broken("medusa", rival_chooses_or_random) == []

    def look_then_choose(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "look_hand", "player": "opponent"})
        after.append({"op": "choose", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "owner"}, "as": "picked"})
        after.append({"op": "return_to_deck", "cards": "$picked", "position": "top"})
    assert broken("medusa", look_then_choose) == []


def test_validator_checks_bindings_scope_and_reserved_names():
    errs = broken("medusa", lambda d: card(d, "Dash")["effects"]["after"][0].update(target="$ghost"))
    assert len(errs) == 1 and "'$ghost' is not bound" in errs[0]

    def binding_does_not_leak_out_of_a_branch(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "if", "condition": {"test": "combat_result", "result": "won"},
                      "then": [{"op": "discard", "cards": {"zone": "hand", "player": "owner"}, "as": "fuel"}]})
        after.append({"op": "move", "target": "hero", "amount": {"attr": "boost", "of": "$fuel"}, "up_to": True})
    assert any("'$fuel' is not bound" in e for e in broken("medusa", binding_does_not_leak_out_of_a_branch))

    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"][0].update({"as": "hero"}))
    assert errs == ["cards[4] (Snipe).effects.after[0] (draw): 'hero' is a reserved name, it cannot be bound"]


def test_validator_checks_status_scope_counters_forms_names_and_plugins():
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append(
        {"op": "status", "name": "cannot_draw", "target": "hero", "until": {"event": "end_of_turn"}}))
    assert len(errs) == 1 and "'cannot_draw' goes on 'player', not on 'target'" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append({"op": "counter", "name": "rage", "delta": 1}))
    assert len(errs) == 1 and "counter 'rage' not declared" in errs[0]
    errs = broken("hellboy", lambda d: card(d, "Right Hand Of Doom")["effects"]["after"][1]["condition"].update(form="BIG"))
    assert len(errs) == 1 and "form 'BIG' does not exist" in errs[0]
    errs = broken("medusa", lambda d: card(d, "The Hounds of Mighty Zeus")["effects"]["after"][0]["target"].update(name="Harpie"))
    assert len(errs) == 1 and "fighter 'Harpie' does not exist" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append({"op": "plugin", "id": "medusa:stare"}))
    assert errs == ["plugins: 'medusa:stare' is used but not declared"]
    errs = broken("medusa", lambda d: d["plugins"].append({"id": "medusa:stare", "why": "nothing"}))
    assert errs == ["plugins: 'medusa:stare' is declared but no op or passive uses it"]
    errs = broken("medusa", lambda d: card(d, "Second Shot")["effects"]["during"].append({"op": "boost", "card": "this"}))
    assert len(errs) == 1 and "may_boost already expresses the free BOOST" in errs[0]


def test_validator_treats_the_rival_deck_as_hidden_too():
    """Choosing from the rival deck requires a prior look_deck/search_deck; top/bottom/random do not choose and pass; the hand has
    no order (no top/bottom); exists and count_cards count without looking."""
    def pick_from_rival_deck(d):
        card(d, "Snipe")["effects"]["after"].append(
            {"op": "put_in_hand", "cards": {"zone": "deck", "player": "opponent", "amount": 1, "chooser": "owner"}})
    errs = broken("medusa", pick_from_rival_deck)
    assert len(errs) == 1 and "owner chooses from the deck of opponent without a prior look_deck or search_deck" in errs[0]

    def look_then_pick(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "look_deck", "player": "opponent", "amount": 3, "as": "top3"})
        after.append({"op": "put_in_hand", "cards": {"zone": "deck", "player": "opponent", "amount": 1, "chooser": "owner"}})
    assert broken("medusa", look_then_pick) == []

    def blind_picks(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "discard", "cards": {"zone": "deck", "player": "opponent", "pick": "top", "amount": 1}})
        after.append({"op": "discard", "cards": {"zone": "deck", "player": "opponent", "pick": "random", "amount": 1}})
        after.append({"op": "if", "condition": {"test": "exists", "cards": {"zone": "hand", "player": "opponent", "filter": {"tag": "TRICK"}}},
                      "then": [{"op": "modify_value", "card": "this", "amount": {"count_cards": {"zone": "hand", "player": "opponent"}, "times": 3}}]})
    assert broken("medusa", blind_picks) == []

    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append(
        {"op": "discard", "cards": {"zone": "hand", "player": "owner", "pick": "top", "amount": 1}}))
    assert len(errs) == 1 and "the hand has no order" in errs[0]


def test_validator_reports_errors_inside_ongoing_against_the_ongoing_branch():
    """anyOf [null, Ongoing]: a failure inside a Pact must come out as an Ongoing failure, not as 'must be null'."""
    errs = broken("baba-yaga", lambda d: card(d, "Pact Of Peace")["ongoing"].pop("until"))
    assert errs == ["$.cards[13].ongoing: missing required field 'until'"]
    errs = broken("baba-yaga", lambda d: card(d, "Pact Of Time")["ongoing"]["modifiers"][0].update(rule="no_schemes"))
    assert len(errs) == 1 and errs[0].startswith("$.cards[15].ongoing.modifiers[0].rule:") and "is not among" in errs[0]
    errs = broken("abe-sapien", lambda d: card(d, "Counterhex Shield")["ongoing"]["triggers"].append({"id": "x", "when": {"event": "end_of_turn"}}))
    assert errs == ["$.cards[12].ongoing.triggers[0]: missing required field 'ops'"]
    # same improvement for selectors: a broken FighterSel object is explained as an object, not as a string
    errs = broken("medusa", lambda d: card(d, "Dash")["effects"]["after"][0].update(target={"side": "own", "kind": "harpy"}))
    assert len(errs) == 1 and errs[0].startswith("$.cards[3].effects.after[0].target.kind:")


def test_event_bindings_of_amount_are_usable_and_typed():
    """damage_taken and combat_damage_dealt bind $amount (a number): it counts as Amount and not as a fighter."""
    def draw_what_you_took(d):
        d["ability"]["triggers"].append({"id": "payback", "when": {"event": "damage_taken", "target": "hero", "damage": "combat"},
                                         "ops": [{"op": "draw", "player": "owner", "amount": "$amount"}]})
    assert broken("medusa", draw_what_you_took) == []

    def amount_as_fighter(d):
        d["ability"]["triggers"].append({"id": "bad", "when": {"event": "combat_damage_dealt", "by": "hero"},
                                         "ops": [{"op": "heal", "target": "$amount", "amount": 1}]})
    errs = broken("medusa", amount_as_fighter)
    assert len(errs) == 1 and "'$amount' binds a number, but here (target) a fighter is needed" in errs[0]

    def fighter_as_player(d):
        card(d, "Snipe")["effects"]["after"].append({"op": "for_each", "over": {"fighters": {"side": "own", "pick": "all"}}, "as": "f",
                                                      "ops": [{"op": "draw", "player": "$f", "amount": 1}]})
    errs = broken("medusa", fighter_as_player)
    assert len(errs) == 1 and "'$f' binds a fighter, but here (player) a player is needed" in errs[0]

    def card_binding_as_card_and_number(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "discard", "cards": {"zone": "hand", "player": "owner"}, "as": "x"})
        after.append({"op": "return_to_deck", "cards": "$x", "position": "top"})
        after.append({"op": "heal", "target": "hero", "amount": {"attr": "boost", "of": "$x"}})
    assert broken("medusa", card_binding_as_card_and_number) == []


def test_validator_rejects_what_the_doc_forbids():
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append(
        {"op": "discard", "cards": {"zone": "hand", "player": "owner", "pick": "all", "amount": 2}}))
    assert len(errs) == 1 and "'amount' makes no sense with pick 'all'" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append(
        {"op": "discard", "cards": {"zone": "hand", "player": "owner", "pick": "random", "chooser": "owner", "up_to": True}}))
    assert len(errs) == 2 and all("only goes with pick 'chosen'" in e for e in errs)
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append(
        {"op": "discard", "cards": {"zone": "hand", "player": "owner", "chooser": "random"}}))
    assert len(errs) == 1 and "chooser" in errs[0]                       # chance is pick random, not a chooser
    errs = broken("medusa", lambda d: card(d, "A Momentary Glance").update(may_boost=True))
    assert errs == ["cards[9] (A Momentary Glance): a scheme is not played in combat, it cannot carry may_boost"]
    errs = broken("medusa", lambda d: card(d, "Dash")["effects"]["after"][0].update(target={}))
    assert len(errs) == 1 and errs[0].startswith("$.cards[3].effects.after[0].target:") and "role" in errs[0] and "side" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Dash")["effects"]["after"][0].update(amount=0))
    assert errs == ["cards[3] (Dash).effects.after[0] (move): move with amount 0 moves nothing; the op is redundant"]
    errs = broken("medusa", lambda d: d["ability"]["triggers"][0].update(optional=True))
    assert len(errs) == 1 and "unknown field 'optional'" in errs[0]   # a trigger's 'you may' is the optional op


def test_validator_cross_checks_the_herodef():
    errs = broken("medusa", lambda d: card(d, "Snipe").update(copies=4))
    assert errs == ["cards (Snipe): copies 4 but the deck has 3"]
    errs = broken("medusa", lambda d: card(d, "Snipe").update(text="AFTER COMBAT: Draw 2 cards."))
    assert errs == ["cards (Snipe): the text is not the HeroDef's"]
    errs = broken("medusa", lambda d: d["cards"].pop(0))
    assert errs == ["cards: card 'Second Shot' of the deck is missing"]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["scheme"].append({"op": "end_turn"}))
    assert errs == ["cards[4] (Snipe): only schemes carry ops in 'scheme'"]
    errs = broken("medusa", lambda d: card(d, "A Momentary Glance")["effects"]["after"].append({"op": "end_turn"}))
    assert errs == ["cards[9] (A Momentary Glance): a scheme has no moment after"]
