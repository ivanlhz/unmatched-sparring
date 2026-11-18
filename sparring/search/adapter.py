"""Adapter of the current engine (Medusa vs Hellboy) to the `SearchState` Protocol.

What the search sees: moves as hashable tuples, with card titles (copies of a card are
equivalent, so statistics are not split among them). A combinatorial action is decomposed into
chained sub-decisions that share statistics in the tree (the root has ~12 children instead of ~150):
  ("ability", fid | None)                       Medusa's ability at the start of her turn
  ("anung", title) -> ("anung_to", d | None)   forced discard + movement of ANUNG UN RAMA
  ("attack", fid, target) -> ("attack_card", fid, title)   the rival sees ("attack_card", fid, None)
  ("defend", title | None)                      resolves the pending combat
  ("scheme", title, target | None, variant)     schemes: Medusa's with their target / policy (C5); those of
                                                any other hero interpreted with a SyntheticChooser
                                                deciding inside (variant greedy | safe, D2; None if the
                                                card asks nothing), at most SCHEME_MOVES_KEEP per node
  ("maneuver", boost | None) -> ("place", d, policy)   the hero's destination and the sidekicks' policy
Sub-phases with a single option resolve themselves. `decision_pending()` says whether the action is half-done, so
the controller completes the move following the principal variation.

What the engine delegates in mid-resolution (Second Shot's boost, Dash, Hounds, forced discard, repositioning
a Harpy) is decided by `SearchController` with fixed heuristics: it is not part of the tree. The sidekicks move
as a block with a policy (stay, advance, retreat, guard: stand where the rivals' paths to the hero are blocked). Only complete placements enter the tree
(hero and sidekicks already moved) best scored by the static evaluation as an end-of-turn position
(`PLACEMENT_KEEP`), plus the best ones from which the hero strikes and staying still: with all of them, the maneuver
had ~30 leaves with few visits each and the noise chose the space. The rollout does not prune.

No cheating: `determinize` only uses `full_set`, `discard`, `len(hand)` and the known cards (`Knowledge`).

Leaf evaluation (`evaluate`): material of each side (hero HP, HP and number of sidekicks, hand, deck) minus
the threat on its hero next turn (`EngineState.threat`): expected damage from the rivals that really reach it
(without passing through its own fighters, so a sidekick in the corridor is a shield), with the average attack of the
attacker's whole deck against the best defense in hand, plus the probability of being killed. It is generic
(any hero, any sidekick) and, subtracted from the opposing side, is its own pressure: a sidekick within range of the
rival hero counts as an attacker, not just as HP to keep. The weights live in `EvalWeights` (F10 tunes them); `HERO_EVAL` holds
the ones a hero plays with: the bot's Raptors (a team, beaten only with their last fighter) count their three fighters as one life,
threatened through whichever of them the rival reaches.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field, replace
from functools import lru_cache
from math import comb, fsum, prod, sqrt

from .. import enraged, pack, tracks
from ..ai_hazards import zone_cover_factor, zone_damage, zone_exposed
from ..ai_medusa import (ATTACKS_PER_TURN, DRAWS_PER_TURN, GAZE, LONG_GAME, MIN_NET, beside_stake, boost_effect_value, bot_may_spend,
                         can_use, discard_cut, exhaustion_owed, held_for_plan, maneuver_may_spend, play_signature, scheme_fighter)
from ..cards import Card, can_be_boost
from ..combat import is_medusa_card, resolve_combat
from ..controller import Controller
from ..effects import ongoing
from ..effects.inventions import INVENTION_WORTH
from ..effects.choose import SCHEME_VARIANTS, SyntheticChooser
from ..effects.model import load_effects, walk_ops
from ..guard import boost_reach, guard_dest, free_steps, reach_from, strike_spots
from ..state import ANUNG, EXHAUST_DAMAGE, Fighter, Game, PlayerState

SIDEKICK_POLICIES = ("stay", "advance", "retreat", "guard")
PACK = "pack"           # a follower closes on the rival the hero ends next to, so every Raptor stands beside the defender (the pack bonus); offered only to a hero with that passive
BESIDE = "beside"       # a sidekick ends next to its hero (cards that pay for it: `beside_stake`); in the tree only, offered when the stake is not 0
ROLLOUT_POLICIES = ("stay", "advance", "retreat", PACK)    # "guard" lives in the tree only: its path analysis costs more than a random playout is worth
FRENZY_VARIANTS = ("advance", "retreat")
SCHEME_MOVES_KEEP = 6         # scheme moves per node: every title's greedy line first, the safe ones while they fit
ASKING_OPS = ("move", "place", "swap", "revive", "summon", "optional", "choose_effect", "choose", "search_deck")
ROLLOUT_ATTACK_PROB = 0.7     # in the rollout, whoever can attack almost always does (makes threats visible)
ROLLOUT_BOOST_PROB = 0.3
ROLLOUT_APPROACH_PROB = 0.5   # in the rollout, the hero maneuvering looks for a space from which to strike
PLACEMENT_KEEP = 6            # maneuver placements in the tree: the best by static evaluation...
PLACEMENT_STRIKE_KEEP = 2     # ...plus the best ones from which the hero strikes, plus staying still
HAND_RESERVE = 3              # the cards of a hand that are its reserve (`EvalWeights.hand_reserve`): two blows to answer next turn and one card to play
REFERENCE_HP = 16               # the hero hit points that one life is measured in when a card or a deck is priced in hit points (`card_hp`, `deck_hp`), whoever the side is
GAME_TURNS = 15               # turns of its own that a game can last, for the exhaustion race (`EngineState._exhaustion`): the live games and the duels went 8 to 13
MIN_HORIZON = 6               # the fewest turns an exhaustion race still looks ahead (`EngineState._exhaustion`), however long the game has gone on
LAST_DEFENCE_WORTH = 100.0   # the price of the bot's only card able to defend as a maneuver boost (`_boost_variants`): the dearest card, offered only when nothing else boosts as much
PACK_RESERVE = 2              # cards a pack keeps after a blow (a defense among them) for that blow to be forced on its last action: the rival answers with two actions


@dataclass(frozen=True)
class EvalWeights:
    """Weights of the leaf evaluation. Units: 1.0 = all of the hero's HP."""
    sidekicks: float = 1.0          # HP of the living sidekicks, measured in the hero's max HP
    alive: float = 0.15             # living sidekicks: a fallen one is one attacker and one shield less
    hand: float = 0.15
    deck: float = 0.1
    threat: float = 0.6             # expected damage on the hero next turn (fraction of its current HP)
    lethal: float = 0.5             # probability that that turn kills it
    victim_moves_first: float = 0.1 # discount if the threatened one moves first: it can step aside or strike first
    boost_reach: float = 0.4        # the attacker that needs a boost to reach: it costs a card and is uncertain
    defend_card_hp: float = 0.75    # each attack received also costs a defense card (in equivalent HP)
    ongoing: float = 1.0            # the ONGOING in play, in hero HP (`effects.ongoing.worth`)
    beside: float = 0.0             # share of the sidekicks standing next to their hero, when its cards pay for it (`beside_stake`)
    pack: float = 0.15              # for a hero with the pack bonus (the Raptors): each fighter beyond the first standing beside the same rival, in hero HP (the +1 of every blow it lands is about two points a turn)
    caution: float = 1.0            # multiplier of the expected damage on the bot's own hero (less: it stands in reach); the lethal risk is not scaled
    reserve: float = 0.0            # cards are counted per blow in `threat`. Above 0 the attacker lands no more blows than it has cards for; and each blow after the first is measured that far from the best defense in hand towards the next one (1: a card defends once)
    team_life: float = 0.0          # above 0, a team (the Raptors) is one life: the hit points of all its fighters in `_side_value`, threatened through whichever of them the rival reaches (`_life_pool`)
    hand_reserve: float = 0.0       # the first `HAND_RESERVE` cards of the hand, on top of `hand`: an empty hand answers nothing, a seventh card adds little
    slope: float = 1.5              # scale of `squash` over the difference between sides
    # F-AI-EVAL-RESOLUTION. Each of these is off at 0 (the evaluation above, untouched); `RESOLUTION` turns them on together
    normalize: float = 0.0          # above 0, every side is measured against its own full strength (`_side_value_normalized`): hit points of the hero and of all the sidekicks as shares of what each started with, so a hero with a sidekick does not open ahead of one without
    card_hp: float = 0.0            # above 0 (with `normalize`), a card in hand is this many hit points (of the side's life) and the deck counts linearly: `deck_hp` per card, no ceiling
    deck_hp: float = 0.0
    race: float = 0.0               # above 0 (with `normalize`), the exhaustion each deck will owe over the length of the game (turns until the first hero falls, at the real draw rate, Wildfire's burn included), scaled by this weight
    race_rival: float = 1.0         # the share of the rival's exhaustion bill that the evaluation counts in the bot's favour (the bot's own bill counts whole): the rival's deck is its own to manage, and it is refilled by its cards (Rekindle) or spared by playing them
    fighter_threat: float = 0.0     # above 0, `_exposure` adds the loss of the best-placed sidekick the rival reaches (hit points and the fighter itself), scaled by this weight
    unseen: float = 0.0             # above 0, the rival's blows are valued from the cards it may still hold (its set minus discard and removed) and its hand size: the i-th best attack of a hand of that size
    next_draw: float = 0.0          # above 0 (with `normalize`), the draws the next turn needs (this many) are charged to the hit points of a side whose deck is short of them: every fighter pays EXHAUST_DAMAGE per missing card, so a hero at that many hit points or fewer cannot afford to maneuver
    piles: float = 0.0              # above 0, a VOYAGE card (Sinbad's) is valued at the attack it will be, 2 plus the VOYAGE cards in its owner's pile, wherever the evaluation reads the attacks of a hand or a deck
    hidden_attack: float = 0.0      # above 0, the rival's face-down attack is one of the attack cards of the hand it is dealt (known and sampled cards alike), not always one of the known ones


