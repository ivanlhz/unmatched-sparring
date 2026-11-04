"""Entry point of the live game.

    python -m sparring.play --config config\\game.json              # play: panel + event loop
    python -m sparring.play --config config\\game.json --read-only  # only read the table and print a report

`--read-only` sends nothing that changes the table: a wrapper lets through only the read builders
(piece_spaces_by_guid, read_hand, count_hand, read_discard, read_face_down_cards, inspect_guids,
read_health_dials, zone_overlaps). It is meant for the first live test: it confirms GUIDs, seats and positions before
the bot is allowed to touch anything.

Everything the player reads on the console (warnings, errors, the read-only report, `--help`) is a tag of the language
catalogs, like the chat and the panel.
"""
from __future__ import annotations

import argparse
import errno
import json
import math
import os
import re
import secrets
import sys
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .search.controller import make_bot_ai
from .board import Board, catalog as board_catalog
from .board_detect import BoardError, choose_board
from .hero_detect import HeroDetectionError, detect_heroes, detected_decks, read_table
from .heroes import HeroDataError, load_hero
from . import game_log, i18n, persist, table_prep
from .i18n import t
from .session import DEFAULT_ACTION_ANNOUNCE_HOLD, DEFAULT_BOT_PAUSE, DEFAULT_ONGOING_HOLD, DEFAULT_WILDFIRE_HOLD, TABLE_ERRORS, Msg, Session, SessionConfig, SessionError, deck_where, piece_guids
from .state import DEFAULT_HEROES, Game
from .session_translators import ASIDE_STEP
from .tts import lua, ui
from .tts.hero_table import HeroTableError, load_hero_table, table_defaults
from .tts.client import LISTEN_PORT, SEND_PORT, TTSClient, TTSLuaError
from .tts.ui import parse_event

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "table.json"
ROOT = Path(__file__).resolve().parent.parent
LEGACY_CONFIG = ROOT / "config" / "partida.json"           # the Spanish names of before the repo went English
LEGACY_STATE = ROOT / "estado" / "sesion.json"
FROZEN = bool(getattr(sys, "frozen", False))        # the PyInstaller build of the desktop launcher (launcher/)


def state_dir(frozen: bool = FROZEN) -> Path:
    """Where the save goes by default. From the repo, the `state` folder next to the code; from the frozen executable the code
    sits in a folder that may not be writable (Program Files), so the save goes under the user's local app data."""
    if not frozen:
        return ROOT / "state"
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "UnmatchedSparring" / "state"


DEFAULT_STATE = state_dir() / "session.json"
LAUNCHED = False                                   # set by launcher_mode: the console is the launcher window, not a terminal
STATUS_PREFIX = "[sparring:status]"                 # --launcher: one machine-readable line per change of state


LEGACY_LOG = "partida.log"


def migrate_legacy_files(state: Path) -> list[str]:
    """Moves, once, a game saved under the old Spanish names to the new ones, so there is never an old+new pair:
    `estado/sesion.json` -> `state/session.json` (only when `state` is the default one and the new file does not
    exist) and the `partida.log` next to the save in use -> `session.log`. Returns the notices to print."""
    notices = []
    if state == DEFAULT_STATE and LEGACY_STATE.exists() and not DEFAULT_STATE.exists():
        DEFAULT_STATE.parent.mkdir(parents=True, exist_ok=True)
        LEGACY_STATE.replace(DEFAULT_STATE)
        notices.append(t("console.moved_state", old=LEGACY_STATE, new=DEFAULT_STATE))
        old_log, new_log = LEGACY_STATE.with_name(LEGACY_LOG), DEFAULT_STATE.with_name(game_log.LOG_NAME)
    else:
        old_log, new_log = state.with_name(LEGACY_LOG), state.with_name(game_log.LOG_NAME)
    if old_log.exists() and not new_log.exists():
        new_log.parent.mkdir(parents=True, exist_ok=True)
        old_log.replace(new_log)
        notices.append(t("console.moved_log", old=old_log, new=new_log))
    return notices
BOT, HUMAN = 0, 1
READ_ONLY_TAGS = frozenset({"snapshot", "piece_spaces_by_guid", "read_hand", "count_hand", "read_discard",
                            "read_face_down_cards", "read_cards_at", "inspect_guids", "read_health_dials", "zone_overlaps", "deck_identities",
                            "hand_identities", "reset_plan", "table_heroes", "inspect_objects", "find_pieces_by_name", "find_dials_by_name", "list_boards"})

REQUIRED = ("bot_seat", "human_seat", "nicknames", "bot_card_spot", "human_card_spot", "bot_discard_spot",
            "bot_discard_zone", "bot_deck_guid", "human_discard_zone", "bot_deck_spot", "pieces")


SRC_DEFAULT, SRC_OPTION, SRC_CONFIG, SRC_SAVE, SRC_TABLE = ("default", "option", "config", "save", "table")
HERO_AUTO = "auto"


def _deck_zone(raw: dict, key: str) -> str | None:
    """GUID of a deck Scripting zone (`bot_deck_zone` / `human_deck_zone`); empty, missing or TODO means none."""
    v = raw.get(key)
    if is_todo(v) or (isinstance(v, str) and not v.strip()):
        return None
    if not isinstance(v, str):
        raise ValueError(t("cfg.deck_zone_bad", key=key, value=v))
    return v.strip()


def _deck_zones(raw: dict) -> dict[str, str]:
    zones = {side: _deck_zone(raw, f"{side}_deck_zone") for side in ("bot", "human")}
    return {side: g for side, g in zones.items() if g}


def hero_setting(raw: dict, key: str) -> str | None:
    """The hero fixed for a side (`bot_hero` / `human_hero`); None if it is `auto` or missing: it has to be detected."""
    v = raw.get(key)
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", HERO_AUTO)):
        return None
    return str(v)


