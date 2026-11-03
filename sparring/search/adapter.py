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
as a block with a policy (stay, advance, retreat). Only complete placements enter the tree
(hero and sidekicks already moved) best scored by the static evaluation as an end-of-turn position
(`PLACEMENT_KEEP`), plus the best ones from which the hero strikes and staying still: with all of them, the maneuver
had ~30 leaves with few visits each and the noise chose the space. The rollout does not prune.

No cheating: `determinize` only uses `full_set`, `discard`, `len(hand)` and the known cards (`Knowledge`).

Leaf evaluation (`evaluate`): material of each side (hero HP, HP and number of sidekicks, hand, deck) minus
the threat on its hero next turn (`EngineState.threat`): expected damage from the rivals that really reach it
(without passing through its own fighters, so a sidekick in the corridor is a shield), with the average attack of the
attacker's whole deck against the best defense in hand, plus the probability of being killed. It is generic
(any hero, any sidekick) and, subtracted from the opposing side, is its own pressure: a sidekick within range of the
rival hero counts as an attacker, not just as HP to keep. The weights live in `EvalWeights` (F10 tunes them).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from functools import lru_cache
from math import sqrt

from ..ai_medusa import GAZE, boost_effect_value, bot_may_spend, scheme_fighter
from ..cards import Card
from ..combat import is_medusa_card, resolve_combat
from ..controller import Controller
from ..effects import ongoing
from ..effects.inventions import INVENTION_WORTH
from ..effects.choose import SCHEME_VARIANTS, SyntheticChooser
from ..effects.model import load_effects, walk_ops
from ..state import ANUNG, Fighter, Game, PlayerState

SIDEKICK_POLICIES = ("stay", "advance", "retreat")
FRENZY_VARIANTS = ("advance", "retreat")
SCHEME_MOVES_KEEP = 6         # scheme moves per node: every title's greedy line first, the safe ones while they fit
ASKING_OPS = ("move", "place", "swap", "revive", "summon", "optional", "choose_effect", "choose", "search_deck")
ROLLOUT_ATTACK_PROB = 0.7     # in the rollout, whoever can attack almost always does (makes threats visible)
ROLLOUT_BOOST_PROB = 0.3
ROLLOUT_APPROACH_PROB = 0.5   # in the rollout, the hero maneuvering looks for a space from which to strike
BOOST_STEPS = 2               # extra steps an attacker can buy with a boost (typical of the deck)
PLACEMENT_KEEP = 6            # maneuver placements in the tree: the best by static evaluation...
PLACEMENT_STRIKE_KEEP = 2     # ...plus the best ones from which the hero strikes, plus staying still
ANUNG_FREE_STEPS = 2          # free movement of ANUNG UN RAMA at the start of the turn (see MedusaAI)


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
    slope: float = 1.5              # scale of `squash` over the difference between sides


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


_reach_cache: dict[tuple, frozenset[int]] = {}
_near_cache: dict[tuple, int] = {}
_moves_cache: dict[tuple, list] = {}
MOVES_CACHE_MAX = 50_000


def reach_from(board, pos: int, steps: int, own: frozenset[int], enemy: frozenset[int],
               through: bool = False) -> frozenset[int]:
    """`Board.reachable` with a cache: within a search the same positions repeat thousands of times."""
    key = (board.key, pos, steps, own, enemy, through)
    r = _reach_cache.get(key)
    if r is None:
        r = _reach_cache[key] = frozenset(board.reachable(pos, steps, set(own), set(enemy), through))
    return r


def reach(game: Game, f: Fighter, steps: int, through: bool = False) -> frozenset[int]:
    """`Game.legal_moves` with a cache (a fighter immobilized by an effect, Burning Barrier, stays where it is)."""
    if not game.fx.can_move(f):
        return frozenset({f.pos})
    own = frozenset(game.occupied(f.owner) - {f.pos})
    enemy = frozenset(game.occupied(1 - f.owner))
    return reach_from(game.board, f.pos, steps, own, enemy, through)


def nearest(board, pos: int, foes: tuple[int, ...]) -> int:
    key = (board.key, pos, foes)
    d = _near_cache.get(key)
    if d is None:
        d = _near_cache[key] = min((board.distance(pos, e) for e in foes), default=0)
    return d


