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
  effect     simulate every option on a determinized clone and keep the best evaluation. A Perfect Shot
             prediction (`op: predict`) is `predict_value`: the most common printed value among the rival's
             defense cards the bot has legitimately seen, else among the rival's whole deck minus its public
             discard pile.
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
from functools import lru_cache

from .ai_medusa import (DECK_SCARCITY, HARPY_VALUE, KILL_SIDEKICK, LETHAL, SURVIVAL_P, W_HERO, W_MEDUSA_HP,
                        W_SIDEKICK, MedusaAI, Model, keep_value, kill_value, play_signature)
from .controller import Controller
from .effects import ongoing
from .effects.choose import ChoiceRequest, ControllerChooser, SyntheticChooser, default_answer, worth_paying
from .effects.model import EffectError, load_effects
from .effects.ops_combat import PREDICT_OP
from .effects.run import Ctx, EffectRun
from .search.adapter import card_worth
from .state import Game, PlayerState, RuleError

GIVE_UP_PURPOSES = ("discard", "return", "reveal")      # cards the chooser parts with: the least useful go


def predict_value(game: Game, me: int) -> int:
    """Perfect Shot: the printed value the rival's defense most likely has. Only legitimate information: the rival's
    cards a look showed (`KnownHand`) if any can defend, else the composition of their deck (public) minus their
    discard pile (public). Ties go to the higher value. The rival's hand and deck are never read."""
    rival = game.players[1 - me]
    seen = [c for c in game.players[me].known.cards(rival) if c.can_defend]
    pool = seen or [c for c in rival.full_set if c.can_defend and c not in rival.gone]
    if not pool:
        return 0
    counts: dict[int, int] = {}
    for c in pool:
        counts[c.value or 0] = counts.get(c.value or 0, 0) + 1
    return max(counts, key=lambda v: (counts[v], v))
SIM_WIN = 200.0                                         # a finished game dominates any material
PAY_MARGIN = 0.1                                        # an optional price is paid only when it clearly returns more
CARD_FLAT = 1.2                                         # an unseen rival card, in the units of keep_value
DEFAULT_BLOW = 1                                        # damage or heal assumed when a pick does not say how much
DEFAULT_REACH = 2                                       # steps a place/swap candidate is assumed to relocate by
HP_OPS = ("damage", "heal", "set_hp")
RELOCATE_OPS = ("move", "place", "swap")
CANCEL_MAX_KEEP = 1.6                                   # the card given up to cancel the rival's effects is worth this or less
BONUS_MARGIN = 0.2                                      # a card is given up for a bonus only when it clearly pays
BOUNCE_BONUS = 0.5                                      # a returning card at the bottom also burns 1 when it comes back
PACT_MARGIN = 0.3                                       # DARK PACT is paid when it returns this much more than the hit point costs
PACT_FLOOR = 4                                          # DARK PACT never leaves the hero with fewer hit points than this (effect damage, exhaustion)
PACT_COMFORT = 8                                        # below this many hit points left, each one costs more (PACT_URGENCY per missing point)
PACT_URGENCY = 0.15
PACT_RISK_STEP = 0.1                                    # ... and the hit point does not raise the chance of dying next turn by more than this
PACT_RECYCLE = 4.0                                      # a card put at the bottom of a deck of n cards comes back with weight PACT_RECYCLE / (n + 1)
BLIND_COST = 0.1                                        # a blind boost mills one card of the deck: the exhaustion clock ticks


@lru_cache(maxsize=None)
def returning_tag(slug: str) -> str | None:
    """The card tag that comes back to its owner's hand when discarded from the deck (Liz's WILDFIRE returns a
    burning card; her start of turn discards the bottom one): a card so tagged put at the bottom is not lost."""
    for trig in load_effects(slug).triggers:
        when = trig["when"]
        if when["event"] == "card_discarded" and "deck" in when.get("from", ()) and (when.get("filter") or {}).get("tag"):
            return when["filter"]["tag"]
    return None


def bounces_back(game, player: int, card) -> bool:
    tag = returning_tag(game.players[player].hero.slug)
    return tag is not None and tag in card.tags


