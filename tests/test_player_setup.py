"""The player sets the table: Clean table empties it, the player drags the map and the two heroes from the roster, Prepare reads
and lays them out on the slots calibrated for that map (`sparring/player_setup.py`, `map_setup.py`, `calibrate.py`).

The Lua tests run the generated scripts under lupa (tests/lua_stub.lua); the reading and the decision are plain functions; the
gate flows go through `play.main` against the fake table, with two heroes that are NOT the default pair (Bigfoot vs Houdini)."""
from __future__ import annotations

import json

import pytest

from sparring import hero_detect, map_setup, player_setup, table_layout
from sparring.board import catalog as board_catalog
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from test_official_save_setup import tts  # noqa: F401
from test_review10 import conv

lupa = pytest.importorskip("lupa")

BOT_HERO, HUMAN_HERO = "bigfoot", "houdini"


def run(runtime, script: str, rid: int = 1):
    """The generated script through the request wrapper, as TTS runs it; returns the decoded answer."""
    n = len(runtime.globals().SENT)
    runtime.execute(lua.request(script, rid))
    got = conv(runtime.globals().SENT[n + 1])
    assert "err" not in got, got
    return json.loads(got["value"])


def deck_object(slug: str, guid: str, x: float, cards: int = 30, extra: list[int] = ()) -> str:
    """Lua that puts a hero's deck on the table: its cards carry the hero's deck image (the stub builds the image URL from `owner`)."""
    table = load_hero_table(slug)
    lo = table.card_ids[0]
    cards_lua = ", ".join(f"{{cid = {lo + i}, guid = 'c{guid}{i}', owner = '{slug}'}}" for i in range(cards))
    cards_lua += "".join(f", {{cid = {cid}, guid = 'x{guid}{cid}', owner = '{slug}'}}" for cid in extra)
    return f"mkobj({{guid = '{guid}', type = 'Deck', pos = Vector({x}, 1.5, 3), cards = {{{cards_lua}}}}})"


def identity_of(slug: str):
    return [(f"https://img.test/{slug}/face", f"https://img.test/{slug}/back")]


def clear_script(slugs=(BOT_HERO,), names=("bigfoot", "jackalope"), maps=()):
    tables = [load_hero_table(s) for s in slugs]
    return lua.clear_setup([(t.card_ids, identity_of(t.slug), t.character_card_id) for t in tables],
                           sorted({g for t in tables for g in t.all_guids()}), list(names), list(maps), (26.0, 36.0))


# ---------- Clean table: what it destroys and what it leaves ----------
def test_clean_destroys_every_hero_object_of_the_game_and_nothing_else(tts):  # noqa: F811
    table = load_hero_table(BOT_HERO)
    tts.execute(deck_object(BOT_HERO, "deck1", 5))
    tts.execute(f"mkobj({{guid = 'charcard', type = 'Card', cid = {table.character_card_id}, owner = 'sheet3', pos = Vector(5, 1, 9)}})")
    tts.execute("mkobj({guid = 'bag1', type = 'Bag', pos = Vector(-6, 1, 2), items = {{guid = '7fd9a3'}, {guid = 'dc0472'}, {guid = 'de393d'}}})")
    tts.execute("mkobj({guid = 'dc0472', type = 'Custom_Model', name = 'Bigfoot', pos = Vector(4, 1, 20)})")
    tts.execute("mkobj({guid = 'newguid', type = 'Custom_Token', name = '[6f2176]Jackalope', pos = Vector(-4, 1, 20)})")
    # what must stay
    tts.execute("mkobj({guid = 'roster', type = 'Infinite', infinite = true, name = 'Bigfoot', pos = Vector(19, 1, -87)})")
    tts.execute("mkobj({guid = 'shelf', type = 'Custom_Model', name = 'Bigfoot', pos = Vector(19, 1, -88)})")
    tts.execute("mkobj({guid = 'pad', type = 'Board', pos = Vector(0, 1, 0)})")
    tts.execute("mkobj({guid = 'other', type = 'Bag', pos = Vector(0, 1, 5), items = {{guid = 'zzzzzz'}, {guid = 'dc0472'}}})")
    tts.execute("mkobj({guid = 'zone', type = 'Scripting', pos = Vector(0, 4, 0), name = 'Bigfoot'})")
    tts.execute(deck_object("medusa", "meddeck", -5))
    res = run(tts, clear_script())
    assert res == {"cards": 2, "boards": 0, "bags": 1, "objects": 2, "mixed": []}
    left = {g: tts.eval(f"getObjectFromGUID('{g}') ~= nil") for g in ("deck1", "charcard", "bag1", "dc0472", "newguid", "roster",
                                                                      "shelf", "pad", "other", "zone", "meddeck")}
    assert left == {"deck1": False, "charcard": False, "bag1": False, "dc0472": False, "newguid": False, "roster": True,
                    "shelf": True, "pad": True, "other": True, "zone": True, "meddeck": True}, \
        "a bag with a foreign object, another hero's deck (same CardID range, other image), the roster and the shelves stay"


def test_clean_leaves_a_pile_that_mixes_hero_cards_with_foreign_ones_and_says_so(tts):  # noqa: F811
    tts.execute(deck_object(BOT_HERO, "mixed1", 5, cards=10, extra=[555]))
    tts.execute("local d = getObjectFromGUID('mixed1'); d.cards[#d.cards].owner = 'foreign'")
    res = run(tts, clear_script())
    assert res["cards"] == 0 and res["mixed"] == ["mixed1"] and tts.eval("getObjectFromGUID('mixed1') ~= nil")


def test_clean_destroys_the_map_boards_of_the_catalog_and_not_the_pad(tts):  # noqa: F811
    key = next(e.image_key for e in board_catalog() if e.key == "azuchi-castle")
    tts.execute(f"local b = mkobj({{guid = 'map1', type = 'Board', locked = true}}); b.getCustomObject = function() return {{image = 'https://x.test/ugc/AB/{key.lower()}/'}} end")
    pad = "98097621768AC24FF097E6997A46CF69EE91FE46"
    tts.execute(f"local b = mkobj({{guid = 'pad1', type = 'Board'}}); b.getCustomObject = function() return {{image = 'https://x.test/ugc/AB/{pad}/'}} end")
    res = run(tts, clear_script(maps=[e.image_key for e in board_catalog()]))
    assert res["boards"] == 1
    assert not tts.eval("getObjectFromGUID('map1') ~= nil") and tts.eval("getObjectFromGUID('pad1') ~= nil")


