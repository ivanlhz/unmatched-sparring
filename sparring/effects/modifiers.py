"""Statuses and rule modifiers of the DSL (docs/effects-dsl.md section 3, "Statuses" and "Modifiers").

Two stores live in `Game.fx`:
- `fx.statuses`: what the `status` op creates, each with an `until` event. Entry: {name, fid | player, amount,
  until, owner, label}.
- `fx.modifiers`: loose continuous effects, written by `add_modifier` and removed with `remove_modifiers`. The
  modifiers of an ONGOING card in play are not copied here: `_modifier_entries` reads them from the card (C3). Entry: {kind, owner, card_id, ...spec}; a modifier of kind "status" is
  read exactly like a status.

The `EffectState` hooks call the functions below with the EffectState (no game), so they only look at fighter ids,
player numbers and `fx.acting` (the player whose effect op is running; None = an effect of the legacy engine path,
which is always the other player's when the hero of the status is in `dsl_heroes`)."""
from __future__ import annotations

from functools import lru_cache

from .model import EFFECTS_DIR, CardEffects, EffectError, load_effects, walk_ops

FIGHTER_STATUSES = ("immune_to_effect_damage", "cannot_leave_space", "attack_bonus")
PLAYER_STATUSES = ("immune_to_enemy_effect_damage", "immune_to_enemy_effect_moves",
                   "immune_to_enemy_forced_discards", "cannot_gain_actions", "cannot_draw", "next_attack_bonus")
_DEFAULT_PLAYER = {"end_of_turn": "any", "start_of_turn": "owner", "after_maneuver": "any"}


# ---------------------------------------------------------------- card data by title

@lru_cache(maxsize=None)
def _cards_by_title() -> dict[str, CardEffects]:
    """Card title -> its effects, over every hero with an effects file. Titles shared by several heroes (B.P.R.D.
    Training) carry the same flags; tests/test_effects_combat.py checks that, because combat code only has the Card
    and a Card knows its title, not the hero's slug."""
    out: dict[str, CardEffects] = {}
    for path in sorted(EFFECTS_DIR.glob("*.json")):
        if path.stem != "schema":
            out.update({t: c for t, c in load_effects(path.stem).cards.items() if t not in out})
    return out


def card_effects(card) -> CardEffects | None:
    return _cards_by_title().get(card.title)


def may_boost(card) -> bool:
    """The card lets its owner BOOST it for free in DURING COMBAT (data `may_boost`), attacking or defending."""
    fx = card_effects(card)
    return fx is not None and fx.may_boost


@lru_cache(maxsize=None)
def _deck_boost_titles() -> frozenset[str]:
    return frozenset(
        title for title, fx in _cards_by_title().items()
        if any(o["op"] == "discard" and isinstance(o.get("cards"), dict) and o["cards"].get("zone") == "deck"
               and o["cards"].get("pick") == "bottom" for o in walk_ops(fx.moments.get("during", []))))


def draws_bottom_for_boost(card) -> bool:
    """Flame Lash: the BOOST is the bottom card of the deck, discarded by the card's own DURING ops."""
    return card.title in _deck_boost_titles()


def is_uncancelable(card) -> bool:
    fx = card_effects(card)
    return fx is not None and fx.uncancelable


# ---------------------------------------------------------------- stores

def add_status(fx, name: str, *, owner: int, until: dict, fid: str | None = None, player: int | None = None,
               amount: int = 0, label: str = "") -> dict:
    if name not in FIGHTER_STATUSES + PLAYER_STATUSES:
        raise EffectError(f"unknown status {name!r}")
    if (fid is None) == (player is None):
        raise EffectError(f"status {name}: exactly one of fighter or player")
    st = {"name": name, "owner": owner, "until": dict(until), "amount": amount, "label": label}
    st["fid" if fid is not None else "player"] = fid if fid is not None else player
    fx.statuses.append(st)
    return st


def add_modifier(fx, owner: int, card_id: int, spec: dict) -> None:
    """An ONGOING card's modifier enters play. Player selectors of a status are resolved now (owner / opponent)."""
    entry = {**spec, "owner": owner, "card_id": card_id}
    if spec["kind"] == "status":
        if "player" not in spec:
            raise EffectError("status modifier: only player-scoped statuses are supported")
        entry["player"] = {"owner": owner, "opponent": 1 - owner}[spec["player"]]
    fx.modifiers.append(entry)


def remove_modifiers(fx, card_id: int) -> None:
    fx.modifiers[:] = [m for m in fx.modifiers if m.get("card_id") != card_id]


