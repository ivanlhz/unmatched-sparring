"""El DSL de efectos (docs/effects-dsl.md): los cinco ficheros de data/heroes/effects validan contra schema.json y las
reglas semanticas de tools/validate_effects.py, cada carta de cada mazo tiene su entrada, lo que el motor detecta
por texto (BOOST propio) esta marcado en datos, y el validador rechaza lo que debe con un mensaje claro.
Sin motor, sin TTS, sin sockets."""
import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from sparring.heroes import HEROES_DIR, load_hero
from tools.validate_effects import EFFECTS_DIR, SCHEMA_PATH, effect_files, load_schema, validate, validate_file

DOC = Path(__file__).resolve().parent.parent / "docs" / "effects-dsl.md"
BOX = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]


@pytest.fixture(scope="module")
def schema():
    return load_schema()


def load_effects(slug: str) -> dict:
    return json.loads((EFFECTS_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def load_hero_raw(slug: str) -> dict:
    return json.loads((HEROES_DIR / f"{slug}.json").read_text(encoding="utf-8"))


def op_names(schema: dict) -> set[str]:
    return {b["properties"]["op"]["const"] for b in schema["$defs"]["Op"]["oneOf"]}


# ---------------------------------------------------------------- los ficheros de la caja mas Medusa

def test_the_five_effect_files_exist_and_validate():
    assert sorted(p.stem for p in effect_files()) == sorted(BOX)
    for path in effect_files():
        assert validate_file(path) == [], path.name


@pytest.mark.parametrize("slug", BOX)
def test_every_deck_card_has_an_entry_with_its_copies_and_real_text(slug):
    deck = load_hero(slug).deck()
    cards = load_effects(slug)["cards"]
    assert Counter(c["title"] for c in cards) == {t: 1 for t in {c.title for c in deck}}   # una entrada por titulo
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
    """combat.can_boost busca 'boost this attack' en el texto; Out Of Time dice 'BOOST this card' y se le escapa.
    El dato may_boost cubre las dos formas, y nada mas."""
    flagged, by_text = {}, {}
    for slug in BOX:
        for card in load_effects(slug)["cards"]:
            if card.get("may_boost"):
                flagged[(slug, card["title"])] = True
            low = card["text"].lower()
            if "boost this attack" in low or "boost this card" in low:
                by_text[(slug, card["title"])] = True
    assert flagged == by_text
    assert set(flagged) == {("medusa", "Second Shot"), ("hellboy", "Second Shot"), ("baba-yaga", "Out Of Time")}
    for slug, title in flagged:
        card = next(c for c in load_effects(slug)["cards"] if c["title"] == title)
        assert not any(op["op"] == "boost" for op in card["effects"]["during"]), "may_boost no se duplica como op"


def test_all_damage_is_effect_damage_and_no_old_vocabulary_survives(schema):
    """Nada de source/kind en damage, nada de bind/ref/self_player/this_card/push/choose_n/persistent_scheme."""
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


# ---------------------------------------------------------------- el esquema y la documentacion

def test_schema_ops_match_the_documented_closed_list(schema):
    doc = DOC.read_text(encoding="utf-8")
    section = doc.split("## 3. Ops (lista cerrada)")[1].split("### Estados")[0]
    documented = set(re.findall(r"^\| `([a-z_]+)` \|", section, flags=re.M))
    assert documented == op_names(schema)
    statuses = set(re.findall(r"^\| `([a-z_]+)` \| (?:fighter|player)", doc.split("### Estados")[1].split("### Modificadores")[0], flags=re.M))
    assert statuses == set(schema["$defs"]["StatusName"]["enum"])
    events = set(re.findall(r"^\| `([a-z_]+)` \|", doc.split("### 2.10 Eventos")[1].split("Como caducidad")[0], flags=re.M))
    assert events == {b["properties"]["event"]["const"] for b in schema["$defs"]["Event"]["oneOf"]}
    tests = set(re.findall(r"^\| `([a-z_]+)` \|", doc.split("### 2.9 Condiciones")[1].split("Nunca hay condiciones")[0], flags=re.M))
    assert tests == {b["properties"]["test"]["const"] for b in schema["$defs"]["Test"]["oneOf"]}


def test_schema_is_closed_everywhere(schema):
    """Toda op, evento, test y modificador prohibe campos desconocidos y exige 'up_to' en move."""
    for group in ("Op", "Event", "Test", "Modifier"):
        for branch in schema["$defs"][group]["oneOf"]:
            assert branch["additionalProperties"] is False, group
    move = next(b for b in schema["$defs"]["Op"]["oneOf"] if b["properties"]["op"]["const"] == "move")
    assert "up_to" in move["required"]
    assert schema["properties"]["schema"] == {"const": 1}
    assert SCHEMA_PATH.name == "schema.json" and SCHEMA_PATH not in effect_files()


# ---------------------------------------------------------------- el validador rechaza lo que debe

def broken(slug: str, mutate):
    doc = copy.deepcopy(load_effects(slug))
    mutate(doc)
    return validate(doc, load_schema(), load_hero_raw(slug))


def card(doc, title):
    return next(c for c in doc["cards"] if c["title"] == title)


def test_validator_rejects_unknown_ops_fields_and_string_conditions():
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append({"op": "teleport"}))
    assert len(errs) == 1 and "op 'teleport' desconocida" in errs[0] and "(Snipe)" not in errs[0] and "cards[4]" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"][0].update(times=2))
    assert errs == ["$.cards[4].effects.after[0]: campo desconocido 'times' (validos: op, player, amount, up_to, chooser, as)"]
    errs = broken("medusa", lambda d: card(d, "Gaze of Stone")["effects"]["after"][0].update(condition="won_combat"))
    assert len(errs) == 1 and "condition" in errs[0] and "no encaja" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Dash")["effects"]["after"][0].pop("up_to"))
    assert errs == ["$.cards[3].effects.after[0]: falta el campo obligatorio 'up_to'"]


def test_validator_enforces_the_hidden_information_rule():
    def peek_without_look(d):
        card(d, "Snipe")["effects"]["after"].append(
            {"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "owner"}})
    errs = broken("medusa", peek_without_look)
    assert len(errs) == 1 and "sin un look_hand previo" in errs[0] and "(discard)" in errs[0]

    def look_inside_branch_only(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "if", "condition": {"test": "combat_result", "result": "won"}, "then": [{"op": "look_hand", "player": "opponent"}]})
        after.append({"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "owner"}})
    assert any("sin un look_hand previo" in e for e in broken("medusa", look_inside_branch_only))

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
    assert len(errs) == 1 and "'$ghost' no esta ligado" in errs[0]

    def binding_does_not_leak_out_of_a_branch(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "if", "condition": {"test": "combat_result", "result": "won"},
                      "then": [{"op": "discard", "cards": {"zone": "hand", "player": "owner"}, "as": "fuel"}]})
        after.append({"op": "move", "target": "hero", "amount": {"attr": "boost", "of": "$fuel"}, "up_to": True})
    assert any("'$fuel' no esta ligado" in e for e in broken("medusa", binding_does_not_leak_out_of_a_branch))

    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"][0].update({"as": "hero"}))
    assert errs == ["cards[4] (Snipe).effects.after[0] (draw): 'hero' es un nombre reservado, no se puede ligar"]


def test_validator_checks_status_scope_counters_forms_names_and_plugins():
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append(
        {"op": "status", "name": "cannot_draw", "target": "hero", "until": {"event": "end_of_turn"}}))
    assert len(errs) == 1 and "'cannot_draw' va sobre 'player', no sobre 'target'" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append({"op": "counter", "name": "rage", "delta": 1}))
    assert len(errs) == 1 and "contador 'rage' no declarado" in errs[0]
    errs = broken("hellboy", lambda d: card(d, "Right Hand Of Doom")["effects"]["after"][1]["condition"].update(form="BIG"))
    assert len(errs) == 1 and "forma 'BIG' no existe" in errs[0]
    errs = broken("medusa", lambda d: card(d, "The Hounds of Mighty Zeus")["effects"]["after"][0]["target"].update(name="Harpie"))
    assert len(errs) == 1 and "luchador 'Harpie' no existe" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append({"op": "plugin", "id": "medusa:stare"}))
    assert errs == ["plugins: 'medusa:stare' se usa pero no esta declarado"]
    errs = broken("medusa", lambda d: d["plugins"].append({"id": "medusa:stare", "why": "nada"}))
    assert errs == ["plugins: 'medusa:stare' esta declarado pero ninguna op ni pasiva lo usa"]
    errs = broken("medusa", lambda d: card(d, "Second Shot")["effects"]["during"].append({"op": "boost", "card": "this"}))
    assert len(errs) == 1 and "may_boost ya expresa el BOOST gratuito" in errs[0]