def test_clean_reaches_the_cards_in_a_hand_but_the_objects_only_inside_the_play_area(tts):  # noqa: F811
    tts.execute(deck_object(BOT_HERO, "inhand", 30))
    tts.execute("getObjectFromGUID('inhand').held_by_color = 'Green'")
    tts.execute("mkobj({guid = 'dc0472', type = 'Custom_Model', name = 'Bigfoot', pos = Vector(30, 1, 0)})")
    res = run(tts, clear_script())
    assert res["cards"] == 1 and res["objects"] == 0
    assert tts.eval("getObjectFromGUID('dc0472') ~= nil"), "30 is past the play area (|x| <= 26)"


def test_clean_builder_refuses_what_it_cannot_describe():
    with pytest.raises(ValueError):
        lua.clear_setup([], [], [], [], (26.0, 36.0))
    with pytest.raises(ValueError):
        lua.clear_setup([((1, 2), identity_of("bigfoot"), 3)], ['x"y'], [], [], (26.0, 36.0))


# ---------- the readers ----------
def test_list_bags_reports_loose_bags_and_what_they_hold_and_skips_infinite_ones(tts):  # noqa: F811
    tts.execute("mkobj({guid = 'bag1', type = 'Bag', name = '', pos = Vector(-6, 1, 2), items = {{guid = 'aaa111'}, {guid = 'bbb222'}}})")
    tts.execute("mkobj({guid = 'roster', type = 'Infinite', infinite = true, items = {{guid = 'bag9'}}})")
    rows = run(tts, lua.list_bags())
    assert [(r["guid"], r["guids"], round(r["x"])) for r in rows] == [("bag1", ["aaa111", "bbb222"], -6)]


def read_rows(tts, rows):
    return run(tts, lua.read_transforms(rows))


def test_read_transforms_finds_by_guid_then_by_name_and_tells_dials_from_miniatures(tts):  # noqa: F811
    tts.execute("mkobj({guid = 'piece1', type = 'Custom_Model', name = 'Bigfoot', pos = Vector(-4, 1.7, 22), rot = Vector(0, 180, 0)})")
    tts.execute("local d = mkobj({guid = 'newdial', type = 'Custom_Model', name = 'Bigfoot', pos = Vector(-2, 1.6, 15), rot = Vector(0, 270, 0)}); d.tbl = {MAX_VALUE = 16}")
    got = read_rows(tts, [("a", "object", ["piece1"], "bigfoot", -1, 0),
                          ("b", "dial", ["de393d"], "bigfoot", -1, 0),          # the data GUID is not on the table: found by name
                          ("c", "object", ["nothere"], "bigfoot", 1, 0),       # right name, wrong half
                          ("d", "object", ["nothere"], "", 0, 0)])
    assert got["a"]["found"] and got["a"]["guid"] == "piece1" and got["a"]["ry"] == 180 and got["a"]["z"] == 22
    assert got["b"]["guid"] == "newdial" and got["b"]["ry"] == 270
    assert got["c"] == {"found": False, "why": "none"} and got["d"] == {"found": False, "why": "none"}


def test_read_transforms_says_when_a_name_fits_several_objects_and_reads_cards_by_id_and_half(tts):  # noqa: F811
    for i, x in enumerate((-3, -4)):
        tts.execute(f"mkobj({{guid = 'h{i}', type = 'Custom_Token', name = 'Harpy', pos = Vector({x}, 1, 20)}})")
    tts.execute("mkobj({guid = 'cc', type = 'Card', cid = 309, owner = 's3', pos = Vector(-6, 1.6, 15), rot = Vector(0, 270, 0)})")
    tts.execute("mkobj({guid = 'cc2', type = 'Card', cid = 309, owner = 's3', pos = Vector(6, 1.6, 15)})")
    got = read_rows(tts, [("w", "object", [], "harpy", -1, 0), ("c", "card", [], "", -1, 309)])
    assert got["w"] == {"found": False, "why": "several"} and got["c"]["guid"] == "cc"


def test_place_map_sets_scale_place_and_turn_and_locks_it(tts):  # noqa: F811
    tts.execute("mkobj({guid = 'map1', type = 'Board', pos = Vector(20, 1, 20)})")
    assert run(tts, lua.place_map("map1", (0.07, 1.64, -1.93), 270.0, 1.1)) == {"placed": True}
    assert tts.eval("getObjectFromGUID('map1').scale.x") == pytest.approx(1.1)
    assert tts.eval("getObjectFromGUID('map1').pos.z") == pytest.approx(-1.93)
    assert tts.eval("getObjectFromGUID('map1').rot.y") == pytest.approx(270.0)
    assert tts.eval("getObjectFromGUID('map1').locked") is True
    assert run(tts, lua.place_map("nothere", (0, 1, 0), 0.0, 1.0)) == {"placed": False}
    with pytest.raises(ValueError):
        lua.place_map("map1", (0, 1, 0), 0.0, 0)


# ---------- a fake table with a world: roster copies the player drops, closed or opened ----------
import dataclasses  # noqa: E402
import re  # noqa: E402

from sparring import play, table_reset  # noqa: E402
from sparring.play import load_config  # noqa: E402
from sparring.tts.hero_table import table_defaults  # noqa: E402
from test_play import cfg_file, free_port, live  # noqa: E402,F401
from test_table_reset import GateTable, finish, press, run_main, said, shown, wait_for  # noqa: E402


@dataclasses.dataclass
class Obj:
    kind: str                       # pad | board | bag | deck | char | piece | dial | token
    guid: str
    key: str = ""                   # the row key `calibrate` reads it by ("bot:deck", "human:piece:houdini", "map")
    slug: str = ""
    x: float = 0.0
    y: float = 1.6
    z: float = 0.0
    rot: tuple = (0.0, 0.0, 0.0)
    scale: float = 1.0
    guids: list = dataclasses.field(default_factory=list)       # what a closed bag holds
    image: str = ""


PAD_IMAGE = "https://img.test/ugc/98097621768AC24FF097E6997A46CF69EE91FE46/"


def map_image(key: str) -> str:
    return f"https://img.test/ugc/{next(e.image_key for e in board_catalog() if e.key == key)}/"


