"""EffectAI: how the bot answers the decisions an effect asks (`ChoiceRequest`, docs/effects-dsl.md §11).

Each kind has its own rule, all built on the evaluation the heuristic bot already uses (`ai_medusa`):
  fighter    scored for what the op does to it (`extra["op"]`/`extra["amount"]`, set by `pick_fighters`): damage
             to the enemy that pays most (kills first), or to the own piece that loses least; heals to the own piece
             that needs it most; a move/place/swap to the piece whose relocation gains most `position_value`.
             An op the rule does not know is left to the controller's default path.
  space      an own piece's move is `MedusaAI.choose_move` (the planned destination of a scheme, else the kiting /
             harpy rules) and a dead own piece's placement `choose_placement`, exactly as the legacy engine asked;
             the rest through `position_value` / `harpy_score`; a rival piece goes where it hurts the bot least.
  cards      own hand: give up the lowest `keep_value`; own piles and the rival's public piles: take the best.
             Never looks at the rival hand: only what `KnownHand` has seen.
  effect     simulate every option on a determinized clone and keep the best evaluation.
  optional   same, yes against no; a price paid in cards is judged by `worth_paying` on the combat context the
             interpreter sends (`cost_cards`, `at_stake`, `hp`), the one policy every bot shares.
  order      best first for the bot's own cards, worst first for the rival's.
  amount     the largest useful one.

NO-CHEATING: the bot never reads the human's hidden hand. Every clone used to evaluate is built blind
(`blind_clone`): the rival hand and deck are never copied, they are re-drawn from what the bot legitimately knows
(`KnownHand`, public piles) before anything is simulated; the bot's own deck order is shuffled too.

Deterministic (the clone's rng is seeded from the request) and cheap: at most one clone per option, no search."""
from __future__ import annotations

import copy
import random

from .ai_medusa import (DECK_SCARCITY, HARPY_VALUE, KILL_SIDEKICK, LETHAL, W_HERO, W_MEDUSA_HP,
                        W_SIDEKICK, MedusaAI, Model, keep_value)
from .controller import Controller
from .effects.choose import ChoiceRequest, ControllerChooser, default_answer, worth_paying
from .effects.model import EffectError, load_effects
from .effects.run import Ctx, EffectRun
from .search.adapter import card_worth
from .state import Game, PlayerState, RuleError

GIVE_UP_PURPOSES = ("discard", "return", "reveal")      # cards the chooser parts with: the least useful go
SIM_WIN = 200.0                                         # a finished game dominates any material
PAY_MARGIN = 0.1                                        # an optional price is paid only when it clearly returns more
CARD_FLAT = 1.2                                         # an unseen rival card, in the units of keep_value
DEFAULT_BLOW = 1                                        # damage or heal assumed when a pick does not say how much
DEFAULT_REACH = 2                                       # steps a place/swap candidate is assumed to relocate by
HP_OPS = ("damage", "heal", "set_hp")
RELOCATE_OPS = ("move", "place", "swap")


def blind_clone(game: Game, me: int, rng: random.Random) -> Game:
    """A copy of `game` for `me` to simulate on, with nothing of the rival's hidden cards in it: the rival hand and
    deck are re-drawn from what `me` has legitimately learned, and `me`'s own deck is shuffled (its order is hidden
    too). The real rival hand is only measured (its size), never iterated."""
    rival = 1 - me
    real = game.players[rival]
    n_hand, n_deck = len(real.hand), len(real.deck)
    shell = PlayerState(real.hero, [], real.full_set, [], list(real.discard), real.known.copy())
    shadow = copy.copy(game)
    shadow.players = list(game.players)
    shadow.players[rival] = shell
    g = Game.clone(shadow)
    g.rng = rng
    g.controllers = {0: Controller(), 1: Controller()}
    shell = g.players[rival]                 # the clone's rival, still empty: filled below
    known = g.players[me].known
    sure = [c for c in known.cards(shell)]
    top = [c for c in known.top(shell) if c not in sure]
    pool = [c for c in sorted(shell.full_set, key=lambda c: c.card_id) if c not in shell.discard]
    for c in sure:
        if c in pool:
            pool.remove(c)
    for c in top:
        if c in pool:
            pool.remove(c)
    rng.shuffle(pool)
    need = max(0, n_hand - len(sure))
    maybe = [c for c in known.possible_cards(shell) if c in pool]
    if maybe and need:
        lo = min(known.possible_lo, need, len(maybe))
        picked = rng.sample(maybe, rng.randint(lo, min(max(known.possible_hi, lo), need, len(maybe))))
        for c in picked:
            pool.remove(c)
        rest = [c for c in pool if c not in picked]
        extra = rest[:need - len(picked)]
        pool = [c for c in pool if c not in picked and c not in extra]
        hand = sure + picked + extra
    else:
        hand, pool = sure + pool[:need], pool[need:]
    shell.hand = hand[:n_hand]
    shell.deck = (top + pool)[:max(n_deck, 0)] if n_deck else []
    mine = g.players[me]
    mine.deck.sort(key=lambda c: c.card_id)
    rng.shuffle(mine.deck)
    return g