# The evaluation of F-AI-EVAL-RESOLUTION, to be switched on by configuration (`ai_eval`) until the duels (tools/ai_duel.py `eval=new`) accept it
RESOLUTION: dict[str, float] = {"normalize": 1.0, "card_hp": 1.0, "deck_hp": 0.8, "race": 1.0, "fighter_threat": 0.5, "unseen": 1.0,
                                "hidden_attack": 1.0, "team_life": 1.0, "reserve": 1.0, "piles": 1.0, "next_draw": 1.0, "caution": 0.5, "race_rival": 0.0, "victim_moves_first": 0.5}

# evaluation weights a hero plays with; the configuration's own values win. Doctor Strange stands in reach (F-STRANGE-AGGRO); the Raptors
# are one life, count a card per blow and keep a reserve (F-RAPTORS-SWARM: they attacked themselves out of cards, and only a third of
# their deck defends). A bot of another hero facing the Raptors keeps the old evaluation: one life there cost it attacks and, if
# anything, games (120 paired games of Liz Sherman, features.json)
HERO_EVAL: dict[str, dict[str, float]] = {"doctor-strange": {"caution": 0.3},
                                          "raptors": {"team_life": 1.0, "reserve": 1.0, "hand_reserve": 0.45}}


@dataclass(frozen=True)
class PackPlan:
    """The one place where the rule of a pack (the Raptors: "never maneuver with the last action if an attack exists") is decided, per hero.
    `reserve`: the pack presses only while a blow leaves it this many cards (a defense among them), the rule F-RAPTORS-SWARM measured.
    `press`: always (the rule before it). `pulse`: `span` of its own turns pressing, then `span` not (the video's pattern for a pack that does
    not draw: two turns forward, two back). The plan layer of phase 3 sets the mode of the game; until then the table says `reserve`."""
    mode: str = "reserve"
    reserve: int = PACK_RESERVE
    span: int = 2


PACK_PLANS: dict[str, PackPlan] = {}
DEFAULT_PACK_PLAN = PackPlan()


def pack_plan(game: Game, player: int) -> PackPlan:
    return PACK_PLANS.get(game.players[player].hero.slug, DEFAULT_PACK_PLAN)


def hero_weights(weights: EvalWeights, slug: str, explicit: frozenset[str] = frozenset()) -> EvalWeights:
    """`weights` with the hero's profile on top of every field the configuration did not set: those in `explicit` (the keys the
    configuration's own `ai_eval` sets, even when equal to the default) and any field that differs from the default are left alone. The values of
    `RESOLUTION` count as the default, so a profile (Doctor Strange's caution) still wins over the new evaluation."""
    base = EvalWeights()
    mine = {k: v for k, v in HERO_EVAL.get(slug, {}).items() if k not in explicit and getattr(weights, k) in (getattr(base, k), RESOLUTION.get(k))}
    return replace(weights, **mine) if mine else weights


@dataclass(frozen=True)
class Knowledge:
    """A frozen snapshot of the observer's `KnownHand` (the single source of truth, kept by the engine, already
    discounted of the cards that left): what a legitimate look-at-the-hand or reveal effect showed. The adapter only
    respects it. Keys are the RIVAL player whose hand/deck it describes.
    - known_in_hand: certainly in that hand.
    - possible_in_hand / possible_bounds: seen once, maybe gone face down; between lo and hi of them are in the hand.
    - top_of_deck: that deck's known prefix, top first."""
    known_in_hand: dict[int, tuple[Card, ...]] = field(default_factory=dict)
    possible_in_hand: dict[int, tuple[Card, ...]] = field(default_factory=dict)
    possible_bounds: dict[int, tuple[int, int]] = field(default_factory=dict)
    top_of_deck: dict[int, tuple[Card, ...]] = field(default_factory=dict)

    @classmethod
    def from_game(cls, game: Game, observer: int) -> "Knowledge":
        known, rival = game.players[observer].known, 1 - observer
        st = game.players[rival]
        poss = tuple(known.possible_cards(st))
        return cls({rival: tuple(known.cards(st))}, {rival: poss},
                   {rival: (min(known.possible_lo, len(poss)), min(known.possible_hi, len(poss)))},
                   {rival: tuple(known.top(st))})


def squash(x: float) -> float:
    """Advantage (in hero lives) to reward in (0, 1), with heavy tails. With the sigmoid, a badly
    lost position (Medusa at 3 HP against a full Hellboy) was worth ~0.04 whatever she did, and a 10 % chance of dying now
    weighed less than cancelling a card; this way staying alive is distinguished from dying there too."""
    return 0.5 + 0.5 * x / (1.0 + abs(x))


def card_worth(c: Card) -> float:
    return (c.value or 0) + 0.5 * c.boost + (2.0 if c.is_scheme else 0.0) + (INVENTION_WORTH if "invention" in c.tags else 0.0)


def by_title(hand: list[Card], title: str) -> Card:
    return next(c for c in hand if c.title == title)


_near_cache: dict[tuple, int] = {}
_moves_cache: dict[tuple, list] = {}
MOVES_CACHE_MAX = 50_000
_pure_loss_cache: dict[tuple, bool] = {}
PURE_LOSS_SHADOW = {"on": os.environ.get("SPARRING_PURE_LOSS_SHADOW") == "1", "verdicts": 0, "hits": 0, "disagree": []}


def reach(game: Game, f: Fighter, steps: int, through: bool = False) -> frozenset[int]:
    """`Game.legal_moves` with a cache (a fighter immobilized by an effect, Burning Barrier, stays where it is)."""
    if not game.fx.can_move(f):
        return frozenset({f.pos})
    if through == "sidekicks" or tracks.free_spaces(game, f):     # a move through the rivals' sidekicks only, or one over John Henry's tracks (not worth a cache entry)
        return frozenset(game.legal_moves(f, steps, through))
    own = frozenset(game.occupied(f.owner) - {f.pos})
    enemy = frozenset(game.occupied(1 - f.owner))
    return reach_from(game.board, f.pos, steps, own, enemy, through)


def nearest_walk_from(board, pos: int, foes: tuple[int, ...]) -> int:
    """Steps the nearest foe needs to walk to `pos` (fleeing and placement: it is the foe that walks, and with one-way
    edges that is not the distance from `pos` to the foe)."""
    key = (board.key, "from", pos, foes)
    d = _near_cache.get(key)
    if d is None:
        d = _near_cache[key] = min((board.distance(e, pos) for e in foes), default=0)
    return d


def nearest(board, pos: int, foes: tuple[int, ...]) -> int:
    key = (board.key, pos, foes)
    d = _near_cache.get(key)
    if d is None:
        d = _near_cache[key] = min((board.distance(pos, e) for e in foes), default=0)
    return d


_attack_values_cache: dict[tuple, tuple[int, ...]] = {}
_attack_stats_cache: dict[tuple, tuple[float, float]] = {}


def attack_stats(values: tuple[int, ...], delta: int, hp: float) -> tuple[float, float]:
    """(mean net damage, fraction of cards that kill) of a deck of values `values` with `delta` = attacker's
    bonus minus the target's defense, against `hp` HP. It repeats thousands of times per decision: cached."""
    key = (values, delta, hp)
    r = _attack_stats_cache.get(key)
    if r is None:
        n = len(values)
        r = _attack_stats_cache[key] = (sum(max(0, v + delta) for v in values) / n,
                                        sum(1 for v in values if v + delta >= hp) / n)
    return r


def pile_bonus(st: PlayerState) -> int:
    """What a VOYAGE card adds to its printed value for `st` now: the VOYAGE cards of its discard pile (0 for any other hero)."""
    return sum(1 for c in st.discard if "voyage" in c.tags) if "voyage" in st.hero.counters else 0


def attack_values(st: PlayerState, fighter_name: str, piles: bool = False) -> tuple[int, ...]:
    """Attack values of the whole deck that `fighter_name` can use: the printed ones, and a VOYAGE card (Sinbad's) at 2 plus the VOYAGE cards
    in its owner's pile (`piles`), the value it will have when played (`ai_sinbad.own_value`): the pile is public."""
    bonus = pile_bonus(st) if piles else 0
    key = (st.hero_name, fighter_name, bonus)
    v = _attack_values_cache.get(key)
    if v is None:
        v = _attack_values_cache[key] = tuple(c.value + (bonus if "voyage" in c.tags else 0)
                                              for c in st.full_set if c.can_attack and c.usable_by(fighter_name))
    return v


