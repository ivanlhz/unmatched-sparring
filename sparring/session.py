"""Sesion en vivo: traduce los botones del humano (eventos del panel) a llamadas de `Game` y proyecta
las decisiones del bot en la mesa de TTS. Toda la E/S va por `TTSClient.call_lua` (peticion y respuesta).

Principios
  * La mesa manda. La mano del bot se lee de su asiento; su mazo es el multiconjunto de 30 cartas menos lo
    visto (orden desconocido); robar y descartar son operaciones fisicas confirmadas leyendo la mesa. Si la
    mesa y el motor discrepan de forma permanente (el humano movio una carta del bot, una pieza no se deja
    mover...), tras `adopt_after` fallos seguidos, o con Cancelar, el motor adopta lo que muestra la mesa.
  * Del humano solo se conoce lo que esta en su descarte y el tamano de su mano; nada se inventa. Lo que el
    motor no puede saber (dano o curacion de efectos) entra por los botones de PV y Retirar.
  * Las piezas se identifican por GUID, nunca por nombre.
  * Revelar valida antes de tocar nada: una carta ilegal deja el combate pendiente.
  * El estado se guarda tras cada boton (`state_path`) y se puede reanudar.
"""
from __future__ import annotations

import hashlib
import json
import math
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import persist
from .ai_medusa import MedusaAI
from .cards import Card, can_be_boost
from .controller import Controller
from .combat_flow import PendingChoice
from .combat import FEINT, FIGHT_OR_FLIGHT, FIGHT_OR_FLIGHT_BONUS, GLANCE_DAMAGE, can_boost, deck_boost, is_medusa_card, scheme_gain_actions
from .state import ANUNG, DETECTIVE, EXHAUST_DAMAGE, HAND_LIMIT, START_HAND, Fighter, Game, RuleError
from .tts import lua, ui
from .tts.lua import ChatKind
from .tts.client import TTSClient, TTSLuaError
from .tts.ui import Event


CROWN = "And Upon His Brow Is Set A Crown Of Flame"


class SessionError(Exception):
    """La mesa no esta como el motor esperaba (carta que no esta, descarte que no coincide...)."""


TABLE_ERRORS = (SessionError, TTSLuaError, OSError)      # TimeoutError es un OSError
RESTART_WINDOW = 3.0   # segundos para confirmar Reiniciar partida con una segunda pulsacion
COMPOSITE_OVERHEAD = 12_000   # lo que ocupa la instantanea y el armazon de un compuesto, ademas de sus operaciones
TRANSIT_READS = 4   # lecturas del descarte que se espera a una carta humana recien jugada antes de darla por perdida


class Msg(str):
    """Mensaje del bot: un `str` que ademas lleva su categoria, para colorearlo en el chat sin tocar a quien lo trata como texto."""
    kind: ChatKind

    def __new__(cls, text: str, kind: ChatKind = ChatKind.NEUTRAL) -> "Msg":
        obj = super().__new__(cls, text)
        obj.kind = ChatKind(kind)
        return obj


# categoria de cada accion del bot en `_action_text`; el ataque no pasa por ahi (lo dice `_bot_continue`)
ACTION_KIND = {"maneuver": ChatKind.MOVE, "glance": ChatKind.SCHEME, "frenzy": ChatKind.SCHEME}


CODED_ABILITY_HERO = "medusa"     # el heroe cuya habilidad de inicio de turno ejecuta el motor (`medusa_ability`)
DEFAULT_BOT_PAUSE = 1.0     # segundos entre acciones del bot en la partida real (los tests usan 0)


@dataclass
class SessionConfig:
    bot_seat: str
    human_seat: str
    nicknames: dict[str, str]                    # fid -> nombre para los mensajes (las piezas van por GUID)
    bot_card_spot: tuple[float, float, float]    # donde el bot deja su carta boca abajo (mundo)
    human_card_spot: tuple[float, float]         # (x, z) donde el humano deja la suya
    bot_discard_spot: tuple[float, float, float]  # origen de la rejilla del descarte del bot (primer hueco)
    bot_discard_zone: str                        # GUID de la ZONA de scripting sobre el descarte del bot
    bot_deck_guid: str                           # GUID del mazo fisico del bot
    human_discard_zone: str                      # GUID de la ZONA de scripting sobre el descarte del humano
    bot_deck_spot: tuple[float, float]           # (x, z) del mazo: la ultima carta queda suelta y solo se halla asi
    pieces: dict[str, str | list[str]]           # fid -> GUID de la miniatura, o varios si cambia de estado
    reveal_radius: float = 2.0
    rot_y: float = 0.0
    settle_tries: int = 6          # lecturas de la mesa antes de dar por fallado un movimiento de cartas
    settle_wait: float = 0.4       # segundos entre lecturas (0 en los tests)
    dials: dict[str, str] = field(default_factory=dict)   # fid -> GUID del dial de vida (opcional: solo avisa)
    off_board_dist: float = 4.0    # una pieza a mas de esto de su casilla mas cercana no esta en el tablero
    adopt_after: int = 3           # fallos de mesa seguidos tras los que se adopta lo que muestra la mesa
    bot_discard_step: tuple[float, float] = (-3.6, 2.2)   # (dx de columna, dz de fila) entre huecos del descarte
    bot_discard_rows: int = 15     # huecos por columna antes de pasar a la siguiente
    bot_discard_rot_y: float = 90.0
    deck_clear: float = 3.0        # los huecos a menos de esto del mazo de robo se saltan
    human_deck_guid: str | None = None            # mazo de robo del humano (puede estar dentro de su zona)
    human_deck_spot: tuple[float, float] | None = None
    deck_exclude_radius: float = 1.5              # lo que este tan cerca de un mazo no es descarte
    start_spaces: dict[str, int] = field(default_factory=dict)   # fid del heroe -> su casilla de salida real
    bot_discard_bounds: tuple[float, float, float, float, float] | None = None   # (cx, cz, tamano x, z, rotY) de la zona
    setup: bool = False            # preparar la partida (mano, mulligan, colocar piezas) antes de jugar
    mulligan_bot: bool = True      # el bot puede cambiar su mano inicial una vez si es mala (regla de la casa)
    mulligan_human: bool = True    # el humano dispone del boton Mulligan en la preparacion (regla de la casa)
    destiny_dial: str | None = None   # GUID del dial de destinos (cuenta de destinos de Hellboy en su descarte)
    dead_spot: tuple[float, float, float] | None = None   # donde el bot aparta las miniaturas de SUS caidos
    discard_layer: float = 0.15    # altura que se sube cada vuelta completa de la rejilla del descarte
    batch: bool = False            # modo rapido: lecturas desde la instantanea y escrituras en un solo script por paso
    human_dead_spot: tuple[float, float, float] | None = None   # donde el bot aparta las miniaturas CAIDAS del humano
    label_font: float = lua.LABEL_FONT   # tamano del texto de las etiquetas del suelo
    bot_pause: float = 0.0         # segundos de pausa tras cada accion del bot (0 = sin pausa; `play` usa 1.0)
    live_ui: bool = False          # linea de estado, botones segun el estado y anuncios por pantalla en el mismo script
    bot_card_ids: tuple[int, int] = lua.BOT_CARD_IDS         # rango de CardID del mazo del bot (de su heroe: data/tts)
    human_card_ids: tuple[int, int] = lua.HUMAN_CARD_IDS     # y del mazo del humano
    deck_identity: dict[str, tuple] = field(default_factory=dict)   # "bot"/"human" -> pares (FaceURL, BackURL) de data/tts
    bot_label: str = "MEDUSA"      # nombre de cada bando en las etiquetas del suelo (el de su heroe)
    human_label: str = "HELLBOY"
    look_spot: tuple[float, float, float] = (-23.0, 2.5, 0.0)   # centro de la fila de la mano del bot a la vista (estimacion: calibrar en vivo)
    look_step: tuple[float, float] = (0.0, 2.6)                 # (dx, dz) entre cartas de la fila
    look_rot_y: float | None = None                              # giro de las cartas de la fila (por defecto, el del descarte del bot)


def human_dead_spot(cfg: "SessionConfig") -> tuple[float, float, float] | None:
    """Zona de bajas del humano: la configurada o, por defecto, la del bot reflejada al otro lado de la mesa (fuera
    del tablero, junto a su asiento)."""
    if cfg.human_dead_spot is not None:
        return cfg.human_dead_spot
    if cfg.dead_spot is not None:
        return (-cfg.dead_spot[0], cfg.dead_spot[1], cfg.dead_spot[2])
    return None


def piece_guids(value) -> list[str]:
    """GUID de una miniatura: uno, o varios si cambia de estado (cada estado es otro objeto con otro GUID)."""
    guids = [value] if isinstance(value, str) else value
    if not isinstance(guids, (list, tuple)) or not guids or not all(isinstance(g, str) for g in guids):
        raise ValueError(f"GUID de miniatura no valido: {value!r} (un GUID o una lista no vacia de GUID)")
    return list(guids)


# claves de la configuracion que identifican la mesa y la partida (los ajustes finos no cuentan)
IDENTITY_KEYS = ("destiny_dial", "bot_seat", "human_seat", "bot_deck_guid", "bot_discard_zone", "human_discard_zone",
                 "human_deck_guid", "start_spaces", "dials")


class HumanProxy(Controller):
    """El humano decide en la mesa: cuando el motor le obliga a descartar, el bot lo anuncia y espera."""

    def __init__(self, owe):
        self.owe = owe

    def take_turn(self, game: Game) -> None:
        pass

    def choose_discard(self, game: Game, player: int, n: int, reason: str):
        self.owe(n, reason)
        return []


class _Op:
    """Escritura en la mesa. En modo rapido espera en la cola hasta que algo necesita su resultado (o la mesa)."""
    __slots__ = ("session", "script", "domain", "value", "error", "done", "seen")

    def __init__(self, session: "Session", script: str, domain: str):
        self.session, self.script, self.domain = session, script, domain
        self.value, self.error, self.done, self.seen = None, None, False, False

    @property
    def result(self):
        if not self.done:
            self.session._flush()
        self.seen = True
        if self.error is not None:
            raise self.error
        return self.value


class _Timed:
    """Cuenta los mensajes a TTS y el tiempo de un boton o de una accion del bot (`--timing`)."""

    def __init__(self, session: "Session", label: str):
        self.session, self.label = session, label

    def __enter__(self):
        if self.session._depth == 0:
            self.session._epoch += 1
        self.session._depth += 1
        self.calls0 = getattr(self.session.client, "calls", 0)
        self.t0 = time.monotonic()
        return self

    def __exit__(self, *exc):
        self.session._depth -= 1
        calls = getattr(self.session.client, "calls", 0) - self.calls0
        took = time.monotonic() - self.t0
        self.session.cost_log.append((self.label, calls, took))
        if self.session.timing is not None:
            self.session.timing(f"[tiempo] {self.label}: {calls} mensajes a TTS, {took * 1000:.0f} ms")
        return False


# con la mano del bot a la vista solo se atiende lo que la resuelve (o no la toca: PV, retirar, valor)
LOOK_EVENTS = (Event.LOOK_PING, Event.CANCEL, Event.END_ACTION, Event.HP, Event.REMOVE, Event.VALUE, Event.RESTART)
CARD_TYPE_NAME = {"attack": "ataque", "defense": "defensa", "versatile": "versatil", "scheme": "esquema"}

SNAP_KEYS = ("bot_hand", "human_count", "bot_discard", "human_discard", "face_bot", "face_human", "pieces", "dials")


@dataclass
class Pending:
    kind: str                    # human_attacks | bot_attacks
    attacker: Fighter
    target: Fighter
    bot_card: Card | None        # defensa del bot (human_attacks) o ataque del bot (bot_attacks)
    bot_card_guid: str | None = None
    cancel_failures: int = 0
    defended: bool = True        # False: el humano ataca y el bot aun no ha decidido ni puesto su defensa (se hace al Revelar)
    wait: PendingChoice | None = None   # cartas ya reveladas, sin resolver: espera el BOOST del humano (extra: guid, baseline, hand, stuck)

    @property
    def boost_wait(self) -> dict | None:
        """Flat save form of `wait` (read-only: mutate `wait` itself, e.g. `wait.extra["stuck"] = True`)."""
        return None if self.wait is None else self.wait.to_dict()