def hero_pair(raw: dict) -> tuple[str, str]:
    """(bot hero, human hero) from the configuration; the one that is not fixed falls back to Medusa / Hellboy."""
    bot, human = hero_setting(raw, "bot_hero"), hero_setting(raw, "human_hero")
    if bot is None and human is None:
        return DEFAULT_HEROES
    if bot is None:        # the missing one cannot repeat the other: it falls to the other default hero
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
    warnings: list[str] = field(default_factory=list)      # configuration warnings (printed at start-up)
    base: dict = field(default_factory=dict)                # the configuration before `with_hero_data`
    sources: tuple[str, str] = (SRC_DEFAULT, SRC_DEFAULT)   # where each side's hero comes from
    detected_decks: dict[str, str] = field(default_factory=dict)   # side -> GUID of the deck the start-up read found
    saved_zones: dict[str, str] = field(default_factory=dict)      # discard zones the bot created in an earlier run (state file)

    @property
    def language(self) -> str:
        """Language of the panel and the chat: `language` of the configuration (or `--language`); an unknown one is Spanish."""
        value = self.raw.get("language")
        return value if value in i18n.available() else i18n.DEFAULT

    @property
    def heroes(self) -> tuple[str, str]:
        """(bot hero, human hero): `bot_hero` / `human_hero` of the configuration, Medusa vs Hellboy by default. Each
        one needs its data/heroes/<slug>.json."""
        return hero_pair(self.raw)

    @property
    def pending_heroes(self) -> tuple[bool, bool]:
        """Sides whose hero still has to be detected on the table (`auto` or not written)."""
        return tuple(src == SRC_DEFAULT for src in self.sources)  # type: ignore[return-value]

    @property
    def hero_names(self) -> tuple[str, str]:
        """Upper-case name of each side for the floor labels (its hero's)."""
        return tuple(load_hero(slug).name.upper() for slug in self.heroes)  # type: ignore[return-value]

    @property
    def fighter_ids(self) -> list[str]:
        """Fighter ids of both sides (the bot first): the keys of nicknames, pieces and dials."""
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
        """The human's fighters: one "Attack X" button each (the names come from the hero data)."""
        return tuple(f.fid for f in load_hero(self.heroes[1]).fighters())

    def session_config(self) -> SessionConfig:
        """The session configuration; it only exists if no TODO is left and everything validates."""
        if self.todos:
            raise ConfigError(t("cfg.todos", todos=", ".join(self.todos)))
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
                bot_deck_zone=_deck_zone(r, "bot_deck_zone"), human_deck_zone=_deck_zone(r, "human_deck_zone"),
                deck_radius=float(r.get("deck_radius", lua.DECK_RADIUS)),
                bot_deck_hint=self.detected_decks.get("bot"), human_deck_hint=self.detected_decks.get("human"),
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
                bot_tuck_spot=tuple(float(v) for v in r["bot_tuck_spot"]) if r.get("bot_tuck_spot") else None,
                bot_removed_spot=tuple(float(v) for v in r["bot_removed_spot"]) if r.get("bot_removed_spot") else None,
                batch=bool(r.get("batch", True)), live_ui=bool(r.get("live_ui", True)),
                bot_pause=float(r.get("bot_pause", DEFAULT_BOT_PAUSE)),
                wildfire_hold=float(r.get("wildfire_hold", DEFAULT_WILDFIRE_HOLD)),
                ongoing_hold=float(r.get("ongoing_hold", DEFAULT_ONGOING_HOLD)),
                action_announce_hold=float(r.get("action_announce_hold", DEFAULT_ACTION_ANNOUNCE_HOLD)),
                card_zoom=bool(r.get("card_zoom", True)),
                card_zoom_seconds=float(r.get("card_zoom_seconds", SessionConfig.card_zoom_seconds)),
                card_zoom_scale=float(r.get("card_zoom_scale", SessionConfig.card_zoom_scale)),
                card_zoom_spot=tuple(float(v) for v in r.get("card_zoom_spot", SessionConfig.card_zoom_spot)),
                card_zoom_rot=tuple(float(v) for v in r["card_zoom_rot"]) if r.get("card_zoom_rot") else None,
                zone_spawns=table_prep.zone_spawns(r), remove_plan=table_prep.removal_plan(r), remove_limits=table_prep.removal_limits(r))
            if not (math.isfinite(cfg.bot_pause) and 0 <= cfg.bot_pause <= 30):
                raise ValueError(t("cfg.range.pause", key="bot_pause", max=30))
            if not (math.isfinite(cfg.wildfire_hold) and 0 <= cfg.wildfire_hold <= lua.MAX_HOLD):
                raise ValueError(t("cfg.range.scene", key="wildfire_hold", max=lua.MAX_HOLD))
            if not (math.isfinite(cfg.action_announce_hold) and 0 <= cfg.action_announce_hold <= lua.MAX_HOLD):
                raise ValueError(t("cfg.range.pause", key="action_announce_hold", max=lua.MAX_HOLD))
            if not (math.isfinite(cfg.ongoing_hold) and 0 <= cfg.ongoing_hold <= lua.MAX_HOLD):
                raise ValueError(t("cfg.range.pause", key="ongoing_hold", max=lua.MAX_HOLD))
            if len(cfg.card_zoom_spot) != 3 or (cfg.card_zoom_rot is not None and len(cfg.card_zoom_rot) != 3):
                raise ValueError("card_zoom_spot: (x, y, z); card_zoom_rot: (x, y, z)")
            if not (0 < cfg.card_zoom_seconds <= lua.MAX_ZOOM_SECONDS and 0 < cfg.card_zoom_scale <= lua.MAX_ZOOM_SCALE):
                raise ValueError(t("cfg.range.zoom", seconds=lua.MAX_ZOOM_SECONDS, scale=lua.MAX_ZOOM_SCALE))
            if cfg.token_spot is not None and len(cfg.token_spot) != 3:
                raise ValueError("token_spot: (x, y, z)")
            if cfg.bot_ongoing_spot is not None and len(cfg.bot_ongoing_spot) != 3:
                raise ValueError("bot_ongoing_spot: (x, y, z)")
            if cfg.human_ongoing_spot is not None and len(cfg.human_ongoing_spot) != 2:
                raise ValueError("human_ongoing_spot: (x, z)")
            for key in ("bot_tuck_spot", "bot_removed_spot"):
                if getattr(cfg, key) is not None and len(getattr(cfg, key)) != 3:
                    raise ValueError(f"{key}: (x, y, z)")
            if len(cfg.look_spot) != 3 or len(cfg.look_step) != 2:
                raise ValueError("look_spot: (x, y, z); look_step: (dx, dz)")
            if len(cfg.bot_row_spot) != 3 or len(cfg.bot_row_step) != 2:
                raise ValueError("bot_row_spot: (x, y, z); bot_row_step: (dx, dz)")
            if cfg.bot_discard_bounds is not None and len(cfg.bot_discard_bounds) != 5:
                raise ValueError(t("cfg.bounds"))
            self._dry_build(cfg)
        except (KeyError, TypeError, ValueError) as e:
            raise ConfigError(t("cfg.invalid", error=e)) from None
        for key in ("nicknames", "pieces"):
            missing = sorted(set(self.fighter_ids) - set(getattr(cfg, key)))
            if missing:
                raise ConfigError(t("cfg.missing_key", key=key, fighters=", ".join(missing)))
        return cfg

    def _start_spaces(self) -> dict[str, int]:
        """The real starting spaces. The keys are fighter ids of a hero (as always) or "bot" / "human" (the hero of
        that side: works for any pair of heroes); the result is always keyed by fighter id."""
        hero_fid = {"bot": load_hero(self.heroes[0]).fid, "human": load_hero(self.heroes[1]).fid}
        valid = set(self.fighter_ids)
        out = {}
        for k, v in (self.raw.get("start_spaces") or {}).items():
            fid = hero_fid.get(str(k), str(k))
            if fid in valid:
                out[fid] = int(v)
            else:                             # a key of another hero (from an older config) does not count, but it is said
                self.warnings.append(t("cfg.start_space_ignored", key=k, bot=self.heroes[0], human=self.heroes[1]))
        return out

    def _dry_build(self, cfg: SessionConfig) -> None:
        """Builds every script once with the configuration: a badly written value fails here, not in mid-game."""
        lua.read_hand(cfg.bot_seat), lua.read_hand(cfg.human_seat), lua.count_hand(cfg.human_seat)
        lua.read_discard(cfg.bot_discard_zone, [cfg.bot_deck_guid], [cfg.bot_deck_spot],
                         exclude_zones=[cfg.bot_deck_zone] if cfg.bot_deck_zone else [])
        lua.read_discard(cfg.human_discard_zone, [cfg.human_deck_guid] if cfg.human_deck_guid else [],
                         [cfg.human_deck_spot] if cfg.human_deck_spot else [],
                         exclude_zones=[cfg.human_deck_zone] if cfg.human_deck_zone else [])
        ident = (("https://example.invalid/face", "https://example.invalid/back"),)
        spots = [(cfg.bot_card_spot[0], cfg.bot_card_spot[2]), tuple(cfg.human_card_spot), tuple(cfg.bot_deck_spot)]
        scope = lua.Scope((cfg.bot_seat, cfg.human_seat), (cfg.bot_discard_zone, cfg.human_discard_zone), tuple(spots))
        lua.deal_cards(cfg.bot_deck_guid, 1, cfg.bot_seat, spot=cfg.bot_deck_spot, identity=ident,
                       zone=cfg.bot_deck_zone, radius=cfg.deck_radius)
        lua.discard_cards([0], [cfg.bot_discard_spot], cfg.bot_discard_rot_y, identity=ident, scope=scope)
        lua.reset_deck(cfg.bot_deck_guid, cfg.bot_deck_spot, cfg.bot_card_ids, identity=ident, scope=scope,
                       zone=cfg.bot_deck_zone)
        lua.deck_identities([(cfg.bot_deck_guid, tuple(cfg.bot_deck_spot), cfg.bot_card_ids, cfg.bot_deck_zone)])
        lua.play_card_face_down(0, cfg.bot_seat, *cfg.bot_card_spot, cfg.rot_y, identity=ident)
        lua.flip_card(cfg.bot_deck_guid, cfg.rot_y, identity=ident)
        lua.reset_plan([(cfg.bot_deck_guid, cfg.bot_deck_spot, cfg.bot_card_ids, ident, cfg.bot_deck_zone)], scope=scope)
        lua.hand_identities(cfg.bot_seat, cfg.bot_card_ids)
        lua.read_face_down_cards(*cfg.human_card_spot, cfg.reveal_radius)
        for name in cfg.nicknames.values():
            lua.lua_str(name)
        guids = sorted({g for v in cfg.pieces.values() for g in piece_guids(v)})
        lua.piece_spaces_by_guid(self.board, guids)
        lua.move_piece(self.board, guids[0], next(iter(self.board.spaces)))
        lua.read_health_dials(sorted({*cfg.dials.values(), *([cfg.destiny_dial] if cfg.destiny_dial else [])}))
        lua.set_health_dials({g: 0 for g in {*cfg.dials.values(), *([cfg.destiny_dial] if cfg.destiny_dial else [])}})
        lua.return_hand_to_deck(cfg.bot_seat, cfg.bot_deck_guid, identity=ident, zone=cfg.bot_deck_zone)
        lua.shuffle_deck(cfg.bot_deck_guid, cfg.bot_deck_spot, identity=ident, zone=cfg.bot_deck_zone)
        if cfg.dead_spot is not None:
            if len(cfg.dead_spot) != 3:
                raise ValueError("dead_spot: (x, y, z)")
            lua.place_piece("abc", *cfg.dead_spot)
        lua.zone_overlaps([cfg.bot_discard_zone, cfg.human_discard_zone])


