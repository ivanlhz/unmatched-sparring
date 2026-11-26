"""The ORDER of a discard pile matters to the engine since Little Red (her basket is the top card). The pile is a plain list whose last element is the
newest card; this file pins the audit of docs/heroes/little-red-riding-hood.md ("The order of the discard pile"):

  * no code of the game reorders a pile (no sort, insert, reverse, shuffle or rebuild from a set);
  * the only places that assign a whole pile keep the order they are given (a save, the table's adoption of the bot's pile);
  * an effect that names "the top card" of a discard pile says `pick: last` (the newest); `top` and `bottom` are for decks and the validator rejects them
    on a pile, so a hero's data cannot read the wrong end (Loki's Sindri's Bet and Devil of Hell's Kitchen use `last`; Pandora's Hindsight and Achilles
    name a card, which leaves the order of the others alone)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from conftest import give
from sparring.heroes import HEROES_DIR
from test_little_red_effects import mk, pile

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted((ROOT / "sparring").rglob("*.py"))
REORDERS = re.compile(r"\bdiscard\s*\.\s*(sort|reverse|insert)\s*\(|sorted\(\s*[\w.\[\]]*\.discard\b|random\.shuffle\(\s*[\w.\[\]]*\.discard\b|\.discard\s*=\s*(sorted|list\(set|set)\(")
ASSIGNS = re.compile(r"\.discard\[:\]\s*=")


def test_nothing_in_the_game_reorders_a_discard_pile():
    found = [f"{path.relative_to(ROOT)}:{n}" for path in SOURCES for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
             if REORDERS.search(line) and not line.lstrip().startswith("#")]
    assert found == []


def test_the_whole_pile_is_only_assigned_by_the_save_and_by_the_adoption_of_the_bots_table():
    found = sorted({str(path.relative_to(ROOT)).replace("\\", "/") for path in SOURCES
                    if any(ASSIGNS.search(line) for line in path.read_text(encoding="utf-8").splitlines())})
    assert found == ["sparring/persist.py", "sparring/session.py"]


def test_a_pile_selector_never_names_the_top_or_the_bottom_of_a_pile():
    """`top` and `bottom` are the ends of a deck; the newest card of a pile is `last`."""
    bad = []

    def walk(node, where):
        if isinstance(node, dict):
            if node.get("zone") == "discard" and node.get("pick") in ("top", "bottom"):
                bad.append(where)
            for v in node.values():
                walk(v, where)
        elif isinstance(node, list):
            for v in node:
                walk(v, where)

    for path in sorted((HEROES_DIR / "effects").glob("*.json")):
        if path.stem != "schema":
            walk(json.loads(path.read_text(encoding="utf-8")), path.name)
    assert bad == []


def test_the_pile_is_a_list_and_discarding_appends_to_it(bprd):
    g = mk(bprd)
    a, b = give(g, 0, "The Wolf's Skin"), give(g, 0, "Once Upon a Time")
    g.discard_card(0, b)
    g.discard_card(0, a)
    assert g.players[0].discard == [b, a]


def test_a_pile_cloned_for_the_search_keeps_its_order(bprd):
    g = mk(bprd)
    pile(g, "The Wolf's Skin", "Once Upon a Time", "Never Leave the Path")
    clone = g.clone()
    clone.discard_card(0, give(clone, 0, "Into the Woods"))
    assert [c.title for c in clone.players[0].discard] == ["The Wolf's Skin", "Once Upon a Time", "Never Leave the Path", "Into the Woods"]
    assert [c.title for c in g.players[0].discard] == ["The Wolf's Skin", "Once Upon a Time", "Never Leave the Path"]
