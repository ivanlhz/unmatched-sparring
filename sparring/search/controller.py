"""Bot AI with ISMCTS search: a substitute for `MedusaAI` with the same interface that `Session` and `sim` use
(`plan`, `execute`, `choose_defense`, `pick_ability_target`, `should_mulligan`, `choose_setup`, `take_turn`).

The search decides the turn's actions and the defense. The rest (start-of-turn ability, mulligan,
initial placement, and the decisions the engine delegates in mid-resolution: boost, Dash, Hounds, forced
discard, repositioning a Harpy) is still decided by the `MedusaAI` heuristic through composition.

Hook: `make_bot_ai(cfg)` reads `cfg["ai"]`; without the key (or "heuristic") it returns `MedusaAI`, with "ismcts"
it returns this class. `play.py` uses it with `--ai` / `--ai-time`. If the search fails, the decision falls back to `MedusaAI`
with a WARNING in the log instead of bringing the turn down.
"""
from __future__ import annotations

import logging
import random
from dataclasses import replace

from .. import enraged
from ..ai_medusa import GAZE, Act, MedusaAI, scheme_fighter
from ..cards import Card
from ..combat import is_medusa_card
from ..controller import Controller
from ..state import Fighter, Game
from .adapter import EngineState, EvalWeights, Knowledge, by_title, plan_frenzy, sidekick_plan
from .ismcts import ISMCTS, SearchConfig, SearchReport

DEFAULT_TIME_BUDGET = 1.5
log = logging.getLogger(__name__)


