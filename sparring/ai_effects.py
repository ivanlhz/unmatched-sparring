"""EffectAI: how the bot answers the decisions an effect asks (`ChoiceRequest`, docs/effects-dsl.md §11).

Each kind has its own rule, all built on the evaluation the heuristic bot already uses (`ai_medusa`):
  fighter    enemy: the blow that pays most (kills first, then the hero, then sidekicks by value); own: who needs it most.
  space      kiting and reach through `position_value` (own sidekicks through `harpy_score`, as the legacy moves do);
             a rival piece goes where it hurts the bot least.
  cards      own hand: give up the lowest `keep_value`; own piles and the rival's public piles: take the best.
             Never looks at the rival hand: only what `KnownHand` has seen.
  effect     simulate every option on a determinized clone and keep the best evaluation.
  optional   same, yes against no; a price paid in cards is compared with what the effect is worth in the combat.
  order      best first for the bot's own cards, worst first for the rival's.
  amount     the largest useful one.

NO-CHEATING: the bot never reads the human's hidden hand. Every clone used to evaluate is built blind
(`blind_clone`): the rival hand and deck are never copied, they are re-drawn from what the bot legitimately knows
(`KnownHand`, public piles) before anything is simulated; the bot's own deck order is shuffled too.

Deterministic (the clone's rng is seeded from the request) and cheap: at most one clone per option, no search."""
from __future__ import annotations

import copy
import random
from dataclasses import dataclass

from .ai_medusa import (DECK_SCARCITY, HARPY_VALUE, KILL_SIDEKICK, LETHAL, W_HERO, W_MEDUSA_HP,
                        W_SIDEKICK, MedusaAI, Model, keep_value)
from .controller import Controller
from .effects.choose import ChoiceRequest, default_answer
from .effects.model import load_effects
from .effects.run import Ctx, EffectRun
from .search.adapter import card_worth
from .state import Game, PlayerState

GIVE_UP_PURPOSES = ("discard", "return", "reveal")      # cards the chooser parts with: the least useful go
SIM_WIN = 200.0                                         # a finished game dominates any material
PAY_MARGIN = 0.1                                        # an optional price is paid only when it clearly returns more
CARD_FLAT = 1.2                                         # an unseen rival card, in the units of keep_value
DEFAULT_BLOW = 1                                        # damage assumed when a fighter pick does not say how much