HERO_KEYS = ("nicknames", "pieces", "dials")       # by fighter id: the configuration refines what the data gives
HERO_SCALARS = ("bot_deck_guid", "human_deck_guid", "destiny_dial", "bot_card_ids", "human_card_ids",
                "bot_identity", "human_identity")


def with_hero_data(raw: dict) -> dict:
    """Completes the table configuration with what is specific to each hero (`data/tts/<slug>.json`): pieces, dials,
    names, deck GUIDs, CardID ranges and identity. What the configuration says by hand wins (an old `partida.json` with
    everything written still works); of the fighters only those of the two heroes count."""
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


def load_config(path: str | Path, bot_hero: str | None = None, human_hero: str | None = None,
                language: str | None = None) -> PlayConfig:
    """`bot_hero` / `human_hero` (launch options) win over the configuration; with neither value the hero is left to
    be detected (`resolve_heroes`) and, meanwhile, is the default one. `language` (`--language`) wins over the
    `language` key."""
    i18n.set_language(language)                    # the messages of this function come out in the requested language
    path = Path(path)
    legacy_name = path.name == LEGACY_CONFIG.name
    if legacy_name and not path.exists() and path.with_name(DEFAULT_CONFIG.name).exists():
        path = path.with_name(DEFAULT_CONFIG.name)   # a command line written for the old file name keeps working
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError(t("cfg.unreadable", path=path, error=e)) from None
    if not language:
        i18n.set_language(raw.get("language"))
    sources = []
    for key, option in (("bot_hero", bot_hero), ("human_hero", human_hero)):
        if option:
            raw[key] = option
            sources.append(SRC_OPTION)
        else:
            sources.append(SRC_CONFIG if hero_setting(raw, key) else SRC_DEFAULT)
    if language:
        raw["language"] = language
    cfg = build_config(raw, tuple(sources))     # type: ignore[arg-type]
    if legacy_name:
        cfg.warnings.append(t("console.legacy_config", old=LEGACY_CONFIG.name, new=DEFAULT_CONFIG.name))
    if raw.get("language") not in (None, *i18n.available()):
        cfg.warnings.append(t("cfg.language_unknown", value=raw["language"], default=i18n.DEFAULT))
    return cfg


def build_config(raw: dict, sources: tuple[str, str], found_board_guid: str | None = None) -> PlayConfig:
    board_key = raw.get("board", "bprd-hq")
    if board_key not in {e.key for e in board_catalog() if e.status == "supported"}:
        raise ConfigError(t("cfg.unknown_board", board=board_key))
    expected = lua.BOARD_GUIDS.get(board_key)
    if not found_board_guid and raw.get("board_guid") not in (None, expected):
        raise ConfigError(t("cfg.board_guid", guid=raw["board_guid"], board=board_key,
                            expected=expected or t("cfg.board_guid_none")))
    full = with_hero_data(raw)
    todos = [k for k in REQUIRED if is_todo(full.get(k))]
    board = Board.load(board_key)
    board.guid = found_board_guid or raw.get("board_guid")
    return PlayConfig(full, board, todos, base=raw, sources=sources)


def detect_board(client, cfg: PlayConfig, echo: Callable[[str], None] = print) -> PlayConfig:
    """Finds the map on the table by its image (read only) and rebuilds the configuration on it, with the board's real
    GUID. `BoardError` when the board is unknown, excluded or unverified."""
    found = ReadOnlyClient(client).call_lua(lua.list_boards())
    entry, guid = choose_board(found if isinstance(found, list) else [], board_catalog())
    out = build_config({**cfg.base, "board": entry.key}, cfg.sources, found_board_guid=guid)
    out.warnings = list(cfg.warnings)
    echo(t("board.found", name=entry.name))
    return out


def resolve_heroes(client, cfg: PlayConfig, saved: tuple[str, str] | None = None,
                   echo: Callable[[str], None] = print) -> PlayConfig:
    """Fixes each side's hero before `with_hero_data`: launch option > configuration > saved game (when resuming) >
    decks on the table (read only). If the table cannot be read, falls back to Medusa / Hellboy with a warning; if it
    is read and unclear, `HeroDetectionError`."""
    names = list(hero_pair(cfg.base))
    sources = list(cfg.sources)
    reading, r = None, cfg.raw
    if saved:
        for i in (0, 1):
            if sources[i] == SRC_DEFAULT:
                names[i], sources[i] = saved[i], SRC_SAVE
    if SRC_DEFAULT in sources:
        fixed = tuple(None if src == SRC_DEFAULT else name for name, src in zip(names, sources))
        failure = None
        if not (r.get("bot_deck_spot") and r.get("human_deck_spot")) or is_todo(r.get("human_deck_spot")):
            failure = t("herosel.no_spots")
        else:
            try:
                reading = read_table(ReadOnlyClient(client), _deck_zones(r))
                # the loose objects the fresh start removes (the official save's two centre decks) are not hero decks
                removed = {g for g, _ in table_prep.removal_plan(r)}
                reading.piles = [p for p in reading.piles if p.get("guid") not in removed]
            except (TTSLuaError, TimeoutError, OSError, ValueError, TypeError, KeyError) as e:
                failure = t("herosel.read_failed", error=e)
        if failure:
            cfg.warnings.append(t("herosel.undetected", why=failure, bot=DEFAULT_HEROES[0], human=DEFAULT_HEROES[1]))
        else:
            found = detect_heroes(reading, r["bot_deck_spot"], r["human_deck_spot"], fixed)
            for i in (0, 1):
                if sources[i] == SRC_DEFAULT:
                    names[i], sources[i] = found[i], SRC_TABLE
    raw = {**cfg.base, "bot_hero": names[0], "human_hero": names[1]}
    out = build_config(raw, tuple(sources), found_board_guid=cfg.board.guid)     # type: ignore[arg-type]
    out.warnings = list(cfg.warnings)
    if reading is not None:
        out.detected_decks = detected_decks(reading, out.heroes, r["bot_deck_spot"], r["human_deck_spot"],
                                            float(r.get("deck_radius", lua.DECK_RADIUS)), _deck_zones(r))
    echo(describe_heroes(out))
    return out