def test_validator_treats_the_rival_deck_as_hidden_too():
    """Elegir del mazo rival exige look_deck/search_deck previo; top/bottom/random no eligen y pasan; la mano no
    tiene orden (sin top/bottom); exists y count_cards cuentan sin mirar."""
    def pick_from_rival_deck(d):
        card(d, "Snipe")["effects"]["after"].append(
            {"op": "put_in_hand", "cards": {"zone": "deck", "player": "opponent", "amount": 1, "chooser": "owner"}})
    errs = broken("medusa", pick_from_rival_deck)
    assert len(errs) == 1 and "owner elige de el mazo de opponent sin un look_deck o search_deck previo" in errs[0]

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
    assert len(errs) == 1 and "la mano no tiene orden" in errs[0]


def test_validator_reports_errors_inside_ongoing_against_the_ongoing_branch():
    """anyOf [null, Ongoing]: un fallo dentro de un Pacto debe salir como fallo del Ongoing, no como 'debe ser null'."""
    errs = broken("baba-yaga", lambda d: card(d, "Pact Of Peace")["ongoing"].pop("until"))
    assert errs == ["$.cards[13].ongoing: falta el campo obligatorio 'until'"]
    errs = broken("baba-yaga", lambda d: card(d, "Pact Of Time")["ongoing"]["modifiers"][0].update(rule="no_schemes"))
    assert len(errs) == 1 and errs[0].startswith("$.cards[15].ongoing.modifiers[0].rule:") and "no esta entre" in errs[0]
    errs = broken("abe-sapien", lambda d: card(d, "Counterhex Shield")["ongoing"]["triggers"].append({"id": "x", "when": {"event": "end_of_turn"}}))
    assert errs == ["$.cards[12].ongoing.triggers[0]: falta el campo obligatorio 'ops'"]
    # misma mejora para los selectores: un FighterSel objeto roto se explica como objeto, no como cadena
    errs = broken("medusa", lambda d: card(d, "Dash")["effects"]["after"][0].update(target={"side": "own", "kind": "harpy"}))
    assert len(errs) == 1 and errs[0].startswith("$.cards[3].effects.after[0].target.kind:")