_unseen_values_cache: dict[tuple, tuple[int, ...]] = {}
_best_stats_cache: dict[tuple, tuple[float, float]] = {}
UNSEEN_BEST, UNSEEN_MEAN = 1.0, 2.0     # `EvalWeights.unseen`: the i-th best attack of the hand the rival holds, or the mean attack of the cards it may still hold
NO_ATTACK = -1      # in `unseen_values`: a card that cannot attack with that fighter (it still takes a place in the hand)


def unseen_values(st: PlayerState, fighter_name: str, piles: bool = False) -> tuple[int, ...]:
    """The cards `st` may still hold in its hand or deck (its set minus the discard pile and what was removed: public), as the attack value
    each gives `fighter_name`, best first; `NO_ATTACK` for the ones that cannot attack with it."""
    gone = frozenset(c.card_id for c in st.gone)
    bonus = pile_bonus(st) if piles else 0
    key = (st.hero_name, fighter_name, gone, bonus)
    v = _unseen_values_cache.get(key)
    if v is None:
        if len(_unseen_values_cache) >= MOVES_CACHE_MAX:
            _unseen_values_cache.clear()
        v = _unseen_values_cache[key] = tuple(sorted((c.value + (bonus if "voyage" in c.tags else 0) if c.can_attack and c.usable_by(fighter_name) else NO_ATTACK
                                                       for c in st.full_set if c.card_id not in gone), reverse=True))
    return v


def best_attack_stats(values: tuple[int, ...], hand: int, rank: int, delta: int, hp: float) -> tuple[float, float]:
    """(mean net damage, probability of killing) of the `rank`-th best attack (0 = the best) of a hand of `hand` cards dealt at random
    from the cards `values` (best first, `NO_ATTACK` for the ones that cannot attack), with `delta` = the attacker's bonus minus the target's
    defense, against `hp` HP. The i-th best of the hand is the card of place j of the pool with the probability C(j, i) C(n-1-j, h-1-i) / C(n, h)."""
    n = len(values)
    hand = min(hand, n)
    key = (values, hand, rank, delta, hp)
    r = _best_stats_cache.get(key)
    if r is None:
        if len(_best_stats_cache) >= MOVES_CACHE_MAX:
            _best_stats_cache.clear()
        mean = kill = 0.0
        if rank < hand:
            total = comb(n, hand)
            for j in range(rank, n - (hand - 1 - rank)):
                v = values[j]
                if v == NO_ATTACK:
                    break
                p = comb(j, rank) * comb(n - 1 - j, hand - 1 - rank) / total
                mean += p * max(0, v + delta)
                kill += p * (v + delta >= hp)
        r = _best_stats_cache[key] = (mean, kill)
    return r


def policy_dest_from(board, pos: int, options, foes: tuple[int, ...], policy: str) -> int:
    if policy == "stay" or not foes:
        return pos
    cands = set(options) | {pos}
    if policy == "advance":
        return min(cands, key=lambda d: (nearest(board, d, foes), d))
    return max(cands, key=lambda d: (nearest_walk_from(board, d, foes), -d))


def foe_positions(game: Game, player: int) -> tuple[int, ...]:
    return tuple(sorted(game.occupied(1 - player)))


def policy_dest(game: Game, f: Fighter, options, policy: str) -> int:
    return policy_dest_from(game.board, f.pos, options, foe_positions(game, f.owner), policy)


def sidekick_plan(game: Game, player: int, extra: int, policy: str,
                  hero_dest: int | None = None) -> tuple[tuple[str, int], ...]:
    """Destinations of the sidekicks in fid order, with the occupation updated after each one (and the hero already at
    `hero_dest` if given): exactly the order in which the engine validates the maneuver. Without cloning the `Game`."""
    board = game.board
    own = {f.fid: f.pos for f in game.own(player)}
    if hero_dest is not None:
        own[game.hero(player).fid] = hero_dest
    enemy = frozenset(game.occupied(1 - player))
    foes = tuple(sorted(enemy))
    stake = beside_stake(game, player) > 0
    out = []
    for h in sorted((x for x in game.own(player) if not x.hero), key=lambda x: x.fid):
        others = frozenset(v for k, v in own.items() if k != h.fid)
        if not game.fx.can_move(h):
            out.append((h.fid, h.pos))
            continue
        options = reach_from(board, own[h.fid], h.move + extra, others, enemy)
        if policy == PACK:
            dest = pack_dest(game, own[game.hero(player).fid], options, h, own[h.fid])
        elif policy == "guard":
            dest = guard_dest(game, own[game.hero(player).fid], options, h.fid, own)
        elif policy == BESIDE or (policy == "advance" and stake):      # advancing, a sidekick whose hero's cards pay for it closes up
            dest = beside_dest(board, h, own[game.hero(player).fid], options, foes)
        else:
            dest = policy_dest_from(board, own[h.fid], options, foes, policy)
        own[h.fid] = dest
        out.append((h.fid, dest))
    return tuple(out)


def pack_dest(game: Game, hero_pos: int, options, h: Fighter, pos: int) -> int:
    """Where a follower goes to join the pack: the space next to the rival the hero stands (or ends) nearest to, the one
    nearest to the follower among those it can reach (every such space is a strike with the pack bonus); with none in reach,
    the reachable space nearest to that rival. The rival is the closest to the hero, the weakest of a tie."""
    board = game.board
    foes = [e for e in game.foes(h.owner) if e.pos is not None]
    if not foes:
        return pos
    prey = min(foes, key=lambda e: (board.distance(hero_pos, e.pos), e.hp, e.fid))
    cands = set(options) | {pos}
    ring = cands & set(board.adj[prey.pos])
    if ring:
        return min(ring, key=lambda d: (board.distance(pos, d), d))
    return min(cands, key=lambda d: (board.distance(d, prey.pos), d))


def beside_dest(board, h: Fighter, hero_pos: int, options, foes: tuple[int, ...]) -> int:
    """The square next to the hero that gives up no strike the best `advance` square has, the nearest to the rivals among them;
    the `advance` square itself when none is reachable (like `MedusaAI.sidekick_dest` but with no slack bound: any reachable adjacent square is taken)."""
    best = policy_dest_from(board, h.pos, options, foes, "advance")
    strikes = lambda d: any(board.can_reach_target(d, e, h.ranged, h.reach) for e in foes)
    keeps = strikes(best)
    near = [d for d in set(options) | {h.pos} if d in board.adj[hero_pos] and (strikes(d) or not keeps)]
    return min(near, key=lambda d: (nearest(board, d, foes), d)) if near else best


def plan_frenzy(game: Game, player: int, variant: str) -> tuple[dict[str, int], int | None]:
    """Winged Frenzy movements (all fighters, 3 steps, through rivals) and the space where the fallen
    Harpy returns, with the same policy the simulation uses."""
    g = game.clone()
    moves = {}
    for f in sorted(g.own(player), key=lambda x: x.fid):
        dest = policy_dest(g, f, reach(g, f, 3, True), variant)
        f.pos = dest
        moves[f.fid] = dest
    spot = None
    dead = [f for f in g.own(player, alive_only=False) if not f.hero and not f.alive]
    if dead:
        hero = g.hero(player)
        taken = {f.pos for f in g.fighters.values() if f.alive}
        options = sorted(s for s in g.board.spaces if s not in taken and g.board.share_zone(hero.pos, s))
        spot = placement_choice(g, player, options)
    return moves, spot


def placement_choice(game: Game, player: int, options: list[int]) -> int | None:
    foes = foe_positions(game, player)
    return max(options, key=lambda s: (nearest_walk_from(game.board, s, foes), -s)) if options else None


@lru_cache(maxsize=None)
def scheme_variants(slug: str, title: str) -> tuple:
    """The chooser policies worth a move of their own for this scheme: both when its ops ask something (a
    destination, an option, a price, a card to give up), a single line (None) when nothing is decided inside."""
    ops = load_effects(slug).moment_ops(title, "scheme")
    for o in walk_ops(ops):
        if o["op"] in ASKING_OPS or any(isinstance(v, dict) and "chooser" in v for v in o.values()):
            return SCHEME_VARIANTS
    return (None,)


class SearchController(Controller):
    """Decisions delegated by the engine inside the simulation: fixed, cheap heuristics."""

    def __init__(self, me: int, state: "EngineState"):
        self.me = me
        self.state = state

    def choose_combat_boost(self, game: Game, ctx):
        """Attacking: the damage the boost adds; defending (Out Of Time): the damage it spares, same price."""
        hand = game.players[self.me].hand
        t = ctx.target
        sign = -1 if t.owner == self.me else 1
        now = min(game.combat_damage_taken(t, max(0, ctx.atk_value - ctx.def_value)), t.hp)
        best, best_gain = None, 0.0
        for c in filter(bot_may_spend, hand):
            net = min(game.combat_damage_taken(t, max(0, ctx.atk_value + sign * c.boost - ctx.def_value)), t.hp)
            gain = sign * (net - now) - 0.3 * card_worth(c) + 0.3 * boost_effect_value(game, self.me, c)     # BOOSTED WITH
            if gain > best_gain:
                best, best_gain = c, gain
        return best

    def choose_discard(self, game: Game, player: int, n: int, reason: str):
        return discard_cut(game, player, game.players[player].hand, card_worth, n)

    def choose_move(self, game: Game, fighter: Fighter, steps: int, through_enemies: bool = False):
        policy = self.state.variant
        if policy in (None, "advance") and not fighter.hero and beside_stake(game, fighter.owner):
            hero_pos = game.hero(fighter.owner).pos
            foes = foe_positions(game, fighter.owner)
            if hero_pos is not None and foes:
                return beside_dest(game.board, fighter, hero_pos, reach(game, fighter, steps, through_enemies) | {fighter.pos}, foes)
        if policy is None:      # Dash and Hounds: the ranged hero moves away, the others approach
            policy = "retreat" if (fighter.hero and fighter.ranged) else "advance"
        return policy_dest(game, fighter, reach(game, fighter, steps, through_enemies), policy)

    def choose_placement(self, game: Game, fighter: Fighter, options: list[int]):
        return placement_choice(game, fighter.owner, options)


