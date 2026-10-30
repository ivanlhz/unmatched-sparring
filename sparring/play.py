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
import math
import re
import secrets
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .search.controller import make_bot_ai
from .board import Board
from .hero_detect import HeroDetectionError, detect_heroes, read_table
from .heroes import HeroDataError, load_hero
from . import persist
from .session import DEFAULT_BOT_PAUSE, DEFAULT_WILDFIRE_HOLD, TABLE_ERRORS, Msg, Session, SessionConfig, SessionError, piece_guids
from .state import DEFAULT_HEROES, Game
from .tts import lua, ui
from .tts.hero_table import HeroTableError, load_hero_table, table_defaults
from .tts.client import LISTEN_PORT, SEND_PORT, TTSClient, TTSLuaError
from .tts.ui import parse_event

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "partida.json"
DEFAULT_STATE = Path(__file__).resolve().parent.parent / "estado" / "sesion.json"
BOT, HUMAN = 0, 1
READ_ONLY_TAGS = frozenset({"snapshot", "piece_spaces_by_guid", "read_hand", "count_hand", "read_discard",
                            "read_face_down_cards", "read_cards_at", "inspect_guids", "read_health_dials", "zone_overlaps", "deck_identities",
                            "hand_identities", "reset_plan", "table_heroes", "inspect_objects"})

REQUIRED = ("bot_seat", "human_seat", "nicknames", "bot_card_spot", "human_card_spot", "bot_discard_spot",
            "bot_discard_zone", "bot_deck_guid", "human_discard_zone", "bot_deck_spot", "pieces")


SRC_DEFAULT, SRC_OPTION, SRC_CONFIG, SRC_SAVE, SRC_TABLE = ("defecto", "opcion de arranque", "configuracion",
                                                           "guardado", "mazos en la mesa")
HERO_AUTO = "auto"


def hero_setting(raw: dict, key: str) -> str | None:
    """Heroe fijado de un bando (`bot_hero` / `human_hero`); None si es `auto` o falta: hay que detectarlo."""
    v = raw.get(key)
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", HERO_AUTO)):
        return None
    return str(v)


