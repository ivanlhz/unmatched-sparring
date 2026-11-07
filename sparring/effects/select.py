"""Selectors, amounts and conditions of the DSL (docs/effects-dsl.md sections 2.1-2.9).

Everything takes `(game, run, ...)`; `run` supplies the context (`run.ctx`), the bindings (`$name`) and `run.ask`
for the decisions. Nothing here mutates the game."""
from __future__ import annotations

from typing import NamedTuple

from .model import EffectError

SIDES = {"own", "enemy", "any"}


class Picked(NamedTuple):
    player: int
    zone: str
    card: object


# ---------------------------------------------------------------- players

def players_of(game, run, sel) -> list[int]:
    """PlayerSel -> player numbers (`all` is owner first)."""
    ctx, owner = run.ctx, run.ctx.owner
    if sel == "owner":
        return [owner]
    if sel == "opponent":
        return [1 - owner]
    if sel == "all":
        return [owner, 1 - owner]
    if sel in ("attacking_player", "defending_player"):
        fid = ctx.attacker_fid if sel == "attacking_player" else ctx.defender_fid
        if fid is None:
            raise EffectError(f"{sel}: this effect has no combat")
        return [game.fighters[fid].owner]
    if isinstance(sel, str) and sel.startswith("$"):
        return run.bound(sel[1:], "players")
    raise EffectError(f"bad player selector {sel!r}")


def player_of(game, run, sel) -> int:
    got = players_of(game, run, sel)
    if len(got) != 1:
        raise EffectError(f"player selector {sel!r} must be a single player")
    return got[0]


# ---------------------------------------------------------------- spaces

def _ref_fighter(game, run, ref):
    """FighterRef (a role name or $var) -> one Fighter or None."""
    got = _role_fighters(game, run, ref)
    return got[0] if got else None


def space_options(game, run, sel, default_empty: bool = True, mover=None) -> list[int]:
    """SpaceSel -> sorted space ids. `empty` (default true for placing) drops spaces held by a living fighter
    other than `mover`."""
    board = game.board
    out = set(board.spaces)
    for key in ("zone_of", "no_zone_of", "adjacent_to", "space_of", "nearest_to"):
        if key not in sel:
            continue
        ref = _ref_fighter(game, run, sel[key])
        if ref is None or ref.pos is None:
            return []
        if key == "zone_of":
            out &= {s for s in board.spaces if board.share_zone(ref.pos, s)}
        elif key == "no_zone_of":                          # shares no zone with the fighter's space (Tactical Retreat)
            out -= {s for s in board.spaces if board.share_zone(ref.pos, s)}
        elif key == "adjacent_to":
            out &= set(board.adj[ref.pos])
        elif key == "space_of":
            out &= {ref.pos}
    if "start_space_of" in sel:
        out &= {game.start_spaces[player_of(game, run, sel["start_space_of"])]}
    if sel.get("start"):                                   # any starting space of the board
        out &= set(game.board.starts.values())
    if sel.get("empty", default_empty):
        taken = {f.pos for f in game.fighters.values() if f.alive and f is not mover}
        out -= taken
    if sel.get("other") and mover is not None:
        out.discard(mover.pos)
    if "nearest_to" in sel and out:
        ref = _ref_fighter(game, run, sel["nearest_to"])
        best = min(board.span(ref.pos, s) for s in out)        # span, like nearest_free: "nearest" is spatial, not the walk
        out = {s for s in out if board.span(ref.pos, s) == best}
    return sorted(out)


# ---------------------------------------------------------------- fighters

def _role_fighters(game, run, role) -> list:
    ctx = run.ctx
    if role == "this":
        return [game.fighters[ctx.this_fid]] if ctx.this_fid else []
    if role == "hero":
        return [game.hero(ctx.owner)]
    if role in ("attacker", "defender"):
        fid = ctx.attacker_fid if role == "attacker" else ctx.defender_fid
        return [game.fighters[fid]] if fid else []
    if role == "opposing":
        if ctx.attacker_fid is None or ctx.this_fid is None:
            return []
        other = ctx.defender_fid if ctx.this_fid == ctx.attacker_fid else ctx.attacker_fid
        return [game.fighters[other]] if other else []
    if role == "combatant":
        return [game.fighters[f] for f in (ctx.attacker_fid, ctx.defender_fid) if f]
    if isinstance(role, str) and role.startswith("$"):
        return [game.fighters[f] for f in run.bound(role[1:], "fighters")]
    raise EffectError(f"bad fighter role {role!r}")