_strike_cache: dict[tuple, frozenset[int]] = {}
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


def strike_spots(board, target_pos: int, ranged: bool) -> frozenset[int]:
    """Spaces from which an attacker (melee or ranged) strikes whoever is at `target_pos`."""
    key = (board.key, target_pos, ranged)
    r = _strike_cache.get(key)
    if r is None:
        r = _strike_cache[key] = frozenset(s for s in board.spaces if board.can_reach_target(s, target_pos, ranged))
    return r


def attack_values(st: PlayerState, fighter_name: str) -> tuple[int, ...]:
    """Attack values of the whole deck that `fighter_name` can use: public information, fixed during the game."""
    key = (st.hero_name, fighter_name)
    v = _attack_values_cache.get(key)
    if v is None:
        v = _attack_values_cache[key] = tuple(c.value for c in st.full_set if c.can_attack and c.usable_by(fighter_name))
    return v


def free_steps(game: Game, f: Fighter) -> int:
    """Free movement before maneuvering (today, ANUNG UN RAMA's; what is specific to the hero stays here)."""
    return ANUNG_FREE_STEPS if f.hero and game.form(f.owner) == ANUNG else 0


def policy_dest_from(board, pos: int, options, foes: tuple[int, ...], policy: str) -> int:
    if policy == "stay" or not foes:
        return pos
    cands = set(options) | {pos}
    if policy == "advance":
        return min(cands, key=lambda d: (nearest(board, d, foes), d))
    return max(cands, key=lambda d: (nearest(board, d, foes), -d))


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
    out = []
    for h in sorted((x for x in game.own(player) if not x.hero), key=lambda x: x.fid):
        others = frozenset(v for k, v in own.items() if k != h.fid)
        if not game.fx.can_move(h):
            out.append((h.fid, h.pos))
            continue
        dest = policy_dest_from(board, own[h.fid], reach_from(board, own[h.fid], h.move + extra, others, enemy),
                                foes, policy)
        own[h.fid] = dest
        out.append((h.fid, dest))
    return tuple(out)


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
    return max(options, key=lambda s: (nearest(game.board, s, foes), -s)) if options else None


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
        now = min(max(0, ctx.atk_value - ctx.def_value), t.hp)
        best, best_gain = None, 0.0
        for c in filter(bot_may_spend, hand):
            net = min(max(0, ctx.atk_value + sign * c.boost - ctx.def_value), t.hp)
            gain = sign * (net - now) - 0.3 * card_worth(c) + 0.3 * boost_effect_value(game, self.me, c)     # BOOSTED WITH
            if gain > best_gain:
                best, best_gain = c, gain
        return best

    def choose_discard(self, game: Game, player: int, n: int, reason: str):
        return sorted(game.players[player].hand, key=lambda c: (card_worth(c), c.card_id))[:n]

    def choose_move(self, game: Game, fighter: Fighter, steps: int, through_enemies: bool = False):
        policy = self.state.variant
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
        return moves

    def _signature(self) -> tuple:
        g = self.game
        mover = self.player_to_move()
        return (g.board.key, g.turn, self.phase, self.partial, self.pending[:2] if self.pending else None,
                g.form(1 - g.turn) if self.phase == "start" else None,
                tuple((f.fid, f.pos, f.hp) for f in g.fighters.values() if f.alive),
                tuple(sorted(c.card_id for c in g.players[mover].hand)),
                tuple(f.fid for f in g.fighters.values() if f.alive and not g.fx.can_move(f)))    # pinned by an effect

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
            return [("attack_card", f.fid, t) for t in self._attack_titles(p, f)]
        if self.phase == "maneuver_place":
            return [("place", d, policy) for d, policy in self._placements(p, hero)]
        moves = self._attack_moves(p) + self._scheme_moves(p)
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
            g.use_action()
            self.pending = (att, tgt, by_title(hand, move[2]))
            g.fx.emit("attacked", g.fighters[att], g.fighters[tgt], self.pending[2])   # as Game._declare_attack does
        elif kind == "maneuver":
            self.phase, self.partial = "maneuver_place", (move[1],)
        elif kind == "place":
            title, = self.partial
            _, d, policy = move
            self.phase, self.partial = "action", ()
            boost = by_title(hand, title) if title is not None else None
            plan = sidekick_plan(g, p, boost.boost if boost else 0, policy, hero_dest=d)
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
            return ("place", d, rng.choice(self._policies(p)))
        if self.pending is not None or self.phase != "action":
            return rng.choice(self.legal_moves())
        p = g.turn
        attacks = self._attack_moves(p)
        if attacks and rng.random() < ROLLOUT_ATTACK_PROB:
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
            top = [c for c in self.knowledge.top_of_deck.get(p, ()) if c not in gone and c not in known]
            pool = sorted((c for c in st.full_set if c not in gone and c not in known and c not in top),
                          key=lambda c: c.card_id)
            if self.pending is not None and self.pending[2] is None and g.fighters[self.pending[0]].owner == p:
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
                continue
            st.hand = known + pool[:k]
            st.deck = top + pool[k:]

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
            if g.actions_left <= 0:
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

    def _attack_titles(self, p: int, f: Fighter) -> list[str]:
        return list(dict.fromkeys(c.title for c in self.game.players[p].hand if c.can_attack and c.usable_by(f.name)))

    def _attack_moves(self, p: int) -> list:
        g = self.game
        out = []
        for f in g.own(p):
            if not self._attack_titles(p, f):
                continue
            out += [("attack", f.fid, t.fid) for t in g.foes(p) if g.can_attack(f, t)]
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

    def _boost_variants(self, p: int) -> list[Card | None]:
        """Without boost, the cheapest card with the maximum boost and the cheapest card in hand (if its boost is
        different): at most three reaches."""
        hand = [c for c in self.game.players[p].hand if bot_may_spend(c)]
        if not hand:
            return [None]
        cheapest = min(hand, key=lambda c: (card_worth(c), c.card_id))
        top = max(hand, key=lambda c: (c.boost, -card_worth(c), -c.card_id))
        out = [None, top]
        if cheapest.boost != top.boost:
            out.append(cheapest)
        g = self.game
        rich = max(hand, key=lambda c: (boost_effect_value(g, p, c) - 0.3 * card_worth(c), -c.card_id))    # the best BOOSTED WITH for its price
        if boost_effect_value(g, p, rich) > 0 and all(rich.title != c.title for c in out if c is not None):
            out.append(rich)
        return out

    def _extra(self) -> int:
        title = self.partial[0]
        return by_title(self.game.players[self.game.turn].hand, title).boost if title is not None else 0

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
        return frozenset().union(*(strike_spots(g.board, e.pos, hero.ranged) for e in g.foes(p)))

    def _policies(self, p: int) -> tuple[str, ...]:
        return SIDEKICK_POLICIES if any(not f.hero for f in self.game.own(p)) else ("stay",)

    def _placements(self, p: int, hero: Fighter) -> list[tuple[int, str]]:
        """(hero destination, sidekick policy) that enter the tree: the `PLACEMENT_KEEP` best by the
        static evaluation with all already moved and seen as an end of turn (the rival moves afterwards), the
        `PLACEMENT_STRIKE_KEEP` best ones from which the hero strikes, and staying still."""
        g = self.game
        options = sorted(self._hero_options(hero))
        policies = self._policies(p)
        if len(options) * len(policies) <= PLACEMENT_KEEP:
            return [(d, policy) for d in options for policy in policies]
        extra = self._extra()
        side = [f for f in g.own(p) if not f.hero]
        origin = {f.fid: f.pos for f in g.own(p)}
        scored = []
        for d in options:
            for policy in policies:
                plan = sidekick_plan(g, p, extra, policy, hero_dest=d)
                hero.pos = d
                for fid, dest in plan:
                    g.fighters[fid].pos = dest
                scored.append((self._exposure(1 - p, True) - self._exposure(p, True), d, policy))
                for f in side:
                    f.pos = origin[f.fid]
        hero.pos = origin[hero.fid]
        scored.sort(key=lambda x: (-x[0], x[1], x[2]))
        spots = self._striking_spots(p)
        striking = [(d, policy) for _, d, policy in scored if d in spots][:PLACEMENT_STRIKE_KEEP]
        keep = {(d, policy) for _, d, policy in scored[:PLACEMENT_KEEP]} | set(striking) | {(hero.pos, "stay")}
        return sorted(keep)

    # ---------- evaluation ----------
    def _side_value(self, p: int, urgent: bool = False) -> float:
        g, w = self.game, self.weights
        hero = g.hero(p)
        side = [f for f in g.own(p, alive_only=False) if not f.hero]
        side_hp = sum(f.hp for f in side if f.alive) / hero.max_hp      # in hero HP: a Harpy is worth less than Lobster
        alive = sum(1 for f in side if f.alive) / len(side) if side else 0.0
        cap = g.hand_cap(p)                                  # a 3-card hero (Michelangelo) is full at 3, not at 7
        hand = min(len(g.players[p].hand), cap) / cap
        deck = min(len(g.players[p].deck), 10) / 10
        # square root: the first HP are worth more than the last; staying alive at 3 HP is not almost the same as dying
        return (sqrt(max(hero.hp, 0) / hero.max_hp) + w.sidekicks * side_hp + w.alive * alive + w.hand * hand
                + w.deck * deck + w.ongoing * ongoing.worth(g, p) / hero.max_hp - self._exposure(p, urgent))

    def _exposure(self, p: int, urgent: bool) -> float:
        """What the threat on `p`'s hero subtracts from their side (weighted `threat`)."""
        w = self.weights
        expected, lethal = self.threat(p, urgent)
        return w.threat * expected + w.lethal * lethal

    def threat(self, victim: int, urgent: bool = False) -> tuple[float, float]:
        """Threat on `victim`'s hero in the rival's next turn: (expected damage as a fraction of its current
        HP, probability of being killed). Each rival counts if it reaches a striking space with its movement
        (without passing through `victim`'s fighters: sidekicks in the way are a shield), discounted if it needs a
        boost. The cost of an attack is the average value of the attacker's whole deck against the best defense in
        hand, plus the defense card it spends. Actions limit: whoever is already in range can hit twice;
        whoever has to maneuver, once. If the threatened one moves first, the threat is discounted, except with `urgent`
        (the position is seen as an end of turn: used by the placement pruning)."""
        g, w = self.game, self.weights
        hero = g.hero(victim)
        if not hero.alive:
            return 0.0, 1.0
        attacker = 1 - victim
        hand = g.players[victim].hand
        best_def = max((c.value for c in hand if c.can_defend and c.usable_by(hero.name)), default=0)
        shield = frozenset(g.occupied(victim))
        mates = g.occupied(attacker)
        in_range: list[tuple[float, float]] = []       # (cost per attack, p. of killing) of whoever is already in range
        after_move: list[tuple[float, float]] = []     # same for whoever arrives by maneuvering (factor already applied)
        for e in g.foes(victim):
            values = attack_values(g.players[attacker], e.name)
            if not values:
                continue
            spots = strike_spots(g.board, hero.pos, e.ranged)
            own = frozenset(mates - {e.pos})
            steps = e.move + free_steps(g, e)
            if e.pos in spots:
                factor, bucket = 1.0, in_range
            elif reach_from(g.board, e.pos, steps, own, shield) & spots:
                factor, bucket = 1.0, after_move
            elif reach_from(g.board, e.pos, steps + BOOST_STEPS, own, shield) & spots:
                factor, bucket = w.boost_reach, after_move
            else:
                continue
            net, kill = attack_stats(values, g.attack_bonus(e) - best_def, hero.hp)
            bucket.append((factor * (net + (w.defend_card_hp if best_def else 0.0)), factor * kill))
        if not in_range and not after_move:
            return 0.0, 0.0
        actions = g.actions_left if g.turn == attacker else 2
        now_cost = max((c for c, _ in in_range), default=0.0)
        now_kill = max((k for _, k in in_range), default=0.0)
        any_cost = max(c for c, _ in in_range + after_move)
        any_kill = max(k for _, k in in_range + after_move)
        # two attacks in a row from where it is, or a maneuver and the best attack of all
        expected = max(actions * now_cost, (actions - 1) * any_cost)
        lethal = max(1 - (1 - now_kill) ** actions, any_kill if actions >= 2 else 0.0)
        urgency = w.victim_moves_first if g.turn == victim and not urgent else 1.0
        # over the current HP, not the maximum: the same expected hit weighs more the less life is left
        return min(1.0, expected / hero.hp) * urgency, lethal * urgency
