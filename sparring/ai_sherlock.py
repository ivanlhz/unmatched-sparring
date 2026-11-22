"""Sherlock Holmes in the bots (docs/heroes/sherlock-holmes.md): what to predict, what to name, when to change a value.

Everything here reads only what a player may know: the rival's deck list (public) minus what is gone (their discard pile and the
cards removed), the cards a `look_hand` showed (`KnownHand`) and the rival's hand SIZE. Never the rival's hand, deck order or a
face-down card, in a game or in a search that gave the bot a determinized rival.
"""
from __future__ import annotations

from math import comb

from .effects.ops_combat import PREDICT_VALUES
from .state import Game

NO_MATCH = 0.5          # what the revealed hand of a miss is worth to the namer, in hit points (the look, not a card)
CARD_LOSS = 1.0         # a card of the rival's hand discarded is worth about a hit point


def _pool(game: Game, me: int) -> list:
    """The rival's cards that can still be in their hand: the ones a look showed if any, else their deck list minus what is gone."""
    rival = game.players[1 - me]
    seen = game.players[me].known.cards(rival)
    return list(seen) if seen else [c for c in rival.full_set if c not in rival.gone]


def predict_attack_value(game: Game, me: int, attacker_fid: str | None = None) -> int:
    """Elementary: the printed value the rival's attack most likely has. Candidates are the cards the attacking fighter may play
    (band and attack type); the commonest printed value wins, ties go to the higher one (the likelier blow is a strong one)."""
    attacker = game.fighters.get(attacker_fid) if attacker_fid is not None else None
    pool = [c for c in _pool(game, me) if c.can_attack and (attacker is None or c.usable_by(attacker.name))]
    if not pool:
        return 0                    # nothing the attacker may still play: any number is as good as another
    counts: dict[int, int] = {}
    for c in pool:
        counts[c.value or 0] = counts.get(c.value or 0, 0) + 1
    return max(counts, key=lambda v: (counts[v], v))


def name_value(game: Game, me: int) -> int:
    """Confirm Suspicion: the value to name. Each value is priced by the chance the rival holds a card of it (a card a look showed is
    certain) times what a match costs them (the least BOOST they can discard, plus the card), against the look at their hand a miss
    gives; a tie goes to the lower value (the rival's cheap cards are the likelier ones to be kept)."""
    rival = game.players[1 - me]
    seen = game.players[me].known.cards(rival)
    pool = list(seen) if seen else [c for c in rival.full_set if c not in rival.gone]
    hand = len(rival.hand)

    def worth(v: int) -> float:
        match = [c for c in pool if c.type != "scheme" and (c.value or 0) == v]
        if not match:
            return NO_MATCH
        n = len(pool)
        if seen:
            p = 1.0
        elif n <= hand:
            p = 1.0
        else:
            p = 1.0 - comb(n - len(match), hand) / comb(n, hand) if hand and n - len(match) >= hand else (1.0 if hand else 0.0)
        return p * (min(c.boost for c in match) + CARD_LOSS) + (1 - p) * NO_MATCH

    return max(PREDICT_VALUES, key=lambda v: (worth(v), -v))


def deduce_pays(info: dict) -> bool:
    """Deduce Strategy: the rival's printed value becomes its BOOST; worth it when that is lower (a card's value counts for the rival)."""
    return info["to"] < info["now"]