def hero_pair(raw: dict) -> tuple[str, str]:
    """(heroe del bot, heroe del humano) de la configuracion; el que no este fijado cae a Medusa / Hellboy."""
    bot, human = hero_setting(raw, "bot_hero"), hero_setting(raw, "human_hero")
    if bot is None and human is None:
        return DEFAULT_HEROES
    if bot is None:        # el que falta no puede repetir al otro: cae al otro heroe por defecto
        return (DEFAULT_HEROES[0] if human != DEFAULT_HEROES[0] else DEFAULT_HEROES[1], human)
    if human is None:
        return (bot, DEFAULT_HEROES[1] if bot != DEFAULT_HEROES[1] else DEFAULT_HEROES[0])
    return bot, human


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
    warnings: list[str] = field(default_factory=list)      # avisos de la configuracion (se imprimen al arrancar)
    base: dict = field(default_factory=dict)                # la configuracion antes de `with_hero_data`
    sources: tuple[str, str] = (SRC_DEFAULT, SRC_DEFAULT)   # de donde sale el heroe de cada bando

    @property
    def heroes(self) -> tuple[str, str]:
        """(heroe del bot, heroe del humano): `bot_hero` / `human_hero` de la configuracion, por defecto Medusa vs
        Hellboy. Cada uno debe tener su data/heroes/<slug>.json."""
        return hero_pair(self.raw)

    @property
    def pending_heroes(self) -> tuple[bool, bool]:
        """Bandos cuyo heroe aun hay que detectar en la mesa (`auto` o sin escribir)."""
        return tuple(src == SRC_DEFAULT for src in self.sources)  # type: ignore[return-value]

    @property
    def hero_names(self) -> tuple[str, str]:
        """Nombre en mayusculas de cada bando para las etiquetas del suelo (el de su heroe)."""
        return tuple(load_hero(slug).name.upper() for slug in self.heroes)  # type: ignore[return-value]

    @property
    def fighter_ids(self) -> list[str]:
        """Ids de luchador de los dos bandos (el bot primero): claves de nicknames, pieces y dials."""
        return [f.fid for slug in self.heroes for f in load_hero(slug).fighters()]

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

    @property
    def attacker_ids(self) -> tuple[str, ...]:
        """Luchadores del humano: un boton "Ataca X" por cada uno (los nombres salen de los datos del heroe)."""
        return tuple(f.fid for f in load_hero(self.heroes[1]).fighters())

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
                bot_card_ids=tuple(r.get("bot_card_ids", lua.BOT_CARD_IDS)),
                human_card_ids=tuple(r.get("human_card_ids", lua.HUMAN_CARD_IDS)),
                deck_identity={side: tuple(tuple(p) for p in r[f"{side}_identity"])
                               for side in ("bot", "human") if r.get(f"{side}_identity")},
                bot_label=self.hero_names[0], human_label=self.hero_names[1],
                setup=bool(r.get("setup", True)), mulligan_bot=bool(r.get("mulligan_bot", True)),
                mulligan_human=bool(r.get("mulligan_human", True)),
                dead_spot=tuple(float(v) for v in r["dead_spot"]) if r.get("dead_spot") else None, off_board_dist=float(r.get("off_board_dist", 4.0)),
                adopt_after=int(r.get("adopt_after", 3)),
                bot_discard_step=tuple(r.get("bot_discard_step", (-3.6, 2.2))),
                bot_discard_rows=int(r.get("bot_discard_rows", 15)),
                bot_discard_rot_y=float(r.get("bot_discard_rot_y", 90.0)),
                human_deck_guid=r.get("human_deck_guid"),
                human_deck_spot=tuple(r["human_deck_spot"]) if r.get("human_deck_spot") else None,
                start_spaces=self._start_spaces(),
                bot_discard_bounds=tuple(float(v) for v in r["bot_discard_bounds"])
                if r.get("bot_discard_bounds") else None,
                human_dead_spot=tuple(float(v) for v in r["human_dead_spot"]) if r.get("human_dead_spot") else None,
                label_font=float(r.get("label_font", lua.LABEL_FONT)),
                look_spot=tuple(float(v) for v in r.get("look_spot", SessionConfig.look_spot)),
                look_step=tuple(float(v) for v in r.get("look_step", SessionConfig.look_step)),
                bot_row_spot=tuple(float(v) for v in r.get("bot_row_spot", SessionConfig.bot_row_spot)),
                bot_row_step=tuple(float(v) for v in r.get("bot_row_step", SessionConfig.bot_row_step)),
                look_rot_y=float(r["look_rot_y"]) if r.get("look_rot_y") is not None else None,
                token_spot=tuple(float(v) for v in r["token_spot"]) if r.get("token_spot") else None,
                bot_ongoing_spot=tuple(float(v) for v in r["bot_ongoing_spot"]) if r.get("bot_ongoing_spot") else None,
                human_ongoing_spot=tuple(float(v) for v in r["human_ongoing_spot"]) if r.get("human_ongoing_spot") else None,
                batch=bool(r.get("batch", True)), live_ui=bool(r.get("live_ui", True)),
                bot_pause=float(r.get("bot_pause", DEFAULT_BOT_PAUSE)),
                wildfire_hold=float(r.get("wildfire_hold", DEFAULT_WILDFIRE_HOLD)))
            if not (math.isfinite(cfg.bot_pause) and 0 <= cfg.bot_pause <= 30):
                raise ValueError("bot_pause: segundos entre 0 (sin pausa) y 30")
            if not (math.isfinite(cfg.wildfire_hold) and 0 <= cfg.wildfire_hold <= lua.MAX_HOLD):
                raise ValueError(f"wildfire_hold: segundos entre 0 (sin escena) y {lua.MAX_HOLD:g}")
            if cfg.token_spot is not None and len(cfg.token_spot) != 3:
                raise ValueError("token_spot: (x, y, z)")
            if cfg.bot_ongoing_spot is not None and len(cfg.bot_ongoing_spot) != 3:
                raise ValueError("bot_ongoing_spot: (x, y, z)")
            if cfg.human_ongoing_spot is not None and len(cfg.human_ongoing_spot) != 2:
                raise ValueError("human_ongoing_spot: (x, z)")
            if len(cfg.look_spot) != 3 or len(cfg.look_step) != 2:
                raise ValueError("look_spot: (x, y, z); look_step: (dx, dz)")
            if len(cfg.bot_row_spot) != 3 or len(cfg.bot_row_step) != 2:
                raise ValueError("bot_row_spot: (x, y, z); bot_row_step: (dx, dz)")
            if cfg.bot_discard_bounds is not None and len(cfg.bot_discard_bounds) != 5:
                raise ValueError("bot_discard_bounds: (centro x, centro z, tamano x, tamano z, rotY)")
            self._dry_build(cfg)
        except (KeyError, TypeError, ValueError) as e:
            raise ConfigError(f"configuracion no valida: {e}") from None
        for key in ("nicknames", "pieces"):
            missing = sorted(set(self.fighter_ids) - set(getattr(cfg, key)))
            if missing:
                raise ConfigError(f"faltan {key} de: {', '.join(missing)}")
        return cfg

    def _start_spaces(self) -> dict[str, int]:
        """Casillas de salida reales. Las claves son ids de luchador de un heroe (como siempre) o "bot" / "human"
        (el heroe de ese bando: sirve para cualquier par de heroes); el resultado va siempre por id de luchador."""
        hero_fid = {"bot": load_hero(self.heroes[0]).fid, "human": load_hero(self.heroes[1]).fid}
        valid = set(self.fighter_ids)
        out = {}
        for k, v in (self.raw.get("start_spaces") or {}).items():
            fid = hero_fid.get(str(k), str(k))
            if fid in valid:
                out[fid] = int(v)
            else:                             # una clave de otro heroe (de una config anterior) no cuenta, pero se dice
                self.warnings.append(f"start_spaces: la clave {k!r} no es de ningun luchador de {self.heroes[0]} / "
                                     f"{self.heroes[1]} ni bot / human: se ignora.")
        return out

    def _dry_build(self, cfg: SessionConfig) -> None:
        """Construye una vez cada script con la configuracion: un valor mal escrito falla aqui, no en mitad de la partida."""
        lua.read_hand(cfg.bot_seat), lua.read_hand(cfg.human_seat), lua.count_hand(cfg.human_seat)
        lua.read_discard(cfg.bot_discard_zone, [cfg.bot_deck_guid], [cfg.bot_deck_spot])
        lua.read_discard(cfg.human_discard_zone, [cfg.human_deck_guid] if cfg.human_deck_guid else [],
                         [cfg.human_deck_spot] if cfg.human_deck_spot else [])
        ident = (("https://example.invalid/face", "https://example.invalid/back"),)
        spots = [(cfg.bot_card_spot[0], cfg.bot_card_spot[2]), tuple(cfg.human_card_spot), tuple(cfg.bot_deck_spot)]
        scope = lua.Scope((cfg.bot_seat, cfg.human_seat), (cfg.bot_discard_zone, cfg.human_discard_zone), tuple(spots))
        lua.deal_cards(cfg.bot_deck_guid, 1, cfg.bot_seat, spot=cfg.bot_deck_spot, identity=ident)
        lua.discard_cards([0], [cfg.bot_discard_spot], cfg.bot_discard_rot_y, identity=ident, scope=scope)
        lua.reset_deck(cfg.bot_deck_guid, cfg.bot_deck_spot, cfg.bot_card_ids, identity=ident, scope=scope)
        lua.deck_identities([(cfg.bot_deck_guid, tuple(cfg.bot_deck_spot), cfg.bot_card_ids)])
        lua.play_card_face_down(0, cfg.bot_seat, *cfg.bot_card_spot, cfg.rot_y, identity=ident)
        lua.flip_card(cfg.bot_deck_guid, cfg.rot_y, identity=ident)
        lua.reset_plan([(cfg.bot_deck_guid, cfg.bot_deck_spot, cfg.bot_card_ids, ident)], scope=scope)
        lua.hand_identities(cfg.bot_seat, cfg.bot_card_ids)
        lua.read_face_down_cards(*cfg.human_card_spot, cfg.reveal_radius)
        for name in cfg.nicknames.values():
            lua.lua_str(name)
        guids = sorted({g for v in cfg.pieces.values() for g in piece_guids(v)})
        lua.piece_spaces_by_guid(self.board, guids)
        lua.move_piece(self.board, guids[0], next(iter(self.board.spaces)))
        lua.read_health_dials(sorted({*cfg.dials.values(), *([cfg.destiny_dial] if cfg.destiny_dial else [])}))
        lua.set_health_dials({g: 0 for g in {*cfg.dials.values(), *([cfg.destiny_dial] if cfg.destiny_dial else [])}})
        lua.return_hand_to_deck(cfg.bot_seat, cfg.bot_deck_guid, identity=ident)
        lua.shuffle_deck(cfg.bot_deck_guid, cfg.bot_deck_spot, identity=ident)
        if cfg.dead_spot is not None:
            if len(cfg.dead_spot) != 3:
                raise ValueError("dead_spot: (x, y, z)")
            lua.place_piece("abc", *cfg.dead_spot)
        lua.zone_overlaps([cfg.bot_discard_zone, cfg.human_discard_zone])