def describe_heroes(cfg: PlayConfig) -> str:
    names = [load_hero(slug).name for slug in cfg.heroes]
    src_b, src_h = (t(f"herosel.src.{src}") for src in cfg.sources)
    if src_b == src_h:
        why = t("herosel.why.table") if cfg.sources[0] == SRC_TABLE else t("herosel.why.same", src=src_b)
    else:
        why = t("herosel.why.mixed", bot=src_b, human=src_h)
    line = "herosel.line.detected" if SRC_TABLE in cfg.sources else "herosel.line.plain"
    return t(line, bot=names[0], human=names[1], why=why)


# ---------- read-only mode ----------
class ReadOnlyClient:
    """Wraps the client and only lets read scripts through; it exposes neither `send` nor `execute_lua`."""

    def __init__(self, client: TTSClient):
        self._client = client

    def call_lua(self, script: str, *a, **kw):
        tag = re.match(r"-- sparring:(\w+)", script)
        if not tag or tag.group(1) not in READ_ONLY_TAGS:
            raise ReadOnlyViolation(f"read-only mode: script not allowed ({script[:40]!r})")
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
    """Reads the table and returns the report lines. Changes nothing."""
    ro = client if isinstance(client, ReadOnlyClient) else ReadOnlyClient(client)
    raw, titles, out, warn = cfg.raw, _titles(cfg), [], []

    def val(key):
        v = raw.get(key)
        return None if is_todo(v) else v

    def show_ids(rows) -> str:
        return ", ".join(titles.get(r["id"], f"?{r['id']}") for r in rows) or t("ro.empty")

    def read(label: str, builder: Callable[[], str]):
        try:
            return ro.call_lua(builder())
        except ReadOnlyViolation:
            raise
        except (TTSLuaError, TimeoutError, ValueError, TypeError) as e:
            warn.append(t("ro.w.read_failed", label=label, error=e))
            return None

    out.append(t("ro.header"))
    guids = {t("ro.label.board"): lua.board_guid(cfg.board), t("ro.label.bot_deck"): val("bot_deck_guid"),
             t("ro.label.bot_discard"): val("bot_discard_zone"), t("ro.label.human_discard"): val("human_discard_zone"),
             t("ro.label.bot_deck_zone"): val("bot_deck_zone"), t("ro.label.human_deck_zone"): val("human_deck_zone")}
    guids.update({t("ro.label.probe", guid=g): g for g in raw.get("probe_guids", [])})
    known = {k: g for k, g in guids.items() if g}
    saved = {key: g for key, g in cfg.saved_zones.items() if g not in known.values()}
    found = read(t("ro.read.objects"), lambda: lua.inspect_guids(sorted({*known.values(), *saved.values()}))) or {}
    live = {key: saved[key] for key in saved if not (found.get(val(key)) or {}).get("found")
            and (found.get(saved[key]) or {}).get("found")}      # a zone the bot created earlier stands in for the configured one
    swap = {val(key): g for key, g in live.items()}
    known = {k: swap.get(g, g) for k, g in known.items()}
    out.append(t("ro.objects"))
    for label, g in known.items():
        info = found.get(g, {"found": False})
        if info.get("found"):
            qty = t("ro.qty", n=info["quantity"]) if info.get("quantity") is not None else ""
            out.append(t("ro.object_line", label=label, guid=g, type=info["type"], name=info.get("name", ""), qty=qty,
                         x=info["x"], y=info["y"], z=info["z"]))
        else:
            warn.append(t("ro.w.missing_guid", label=label, guid=g))
    for label in (k for k, g in guids.items() if not g and "zone" not in label.lower()):
        out.append(t("ro.todo_label", label=label))

    wanted = raw.get("pieces") or {}
    off = float(raw.get("off_board_dist", 4.0))
    out.append(t("ro.pieces"))
    flat = sorted({g for v in wanted.values() for g in piece_guids(v)})
    pieces = read(t("ro.read.pieces"), lambda: lua.piece_spaces_by_guid(cfg.board, flat)) or {}
    pieces = pieces if isinstance(pieces, dict) else {}
    for fid, value in wanted.items():
        guids = piece_guids(value)
        g = next((x for x in guids if (pieces.get(x) or {}).get("found")), guids[0])
        p = pieces.get(g) or {"found": False}
        if not p.get("found"):
            warn.append(t("ro.w.piece_missing", fid=fid, guids="/".join(guids)))
            continue
        out.append(t("ro.piece_line", fid=fid, guid=g, type=p.get("type"), name=p.get("name", ""), space=p["space"],
                     dist=p["dist"]))
        if p["dist"] > off:
            warn.append(t("ro.w.piece_off_board", fid=fid, guid=g, dist=p["dist"], off=off))
    if not wanted:
        out.append(t("ro.pieces_todo"))

    dials = dict(raw.get("dials") or {})
    if raw.get("destiny_dial"):
        dials[t("ro.label.destiny")] = raw["destiny_dial"]
    if dials:
        out.append(t("ro.dials"))
        rows = read(t("ro.read.dials"), lambda: lua.read_health_dials(sorted(set(dials.values())))) or {}
        rows = rows if isinstance(rows, dict) else {}
        for fid, g in dials.items():
            d = rows.get(g) or {"found": False}
            if not d.get("found"):
                warn.append(t("ro.w.dial_missing", fid=fid, guid=g))
            elif d.get("value") is None:
                out.append(t("ro.dial_unreadable", fid=fid, guid=g, name=d.get("name", ""), label=d.get("label"),
                             value=d.get("object_value")))
            else:
                out.append(t("ro.dial_line", fid=fid, guid=g, name=d.get("name", ""), value=d["value"], max=d.get("max")))

    hands: dict[str, set[int]] = {}
    for side, seat_key in (("bot", "bot_seat"), ("human", "human_seat")):
        role = t(f"ro.role.{side}")
        seat = val(seat_key)
        if not seat:
            out.append(t("ro.hand_todo", role=role, key=seat_key))
            continue
        hand = read(t("ro.read.hand", role=role), lambda s=seat: lua.read_hand(s)) or []
        hands[side] = {r["id"] for r in hand}
        if side == "bot":
            out.append(t("ro.hand_bot", seat=seat, n=len(hand), titles=show_ids(hand)))
        else:
            count = (read(t("ro.read.count"), lambda: lua.count_hand(seat)) or {}).get("count")
            out.append(t("ro.hand_human", seat=seat, count=count, n=len(hand)))
    zones: dict[str, str] = {}
    for side, key in (("bot", "bot_discard_zone"), ("human", "human_discard_zone")):
        role = t(f"ro.role.{side}")
        zone = live.get(key) or val(key)
        if not zone:
            out.append(t("ro.discard_todo", role=role, key=key))
            continue
        zones[side] = zone
        deck_guid, deck_spot = ((val("bot_deck_guid"), raw.get("bot_deck_spot")) if side == "bot"
                                else (raw.get("human_deck_guid"), raw.get("human_deck_spot")))
        deck_zone = _deck_zone(raw, f"{side}_deck_zone")
        rows = read(t("ro.read.discard", role=role), lambda z=zone: lua.read_discard(
            z, [deck_guid] if deck_guid else [], [deck_spot] if deck_spot else [],
            exclude_zones=[deck_zone] if deck_zone else [])) or []
        out.append(t("ro.discard_line", role=role, n=len(rows), titles=show_ids(rows)))
        shared = hands.get(side, set()) & {r["id"] for r in rows}
        if shared:
            warn.append(t("ro.w.discard_shares", role=role, zone=zone, n=len(shared),
                          titles=", ".join(titles.get(i, str(i)) for i in sorted(shared))))
    for side in ("bot", "human"):
        deck_guid, deck_spot = val(f"{side}_deck_guid"), raw.get(f"{side}_deck_spot")
        card_ids = raw.get(f"{side}_card_ids")
        if not (deck_guid and deck_spot and card_ids) or is_todo(deck_spot):
            continue
        deck_zone, radius = _deck_zone(raw, f"{side}_deck_zone"), float(raw.get("deck_radius", lua.DECK_RADIUS))
        role = t(f"ro.role.{side}")
        res = read(t("ro.read.deck", role=role), lambda g=deck_guid, sp=deck_spot, c=card_ids, z=deck_zone: lua.deck_identities(
            [(g, tuple(sp), tuple(c), z)], radius))
        entry = res[0] if isinstance(res, list) and res and isinstance(res[0], dict) else None
        if entry and entry.get("found"):
            out.append(t("ro.deck_found", role=role, guid=entry.get("guid"), where=deck_where(deck_zone, deck_spot, radius)))
        elif entry is not None:
            warn.append(t("ro.w.deck_not_found", role=role, where=deck_where(deck_zone, deck_spot, radius)))
    if zones:
        over = read(t("ro.read.zones"), lambda: lua.zone_overlaps(sorted(set(zones.values())))) or {}
        over = over if isinstance(over, dict) else {}
        for side, zone in zones.items():
            hz = list((over.get(zone) or {}).get("hands") or [])
            if hz:
                warn.append(t("ro.w.discard_overlaps", role=t(f"ro.role.{side}"), zone=zone, hands=", ".join(hz)))
    spot = val("human_card_spot")
    if spot:
        rows = read(t("ro.read.face_down"),
                    lambda: lua.read_face_down_cards(*spot, float(raw.get("reveal_radius", 2.0)))) or []
        out.append(t("ro.face_down", titles=show_ids(rows)))
    else:
        out.append(t("ro.face_down_todo"))

    out.extend(_bridge_objects_report(read, cfg))

    if cfg.todos:
        out.append(t("ro.todos", todos=", ".join(cfg.todos)))
    for w in warn:
        out.append(t("ro.warning", text=w))
    out.append(t("ro.footer"))
    return out


