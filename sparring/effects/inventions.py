"""Inventions (Donatello's INVENTIVE): cards with an `invention` block in the effects file.

After an invention is played (a combat card when its combat ends, a scheme when its ops are done) it is not discarded:
it is tucked under the hero card (`PlayerState.tucked`) and its invention bonus holds for the rest of the game. The
bonus is read from the card, never copied: `modifiers` add to the value of the owner's attacks or defenses (inside an
invention `type: attack | defense` means "played as an attack / as a defense": a versatile card counts as whichever it
plays as), `triggers` fire like the hero's own (Smoke bomb: a scheme played gains an action).

A tucked card is out of every pile: effects that read the discard pile never see it. It does not help in the combat or
the scheme that tucks it (it is tucked after it)."""
from __future__ import annotations

from . import table
from .model import EffectError, load_effects

INVENTION_WORTH = 3.0         # what an invention is worth in hand, in the units of `card_worth`: it must not be wasted
BONUS_HP = 1.5                # a permanent +1 on one side of every combat, in hit points over the rest of the game
TRIGGER_HP = 1.0              # a permanent trigger: about one action per scheme played


def spec_of(game, player: int, card) -> dict | None:
    """The `invention` block of `card` in `player`'s hero data (None: it is not an invention)."""
    return spec_of_title(game.players[player].hero.slug, card.title)


def spec_of_title(slug: str, title: str) -> dict | None:
    try:
        fx = load_effects(slug).cards.get(title)
    except EffectError:
        return None
    return None if fx is None else fx.invention


def settle_played(game, player: int, card) -> None:
    """A card of `player` has been played and resolved: it is tucked if it is an invention (and the hero is on the
    interpreter), else it goes to the discard pile."""
    pile = game.players[player]
    if game.fx.interprets(player) and spec_of(game, player, card) is not None:
        pile.tucked.append(card)
        table.intent(game, op="tuck", player=player, card=card.card_id)
    else:
        pile.discard.append(card)


def tucked(game, player: int):
    """(card, invention block) of each invention tucked under `player`'s hero card, in the order they were tucked."""
    for card in game.players[player].tucked:
        spec = spec_of(game, player, card)
        if spec is not None:
            yield card, spec


def bonus_parts(game, player: int, side: str) -> list[tuple[int, str]]:
    """(bonus, label) the tucked inventions of `player` add to a card played as `side` ("attack" | "defense")."""
    out = []
    for card, spec in tucked(game, player):
        n = sum(int(m["amount"]) for m in spec.get("modifiers", ())
                if m["kind"] == "modify_value" and m["cards"].get("type") in (None, side))
        if n:
            out.append((n, card.title))
    return out


def triggers(game, player: int) -> list[tuple[dict, int]]:
    """(trigger, card id) of the tucked inventions of `player`."""
    return [(trig, card.card_id) for card, spec in tucked(game, player) for trig in spec.get("triggers", ())]


def worth(game, player: int) -> float:
    """Hit points the tucked inventions of `player` are worth to them, so the bots score playing one early."""
    total = 0.0
    for _, spec in tucked(game, player):
        total += sum(BONUS_HP * int(m["amount"]) for m in spec.get("modifiers", ()) if m["kind"] == "modify_value")
        total += TRIGGER_HP * len(spec.get("triggers", ()))
    return total