HERO_KEYS = ("nicknames", "pieces", "dials")       # por id de luchador: la configuracion afina lo que los datos dan
HERO_SCALARS = ("bot_deck_guid", "human_deck_guid", "destiny_dial", "bot_card_ids", "human_card_ids",
                "bot_identity", "human_identity")


def with_hero_data(raw: dict) -> dict:
    """Completa la configuracion de la mesa con lo propio de cada heroe (`data/tts/<slug>.json`): piezas, diales,
    nombres, GUID de mazos, rangos de CardID e identidad. Lo que la configuracion diga a mano manda (una
    `partida.json` antigua con todo escrito sigue valiendo); de los luchadores solo cuentan los de los dos heroes."""
    bot, human = hero_pair(raw)
    try:
        derived = table_defaults(bot, human)
        fids = {f.fid for slug in (bot, human) for f in load_hero(slug).fighters()}
    except (HeroTableError, HeroDataError) as e:
        raise ConfigError(str(e)) from None
    out = dict(raw)
    for key in HERO_KEYS:
        given = raw.get(key) if isinstance(raw.get(key), dict) else {}
        out[key] = {**derived[key], **{k: v for k, v in given.items() if k in fids}}
    for key in HERO_SCALARS:
        if key in derived and is_todo(raw.get(key)):
            out[key] = derived[key]
    return out


