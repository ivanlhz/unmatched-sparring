"""What the rival hero's own abilities cost the bot's fighters, read from the effects data (no hero is named here).

Two things the heuristic's `Model` and the search's evaluation both need:
  * `zone_hazard` / `zone_damage`: expected damage per start of the rival's turn to one of my fighters standing in the rival
    hero's zone (Medusa's gaze, Liz Sherman's wildfire, She-Hulk's throw): every start_of_turn trigger of the rival hero that
    deals damage to a fighter `zone_of: hero`. An `if` on a card tag is weighted by the share of the rival's unplayed cards
    with that tag; any other condition counts half. A damage that needs a card of the rival's deck or hand is nothing when
    that zone is empty. `zone_cover_factor` discounts its hit points for a fighter that holds defenses.
  * `attack_harm`: what a played attack card does to the defender besides its value (forced discards, damage to my fighters,
    statuses, movement of my fighters): what a cancel-effects defense card prevents.
"""
from __future__ import annotations

from functools import lru_cache

from .effects.model import load_effects
from .effects.modifiers import card_effects

_ZONE_SIDES = ("enemy", "any")
ZONE_COVER_RELIEF = 0.5     # most the zone damage's hit points are discounted, for a fighter whose two best defenses stop the rival hero's whole expected blow
OTHER_CONDITION = 0.5       # an `if` the model cannot price: half the time
STATUS_HARM = 0.5           # a status on the defender (cannot gain actions, cannot leave its space...)
MOVE_HARM = 0.3             # one of the defender's fighters is pushed / placed by the card
ANY_SIDE_SHARE = 0.5        # damage to a fighter of "any" side: see `_harm_walk`
UNREAD_OPTION_HARM = 0.5    # an option the defender may pick whose ops cannot be read (a plugin: mill 4 cards of its deck)
# What one forced discard and one point of damage cost the defender, to compare the branches of a choice it makes. They are the
# heuristic's CARD_VALUE and W_MEDUSA_HP (ai_medusa imports this module, so they are repeated here; a test pins them equal).
# The hero's price per point is used whoever is hit: a sidekick's price and a lethal blow depend on the target, unknown per card.
DISCARD_COST = 0.4
DAMAGE_COST = 1.2
HARM_KINDS = ("discard", "damage", "direct")
_COST = dict(zip(HARM_KINDS, (DISCARD_COST, DAMAGE_COST, 1.0)))


def _bound_zone(op) -> str | None:
    """The zone of the rival's that the card an op binds (`as`) comes from: a discard names it; a plugin that binds a card asks
    the owner for one of its hand (the only such start-of-turn plugin is a discard from the hand: She-Hulk's throw)."""
    if op.get("op") == "discard" and isinstance(op.get("cards"), dict) and op["cards"].get("player") == "owner":
        return op["cards"].get("zone")
    if op.get("op") == "plugin" and (op.get("args") or {}).get("as"):
        return "hand"
    return None


def _ref(value) -> str | None:
    return value[1:] if isinstance(value, str) and value.startswith("$") else None


def _collect(ops, tag, flat, source, bound: dict, out: list) -> None:
    for op in ops or ():
        kind = op.get("op")
        name = op.get("as") or (op.get("args") or {}).get("as")
        if name and _bound_zone(op):
            bound[name] = _bound_zone(op)
        if kind == "damage":
            target = op.get("target")
            if isinstance(target, dict) and target.get("side") in _ZONE_SIDES and (target.get("where") or {}).get("zone_of") == "hero":
                amount = op.get("amount")
                fed_by = bound.get(_ref(amount.get("of"))) if isinstance(amount, dict) else None
                out.append((amount, tag, flat, fed_by or source))
        elif kind == "optional":
            _collect(op.get("ops"), tag, flat, source, bound, out)
        elif kind == "if":
            cond = op.get("condition") or {}
            if cond.get("test") == "card":
                wanted = (cond.get("filter") or {}).get("tag")
                _collect(op.get("then"), wanted or tag, flat, bound.get(_ref(cond.get("card"))) or source, bound, out)
            else:
                _collect(op.get("then"), tag, flat * OTHER_CONDITION, source, bound, out)


@lru_cache(maxsize=None)
def zone_hazards(slug: str) -> tuple:
    """(amount spec, card tag or None, flat chance, zone of the rival's that the deciding card comes from or None) of each
    start-of-turn damage to a fighter in the hero's zone."""
    try:
        triggers = load_effects(slug).triggers
    except Exception:
        return ()
    out: list = []
    for t in triggers:
        when = t.get("when") or {}
        if when.get("event") == "start_of_turn" and when.get("player") == "owner":
            _collect(t.get("ops"), None, 1.0, None, {}, out)
    return tuple(out)


def zone_hazard(game, rival: int) -> tuple[float, float]:
    """(expected damage, cards it pays from its hand) of `rival`'s start-of-turn ability per turn on the fighter it picks in its
    hero's zone. A damage decided by a card of its deck (Liz Sherman's wildfire) needs a deck; one fed by a card of its hand
    (She-Hulk's throw) needs a hand and costs it that card. The hidden card is any of its unplayed ones (public: its set minus
    what is gone), so all that is read of the two zones is whether they are empty."""
    hero = game.hero(rival)
    if not hero.alive:
        return 0.0, 0.0
    st = game.players[rival]
    pool = None
    damage = paid = 0.0
    for amount, tag, flat, source in zone_hazards(st.hero.slug):
        if source is not None and not getattr(st, source, None):
            continue                              # no card left where the ability takes it from: nothing is dealt
        chance = flat
        if tag is not None or isinstance(amount, dict):
            if pool is None:
                pool = [c for c in st.full_set if c not in st.gone]
            if not pool:
                continue
        if tag is not None:
            chance *= sum(1 for c in pool if tag in c.tags) / len(pool)
        if isinstance(amount, dict):
            amount = sum(c.boost for c in pool) / len(pool)
        damage += chance * (amount or 0)
        if source == "hand":
            paid += chance
    return damage, paid


