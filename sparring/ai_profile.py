"""Static AI profile of each fighter, computed when a hero is imported (tools/import_hero.py) and stored in the
HeroDef as `ai_profile`. Nothing here depends on the game state: the bot weighs it against the state at runtime
(`sparring/ai_medusa.py: kill_value`, `protect_factor`, `strike_reward`).

Why: what a sidekick is worth depends on the hero. Bigfoot's Jackalope carries a scheme only it can play (2 damage
to an enemy hero, 3 copies): killing it early prevents up to 6 damage. That is read from the card data (restriction
to the fighter + DSL ops), never hand-coded per hero in the AI.

Schema, one entry per fighter group (key: the fid of the hero or of the sidekick group):

    {"name", "hero", "count", "max_hp", "move", "ranged",
     "role":     "hero" | "striker" | "keep_away"       (overlay `ai_role` overrides the derived one)
     "attack":   {"cards": n, "mean": m, "max": v}      attack/versatile cards it can play (its own + ANY)
     "exclusive": [{"title", "type", "copies", "impact"}]   cards restricted to this fighter: points per copy
     "requires_alive": [{"source", "kind": "ability" | "card", "copies", "impact"}]
                                        effects of the hero / other fighters that need this fighter on the board}

`impact` is in the evaluation's points (the scale of ai_medusa: CARD_VALUE 0.4 per card, 1.0 per hit point of an
enemy hero). Derived from the DSL ops of the card (docs/effects-dsl.md) with the table `OP_POINTS` below.

Role: a ranged fighter is a "striker" (it is worth ending its move in strike range); a melee fighter with 3 or more
hit points too; a fragile melee one (Medusa's Harpies, 1 hit point) is "keep_away" and keeps the kiting rule of
`MedusaAI.harpy_score`. A hero declares what the data cannot say in the overlay: `"ai_role": {"<fid>": "<role>"}`.

Op -> points (per resolution; amounts that are not a plain integer count as DEFAULT_AMOUNT):
    damage      enemy hero 1.0/hp, enemy sidekick 0.8/hp, "any fighter" 0.9/hp, own fighter -0.9/hp
                (x1.5 when it hits each fighter of a selector)
    heal        0.9/hp (own); set_hp 0.5; revive / summon 1.5
    draw        0.4 per card (owner), -0.4 (rival draws)
    discard     rival hand 0.5/card, rival deck 0.3, an ongoing in play 1.0; own cards -0.3/card
    move/swap   0.3; place 0.4; gain_action 1.0/action; cancel_effects 1.0; redirect_damage 1.0
    modify_value 0.3/point; set_value 0.5; boost 0.4; status immune_* 1.0, cannot_* 0.8, next_attack_bonus
                0.3/point, any other 0.5; search_deck 0.6; return_to_deck / put_in_hand 0.5; look_hand 0.3;
                look_deck 0.2; counter 0.3; plugin 0.5; reveal / choose / end_turn 0
    if          0.7 x the better branch; optional 0.8 x its ops; for_each 1.5 x its ops;
                choose_effect: the best option
    moments     scheme 1.0, immediately/during/after 0.6 (the combat must be won / go that way), boost 0.3
    a card only the fighter can play is a dead card in the rival's hand without it: DEAD_CARD 0.3 per copy, plus its
                own combat value COMBAT_PER_POINT 0.15 per printed point (attack, defense, versatile); a card's impact is >= 0

`requires_alive`: sources outside the fighter's own cards whose effects need it on the board: ops that target it
(heal, place, redirect to it) or sit under an `if` / passive condition that tests it exists. A passive of the hero
(FATEFUL BARGAINS) is worth PASSIVE_VALUE for the whole game; a card is worth its ops per copy."""
from __future__ import annotations

DEFAULT_AMOUNT = 2
DEAD_CARD = 0.3
COMBAT_PER_POINT = 0.15     # a card's own combat value: per printed point above zero (Second Shot 2 -> 0.3 on top of the dead card)
PASSIVE_VALUE = 2.0
IF_FACTOR, OPTIONAL_FACTOR, EACH_FACTOR = 0.7, 0.8, 1.5
MOMENT_FACTOR = {"scheme": 1.0, "immediately": 0.6, "during": 0.6, "after": 0.6, "boost": 0.3}
ROLES = ("hero", "striker", "keep_away")
STRIKER_MIN_HP = 3          # a melee fighter with this many hit points or more is worth sending forward