def load_config(path: str | Path, bot_hero: str | None = None, human_hero: str | None = None) -> PlayConfig:
    """`bot_hero` / `human_hero` (opciones de arranque) mandan sobre la configuracion; sin ninguno de los dos valores
    el heroe queda por detectar (`resolve_heroes`) y, mientras tanto, es el de por defecto."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(f"no puedo leer la configuracion {path}: {e}") from None
    sources = []
    for key, option in (("bot_hero", bot_hero), ("human_hero", human_hero)):
        if option:
            raw[key] = option
            sources.append(SRC_OPTION)
        else:
            sources.append(SRC_CONFIG if hero_setting(raw, key) else SRC_DEFAULT)
    return build_config(raw, tuple(sources))     # type: ignore[arg-type]


def build_config(raw: dict, sources: tuple[str, str]) -> PlayConfig:
    board_key = raw.get("board", "bprd-hq")
    if board_key not in lua.BOARD_GUIDS:
        raise ConfigError(f"tablero desconocido: {board_key!r}")
    if raw.get("board_guid") not in (None, lua.BOARD_GUIDS[board_key]):
        raise ConfigError(f"board_guid {raw['board_guid']!r} no es el del tablero {board_key} "
                          f"({lua.BOARD_GUIDS[board_key]})")
    full = with_hero_data(raw)
    todos = [k for k in REQUIRED if is_todo(full.get(k))]
    return PlayConfig(full, Board.load(board_key), todos, base=raw, sources=sources)


def resolve_heroes(client, cfg: PlayConfig, saved: tuple[str, str] | None = None,
                   echo: Callable[[str], None] = print) -> PlayConfig:
    """Fija el heroe de cada bando antes de `with_hero_data`: opcion de arranque > configuracion > guardado (al
    reanudar) > mazos de la mesa (solo lectura). Si la mesa no se puede leer, cae a Medusa / Hellboy con un aviso;
    si se lee y no esta claro, `HeroDetectionError`."""
    names = list(hero_pair(cfg.base))
    sources = list(cfg.sources)
    if saved:
        for i in (0, 1):
            if sources[i] == SRC_DEFAULT:
                names[i], sources[i] = saved[i], SRC_SAVE
    if SRC_DEFAULT in sources:
        fixed = tuple(None if src == SRC_DEFAULT else name for name, src in zip(names, sources))
        r, failure = cfg.raw, None
        if not (r.get("bot_deck_spot") and r.get("human_deck_spot")) or is_todo(r.get("human_deck_spot")):
            failure = "faltan bot_deck_spot y human_deck_spot"
        else:
            try:
                reading = read_table(ReadOnlyClient(client))
            except (TTSLuaError, TimeoutError, OSError, ValueError, TypeError, KeyError) as e:
                failure = f"fallo la lectura de la mesa ({e})"
        if failure:
            cfg.warnings.append(f"no pude detectar los heroes: {failure}. Uso {DEFAULT_HEROES[0]} / {DEFAULT_HEROES[1]} "
                                "para el bando sin fijar (fuerzalo con --bot-hero / --human-hero).")
        else:
            found = detect_heroes(reading, r["bot_deck_spot"], r["human_deck_spot"], fixed)
            for i in (0, 1):
                if sources[i] == SRC_DEFAULT:
                    names[i], sources[i] = found[i], SRC_TABLE
    raw = {**cfg.base, "bot_hero": names[0], "human_hero": names[1]}
    out = build_config(raw, tuple(sources))     # type: ignore[arg-type]
    out.warnings = list(cfg.warnings)
    echo(describe_heroes(out))
    return out


def describe_heroes(cfg: PlayConfig) -> str:
    names = [load_hero(slug).name for slug in cfg.heroes]
    src_b, src_h = cfg.sources
    if src_b == src_h:
        why = "por los mazos en la mesa" if src_b == SRC_TABLE else f"por {src_b}"
    else:
        why = f"bot: {src_b}; humano: {src_h}"
    return f"{'Heroes detectados' if SRC_TABLE in cfg.sources else 'Heroes'}: bot {names[0]}, humano {names[1]} ({why})"


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


def _titles(cfg: PlayConfig) -> dict[int, str]:
    return {c.card_id: c.title for slug in cfg.heroes for c in load_hero(slug).deck()}


def _bridge_objects(slug: str) -> dict[str, str]:
    """Label -> GUID of the objects whose live setup the effect bridge depends on (multi-state miniatures, two-faced
    tokens with their glued child, token sources); empty for a hero without any."""
    try:
        table = load_hero_table(slug)
    except HeroTableError:
        return {}
    found = {}
    for fid, f in table.fighters.items():
        if len(f.pieces) > 1:
            found.update({f"{slug} {fid} state {i}": g for i, g in enumerate(f.pieces, 1)})
    for name, spec in table.token_faces.items():
        found[f"{slug} token {name}"] = table.tokens[name]
        if spec.get("child"):
            found[f"{slug} token {name} child"] = spec["child"]
    for name in table.token_sources:
        found[f"{slug} token {name} (source)"] = table.tokens[name]
    return found


def _bridge_objects_report(read: Callable, cfg: PlayConfig) -> list[str]:
    wanted: dict[str, str] = {}
    for slug in dict.fromkeys(cfg.heroes):
        wanted.update(_bridge_objects(slug))
    if not wanted:
        return []
    rows = read("bridge objects", lambda: lua.inspect_objects(sorted(set(wanted.values())))) or {}
    rows = rows if isinstance(rows, dict) else {}
    out = ["-- bridge objects (type, rotation, states; verify live)"]
    for label, g in wanted.items():
        d = rows.get(g) or {"found": False}
        if not d.get("found"):
            out.append(f"  {label} {g}: not found as a top-level object (a glued child shows under its parent)")
            continue
        kids = ", ".join(f"{k.get('guid')} '{k.get('name', '')}'" for k in d.get("attached") or []) or "none"
        out.append(f"  {label} {g}: {d.get('type')} '{d.get('name', '')}' rot ({d['rot_x']:.0f}, {d['rot_y']:.0f}, "
                   f"{d['rot_z']:.0f}) state {d.get('state_id')} of {d.get('state_ids')} quantity {d.get('quantity')} "
                   f"attached: {kids}")
    return out


def read_only_report(client, cfg: PlayConfig) -> list[str]:
    """Lee la mesa y devuelve las lineas del informe. No cambia nada."""
    ro = client if isinstance(client, ReadOnlyClient) else ReadOnlyClient(client)
    raw, titles, out, warn = cfg.raw, _titles(cfg), [], []

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

    out.extend(_bridge_objects_report(read, cfg))

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
            if not to_table or getattr(m, "shown", False):
                continue
            for chunk in lua.ascii_text(m):
                try:
                    client.call_lua(lua.broadcast(chunk, getattr(m, "kind", lua.ChatKind.NEUTRAL)))
                except (TTSLuaError, TimeoutError, OSError) as e:
                    echo(f"[aviso] no pude mostrar el mensaje en la mesa: {e}")
                    return
    return announce


Recovery = Callable[[], tuple[str, list[str]]]      # -> ("ok" | "retry" | "stop", mensajes)


ONGOING_LABELS = ("ONGOING BOT", "ONGOING TUYO")   # floor labels of the bot's / the human's ONGOING zone (unique texts)


def mark_floor(client, scfg: SessionConfig) -> None:
    """Dibuja en el suelo las zonas de descarte, los puntos de combate y las zonas ONGOING configuradas (idempotente;
    solo en modo juego)."""
    cards = [(scfg.human_label, *scfg.human_card_spot), (scfg.bot_label, scfg.bot_card_spot[0], scfg.bot_card_spot[2])]
    if scfg.human_ongoing_spot is not None:
        cards.append((ONGOING_LABELS[1], *scfg.human_ongoing_spot))
    if scfg.bot_ongoing_spot is not None:
        cards.append((ONGOING_LABELS[0], scfg.bot_ongoing_spot[0], scfg.bot_ongoing_spot[2]))
    client.call_lua(lua.draw_markings(
        [(f"DESCARTE {scfg.human_label}", scfg.human_discard_zone), (f"DESCARTE {scfg.bot_label}", scfg.bot_discard_zone)],
        cards, label_font=scfg.label_font))


def _zone_rect(bounds) -> tuple[float, float, float, float]:
    cx, cz, w, d, rot = (float(v) for v in bounds)
    t = math.radians(rot)
    hx = abs(math.cos(t)) * w / 2 + abs(math.sin(t)) * d / 2
    hz = abs(math.sin(t)) * w / 2 + abs(math.cos(t)) * d / 2
    return cx - hx, cx + hx, cz - hz, cz + hz


def floor_layout(cfg: PlayConfig) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Rectangulos (x min, x max, z min, z max) de todo lo que se dibuja en el suelo: las cajas de descarte, de combate y
    ONGOING y sus etiquetas. Las zonas de descarte solo se conocen si la configuracion trae sus limites."""
    r, font = cfg.raw, float(cfg.raw.get("label_font", lua.LABEL_FONT))
    out: list[tuple[str, tuple[float, float, float, float]]] = []

    def label(text: str, cx: float, cz: float, w: float, d: float, rot: float) -> None:
        x, z, ex, ez = lua.label_position(cx, cz, w, d, rot, text, font)
        out.append((f"etiqueta {text}", (x - ex / 2, x + ex / 2, z - ez / 2, z + ez / 2)))
    w, d = lua.CARD_SIZE
    bot_name, human_name = cfg.hero_names
    for name, spot in ((bot_name, (r["bot_card_spot"][0], r["bot_card_spot"][2])), (human_name, r["human_card_spot"])):
        out.append((f"caja de combate {name}", (spot[0] - w / 2, spot[0] + w / 2, spot[1] - d / 2, spot[1] + d / 2)))
        label(name, spot[0], spot[1], w, d, 0.0)
    for name, key in ((ONGOING_LABELS[0], "bot_ongoing_spot"), (ONGOING_LABELS[1], "human_ongoing_spot")):
        if r.get(key):
            spot = (r[key][0], r[key][-1])
            out.append((f"caja {name}", (spot[0] - w / 2, spot[0] + w / 2, spot[1] - d / 2, spot[1] + d / 2)))
            label(name, spot[0], spot[1], w, d, 0.0)
    for name, key in ((f"DESCARTE {bot_name}", "bot_discard_bounds"), (f"DESCARTE {human_name}", "human_discard_bounds")):
        if r.get(key):
            out.append((f"zona {name}", _zone_rect(r[key])))
            cx, cz, bw, bd, rot = (float(v) for v in r[key])
            label(name, cx, cz, bw, bd, rot)
    return out