def zone_damage(game, rival: int) -> float:
    """Expected damage of `rival`'s start-of-turn ability per turn to the fighter it picks in its hero's zone (0 if none)."""
    return zone_hazard(game, rival)[0]


def zone_cover_factor(defenses, blow: float) -> float:
    """Share of the zone damage's hit points still charged to a fighter that holds the defense values `defenses` (the cards
    of the hand it may defend with), against a rival hero whose attack is expected to be worth `blow`. Standing in that zone is
    also standing where the rival strikes, so the two best defenses count, each for the part of the blow it stops:
    cover = sum(min(d, blow)) / (2 * blow), and the factor is 1 - ZONE_COVER_RELIEF * cover (1.0 with no defense, never below
    1 - ZONE_COVER_RELIEF). It never applies to the lethal part: no card stops the damage itself."""
    best = sorted(defenses, reverse=True)[:2]
    cover = sum(min(d, blow) / blow if blow > 0 else 1.0 for d in best) / 2
    return 1 - ZONE_COVER_RELIEF * min(1.0, cover)


def _branch_cost(parts: list) -> float:
    return sum(_COST[kind] * v for kind, v in parts)


def _harm_walk(ops, scale: float, parts: list) -> None:
    for op in ops or ():
        kind = op.get("op")
        target = op.get("target")
        side = target.get("side") if isinstance(target, dict) else target      # "opposing" / "hero" ... may be a bare string
        foe_target = side in ("enemy", "opponent", "opposing")
        cards = op.get("cards")
        if kind == "discard" and isinstance(cards, dict):
            if cards.get("player") == "opponent" and cards.get("zone") == "hand":
                parts.append(("discard", scale * (cards.get("amount") or 1)))
        elif kind == "discard":
            # `cards` is a reference ("$memory": a card an earlier op chose, Baba Yaga's Remove A Painful Memory) that cannot be
            # resolved statically: its owner is unknown, so count one discard at half weight instead of reading it as a filter
            parts.append(("discard", scale * OTHER_CONDITION))
        elif kind == "damage" and isinstance(op.get("amount"), (int, float)) and (foe_target or side == "any"):
            # "any" side (Iron Teeth, Savagery, Ricochet: a fighter next to the attacker's hero or in the defender's zone): the
            # attacker aims it at one of mine when one qualifies. The defender usually does (melee, its own zone) but not always
            # (a ranged attacker, a sidekick striking far from its hero), and where they stand is not known per card: half
            parts.append(("damage", scale * op["amount"] * (1.0 if foe_target else ANY_SIDE_SHARE)))
        elif kind == "status" and (op.get("player") == "opponent" or foe_target):
            parts.append(("direct", scale * STATUS_HARM))
        elif kind in ("move", "place") and foe_target:
            parts.append(("direct", scale * MOVE_HARM))
        elif kind == "optional":
            doing, declining = [], []
            _harm_walk(op.get("ops"), scale, doing)
            _harm_walk(op.get("else"), scale, declining)
            if op.get("chooser") == "opponent":      # the defender picks: it takes the branch that costs it less
                parts.extend(min(doing, declining, key=_branch_cost))
            else:
                parts.extend(doing)
                parts.extend(declining)
        elif kind == "choose_effect":
            options = []
            for option in op.get("options") or ():
                branch: list = []
                _harm_walk(option.get("ops"), scale, branch)
                options.append((branch, any(o.get("op") == "plugin" for o in option.get("ops") or ())))
            if not options:
                continue
            take = op.get("amount") or 1
            if op.get("chooser") == "opponent":
                # the defender picks (Merigold's Hailstorm, Legalese won): its cheapest options. Every option of such a choice is
                # a price it pays, so one that reads as nothing only because a plugin does it is not free
                priced = [b or ([("direct", scale * UNREAD_OPTION_HARM)] if unread else b) for b, unread in options]
                for branch in sorted(priced, key=_branch_cost)[:take]:
                    parts.extend(branch)
            else:
                # the attacker picks what suits it, which is not known per card: the average option
                parts.extend((k, v * take / len(options)) for branch, _ in options for k, v in branch)
        elif kind == "if":
            _harm_walk(op.get("then"), scale * OTHER_CONDITION, parts)
            _harm_walk(op.get("else"), scale * OTHER_CONDITION, parts)


def ops_harm(moments) -> tuple:
    """(discards, damage, direct) that the ops of the given moments do to the opponent of whoever plays them."""
    parts: list = []
    for ops in moments:
        _harm_walk(ops, 1.0, parts)
    return tuple(sum(v for k, v in parts if k == kind) for kind in HARM_KINDS)


_HARM_CACHE: dict = {}


def attack_harm(card) -> tuple:
    """Harm a card does to its opponent besides its value, as (discards, damage, direct) in expected units (read from the
    effects data; an `if` halves what is under it). All zeros for a card without effects."""
    if card.title not in _HARM_CACHE:
        fx = card_effects(card)
        _HARM_CACHE[card.title] = ops_harm([fx.moments.get(m) for m in ("immediately", "during", "after")] if fx else ())
    return _HARM_CACHE[card.title]