# ---------------------------------------------------------------- play style (derived from the hero's data, read by ai_medusa)
STYLE_HIT_AND_RUN = "hit_and_run"
STYLE_FINISHER = "finisher"
FINISHER_BOOSTS = 2         # a card the owner may BOOST this many times or more (The Big Reveal) is a finisher: it is saved for a blow that lands


def derive_style(places_on_boosted_maneuver: bool, max_boosts: int) -> frozenset:
    """The play style traits of a hero from what its data allows, each independent of the other:
    - hit and run: a boosted Maneuver can place the hero on any space (ESCAPE ARTIST, rule `maneuver_boost_places_hero`), so it
      can stay out of the rival's reach almost always and pop in for a blow (`ai_medusa`: stronger fear of standing in reach, a
      bonus for a real opportunity). Without the placement rule there is no way back in: the trait is never granted.
    - finisher: a card the hero's own fighters may BOOST FINISHER_BOOSTS times or more is a blow worth saving."""
    traits = set()
    if places_on_boosted_maneuver:
        traits.add(STYLE_HIT_AND_RUN)
    if max_boosts >= FINISHER_BOOSTS:
        traits.add(STYLE_FINISHER)
    return frozenset(traits)


OP_POINTS = {"set_hp": 0.5, "revive": 1.5, "summon": 1.5, "move": 0.3, "swap": 0.3, "place": 0.4,
             "cancel_effects": 1.0, "redirect_damage": 1.0, "set_value": 0.5, "boost": 0.4, "search_deck": 0.6,
             "return_to_deck": 0.5, "put_in_hand": 0.5, "look_hand": 0.3, "look_deck": 0.2, "counter": 0.3,
             "plugin": 0.5, "reveal": 0.0, "choose": 0.0, "end_turn": 0.0}
PER_HP = {"damage_hero": 1.0, "damage_sidekick": 0.8, "damage_any": 0.9, "damage_own": -0.9, "heal": 0.9}
PER_CARD = {"draw": 0.4, "draw_rival": -0.4, "discard_hand": 0.5, "discard_deck": 0.3, "discard_play": 1.0,
            "discard_own": -0.3}
ACTION_POINTS = 1.0
MODIFY_PER_POINT = 0.3


def amount(raw, default: int = DEFAULT_AMOUNT) -> float:
    return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else float(default)


def _sel(target) -> dict:
    if isinstance(target, str):
        return {"role": target}
    return target if isinstance(target, dict) else {}


def _side(sel: dict) -> str:
    """own | enemy | any, from a FighterSel (a role: hero/this are the owner's, opposing the rival's)."""
    role = sel.get("role")
    if role in ("hero", "this"):
        return "own"
    if role in ("opposing", "attacker", "defender"):
        return "any"
    return sel.get("side", "any")


def _damage_points(sel: dict, n: float) -> float:
    side, each = _side(sel), (EACH_FACTOR if sel.get("pick") == "all" else 1.0)
    if side == "own":
        return PER_HP["damage_own"] * n * each
    if side == "enemy":
        per = PER_HP["damage_hero"] if sel.get("kind") == "hero" else PER_HP["damage_sidekick"]
        return per * n * each
    return PER_HP["damage_any"] * n * each


def _discard_points(cards: dict, n: float) -> float:
    if not isinstance(cards, dict):
        return PER_CARD["discard_own"] * n
    mine = cards.get("player", "owner") == "owner"
    if cards.get("zone") == "in_play":
        return 0.0 if mine else PER_CARD["discard_play"] * n
    if mine:
        return PER_CARD["discard_own"] * n
    return PER_CARD["discard_deck" if cards.get("zone") == "deck" else "discard_hand"] * n