class Session:
    def __init__(self, game: Game, client: TTSClient, ai: MedusaAI, cfg: SessionConfig, bot: int = 0):
        self.game, self.client, self.ai, self.cfg = game, client, ai, cfg
        self.bot, self.human = bot, 1 - bot
        game.controllers[self.bot] = ai
        game.controllers[self.human] = HumanProxy(self._owe_discard)
        self.pending: Pending | None = None
        self.pending_discard: dict | None = None
        self.look_fails = 0                      # cierres de la fila que la mesa no hizo (el segundo Cancelar fuerza la salida)
        self.look: dict | None = None            # mano del bot a la vista: {"ids", "guids", "spots"} de la fila de la mesa
        self.pending_value = 0
        self.chosen_attacker: str | None = None
        self.moving = False
        self.bot_discarded: set[int] = set()
        self.messages: list[Msg] = []
        self._destiny_tried = False
        self.dials_written: dict[str, int] = {}  # GUID del dial -> ultimo valor que el motor escribio y verifico
        self.dirty = False                       # el motor movio al bot y la mesa aun no lo refleja
        self.unprojected: dict | None = None     # posiciones previas de las piezas aun sin proyectar
        self.bot_stage: str | None = None        # "start": turno del bot empezado en el motor, E/S pendiente
        self.limit_waived = False
        self.flush_failures = 0                  # fallos de mesa (SessionError) seguidos al saldar la deuda
        self.state_path: Path | None = None      # si esta puesto, se guarda tras cada start/resume/handle
        self.game_id = uuid.uuid4().hex          # identifica esta partida en el guardado
        self.setup: dict | None = None                      # maquina de estados de la preparacion (persistida)
        self.first_mode: str | None = None                  # "random" | "human" | "bot": como se eligio quien empieza
        self.dial_debt = False                              # un dial no se pudo escribir en el turno del bot
        self.scheme_baseline: list[int] | None = None      # descarte del humano al pulsar Plan: espera su carta
        self.destiny_seen: tuple[int, str] | None = None   # (destinos, forma) ya escritos y verificados en el dial
        self._transit: dict[int, int] = {}                 # CardID jugado por el humano -> lecturas que lleva sin llegar al descarte
        self._destiny_said: tuple[int, str] | None = None  # lo ya anunciado (no se repite mientras se reintenta)
        self.placing: dict | None = None         # carta del bot puesta en la mesa cuya respuesta no llego
        self.dials_attempted: dict[str, int] = {}  # GUID -> ultimo valor que se intento escribir (verificado o no)
        self._warned: set[tuple[str, str]] = set()
        self._deck_qty = -1                                 # cartas del mazo de robo del humano en la ultima lectura
        self._deal_check: tuple[int, int] | None = None     # (mano, descarte) del humano al repartirle la carta de Maniobra
        self._epoch = 0                                     # numero de boton atendido (para confirmar bajas del descarte)
        self._wild_credit: tuple[int, int, int] = (-1, -1, 0)  # Wildfire: (turno, boton, cartas de mas en tu mano sin explicar)
        self._gone: dict[int, int] = {}                     # CardID que falta en el descarte de la mesa -> boton en que se vio
        self._depth = 0                                     # >0 mientras se atiende un boton, el inicio o una reanudacion
        self._restart_at: float | None = None               # instante del primer toque de Reiniciar partida
        self.cost_log: list[tuple[str, int, float]] = []   # (que, mensajes a TTS, segundos) por boton y por accion
        self.snap: dict | None = None                       # instantanea vigente de la mesa (modo rapido)
        self._trusted = False                               # la instantanea viene del clic: no hace falta releer para confirmar
        self._queue: list[_Op] = []                         # escrituras pendientes del script compuesto
        self._expect_hand: tuple[str, int] | None = None
        self._dials_pending: set[str] = set()               # diales con una escritura aun por comprobar
        self._post: list[Callable[[], bool]] = []           # comprobaciones que esperan al cierre del boton
        self._snap_spec: lua.SnapSpec | None = None
        self._write_seq = 0                                 # ultima escritura de mesa enviada (la sella el compuesto)
        self._deck_ident: dict[str, tuple] = {}             # "bot"/"human" -> pares (FaceURL, BackURL) de su mazo
        self._saved_ident: dict[str, tuple] = {}            # lo mismo, leido de sesion.json (si la mesa no responde)
        self.new_game: Callable[[], Game] | None = None     # fabrica de la partida nueva al reiniciar
        self.clock: Callable[[], float] = time.monotonic    # reloj de la doble pulsacion de Reiniciar partida
        self.timing: Callable[[str], None] | None = None    # --timing: una linea por boton y por accion del bot
        self.broadcast = cfg.live_ui
        for fid, space in cfg.start_spaces.items():
            if fid in game.fighters:
                game.start_spaces[game.fighters[fid].owner] = space

    # ---------- entrada ----------
    def _check_config(self) -> None:
        if (not isinstance(self.cfg.bot_deck_spot, (tuple, list)) or len(self.cfg.bot_deck_spot) != 2):
            raise SessionError("bot_deck_spot es obligatorio: la ultima carta del mazo solo se halla por posicion")
        missing = sorted(set(self.game.fighters) - set(self.cfg.pieces))
        if missing:
            raise SessionError(f"faltan GUIDs de pieza para: {', '.join(missing)}")
        bad = sorted(s for s in self.cfg.start_spaces.values() if s not in self.game.board.spaces)
        if bad:
            raise SessionError(f"start_spaces: casillas que no existen en el tablero: {bad}")
        if not self._grid_slots():
            raise SessionError("ningun hueco de la rejilla del descarte cae dentro de la zona del descarte del bot: "
                               "revisa bot_discard_spot, bot_discard_step y bot_discard_bounds")

    def start(self) -> list[str]:
        with self._timed("inicio"):
            return self._start()

    def _start(self) -> list[str]:
        """Empieza la partida. Un fallo de mesa o de conexion no la mata: deja la deuda y se reintenta con
        Fin de accion (si empieza el bot, `bot_stage` queda a medias y es reanudable)."""
        self.snap = None
        self.messages = []
        self._destiny_tried = False
        self._begin_game()
        return self._done()

    def _preload_identities(self) -> None:
        if "bot" in self._deck_ident:
            return
        try:
            self.load_identities()
        except TABLE_ERRORS as e:
            self._table_failure(e)               # se reintenta al primer uso: sin identidad no se escribe ninguna carta
        for side, pairs in self._saved_ident.items():
            self._deck_ident.setdefault(side, pairs)

    def _begin_game(self) -> None:
        self._check_config()
        self._preload_identities()
        self._announce_first()
        self._announce_bot_hero()
        if self.cfg.setup:
            self.setup = {"stage": "hand", "mull_done": False, "mull_decision": None, "mull_step": "start",
                          "human_mull": False}
            self._assign_start_spaces()
            self._persist()
            self._setup_advance()
            return
        if self.game.turn == self.bot:
            self.bot_stage = "start"
        self._open(announce_turn=True)

    def _announce_first(self) -> None:
        if self.first_mode is None:
            return
        who = self._name(self.game.hero(self.game.turn))
        self.say(f"Sorteo: empieza {who}." if self.first_mode == "random"
                 else f"Empieza {who} (elegido con --first {self.first_mode}).")

    def _bot_ability_coded(self) -> bool:
        """Solo la habilidad de inicio de turno de Medusa esta codificada en el motor (`Game.medusa_ability`); las de
        los demas heroes llegan con los efectos estructurados (F07, pasos 4 a 6)."""
        return self.game.hero_def(self.bot).slug == CODED_ABILITY_HERO

    def _announce_bot_hero(self) -> None:
        """Un heroe del bot sin habilidad codificada: se dice su texto y se juega por valor y boost, sin romper nada."""
        hero = self.game.hero_def(self.bot)
        if not self._bot_ability_coded() and hero.ability:
            self.say(f"El bot juega {hero.name}. Su habilidad ('{hero.ability}') aun no esta codificada en el motor: "
                     "el bot la ignora y juega por valor y boost; si te afecta, aplicala tu en la mesa.",
                     ChatKind.ABILITY)

    def resume(self) -> list[str]:
        with self._timed("reanudar"):
            return self._resume()

    def _resume(self) -> list[str]:
        """Reanuda una partida cargada de un guardado: la mesa manda (se relee) y se retoma donde se quedo."""
        self.snap = None
        self.messages = []
        self._destiny_tried = False
        self._check_config()
        self._preload_identities()
        self.say("Partida reanudada desde el guardado.")
        if self.setup is not None:
            self.say(f"La preparacion de la partida estaba en la etapa '{self.setup['stage']}'.")
            self._setup_advance()
            self._write_dials(post=True)
            return self._done()
        self._open(announce_turn=False)
        self._write_dials(post=True)              # la mesa ensena ya la vida del motor, no la de antes del corte
        if self.game.winner is not None:
            self.say(f"Fin de partida: gana el jugador {self.game.winner}. (Deshacer fin de partida si es un error.)")
        elif self.look is not None:
            self._w(lua.set_look_row(self._look_entries()), "misc")     # la variable del panel no sobrevive a una recarga
            self.say("La mano del bot sigue a la vista: haz ping (Tab) sobre la carta a descartar o pulsa Cancelar.",
                     ChatKind.YOUR_TURN)
        elif self.pending is not None and self.pending.wait is not None:
            self.say(self._boost_prompt(self.pending), ChatKind.YOUR_TURN)
        elif self.pending is not None:
            self.say("Hay un combate pendiente: pulsa Revelar o Cancelar ataque.", ChatKind.YOUR_TURN)
        elif self.pending_discard is not None:
            self.say("Hay un descarte pendiente: terminalo y pulsa Fin de accion.", ChatKind.YOUR_TURN)
        elif self.game.turn == self.human:
            self.say(f"Es tu turno y te quedan {self.game.actions_left} accion(es).", ChatKind.YOUR_TURN)
        return self._done()

    def _open(self, announce_turn: bool) -> None:
        try:
            self._name_pieces()
            if announce_turn:
                self._setup_new_game()
            self.read_bot_hand()
            if announce_turn and self.dirty:
                self._flush_table()                  # reparto de las manos iniciales
            self.sync_positions()
            self.sync_human()
            if self.game.turn == self.bot and self.pending is None and self.game.winner is None:
                self._bot_continue()
            elif announce_turn and self.game.turn == self.human:
                self._announce_human_start()
        except TABLE_ERRORS as e:
            self._table_failure(e)
            if self.game.turn == self.bot:
                self.say("Pulsa Fin de accion para que el bot retome su turno.", ChatKind.YOUR_TURN)

    def _setup_new_game(self) -> None:
        """Solo al empezar una partida nueva: casillas de salida reales y manos iniciales."""
        if not self.cfg.start_spaces:
            for player in (self.bot, self.human):                 # sin configurar: son donde empieza cada heroe
                info = self._table_pieces().get(self.game.hero(player).fid) or {}
                if self._on_board(info):
                    self.game.start_spaces[player] = info["space"]
        if not self._table_hand_ids():
            self.game.drawn[self.bot] = START_HAND
            self.dirty = True
            self.say(f"El bot reparte sus {START_HAND} cartas iniciales.")
        if self._rd_human_count(1) == 0:
            self.say(f"Roba tus {START_HAND} cartas iniciales (el bot no reparte a tu asiento).", ChatKind.YOUR_TURN)

    # ---------- preparacion de la partida: maquina de estados persistida ----------
    # Etapas (self.setup["stage"]): las que ejecuta el bot solo, y las que esperan al humano (boton Listo).
    #   hand -> mulligan -> [empieza el bot]    place_bot -> wait_human            -> begin
    #                       [empieza el humano] wait_human_first -> place_bot -> begin
    # Quien coloca primero sigue el turno: si empieza el bot coloca Medusa y las Harpias (solo con su mano y las
    # casillas de salida conocidas) y luego pide al humano que coloque; si empieza el humano, el bot ESPERA, lee
    # donde puso a Hellboy y Lobster y entonces coloca las Harpias teniendo en cuenta esas casillas.
    SETUP_AUTO = ("hand", "mulligan", "place_bot", "begin")

    def _assign_start_spaces(self) -> None:
        """Reglamento: el primer jugador ocupa la casilla de salida 1 y el otro la 2 (salvo configuracion explicita).
        Las piezas del motor se recolocan en su zona de salida hasta que se coloquen de verdad."""
        g = self.game
        if not self.cfg.start_spaces:
            first = g.turn
            g.start_spaces = {first: g.board.starts["1"], 1 - first: g.board.starts["2"]}
        taken: set[int] = set()
        for player in (self.bot, self.human):
            start = g.start_spaces[player]
            for f in sorted(g.own(player), key=lambda f: (not f.hero, f.fid)):    # solo los que estan en el tablero
                f.pos = g.board.nearest_free(start, taken, zone_of=start)
                taken.add(f.pos)

    def _setup_advance(self) -> None:
        """Avanza las etapas del bot hasta una que espere al humano. Reanudable: cada etapa es idempotente y se
        guarda al terminar; un fallo de mesa deja la etapa donde estaba y Listo la reintenta."""
        try:
            while self.setup is not None and self.setup["stage"] in self.SETUP_AUTO:
                stage = self.setup["stage"]
                if stage == "hand":
                    self._setup_hand()
                    self.setup["stage"] = "mulligan"
                elif stage == "mulligan":
                    self._setup_mulligan()
                    self._require_bot_hand_matches()
                    self.setup["stage"] = "place_bot" if self.game.turn == self.bot else "wait_human_first"
                    if self.setup["stage"] == "wait_human_first":
                        self._setup_place_hero()
                        names, many = self._sidekick_names(), len(self._sidekicks()) > 1
                        place = (f", coloca a {names} en la zona de la casilla {self.game.start_spaces[self.human]}"
                                 if names else "")
                        where = ("donde " + ("los pusiste" if many else "lo pusiste")) if names else "donde esta tu heroe"
                        self.say(f"Empiezas tu. Roba tus 5 cartas{place} y pulsa Listo. El bot colocara despues, "
                                 f"viendo {where}.", ChatKind.YOUR_TURN)
                elif stage == "place_bot":
                    self._require_bot_hand_matches()
                    self._setup_place()
                    if self.game.turn == self.bot:
                        self._setup_place_hero()
                        self.setup["stage"] = "wait_human"
                        names = self._sidekick_names()
                        place = (f"coloca a {names} en la zona de la casilla {self.game.start_spaces[self.human]}, "
                                 if names else "")
                        self.say(f"Ahora {place}roba tus 5 cartas y pulsa Listo.", ChatKind.YOUR_TURN)
                    else:
                        self.setup["stage"] = "begin"
                elif stage == "begin":
                    self._setup_begin()
                    return
                self._persist()
        except TABLE_ERRORS as e:
            self._table_failure(e)
            self.say("Pulsa Listo para reintentar la preparacion.", ChatKind.WARNING)

    def _setup_hand(self) -> None:
        self._name_pieces()
        if not self._table_hand_ids():
            self.game.drawn[self.bot] = START_HAND
            self.dirty = True
            self.say(f"El bot reparte sus {START_HAND} cartas iniciales.")
        self.read_bot_hand()
        if self.dirty:
            self._flush_table()

    def _setup_mulligan(self) -> None:
        """Una sola vez: si la mano es mala, las 5 cartas vuelven al mazo, se baraja y se reparten 5 nuevas.
        Se anuncia sin decir cuales eran las cartas.

        Reanudable: la decision se guarda (`mull_decision`) antes de tocar la mesa, porque tras devolver la mano ya no
        hay mano que evaluar, y cada sub-paso fisico (`mull_step`) se guarda al terminar. `mull_done` solo se pone
        cuando la mano de la mesa vuelve a coincidir con la del motor."""
        s, g = self.setup, self.game
        if s["mull_done"]:
            return
        who = self._name(g.hero(self.bot))
        if s.get("mull_decision") and not self.cfg.mulligan_bot:
            self._abandon_mulligan()
        if s.get("mull_decision") is None:
            self.read_bot_hand()
            s["mull_decision"] = bool(self.cfg.mulligan_bot and self.ai.should_mulligan(g, g.players[self.bot].hand))
            self._persist()
        if s["mull_decision"]:
            self._physical_mulligan()
            self.say(f"{who} hace mulligan.")
        else:
            self.say(f"{who} se queda la mano.")
        s["mull_done"] = True

    def _abandon_mulligan(self) -> None:
        """Reanudado con mulligan_bot=false tras un mulligan fisico a medias: se renuncia a el. La mesa manda; si
        la mano esta vacia se reparten 5 cartas, y la preparacion exige que mesa y motor coincidan."""
        s, g = self.setup, self.game
        s["mull_decision"], s["mull_step"] = False, "start"
        self.read_bot_hand()
        if not self._table_hand_ids():
            g.drawn[self.bot] = START_HAND
            self.read_bot_hand()
            self.dirty = True
        if self.dirty:
            self._flush_table()
        self._require_bot_hand_matches()
        self._persist()

    def _physical_mulligan(self) -> None:
        """devolver (returned) -> barajar (shuffled) -> repartir (dealt). Cada paso se anota al acabar; un corte
        o un fallo deja el paso donde estaba y Listo lo reintenta sin repetir los anteriores."""
        c, g, s = self.cfg, self.game, self.setup
        step = s.setdefault("mull_step", "start")
        if step == "start":
            res = self._w(lua.return_hand_to_deck(c.bot_seat, c.bot_deck_guid, c.bot_card_ids, identity=self._identity()), "cards").result or {}
            if not res.get("deck"):
                raise SessionError("no encuentro el mazo del bot para el mulligan")
            if not self._settle(lambda: not self._table_hand_ids()):
                raise SessionError("las cartas del bot no han vuelto al mazo; reintenta con Listo")
            step = s["mull_step"] = "returned"
            self._persist()
        if step == "returned":
            total = len(g.players[self.bot].full_set)

            def shuffled() -> bool:
                r = self._w(lua.shuffle_deck(c.bot_deck_guid, c.bot_deck_spot, id_range=c.bot_card_ids, identity=self._identity()), "cards").result or {}
                return bool(r.get("shuffled")) and r.get("quantity") == total
            if not self._settle(shuffled):
                raise SessionError(f"no pude barajar el mazo completo del bot ({total} cartas); reintenta con Listo")
            st = g.players[self.bot]
            st.hand, st.deck = [], [x for x in st.full_set if x not in st.discard]
            g.rng.shuffle(st.deck)
            g.drawn[self.bot] = 0
            g.draw(self.bot, START_HAND, log=False)
            self.dirty = True
            step = s["mull_step"] = "shuffled"
            self._persist()
        if step == "shuffled":
            self._flush_table()
            self._require_bot_hand_matches()
            s["mull_step"] = "dealt"

    def _require_bot_hand_matches(self) -> None:
        """La preparacion no avanza mientras la mano de la mesa no sea la del motor."""
        table = sorted(self._table_hand_ids())
        engine = sorted(c.card_id for c in self.game.players[self.bot].hand)
        if table != engine:
            raise SessionError(f"la mano del bot en la mesa ({len(table)} cartas) no coincide con la del motor "
                               f"({len(engine)}); reintenta con Listo")

    def _setup_place(self) -> None:
        """Medusa y las Harpias se colocan en la mesa con move_piece y se verifican leyendo la mesa."""
        g = self.game
        self.sync_positions()                     # donde estan de verdad Hellboy y Lobster (si ya se colocaron)
        plan = self.ai.choose_setup(g, g.players[self.bot].hand)
        pieces = self._table_pieces() if self.cfg.batch else None
        staged = []
        for fid, space in plan.items():
            g.fighters[fid].pos = space
            staged.append((fid, space, self._move_stage(fid, space, pieces)))
            if not self.cfg.batch and not staged[-1][2]():
                raise SessionError(f"no pude mover la pieza de {self._name(g.fighters[fid])} a la casilla {space}")
        if self.cfg.batch:
            for fid, space, moved in staged:
                if not moved():
                    raise SessionError(f"no pude mover la pieza de {self._name(g.fighters[fid])} a la casilla {space}")

        def placed() -> bool:
            pieces = self._table_pieces()
            return all((pieces.get(fid) or {}).get("found") and pieces[fid].get("space") == sp
                       for fid, sp in plan.items())
        if not self._settle(placed):
            raise SessionError("las piezas del bot no estan donde debian; reintenta con Listo")
        self.say("El bot coloca: " + "; ".join(f"{self._name(g.fighters[fid])} en la casilla {sp}"
                                                for fid, sp in plan.items()) + ".")

    def _setup_place_hero(self) -> None:
        """El heroe del humano sale de su casilla de salida (fija por el reglamento): el bot lo coloca, lo verifica
        en la mesa y lo anuncia. El humano solo coloca a su ayudante. Idempotente (`hero_placed` se persiste)."""
        s, g = self.setup, self.game
        if s.get("hero_placed"):
            return
        hero = g.hero(self.human)
        space = g.start_spaces[self.human]
        hero.pos = space
        if not self._move_piece(hero.fid, space):
            raise SessionError(f"no pude mover la pieza de {self._name(hero)} a la casilla {space}")

        def placed() -> bool:
            info = self._table_pieces().get(hero.fid) or {}
            return bool(info.get("found")) and info.get("space") == space
        if not self._settle(placed):
            raise SessionError(f"{self._name(hero)} no esta en su casilla de salida; reintenta con Listo")
        s["hero_placed"] = True
        self.say(f"El bot coloca a {self._name(hero)} (tu heroe) en su casilla de salida {space}.")

    def _setup_begin(self) -> None:
        g = self.game
        self.setup = None
        self.sync_human()
        self.say("Preparacion terminada: empieza la partida.")
        if g.turn == self.bot:
            self.bot_stage = "start"
            self._persist()
            self._bot_continue()
        else:
            self._persist()
            self._announce_human_start()

    def _ready(self, _: dict) -> None:
        """Boton Listo: el humano termino de colocar (y robar). Se comprueba en la mesa antes de seguir."""
        s = self.setup
        if s is None:
            self.say("No hay ninguna preparacion en curso.", ChatKind.WARNING)
            return
        if s["stage"] in ("wait_human_first", "wait_human"):
            try:
                self._setup_place_hero()                 # si un fallo anterior lo dejo sin colocar
            except TABLE_ERRORS as e:
                self._table_failure(e)
                return
            if not self._human_setup_ok():
                return
            s["stage"] = "place_bot" if s["stage"] == "wait_human_first" else "begin"
        self._setup_advance()

    def _human_mulligan(self, _: dict) -> None:
        """Boton Mulligan del humano: solo en la preparacion, una vez y antes de Listo. El bot no toca su mazo: le
        dice que devuelva la mano, baraje y robe 5 (el humano roba en su asiento)."""
        s = self.setup
        if s is None:
            self.say("El mulligan solo se hace durante la preparacion, antes de pulsar Listo.", ChatKind.WARNING)
        elif not self.cfg.mulligan_human:
            self.say("El mulligan del humano esta desactivado en la configuracion (mulligan_human).", ChatKind.WARNING)
        elif s["stage"] not in ("wait_human_first", "wait_human"):
            self.say("Espera a que el bot termine de preparar su mano y pulsa Mulligan despues.", ChatKind.WARNING)
        elif s.get("human_mull"):
            self.say(f"Ya has hecho tu mulligan: solo se puede una vez. Pulsa Listo cuando tengas {START_HAND} cartas.", ChatKind.WARNING)
        else:
            s["human_mull"] = True
            self.say(f"Mulligan: devuelve tu mano a tu mazo, baraja y vuelve a robar {START_HAND} cartas. "
                     + (f"Despues coloca a {self._sidekick_names()} y pulsa Listo." if self._sidekicks()
                        else "Despues pulsa Listo."), ChatKind.YOUR_TURN)

    def _human_setup_ok(self) -> bool:
        g = self.game
        self.sync_positions()
        start = g.start_spaces[self.human]
        for fid, f in g.fighters.items():
            if f.owner != self.human:
                continue
            info = self._table_pieces().get(fid) or {}
            if not self._on_board(info) or not g.board.share_zone(start, info["space"]):
                self.say(f"Falta colocar a {self._name(f)} en la zona de la casilla {start}.", ChatKind.WARNING)
                return False
        count = self._rd_human_count(0)
        if count == 0:
            self.say(f"Roba tus {START_HAND} cartas antes de pulsar Listo.", ChatKind.WARNING)
            return False
        if (self.setup or {}).get("human_mull") and count != START_HAND:
            self.say(f"Tras tu mulligan debes tener {START_HAND} cartas en la mano (tienes {count}).", ChatKind.WARNING)
            return False
        return True

    def _name_pieces(self) -> None:
        """Pone a cada miniatura el nombre de su clave de configuracion (Harpy 1/2/3...) para distinguirlas con el
        raton. Por GUID; un fallo no importa a la partida."""
        names = {g: self.cfg.nicknames[fid] for fid in self.cfg.pieces if fid in self.cfg.nicknames
                 for g in self._guids(fid)}
        if not names:
            return
        try:
            self._w(lua.name_pieces(names), "misc")
        except (ValueError, *TABLE_ERRORS) as e:
            self.say(f"Aviso: no pude poner nombre a las miniaturas ({e}).", ChatKind.WARNING)

    def _done(self) -> list[str]:
        self._commit()
        self._persist()
        self.snap = None                          # la mesa cambia entre botones: el siguiente trae la suya
        return self.messages

    def _table_failure(self, e: Exception) -> None:
        if isinstance(e, SessionError):
            self.say(f"Error de mesa: {e}", ChatKind.WARNING)
        elif isinstance(e, (TTSLuaError, TimeoutError)):
            self.say(f"TTS no respondio como se esperaba ({e}); repite el boton "
                     "(Fin de accion si el bot estaba jugando).", ChatKind.WARNING)
        else:
            self.say(f"Error de mesa y de conexion: no consigo hablar con TTS ({e}); esta cerrado? "
                     "Se reintentara con el siguiente boton.", ChatKind.WARNING)

    def handle(self, event: Event, payload: dict | None = None) -> list[str]:
        payload = dict(payload or {})
        self._take_snapshot(payload.pop("snapshot", None))
        self.messages = []
        self._destiny_tried = False
        with self._timed(f"boton {event.value}"):
            return self._handle(event, payload)

    def _handle(self, event: Event, payload: dict) -> list[str]:
        table = {Event.MANEUVER: self._maneuver, Event.ATTACKER: self._choose_attacker, Event.ATTACK: self._attack,
                 Event.SCHEME: self._scheme, Event.REVEAL: self._reveal, Event.END_ACTION: self._end_action,
                 Event.VALUE: self._value, Event.CANCEL: self._cancel, Event.HP: self._hp,
                 Event.REMOVE: self._remove, Event.UNDO_GAME_OVER: self._undo_game_over, Event.READY: self._ready,
                 Event.MULLIGAN: self._human_mulligan, Event.RESTART: self._restart,
                 Event.BOOST: self._boost, Event.NO_BOOST: self._no_boost,
                 Event.LOOK: self._look_hand, Event.LOOK_PING: self._look_ping}
        if self.setup is not None and event not in (Event.READY, Event.HP, Event.REMOVE, Event.CANCEL, Event.VALUE,
                                                    Event.MULLIGAN, Event.RESTART):
            self.say("La partida aun se esta preparando: termina la colocacion y pulsa Listo.", ChatKind.WARNING)
            return self._done()
        if self.look is not None and event not in LOOK_EVENTS:
            self.say("La mano del bot esta a la vista: haz ping (Tab) sobre la carta a descartar, o gira una boca abajo "
                     "y pulsa Fin de accion, o Cancelar para devolverlas sin descartar.", ChatKind.WARNING)
            return self._done()
        if event is not Event.RESTART:
            self._restart_at = None               # cualquier otro boton desarma la confirmacion
        try:
            table[event](payload)
        except RuleError as e:
            self.say(f"Accion ilegal: {e}", ChatKind.WARNING)
        except TABLE_ERRORS as e:
            self._table_failure(e)
        return self._done()

    def say(self, msg: str, kind: ChatKind = ChatKind.NEUTRAL) -> None:
        self.messages.append(Msg(msg, kind))

    def _warn(self, fid: str, kind: str, msg: str) -> None:
        """Avisa una sola vez por pieza y motivo hasta que el problema desaparezca."""
        if (fid, kind) not in self._warned:
            self._warned.add((fid, kind))
            self.say(msg, ChatKind.WARNING)


    # ---------- reiniciar la partida ----------
    def _restart(self, _: dict) -> None:
        """Doble pulsacion (3 s): la primera arma, la segunda reinicia."""
        if not self.restart_armed():
            self._restart_at = self.clock()
            self.say("Reiniciar partida: pulsa otra vez en 3 segundos para confirmar. Todas las cartas vuelven a sus "
                     "mazos, la vida se restaura, las piezas salen del tablero y se borra el guardado.", ChatKind.WARNING)
            return
        self._restart_at = None
        if self.look is not None:
            self._look_best_effort_cancel()
        fresh = self._fresh_game()
        self._reset_table(fresh)
        self._adopt_fresh(fresh)
        if self.state_path is not None:
            try:
                self.state_path.unlink(missing_ok=True)
            except OSError as e:
                self.say(f"No pude borrar el guardado {self.state_path}: {e}", ChatKind.WARNING)
        self.say("Partida reiniciada: vuelta al reparto, el mulligan y la colocacion.")
        self._begin_game()

    def _fresh_game(self) -> Game:
        if self.new_game is not None:
            return self.new_game()
        game = Game.new(self.game.board, secrets.randbelow(2 ** 31), controllers={}, bot_player=self.bot,
                        heroes=(self.game.hero_def(self.bot).slug, self.game.hero_def(self.human).slug))
        if self.first_mode in ("human", "bot"):
            game.turn = self.human if self.first_mode == "human" else self.bot
        game.begin_turn()
        return game

    def _reset_table(self, fresh: Game) -> None:
        """La mesa a su estado inicial en UN mensaje: todas las cartas de los dos bandos a sus mazos (barajados),
        los diales a vida completa y los destinos a 0, y todas las miniaturas fuera del tablero. Se comprueba en la
        mesa resultante; si algo falla el motor no se toca y se puede repetir."""
        c = self.cfg
        bot_spot, human_spot = c.dead_spot, human_dead_spot(c)
        if bot_spot is None or human_spot is None:
            raise SessionError("falta dead_spot en la configuracion: no hay donde apartar las miniaturas")
        scope = self._scope()
        sizes = {"bot": len(fresh.players[self.bot].full_set), "human": len(fresh.players[self.human].full_set)}
        self._flush()
        self._check_reset_plan(scope, sizes)
        decks = {"bot": self._w(lua.reset_deck(c.bot_deck_guid, c.bot_deck_spot, c.bot_card_ids,
                                               identity=self._identity(), scope=scope), "cards")}
        if c.human_deck_guid:
            decks["human"] = self._w(lua.reset_deck(c.human_deck_guid, c.human_deck_spot, c.human_card_ids,
                                                    identity=self._identity("human"), scope=scope), "cards")
        else:
            self.say("Aviso: sin human_deck_guid no puedo devolver tus cartas a tu mazo; hazlo tu.", ChatKind.WARNING)
        pieces = self._table_pieces()
        for owner, spot, sign in ((self.bot, bot_spot, 1.5), (self.human, human_spot, -1.5)):
            for slot, f in enumerate(sorted(fresh.own(owner, alive_only=False), key=lambda f: f.fid)):
                info = pieces.get(f.fid) or {}
                guid = info["guid"] if info.get("found") else self._guids(f.fid)[0]
                self._w(lua.place_piece(guid, spot[0] + sign * slot, spot[1], spot[2]), "pieces")
        want = {guid: fresh.fighters[fid].max_hp for fid, guid in c.dials.items()}
        want = {g: int(v) for g, v in want.items()}
        if c.destiny_dial:
            want[c.destiny_dial] = 0
        if want:
            self._w(lua.set_health_dials(want), "dials")
        self._flush()
        for side, op in decks.items():
            res = op.result or {}
            if not res.get("deck") or res.get("quantity") != sizes[side]:
                raise SessionError(f"el mazo {'del bot' if side == 'bot' else 'tuyo'} no ha quedado completo "
                                   f"({res.get('quantity')} de {sizes[side]} cartas); repite Reiniciar partida")
        own = {x.card_id for x in fresh.players[self.bot].full_set}

        def clean() -> bool:
            on_board = [fid for fid, info in self._table_pieces().items() if self._on_board(info)]
            dials = self._rd_dials(sorted(want)) if want else {}
            return (not self._table_hand_ids() and not ({r["id"] for r in self._rd_bot_discard()} & own)
                    and not on_board and ("human" not in decks or self._rd_human_count(0) == 0)
                    and all((dials.get(g) or {}).get("value") == v for g, v in want.items()))
        if not self._settle(clean):
            raise SessionError("el reinicio no ha dejado la mesa limpia (manos, descartes, piezas o diales); "
                               "repite Reiniciar partida")

    def _check_reset_plan(self, scope: lua.Scope, sizes: dict[str, int]) -> None:
        """Antes de mover nada: cada bando tiene que poder reunir TODAS sus cartas en su mazo. Si uno no puede, el
        reinicio se rechaza entero (no se deja un bando devuelto y el otro no)."""
        c = self.cfg
        sides = [("bot", c.bot_deck_guid, c.bot_deck_spot, c.bot_card_ids)]
        if c.human_deck_guid:
            sides.append(("human", c.human_deck_guid, c.human_deck_spot, c.human_card_ids))
        plans = self.client.call_lua(lua.reset_plan(
            [(guid, spot, rng, self._identity(side)) for side, guid, spot, rng in sides], scope=scope))
        if not isinstance(plans, list) or len(plans) != len(sides):
            raise TTSLuaError(f"respuesta no valida del plan de reinicio: {str(plans)[:80]!r}")
        for (side, *_), plan in zip(sides, plans):
            plan = plan if isinstance(plan, dict) else {}
            total, gatherable = plan.get("total"), plan.get("deck") or (plan.get("loose") or 0) >= 2
            if total != sizes[side] or not gatherable:
                raise SessionError(
                    f"no puedo reunir las {sizes[side]} cartas del mazo {'del bot' if side == 'bot' else 'tuyo'} "
                    f"(a mi alcance hay {total if isinstance(total, int) else 0}); no he movido nada. Deja todas sus "
                    "cartas en la mano, el descarte, la zona de combate o el mazo y repite Reiniciar partida")

    def _adopt_fresh(self, fresh: Game) -> None:
        """La sesion pasa a la partida nueva, conservando el cliente, la configuracion y los ajustes de ejecucion."""
        keep = ("client", "ai", "cfg", "bot", "human", "timing", "state_path", "first_mode", "new_game", "clock",
                "cost_log", "broadcast", "snap", "_trusted", "_queue", "_post", "_expect_hand", "_snap_spec", "_depth",
                "_epoch", "messages", "_write_seq", "_deck_ident")
        saved = {k: self.__dict__[k] for k in keep}
        blank = Session(fresh, self.client, self.ai, self.cfg, self.bot)
        self.__dict__.clear()
        self.__dict__.update(blank.__dict__)
        self.__dict__.update(saved)
        self.game.controllers[self.human] = HumanProxy(self._owe_discard)
        getattr(self.ai, "reset", lambda: None)()          # la IA con memoria olvida la partida anterior

    # ---------- guardado ----------
    def to_dict(self) -> dict:
        p = self.pending
        return {
            "game": persist.game_to_dict(self.game),
            "heroes": [self.game.hero_def(self.bot).slug, self.game.hero_def(self.human).slug],
            "pending": None if p is None else {
                "kind": p.kind, "attacker": p.attacker.fid, "target": p.target.fid,
                "bot_card": p.bot_card.card_id if p.bot_card else None, "bot_card_guid": p.bot_card_guid,
                "cancel_failures": p.cancel_failures, "defended": p.defended, "boost_wait": None if p.wait is None else p.wait.to_dict()},
            "pending_discard": self.pending_discard, "pending_value": self.pending_value, "look": self.look,
            "chosen_attacker": self.chosen_attacker, "moving": self.moving,
            "bot_discarded": sorted(self.bot_discarded), "dirty": self.dirty,
            "unprojected": None if self.unprojected is None else {k: list(v) for k, v in self.unprojected.items()},
            "bot_stage": self.bot_stage, "limit_waived": self.limit_waived, "flush_failures": self.flush_failures,
            "placing": self.placing, "fingerprint": self.fingerprint(),
            "destiny_seen": None if self.destiny_seen is None else list(self.destiny_seen),
            "scheme_baseline": self.scheme_baseline, "dial_debt": self.dial_debt, "setup": self.setup,
            "dials_written": self.dials_written, "dials_attempted": self.dials_attempted,
            "start_spaces": {str(k): v for k, v in self.game.start_spaces.items()},
            "deck_ident": {side: [list(pair) for pair in pairs]
                           for side, pairs in {**self._saved_ident, **self._deck_ident}.items()},
        }

    def fingerprint(self) -> dict:
        """Huella del guardado: a que mesa (GUID y ajustes de identidad) y a que partida pertenece."""
        c = self.cfg
        identity = {k: getattr(c, k) for k in IDENTITY_KEYS}
        identity["pieces"] = {fid: piece_guids(v) for fid, v in sorted(c.pieces.items())}
        identity["board"] = self.game.board.key
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()
        return {"game_id": self.game_id, "config_hash": digest, "guids": self.guids_in_use()}

    def _check_fingerprint(self, saved) -> None:
        if not isinstance(saved, dict) or not isinstance(saved.get("game_id"), str):
            raise persist.StateError("el guardado no tiene huella de partida (es de una version antigua o ajeno): "
                                     "no se reanuda; empieza una partida nueva")
        mine = self.fingerprint()
        if saved.get("config_hash") != mine["config_hash"]:
            differ = sorted(set(saved.get("guids") or []) ^ set(mine["guids"]))
            detail = f"GUID distintos: {', '.join(differ)}" if differ else "cambian asientos, zonas o casillas de salida"
            raise persist.StateError(f"el guardado es de otra configuracion u otra mesa ({detail}); no se reanuda. "
                                     "Usa la configuracion con la que se guardo o empieza una partida nueva")

    def load_dict(self, d: dict) -> None:
        self._check_fingerprint(d.get("fingerprint"))
        try:
            persist.apply_game(self.game, d["game"])
            by_id = {c.card_id: c for c in self.game.players[self.bot].full_set}
            p = d["pending"]
            self.pending = None if p is None else Pending(
                p["kind"], self.game.fighters[p["attacker"]], self.game.fighters[p["target"]],
                by_id[p["bot_card"]] if p["bot_card"] is not None else None, p["bot_card_guid"], p["cancel_failures"],
                bool(p.get("defended", True)),
                self._load_boost_wait(p.get("boost_wait"), self.human, {c.card_id: c for c in self.game.players[self.human].full_set}))
            self.pending_discard, self.pending_value = d["pending_discard"], d["pending_value"]
            self.look = self._load_look(d.get("look"))
            self.chosen_attacker, self.moving = d["chosen_attacker"], d["moving"]
            self.bot_discarded, self.dirty = set(d["bot_discarded"]), d["dirty"]
            un = d["unprojected"]
            self.unprojected = None if un is None else {k: (v[0], v[1]) for k, v in un.items()}
            self.bot_stage, self.limit_waived = d["bot_stage"], d["limit_waived"]
            self.flush_failures = d["flush_failures"]
            self.placing = d.get("placing")
            self.scheme_baseline = d.get("scheme_baseline")
            self.dial_debt = bool(d.get("dial_debt", False))
            self.dials_written = {str(k): int(v) for k, v in (d.get("dials_written") or {}).items()}
            self.dials_attempted = {str(k): int(v) for k, v in (d.get("dials_attempted") or {}).items()}
            self.setup = d.get("setup")
            if d.get("start_spaces"):
                self.game.start_spaces = {int(k): int(v) for k, v in d["start_spaces"].items()}
            seen = d.get("destiny_seen")
            self.destiny_seen = None if seen is None else (int(seen[0]), str(seen[1]))
            self.game_id = d["fingerprint"]["game_id"]
            self._saved_ident = self._load_saved_identities(d.get("deck_ident"))
        except (KeyError, TypeError, IndexError) as e:
            raise persist.StateError(f"guardado no valido: {e!r}") from None

    @staticmethod
    def _load_look(raw) -> dict | None:
        if raw is None:
            return None
        ok = (isinstance(raw, dict) and all(isinstance(raw.get(k), list) for k in ("ids", "guids", "spots"))
              and 1 <= len(raw["ids"]) <= lua.MAX_LOOK_CARDS
              and len(raw["ids"]) == len(raw["guids"]) == len(raw["spots"])
              and all(isinstance(i, int) and not isinstance(i, bool) for i in raw["ids"])
              and all(isinstance(g, str) and lua._GUID.fullmatch(g) for g in raw["guids"])
              and all(isinstance(sp, list) and len(sp) == 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                                                     and math.isfinite(v) for v in sp)
                      for sp in raw["spots"]))
        if not ok:
            raise KeyError("look")
        return {"ids": list(raw["ids"]), "guids": list(raw["guids"]), "spots": [list(sp) for sp in raw["spots"]]}

    @staticmethod
    def _load_boost_wait(raw, human: int, human_cards: dict | None = None) -> PendingChoice | None:
        """Translator for the saved `boost_wait`: a dict without "kind" is the old flat format (the human's boost)."""
        if raw is None:
            return None
        hand = raw.get("hand") if isinstance(raw, dict) else None
        if not isinstance(raw, dict) or not isinstance(raw.get("card"), int) \
                or not isinstance(raw.get("baseline"), list) or not all(isinstance(i, int) for i in raw["baseline"]) \
                or not (raw.get("guid") is None or isinstance(raw["guid"], str)) \
                or not (hand is None or (isinstance(hand, int) and not isinstance(hand, bool))):
            raise KeyError("boost_wait")
        flat = {"kind": raw.get("kind", "boost"), "player": raw.get("player", human), "card": raw["card"],
                "guid": raw.get("guid"), "baseline": list(raw["baseline"]), "hand": hand,
                "stuck": raw.get("stuck") is True}

        def deck_of(card_id: int) -> bool:        # Flame Lash: recomputed from the card, so a save without the key also works
            card = (human_cards or {}).get(card_id)
            return card is not None and deck_boost(card)
        try:
            return PendingChoice.from_dict({**flat, "deck": raw.get("deck")}, default_player=human, deck_of=deck_of)
        except KeyError:
            raise KeyError("boost_wait") from None

    @staticmethod
    def _load_saved_identities(raw) -> dict[str, tuple]:
        """Las identidades guardadas se validan como las leidas de la mesa; lo que no sirve se descarta sin romper
        el guardado (la identidad se vuelve a leer de la mesa)."""
        out = {}
        for side in ("bot", "human"):
            rows = raw.get(side) if isinstance(raw, dict) else None
            rows = rows if isinstance(rows, list) else []
            pairs = Session._parse_pairs([{"face": r[0], "back": r[1]} for r in rows
                                          if isinstance(r, (list, tuple)) and len(r) == 2])
            if pairs:
                out[side] = pairs
        return out

    def _persist(self) -> None:
        if self.state_path is None:
            return
        try:
            persist.save_atomic(self.state_path, self.to_dict())
        except OSError as e:
            self.say(f"No pude guardar la partida en {self.state_path}: {e}", ChatKind.WARNING)

    def guids_in_use(self) -> list[str]:
        """Todos los GUID de la configuracion que deben seguir existiendo tras recargar la partida."""
        c = self.cfg
        guids = [lua.BOARD_GUIDS[self.game.board.key], c.bot_deck_guid, c.bot_discard_zone, c.human_discard_zone,
                 *(g for v in c.pieces.values() for g in piece_guids(v)), *c.dials.values(),
                 *([c.destiny_dial] if c.destiny_dial else [])]
        return sorted(set(guids))

    def guid_groups(self) -> list[list[str]]:
        """GUID que deben existir, en grupos: de cada grupo basta uno (una miniatura con estados es un solo objeto
        a la vez; el resto de los GUID son los suyos)."""
        c = self.cfg
        singles = [lua.BOARD_GUIDS[self.game.board.key], c.bot_deck_guid, c.bot_discard_zone, c.human_discard_zone,
                   *c.dials.values(), *([c.destiny_dial] if c.destiny_dial else [])]
        return [[g] for g in sorted(set(singles))] + [piece_guids(v) for _, v in sorted(c.pieces.items())]

    def _require_human_turn(self) -> bool:
        if self.game.winner is not None:
            self.say("La partida ha terminado (Deshacer fin de partida si es un error de PV).", ChatKind.WARNING)
            return False
        if self.game.turn != self.human or self.pending is not None or self.pending_discard is not None:
            self.say("Ahora no es posible: termina la resolucion en curso (Revelar / Fin de accion) o espera tu turno.", ChatKind.WARNING)
            return False
        if self.moving:
            self.say("Ya tienes una accion abierta: resuelvela en la mesa y pulsa Fin de accion antes de empezar otra.", ChatKind.WARNING)
            return False
        return True

    def _begin_action(self) -> None:
        """Antes de cada accion del humano se relee la mesa (incluye lo que hizo al empezar el turno)."""
        self._try_flush_table()
        self.sync_positions()
        self.sync_human()

    def _try_flush_table(self) -> None:
        """Salda la deuda de mesa del bot sin bloquear al humano: si sigue fallando solo se avisa."""
        self._try_flush_stage()()

    def _try_flush_stage(self) -> Callable[[], None]:
        try:
            fin = self._flush_table_stage()
        except TABLE_ERRORS as e:
            self.say(f"Aviso: la mesa del bot aun no coincide con el motor ({e}); se reintentara.", ChatKind.WARNING)
            return lambda: None

        def run() -> None:
            try:
                fin()
            except TABLE_ERRORS as e:
                self.say(f"Aviso: la mesa del bot aun no coincide con el motor ({e}); se reintentara.", ChatKind.WARNING)
        return run

    # ---------- botones del humano ----------
    def _maneuver(self, _: dict) -> None:
        if not self._require_human_turn():
            return
        self._begin_action()
        self.game.use_action()
        hp0, alive0 = {fid: f.hp for fid, f in self.game.fighters.items()}, self._alive_map()
        self.moving = True
        st = self.game.players[self.human]
        if not self.cfg.human_deck_guid:
            self.game.draw(self.human)
            self._announce_exhaustion(hp0, alive0)
            self.say("Maniobra: robas 1. Mueve tus miniaturas y pulsa Fin de accion.", ChatKind.YOUR_TURN)
            return
        if not st.deck:                           # mazo vacio: agotamiento por el mismo camino que el del bot
            self.game.draw(self.human)
            self._announce_exhaustion(hp0, alive0)
            self.say("Maniobra: tu mazo esta vacio, no robas. Mueve tus miniaturas (puedes potenciar descartando "
                     "una carta) y pulsa Fin de accion.", ChatKind.YOUR_TURN)
            return
        self._deal_maneuver_card(st)

    def _deal_maneuver_card(self, st) -> None:
        """Reparte la carta de la Maniobra del mazo del humano a su mano, en el mismo compuesto que el boton. Solo
        cuenta cartas: nunca lee cuales tiene el humano. Un reparto fallido no se repite (la carta la roba el humano
        a mano y el motor se ajusta a la cuenta de la mano en la siguiente lectura)."""
        c = self.cfg
        before, discarded = len(st.hand), len(st.discard)
        try:
            script = lua.deal_cards(c.human_deck_guid, 1, c.human_seat, spot=c.human_deck_spot,
                                    id_range=c.human_card_ids, identity=self._identity("human"))
        except TABLE_ERRORS as e:
            self.say(f"No he podido darte la carta de la Maniobra ({e}). Roba tu carta a mano y pulsa Fin de accion.", ChatKind.WARNING)
            return
        try:
            op = self._w(script, "cards")
        except TABLE_ERRORS as e:             # la respuesta puede llegar tarde con la carta ya repartida
            self.say(f"No he podido confirmar el reparto de tu carta ({e}): mira tu mano; si no tienes la carta nueva, "
                     "roba a mano y pulsa Fin de accion.", ChatKind.WARNING)
            return
        drawn = self.game.draw(self.human)
        self.say("Maniobra: te he dado 1 carta. Mueve tus miniaturas (puedes potenciar descartando una carta) y "
                 "pulsa Fin de accion", ChatKind.YOUR_TURN)

        def check() -> bool:
            try:
                dealt = (op.result or {}).get("dealt")
            except TABLE_ERRORS:
                self.say("No he podido confirmar el reparto de tu carta: mira tu mano. Roba tu carta a mano si no "
                         "tienes la nueva.", ChatKind.WARNING)
                self._deal_check = None
                return False
            if dealt != 1:
                for card in drawn:
                    if card in st.hand:
                        st.hand.remove(card)
                        st.deck.insert(0, card)
                        self.game.drawn[self.human] = max(0, self.game.drawn[self.human] - 1)
                self.say("No he podido darte la carta. Roba tu carta a mano y pulsa Fin de accion.", ChatKind.WARNING)
                self._deal_check = None
                return False
            self._deal_check = (before, discarded)
            return True
        self._post.append(check)

    def _verify_maneuver_deal(self, real: int, discard_now: int) -> None:
        """En la siguiente instantanea la mano del humano ha de haber subido 1 (descontando lo que haya jugado o
        descartado desde entonces); si no, se avisa una vez y no se reparte otra vez."""
        chk, self._deal_check = self._deal_check, None
        if chk is None:
            return
        before, discarded = chk
        if real >= before + 1:
            return
        played = max(0, discard_now - discarded) + len(self._rd_face("human"))
        if real + played < before + 1:
            self.say("La carta de la Maniobra no ha llegado a tu mano. Roba tu carta a mano.", ChatKind.WARNING)

    def _announce_exhaustion(self, hp0: dict[str, float], alive0: dict[str, bool]) -> None:
        """Robar con el mazo vacio hace dano a todos: se anuncia y se escribe igual que cualquier otro dano."""
        g = self.game
        hurt = [f for fid, f in g.fighters.items() if f.hp != hp0[fid]]
        if not hurt:
            return
        self.say("Mazo vacio: " + self._hp_text(hp0).removeprefix("PV: ") + ".", ChatKind.COMBAT)
        for f in hurt:
            if alive0[f.fid] and not f.alive:
                self._announce_fall(f)
        if g.winner is not None:
            self.say(f"Fin de partida: gana el jugador {g.winner}. Si ha sido un error de PV, corrige con +1 "
                     "o pulsa Deshacer fin de partida.")
        self._write_dials(post=True)
        self._drop_pending_if_gone()

    def _scheme(self, _: dict) -> None:
        if not self._require_human_turn():
            return
        self._begin_action()
        self.game.use_action()
        self.moving = True
        self.scheme_baseline = [c.card_id for c in self.game.players[self.human].discard]
        if self._resolve_human_scheme(wait=not self.cfg.batch):
            self.say("Pulsa Fin de accion cuando termines.", ChatKind.YOUR_TURN)
        else:
            self.say("Plan: deja tu carta de plan boca arriba en tu descarte; la reconozco sola y aplico lo que no "
                     "necesite eleccion tuya. Pulsa Fin de accion cuando termines.", ChatKind.YOUR_TURN)

    def _resolve_human_scheme(self, wait: bool) -> bool:
        """Espera (acotado) a que la carta de plan del humano aparezca boca arriba en su descarte, la identifica por
        el CardID de la mesa y aplica lo que no necesita eleccion del humano. True si encontro la carta."""
        base = set(self.scheme_baseline or [])
        found: list[Card] = []

        def seen() -> bool:
            self.sync_human()
            found[:] = [c for c in self.game.players[self.human].discard if c.card_id not in base and c.is_scheme]
            return bool(found)
        if not (self._settle(seen) if wait else seen()):
            return False
        self.scheme_baseline = None
        crown = [c for c in found if c.title == CROWN]
        if crown:                                 # Crown descarta la mano: lo demas que aparece no es un plan jugado
            found[:] = crown[:1]
        for c in found:
            self._apply_human_scheme(c)
        self._write_dials(post=True)
        return True

    def _apply_human_scheme(self, c: Card) -> None:
        g = self.game
        if c.title == CROWN:
            g.grant_actions(2)
            self.say(f"Detecto {c.title}: aplicado, ganas 2 acciones (te quedan {g.actions_left}). Descartar tu mano "
                     "y robar 2 cartas lo haces tu: son tus cartas.", ChatKind.SCHEME)
        elif c.title == FIGHT_OR_FLIGHT:
            old = g.add_combat_bonus(self.human, FIGHT_OR_FLIGHT_BONUS, FIGHT_OR_FLIGHT)
            if old is not None:
                self.say(f"{c.title} reemplaza a {old}: solo hay un ONGOING activo por jugador.", ChatKind.SCHEME)
            total = g.combat_bonus_total(self.human)
            self.say(f"Detecto {c.title}: +{FIGHT_OR_FLIGHT_BONUS} a tus cartas de combate hasta el inicio de tu siguiente "
                     f"turno (ahora +{total}). Robar 1 y mover hasta 5 lo haces tu en la mesa; descarta el plan al "
                     "empezar tu siguiente turno.", ChatKind.SCHEME)
        elif c.title == "Pancakes!":
            self.say(f"Detecto {c.title}: tienes que elegir dos efectos. Para curar a {g.hero(self.human).name} 2 pulsa su +1 dos veces; "
                     "el mazo y el robo los haces tu en la mesa.", ChatKind.SCHEME)
        elif scheme_gain_actions(c):
            n = scheme_gain_actions(c)
            g.grant_actions(n)
            self.say(f"Detecto {c.title}: ganas {n} accion{'es' if n != 1 else ''}, te quedan {g.actions_left}; "
                     f"lo demas lo resuelves tu: {c.text} Usa +1 / -1 para los PV.", ChatKind.SCHEME)
        else:
            self.say(f"Detecto {c.title}: {c.text} Resuelvelo a mano; usa +1 / -1 para los PV.", ChatKind.SCHEME)

    def _value(self, payload: dict) -> None:
        raw = payload.get("value")
        if raw is None:
            raw = 0
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or abs(raw) > 100:
            self.say("Valor no valido: escribe un numero entre -100 y 100.", ChatKind.WARNING)
            return
        if self.pending is None:
            self.say("No hay combate pendiente: el valor extra solo vale antes de Revelar, en el combate en curso.", ChatKind.WARNING)
            return
        if self.pending.wait is not None:
            self.say("El boost se lee de tu descarte al pulsar Continuar: no hace falta escribir un valor.", ChatKind.WARNING)
            return
        self.pending_value = int(raw)
        self.say(f"Valor extra registrado: {self.pending_value}")

    def _choose_attacker(self, payload: dict) -> None:
        if not self._require_human_turn():
            return
        fid = str(payload.get("attacker", "")).removeprefix("att_")
        f = self.game.fighters.get(fid)
        if f is not None and f.owner == self.human and not f.alive:
            self.say(f"{self._name(f)} esta muerto: no puede atacar.", ChatKind.WARNING)
            return
        if f is None or f.owner != self.human:
            self.say(f"Atacante no valido: {payload.get('attacker')!r}.", ChatKind.WARNING)
            return
        self._try_flush_table()
        self.sync_positions()                     # lo movido fuera de una accion (Wildfire al empezar el turno) cuenta ya
        self.chosen_attacker = fid
        self.say(f"Ataca {fid}: elige el objetivo.", ChatKind.YOUR_TURN)

    def _attack(self, payload: dict) -> None:
        if not self._require_human_turn():
            return
        if self.chosen_attacker is None:
            who = " / ".join(f"Ataca {self._name(f)}" for f in self.game.own(self.human))
            self.say(f"Elige primero quien ataca ({who}).", ChatKind.WARNING)
            return
        target = self.game.fighters.get(str(payload.get("target", "")))
        if target is None or target.owner != self.bot or not target.alive:
            self.say(f"Objetivo no valido: {payload.get('target')!r}.", ChatKind.WARNING)
            return
        self._begin_action()
        if self.pending is not None:              # una jugada con respuesta tardia: la carta ya esta en la mesa
            if not self.pending.defended:
                self.say("Ya hay un ataque abierto: pon tu carta de ataque boca abajo y pulsa Revelar (o Cancelar).", ChatKind.WARNING)
            else:
                self.say("La carta del bot ya esta en la mesa: pulsa Revelar.", ChatKind.WARNING)
            return
        attacker = self.game.fighters[self.chosen_attacker]
        if not self.game.can_attack(attacker, target):
            self.chosen_attacker = None
            raise RuleError(f"{attacker.fid} no alcanza a {target.fid}")
        self.pending = Pending("human_attacks", attacker, target, None, None, defended=False)
        self.chosen_attacker = None
        self.say(f"{attacker.fid} ataca a {target.fid}: pon tu carta de ataque boca abajo en tu zona de combate "
                 "y pulsa Revelar.", ChatKind.YOUR_TURN)

    def _bot_defends(self, p: Pending) -> None:
        """El bot decide y coloca su defensa DESPUES de que el humano se haya comprometido. La decision usa solo lo
        que la IA ya sabia (estado del motor y mano del bot): jamas el CardID de la carta boca abajo del humano."""
        self.read_bot_hand()
        card = self.ai.choose_defense(self.game, p.attacker, p.target)
        guid = self._place_bot_card(card, "human_attacks", p.attacker, p.target)
        p.bot_card, p.bot_card_guid, p.defended = card, guid, True

    def _cancel(self, _: dict) -> None:
        """Salida de emergencia de cualquier estado pendiente del humano.

        Ataque del humano sin resolver: devuelve la carta del bot a su mano (tras dos intentos fallidos se
        abandona y se pide colocarla a mano). Descarte pendiente: se anula (la mesa se resincroniza sola).
        Mesa del bot sucia (deuda sin saldar): se adopta lo que muestra la mesa. Un ataque del bot no se
        cancela: se revela, sin carta si el humano no tiene defensa. Una carta puesta cuya respuesta llego tarde
        (`placing`) se resuelve primero: si aterrizo pasa a ser el ataque pendiente y se devuelve como cualquier otra."""
        if self.look is not None:
            self._look_close()
            return
        if self.placing is not None:
            self._recover_placing()
        if self._drop_pending_if_gone():
            return
        p = self.pending
        if p is not None and p.wait is not None:
            if p.wait.extra["stuck"]:
                self._cancel_stuck_boost(p)
                return
            self.say("Las cartas ya estan giradas: no se puede cancelar. Pulsa Continuar (con tu carta de boost en el "
                     "descarte) o Sin boost.", ChatKind.WARNING)
            return
        if p is not None and p.kind != "human_attacks":
            self.say("No se puede cancelar un ataque del bot: revela (sin carta si no tienes defensa).", ChatKind.WARNING)
            return
        if p is not None:
            self._return_bot_card(p)
            self.pending, self.pending_value, self.chosen_attacker = None, 0, None
            self.say("Ataque cancelado: la accion no se ha gastado.")
            return
        if self.pending_discard is not None:
            self.limit_waived = self.pending_discard["kind"] == "limit"
            self.pending_discard = None
            self.say("Descarte pendiente anulado: la mesa manda y se sincroniza en el proximo Fin de accion.")
            return
        if self.dirty or self.unprojected is not None or self.flush_failures:
            self.adopt_table()
            return
        if self.chosen_attacker is not None or self.pending_value:
            self.pending_value, self.chosen_attacker = 0, None
            self.say("Seleccion de atacante y valor extra borrados.")
            return
        self.say("No hay nada que cancelar.", ChatKind.WARNING)

    def _return_bot_card(self, p: Pending) -> None:
        if not p.bot_card_guid:
            return
        try:
            res = self._w(lua.return_card_to_hand(p.bot_card_guid, self.cfg.bot_seat), "cards").result or {}
            want = p.bot_card.card_id
            if not res.get("returned"):
                raise SessionError("no pude devolver la carta del bot a su mano; repite Cancelar ataque")
            if not self._settle(lambda: want in self._table_hand_ids()):
                raise SessionError("la carta del bot no ha vuelto a su mano; repite Cancelar ataque")
        except TABLE_ERRORS:
            p.cancel_failures += 1
            if p.cancel_failures < 2:
                raise
            self.say(f"No he podido devolver {p.bot_card.title} a la mano del bot: ponla tu en su mano.", ChatKind.WARNING)
        self.read_bot_hand()

    def _reveal(self, _: dict) -> None:
        p = self.pending
        if p is None:
            self.say("No hay combate pendiente.", ChatKind.WARNING)
            return
        if self._drop_pending_if_gone():
            return
        if p.wait is not None:              # con las cartas ya giradas no hay nada boca abajo que buscar
            self.say(self._boost_prompt(p), ChatKind.YOUR_TURN)
            return
        if self.placing is not None:              # defensa puesta cuya respuesta llego tarde: no se pone dos veces
            self._recover_placing()
            p = self.pending
        g = self.game
        seen = self._rd_face("human")
        mine = {c.card_id: c for c in g.players[self.human].full_set}
        theirs = [r for r in seen if r["id"] in mine]  # por propiedad del CardID, nunca por orden
        if len(theirs) > 1:
            self.say(f"Hay {len(theirs)} cartas tuyas boca abajo en la zona: deja solo una y pulsa Revelar.", ChatKind.WARNING)
            return
        human_card = mine[theirs[0]["id"]] if theirs else None
        try:
            if p.kind == "human_attacks":
                if human_card is None:
                    raise RuleError("no hay ninguna carta tuya boca abajo en la zona de combate")
                g.check_attack_card(p.attacker, human_card)
                if not p.defended:
                    self._bot_defends(p)
                if p.bot_card:
                    g.check_defense_card(p.target, p.bot_card)
            else:
                g.check_attack_card(p.attacker, p.bot_card)
                if human_card:
                    g.check_defense_card(p.target, human_card)
        except RuleError as e:
            self.say(f"Carta ilegal: {e}. Cambiala o dale la vuelta y pulsa Revelar otra vez.", ChatKind.WARNING)
            return
        human_guid = theirs[0]["guid"] if theirs else None
        if p.kind == "human_attacks" and human_card is not None and can_boost(human_card):
            if p.bot_card is not None and is_medusa_card(p.bot_card) and p.bot_card.title == FEINT:
                self.say(f"{p.bot_card.title} cancela los efectos de {human_card.title}: no hay boost que jugar.", ChatKind.COMBAT)
            else:
                self._await_boost(p, human_card, human_guid)
                return
        self._resolve_combat(p, human_card, human_guid, flip=True, boost=None)

    def _await_boost(self, p: Pending, card: Card, guid: str | None) -> None:
        """Se giran las dos cartas y el combate queda a medias: el BOOST se juega DESPUES de revelar. Salida:
        Continuar (lee la carta nueva del descarte) o Sin boost; Cancelar ya no vale con las cartas giradas."""
        own = {c.card_id for c in self.game.players[self.human].full_set}
        baseline = sorted({r["id"] for r in self._rd_human_discard()} & own)
        cards = [(p.bot_card_guid, "bot"), (guid, "human")]
        self._flip_all(cards)
        self._flip_queued(cards)
        p.wait = PendingChoice("boost", self.human, card.card_id, deck_boost(card),
                               {"guid": guid, "baseline": baseline, "hand": self._rd_human_count(-1), "stuck": False})
        if p.wait.deck:
            self.say(f"{card.title} revelado: pon la carta del FONDO de tu mazo en tu descarte y pulsa Continuar (Sin "
                     "boost si tu mazo esta vacio). Si es ardiente, recogela despues: Wildfire la devuelve a tu mano.",
                     ChatKind.YOUR_TURN)
        else:
            self.say(f"{card.title} revelado: si quieres potenciar, pon una carta de tu mano en tu descarte y pulsa "
                     "Continuar (o Sin boost).", ChatKind.YOUR_TURN)

    def _boost(self, _: dict) -> None:
        self._finish_boost(True)

    def _no_boost(self, _: dict) -> None:
        self._finish_boost(False)

    def _boost_prompt(self, p: Pending) -> str:
        if p.wait.extra["stuck"]:
            return ("El combate no se pudo resolver con la mesa actual: corrige la posicion o la carta y pulsa "
                    "Continuar o Sin boost, o pulsa Cancelar para deshacerlo (las cartas vuelven a quedar boca abajo).")
        if p.wait.deck:
            return ("Las cartas ya estan reveladas: pon la carta del fondo de tu mazo en el descarte y pulsa "
                    "Continuar, o pulsa Sin boost.")
        return ("Las cartas ya estan reveladas: pon tu carta de boost en el descarte y pulsa Continuar, "
                "o pulsa Sin boost.")

    def _finish_boost(self, use: bool) -> None:
        p = self.pending
        if p is None or p.wait is None:
            self.say("No hay ningun boost pendiente.", ChatKind.WARNING)
            return
        if self._drop_pending_if_gone():
            return
        mine = {c.card_id: c for c in self.game.players[self.human].full_set}
        card, boost = mine[p.wait.card_id], None
        if use:
            seen = {r["id"] for r in self._rd_human_discard() if r["id"] in mine}
            new = sorted(seen - set(p.wait.extra["baseline"]) - {card.card_id})
            if not new:
                self.say("No veo ninguna carta nueva en tu descarte: ponla y pulsa Continuar, o pulsa Sin boost.", ChatKind.WARNING)
                return
            if len(new) > 1:
                self.say(f"Hay {len(new)} cartas nuevas en tu descarte ({', '.join(mine[i].title for i in new)}): "
                         "deja solo la del boost y pulsa Continuar.", ChatKind.WARNING)
                return
            before, now = p.wait.extra["hand"], self._rd_human_count(-1)
            if p.wait.deck:          # Flame Lash: sale del fondo del mazo, la mano no cambia
                before = -1
            if isinstance(before, int) and before >= 0 and now >= 0 and now != before - 1:
                self.say(f"El boost tiene que salir de tu mano: tenias {before} cartas y ahora tienes {now} "
                         f"(deberian ser {max(before - 1, 0)}). Corrigelo y pulsa Continuar, o pulsa Sin boost.", ChatKind.WARNING)
                return
            boost = mine[new[0]]
            if not p.wait.deck and not can_be_boost(boost):
                self.say(f"{boost.title} no tiene valor de impulso: no cuenta. Quita esa carta del descarte y pon otra "
                         "con valor de impulso, o pulsa Sin boost.", ChatKind.WARNING)
                return
        self.sync_positions()                     # la mesa manda: algo pudo moverse mientras se esperaba
        self._resolve_combat(p, card, p.wait.extra["guid"], flip=False, boost=boost)
        if self.pending is p and p.wait is not None:
            p.wait.extra["stuck"] = True          # el motor lo rechazo: Cancelar pasa a ser la salida

    def _cancel_stuck_boost(self, p: Pending) -> None:
        """Salida del combate atascado tras revelar: las dos cartas vuelven a quedar boca abajo, la del bot a su mano
        y la accion no se gasta. La carta tuya la recoges tu."""
        self._unflip([(p.bot_card_guid, "bot"), (p.wait.extra["guid"], "human")])
        self._return_bot_card(p)
        self.pending, self.pending_value, self.chosen_attacker = None, 0, None
        self.say("Combate cancelado: la accion no se ha gastado. Recoge tu carta de la zona de combate.")

    def _resolve_combat(self, p: Pending, human_card: Card | None, human_guid: str | None, flip: bool,
                        boost: Card | None) -> None:
        g = self.game
        hst = g.players[self.human]
        guess = (list(hst.hand), list(hst.deck), list(hst.discard))
        known_before = [pl.known.copy() for pl in g.players]      # un combate fallido no descuenta cartas vistas
        flip_cards = [(p.bot_card_guid, "bot"), (human_guid, "human")]
        flipped = self._flip_all(flip_cards) if flip else []
        value = self.pending_value
        before = self._snapshot_bot()
        alive_before = {fid: f.alive for fid, f in g.fighters.items()}
        bot_seen = len(g.players[self.bot].discard)
        try:
            if human_card is not None:
                self._make_known(human_card)
                self._transit[human_card.card_id] = 0
            if boost is not None:
                self._make_known(boost, keep=(human_card,))
            if p.kind == "human_attacks":
                res = g.attack(p.attacker, p.target, human_card, p.bot_card, values=(value, 0), boost=boost)
            else:
                res = g.attack(p.attacker, p.target, p.bot_card, human_card, values=(0, value))
        except RuleError as e:
            hst.hand[:], hst.deck[:], hst.discard[:] = guess
            for pl, kn in zip(g.players, known_before):
                pl.known = kn
            if human_card is not None:
                self._transit.pop(human_card.card_id, None)
            self._unflip(flipped)
            if p.wait is not None:
                self.say(f"No se puede resolver el combate: {e}. Corrige la mesa y pulsa Continuar o Sin boost "
                         "otra vez, o pulsa Cancelar para deshacerlo.", ChatKind.WARNING)
            else:
                self.say(f"Carta ilegal: {e}. Cambiala y pulsa Revelar otra vez.", ChatKind.WARNING)
            return
        discarded_now = p.bot_card is not None and p.bot_card in g.players[self.bot].discard
        if flip:
            self._flip_queued([(None if discarded_now and side == "bot" else guid, side) for guid, side in flip_cards])
        self.pending, self.pending_value, self.chosen_attacker = None, 0, None
        if self.pending_discard is not None:      # antes de cualquier E/S: un fallo de mesa no puede dejarlo sin base
            self.pending_discard["baseline"] = len(g.players[self.human].discard)
        self._mark_dirty(before)
        self.say(self._combat_text(p, res), ChatKind.COMBAT)
        reasons = {}
        for c, why in ((res.atk_card, "ataque"), (res.def_card, "defensa")):
            if c is not None and c in g.players[self.bot].full_set:
                reasons[c.card_id] = why
        if res.boost_card is not None and res.boost_card in g.players[self.bot].full_set:
            reasons[res.boost_card.card_id] = "boost de combate"
        listed = self._discard_list(bot_seen, reasons, "efecto")
        if listed:
            self.say(f"El bot descarta {listed}.")
        for e in res.applied:
            self.say(f"Aplicado: {e}", ChatKind.WARNING)
        for e in res.bot_notes:
            self.say(e, ChatKind.WARNING)
        for e in res.human_effects:
            self.say(f"Resuelve a mano: {e}", ChatKind.WARNING)
        for fid, was in alive_before.items():
            f = g.fighters[fid]
            if was and not f.alive and f.owner == self.human:    # las del bot las retira _project
                self._announce_fall(f)
        self._track_destiny()
        fin_dials = self._write_dials(defer=True)
        fin_table = self._try_flush_stage()
        fin_dials()
        fin_table()
        if g.winner is not None:
            self.say(f"Fin de partida: gana el jugador {g.winner}.")
            return
        self.moving = True
        self.say("Resuelve los efectos de despues del combate (mover piezas, descartar) y pulsa Fin de accion.", ChatKind.YOUR_TURN)

    def _combat_text(self, p: Pending, res) -> str:
        """Cuenta de donde sale cada total: carta jugada, bonos y carta de impulso, con sus titulos."""
        a, t = self._name(p.attacker), self._name(p.target)
        atk = f"{a} ataca con {res.atk_parts[0]}" + "".join(
            f" y {part}" if i == 0 else f", {part}" for i, part in enumerate(res.atk_parts[1:]))
        if res.def_card is None:
            dfn = f"{t} no defiende"
        else:
            dfn = f"{t} defiende con {res.def_parts[0]}" + "".join(f", {part}" for part in res.def_parts[1:])
        return f"Combate: {atk}: total {res.atk_value}. {dfn}: total {res.def_value}. Dano {res.damage}."

    def _track_destiny(self) -> bool:
        """Cuenta los destinos de Hellboy en su descarte (el motor los iguala al descarte de la mesa en sync_human),
        anuncia cuando cambian y cuando cambia la forma. True si el dial aun no refleja la cuenta: `destiny_seen`
        solo avanza tras una escritura verificada (`_write_dials`), asi un fallo se reintenta en la siguiente lectura."""
        g = self.game
        if "destiny" not in g.hero_def(self.human).counters:
            return False                          # solo el heroe con contador de destinos (Hellboy) los lleva
        now = (g.destiny_count(self.human), g.form(self.human))
        said = self._destiny_said if self._destiny_said is not None else self.destiny_seen
        prev, self._destiny_said = said, now
        if not self.cfg.destiny_dial:
            self.destiny_seen = now               # sin dial no hay nada que verificar
        if prev != now:
            self._announce_destiny(prev, now)
        return now != self.destiny_seen

    def _announce_destiny(self, prev: tuple[int, str] | None, now: tuple[int, str]) -> None:
        if prev is not None and prev[0] != now[0]:
            self.say(f"Destinos de Hellboy: {now[0]} (antes {prev[0]})." if now[0] < prev[0]
                     else f"Destinos de Hellboy: {now[0]} (en su descarte).", ChatKind.ABILITY)
        if prev is not None and prev[1] != now[1]:
            if now[1] == ANUNG:
                self.say(f"Hellboy pasa a ANUNG UN RAMA ({now[0]} destinos, 6 o mas): dale la vuelta a su miniatura "
                         "(cambia de GUID, el bot ya lo reconoce). Sus ataques suman +2 y al empezar tu turno "
                         "descartas 1 carta y mueves hasta su BOOST.", ChatKind.ABILITY)
            else:
                self.say(f"Hellboy vuelve a OCCULT DETECTIVE ({now[0]} destinos): devuelvele su miniatura a la forma "
                         "normal.", ChatKind.ABILITY)

    def _write_dials(self, only_destiny: bool = False, defer: bool = False, post: bool = False):
        """Escribe los diales (ver `_put_dials`). Todo fallo, venga de donde venga, deja la deuda `dial_debt`: el
        turno del bot lo convierte en una pausa (`_pause_for_dials`) y `_bot_continue` la salda. Una escritura
        verificada de los diales de vida la cancela. Con `defer` devuelve la funcion que verifica (en modo rapido
        la comprobacion comparte mensaje con las demas escrituras pendientes); con `post` la comprobacion espera al
        cierre del boton (`_commit`) y comparte su mensaje: solo para quien no necesita el resultado."""
        verify = self._put_dials(only_destiny)

        def done() -> bool:
            ok = verify()
            if not ok:
                self.dial_debt = True
            elif not only_destiny:
                self.dial_debt = False
            return ok
        if post and self.cfg.batch:
            self._post.append(done)
            return True
        if not defer:
            return done()
        if self.cfg.batch:
            return done
        ok = done()
        return lambda: ok

    def _put_dials(self, only_destiny: bool) -> Callable[[], bool]:
        """El motor manda: los diales de vida se ponen a la vida del motor y se relee la mesa para comprobarlo.
        Escribe (o encola) y devuelve la funcion que comprueba: True si quedaron verificados (o no habia nada).

        Un dial que el humano toco a mano (no marca lo ultimo que escribio el motor ni lo que toca ahora) NO se
        pisa: se avisa y no se escribe nada; el humano lo reconcilia con +1 / -1 (el motor cuenta) o devolviendolo.
        Es la opcion segura: ni se pierde su correccion ni un dial puede cambiar el estado del motor."""
        if not self.cfg.destiny_dial and (only_destiny or not self.cfg.dials):
            return lambda: True
        g = self.game
        dials = {} if only_destiny else self.cfg.dials
        want = {guid: (max(0, math.ceil(g.fighters[fid].hp)) if g.fighters[fid].alive else 0)
                for fid, guid in dials.items()}
        label = {guid: self._name(g.fighters[fid]) for fid, guid in dials.items()}
        if self.cfg.destiny_dial:
            want[self.cfg.destiny_dial] = g.destiny_count(self.human)
            label[self.cfg.destiny_dial] = "el dial de destinos"
        try:
            now = self._rd_dials(sorted(want))
            touched = [gd for gd, v in want.items() if self._hand_edited(gd, v, now)]
            if touched:
                self.say("No toco " + "; ".join(f"{label[gd]} (marca {now[gd]['value']:g}, el motor {want[gd]})"
                                                for gd in touched)
                         + ": parece cambiado a mano. "
                         + " ".join(f"Pon {label[gd]} en {want[gd]} si el motor tiene razon; usa +1/-1 si el dial "
                                    "tiene razon." for gd in touched), ChatKind.WARNING)
                for gd in touched:                # solo ese dial se respeta: los demas se escriben y se comprueban
                    del want[gd]
            if want:
                self.dials_attempted.update(want)
                self._w(lua.set_health_dials(want), "dials")
                if self.cfg.batch:
                    self._dials_pending |= set(want)
        except TABLE_ERRORS as e:
            self.say(f"No pude actualizar los diales de vida ({e}); corrigelos a mano.", ChatKind.WARNING)
            return lambda: False

        def verify() -> bool:
            self._dials_pending -= set(want)
            if not want:
                return not touched
            seen: dict = {}

            def matches() -> bool:
                res = self._rd_dials(sorted(want))
                seen.update(res if isinstance(res, dict) else {})
                return all(isinstance((seen.get(gd) or {}).get("value"), (int, float))
                           and seen[gd]["value"] == v for gd, v in want.items())
            try:
                if not self._settle(matches):
                    bad = [f"{label[gd]} deberia marcar {want[gd]}" for gd in want
                           if (seen.get(gd) or {}).get("value") != want[gd]]
                    self.say("No pude comprobar los diales de vida: " + "; ".join(bad) + ". Corrigelos a mano.", ChatKind.WARNING)
                    return False
            except TABLE_ERRORS as e:
                self.say(f"No pude actualizar los diales de vida ({e}); corrigelos a mano.", ChatKind.WARNING)
                return False
            self.dials_written.update(want)
            if self.cfg.destiny_dial in want:
                self.destiny_seen = (want[self.cfg.destiny_dial], g.form(self.human))
            return not touched
        return verify

    def _hand_edited(self, guid: str, want: int, now) -> bool:
        """El dial marca algo que ni es lo ultimo que escribio el motor ni lo que toca escribir ahora."""
        value = (now.get(guid) or {}).get("value") if isinstance(now, dict) else None
        last = self.dials_written.get(guid)
        tried = self.dials_attempted.get(guid)
        return isinstance(value, (int, float)) and last is not None and value not in (last, want, tried)

    def _pause_for_dials(self) -> None:
        """Un dial no se pudo escribir en pleno turno del bot: se para aqui (el estado ya esta guardado) y se pide al
        humano que lo ponga; Fin de accion retoma el turno. Nunca se sigue en silencio."""
        self.dial_debt = True
        self._persist()
        self.say("Turno del bot en pausa: pon a mano los diales indicados arriba y pulsa Fin de accion para que siga.", ChatKind.WARNING)

    def _hp_text(self, before: dict[str, float], skip: str | None = None) -> str:
        """Cambios de PV desde `before`: 'Lobster Johnson de 6 a 3'. (ASCII: los mensajes tambien salen por broadcast.)"""
        g = self.game
        parts = [f"{self._name(f)} de {before[fid]:g} a {max(f.hp, 0):g}" for fid, f in g.fighters.items()
                 if fid != skip and fid in before and f.hp != before[fid]]
        return "PV: " + ", ".join(parts) if parts else ""

    def _flip_script(self, guid: str, side: str, face_up: bool = True) -> str:
        ids = self.cfg.bot_card_ids if side == "bot" else self.cfg.human_card_ids
        return lua.flip_card(guid, self.cfg.rot_y, face_up, ids, identity=self._identity(side))

    def _flip_all(self, cards: list[tuple[str | None, str]]) -> list[tuple[str, str]]:
        """Gira las cartas (guid, bando); si una falla se vuelven a ocultar las ya giradas antes de propagar el error.
        En modo rapido no se gira aqui: `_flip_queued` las encola cuando el motor ya acepto el combate."""
        flipped: list[tuple[str, str]] = []
        if self.cfg.batch:
            return flipped
        try:
            for guid, side in cards:
                if guid:
                    self._w(self._flip_script(guid, side), "flip")
                    flipped.append((guid, side))
        except Exception:
            self._unflip(flipped)
            raise
        return flipped

    def _flip_queued(self, cards: list[tuple[str | None, str]]) -> None:
        if self.cfg.batch:
            for guid, side in cards:
                if guid:
                    self._w(self._flip_script(guid, side), "flip")

    def _unflip(self, cards: list[tuple[str | None, str]]) -> None:
        for guid, side in cards:
            if not guid:
                continue
            try:
                self._w(self._flip_script(guid, side, face_up=False), "flip").result
            except TABLE_ERRORS:
                self.say("No pude volver a ocultar una carta: giala boca abajo a mano.", ChatKind.WARNING)

    def _end_action(self, _: dict) -> None:
        if self.look is not None:
            self._look_close(face_down=True)
            return
        if self.pending is not None and not self._drop_pending_if_gone():
            self.say("Termina primero el boost: pulsa Continuar o Sin boost." if self.pending.wait is not None
                     else "Revela primero el combate en curso.", ChatKind.WARNING)
            return
        if self.game.winner is not None:
            self.say("La partida ha terminado (Deshacer fin de partida si es un error de PV).", ChatKind.WARNING)
            return
        self._flush_table()                       # si el ultimo intento fallo, se reintenta antes que nada
        if self.pending is not None:              # la carta jugada con respuesta tardia aparecio en la mesa
            self.say("La carta del bot ya esta en la mesa: pulsa Revelar.", ChatKind.WARNING)
            return
        self.sync_positions()
        self.sync_human()
        if self.scheme_baseline is not None and not self._resolve_human_scheme(wait=False):
            self.say("No he visto ninguna carta de plan nueva en tu descarte: resuelve el plan a mano.", ChatKind.WARNING)
        self.scheme_baseline = None
        self._check_dials()
        self.moving = False
        if self.pending_discard is not None and not self._discard_done():
            return
        self.pending_discard = None
        if self.game.turn == self.bot:
            self._bot_continue()
        else:
            self._after_human_action()

    # ---------- PV y bajas por efectos (el motor no los ve) ----------
    def _fighter_arg(self, payload: dict) -> Fighter | None:
        f = self.game.fighters.get(str(payload.get("fighter", "")))
        if f is None:
            self.say(f"Luchador no valido: {payload.get('fighter')!r}.", ChatKind.WARNING)
        return f

    def _name(self, f: Fighter) -> str:
        return self.cfg.nicknames.get(f.fid, f.fid)

    def _sidekicks(self) -> list[Fighter]:
        """Los luchadores del humano que coloca el, no el bot (todos menos su heroe)."""
        return [f for f in self.game.own(self.human, alive_only=False) if not f.hero]

    def _sidekick_names(self) -> str:
        names = [self._name(f) for f in self._sidekicks()]
        return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1] if names else ""

    def _after_hp_change(self, f: Fighter) -> None:
        g = self.game
        if not f.alive:
            self._announce_fall(f)
        if g.winner is not None:
            self.say(f"Fin de partida: gana el jugador {g.winner}. Si ha sido un error de PV, corrige con +1 "
                     "o pulsa Deshacer fin de partida.")
        self._write_dials(post=True)
        self._drop_pending_if_gone()

    def _drop_pending_if_gone(self) -> bool:
        """Un combate pendiente cuyo atacante u objetivo ya no esta en juego (Retirar, PV, baja que el bot no vio)
        no se puede resolver ni hay carta legal que lo arregle: se cancela, la carta del bot vuelve a su mano y la
        accion no se gasta. Si la mesa falla al devolverla, el combate sigue y cualquier boton reintenta."""
        p = self.pending
        if p is None or (p.attacker.alive and p.target.alive):
            return False
        gone = p.attacker if not p.attacker.alive else p.target
        self._return_bot_card(p)
        self.pending, self.pending_value, self.chosen_attacker = None, 0, None
        self.say(f"Combate cancelado: {self._name(gone)} ya no esta en juego. La accion no se ha gastado.", ChatKind.WARNING)
        return True

    def _hp(self, payload: dict) -> None:
        """Ajuste manual de PV (dano o curacion de efectos de carta: Horseshoes, Posthumous Power, Pancakes!...)."""
        f = self._fighter_arg(payload)
        delta = payload.get("delta")
        if f is None:
            return
        if isinstance(delta, bool) or delta not in (1, -1):
            self.say(f"Ajuste de PV no valido: {delta!r} (solo +1 o -1).", ChatKind.WARNING)
            return
        g = self.game
        if delta < 0:
            if not f.alive:
                self.say(f"{self._name(f)} ya esta fuera.", ChatKind.WARNING)
                return
            g.damage(f, 1, "manual")
        elif f.alive:
            g.heal(f, 1)
        elif not self._revive(f):
            return
        self.say(f"{self._name(f)}: {f.hp:g} PV.", ChatKind.COMBAT)
        self._after_hp_change(f)

    def _remove(self, payload: dict) -> None:
        """Retira a un luchador muerto por un efecto (sin pasar por los +1/-1)."""
        f = self._fighter_arg(payload)
        if f is None:
            return
        if not f.alive:
            self.say(f"{self._name(f)} ya esta fuera.", ChatKind.WARNING)
            return
        self.game.damage(f, f.hp, "manual")
        self._after_hp_change(f)

    def _revive(self, f: Fighter, force: bool = False) -> bool:
        """Repone a un luchador dado por muerto (error de PV o de baja) en la casilla donde esta su miniatura."""
        info = self._table_pieces().get(f.fid) or {}
        buried = (f.owner == self.bot and f.died_at is not None and self.cfg.dead_spot is not None
                  and not self._on_board(info))      # la aparto el bot: vuelve a la casilla donde cayo
        if buried:
            taken = {o.pos for o in self.game.fighters.values() if o.alive and o is not f}
            pos = f.died_at if f.died_at not in taken else self.game.board.nearest_free(f.died_at, taken, f.died_at)
        elif self._on_board(info):
            pos = info["space"]
        elif force:
            pos = self.game.start_spaces[f.owner]
            self.say(f"Coloca a {self._name(f)} en la casilla {pos} (no esta en el tablero).", ChatKind.YOUR_TURN)
        else:
            self.say(f"No puedo reponer a {self._name(f)}: su miniatura no esta en el tablero. Colocala y repite.", ChatKind.WARNING)
            return False
        f.alive, f.hp, f.pos = True, 1, pos
        if f.hero and self.game.winner == 1 - f.owner:
            self.game.winner = None
        if buried:
            self._place_revived(f, self._name(f))
        return True

    def _undo_game_over(self, _: dict) -> None:
        g = self.game
        if g.winner is None:
            self.say("No hay fin de partida que deshacer.", ChatKind.WARNING)
            return
        g.winner = None
        for f in g.fighters.values():
            if f.hero and not f.alive:
                self._revive(f, force=True)
        self.say("Partida reabierta: los heroes caidos vuelven con 1 PV. Corrige los PV con +1 / -1.")
        self._write_dials(post=True)
        self._drop_pending_if_gone()

    def _check_dials(self) -> None:
        """Si hay diales de vida configurados, avisa de discrepancias con el motor (no cambia nada)."""
        if not self.cfg.dials:
            return
        try:
            guids = sorted(set(self.cfg.dials.values()) - self._dials_pending)   # los que se estan escribiendo, los verifica su escritura
            if self.cfg.batch and self.snap is not None:
                res = {g: (self.snap["dials"].get(g) or {"found": False}) for g in guids}   # sin forzar la cola
            else:
                res = self._rd_dials(guids)
        except (TTSLuaError, OSError):
            return
        if not isinstance(res, dict):
            return
        for fid, guid in self.cfg.dials.items():
            if guid in self._dials_pending:
                continue
            f, info = self.game.fighters[fid], res.get(guid) or {}
            value = info.get("value")
            if f.alive and isinstance(value, (int, float)) and value != f.hp:
                self.say(f"Aviso: el dial de {self._name(f)} marca {value:g} y el motor {f.hp:g}: "
                         "ajusta con +1 / -1 o corrige el dial.", ChatKind.WARNING)

    # ---------- descartes del humano ----------
    def _owe_discard(self, n: int, reason: str) -> None:
        d = self.pending_discard or {"n": 0, "baseline": len(self.game.players[self.human].discard), "kind": "cards"}
        d["n"] += n
        self.pending_discard = d
        self.say(f"Descarta {n} carta(s) ({reason}) y pulsa Fin de accion.{self._wildfire_hint()}", ChatKind.YOUR_TURN)

    def _human_wildfire(self) -> bool:
        """Liz (Wildfire): toda ardiente que el humano descarta de la mano vuelve a ella, asi que un descarte
        obligado puede no cambiar ni su descarte ni su mano en la mesa."""
        return any(p.get("effect") == "liz_wildfire_return_to_hand" for p in self.game.hero_def(self.human).passives)

    def _wildfire_hint(self) -> str:
        return (" Wildfire: deja la ardiente en tu descarte, pulsa Fin de accion y luego vuelve a cogerla (asi se"
                " cuenta y el bot sabe cual vuelve a tu mano)."
                if self._human_wildfire() else "")

    def _discard_done(self) -> bool:
        d, st = self.pending_discard, self.game.players[self.human]
        if d["kind"] == "limit":
            done = len(st.hand) <= HAND_LIMIT
        else:
            if d["baseline"] is None:
                d["baseline"] = len(st.discard)
            done = len(st.discard) >= d["baseline"] + d["n"]
        if not done and self._human_wildfire() and d.get("wildfire_asked"):
            # segunda vez: las ardientes volvieron a la mano sin pasar por el descarte de la mesa; se le cree
            if d["kind"] == "limit":
                known = self.game.players[self.bot].known.seen
                while len(st.hand) > HAND_LIMIT:        # al mazo primero las que el bot NO ha visto
                    spare = next((c for c in reversed(st.hand) if c.card_id not in known), st.hand[-1])
                    st.hand.remove(spare)
                    st.deck.append(spare)
            self.say("Wildfire: doy el descarte por hecho (las ardientes vuelven a tu mano).")
            return True
        if not done and self._human_wildfire():
            d["wildfire_asked"] = True
            self.say("Aun no veo el descarte en la mesa. Si descartaste ardientes que han vuelto a tu mano, pulsa "
                     "Fin de accion otra vez y lo doy por hecho.", ChatKind.WARNING)
            return False
        if not done:
            self.say(f"Aun falta descartar {d['n']} carta(s); lleva tambien al descarte las cartas ya jugadas.", ChatKind.WARNING)
        return done

    # ---------- turnos ----------
    def _after_human_action(self) -> None:
        g = self.game
        if g.winner is not None or g.turn != self.human:
            return
        if g.actions_left > 0:
            self.say(f"Te quedan {g.actions_left} accion(es).", ChatKind.YOUR_TURN)
            return
        hand = g.players[self.human].hand
        excess = len(hand) - HAND_LIMIT
        if excess > 0 and self.limit_waived:      # el humano anulo el descarte: el motor no se lo vuelve a exigir
            while len(hand) > HAND_LIMIT:
                g.players[self.human].deck.append(hand.pop())
        elif excess > 0:
            self.pending_discard = {"n": excess, "baseline": None, "kind": "limit"}
            self.say(f"Descarta {excess} carta(s) hasta tener {HAND_LIMIT} y pulsa Fin de accion "
                     f"(Cancelar ataque anula el descarte).{self._wildfire_hint()}", ChatKind.YOUR_TURN)
            return
        self.limit_waived = False
        self.chosen_attacker = None
        g.end_turn()
        g.begin_turn()                            # el cambio de turno es atomico; lo que sigue es solo E/S
        self.bot_stage = "start"
        self._persist()                           # punto de control: el turno del bot empieza aqui, una sola vez
        self.say("Fin de tu turno. Turno del bot.")
        self._bot_continue()

    def start_bot_turn(self) -> None:
        self.game.begin_turn()
        self.bot_stage = "start"
        self._persist()
        self._bot_continue()

    def _mark_dirty(self, before: dict | None = None) -> None:
        """El motor ya cambio al bot; hasta que la mesa lo refleje queda una deuda que cualquier boton reintenta."""
        self.dirty = True
        if before is not None and self.unprojected is None:
            self.unprojected = before

    def _flush_table(self) -> None:
        """Proyecta y reconcilia lo que el motor decidio para el bot. Idempotente: si falla, la deuda sigue.

        Tras `adopt_after` discrepancias seguidas entre mesa y motor (SessionError) la mesa gana: se adopta."""
        self._flush_table_stage()()

    def _flush_table_stage(self) -> Callable[[], None]:
        """Prepara (encola) el flush de la mesa y devuelve la funcion que lo comprueba. Asi, en modo rapido, los
        diales y las cartas comparten el mismo mensaje; sin `batch` todo ocurre ya y la funcion no hace nada."""
        checks: list[Callable[[], None]] = []
        try:
            self._recover_placing()
            if self.unprojected is not None:
                check = self._project_stage(self.unprojected)
                if self.cfg.batch:
                    checks += [check, self._forget_unprojected]
                else:
                    self.unprojected = None
            if self.dirty:
                checks.append(self._reconcile_stage())
                checks.append(self._forget_dirty)
        except SessionError:
            self._flush_failed()
            return lambda: None
        done = False

        def fin() -> None:
            nonlocal done
            if done:
                return
            done = True
            try:
                for c in checks:
                    c()
            except SessionError:
                self._flush_failed()
                return
            self.flush_failures = 0
        if self.cfg.batch:
            return fin
        fin()
        return lambda: None

    def _forget_unprojected(self) -> None:
        self.unprojected = None

    def _forget_dirty(self) -> None:
        self.dirty = False

    def _flush_failed(self) -> None:
        self.flush_failures += 1
        if self.flush_failures < self.cfg.adopt_after:
            raise
        self.adopt_table()

    def _card_on_spot(self, card_id: int) -> str | None:
        """GUID de la carta boca abajo con ese CardID en el punto de carta del bot, o None si la mesa no la muestra."""
        for r in self._rd_face("bot"):
            if r["id"] == card_id:
                return r["guid"]
        return None

    def _discard_list(self, seen: int, reasons: dict[int, str], default: str, skip: Card | None = None) -> str:
        """'Snipe por ataque, Dash por boost de combate': las cartas que el bot ha mandado al descarte desde que
        habia `seen` en la pila, en el orden en que quedan en la rejilla, cada una con su motivo."""
        return ", ".join(f"{c.title} por {reasons.get(c.card_id, default)}"
                         for c in self.game.players[self.bot].discard[seen:] if c is not skip)

    def _played_text(self, seen: int, reasons: dict[int, str], default: str, skip: Card | None = None) -> str:
        listed = self._discard_list(seen, reasons, default, skip)
        return f" (descarta {listed})" if listed else ""

    def _action_text(self, act, seen: int, before: dict, hp0: dict[str, float]) -> str:
        """Que ha hecho el bot, con el nombre de la carta jugada, el dano que hizo y a donde movio cada pieza."""
        g = self.game
        moved = [f"{self._name(g.fighters[fid])} a la casilla {g.fighters[fid].pos}"
                 for fid, (pos, was_alive) in before.items()
                 if was_alive and g.fighters[fid].alive and g.fighters[fid].pos != pos]
        if act.kind in ("glance", "frenzy"):
            title = act.card.title
            text = f"El bot juega {title}" + self._played_text(seen, {}, "efecto", skip=act.card)
            if act.kind == "glance":
                t = g.fighters[act.target]
                dealt = hp0[t.fid] - t.hp
                text += (f": {dealt:g} de dano a {self._name(t)} (PV de {hp0[t.fid]:g} a {max(t.hp, 0):g})"
                         if dealt else f": sin efecto sobre {self._name(t)} (dano de efectos evitado)")
        else:
            boost = {act.boost.card_id: "boost de maniobra"} if act.boost is not None else {}
            text = f"El bot hace {act.kind}" + self._played_text(seen, boost, "efecto")
        others = self._hp_text(hp0, skip=act.target if act.kind == "glance" else None)
        return (text + (f". Mueve {', '.join(moved)}" if moved else "") + (f". {others}" if others else "") + ".")

    def _recover_placing(self) -> None:
        """Una carta que el bot puso boca abajo y cuya respuesta no llego (timeout tras ejecutarse): si esta en su
        punto de carta cuenta como jugada y se retoma el combate; si no aparece, nunca salio de la mano."""
        it = self.placing
        if it is None:
            return
        found: dict = {}

        def on_spot() -> bool:
            found["guid"] = self._card_on_spot(it["card"])
            return found["guid"] is not None
        landed = self._settle(on_spot)
        self.placing = None
        if landed:
            card = next(c for c in self.game.players[self.bot].full_set if c.card_id == it["card"])
            fighters = self.game.fighters
            self.pending = Pending(it["kind"], fighters[it["attacker"]], fighters[it["target"]], card, found["guid"])
            self.read_bot_hand()
            self.say(f"{card.title} del bot ya estaba boca abajo en la mesa: la cuento como jugada. Pulsa Revelar.", ChatKind.WARNING)

    def _bot_continue(self) -> None:
        """Turno del bot reanudable: cada paso de E/S que falla deja el estado listo para repetir Fin de accion.

        Puntos de control (guardado en disco): al empezar el turno, tras la habilidad de Medusa y tras cada accion,
        de modo que un corte o Ctrl+C reanudado no repite nada de lo ya hecho."""
        g = self.game
        self._flush_table()
        if self.pending is not None:
            self.say("La carta del bot ya esta en la mesa: pulsa Revelar.", ChatKind.WARNING)
            return
        if self.dial_debt:                        # se retoma tras una pausa por un dial que no se pudo escribir
            self.dial_debt = False
            if not self._write_dials():
                self.say("Los diales siguen sin coincidir con el motor; sigo con el turno, revisalos.", ChatKind.WARNING)
        if self.bot_stage == "start":
            self.sync_positions()
            self.sync_human()
            self.read_bot_hand()
            target = self.ai.pick_ability_target(g) if self._bot_ability_coded() else None
            self.bot_stage = None
            if target:
                hp0, alive0 = target.hp, self._alive_map()
                g.medusa_ability(target)
                dials_ok = self._write_dials()        # primero el dial y su verificacion, luego el anuncio
                self.say(f"Habilidad de Medusa: 1 de dano a {self._name(target)} (PV de {hp0:g} a {max(target.hp, 0):g}).", ChatKind.ABILITY)
                self._announce_human_falls(alive0)
                self._persist()
                if not dials_ok:
                    self._pause_for_dials()
                    return
                self._bot_breath()
            self._persist()
        while g.actions_left > 0 and g.winner is None:
            with self._timed("accion del bot"):
                self.read_bot_hand()
                act = self.ai.plan(g)
                if act.kind == "attack":
                    attacker, target = g.fighters[act.fid], g.fighters[act.target]
                    guid = self._place_bot_card(act.card, "bot_attacks", attacker, target)
                    self.pending = Pending("bot_attacks", attacker, target, act.card, guid)
                    self._persist()
                    self.say(f"El bot ataca con {attacker.fid} a {target.fid}: deja tu defensa boca abajo "
                             "(o nada) y pulsa Revelar.", ChatKind.ATTACK)
                    return
                before = self._snapshot_bot()
                seen = len(g.players[self.bot].discard)
                hp0 = {fid: f.hp for fid, f in g.fighters.items()}
                alive0 = self._alive_map()
                exhausting = act.kind == "maneuver" and not g.players[self.bot].deck
                self.ai.execute(g, act)
                self._mark_dirty(before)
                self._persist()
                fin_table = self._flush_table_stage()
                dials_ok = self._write_dials(defer=True)()    # un solo mensaje para cartas, piezas y diales
                fin_table()
                self._persist()
                if exhausting:
                    self.say(f"Mazo vacio: el bot roba y cada luchador suyo pierde {EXHAUST_DAMAGE} PV.", ChatKind.COMBAT)
                self.say(self._action_text(act, seen, before, hp0), ACTION_KIND.get(act.kind, ChatKind.MOVE))
                self._announce_human_falls(alive0)
                if not dials_ok:
                    self._pause_for_dials()
                    return
            if g.winner is None:
                self._bot_breath()                # entre acciones y tambien antes del "Tu turno"
        if g.winner is not None:
            self.say(f"Fin de partida: gana el jugador {g.winner}.")
            return
        seen = len(g.players[self.bot].discard)
        g.end_turn()                              # puede descartar por limite de mano: eso tambien es deuda de mesa
        expired = g.begin_turn()
        if len(g.players[self.bot].discard) > seen:
            self.say("El bot descarta " + self._discard_list(seen, {}, "limite de mano") + ".")
        self._mark_dirty()
        self._persist()
        for n, label in expired:
            self.say(f"{label}: caduca el +{n} a tus cartas de combate. Descarta el plan.", ChatKind.SCHEME)
        self._announce_human_start()
        try:
            self._flush_table()
        except TABLE_ERRORS as e:
            self.say(f"Tu turno ya ha empezado, pero la mesa del bot no coincide aun ({e}); se reintentara con tu proximo boton.", ChatKind.WARNING)

    def _bot_breath(self) -> None:
        """Pausa tras una accion del bot para que la mesa se vea moverse paso a paso y no todo de golpe. Es un sleep
        de Python, no un mensaje: un `Wait.time` dentro del compuesto no separaria acciones distintas (cada una es su
        propio mensaje) y un mensaje extra costaria ~0.5 s, mas que la propia pausa. Va fuera de la medicion
        `_timed` de la accion para que `--timing` siga dando lo que cuestan los mensajes."""
        if self.cfg.bot_pause > 0:
            time.sleep(self.cfg.bot_pause)

    def _announce_human_start(self) -> None:
        g = self.game
        hb = g.hero(self.human)
        form = g.form(self.human)
        if g.hero_def(self.human).forms is None:
            self.say("Tu turno.", ChatKind.YOUR_TURN)           # sin formas no hay robo ni descarte de inicio de turno
            return
        self.say(f"Tu turno (forma: {form}).", ChatKind.YOUR_TURN)
        if form == DETECTIVE and hb.pos == g.start_spaces[self.bot]:
            self.say("Estas en la salida rival: puedes robar 2 cartas (hazlo en la mesa).", ChatKind.YOUR_TURN)
        elif form != DETECTIVE:
            self.say(f"ANUNG UN RAMA: descarta 1 carta (obligatorio) y mueve a {hb.name} hasta su BOOST, en la mesa.", ChatKind.YOUR_TURN)

    # ---------- E/S con la mesa: instantanea, cola de escrituras y script compuesto ----------
    # Cada mensaje a TTS cuesta ~0.5 s fijos, asi que el modo rapido (`cfg.batch`) minimiza mensajes:
    #   * el clic del panel trae la instantanea de la mesa (`snap`); las lecturas salen de ella, sin preguntar;
    #   * las escrituras se encolan (`_w`) y salen juntas en UN script compuesto que devuelve la mesa resultante
    #     (que pasa a ser la nueva instantanea). Una lectura solo fuerza la salida si la cola toca lo que lee;
    #   * si una lectura discrepa, `_settle` descarta la instantanea y relee (un solo mensaje trae todo).
    # Sin `batch` cada lectura y cada escritura es un mensaje, como antes.
    def _timed(self, label: str):
        return _Timed(self, label)

    def load_identities(self) -> None:
        """Al empezar: la identidad de cada mazo configurado (FaceURL/BackURL del CustomDeck de sus cartas), leida del
        propio objeto. El CardID no identifica un mazo (otros juegos de cartas comparten DeckID), asi que ninguna
        escritura de cartas toca algo que no tenga estas imagenes."""
        c = self.cfg
        decks = [("bot", (c.bot_deck_guid, tuple(c.bot_deck_spot), c.bot_card_ids))]
        if c.human_deck_guid:
            decks.append(("human", (c.human_deck_guid, tuple(c.human_deck_spot) if c.human_deck_spot else None,
                                    c.human_card_ids)))
        res = self.client.call_lua(lua.deck_identities([d for _, d in decks]))
        if not isinstance(res, list) or len(res) != len(decks) or not all(isinstance(e, dict) for e in res):
            raise TTSLuaError(f"respuesta no valida de la lectura de identidades: {str(res)[:80]!r}")
        for (side, _), entry in zip(decks, res):
            pairs = self._parse_pairs(entry.get("pairs"))
            if entry.get("found") and pairs:
                self._deck_ident[side] = pairs

    @staticmethod
    def _parse_pairs(rows) -> tuple:
        if not isinstance(rows, list):
            return ()
        return tuple((r["face"], r["back"]) for r in rows
                     if isinstance(r, dict) and all(isinstance(r.get(k), str) and lua._URL.fullmatch(r[k])
                                                    for k in ("face", "back")))[:lua.MAX_IDENTITIES]

    def _identity_from_hand(self, side: str) -> None:
        """Ultimo recurso: las imagenes de las cartas de la mano del bando (solo las de su rango de CardID)."""
        seat, rng = ((self.cfg.bot_seat, self.cfg.bot_card_ids) if side == "bot"
                     else (self.cfg.human_seat, self.cfg.human_card_ids))
        res = self.client.call_lua(lua.hand_identities(seat, rng))
        pairs = self._parse_pairs(res.get("pairs") if isinstance(res, dict) else None)
        if pairs:
            self._deck_ident[side] = pairs

    def _identity(self, side: str = "bot") -> tuple:
        """Imagenes de las cartas del bando: de la mesa; si no, del guardado de la sesion; si no, de los datos del heroe
        (data/tts, p. ej. con el mazo aun en su bolsa); si no, de su mano."""
        failure: Exception | None = None
        if side not in self._deck_ident:
            try:
                self.load_identities()
            except TABLE_ERRORS as e:
                failure = e
        if side not in self._deck_ident and side in self._saved_ident:
            self._deck_ident[side] = self._saved_ident[side]
        if side not in self._deck_ident and self.cfg.deck_identity.get(side):
            self._deck_ident[side] = tuple(self.cfg.deck_identity[side])[:lua.MAX_IDENTITIES]
        if side not in self._deck_ident:
            try:
                self._identity_from_hand(side)
            except TABLE_ERRORS as e:
                failure = failure or e
        if side not in self._deck_ident:
            if failure is not None:
                raise failure
            raise SessionError(f"no consigo leer la identidad (imagenes) del mazo {'del bot' if side == 'bot' else 'tuyo'}: "
                               "sin ella no toco ninguna carta")
        return self._deck_ident[side]

    def _scope(self) -> lua.Scope:
        c = self.cfg
        spots = [(c.bot_card_spot[0], c.bot_card_spot[2]), tuple(c.human_card_spot), tuple(c.bot_deck_spot)]
        if c.human_deck_spot:
            spots.append(tuple(c.human_deck_spot))
        return lua.Scope((c.bot_seat, c.human_seat), (c.bot_discard_zone, c.human_discard_zone), tuple(spots),
                         max(2.0, c.reveal_radius))

    def snapshot_spec(self) -> lua.SnapSpec:
        if self._snap_spec is None:
            c = self.cfg
            pieces = sorted({g for v in c.pieces.values() for g in piece_guids(v)})
            dials = sorted({*c.dials.values(), *([c.destiny_dial] if c.destiny_dial else [])})
            self._snap_spec = lua.SnapSpec(
                self.game.board, c.bot_seat, c.human_seat, c.bot_discard_zone, (c.bot_deck_guid,),
                (tuple(c.bot_deck_spot),), c.human_discard_zone,
                (c.human_deck_guid,) if c.human_deck_guid else (),
                (tuple(c.human_deck_spot),) if c.human_deck_spot else (), c.deck_exclude_radius,
                (c.bot_card_spot[0], c.bot_card_spot[2]), tuple(c.human_card_spot), c.reveal_radius,
                tuple(pieces), tuple(dials), human_deck=c.human_deck_guid)
        return self._snap_spec

    @staticmethod
    def _valid_snap(snap: dict, spaces=None) -> bool:
        """Tipos y rangos de lo que trae el clic (lo manda un script de TTS, pero tambien lo puede falsear un
        mensaje externo): cualquier valor raro descarta la instantanea entera y se pide una a la mesa."""
        def num(v, lo, hi) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi

        def cards(rows) -> bool:
            return len(rows) <= 300 and all(isinstance(r, dict) and num(r.get("id"), 0, 10 ** 6)
                                            and float(r["id"]).is_integer() and isinstance(r.get("guid"), str)
                                            and len(r["guid"]) <= 40 for r in rows)
        if not all(cards(snap[k]) for k in ("bot_hand", "bot_discard", "human_discard", "face_bot", "face_human")):
            return False
        if not num(snap["human_count"], 0, 300) or not num(snap.get("human_deck_qty", -1), -1, 300):
            return False
        if "seq" in snap and not (isinstance(snap["seq"], int) and not isinstance(snap["seq"], bool)
                                  and 0 <= snap["seq"] < 10 ** 12):
            return False
        for g, info in snap["pieces"].items():
            if not isinstance(g, str) or not isinstance(info, dict) or not isinstance(info.get("found"), bool):
                return False
            if info["found"] and not (num(info.get("space"), 0, 10 ** 4) and num(info.get("dist"), 0, 10 ** 7)
                                      and (spaces is None or info["space"] in spaces)):
                return False
        for g, info in snap["dials"].items():
            if not isinstance(g, str) or not isinstance(info, dict) or not isinstance(info.get("found"), bool):
                return False
            if info["found"] and any(info.get(k) is not None and not num(info[k], -10 ** 4, 10 ** 4)
                                     for k in ("value", "max")):
                return False
        return True

    @staticmethod
    def _parse_snap(raw, spaces=None) -> dict | None:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return None
        if not isinstance(raw, dict) or not all(k in raw for k in SNAP_KEYS):
            return None
        snap = dict(raw)
        for k in ("pieces", "dials"):             # un objeto vacio de Lua llega como lista vacia
            if not isinstance(snap[k], dict):
                snap[k] = {}
        for k in ("bot_hand", "bot_discard", "human_discard", "face_bot", "face_human"):
            if not isinstance(snap[k], list):
                snap[k] = []
        return snap if Session._valid_snap(snap, spaces) else None

    def _snap_stale(self, snap: dict) -> bool:
        """Una instantanea anterior a la ultima escritura de mesa (o sin sello) no refleja la mesa: reabsorberla
        desharia lo que el motor ya movio."""
        seq = snap.get("seq")
        return not isinstance(seq, int) or seq < self._write_seq

    def _take_snapshot(self, raw) -> None:
        """La instantanea que trae el clic (tomada por el propio panel, sin ida y vuelta)."""
        self.snap, self._trusted = None, False
        if self.cfg.batch and raw is not None:
            snap = self._parse_snap(raw, set(self.game.board.spaces))
            if snap is not None and not self._snap_stale(snap):
                self.snap, self._trusted = snap, True

    def _view(self, domain: str) -> dict:
        """La instantanea vigente. Si hay escrituras en cola que tocan `domain` salen antes (y su resultado la
        renueva); sin instantanea se pide una (un solo mensaje trae toda la mesa)."""
        if any(o.domain == domain for o in self._queue):
            self._flush()
        if self._depth == 0:
            self.snap = None                      # la instantanea solo vale mientras se atiende un boton
        if self.snap is not None and self._snap_stale(self.snap):
            self.snap = None                      # anterior a la ultima escritura: nunca se adopta
        if self.snap is None:
            snap = self._parse_snap(self.client.call_lua(lua.snapshot(self.snapshot_spec())),
                                    set(self.game.board.spaces))
            if snap is None:
                raise SessionError("la instantanea de la mesa no es valida")
            snap["seq"] = self._write_seq         # recien leida: refleja todo lo escrito hasta ahora
            if self._depth == 0:
                return snap
            self.snap, self._trusted = snap, False
        return self.snap

    def _w(self, script: str, domain: str) -> _Op:
        """Escribe en la mesa: inmediato sin `batch`, encolado con el (sale en el siguiente `_flush`)."""
        op = _Op(self, script, domain)
        if self.cfg.batch:
            self._queue.append(op)
        else:
            op.value, op.done = self.client.call_lua(script), True
        return op

    def _flush(self) -> None:
        """Envia la cola como UN script compuesto y adopta la mesa resultante como instantanea."""
        while self._queue:
            take, size = 0, 0
            for o in self._queue[:lua.MAX_OPS - 4]:          # tambien se corta por tamano en bytes
                size += len(o.script.encode("utf-8"))
                if take and size > lua.MAX_COMPOSITE_BYTES - COMPOSITE_OVERHEAD:
                    break
                take += 1
            ops, self._queue = self._queue[:take], self._queue[take:]
            expect, self._expect_hand = self._expect_hand, None
            wants_state = any(o.domain != "misc" for o in ops)
            if wants_state:
                self._write_seq += 1
            try:
                res = self.client.call_lua(lua.composite([o.script for o in ops],
                                                         self.snapshot_spec() if wants_state else None, expect,
                                                         seq=self._write_seq))
            except Exception as e:                        # noqa: BLE001 - se propaga a quien pidio el resultado
                self.snap = None
                for o in ops:
                    o.error, o.done = e, True
                raise
            results = res.get("ops") if isinstance(res, dict) else None
            results = results if isinstance(results, list) and len(results) == len(ops) else [None] * len(ops)
            for o, r in zip(ops, results):
                o.done = True
                if isinstance(r, dict) and "__err" in r:
                    o.error = TTSLuaError(r["__err"])
                    continue
                o.value = r
            if wants_state:
                self.snap = self._parse_snap(res.get("state") if isinstance(res, dict) else None,
                                             set(self.game.board.spaces))
                if self.snap is not None:
                    self.snap["seq"] = self._write_seq
                self._trusted = True
                if self._depth == 0:
                    self.snap = None
            for o in ops:
                if o.error is not None and not o.seen:
                    tag = o.script.split("\n", 1)[0].removeprefix("-- sparring:")
                    self.say(f"TTS fallo en {tag} ({o.error}); revisa la mesa a mano.", ChatKind.WARNING)

    def _commit(self) -> None:
        """Cierre de cada boton: lo que queda en cola, la linea de estado y los botones del panel y los anuncios,
        todo en el mismo mensaje."""
        posts, self._post = self._post, []
        said = len(self.messages)
        if self.cfg.live_ui:
            status, states = self.panel_view()
            shown = (status, states)
            try:
                self._w(lua.set_panel(status, states, release_busy=not self.cfg.batch), "misc")
                if self.broadcast:
                    for m in self.messages:
                        for chunk in lua.ascii_text(m):
                            self._w(lua.broadcast(chunk, m.kind), "misc")
            except (ValueError, TypeError) as e:
                self.say(f"No pude preparar el estado del panel ({e}).", ChatKind.WARNING)
        if self._queue:
            try:
                self._flush()
            except TABLE_ERRORS as e:
                self.say(f"No pude actualizar la mesa al terminar ({e}).", ChatKind.WARNING)
        for check in posts:
            check()
        if posts and self.cfg.live_ui and self.panel_view() != shown:
            self._refresh_panel()                     # los cierres cambiaron el estado: la linea y los botones, al dia
        if len(self.messages) > said and posts:       # una comprobacion fallo: se avisa tambien en pantalla
            if self.broadcast:
                for m in self.messages[said:]:
                    for chunk in lua.ascii_text(m):
                        self._w(lua.broadcast(chunk, m.kind), "misc")
            try:
                self._flush()
            except TABLE_ERRORS:
                pass

    def _refresh_panel(self) -> None:
        status, states = self.panel_view()
        try:
            self._w(lua.set_panel(status, states, release_busy=not self.cfg.batch), "misc")
            self._flush()
        except (ValueError, TypeError) + TABLE_ERRORS as e:
            self.say(f"No pude actualizar el panel tras las comprobaciones ({e}).", ChatKind.WARNING)

    def _rd_bot_hand(self) -> list[dict]:
        if self.cfg.batch:
            return self._view("cards")["bot_hand"]
        return self.client.call_lua(lua.read_hand(self.cfg.bot_seat)) or []

    def _rd_bot_discard(self) -> list[dict]:
        c = self.cfg
        if c.batch:
            return self._view("cards")["bot_discard"]
        return self.client.call_lua(lua.read_discard(c.bot_discard_zone, [c.bot_deck_guid], [c.bot_deck_spot],
                                                     c.deck_exclude_radius)) or []

    def _rd_human_discard(self) -> list[dict]:
        c = self.cfg
        if c.batch:
            return self._view("cards")["human_discard"]
        skip = [c.human_deck_guid] if c.human_deck_guid else []
        spots = [c.human_deck_spot] if c.human_deck_spot else []
        return self.client.call_lua(lua.read_discard(c.human_discard_zone, skip, spots, c.deck_exclude_radius)) or []

    def _rd_human_count(self, default: int) -> int:
        if self.cfg.batch:
            count = self._view("cards")["human_count"]
            return count if isinstance(count, int) else default
        return (self.client.call_lua(lua.count_hand(self.cfg.human_seat)) or {}).get("count", default)

    def _rd_face(self, side: str) -> list[dict]:
        """Cartas boca abajo en el punto de combate del bot (`bot`) o del humano (`human`)."""
        c = self.cfg
        if c.batch:
            return self._view("cards")["face_" + side]
        if side == "bot":
            return self.client.call_lua(lua.read_face_down_cards(c.bot_card_spot[0], c.bot_card_spot[2],
                                                                 c.reveal_radius)) or []
        return self.client.call_lua(lua.read_face_down_cards(*c.human_card_spot, c.reveal_radius)) or []

    def _rd_dials(self, guids: list[str]) -> dict:
        if self.cfg.batch:
            dials = self._view("dials")["dials"]
            return {g: dials.get(g) or {"found": False} for g in guids}
        return self.client.call_lua(lua.read_health_dials(guids)) or {}

    # ---------- linea de estado y botones del panel ----------
    def _panel_ids(self) -> list[str]:
        return ui.element_ids([f.fid for f in self.game.own(self.bot, alive_only=False)],
                              tuple(f.fid for f in self.game.own(self.human, alive_only=False)))

    def panel_view(self) -> tuple[str, dict[str, tuple[bool, bool]]]:
        """(texto de la linea de estado, {id: (se puede pulsar, se ve)}) segun el estado de la sesion."""
        g = self.game
        states = {i: (True, True) for i in self._panel_ids()}
        in_setup = self.setup is not None
        free = (not in_setup and g.winner is None and g.turn == self.human and self.pending is None
                and self.pending_discard is None and not self.moving and self.look is None)

        def alive(fid: str) -> bool:
            return g.fighters[fid].alive

        for i in ("btn_maneuver", "btn_scheme"):
            states[i] = (free, True)
        chosen = g.fighters.get(self.chosen_attacker) if self.chosen_attacker else None
        for fid, f in g.fighters.items():
            if f.owner == self.human:
                states[f"att_{fid}"] = (free and f.alive, True)
            else:
                try:
                    reach = bool(free and chosen is not None and f.alive and g.can_attack(chosen, f))
                except RuleError:
                    reach = False
                states[fid] = (reach, True)
            states[f"hpm_{fid}"] = (f.alive, True)
            states[f"rm_{fid}"] = (f.alive, True)
        cancellable = (self.look is not None or self.pending is not None or self.pending_discard is not None
                       or self.chosen_attacker is not None or bool(self.pending_value) or self.dirty or self.unprojected is not None
                       or bool(self.flush_failures))
        boosting = self.pending is not None and self.pending.wait is not None
        stuck = boosting and bool(self.pending.wait.extra["stuck"])
        states["btn_reveal"] = (self.pending is not None and not boosting, not boosting)
        states["btn_cancel"] = (cancellable and (not boosting or stuck), not boosting or stuck)
        states["btn_boost"] = (boosting, boosting)
        states["btn_noboost"] = (boosting, boosting)
        states["btn_end"] = (not in_setup and g.winner is None and (self.pending is None or self.look is not None), True)
        states["btn_look"] = (self._look_blocked() is None, True)
        states["btn_undo"] = (g.winner is not None, g.winner is not None)
        waiting = in_setup and self.setup["stage"] in ("wait_human_first", "wait_human")
        states["btn_ready"] = (in_setup, in_setup)
        states["btn_mulligan"] = (bool(waiting and self.cfg.mulligan_human and not self.setup.get("human_mull")),
                                  in_setup)
        states["btn_restart"] = (True, not in_setup)
        return self._status_text(), {k: v for k, v in states.items() if k in set(self._panel_ids())}

    def restart_armed(self) -> bool:
        return self._restart_at is not None and self.clock() - self._restart_at <= RESTART_WINDOW

    def _status_text(self) -> str:
        g = self.game
        if self.restart_armed():
            return "Pulsa Reiniciar partida otra vez para confirmar"
        if self.setup is not None:
            if self.setup["stage"] in ("wait_human_first", "wait_human"):
                return "Preparacion · coloca a tu ayudante, roba 5 y pulsa Listo"
            return "Preparacion · el bot prepara su mesa"
        if g.winner is not None:
            return f"Fin de partida · gana {self._name(g.hero(g.winner))}"
        if self.look is not None:
            return "Mano del bot a la vista: Tab sobre la carta a descartar o Cancelar"
        if g.turn != self.human:
            paused = self.dial_debt or self.bot_stage is not None or self.dirty or self.flush_failures
            return "Turno del bot" + (" · en pausa, pulsa Fin de accion" if paused else "")
        n = g.actions_left
        head = f"Tu turno · {n} accion{'es' if n != 1 else ''}"
        if self.pending is not None and self.pending.wait is not None:
            title = next((c.title for c in g.players[self.human].full_set
                          if c.card_id == self.pending.wait.card_id), "Boost")
            if self.pending.wait.extra["stuck"]:
                return f"{title} sin resolver: corrige la mesa y pulsa Continuar o Sin boost, o Cancelar"
            return f"{title} revelado: pon una carta en tu descarte y pulsa Continuar o Sin boost"
        if self.pending is not None:
            wait = "tu defensa y Revelar" if self.pending.kind == "bot_attacks" else "Revelar"
        elif self.pending_discard is not None:
            wait = "descartar y Fin de accion"
        elif self.moving:
            wait = "Fin de accion"
        elif self.chosen_attacker is not None:
            wait = "elegir objetivo"
        else:
            wait = "tu accion"
        return f"{head} · esperando {wait}"

    # ---------- mirar la mano del bot (Confront Any Demon or God y similares) ----------
    def _look_blocked(self) -> str | None:
        """Por que ahora no se puede mirar la mano del bot (None si se puede)."""
        g = self.game
        if self.setup is not None:
            return "La partida aun se esta preparando: termina la colocacion y pulsa Listo."
        if g.winner is not None:
            return "La partida ha terminado."
        if self.look is not None:
            return "La mano del bot ya esta a la vista."
        if g.turn != self.human and self.pending is None:
            return "Solo puedes mirar la mano del bot en tu turno o durante un combate."
        if self.dirty or self.unprojected is not None or self.flush_failures or self.placing is not None:
            return "La mesa del bot tiene movimientos sin reflejar: pulsa Fin de accion (o Cancelar) antes de mirar su mano."
        held = self.pending.bot_card if self.pending is not None else None
        if not [c for c in self.game.players[self.bot].hand if c is not held]:
            return "El bot no tiene cartas en la mano."
        return None

    def _look_spots(self, n: int) -> list[tuple[float, float, float]]:
        (x, y, z), (dx, dz) = self.cfg.look_spot, self.cfg.look_step
        return [(x + (i - (n - 1) / 2) * dx, y, z + (i - (n - 1) / 2) * dz) for i in range(n)]

    def _look_rot(self) -> float:
        return self.cfg.bot_discard_rot_y if self.cfg.look_rot_y is None else self.cfg.look_rot_y

    def _look_entries(self) -> list[tuple[str, float, float]]:
        return [(g, sp[0], sp[1]) for g, sp in zip(self.look["guids"], self.look["spots"])]

    def restore_look_row(self) -> None:
        """Tras recrear el panel (TTS recargo la partida) vuelve a anotar en el la fila a la vista, si la hay."""
        if self.look is not None:
            self.client.call_lua(lua.set_look_row(self._look_entries()))

    def _card_line(self, n: int, c: Card) -> str:
        stats = ", ".join(p for p in (CARD_TYPE_NAME.get(c.type, c.type),
                                      f"valor {c.value}" if c.value is not None else "", f"impulso {c.boost}") if p)
        return f"{n}) {c.title}, {stats}: {c.text or 'sin efecto'}"

    def _look_hand(self, _: dict) -> None:
        """Pone las cartas de la mano del bot boca arriba en fila delante del humano y las lee en el chat. No gasta
        accion. El bot no aprende nada de la mano del humano: la que se revela es la suya."""
        why = self._look_blocked()
        if why:
            self.say(why, ChatKind.WARNING)
            return
        self.read_bot_hand()
        st = self.game.players[self.bot]
        by_id = {c.card_id: c for c in st.full_set}
        rows = [r for r in self._rd_bot_hand() if r["id"] in by_id][:lua.MAX_LOOK_CARDS]
        if not rows:
            self.say("No veo cartas en la mano del bot en la mesa.", ChatKind.WARNING)
            return
        self.look_fails = 0                       # una fila nueva empieza sin fallos
        spots = self._look_spots(len(rows))
        if self.cfg.batch:
            self._expect_hand = (self.cfg.bot_seat, 0)
        op = self._w(lua.show_hand_row([r["id"] for r in rows], spots, self._look_rot(), self.cfg.bot_seat,
                                       identity=self._identity(), id_range=self.cfg.bot_card_ids), "cards")
        # los GUID salen de la lectura de la mano: no hace falta esperar a la respuesta (un solo mensaje con el aviso)
        self.look = {"ids": [r["id"] for r in rows], "guids": [r["guid"] for r in rows],
                     "spots": [[sp[0], sp[2]] for sp in spots]}
        self._post.append(lambda: self._look_shown(op))
        self.say(f"Mano del bot ({len(rows)}): haz ping (Tab) sobre la carta a descartar. Tambien vale girar una "
                 "boca abajo y pulsar Fin de accion; Cancelar las devuelve sin descartar.", ChatKind.YOUR_TURN)
        for n, r in enumerate(rows, 1):
            self.say(self._card_line(n, by_id[r["id"]]), ChatKind.SCHEME)

    def _look_shown(self, op: _Op) -> bool:
        """Comprobacion al cierre del boton: la mesa saco las cartas de la mano. Si solo saco algunas, la fila queda con
        esas; si fallo del todo, la mirada se deshace (un error de TTS deja la fila para que Cancelar la recoja)."""
        look = self.look
        if look is None:
            return True
        try:
            shown = {e["id"] for e in ((op.result or {}).get("shown") or []) if isinstance(e, dict)}
        except TABLE_ERRORS as e:
            self.say(f"TTS no confirmo que sacara las cartas ({e}); revisa la mesa y pulsa Cancelar para recogerlas.",
                     ChatKind.WARNING)
            return False
        keep = [i for i, cid in enumerate(look["ids"]) if cid in shown]
        if not keep:
            self.look = None
            self.read_bot_hand()
            self.say("No he podido sacar las cartas de la mano del bot; repite Mirar mano del bot.", ChatKind.WARNING)
            return False
        if len(keep) < len(look["ids"]):
            self.look = {k: [v[i] for i in keep] for k, v in look.items()}
            self.say(f"Solo he podido sacar {len(keep)} de {len(look['ids'])} cartas; el resto sigue en su mano.",
                     ChatKind.WARNING)
        return True

    def _look_ping(self, payload: dict) -> None:
        guid = payload.get("guid")
        if self.look is None:
            self.say("No hay cartas del bot a la vista: pulsa Mirar mano del bot.", ChatKind.WARNING)
            return
        if guid not in self.look["guids"]:
            self.say("Ese ping no era sobre una carta de la fila del bot.", ChatKind.WARNING)
            return
        self._look_close(discard=guid)

    def _look_close(self, discard: str | None = None, face_down: bool = False) -> None:
        """Cierra la fila con un solo script: la carta elegida (por ping, o la unica boca abajo) va al descarte del bot y
        el resto vuelve a su mano; sin eleccion es Cancelar y todo vuelve. Con ping o Cancelar el motor cuenta el descarte
        ya (la carta se conoce por su GUID) y la mesa lo confirma al cierre del boton (`_look_closed`); con la carta
        boca abajo hay que esperar a que la mesa diga cual era."""
        look, st = self.look, self.game.players[self.bot]
        by_id = {c.card_id: c for c in st.full_set}
        n = len(look["ids"])
        if discard is None and not face_down and self.look_fails:
            self._look_force_exit("segundo Cancelar")
            return
        if self.cfg.batch:
            self._expect_hand = (self.cfg.bot_seat, n - 1 if (discard or face_down) else n)
        try:
            op = self._w(lua.resolve_hand_row(
                look["guids"], self.cfg.bot_seat, identity=self._identity(), id_range=self.cfg.bot_card_ids,
                discard=discard, face_down=face_down, spot=self._discard_slot(len(st.discard)),
                rot_y=self.cfg.bot_discard_rot_y), "cards")
        except TABLE_ERRORS:
            if discard is None and not face_down:
                self.look_fails += 1              # sin lote el fallo llega ya: solo cuentan los Cancelar fallidos
            raise
        if face_down:
            chosen = (op.result or {}).get("discarded")
            if chosen in (None, False):
                self.say(f"Hay {(op.result or {}).get('down', 0)} cartas boca abajo en la fila: deja exactamente una (la "
                         "que descartas) y pulsa Fin de accion, o haz ping (Tab) sobre ella.", ChatKind.WARNING)
                return
            card = by_id.get(chosen)
        else:
            card = by_id[look["ids"][look["guids"].index(discard)]] if discard else None
        self.look = None
        if card is not None:
            if card in st.hand:
                self.game.discard_card(self.bot, card)
            else:
                if card in st.deck:
                    st.deck.remove(card)
                st.discard.append(card)
                self.game.card_left_hand(self.bot, card)
        self._post.append(lambda: self._look_closed(op, card, look))
        self.say(f"El bot descarta {card.title} y devuelve el resto de su mano." if card is not None
                 else "Mano del bot devuelta sin descartar nada.", ChatKind.SCHEME if card is not None else ChatKind.NEUTRAL)

    def _look_force_exit(self, why: str) -> None:
        """Salida de la mirada cuando la mesa no deja cerrarla: la mesa manda. El motor suelta la fila, relee la mano y
        deja la deuda de mesa para el proximo Fin de accion; las cartas del bot que no esten en su mano se recogen a mano."""
        self.look, self.look_fails = None, 0
        self.read_bot_hand()
        self._mark_dirty()
        self.say(f"Mirada cerrada a la fuerza ({why}): la mesa manda. Las cartas del bot que no esten en su mano "
                 "(las de la fila) recogelas a mano y devuelvelas a ella; pulsa Fin de accion para sincronizar.",
                 ChatKind.WARNING)

    def _look_best_effort_cancel(self) -> None:
        """Antes de reiniciar: intenta devolver la fila a la mano para que el reinicio recoja las cartas; si falla, sigue."""
        look = self.look
        self.look, self.look_fails = None, 0
        try:
            self._w(lua.resolve_hand_row(look["guids"], self.cfg.bot_seat, identity=self._identity(),
                                         id_range=self.cfg.bot_card_ids), "cards").result
        except TABLE_ERRORS:
            pass

    def _look_closed(self, op: _Op, card: Card | None, look: dict) -> bool:
        """Comprobacion al cierre del boton: la mesa hizo lo que el motor ya conto. Si no (la carta no estaba, TTS fallo),
        el motor deshace el descarte y la fila vuelve a estar a la vista para repetir el ping o Cancelar."""
        st = self.game.players[self.bot]
        try:
            res = op.result or {}
            done = res.get("discarded") == card.card_id if card is not None else bool(res.get("found"))
            fail = None if done else "esa carta no estaba en la fila de la mesa"
        except TABLE_ERRORS as e:
            fail = f"error: {e}"
        if fail is not None:
            if card is not None and card in st.discard:
                st.discard.remove(card)
                st.hand.append(card)
            if not fail.startswith("error") and not (op.result or {}).get("found"):
                self._look_force_exit("ninguna carta de la fila responde")      # apiladas, borradas...
                return
            if card is None:
                self.look_fails += 1              # solo un Cancelar fallido acerca la salida forzada
            self.look = look
            self.say(f"La mesa no hizo el cambio ({fail}): la mano del bot sigue a la vista; repite el ping o Cancelar.",
                     ChatKind.WARNING)
            return False
        self.look_fails = 0
        if card is not None:
            want = len(look["ids"]) - 1
            if self._settle(lambda: card.card_id in self._table_discard() and len(self._table_hand_ids()) >= want):
                self.bot_discarded.add(card.card_id)
            else:
                self._mark_dirty()                # el motor ya la descarto: la proxima sincronizacion termina de moverla
                self.say(f"{card.title} aun no se ve en el descarte del bot; si no llega, pulsa Fin de accion.",
                         ChatKind.WARNING)
        self.read_bot_hand()
        return True

    # ---------- mesa del bot ----------
    def read_bot_hand(self) -> None:
        """La mano sale de la mesa. Los robos que el motor ya conto pero el mazo aun no repartio (`drawn`) se
        mantienen en la mano del motor y fuera de su mazo: un fallo de reparto nunca reinfla el mazo."""
        res = self._rd_bot_hand()
        st = self.game.players[self.bot]
        by_id = {c.card_id: c for c in st.full_set}
        try:
            cards = [by_id[r["id"]] for r in res]
        except KeyError as e:
            raise SessionError(f"carta desconocida en la mano del bot: {e}") from None
        held = self.pending.bot_card if self.pending is not None else None
        if held is not None and held not in cards and held not in st.discard:
            cards.append(held)                    # la carta jugada boca abajo sigue siendo suya hasta resolverse
        for card_id in (self.look["ids"] if self.look is not None else ()):
            c = by_id.get(card_id)                # la mano a la vista esta en la fila de la mesa, no en su mano
            if c is not None and c not in cards and c not in st.discard:
                cards.append(c)
        unseen = [c for c in st.full_set if c not in cards and c not in st.discard]
        owed = min(self.game.drawn[self.bot], len(unseen))
        st.hand = cards + unseen[:owed]
        st.deck = unseen[owed:]

    def _place_bot_card(self, card: Card | None, kind: str, attacker: Fighter, target: Fighter) -> str | None:
        """Deja la carta boca abajo. Si la respuesta no llega (timeout) no se sabe si TTS la movio: `placing` lo
        recuerda y el siguiente `_flush_table` mira la mesa (`_recover_placing`)."""
        if card is None:
            return None
        x, y, z = self.cfg.bot_card_spot
        self.placing = {"kind": kind, "attacker": attacker.fid, "target": target.fid, "card": card.card_id}
        try:
            if self.cfg.batch:
                self._expect_hand = (self.cfg.bot_seat, len(self._table_hand_ids()) - 1)
            ping = ((piece_guids(self.cfg.pieces[attacker.fid]), piece_guids(self.cfg.pieces[target.fid]),
                     [self.cfg.bot_seat, self.cfg.human_seat])
                    if kind == "bot_attacks" else None)
            res = self._w(lua.play_card_face_down(card.card_id, self.cfg.bot_seat, x, y, z, self.cfg.rot_y,
                                                  self.cfg.bot_card_ids, identity=self._identity(), ping=ping),
                          "cards").result
        except OSError:
            raise
        except Exception:
            self.placing = None
            raise
        self.placing = None
        guid = (res or {}).get("played")
        if not guid:
            self.read_bot_hand()
            raise SessionError(f"{card.title} no esta en la mano del bot en la mesa; accion cancelada")
        # no se fia del valor devuelto: la carta tiene que estar de verdad en su punto y fuera de la mano
        if not self._settle(lambda: self._card_on_spot(card.card_id) is not None):
            self.placing = None
            self.read_bot_hand()
            raise SessionError(f"{card.title} no ha salido de la mano del bot (no esta en su punto de carta); "
                               "accion cancelada")
        return self._card_on_spot(card.card_id) or guid

    def _settle(self, ok) -> bool:
        """Sondeo acotado: la mesa de TTS tarda en reflejar los movimientos suaves de cartas. Solo se espera (y se
        relee la mesa) si la lectura discrepa; la primera sale de la instantanea."""
        tries = max(1, self.cfg.settle_tries)
        for i in range(tries):
            if ok():
                return True
            if i < tries - 1:
                if self.cfg.batch:
                    self.snap = None                  # la siguiente lectura va a la mesa
                if self.cfg.settle_wait > 0:
                    time.sleep(self.cfg.settle_wait)
        return False

    def _table_hand_ids(self) -> list[int]:
        return [r["id"] for r in self._rd_bot_hand()]

    def _table_discard(self) -> set[int]:
        """CardID de las cartas del bot en su descarte (el mazo de robo y lo ajeno que haya en la zona se ignoran)."""
        own = {card.card_id for card in self.game.players[self.bot].full_set}
        return {r["id"] for r in self._rd_bot_discard()} & own

    def _in_discard_zone(self, x: float, z: float) -> bool:
        """El centro (x, z) cae dentro de la zona del descarte, con su rotacion (sin limites configurados, si)."""
        bounds = self.cfg.bot_discard_bounds
        if bounds is None:
            return True
        cx, cz, sx, sz, rot = bounds
        t = math.radians(rot)
        dx, dz = x - cx, z - cz
        lx, lz = dx * math.cos(t) - dz * math.sin(t), dx * math.sin(t) + dz * math.cos(t)
        return abs(lx) <= sx / 2 and abs(lz) <= sz / 2

    def _grid_slots(self) -> list[tuple[float, float, float]]:
        """Huecos validos de la rejilla del descarte, en orden de juego: columnas hacia dx, filas hacia dz, sin los
        que caen sobre el mazo de robo ni fuera de la zona."""
        c = self.cfg
        (x0, y0, z0), (dx, dz), (kx, kz) = c.bot_discard_spot, c.bot_discard_step, c.bot_deck_spot
        rows = max(1, c.bot_discard_rows)
        cols = 8 if c.bot_discard_bounds is not None else 4
        out = []
        for i in range(cols * rows):
            col, row = divmod(i, rows)
            x, z = x0 + col * dx, z0 + row * dz
            if (x - kx) ** 2 + (z - kz) ** 2 > c.deck_clear ** 2 and self._in_discard_zone(x, z):
                out.append((x, y0, z))
        return out

    def _discard_slot(self, k: int) -> tuple[float, float, float]:
        """Hueco k-esimo (en orden de juego) de la rejilla. Llena la rejilla, vuelve al primer hueco y apila encima
        (cada vuelta un poco mas alto): las cartas se funden en un Deck, que `read_discard` ya sabe leer."""
        slots = self._grid_slots()
        lap, i = divmod(k, len(slots))
        x, y, z = slots[i]
        return (x, y + lap * self.cfg.discard_layer, z)

    def _adopt_extra_discards(self, on_pile: set[int]) -> None:
        """Cartas del bot que estan en su descarte en la mesa sin que el motor las haya descartado (el humano las
        movio: p. ej. Confront Any Demon or God): salen de la mano o del mazo del motor y pasan al descarte."""
        st = self.game.players[self.bot]
        held = self.pending.bot_card.card_id if self.pending and self.pending.bot_card else None
        for c in st.full_set:
            if c.card_id in on_pile and c not in st.discard and c.card_id != held:
                for zone in (st.hand, st.deck):
                    if c in zone:
                        zone.remove(c)
                st.discard.append(c)
                self.bot_discarded.add(c.card_id)
                self.say(f"La mesa manda: {c.title} esta en el descarte del bot (por un efecto del rival); "
                         "la cuento como descartada.", ChatKind.WARNING)

    def adopt_table(self) -> None:
        """La mesa gana: mano, descarte y posiciones del motor pasan a ser lo que se ve. Cierra cualquier deuda."""
        st = self.game.players[self.bot]
        by_id = {c.card_id: c for c in st.full_set}
        on_pile = self._table_discard()
        st.discard[:] = [c for c in st.discard if c.card_id in on_pile] \
            + [by_id[i] for i in sorted(on_pile) if by_id[i] not in st.discard]
        self.bot_discarded = set(on_pile)
        self.game.drawn[self.bot] = 0
        self.dirty, self.unprojected, self.flush_failures = False, None, 0
        self.read_bot_hand()
        self.sync_positions()
        self.say("Adopto lo que muestra la mesa para el bot (mano, descarte y posiciones). "
                 "Si falta o sobra alguna carta, corrigela en la mesa y pulsa Fin de accion.", ChatKind.WARNING)

    def _adopt_strays(self, missing: int) -> int:
        """Cartas del bot que la mesa muestra sueltas y boca abajo (en su punto de carta o en el del mazo) sin
        estar en su mano ni en su descarte: se devuelven a la mano y cuentan como repartidas."""
        by_id = {c.card_id: c for c in self.game.players[self.bot].full_set}
        known = set(self._table_hand_ids()) | self._table_discard()
        if self.pending and self.pending.bot_card:
            known.add(self.pending.bot_card.card_id)
        dx, dz = self.cfg.bot_deck_spot
        rows = [*self._rd_face("bot"),
                *(self.client.call_lua(lua.read_face_down_cards(dx, dz, self.cfg.reveal_radius)) or [])]
        moved = 0
        for r in rows:
            if moved >= missing:
                break
            if r["id"] in by_id and r["id"] not in known:
                known.add(r["id"])
                res = self._w(lua.return_card_to_hand(r["guid"], self.cfg.bot_seat), "cards").result or {}
                if res.get("returned"):
                    moved += 1
                    self.say(f"{by_id[r['id']].title} del bot estaba suelta en la mesa: la devuelvo a su mano.", ChatKind.WARNING)
        return moved

    def _reconcile_bot(self) -> None:
        """Hace fisico lo que el motor decidio para el bot (descartes y robos) y relee la mano (ver `_reconcile_stage`)."""
        self._reconcile_stage()()

    def _reconcile_stage(self) -> Callable[[], None]:
        """Encola lo que el motor decidio para el bot (descartes y robos) y devuelve la funcion que lo comprueba.

        Idempotente: lo que la mesa ya tiene (en el descarte, aunque sea un Deck) cuenta como movido, y solo se
        reenvia lo que falta. `bot_discarded` crece tras verlo en el descarte y `drawn` solo baja por lo que el
        mazo dice haber repartido, de modo que cualquier fallo se puede reintentar sin duplicar nada. Todas las
        lecturas se hacen antes de escribir: el descarte y el robo salen en el mismo mensaje."""
        g, st = self.game, self.game.players[self.bot]
        held = {self.pending.bot_card.card_id} if self.pending and self.pending.bot_card else set()
        on_pile = self._table_discard()
        self._adopt_extra_discards(on_pile)
        new = [c.card_id for c in st.discard if c.card_id not in self.bot_discarded]
        hand_now = self._table_hand_ids() if g.drawn[self.bot] else []
        discard_op, todo = None, []
        if new:
            self.bot_discarded.update(i for i in new if i in on_pile)
            todo = [i for i in new if i not in on_pile]
            if todo:
                order = [c.card_id for c in st.discard]
                spots = [self._discard_slot(order.index(i)) for i in todo]
                discard_op = self._w(lua.discard_cards(todo, spots, self.cfg.bot_discard_rot_y, identity=self._identity(),
                                                  scope=self._scope(), id_range=self.cfg.bot_card_ids), "cards")

        def check_discard() -> None:
            if discard_op is None:
                return
            missing = set(todo) - set((discard_op.result or {}).get("moved") or [])
            if missing:
                raise SessionError(f"no encontre en la mesa las cartas del bot {sorted(missing)} para descartarlas")
        if not self.cfg.batch:
            check_discard()
        n = g.drawn[self.bot]
        if n:
            # un reparto cuya respuesta llego tarde ya esta en la mano de la mesa: se acredita, no se repite.
            # Las cartas ya descartadas por el motor (aunque sigan volando hacia la pila) no cuentan como mano.
            gone = {c.card_id for c in st.discard} | held
            present = len({i for i in hand_now if i not in gone})
            n = max(0, min(n, len([c for c in st.hand if c.card_id not in held]) - present))
            g.drawn[self.bot] = n
        deal_op = None
        if n:
            deal_op = self._w(lua.deal_cards(self.cfg.bot_deck_guid, n, self.cfg.bot_seat,
                                             spot=self.cfg.bot_deck_spot, id_range=self.cfg.bot_card_ids,
                                             identity=self._identity()), "cards")
        # la carta jugada boca abajo cuenta en la mano del motor pero no esta en la mano de la mesa
        want_discard = {c.card_id for c in st.discard}
        want_hand = len([c for c in st.hand if c.card_id not in held])
        if discard_op is not None or deal_op is not None:
            self._expect_hand = (self.cfg.bot_seat, want_hand)

        def fin() -> None:
            short = 0
            if deal_op is not None:
                res = deal_op.result or {}
                dealt = res.get("dealt") or 0
                short = n - min(n, dealt)
                if short:
                    short -= self._adopt_strays(short)
                g.drawn[self.bot] = short
            if self.cfg.batch:
                check_discard()
            if short:
                raise SessionError(f"el mazo del bot repartio {n - short} de {n} cartas")
            if not self._settle(lambda: len([i for i in self._table_hand_ids() if i not in held]) == want_hand
                                and self._table_discard() == want_discard):
                raise SessionError("la mesa del bot no coincide con el motor (mano o descarte); reintenta Fin de accion")
            self.bot_discarded.update(new)
            self.read_bot_hand()
        if not self.cfg.batch:
            fin()
            return lambda: None
        return fin

    def _alive_map(self) -> dict[str, bool]:
        return {fid: f.alive for fid, f in self.game.fighters.items()}

    def _announce_human_falls(self, alive_before: dict[str, bool]) -> None:
        """Bajas del humano causadas por el bot (habilidad, A Momentary Glance...). Las del bot las proyecta `_project`."""
        for fid, was in alive_before.items():
            f = self.game.fighters[fid]
            if was and not f.alive and f.owner == self.human:
                self._announce_fall(f)

    def _snapshot_bot(self) -> dict[str, tuple[int | None, bool]]:
        return {f.fid: (f.pos, f.alive) for f in self.game.own(self.bot, alive_only=False)}

    def _project(self, before: dict[str, tuple[int | None, bool]]) -> None:
        """Proyecta en la mesa todo movimiento de piezas del bot hecho por el motor (incluye resurrecciones)."""
        self._project_stage(before)()

    def _project_stage(self, before: dict[str, tuple[int | None, bool]]) -> Callable[[], None]:
        """Encola los movimientos y devuelve la funcion que los comprueba (sin `batch` se comprueba ya, pieza a
        pieza, como siempre)."""
        defer = self.cfg.batch
        pieces = self._table_pieces() if defer else None
        checks: list[Callable[[], None]] = []
        for fid, (pos, was_alive) in before.items():
            f, name = self.game.fighters[fid], self._name(self.game.fighters[fid])
            if not was_alive and f.alive:
                check = self._place_revived(f, name, defer, pieces)
            elif not f.alive:
                check = self._bury(fid, name, defer, pieces) if was_alive else None
            elif f.pos != pos:
                check = self._move_checked(fid, name, f.pos, pieces)
            else:
                check = None
            if check is not None:
                if defer:
                    checks.append(check)
                else:
                    check()

        def fin() -> None:
            for c in checks:
                c()
        return fin

    def _move_checked(self, fid: str, name: str, space: int, pieces) -> Callable[[], None]:
        moved = self._move_stage(fid, space, pieces)
        if not self.cfg.batch:
            def check() -> None:
                if not moved():
                    raise SessionError(f"no pude mover la pieza de {name} ({'/'.join(self._guids(fid))}) a la "
                                       f"casilla {space}: el GUID no existe en la mesa")
            return check

        def check() -> None:
            if not moved():
                raise SessionError(f"no pude mover la pieza de {name} ({'/'.join(self._guids(fid))}) a la "
                                   f"casilla {space}: el GUID no existe en la mesa")
        return check

    def _announce_fall(self, f: Fighter) -> None:
        """Toda baja, venga de donde venga (combate, habilidad, efecto del bot, Retirar, PV a 0), se anuncia igual:
        '<nombre> cae' y que pasa con la miniatura. La del bot la aparta `_bury`; la del humano la retira el."""
        name = self._name(f)
        self._bury(f.fid, name)
        if f.owner == self.human:
            return
        if self.unprojected is not None and f.fid in self.unprojected:
            self.unprojected[f.fid] = (self.unprojected[f.fid][0], False)    # ya apartada: `_project` no la repite

    def _bury(self, fid: str, name: str, defer: bool = False, pieces=None) -> Callable[[], None] | None:
        """Una pieza que cae (del bot o del humano) se aparta sola a su zona de bajas (`dead_spot` o `human_dead_spot`,
        una por pieza) y se relee la mesa para comprobar que ya no esta en el tablero; sin zona, o si TTS no la mueve,
        se le dice al humano que la retire. Con `defer` encola y devuelve la comprobacion."""
        owner = self.game.fighters[fid].owner
        mine = owner == self.bot
        spot = self.cfg.dead_spot if mine else human_dead_spot(self.cfg)
        done = f"{name} cae: la he apartado fuera del tablero." if mine else f"{name} cae: lo he apartado."
        failed = (f"{name} cae: retira su miniatura de la mesa (no he podido apartarla yo)." if mine
                  else f"{name} (tuyo) cae: retira su miniatura de la mesa.")
        if spot is not None:
            slot = sorted(f.fid for f in self.game.own(owner, alive_only=False)).index(fid)
            at = (spot[0] + (1.5 if mine else -1.5) * slot, spot[1], spot[2])
            if defer:
                info = (pieces if pieces is not None else self._table_pieces()).get(fid) or {}
                guids = [info["guid"]] if info.get("found") else self._guids(fid)
                op = self._w(lua.place_piece(guids[0], *at), "pieces")

                def check() -> None:
                    try:
                        res = op.result or {}
                    except TABLE_ERRORS:
                        res = {}
                    if res.get("moved") and self._off_board(fid):
                        self.say(done)
                    else:
                        self.say(failed, ChatKind.WARNING)
                return check
            for guid in self._guids(fid):
                try:
                    res = self._w(lua.place_piece(guid, *at), "pieces").result or {}
                except TABLE_ERRORS:
                    break
                if res.get("moved") and self._off_board(fid):
                    self.say(done)
                    return None
        self.say(failed, ChatKind.WARNING)
        return None

    def _off_board(self, fid: str) -> bool:
        """Relectura de la mesa: la miniatura existe y ya no esta sobre el tablero."""
        def away() -> bool:
            try:
                info = self._table_pieces().get(fid) or {}
            except TABLE_ERRORS:
                return False
            return bool(info.get("found")) and not self._on_board(info)
        return self._settle(away)

    def _place_revived(self, f: Fighter, name: str, defer: bool = False, pieces=None) -> Callable[[], None] | None:
        """Winged Frenzy: la Harpia vuelve; se mueve su miniatura a la casilla y se comprueba en la mesa."""
        moved = self._move_stage(f.fid, f.pos, pieces)

        def there() -> bool:
            info = self._table_pieces().get(f.fid) or {}
            return bool(info.get("found")) and info.get("space") == f.pos

        def check() -> None:
            if moved() and self._settle(there):
                self.say(f"{name} vuelve al juego: la he colocado yo en la casilla {f.pos}.")
            else:
                self.say(f"Coloca a {name} en la casilla {f.pos} (no la he podido mover yo); luego pulsa Fin de accion.", ChatKind.YOUR_TURN)
        if defer:
            return check
        check()
        return None

    # ---------- mesa del humano ----------
    def _guids(self, fid: str) -> list[str]:
        return piece_guids(self.cfg.pieces[fid])

    def _table_pieces(self) -> dict[str, dict]:
        """fid -> {found, space, dist, type, name, guid} leido por GUID (una sola llamada). Si la miniatura tiene
        varios GUID (uno por estado) vale el que exista en la mesa."""
        guids = sorted({g for fid in self.cfg.pieces for g in self._guids(fid)})
        if self.cfg.batch:
            found = self._view("pieces")["pieces"]
        else:
            found = self.client.call_lua(lua.piece_spaces_by_guid(self.game.board, guids))
        found = found if isinstance(found, dict) else {}
        out = {}
        for fid in self.cfg.pieces:
            hit = next(((g, found[g]) for g in self._guids(fid)
                        if isinstance(found.get(g), dict) and found[g].get("found")), None)
            out[fid] = {**hit[1], "guid": hit[0]} if hit else {"found": False}
        return out

    def _move_stage(self, fid: str, space: int, pieces: dict[str, dict] | None = None) -> Callable[[], bool]:
        """Encola el movimiento de la miniatura (con el GUID que la mesa muestra; si no, el primero) y devuelve la
        funcion que dice si se movio, probando los demas GUID si el primero fallo."""
        guids = self._guids(fid)
        order = guids
        if self.cfg.batch:
            info = (pieces if pieces is not None else self._table_pieces()).get(fid) or {}
            order = [info["guid"]] if info.get("found") else guids
        first = self._w(lua.move_piece(self.game.board, order[0], space), "pieces")

        def moved() -> bool:
            if (first.result or {}).get("moved"):
                return True
            return any((self._w(lua.move_piece(self.game.board, g, space), "pieces").result or {}).get("moved")
                       for g in order[1:])
        return moved

    def _move_piece(self, fid: str, space: int) -> bool:
        """Mueve la miniatura a una casilla probando sus GUID por orden hasta que uno exista."""
        return self._move_stage(fid, space)()

    def _on_board(self, info: dict) -> bool:
        return bool(info.get("found")) and info.get("dist", 0) <= self.cfg.off_board_dist

    def sync_positions(self) -> None:
        for fid, info in self._table_pieces().items():
            f = self.game.fighters[fid]
            if not f.alive:
                continue
            quiet = self.setup is not None        # en la preparacion aun no hay piezas colocadas: nada que avisar
            name, guid = self._name(f), "/".join(self._guids(fid))
            if quiet and not self._on_board(info):
                continue
            if not info.get("found"):
                self._warn(fid, "missing", f"No encuentro la pieza de {name} ({guid}) en la mesa; "
                                           "mantengo su ultima casilla.")
            elif not self._on_board(info):
                self._warn(fid, "off", f"{name} esta fuera del tablero (a {info['dist']:.1f} de la casilla "
                                       f"{info['space']}): si ha muerto, pulsa Retirar; si no, devuelvela al tablero.")
            else:
                f.pos = info["space"]
                self._warned.discard((fid, "missing"))
                self._warned.discard((fid, "off"))

    def sync_human(self) -> None:
        """Descarte del motor == descarte de la mesa (altas y bajas); tamano de mano por conteo."""
        st = self.game.players[self.human]
        own = {x.card_id for x in st.full_set}
        def read() -> set[int]:                   # solo cartas del humano: lo ajeno en la zona no cuenta ni retrasa
            return {r["id"] for r in self._rd_human_discard()} & own
        ids = read()
        known = {x.card_id for x in st.discard}
        # un cambio solo vale si lo ven dos lecturas (carta en transito, borde); la instantanea del clic ya es la
        # segunda: el humano no puede estar arrastrando una carta mientras pulsa un boton
        if ids != known and not (self.cfg.batch and self._trusted):
            if self.cfg.settle_wait > 0:
                time.sleep(self.cfg.settle_wait)
            if self.cfg.batch:
                self.snap = None
            again = read()
            ids = (ids & again) | (known & (ids | again))
        for i in list(self._transit):             # carta recien jugada: se mantiene en el descarte hasta que aparece
            if i in ids or self._transit[i] >= TRANSIT_READS:
                del self._transit[i]
            else:
                self._transit[i] += 1
                ids = ids | ({i} & known)
        by_id = {c.card_id: c for c in st.full_set}
        deck_qty = (self.snap or {}).get("human_deck_qty", -1) if self.cfg.batch else -1
        fresh = [c for c in st.discard if c.card_id not in ids and c.card_id not in self._gone]
        real = self._rd_human_count(len(st.hand))
        # Si el mazo de robo crecio en tantas cartas como acaban de faltar, el mazo prueba a donde fueron: la baja vale
        # ya, sin esperar al segundo boton. El crecimiento que explica una carta menos en la mano (Vistazo al infierno:
        # mano -> mazo) no cuenta, o una lectura suelta fallida bajaria el contador.
        hand_drop = max(0, len(st.hand) - real)
        grew = (isinstance(deck_qty, int) and deck_qty >= 0 and self._deck_qty >= 0 and bool(fresh)
                and deck_qty - self._deck_qty - hand_drop >= len(fresh))
        # Wildfire: solo vuelve a la mano una ardiente que sale del descarte si tu mano de la mesa crecio sin
        # explicacion (la recogiste) y no la explica el mazo (Rekindle, Searing Clarity: la barajan en el mazo)
        wildfire, back = self._human_wildfire(), []
        # El credito caduca en el boton siguiente al que lo genero y solo lo gasta una ardiente que empezo a faltar
        # en esa misma lectura o despues: la ardiente del fondo del mazo que vuelve a tu mano al empezar el turno no
        # puede mandar a la mano otra que Rekindle baraja en el mazo mas tarde.
        turn, at, credit = self._wild_credit
        credit = credit if turn == self.game.turn_no and self._epoch - at <= 1 else 0
        if real > len(st.hand):
            at, credit = self._epoch, credit + real - len(st.hand)
        for c in list(st.discard):
            if c.card_id in ids:
                self._gone.pop(c.card_id, None)
                continue
            # Una carta que falta solo sale del descarte si falta tambien en OTRO boton (una lectura suelta que la
            # pierde no puede bajar el contador de destinos), o si el mazo de robo crecio justo por ella.
            if self._gone.setdefault(c.card_id, self._epoch) == self._epoch and not (grew and c in fresh):
                continue
            missing_since = self._gone.pop(c.card_id)
            st.discard.remove(c)
            st.deck.append(c)
            if (wildfire and "burning" in c.tags and not (grew and c in fresh) and len(back) < credit
                    and missing_since >= at):
                back.append(c)                          # vuelve a la mano, y a la vista
        self._wild_credit = (self.game.turn_no, at, credit - len(back)) if wildfire else (-1, -1, 0)
        for c in back:
            self._make_known(c, keep=tuple(back))
            self.game.players[self.bot].known.add(c, self.game.turn_no)
        if isinstance(deck_qty, int) and deck_qty >= 0:
            self._deck_qty = deck_qty
        for i in sorted(ids & by_id.keys()):
            c = by_id[i]
            if c in st.discard:
                continue
            if c in st.hand:
                st.hand.remove(c)
            elif c in st.deck:
                st.deck.remove(c)
            st.discard.append(c)
            self.game.card_left_hand(self.human, c)     # si el bot la habia visto en tu mano, deja de contar con ella
        self._verify_maneuver_deal(real, len(ids))
        known = self.game.players[self.bot].known.seen
        while len(st.hand) > real:                      # la mano virtual se recorta por las cartas NO vistas
            spare = next((c for c in reversed(st.hand) if c.card_id not in known), st.hand[-1])
            st.hand.remove(spare)
            st.deck.append(spare)
        while len(st.hand) < real and st.deck:
            st.hand.append(st.deck.pop(0))
        if self._track_destiny() and not self._destiny_tried:
            self._destiny_tried = True                # un solo intento por boton: un dial roto no frena cada lectura
            self._write_dials(only_destiny=True, post=True)   # los PV solo se escriben tras un cambio real

    def _make_known(self, card: Card, keep: tuple = ()) -> None:
        """La mano del humano es virtual: al verse una carta se intercambia con una de la mano virtual (nunca con las
        de `keep`, ya conocidas en este mismo paso)."""
        st = self.game.players[self.human]
        if card in st.hand:
            return
        if card in st.discard:                    # la carta esta boca abajo en la mesa: la lectura del descarte era vieja
            st.discard.remove(card)
        elif card in st.deck:
            st.deck.remove(card)
        known = self.game.players[self.bot].known.seen
        spare = [c for c in st.hand if c not in keep and c.card_id not in known] or [c for c in st.hand if c not in keep]
        if spare:
            st.hand.remove(spare[-1])
            st.deck.append(spare[-1])
        st.hand.append(card)
