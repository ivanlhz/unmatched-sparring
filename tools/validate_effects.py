"""Valida los ficheros de efectos `data/heroes/effects/<slug>.json` contra el DSL v1 (docs/effects-dsl.md).

Dos capas:
1. `schema.json` (JSON Schema): estructura, ops cerradas y tipos de argumento. Se aplica con el validador de
   subconjunto de este modulo (no hay `jsonschema` en el entorno y no hace falta mas que esto).
2. Reglas semanticas que un esquema no expresa: ligaduras resueltas y con el tipo que toca (jugador, luchador,
   carta, numero), zonas ocultas (elegir de la mano o del mazo de otro exige haberlos mirado antes en el mismo
   efecto), plugins declarados y usados, ambito de cada estado, combinaciones prohibidas de CardSel, `may_boost`
   sin `boost` duplicado ni en planes, `move` con amount 0, y el cruce con el HeroDef (`data/heroes/<slug>.json`):
   titulos, copias, texto, tipos de carta, nombres de luchador, formas y contadores.

Uso:
    python tools/validate_effects.py                 # todos los ficheros de data/heroes/effects
    python tools/validate_effects.py data/heroes/effects/medusa.json
Salida: una linea por error `<fichero>: <ruta>: <mensaje>`; codigo 1 si hay alguno.
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
# que liga cada evento y de que tipo (ver docs/effects-dsl.md 2.10)
EVENT_BINDINGS = {
    "after_attack": {"attacker": "fighter", "target": "fighter"},
    "attacked": {"attacker": "fighter", "target": "fighter"},
    "combat_damage_dealt": {"by": "fighter", "to": "fighter", "amount": "number"},
    "damage_taken": {"target": "fighter", "amount": "number"},
    "card_discarded": {"card": "card"},
    "card_played": {"card": "card"},
    "fighter_defeated": {"fighter": "fighter"},
}
# tipo de la ligadura que crea cada op con `as`
OP_BINDINGS = {"draw": "card", "discard": "card", "choose": "card", "look_deck": "card", "search_deck": "card",
               "damage": "fighter"}
# tipo que espera cada campo cuando lleva una referencia $var
PLAYER_KEYS = frozenset({"player", "chooser", "order", "start_space_of"})
FIGHTER_KEYS = frozenset({"role", "zone_of", "adjacent_to", "space_of", "nearest_to", "fighter", "target",
                          "with", "by", "from", "fighters", "count"})
CARD_KEYS = frozenset({"card", "cards", "of", "except"})
NUMBER_KEYS = frozenset({"amount", "hp", "left", "right", "look"})
STATUS_SCOPE = {
    "immune_to_effect_damage": "target", "cannot_leave_space": "target",
    "immune_to_enemy_effect_damage": "player", "immune_to_enemy_effect_moves": "player",
    "immune_to_enemy_forced_discards": "player", "cannot_gain_actions": "player", "cannot_draw": "player",
    "next_attack_bonus": "player",
}
HIDDEN_ZONES = ("hand", "deck")
OP_LIST_KEYS = ("ops", "then", "else", "cost")
MOMENTS = ("immediately", "during", "after", "scheme", "boost")
TYPE_NAMES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float),
              "boolean": bool, "null": type(None)}
FIGHTER_SEL_KEYS = frozenset({"role", "side", "kind", "name", "where", "other", "state", "filter", "pick"})


# ---------------------------------------------------------------- capa 1: subconjunto de JSON Schema

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
            return [f"{path}: debe ser {schema['const']!r}, es {_short(inst)}"]
        if "enum" in schema and inst not in schema["enum"]:
            return [f"{path}: {_short(inst)} no esta entre {schema['enum']}"]
        if "type" in schema and not _is_type(inst, schema["type"]):
            return [f"{path}: debe ser de tipo {schema['type']}, es {_short(inst)}"]
        if "oneOf" in schema:
            out += self._one_of(inst, schema["oneOf"], path)
        if "anyOf" in schema:
            out += self._any_of(inst, schema["anyOf"], path)
        if isinstance(inst, str):
            if "pattern" in schema and not re.search(schema["pattern"], inst):
                out.append(f"{path}: {inst!r} no cumple el patron {schema['pattern']}")
            if "minLength" in schema and len(inst) < schema["minLength"]:
                out.append(f"{path}: cadena vacia")
        if isinstance(inst, (int, float)) and not isinstance(inst, bool):
            if "minimum" in schema and inst < schema["minimum"]:
                out.append(f"{path}: {inst} es menor que {schema['minimum']}")
            if "maximum" in schema and inst > schema["maximum"]:
                out.append(f"{path}: {inst} es mayor que {schema['maximum']}")
        if isinstance(inst, list):
            if "minItems" in schema and len(inst) < schema["minItems"]:
                out.append(f"{path}: hacen falta al menos {schema['minItems']} elementos")
            if "items" in schema:
                for i, v in enumerate(inst):
                    out += self.errors(v, schema["items"], f"{path}[{i}]")
        if isinstance(inst, dict):
            props = schema.get("properties", {})
            for key in schema.get("required", ()):
                if key not in inst:
                    out.append(f"{path}: falta el campo obligatorio {key!r}")
            for key, v in inst.items():
                if key in props:
                    out += self.errors(v, props[key], f"{path}.{key}")
                elif schema.get("additionalProperties", True) is False:
                    out.append(f"{path}: campo desconocido {key!r} (validos: {', '.join(props)})")
                elif isinstance(schema.get("additionalProperties"), dict):
                    out += self.errors(v, schema["additionalProperties"], f"{path}.{key}")
        return out

    def _discriminator(self, branches: list[dict]) -> str | None:
        """Clave cuyo `const` distingue cada alternativa (op, test, event, kind), si todas la tienen."""
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
                return [f"{path}: debe ser un objeto con {key!r}, es {_short(inst)}"]
            if key not in inst:
                return [f"{path}: falta {key!r}"]
            for b in branches:
                b = self.resolve(b)
                if self.resolve(b["properties"][key])["const"] == inst[key]:
                    return self.errors(inst, b, path)
            valid = [self.resolve(self.resolve(b)["properties"][key])["const"] for b in branches]
            return [f"{path}: {key} {inst[key]!r} desconocida (validas: {', '.join(map(str, valid))})"]
        return self._any_of(inst, branches, path)

    def _applicable(self, inst, schema: dict) -> bool:
        """La alternativa puede valer para este valor por su tipo, const o enum (sin mirar el contenido)."""
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
        """Elige la rama por tipo (null frente a objeto, cadena frente a objeto) y, entre varias del mismo tipo,
        por las claves obligatorias presentes; asi el error que sale es el de la rama que el autor queria."""
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
            return [f"{path}: hace falta al menos uno de los campos {keys}"]
        best = min(attempts, key=len)
        return [f"{path}: {_short(inst)} no encaja con ninguna alternativa; la mas cercana falla por: "
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


# ---------------------------------------------------------------- capa 2: reglas semanticas

class _Ctx:
    """Lo que el validador arrastra por un arbol de ops: ligaduras en ambito (nombre -> tipo) y, por jugador,
    que zonas ocultas (mano, mazo) ya se han mirado en este efecto."""

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
        for i, p in enumerate(ab["passives"]):
            if "id" not in p:
                self.errors.append(f"ability.passives[{i}]: una pasiva necesita 'id'")
            self.modifier(p, f"ability.passives[{i}]", _Ctx({}, set()))
        titles = [c["title"] for c in self.doc["cards"]]
        for t in sorted({t for t in titles if titles.count(t) > 1}):
            self.errors.append(f"cards: titulo repetido {t!r}")
        for i, card in enumerate(self.doc["cards"]):
            self.card(card, f"cards[{i}] ({card['title']})")
        declared = {p["id"] for p in self.doc["plugins"]}
        for pid in sorted(self.plugins_used - declared):
            self.errors.append(f"plugins: {pid!r} se usa pero no esta declarado")
        for pid in sorted(declared - self.plugins_used):
            self.errors.append(f"plugins: {pid!r} esta declarado pero ninguna op ni pasiva lo usa")
        prefix = (self.hero or {}).get("fid") or self.doc["hero"]
        for pid in declared:
            if not pid.startswith(prefix + ":"):
                self.errors.append(f"plugins: {pid!r} debe empezar por '{prefix}:' (el fid del HeroDef)")
        if self.hero:
            self.cross_check()
        return self.errors

    # --- cartas

    def card(self, card: dict, path: str) -> None:
        for moment in MOMENTS:
            self.ops(card["effects"][moment], f"{path}.effects.{moment}", _Ctx({}, set()))
        ongoing = card.get("ongoing")
        if ongoing:
            for i, m in enumerate(ongoing["modifiers"]):
                self.modifier(m, f"{path}.ongoing.modifiers[{i}]", _Ctx({}, set()))
            for i, t in enumerate(ongoing["triggers"]):
                self.trigger(t, f"{path}.ongoing.triggers[{i}]")
            self.refs(ongoing["until"], f"{path}.ongoing.until", _Ctx({}, set()))
        if card.get("may_boost"):
            for op in _walk(card["effects"]["during"]):
                if op["op"] == "boost" and op["card"] == "this":
                    self.errors.append(f"{path}: may_boost ya expresa el BOOST gratuito; sobra la op boost sobre this")
        if self.hero:
            kind = self.hero_cards.get(card["title"], {}).get("type")
            if kind == "scheme":
                for moment in ("immediately", "during", "after"):
                    if card["effects"][moment]:
                        self.errors.append(f"{path}: un plan no tiene momento {moment}")
                if card.get("may_boost"):
                    self.errors.append(f"{path}: un plan no se juega en combate, no puede llevar may_boost")
            elif kind is not None:
                if card["effects"]["scheme"]:
                    self.errors.append(f"{path}: solo los planes llevan ops en 'scheme'")
                if ongoing:
                    self.errors.append(f"{path}: solo los planes llevan 'ongoing'")

    # --- disparadores y modificadores

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
        """Recorre una lista en orden: cada op ve las ligaduras y las zonas vistas por las anteriores."""
        for i, op in enumerate(ops):
            self.op(op, f"{path}[{i}] ({op['op']})", ctx)

    def op(self, op: dict, path: str, ctx: _Ctx) -> None:
        name = op["op"]
        if name == "plugin":
            self.plugins_used.add(op["id"])
        if name == "status":
            self.status_scope(op, path)
        if name == "counter" and ("delta" in op) == ("set" in op):
            self.errors.append(f"{path}: counter lleva 'delta' o 'set', uno de los dos")
        if name == "counter" and self.counters is not None and op["name"] not in self.counters:
            self.errors.append(f"{path}: contador {op['name']!r} no declarado (ability.counters o HeroDef)")
        if name == "revive":
            tgt = op["target"]
            if not (isinstance(tgt, dict) and tgt.get("state") == "defeated"):
                self.errors.append(f"{path}: revive necesita un selector con state 'defeated'")
        if name == "move" and op["amount"] == 0:
            self.errors.append(f"{path}: move con amount 0 no mueve nada; sobra la op")
        self.refs({k: v for k, v in op.items() if k not in OP_LIST_KEYS and k != "options"}, path, ctx)
        # listas anidadas: ambito hijo (lo ligado dentro no sale fuera)
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
        # efectos sobre el ambito para las ops siguientes de la misma lista
        if name == "look_hand":
            ctx.seen.add((op["player"], "hand"))
        if name in ("look_deck", "search_deck"):
            ctx.seen.add((op["player"], "deck"))
        if "as" in op and name != "for_each":
            self.bind(op["as"], OP_BINDINGS[name], path, ctx)

    def bind(self, name: str, kind: str, path: str, ctx: _Ctx) -> None:
        if name in RESERVED_NAMES:
            self.errors.append(f"{path}: {name!r} es un nombre reservado, no se puede ligar")
        ctx.scope[f"${name}"] = kind

    def status_scope(self, node: dict, path: str) -> None:
        want = STATUS_SCOPE[node["name"]]
        other = "player" if want == "target" else "target"
        if want not in node or other in node:
            self.errors.append(f"{path}: el estado {node['name']!r} va sobre '{want}', no sobre '{other}'")
        if (node["name"] == "next_attack_bonus") != ("amount" in node):
            self.errors.append(f"{path}: 'amount' solo (y siempre) con next_attack_bonus")

    # --- referencias dentro de los argumentos de una op, condicion, evento o modificador

    def refs(self, node, path: str, ctx: _Ctx, key: str | None = None, parent: dict | None = None,
             counting: bool = False) -> None:
        """`key`/`parent`: donde esta el nodo (para saber que tipo de ligadura se espera y si un CardSel elige).
        `counting`: el nodo esta bajo un test `exists` o un `count_cards`, que cuentan sin elegir ni mirar."""
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
            self.errors.append(f"{path}: forma {node['form']!r} no existe en el HeroDef ({sorted(self.forms)})")
        if node.get("test") == "counter" and self.counters is not None and node["name"] not in self.counters:
            self.errors.append(f"{path}: contador {node['name']!r} no declarado")
        if "counter" in node and isinstance(node["counter"], str) and self.counters is not None \
                and node["counter"] not in self.counters and "test" not in node:
            self.errors.append(f"{path}: contador {node['counter']!r} no declarado")
        if self.fighter_names is not None and _is_fighter_sel(node) and "name" in node \
                and node["name"] not in self.fighter_names:
            self.errors.append(f"{path}: luchador {node['name']!r} no existe ({sorted(self.fighter_names)})")
        below_counts = counting or node.get("test") == "exists" or "count_cards" in node
        for k, v in node.items():
            if k == "as":
                continue
            self.refs(v, f"{path}.{k}", ctx, k, node, below_counts)

    def var_ref(self, var: str, path: str, ctx: _Ctx, key: str | None, parent: dict | None) -> None:
        if var not in ctx.scope:
            self.errors.append(f"{path}: {var!r} no esta ligado en este punto (ligaduras: {sorted(ctx.scope) or 'ninguna'})")
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
            self.errors.append(f"{path}: {var!r} liga un {have}, pero aqui ({key}) hace falta un {want}")

    def card_sel(self, sel: dict, path: str, ctx: _Ctx, counting: bool) -> None:
        pick = sel.get("pick", "chosen")
        if pick == "all" and "amount" in sel:
            self.errors.append(f"{path}: 'amount' no tiene sentido con pick 'all'")
        if pick != "chosen":
            for k in ("chooser", "up_to"):
                if k in sel:
                    self.errors.append(f"{path}: {k!r} solo va con pick 'chosen' (aqui pick {pick!r})")
        if sel["zone"] == "hand" and pick in ("top", "bottom"):
            self.errors.append(f"{path}: la mano no tiene orden; pick {pick!r} solo vale en el mazo")
        if counting or sel["zone"] not in HIDDEN_ZONES or pick != "chosen":
            return
        chooser = sel.get("chooser", "owner")
        if chooser == sel["player"]:
            return
        if (sel["player"], sel["zone"]) not in ctx.seen:
            how = "look_hand" if sel["zone"] == "hand" else "look_deck o search_deck"
            zone = "la mano" if sel["zone"] == "hand" else "el mazo"
            self.errors.append(f"{path}: {chooser} elige de {zone} de {sel['player']} sin un {how} previo "
                               f"en este efecto (regla de informacion oculta)")

    # --- cruce con el HeroDef

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
            self.errors.append(f"cards: falta la carta {t!r} del mazo")
        for t in sorted(set(mine) - set(deck)):
            self.errors.append(f"cards: {t!r} no esta en el mazo del HeroDef")
        for t in sorted(set(mine) & set(deck)):
            if mine[t]["copies"] != deck[t]["copies"]:
                self.errors.append(f"cards ({t}): copies {mine[t]['copies']} pero el mazo tiene {deck[t]['copies']}")
            if mine[t]["text"].strip() != deck[t]["text"].strip():
                self.errors.append(f"cards ({t}): el texto no es el del HeroDef")


def _is_fighter_sel(node: dict) -> bool:
    """Un objeto con solo claves de FighterSel (una op, un test o un modificador llevan op/test/event/kind propio)."""
    return bool(node) and set(node) <= FIGHTER_SEL_KEYS and node.get("kind") in (None, "hero", "sidekick", "any")


def _walk(ops):
    for op in ops:
        yield op
        for key in OP_LIST_KEYS:
            if isinstance(op.get(key), list):
                yield from _walk(op[key])
        for opt in op.get("options", ()):
            yield from _walk(opt["ops"])


# ---------------------------------------------------------------- entrada

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
        return [f"JSON no valido: {e}"]
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