def defeated(game, f) -> bool:
    """Dead on the board, as opposed to waiting in the reserve: it fell somewhere (`died_at`) or it is a fighter that
    starts on the board and so was never in reserve (a Harpy dead in a save from before `died_at` existed)."""
    if f.alive:
        return False
    if f.died_at is not None:
        return True
    return any(spec.on_board for spec in game.players[f.owner].hero.fighters() if spec.fid == f.fid)


def fighter_candidates(game, run, sel) -> tuple[list, bool]:
    """FighterSel -> (candidates in engine order, pick_all)."""
    if isinstance(sel, str):
        sel = {"role": sel}
    owner = run.ctx.owner
    pool = _role_fighters(game, run, sel["role"]) if "role" in sel else list(game.fighters.values())
    side = sel.get("side", "any")
    if side not in SIDES:
        raise EffectError(f"bad side {side!r}")
    kind, name = sel.get("kind", "any"), sel.get("name")
    want_alive = sel.get("state", "alive") == "alive"      # "defeated" = dead on the board; reserve is neither
    out = []
    for f in pool:
        if side == "own" and f.owner != owner or side == "enemy" and f.owner == owner:
            continue
        if kind == "hero" and not f.hero or kind == "sidekick" and f.hero:
            continue
        if name is not None and f.name != name:
            continue
        if want_alive != f.alive or (not want_alive and not defeated(game, f)):
            continue
        out.append(f)
    if "where" in sel:
        where = sel["where"]
        spaces = set(space_options(game, run, where, default_empty=False))
        out = [f for f in out if f.pos in spaces]
        if "nearest_to" in where and out:
            ref = _ref_fighter(game, run, where["nearest_to"])
            best = min(game.board.span(ref.pos, f.pos) for f in out)       # span: "nearest" is spatial, not the walk
            out = [f for f in out if game.board.span(ref.pos, f.pos) == best]
        if sel.get("other"):
            for key in ("zone_of", "adjacent_to", "space_of", "nearest_to"):
                if key in where:
                    ref = _ref_fighter(game, run, where[key])
                    out = [f for f in out if f is not ref]
    if sel.get("other") and run.ctx.this_fid:
        out = [f for f in out if f.fid != run.ctx.this_fid]
    flt = sel.get("filter") or {}
    if "attacked_this_turn" in flt:
        attacked = run.flags.get("attacked", game.fx.attacked)       # an end-of-turn run keeps the turn it belongs to
        out = [f for f in out if (f.fid in attacked) == bool(flt["attacked_this_turn"])]
    if "passed_by" in flt:
        out = _passed_by(game, run, out, flt["passed_by"])
    if "is_or_adjacent_to" in flt:     # the fighter itself or one next to it ("Dr. Strange or a friendly fighter adjacent to him")
        anchor = _ref_fighter(game, run, flt["is_or_adjacent_to"])
        adj = game.board.adj
        out = [f for f in out if anchor is not None and anchor.pos is not None and f.pos is not None
               and (f is anchor or f.pos in adj[anchor.pos])]
    if "adjacent_to_any" in flt:       # next to at least one other living fighter the selector designates
        others = fighter_candidates(game, run, flt["adjacent_to_any"])[0]
        adj = game.board.adj
        out = [f for f in out if f.pos is not None and any(o is not f and o.pos is not None and o.pos in adj[f.pos]
                                                           for o in others)]
    return out, sel.get("pick", "one") == "all"


def _path_unknown(game, run, sel) -> bool:
    """True if `sel` filters by `passed_by` and a mover's path is one the engine did not see (moved by hand)."""
    ref = (sel.get("filter") or {}).get("passed_by") if isinstance(sel, dict) else None
    if ref is None:
        return False
    passed = run.flags.get("passed") or {}
    return any(passed.get(mover.fid, []) is None for mover in _role_fighters(game, run, ref))