def floor_layout_warnings(cfg: PlayConfig) -> list[str]:
    """Avisos de arranque: ninguna etiqueta ni rectangulo del suelo puede quedar bajo el panel (el 27/10 las etiquetas
    las etiquetas del suelo se pintaban encima de sus botones)."""
    pos, scale = cfg.panel_position, cfg.panel_scale
    x0, x1, z0, z1 = lua.panel_footprint(pos, scale, ui.PANEL_WIDTH, ui.panel_height(len(cfg.fighter_ids)))
    warnings = []
    for name, (a0, a1, b0, b1) in floor_layout(cfg):
        if a0 < x1 and a1 > x0 and b0 < z1 and b1 > z0:
            warnings.append(f"{name} queda bajo el panel (x {x0:.1f}..{x1:.1f}, z {z0:.1f}..{z1:.1f}): "
                            "mueve panel_position o reduce panel_scale en la configuracion.")
    warnings += look_row_warnings(cfg, floor_layout(cfg))
    return warnings


LOOK_ROWS = {   # spot key -> (step key, default spot, default step, name in the warning)
    "look_spot": ("look_step", SessionConfig.look_spot, SessionConfig.look_step, "La fila de la mano del bot a la vista"),
    "bot_row_spot": ("bot_row_step", SessionConfig.bot_row_spot, SessionConfig.bot_row_step,
                     "La fila de la mano del bot de sus cartas"),
}