class EngineState:
    """`pending`: (attacker fid, target fid, card | None). With card None the play is face down and
    determinization samples it (the bot choosing a defense). `phase`: "start", "action" or a sub-phase
    ("attack_card", "maneuver_place", "anung_to") with the decision half-made in `partial`."""

    SUBPHASES = ("attack_card", "maneuver_place", "anung_to")

    def __init__(self, game: Game, observer: int, knowledge: Knowledge | None = None,
                 pending: tuple[str, str, Card | None] | None = None, phase: str = "action",
                 weights: EvalWeights | None = None):
        self.game = game.clone()
        self.game.controllers = {0: SearchController(0, self), 1: SearchController(1, self)}
        # own things in canonical order: with the same seed the decision does not depend on the real order of the deck or
        # the hand (the rival's is replaced entirely when determinizing and is not read here)
        mine = self.game.players[observer]
        mine.hand.sort(key=lambda c: c.card_id)
        mine.deck.sort(key=lambda c: c.card_id)
        self.observer = observer
        self.knowledge = knowledge or Knowledge()
        self.weights = weights or EvalWeights()
        self.pending = pending
        self.phase = phase
        self.partial: tuple = ()
        self.variant: str | None = None
        self._eval: float | None = None
        self._advance()

    # ---------- Protocol ----------
    def clone(self) -> "EngineState":
        c = EngineState.__new__(EngineState)
        c.game = self.game.clone()
        c.game.controllers = {0: SearchController(0, c), 1: SearchController(1, c)}
        c.observer, c.knowledge, c.pending, c.weights = self.observer, self.knowledge, self.pending, self.weights
        c.phase, c.partial, c.variant, c._eval = self.phase, self.partial, self.variant, self._eval
        return c

    def player_to_move(self) -> int:
        if self.pending is not None:
            return self.game.fighters[self.pending[1]].owner
        return self.game.turn

    def turn_owner(self) -> int:
        return self.game.turn

    def is_terminal(self) -> bool:
        return self.game.winner is not None

    def winner(self) -> int | None:
        return self.game.winner

    def pending_card(self) -> Card | None:
        return self.pending[2] if self.pending else None

    def decision_pending(self) -> bool:
        return self.phase in self.SUBPHASES

    def legal_moves(self) -> list:
        """Memoized by signature (phase, pending, positions, hand of whoever moves): the root is the same in every
        iteration and the rival's nodes repeat a lot. The returned list is not modified."""
        key = self._signature()
        moves = _moves_cache.get(key)
        if moves is None:
            if len(_moves_cache) >= MOVES_CACHE_MAX:
                _moves_cache.clear()
            moves = _moves_cache[key] = self._generate_moves()
        return self._without_pure_losses(moves)

    def _without_pure_losses(self, moves: list) -> list:
        """The schemes that would only spend here (`_pure_loss`) leave the list. Judged on this very state at every
        call, outside the cache: the verdict reads what the signature does not hold (piles, hidden hands, draws)."""
        if self.pending is not None or self.phase != "action" or not any(m[0] == "scheme" and m[2] is None for m in moves):
            return moves
        p = self.game.turn
        hand = self.game.players[p].hand

        def spends_only(m) -> bool:
            if m[0] != "scheme" or m[2] is not None:
                return False
            card = by_title(hand, m[1])
            return not is_medusa_card(card) and self._pure_loss(p, card, m[3])
        return [m for m in moves if not spends_only(m)]

    def _signature(self) -> tuple:
        g = self.game
        mover = self.player_to_move()
        return (g.board.key, g.turn, self.phase, self.partial, self.pending[:2] if self.pending else None,
                g.form(1 - g.turn) if self.phase == "start" else None,
                tuple((f.fid, f.pos, f.hp) for f in g.fighters.values() if f.alive),
                tuple(sorted(c.card_id for c in g.players[mover].hand)),
                tuple(f.fid for f in g.fighters.values() if f.alive and not g.fx.can_move(f)),    # pinned by an effect
                g.maneuver_bonus(g.turn),      # the Maneuver's reach moves with the hero's ability (Sinbad's VOYAGE cards in the pile)
                g.actions_left if pack.passive(g, g.turn) else None,    # a pack's last action is spent on a blow, not on a walk (`_generate_moves`)
                tuple(map(tuple, g.fx.tracks)), tracks.attack_only(g), tuple(g.free_attacks))      # John Henry's tracks decide his walks, and a free action to attack allows nothing else (and Wyatt Earp's can be bound to a fighter)

    def _generate_moves(self) -> list:
        g = self.game
        if self.pending is not None:
            return self._defend_moves()
        p = g.turn
        hero = g.hero(p)
        if self.phase == "start":
            return self._start_moves(p)
        if self.phase == "anung_to":
            card = by_title(g.players[p].hand, self.partial[0])
            return [("anung_to", None)] + [("anung_to", d) for d in sorted(reach(g, hero, card.boost))]
        if self.phase == "attack_card":
            f = g.fighters[self.partial[0]]
            return [("attack_card", f.fid, t) for t in self._attack_titles(p, f, g.fighters[self.partial[1]])]
        if self.phase == "maneuver_place":
            return [("place", d, policy) for d, policy in self._placements(p, hero)]
        attacks = self._attack_moves(p)
        if tracks.attack_only(g):                   # the action left is a free action to attack: nothing else may spend it
            return attacks
        moves = attacks + self._scheme_moves(p)
        if attacks and g.actions_left <= 1 and self._pack_presses(p):
            return moves        # the pack whose hand can pay for it never spends its last action walking when it has a blow to land (Iván: super aggressive); with an action to spare it may close up first (`_placements`)
        moves += [("maneuver", c.title if c else None) for c in self._boost_variants(p)]
        return moves

    def apply(self, move) -> None:
        g = self.game
        kind = move[0]
        p = self.player_to_move()
        hand = g.players[p].hand
        self._eval = None
        if kind == "defend":
            att, tgt, atk_card = self.pending
            self.pending = None
            def_card = by_title(hand, move[1]) if move[1] is not None else None
            resolve_combat(g, g.fighters[att], g.fighters[tgt], atk_card, def_card)
        elif kind == "attack":
            self.phase, self.partial = "attack_card", (move[1], move[2])
        elif kind == "attack_card":
            att, tgt = self.partial
            self.phase, self.partial = "action", ()
            g.use_action(attack=True, attack_on=tgt)
            self.pending = (att, tgt, by_title(hand, move[2]))
            g.fx.emit("attacked", g.fighters[att], g.fighters[tgt], self.pending[2])   # as Game._declare_attack does
        elif kind == "maneuver":
            self.phase, self.partial = "maneuver_place", (move[1],)
        elif kind == "place":
            title, = self.partial
            _, d, policy = move
            self.phase, self.partial = "action", ()
            boost = by_title(hand, title) if title is not None else None
            plan = sidekick_plan(g, p, (boost.boost if boost else 0) + g.maneuver_bonus(p, boost), policy, hero_dest=d)
            g.maneuver(p, dict(((g.hero(p).fid, d),) + plan), boost)
        elif kind == "scheme":
            card = by_title(hand, move[1])
            if move[2] is not None:
                g.play_scheme(p, g.hero(p), card, target=g.fighters[move[2]])
            elif is_medusa_card(card):      # C5: the frenzy policy reaches choose_move through the controller
                self.variant = move[3]
                try:
                    g.play_scheme(p, g.hero(p), card)
                finally:
                    self.variant = None
            else:                           # D2: the chooser of the variant decides inside; the rival answers greedy
                mine = SyntheticChooser(policy=move[3] or "greedy")
                g.play_scheme(p, scheme_fighter(g, p, card), card, choosers={p: mine, 1 - p: SyntheticChooser(policy="greedy")})
        elif kind == "ability":
            if move[1] is not None:
                g.use_ability(p, GAZE, g.fighters[move[1]])
            self.phase = "action"
        elif kind == "anung":
            self.phase, self.partial = "anung_to", (move[1],)
        elif kind == "anung_to":
            title, = self.partial
            self.phase, self.partial = "action", ()
            g.hellboy_anung_start(p, by_title(hand, title), move[1])
        else:
            raise ValueError(f"unknown move: {move!r}")
        self._advance()

    def observe(self, move, viewer: int):
        if move[0] == "attack_card" and self.game.fighters[move[1]].owner != viewer:
            return ("attack_card", move[1], None)
        return move

    def evaluate(self, player: int) -> float:
        g = self.game
        if g.winner is not None:
            return 1.0 if g.winner == player else 0.0
        if self._eval is None:      # the search asks for the leaf from both sides: computed once
            self._eval = squash(self.weights.slope * self._advantage(0))
        return self._eval if player == 0 else 1.0 - self._eval

    def _advantage(self, p: int, urgent: bool = False) -> float:
        return self._side_value(p, urgent) - self._side_value(1 - p, urgent)

    def _hero_options(self, hero: Fighter) -> frozenset[int]:
        """Where the hero can end up in the maneuver under way (with the chosen boost), staying included. A hero that
        places himself when he boosts (ESCAPE ARTIST) can end on any empty space."""
        g = self.game
        if self.partial and self.partial[0] is not None and g.fx.can_move(hero) and g.fx.hero_rule(hero.owner, "maneuver_boost_places_hero"):
            taken = {f.pos for f in g.fighters.values() if f.alive and f is not hero}
            return frozenset(s for s in g.board.spaces if s not in taken) | {hero.pos}
        return reach(g, hero, hero.move + self._extra()) | {hero.pos}

    def rollout_move(self, rng: random.Random):
        """Move that is legal for the engine; the hero's destination comes from the full reach (without the tree's pruning, which
        costs one evaluation per space and does not pay off in the rollout)."""
        g = self.game
        if self.phase == "maneuver_place":
            p = g.turn
            dests = sorted(self._hero_options(g.hero(p)))
            d = self._approach_dest(dests, rng) if rng.random() < ROLLOUT_APPROACH_PROB else rng.choice(dests)
            return ("place", d, rng.choice([x for x in self._policies(p) if x in ROLLOUT_POLICIES]))
        if self.pending is not None or self.phase != "action":
            return rng.choice(self.legal_moves())
        p = g.turn
        attacks = self._attack_moves(p)
        if attacks and (tracks.attack_only(g) or rng.random() < ROLLOUT_ATTACK_PROB):
            return rng.choice(attacks)
        boosts = self._boost_variants(p)
        boost = rng.choice(boosts[1:]) if len(boosts) > 1 and rng.random() < ROLLOUT_BOOST_PROB else None
        return ("maneuver", boost.title if boost else None)

    def determinize(self, observer: int, rng: random.Random) -> None:
        g = self.game
        self._eval = None
        g.rng = random.Random(rng.random())     # a shuffle inside a simulated effect never moves the live game's rng
        for p, st in enumerate(g.players):
            if p == observer:
                st.deck.sort(key=lambda c: c.card_id)   # the order of the deck itself is hidden too: from the canonical one
                rng.shuffle(st.deck)
                continue
            gone = st.gone
            known = [c for c in self.knowledge.known_in_hand.get(p, ()) if c not in gone]
            if self.pending is not None and self.pending[2] is not None and g.fighters[self.pending[0]].owner == p \
                    and self.pending[2] not in known:
                known.append(self.pending[2])         # an attack played face up (Witness My Last Battle) is in the hand the defense answers
            top = [c for c in self.knowledge.top_of_deck.get(p, ()) if c not in gone and c not in known]
            pool = sorted((c for c in st.full_set if c not in gone and c not in known and c not in top),
                          key=lambda c: c.card_id)
            face_down = self.pending is not None and self.pending[2] is None and g.fighters[self.pending[0]].owner == p
            if face_down and not self.weights.hidden_attack:
                attacker = g.fighters[self.pending[0]]
                legal = [c for c in known if c.can_attack and c.usable_by(attacker.name)]
                if not legal:
                    legal = [c for c in pool if c.can_attack and c.usable_by(attacker.name)]
                # out-of-sync discard (what is public does not explain the attack): any card of the pool, or of the whole deck
                card = rng.choice(legal or pool or list(st.full_set))
                if card not in known:
                    known.append(card)
                    if card in pool:
                        pool.remove(card)
                self.pending = (self.pending[0], self.pending[1], card)
            rng.shuffle(pool)
            k = max(0, len(st.hand) - len(known))
            maybe = [c for c in self.knowledge.possible_in_hand.get(p, ()) if c in pool]
            if maybe and k:
                # seen once but maybe gone face down: between lo and hi of them are in the hand, the rest back in the pool
                lo, hi = self.knowledge.possible_bounds.get(p, (0, len(maybe)))
                lo = min(lo, k, len(maybe))
                chosen = rng.sample(maybe, rng.randint(lo, min(max(hi, lo), k, len(maybe))))
                others = [c for c in pool if c not in maybe]
                st.hand = known + chosen + others[:k - len(chosen)]
                leftover = others[k - len(chosen):] + [c for c in maybe if c not in chosen]
                rng.shuffle(leftover)
                st.deck = top + leftover
                if face_down and self.weights.hidden_attack:
                    self._commit_attack(st, known, rng)
                continue
            st.hand = known + pool[:k]
            st.deck = top + pool[k:]
            if face_down and self.weights.hidden_attack:
                self._commit_attack(st, known, rng)

    def _commit_attack(self, st: PlayerState, known: list[Card], rng: random.Random) -> None:
        """The face-down attack of a rival whose hand was just dealt (the known cards and the sampled ones): one of the attack cards that
        hand holds, each card as likely as any other, so a hand with a known Fireball and four hidden cards plays it about one time in five and
        not every time. A hand that holds none (what is public does not explain the attack) is given one from the cards still unseen, in place of
        a sampled one; a pool without any, or a set that cannot attack, plays any card of the set."""
        g = self.game
        attacker = g.fighters[self.pending[0]]
        usable = lambda cards: [c for c in cards if c.can_attack and c.usable_by(attacker.name)]
        legal = usable(st.hand)
        if not legal:
            legal = usable(st.deck) or list(st.full_set)
            card = rng.choice(legal)
            if card in st.deck:
                st.deck.remove(card)
            swap = [c for c in st.hand if c not in known] or st.hand
            if swap:
                out = rng.choice(swap)
                st.hand.remove(out)
                st.deck.append(out)
            st.hand.append(card)
        else:
            card = rng.choice(legal)
        self.pending = (self.pending[0], self.pending[1], card)

    # ---------- automatic steps ----------
    def _advance(self) -> None:
        g = self.game
        while g.winner is None:
            if self.pending is not None:
                if self.pending[2] is None or len(self._defend_moves()) > 1:
                    return
                self.apply(("defend", None))
                return
            p = g.turn
            if self.phase == "start":
                hero = g.hero(p)
                if hero.name == "Medusa":
                    if self._ability_targets(p):
                        return
                    self.phase = "action"
                    continue
                if hero.name == "Hellboy" and "hellboy" not in g.fx.dsl_heroes:   # interpreted: begin_turn did it
                    if g.form(p) == ANUNG and g.players[p].hand:
                        return
                    g.hellboy_detective_draw(p)
                self.phase = "action"
                continue
            if self.phase == "maneuver_place":      # without pruning: here all that matters is whether there is a choice
                hero = g.hero(p)
                if len(self._hero_options(hero)) == 1 and len(self._policies(p)) == 1:
                    self.apply(("place", hero.pos, "stay"))
                return
            if self.phase in self.SUBPHASES:
                moves = self.legal_moves()
                if len(moves) == 1:         # sub-phase without a real choice: it resolves itself
                    self.apply(moves[0])
                return
            if not tracks.turn_goes_on(g):
                g.end_turn()
                g.begin_turn()
                self.phase = "start"
                continue
            return

    # ---------- generators ----------
    def _ability_targets(self, p: int) -> list[Fighter]:
        medusa = self.game.hero(p)
        return [f for f in self.game.foes(p) if self.game.board.share_zone(medusa.pos, f.pos)]

    def _start_moves(self, p: int) -> list:
        g = self.game
        hero = g.hero(p)
        if hero.name == "Medusa":
            return [("ability", f.fid) for f in self._ability_targets(p)] + [("ability", None)]
        return [("anung", t) for t in dict.fromkeys(c.title for c in g.players[p].hand)]

    def _defend_moves(self) -> list:
        g = self.game
        target = g.fighters[self.pending[1]]
        out, seen = [("defend", None)], set()
        for c in g.players[target.owner].hand:
            if c.can_defend and c.usable_by(target.name) and c.title not in seen:
                seen.add(c.title)
                out.append(("defend", c.title))
        return out

    def _attack_titles(self, p: int, f: Fighter, target: Fighter | None = None) -> list[str]:
        """The titles `f` may attack with; with `target`, only the cards that can reach it (an adjacent-only attack)."""
        return list(dict.fromkeys(c.title for c in self.game.players[p].hand if enraged.may_attack_with(self.game, p, c) and c.usable_by(f.name)
                                  and (target is None or self.game.attack_card_reaches(f, target, c))))

    def _attack_moves(self, p: int) -> list:
        g = self.game
        out = []
        for f in g.own(p):
            if not self._attack_titles(p, f):
                continue
            out += [("attack", f.fid, t.fid) for t in g.foes(p) if g.can_declare_attack(f, t) and self._attack_titles(p, f, t)
                    and (g.paid_actions > 0 or g.free_attack_for(t.fid) is not None)]
        return out

    def _scheme_moves(self, p: int) -> list:
        """Medusa's schemes with their planned target / policy (C5); any other interpreted hero's with the chooser
        variants of `scheme_variants`, capped at SCHEME_MOVES_KEEP (the safe lines are the ones dropped). A hero
        outside `fx.dsl_heroes` (a save that switched the interpreter off) plays no scheme in the search."""
        g = self.game
        hero = g.hero(p)
        slug = g.players[p].hero.slug
        interpreted = slug in g.fx.dsl_heroes
        out, seen = [], set()
        for c in g.players[p].hand:
            if not c.is_scheme or c.title in seen or scheme_fighter(g, p, c) is None:
                continue
            seen.add(c.title)
            if c.title == "A Momentary Glance":
                out += [("scheme", c.title, t.fid, None) for t in g.foes(p) if g.board.share_zone(hero.pos, t.pos)]
            elif c.title == "Winged Frenzy":
                out += [("scheme", c.title, None, v) for v in FRENZY_VARIANTS]
            elif interpreted and not is_medusa_card(c):
                out += [("scheme", c.title, None, v) for v in scheme_variants(slug, c.title)]
        if len(out) > SCHEME_MOVES_KEEP:
            out = sorted(out, key=lambda m: m[3] == "safe")[:SCHEME_MOVES_KEEP]
        return out

    def _pure_loss(self, p: int, card: Card, variant: str | None) -> bool:
        """`_judge_pure_loss`, memoized by what the verdict reads of the state: everything of the mover's and the
        public cards and pieces, and of the rival only the sizes of hand and deck (the determinization re-samples
        their ids and order at every iteration, and a scheme that only spends moves none of them)."""
        key = self._pure_loss_key(p, card, variant)
        verdict = _pure_loss_cache.get(key)
        shadow = PURE_LOSS_SHADOW
        if shadow["on"]:
            exact = self._judge_pure_loss(p, card, variant)
            shadow["verdicts"] += 1
            if verdict is not None:
                shadow["hits"] += 1
                if verdict != exact:
                    shadow["disagree"].append((card.title, variant, verdict, exact))
            else:
                _pure_loss_cache[key] = exact
            return exact
        if verdict is None:
            if len(_pure_loss_cache) >= MOVES_CACHE_MAX:
                _pure_loss_cache.clear()
            verdict = _pure_loss_cache[key] = self._judge_pure_loss(p, card, variant)
        return verdict

    def _pure_loss_key(self, p: int, card: Card, variant: str | None) -> tuple:
        g = self.game
        mine, rival = g.players[p], g.players[1 - p]
        ids = lambda cards: tuple(c.card_id for c in cards)
        return (card.card_id, variant, p, g.turn, g.actions_left, g.board.key, ids(mine.hand), tuple(sorted(ids(mine.deck))),
                ids(mine.discard), ids(rival.discard), len(rival.hand), len(rival.deck), tuple(g.drawn),
                tuple((fid, f.hp, f.pos, f.alive) for fid, f in sorted(g.fighters.items())),
                tuple(g.fx.ongoing_card_id(q) for q in (0, 1)), repr(g.fx.statuses), repr(g.fx.modifiers), repr(g.fx.counters))

    def _judge_pure_loss(self, p: int, card: Card, variant: str | None) -> bool:
        """The scheme, played here as `apply` would, only spends: its own card and action, and maybe more cards of the
        hand (No, Really, I'm a Doctor with nobody to heal puts one back on the deck). Nothing else moved: no piece, no
        health, no ONGOING or status, no rival card, no draw, no action handed back, no card gained. Such a line is not a
        move while the deck holds cards (with an empty deck it is the pass that does not exhaust), as in
        `MedusaAI.scheme_act`. The leaf evaluation cannot tell by itself: a card is 0.15 / hand limit of a hero's life
        and the random placements of the maneuvers it competes with are noisier than that."""
        g = self.game
        if not g.players[p].deck:
            return False
        after = g.clone()
        after.rng = random.Random(0)        # the clone shares the game's rng: a simulated shuffle must not move it
        after.drawn = list(g.drawn)         # `Game.clone` resets the draw counter the signatures compare
        played = next(c for c in after.players[p].hand if c.card_id == card.card_id)
        after.play_scheme(p, scheme_fighter(after, p, played), played,
                          choosers={p: SyntheticChooser(policy=variant or "greedy"), 1 - p: SyntheticChooser(policy="greedy")})
        if after.winner is not None or after.actions_left >= g.actions_left:
            return False
        kept = {c.card_id for c in g.players[p].hand}
        if any(c.card_id not in kept for c in after.players[p].hand):
            return False
        # play_signature[0] is the own hand (it may shrink) and [1] the own deck (it may take those cards)
        return play_signature(g, p, card)[2:] == play_signature(after, p, card)[2:]

    def _boost_variants(self, p: int) -> list[Card | None]:
        """Without boost, the cheapest card with the maximum boost and the cheapest card in hand (if its boost is
        different): at most three reaches."""
        may = maneuver_may_spend if p == self.observer else can_be_boost     # Iván's bans are the bot's own; the modelled rival boosts as the rules allow
        every = self.game.players[p].hand
        usable = {c.card_id: can_use(self.game, p, c) for c in every}
        defenders = [c for c in every if c.can_defend and usable[c.card_id]]
        last_defence = defenders[0] if len(defenders) == 1 and p == self.observer else None     # the bot's only defence card: the dearest of the hand
        worth = lambda c: (0.0 if not usable[c.card_id] else card_worth(c) + (LAST_DEFENCE_WORTH if c is last_defence else 0.0))    # a card nobody alive can use is the cheapest of all
        hand = [c for c in every if may(c) and not (p == self.observer and held_for_plan(self.game, p, c, every))]
        if not hand:
            return [None]
        cheapest = min(hand, key=lambda c: (worth(c), c.card_id))
        top = max(hand, key=lambda c: (c.boost, -worth(c), -c.card_id))
        out = [None, top]
        if cheapest.boost != top.boost:
            out.append(cheapest)
        g = self.game
        rich = max(hand, key=lambda c: (boost_effect_value(g, p, c) - 0.3 * worth(c), -c.card_id))    # the best BOOSTED WITH for its price
        if boost_effect_value(g, p, rich) > 0 and all(rich.title != c.title for c in out if c is not None):
            out.append(rich)
        return out

    def _extra(self) -> int:
        title, g = self.partial[0], self.game
        boost = by_title(g.players[g.turn].hand, title) if title is not None else None
        return (boost.boost if boost is not None else 0) + g.maneuver_bonus(g.turn, boost)

    def _approach_dest(self, dests: list[int], rng: random.Random) -> int:
        """Hero destination in the rollout: a space from which it strikes a rival; if there is none, the closest.
        Without this Hellboy never approached Medusa in 6 plays and being in her reach was not punished."""
        g = self.game
        p = g.turn
        foes = foe_positions(g, p)
        striking = [d for d in dests if d in self._striking_spots(p)]
        if striking:
            return rng.choice(striking)
        return min(dests, key=lambda d: (nearest(g.board, d, foes), d))

    def _striking_spots(self, p: int) -> frozenset[int]:
        g = self.game
        hero = g.hero(p)
        return frozenset().union(*(strike_spots(g.board, e.pos, hero.ranged, hero.reach) for e in g.foes(p)))

    def _policies(self, p: int) -> tuple[str, ...]:
        if not any(not f.hero for f in self.game.own(p)):
            return ("stay",)
        base = SIDEKICK_POLICIES + (BESIDE,) if beside_stake(self.game, p) else SIDEKICK_POLICIES
        return base + (PACK,) if pack.passive(self.game, p) else base

    def _placements(self, p: int, hero: Fighter) -> list[tuple[int, str]]:
        """(hero destination, sidekick policy) that enter the tree: the `PLACEMENT_KEEP` best by the
        static evaluation with all already moved and seen as an end of turn (the rival moves afterwards), the
        `PLACEMENT_STRIKE_KEEP` best ones from which the hero strikes, and staying still."""
        g = self.game
        options = sorted(self._hero_options(hero))
        policies = self._policies(p)
        if self._pack_presses(p) and self._attack_moves(p):
            # a pack with a blow to land walks only to join it: every Raptor to a space beside the rival, the hero where he strikes from
            options = [d for d in options if d in self._striking_spots(p)] or options
            policies = (PACK,)
        if len(options) * len(policies) <= PLACEMENT_KEEP:
            return [(d, policy) for d in options for policy in policies]
        extra = self._extra()
        side = [f for f in g.own(p) if not f.hero]
        origin = {f.fid: f.pos for f in g.own(p)}
        scored = []
        seen = set()        # policies that end in the same sidekick squares are one placement: the first one stands

        def score(d: int, policy: str) -> None:
            plan = sidekick_plan(g, p, extra, policy, hero_dest=d)
            if (d, plan) in seen:
                return
            seen.add((d, plan))
            hero.pos = d
            for fid, dest in plan:
                g.fighters[fid].pos = dest
            scored.append((self._exposure(1 - p, True) - self._exposure(p, True), d, policy))
            for f in side:
                f.pos = origin[f.fid]

        spots = self._striking_spots(p)

        def pick() -> tuple[list, set]:
            ranked = sorted(scored, key=lambda x: (-x[0], x[1], x[2]))
            striking = [(d, policy) for _, d, policy in ranked if d in spots][:PLACEMENT_STRIKE_KEEP]
            return ranked, {(d, policy) for _, d, policy in ranked[:PLACEMENT_KEEP]} | set(striking) | {(origin[hero.fid], "stay")}

        plain = [x for x in policies if x != "guard"]
        for d in options:
            for policy in plain:
                score(d, policy)
        if "guard" in policies:     # the covering placements cost a path analysis each: only for hero squares that already made the cut
            for d in sorted({d for d, _ in pick()[1]}):
                score(d, "guard")
        hero.pos = origin[hero.fid]
        keep = pick()[1]
        return sorted(keep)

    # ---------- evaluation ----------
    def _side_value(self, p: int, urgent: bool = False) -> float:
        if self.weights.normalize:
            return self._side_value_normalized(p, urgent)
        g, w = self.game, self.weights
        hero = g.hero(p)
        everyone = g.own(p, alive_only=False)
        side = [f for f in everyone if not f.hero]
        if w.team_life and g.players[p].hero.team:
            # a team is one life: with each follower counted as a sidekick on top of a whole hero, three Raptors were worth three heroes
            # against the rival's one, the leaf sat on the flat end of `squash` and no move (a card kept, a blow taken) changed it
            life = sqrt(sum(f.hp for f in everyone if f.alive) / sum(f.max_hp for f in everyone))
            side_hp = 0.0
        else:
            # square root: the first HP are worth more than the last; staying alive at 3 HP is not almost the same as dying
            life = sqrt(max(hero.hp, 0) / hero.max_hp)
            side_hp = sum(f.hp for f in side if f.alive) / hero.max_hp      # in hero HP: a Harpy is worth less than Lobster
        alive = sum(1 for f in side if f.alive) / len(side) if side else 0.0
        cap = g.hand_cap(p)                                  # a 3-card hero (Michelangelo) is full at 3, not at 7
        held = len(g.players[p].hand)
        hand = min(held, cap) / cap
        reserve = min(held, HAND_RESERVE, cap) / min(HAND_RESERVE, cap)
        deck = min(len(g.players[p].deck), 10) / 10
        next_to = 0.0
        if alive and hero.pos is not None and beside_stake(g, p):
            next_to = sum(1 for f in side if f.alive and f.pos in g.board.adj[hero.pos]) / len(side)
        return (life + w.sidekicks * side_hp + w.beside * next_to + w.alive * alive + w.hand * hand + w.hand_reserve * reserve + w.pack * self._pack_ready(p)
                + w.deck * deck + w.ongoing * ongoing.worth(g, p) / hero.max_hp - self._exposure(p, urgent))

    def _side_value_normalized(self, p: int, urgent: bool) -> float:
        return sum(self._side_terms(p, urgent).values())

    def _side_terms(self, p: int, urgent: bool) -> dict[str, float]:
        """What `_side_value` measures, with every side at 1.0 for its own full strength, so that the position is judged by what each
        side has lost and not by how many pieces it began with (a hero with a sidekick opened 0.5 ahead of one without, and a bot facing
        the Raptors saw three lives of Blue): the hit points of the hero (square root: the first ones are worth more) and of all the
        sidekicks together, each as a share of what it started with and weighed by its share of the side's hit points; a team is one
        life, every fighter's hit points over the total. A card in hand is `card_hp` hit points of the side's life (up to the hand limit),
        a card of the deck `deck_hp` (no ceiling), and the exhaustion the deck owes over the length of the game is charged (`_exhaustion`)."""
        g, w = self.game, self.weights
        hero = g.hero(p)
        everyone = g.own(p, alive_only=False)
        side = [f for f in everyone if not f.hero]
        # the draw the next turn will cost: with fewer cards in the deck than that, every fighter pays EXHAUST_DAMAGE for each one it is short of
        # (a maneuver is the only way to move), so a hero left at that many hit points or fewer is, for the next turn, a hero that cannot move
        owed = EXHAUST_DAMAGE * max(0, w.next_draw - len(g.players[p].deck)) if w.next_draw else 0
        if w.team_life and g.players[p].hero.team:
            life_hp = sum(f.max_hp for f in everyone)
            life = sqrt(sum(max(f.hp - owed, 0) for f in everyone if f.alive) / life_hp)
        else:
            life = sqrt(max(hero.hp - owed, 0) / hero.max_hp)
            if side:
                side_max = sum(f.max_hp for f in side)
                share = side_max / (side_max + hero.max_hp)
                life = (1 - share) * life + share * sum(max(f.hp - owed, 0) for f in side if f.alive) / side_max
        alive = sum(1 for f in side if f.alive) / len(side) if side else 1.0
        cap = g.hand_cap(p)
        held = len(g.players[p].hand)
        hp_life = 1.0 / (2.0 * REFERENCE_HP)             # a hit point in lives at full health (the slope of the square root there), on one scale for every side: a card is worth the same to a team and to a hero
        hand = (w.card_hp * min(held, cap) * hp_life) if w.card_hp else w.hand * min(held, cap) / cap
        reserve = min(held, HAND_RESERVE, cap) / min(HAND_RESERVE, cap)
        deck = (w.deck_hp * len(g.players[p].deck) * hp_life) if w.deck_hp else w.deck * min(len(g.players[p].deck), 10) / 10
        next_to = 0.0
        if side and hero.pos is not None and beside_stake(g, p):
            next_to = sum(1 for f in side if f.alive and f.pos in g.board.adj[hero.pos]) / len(side)
        return {"life": life, "beside": w.beside * next_to, "alive": w.alive * alive, "hand": hand, "hand_reserve": w.hand_reserve * reserve,
                "pack": w.pack * max(0, self._pack_ready(p)), "deck": deck, "ongoing": w.ongoing * ongoing.worth(g, p) / hero.max_hp,
                "exposure": -self._exposure(p, urgent), "exhaustion": -self._exhaustion(p) * hp_life}

    def _exhaustion(self, p: int) -> float:
        """Hit points that `p`'s deck will cost it through exhaustion over the rest of the game, in the units of `exhaustion_owed`: the draws it
        is short of, over the turns the game can still last (`GAME_TURNS` of each player's own, less those played), at its own rate of draws a turn (one, plus what its start-of-turn triggers
        discard from the bottom of the deck: Wildfire), each costing `EXHAUST_DAMAGE` to every fighter it still has. The bill grows smoothly as
        the deck runs down (`exhaustion_owed`), so the last cards of a deck are worth more than the first ones. The length is the turns of
        `GAME_TURNS` the game has left, never fewer than `MIN_HORIZON` (a game can always go on a few turns more), and not a function of the hit
        points or the hands: the first version took the turns until a hero falls, and every blow on a deck that burns shortened the race and
        cancelled what it took from her life, while a hand emptied by attacking read as a shorter game."""
        w = self.weights
        if not w.race:
            return 0.0
        g = self.game
        length = max(MIN_HORIZON, GAME_TURNS - g.turn_no // 2)
        st = g.players[p]
        rate = DRAWS_PER_TURN + sum(1 for t in st.hero.triggers if t.get("when") == "start_of_turn" and "discard_bottom" in str(t.get("effect")))
        owed = exhaustion_owed(max(0.0, length * rate - len(st.deck)))
        share = 1.0 if p == self.observer else w.race_rival
        return share * w.race * EXHAUST_DAMAGE * len(g.own(p)) * owed if owed else 0.0

    def _pack_presses(self, p: int) -> bool:
        """Whether a hero with the pack bonus forces the blow on its last action and binds the walk to the rival's side (Iván: super
        aggressive), as its `PackPlan` says. A bot of another hero facing the Raptors models the pack as it was, always pressing: its hand
        is a sample, and that bot's play against the Raptors was not measured with any other model."""
        g = self.game
        if not pack.passive(g, p):
            return False
        if p != self.observer:
            return True
        plan = pack_plan(g, p)
        if plan.mode == "press":
            return True
        if plan.mode == "pulse":       # `span` turns forward, `span` back: a pack that does not draw spends cards only while it presses
            return (g.turn_no // 2 // plan.span) % 2 == 0
        hand = g.players[p].hand
        if len(hand) <= plan.reserve:
            return False
        defenses = sum(1 for c in hand if c.can_defend)
        return defenses > 1 or (defenses == 1 and any(c.can_attack and not c.can_defend for c in hand))

    def _pack_ready(self, p: int) -> int:
        """Fighters beyond the first of `p` standing beside the same rival, for a hero whose attacks grow with them (`pack.passive`): the pack
        bonus every blow on that rival is worth next turn. 0 for any other hero."""
        g = self.game
        if not pack.passive(g, p):
            return 0
        mine = [f.pos for f in g.own(p) if f.pos is not None]
        return max((sum(1 for pos in mine if pos in g.board.adj[e.pos]) - 1 for e in g.foes(p) if e.pos is not None), default=0) if len(mine) > 1 else 0

    def _exposure(self, p: int, urgent: bool) -> float:
        """What the threat on `p`'s hero subtracts from their side (weighted `threat`)."""
        w = self.weights
        expected, lethal = self.threat(p, urgent)
        return w.threat * expected + w.lethal * lethal + (w.fighter_threat * self._fighters_exposure(p, urgent) if w.fighter_threat else 0.0)

    def _fighters_exposure(self, victim: int, urgent: bool) -> float:
        """The loss, in lives, of the sidekick the rival's next turn hurts most: the hit points it would lose (up to the ones it has) and the
        chance of it falling, each as `_side_value` counts them. A sidekick left next to the rival with a few hit points shows here; with the
        weight `fighter_threat` it is added to the threat on the hero. A team's fighters are all in `threat` already."""
        g, w = self.game, self.weights
        hero = g.hero(victim)
        if not hero.alive or (w.team_life and g.players[victim].hero.team):
            return 0.0
        side = [f for f in g.own(victim, alive_only=False) if not f.hero]
        if not side:
            return 0.0
        per_hp = 1.0 / (sum(f.max_hp for f in side) + hero.max_hp) if w.normalize else w.sidekicks / hero.max_hp
        per_fall = w.alive / len(side)
        worst = 0.0
        for f in side:
            blows = self._blows_on(victim, f) if f.alive else None
            if blows is not None:
                expected, kill = blows
                worst = max(worst, per_hp * min(expected, f.hp) + per_fall * kill)
        fear = w.caution if victim == self.observer else 1.0
        return fear * worst * (w.victim_moves_first if g.turn == victim and not urgent else 1.0)

    def threat(self, victim: int, urgent: bool = False) -> tuple[float, float]:
        """Threat on `victim`'s hero in the rival's next turn: (expected damage as a fraction of its current
        HP, probability of being killed). Each rival counts if it reaches a striking space with its movement
        (without passing through `victim`'s fighters: sidekicks in the way are a shield), discounted if it needs a
        boost: the biggest one the attacker's side still has to play (`boost_reach`, public), none once its cards are
        gone. The cost of an attack is the average value of the attacker's whole deck against the best defense in
        hand, plus the defense card it spends; with the weight `reserve`, each later blow meets the next defense of the hand
        (none left: it lands whole). Actions limit: whoever is already in range can hit twice;
        whoever has to maneuver, once. If the threatened one moves first, the threat is discounted, except with `urgent`
        (the position is seen as an end of turn: used by the placement pruning). For a team that is one life (`_life_pool`)
        the blows are measured on each of its fighters, the worst counts, over the hit points of all of them, and none of
        them kills while another stands."""
        g, w = self.game, self.weights
        hero = g.hero(victim)
        if not hero.alive:
            return 0.0, 1.0
        pool = self._life_pool(victim)
        blows = [b for b in (self._blows_on(victim, f) for f in pool) if b is not None]
        gaze_hp, gaze_kill = self._zone_exposure(victim, hero)
        urgency = w.victim_moves_first if g.turn == victim and not urgent else 1.0
        if not blows:
            return gaze_hp * urgency, gaze_kill * urgency
        expected = max(e for e, _ in blows)
        lethal = max(k for _, k in blows) if len(pool) == 1 else 0.0       # a team is beaten only with its last fighter
        # over the current HP, not the maximum: the same expected hit weighs more the less life is left
        fear = w.caution if victim == self.observer and not (w.team_life and g.players[victim].hero.team) else 1.0       # only of the blows in reach: the zone hazard keeps its weight; a team keeps the fear its own profile was measured with
        return (min(1.0, fear * expected / sum(f.hp for f in pool) + gaze_hp) * urgency,
                1 - (1 - lethal * urgency) * (1 - gaze_kill * urgency))

    def _life_pool(self, p: int) -> list[Fighter]:
        """The living fighters whose hit points are `p`'s life: the hero, or with the weight `team_life` every fighter of a team (the
        Raptors lose with the last of the three, so the three are one life and the rival's blows fall on whichever of them it reaches)."""
        g = self.game
        return g.own(p) if self.weights.team_life and g.players[p].hero.team else [g.hero(p)]

    def _blows_on(self, victim: int, hero: Fighter) -> tuple[float, float] | None:
        """(expected damage in hit points, probability of being killed) for `hero`, a fighter of `victim`'s life pool, in the
        rival's next turn; None when no rival reaches it."""
        g, w = self.game, self.weights
        attacker = 1 - victim
        hand = g.players[victim].hand
        defenses = sorted((c.value for c in hand if c.can_defend and c.usable_by(hero.name)), reverse=True)
        actions = g.actions_left if g.turn == attacker else 2
        strikes, walk_strikes = actions, actions - 1    # blows from where the rival stands, and after a Maneuver to get in range
        answers = [defenses[0] if defenses else 0] * strikes       # the defense each of those blows meets
        held = len(g.players[attacker].hand)
        if w.reserve:
            # a card per blow on both sides: the attacker's are the ones it holds (the count is public) plus one drawn per Maneuver
            strikes = max(min(actions - walks, held + walks) for walks in range(actions + 1))
            walk_strikes = min(walk_strikes, held + 1)
            answers = (defenses + [0] * strikes)[:strikes]
        shield = frozenset(g.occupied(victim))
        mates = g.occupied(attacker)
        boost = None                                    # the attacker's boost reach: read only when someone needs it
        chained = bool(w.piles) and "voyage" in g.players[attacker].hero.counters      # each VOYAGE blow lands in the pile: the next one is worth one more
        in_range: list[list[tuple[float, float]]] = []      # per blow, (cost, p. of killing) of whoever is already in range
        after_move: list[list[tuple[float, float]]] = []    # same for whoever arrives by maneuvering (factor already applied)
        for e in g.foes(victim):
            values = (unseen_values(g.players[attacker], e.name, bool(w.piles)) if w.unseen else attack_values(g.players[attacker], e.name, bool(w.piles)))
            if w.unseen == UNSEEN_MEAN:
                values = tuple(v for v in values if v != NO_ATTACK)
            if not values or values[0] == NO_ATTACK:
                continue
            spots = strike_spots(g.board, hero.pos, e.ranged, e.reach)
            own = frozenset(mates - {e.pos})
            steps = e.move + free_steps(g, e)
            if e.pos in spots:
                factor, bucket = 1.0, in_range
            elif reach_from(g.board, e.pos, steps, own, shield) & spots:
                factor, bucket = 1.0, after_move
            else:
                if boost is None:
                    boost = boost_reach(g, attacker)
                if not boost or not reach_from(g.board, e.pos, steps + boost, own, shield) & spots:
                    continue
                factor, bucket = w.boost_reach, after_move
            bonus = g.attack_bonus(e, hero if e.pos in spots else None)
            blows: list[tuple[float, float]] = []
            cards = max(held, 1) if bucket is in_range else held + 1       # a blow after a Maneuver is dealt from a hand with the card it drew
            for rank, answer in enumerate(answers):
                if blows and answer == answers[0] and w.unseen != UNSEEN_BEST:
                    blows.append(blows[0])
                    continue
                delta = bonus + (rank if chained else 0) - answer
                net, kill = best_attack_stats(values, cards, rank, delta, hero.hp) if w.unseen == UNSEEN_BEST else attack_stats(values, delta, hero.hp)
                cost = net + (w.defend_card_hp if answer and (net or w.unseen != UNSEEN_BEST) else 0.0)     # no blow, no defense card spent
                if blows:           # `reserve` below 1: part of the way from the best defense to this one
                    first_cost, first_kill = blows[0]
                    cost, kill = first_cost + w.reserve * (cost - first_cost), first_kill + w.reserve * (kill - first_kill)
                blows.append((cost, kill))
            bucket.append([(factor * cost, factor * kill) for cost, kill in blows])
        if not in_range and not after_move:
            return None
        everyone = in_range + after_move
        now_cost = [max((blows[i][0] for blows in in_range), default=0.0) for i in range(strikes)]
        now_kill = [max((blows[i][1] for blows in in_range), default=0.0) for i in range(strikes)]
        any_cost = [max(blows[i][0] for blows in everyone) for i in range(walk_strikes)]
        any_kill = max(blows[0][1] for blows in everyone) if walk_strikes >= 1 else 0.0
        # two attacks in a row from where it is, or a maneuver and the best attack of all
        return max(fsum(now_cost), fsum(any_cost)), max(1 - prod(1 - k for k in now_kill), any_kill)

    def _zone_exposure(self, victim: int, hero: Fighter) -> tuple[float, float]:
        """(expected damage as a fraction of HP, probability of dying) from the rival hero's start-of-turn damage to a fighter in
        its zone (Medusa's gaze, from the effects data), for the fighters of `victim` that stand in that zone: the hero alone, or
        every fighter of a team (the Raptors: many fighters of few hit points, each one standing there is a target the rival
        picks from, so each is weighed on its own (as its share of the team's life with the weight `team_life`) and they add up; the
        game is lost only when the last one falls). The hit points (never the chance of dying) weigh less the better the fighter's defenses in hand cover the
        rival hero's average attack (`zone_cover_factor`, as in the heuristic's `zone_hazard_cost`)."""
        g = self.game
        rival = g.hero(1 - victim)
        exposed = zone_exposed(g, victim, rival)
        if not exposed:
            return 0.0, 0.0
        dmg = zone_damage(g, 1 - victim)
        if not dmg:
            return 0.0, 0.0
        values = attack_values(g.players[1 - victim], rival.name, bool(self.weights.piles))
        blow = sum(values) / len(values) if values else 0.0
        hand = g.players[victim].hand
        team = g.players[victim].hero.team
        pool = self._life_pool(victim)
        life = sum(f.hp for f in pool)
        expected = sum(min(1.0, dmg / f.hp) * (f.hp / life if len(pool) > 1 else 1.0)
                       * zone_cover_factor([c.value for c in hand if c.can_defend and c.usable_by(f.name)], blow)
                       for f in exposed)
        last = len(g.own(victim)) == 1
        dies = any(dmg >= f.hp for f in exposed) and (last or not team)
        return (expected if team else min(1.0, expected)), 1.0 if dies else 0.0