def _passed_by(game, run, fighters: list, ref) -> list:
    """The fighters a moved fighter passed through (`move` records them in `run.flags["passed"]`). `None` is a move
    the engine did not see (the human moved their miniature by hand): every candidate stays, the human answers."""
    passed = run.flags.get("passed") or {}
    keep: set[str] | None = set()
    for mover in _role_fighters(game, run, ref):
        seen = passed.get(mover.fid, [])
        if seen is None:
            return fighters
        keep |= set(seen)
    return [f for f in fighters if f.fid in keep]


def _near(game, run, sel) -> str | None:
    """The fighter a selector says "adjacent to" (its id), for the prompt of the choice."""
    where = sel.get("where") if isinstance(sel, dict) else None
    if not isinstance(where, dict) or "adjacent_to" not in where:
        return None
    ref = _ref_fighter(game, run, where["adjacent_to"])
    return None if ref is None or ref is game.hero(run.ctx.owner) else ref.fid       # the owner's hero keeps the generic prompt


def pick_fighters(game, run, sel, chooser: int, prompt: str = "", **extra) -> list:
    """The fighters a selector designates. `pick: one` with several candidates asks `chooser`; with none it is
    empty (the op does nothing); `pick: all` returns every candidate (zero is fine). `extra` (the op name, its
    amount...) travels in the request so a bot can score the candidates for what is about to happen to them."""
    cands, pick_all = fighter_candidates(game, run, sel)
    unknown = _path_unknown(game, run, sel)          # moved by hand: the human may also answer "nobody was passed"
    if pick_all or not cands or (len(cands) == 1 and not unknown):
        return cands
    near = _near(game, run, sel)
    if near is not None:
        extra["near"] = near                         # "adjacent to the Jackalope": the panel says it
    got = run.ask(game, "fighter", chooser, [f.fid for f in cands], 0 if unknown else 1, 1, prompt or "choose a fighter", **extra)
    if not got:
        return []
    return [game.fighters[got[0]]]


# ---------------------------------------------------------------- cards

def find_card(game, card_id: int, owner: int | None = None):
    """The card with that id. Decks can share CardIDs (the TMNT heroes and Medusa are all DeckID 176): `owner`'s own
    card wins, the rival's is the fallback."""
    if owner is not None:
        return game.card_of(card_id, owner)
    for p in game.players:
        for c in p.full_set:
            if c.card_id == card_id:
                return c
    return None


def locate(game, card) -> tuple[int, str] | None:
    """(player, zone) of a card that is in a hand, deck or discard; None when it is somewhere else (in combat)."""
    for i, p in enumerate(game.players):
        for zone, pile in (("hand", p.hand), ("deck", p.deck), ("discard", p.discard)):
            if card in pile:
                return i, zone
    return None


def card_ref(game, run, ref) -> list:
    """CardRef -> list of Card (empty if that card is not known to this effect)."""
    ctx = run.ctx
    ids = {"this": ctx.card_id, "opponent_card": ctx.opp_card_id, "attack_card": ctx.attack_card_id,
           "defense_card": ctx.defense_card_id}
    if ref in ids:
        owners = {"this": ctx.owner, "opponent_card": 1 - ctx.owner,
                  "attack_card": game.fighters[ctx.attacker_fid].owner if ctx.attacker_fid else None,
                  "defense_card": game.fighters[ctx.defender_fid].owner if ctx.defender_fid else None}
        card = find_card(game, ids[ref], owners[ref]) if ids[ref] is not None else None
        return [] if card is None else [card]
    if isinstance(ref, str) and ref.startswith("$"):
        return [c for c in (find_card(game, i, ctx.owner) for i in run.bound(ref[1:], "cards")) if c is not None]
    raise EffectError(f"bad card reference {ref!r}")