@dataclass
class CombatView:
    """What the bot knows of the combat an effect runs in. The interpreter's combat driver sets `EffectAI.combat`
    (or passes the same keys as `req.extra["combat"]`); without it the card's printed value stands in for the
    attack and the defense counts as zero."""
    target_fid: str | None = None
    atk_value: int | None = None
    def_value: int = 0


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
        self.combat: CombatView | None = None

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
    def _fighter(self, game: Game, req: ChoiceRequest, nested: bool) -> list:
        me = req.player
        cands = [game.fighters[i] for i in req.options]
        foes = [f for f in cands if f.owner != me]
        blow = req.extra.get("amount") or DEFAULT_BLOW
        if foes:
            key = lambda f: (-self.blow_value(f, blow), f.fid)
            return [min(foes, key=key).fid]
        need = lambda f: (W_MEDUSA_HP if f.hero else HARPY_VALUE) * (f.max_hp - f.hp)
        return [min(cands, key=lambda f: (-need(f), not f.hero, f.fid)).fid]

    @staticmethod
    def blow_value(f, dmg: float) -> float:
        """What hitting `f` for `dmg` is worth to its rival: damage by weight, and a kill on top."""
        hit = min(dmg, f.hp)
        if f.hero:
            return W_HERO * hit + (LETHAL if dmg >= f.hp else 0.0)
        return W_SIDEKICK * hit + (KILL_SIDEKICK if dmg >= f.hp else 0.0)

    # ------------------------------------------------------------------ spaces
    def _space(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        me = req.player
        f = game.fighters.get(req.extra.get("fighter"))
        if f is None:
            return None
        ai = self.medusa(me)
        options = list(req.options)
        if f.owner == me and not f.hero:
            if f.pos is None or not f.alive:
                return [max(options, key=lambda s: (self._harpy_spot(game, ai, f, s), -s))]
            scored = {s: ai.harpy_score(game, f, s) for s in options}
            stay = ai.harpy_score(game, f, f.pos)
        else:
            if not f.alive or f.pos is None:
                return None
            if f.owner == me and req.extra.get("op") == "move":     # the legacy move rule, plan included
                dest = ai.choose_move(game, f, req.extra["steps"], req.extra.get("through", False))
                if dest in options:
                    return [dest]
            model = Model(game, me)
            scored = {s: ai.position_value(game, model, {f.fid: s}) for s in options}
            stay = ai.position_value(game, model, {f.fid: f.pos})
        best = max(options, key=lambda s: (scored[s], -s))
        if req.min == 0 and stay >= scored[best]:
            return []
        return [best]

    @staticmethod
    def _harpy_spot(game: Game, ai: MedusaAI, f, spot: int) -> float:
        foes = game.foes(f.owner)
        if not foes:
            return 0.0
        near = min(game.board.distance(spot, e.pos) for e in foes)
        return -0.25 * near + (0.6 if near == 1 else 0.0)

    # ------------------------------------------------------------------ cards
    def _cards(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        me = req.player
        zone, purpose = req.extra.get("zone"), req.extra.get("purpose")
        of = req.extra.get("of", me)
        n_min, n_max = req.min, min(req.max, len(req.options))
        if zone == "hand" and of != me:
            return self._rival_hand(game, req, of)
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

    def _rival_hand(self, game: Game, req: ChoiceRequest, of: int) -> list:
        """Only the cards a look already showed; the rest by position, never by identity."""
        seen = {c.card_id: c for c in game.players[req.player].known.cards(game.players[of])}
        ranked = sorted((i for i in req.options if i in seen), key=lambda i: (-card_worth(seen[i]), i))
        blind = [i for i in req.options if i not in ranked]
        return (ranked + blind)[:max(req.min, min(req.max, len(req.options)))]

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
        found = self._locate(game, req)
        if nested or found is None:
            return None
        op, card, owner, label = found
        cost, ops, other = op.get("cost") or [], op.get("ops") or [], op.get("else") or []
        base = self._base(game, req)
        me = req.player
        worth = self._combat_worth(game, req, ops, card, owner)
        if worth is not None:               # the effect changes the value of a combat card: price it in damage
            return [self._price(base, cost, worth, card, owner, label, me) > PAY_MARGIN]
        yes = self._simulate(base, list(cost) + list(ops), card, owner, label, me)
        no = self._simulate(base, other, card, owner, label, me) if other else self.evaluate(base, me)
        if yes is None and no is not None and other and not cost:
            yes = self.evaluate(base, me) - CARD_FLAT      # an effect that names a card we cannot see: one average card
        if yes is None or no is None:
            return [not cost]
        return [yes >= no - 1e-9] if not cost else [yes > no + PAY_MARGIN]

    def _price(self, base: Game, cost: list, worth: float, card, owner: int, label: str, me: int) -> float:
        """Worth of the effect minus what the price takes from the bot's evaluation (a discard cost loses the cards
        that `keep_value` rates lowest)."""
        paid = self._simulate(base, cost, card, owner, label, me)
        spent = 0.0 if paid is None else self.evaluate(base, me) - paid
        return worth - spent

    def _combat_worth(self, game: Game, req: ChoiceRequest, ops: list, card, owner: int) -> float | None:
        """What an effect that sets or shifts the value of the combat card is worth to the bot, in the evaluation's
        units; None when the effect does not touch that value."""
        change = None
        for o in ops:
            if o.get("op") in ("set_value", "modify_value") and o.get("card") == "this":
                change = o
        if change is None or card is None:
            return None
        view = self._combat_view(req)
        printed = card.value or 0
        atk = view.atk_value if view and view.atk_value is not None else printed
        new = change["amount"] if change["op"] == "set_value" else atk + change["amount"]
        if not isinstance(new, (int, float)):
            return None
        me = req.player
        victim_is_me = owner != me
        if view and view.target_fid in game.fighters:
            target = game.fighters[view.target_fid]
        else:
            target = game.hero(me if victim_is_me else 1 - me)
        defense = view.def_value if view else 0
        before, after = max(0, atk - defense), max(0, new - defense)
        if victim_is_me:
            return self._harm(target, before, True) - self._harm(target, after, True)
        return self._harm(target, after, False) - self._harm(target, before, False)

    @staticmethod
    def _harm(f, dmg: float, mine: bool) -> float:
        hit = min(dmg, f.hp)
        if mine:
            return HARPY_VALUE * hit if not f.hero else W_MEDUSA_HP * hit + (LETHAL if dmg >= f.hp else 0.0)
        return EffectAI.blow_value(f, dmg) if dmg > 0 else 0.0

    def _combat_view(self, req: ChoiceRequest) -> CombatView | None:
        raw = req.extra.get("combat")
        if isinstance(raw, dict):
            return CombatView(raw.get("target_fid"), raw.get("atk_value"), raw.get("def_value", 0))
        return self.combat

    # ------------------------------------------------------------------ clones and evaluation
    def _base(self, game: Game, req: ChoiceRequest) -> Game:
        rng = random.Random(f"{self.seed}:{game.turn_no}:{req.player}:{req.card_id}:{req.key}")
        return blind_clone(game, req.player, rng)

    def _simulate(self, base: Game, ops: list, card, owner: int, label: str, me: int) -> float | None:
        """Evaluation after `ops` on a copy of `base`; None when the ops cannot be run out of their context."""
        if not ops:
            return self.evaluate(base, me)
        g = base.clone()
        g.rng = random.Random(0)
        g.controllers = {0: Controller(), 1: Controller()}
        try:
            ctx = Ctx(owner=owner, this_fid=g.hero(owner).fid, card_id=card.card_id if card else None, moment=label)
            run = EffectRun(copy.deepcopy(ops), ctx, label="sim")
            run.run(g, _SimChooser(self))
        except AssertionError:
            raise
        except Exception:
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