def _status_points(op: dict) -> float:
    name = op.get("name", "")
    if name.startswith("immune_"):
        return 1.0
    if name.startswith("cannot_"):
        return 0.8
    if name in ("next_attack_bonus", "attack_bonus"):
        return 0.3 * amount(op.get("amount"), 1)
    return 0.5


def op_points(op: dict) -> float:
    """Points of one op (and of what it contains), at the top level of a moment before the moment factor."""
    kind = op.get("op")
    if kind == "damage":
        return _damage_points(_sel(op.get("target")), amount(op.get("amount")))
    if kind == "heal":
        return PER_HP["heal"] * amount(op.get("amount")) * (EACH_FACTOR if _sel(op.get("target")).get("pick") == "all" else 1.0)
    if kind == "draw":
        n = amount(op.get("amount"), 1)
        return PER_CARD["draw" if op.get("player", "owner") == "owner" else "draw_rival"] * n
    if kind == "discard":
        return _discard_points(op.get("cards"), amount((op.get("cards") or {}).get("amount") if isinstance(op.get("cards"), dict) else 1, 1))
    if kind == "gain_action":
        return ACTION_POINTS * amount(op.get("amount"), 1)
    if kind == "modify_value":
        return MODIFY_PER_POINT * abs(amount(op.get("amount"), 1))
    if kind == "status":
        return _status_points(op)
    if kind == "if":
        return IF_FACTOR * max(ops_points(op.get("then") or ()), ops_points(op.get("else") or ()))
    if kind == "optional":
        return OPTIONAL_FACTOR * ops_points(op.get("ops") or ())
    if kind == "for_each":
        return EACH_FACTOR * ops_points(op.get("ops") or ())
    if kind == "choose_effect":
        return max((ops_points(o.get("ops") or ()) for o in op.get("options") or ()), default=0.0)
    return OP_POINTS.get(kind, 0.0)


def ops_points(ops) -> float:
    return sum(op_points(o) for o in ops)


def moment_points(effects: dict) -> float:
    return sum(MOMENT_FACTOR[m] * ops_points(effects.get(m) or ()) for m in MOMENT_FACTOR)


# ---------------------------------------------------------------- dependencies on a fighter being alive
def _names_alive(node, name: str) -> bool:
    """Does a FighterSel (or anything containing one) name `name` as a live fighter of the owner's side?"""
    if isinstance(node, dict):
        if node.get("name") == name and node.get("state", "alive") != "defeated" and node.get("side", "own") == "own":
            return True
        return any(_names_alive(v, name) for v in node.values())
    if isinstance(node, list):
        return any(_names_alive(v, name) for v in node)
    return False


def _mentions_defeated(node, name: str) -> bool:
    if isinstance(node, dict):
        if node.get("name") == name and node.get("state") == "defeated":
            return True
        return any(_mentions_defeated(v, name) for v in node.values())
    if isinstance(node, list):
        return any(_mentions_defeated(v, name) for v in node)
    return False


def dependent_points(ops, name: str) -> float:
    """Points of the ops that only work with `name` on the board."""
    total = 0.0
    for op in ops:
        kind = op.get("op")
        if kind == "if":
            cond = op.get("condition")
            if _mentions_defeated(cond, name):
                continue                    # revive-or-place: the fighter being down is the case it handles
            if _names_alive(cond, name):
                total += op_points(op)
            else:
                total += dependent_points(op.get("then") or (), name) + dependent_points(op.get("else") or (), name)
        elif kind in ("optional", "for_each"):
            total += dependent_points(op.get("ops") or (), name)
        elif kind == "choose_effect":
            total += max((dependent_points(o.get("ops") or (), name) for o in op.get("options") or ()), default=0.0)
        elif kind in ("heal", "place", "move", "swap", "redirect_damage", "set_hp") and (
                _names_alive(op.get("target"), name) or _names_alive(op.get("to"), name)):
            total += op_points(op)
    return total


def card_dependency(effects: dict, name: str) -> float:
    return sum(MOMENT_FACTOR[m] * dependent_points(effects.get(m) or (), name) for m in MOMENT_FACTOR)