def look_row_rect(cfg: PlayConfig, n: int = 7, spot_key: str = "look_spot") -> tuple[float, float, float, float]:
    """Rectangulo (x min, x max, z min, z max) que ocupa una fila de la mano del bot (`look_spot` o `bot_row_spot`)
    con `n` cartas."""
    r = cfg.raw
    step_key, default_spot, default_step, _ = LOOK_ROWS[spot_key]
    x, _, z = (float(v) for v in r.get(spot_key, default_spot))
    dx, dz = (float(v) for v in r.get(step_key, default_step))
    rot = math.radians(float(r.get("look_rot_y", r.get("bot_discard_rot_y", 90.0))))
    w, d = lua.CARD_SIZE
    hx = abs(math.cos(rot)) * w / 2 + abs(math.sin(rot)) * d / 2
    hz = abs(math.sin(rot)) * w / 2 + abs(math.cos(rot)) * d / 2
    half = (n - 1) / 2
    return (x - half * abs(dx) - hx, x + half * abs(dx) + hx, z - half * abs(dz) - hz, z + half * abs(dz) + hz)


def look_row_warnings(cfg: PlayConfig, floor: list[tuple[str, tuple[float, float, float, float]]]) -> list[str]:
    """Aviso de arranque: las filas de la mano del bot (hasta 7 cartas) no pueden pisar el panel, las cajas de combate
    y ONGOING ni las zonas de descarte."""
    pos, scale = cfg.panel_position, cfg.panel_scale
    others = [("el panel", lua.panel_footprint(pos, scale, ui.PANEL_WIDTH, ui.panel_height(len(cfg.fighter_ids)))),
              *((name, rect) for name, rect in floor if name.startswith(("caja", "zona")))]
    out = []
    for spot_key, (*_, what) in LOOK_ROWS.items():
        a0, a1, b0, b1 = look_row_rect(cfg, 7, spot_key)
        out += [f"{what} ({spot_key}, x {a0:.1f}..{a1:.1f}, z {b0:.1f}..{b1:.1f}) pisa {name}: "
                f"mueve {spot_key} en la configuracion." for name, (x0, x1, z0, z1) in others
                if a0 < x1 and a1 > x0 and b0 < z1 and b1 > z0]
    return out


def recover_after_reload(session: Session, client: TTSClient, targets: list[str],
                         position: tuple[float, float, float], rotation=ui.PANEL_ROTATION,
                         scale=ui.PANEL_SCALE, names: dict[str, str] | None = None,
                         attackers: tuple[str, ...] | None = None) -> tuple[str, list[str]]:
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
        if attackers is None:
            attackers = tuple(f.fid for f in session.game.own(session.human, alive_only=False))
        client.call_lua(lua.create_panel(targets, position, rotation, scale, names,
                                         snapshot=session.snapshot_spec() if session.cfg.batch else None,
                                         attacker_ids=attackers, human_seat=session.cfg.human_seat))
        mark_floor(client, session.cfg)
        session.restore_look_row()
    except TABLE_ERRORS as e:
        return "retry", [f"TTS recargo la partida y aun no responde ({e}); reintento."]
    session.dirty = True
    return "ok", ["TTS recargo la partida: GUIDs comprobados y panel recreado. Pulsa Fin de accion para que "
                  "el bot relea la mesa."]