def _matches(card, flt: dict) -> bool:
    if "type" in flt and card.type != flt["type"]:
        return False
    if "type_not" in flt and card.type == flt["type_not"]:
        return False
    if "type_in" in flt and card.type not in flt["type_in"]:
        return False
    if "tag" in flt and flt["tag"] not in card.tags:
        return False
    if "tag_not" in flt and flt["tag_not"] in card.tags:
        return False
    if "title" in flt and card.title != flt["title"]:
        return False
    if "fighter" in flt and card.fighter != flt["fighter"]:
        return False
    return True


def card_candidates(game, run, sel: dict) -> list[Picked]:
    """CardSel -> every card of the zone that passes `filter` and `except`, in zone order (deck: top first)."""
    player = player_of(game, run, sel["player"])
    zone, p = sel["zone"], game.players[player]
    if zone == "hand":
        pile = p.hand
    elif zone == "discard":
        pile = p.discard
    elif zone == "deck":
        pile = p.deck
    elif zone == "in_play":
        cid = game.fx.ongoing_card_id(player)
        pile = [] if cid is None else [c for c in [find_card(game, cid, player)] if c is not None]
    else:
        raise EffectError(f"bad card zone {zone!r}")
    skip = set(card_ref(game, run, sel["except"])) if "except" in sel else set()
    flt = sel.get("filter") or {}
    return [Picked(player, zone, c) for c in pile if c not in skip and _matches(c, flt)]


def select_cards(game, run, sel: dict, purpose: str = "choose", prompt: str | None = None, **extra) -> list[Picked]:
    """The cards a CardSel designates, deciding `chosen` through the chooser and `random` through the run's
    memoized rng. `prompt` names the request (a bot's `choose_discard` gets it as the reason: the card's title);
    `extra` travels in the request (where a returned card goes, so a bot can prefer one that comes back)."""
    cands = card_candidates(game, run, sel)
    pick = sel.get("pick", "chosen")
    if cands and run.flags.get("look_cancelled") and sel["zone"] == "hand" \
            and player_of(game, run, sel.get("chooser", "owner")) != cands[0].player:
        return []                                  # the look was cancelled: nothing of that hand was seen to pick from
    if pick == "all":
        return cands
    n = min(int(amount(game, run, sel.get("amount", 1))), len(cands))
    if n <= 0:
        return []
    if pick == "top":
        return cands[:n]
    if pick == "bottom":
        return cands[::-1][:n]
    if pick == "random":
        return run.random_sample(cands, n)
    chooser = player_of(game, run, sel.get("chooser", "owner"))
    lo = 0 if sel.get("up_to") else n
    by_id = {c.card.card_id: c for c in cands}
    got = run.ask(game, "cards", chooser, list(by_id), lo, n, prompt or f"{purpose} cards", zone=sel["zone"],
                  purpose=purpose, of=cands[0].player, **extra)
    return [by_id[i] for i in got]


# ---------------------------------------------------------------- amounts

def amount(game, run, a):
    if isinstance(a, bool):
        raise EffectError(f"bad amount {a!r}")
    if isinstance(a, (int, float)):
        return a
    if isinstance(a, str) and a.startswith("$"):
        return run.bound(a[1:], "num")
    if not isinstance(a, dict):
        raise EffectError(f"bad amount {a!r}")
    times = a.get("times", 1)
    if "attr" in a:
        cards = card_ref(game, run, a["of"])
        value = 0 if not cards else (cards[0].boost if a["attr"] == "boost" else (cards[0].value or 0))
    elif "count" in a:
        value = len(fighter_candidates(game, run, a["count"])[0])
    elif "combat_value" in a:       # the running total of the card's side in this combat (boosts and bonuses included)
        value = combat_value(game, run, a["combat_value"])
    elif "count_cards" in a:
        value = len(card_candidates(game, run, a["count_cards"]))
    elif "count_of" in a:
        value = len(card_ref(game, run, a["count_of"]))
    elif "counter" in a:
        player = player_of(game, run, a.get("player", "owner"))
        value = counter_value(game, player, a["counter"])
    elif "stat" in a:
        value = _stat(game, run, a)
    else:
        raise EffectError(f"bad amount {a!r}")
    return value * times