def passive_dependency(passive: dict, name: str) -> float:
    if not (_names_alive(passive.get("condition"), name) or _names_alive(passive.get("to"), name)):
        return 0.0
    return PASSIVE_VALUE


def trigger_dependency(trigger: dict, name: str) -> float:
    if _names_alive(trigger.get("condition"), name):
        return ops_points(trigger.get("ops") or ())
    return dependent_points(trigger.get("ops") or (), name)


# ---------------------------------------------------------------- the profile
def _round(x: float) -> float:
    return round(x + 0.0, 2)


def derive_role(hero: bool, ranged: bool, max_hp: int) -> str:
    if hero:
        return "hero"
    return "striker" if ranged or max_hp >= STRIKER_MIN_HP else "keep_away"


def attack_summary(cards: list[dict], name: str) -> dict:
    values = [c["value"] for c in cards if c["type"] in ("attack", "versatile") and c["fighter"] in (name, "any")]
    return {"cards": len(values), "mean": _round(sum(values) / len(values)) if values else 0.0,
            "max": max(values, default=0)}


def compute_ai_profile(hero: dict, effects: dict | None = None, roles: dict | None = None) -> dict:
    """The `ai_profile` of a generated HeroDef (a dict as `tools/import_hero.build` assembles it, before parsing).
    `effects`: the hero's DSL file (`data/heroes/effects/<slug>.json`), None when it has none yet: then only the
    cards' restrictions and values count. `roles`: the overlay's `ai_role`."""
    roles = roles or {}
    cards = (hero.get("deck") or {}).get("cards") or []
    by_title = {c["title"]: c for c in (effects or {}).get("cards", ())}
    ability = (effects or {}).get("ability") or {}
    groups = [(hero["fid"], hero["name"], True, 1, hero["hp"], hero["move"], hero["attack"] == "range")]
    groups += [(s["fid"], s["name"], False, s["count"], s["hp"], s["move"], s["attack"] == "range")
               for s in hero.get("sidekicks", ())]
    profile = {}
    for fid, name, is_hero, count, hp, move, ranged in groups:
        role = roles.get(fid) or derive_role(is_hero, ranged, hp)
        if role not in ROLES:
            raise ValueError(f"{hero['slug']}: ai_role {role!r} of {fid} is not one of {ROLES}")
        exclusive, seen = [], set()
        for c in cards:
            if c["fighter"] != name or c["title"] in seen:
                continue
            seen.add(c["title"])
            copies = sum(1 for x in cards if x["title"] == c["title"])
            fx = (by_title.get(c["title"]) or {}).get("effects") or {}
            exclusive.append({"title": c["title"], "type": c["type"], "copies": copies,
                              "impact": _round(max(0.0, DEAD_CARD + COMBAT_PER_POINT * (c["value"] or 0) + moment_points(fx)))})
        entry = {"name": name, "hero": is_hero, "count": count, "max_hp": hp, "move": move, "ranged": ranged,
                 "role": role, "attack": attack_summary(cards, name), "exclusive": exclusive}
        if not is_hero:
            entry["requires_alive"] = _requires_alive(cards, by_title, ability, name)
        profile[fid] = entry
    return profile


def _requires_alive(cards: list[dict], by_title: dict, ability: dict, name: str) -> list[dict]:
    out = []
    for p in ability.get("passives") or ():
        pts = passive_dependency(p, name)
        if pts:
            out.append({"source": f"ability:{p.get('id', 'passive')}", "kind": "ability", "copies": 1,
                        "impact": _round(pts)})
    for t in ability.get("triggers") or ():
        pts = trigger_dependency(t, name)
        if pts:
            out.append({"source": f"ability:{t.get('id', 'trigger')}", "kind": "ability", "copies": 1,
                        "impact": _round(pts)})
    done = set()
    for c in cards:
        if c["fighter"] == name or c["title"] in done:
            continue
        done.add(c["title"])
        fx = (by_title.get(c["title"]) or {}).get("effects") or {}
        pts = card_dependency(fx, name)
        if pts:
            out.append({"source": c["title"], "kind": "card", "copies": sum(1 for x in cards if x["title"] == c["title"]),
                        "impact": _round(pts)})
    return out
