"""IA heuristica de Medusa.

Funcion de valoracion (puntos de "ventaja" desde el punto de vista de Medusa)
-----------------------------------------------------------------------------
Un plan son hasta 2 acciones (maniobra, ataque, plan, pasar). Se puntua
    valor(plan) = sum(valor de cada accion) + valor_posicion(estado final esperado)
y se ejecuta solo la primera accion; luego se replanifica con el resultado real.

Valor de una accion
  * ataque   = peso(objetivo) * dano esperado + bonus de efectos "AFTER COMBAT" ponderados por
               la probabilidad de ganar - coste de carta (+ penalizacion si acelera la
               transformacion de Hellboy con Clutching Claws / Hiss and Slither)
  * maniobra = robar (+CARD_VALUE) - coste de la carta de boost
  * plan     = dano esperado (A Momentary Glance) o reposicionamiento (Winged Frenzy) - coste de carta
  * plan de cualquier otro heroe interpretado (D2) = lo que deja simularlo en un clon ciego con EffectAI
               decidiendo dentro (material, ONGOING que entra o sale, cartas que gana o pierde, acciones que da)
               - coste de carta; la ejecucion real decide con las mismas reglas.
  El rival se modela con la hipergeometrica: su mano son `h` cartas al azar de las que NO estan en su
  descarte; juega su mejor carta elegible. Asi salen P(ganar), dano esperado y P(matar).

Valor de posicion (kiting)
  -amenaza de Hellboy y Lobster para el turno siguiente, tomando por atacante el mejor objetivo:
     pasos hasta una casilla desde la que pueden golpear  vs  movimiento + boost posible
     (P(tener carta con el boost necesario), ANUNG UN RAMA suma ANUNG_FREE_MOVE por su movimiento libre
     y +2 al valor de ataque), dano esperado descontando mi mejor defensa en mano, y riesgo letal.
  +PRESSURE por cada rival en la zona de Medusa (habilidad + disparo sin moverse).
  Simplificacion: los cuerpos no bloquean el camino del rival (solo ocupan casillas de ataque).

Agotamiento, limite de mano y desesperacion
  * Robar con el mazo vacio hace EXHAUST_DAMAGE a cada luchador propio: `apply_expected` lo simula (una maniobra
    o un Snipe/Regroup que mata a Medusa vale -DEATH) y los robos con mazo se cuentan como cartas desconocidas
    (`Game.phantom_draws`).
  * Al acabar el turno (`terminal_value`): se descartan las cartas que pasen de HAND_LIMIT (las de menor
    `keep_value`, y el robo desconocido vale su media) y cada robo que se come el mazo cuesta `DECK_SCARCITY`
    segun los robos que Medusa aun puede pagar (`draw_budget`). Una maniobra sin mover con la mano llena solo pierde.
  * `desperation` (0..1) mide cuanto va perdiendo el bot: PV propios frente a los del heroe rival, Harpias caidas y
    reloj del agotamiento. Con ella sube el premio por quedar a tiro del heroe rival (progreso esperado hacia ganar
    x LETHAL, el mismo patron que el castigo por morir) y baja el peso de la huida: huir solo compensa si el
    tiempo juega a favor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, comb

from .cards import can_be_boost
from .combat import GAZE_DAMAGE, GLANCE_DAMAGE, ON_EARTH, SECOND_SHOT
from .controller import Controller
from .state import ANUNG, EXHAUST_DAMAGE, HAND_LIMIT, Fighter, Game

GAZE = "medusa_gaze"      # Medusa's start-of-turn ability trigger (data/heroes/effects/medusa.json)

CARD_VALUE = 0.4
W_HERO = 1.0
W_SIDEKICK = 0.8
KILL_SIDEKICK = 3.0
W_MEDUSA_HP = 1.2
HARPY_VALUE = 0.9
LETHAL = 60.0
PRESSURE = 0.3
BOOST_DISCOUNT = 0.65   # reaching with a boost costs him a card and both actions
DOUBLE_ATTACK = 1.5     # already in reach: he can attack twice without moving
ANUNG_FREE_MOVE = 2
BOOST_RELIANCE = 0.6
TRANSFORM_PENALTY = {1: 3.0, 2: 1.8, 3: 0.8}
MAX_ENEMY_STEPS = 9
TOP_FIRST = 6
TOP_FIRST_DESPERATE = 14   # cuando cada accion cuenta se mira mas ancho antes de comprometerse
TOP_SECOND = 4
APPROACH_PULL = 0.1        # position value lost per space between a non-Medusa hero and the nearest rival
APPROACH_TOP = 3           # extra first actions that walk into reach of a rival (non-Medusa heroes)
DEATH = 120.0           # perder la partida (mas que LETHAL, que se pondera por probabilidad)
DECK_SCARCITY = {0: 3.0, 1: 1.8, 2: 1.0, 3: 0.5, 4: 0.25}   # coste de quedarse con pocos robos que pagar
DESPERATE_FEAR_DROP = 0.8   # con desesperacion total la huida pesa un 20 %
WIN_PRIZE = 60.0            # ganar vale lo que perder cuesta: progreso esperado x premio
PROGRESS_DISCOUNT = 0.8     # el rival puede apartarse antes de mi proximo turno
CLOCK_HORIZON = 8           # con 8 o mas robos por pagar el reloj del mazo no aprieta
IDLE_MANEUVER = 0.5         # (not Medusa, whose kiting is standing clear) a maneuver that moves nobody and spends no boost is only a draw: it gives way to a decent attack
ACTION_VALUE = 1.0          # una accion que regala un plan: al menos el robo de una maniobra, a menudo un ataque

AFTER_BONUS = {
    "Regroup": (CARD_VALUE, CARD_VALUE),       # (siempre, extra si gana)
    "Snipe": (CARD_VALUE, 0.0),
    "Dash": (0.5, 0.0),
    "The Hounds of Mighty Zeus": (0.4, 0.0),
    "Clutching Claws": (0.7, 0.0),
    "Hiss and Slither": (0.7, 0.0),
}
DISCARD_EFFECTS = ("Clutching Claws", "Hiss and Slither")

KEEP_BASE = {"attack": 1.0, "defense": 0.8, "versatile": 1.1, "scheme": 0.9}
KEEP_SPECIAL = {"Gaze of Stone": 3.0, "Feint": 1.4, "A Momentary Glance": 1.6, "Hiss and Slither": 1.8,
                "Winged Frenzy": 1.0}


def keep_value(card, hand) -> float:
    v = KEEP_SPECIAL.get(card.title, KEEP_BASE[card.type] + 0.25 * (card.value or 0)) + 0.1 * card.boost
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
    variant: str | None = None      # scheme: the SyntheticChooser policy the search evaluated it with (D2)
    sim: object = None              # scheme: the game the heuristic's simulation left (its expected state)


class Model:
    """Lo que Medusa sabe del rival: composicion de su mazo menos lo que ya esta en el descarte."""

    def __init__(self, game: Game, me: int):
        self.game, self.me, self.opp = game, me, 1 - me
        st = game.players[self.opp]
        self.pool = [c for c in st.full_set if c not in st.discard]
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
        """Valor del ataque dado que el rival ya ha jugado una carta: sin masa de "no tiene carta", renormalizada."""
        bonus = self.game.attack_bonus(f)
        fn = lambda c: c.value + bonus if c.can_attack and c.usable_by(f.name) else None
        dist = [(p, v) for p, v in self.best_dist(("commit", f.name, bonus), fn, max(self.h, 1)) if v is not None]
        total = sum(p for p, _ in dist)
        if total == 0:
            return [(1.0, 0)]
        return [(p / total, v) for p, v in dist]

    def defense_dist(self, t: Fighter):
        destiny = self.game.destiny_count(self.opp)
        bonus = self.game.combat_bonus_total(t.owner)     # ONGOING publico del rival (Fight Or Flight)
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


class MedusaAI(Controller):
    """Sin azar propio: los empates se rompen por id, asi que dada la partida (semilla) es determinista."""

    def __init__(self, me: int = 0):
        self.me = me
        self._plan_moves: dict[str, int] = {}
        self._plan_spot: int | None = None
        self._strike_cache: dict = {}
        self._effect_ai = None

    # ---------- preparacion de la partida ----------
    def should_mulligan(self, game: Game, hand) -> bool:
        """Mano inicial mala: ninguna carta con la que atacar, o tres o mas que no sirven para atacar (planes y
        defensas puras). El mulligan es de una sola vez (lo aplica la sesion)."""
        attackers = sum(1 for c in hand if c.can_attack)
        return attackers == 0 or len(hand) - attackers >= 3

    def choose_setup(self, game: Game, hand) -> dict[str, int]:
        """Casillas iniciales: Medusa en su salida y las Harpias en su zona de salida. Con Clutching Claws o The
        Hounds of Mighty Zeus en la mano se adelantan (la mejor `harpy_score` frente a las piezas rivales ya
        colocadas); sin ellas se quedan atras, lo mas lejos posible de Hellboy y cerca de Medusa."""
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

    # ---------- inicio de turno ----------
    def pick_ability_target(self, game: Game) -> Fighter | None:
        """Objetivo de la habilidad de inicio de turno de Medusa; con cualquier otro heroe no hay (aun) habilidad."""
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

    # ---------- planificacion ----------
    def plan(self, game: Game) -> Act:
        model = Model(game, self.me)
        ranked = self.candidates(game, model)
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
        """Acciones legales ordenadas por valor propio + valor de la posicion que dejan. Pasar no existe: una maniobra sin mover roba igual."""
        acts = self.attack_acts(game, model) + self.scheme_acts(game, model) + self.maneuver_acts(game, model)
        for a in acts:
            g = self.apply_expected(game, a)
            if g.winner is not None:
                a.total = a.value + self.outcome(g)
                continue
            a.total = a.value + self.position_value(g, model)
            if g.actions_left == 0:
                a.total += self.terminal_value(g)
        unique = {(a.kind, a.fid, a.target, a.card and a.card.card_id, a.boost and a.boost.card_id,
                   tuple(sorted(a.moves.items())), a.spot, a.variant): a for a in reversed(acts)}   # la 1.a de cada una
        return sorted(unique.values(), key=lambda a: -a.total)

    def outcome(self, g: Game) -> float:
        """A game finished in the expected state: lost (exhaustion) or won (a scheme that finishes the rival)."""
        return DEATH if g.winner == self.me else -DEATH

    # ----- ataques -----
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
                    value, dmg = self.attack_eval(game, model, f, t, c)
                    out.append(Act("attack", value, f.fid, t.fid, c, exp_damage=dmg, p_win=self.p_win_of(game, model, f, t, c)))
        return out

    def eval_attack(self, game: Game, model: Model, f: Fighter, t: Fighter, c) -> float:
        return self.attack_eval(game, model, f, t, c)[0]

    def p_win_of(self, game: Game, model: Model, f: Fighter, t: Fighter, c) -> float:
        atk = float(c.value) + game.attack_bonus(f)
        if c.title == SECOND_SHOT:
            spare = [x for x in game.players[self.me].hand if x is not c]
            atk += BOOST_RELIANCE * max((x.boost for x in spare), default=0)
        return sum(p for p, dv in model.defense_dist(t) if atk - (dv or 0) >= 1)

    def attack_eval(self, game: Game, model: Model, f: Fighter, t: Fighter, c) -> tuple[float, float]:
        hand = game.players[self.me].hand
        atk, cost = float(c.value) + game.attack_bonus(f), CARD_VALUE + 0.05 * c.boost    # ANUNG UN RAMA's +2, a live ONGOING
        if c.title == SECOND_SHOT:
            spare = [x for x in hand if x is not c]
            if spare:
                atk += BOOST_RELIANCE * max(x.boost for x in spare)
                cost += CARD_VALUE
        e_net = p_win = p_kill = gaze_dmg = 0.0
        for p, dv in model.defense_dist(t):
            net = max(0.0, atk - (dv or 0))
            won = net >= 1
            e_net += p * min(net, t.hp)
            p_win += p * won
            extra = min(GAZE_DAMAGE, max(0.0, t.hp - net)) if (c.title == "Gaze of Stone" and won) else 0.0
            gaze_dmg += p * extra
            p_kill += p * (net + extra >= t.hp)
        w = weight(t)
        value = w * (e_net + gaze_dmg) + (KILL_SIDEKICK if not t.hero else 8.0) * p_kill - cost
        if t.hero and f.owner == self.me:
            # el dano ya hecho vale mas que el que solo se podria hacer luego (`win_progress` lo descuenta)
            value += self.desperation(game) * WIN_PRIZE * (e_net + gaze_dmg) / max(t.hp, 1)
        always, on_win = AFTER_BONUS.get(c.title, (0.0, 0.0))
        value += always + on_win * p_win
        if c.title in DISCARD_EFFECTS:
            decisive = p_kill >= 0.5 or (p_win >= 0.85 and e_net >= 5)
            if not decisive:
                value -= self.transform_penalty(game, model)
        return value, e_net + gaze_dmg

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
            if not c.is_scheme or not c.usable_by(medusa.name) or c.title in seen:
                continue
            seen.add(c.title)
            if c.title == "A Momentary Glance":
                for t in game.foes(self.me):
                    if game.board.share_zone(medusa.pos, t.pos):
                        dmg = min(GLANCE_DAMAGE, t.hp)
                        v = weight(t) * dmg + (KILL_SIDEKICK if not t.hero and t.hp <= GLANCE_DAMAGE else 0) - CARD_VALUE
                        out.append(Act("glance", v, medusa.fid, t.fid, c))
            elif c.title == "Winged Frenzy":
                out.append(self.frenzy_act(game, model, c))
            elif interpreted:
                out.append(self.scheme_act(game, c))
        return [a for a in out if a is not None]

    def scheme_act(self, game: Game, card) -> Act | None:
        """A scheme played on a blind clone with EffectAI deciding inside (`EffectAI.scheme_outcome`): its value is
        the material it swings (kills, the ONGOING it brings in or replaces), the cards it draws (unknown: CARD_VALUE
        each) minus those it gives up (their keep_value) and the card itself, plus the actions it grants."""
        me = self.me
        after = self.effect_ai().scheme_outcome(game, card, me)
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
        return Act("scheme", value, game.hero(me).fid, "", card, sim=after)

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

    # ----- maniobra -----
    def maneuver_acts(self, game: Game, model: Model) -> list[Act]:
        hand = game.players[self.me].hand
        medusa = game.hero(self.me)
        variants: list = [(None, 0.0)]
        seen = set()
        for c in sorted(hand, key=lambda c: (keep_value(c, hand), -c.boost, c.card_id)):
            if can_be_boost(c) and c.boost not in seen:    # por cada alcance, la carta que menos duele gastar
                seen.add(c.boost)
                variants.append((c, keep_value(c, hand) * 0.5))
        out = []
        by_extra: dict[int, list[int]] = {}    # los mejores destinos solo dependen del alcance, no de la carta
        for boost, cost in variants:
            extra = boost.boost if boost else 0
            if extra not in by_extra:
                options = game.legal_moves(medusa, medusa.move + extra) | {medusa.pos}
                ranked = sorted(((-self.position_value(game, model, {medusa.fid: d}), d) for d in options))
                # ademas de los mejores por posicion, los que dejan a Medusa a tiro de un rival: moverse y atacar
                # en la misma accion doble (la posicion sola nunca los elegiria si el rival es peligroso)
                striking = [x for x in ranked if any(game.board.can_reach_target(x[1], e.pos, medusa.ranged)
                                                     for e in game.foes(self.me))]
                by_extra[extra] = list(dict.fromkeys(d for _, d in ranked[:3] + striking[:2]))
            scored = by_extra[extra]
            for d in dict.fromkeys(scored + [medusa.pos]):
                for harpies_advance in (True, False):
                    g = game.clone()
                    g.fighters[medusa.fid].pos = d
                    moves = {medusa.fid: d}
                    exhausting = not g.players[self.me].deck
                    for h in sorted((x for x in g.own(self.me) if not x.hero), key=lambda x: x.fid):
                        if exhausting and h.hp <= EXHAUST_DAMAGE:
                            continue    # el robo con el mazo vacio la mata antes de moverse
                        if harpies_advance:
                            opts = g.legal_moves(h, h.move + extra) | {h.pos}
                            h.pos = max(opts, key=lambda s: (self.harpy_score(g, h, s), -s))
                        moves[h.fid] = h.pos
                    idle = medusa.name != "Medusa" and boost is None and all(game.fighters[fid].pos == dest for fid, dest in moves.items())
                    out.append(Act("maneuver", CARD_VALUE - cost - (IDLE_MANEUVER if idle else 0.0), medusa.fid, "", None,
                                   moves=moves, boost=boost))
        return out

    # ---------- estado esperado ----------
    def expected_draw(self, g: Game, n: int = 1) -> None:
        """Robo simulado: con mazo, una carta desconocida (`phantom_draws`); sin mazo, el agotamiento del motor."""
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
                self.expected_draw(g, 2 if a.p_win > 0 else 1)   # pesimista: el agotamiento no se juega a cara o cruz
        elif a.kind == "maneuver":
            self.expected_draw(g, 1)
            if a.boost is not None:
                hand.remove(a.boost)
                g.players[self.me].discard.append(a.boost)
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
        return g

    # ---------- tiempo: mazo, mano y desesperacion ----------
    def draw_budget(self, game: Game) -> int:
        """Robos que Medusa aun puede pagar sin morir: el mazo y los agotamientos que sus PV aguantan."""
        medusa = game.hero(self.me)
        return max(0, len(game.players[self.me].deck) + ceil(medusa.hp / EXHAUST_DAMAGE) - 1)

    def avg_unseen_keep(self, game: Game) -> float:
        p = game.players[self.me]
        unseen = list(p.full_set)
        for c in p.hand + p.discard:
            if c in unseen:
                unseen.remove(c)
        return sum(keep_value(c, [c]) for c in unseen) / len(unseen) if unseen else KEEP_BASE["attack"]

    def terminal_value(self, game: Game) -> float:
        """Coste de cerrar el turno asi: descartar lo que pase del limite de mano y gastar robos escasos."""
        p = game.players[self.me]
        over = len(p.hand) + game.phantom_draws - HAND_LIMIT
        cost = 0.0
        if over > 0:
            pool = sorted([keep_value(c, p.hand) for c in p.hand] + [self.avg_unseen_keep(game)] * game.phantom_draws)
            cost = sum(pool[:over])
        return -cost - DECK_SCARCITY.get(self.draw_budget(game), 0.0)

    def desperation(self, game: Game) -> float:
        """0 (sin problema) a 1 (perdiendo claramente): PV propios frente a los del heroe rival, Harpias caidas y
        reloj del agotamiento."""
        me, rival = game.hero(self.me), game.hero(1 - self.me)
        if not me.alive or not rival.alive:
            return 0.0
        hp_c = min(1.0, max(0.0, (1 - me.hp / max(rival.hp, 0.5)) / 0.6))
        harpies = [f for f in game.own(self.me, alive_only=False) if not f.hero]
        side_c = sum(1 for f in harpies if not f.alive) / len(harpies) if harpies else 0.0
        clock_c = min(1.0, max(0.0, 1 - self.draw_budget(game) / CLOCK_HORIZON))
        return min(1.0, max(0.0, ((hp_c + side_c + clock_c) / 3 - 0.25) / 0.75))

    def win_progress(self, game: Game, model: Model, medusa: Fighter, rival: Fighter) -> float:
        """Fraccion de los PV del heroe rival que mis dos mejores ataques de la mano le quitarian."""
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
        foes = game.foes(self.me)
        board = game.board
        occupied = set(pos.values())
        hand = game.players[self.me].hand
        despair = self.desperation(game)
        score = 0.0
        for e in foes:
            extra = game.form(1 - self.me) == ANUNG and e.hero
            best = 0.0
            for t in mine:
                spots = [s for s in self.strike_spots(board, pos[t.fid], e.ranged) if s == pos[e.fid] or s not in occupied]
                steps = min((board.distance(pos[e.fid], s) for s in spots), default=MAX_ENEMY_STEPS)
                if steps >= MAX_ENEMY_STEPS:
                    continue
                need = steps - e.move - (ANUNG_FREE_MOVE if extra else 0)
                p_reach = model.p_boost(need) * (BOOST_DISCOUNT if need > 0 else DOUBLE_ATTACK if steps == 0 else 1.0)
                if p_reach <= 0:
                    continue
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
                    danger = HARPY_VALUE * t.max_hp * p_hit
                else:
                    danger = W_MEDUSA_HP * exp + LETHAL * p_dead
                best = max(best, p_reach * danger)
            score -= best * (1 - DESPERATE_FEAR_DROP * despair)
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
        return score

    def harpy_score(self, game: Game, h: Fighter, dest: int) -> float:
        foes = game.foes(self.me)
        if not foes:
            return 0.0
        b = game.board
        near = min(b.distance(dest, e.pos) for e in foes)
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
            options = self.reach_dests(game, f, options) or options
            return max(options, key=lambda d: (self.position_value(game, model, {f.fid: d}), -d))
        return max(options, key=lambda d: (self.harpy_score(game, f, d), -d))

    # ---------- ejecucion ----------
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
            return game.play_scheme(me, game.hero(me), a.card, choosers=self.scheme_choosers(game, a.variant))

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

    # ---------- decisiones que el motor delega ----------
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
        return sorted(hand, key=lambda c: (keep_value(c, hand), c.card_id))[:n]

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
        defending = t.owner == self.me
        best, best_gain = None, 0.0
        for c in filter(can_be_boost, hand):
            if defending:
                net = max(0, ctx.atk_value - ctx.def_value - c.boost)
                gain = (W_MEDUSA_HP if t.hero else HARPY_VALUE) * (min(now, t.hp) - min(net, t.hp))
                gain += LETHAL if t.hero and now >= t.hp > net else 0.0
            else:
                net = max(0, ctx.atk_value + c.boost - ctx.def_value)
                gain = weight(t) * (min(net, t.hp) - min(now, t.hp))
            gain -= keep_value(c, hand)
            if gain > best_gain:
                best, best_gain = c, gain
        return best

    def choose_defense(self, game: Game, attacker: Fighter, target: Fighter, attack_card: Card | None = None):
        """`attack_card`: the attack played face up (UNCANNY INTUITION, Perfect Shot): the one card the defense may
        know; otherwise the value is the distribution of what the rival may have committed."""
        model = Model(game, self.me)
        hand = game.players[self.me].hand
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
        return best

    def eval_defense(self, game: Game, model: Model, dist, target: Fighter, c) -> float:
        dv = c.value if c else 0
        exp = p_dead = p_hit = p_block = 0.0
        for p, av in dist:
            net = max(0, (av or 0) - dv) if av is not None else 0
            exp += p * min(net, target.hp)
            p_dead += p * (net >= target.hp)
            p_hit += p * (net >= 1)
            p_block += p * (net == 0)
        if not target.hero:
            v = -HARPY_VALUE * target.max_hp * p_hit
        else:
            v = -W_MEDUSA_HP * exp - LETHAL * p_dead
        if c is None:
            return v
        v -= CARD_VALUE + 0.05 * c.boost
        always, on_win = AFTER_BONUS.get(c.title, (0.0, 0.0))
        v += always + on_win * p_block
        if c.title == "Feint":
            v += 0.3
        if c.title in DISCARD_EFFECTS:
            decisive = p_block >= 0.85 and exp < 0.5
            if not decisive:
                v -= self.transform_penalty(game, model)
        return v
