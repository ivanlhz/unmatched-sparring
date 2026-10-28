"""IA del bot con busqueda ISMCTS: sustituto de `MedusaAI` con la misma interfaz que usan `Session` y `sim`
(`plan`, `execute`, `choose_defense`, `pick_ability_target`, `should_mulligan`, `choose_setup`, `take_turn`).

La busqueda decide las acciones del turno y la defensa. Lo demas (habilidad de inicio de turno, mulligan,
colocacion inicial, y las decisiones que el motor delega a mitad de una resolucion: boost, Dash, Hounds, descarte
forzado, recolocar Harpia) lo sigue decidiendo la heuristica de `MedusaAI` por composicion.

Enganche: `make_bot_ai(cfg)` lee `cfg["ai"]`; sin la clave (o "heuristic") devuelve `MedusaAI`, con "ismcts"
devuelve esta clase. `play.py` la usa con `--ai` / `--ai-time`. Si la busqueda falla, la decision cae a `MedusaAI`
con un WARNING en el log en vez de tumbar el turno.
"""
from __future__ import annotations

import logging
import random
from dataclasses import replace

from ..ai_medusa import Act, MedusaAI
from ..cards import Card
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
        self.fallbacks = 0                                       # decisiones que cayeron a la heuristica por un fallo

    def reset(self) -> None:
        """Partida nueva (Reiniciar): se olvida el ultimo informe. Lo visto de la mano rival vive en el motor
        (`Game.players[me].known`) y la partida nueva lo trae vacio."""
        self.last_report = None

    # ---------- lo que la busqueda no decide ----------
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

    # ---------- busqueda ----------
    def _decide(self, root: EngineState) -> list:
        """Jugada de la raiz y, si la accion esta descompuesta en subjugadas, las siguientes por la variacion
        principal del arbol del bot; si el arbol no llega, se busca de nuevo desde el estado intermedio."""
        search = ISMCTS(self.config)
        move, report = search.search(root, self.me)
        self.last_report = report
        chosen = [move]
        state = root.clone()
        # el recorrido tambien determiniza: nunca se consulta la mano real del rival, ni para ver si defiende
        state.determinize(self.me, random.Random(self.config.seed))
        state.apply(move)
        pv = search.principal_variation(self.me, start=move)[1:]
        while state.decision_pending() and state.player_to_move() == self.me:
            legal = state.legal_moves()
            if pv and pv[0] in legal:
                nxt = pv.pop(0)
            else:                       # raro: el arbol no llego; una busqueda corta desde el estado intermedio
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
        except AssertionError:                 # los tripwires anti-trampas no se disfrazan de fallo de busqueda
            raise
        except Exception:
            self._fell_back("plan")
            return self.heuristic.plan(game)

    def _fell_back(self, what: str) -> None:
        self.fallbacks += 1
        log.warning("La busqueda ISMCTS fallo en %s; decide la heuristica de MedusaAI.", what, exc_info=True)

    def knowledge(self, game: Game) -> Knowledge:
        """Lo visto por un efecto de mirar la mano rival, tal como lo lleva el motor (ya descontado de lo salido)."""
        rival = 1 - self.me
        return Knowledge({rival: tuple(game.players[self.me].known.cards(game.players[rival]))})

    def _plan(self, game: Game) -> Act:
        root = EngineState(game, observer=self.me, knowledge=self.knowledge(game), weights=self.weights)
        return self.to_act(game, self._decide(root))

    def choose_defense(self, game: Game, attacker: Fighter, target: Fighter) -> Card | None:
        try:
            return self._choose_defense(game, attacker, target)
        except AssertionError:
            raise
        except Exception:
            self._fell_back("defensa")
            return self.heuristic.choose_defense(game, attacker, target)

    def _choose_defense(self, game: Game, attacker: Fighter, target: Fighter) -> Card | None:
        root = EngineState(game, observer=self.me, knowledge=self.knowledge(game),
                           pending=(attacker.fid, target.fid, None), weights=self.weights)
        move = self._decide(root)[0]
        return by_title(game.players[self.me].hand, move[1]) if move[1] is not None else None

    def to_act(self, game: Game, chosen: list) -> Act:
        """De la cadena de subjugadas a la `Act` que entienden `execute` y la sesion."""
        hand = game.players[self.me].hand
        hero = game.hero(self.me)
        first = chosen[0]
        kind = first[0]
        # una subfase con una sola opcion se resolvio sola y no esta en la cadena: se reconstruye igual que alli
        sub = {m[0]: m for m in chosen[1:]}
        if kind == "attack":
            fighter = game.fighters[first[1]]
            titles = list(dict.fromkeys(c.title for c in hand if c.can_attack and c.usable_by(fighter.name)))
            card = sub["attack_card"][2] if "attack_card" in sub else titles[0]
            return Act("attack", fid=first[1], target=first[2], card=by_title(hand, card))
        if kind == "maneuver":
            boost = by_title(hand, first[1]) if first[1] is not None else None
            _, dest, policy = sub.get("place", ("place", hero.pos, "stay"))
            plan = sidekick_plan(game, self.me, boost.boost if boost else 0, policy, hero_dest=dest)
            return Act("maneuver", fid=hero.fid, moves=dict(((hero.fid, dest),) + plan), boost=boost)
        if kind == "scheme" and first[2] is not None:
            return Act("glance", fid=hero.fid, target=first[2], card=by_title(hand, first[1]))
        if kind == "scheme":
            moves, spot = plan_frenzy(game, self.me, first[3])
            return Act("frenzy", fid=hero.fid, card=by_title(hand, first[1]), moves=moves, spot=spot)
        raise ValueError(f"jugada sin accion equivalente: {chosen!r}")

    def execute(self, game: Game, act: Act) -> None:
        self.heuristic.execute(game, act)

    def take_turn(self, game: Game) -> None:
        target = self.pick_ability_target(game)
        if target:
            game.medusa_ability(target)
        while game.actions_left > 0 and game.winner is None and game.hero(self.me).alive:
            self.execute(game, self.plan(game))


def make_bot_ai(cfg: dict, bot: int = 0):
    """Flag de configuracion, apagado por defecto: `"ai": "ismcts"` activa la busqueda; `ai_time_budget` (s),
    `ai_iterations` (tope por decision, para pruebas) y `ai_seed` la ajustan; `ai_eval` (objeto con campos de
    `EvalWeights`) cambia los pesos de la evaluacion."""
    kind = cfg.get("ai", "heuristic")
    if kind == "heuristic":
        return MedusaAI(bot)
    if kind == "ismcts":
        iters = cfg.get("ai_iterations")
        return IsmctsMedusa(bot, SearchConfig(time_budget=float(cfg.get("ai_time_budget", DEFAULT_TIME_BUDGET)),
                                              iterations=None if iters is None else int(iters),
                                              seed=int(cfg.get("ai_seed", 0))),
                            EvalWeights(**cfg.get("ai_eval", {})))
    raise ValueError(f"ai desconocida en la configuracion: {kind!r} (heuristic | ismcts)")