UNPACK_SPOTS = {"bot": (22.0, 2.5, -10.0), "human": (-22.0, 2.5, 10.5)}   # fuera de las manos (|x| >= 25) y de los descartes
UNPACK_STEP = (0.0, 0.0, 3.0)


def unpack_plan(cfg: PlayConfig) -> list[tuple]:
    """(clase, GUID de cada estado, bolsa interior, sitio, rango de CardID o None) de todo lo de los dos heroes. El mazo va
    a su sitio de mazo; lo demas, en fila desde `bot_unpack_spot` / `human_unpack_spot` cada `unpack_step`."""
    r, step = cfg.raw, [float(v) for v in cfg.raw.get("unpack_step", UNPACK_STEP)]
    out = []
    for slug, side in zip(cfg.heroes, ("bot", "human")):
        origin = r.get(f"{side}_unpack_spot") or UNPACK_SPOTS[side]
        deck_xz = r.get(f"{side}_deck_spot")
        table, n = load_hero_table(slug), 0
        for kind, guids in table.unpack_items():
            if kind == "deck" and deck_xz:
                out.append((kind, guids, table.inner_bag, (float(deck_xz[0]), float(origin[1]), float(deck_xz[1])),
                            table.card_ids))
                continue
            out.append((kind, guids, table.inner_bag, tuple(float(o) + n * d for o, d in zip(origin, step)), None))
            n += 1
    return out


def prepare_heroes(client, cfg: PlayConfig, echo: Callable[[str], None] = print) -> None:
    """Solo con --unpack (o "unpack": true) y nunca al reanudar: saca de la bolsa interior de cada heroe lo que falte en
    la mesa. Falta = no responde NINGUN GUID del objeto (todos sus estados) y, en un mazo, no hay ninguna pila suya en su
    sitio. Se saca unicamente de la bolsa con el GUID de bolsa del heroe; si no esta en la mesa no se hace nada y se avisa
    (el bot nunca saca nada de una bolsa infinita). Un solo mensaje a TTS."""
    plan = unpack_plan(cfg)
    res = client.call_lua(lua.unpack_from_bags(plan)) or {}
    taken, missing = list(res.get("taken") or []), list(res.get("missing") or [])
    if taken:
        echo(f"[bot] He sacado de su bolsa {len(taken)} objeto(s) de los heroes: {', '.join(taken)}.")
    for slug in cfg.heroes:
        table = load_hero_table(slug)
        lost = [g for _, guids in table.unpack_items() for g in guids[:1] if g in missing]
        if lost:
            echo(f"[aviso] Faltan en la mesa {', '.join(lost)} de {load_hero(slug).name} y su bolsa interior "
                 f"{table.inner_bag} no esta en la mesa (o no los contiene): colocalos a mano; el bot no saca nada de una "
                 "bolsa infinita.")


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
                announce([Msg(f"Evento desconocido ignorado: {raw!r}", lua.ChatKind.WARNING)])
                continue
            try:
                announce(session.handle(event, payload))
            except Exception:                                    # noqa: BLE001 - la partida debe seguir
                traceback.print_exc()
                announce([Msg("Error interno del bot; la partida sigue. Repite el boton o usa Cancelar ataque.", lua.ChatKind.WARNING)])
        if not events:
            stop.wait(poll)


def ai_config(cfg: PlayConfig, ai: str | None, ai_time: float | None) -> dict:
    """Config de la IA: la linea de comandos manda sobre las claves `ai` / `ai_time_budget` del JSON."""
    raw = dict(cfg.raw)
    if ai is not None:
        raw["ai"] = ai
    if ai_time is not None:
        raw["ai_time_budget"] = ai_time
    return raw


def build_game(cfg: PlayConfig, first: str, seed: int) -> Game:
    game = Game.new(cfg.board, seed, controllers={}, bot_player=BOT, heroes=cfg.heroes)
    if first in ("human", "bot"):
        game.turn = HUMAN if first == "human" else BOT
    game.begin_turn()
    return game