def _modifier_entries(fx):
    """`fx.modifiers` plus the modifiers of the ONGOING cards in play (C3 reads those from the card, it does not copy
    them into `fx.modifiers`), in the same shape `add_modifier` writes."""
    yield from fx.modifiers
    if fx._game_ref is None or not any(fx.card_slots()):
        return
    from .ongoing import active_modifiers
    game = fx.game()
    for owner, spec in active_modifiers(game):
        entry = {**spec, "owner": owner, "card_id": fx.ongoing_card_id(owner)}
        if spec["kind"] == "status":
            entry["player"] = {"owner": owner, "opponent": 1 - owner}[spec.get("player", "owner")]
        yield entry


def _status_entries(fx, name: str):
    for st in fx.statuses:
        if st["name"] == name:
            yield st
    for m in _modifier_entries(fx):
        if m["kind"] == "status" and m["name"] == name:
            yield m


def _fighter_has(fx, name: str, fid: str) -> bool:
    return any(st.get("fid") == fid for st in _status_entries(fx, name))


def _player_has(fx, name: str, player: int) -> bool:
    return any(st.get("player") == player for st in _status_entries(fx, name))


def _rule_amounts(fx, rule: str) -> list[int]:
    return [m.get("amount", 0) for m in _modifier_entries(fx) if m["kind"] == "rule" and m["rule"] == rule]


def _is_enemy_source(fx, owner_of_target: int) -> bool:
    """Effects of the legacy path (`acting` None) come from the player who is not a DSL hero: the enemy."""
    return fx.acting is None or fx.acting != owner_of_target


# ---------------------------------------------------------------- hooks

def adjust_damage(fx, fighter, n, source):
    """Effect damage only (never combat, exhaustion or set_hp): immunities first, then the +N rule."""
    if source != "effect":
        return n
    if _fighter_has(fx, "immune_to_effect_damage", fighter.fid):
        return 0
    if _is_enemy_source(fx, fighter.owner) and _player_has(fx, "immune_to_enemy_effect_damage", fighter.owner):
        return 0
    return n + sum(_rule_amounts(fx, "effect_damage_bonus"))


def can_draw(fx, player: int) -> bool:
    return not _player_has(fx, "cannot_draw", player)


def can_gain_actions(fx, player: int) -> bool:
    return not _player_has(fx, "cannot_gain_actions", player) and not _rule_amounts(fx, "no_gain_actions")


def can_force_discard(fx, player: int, source_player: int) -> bool:
    return source_player == player or not _player_has(fx, "immune_to_enemy_forced_discards", player)


def can_move(fx, fighter) -> bool:
    if _fighter_has(fx, "cannot_leave_space", fighter.fid):
        return False
    return not (fx.acting is not None and fx.acting != fighter.owner
                and _player_has(fx, "immune_to_enemy_effect_moves", fighter.owner))


def take_next_attack_bonus(fx, player: int) -> list[tuple[int, str]]:
    """The first attack of `player` this turn consumes their `next_attack_bonus` statuses: (+n, label) each."""
    got = [st for st in fx.statuses if st["name"] == "next_attack_bonus" and st.get("player") == player]
    fx.statuses[:] = [st for st in fx.statuses if st not in got]
    return [(st["amount"], st["label"]) for st in got if st["amount"]]


def fighter_attack_bonus(fx, fid: str) -> list[tuple[int, str]]:
    """(+n, label) of each `attack_bonus` status on the fighter: every attack it makes while the status lasts
    (Nunchaku), unlike `next_attack_bonus`, which the first attack consumes."""
    return [(st["amount"], st["label"]) for st in fx.statuses
            if st["name"] == "attack_bonus" and st.get("fid") == fid and st["amount"]]


def expire_on_event(fx, name: str, *args) -> None:
    """Drops the statuses whose `until` is this event. Other events (damage_taken for the Pacts...) belong to C3."""
    player = args[0] if args and isinstance(args[0], int) else None

    def over(st) -> bool:
        until = st["until"]
        if until.get("event") != name:
            return False
        sel = until.get("player", _DEFAULT_PLAYER.get(name, "any"))
        wanted = {"any": player, "owner": st["owner"], "opponent": 1 - st["owner"]}.get(sel, sel)
        return wanted == player
    fx.statuses[:] = [st for st in fx.statuses if not over(st)]


# ---------------------------------------------------------------- combat values

def side_of(flow, card) -> str | None:
    if card == flow.atk_card:           # by value: two decks can share a CardID, never a whole card
        return "atk"
    if flow.def_card is not None and card == flow.def_card:
        return "def"
    return None


COMBAT_MOMENTS = ("immediately", "during", "after")