def test_event_bindings_of_amount_are_usable_and_typed():
    """damage_taken y combat_damage_dealt ligan $amount (numero): vale como Amount y no como luchador."""
    def draw_what_you_took(d):
        d["ability"]["triggers"].append({"id": "payback", "when": {"event": "damage_taken", "target": "hero", "damage": "combat"},
                                         "ops": [{"op": "draw", "player": "owner", "amount": "$amount"}]})
    assert broken("medusa", draw_what_you_took) == []

    def amount_as_fighter(d):
        d["ability"]["triggers"].append({"id": "bad", "when": {"event": "combat_damage_dealt", "by": "hero"},
                                         "ops": [{"op": "heal", "target": "$amount", "amount": 1}]})
    errs = broken("medusa", amount_as_fighter)
    assert len(errs) == 1 and "'$amount' liga un number, pero aqui (target) hace falta un fighter" in errs[0]

    def fighter_as_player(d):
        card(d, "Snipe")["effects"]["after"].append({"op": "for_each", "over": {"fighters": {"side": "own", "pick": "all"}}, "as": "f",
                                                      "ops": [{"op": "draw", "player": "$f", "amount": 1}]})
    errs = broken("medusa", fighter_as_player)
    assert len(errs) == 1 and "'$f' liga un fighter, pero aqui (player) hace falta un player" in errs[0]

    def card_binding_as_card_and_number(d):
        after = card(d, "Snipe")["effects"]["after"]
        after.append({"op": "discard", "cards": {"zone": "hand", "player": "owner"}, "as": "x"})
        after.append({"op": "return_to_deck", "cards": "$x", "position": "top"})
        after.append({"op": "heal", "target": "hero", "amount": {"attr": "boost", "of": "$x"}})
    assert broken("medusa", card_binding_as_card_and_number) == []


