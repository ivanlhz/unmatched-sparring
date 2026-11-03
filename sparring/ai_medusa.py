"""Medusa's heuristic AI.

Evaluation function (points of "advantage" from Medusa's point of view)
-----------------------------------------------------------------------
A plan is up to 2 actions (maneuver, attack, scheme, pass). It is scored
    value(plan) = sum(value of each action) + position_value(expected final state)
and only the first action is executed; then it replans with the real result.

Value of an action
  * attack   = weight(target) * expected damage + bonus of "AFTER COMBAT" effects weighted by
               the probability of winning - card cost (+ penalty if it speeds up
               Hellboy's transformation with Clutching Claws / Hiss and Slither)
  * maneuver = draw (+CARD_VALUE) - cost of the boost card
  * scheme   = expected damage (A Momentary Glance) or repositioning (Winged Frenzy) - card cost
  * scheme of any other interpreted hero (D2) = what simulating it on a blind clone with EffectAI
               deciding inside allows (material, ONGOING entering or leaving, cards gained or lost, actions granted)
               - card cost; the real execution decides with the same rules.
  The rival is modelled with the hypergeometric: its hand is `h` random cards from those NOT in its
  discard pile; it plays its best eligible card. That yields P(win), expected damage and P(kill).

Position value (kiting)
  -threat of Hellboy and Lobster for the next turn, taking the best target as the attacker:
     steps to a space from which they can strike  vs  movement + possible boost
     (P(having a card with the needed boost), ANUNG UN RAMA adds ANUNG_FREE_MOVE for its free movement
     and +2 to the attack value), expected damage discounting my best defense in hand, and lethal risk.
  +PRESSURE for each rival in Medusa's zone (ability + shot without moving).
  Simplification: bodies do not block the rival's path (they only occupy attack spaces).

Survival (any hero)
  * A rival already in reach hits twice in its turn: the hero's threat counts its two best attacks (`Model.two_hit_dist`)
    against my two best defenses in hand (none: undefended), each landed blow one point heavier (EFFECT_MARGIN).
    The more likely that kills (continuous up to SURVIVAL_P), the less desperation eases the fear of dying, so running
    away (maneuver, with or without a boost, and the free move of ANUNG UN RAMA) outranks the "move to strike"
    preference whenever the strike square carries a SURVIVAL_P chance of death.
  * Lethal first (`lethal_attack`): an attack on the rival hero that kills with LETHAL_GO chance, or two attacks whose
    expected damage together clears its HP by TWO_ATTACK_MARGIN, is played before any survival consideration.

Exhaustion, hand limit and desperation
  * Drawing with an empty deck does EXHAUST_DAMAGE to each own fighter: `apply_expected` simulates it (a maneuver
    or a Snipe/Regroup that kills Medusa is worth -DEATH) and draws with a deck are counted as unknown cards
    (`Game.phantom_draws`).
  * At the end of the turn (`terminal_value`): cards beyond the hero's hand cap (`Game.hand_cap`) are discarded (those of lowest
    `keep_value`, and the unknown draw is worth its average) and each draw that eats the deck costs `DECK_SCARCITY`
    according to the draws Medusa can still afford (`draw_budget`). A maneuver without moving with a full hand only loses.
  * `desperation` (0..1) measures how badly the bot is losing: own HP against the rival hero's, fallen Harpies and
    the exhaustion clock. With it the prize for being in range of the rival hero goes up (expected progress toward winning
    x LETHAL, the same pattern as the penalty for dying) and the weight of fleeing goes down: fleeing only pays off if
    time plays in our favor.
  * The deck depends on the strategy (`race`, `deck_cost`): a draw is not worth the same with the game won in
    few turns as with a long game. The turns the bot takes to kill the rival hero are estimated
    (rival HP / average damage per turn), those the rival takes to kill it and the deck turns that remain. If the
    race is won before the deck runs out, drawing is almost free (scarcity drops to DECK_SCARCITY_FLOOR);
    if the game would last longer than the deck, each draw brings forward exhaustion draws and pays EXHAUST_BILL (soft,
    growing with the shortfall, up to x2 if the bot is also losing the race): attacks, schemes and
    maneuvers with a boost are preferred over drawing without moving anyone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
from math import ceil, comb

from .cards import can_be_boost
from .combat import GAZE_DAMAGE, GLANCE_DAMAGE, ON_EARTH
from .controller import Controller
from .effects.model import walk_ops
from .effects.modifiers import boost_limit, card_effects, defers_defeat
from .state import ANUNG, EXHAUST_DAMAGE, Fighter, Game

GAZE = "medusa_gaze"      # Medusa's start-of-turn ability trigger (data/heroes/effects/medusa.json)

CARD_VALUE = 0.4
W_HERO = 1.0
W_SIDEKICK = 0.8
KILL_SIDEKICK = 3.0      # a sidekick without an AI profile (and the scale of protect_factor)
KILL_BASE = 2.0          # killing any sidekick: the body, before what its death costs the rival
STAKE_WEIGHT = 0.6       # share of the rival's still-to-come exclusive / dependent effects (the AI profile) a kill counts
THREAT_WEIGHT = 0.15     # per point of the sidekick's mean attack value (x RANGED_THREAT when it shoots)
RANGED_THREAT = 1.5
KILL_CAP = 6.0           # a sidekick never outweighs the hero: killing or protecting the hero comes first
STRIKE_PER_POINT = 0.2   # position reward per point of the best attack its owner holds, for a striker in strike range
STRIKE_MIN = 0.6         # least a striker gains from standing in strike range (what adjacency always gave a sidekick)
W_MEDUSA_HP = 1.2
HARPY_VALUE = 0.9
LETHAL = 60.0
HERO_KILL = 8.0          # the hero's kill bonus before the game itself (LETHAL): no sidekick kill (<= KILL_CAP + its hit points) outranks it
PRESSURE = 0.3
BOOST_DISCOUNT = 0.65   # reaching with a boost costs him a card and both actions
DOUBLE_ATTACK = 1.5     # already in reach: he can attack twice without moving
ANUNG_FREE_MOVE = 2
BOOST_RELIANCE = 0.6
TRANSFORM_PENALTY = {1: 3.0, 2: 1.8, 3: 0.8}
MAX_ENEMY_STEPS = 9
TOP_FIRST = 6
TOP_FIRST_DESPERATE = 14   # when every action counts, a wider look is taken before committing
TOP_SECOND = 4
APPROACH_PULL = 0.1        # position value lost per space between a non-Medusa hero and the nearest rival
APPROACH_TOP = 3           # extra first actions that walk into reach of a rival (non-Medusa heroes)
DEATH = 120.0           # losing the game (more than LETHAL, which is weighted by probability)
DECK_SCARCITY = {0: 3.0, 1: 1.8, 2: 1.0, 3: 0.5, 4: 0.25}   # cost of being left with few draws to pay
DESPERATE_FEAR_DROP = 0.8   # with total desperation fleeing weighs 20 % less
WIN_PRIZE = 60.0            # winning is worth what losing costs: expected progress x prize
PROGRESS_DISCOUNT = 0.8     # the rival can step aside before my next turn
CLOCK_HORIZON = 8           # with 8 or more draws to pay the deck clock does not press
IDLE_MANEUVER = 0.5         # (not Medusa, whose kiting is standing clear) a maneuver that moves nobody and spends no boost is only a draw: it gives way to a decent attack
EFFECT_MARGIN = 1           # survival: a blow that lands is counted one point heavier (effects after or during the combat: Crowd control, Unbridled rage)
SURVIVAL_P = 0.25           # survival: from this chance of dying next turn the fear of the rival is no longer eased by desperation
TWO_ATTACK_MARGIN = 3       # two attacks only open the turn when their expected damage together exceeds the rival's hit points by this much (a coin flip is left to the ranking)
LETHAL_GO = 0.5             # an attack on the rival hero that kills with at least this chance is played before anything else
ATTACKS_PER_TURN = 1.0      # measured in simulation: about one attack and one draw per own turn
DRAWS_PER_TURN = 1.0
LONG_GAME = 12              # turns: a race longer than this is "the game will not end soon" (also caps the estimate)
EXHAUST_BILL = 3.5          # ~ a round of exhaustion (EXHAUST_DAMAGE to the hero and to each sidekick), in position points
BILL_SPAN = 4.0             # draws of shortfall (game longer than deck) at which one more draw pays the whole EXHAUST_BILL
DECK_SCARCITY_FLOOR = 0.25  # share of DECK_SCARCITY still charged when the race is won well before the deck runs out
MIN_NET = 0.25              # floor of the expected net damage per attack, so no estimate divides by zero
ACTION_VALUE = 1.0          # an action that gives away a scheme: at least the draw of a maneuver, often an attack

BLIND_BOOST = {"Bolts of Balthakk": (1, None), "Seven Suns of Cinnibus": (2, 7)}   # Doctor Strange: (blind boosts allowed, total above which the value is ignored)
MASTER, CLOAK, RINGS, MISTS = "Master of Kamar-Taj", "Cloak of Levitation", "The Rings of Raggadorr", "The Mists of Munnopor"
MISTS_EDGE = 0.4          # the Mists also cancel the effects of the attack that was played and replace it with a card nobody chose
BOOST_ACTION = 0.9        # a BOOSTED WITH that gains an action (it only pays on the bot's own turn)
STRIP_VALUE = 1.0         # a card the rival loses to a BOOSTED WITH that picks one from their hand
LOOK_VALUE = 0.5          # what looking at the rival's hand is worth by itself
RESCUE_SHARE = 0.9        # share of the cost of dying a card that brings the hero back (All Part of the Show) takes away
ELECTRO_GRENADE = "Electro grenade"
UNTESTED = "Untested enhancements"
INVENTION_PLAY = 1.2      # what playing an invention early is worth: its bonus (tucked) lasts the rest of the game

AFTER_BONUS = {
    "Quick strike": (CARD_VALUE, 0.0),                       # Donatello: draws one
    "Bo staff": (CARD_VALUE + 0.5, 0.0),                     # draws one and hits an adjacent rival for 1
    "Thinking ahead": (0.0, 0.2),
    "Shift focus": (0.1, 0.0),
    "Short circuit": (0.2, 0.0),
    "Self defense grid": (0.5, 0.0),                         # heals what it removes
    "Regroup": (CARD_VALUE, CARD_VALUE),       # (always, extra if it wins)
    "Snipe": (CARD_VALUE, 0.0),
    "Dash": (0.5, 0.0),
    "The Hounds of Mighty Zeus": (0.4, 0.0),
    "Clutching Claws": (0.7, 0.0),
    "Hiss and Slither": (0.7, 0.0),
    "Let's do this!": (CARD_VALUE, CARD_VALUE),     # Raphael: draws 1, 2 if it wins
    "Crowd control": (0.5, 0.0),                    # draws and hurts every adjacent rival
    "Batter up!": (0.0, 0.3),                       # pushes the loser away
    "Relentless": (0.6, 0.0),                       # the card comes back to the deck and 1 is drawn
    "Break something": (0.5, 0.0),                  # cancels the rival card's effects
    "Unbridled rage": (0.8, 0.0),                   # expected bonus of the cards it can give up
    "Bolts of Balthakk": (0.0, 0.7),                # Doctor Strange: gains an action when it wins
    "Steadfast Disciple": (0.5, 0.0),               # Wong: draws and hits 1 when he is beside the target
    "For My Next Trick": (CARD_VALUE + 0.9, 0.0),   # Houdini: moves a fighter, draws one and gains an action
    "Vanishing Act": (0.3, 0.0),                    # moves one of the two fighters up to 3 spaces
    "Grand Escape": (0.0, 0.3),                     # the winner goes to any space
    "The Big Reveal": (0.3, 0.0),                   # a boosted card comes back to the hand
    "Misdirection": (0.4, 0.0),                     # cancels the rival card's effects
}
DISCARD_EFFECTS = ("Clutching Claws", "Hiss and Slither")

KEEP_BASE = {"attack": 1.0, "defense": 0.8, "versatile": 1.1, "scheme": 0.9}
INVENTION_KEEP = 1.5
KEEP_SPECIAL = {"Gaze of Stone": 3.0, "Feint": 1.4, "A Momentary Glance": 1.6, "Hiss and Slither": 1.8,
                "Winged Frenzy": 1.0, "All Part of the Show": 2.0, "Set the Stage": 2.0, "A Magician Never Reveals His Secrets": 2.0}


CANCEL_KEEP = 1.6         # keep value a card that cancels the rival card's effects gains against a rival whose deck lives on effects
RELIANCE_LOW, RELIANCE_HIGH = 0.68, 0.80    # share of the rival's combat cards with effects: at or below LOW the cancel is worth nothing, at HIGH full
CHIP_DISCOUNT = 0.25       # a BOOSTED WITH hit that does not kill is worth this much less (at most) the healthier the target is: early chip damage


def cancels_effects(card) -> bool:
    """The card's IMMEDIATELY / DURING cancels ALL the effects of the opponent's card (read from the effects data): Feint,
    Misdirection. A partial cancel (Raphael's Break something: only DURING and AFTER, its IMMEDIATELY stays) does not
    count: such a card is an attack first, and hoarding it as an anti-effects answer starves the attacks."""
    fx = card_effects(card)
    return fx is not None and any(op["op"] == "cancel_effects" and not op.get("moments")
                                  for m in ("immediately", "during") for op in walk_ops(fx.moments.get(m) or []))


def effect_reliance(game: Game, me: int) -> float:
    """0..1: how much the rival's deck relies on card effects, from public data: the share of its attack / defense / versatile
    cards still to come (its full set minus what is in its discard pile; its whole set when that is empty) with an
    IMMEDIATELY / DURING / AFTER effect, weighted by the card's printed value (a strong card with an effect hurts more)."""
    st = game.players[1 - me]
    pool = [c for c in st.full_set if c not in st.gone and c.type != "scheme"] or [c for c in st.full_set if c.type != "scheme"]
    weight_of = lambda c: 1.0 + (c.value or 0)
    total = sum(weight_of(c) for c in pool)
    if not total:
        return 0.0
    withfx = 0.0
    for c in pool:
        fx = card_effects(c)
        if fx is not None and any(fx.moments.get(m) for m in ("immediately", "during", "after")):
            withfx += weight_of(c)
    return min(1.0, max(0.0, (withfx / total - RELIANCE_LOW) / (RELIANCE_HIGH - RELIANCE_LOW)))


def keep_value(card, hand, reliance: float = 0.0) -> float:
    """What the card is worth in the hand. `reliance` (effect_reliance of the rival) adds CANCEL_KEEP x reliance to a card
    that cancels the rival's card effects: it stays in the hand against an effect-heavy deck."""
    v = KEEP_SPECIAL.get(card.title, KEEP_BASE[card.type] + 0.25 * (card.value or 0)) + 0.1 * card.boost
    if "invention" in card.tags:       # worth playing early, never worth discarding (Donatello): its bonus lasts the game
        v += INVENTION_KEEP
    if reliance and cancels_effects(card):
        v += CANCEL_KEEP * reliance
    return v - 0.4 * (sum(1 for c in hand if c.title == card.title) - 1)


@dataclass
class Act:
    kind: str                       # attack | maneuver | glance | frenzy | scheme (any other interpreted hero's)
    value: float = 0.0
    fid: str = ""
    target: str = ""
    card: object = None
    moves: dict = field(default_factory=dict)
    boost: object = None
    spot: int | None = None
    total: float = 0.0
    exp_damage: float = 0.0
    p_win: float = 0.0
    p_kill: float = 0.0
    variant: str | None = None      # scheme: the SyntheticChooser policy the search evaluated it with (D2)
    sim: object = None              # scheme: the game the heuristic's simulation left (its expected state)


class Model:
    """What Medusa knows of the rival: composition of its deck minus what is already in the discard pile."""

    def __init__(self, game: Game, me: int):
        self.game, self.me, self.opp = game, me, 1 - me
        st = game.players[self.opp]
        self.pool = [c for c in st.full_set if c not in st.gone]
        self.n, self.h = len(self.pool), len(st.hand)
        self._cache: dict = {}

    def best_dist(self, key, value_fn, hand_size: int | None = None) -> list[tuple[float, int | None]]:
        key = (key, hand_size)
        if key in self._cache:
            return self._cache[key]
        vals = sorted((value_fn(c) for c in self.pool), key=lambda v: -1 if v is None else v, reverse=True)
        n, h = self.n, min(self.h if hand_size is None else hand_size, self.n)
        out: dict = {}
        if h == 0 or n == 0:
            out[None] = 1.0
        else:
            tot = comb(n, h)
            for i in range(n - h + 1):
                p = comb(n - 1 - i, h - 1) / tot
                out[vals[i]] = out.get(vals[i], 0) + p
        res = sorted(((p, v) for v, p in out.items()), key=lambda x: (x[1] is None, -(x[1] or 0)))
        self._cache[key] = res
        return res

    def attack_dist(self, f: Fighter):
        bonus = self.game.attack_bonus(f)
        return self.best_dist(("atk", f.name, bonus),
                              lambda c: c.value + bonus if c.can_attack and c.usable_by(f.name) else None)

    def committed_attack_dist(self, f: Fighter):
        """Value of the attack given that the rival has already played a card: without the "has no card" mass, renormalized."""
        bonus = self.game.attack_bonus(f)
        fn = lambda c: c.value + bonus if c.can_attack and c.usable_by(f.name) else None
        dist = [(p, v) for p, v in self.best_dist(("commit", f.name, bonus), fn, max(self.h, 1)) if v is not None]
        total = sum(p for p, _ in dist)
        if total == 0:
            return [(1.0, 0)]
        return [(p / total, v) for p, v in dist]

    def two_hit_dist(self, f: Fighter) -> list[tuple[float, int, int]]:
        """(probability, best, second best attack value) of the rival's hand for `f`, over the hands it can hold
        (0 where it has no second attack): what two actions in a row can hit with. The lowest-ranked chosen card of
        the sorted pool is the best of the hand, the next one the second best."""
        bonus = self.game.attack_bonus(f)
        key = ("two", f.name, bonus, self.h)
        if key in self._cache:
            return self._cache[key]
        vals = sorted((c.value + bonus if c.can_attack and c.usable_by(f.name) else 0 for c in self.pool), reverse=True)
        n, h = self.n, min(self.h, self.n)
        out: dict = {}
        if h == 0:
            out[(0, 0)] = 1.0
        elif h == 1:
            for i in range(n):
                out[(vals[i], 0)] = out.get((vals[i], 0), 0) + 1 / n
        else:
            tot = comb(n, h)
            for i in range(n - 1):
                for j in range(i + 1, n - h + 2):
                    p = comb(n - 1 - j, h - 2) / tot
                    if p:
                        out[(vals[i], vals[j])] = out.get((vals[i], vals[j]), 0) + p
        res = [(p, a, b) for (a, b), p in out.items()]
        self._cache[key] = res
        return res

    def defense_dist(self, t: Fighter):
        destiny = self.game.destiny_count(self.opp)
        bonus = self.game.defense_bonus_total(t.owner)    # the rival's public ONGOING (Fight Or Flight) and tucked inventions
        return self.best_dist(("def", t.name, destiny, bonus),
                              lambda c: (destiny if c.title == ON_EARTH else c.value) + bonus
                              if c.can_defend and c.usable_by(t.name) else None)

    def p_boost(self, need: int) -> float:
        if need <= 0:
            return 1.0
        if self.h == 0 or self.n == 0:
            return 0.0
        k = sum(1 for c in self.pool if c.boost >= need)
        return 1 - comb(self.n - k, min(self.h, self.n)) / comb(self.n, min(self.h, self.n))

    def destinies_unseen(self) -> int:
        return sum(1 for c in self.pool if c.destiny)


def play_signature(g: Game, me: int, card) -> tuple:
    """What a scheme may change, as comparable data, with the played card ignored (it moves from the hand to the
    discard pile): both players' cards (decks sorted: a shuffle that moved nothing is no change, but a rival deck top
    that was reordered does show up through the rival's unsorted deck), the pieces, the ONGOINGs, the statuses,
    modifiers and counters, and the draws."""
    ids = lambda cards: [c.card_id for c in cards if c.card_id != card.card_id]
    mine, rival = g.players[me], g.players[1 - me]
    return (ids(mine.hand), sorted(ids(mine.deck)), ids(mine.discard), g.drawn[me],
            ids(rival.hand), ids(rival.deck), ids(rival.discard),
            [(fid, f.hp, f.pos, f.alive) for fid, f in sorted(g.fighters.items())],
            [g.fx.ongoing_card_id(p) for p in (0, 1)], repr(g.fx.statuses), repr(g.fx.modifiers), repr(g.fx.counters))


def weight(t: Fighter) -> float:
    return W_HERO if t.hero else W_SIDEKICK


def unseen_copies(game: Game, owner: int) -> Counter:
    """Copies per title of `owner`'s cards that are not in their public discard: still in hand or deck, still to
    come for them (for the rival: what the Model also treats as possible)."""
    st = game.players[owner]
    left = Counter(c.title for c in st.full_set)
    left.subtract(c.title for c in st.gone)
    return left


def fighter_profile(game: Game, f: Fighter) -> dict | None:
    return None if f.hero else game.players[f.owner].hero.fighter_profile(f.name)


def stake(game: Game, f: Fighter, prof: dict) -> float:
    """What the owner of sidekick `f` still stands to lose with it (AI profile, sparring/ai_profile.py): the
    exclusive cards it alone can play and the effects that need it alive, counted by the copies not yet in the
    owner's discard. The living pieces of a group (3 Harpies) share it: each carries 1/n^2 of it, so killing the
    first barely matters and the last one alive carries all (the cards die with it). Their attack threat is not
    shared (`kill_value`): each piece killed is one attacker less."""
    left = unseen_copies(game, f.owner)
    total = sum(e["impact"] * max(0, min(e["copies"], left[e["title"]])) for e in prof["exclusive"] if e["impact"] > 0)
    total += sum(r["impact"] * (1 if r["kind"] == "ability" else max(0, min(r["copies"], left[r["source"]])))
                 for r in prof["requires_alive"])
    alive = sum(1 for x in game.own(f.owner) if x.name == f.name)
    return total / (alive * alive)


def kill_value(game: Game, f: Fighter) -> float:
    """What killing sidekick `f` is worth to its rival (and costs its owner): the body, a share of its stake and
    its attack threat; at most KILL_CAP. Finishing the rival hero is worth HERO_KILL + LETHAL in `attack_eval`, so
    no sidekick kill outranks it; a big hit on the hero that does not finish it may lose to a valuable kill."""
    prof = fighter_profile(game, f)
    if prof is None:
        return KILL_SIDEKICK
    threat = THREAT_WEIGHT * prof["attack"]["mean"] * (RANGED_THREAT if prof["ranged"] else 1.0)
    return min(KILL_CAP, KILL_BASE + STAKE_WEIGHT * stake(game, f, prof) + threat)


def protect_factor(game: Game, f: Fighter) -> float:
    return max(1.0, kill_value(game, f) / KILL_SIDEKICK)


def scheme_fighter(game: Game, me: int, card) -> Fighter | None:
    """The fighter that plays a scheme: the hero if the card lets him, else the first living fighter it does (Houdini's Set
    the Stage is Bess's). None when nobody can."""
    return next((f for f in sorted(game.own(me), key=lambda f: (not f.hero, f.fid)) if card.usable_by(f.name)), None)


def chip_factor(f: Fighter, n: int) -> float:
    """1 for a blow that kills; otherwise it shrinks with the health the target keeps (a hit on a fighter at full health is
    worth CHIP_DISCOUNT less than the same hit on one that is nearly dead)."""
    if f.hp <= n or not f.max_hp:
        return 1.0
    return 1.0 - CHIP_DISCOUNT * (f.hp - n) / f.max_hp


def boost_effect_value(game: Game, me: int, card) -> float:
    """What the BOOSTED WITH of `card` is worth to `me` if the card is spent as a boost now (0 for a card without one), read
    from the card's `boost` moment: the cards it draws (unknown: CARD_VALUE each), the action it gains (only on the own turn),
    the hit points it heals or deals (the best blow on a rival, a kill and the hero's finishing blow included) and the
    look at the rival's hand that strips a card from it. Whoever spends the card still pays its keep value."""
    fx = card_effects(card)
    ops = fx.moments.get("boost") if fx is not None else None
    if not ops:
        return 0.0
    hero = game.hero(me)
    total = 0.0
    for op in walk_ops(ops):
        kind = op["op"]
        n = op["amount"] if isinstance(op.get("amount"), int) else 1
        if kind == "draw" and op["player"] == "owner":
            total += CARD_VALUE * n
        elif kind == "gain_action" and game.turn == me:
            total += BOOST_ACTION * n
        elif kind == "heal" and hero.alive:
            total += W_MEDUSA_HP * min(n, hero.max_hp - hero.hp)
        elif kind == "damage":
            total += max((weight(f) * min(n, f.hp) * chip_factor(f, n) + ((HERO_KILL + LETHAL if f.hero else kill_value(game, f)) if f.hp <= n else 0.0)
                          for f in game.foes(me)), default=0.0)
        elif kind == "look_hand" and game.players[1 - me].hand:
            total += LOOK_VALUE + STRIP_VALUE
    return total


def free_boosts(game: Game, me: int, card, hand) -> list:
    """The cards the hand would spend to BOOST `card` with by its own text (`may_boost`, `max_boosts`): the biggest boosts,
    best BOOSTED WITH first on a tie. Empty when the card has no free BOOST or nothing in the hand can be spent."""
    limit = boost_limit(card)
    spare = [x for x in hand if x is not card and can_be_boost(x)]
    return sorted(spare, key=lambda x: (-x.boost, -boost_effect_value(game, me, x), x.card_id))[:limit]


def is_striker(game: Game, f: Fighter) -> bool:
    prof = fighter_profile(game, f)
    return prof is not None and prof["role"] == "striker"


class MedusaAI(Controller):
    """No randomness of its own: ties are broken by id, so given the game (seed) it is deterministic."""

    def __init__(self, me: int = 0):
        self.me = me
        self._plan_moves: dict[str, int] = {}
        self._plan_spot: int | None = None
        self._strike_cache: dict = {}
        self._effect_ai = None

    # ---------- game setup ----------
    def should_mulligan(self, game: Game, hand) -> bool:
        """Bad opening hand: no card to attack with, or three or more that are no use for attacking (schemes and
        pure defenses). The mulligan is once only (the session applies it)."""
        attackers = sum(1 for c in hand if c.can_attack)
        return attackers == 0 or len(hand) - attackers >= 3

    def choose_setup(self, game: Game, hand) -> dict[str, int]:
        """Starting spaces: Medusa on her start space and the Harpies in their start zone. With Clutching Claws or The
        Hounds of Mighty Zeus in hand they move forward (the best `harpy_score` against the rival pieces already
        placed); without them they stay back, as far as possible from Hellboy and close to Medusa."""
        me, b = self.me, game.board
        start = game.start_spaces[me]
        taken = {f.pos for f in game.foes(me)} | {start}
        zone = [s for s in sorted(b.spaces) if b.share_zone(start, s) and s not in taken]
        forward = any(c.title in ("Clutching Claws", "The Hounds of Mighty Zeus") for c in hand)
        plan = {game.hero(me).fid: start}
        for h in sorted((f for f in game.own(me) if not f.hero), key=lambda f: f.fid):
            pool = zone or [s for s in sorted(b.spaces) if s not in taken]
            if forward:
                best = max(pool, key=lambda s: (self.harpy_score(game, h, s), -s))
            else:
                best = max(pool, key=lambda s: (-self.harpy_score(game, h, s), -b.distance(start, s), -s))
            plan[h.fid] = best
            taken.add(best)
            zone = [s for s in zone if s != best]
        return plan

    # ---------- start of turn ----------
    def pick_ability_target(self, game: Game) -> Fighter | None:
        """Target of Medusa's start-of-turn ability; with any other hero there is (as yet) no ability."""
        medusa = game.hero(self.me)
        if medusa.name != "Medusa":
            return None
        targets = [f for f in game.foes(self.me) if game.board.share_zone(medusa.pos, f.pos)]
        if not targets:
            return None
        kills = [f for f in targets if f.hp <= 1]
        if kills:
            return min(kills, key=lambda f: (not f.hero, f.fid))
        side = [f for f in targets if not f.hero]
        if side and min(f.hp for f in side) <= 3:
            return min(side, key=lambda f: (f.hp, f.fid))
        heroes = [f for f in targets if f.hero]
        return heroes[0] if heroes else side[0]

    def take_turn(self, game: Game) -> None:
        target = self.pick_ability_target(game)
        if target:
            game.use_ability(self.me, GAZE, target)
        while game.actions_left > 0 and game.winner is None and game.hero(self.me).alive:
            self.execute(game, self.plan(game))

    # ---------- planning ----------
    def plan(self, game: Game) -> Act:
        model = Model(game, self.me)
        ranked = self.candidates(game, model)
        kill = self.lethal_attack(game, ranked)
        # an act the ranking already sees winning the game (Pact Of Peace on a 1 HP hero) beats the shortcut
        if kill is not None and not (ranked[0] is not kill and ranked[0].total >= DEATH / 2):
            return kill
        width = TOP_FIRST_DESPERATE if self.desperation(game) >= 0.3 else TOP_FIRST
        firsts = ranked[:width] + self.approach_acts(game, ranked[width:])
        if game.actions_left < 2:
            return firsts[0]
        best, best_v = None, None
        for a1 in firsts:
            g1 = self.apply_expected(game, a1)
            second = self.outcome(g1) if g1.winner is not None else self.candidates(g1, model)[0].total
            total = a1.value + second
            if best_v is None or total > best_v + 1e-9:
                best, best_v = a1, total
        return best

    def lethal_attack(self, game: Game, ranked: list[Act]) -> Act | None:
        """The attack to open with when this turn can finish the rival hero: one that kills with LETHAL_GO or more
        chance, or (two actions) the biggest of two different attacks whose expected damage together clears its hit points
        by TWO_ATTACK_MARGIN.
        Survival terms never hold it back: a win now needs no defense next turn."""
        rival = game.hero(1 - self.me)
        hits = [a for a in ranked if a.kind == "attack" and a.target == rival.fid]
        sure = [a for a in hits if a.p_kill >= LETHAL_GO]
        if sure:
            return max(sure, key=lambda a: (a.p_kill, a.value))
        if game.actions_left >= 2:
            ordered = sorted(hits, key=lambda a: -a.exp_damage)
            for i, first in enumerate(ordered):
                second = next((b for b in ordered[i + 1:] if b.card.title != first.card.title), None)
                if second is not None and first.exp_damage + second.exp_damage >= rival.hp + TWO_ATTACK_MARGIN:
                    return first
        return None

    def approach_acts(self, game: Game, rest: list[Act]) -> list[Act]:
        """Maneuvers outside the top acts that end in reach of a rival when none is in reach now and the hand has an
        attack: their worth is the attack the second action makes of them, which the one-step ranking cannot see
        (a hero with fear of the rival's hits would otherwise stand still and draw until the hand overflows)."""
        hero = game.hero(self.me)
        if hero.name == "Medusa" or any(game.can_attack(hero, e) for e in game.foes(self.me)):
            return []
        if not any(c.can_attack and c.usable_by(hero.name) for c in game.players[self.me].hand):
            return []
        board, foes = game.board, game.foes(self.me)
        return [a for a in rest if a.kind == "maneuver" and hero.fid in a.moves
                and any(board.can_reach_target(a.moves[hero.fid], e.pos, hero.ranged) for e in foes)][:APPROACH_TOP]

    def candidates(self, game: Game, model: Model) -> list[Act]:
        """Legal actions ordered by own value + value of the position they leave. Passing does not exist: a maneuver without moving still draws."""
        acts = self.attack_acts(game, model) + self.scheme_acts(game, model) + self.maneuver_acts(game, model)
        for a in acts:
            g = self.apply_expected(game, a)
            if g.winner is not None:
                a.total = a.value + self.outcome(g)
                continue
            a.total = a.value + self.position_value(g, model)
            if g.actions_left == 0:
                a.total += self.terminal_value(g, model)
        unique = {(a.kind, a.fid, a.target, a.card and a.card.card_id, a.boost and a.boost.card_id,
                   tuple(sorted(a.moves.items())), a.spot, a.variant): a for a in reversed(acts)}   # the 1st of each one
        return sorted(unique.values(), key=lambda a: -a.total)

    def outcome(self, g: Game) -> float:
        """A game finished in the expected state: lost (exhaustion) or won (a scheme that finishes the rival)."""
        return DEATH if g.winner == self.me else -DEATH

    # ----- attacks -----
    def attack_acts(self, game: Game, model: Model) -> list[Act]:
        hand = game.players[self.me].hand
        out = []
        for f in game.own(self.me):
            for t in game.foes(self.me):
                if not game.can_attack(f, t):
                    continue
                seen = set()
                for c in hand:
                    if c.title in seen or not c.can_attack or not c.usable_by(f.name):
                        continue
                    seen.add(c.title)
                    value, dmg, kill = self.attack_outcome(game, model, f, t, c)
                    out.append(Act("attack", value, f.fid, t.fid, c, exp_damage=dmg, p_win=self.p_win_of(game, model, f, t, c),
                                   p_kill=kill))
        return out

    def eval_attack(self, game: Game, model: Model, f: Fighter, t: Fighter, c) -> float:
        return self.attack_eval(game, model, f, t, c)[0]

    def card_value(self, game: Game, f: Fighter, t: Fighter, c) -> float:
        """The value an attack card will have against `t`: the printed one, or the one its DURING sets when that is
        known now (Raphael's Slapshot with Casey next to the target, Payback time! after a lost combat)."""
        if c.title == "Slapshot" and any(o.name == "Casey Jones" and o.pos in game.board.adj[t.pos]
                                         for o in game.own(f.owner) if o.pos is not None):
            return 6.0
        if c.title == "Payback time!" and game.fx.lost[f.owner]:
            return 5.0
        if c.title == MASTER and self.strange_with_wong(game, f.owner):
            return 4.0
        return float(c.value)

    @staticmethod
    def strange_with_wong(game: Game, owner: int) -> bool:
        """Doctor Strange and Wong stand next to each other (Master of Kamar-Taj is worth 4)."""
        hero = game.hero(owner)
        return hero.pos is not None and any(o.name == "Wong" and o.pos in game.board.adj[hero.pos] for o in game.own(owner))

    @staticmethod
    def cloak_ignores(game: Game, f: Fighter, t: Fighter, c) -> bool:
        """Cloak of Levitation: Doctor Strange himself is next to the opposing fighter, whose card then counts for nothing."""
        hero = game.hero(f.owner)
        return c.title == CLOAK and hero.pos is not None and t.pos is not None and t.pos in game.board.adj[hero.pos]

    def p_win_of(self, game: Game, model: Model, f: Fighter, t: Fighter, c) -> float:
        atk = self.card_value(game, f, t, c) + game.attack_bonus(f)
        atk += BOOST_RELIANCE * sum(x.boost for x in free_boosts(game, self.me, c, game.players[self.me].hand))
        atk += self.during_gain(game, c)
        ignore = self.cloak_ignores(game, f, t, c)
        return sum(p for p, dv in model.defense_dist(t) if atk - (0 if ignore else (dv or 0)) >= 1)

    def during_gain(self, game: Game, c) -> float:
        """What the DURING of a Donatello attack is expected to add to its value: Electro grenade removes up to 4
        attack or versatile cards of the own discard pile (+1 each), Untested enhancements adds the boost of the
        bottom card of the deck (the average of the cards still to come, discounted: it is unknown)."""
        mine = game.players[self.me]
        if c.title == ELECTRO_GRENADE:
            return min(4, sum(1 for x in mine.discard if x.can_attack))
        if c.title == UNTESTED:
            unseen = [x for x in mine.full_set if x not in mine.hand and x not in mine.gone]
            return BOOST_RELIANCE * sum(x.boost for x in unseen) / len(unseen) if unseen else 0.0
        if c.title in BLIND_BOOST:      # free boosts from the top of the deck: the bot knows what its deck still holds
            times, limit = BLIND_BOOST[c.title]
            unseen = [x for x in mine.full_set if x not in mine.hand and x not in mine.gone]
            gain = BOOST_RELIANCE * times * sum(x.boost for x in unseen) / len(unseen) if unseen else 0.0
            return gain if limit is None else min(gain, max(0.0, limit - (c.value or 0)))
        return 0.0

    def attack_eval(self, game: Game, model: Model, f: Fighter, t: Fighter, c) -> tuple[float, float]:
        return self.attack_outcome(game, model, f, t, c)[:2]

    def attack_outcome(self, game: Game, model: Model, f: Fighter, t: Fighter, c) -> tuple[float, float, float]:
        """(value, expected damage, probability of killing `t`) of attacking `t` with `f` and card `c`."""
        hand = game.players[self.me].hand
        atk, cost = self.card_value(game, f, t, c) + game.attack_bonus(f), CARD_VALUE + 0.05 * c.boost    # ANUNG UN RAMA's +2, a live ONGOING
        boosts = free_boosts(game, self.me, c, hand)
        atk += BOOST_RELIANCE * sum(x.boost for x in boosts)
        cost += CARD_VALUE * len(boosts)
        effects = BOOST_RELIANCE * sum(boost_effect_value(game, self.me, x) for x in boosts)     # what spending them also does
        atk += self.during_gain(game, c)
        if "invention" in c.tags:
            cost -= INVENTION_PLAY
        e_net = p_win = p_kill = gaze_dmg = 0.0
        ignore = self.cloak_ignores(game, f, t, c)
        for p, dv in model.defense_dist(t):
            net = max(0.0, atk - (0 if ignore else (dv or 0)))
            won = net >= 1
            e_net += p * min(net, t.hp)
            p_win += p * won
            extra = min(GAZE_DAMAGE, max(0.0, t.hp - net)) if (c.title == "Gaze of Stone" and won) else 0.0
            gaze_dmg += p * extra
            p_kill += p * (net + extra >= t.hp)
        w = weight(t)
        value = w * (e_net + gaze_dmg) - cost + effects
        if p_kill > 0:      # the kill prize is only looked up when the blow can kill (it scans both decks)
            value += (HERO_KILL + LETHAL if t.hero else kill_value(game, t)) * p_kill   # finishing the hero wins the game
        if t.hero and f.owner == self.me:
            # damage already done is worth more than what could only be done later (`win_progress` discounts it)
            value += self.desperation(game) * WIN_PRIZE * (e_net + gaze_dmg) / max(t.hp, 1)
        always, on_win = AFTER_BONUS.get(c.title, (0.0, 0.0))
        value += always + on_win * p_win
        if c.title == RINGS:             # the damage dealt heals the fighter and the friendly ones beside it (only what is missing counts)
            near = [o for o in game.own(f.owner) if o is f or (o.pos is not None and f.pos is not None and o.pos in game.board.adj[f.pos])]
            value += W_MEDUSA_HP * min(e_net, sum(o.max_hp - o.hp for o in near)) * p_win
        if c.title in DISCARD_EFFECTS:
            decisive = p_kill >= 0.5 or (p_win >= 0.85 and e_net >= 5)
            if not decisive:
                value -= self.transform_penalty(game, model)
        return value, e_net + gaze_dmg, p_kill

    def transform_penalty(self, game: Game, model: Model) -> float:
        opp = 1 - self.me
        if game.form(opp) == ANUNG or model.destinies_unseen() == 0:
            return 0.0
        remaining = 6 - game.destiny_count(opp)
        return TRANSFORM_PENALTY.get(remaining, 0.0)

    # ----- planes -----
    def scheme_acts(self, game: Game, model: Model) -> list[Act]:
        """Medusa's two schemes keep their planned targets (C5 presets); any other interpreted hero's scheme is
        valued by simulating it (`scheme_act`), one act per title."""
        medusa = game.hero(self.me)
        interpreted = game.fx.interprets(self.me)
        out, seen = [], set()
        for c in game.players[self.me].hand:
            if not c.is_scheme or c.title in seen:
                continue
            fighter = scheme_fighter(game, self.me, c)
            if fighter is None:
                continue
            seen.add(c.title)
            if c.title == "A Momentary Glance":
                for t in game.foes(self.me):
                    if game.board.share_zone(medusa.pos, t.pos):
                        dmg = min(GLANCE_DAMAGE, t.hp)
                        v = weight(t) * dmg + (kill_value(game, t) if not t.hero and t.hp <= GLANCE_DAMAGE else 0) - CARD_VALUE
                        out.append(Act("glance", v, medusa.fid, t.fid, c))
            elif c.title == "Winged Frenzy":
                out.append(self.frenzy_act(game, model, c))
            elif interpreted:
                out.append(self.scheme_act(game, c, fighter))
        return [a for a in out if a is not None]

    def scheme_act(self, game: Game, card, fighter: Fighter | None = None) -> Act | None:
        """A scheme played on a blind clone with EffectAI deciding inside (`EffectAI.scheme_outcome`): its value is
        the material it swings (kills, the ONGOING it brings in or replaces), the cards it draws (unknown: CARD_VALUE
        each) minus those it gives up (their keep_value) and the card itself, plus the actions it grants."""
        me = self.me
        fighter = fighter or game.hero(me)
        after = self.effect_ai().scheme_outcome(game, card, me, fighter.fid)
        if after is None:
            return None
        hand, hand_after = game.players[me].hand, after.players[me].hand
        lost = [c for c in hand if c is not card and c not in hand_after]
        gained = sum(1 for c in hand_after if c not in hand)
        value = self.effect_ai().material_delta(game, after, me) - CARD_VALUE
        value += CARD_VALUE * gained - sum(keep_value(c, hand) for c in lost)
        gained = after.actions_left - (game.actions_left - 1)
        if not self.scheme_changed_nothing(game, after, card):
            value += ACTION_VALUE * gained       # an action handed back is only worth something when the card did more
        return Act("scheme", value, fighter.fid, "", card, sim=after)

    def scheme_changed_nothing(self, game: Game, after: Game, card) -> bool:
        """The scheme left everything but its own action where it was (`play_signature`): Searing Clarity with no
        non-scheme card in the discard pile shuffles nothing and only returns its own action. `after` carries the
        signature of the (blind) game it was played on, taken just before the play."""
        before = getattr(after, "pre_play_signature", None) or play_signature(game, self.me, card)
        return before == play_signature(after, self.me, card)

    def frenzy_act(self, game: Game, model: Model, card) -> Act | None:
        g = game.clone()
        moves = {}
        for f in sorted(g.own(self.me), key=lambda x: x.fid):
            dest = self.best_dest(g, model, f, 3, True)
            moves[f.fid] = dest
            f.pos = dest
        dead = [f for f in g.own(self.me, alive_only=False) if f.name == "Harpy" and not f.alive]
        spot, value = None, -CARD_VALUE
        if dead:
            medusa = g.hero(self.me)
            taken = {f.pos for f in g.fighters.values() if f.alive}
            options = sorted(s for s in g.board.spaces if s not in taken and g.board.share_zone(medusa.pos, s))
            if options:
                spot = max(options, key=lambda s: (self.harpy_score(g, dead[0], s), -s))
                value += HARPY_VALUE
        return Act("frenzy", value, "medusa", "", card, moves=moves, spot=spot)

    # ----- maneuver -----
    def maneuver_acts(self, game: Game, model: Model) -> list[Act]:
        hand = game.players[self.me].hand
        medusa = game.hero(self.me)
        variants: list = [(None, 0.0)]
        seen = set()
        rel = effect_reliance(game, self.me)
        net = lambda c: keep_value(c, hand, rel) * 0.5 - boost_effect_value(game, self.me, c)     # its BOOSTED WITH pays part of the price
        for c in sorted(hand, key=lambda c: (net(c), -c.boost, c.card_id)):
            if can_be_boost(c) and c.boost not in seen:    # for each reach, the card that hurts least to spend
                seen.add(c.boost)
                variants.append((c, net(c)))
        out = []
        by_extra: dict[tuple, list[int]] = {}    # the best destinations depend only on the reach, not on the card
        for boost, cost in variants:
            extra = boost.boost if boost else 0
            places = boost is not None and game.fx.hero_rule(self.me, "maneuver_boost_places_hero")     # ESCAPE ARTIST
            if (extra, places) not in by_extra:
                if places:
                    taken = {f.pos for f in game.fighters.values() if f.alive and f is not medusa}
                    options = ({s for s in game.board.spaces if s not in taken} if game.fx.can_move(medusa) else set()) | {medusa.pos}
                else:
                    options = game.legal_moves(medusa, medusa.move + extra) | {medusa.pos}
                ranked = sorted(((-self.position_value(game, model, {medusa.fid: d}), d) for d in options))
                # besides the best by position, those that leave Medusa within range of a rival: moving and attacking
                # in the same double action (position alone would never choose them if the rival is dangerous)
                striking = [x for x in ranked if any(game.board.can_reach_target(x[1], e.pos, medusa.ranged)
                                                     for e in game.foes(self.me))]
                by_extra[(extra, places)] = list(dict.fromkeys(d for _, d in ranked[:3] + striking[:2]))
            scored = by_extra[(extra, places)]
            for d in dict.fromkeys(scored + [medusa.pos]):
                for harpies_advance in (True, False):
                    g = game.clone()
                    g.fighters[medusa.fid].pos = d
                    moves = {medusa.fid: d}
                    exhausting = not g.players[self.me].deck
                    for h in sorted((x for x in g.own(self.me) if not x.hero), key=lambda x: x.fid):
                        if exhausting and h.hp <= EXHAUST_DAMAGE:
                            continue    # drawing with an empty deck kills her before she moves
                        if harpies_advance:
                            opts = g.legal_moves(h, h.move + extra) | {h.pos}
                            h.pos = max(opts, key=lambda s: (self.harpy_score(g, h, s), -s))
                        moves[h.fid] = h.pos
                    idle = medusa.name != "Medusa" and boost is None and all(game.fighters[fid].pos == dest for fid, dest in moves.items())
                    out.append(Act("maneuver", CARD_VALUE - cost - (IDLE_MANEUVER if idle else 0.0), medusa.fid, "", None,
                                   moves=moves, boost=boost))
        return out

    # ---------- expected state ----------
    def expected_draw(self, g: Game, n: int = 1) -> None:
        """Simulated draw: with a deck, an unknown card (`phantom_draws`); without a deck, the engine's exhaustion."""
        p = g.players[self.me]
        for _ in range(n):
            if g.winner is not None:
                return
            if p.deck:
                p.deck.pop()
                g.phantom_draws += 1
            else:
                for f in g.own(self.me):
                    g.damage(f, EXHAUST_DAMAGE, "exhaustion")

    def apply_expected(self, game: Game, a: Act) -> Game:
        g = game.clone()
        hand = g.players[self.me].hand
        if a.kind == "attack":
            hand.remove(a.card)
            g.players[self.me].discard.append(a.card)
            t = g.fighters[a.target]
            t.hp -= a.exp_damage
            if t.hp <= 0 and not t.hero:
                t.alive, t.pos = False, None
            if a.card.title == "Snipe":
                self.expected_draw(g, 1)
            elif a.card.title == "Regroup":
                self.expected_draw(g, 2 if a.p_win > 0 else 1)   # pessimistic: exhaustion is not played on a coin flip
        elif a.kind == "maneuver":
            self.expected_draw(g, 1)
            bonus_actions = 0
            if a.boost is not None:
                hand.remove(a.boost)
                g.players[self.me].discard.append(a.boost)
                bonus_actions = self.expected_boost_effect(g, a.boost)
            for fid, d in a.moves.items():
                if g.fighters[fid].alive:
                    g.fighters[fid].pos = d
        elif a.kind == "glance":
            hand.remove(a.card)
            t = g.fighters[a.target]
            t.hp = max(0.0, t.hp - GLANCE_DAMAGE)
        elif a.kind == "frenzy":
            hand.remove(a.card)
            for fid, d in a.moves.items():
                g.fighters[fid].pos = d
        elif a.kind == "scheme":        # the simulation already spent the action and granted what the card gives
            return a.sim.clone()
        g.actions_left -= 1
        if a.kind == "maneuver":
            g.actions_left += bonus_actions
        return g

    def expected_boost_effect(self, g: Game, card) -> int:
        """The BOOSTED WITH of a card spent in the maneuver, applied to the expected state: draws (unknown cards) and heals;
        returns the actions it gains (the blow of a damage is valued, not simulated)."""
        fx = card_effects(card)
        gained = 0
        for op in walk_ops(fx.moments.get("boost", [])) if fx is not None else ():
            n = op["amount"] if isinstance(op.get("amount"), int) else 1
            if op["op"] == "draw" and op["player"] == "owner":
                self.expected_draw(g, n)
            elif op["op"] == "gain_action" and g.turn == self.me:
                gained += n
            elif op["op"] == "heal" and g.hero(self.me).alive:
                g.heal(g.hero(self.me), n)
        return gained

    # ---------- time: deck, hand and desperation ----------
    def draw_budget(self, game: Game) -> int:
        """Draws Medusa can still afford without dying: the deck and the exhaustions her HP can bear."""
        medusa = game.hero(self.me)
        return max(0, len(game.players[self.me].deck) + ceil(medusa.hp / EXHAUST_DAMAGE) - 1)

    def avg_unseen_keep(self, game: Game) -> float:
        p = game.players[self.me]
        unseen = list(p.full_set)
        for c in p.hand + p.gone:
            if c in unseen:
                unseen.remove(c)
        return sum(keep_value(c, [c]) for c in unseen) / len(unseen) if unseen else KEEP_BASE["attack"]

    def terminal_value(self, game: Game, model: Model | None = None) -> float:
        """Cost of closing the turn like this: discarding what exceeds the hand limit and spending scarce draws."""
        p = game.players[self.me]
        over = len(p.hand) + game.phantom_draws - game.hand_cap(self.me)
        cost = 0.0
        if over > 0:
            pool = sorted([keep_value(c, p.hand) for c in p.hand] + [self.avg_unseen_keep(game)] * game.phantom_draws)
            cost = sum(pool[:over])
        return -cost - self.deck_cost(game, model or Model(game, self.me))

    def race(self, game: Game, model: Model) -> tuple[float, float]:
        """(turns until the bot kills the rival hero, turns until the rival hero kills the bot's), from the average
        card of each deck against the other's likely best answer. Sidekicks are left out: they decide fights, not games."""
        me, rival = game.hero(self.me), game.hero(1 - self.me)
        mine = game.players[self.me].full_set
        atk = [c.value + game.attack_bonus(me) for c in mine if c.can_attack and c.usable_by(me.name)]
        dfn = [c.value for c in mine if c.can_defend and c.usable_by(me.name)]
        avg_atk, avg_def = (sum(atk) / len(atk) if atk else 0.0), (sum(dfn) / len(dfn) if dfn else 0.0)
        out = sum(p * max(0.0, avg_atk - (dv or 0)) for p, dv in model.defense_dist(rival))
        inc = sum(p * max(0.0, v - avg_def) for p, v in model.attack_dist(rival) if v is not None)
        return (rival.hp / (ATTACKS_PER_TURN * max(out, MIN_NET)), me.hp / (ATTACKS_PER_TURN * max(inc, MIN_NET)))

    def deck_cost(self, game: Game, model: Model) -> float:
        """What the deck left costs at the end of the turn, by strategy (see the module docstring): the scarcity
        table scaled down when the race is won before the deck runs out, plus the exhaustion that a game longer
        than the deck will bring, growing smoothly with the shortfall."""
        me, rival = game.hero(self.me), game.hero(1 - self.me)
        if not me.alive or not rival.alive:
            return 0.0
        t_kill, t_die = self.race(game, model)
        length = min(t_kill, LONG_GAME)
        deck = len(game.players[self.me].deck)
        scale = min(1.0, max(DECK_SCARCITY_FLOOR, length / (deck / DRAWS_PER_TURN + 1)))
        shortfall = max(0.0, length * DRAWS_PER_TURN - deck)
        # quadratic up to BILL_SPAN draws of shortfall (marginal draw cost 0 -> EXHAUST_BILL), linear after
        owed = shortfall * shortfall / (2 * BILL_SPAN) if shortfall < BILL_SPAN else shortfall - BILL_SPAN / 2
        losing = 1 + max(0.0, 1 - t_die / max(t_kill, MIN_NET))     # up to x2: exhaustion on top of a lost race
        return DECK_SCARCITY.get(self.draw_budget(game), 0.0) * scale + EXHAUST_BILL * losing * owed

    def desperation(self, game: Game) -> float:
        """0 (no problem) to 1 (clearly losing): own HP against the rival hero's, fallen Harpies and
        the exhaustion clock."""
        me, rival = game.hero(self.me), game.hero(1 - self.me)
        if not me.alive or not rival.alive:
            return 0.0
        hp_c = min(1.0, max(0.0, (1 - me.hp / max(rival.hp, 0.5)) / 0.6))
        harpies = [f for f in game.own(self.me, alive_only=False) if not f.hero]
        side_c = sum(1 for f in harpies if not f.alive) / len(harpies) if harpies else 0.0
        clock_c = min(1.0, max(0.0, 1 - self.draw_budget(game) / CLOCK_HORIZON))
        return min(1.0, max(0.0, ((hp_c + side_c + clock_c) / 3 - 0.25) / 0.75))

    def win_progress(self, game: Game, model: Model, medusa: Fighter, rival: Fighter) -> float:
        """Fraction of the rival hero's HP that my two best attacks in hand would take away."""
        hand = game.players[self.me].hand
        dmgs = sorted((self.attack_eval(game, model, medusa, rival, c)[1] for c in hand
                       if c.can_attack and c.usable_by(medusa.name)), reverse=True)
        return min(1.0, sum(dmgs[:2]) / rival.hp) if rival.hp > 0 else 1.0

    def strike_spots(self, board, pos: int, ranged: bool) -> list[int]:
        key = (board.key, pos, ranged)
        if key not in self._strike_cache:
            self._strike_cache[key] = [s for s in board.spaces if board.can_reach_target(s, pos, ranged)]
        return self._strike_cache[key]

    def position_value(self, game: Game, model: Model, override: dict | None = None) -> float:
        pos = {f.fid: f.pos for f in game.fighters.values() if f.alive}
        if override:
            pos.update(override)
        mine = [f for f in game.own(self.me) if f.fid in pos]
        foes = [e for e in game.foes(self.me) if e.fid in pos]   # a foe killed in the projection has no square
        board = game.board
        occupied = set(pos.values())
        hand = game.players[self.me].hand
        despair = self.desperation(game)
        score = 0.0
        despair_fear = 1 - DESPERATE_FEAR_DROP * despair
        for e in foes:
            extra = game.form(1 - self.me) == ANUNG and e.hero
            best = 0.0
            for t in mine:
                spots = [s for s in self.strike_spots(board, pos[t.fid], e.ranged) if s == pos[e.fid] or s not in occupied]
                steps = min((board.distance(pos[e.fid], s) for s in spots), default=MAX_ENEMY_STEPS)
                if steps >= MAX_ENEMY_STEPS:
                    continue
                need = steps - e.move - (ANUNG_FREE_MOVE if extra else 0)
                p_reach = model.p_boost(need) * (BOOST_DISCOUNT if need > 0 else 1.0)
                if p_reach <= 0:
                    continue
                twice = DOUBLE_ATTACK if steps == 0 else 1.0     # already in reach: the rival has an action to spare for a second blow
                my_def = max((c.value for c in hand if c.can_defend and c.usable_by(t.name)), default=0)
                exp = p_dead = 0.0
                for p, v in model.attack_dist(e):
                    if v is None:
                        continue
                    dmg = max(0, v - my_def)
                    exp += p * min(dmg, t.hp)
                    p_dead += p * (dmg >= t.hp)
                if not t.hero:
                    p_hit = sum(p for p, v in model.attack_dist(e) if v is not None and v > my_def)
                    danger = HARPY_VALUE * t.max_hp * p_hit      # positional fear is not scaled for a single prized piece (Lobster, Koschei): it must still go and shoot (scaling it cost 2-9 wins of 30 in the simulator); the last piece of a group (Agents, Harpies) is shielded more because the cards that need any of them die with it. Defense and boost decisions scale for all
                    if sum(1 for x in mine if x.name == t.name) == 1 and (fighter_profile(game, t) or {}).get("count", 1) > 1:
                        danger *= protect_factor(game, t)
                    danger *= despair_fear * twice
                else:
                    held = 0.0
                    if steps == 0:      # the chance of dying comes from the two blows, not from DOUBLE_ATTACK times one
                        p_dead = self.two_hit_threat(model, e, t, hand)[1]
                        held = self.survival_weight(p_dead) * (1 - despair)     # dying loses the game: desperation eases its fear less
                    danger = W_MEDUSA_HP * exp * twice * despair_fear + LETHAL * p_dead * (1 - DESPERATE_FEAR_DROP * despair * (1 - held))
                best = max(best, p_reach * danger)
            score -= best
        medusa = game.hero(self.me)
        for e in foes:
            if board.share_zone(pos[medusa.fid], pos[e.fid]):
                score += PRESSURE
            if despair > 0 and e.hero and board.can_reach_target(pos[medusa.fid], pos[e.fid], medusa.ranged):
                score += despair * WIN_PRIZE * PROGRESS_DISCOUNT * self.win_progress(game, model, medusa, e)
        if medusa.name != "Medusa" and foes:     # a fighter that fears the rival's blows still has to close in to hit back
            score -= APPROACH_PULL * min(board.distance(pos[medusa.fid], pos[e.fid]) for e in foes)
        for h in mine:
            if not h.hero and foes:
                score -= 0.05 * min(board.distance(pos[h.fid], pos[e.fid]) for e in foes)
                if is_striker(game, h) and any(board.can_reach_target(pos[h.fid], pos[e.fid], h.ranged) for e in foes):
                    score += self.strike_reward(game, h)
        return score

    def death_risk(self, game: Game, model: Model, t: Fighter, hp: float) -> float:
        """Chance that my fighter `t`, with `hp` hit points, dies in the rival's next turn: the worst of the rival fighters
        that can get in reach (they move, one extra space for a boost, then strike), hitting twice, against my best
        defenses in hand. Counts every rival, not only those already in reach, so a hit point spent now is priced."""
        if t.pos is None or not t.alive:
            return 0.0
        hand = game.players[self.me].hand
        real, t.hp = t.hp, hp
        try:
            risk = 0.0
            for e in game.foes(self.me):
                if e.pos is None:
                    continue
                strikes = game.legal_moves(e, e.move + 1) | {e.pos}
                if any(game.board.can_reach_target(s, t.pos, e.ranged) for s in strikes):
                    risk = max(risk, self.two_hit_threat(model, e, t, hand)[1])
            return risk
        finally:
            t.hp = real

    def double_blow_risk(self, game: Game, model: Model, override: dict) -> float:
        """Chance that my hero dies to the two blows of a rival already in reach of it, with `override` positions."""
        pos = {f.fid: f.pos for f in game.fighters.values() if f.alive}
        pos.update(override)
        me = game.hero(self.me)
        hand = game.players[self.me].hand
        risk = 0.0
        for e in game.foes(self.me):
            if e.fid not in pos or not any(s == pos[e.fid] for s in self.strike_spots(game.board, pos[me.fid], e.ranged)):
                continue
            risk = max(risk, self.two_hit_threat(model, e, me, hand)[1])
        return risk

    @staticmethod
    def survival_weight(p_dead: float) -> float:
        """0..1: how much of the fear of dying desperation can no longer ease (continuous up to SURVIVAL_P)."""
        return min(1.0, p_dead / SURVIVAL_P)

    def two_hit_threat(self, model: Model, e: Fighter, t: Fighter, hand) -> tuple[float, float]:
        """(expected damage, probability of dying) of `t` (a hero of mine) when rival `e`, already in reach, hits twice
        in its turn. The best defense in my hand covers the first blow, the second best the second; every blow
        that lands counts EFFECT_MARGIN more for the effects the printed value does not show."""
        defs = sorted((c.value for c in hand if c.can_defend and c.usable_by(t.name)), reverse=True) + [0, 0]
        exp = p_dead = 0.0
        for p, first, second in model.two_hit_dist(e):
            dmg = 0
            for v, d in ((first, defs[0]), (second, defs[1])):
                net = max(0, v - d)
                dmg += net + (EFFECT_MARGIN if net > 0 else 0)
            exp += p * min(dmg, t.hp)
            p_dead += p * (dmg >= t.hp)
        return exp, p_dead

    def strike_reward(self, game: Game, f: Fighter) -> float:
        """Position value of an own striker ending in strike range of a rival: STRIKE_PER_POINT for each point of the
        best attack in its owner's hand that it can play (at least STRIKE_MIN: it will draw one)."""
        if not f.ranged:
            return STRIKE_MIN
        hand = game.players[f.owner].hand
        best = max((c.value for c in hand if c.can_attack and c.usable_by(f.name)), default=0)
        return max(STRIKE_MIN, STRIKE_PER_POINT * (best + game.attack_bonus(f)))

    def harpy_score(self, game: Game, h: Fighter, dest: int) -> float:
        foes = game.foes(self.me)
        if not foes:
            return 0.0
        b = game.board
        near = min(b.distance(dest, e.pos) for e in foes)
        if is_striker(game, h):
            reach = any(b.can_reach_target(dest, e.pos, h.ranged) for e in foes)
            return -0.25 * near + (self.strike_reward(game, h) if reach else 0.0)
        return -0.25 * near + (0.6 if near == 1 else 0.0)

    def reach_dests(self, game: Game, f: Fighter, options: set[int]) -> set[int]:
        """The destinations from which a non-Medusa hero holding an attack card can hit a rival, when an action is left
        to do it (Fight Or Flight's move, Wildfire's): the move is for getting into position, not for staying clear of
        the rival's hits. Empty when the rule does not apply or no destination reaches."""
        if (not f.hero or f.name == "Medusa" or game.actions_left < 1
                or not any(c.can_attack and c.usable_by(f.name) for c in game.players[self.me].hand)):
            return set()
        foes = game.foes(self.me)
        return {d for d in options if any(game.board.can_reach_target(d, e.pos, f.ranged) for e in foes)}

    def best_dest(self, game: Game, model: Model, f: Fighter, steps: int, through: bool) -> int:
        options = game.legal_moves(f, steps, through) | {f.pos}
        if f.hero:
            rank = lambda d: (self.position_value(game, model, {f.fid: d}), -d)
            reaching = self.reach_dests(game, f, options)
            if not reaching:
                return max(options, key=rank)
            strike = max(reaching, key=rank)
            # getting into position for the attack is not worth a likely death: the survival fear decides then
            if self.double_blow_risk(game, model, {f.fid: strike}) >= SURVIVAL_P:
                return max(options, key=rank)
            return strike
        return max(options, key=lambda d: (self.harpy_score(game, f, d), -d))

    # ---------- execution ----------
    def execute(self, game: Game, a: Act) -> None:
        me = self.me
        if a.kind == "attack":
            game.attack(game.fighters[a.fid], game.fighters[a.target], a.card)
        elif a.kind == "maneuver":
            game.maneuver(me, a.moves, a.boost)
        elif a.kind == "glance":
            game.play_scheme(me, game.hero(me), a.card, target=game.fighters[a.target])
        elif a.kind == "frenzy":
            self._plan_moves, self._plan_spot = a.moves, a.spot
            try:
                game.play_scheme(me, game.hero(me), a.card)
            finally:
                self._plan_moves, self._plan_spot = {}, None
        elif a.kind == "scheme":
            fighter = game.fighters.get(a.fid) or game.hero(me)            # an act without a fighter is the hero's
            return game.play_scheme(me, fighter, a.card, choosers=self.scheme_choosers(game, a.variant))

    def scheme_choosers(self, game: Game, variant: str | None) -> dict | None:
        """Who decides inside a scheme the bot plays: with a search `variant`, the SyntheticChooser of that policy
        (what the search evaluated); without one, the usual choosers (this controller's EffectAI). The rival's
        decisions always go to the rival's usual chooser (its controller, or the panel in a session)."""
        if variant is None:
            return None
        from .effects.choose import SyntheticChooser
        from .effects.events import default_choosers
        choosers = dict(default_choosers(game))
        choosers[self.me] = SyntheticChooser(policy=variant)
        return choosers

    # ---------- decisions the engine delegates ----------
    def choose_move(self, game: Game, fighter: Fighter, steps: int, through_enemies: bool = False) -> int | None:
        if fighter.fid in self._plan_moves:
            return self._plan_moves[fighter.fid]
        return self.best_dest(game, Model(game, self.me), fighter, steps, through_enemies)

    def choose_placement(self, game: Game, fighter: Fighter, options: list[int]) -> int | None:
        if self._plan_spot is not None:
            return self._plan_spot
        return max(options, key=lambda s: (self.harpy_score(game, fighter, s), -s)) if options else None

    def choose_discard(self, game: Game, player: int, n: int, reason: str):
        hand = game.players[player].hand
        rel = effect_reliance(game, player)
        return sorted(hand, key=lambda c: (keep_value(c, hand, rel), c.card_id))[:n]

    def effect_ai(self):
        """The EffectAI (sparring/ai_effects.py) built on this class's evaluation: it answers the DSL decisions and
        simulates whole schemes for `scheme_act`."""
        if self._effect_ai is None:
            from .ai_effects import EffectAI
            self._effect_ai = EffectAI(self.me, self)
        return self._effect_ai

    def choose_effect(self, game: Game, req):
        """DSL decisions (sparring/effects/choose.py): sparring/ai_effects.py, built on this class's evaluation."""
        return self.effect_ai().choose_effect(game, req)

    def choose_combat_boost(self, game: Game, ctx):
        """The card to BOOST with, or None. Attacking: the damage the boost adds, by the target's weight. Defending
        (Out Of Time, D1): the damage it spares the bot's own fighter, and its life when the hit would kill it."""
        hand = game.players[self.me].hand
        t = ctx.target
        now = max(0, ctx.atk_value - ctx.def_value)
        rel = effect_reliance(game, self.me)
        defending = t.owner == self.me
        best, best_gain = None, 0.0
        for c in filter(can_be_boost, hand):
            if defending:
                net = max(0, ctx.atk_value - ctx.def_value - c.boost)
                gain = (W_MEDUSA_HP if t.hero else HARPY_VALUE) * (min(now, t.hp) - min(net, t.hp))
                gain += LETHAL if t.hero and now >= t.hp > net else 0.0
                if not t.hero:
                    gain *= protect_factor(game, t)
            else:
                net = max(0, ctx.atk_value + c.boost - ctx.def_value)
                gain = weight(t) * (min(net, t.hp) - min(now, t.hp))
            gain += boost_effect_value(game, self.me, c) - keep_value(c, hand, rel)
            if gain > best_gain:
                best, best_gain = c, gain
        return best

    def choose_defense(self, game: Game, attacker: Fighter, target: Fighter, attack_card: Card | None = None):
        """`attack_card`: the attack played face up (UNCANNY INTUITION, Perfect Shot): the one card the defense may
        know; otherwise the value is the distribution of what the rival may have committed."""
        model = Model(game, self.me)
        hand = game.players[self.me].hand
        self._attacker = attacker
        try:
            if attack_card is not None:
                dist = [(1.0, (attack_card.value or 0) + game.attack_bonus(attacker))]
            else:
                dist = model.committed_attack_dist(attacker)
            best, best_v = None, None
            options = [None] + [c for c in hand if c.can_defend and c.usable_by(target.name)]
            seen = set()
            for c in options:
                if c is not None:
                    if c.title in seen:
                        continue
                    seen.add(c.title)
                v = self.eval_defense(game, model, dist, target, c)
                if best_v is None or v > best_v + 1e-9:
                    best, best_v = c, v
        finally:
            self._attacker = None
        return best

    def mists_dist(self, game: Game, model: Model, attacker: Fighter) -> list[tuple[float, int]]:
        """What the attack becomes when The Mists of Munnopor replace it: the first playable card of the rival's deck, one nobody
        chose, so its value is that of a card drawn at random among the attack and versatile cards the attacker may still have
        (public: the pool is its whole deck minus its discard pile)."""
        bonus = game.attack_bonus(attacker)
        values = [c.value + bonus for c in model.pool if c.can_attack and c.usable_by(attacker.name)]
        if not values:
            return [(1.0, 0)]
        return [(1 / len(values), v) for v in values]

    def eval_defense(self, game: Game, model: Model, dist, target: Fighter, c) -> float:
        if c is not None and c.title == MISTS and getattr(self, "_attacker", None) is not None:
            dist = self.mists_dist(game, model, self._attacker)
        elif c is not None and c.title == CLOAK and getattr(self, "_attacker", None) is not None:
            hero = game.hero(target.owner)
            if hero.pos is not None and self._attacker.pos in game.board.adj[hero.pos]:
                dist = [(1.0, 0)]                      # Doctor Strange is next to the attacker: its value counts for nothing
        dv = c.value if c else 0
        boosts = free_boosts(game, self.me, c, game.players[self.me].hand) if c is not None else []
        dv += BOOST_RELIANCE * sum(x.boost for x in boosts)
        exp = p_dead = p_hit = p_block = 0.0
        for p, av in dist:
            net = max(0, (av or 0) - dv) if av is not None else 0
            exp += p * min(net, target.hp)
            p_dead += p * (net >= target.hp)
            p_hit += p * (net >= 1)
            p_block += p * (net == 0)
        if not target.hero:
            v = -HARPY_VALUE * target.max_hp * p_hit * protect_factor(game, target)   # a dead card engine is worth a defense card
        else:
            v = -W_MEDUSA_HP * exp - LETHAL * p_dead
        if c is None:
            return v
        v -= CARD_VALUE + 0.05 * c.boost
        if "invention" in c.tags:
            v += INVENTION_PLAY
        if defers_defeat(c) and target.hero:
            v += RESCUE_SHARE * LETHAL * p_dead      # the hero that would fall comes back with 4 health: the game goes on
        v += BOOST_RELIANCE * sum(boost_effect_value(game, self.me, x) for x in boosts)
        always, on_win = AFTER_BONUS.get(c.title, (0.0, 0.0))
        v += always + on_win * p_block
        if c.title == "Feint":
            v += 0.3
        if c.title == MISTS:
            v += MISTS_EDGE
        if c.title in DISCARD_EFFECTS:
            decisive = p_block >= 0.85 and exp < 0.5
            if not decisive:
                v -= self.transform_penalty(game, model)
        return v