def blind_clone(game: Game, me: int, rng: random.Random) -> Game:
    """A copy of `game` for `me` to simulate on, with nothing of the rival's hidden cards in it: the rival hand and
    deck are re-drawn from what `me` has legitimately learned, and `me`'s own deck is shuffled (its order is hidden
    too). The real rival hand is only measured (its size), never iterated."""
    rival = 1 - me
    real = game.players[rival]
    n_hand, n_deck = len(real.hand), len(real.deck)
    shell = PlayerState(real.hero, [], real.full_set, [], list(real.discard), real.known.copy(),
                        list(real.tucked), list(real.removed))
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
    pool = [c for c in sorted(shell.full_set, key=lambda c: c.card_id) if c not in shell.gone]
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
    if mine.deck and bounces_back(g, me, mine.deck[-1]):      # the bottom is unknown too: only what a simulated
        plain = next((i for i in range(len(mine.deck) - 1, -1, -1)     # effect puts there counts as coming back
                      if not bounces_back(g, me, mine.deck[i])), None)
        if plain is not None:
            mine.deck.append(mine.deck.pop(plain))
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
            score = self._hp_scorer(op, req.extra.get("amount"), me, game)
        elif op in RELOCATE_OPS:
            score = self._relocation_scorer(game, op, req.extra, me)
        else:
            return None
        if score is None:
            return None
        return [min(cands, key=lambda f: (-score(f), f.fid)).fid]

    @staticmethod
    def _hp_scorer(op: str, n, me: int, game: Game | None = None):
        """Value to `me` of `op` landing on a fighter; None when a `set_hp` does not say the hit points."""
        if op == "set_hp":
            if not isinstance(n, (int, float)):
                return None
            return lambda f: EffectAI.hp_change(f, n, me, game)
        n = n if isinstance(n, (int, float)) else DEFAULT_BLOW
        if op == "damage":
            return lambda f: EffectAI.hp_change(f, f.hp - n, me, game)
        return lambda f: EffectAI.hp_change(f, f.hp + n, me, game)

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
    def hp_change(f, new_hp: float, me: int, game: Game | None = None) -> float:
        """What `f` going from its hit points to `new_hp` is worth to `me`: hit points by the weights the
        evaluation uses, and a kill on top (a loss when the piece is `me`'s, the game when it is the hero; a prize
        when it is a rival's). With the `game`, a sidekick's kill is worth what its AI profile says (`kill_value`)."""
        new = max(0, min(f.max_hp, new_hp))
        delta, dead = new - f.hp, new <= 0 < f.hp
        kill = (LETHAL if f.hero else kill_value(game, f) if game else KILL_SIDEKICK) if dead else 0.0
        if f.owner == me:
            return (W_MEDUSA_HP if f.hero else HARPY_VALUE) * delta - kill
        return -(W_HERO if f.hero else W_SIDEKICK) * delta + kill

    @staticmethod
    def blow_value(f, dmg: float, game: Game | None = None) -> float:
        """What hitting `f` for `dmg` is worth to its rival."""
        return EffectAI.hp_change(f, f.hp - dmg, 1 - f.owner, game)

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
        if f.owner == me and f.hero and not f.alive:              # the hero coming back (All Part of the Show): where he stands best
            return self._hero_return(game, req, f, options)
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

    def _hero_return(self, game: Game, req: ChoiceRequest, f, options: list) -> list | None:
        """The hero put back on the board with `hp` (the request says) is judged where he would stand: the evaluation of the
        position with him there, not the Harpy rule (which looks for the rival)."""
        me, ai, hp = req.player, self.medusa(req.player), req.extra.get("hp")
        best, best_v = None, None
        for s in options:
            g = game.clone()
            hero = g.fighters[f.fid]
            hero.alive, hero.pos, hero.hp = True, s, min(hp or hero.max_hp, hero.max_hp)
            v = ai.position_value(g, Model(g, me))
            if best_v is None or v > best_v + 1e-9:
                best, best_v = s, v
        return None if best is None else [best]

    # ------------------------------------------------------------------ cards
    def _cards(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        me = req.player
        zone, purpose = req.extra.get("zone"), req.extra.get("purpose")
        of = req.extra.get("of", me)
        n_min, n_max = req.min, min(req.max, len(req.options))
        if purpose == "bonus":
            return self._bonus_discards(game, req)
        if purpose == "reveal_top":
            return self._card_to_reveal(game, req)
        if zone == "hand" and of != me:                    # C4: what a look showed, the rest by position
            return ControllerChooser._from_rival_hand(game, req, of)
        if zone == "hand":
            by_id = {c.card_id: c for c in game.players[me].hand}
            hand = game.players[me].hand
            ranked = sorted((i for i in req.options if i in by_id), key=lambda i: (keep_value(by_id[i], hand), i))
            if purpose == "return" and req.extra.get("position") == "bottom":     # Wildfire: a burning card comes back
                back = [i for i in ranked if bounces_back(game, me, by_id[i])]
                ranked = back + [i for i in ranked if i not in back]
                return ranked[:max(n_min, min(n_max, len(back)))]
            if purpose in GIVE_UP_PURPOSES:
                junk = [i for i in ranked[n_min:n_max] if keep_value(by_id[i], hand) < 0.9]
                return ranked[:n_min] + junk if purpose == "discard" else ranked[:n_min]
            best = ranked[::-1]
            return best[:n_max] if n_min < n_max else best[:n_min]
        cards = game.cards_by_id(of)
        worth = lambda i: card_worth(cards[i]) if i in cards else 0.0
        if of == me and purpose == "discard":                       # parting with own deck or discard cards
            return sorted(req.options, key=lambda i: (worth(i), i))[:n_min]
        if of == me and purpose == "remove":                        # removing own discard cards from the game: as many as allowed, the cheapest
            return sorted(req.options, key=lambda i: (worth(i), i))[:n_max]
        if of == me and zone == "discard" and purpose == "return":   # own discard back into the deck (Pancakes!): all it
            ranked = sorted(req.options, key=lambda i: (i in cards and cards[i].destiny, -worth(i), i))
            return ranked[:n_max]                                    # may, destiny cards last (they keep ANUNG UN RAMA)
        ranked = sorted(req.options, key=lambda i: (-worth(i), i))
        take = n_max if n_min < n_max and worth(ranked[0]) > 0 else n_min
        return ranked[:take]

    def _card_to_reveal(self, game: Game, req: ChoiceRequest) -> list:
        """No, Really, I'm a Doctor: the card shown goes on top of the deck (it is drawn next) and heals its BOOST value to
        Doctor Strange or the fighter beside him. The one that heals most (only the hit points missing count) for the least
        it is worth in hand."""
        me, hand = req.player, game.players[req.player].hand
        by_id = {c.card_id: c for c in hand}
        missing = req.extra.get("missing", 0)
        best = max((i for i in req.options if i in by_id),
                   key=lambda i: (W_MEDUSA_HP * min(by_id[i].boost, missing) - 0.5 * keep_value(by_id[i], hand), -i), default=None)
        return None if best is None else [best]

    def _bonus_discards(self, game: Game, req: ChoiceRequest) -> list:
        """Unbridled rage: each card given up adds `per_card` to the value of the card. Cards go from the least to the
        most valuable to keep while the damage the next bonus adds to the blow is worth more than the card. Only an
        attack counts (the damage the bot adds); a defense adds nothing it can price."""
        me, hand = req.player, game.players[req.player].hand
        foe = game.fighters.get(req.extra.get("foe"))
        if foe is None or not req.extra.get("attacking"):
            return []
        by_id = {c.card_id: c for c in hand}
        per, margin = req.extra["per_card"], req.extra["margin"]
        ranked = sorted(req.options, key=lambda i: (keep_value(by_id[i], hand), i))
        base = self.blow_value(foe, max(0, margin), game)
        best, best_net, spent = 0, 0.0, 0.0
        for k, i in enumerate(ranked, 1):
            spent += keep_value(by_id[i], hand)
            net = self.blow_value(foe, max(0, margin + per * k), game) - base - spent - BONUS_MARGIN
            if net > best_net:
                best, best_net = k, net
        return ranked[:best]

    # ------------------------------------------------------------------ order, amount
    def _order(self, game: Game, req: ChoiceRequest, nested: bool) -> list:
        me = req.player
        of = req.extra.get("of", me)                        # whose cards the options are: ids mean cards only per owner
        cards = game.cards_by_id(of)
        if req.extra.get("zone") == "deck" or set(req.options) <= set(cards):
            mine = of == me
            sign = -1 if mine else 1
            if req.extra.get("position") == "bottom":       # the very bottom is the last: the card that comes back
                return sorted(req.options, key=lambda i: (mine and bounces_back(game, me, cards[i]),
                                                          sign * card_worth(cards[i]), i))
            return sorted(req.options, key=lambda i: (sign * card_worth(cards[i]), i))
        fighters = game.fighters
        return sorted(req.options, key=lambda i: (-self.blow_value(fighters[i], DEFAULT_BLOW, game), i))

    def _amount(self, game: Game, req: ChoiceRequest, nested: bool) -> list:
        top = max(req.options)
        if req.extra.get("zone") in (None, "deck") and top > 0:
            n = min(top, len(game.players[req.player].deck))      # drawing from an empty deck only hurts
            return [max(min(req.options), n)]
        return [top]

    # ------------------------------------------------------------------ simulated choices
    def _effect(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        if req.extra.get("op") == PREDICT_OP:
            return [predict_value(game, req.player)]
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
            gain = round(value - before, 6) if value is not None else 0.0
            scored.append((gain, SyntheticChooser._option_worth(game, req.player, options[k]), -k, k))   # a tie: the one that does something
        return [max(scored)[3]]

    def _optional(self, game: Game, req: ChoiceRequest, nested: bool) -> list | None:
        if "pact" in req.extra:
            return [self._dark_pact(game, req)]
        if req.extra.get("blind_boost"):
            return [self._blind_boost(game, req)]
        if "shield" in req.extra:           # A Magician Never Reveals His Secrets: showing one card costs less than a look at the hand
            return [True]
        if "replaces_combatant" in req.extra:
            return [self._swap_combatant(game, req)]
        if "bury" in req.extra:             # The future of Ninjutsu: the top card goes to the bottom if it is worse than the average card to come
            top = {c.card_id: c for c in game.players[req.player].full_set}[req.extra["bury"][0]] if req.extra["bury"] else None
            return None if top is None else [keep_value(top, [top]) < self.medusa(req.player).avg_unseen_keep(game)]
        if "gains_action" in req.extra or "cancels" in req.extra:
            return [self._card_from_hand_pays(game, req)]
        if "cost_cards" in req.extra:      # a price in cards: the interpreter sends the combat context, one policy
            return [worth_paying(req)]
        if "to" in req.extra:               # a redirect passive (FATEFUL BARGAINS): whoever loses the bot less takes it
            hit, to = game.fighters.get(req.extra.get("fighter")), game.fighters.get(req.extra["to"])
            if hit is None or to is None:
                return None
            n = req.extra.get("amount", DEFAULT_BLOW)
            return [self.hp_change(to, to.hp - n, req.player, game) >= self.hp_change(hit, hit.hp - n, req.player, game)]
        if req.extra.get("discards") and req.extra.get("else_fighter") in game.fighters:
            return [self._discard_or_take(game, req)]
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

    def _dark_pact(self, game: Game, req: ChoiceRequest) -> bool:
        """DARK PACT: 1 hit point for the card it recycles and a draw. Never when the hit point kills the hero, and never
        when it raises the chance of dying in the rival's next turn (`MedusaAI.death_risk`) to SURVIVAL_P or by more than
        PACT_RISK_STEP, nor below PACT_FLOOR hit points. Otherwise it is paid when what it brings (the draw: an average unseen card, the recycled card:
        its keep value, weighted by how soon the deck brings it back) outweighs the hit point (`W_MEDUSA_HP`)."""
        pact, me = req.extra["pact"], req.player
        hero = game.fighters[pact["fighter"]]
        dmg = pact["damage"]
        left = hero.hp - dmg
        if left < PACT_FLOOR:
            return False
        ai, model = self.medusa(me), Model(game, me)
        now, after = ai.death_risk(game, model, hero, hero.hp), ai.death_risk(game, model, hero, hero.hp - dmg)
        if after >= SURVIVAL_P or after > now + PACT_RISK_STEP:
            return False
        mine = game.players[me]
        card = {c.card_id: c for c in mine.full_set}.get(pact["card"])
        recycle = 0.0 if card is None else keep_value(card, mine.hand) * min(1.0, PACT_RECYCLE / (len(mine.deck) + 1))
        # with an empty deck the card itself comes straight back: the draw adds nothing new
        draw = ai.avg_unseen_keep(game) * pact["draws"] if mine.deck else 0.0
        cost = W_MEDUSA_HP * dmg * (1 + PACT_URGENCY * max(0, PACT_COMFORT - left)) + LETHAL * (after - now)
        return draw + recycle - cost > PACT_MARGIN

    def _blind_boost(self, game: Game, req: ChoiceRequest) -> bool:
        """BLIND BOOST: free (the top card of the deck, no card of the hand), so it is taken while the expected value of
        the blow improves: the average over the boosts the bot's deck can still hold, a card that ignores a value above
        its `limit` (Seven Suns) counting 0 for a total over it."""
        x, me = req.extra, req.player
        mine = game.players[me]
        pool = [c for c in mine.full_set if c not in mine.hand and c not in mine.gone]    # its own deck: it knows what is in it
        target = game.fighters.get(x["target"])
        if not pool or target is None:
            return False
        value, margin, limit = x["value"], x["margin"], x["limit"]

        def score(total: int) -> float:
            if limit is not None and total > limit:
                total = 0
            net = margin + total - value
            if x["attacking"]:
                return self.blow_value(target, max(0, net), game)
            return self.hp_change(target, target.hp - max(0, -net), me, game)
        gain = sum(score(value + c.boost) for c in pool) / len(pool) - score(value)
        return gain - BLIND_COST > 0
    def _swap_combatant(self, game: Game, req: ChoiceRequest) -> bool:
        """Smoke And Mirrors: swap Houdini and Bess so the other one fights in this combat. Defending, the one that loses the
        less to the blow as things stand takes it (a sidekick that the blow would only overkill soaks it for the hero;
        the hero takes it rather than lose the sidekick for a few points). Attacking, the damage is the same: no swap."""
        info, me = req.extra["replaces_combatant"], req.player
        if info["role"] != "defense":
            return False
        this = game.fighters[info["this"]]
        other = next((f for f in game.own(me) if f is not this), None)
        if other is None:
            return False
        blow = req.extra.get("at_stake", 0)
        lose = lambda f: -self.hp_change(f, f.hp - blow, me, game)
        return lose(other) < lose(this) - 1e-9

    def _card_from_hand_pays(self, game: Game, req: ChoiceRequest) -> bool:
        """A card put on the bottom of the deck (it comes back when the deck cycles) for an extra action (Hi-Yaaaaah!!)
        or for cancelling the rival's card effects (Guaranteed Delivery). The least useful card is the one given up;
        the action is worth it while a card that can use it stays in the hand, the cancel while the card given up is
        below the average (`CANCEL_MAX_KEEP`) and the rival's card has effects to cancel."""
        hand = game.players[req.player].hand
        if not hand:
            return False
        junk = min(hand, key=lambda c: (keep_value(c, hand), c.card_id))
        rest = [c for c in hand if c is not junk]
        if "gains_action" in req.extra:
            return any(c.can_attack or c.is_scheme for c in rest)
        return req.extra["cancels"] > 0 and keep_value(junk, hand) <= CANCEL_MAX_KEEP

    def _discard_or_take(self, game: Game, req: ChoiceRequest) -> bool:
        """Remove A Painful Memory's "discard it or take N": the named cards are the bot's own and known, so the
        price of each answer is exact (the simulation cannot run the damage, which names the combat's opposing
        fighter). True (discard) when the hit points the damage costs outweigh what the cards are worth in hand;
        a card that Wildfire returns costs nothing to discard."""
        me, hand = req.player, game.players[req.player].hand
        named = [c for c in hand if c.card_id in req.extra["discards"]]
        price = sum(0.0 if bounces_back(game, me, c) else keep_value(c, hand) for c in named)
        f = game.fighters[req.extra["else_fighter"]]
        return -self.hp_change(f, f.hp - req.extra["else_damage"], me, game) > price

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
        """The bot's view of `g`: material (hit points by weight, the ONGOING in play), cards in hand, deck clock
        and position."""
        if g.winner is not None:
            return SIM_WIN if g.winner == me else -SIM_WIN
        score = self.material(g, me)
        mine = g.players[me]
        score += sum(keep_value(c, mine.hand) for c in mine.hand)
        if mine.deck and bounces_back(g, me, mine.deck[-1]):      # it returns at the start of the turn (Wildfire)
            score += keep_value(mine.deck[-1], mine.hand) + BOUNCE_BONUS
        score -= CARD_FLAT * len(g.players[1 - me].hand)
        score -= DECK_SCARCITY.get(len(mine.deck), 0.0)
        ai = self.medusa(me)
        try:
            score += ai.position_value(g, Model(g, me))
        except (KeyError, StopIteration):       # a hero down or off the board: material already says it
            pass
        return score

    @staticmethod
    def material(g: Game, me: int) -> float:
        """Hit points on the board by the evaluation's weights, plus what each side's ONGOING is worth."""
        score = 0.0
        for f in g.fighters.values():
            if not f.alive:
                continue
            if f.owner == me:
                score += (W_MEDUSA_HP if f.hero else HARPY_VALUE) * f.hp
            else:
                score -= (W_HERO if f.hero else W_SIDEKICK) * f.hp
        return score + W_MEDUSA_HP * ongoing.worth(g, me) - W_HERO * ongoing.worth(g, 1 - me)

    @staticmethod
    def material_delta(before: Game, after: Game, me: int) -> float:
        """What `me` gained from `before` to `after` in hit points, kills included (`hp_change`), and in the ONGOING
        slots. A hero's death is not counted here: the caller reads `after.winner`."""
        delta = 0.0
        for fid, f in before.fighters.items():
            now = after.fighters[fid]
            if f.alive and (now.alive or not now.hero):
                delta += EffectAI.hp_change(f, now.hp if now.alive else 0, me, before)
            elif not f.alive and now.alive:
                delta += (HARPY_VALUE if now.owner == me else -W_SIDEKICK) * now.hp + (1 if now.owner == me else -1) * kill_value(after, now)
        delta += W_MEDUSA_HP * (ongoing.worth(after, me) - ongoing.worth(before, me))
        delta -= W_HERO * (ongoing.worth(after, 1 - me) - ongoing.worth(before, 1 - me))
        return delta

    # ------------------------------------------------------------------ a whole scheme, simulated
    def scheme_outcome(self, game: Game, card, me: int, fid: str | None = None) -> Game | None:
        """The game after `me` plays `card` (a scheme) on a blind clone, deciding inside with these same rules: what
        the heuristic values a scheme by. None when the card cannot be played there."""
        rng = random.Random(f"{self.seed}:{game.turn_no}:{me}:{card.card_id}:scheme")
        g = blind_clone(game, me, rng)
        card = next(c for c in g.players[me].hand if c.card_id == card.card_id)
        chooser = _SimChooser(self)
        g.pre_play_signature = play_signature(g, me, card)       # `MedusaAI.scheme_changed_nothing` compares to it
        try:
            if g.play_scheme(me, g.fighters[fid] if fid else g.hero(me), card, choosers={0: chooser, 1: chooser}) is not None:
                return None
        except (RuleError, EffectError, NotImplementedError):
            return None
        return g

    # ------------------------------------------------------------------ the op behind a request
    @staticmethod
    def _locate(game: Game, req: ChoiceRequest):
        """(op, card, owner, moment) for the card effect that asked, found through the request key
        `moment/path:ask`; None for anything that is not a card moment (ability triggers, unknown cards)."""
        if req.card_id is None or "/" not in req.key:
            return None
        card = None if req.card_owner is None else game.card_of(req.card_id, req.card_owner)
        found = [] if card is None else [(req.card_owner, card)]       # decks share CardIDs: the request names the owner
        label, _, rest = req.key.partition("/")
        segs = rest.rsplit(":", 1)[0].split("/")
        for owner, card in found:
            try:
                node = load_effects(game.players[owner].hero.slug).moment_ops(card.title, label)
                for seg in segs:
                    seg = seg.split("@")[0]
                    node = node[int(seg)] if isinstance(node, list) else node[seg]
            except Exception:
                continue
            if isinstance(node, dict):
                return node, card, owner, label
        return None
