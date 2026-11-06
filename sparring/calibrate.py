"""`python -m sparring.calibrate --map <key>`: writes the calibration of one map from the table as Ivan arranged it by hand.

Ivan puts the map on the table, scales and turns it the way he wants it, puts the two heroes out of their bags (the bot's on the
+x half, his on the -x half) and lays every deck, character card, dial, token and miniature where it should go. This command only
READS the table (read-only scripts, nothing is written to TTS) and stores, for that map, in config/map_setups.json: the board's
scale, position and rotation and the slot of every object of both heroes (`sparring/map_setup.py`). The next time the gate's
Prepare sees that map it lays everything out the same way, whichever heroes are dropped.

The bot must not be running (both listen on the same port)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import i18n, map_setup, player_setup, table_layout
from .board import catalog as board_catalog
from .heroes import load_hero
from .i18n import t
from .play import DEFAULT_CONFIG, ConfigError, ReadOnlyClient, load_config
from .tts import lua
from .tts.client import LISTEN_PORT, SEND_PORT, TTSClient
from .tts.hero_table import load_hero_table

SIDE_SIGN = {player_setup.BOT: 1, player_setup.HUMAN: -1}


def _angle(value: float) -> float:
    """A rotation read from TTS as a clean angle in [0, 360): 89.99 and 360.01 are the 90 and 0 they were meant to be."""
    value = value % 360
    for exact in (0.0, 90.0, 180.0, 270.0, 360.0):
        if abs(value - exact) <= 0.6:
            return exact % 360
    return round(value, 1)


def _slot(found: dict) -> dict:
    return {"pos": [round(found["x"], 2), round(found["y"], 2), round(found["z"], 2)],
            "rot": [_angle(found["rx"]), _angle(found["ry"]), _angle(found["rz"])]}


def _sequential(client, named):
    """The reads one after another (the read-only client does not carry a composite)."""
    return {name: client.call_lua(script) for name, script in named}


def _rows(setup: player_setup.Setup, found: player_setup.Scan) -> list[tuple]:
    """(key, kind, GUIDs, plain name, side sign, CardID) of everything to read: the board, then per side the deck, the character
    card and the objects in the order of their slots."""
    rows = [("map", "object", [setup.board_guid], "", 0, 0)]
    for side, slug in ((player_setup.BOT, setup.bot), (player_setup.HUMAN, setup.human)):
        table, hero, sign = load_hero_table(slug), load_hero(slug), SIDE_SIGN[side]
        deck = next((s.guid for s in found.sightings if s.side == side and s.slug == slug and s.kind == "deck"), None)
        rows.append((f"{side}:deck", "object", [deck] if deck else [], "", sign, 0))      # still in its bag: not found
        rows.append((f"{side}:character", "card", [], "", sign, table.character_card_id))
        names = {f.fid: " ".join((table.fighters[f.fid].nickname or f.name).lower().split()) for f in hero.fighters()}
        for item in table_layout.items(table)[1:]:
            fid = item.key.split(":", 1)[1] if item.kind in ("dial", "piece") and not item.key.startswith("counter") else ""
            rows.append((f"{side}:{item.key}", "dial" if item.kind == "dial" else "object", list(item.guids),
                         names.get(fid, ""), sign, 0))
    return rows


def _layout(setup: player_setup.Setup, read: dict) -> tuple[dict, list[str]]:
    """The `layout` of the map out of what was read, and what is missing (already worded)."""
    layout, missing = {}, []
    for side, slug in ((player_setup.BOT, setup.bot), (player_setup.HUMAN, setup.human)):
        table, spec = load_hero_table(slug), {"sidekick_dials": [], "counter_dials": [], "tokens": [], "pieces": []}
        name = load_hero(slug).name

        def take(key: str, what: str):
            got = read.get(f"{side}:{key}") or {}
            if got.get("found"):
                return _slot(got)
            why = t("cal.why.several") if got.get("why") == "several" else t("cal.why.none")
            missing.append(f"{what} ({why})")
            return None
        deck = take("deck", t("cal.what.deck", hero=name))
        char = take("character", t("cal.what.character", hero=name))
        spec["deck"], spec["character_card"] = deck, char
        for item in table_layout.items(table)[1:]:
            slot = take(item.key, t("cal.what.object", name=item.key.split(":", 1)[1], hero=name))
            if item.role in ("dial",):
                spec["dial"] = slot
            else:
                spec[item.role].append(slot)
        layout[side] = spec
    return layout, missing


def calibrate(client, slug: str, raw: dict, path: Path | None = None, dry_run: bool = False,
              echo=print) -> int:
    """Reads the table through `client` (read only) and stores the entry of `slug`. 0 if written (or shown with `dry_run`)."""
    maps = {e.key: e for e in board_catalog() if e.status == "supported"}
    if slug not in maps:
        echo(t("cal.unknown_map", slug=slug, maps=", ".join(sorted(maps))))
        return 2
    ro = ReadOnlyClient(client)
    found = player_setup.scan(ro, raw, _sequential)
    setup, problems = player_setup.decide(found)
    if setup is None:
        echo(t("cal.need_heroes", problems=" ".join(problems)))
        return 2
    if setup.entry.key != slug:
        echo(t("cal.map_other", found=setup.entry.key, slug=slug))
        return 2
    try:
        read = _sequential(ro, [("t", lua.read_transforms(_rows(setup, found)))])["t"]
    except ValueError as e:                    # a hero with more objects than one read carries
        echo(str(e))
        return 2
    read = read if isinstance(read, dict) else {}
    layout, missing = _layout(setup, read)
    board = read.get("map") or {}
    if missing or not board.get("found"):
        echo(t("cal.missing", what=", ".join(missing) or slug))
        return 2
    entry = map_setup.MapSetup(round(board["sx"], 3), (round(board["x"], 2), round(board["y"], 2), round(board["z"], 2)),
                               _angle(board["ry"]), layout)
    target = path or map_setup.SETUPS_PATH
    if dry_run:
        echo(t("cal.dry", path=target))
        echo(f"{slug}: scale {entry.scale}, position {list(entry.position)}, rot_y {entry.rot_y}")
        return 0
    map_setup.save(slug, entry, path)
    echo(t("cal.written", slug=slug, scale=entry.scale, position=list(entry.position), rot_y=entry.rot_y, path=target))
    return 0


def main(argv: list[str] | None = None, setups_path: Path | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m sparring.calibrate", description=__doc__.split("\n\n")[0])
    ap.add_argument("--map", required=True, metavar="KEY", help=t("cal.arg.map"))
    ap.add_argument("--dry-run", action="store_true", help=t("cal.arg.dry"))
    ap.add_argument("--config", default=str(DEFAULT_CONFIG), help=t("cli.config"))
    ap.add_argument("--send-port", type=int, default=SEND_PORT, help=t("cli.send_port"))
    ap.add_argument("--listen-port", type=int, default=LISTEN_PORT, help=t("cli.listen_port"))
    ap.add_argument("--language", choices=i18n.available(), default=None, help=t("cli.language"))
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config, language=args.language)
    except ConfigError as e:
        print(t("console.config_error", error=e), file=sys.stderr)
        return 2
    client = TTSClient(send_port=args.send_port, listen_port=args.listen_port)
    try:
        client.start_listening()
        return calibrate(client, args.map, cfg.raw, setups_path, args.dry_run)
    except OSError as e:
        print(t("console.config_error", error=e), file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
