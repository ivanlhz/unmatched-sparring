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

from .model import load_effects
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
    return card


def enter_play(game, player: int, card) -> None:
    """`card` becomes the active ONGOING of `player`; the one it replaces goes to the discard pile."""
    leave_play(game, player)
    pile = game.players[player]
    for where in (pile.discard, pile.hand):
        if card in where:
            where.remove(card)
    game.fx.set_ongoing(player, card.card_id)


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


# ------------------------------------------------------------------ playing a scheme

def begin_scheme(game, player: int, card) -> None:
    """A DSL scheme is played. The card leaves the hand/discard (it must not be a target of its own effect) and, if it
    has an ONGOING, the player's active one is replaced now: the new rules are not yet in force during its own ops."""
    pile = game.players[player]
    if card in pile.hand:
        game.take_from_hand(player, card)
    elif card in pile.discard:
        pile.discard.remove(card)
    if load_effects(pile.hero.slug).card(card.title).ongoing is not None:
        leave_play(game, player)


def finish_scheme(game, player: int, card) -> None:
    """The scheme's ops are done: it stays in play when it has an ONGOING, else goes to the discard pile."""
    pile = game.players[player]
    if load_effects(pile.hero.slug).card(card.title).ongoing is not None:
        game.fx.set_ongoing(player, card.card_id)
    else:
        pile.discard.append(card)


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
