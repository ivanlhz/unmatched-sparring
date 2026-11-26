"""What the heuristic AI knows about Loki's cards (docs/heroes/loki.md): the value an attack will really have, what the AFTER of each card is
worth to whoever plays it, and what a TRICK costs the player who is not Loki.

`ai_medusa.card_value` reads the printed value, so the cards whose DURING decides it need these figures to be played at all (Ragnarök and
Shapeshifter print 0). Everything reads what the bot can know when it decides: the number of cards in a hand and the TRICKs the engine
tracks there (both public), never the identity of an unseen card. The search does not use this: its rollouts play the real effects through
the engine; this is the heuristic player's and the leaf's pricing.

The weights are the AI's usual ones, passed in by the caller so this module never imports the AI."""
from __future__ import annotations

from . import tricks

RAGNAROK, SHAPESHIFTER, UNDERHANDED, LAEVATEINN = "Ragnarök", "Shapeshifter", "Underhanded", "Laevateinn"
FLYTING, TROUBLE = "Malicious Flyting", "Looking For Trouble"
BALDR, FREYJA, SINDRI = "Trick: Baldr's Downfall", "Trick: Freyja's Rescue", "Trick: Sindri's Bet"
RAGNAROK_PER_TRICK = 3
UNDERHANDED_VALUE = 6
BALDR_SELF_DAMAGE = 2
FREYJA_HEAL = 3


def is_his(game, owner: int) -> bool:
    return game.players[owner].hero.slug == "loki"


def attack_value(game, owner: int, card) -> float | None:
    """The value `card` will have as an attack of Loki's player, or None when it is the printed one. A TRICK played by anyone else keeps its printed value."""
    if not is_his(game, owner):
        return None
    rival, mine = game.players[1 - owner], game.players[owner]
    title = card.title
    if title == RAGNAROK:
        return float(RAGNAROK_PER_TRICK * len(tricks.tricks_in_rival_hand(game, owner)))
    if title == SHAPESHIFTER:
        return float(len(rival.hand))                                  # one card in their hand, one point
    if title == UNDERHANDED:
        return float(UNDERHANDED_VALUE) if len(rival.hand) > len(mine.hand) - (card in mine.hand) else None
    if title == LAEVATEINN:
        pool = [c for c in rival.full_set if c not in rival.gone]
        mean = sum(c.boost for c in pool) / len(pool) if pool else 0.0
        return card.value + (mean if rival.hand else 0.0)
    return None


def after_value(game, owner: int, card, p_win: float, foe_hp_weight: float, card_value: float, hero_hp_weight: float) -> float:
    """What the AFTER of `card` is worth to `owner` (the player who plays it), in the AI's units (`foe_hp_weight` per hit point of an opposing
    fighter, `card_value` per card, `hero_hp_weight` per hit point of the owner's hero). Loki's own Baldr's Downfall and Malicious Flyting draw;
    a TRICK played by the OTHER player runs its NOT LOKI part, which costs them (Baldr's two damage, Freyja's three hit points for Loki, Sindri
    giving Loki a card back). 0 for any card the AI prices from the data."""
    title = card.title
    if is_his(game, owner):
        if title == BALDR:
            return card_value
        if title == FLYTING:
            return card_value * (1.0 + (1.0 if any(tricks.is_trick(c) for c in game.players[1 - owner].hand) else 0.0) * 0.3)
        return 0.0
    if not tricks.borrowed(game, owner, card):
        return 0.0
    loki = game.hero(1 - owner)
    hero = game.hero(owner)
    if title == BALDR:
        return -hero_hp_weight * min(BALDR_SELF_DAMAGE, max(hero.hp - 1, 0)) if hero.alive else 0.0
    if title == FREYJA:
        return -foe_hp_weight * min(FREYJA_HEAL, max(loki.max_hp - loki.hp, 0))
    if title == SINDRI:
        return -card_value if game.players[1 - owner].discard else 0.0
    return 0.0


def defense_value(game, owner: int, card) -> float | None:
    """Sindri's Bet defending for Loki is a 3 that also takes 3 from the card it meets unless they pay a card: priced as 3 plus a hedge."""
    if is_his(game, owner) and card.title == SINDRI:
        return 3.0 + 1.5
    return None
