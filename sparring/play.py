"""Punto de entrada de la partida en vivo.

    python -m sparring.play --config config\\partida.json              # jugar: panel + bucle de eventos
    python -m sparring.play --config config\\partida.json --read-only  # solo leer la mesa e imprimir un informe

El modo `--read-only` no envia nada que cambie la mesa: un envoltorio solo deja pasar los constructores de
lectura (piece_spaces_by_guid, read_hand, count_hand, read_discard, read_face_down_cards, inspect_guids,
read_health_dials, zone_overlaps). Es para la
primera prueba en vivo: confirma GUIDs, asientos y posiciones antes de dejar que el bot toque nada.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .ai_medusa import MedusaAI
from .board import Board
from .cards import load_hellboy_deck, load_medusa_deck
from . import persist
from .session import TABLE_ERRORS, Session, SessionConfig, SessionError, piece_guids
from .state import Game
from .tts import lua, ui
from .tts.client import LISTEN_PORT, SEND_PORT, TTSClient, TTSLuaError
from .tts.ui import parse_event

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "partida.json"
DEFAULT_STATE = Path(__file__).resolve().parent.parent / "estado" / "sesion.json"
BOT, HUMAN = 0, 1
FIGHTER_IDS = ("medusa", "harpy1", "harpy2", "harpy3", "hellboy", "lobster")
READ_ONLY_TAGS = frozenset({"snapshot", "piece_spaces_by_guid", "read_hand", "count_hand", "read_discard",
                            "read_face_down_cards", "inspect_guids", "read_health_dials", "zone_overlaps"})

REQUIRED = ("bot_seat", "human_seat", "nicknames", "bot_card_spot", "human_card_spot", "bot_discard_spot",
            "bot_discard_zone", "bot_deck_guid", "human_discard_zone", "bot_deck_spot", "pieces")


class ConfigError(Exception):
    pass


class ReadOnlyViolation(Exception):
    pass


def is_todo(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip().upper().startswith("TODO"))


@dataclass
class PlayConfig:
    raw: dict
    board: Board
    todos: list[str]

    @property
    def panel_position(self) -> tuple[float, float, float]:
        return tuple(float(v) for v in self.raw.get("panel_position", lua.PANEL_POSITION))  # type: ignore[return-value]

    @property
    def nicknames(self) -> dict[str, str]:
        return dict(self.raw.get("nicknames") or {})

    @property
    def panel_rotation(self) -> tuple[float, float, float]:
        return tuple(float(v) for v in self.raw.get("panel_rotation", ui.PANEL_ROTATION))  # type: ignore[return-value]

    @property
    def panel_scale(self) -> tuple[float, float, float]:
        return tuple(float(v) for v in self.raw.get("panel_scale", ui.PANEL_SCALE))  # type: ignore[return-value]

    def session_config(self) -> SessionConfig:
        """Configuracion de la sesion; solo existe si no queda ningun TODO y todo valida."""
        if self.todos:
            raise ConfigError("faltan valores por leer de la mesa (modo --read-only): " + ", ".join(self.todos))
        r = self.raw
        try:
            cfg = SessionConfig(
                bot_seat=r["bot_seat"], human_seat=r["human_seat"], nicknames=dict(r["nicknames"]),
                bot_card_spot=tuple(r["bot_card_spot"]), human_card_spot=tuple(r["human_card_spot"]),
                bot_discard_spot=tuple(r["bot_discard_spot"]), bot_discard_zone=r["bot_discard_zone"],
                bot_deck_guid=r["bot_deck_guid"], human_discard_zone=r["human_discard_zone"],
                bot_deck_spot=tuple(r["bot_deck_spot"]), pieces=dict(r["pieces"]),
                reveal_radius=float(r.get("reveal_radius", 2.0)), rot_y=float(r.get("rot_y", 0.0)),
                dials=dict(r.get("dials", {})), destiny_dial=r.get("destiny_dial"),
                setup=bool(r.get("setup", True)), mulligan_bot=bool(r.get("mulligan_bot", True)),
                mulligan_human=bool(r.get("mulligan_human", True)),
                dead_spot=tuple(float(v) for v in r["dead_spot"]) if r.get("dead_spot") else None, off_board_dist=float(r.get("off_board_dist", 4.0)),
                adopt_after=int(r.get("adopt_after", 3)),
                bot_discard_step=tuple(r.get("bot_discard_step", (-3.6, 2.2))),
                bot_discard_rows=int(r.get("bot_discard_rows", 15)),
                bot_discard_rot_y=float(r.get("bot_discard_rot_y", 90.0)),
                human_deck_guid=r.get("human_deck_guid"),
                human_deck_spot=tuple(r["human_deck_spot"]) if r.get("human_deck_spot") else None,
                start_spaces={str(k): int(v) for k, v in (r.get("start_spaces") or {}).items()},
                bot_discard_bounds=tuple(float(v) for v in r["bot_discard_bounds"])
                if r.get("bot_discard_bounds") else None,
                human_dead_spot=tuple(float(v) for v in r["human_dead_spot"]) if r.get("human_dead_spot") else None,
                label_font=float(r.get("label_font", lua.LABEL_FONT)),
                batch=bool(r.get("batch", True)), live_ui=bool(r.get("live_ui", True)))
            if cfg.bot_discard_bounds is not None and len(cfg.bot_discard_bounds) != 5:
                raise ValueError("bot_discard_bounds: (centro x, centro z, tamano x, tamano z, rotY)")
            self._dry_build(cfg)
        except (KeyError, TypeError, ValueError) as e:
            raise ConfigError(f"configuracion no valida: {e}") from None
        for key in ("nicknames", "pieces"):
            missing = sorted(set(FIGHTER_IDS) - set(getattr(cfg, key)))
            if missing:
                raise ConfigError(f"faltan {key} de: {', '.join(missing)}")
        return cfg

    def _dry_build(self, cfg: SessionConfig) -> None:
        """Construye una vez cada script con la configuracion: un valor mal escrito falla aqui, no en mitad de la partida."""
        lua.read_hand(cfg.bot_seat), lua.read_hand(cfg.human_seat), lua.count_hand(cfg.human_seat)
        lua.read_discard(cfg.bot_discard_zone, [cfg.bot_deck_guid], [cfg.bot_deck_spot])
        lua.read_discard(cfg.human_discard_zone, [cfg.human_deck_guid] if cfg.human_deck_guid else [],
                         [cfg.human_deck_spot] if cfg.human_deck_spot else [])
        lua.deal_cards(cfg.bot_deck_guid, 1, cfg.bot_seat, spot=cfg.bot_deck_spot)
        lua.discard_cards([0], [cfg.bot_discard_spot], cfg.bot_discard_rot_y)
        lua.play_card_face_down(0, cfg.bot_seat, *cfg.bot_card_spot, cfg.rot_y)
        lua.read_face_down_cards(*cfg.human_card_spot, cfg.reveal_radius)
        for name in cfg.nicknames.values():
            lua.lua_str(name)
        guids = sorted({g for v in cfg.pieces.values() for g in piece_guids(v)})
        lua.piece_spaces_by_guid(self.board, guids)
        lua.move_piece(self.board, guids[0], next(iter(self.board.spaces)))
        lua.read_health_dials(sorted({*cfg.dials.values(), *([cfg.destiny_dial] if cfg.destiny_dial else [])}))
        lua.set_health_dials({g: 0 for g in {*cfg.dials.values(), *([cfg.destiny_dial] if cfg.destiny_dial else [])}})
        lua.return_hand_to_deck(cfg.bot_seat, cfg.bot_deck_guid)
        lua.shuffle_deck(cfg.bot_deck_guid, cfg.bot_deck_spot)
        if cfg.dead_spot is not None:
            if len(cfg.dead_spot) != 3:
                raise ValueError("dead_spot: (x, y, z)")
            lua.place_piece("abc", *cfg.dead_spot)
        lua.zone_overlaps([cfg.bot_discard_zone, cfg.human_discard_zone])


def load_config(path: str | Path) -> PlayConfig:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"no puedo leer la configuracion {path}: {e}") from None
    board_key = raw.get("board", "bprd-hq")
    if board_key not in lua.BOARD_GUIDS:
        raise ConfigError(f"tablero desconocido: {board_key!r}")
    if raw.get("board_guid") not in (None, lua.BOARD_GUIDS[board_key]):
        raise ConfigError(f"board_guid {raw['board_guid']!r} no es el del tablero {board_key} "
                          f"({lua.BOARD_GUIDS[board_key]})")
    todos = [k for k in REQUIRED if is_todo(raw.get(k))]
    return PlayConfig(raw, Board.load(board_key), todos)


# ---------- modo solo lectura ----------
class ReadOnlyClient:
    """Envuelve al cliente y solo deja pasar scripts de lectura; no expone `send` ni `execute_lua`."""

    def __init__(self, client: TTSClient):
        self._client = client

    def call_lua(self, script: str, *a, **kw):
        tag = re.match(r"-- sparring:(\w+)", script)
        if not tag or tag.group(1) not in READ_ONLY_TAGS:
            raise ReadOnlyViolation(f"modo solo lectura: script no permitido ({script[:40]!r})")
        return self._client.call_lua(script, *a, **kw)


def _titles() -> dict[int, str]:
    return {c.card_id: c.title for c in (*load_medusa_deck(), *load_hellboy_deck())}


def read_only_report(client, cfg: PlayConfig) -> list[str]:
    """Lee la mesa y devuelve las lineas del informe. No cambia nada."""
    ro = client if isinstance(client, ReadOnlyClient) else ReadOnlyClient(client)
    raw, titles, out, warn = cfg.raw, _titles(), [], []

    def val(key):
        v = raw.get(key)
        return None if is_todo(v) else v

    def show_ids(rows) -> str:
        return ", ".join(titles.get(r["id"], f"?{r['id']}") for r in rows) or "(vacio)"

    def read(label: str, builder: Callable[[], str]):
        try:
            return ro.call_lua(builder())
        except ReadOnlyViolation:
            raise
        except (TTSLuaError, TimeoutError, ValueError, TypeError) as e:
            warn.append(f"{label}: fallo la lectura ({e})")
            return None

    out.append("== INFORME DE SOLO LECTURA (no se ha cambiado nada en la mesa) ==")
    guids = {"tablero": lua.BOARD_GUIDS[cfg.board.key], "mazo del bot": val("bot_deck_guid"),
             "zona descarte bot": val("bot_discard_zone"), "zona descarte humano": val("human_discard_zone")}
    guids.update({f"sonda {g}": g for g in raw.get("probe_guids", [])})
    known = {k: g for k, g in guids.items() if g}
    found = read("objetos", lambda: lua.inspect_guids(sorted(set(known.values())))) or {}
    out.append("-- objetos por GUID")
    for label, g in known.items():
        info = found.get(g, {"found": False})
        if info.get("found"):
            qty = f", {info['quantity']} cartas" if info.get("quantity") is not None else ""
            out.append(f"  {label} {g}: {info['type']} '{info.get('name', '')}'{qty} en "
                       f"({info['x']:.1f}, {info['y']:.1f}, {info['z']:.1f})")
        else:
            warn.append(f"{label} {g}: NO existe en la mesa")
    for label in (k for k, g in guids.items() if not g):
        out.append(f"  {label}: TODO (sin valor)")

    wanted = raw.get("pieces") or {}
    off = float(raw.get("off_board_dist", 4.0))
    out.append("-- miniaturas por GUID (casilla mas cercana y distancia)")
    flat = sorted({g for v in wanted.values() for g in piece_guids(v)})
    pieces = read("miniaturas", lambda: lua.piece_spaces_by_guid(cfg.board, flat)) or {}
    pieces = pieces if isinstance(pieces, dict) else {}
    for fid, value in wanted.items():
        guids = piece_guids(value)
        g = next((x for x in guids if (pieces.get(x) or {}).get("found")), guids[0])
        p = pieces.get(g) or {"found": False}
        if not p.get("found"):
            warn.append(f"miniatura {fid} {'/'.join(guids)}: NO existe en la mesa (GUID cambiado o pieza borrada)")
            continue
        out.append(f"  {fid:8} {g}: {p.get('type')} '{p.get('name', '')}' casilla {p['space']} "
                   f"(a {p['dist']:.2f} del enganche)")
        if p["dist"] > off:
            warn.append(f"miniatura {fid} {g} esta fuera del tablero (a {p['dist']:.2f} > {off:g}): "
                        "el bot la tratara como pieza fuera de juego")
    if not wanted:
        out.append("  pieces: TODO (sin valor)")

    dials = dict(raw.get("dials") or {})
    if raw.get("destiny_dial"):
        dials["destinos"] = raw["destiny_dial"]
    if dials:
        out.append("-- diales de vida (solo lectura)")
        rows = read("diales", lambda: lua.read_health_dials(sorted(set(dials.values())))) or {}
        rows = rows if isinstance(rows, dict) else {}
        for fid, g in dials.items():
            d = rows.get(g) or {"found": False}
            if not d.get("found"):
                warn.append(f"dial {fid} {g}: NO existe en la mesa")
            elif d.get("value") is None:
                out.append(f"  {fid:8} {g}: '{d.get('name', '')}' sin CONFIG.VALUE legible "
                           f"(etiqueta {d.get('label')!r}, getValue {d.get('object_value')!r})")
            else:
                out.append(f"  {fid:8} {g}: '{d.get('name', '')}' vida {d['value']} de {d.get('max')}")

    hands: dict[str, set[int]] = {}
    for role, seat_key in (("bot", "bot_seat"), ("humano", "human_seat")):
        seat = val(seat_key)
        if not seat:
            out.append(f"-- mano del {role}: TODO ({seat_key} sin valor)")
            continue
        hand = read(f"mano {role}", lambda s=seat: lua.read_hand(s)) or []
        hands[role] = {r["id"] for r in hand}
        if role == "bot":
            out.append(f"-- mano del bot ({seat}): {len(hand)} cartas: {show_ids(hand)}")
        else:
            count = (read("conteo humano", lambda: lua.count_hand(seat)) or {}).get("count")
            out.append(f"-- mano del humano ({seat}): {count} cartas, {len(hand)} legibles (solo se cuentan)")
    zones: dict[str, str] = {}
    for role, key in (("bot", "bot_discard_zone"), ("humano", "human_discard_zone")):
        zone = val(key)
        if not zone:
            out.append(f"-- descarte del {role}: TODO ({key} sin valor): crea una zona de scripting sobre la pila "
                       "de descarte y pon aqui su GUID")
            continue
        zones[role] = zone
        deck_guid, deck_spot = (val("bot_deck_guid"), raw.get("bot_deck_spot")) if role == "bot" else             (raw.get("human_deck_guid"), raw.get("human_deck_spot"))
        rows = read(f"descarte {role}", lambda z=zone: lua.read_discard(
            z, [deck_guid] if deck_guid else [], [deck_spot] if deck_spot else [])) or []
        out.append(f"-- descarte del {role}: {len(rows)} cartas: {show_ids(rows)}")
        shared = hands.get(role, set()) & {r["id"] for r in rows}
        if shared:
            warn.append(f"descarte {role} {zone}: comparte {len(shared)} carta(s) con la mano del asiento "
                        f"({', '.join(titles.get(i, str(i)) for i in sorted(shared))}): casi seguro es una zona de MANO, "
                        "no la del descarte")
    if zones:
        over = read("zonas de mano", lambda: lua.zone_overlaps(sorted(set(zones.values())))) or {}
        over = over if isinstance(over, dict) else {}
        for role, zone in zones.items():
            hz = list((over.get(zone) or {}).get("hands") or [])
            if hz:
                warn.append(f"descarte {role} {zone}: se solapa con la zona de mano {', '.join(hz)}: no vale como "
                            "zona de descarte")
    spot = val("human_card_spot")
    if spot:
        rows = read("cartas boca abajo", lambda: lua.read_face_down_cards(*spot, float(raw.get("reveal_radius", 2.0)))) or []
        out.append(f"-- boca abajo en la zona del humano: {show_ids(rows)}")
    else:
        out.append("-- boca abajo en la zona del humano: TODO (human_card_spot sin valor)")

    if cfg.todos:
        out.append("-- TODO por rellenar en la configuracion: " + ", ".join(cfg.todos))
    for w in warn:
        out.append(f"AVISO: {w}")
    out.append("== fin del informe ==")
    return out


# ---------- bucle de eventos ----------
def make_announcer(client, echo: Callable[[str], None] = print, to_table: bool = True) -> Callable[[list[str]], None]:
    """Imprime cada mensaje del bot y lo muestra en pantalla a los jugadores (broadcast, no toca la mesa)."""
    def announce(msgs: list[str]) -> None:
        for m in msgs:
            echo(f"[bot] {m}")
            if not to_table:
                continue
            for chunk in lua.ascii_text(m):
                try:
                    client.call_lua(lua.broadcast(chunk))
                except (TTSLuaError, TimeoutError, OSError) as e:
                    echo(f"[aviso] no pude mostrar el mensaje en la mesa: {e}")
                    return
    return announce


Recovery = Callable[[], tuple[str, list[str]]]      # -> ("ok" | "retry" | "stop", mensajes)


def mark_floor(client, scfg: SessionConfig) -> None:
    """Dibuja en el suelo las zonas de descarte y los puntos de combate (idempotente; solo en modo juego)."""
    client.call_lua(lua.draw_markings(
        [("DESCARTE HELLBOY", scfg.human_discard_zone), ("DESCARTE MEDUSA", scfg.bot_discard_zone)],
        [("HELLBOY", *scfg.human_card_spot), ("MEDUSA", scfg.bot_card_spot[0], scfg.bot_card_spot[2])],
        label_font=scfg.label_font))


def recover_after_reload(session: Session, client: TTSClient, targets: list[str],
                         position: tuple[float, float, float], rotation=ui.PANEL_ROTATION,
                         scale=ui.PANEL_SCALE, names: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """TTS recargo la partida (messageID 1): se comprueban los GUID de la configuracion y se recrea el panel.

    "stop" si falta alguno (la partida cargada no es esta: seguir seria escribir en una mesa ajena); "retry" si
    TTS aun no contesta; "ok" con el panel recreado y la mesa marcada para resincronizar."""
    try:
        found = client.call_lua(lua.inspect_guids(session.guids_in_use())) or {}
        found = found if isinstance(found, dict) else {}
        missing = [" o ".join(group) for group in session.guid_groups()
                   if not any((found.get(g) or {}).get("found") for g in group)]
        if missing:
            return "stop", [f"TTS recargo la partida y faltan objetos de la configuracion: {', '.join(missing)}. "
                            "Paro sin tocar la mesa; carga la partida correcta y reanuda con --resume."]
        client.call_lua(lua.create_panel(targets, position, rotation, scale, names,
                                         snapshot=session.snapshot_spec() if session.cfg.batch else None))
        mark_floor(client, session.cfg)
    except TABLE_ERRORS as e:
        return "retry", [f"TTS recargo la partida y aun no responde ({e}); reintento."]
    session.dirty = True
    return "ok", ["TTS recargo la partida: GUIDs comprobados y panel recreado. Pulsa Fin de accion para que "
                  "el bot relea la mesa."]


def run_loop(session: Session, client: TTSClient, stop: threading.Event, announce: Callable[[list[str]], None],
             poll: float = 0.1, recover: Recovery | None = None) -> None:
    """Pasa cada boton del panel a `Session.handle`; un evento raro o un fallo interno nunca mata la partida.

    Con `recover`, un messageID 1 (recarga de TTS) pausa los botones hasta comprobar la mesa; si falta algun
    GUID la partida se detiene de forma segura (sin escribir nada)."""
    reloading, held = False, []
    while not stop.is_set():
        events = held + client.poll_events()
        held = []
        if recover is not None and (reloading or client.take_reload()):
            status, msgs = recover()
            announce(msgs)
            if status == "stop":
                stop.set()
                return
            reloading = status == "retry"
            if reloading:
                held = events
                stop.wait(max(poll, 0.5))
                continue
        for n, raw in enumerate(events):
            if n and isinstance(raw, dict):                       # solo el primer clic trae una mesa todavia valida
                raw = {k: v for k, v in raw.items() if k != "snapshot"}
            try:
                event, payload = parse_event(raw)
            except (KeyError, ValueError, TypeError, AttributeError):
                announce([f"Evento desconocido ignorado: {raw!r}"])
                continue
            try:
                announce(session.handle(event, payload))
            except Exception:                                    # noqa: BLE001 - la partida debe seguir
                traceback.print_exc()
                announce(["Error interno del bot; la partida sigue. Repite el boton o usa Cancelar ataque."])
        if not events:
            stop.wait(poll)


def build_game(cfg: PlayConfig, first: str, seed: int) -> Game:
    game = Game.new(cfg.board, seed, controllers={}, medusa_player=BOT)
    if first in ("human", "bot"):
        game.turn = HUMAN if first == "human" else BOT
    game.begin_turn()
    return game


def play(cfg: PlayConfig, client: TTSClient, first: str, seed: int, stop: threading.Event,
         echo: Callable[[str], None] = print, poll: float = 0.1, state_path: Path | None = None,
         resume: bool = False, timing: bool = False) -> None:
    scfg = cfg.session_config()
    game = build_game(cfg, first, seed)
    session = Session(game, client, MedusaAI(BOT), scfg, bot=BOT)
    session.state_path = state_path
    session.first_mode = first
    session.new_game = lambda: build_game(cfg, first, secrets.randbelow(2 ** 31))
    if timing:
        session.timing = client.trace = lambda line: echo(f"[tiempo] {line}" if not line.startswith("[") else line)
    if resume:
        if state_path is None:
            raise persist.StateError("--resume necesita un fichero de guardado")
        session.load_dict(persist.load(state_path))
    targets = [f.fid for f in game.own(BOT)]
    client.call_lua(lua.clear_markings(remove_panel=True))     # restos de una ejecucion anterior que murio sin limpiar
    client.call_lua(lua.create_panel(targets, cfg.panel_position, cfg.panel_rotation, cfg.panel_scale,
                                     cfg.nicknames, snapshot=session.snapshot_spec() if scfg.batch else None))
    echo("Panel creado en la mesa. Esperando botones (Ctrl+C para salir).")
    try:
        mark_floor(client, scfg)
    except TABLE_ERRORS as e:
        echo(f"[aviso] no pude marcar las zonas en el suelo: {e}")
    announce = make_announcer(client, echo, to_table=not session.broadcast)   # con live_ui el anuncio ya va en el cierre del boton
    try:
        announce(session.resume() if resume else session.start())
        run_loop(session, client, stop, announce, poll,
                 recover=lambda: recover_after_reload(session, client, targets, cfg.panel_position,
                                              cfg.panel_rotation, cfg.panel_scale, cfg.nicknames))
    finally:
        try:
            client.call_lua(lua.clear_markings(remove_panel=True))
        except TABLE_ERRORS:
            pass


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m sparring.play", description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help="JSON con GUIDs, zonas, asientos y posiciones")
    ap.add_argument("--read-only", action="store_true", help="solo leer la mesa e imprimir un informe")
    ap.add_argument("--first", choices=("human", "bot", "random"), default="random",
                    help="quien empieza (por defecto, sorteo)")
    ap.add_argument("--seed", type=int, default=None, help="semilla del sorteo y los mazos (por defecto, al azar)")
    ap.add_argument("--send-port", type=int, default=SEND_PORT, help="puerto donde escucha TTS (39999)")
    ap.add_argument("--listen-port", type=int, default=LISTEN_PORT, help="puerto donde escucha el bot (39998)")
    ap.add_argument("--poll", type=float, default=0.1)
    ap.add_argument("--state", default=str(DEFAULT_STATE), help="guardado de la partida (se escribe tras cada boton)")
    ap.add_argument("--resume", action="store_true", help="reanuda la partida del guardado --state")
    ap.add_argument("--timing", action="store_true",
                    help="escribe, por boton y por accion del bot, los mensajes a TTS y el tiempo (y cada llamada)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None, stop: threading.Event | None = None) -> int:
    args = parse_args(argv)
    try:
        cfg = load_config(args.config)
        if not args.read_only:
            cfg.session_config()                     # falla antes de abrir puertos si falta algo
    except ConfigError as e:
        print(f"Configuracion: {e}", file=sys.stderr)
        return 2
    client = TTSClient(send_port=args.send_port, listen_port=args.listen_port)
    stop = stop or threading.Event()
    try:
        client.start_listening()
        if args.read_only:
            print("\n".join(read_only_report(client, cfg)))
            return 0
        seed = args.seed if args.seed is not None else secrets.randbelow(2 ** 31)
        state = Path(args.state)
        if not args.resume and state.exists():
            print(f"Aviso: {state} se sobrescribira con la partida nueva (usa --resume para reanudarla).")
        state.parent.mkdir(parents=True, exist_ok=True)
        play(cfg, client, args.first, seed, stop, poll=args.poll, state_path=state, resume=args.resume,
             timing=args.timing)
        return 0
    except (SessionError, persist.StateError) as e:
        print(f"No puedo empezar: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrumpido: cerrando.")
        return 130
    except (TTSLuaError, TimeoutError, OSError, ConfigError) as e:
        print(f"No pude hablar con TTS: {e}", file=sys.stderr)
        return 3
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