# ---------- event loop ----------
def make_announcer(client, echo: Callable[[str], None] = print, to_table: bool = True) -> Callable[[list[str]], None]:
    """Prints each bot message and shows it on screen to the players (broadcast, does not touch the table)."""
    def announce(msgs: list[str]) -> None:
        for m in msgs:
            echo(f"[bot] {m}")
            if not to_table or getattr(m, "shown", False):
                continue
            for chunk in lua.ascii_text(m):
                try:
                    client.call_lua(lua.broadcast(chunk, getattr(m, "kind", lua.ChatKind.NEUTRAL)))
                except (TTSLuaError, TimeoutError, OSError) as e:
                    echo(t("console.warn_line", text=t("console.announce_failed", error=e)))
                    return
    return announce


Recovery = Callable[[], tuple[str, list[str]]]      # -> ("ok" | "retry" | "stop", messages)


def ongoing_labels() -> tuple[str, str]:
    """Floor labels of the bot's / the human's ONGOING zone (unique texts)."""
    return t("floor.ongoing.bot"), t("floor.ongoing.human")


def mark_floor(client, scfg: SessionConfig) -> None:
    """Draws on the floor the discard zones, the combat spots and the configured ONGOING zones (idempotent; play mode
    only)."""
    bot_ongoing, human_ongoing = ongoing_labels()
    cards = [(scfg.human_label, *scfg.human_card_spot), (scfg.bot_label, scfg.bot_card_spot[0], scfg.bot_card_spot[2])]
    if scfg.human_ongoing_spot is not None:
        cards.append((human_ongoing, *scfg.human_ongoing_spot))
    if scfg.bot_ongoing_spot is not None:
        cards.append((bot_ongoing, scfg.bot_ongoing_spot[0], scfg.bot_ongoing_spot[2]))
    client.call_lua(lua.draw_markings(
        [(t("floor.discard", name=scfg.human_label), scfg.human_discard_zone),
         (t("floor.discard", name=scfg.bot_label), scfg.bot_discard_zone)],
        cards, label_font=scfg.label_font))


def _zone_rect(bounds) -> tuple[float, float, float, float]:
    cx, cz, w, d, rot = (float(v) for v in bounds)
    t = math.radians(rot)
    hx = abs(math.cos(t)) * w / 2 + abs(math.sin(t)) * d / 2
    hz = abs(math.sin(t)) * w / 2 + abs(math.cos(t)) * d / 2
    return cx - hx, cx + hx, cz - hz, cz + hz