def test_validator_rejects_what_the_doc_forbids():
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append(
        {"op": "discard", "cards": {"zone": "hand", "player": "owner", "pick": "all", "amount": 2}}))
    assert len(errs) == 1 and "'amount' no tiene sentido con pick 'all'" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append(
        {"op": "discard", "cards": {"zone": "hand", "player": "owner", "pick": "random", "chooser": "owner", "up_to": True}}))
    assert len(errs) == 2 and all("solo va con pick 'chosen'" in e for e in errs)
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["after"].append(
        {"op": "discard", "cards": {"zone": "hand", "player": "owner", "chooser": "random"}}))
    assert len(errs) == 1 and "chooser" in errs[0]                       # el azar es pick random, no un chooser
    errs = broken("medusa", lambda d: card(d, "A Momentary Glance").update(may_boost=True))
    assert errs == ["cards[9] (A Momentary Glance): un plan no se juega en combate, no puede llevar may_boost"]
    errs = broken("medusa", lambda d: card(d, "Dash")["effects"]["after"][0].update(target={}))
    assert len(errs) == 1 and errs[0].startswith("$.cards[3].effects.after[0].target:") and "role" in errs[0] and "side" in errs[0]
    errs = broken("medusa", lambda d: card(d, "Dash")["effects"]["after"][0].update(amount=0))
    assert errs == ["cards[3] (Dash).effects.after[0] (move): move con amount 0 no mueve nada; sobra la op"]
    errs = broken("medusa", lambda d: d["ability"]["triggers"][0].update(optional=True))
    assert len(errs) == 1 and "campo desconocido 'optional'" in errs[0]   # el 'you may' de un disparador es la op optional


def test_validator_cross_checks_the_herodef():
    errs = broken("medusa", lambda d: card(d, "Snipe").update(copies=4))
    assert errs == ["cards (Snipe): copies 4 pero el mazo tiene 3"]
    errs = broken("medusa", lambda d: card(d, "Snipe").update(text="AFTER COMBAT: Draw 2 cards."))
    assert errs == ["cards (Snipe): el texto no es el del HeroDef"]
    errs = broken("medusa", lambda d: d["cards"].pop(0))
    assert errs == ["cards: falta la carta 'Second Shot' del mazo"]
    errs = broken("medusa", lambda d: card(d, "Snipe")["effects"]["scheme"].append({"op": "end_turn"}))
    assert errs == ["cards[4] (Snipe): solo los planes llevan ops en 'scheme'"]
    errs = broken("medusa", lambda d: card(d, "A Momentary Glance")["effects"]["after"].append({"op": "end_turn"}))
    assert errs == ["cards[9] (A Momentary Glance): un plan no tiene momento after"]
