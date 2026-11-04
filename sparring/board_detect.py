"""Which map is on the table.

The official save keeps every map in an infinite bag, so a board taken out of it has a GUID the bot cannot know in
advance. The start-up reads the loose boards (`lua.list_boards`) and recognises the map by its image: the SHA-1 its
URL ends with, listed in data/maps/catalog.json. A board that is unknown, excluded or has no verified data stops the
start-up with a message that names it and lists the supported maps."""
from __future__ import annotations

import re

from .board import MapEntry, catalog
from .i18n import t

_IMAGE_KEY = re.compile(r"[0-9A-Fa-f]{40}")


class BoardError(Exception):
    """The board on the table cannot be played; the message is for the player."""


def load_catalog() -> list[MapEntry]:
    return catalog()


def image_key_of(url) -> str | None:
    """The 40-hex SHA-1 at the end of a board image URL, upper case; None when the URL has none."""
    if not isinstance(url, str):
        return None
    found = _IMAGE_KEY.findall(url)
    return found[-1].upper() if found else None


def _supported_names(entries: list[MapEntry]) -> str:
    return ", ".join(sorted(e.name for e in entries if e.status == "supported"))


def choose_board(found: list[dict], entries: list[MapEntry]) -> tuple[MapEntry, str]:
    """The map in play and the GUID of its board, from the boards read off the table (`{"guid", "image"}`).

    Boards that are not a known map (the table's own pad, the small side boards) are ignored while exactly one known
    map is there; two known maps, none, or one that cannot be played raise `BoardError`."""
    by_key = {e.image_key: e for e in entries}
    known = [(by_key[k], b["guid"]) for b in found if (k := image_key_of(b.get("image"))) in by_key]
    supported = _supported_names(entries)
    if not known:
        if not found:
            raise BoardError(t("board.none", maps=supported))
        images = ", ".join(sorted({image_key_of(b.get("image")) or "?" for b in found}))
        raise BoardError(t("board.unknown", image=images, maps=supported))
    if len(known) > 1:
        raise BoardError(t("board.several", names=", ".join(sorted(e.name for e, _ in known)), maps=supported))
    entry, guid = known[0]
    if entry.status == "excluded":
        raise BoardError(t("board.excluded", name=entry.name, reason=t(f"board.reason.{entry.reason}"), maps=supported))
    if entry.status != "supported":
        raise BoardError(t("board.unavailable", name=entry.name, maps=supported))
    return entry, guid