def combat_value(game, run, ref) -> int:
    """The total value the card `ref` has so far in the combat that is running (0 outside a combat or without that card)."""
    flow = getattr(run, "flow", None)
    cards = card_ref(game, run, ref)
    if flow is None or flow.ctx is None or not cards:
        return 0
    from .modifiers import side_of
    side = side_of(flow, cards[0])
    return 0 if side is None else (flow.ctx.atk_value if side == "atk" else flow.ctx.def_value)


def counter_value(game, player: int, name: str) -> int:
    """HeroDef counters (destiny) are counted from the piles; ability counters live in fx.counters."""
    if name in game.players[player].hero.counters:
        return game.counter(player, name)
    from .model import load_effects
    rng = load_effects(game.players[player].hero.slug).counter_range(name)
    return game.fx.counter_value(player, name, rng.start)


def _stat(game, run, a):
    stat = a["stat"]
    if stat in ("hp", "max_hp"):
        f = (fighter_candidates(game, run, a["fighter"])[0] or [None])[0] if "fighter" in a else game.hero(run.ctx.owner)
        return 0 if f is None else getattr(f, stat)
    if stat == "zones":      # how many zones the fighter's space belongs to; 0 off the board
        f = (fighter_candidates(game, run, a["fighter"])[0] or [None])[0]
        return 0 if f is None or f.pos is None else len(game.board.zones(f.pos))
    player = player_of(game, run, a.get("player", "owner"))
    if stat == "hand_size":
        return len(game.players[player].hand)
    if stat == "actions_taken_this_turn":
        return game.fx.taken if player == game.turn else 0
    if stat == "other_cards_played_this_turn":
        if player != game.turn:                            # a defense on the rival's turn: nothing was played on the own turn
            return 0
        return max(0, game.fx.played[player] - 1)         # the card being resolved is counted already
    if stat == "combats_lost_this_turn":
        return game.fx.lost[player]
    if stat == "combats_won_this_turn":
        return game.fx.won[player]
    if stat == "damage_dealt_this_combat":
        return run.ctx.damage_dealt
    if stat == "damage_taken_this_combat":
        return run.ctx.damage_taken
    raise EffectError(f"bad stat {stat!r}")


# ---------------------------------------------------------------- conditions

_COMPARE = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, "==": lambda a, b: a == b,
            ">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "!=": lambda a, b: a != b}


def condition(game, run, c: dict) -> bool:
    if "all" in c:
        return all(condition(game, run, x) for x in c["all"])
    if "any" in c:
        return any(condition(game, run, x) for x in c["any"])
    if "not" in c:
        return not condition(game, run, c["not"])
    test = c.get("test")
    if test == "form_is":
        return game.form(player_of(game, run, c.get("player", "owner"))) == c["form"]
    if test == "exists":
        if "fighters" in c:
            return bool(fighter_candidates(game, run, c["fighters"])[0])
        if "cards" in c:
            return bool(card_candidates(game, run, c["cards"]))
        return bool(space_options(game, run, c["space"]))
    if test == "fighter_at":
        f = _ref_fighter(game, run, c["fighter"])
        return f is not None and f.pos in space_options(game, run, c["space"], default_empty=False)
    if test == "card":
        cards = card_ref(game, run, c["card"])
        return bool(cards) and _matches(cards[0], c.get("filter") or {})
    if test == "combat_result":
        won = run.ctx.combat_result == "won"
        return won if c["result"] == "won" else not won
    if test == "effects_canceled":
        from .modifiers import effects_canceled
        return effects_canceled(game, run, c["card"])
    if test == "counter":
        v = counter_value(game, player_of(game, run, c.get("player", "owner")), c["name"])
        return v >= c.get("min", v) and v <= c.get("max", v)
    if test == "moved_this_turn":
        f = _ref_fighter(game, run, c["fighter"])
        start = None if f is None else game.fx.turn_start_pos.get(f.fid)
        return start is not None and f.pos != start
    if test == "played_as":
        return run.ctx.played_as == c["side"]
    if test == "compare":
        return _COMPARE[c["op"]](amount(game, run, c["left"]), amount(game, run, c["right"]))
    if test == "plugin":
        from .ops_core import plugin_test
        return plugin_test(game, run, c)
    raise EffectError(f"bad condition {c!r}")
