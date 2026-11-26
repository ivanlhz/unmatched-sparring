"""What the AI knows about Pandora's Box (docs/heroes/pandora.md): when to keep revealing and when to stop.

The interpreter asks "keep revealing?" after every Misery (trigger id `pandora_box`) and the generic answer to an optional is yes, which would
walk into three feathers every turn. `keep_revealing` prices it as an optimal stopping problem over the Miseries still in the Box, which
are the only thing the bot may know: it never sees the order (the Box is shuffled and hidden; the next Misery is drawn when it is revealed),
except the top card after HOPE, which it has looked at.

Each Misery is worth something to the turn (a Kakodaemon, +1 to the attacks in hand, 1 damage next to her, a card, a little move) and a Misery that
brings the feathers to three costs one hit point per revealed Misery. `ahead(mask)` is the expected value of revealing once more and then playing on
the best way, against stopping (0); the answer is yes when it is above `MARGIN`. A hit point is `W_MEDUSA_HP`, dearer the lower she is, and a hit
point that raises the chance of dying in the rival's next turn is charged for it (the same price as Sun Wukong's CLONES, `ai_wukong.summon_pays`)."""
from __future__ import annotations

from functools import lru_cache

from .ai_medusa import CARD_VALUE, HARPY_VALUE, LETHAL, W_MEDUSA_HP, Model
from .effects import plugins_pandora as box

BOX_KEY = "pandora_box"        # the key prefix of the request: the id of the ability's trigger
COMFORT = 9                    # below this many hit points left, each one costs more (URGENCY per missing point)
URGENCY = 0.12
DEATH = 120.0                  # the damage would defeat her
MARGIN = 0.0                   # revealing again must be worth more than stopping by this much
BODY = 0.9                     # what a Kakodaemon is worth beyond its hit point: a body that takes a blow, holds a space, strikes with Spite and Malice
TOIL_PER_ATTACK = 0.4          # +1 to an attack she can make this turn (at most two of them are played)
DRAW = 2 * CARD_VALUE          # a card drawn
HOPE = 0.25                    # a look at the top card: the next decision is better informed
MOVE = 0.1                     # one space
HAND_FULL = 7                  # a drawn card past the hand limit is discarded at the end of the turn


def kakodaemon_available(game, me: int) -> bool:
    """One is out of the board (never placed or defeated): Woe can bring it in."""
    return any(f.name == "Kakodaemon" and not f.alive for f in game.own(me, alive_only=False))


def misery_worth(game, me: int, idx: int) -> float:
    """What the effect of the Misery `idx` is worth to `me` now, in the AI's hit-point units."""
    hero = game.hero(me)
    name = box.NAMES[idx]
    if name == "Woe":
        return HARPY_VALUE + BODY if kakodaemon_available(game, me) else 0.0
    if name == "Toil":
        attacks = sum(1 for c in game.players[me].hand if c.can_attack and c.usable_by(hero.name))
        return TOIL_PER_ATTACK * min(attacks, 2)
    if name == "Pain":
        return sum(1.0 for f in game.foes(me) if f.alive and f.pos is not None and hero.pos is not None
                   and game.board.adjacent(hero.pos, f.pos))
    if name == "Hope":
        return HOPE
    if name == "Greed":
        return DRAW if len(game.players[me].hand) < HAND_FULL else DRAW / 4
    if name == "Confusion":
        return MOVE
    return 0.0          # Misfortune: two feathers and nothing else


def stop_cost(ai, game, me: int, n: int, risks: dict) -> float:
    """What taking `n` damage at three feathers costs: the hit points, dearer the lower she is, and the chance of dying next turn."""
    hero = game.hero(me)
    left = hero.hp - n
    if left <= 0:
        return DEATH
    medusa, model = ai.medusa(me), Model(game, me)
    for hp in (left, hero.hp):
        if hp not in risks:
            risks[hp] = medusa.death_risk(game, model, hero, hp)
    now = risks[hero.hp]
    return n * W_MEDUSA_HP * (1 + URGENCY * max(0, COMFORT - left)) + LETHAL * max(0.0, risks[left] - now)


def keep_revealing(ai, game, req) -> bool:
    """The answer to "keep revealing?": the Miseries still in the Box are all she knows (`req.extra['unrevealed']`), and the top one when HOPE showed it."""
    me = req.player
    left = tuple(req.extra["unrevealed"])
    mask = sum(1 << i for i in range(len(box.NAMES)) if i not in left)
    top = req.extra.get("top")
    worth = {i: misery_worth(game, me, i) for i in left}
    risks: dict = {}

    @lru_cache(maxsize=None)
    def ahead(state: int, known: int | None) -> float:
        """Expected value of one more reveal from `state`, playing on optimally; stopping is worth 0."""
        out = [i for i in range(len(box.NAMES)) if not state >> i & 1]
        cands = [known] if known is not None else out
        if not cands:
            return 0.0
        total = 0.0
        for i in cands:
            nxt = state | 1 << i
            total += worth[i]
            if box.feathers(nxt) >= box.STOP_AT:
                total -= stop_cost(ai, game, me, len(box.revealed(nxt)), risks)
            else:
                total += max(0.0, ahead(nxt, None))
        return total / len(cands)

    return ahead(mask, top) > MARGIN