def floor_layout(cfg: PlayConfig) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Rectangles (x min, x max, z min, z max) of everything drawn on the floor: the discard, combat and ONGOING boxes
    and their labels. The discard zones are only known if the configuration carries their bounds."""
    return [(name, rect) for _, name, rect in _floor_items(cfg)]


def _floor_items(cfg: PlayConfig) -> list[tuple[str, str, tuple[float, float, float, float]]]:
    """(kind, name, rectangle) of every floor marking; the kind is "label", "combat_box", "box" or "zone"."""
    r, font = cfg.raw, float(cfg.raw.get("label_font", lua.LABEL_FONT))
    out: list[tuple[str, str, tuple[float, float, float, float]]] = []

    def label(text: str, cx: float, cz: float, w: float, d: float, rot: float) -> None:
        x, z, ex, ez = lua.label_position(cx, cz, w, d, rot, text, font)
        out.append(("label", t("layout.label", text=text), (x - ex / 2, x + ex / 2, z - ez / 2, z + ez / 2)))
    w, d = lua.CARD_SIZE
    bot_name, human_name = cfg.hero_names
    bot_ongoing, human_ongoing = ongoing_labels()
    for name, spot in ((bot_name, (r["bot_card_spot"][0], r["bot_card_spot"][2])), (human_name, r["human_card_spot"])):
        out.append(("combat_box", t("layout.combat_box", name=name),
                    (spot[0] - w / 2, spot[0] + w / 2, spot[1] - d / 2, spot[1] + d / 2)))
        label(name, spot[0], spot[1], w, d, 0.0)
    for name, key in ((bot_ongoing, "bot_ongoing_spot"), (human_ongoing, "human_ongoing_spot")):
        if r.get(key):
            spot = (r[key][0], r[key][-1])
            out.append(("box", t("layout.box", name=name), (spot[0] - w / 2, spot[0] + w / 2, spot[1] - d / 2, spot[1] + d / 2)))
            label(name, spot[0], spot[1], w, d, 0.0)
    for name, key in ((t("floor.discard", name=bot_name), "bot_discard_bounds"),
                      (t("floor.discard", name=human_name), "human_discard_bounds")):
        if r.get(key):
            out.append(("zone", t("layout.zone", name=name), _zone_rect(r[key])))
            cx, cz, bw, bd, rot = (float(v) for v in r[key])
            label(name, cx, cz, bw, bd, rot)
    return out


def floor_layout_warnings(cfg: PlayConfig) -> list[str]:
    """Start-up warnings: no label or floor rectangle may end up under the panel (on 27/10 the floor labels were
    painted over its buttons)."""
    pos, scale = cfg.panel_position, cfg.panel_scale
    x0, x1, z0, z1 = lua.panel_footprint(pos, scale, ui.PANEL_WIDTH, ui.panel_height(len(cfg.fighter_ids)))
    warnings = []
    items = _floor_items(cfg)
    for _, name, (a0, a1, b0, b1) in items:
        if a0 < x1 and a1 > x0 and b0 < z1 and b1 > z0:
            warnings.append(t("layout.under_panel", name=name, x0=x0, x1=x1, z0=z0, z1=z1))
    warnings += _look_row_warnings(cfg, items)
    return warnings


# Unmatched hands start at 5 and only a few cards draw past 7; `lua.MAX_LOOK_CARDS` (12) is a safety cap of the Lua
# row, not a hand a game reaches, and a 12-card column would run into the discard zone and the hero bags.
ROW_WARN_CARDS = 7

LOOK_ROWS = {   # spot key -> (step key, default spot, default step, tag of the name in the warning)
    "look_spot": ("look_step", SessionConfig.look_spot, SessionConfig.look_step, "layout.look_row"),
    "bot_row_spot": ("bot_row_step", SessionConfig.bot_row_spot, SessionConfig.bot_row_step, "layout.bot_row"),
}


def look_row_rect(cfg: PlayConfig, n: int = ROW_WARN_CARDS, spot_key: str = "look_spot") -> tuple[float, float, float, float]:
    """Rectangle (x min, x max, z min, z max) taken up by a row of the bot's hand (`look_spot` or `bot_row_spot`)
    with `n` cards."""
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


ASIDE_SPOTS = ("bot_tuck_spot", "bot_removed_spot")
ASIDE_WARN_CARDS = 6      # cards the bot lays side by side at a set-aside spot before the row gets absurd


def aside_row_rect(cfg: PlayConfig, key: str, n: int = ASIDE_WARN_CARDS) -> tuple[float, float, float, float]:
    """Rectangle (x min, x max, z min, z max) of the cards laid from `bot_tuck_spot` / `bot_removed_spot` in +x."""
    x, _, z = (float(v) for v in cfg.raw[key])
    w, d = lua.CARD_SIZE
    return x - w / 2, x + (n - 1) * ASIDE_STEP + w / 2, z - d / 2, z + d / 2


def look_row_warnings(cfg: PlayConfig) -> list[str]:
    """Start-up warning: the rows of the bot's hand (up to `ROW_WARN_CARDS` cards) may not overlap the panel, the
    combat and ONGOING boxes or the discard zones."""
    return _look_row_warnings(cfg, _floor_items(cfg))


def _look_row_warnings(cfg: PlayConfig, items: list[tuple[str, str, tuple[float, float, float, float]]]) -> list[str]:
    pos, scale = cfg.panel_position, cfg.panel_scale
    others = [(t("layout.panel"), lua.panel_footprint(pos, scale, ui.PANEL_WIDTH, ui.panel_height(len(cfg.fighter_ids)))),
              *((name, rect) for kind, name, rect in items if kind != "label")]
    out = []
    for spot_key, (*_, what) in LOOK_ROWS.items():
        a0, a1, b0, b1 = look_row_rect(cfg, ROW_WARN_CARDS, spot_key)
        out += [t("layout.row_overlap", what=t(what), key=spot_key, x0=a0, x1=a1, z0=b0, z1=b1, name=name)
                for name, (x0, x1, z0, z1) in others if a0 < x1 and a1 > x0 and b0 < z1 and b1 > z0]
    look_rows = [(t(what), look_row_rect(cfg, ROW_WARN_CARDS, key)) for key, (*_, what) in LOOK_ROWS.items()]
    asides = {key: aside_row_rect(cfg, key) for key in ASIDE_SPOTS if cfg.raw.get(key)}
    for key, (a0, a1, b0, b1) in asides.items():
        crowd = [*others, *look_rows, *((k, r) for k, r in asides.items() if k != key)]
        out += [t("layout.row_overlap", what=t("layout.aside_row"), key=key, x0=a0, x1=a1, z0=b0, z1=b1, name=name)
                for name, (x0, x1, z0, z1) in crowd if a0 < x1 and a1 > x0 and b0 < z1 and b1 > z0]
    return out


def saved_zones(state_path: str | Path | None) -> dict[str, str]:
    """The discard zones the bot created in an earlier run (`zones_live` of its session file); empty if there is none or
    the file cannot be read. A fresh start reuses them if they are still on the table instead of creating more."""
    if state_path is None:
        return {}
    try:
        return Session.read_saved_zones(persist.load(state_path).get("zones_live"))
    except persist.StateError:
        return {}


def recover_after_reload(session: Session, client: TTSClient, targets: list[str],
                         position: tuple[float, float, float], rotation=ui.PANEL_ROTATION,
                         scale=ui.PANEL_SCALE, names: dict[str, str] | None = None,
                         attackers: tuple[str, ...] | None = None) -> tuple[str, list[str]]:
    """TTS reloaded the game (messageID 1): the configuration's GUIDs are checked and the panel is recreated.

    "stop" if any is missing (the loaded game is not this one: carrying on would write on somebody else's table);
    "retry" if TTS does not answer yet; "ok" with the panel recreated and the table marked for resync."""
    try:
        session.load_identities()                # a deck re-formed by the reload may have another GUID
        found = client.call_lua(lua.inspect_guids(session.guids_in_use())) or {}
        found = found if isinstance(found, dict) else {}
        missing = [t("common.or").join(group) for group in session.guid_groups()
                   if not any((found.get(g) or {}).get("found") for g in group)]
        if missing:
            return "stop", [t("play.reload_missing", missing=", ".join(missing))]
        if attackers is None:
            attackers = tuple(f.fid for f in session.game.own(session.human, alive_only=False))
        client.call_lua(lua.create_panel(targets, position, rotation, scale, names,
                                         snapshot=session.snapshot_spec() if session.cfg.batch else None,
                                         attacker_ids=attackers, human_seat=session.cfg.human_seat))
        mark_floor(client, session.cfg)
        session.restore_look_row()
    except TABLE_ERRORS as e:
        return "retry", [t("play.reload_retry", error=e)]
    session.dirty = True
    return "ok", [t("play.reload_ok")]


UNPACK_SPOTS = {"bot": (22.0, 2.5, -10.0), "human": (-22.0, 2.5, 10.5)}   # outside the hands (|x| >= 25) and the discards
UNPACK_STEP = (0.0, 0.0, 3.0)


def unpack_plan(cfg: PlayConfig) -> list[tuple]:
    """(kind, GUID of each state, inner bag, spot, CardID range or None) of everything of both heroes. The deck goes to
    its deck spot; the rest in a row from `bot_unpack_spot` / `human_unpack_spot` every `unpack_step`."""
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
    """Only with --unpack (or "unpack": true) and never when resuming: takes out of each hero's inner bag whatever is
    missing on the table. Missing = NO GUID of the object answers (all its states) and, for a deck, none of its piles
    is on its spot. Things are taken only from the bag with the hero's bag GUID; if it is not on the table nothing is
    done and a warning is printed (the bot never takes anything out of an infinite bag). A single message to TTS."""
    plan = unpack_plan(cfg)
    res = client.call_lua(lua.unpack_from_bags(plan)) or {}
    taken, missing = list(res.get("taken") or []), list(res.get("missing") or [])
    if taken:
        echo(t("console.unpacked", n=len(taken), items=", ".join(taken)))
    for slug in cfg.heroes:
        table = load_hero_table(slug)
        lost = [g for _, guids in table.unpack_items() for g in guids[:1] if g in missing]
        if lost:
            echo(t("console.warn_line", text=t("console.unpack_missing", guids=", ".join(lost),
                                                hero=load_hero(slug).name, bag=table.inner_bag)))


def run_loop(session: Session, client: TTSClient, stop: threading.Event, announce: Callable[[list[str]], None],
             poll: float = 0.1, recover: Recovery | None = None) -> None:
    """Passes each panel button to `Session.handle`; an odd event or an internal failure never kills the game.

    With `recover`, a messageID 1 (TTS reload) pauses the buttons until the table is checked; if any GUID is
    missing the game stops safely (writing nothing)."""
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
            if n and isinstance(raw, dict):                       # only the first click carries a still valid table
                raw = {k: v for k, v in raw.items() if k != "snapshot"}
            try:
                event, payload = parse_event(raw)
            except (KeyError, ValueError, TypeError, AttributeError):
                announce([Msg(t("play.unknown_event", event=repr(raw)), lua.ChatKind.WARNING)])
                continue
            try:
                announce(session.handle(event, payload))
            except Exception:                                    # noqa: BLE001 - the game must go on
                traceback.print_exc()
                announce([Msg(t("play.internal_error"), lua.ChatKind.WARNING)])
        if not events:
            stop.wait(poll)


def ai_config(cfg: PlayConfig, ai: str | None, ai_time: float | None) -> dict:
    """AI config: the command line wins over the `ai` / `ai_time_budget` keys of the JSON."""
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


def check_deck_zones(client, scfg: SessionConfig, echo: Callable[[str], None] = print) -> None:
    """Start-up: each configured deck zone must exist and be a Scripting zone (else `SessionError` naming the key); one
    that overlaps a hand zone or a discard zone is warned about (a deck zone only claims what is face down in it)."""
    zones = {key: g for key, g in (("bot_deck_zone", scfg.bot_deck_zone), ("human_deck_zone", scfg.human_deck_zone)) if g}
    if not zones:
        return
    res = client.call_lua(lua.zone_overlaps(sorted(set(zones.values())),
                                            [scfg.bot_discard_zone, scfg.human_discard_zone])) or {}
    res = res if isinstance(res, dict) else {}
    for key, guid in zones.items():
        info = res.get(guid) or {}
        if not info.get("found"):
            raise SessionError(t("cfg.deck_zone_missing", key=key, guid=guid))
        if not info.get("zone"):
            raise SessionError(t("cfg.deck_zone_not_zone", key=key, guid=guid, type=info.get("type")))
        others = [*(info.get("hands") or []), *(info.get("zones") or [])]
        if others:
            echo(t("console.warn_line", text=t("cfg.deck_zone_overlaps", key=key, guid=guid, others=", ".join(others))))


def play(cfg: PlayConfig, client: TTSClient, first: str, seed: int, stop: threading.Event,
         echo: Callable[[str], None] = print, poll: float = 0.1, state_path: Path | None = None,
         resume: bool = False, timing: bool = False, ai: str | None = None,
         ai_time: float | None = None, bot_pause: float | None = None, unpack: bool = False,
         card_zoom: bool = True, on_ready: Callable[[], None] = lambda: None) -> None:
    i18n.set_language(cfg.language)                  # before the first panel or chat line; --resume takes the current one
    scfg = cfg.session_config()
    if bot_pause is not None:
        if not (math.isfinite(bot_pause) and 0 <= bot_pause <= 30):
            raise SessionError(t("cli.bot_pause_range"))
        scfg.bot_pause = bot_pause
    if not card_zoom:
        scfg.card_zoom = False
    if (unpack or cfg.raw.get("unpack") is True) and not resume:
        prepare_heroes(client, cfg, echo)
    game = build_game(cfg, first, seed)
    session = Session(game, client, make_bot_ai(ai_config(cfg, ai, ai_time), BOT), scfg, bot=BOT)
    session.state_path = state_path
    session.game_log.path = game_log.log_path(state_path)
    session.first_mode = first
    session.new_game = lambda: build_game(cfg, first, secrets.randbelow(2 ** 31))
    if timing:
        session.timing = client.trace = lambda line: echo(t("console.timing", line=line) if not line.startswith("[") else line)
    if resume:
        if state_path is None:
            raise persist.StateError(t("save.needs_file"))
        session.load_dict(persist.load(state_path))
    try:
        session.prepare_table(resume, None if resume else saved_zones(state_path))            # before anything reads the zones: a missing one is created, a tilted one straightened
    except (TTSLuaError, OSError):
        pass                                     # table not reachable now: the next step says so
    targets = [f.fid for f in game.own(BOT)]
    try:
        session.resolve_pieces()                 # before the panel is built: its snapshot carries the GUIDs found by name
    except TABLE_ERRORS:
        pass                                     # the start-up check tries again and says why
    try:
        session.load_identities()                # adopts the decks' current GUIDs too: the panel's snapshot skips them by GUID
    except TABLE_ERRORS:
        pass                                     # retried on first use
    try:
        check_deck_zones(client, scfg, echo)
    except (TTSLuaError, OSError):
        pass                                     # table not reachable now: the zones are looked for again on first use
    # a missing deck zone or one that is not a Scripting zone (SessionError) stops the start-up, naming the key
    for warning in floor_layout_warnings(cfg):
        echo(t("console.warn_line", text=warning))
    client.call_lua(lua.clear_markings(remove_panel=True))     # leftovers of a previous run that died without cleaning up
    client.call_lua(lua.create_panel(targets, cfg.panel_position, cfg.panel_rotation, cfg.panel_scale,
                                     cfg.nicknames, snapshot=session.snapshot_spec() if scfg.batch else None,
                                     attacker_ids=cfg.attacker_ids, human_seat=scfg.human_seat))
    echo(t("console.panel_ready_launcher" if LAUNCHED else "console.panel_ready"))
    on_ready()
    try:
        mark_floor(client, scfg)
    except TABLE_ERRORS as e:
        echo(t("console.warn_line", text=t("console.floor_failed", error=e)))
    announce = make_announcer(client, echo, to_table=not session.broadcast)   # with live_ui the announcement already goes in the button's closing script
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


def early_language(argv: list[str] | None) -> str:
    """The language `--help` and the first messages come out in, before anything is parsed: `--language`, else the
    `language` key of the `--config` file, else Spanish."""
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--language")
    probe.add_argument("--config", default=str(DEFAULT_CONFIG))
    known, _ = probe.parse_known_args(argv)
    if known.language:
        return known.language
    try:
        return str(json.loads(Path(known.config).read_text(encoding="utf-8")).get("language") or i18n.DEFAULT)
    except (OSError, ValueError, AttributeError):
        return i18n.DEFAULT


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    i18n.set_language(early_language(argv))
    prog = Path(sys.executable).name if FROZEN else "python -m sparring.play"
    ap = argparse.ArgumentParser(prog=prog, description=t("cli.description"))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help=t("cli.config"))
    ap.add_argument("--read-only", action="store_true", help=t("cli.read_only"))
    ap.add_argument("--first", choices=("human", "bot", "random"), default="random", help=t("cli.first"))
    ap.add_argument("--seed", type=int, default=None, help=t("cli.seed"))
    ap.add_argument("--send-port", type=int, default=SEND_PORT, help=t("cli.send_port"))
    ap.add_argument("--listen-port", type=int, default=LISTEN_PORT, help=t("cli.listen_port"))
    ap.add_argument("--poll", type=float, default=0.1)
    ap.add_argument("--state", default=str(DEFAULT_STATE), help=t("cli.state"))
    ap.add_argument("--ai", choices=("heuristic", "ismcts"), default=None, help=t("cli.ai"))
    ap.add_argument("--ai-time", type=float, default=None, help=t("cli.ai_time"))
    ap.add_argument("--resume", action="store_true", help=t("cli.resume"))
    ap.add_argument("--bot-pause", type=float, default=None, metavar=t("cli.seconds"),
                    help=t("cli.bot_pause", default=DEFAULT_BOT_PAUSE))
    ap.add_argument("--language", choices=i18n.available(), default=None, help=t("cli.language"))
    ap.add_argument("--unpack", action="store_true", help=t("cli.unpack"))
    ap.add_argument("--no-card-zoom", action="store_true", help=t("cli.no_card_zoom"))
    ap.add_argument("--bot-hero", default=None, metavar="SLUG", help=t("cli.bot_hero"))
    ap.add_argument("--human-hero", default=None, metavar="SLUG", help=t("cli.human_hero"))
    ap.add_argument("--timing", action="store_true", help=t("cli.timing"))
    ap.add_argument("--launcher", action="store_true", help=t("cli.launcher"))
    return ap.parse_args(argv)


def saved_heroes(state_path: str | Path) -> tuple[str, str] | None:
    """The (bot, human) heroes the saved game holds; None if it holds none (an older save) or does not exist."""
    try:
        heroes = persist.load(state_path).get("heroes")
    except persist.StateError:
        return None          # the real error comes from `Session.load_dict` on resume
    return (str(heroes[0]), str(heroes[1])) if isinstance(heroes, list) and len(heroes) == 2 else None


def saved_language(state_path: str | Path) -> str | None:
    """The language the saved game was played in; None if it holds none (an older save) or does not exist."""
    try:
        lang = persist.load(state_path).get("language")
    except persist.StateError:
        return None
    return lang if isinstance(lang, str) and lang in i18n.available() else None


def tts_error_kind(error: BaseException) -> str:
    """The plain-language class of a failure to reach TTS, for the launcher's status line. A listen port held by
    another program fails the bind with 10048 (WSAEADDRINUSE) or, as the listener sets SO_REUSEADDR, with 10013
    (WSAEACCES, also what a port reserved by Windows gives)."""
    if isinstance(error, OSError) and (error.errno == errno.EADDRINUSE or getattr(error, "winerror", None) in (10048, 10013)):
        return "port_in_use"
    if isinstance(error, ConnectionRefusedError):
        return "tts_unreachable"
    if isinstance(error, TimeoutError):
        return "tts_timeout"
    return "tts_error"


def launcher_mode(stop: threading.Event) -> Callable[[str], None]:
    """--launcher: UTF-8 line-buffered output (a pipe would get the ANSI code page and block buffering), a stop
    channel on stdin (a `quit` line, or the pipe closing because the launcher died, has the effect of Ctrl+C without
    the interruption: the loop ends and the panel and floor labels are removed) and the status line writer."""
    global LAUNCHED
    LAUNCHED = True
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    def watch_stdin() -> None:
        try:                                      # a broken or undecodable stdin must still stop the bot, never strand it
            for line in sys.stdin:
                if line.strip() == "quit":
                    break
        finally:
            stop.set()
    threading.Thread(target=watch_stdin, name="launcher-stdin", daemon=True).start()

    def status(word: str) -> None:
        print(f"{STATUS_PREFIX} {word}", flush=True)
    return status


def main(argv: list[str] | None = None, stop: threading.Event | None = None) -> int:
    args = parse_args(argv)
    stop = stop or threading.Event()
    status = launcher_mode(stop) if args.launcher else (lambda word: None)
    code = _main(args, stop, status)
    status(f"exit {code}")
    return code


def _main(args: argparse.Namespace, stop: threading.Event, status: Callable[[str], None]) -> int:
    for notice in migrate_legacy_files(Path(args.state)):
        print(t("console.warning", text=notice), file=sys.stderr)
    # a resumed game keeps the language it was played in unless --language is given explicitly
    saved_lang = saved_language(args.state) if args.resume and not args.read_only else None
    try:
        cfg = load_config(args.config, args.bot_hero, args.human_hero, args.language or saved_lang)
        if saved_lang and args.language and args.language != saved_lang:
            cfg.warnings.append(t("save.language_override", new=args.language, old=saved_lang))
        if not args.read_only:
            cfg.session_config()                     # fails before opening ports if something is missing
    except ConfigError as e:
        print(t("console.config_error", error=e), file=sys.stderr)
        status("error config")
        return 2
    for warning in cfg.warnings:
        print(t("console.warning", text=warning), file=sys.stderr)
    printed = set(cfg.warnings)
    client = TTSClient(send_port=args.send_port, listen_port=args.listen_port)
    try:
        status("connecting")
        client.start_listening()
        try:
            saved = saved_heroes(args.state) if args.resume and not args.read_only else None
            cfg = detect_board(client, cfg)
            cfg = resolve_heroes(client, cfg, saved)
            if not args.read_only:
                cfg.session_config()
        except (BoardError, HeroDetectionError, ConfigError, persist.StateError, SessionError) as e:
            print(t("console.cannot_start", error=e), file=sys.stderr)
            status("error cannot_start")
            return 2
        for warning in dict.fromkeys(cfg.warnings):
            if warning not in printed:
                print(t("console.warning", text=warning), file=sys.stderr)
        if args.read_only:
            cfg.saved_zones = saved_zones(args.state)
            print("\n".join(read_only_report(client, cfg)))
            return 0
        seed = args.seed if args.seed is not None else secrets.randbelow(2 ** 31)
        state = Path(args.state)
        if not args.resume and state.exists():
            print(t("console.warning", text=t("console.overwrite", state=state)))
        state.parent.mkdir(parents=True, exist_ok=True)
        play(cfg, client, args.first, seed, stop, poll=args.poll, state_path=state, resume=args.resume,
             timing=args.timing, ai=args.ai, ai_time=args.ai_time, bot_pause=args.bot_pause,
             unpack=args.unpack, card_zoom=not args.no_card_zoom, on_ready=lambda: status("playing"))
        return 0
    except (SessionError, persist.StateError) as e:
        print(t("console.cannot_start", error=e), file=sys.stderr)
        status("error cannot_start")
        return 2
    except KeyboardInterrupt:
        print(t("console.interrupted"))
        return 130
    except (TTSLuaError, TimeoutError, OSError, ConfigError) as e:
        print(t("console.tts_error", error=e), file=sys.stderr)
        status(f"error {tts_error_kind(e)}")
        return 3
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