class IsmctsMedusa(Controller):
    def __init__(self, me: int = 0, config: SearchConfig | None = None, weights: EvalWeights | None = None):
        self.me = me
        self.config = config or SearchConfig(time_budget=DEFAULT_TIME_BUDGET)
        self.weights = weights or EvalWeights()
        self.heuristic = MedusaAI(me)
        self.last_report: SearchReport | None = None
        self.fallbacks = 0                                       # decisions that fell to the heuristic because of a failure

    def reset(self) -> None:
        """New game (Restart): the last report is forgotten. What was seen of the rival's hand lives in the engine
        (`Game.players[me].known`) and the new game brings it empty."""
        self.last_report = None

    # ---------- what the search does not decide ----------
    def should_mulligan(self, game: Game, hand) -> bool:
        return self.heuristic.should_mulligan(game, hand)

    def choose_setup(self, game: Game, hand) -> dict[str, int]:
        return self.heuristic.choose_setup(game, hand)

    def pick_ability_target(self, game: Game) -> Fighter | None:
        return self.heuristic.pick_ability_target(game)

    def choose_move(self, game: Game, fighter: Fighter, steps: int, through_enemies: bool = False):
        return self.heuristic.choose_move(game, fighter, steps, through_enemies)

    def choose_placement(self, game: Game, fighter: Fighter, options: list[int]):
        return self.heuristic.choose_placement(game, fighter, options)

    def choose_discard(self, game: Game, player: int, n: int, reason: str):
        return self.heuristic.choose_discard(game, player, n, reason)

    def choose_combat_boost(self, game: Game, ctx):
        return self.heuristic.choose_combat_boost(game, ctx)

    def choose_effect(self, game: Game, req):
        return self.heuristic.choose_effect(game, req)

    # ---------- search ----------
    def _decide(self, root: EngineState) -> list:
        """Root move and, if the action is decomposed into sub-moves, the following ones along the principal
        variation of the bot's tree; if the tree does not reach, it searches again from the intermediate state."""
        search = ISMCTS(self.config)
        move, report = search.search(root, self.me)
        self.last_report = report
        chosen = [move]
        state = root.clone()
        # the walk also determinizes: the rival's real hand is never consulted, not even to see whether it defends
        state.determinize(self.me, random.Random(self.config.seed))
        state.apply(move)
        pv = search.principal_variation(self.me, start=move)[1:]
        while state.decision_pending() and state.player_to_move() == self.me:
            legal = state.legal_moves()
            if pv and pv[0] in legal:
                nxt = pv.pop(0)
            else:                       # rare: the tree did not reach; a short search from the intermediate state
                nxt, _ = ISMCTS(self._fallback_config()).search(state, self.me)
                pv = []
            chosen.append(nxt)
            state.apply(nxt)
        return chosen

    def _fallback_config(self) -> SearchConfig:
        cfg = self.config
        return replace(cfg, time_budget=cfg.time_budget / 4,
                       iterations=max(50, cfg.iterations // 4) if cfg.iterations is not None else None)

    def plan(self, game: Game) -> Act:
        try:
            return self._plan(game)
        except AssertionError:                 # the anti-cheating tripwires are not disguised as a search failure
            raise
        except Exception:
            self._fell_back("plan")
            return self.heuristic.plan(game)

    def _fell_back(self, what: str) -> None:
        self.fallbacks += 1
        log.warning("The ISMCTS search failed in %s; the MedusaAI heuristic decides.", what, exc_info=True)

    def knowledge(self, game: Game) -> Knowledge:
        """What look-at-the-hand effects showed, as the engine's KnownHand keeps it (already discounted)."""
        return Knowledge.from_game(game, self.me)

    def _plan(self, game: Game) -> Act:
        root = EngineState(game, observer=self.me, knowledge=self.knowledge(game), weights=self.weights)
        return self.to_act(game, self._decide(root))

    def choose_defense(self, game: Game, attacker: Fighter, target: Fighter, attack_card: Card | None = None) -> Card | None:
        try:
            return self._choose_defense(game, attacker, target, attack_card)
        except AssertionError:
            raise
        except Exception:
            self._fell_back("defense")
            return self.heuristic.choose_defense(game, attacker, target, attack_card)

    def _choose_defense(self, game: Game, attacker: Fighter, target: Fighter, attack_card: Card | None) -> Card | None:
        root = EngineState(game, observer=self.me, knowledge=self.knowledge(game),
                           pending=(attacker.fid, target.fid, attack_card), weights=self.weights)
        if root.pending is None:              # the attack known (face up) and no defense card: the root resolved it
            return None
        move = self._decide(root)[0]
        return by_title(game.players[self.me].hand, move[1]) if move[1] is not None else None

    def to_act(self, game: Game, chosen: list) -> Act:
        """From the chain of sub-moves to the `Act` that `execute` and the session understand."""
        hand = game.players[self.me].hand
        hero = game.hero(self.me)
        first = chosen[0]
        kind = first[0]
        # a sub-phase with a single option resolved itself and is not in the chain: it is rebuilt the same way as there
        sub = {m[0]: m for m in chosen[1:]}
        if kind == "attack":
            fighter = game.fighters[first[1]]
            titles = list(dict.fromkeys(c.title for c in hand if enraged.may_attack_with(game, self.me, c) and c.usable_by(fighter.name)
                                        and game.attack_card_reaches(fighter, game.fighters[first[2]], c)))
            card = sub["attack_card"][2] if "attack_card" in sub else titles[0]
            return Act("attack", fid=first[1], target=first[2], card=by_title(hand, card))
        if kind == "maneuver":
            boost = by_title(hand, first[1]) if first[1] is not None else None
            _, dest, policy = sub.get("place", ("place", hero.pos, "stay"))
            plan = sidekick_plan(game, self.me, boost.boost if boost else 0, policy, hero_dest=dest)
            return Act("maneuver", fid=hero.fid, moves=dict(((hero.fid, dest),) + plan), boost=boost)
        if kind == "scheme" and first[2] is not None:
            return Act("glance", fid=hero.fid, target=first[2], card=by_title(hand, first[1]))
        if kind == "scheme" and is_medusa_card(by_title(hand, first[1])):
            moves, spot = plan_frenzy(game, self.me, first[3])
            return Act("frenzy", fid=hero.fid, card=by_title(hand, first[1]), moves=moves, spot=spot)
        if kind == "scheme":        # D2: executed with the SyntheticChooser the search evaluated it with
            card = by_title(hand, first[1])
            return Act("scheme", fid=scheme_fighter(game, self.me, card).fid, card=card, variant=first[3])
        raise ValueError(f"move without an equivalent action: {chosen!r}")

    def execute(self, game: Game, act: Act) -> None:
        self.heuristic.execute(game, act)

    def take_turn(self, game: Game) -> None:
        target = self.pick_ability_target(game)
        if target:
            game.use_ability(self.me, GAZE, target)
        while game.actions_left > 0 and game.winner is None and game.hero(self.me).alive:
            self.execute(game, self.plan(game))


def make_bot_ai(cfg: dict, bot: int = 0):
    """Configuration flag, off by default: `"ai": "ismcts"` enables the search; `ai_time_budget` (s),
    `ai_iterations` (cap per decision, for tests) and `ai_seed` adjust it; `ai_eval` (an object with fields of
    `EvalWeights`) changes the evaluation weights."""
    kind = cfg.get("ai", "heuristic")
    if kind == "heuristic":
        return MedusaAI(bot)
    if kind == "ismcts":
        iters = cfg.get("ai_iterations")
        return IsmctsMedusa(bot, SearchConfig(time_budget=float(cfg.get("ai_time_budget", DEFAULT_TIME_BUDGET)),
                                              iterations=None if iters is None else int(iters),
                                              seed=int(cfg.get("ai_seed", 0))),
                            EvalWeights(**cfg.get("ai_eval", {})))
    raise ValueError(f"unknown ai in the configuration: {kind!r} (heuristic | ismcts)")
