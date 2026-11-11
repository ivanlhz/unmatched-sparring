"""What the AI knows about Sinbad's cards (docs/heroes/sinbad.md): the value a VOYAGE attack will have, and Momentous Shift's 5.

`ai_medusa.card_value` and the rival models read the printed value, so a card whose DURING raises it needs these figures to be
played (or feared) for what it is worth: a VOYAGE card is worth its printed 2 plus the VOYAGE cards in its owner's discard pile
(the card in play is not there yet), Momentous Shift 5 when its fighter started the turn on another space."""
from __future__ import annotations

MOMENTOUS_SHIFT = "Momentous Shift"
MOMENTOUS_VALUE = 5


def voyage_count(game, owner: int) -> int:
    """VOYAGE cards in `owner`'s discard pile (0 for a hero without the counter)."""
    return game.counter(owner, "voyage") if "voyage" in game.players[owner].hero.counters else 0


def voyage_extra(card, count: int) -> int:
    """The bonus a VOYAGE card gets from `count` cards in its owner's pile."""
    return count if "voyage" in card.tags else 0


def own_value(game, fighter, card) -> float | None:
    """The value `card` will have for `fighter` when its DURING is known now, or None when it is the printed one."""
    if "voyage" in card.tags:
        return float(card.value + voyage_count(game, fighter.owner))
    if card.title == MOMENTOUS_SHIFT:
        start = game.fx.turn_start_pos.get(fighter.fid)
        return float(MOMENTOUS_VALUE) if start is not None and fighter.pos != start else None
    return None


VOYAGE_BACK = 0.75           # a VOYAGE card Voyage Home returns to the hand, in cards: it leaves the pile that powers his maneuver and his attacks
MOVE_AFTER = 0.3             # the AFTER that moves Sinbad (Toil and Danger, the Cannibals) or one fighter on a win (Leap Away)
LOOK_AFTER = 0.3             # the look at the rival's hand (the Giant Snakes)
STRIP_AFTER = 0.6            # the random card the rival loses (the Creature With Eyes Like Coals of Fire)
AFTER_DRAWS = {"Exploit": 1, "By Fortune and Fate": 2, "Voyage to the City of the King of Serendib": 1}
AFTER_MOVES = {"Toil and Danger": False, "Voyage to the Cannibals With the Root of Madness": False, "Leap Away": True}   # title -> only on a win


def after_value(game, owner: int, card, p_win: float, foe_hp_weight: float, card_value: float, hero_hp_weight: float,
                room: int | None = None, foe_hp: float = 0.0) -> float:
    """What the AFTER of a Sinbad card is worth, in the AI's units (`card_value` per card, `foe_hp_weight` per hit point of the
    opposing fighter, `hero_hp_weight` per hit point of Sinbad). The cards `ai_medusa.AFTER_BONUS` does not list: without them his
    draws and his VOYAGE effects were worth nothing, and a maneuver (a card for nothing) outbid every attack that drew two.
    `room`: the cards the hand can still take (`ai_medusa.hand_room` less the hand once the card is played); None, no limit."""
    fits = lambda n: n if room is None else min(n, max(0, room))
    title = card.title
    if title in AFTER_DRAWS:
        return card_value * fits(AFTER_DRAWS[title])
    if title in AFTER_MOVES:
        return MOVE_AFTER * (p_win if AFTER_MOVES[title] else 1.0)
    if "voyage" not in card.tags:
        return 0.0
    if title == "Voyage Home":
        return card_value * VOYAGE_BACK * fits(voyage_count(game, owner))
    if title == "Voyage to the City of the Man-Eating Apes":
        return foe_hp_weight * min(2.0, foe_hp)
    if title == "Voyage to the Island That Was a Whale":
        hero = game.hero(owner)
        return hero_hp_weight * min(2.0, hero.max_hp - hero.hp) if hero.alive else 0.0
    if title == "Voyage to the Creature With Eyes Like Coals of Fire":
        return STRIP_AFTER
    if title == "Voyage to the Valley of the Giant Snakes":
        return LOOK_AFTER
    return 0.0
