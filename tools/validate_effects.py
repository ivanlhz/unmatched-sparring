"""Validates the effects files `data/heroes/effects/<slug>.json` against DSL v1 (docs/effects-dsl.md).

Two layers:
1. `schema.json` (JSON Schema): structure, closed ops and argument types. It is applied with the subset validator
   of this module (there is no `jsonschema` in the environment and nothing more is needed).
2. Semantic rules a schema cannot express: bindings resolved and of the right type (player, fighter,
   card, number), hidden zones (choosing from another player's hand or deck requires having looked at them earlier in the same
   effect), plugins declared and used, scope of each status, forbidden CardSel combinations, `may_boost`
   without a duplicated `boost` nor in schemes, `move` with amount 0, and the cross-check with the HeroDef (`data/heroes/<slug>.json`):
   titles, copies, text, card types, fighter names, forms and counters.

Usage:
    python tools/validate_effects.py                 # every file in data/heroes/effects
    python tools/validate_effects.py data/heroes/effects/medusa.json
Output: one line per error `<file>: <path>: <message>`; exit code 1 if there is any.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EFFECTS_DIR = ROOT / "data" / "heroes" / "effects"
HEROES_DIR = ROOT / "data" / "heroes"
SCHEMA_PATH = EFFECTS_DIR / "schema.json"

RESERVED_NAMES = frozenset({"this", "hero", "opposing", "attacker", "defender", "combatant",
                            "opponent_card", "attack_card", "defense_card"})
# what each event binds and of which type (see docs/effects-dsl.md 2.10)
EVENT_BINDINGS = {
    "after_attack": {"attacker": "fighter", "target": "fighter"},
    "attacked": {"attacker": "fighter", "target": "fighter"},
    "combat_damage_dealt": {"by": "fighter", "to": "fighter", "amount": "number"},
    "damage_taken": {"target": "fighter", "amount": "number"},
    "card_discarded": {"card": "card"},
    "card_played": {"card": "card"},
    "card_boosted": {"card": "card"},
    "fighter_defeated": {"fighter": "fighter"},
    "combat_lost": {"fighter": "fighter"},
    "after_combat": {"fighter": "fighter", "card": "card"},
}
# type of the binding each op creates with `as`
OP_BINDINGS = {"draw": "card", "discard": "card", "choose": "card", "look_deck": "card", "search_deck": "card",
               "damage": "fighter", "swap": "fighter", "move": "fighter", "remove_from_game": "card"}
# type each field expects when it carries a $var reference
PLAYER_KEYS = frozenset({"player", "chooser", "order", "start_space_of"})
FIGHTER_KEYS = frozenset({"role", "zone_of", "no_zone_of", "adjacent_to", "space_of", "nearest_to", "next_to_nearest_foe", "fighter", "target",
                          "with", "by", "from", "fighters", "count", "passed_by"})
CARD_KEYS = frozenset({"card", "cards", "of", "except", "count_of"})
NUMBER_KEYS = frozenset({"amount", "hp", "left", "right", "look"})
STATUS_SCOPE = {
    "immune_to_effect_damage": "target", "cannot_leave_space": "target",
    "immune_to_enemy_effect_damage": "player", "immune_to_enemy_effect_moves": "player",
    "immune_to_enemy_forced_discards": "player", "cannot_gain_actions": "player", "cannot_draw": "player",
    "next_attack_bonus": "player", "attack_bonus": "target",
}
AMOUNT_STATUSES = ("next_attack_bonus", "attack_bonus")      # the statuses that carry a bonus
HIDDEN_ZONES = ("hand", "deck")
OP_LIST_KEYS = ("ops", "then", "else", "cost")
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
TYPE_NAMES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
              "boolean": bool, "null": type(None)}
FIGHTER_SEL_KEYS = frozenset({"role", "side", "kind", "name", "where", "other", "state", "filter", "pick"})


# ---------------------------------------------------------------- layer 1: JSON Schema subset

class _Schema:
    def __init__(self, root: dict):
        self.root = root

    def resolve(self, schema: dict) -> dict:
        while "$ref" in schema:
            ref = schema["$ref"]
            assert ref.startswith("#/"), ref
            node = self.root
            for part in ref[2:].split("/"):
                node = node[part]
            schema = node
        return schema

    def errors(self, inst, schema: dict, path: str) -> list[str]:
        schema = self.resolve(schema)
        out: list[str] = []
        if "const" in schema and inst != schema["const"]:
            return [f"{path}: must be {schema['const']!r}, is {_short(inst)}"]
        if "enum" in schema and inst not in schema["enum"]:
            return [f"{path}: {_short(inst)} is not among {schema['enum']}"]
        if "type" in schema and not _is_type(inst, schema["type"]):
            return [f"{path}: must be of type {schema['type']}, is {_short(inst)}"]
        if "oneOf" in schema:
            out += self._one_of(inst, schema["oneOf"], path)
        if "anyOf" in schema:
            out += self._any_of(inst, schema["anyOf"], path)
        if isinstance(inst, str):
            if "pattern" in schema and not re.search(schema["pattern"], inst):
                out.append(f"{path}: {inst!r} does not match the pattern {schema['pattern']}")
            if "minLength" in schema and len(inst) < schema["minLength"]:
                out.append(f"{path}: empty string")
        if isinstance(inst, (int, float)) and not isinstance(inst, bool):
            if "minimum" in schema and inst < schema["minimum"]:
                out.append(f"{path}: {inst} is less than {schema['minimum']}")
            if "maximum" in schema and inst > schema["maximum"]:
                out.append(f"{path}: {inst} is greater than {schema['maximum']}")
        if isinstance(inst, list):
            if "minItems" in schema and len(inst) < schema["minItems"]:
                out.append(f"{path}: at least {schema['minItems']} items are needed")
            if "items" in schema:
                for i, v in enumerate(inst):
                    out += self.errors(v, schema["items"], f"{path}[{i}]")
        if isinstance(inst, dict):
            props = schema.get("properties", {})
            for key in schema.get("required", ()):
                if key not in inst:
                    out.append(f"{path}: missing required field {key!r}")
            for key, v in inst.items():
                if key in props:
                    out += self.errors(v, props[key], f"{path}.{key}")
                elif schema.get("additionalProperties", True) is False:
                    out.append(f"{path}: unknown field {key!r} (valid: {', '.join(props)})")
                elif isinstance(schema.get("additionalProperties"), dict):
                    out += self.errors(v, schema["additionalProperties"], f"{path}.{key}")
        return out

    def _discriminator(self, branches: list[dict]) -> str | None:
        """Key whose `const` tells each alternative apart (op, test, event, kind), if all have it."""
        keys = None
        for b in branches:
            b = self.resolve(b)
            consts = {k for k, v in b.get("properties", {}).items() if "const" in self.resolve(v)}
            keys = consts if keys is None else keys & consts
        return next(iter(sorted(keys))) if keys else None

    def _one_of(self, inst, branches: list[dict], path: str) -> list[str]:
        key = self._discriminator(branches)
        if key is not None:
            if not isinstance(inst, dict):
                return [f"{path}: must be an object with {key!r}, is {_short(inst)}"]
            if key not in inst:
                return [f"{path}: missing {key!r}"]
            for b in branches:
                b = self.resolve(b)
                if self.resolve(b["properties"][key])["const"] == inst[key]:
                    return self.errors(inst, b, path)
            valid = [self.resolve(self.resolve(b)["properties"][key])["const"] for b in branches]
            return [f"{path}: unknown {key} {inst[key]!r} (valid: {', '.join(map(str, valid))})"]
        return self._any_of(inst, branches, path)

    def _applicable(self, inst, schema: dict) -> bool:
        """The alternative may fit this value by its type, const or enum (without looking at the content)."""
        schema = self.resolve(schema)
        if "const" in schema:
            return inst == schema["const"]
        if "enum" in schema:
            return inst in schema["enum"]
        if "type" in schema and not _is_type(inst, schema["type"]):
            return False
        for key in ("anyOf", "oneOf"):
            if key in schema and not any(self._applicable(inst, b) for b in schema[key]):
                return False
        return True

    def _any_of(self, inst, branches: list[dict], path: str) -> list[str]:
        """Chooses the branch by type (null versus object, string versus object) and, among several of the same type,
        by the required keys present; this way the error that comes out is the one of the branch the author meant."""
        fits = [b for b in branches if self._applicable(inst, b)]
        if len(fits) > 1 and isinstance(inst, dict):
            by_required = [b for b in fits if all(k in inst for k in self.resolve(b).get("required", ()))]
            if len(by_required) == 1:
                fits = by_required
        if len(fits) == 1:
            return self.errors(inst, fits[0], path)
        attempts = [self.errors(inst, b, path) for b in (fits or branches)]
        if any(not e for e in attempts):
            return []
        resolved = [self.resolve(b) for b in branches]
        if all(set(b) == {"required"} for b in resolved):
            keys = " o ".join("/".join(b["required"]) for b in resolved)
            return [f"{path}: at least one of the fields is needed {keys}"]
        best = min(attempts, key=len)
        return [f"{path}: {_short(inst)} fits no alternative; the closest one fails with: "
                + "; ".join(e.split(": ", 1)[-1] for e in best[:3])]


def _is_type(inst, t) -> bool:
    types = t if isinstance(t, list) else [t]
    for name in types:
        py = TYPE_NAMES[name]
        if name in ("integer", "number") and isinstance(inst, bool):
            continue
        if isinstance(inst, py):
            return True
    return False


def _short(v) -> str:
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 60 else s[:57] + "..."


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- layer 2: semantic rules

class _Ctx:
    """What the validator carries down a tree of ops: bindings in scope (name -> type) and, per player,
    which hidden zones (hand, deck) have already been looked at in this effect."""

    def __init__(self, scope: dict[str, str], seen: set[tuple[str, str]]):
        self.scope, self.seen = scope, seen

    def child(self) -> "_Ctx":
        return _Ctx(dict(self.scope), set(self.seen))


class Semantics:
    def __init__(self, doc: dict, hero: dict | None):
        self.doc = doc
        self.hero = hero
        self.errors: list[str] = []
        self.plugins_used: set[str] = set()
        self.counters = set((doc.get("ability") or {}).get("counters") or {})
        if hero:
            self.counters |= set(hero.get("counters") or {})
            self.fighter_names = {hero["name"], *(s["name"] for s in hero.get("sidekicks") or ())}
            f = hero.get("forms")
            self.forms = {f["below"], f["at_or_above"]} if f else set()
        else:
            self.fighter_names = self.forms = None

    def run(self) -> list[str]:
        ab = self.doc["ability"]
        for i, t in enumerate(ab["triggers"]):
            self.trigger(t, f"ability.triggers[{i}]")
        for i, eff in enumerate(ab.get("during") or ()):
            ctx = _Ctx({}, set())
            if "condition" in eff:
                self.refs(eff["condition"], f"ability.during[{i}].condition", ctx)
            self.ops(eff["ops"], f"ability.during[{i}].ops", ctx)
        for i, p in enumerate(ab["passives"]):
            if "id" not in p:
                self.errors.append(f"ability.passives[{i}]: a passive needs 'id'")
            self.modifier(p, f"ability.passives[{i}]", _Ctx({}, set()))
        titles = [c["title"] for c in self.doc["cards"]]
        for t in sorted({t for t in titles if titles.count(t) > 1}):
            self.errors.append(f"cards: repeated title {t!r}")
        for i, card in enumerate(self.doc["cards"]):
            self.card(card, f"cards[{i}] ({card['title']})")
        declared = {p["id"] for p in self.doc["plugins"]}
        for pid in sorted(self.plugins_used - declared):
            self.errors.append(f"plugins: {pid!r} is used but not declared")
        for pid in sorted(declared - self.plugins_used):
            self.errors.append(f"plugins: {pid!r} is declared but no op or passive uses it")
        prefix = (self.hero or {}).get("fid") or self.doc["hero"]
        for pid in declared:
            if not pid.startswith(prefix + ":"):
                self.errors.append(f"plugins: {pid!r} must start with '{prefix}:' (the HeroDef fid)")
        if self.hero:
            self.cross_check()
        return self.errors

    # --- cards

    def card(self, card: dict, path: str) -> None:
        for moment in MOMENTS:
            self.ops(card["effects"][moment], f"{path}.effects.{moment}", _Ctx({}, set()))
        if card["effects"].get("unboosted"):
            if not card.get("may_boost"):
                self.errors.append(f"{path}: 'unboosted' is what happens when the free BOOST is declined: it needs may_boost")
            self.ops(card["effects"]["unboosted"], f"{path}.effects.unboosted", _Ctx({}, set()))
        ongoing = card.get("ongoing")
        if ongoing:
            for i, m in enumerate(ongoing["modifiers"]):
                self.modifier(m, f"{path}.ongoing.modifiers[{i}]", _Ctx({}, set()))
            for i, t in enumerate(ongoing["triggers"]):
                self.trigger(t, f"{path}.ongoing.triggers[{i}]")
            self.refs(ongoing["until"], f"{path}.ongoing.until", _Ctx({}, set()))
        invention = card.get("invention")
        if invention:
            for i, m in enumerate(invention["modifiers"]):
                self.modifier(m, f"{path}.invention.modifiers[{i}]", _Ctx({}, set()))
            for i, t in enumerate(invention["triggers"]):
                self.trigger(t, f"{path}.invention.triggers[{i}]")
        if card.get("may_boost"):
            for op in _walk(card["effects"]["during"]):
                if op["op"] == "boost" and op["card"] == "this":
                    self.errors.append(f"{path}: may_boost already expresses the free BOOST; the boost op on this is redundant")
        if self.hero:
            kind = self.hero_cards.get(card["title"], {}).get("type")
            if kind == "scheme":
                for moment in ("immediately", "during", "after"):
                    if card["effects"][moment]:
                        self.errors.append(f"{path}: a scheme has no moment {moment}")
                if card.get("may_boost"):
                    self.errors.append(f"{path}: a scheme is not played in combat, it cannot carry may_boost")
            elif kind is not None:
                if card["effects"]["scheme"]:
                    self.errors.append(f"{path}: only schemes carry ops in 'scheme'")
                if ongoing:
                    self.errors.append(f"{path}: only schemes carry 'ongoing'")

    # --- triggers and modifiers

    def trigger(self, trig: dict, path: str) -> None:
        bound = EVENT_BINDINGS.get(trig["when"]["event"], {})
        ctx = _Ctx({f"${n}": kind for n, kind in bound.items()}, set())
        self.refs(trig["when"], f"{path}.when", ctx)
        if "condition" in trig:
            self.refs(trig["condition"], f"{path}.condition", ctx)
        self.ops(trig["ops"], f"{path}.ops", ctx)

    def modifier(self, mod: dict, path: str, ctx: _Ctx) -> None:
        if mod["kind"] == "plugin":
            self.plugins_used.add(mod["plugin"])
        if mod["kind"] == "status":
            self.status_scope(mod, path)
        self.refs(mod, path, ctx)

    # --- ops

    def ops(self, ops: list[dict], path: str, ctx: _Ctx) -> None:
        """Walks a list in order: each op sees the bindings and the zones seen by the previous ones."""
        for i, op in enumerate(ops):
            self.op(op, f"{path}[{i}] ({op['op']})", ctx)

    def op(self, op: dict, path: str, ctx: _Ctx) -> None:
        name = op["op"]
        if name == "plugin":
            self.plugins_used.add(op["id"])
        if name == "status":
            self.status_scope(op, path)
        if name == "counter" and ("delta" in op) == ("set" in op):
            self.errors.append(f"{path}: counter carries 'delta' or 'set', one of the two")
        if name == "counter" and self.counters is not None and op["name"] not in self.counters:
            self.errors.append(f"{path}: counter {op['name']!r} not declared (ability.counters or HeroDef)")
        if name == "revive":
            tgt = op["target"]
            if not (isinstance(tgt, dict) and tgt.get("state") == "defeated"):
                self.errors.append(f"{path}: revive needs a selector with state 'defeated'")
        if name == "move" and op["amount"] == 0:
            self.errors.append(f"{path}: move with amount 0 moves nothing; the op is redundant")
        self.refs({k: v for k, v in op.items() if k not in OP_LIST_KEYS and k != "options"}, path, ctx)
        # nested lists: child scope (what is bound inside does not leak out)
        if name == "for_each":
            inner = ctx.child()
            self.bind(op["as"], "player" if "players" in op["over"] else "fighter", path, inner)
            self.ops(op["ops"], f"{path}.ops", inner)
        elif name == "optional":
            inner = ctx.child()
            if "cost" in op:
                self.ops(op["cost"], f"{path}.cost", inner)
            self.ops(op["ops"], f"{path}.ops", inner)
            if "else" in op:
                self.ops(op["else"], f"{path}.else", ctx.child())
        elif name == "if":
            self.ops(op["then"], f"{path}.then", ctx.child())
            if "else" in op:
                self.ops(op["else"], f"{path}.else", ctx.child())
        elif name == "choose_effect":
            for i, opt in enumerate(op["options"]):
                self.ops(opt["ops"], f"{path}.options[{i}].ops", ctx.child())
        # effects on the scope for the following ops of the same list
        if name == "look_hand":
            ctx.seen.add((op["player"], "hand"))
        if name in ("look_deck", "search_deck"):
            ctx.seen.add((op["player"], "deck"))
        if name == "plugin" and "as" in (op.get("args") or {}):      # a plugin that binds the cards it chose
            self.bind(op["args"]["as"], "card", path, ctx)
        if "as" in op and name != "for_each":
            self.bind(op["as"], OP_BINDINGS[name], path, ctx)

    def bind(self, name: str, kind: str, path: str, ctx: _Ctx) -> None:
        if name in RESERVED_NAMES:
            self.errors.append(f"{path}: {name!r} is a reserved name, it cannot be bound")
        ctx.scope[f"${name}"] = kind

    def status_scope(self, node: dict, path: str) -> None:
        want = STATUS_SCOPE[node["name"]]
        other = "player" if want == "target" else "target"
        if want not in node or other in node:
            self.errors.append(f"{path}: the status {node['name']!r} goes on '{want}', not on '{other}'")
        if (node["name"] in AMOUNT_STATUSES) != ("amount" in node):
            self.errors.append(f"{path}: 'amount' only (and always) with {' or '.join(AMOUNT_STATUSES)}")

    # --- references inside the arguments of an op, condition, event or modifier

    def refs(self, node, path: str, ctx: _Ctx, key: str | None = None, parent: dict | None = None,
             counting: bool = False) -> None:
        """`key`/`parent`: where the node is (to know what type of binding is expected and whether a CardSel chooses).
        `counting`: the node is under an `exists` test or a `count_cards`, which count without choosing or looking."""
        if isinstance(node, str):
            if node.startswith("$"):
                self.var_ref(node, path, ctx, key, parent)
            return
        if isinstance(node, list):
            for i, v in enumerate(node):
                self.refs(v, f"{path}[{i}]", ctx, key, parent, counting)
            return
        if not isinstance(node, dict):
            return
        if "zone" in node and "player" in node:
            self.card_sel(node, path, ctx, counting)
        if node.get("test") == "form_is" and self.forms is not None and node["form"] not in self.forms:
            self.errors.append(f"{path}: form {node['form']!r} does not exist in the HeroDef ({sorted(self.forms)})")
        if node.get("test") == "counter" and self.counters is not None and node["name"] not in self.counters:
            self.errors.append(f"{path}: counter {node['name']!r} not declared")
        if "counter" in node and isinstance(node["counter"], str) and self.counters is not None \
                and node["counter"] not in self.counters and "test" not in node:
            self.errors.append(f"{path}: counter {node['counter']!r} not declared")
        if self.fighter_names is not None and _is_fighter_sel(node) and "name" in node \
                and node["name"] not in self.fighter_names:
            self.errors.append(f"{path}: fighter {node['name']!r} does not exist ({sorted(self.fighter_names)})")
        below_counts = counting or node.get("test") == "exists" or "count_cards" in node
        for k, v in node.items():
            if k == "as":
                continue
            self.refs(v, f"{path}.{k}", ctx, k, node, below_counts)

    def var_ref(self, var: str, path: str, ctx: _Ctx, key: str | None, parent: dict | None) -> None:
        if var not in ctx.scope:
            self.errors.append(f"{path}: {var!r} is not bound at this point (bindings: {sorted(ctx.scope) or 'none'})")
            return
        want = None
        if key in PLAYER_KEYS or (key == "to" and parent is not None and parent.get("op") == "reveal"):
            want = "player"
        elif key in FIGHTER_KEYS or (key == "to" and parent is not None):
            want = "fighter"
        elif key in CARD_KEYS:
            want = "card"
        elif key in NUMBER_KEYS:
            want = "number"
        have = ctx.scope[var]
        if want is not None and have != want:
            self.errors.append(f"{path}: {var!r} binds a {have}, but here ({key}) a {want} is needed")

    def card_sel(self, sel: dict, path: str, ctx: _Ctx, counting: bool) -> None:
        pick = sel.get("pick", "chosen")
        if pick == "all" and "amount" in sel:
            self.errors.append(f"{path}: 'amount' makes no sense with pick 'all'")
        if pick != "chosen":
            for k in ("chooser", "up_to"):
                if k in sel:
                    self.errors.append(f"{path}: {k!r} only goes with pick 'chosen' (here pick {pick!r})")
        if sel["zone"] != "discard" and pick == "last":
            self.errors.append(f"{path}: pick 'last' (the most recently discarded) is only valid on the discard pile")
        if sel["zone"] == "hand" and pick in ("top", "bottom"):
            self.errors.append(f"{path}: the hand has no order; pick {pick!r} is only valid on the deck")
        if counting or sel["zone"] not in HIDDEN_ZONES or pick != "chosen":
            return
        chooser = sel.get("chooser", "owner")
        if chooser == sel["player"]:
            return
        if (sel["player"], sel["zone"]) not in ctx.seen:
            how = "look_hand" if sel["zone"] == "hand" else "look_deck or search_deck"
            zone = "the hand" if sel["zone"] == "hand" else "the deck"
            self.errors.append(f"{path}: {chooser} chooses from {zone} of {sel['player']} without a prior {how} "
                               f"in this effect (hidden-information rule)")

    # --- cross-check with the HeroDef

    @property
    def hero_cards(self) -> dict[str, dict]:
        if not hasattr(self, "_hero_cards"):
            by = {}
            for c in (self.hero or {}).get("deck", {}).get("cards", ()):
                e = by.setdefault(c["title"], {"copies": 0, "text": c.get("text", ""), "type": c["type"]})
                e["copies"] += 1
            self._hero_cards = by
        return self._hero_cards

    def cross_check(self) -> None:
        deck = self.hero_cards
        mine = {c["title"]: c for c in self.doc["cards"]}
        for t in sorted(set(deck) - set(mine)):
            self.errors.append(f"cards: card {t!r} of the deck is missing")
        for t in sorted(set(mine) - set(deck)):
            self.errors.append(f"cards: {t!r} is not in the HeroDef's deck")
        for t in sorted(set(mine) & set(deck)):
            if mine[t]["copies"] != deck[t]["copies"]:
                self.errors.append(f"cards ({t}): copies {mine[t]['copies']} but the deck has {deck[t]['copies']}")
            if mine[t]["text"].strip() != deck[t]["text"].strip():
                self.errors.append(f"cards ({t}): the text is not the HeroDef's")


def _is_fighter_sel(node: dict) -> bool:
    """An object with only FighterSel keys (an op, a test or a modifier carries its own op/test/event/kind)."""
    return bool(node) and set(node) <= FIGHTER_SEL_KEYS and node.get("kind") in (None, "hero", "sidekick", "any")


def _walk(ops):
    for op in ops:
        yield op
        for key in OP_LIST_KEYS:
            if isinstance(op.get(key), list):
                yield from _walk(op[key])
        for opt in op.get("options", ()):
            yield from _walk(opt["ops"])


# ---------------------------------------------------------------- entry point

def validate(doc: dict, schema: dict, hero: dict | None) -> list[str]:
    errors = _Schema(schema).errors(doc, schema, "$")
    if errors:
        return errors
    return Semantics(doc, hero).run()


def validate_file(path: Path, schema: dict | None = None, heroes_dir: Path = HEROES_DIR) -> list[str]:
    schema = schema or load_schema()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        return [f"invalid JSON: {e}"]
    hero = None
    if isinstance(doc, dict) and isinstance(doc.get("hero"), str):
        hero_path = heroes_dir / f"{doc['hero']}.json"
        if hero_path.exists():
            hero = json.loads(hero_path.read_text(encoding="utf-8"))
    return validate(doc, schema, hero)


def effect_files(effects_dir: Path = EFFECTS_DIR) -> list[Path]:
    return sorted(p for p in effects_dir.glob("*.json") if p.name != "schema.json")


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or effect_files()
    schema = load_schema()
    total = 0
    for p in paths:
        errs = validate_file(p, schema)
        total += len(errs)
        for e in errs:
            print(f"{p}: {e}")
        if not errs:
            print(f"{p}: OK")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
