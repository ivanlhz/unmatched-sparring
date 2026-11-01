"""The ONGOING slot: the one permanent scheme each player may have in play (Ivan, 28/10).

A slot (`game.fx.ongoing[player]`) is either
  - a DSL card:     {"card_id": int}   its `ongoing` block (modifiers, triggers, until) comes from the hero's effects file;
  - a pre-DSL bonus {"card_id": None, "bonus": n, "label": str}   what `Game.add_combat_bonus` has always stored
    (Fight Or Flight before its card is interpreted). Saved apart, in the old `combat_bonus` key.
Playing another ONGOING replaces the player's active one (it goes to the discard pile); the rival's is untouched.
`Game.combat_bonus*` are thin views over this slot.

Rules and statuses of an active ONGOING are not copied anywhere: `active_modifiers` reads them from the card in play,
so they disappear the moment the card leaves. Rule modifiers are global ("Players cannot gain actions"); a status
modifier belongs to the card's owner (`player: owner`)."""
from __future__ import annotations

from typing import Iterator

from . import table
from .model import EffectError, load_effects, walk_ops
from .select import find_card

COMBAT_CARDS = {"player", "type", "fighter"}


# ------------------------------------------------------------------ the slot

def card_in_play(game, player: int):
    cid = game.fx.ongoing_card_id(player)
    return None if cid is None else find_card(game, cid)


def spec_of(game, player: int) -> dict | None:
    """The `ongoing` block of the DSL card `player` has in play (None for no card or a pre-DSL bonus)."""
    card = card_in_play(game, player)
    if card is None:
        return None
    return load_effects(game.players[player].hero.slug).card(card.title).ongoing


def leave_play(game, player: int):
    """The active ONGOING of `player` goes to the discard pile. Returns the card (None for none or a pre-DSL bonus)."""
    card = card_in_play(game, player)
    game.fx.take_ongoing(player)
    if card is not None and card not in game.players[player].discard:
        game.players[player].discard.append(card)
    if card is not None:
        table.intent(game, op="discard", zone="in_play", player=player, card=card.card_id)
    return card


def enter_play(game, player: int, card) -> None:
    """`card` becomes the active ONGOING of `player`; the one it replaces goes to the discard pile."""
    leave_play(game, player)
    pile = game.players[player]
    for where in (pile.discard, pile.hand):
        if card in where:
            where.remove(card)
    game.fx.set_ongoing(player, card.card_id)
    table.intent(game, op="ongoing", player=player, card=card.card_id)


def scheme_traits(slug: str, title: str) -> dict:
    """What the data of a scheme says about it, for a hero outside the interpreter (`fx.dsl_heroes`), where the engine
    cannot run its ops: the table-facing traits the legacy path needs, read from the card's DSL instead of its title.

      bonus          the "+n to the value of your combat cards" its ONGOING adds (0 for none)
      draw           the cards its top-level `draw` ops give
      discards_hand  it discards the whole hand (Crown Of Flame): the table moves it, the rest of what shows on the
                     pile is not another scheme
      choose         how many different effects it makes you pick (Pancakes!: 2), and `heal` the HP one of them heals"""
    try:
        card = load_effects(slug).card(title)
    except EffectError:
        return {}
    ops = card.moments.get("scheme", [])
    bonus = sum(int(m.get("amount", 0)) for m in (card.ongoing or {}).get("modifiers", []) if m.get("kind") == "modify_value")
    whole = any(o["op"] == "discard" and o["cards"].get("zone") == "hand" and o["cards"].get("pick") == "all" for o in ops)
    choices = [o for o in ops if o["op"] == "choose_effect"]
    heals = [h["amount"] for c in choices for h in walk_ops(c["options"]) if h["op"] == "heal"]
    return {"bonus": bonus, "draw": sum(int(o["amount"]) for o in ops if o["op"] == "draw"), "discards_hand": whole,
            "choose": sum(int(c["amount"]) for c in choices), "heal": heals[0] if heals else 0}


def set_legacy(game, player: int, n: int, label: str) -> str | None:
    """Pre-DSL ONGOING "add n to your combat cards" enters play. Returns the label of the one it replaced."""
    slot = game.fx.ongoing[player]
    old = None
    if slot is not None:
        old = slot["label"] if slot["card_id"] is None else getattr(card_in_play(game, player), "title", None)
        leave_play(game, player)
    game.fx.ongoing[player] = {"card_id": None, "bonus": n, "label": label}
    return old


def legacy_parts(game, player: int) -> list[tuple[int, str]]:
    slot = game.fx.ongoing[player]
    return [(slot["bonus"], slot["label"])] if slot is not None and slot["card_id"] is None else []


def set_legacy_all(game, sides) -> None:
    """Assigns `Game.combat_bonus = [[(n, label)], [...]]`: the last entry of each side is that player's ONGOING."""
    for player, side in enumerate(sides):
        if side:
            set_legacy(game, player, int(side[-1][0]), str(side[-1][1]))
        else:
            game.fx.ongoing[player] = None


def bonus_parts(game, player: int) -> list[tuple[int, str]]:
    """(bonus, label) the live ONGOING of `player` adds to ALL their combat cards (at most one entry)."""
    slot = game.fx.ongoing[player]
    if slot is None:
        return []
    if slot["card_id"] is None:
        return [(slot["bonus"], slot["label"])]
    spec = spec_of(game, player)
    card = card_in_play(game, player)
    n = sum(m["amount"] for m in (spec or {}).get("modifiers", ())
            if m["kind"] == "modify_value" and set(m["cards"]) <= {"player"})
    return [(n, card.title)] if n else []