def play(cfg: PlayConfig, client: TTSClient, first: str, seed: int, stop: threading.Event,
         echo: Callable[[str], None] = print, poll: float = 0.1, state_path: Path | None = None,
         resume: bool = False, timing: bool = False, ai: str | None = None,
         ai_time: float | None = None, bot_pause: float | None = None, unpack: bool = False) -> None:
    scfg = cfg.session_config()
    if bot_pause is not None:
        if not (math.isfinite(bot_pause) and 0 <= bot_pause <= 30):
            raise SessionError("--bot-pause: segundos entre 0 (sin pausa) y 30")
        scfg.bot_pause = bot_pause
    if (unpack or cfg.raw.get("unpack") is True) and not resume:
        prepare_heroes(client, cfg, echo)
    game = build_game(cfg, first, seed)
    session = Session(game, client, make_bot_ai(ai_config(cfg, ai, ai_time), BOT), scfg, bot=BOT)
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
    for warning in floor_layout_warnings(cfg):
        echo(f"[aviso] {warning}")
    client.call_lua(lua.clear_markings(remove_panel=True))     # restos de una ejecucion anterior que murio sin limpiar
    client.call_lua(lua.create_panel(targets, cfg.panel_position, cfg.panel_rotation, cfg.panel_scale,
                                     cfg.nicknames, snapshot=session.snapshot_spec() if scfg.batch else None,
                                     attacker_ids=cfg.attacker_ids, human_seat=scfg.human_seat))
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
                                              cfg.panel_rotation, cfg.panel_scale, cfg.nicknames,
                                              attackers=cfg.attacker_ids))
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
    ap.add_argument("--ai", choices=("heuristic", "ismcts"), default=None,
                    help="IA del bot (manda sobre la clave ai de la configuracion; por defecto heuristic)")
    ap.add_argument("--ai-time", type=float, default=None, help="segundos de busqueda por decision con --ai ismcts (1.5)")
    ap.add_argument("--resume", action="store_true", help="reanuda la partida del guardado --state")
    ap.add_argument("--bot-pause", type=float, default=None, metavar="SEGUNDOS",
                    help="pausa entre las acciones del turno del bot y antes de tu turno (manda sobre bot_pause de "
                         f"la configuracion; por defecto {DEFAULT_BOT_PAUSE:g}; 0 la desactiva)")
    ap.add_argument("--unpack", action="store_true",
                    help="antes de jugar, saca de la bolsa interior de cada heroe lo que falte en la mesa (tambien "
                         '"unpack": true en la configuracion); nunca al reanudar con --resume')
    ap.add_argument("--bot-hero", default=None, metavar="SLUG",
                    help="heroe del bot (slug de data/heroes: medusa, hellboy, abe-sapien, baba-yaga, liz-sherman); manda "
                         "sobre bot_hero de la configuracion y sobre la deteccion en la mesa")
    ap.add_argument("--human-hero", default=None, metavar="SLUG", help="heroe del humano (como --bot-hero)")
    ap.add_argument("--timing", action="store_true",
                    help="escribe, por boton y por accion del bot, los mensajes a TTS y el tiempo (y cada llamada)")
    return ap.parse_args(argv)


def saved_heroes(state_path: str | Path) -> tuple[str, str] | None:
    """Heroes (bot, humano) que guardo la partida; None si no los guarda (guardado anterior) o no existe."""
    try:
        heroes = persist.load(state_path).get("heroes")
    except persist.StateError:
        return None          # el error de verdad lo da `Session.load_dict` al reanudar
    return (str(heroes[0]), str(heroes[1])) if isinstance(heroes, list) and len(heroes) == 2 else None


def main(argv: list[str] | None = None, stop: threading.Event | None = None) -> int:
    args = parse_args(argv)
    try:
        cfg = load_config(args.config, args.bot_hero, args.human_hero)
        if not args.read_only:
            cfg.session_config()                     # falla antes de abrir puertos si falta algo
    except ConfigError as e:
        print(f"Configuracion: {e}", file=sys.stderr)
        return 2
    for warning in cfg.warnings:
        print(f"Aviso: {warning}", file=sys.stderr)
    printed = set(cfg.warnings)
    client = TTSClient(send_port=args.send_port, listen_port=args.listen_port)
    stop = stop or threading.Event()
    try:
        client.start_listening()
        try:
            saved = saved_heroes(args.state) if args.resume and not args.read_only else None
            cfg = resolve_heroes(client, cfg, saved)
            if not args.read_only:
                cfg.session_config()
        except (HeroDetectionError, ConfigError, persist.StateError, SessionError) as e:
            print(f"No puedo empezar: {e}", file=sys.stderr)
            return 2
        for warning in dict.fromkeys(cfg.warnings):
            if warning not in printed:
                print(f"Aviso: {warning}", file=sys.stderr)
        if args.read_only:
            print("\n".join(read_only_report(client, cfg)))
            return 0
        seed = args.seed if args.seed is not None else secrets.randbelow(2 ** 31)
        state = Path(args.state)
        if not args.resume and state.exists():
            print(f"Aviso: {state} se sobrescribira con la partida nueva (usa --resume para reanudarla).")
        state.parent.mkdir(parents=True, exist_ok=True)
        play(cfg, client, args.first, seed, stop, poll=args.poll, state_path=state, resume=args.resume,
             timing=args.timing, ai=args.ai, ai_time=args.ai_time, bot_pause=args.bot_pause,
             unpack=args.unpack)
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