class _SimChooser:
    """Answers the decisions inside a simulated effect: the same rules, but never a nested simulation."""

    def __init__(self, ai: "EffectAI"):
        self.ai = ai

    def choose(self, game, req):
        answer = self.ai.decide(game, req, nested=True)
        return default_answer(req) if answer is None else answer


class EffectAI:
    def __init__(self, me: int = 0, medusa: MedusaAI | None = None, seed: int = 0):
        self.me, self.seed = me, seed
        self._medusas: dict[int, MedusaAI] = {me: medusa} if medusa is not None else {}

    def medusa(self, player: int) -> MedusaAI:
        if player not in self._medusas:
            self._medusas[player] = MedusaAI(player)
        return self._medusas[player]

    # ------------------------------------------------------------------ entry
    def choose_effect(self, game: Game, req: ChoiceRequest) -> list | None:
        return self.decide(game, req, nested=False)

    def decide(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        handler = getattr(self, f"_{req.kind}", None)
        if handler is None or not req.options:
            return None
        answer = handler(game, req, nested)
        if answer is None:
            return None
        try:
            return req.validate(answer)
        except ValueError:                  # a rule that overreached: the generic fallback is always legal
            return None

    # ------------------------------------------------------------------ fighters
    def _fighter(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        me, op = req.player, req.extra.get("op")
        cands = [game.fighters[i] for i in req.options if i in game.fighters]
        if not cands:
            return None
        if op in HP_OPS:
            score = self._hp_scorer(op, req.extra.get("amount"), me)
        elif op in RELOCATE_OPS:
            score = self._relocation_scorer(game, op, req.extra, me)
        else:
            return None
        if score is None:
            return None
        return [min(cands, key=lambda f: (-score(f), f.fid)).fid]

    @staticmethod
    def _hp_scorer(op: str, n, me: int):
        """Value to `me` of `op` landing on a fighter; None when a `set_hp` does not say the hit points."""
        if op == "set_hp":
            if not isinstance(n, (int, float)):
                return None
            return lambda f: EffectAI.hp_change(f, n, me)
        n = n if isinstance(n, (int, float)) else DEFAULT_BLOW
        if op == "damage":
            return lambda f: EffectAI.hp_change(f, f.hp - n, me)
        return lambda f: EffectAI.hp_change(f, f.hp + n, me)

    def _relocation_scorer(self, game: Game, op: str, extra: dict, me: int):
        """The best `position_value` gain a fighter's relocation can bring `me`: an own piece goes where it is
        best placed, a rival piece where it hurts the bot least (the same chooser picks the space next)."""
        ai, model = self.medusa(me), Model(game, me)
        steps = int(extra.get("amount") or DEFAULT_REACH) if op == "move" else DEFAULT_REACH
        through = bool(extra.get("through", False))

        def gain(f) -> float:
            if not f.alive or f.pos is None:
                return 0.0
            stay = ai.position_value(game, model, {f.fid: f.pos})
            dests = game.legal_moves(f, steps, through)
            return max((ai.position_value(game, model, {f.fid: s}) for s in dests), default=stay) - stay
        return gain

    @staticmethod
    def hp_change(f, new_hp: float, me: int) -> float:
        """What `f` going from its hit points to `new_hp` is worth to `me`: hit points by the weights the
        evaluation uses, and a kill on top (a loss when the piece is `me`'s, the game when it is the hero; a prize
        when it is a rival's)."""
        new = max(0, min(f.max_hp, new_hp))
        delta, dead = new - f.hp, new <= 0 < f.hp
        kill = (LETHAL if f.hero else KILL_SIDEKICK) if dead else 0.0
        if f.owner == me:
            return (W_MEDUSA_HP if f.hero else HARPY_VALUE) * delta - kill
        return -(W_HERO if f.hero else W_SIDEKICK) * delta + kill

    @staticmethod
    def blow_value(f, dmg: float) -> float:
        """What hitting `f` for `dmg` is worth to its rival."""
        return EffectAI.hp_change(f, f.hp - dmg, 1 - f.owner)

    # ------------------------------------------------------------------ spaces
    def _space(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        me = req.player
        f = game.fighters.get(req.extra.get("fighter"))
        if f is None:
            return None
        ai = self.medusa(me)
        options = list(req.options)
        if f.owner == me and req.extra.get("op") == "move":     # the legacy move rule, plan included; staying = []
            dest = ai.choose_move(game, f, req.extra["steps"], req.extra.get("through", False))
            return [dest] if dest in options else ([] if req.min == 0 else None)
        if f.owner == me and (f.pos is None or not f.alive):     # a placement (a Harpy returning): plan included
            dest = ai.choose_placement(game, f, options)
            return [dest] if dest in options else None
        if f.owner == me and not f.hero:
            scored = {s: ai.harpy_score(game, f, s) for s in options}
            stay = ai.harpy_score(game, f, f.pos)
        else:
            if not f.alive or f.pos is None:
                return None
            model = Model(game, me)
            scored = {s: ai.position_value(game, model, {f.fid: s}) for s in options}
            stay = ai.position_value(game, model, {f.fid: f.pos})
        best = max(options, key=lambda s: (scored[s], -s))
        if req.min == 0 and stay >= scored[best]:
            return []
        return [best]

    # ------------------------------------------------------------------ cards
    def _cards(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        me = req.player
        zone, purpose = req.extra.get("zone"), req.extra.get("purpose")
        of = req.extra.get("of", me)
        n_min, n_max = req.min, min(req.max, len(req.options))
        if zone == "hand" and of != me:                    # C4: what a look showed, the rest by position
            return ControllerChooser._from_rival_hand(game, req, of)
        if zone == "hand":
            by_id = {c.card_id: c for c in game.players[me].hand}
            hand = game.players[me].hand
            ranked = sorted((i for i in req.options if i in by_id), key=lambda i: (keep_value(by_id[i], hand), i))
            if purpose in GIVE_UP_PURPOSES:
                junk = [i for i in ranked[n_min:n_max] if keep_value(by_id[i], hand) < 0.9]
                return ranked[:n_min] + junk if purpose == "discard" else ranked[:n_min]
            best = ranked[::-1]
            return best[:n_max] if n_min < n_max else best[:n_min]
        cards = {c.card_id: c for p in game.players for c in p.full_set}
        worth = lambda i: card_worth(cards[i]) if i in cards else 0.0
        if of == me and purpose == "discard":                       # parting with own deck or discard cards
            return sorted(req.options, key=lambda i: (worth(i), i))[:n_min]
        ranked = sorted(req.options, key=lambda i: (-worth(i), i))
        take = n_max if n_min < n_max and worth(ranked[0]) > 0 else n_min
        return ranked[:take]

    # ------------------------------------------------------------------ order, amount
    def _order(self, game: Game, req: ChoiceRequest, nested: bool) -> list:
        me = req.player
        cards = {c.card_id: c for p in game.players for c in p.full_set}
        if req.extra.get("zone") == "deck" or set(req.options) <= set(cards):
            mine = {c.card_id for c in game.players[me].full_set}
            sign = {True: -1, False: 1}
            return sorted(req.options, key=lambda i: (sign[i in mine] * card_worth(cards[i]), i))
        fighters = game.fighters
        return sorted(req.options, key=lambda i: (-self.blow_value(fighters[i], DEFAULT_BLOW), i))

    def _amount(self, game: Game, req: ChoiceRequest, nested: bool) -> list:
        top = max(req.options)
        if req.extra.get("zone") in (None, "deck") and top > 0:
            n = min(top, len(game.players[req.player].deck))      # drawing from an empty deck only hurts
            return [max(min(req.options), n)]
        return [top]

    # ------------------------------------------------------------------ simulated choices
    def _effect(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        found = self._locate(game, req)
        if nested or found is None:
            return None
        op, card, owner, label = found
        options = op.get("options") or []
        base = self._base(game, req)
        before = self.evaluate(base, req.player)
        scored = []
        for k in req.options:
            if not 0 <= k < len(options):
                return None
            value = self._simulate(base, options[k].get("ops", []), card, owner, label, req.player)
            scored.append((value - before if value is not None else 0.0, -k, k))
        return [max(scored)[2]]

    def _optional(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        if "cost_cards" in req.extra:       # a price in cards: the interpreter sends the combat context, one policy
            return [worth_paying(req)]
        if "to" in req.extra:               # a redirect passive (FATEFUL BARGAINS): whoever loses the bot less takes it
            hit, to = game.fighters.get(req.extra.get("fighter")), game.fighters.get(req.extra["to"])
            if hit is None or to is None:
                return None
            n = req.extra.get("amount", DEFAULT_BLOW)
            return [self.hp_change(to, to.hp - n, req.player) >= self.hp_change(hit, hit.hp - n, req.player)]
        found = self._locate(game, req)
        if nested or found is None:
            return None
        op, card, owner, label = found
        cost, ops, other = op.get("cost") or [], op.get("ops") or [], op.get("else") or []
        base = self._base(game, req)
        me = req.player
        yes = self._simulate(base, list(cost) + list(ops), card, owner, label, me)
        no = self._simulate(base, other, card, owner, label, me) if other else self.evaluate(base, me)
        if yes is None and no is not None and other and not cost:
            yes = self.evaluate(base, me) - CARD_FLAT      # an effect that names a card we cannot see: one average card
        if yes is None or no is None:
            return [not cost]
        return [yes >= no - 1e-9] if not cost else [yes > no + PAY_MARGIN]

    # ------------------------------------------------------------------ clones and evaluation
    def _base(self, game: Game, req: ChoiceRequest) -> Game:
        rng = random.Random(f"{self.seed}:{game.turn_no}:{req.player}:{req.card_id}:{req.key}")
        return blind_clone(game, req.player, rng)

    def _simulate(self, base: Game, ops: list, card, owner: int, label: str, me: int) -> float | None:
        """Evaluation after `ops` on a copy of `base`; None when the ops cannot be run out of their context (a
        combat op outside a combat, a rule the clone breaks, a pending phase). Anything else is a bug and surfaces."""
        if not ops:
            return self.evaluate(base, me)
        g = base.clone()
        g.rng = random.Random(0)
        g.controllers = {0: Controller(), 1: Controller()}
        try:
            ctx = Ctx(owner=owner, this_fid=g.hero(owner).fid, card_id=card.card_id if card else None, moment=label)
            run = EffectRun(copy.deepcopy(ops), ctx, label="sim")
            run.run(g, _SimChooser(self))
        except (RuleError, EffectError, NotImplementedError):
            return None
        return self.evaluate(g, me)

    def evaluate(self, g: Game, me: int) -> float:
        """The bot's view of `g`: material (hit points by weight), cards in hand, deck clock and position."""
        if g.winner is not None:
            return SIM_WIN if g.winner == me else -SIM_WIN
        score = 0.0
        for f in g.fighters.values():
            if not f.alive:
                continue
            if f.owner == me:
                score += (W_MEDUSA_HP if f.hero else HARPY_VALUE) * f.hp
            else:
                score -= (W_HERO if f.hero else W_SIDEKICK) * f.hp
        mine = g.players[me]
        score += sum(keep_value(c, mine.hand) for c in mine.hand)
        score -= CARD_FLAT * len(g.players[1 - me].hand)
        score -= DECK_SCARCITY.get(len(mine.deck), 0.0)
        ai = self.medusa(me)
        try:
            score += ai.position_value(g, Model(g, me))
        except (KeyError, StopIteration):       # a hero down or off the board: material already says it
            pass
        return score

    # ------------------------------------------------------------------ the op behind a request
    @staticmethod
    def _locate(game: Game, req: ChoiceRequest):
        """(op, card, owner, moment) for the card effect that asked, found through the request key
        `moment/path:ask`; None for anything that is not a card moment (ability triggers, unknown cards)."""
        if req.card_id is None or "/" not in req.key:
            return None
        owner = card = None
        for p, st in enumerate(game.players):
            for c in st.full_set:
                if c.card_id == req.card_id:
                    owner, card = p, c
        if card is None:
            return None
        label, _, rest = req.key.partition("/")
        segs = rest.rsplit(":", 1)[0].split("/")
        try:
            node = load_effects(game.players[owner].hero.slug).moment_ops(card.title, label)
            for seg in segs:
                seg = seg.split("@")[0]
                node = node[int(seg)] if isinstance(node, list) else node[seg]
        except Exception:
            return None
        return (node, card, owner, label) if isinstance(node, dict) else None