def expiring_parts(game, player: int) -> list[tuple[int, str]]:
    """What `bonus_parts` would report if the slot expires at the start of `player`'s turn (what begin_turn returns)."""
    slot = game.fx.ongoing[player]
    if slot is None:
        return []
    if slot["card_id"] is not None:
        until = (spec_of(game, player) or {}).get("until") or {}
        if until.get("event") != "start_of_turn" or until.get("player", "owner") not in ("owner", "any"):
            return []
    return bonus_parts(game, player)


def expire_legacy(game, player: int) -> None:
    """Start of the owner's turn: a pre-DSL bonus lapses (a DSL card lapses through its own `until`)."""
    slot = game.fx.ongoing[player]
    if slot is not None and slot["card_id"] is None:
        game.fx.ongoing[player] = None


# ------------------------------------------------------------------ rules and statuses of the cards in play

def active_modifiers(game, kind: str | None = None) -> Iterator[tuple[int, dict]]:
    """(owner, modifier) of every modifier of the ongoing cards in play, optionally only one `kind`."""
    if not any(game.fx.card_slots()):
        return
    for player in (0, 1):
        spec = spec_of(game, player)
        for m in (spec or {}).get("modifiers", ()):
            if kind is None or m["kind"] == kind:
                yield player, m


def rules(game, rule: str) -> list[dict]:
    return [m for _, m in active_modifiers(game, "rule") if m["rule"] == rule]


def rule_total(game, rule: str) -> int:
    """Sum of the `amount` of an active rule (effect_damage_bonus)."""
    return sum(m.get("amount", 0) for m in rules(game, rule))


def can_gain_actions(game, player: int) -> bool:
    if rules(game, "no_gain_actions"):
        return False
    return not any(m["name"] == "cannot_gain_actions" and owner == player
                   for owner, m in active_modifiers(game, "status"))


def may_attack(game, player: int) -> bool:
    """Pact Of Freedom: nobody attacks as the first action of their own turn."""
    return not (rules(game, "no_attack_as_first_action") and game.turn == player and game.fx.taken == 0)


def hand_limit(game, player: int, default: int) -> int:
    return min([default] + [m["amount"] for m in rules(game, "max_hand_size")])


# ------------------------------------------------------------------ what a slot is worth to its owner (D2)

VALUE_POINT_HP = 1.0        # +1 to the owner's combat cards: about one hit point over the card's life (a combat)
IMMUNITY_HP = 0.5           # a status that shields the owner's side (Counterhex Shield: three of them)
EFFECT_BONUS_HP = 0.5       # +1 to the owner's effect damage (Pact Of Mortality)


def worth(game, player: int) -> float:
    """Hit points the ONGOING of `player` is worth to them, so the bots score keeping it, replacing it or losing it.
    Rules that bind both players alike (no first-action attacks, hand size, no gained actions, Pact Of Peace's
    trigger) count 0: their value depends on the matchup and the search sees their effect in the simulation."""
    slot = game.fx.ongoing[player]
    if slot is None:
        return 0.0
    if slot["card_id"] is None:
        return VALUE_POINT_HP * slot["bonus"]
    total = 0.0
    for m in (spec_of(game, player) or {}).get("modifiers", ()):
        if m["kind"] == "modify_value" and set(m["cards"]) <= COMBAT_CARDS and m["cards"].get("player", "owner") == "owner":
            total += VALUE_POINT_HP * m["amount"]
        elif m["kind"] == "status":
            total += IMMUNITY_HP
        elif m["kind"] == "rule" and m["rule"] == "effect_damage_bonus":
            total += EFFECT_BONUS_HP * m.get("amount", 0)
    return total


# ------------------------------------------------------------------ playing a scheme

def begin_scheme(game, player: int, card) -> None:
    """A DSL scheme is played. The card leaves the hand/discard (it must not be a target of its own effect) and, if it
    has an ONGOING, the player's active one is replaced now: the new rules are not yet in force during its own ops."""
    pile = game.players[player]
    if card in pile.hand:
        game.take_from_hand(player, card)
    elif card in pile.discard:
        pile.discard.remove(card)
    game.fx.count_played(player)
    if load_effects(pile.hero.slug).card(card.title).ongoing is not None:
        leave_play(game, player)


def finish_scheme(game, player: int, card) -> None:
    """The scheme's ops are done: it stays in play when it has an ONGOING, else goes to the discard pile."""
    pile = game.players[player]
    if load_effects(pile.hero.slug).card(card.title).ongoing is not None:
        game.fx.set_ongoing(player, card.card_id)
        table.intent(game, op="ongoing", player=player, card=card.card_id)
    else:
        pile.discard.append(card)
    if game.winner is None:
        game.fx.emit("after_scheme", player, card)


def resolve_scheme(game, player: int, fighter, card, choosers=None):
    """Plays the `scheme` moment of a DSL card start to finish. Returns the EffectRun and its Await (None = done and
    the card has been placed; an Await leaves `finish_scheme` to the caller once the run completes)."""
    from .run import Ctx, EffectRun
    from .events import default_choosers
    begin_scheme(game, player, card)
    run = EffectRun.for_card(game.players[player].hero.slug, card.title, "scheme",
                             Ctx(owner=player, this_fid=fighter.fid, card_id=card.card_id))
    pending = run.run(game, choosers or default_choosers(game))
    if pending is None:
        finish_scheme(game, player, card)
    else:                                        # parked like a trigger: the live session shows the choice and finishes
        run.flags["scheme"] = {"player": player, "card_id": card.card_id}
        game.fx.parked.append(run)
    return run, pending