class SetupTable(GateTable):
    """The gate's fake table with a world model for the new flow: the player drops a board and, for each hero, either a closed
    bag copy (its own GUID, like a copy taken from the roster) or the opened contents. Clean table empties the world; the
    reading scripts answer from it; unpacking opens the bags. The Lua behind each script has its own tests above."""

    def __init__(self, bot=BOT_HERO, human=HUMAN_HERO):
        super().__init__()
        defaults = table_defaults(bot, human)
        if (bot, human) != ("medusa", "hellboy"):          # Medusa vs Hellboy keeps the fake GUIDs the other gate tests use
            self.nick, self.pieces = defaults["nicknames"], defaults["pieces"]
            self.guid_name = {g: self.nick[f] for f, v in self.pieces.items() for g in ([v] if isinstance(v, str) else v)}
        self.bot_cards = load_hero_table(bot).card_ids[0]
        self.dial_start = {g: next(f.dial_max for slug in (bot, human) for f in load_hero_table(slug).fighters.values() if f.dial == g)
                           for g in defaults["dials"].values()}
        if defaults.get("destiny_dial"):
            self.dial_start[defaults["destiny_dial"]] = 0
        self.in_bags = True
        self.inner_on_table = set()
        self.positions, self.piece_dist, self.dials, self.bot_deck, self.human_count = {}, {}, {}, [], 0
        self.world: list[Obj] = [Obj("pad", "45c723", image=PAD_IMAGE)]
        self.map_placed: list[tuple] = []
        self.cleared = 0
        self.bags_opened: list[str] = []
        self.unpack_rows: list[tuple] = []

    # -- what the player does
    def drop_map(self, key: str, guid: str = "mapcopy1") -> Obj:
        obj = Obj("board", guid, key="map", x=14.0, z=-6.0, image=map_image(key))
        self.world.append(obj)
        return obj

    def drop_bag(self, slug: str, x: float, guid: str | None = None) -> Obj:
        obj = Obj("bag", guid or f"copy{slug}", slug=slug, x=x, z=30.0,
                  guids=[i.guids[0] for i in table_layout.items(load_hero_table(slug))])      # a miniature's other states are not in the bag
        self.world.append(obj)
        return obj

    def drop_open(self, slug: str, x: float, lost: tuple = ()) -> None:
        """The hero's bag opened and spread over its half, every object loose (`lost` GUIDs are not on the table)."""
        side = "bot" if x > 0 else "human"
        table = load_hero_table(slug)
        for i, item in enumerate(table_layout.items(table)):
            if item.guids[0] in lost:
                continue
            self.world.append(Obj(item.kind, item.guids[0], key=f"{side}:{item.key}", slug=slug, x=x + 0.5 * i, z=24.0 - i))

    # -- what the bot reads
    def do_list_boards(self, s):
        return [{"guid": o.guid, "image": o.image} for o in self.world if o.kind in ("pad", "board")]

    def do_list_bags(self, s):
        return [{"guid": o.guid, "name": "", "x": o.x, "y": o.y, "z": o.z, "guids": o.guids} for o in self.world if o.kind == "bag"]

    def do_table_heroes(self, s):
        slugs = hero_detect.hero_slugs()
        piles = []
        for o in self.world:
            if o.kind == "deck":
                piles.append({"type": "Deck", "guid": o.guid, "x": o.x, "z": o.z, "name": "", "size": 31, "pairs": [], "side": None,
                              "down": True, "counts": [30 if slug == o.slug else 0 for slug in slugs],
                              "deck_ids": [load_hero_table(slug).card_ids[0] // 100 if slug == o.slug else 0 for slug in slugs]})
        return {"piles": piles, "pieces": {}}

    def do_read_transforms(self, s):
        rows = re.findall(r'\{"([\w:]+)", "(\w+)", \{([^}]*)\}, "([^"]*)", (-?\d), (\d+)\}', s)
        out = {}
        for key, kind, guids, name, side, card in rows:
            hit = next((o for o in self.world if o.key == key), None)
            out[key] = ({"found": True, "guid": hit.guid, "x": hit.x, "y": hit.y, "z": hit.z, "rx": hit.rot[0], "ry": hit.rot[1],
                         "rz": hit.rot[2], "sx": hit.scale} if hit else {"found": False, "why": "none"})
        return out

    # -- what the bot writes
    def do_clear_setup(self, s):
        gone = [o for o in self.world if o.kind != "pad"]
        self.world = [o for o in self.world if o.kind == "pad"]
        self.cleared += 1
        self.in_bags, self.char_in_deck, self.deck_face_up = True, False, False
        self.positions, self.piece_dist, self.dials, self.bot_deck = {}, {}, {}, []
        self.arranged = {}
        return {"cards": sum(o.kind in ("deck", "char") for o in gone), "boards": sum(o.kind == "board" for o in gone),
                "bags": sum(o.kind == "bag" for o in gone), "objects": sum(o.kind in ("piece", "dial", "token") for o in gone), "mixed": []}

    def do_place_map(self, s):
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        board = next((o for o in self.world if o.guid == guid and o.kind == "board"), None)
        if board is None:
            return {"placed": False}
        scale = float(re.search(r"board.setScale\(Vector\(([-\d.e]+),", s).group(1))
        rot_y = float(re.search(r"board.setRotation\(Vector\(0, ([-\d.e]+), 0\)\)", s).group(1))
        x, y, z = (float(v) for v in re.search(r"board.setPosition\(Vector\(([^)]*)\)\)", s).group(1).split(","))
        board.x, board.y, board.z, board.rot, board.scale = x, y, z, (0.0, rot_y, 0.0), scale
        self.map_placed.append((guid, (x, y, z), rot_y, scale))
        return {"placed": True}

    def do_unpack_from_bags(self, s):
        """The real script's rules: an item that is on the table stays; one that is still in the bag it is asked from is taken out
        at its spot; a bag the player dropped (`ADOPT`) is destroyed once empty; the rest is missing."""
        self.unpacked += 1
        adopt = set(re.findall(r'\["(\w+)"\] = true', s.split("local ADOPT = ", 1)[1].splitlines()[0]))
        rows = re.findall(r'\{"(deck|piece|dial|token)", \{([^}]*)\}, "(\w+)", ([-\d.]+), ([-\d.]+), ([-\d.]+), ', s)
        taken, missing = [], []
        for kind, guids, bag_guid, x, y, z in rows:
            first = re.findall(r'"(\w+)"', guids)[0]
            self.unpack_rows.append((first, bag_guid))
            if any(o.guid in re.findall(r'"(\w+)"', guids) for o in self.world if o.kind != "bag"):
                continue
            bag = next((o for o in self.world if o.kind == "bag" and o.guid == bag_guid and first in o.guids), None)
            if bag is None:
                missing.append(first)
                continue
            bag.guids.remove(first)
            side = "bot" if bag.x > 0 else "human"
            item = next(i for i in table_layout.items(load_hero_table(bag.slug)) if first in i.guids)
            self.world.append(Obj(item.kind, first, key=f"{side}:{item.key}", slug=bag.slug, x=float(x), y=float(y), z=float(z)))
            taken.append(first)
        for bag in [o for o in self.world if o.kind == "bag" and o.guid in adopt and not o.guids]:
            self.world.remove(bag)
            self.bags_opened.append(bag.guid)
        if self.in_bags and not any(o.kind == "bag" for o in self.world) and not missing:
            self.heroes_present()
        return {"present": [], "taken": taken, "missing": missing, "bags": [], "reused": [], "bags_failed": []}

    def heroes_present(self):
        """Every hero object is out of its bag: miniatures set aside, dials full, a deck of 30 plus the character card, face up."""
        self.in_bags = False
        self.positions = {n: i + 1 for i, n in enumerate(self.nick.values())}
        self.piece_dist = {n: 99.0 for n in self.positions}
        self.bot_deck = list(range(self.bot_cards, self.bot_cards + 30))
        self.dials = {g: {"found": True, "name": "dial", "value": v, "max": 20} for g, v in self.dial_start.items()}
        self.hero_bag_decks()

    def do_arrange_objects(self, s):
        out = super().do_arrange_objects(s)
        for first, (pos, rot) in self.arranged.items():
            for o in self.world:
                if o.guid == first:
                    o.x, o.y, o.z, o.rot = pos[0], pos[1], pos[2], rot
        return out


def live_with(table, live, monkeypatch, tmp_path):
    _, fake, ports = live
    fake.return_value = table
    monkeypatch.setattr(table_reset, "PANEL_SETTLE", 0.0)
    monkeypatch.setattr(map_setup, "SETUPS_PATH", tmp_path / "map_setups.json")
    return table, fake, ports


@pytest.fixture
def setup_live(live, monkeypatch, tmp_path):  # noqa: F811
    """`live` with the new flow's table (Bigfoot vs Houdini, nothing dropped yet) and the map calibrations in a private file."""
    return live_with(SetupTable(), live, monkeypatch, tmp_path)


@pytest.fixture
def medusa_live(live, monkeypatch, tmp_path):  # noqa: F811
    """The same with Medusa vs Hellboy and the fake GUIDs of the other gate tests, for the dirty-state matrix."""
    table = SetupTable("medusa", "hellboy")
    table.positions = {n: i + 1 for i, n in enumerate(table.nick.values())}
    return live_with(table, live, monkeypatch, tmp_path)


def start(setup_live, cfg_file, tmp_path):
    return run_main(setup_live, cfg_file, tmp_path, bot_hero="auto", human_hero="auto")


def write_setups(path, **entries):
    path.write_text(json.dumps(entries), encoding="utf-8")


def default_layout():
    return json.loads(play.DEFAULT_CONFIG.read_text(encoding="utf-8"))["layout"]


# ---------- reading and deciding (no TTS) ----------
def bag_row(slug: str, x: float, guid: str | None = None, guids=None) -> dict:
    return {"guid": guid or f"copy{slug}", "name": "", "x": x, "y": 1.6, "z": 30.0,
            "guids": list(guids if guids is not None else load_hero_table(slug).all_guids())}


def pile_row(slug: str, x: float, guid: str | None = None, n: int = 31) -> dict:
    slugs = hero_detect.hero_slugs()
    return {"type": "Deck", "guid": guid or f"deck-{slug}", "x": x, "z": 17.0, "name": "", "size": n, "pairs": [],
            "down": True, "counts": [min(n, 30) if s == slug else 0 for s in slugs]}


def reading(*piles):
    return hero_detect.TableReading(list(piles), {}, hero_detect.hero_slugs())


def seen(bags=(), piles=(), board="bprd-hq"):
    boards = [{"guid": "pad", "image": PAD_IMAGE}] + ([{"guid": "map1", "image": map_image(board)}] if board else [])
    tables = {s: load_hero_table(s) for s in hero_detect.hero_slugs()}
    return player_setup.Scan(boards, player_setup._sightings(list(bags), reading(*piles), tables, set()))


def decide(found, path=None):
    setup, problems = player_setup.decide(found, path)
    return setup, " | ".join(problems)


def test_two_closed_bags_on_their_halves_and_a_map_make_a_setup(tmp_path):
    setup, problems = decide(seen([bag_row("bigfoot", 7), bag_row("houdini", -7)]), tmp_path / "none.json")
    assert problems == "" and (setup.bot, setup.human) == ("bigfoot", "houdini")
    assert setup.bags == {"bigfoot": "copybigfoot", "houdini": "copyhoudini"} and setup.entry.key == "bprd-hq"
    assert setup.calibration is None, "no calibration file: not calibrated"


def test_opened_contents_are_read_from_the_decks(tmp_path):
    setup, problems = decide(seen(piles=[pile_row("houdini", 6), pile_row("bigfoot", -9)]), tmp_path / "none.json")
    assert problems == "" and (setup.bot, setup.human) == ("houdini", "bigfoot") and setup.bags == {}


def test_one_hero_closed_and_the_other_opened(tmp_path):
    setup, _ = decide(seen([bag_row("bigfoot", 7)], [pile_row("houdini", -9)]), tmp_path / "none.json")
    assert (setup.bot, setup.human) == ("bigfoot", "houdini") and setup.bags == {"bigfoot": "copybigfoot"}


def test_the_halves_split_at_x_zero_and_the_bot_has_the_positive_one(tmp_path):
    assert player_setup.side_of(0.4) == "bot" and player_setup.side_of(-0.4) == "human"
    setup, _ = decide(seen([bag_row("medusa", 0.5), bag_row("hellboy", -0.5)]), tmp_path / "none.json")
    assert (setup.bot, setup.human) == ("medusa", "hellboy")


@pytest.mark.parametrize("name, found, words", [
    ("both heroes on the bot's half", seen([bag_row("bigfoot", 7), bag_row("houdini", 9)]), ("dos heroes", "tu mitad")),
    ("both on the player's half", seen([bag_row("bigfoot", -7), bag_row("houdini", -9)]), ("dos heroes", "mitad del bot")),
    ("no hero on the player's half", seen([bag_row("bigfoot", 7)]), ("No veo ningun heroe", "tu mitad")),
    ("no hero at all", seen(), ("mitad del bot", "tu mitad")),
    ("a hero twice on a half", seen([bag_row("bigfoot", 7), bag_row("bigfoot", 9, "copy2"), bag_row("houdini", -7)]),
     ("dos copias de Bigfoot", "mitad del bot")),
    ("the same hero on both halves", seen([bag_row("bigfoot", 7), bag_row("bigfoot", -7, "copy2")]), ("Bigfoot esta en las dos mitades",)),
    ("no map", seen([bag_row("bigfoot", 7), bag_row("houdini", -7)], board=None), ("No hay ningun mapa",)),
])
def test_what_the_player_must_fix_is_said_clearly(name, found, words, tmp_path):
    setup, problems = decide(found, tmp_path / "none.json")
    assert setup is None, name
    assert all(w in problems for w in words), (name, problems)


def test_a_hero_the_bot_cannot_play_is_named_when_its_deck_is_loose_and_flagged_when_it_is_in_a_bag(tmp_path):
    loose = {**pile_row("bigfoot", 7, n=31), "counts": [0] * len(hero_detect.hero_slugs()), "catalog": "blackbeard"}
    found = seen([bag_row("houdini", -7)], [loose])
    setup, problems = decide(found, tmp_path / "none.json")
    assert setup is None and "Blackbeard" in problems and "no sabe jugar" in problems and "Heroes jugables" in problems
    closed = seen([bag_row("houdini", -7), bag_row("bigfoot", 7, guids=["aaa111", "bbb222", "ccc333", "ddd444"])])
    setup, problems = decide(closed, tmp_path / "none.json")
    assert setup is None and "no reconozco como un heroe jugable" in problems


def test_a_bag_that_holds_a_mix_of_heroes_or_a_single_shared_guid_is_nobodys():
    tables = {s: load_hero_table(s) for s in hero_detect.hero_slugs()}
    mixed = list(tables["bigfoot"].all_guids()[:2]) + list(tables["houdini"].all_guids()[:2])
    assert player_setup._bag_hero(mixed, tables) is None
    assert player_setup._bag_hero(tables["bigfoot"].all_guids()[:3], tables) == "bigfoot", "a bag with some of it taken out is still his"
    assert player_setup._bag_hero(["18c384"], tables) is None, "Lobster's and the Jackalope's dial share a GUID"


def test_the_leftover_centre_decks_of_the_official_save_do_not_count_as_unknown_heroes(tmp_path):
    centre = {**pile_row("bigfoot", -5.8, "addeca", n=78), "counts": [0] * len(hero_detect.hero_slugs())}
    tables = {s: load_hero_table(s) for s in hero_detect.hero_slugs()}
    got = player_setup._sightings([], reading(centre), tables, {"addeca"})
    assert got == []
    assert len(player_setup._sightings([], reading(centre), tables, set())) == 1


def test_a_calibrated_map_brings_its_transform_and_layout(tmp_path):
    path = tmp_path / "setups.json"
    write_setups(path, **{"bprd-hq": {"scale": 1.1, "position": [0.07, 1.64, -1.93], "rot_y": 270.0, "layout": default_layout()}})
    setup, _ = decide(seen([bag_row("bigfoot", 7), bag_row("houdini", -7)]), path)
    assert setup.calibration.scale == 1.1 and setup.calibration.rot_y == 270.0 and setup.calibration.position == (0.07, 1.64, -1.93)
    assert player_setup.describe(setup) == "Bot: Bigfoot · Tú: Houdini · Mapa: B.P.R.D. Headquarters"
    assert "no esta calibrado" in player_setup.not_calibrated(setup)


def test_the_repo_calibrates_bprd_hq_with_the_transform_and_layout_of_the_gate_that_was_verified_live():
    setup = map_setup.setup_for("bprd-hq")
    raw = json.loads(play.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    assert (setup.scale, setup.position, setup.rot_y) == (1.10, (0.07, 1.64, -1.93), 270.0)
    assert setup.layout == raw["layout"], "the entry is the layout the gate had before maps were calibrated"
    over = map_setup.overrides("bprd-hq")
    assert over["bot_deck_spot"] == raw["bot_deck_spot"] and over["human_deck_spot"] == raw["human_deck_spot"]


def test_a_malformed_calibration_file_is_an_error_not_a_silent_default(tmp_path):
    path = tmp_path / "setups.json"
    for bad in ({"scale": 0, "position": [0, 1, 0], "layout": default_layout()}, {"scale": 1, "position": [0, 1], "layout": default_layout()},
                {"scale": 1, "position": [0, 1, 0], "layout": {"bot": {}, "human": {}}}):
        write_setups(path, azuchi=bad)
        with pytest.raises(ValueError):
            map_setup.load_all(path)
    path.write_text("{ nope", encoding="utf-8")
    with pytest.raises(ValueError):
        map_setup.load_all(path)
    assert map_setup.load_all(tmp_path / "missing.json") == {}


# ---------- the gate end to end: Clean table, drag, Prepare ----------
def azuchi_setup() -> dict:
    """A calibration that differs from the default in everything that matters: other scale and place, decks moved 3 units out."""
    layout = default_layout()
    layout["bot"]["deck"]["pos"] = [8.5, 1.76, 20.0]
    layout["human"]["deck"]["pos"] = [-9.7, 1.76, 20.0]
    layout["bot"]["character_card"]["pos"] = [8.6, 1.61, 17.0]
    return {"scale": 0.95, "position": [1.5, 1.7, -2.0], "rot_y": 90.0, "layout": layout}


def lifted(pos):
    return (pos[0], pos[1] + table_layout.SETTLE_LIFT, pos[2])


def prepared_ok(table, fake):
    return wait_for(lambda: shown(table, "btn_start") == (True, True), 12.0)


def client_for(setup_live):
    from test_table_reset import client_for as make
    return make(setup_live)


@pytest.mark.gate
def test_clean_table_leaves_no_hero_and_no_map_and_asks_the_player_to_drag_them(setup_live, cfg_file, tmp_path):
    table, fake, _ = setup_live
    table.drop_map("bprd-hq")
    table.drop_open("bigfoot", 7)
    table.drop_bag("houdini", -7)
    table.leftovers["addeca"] = "DeckCustom"
    stop, t, result = start(setup_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_clean") == (True, True))
        press(fake, "clean_table")
        assert wait_for(lambda: said(table, "Arrastra ahora el mapa")())
        assert [o.kind for o in table.world] == ["pad"], "no hero, no bag and no map left; the table's own pad stays"
        assert table.cleared == 1 and "addeca" in table.removed, "the leftovers of the save go too"
        assert shown(table, "btn_clean") == (True, True) and shown(table, "btn_prep") == (True, True)
        assert shown(table, "btn_start") == (False, False)
        assert "Mesa limpia" in " ".join(table.broadcasts)
        assert "(0 objetos quitados)" not in " ".join(table.broadcasts), "the count includes the leftovers it removed"
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_closed_bags_on_a_calibrated_map_with_two_non_default_heroes(setup_live, cfg_file, tmp_path):
    table, fake, _ = setup_live
    write_setups(map_setup.SETUPS_PATH, **{"azuchi-castle": azuchi_setup()})
    table.drop_map("azuchi-castle", "azucopy")
    table.drop_bag("bigfoot", 7)
    table.drop_bag("houdini", -7)
    stop, t, result = start(setup_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert prepared_ok(table, fake), table.broadcasts[-6:]
        text = " ".join(table.broadcasts)
        assert "Bot: Bigfoot Tu: Houdini Mapa: Azuchi Castle" in text and "Mesa preparada" in text
        assert "no esta calibrado" not in text
        assert table.map_placed == [("azucopy", (1.5, 1.7, -2.0), 90.0, 0.95)]
        assert {bag for _, bag in table.unpack_rows} == {"copybigfoot", "copyhoudini"}, "the items come out of the copies the player dropped"
        assert sorted(table.bags_opened) == ["copybigfoot", "copyhoudini"] and not [o for o in table.world if o.kind == "bag"]
        layout = azuchi_setup()["layout"]
        assert table.arranged["7fd9a3"][0] == lifted(layout["bot"]["deck"]["pos"]), "Bigfoot's deck at the bot slot of THIS map"
        assert table.arranged["a3afc4"][0] == lifted(layout["human"]["deck"]["pos"]), "Houdini's deck at the player slot of this map"
        assert table.char_loose[0][0] == lifted(layout["bot"]["character_card"]["pos"])
        assert table.arranged["dc0472"][0] == lifted(layout["bot"]["pieces"][0]["pos"]) and table.arranged["de393d"][0] == \
            lifted(layout["bot"]["dial"]["pos"])
        assert shown(table, "btn_prep") == (False, False) and shown(table, "btn_clean") == (True, True)
        assert not any("Tu turno" in b for b in table.broadcasts), "preparing is not starting"
    finally:
        finish(stop, t, result)
    # after Prepare, finding the decks in game points at where they were laid for this map
    client = client_for(setup_live)
    try:
        cfg = play.detect_board(client, load_config(cfg_file(bot_hero="auto", human_hero="auto")))
        assert cfg.raw["bot_deck_spot"] == [8.5, 20.0] and cfg.raw["human_deck_spot"] == [-9.7, 20.0]
        assert cfg.raw["layout"]["bot"]["deck"]["pos"] == [8.5, 1.76, 20.0]
        resolved = play.resolve_heroes(client, cfg, None, lambda line: None)
        assert resolved.heroes == ("bigfoot", "houdini")
        assert resolved.detected_decks == {"bot": "7fd9a3", "human": "a3afc4"}
    finally:
        client.close()


@pytest.mark.gate
def test_opened_contents_with_the_heroes_on_the_other_halves(setup_live, cfg_file, tmp_path):
    table, fake, _ = setup_live
    write_setups(map_setup.SETUPS_PATH, **{"azuchi-castle": azuchi_setup()})
    table.drop_map("azuchi-castle")
    table.drop_open("houdini", 6)
    table.drop_open("bigfoot", -9)
    stop, t, result = start(setup_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert prepared_ok(table, fake), table.broadcasts[-6:]
        assert "Bot: Houdini Tu: Bigfoot" in " ".join(table.broadcasts)
        assert table.bags_opened == [] and table.unpack_rows and all(b == load_hero_table(
            "houdini" if g in load_hero_table("houdini").all_guids() else "bigfoot").inner_bag for g, b in table.unpack_rows)
        layout = azuchi_setup()["layout"]
        assert table.arranged["a3afc4"][0] == lifted(layout["bot"]["deck"]["pos"]) and table.arranged["7fd9a3"][0] == \
            lifted(layout["human"]["deck"]["pos"]), "each hero lands on the slots of the half it was dropped on"
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_an_uncalibrated_map_is_used_as_it_lies_with_the_default_layout_and_the_chat_gives_the_command(setup_live, cfg_file, tmp_path):
    table, fake, _ = setup_live
    table.drop_map("azuchi-castle", "azucopy")
    table.drop_bag("bigfoot", 7)
    table.drop_bag("houdini", -7)
    stop, t, result = start(setup_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert prepared_ok(table, fake), table.broadcasts[-6:]
        text = " ".join(table.broadcasts)
        assert "no esta calibrado" in text and "python -m sparring.calibrate --map azuchi-castle" in text
        assert table.map_placed == [], "an uncalibrated map is neither scaled nor moved"
        board = next(o for o in table.world if o.kind == "board")
        assert (board.x, board.z, board.scale) == (14.0, -6.0, 1.0)
        assert table.arranged["7fd9a3"][0] == lifted(default_layout()["bot"]["deck"]["pos"])
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_both_heroes_on_one_half_is_refused_with_a_clear_line_and_nothing_is_touched_until_it_is_fixed(setup_live, cfg_file, tmp_path):
    table, fake, _ = setup_live
    table.drop_map("bprd-hq")
    bag_a, bag_b = table.drop_bag("bigfoot", 7), table.drop_bag("houdini", 9)
    stop, t, result = start(setup_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "No he tocado nada"))
        text = " ".join(table.broadcasts)
        assert "dos heroes" in text and "No veo ningun heroe en tu mitad" in text
        assert table.unpacked == 0 and table.map_placed == [] and table.arranged == {}
        assert shown(table, "btn_start") == (False, False) and shown(table, "btn_prep") == (True, True)
        bag_b.x = -9.0                                                       # the player moves one over
        said_before = len(table.broadcasts)
        press(fake, "prepare_table")
        assert prepared_ok(table, fake), table.broadcasts[said_before:]
        assert "Bot: Bigfoot" in " ".join(table.broadcasts[said_before:]) and "Tu: Houdini" in " ".join(table.broadcasts[said_before:])
    finally:
        finish(stop, t, result)


@pytest.mark.gate
@pytest.mark.parametrize("what, arrange, words", [
    ("no map", lambda t: (t.drop_bag("bigfoot", 7), t.drop_bag("houdini", -7)), ("No hay ningun mapa",)),
    ("nothing dropped", lambda t: t.drop_map("bprd-hq"), ("mitad del bot", "tu mitad")),
    ("the same hero twice", lambda t: (t.drop_map("bprd-hq"), t.drop_bag("bigfoot", 7), t.drop_bag("bigfoot", -7, "copy2")),
     ("Bigfoot esta en las dos mitades",)),
])
def test_prepare_refuses_and_says_why(setup_live, cfg_file, tmp_path, what, arrange, words):
    table, fake, _ = setup_live
    arrange(table)
    stop, t, result = start(setup_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "No he tocado nada")), what
        assert all(w in " ".join(table.broadcasts) for w in words), (what, table.broadcasts)
        assert table.unpacked == 0 and shown(table, "btn_start") == (False, False)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_an_opened_hero_that_lost_a_piece_is_named_and_the_button_stays(setup_live, cfg_file, tmp_path):
    table, fake, _ = setup_live
    table.drop_map("bprd-hq")
    table.drop_open("bigfoot", 7, lost=("b31c7a",))
    table.drop_bag("houdini", -7)
    stop, t, result = start(setup_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "No he podido preparar la mesa"))
        text = " ".join(table.broadcasts)
        assert "Faltan en la mesa estos objetos de Bigfoot (b31c7a)" in text
        assert shown(table, "btn_start") == (False, False) and shown(table, "btn_prep") == (True, True)
    finally:
        finish(stop, t, result)


# ---------- calibrating a map ----------
def hand_arranged(table, map_key="azuchi-castle"):
    """Ivan's table: the map scaled and turned, both heroes out of their bags with every object where he wants it."""
    board = table.drop_map(map_key)
    board.x, board.y, board.z, board.rot, board.scale = 2.5, 1.64, -3.0, (0.0, 89.99, 0.0), 0.9
    table.drop_open("bigfoot", 7)
    table.drop_open("houdini", -7)
    for i, o in enumerate(o for o in table.world if o.key.startswith(("bot:", "human:"))):
        sign = 1 if o.key.startswith("bot:") else -1
        o.x, o.y, o.z, o.rot = sign * (4.0 + i), 1.6 + 0.01 * i, 15.0 + 0.5 * i, (359.99, 90.0 if sign > 0 else 270.0, 180.04)
    table.world += [Obj("char", f"chr{side}", key=f"{side}:character", x=sign * 5.5, y=1.61, z=15.0, rot=(0.0, 90.0, 0.0))
                    for side, sign in (("bot", 1), ("human", -1))]


def test_calibrate_writes_the_map_entry_from_the_live_table_in_the_order_of_the_slots(setup_live, tmp_path):
    from sparring import calibrate
    table, _, _ = setup_live
    hand_arranged(table)
    path = tmp_path / "out.json"
    client = client_for(setup_live)
    try:
        lines = []
        assert calibrate.calibrate(client, "azuchi-castle", load_config(play.DEFAULT_CONFIG).raw, path, echo=lines.append) == 0
    finally:
        client.close()
    assert "Calibrado azuchi-castle" in lines[-1] and "escala 0.9" in lines[-1]
    entry = map_setup.setup_for("azuchi-castle", path)
    assert (entry.scale, entry.position, entry.rot_y) == (0.9, (2.5, 1.64, -3.0), 90.0), "89.99 is the 90 it was meant to be"
    bot, human = entry.layout["bot"], entry.layout["human"]
    deck = next(o for o in table.world if o.key == "bot:deck")
    assert bot["deck"] == {"pos": [round(deck.x, 2), round(deck.y, 2), round(deck.z, 2)], "rot": [0.0, 90.0, 180.0]}
    assert bot["character_card"] == {"pos": [5.5, 1.61, 15.0], "rot": [0.0, 90.0, 0.0]} and human["character_card"]["pos"][0] == -5.5
    assert len(bot["pieces"]) == 2 and len(bot["sidekick_dials"]) == 1 and bot["dial"]["pos"][0] > 0 > human["dial"]["pos"][0]
    # the entry reproduces the table: Prepare with the same heroes lays every object where it stood
    for side, slug in (("bot", "bigfoot"), ("human", "houdini")):
        plan = table_layout.plan({"layout": entry.layout}, side, load_hero_table(slug))
        assert plan.unplaced == []
        for p in plan.placements:
            here = next(o for o in table.world if o.guid == p.guids[0])
            assert list(p.slot.pos) == [round(here.x, 2), round(here.y, 2), round(here.z, 2)], p.guids


def test_calibrate_keeps_the_other_maps_and_replaces_the_one_it_calibrates(setup_live, tmp_path):
    from sparring import calibrate
    table, _, _ = setup_live
    path = tmp_path / "out.json"
    write_setups(path, **{"bprd-hq": json.loads(json.dumps({"scale": 1.1, "position": [0, 1, 0], "rot_y": 270.0, "layout": default_layout()}))})
    hand_arranged(table)
    client = client_for(setup_live)
    try:
        assert calibrate.calibrate(client, "azuchi-castle", load_config(play.DEFAULT_CONFIG).raw, path, echo=lambda line: None) == 0
        table.world[1].scale = 0.8
        assert calibrate.calibrate(client, "azuchi-castle", load_config(play.DEFAULT_CONFIG).raw, path, echo=lambda line: None) == 0
    finally:
        client.close()
    assert sorted(map_setup.load_all(path)) == ["azuchi-castle", "bprd-hq"]
    assert map_setup.setup_for("azuchi-castle", path).scale == 0.8 and map_setup.setup_for("bprd-hq", path).scale == 1.1


def test_calibrate_dry_run_writes_nothing_and_never_sends_a_write(setup_live, tmp_path):
    from sparring import calibrate
    table, fake, _ = setup_live
    hand_arranged(table)
    path = tmp_path / "out.json"
    client = client_for(setup_live)
    try:
        lines = []
        assert calibrate.calibrate(client, "azuchi-castle", load_config(play.DEFAULT_CONFIG).raw, path, True, lines.append) == 0
    finally:
        client.close()
    assert not path.exists() and "Nada guardado" in lines[0]
    writes = {"place_map", "clear_setup", "arrange_objects", "unpack_from_bags", "set_panel", "create_panel", "broadcast", "composite"}
    assert not writes & set(table.sent), table.sent


@pytest.mark.parametrize("what, prepare, slug, words", [
    ("another map on the table", lambda t: hand_arranged(t, "bprd-hq"), "azuchi-castle", "esta el mapa bprd-hq, no azuchi-castle"),
    ("unknown key", lambda t: hand_arranged(t), "atlantis", "no esta en el catalogo"),
    ("no heroes", lambda t: t.drop_map("azuchi-castle"), "azuchi-castle", "No puedo calibrar"),
    ("a hero still in its bag", lambda t: (t.drop_map("azuchi-castle"), t.drop_bag("bigfoot", 7), t.drop_open("houdini", -7)), "azuchi-castle",
     "el mazo de Bigfoot (no esta)"),
])
def test_calibrate_says_what_is_wrong_and_writes_nothing(setup_live, tmp_path, what, prepare, slug, words):
    from sparring import calibrate
    table, _, _ = setup_live
    prepare(table)
    path = tmp_path / "out.json"
    client = client_for(setup_live)
    try:
        lines = []
        assert calibrate.calibrate(client, slug, load_config(play.DEFAULT_CONFIG).raw, path, echo=lines.append) == 2, what
    finally:
        client.close()
    assert words in " ".join(lines) and not path.exists()


def test_calibrate_names_what_it_could_not_find(setup_live, tmp_path):
    from sparring import calibrate
    table, _, _ = setup_live
    hand_arranged(table)
    table.world = [o for o in table.world if o.key != "human:piece:bess"]
    client = client_for(setup_live)
    try:
        lines = []
        assert calibrate.calibrate(client, "azuchi-castle", load_config(play.DEFAULT_CONFIG).raw, tmp_path / "out.json", echo=lines.append) == 2
    finally:
        client.close()
    assert "No he encontrado en la mesa" in lines[0] and "bess de Houdini (no esta)" in lines[0]


# ---------- Prepare on heroes that are already out (played before, or dirty in any way) ----------
from test_table_reset import DIRTY, cards_scattered, game_started, mid_game, pristine  # noqa: E402


def medusa_hellboy_out(table):
    """Medusa (bot) and Hellboy (you) opened on their halves with a map: the state the old single button used to start from."""
    table.drop_map("bprd-hq")
    table.drop_open("medusa", 7)
    table.drop_open("hellboy", -7)
    table.heroes_present()
    table.make_ready()


@pytest.mark.gate
@pytest.mark.parametrize("name", list(DIRTY))
def test_every_dirty_state_of_heroes_already_out_ends_clean_and_prepared(medusa_live, cfg_file, tmp_path, name):
    table, fake, _ = medusa_live
    dirt, over = DIRTY[name]
    medusa_hellboy_out(table)
    state = tmp_path / "s.json"
    dirt(table, state)
    stop, t, result = run_main(medusa_live, cfg_file, tmp_path, **over)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        assert shown(table, "btn_start") == (False, False), f"{name}: dirty, yet the start is offered"
        press(fake, "prepare_table")
        assert prepared_ok(table, fake), table.broadcasts[-4:]
        assert shown(table, "btn_prep") == (False, False)
        pristine(table, state)
        assert any("Mesa preparada" in b for b in table.broadcasts) and not game_started(table)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_table_that_is_dirty_in_every_way_at_once_ends_prepared(medusa_live, cfg_file, tmp_path):
    table, fake, _ = medusa_live
    medusa_hellboy_out(table)
    state = tmp_path / "s.json"
    mid_game(table, state)
    cards_scattered(table, state)
    table.deck_face_up = True
    table.leftovers.update({"addeca": "DeckCustom", "5085eb": "Custom_Assetbundle"})
    table.piece_dist.clear()
    stop, t, result = run_main(medusa_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert prepared_ok(table, fake)
        pristine(table, state)
        assert sorted(table.removed) == ["5085eb", "addeca"] and table.leftovers == {}
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_what_preparing_cannot_fix_is_named_and_the_button_stays(medusa_live, cfg_file, tmp_path):
    table, fake, _ = medusa_live
    medusa_hellboy_out(table)
    table.sticky = 3                                   # three cards in the human's hand that the bot's reset cannot move
    table.piece_dist.clear()
    stop, t, result = run_main(medusa_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "queda esto", "Red 3"))
        assert shown(table, "btn_prep") == (True, True) and shown(table, "btn_start") == (False, False)
        assert all(d == 99.0 for d in table.piece_dist.values()), "the rest was prepared"
        table.sticky = 0                                # the human takes them away; pressing again finishes
        press(fake, "prepare_table")
        assert prepared_ok(table, fake)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_table_that_cannot_be_prepared_says_so_and_can_be_retried(setup_live, cfg_file, tmp_path):
    table, fake, _ = setup_live
    table.drop_map("bprd-hq")
    table.drop_bag("bigfoot", 7)
    table.drop_bag("houdini", -7)
    real = table.do_unpack_from_bags
    table.do_unpack_from_bags = lambda s: (lambda out: table.bot_deck.clear() or out)(real(s))      # the deck cannot be gathered
    stop, t, result = start(setup_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "No he podido preparar la mesa", "arreglarla a mano"))
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        assert shown(table, "btn_start") == (False, False) and not game_started(table)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_second_press_of_prepare_on_a_prepared_table_changes_nothing_that_matters(setup_live, cfg_file, tmp_path):
    table, fake, _ = setup_live
    write_setups(map_setup.SETUPS_PATH, **{"azuchi-castle": azuchi_setup()})
    table.drop_map("azuchi-castle")
    table.drop_bag("bigfoot", 7)
    table.drop_bag("houdini", -7)
    stop, t, result = start(setup_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert prepared_ok(table, fake)
        arranged, seen_before = dict(table.arranged), len(table.broadcasts)
        press(fake, "prepare_table")                                          # a stale or double click
        assert wait_for(lambda: said(table, "Mesa preparada")() and len(table.broadcasts) > seen_before + 3)
        assert table.arranged == arranged and shown(table, "btn_start") == (True, True)
        assert [o.kind for o in table.world].count("board") == 1 and not [o for o in table.world if o.kind == "bag"]
    finally:
        finish(stop, t, result)