def has_effects(game, flow, side: str, moments=None) -> bool:
    """The card on `side` has effects in `moments` (default: the three combat ones) that a cancellation would remove:
    ops in those moments or the free BOOST of a `may_boost` card (a DURING effect). A hero outside the interpreter
    has only the card's text to say."""
    card = flow.atk_card if side == "atk" else flow.def_card
    if card is None:
        return False
    owner = flow.att.owner if side == "atk" else flow.tgt.owner
    slug = game.players[owner].hero.slug
    if slug not in game.fx.dsl_heroes:
        return bool(card.text.strip())
    fx = load_effects(slug).cards.get(card.title)
    names = tuple(moments or COMBAT_MOMENTS)
    return fx is not None and (any(fx.moments.get(m) for m in names) or ("during" in names and fx.may_boost))


def effects_canceled(game, run, ref) -> bool:
    """`effects_canceled` test: a cancellation of this combat really took an effect off the card `ref` names."""
    from .select import card_ref
    flow = getattr(run, "flow", None)
    if flow is None:
        return False
    cards = card_ref(game, run, ref)
    side = side_of(flow, cards[0]) if cards else None
    return side is not None and side in flow.cancel_hits


def printed_value(flow, side: str) -> int:
    card = flow.atk_card if side == "atk" else flow.def_card
    return flow.printed_set.get(side, card.value or 0)


def add_value(flow, side: str, n: int, label: str, record: bool = True) -> int:
    """Adds `n` to the running value of one side (never below 0). Returns the change actually applied. `record`: list
    it as a modifier of the side (the announcement); a change of the printed value is not one."""
    ctx = flow.ctx
    now = ctx.atk_value if side == "atk" else ctx.def_value
    new = max(0, now + n)        # Ivan (28/10): never below 0 at every step, in timing order
    if side == "atk":
        ctx.atk_value = new
    else:
        ctx.def_value = new
    if new != now and record:
        flow.mods[side].append([new - now, label])
        if side == "atk":
            flow.result.atk_parts.append(f"{label} ({new - now:+d})")
    return new - now


def set_value(flow, side: str, n: int, label: str, ignore: bool) -> None:
    """`ignore`: "ignore this card's value" - the whole value goes to 0, bonuses included (Incinerate). Otherwise "the
    value becomes N" replaces the PRINTED value and leaves bonuses and extras alone (On Earth, Shock And Awe)."""
    if ignore:
        total = flow.ctx.atk_value if side == "atk" else flow.ctx.def_value
        flow.printed_set[side] = 0
        add_value(flow, side, -total, label)
        return
    before = printed_value(flow, side)
    flow.printed_set[side] = n
    add_value(flow, side, n - before, label, record=False)
    if side == "atk":
        flow.result.atk_parts[0] = f"{flow.atk_card.title} ({n})"


# ---------------------------------------------------------------- redirected damage

def redirect_sources(game, fighter) -> list[dict]:
    """Redirections that may divert damage aimed at `fighter`: the hero's passives and ONGOING modifiers."""
    owner, out = fighter.owner, []
    slug = game.players[owner].hero.slug
    if slug in game.fx.dsl_heroes:
        out += [{**p, "owner": owner} for p in load_effects(slug).passives if p["kind"] == "redirect_damage"]
    out += [m for m in game.fx.modifiers if m["kind"] == "redirect_damage" and m["owner"] == owner]
    return out


def _owner_run(game, owner: int):
    from .run import Ctx, EffectRun
    return EffectRun([], Ctx(owner=owner, this_fid=game.hero(owner).fid))


def combat_redirect_target(flow):
    """Who takes the combat damage: the redirection a `redirect_damage` op registered for this combat (Bound In
    Blood), or the defender. The condition is checked now, when the damage is dealt."""
    from .select import condition, fighter_candidates
    game = flow.game
    for r in flow.redirects:
        if r["from"] != flow.tgt.fid or r["damage"] not in ("combat", "any"):
            continue
        view = _owner_run(game, r["owner"])
        if r.get("condition") and not condition(game, view, r["condition"]):
            continue
        dests = [f for f in fighter_candidates(game, view, r["to"])[0] if f.fid != flow.tgt.fid]
        if dests:
            if r.get("optional"):
                raise NotImplementedError("optional combat redirect: E1 (needs a pause inside the DAMAGE phase)")
            return dests[0]
    return flow.tgt


def redirect_target(game, fighter, kind: str):
    """(target, source) when a redirection of this damage `kind` applies to `fighter` and has somewhere to go;
    otherwise (None, None). Asking the optional ones is the caller's job."""
    from .select import condition, fighter_candidates
    for src in redirect_sources(game, fighter):
        if src["damage"] not in (kind, "any"):
            continue
        view = _owner_run(game, src["owner"])
        if fighter not in fighter_candidates(game, view, src["from"])[0]:
            continue
        if "condition" in src and not condition(game, view, src["condition"]):
            continue
        dests = [f for f in fighter_candidates(game, view, src["to"])[0] if f is not fighter]
        if dests:
            return dests[0], src
    return None, None
