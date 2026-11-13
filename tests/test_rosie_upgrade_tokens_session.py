"""The bot's Rosie flips the four upgrade tokens on the table (FakeTTS, batch mode): the first look keeps the tokens where they lie as the four
spots of the row, an activation turns a token up and pings it, a deactivation turns it down and sends it to the end of the row (every token
that changed place is pinged), the reset turns all four down, a missing token is said once, and a resumed game puts the tokens back from the
engine's row with the saved spots. A human Rosie flips her own tokens: the session only says it in the chat.

The fake table models the live tokens: a GUID, a position and a Z rotation (0 = inactive face up, 180 = active face up), and its
`do_set_upgrade_tokens` does what the Lua of `lua_rosie.set_upgrade_tokens` does to them (tests/test_rosie_upgrade_tokens.py runs that Lua)."""
from __future__ import annotations

import json
import re

import pytest

from sparring import session_rosie, upgrades
from sparring.ai_medusa import MedusaAI
from sparring.session import Session
from sparring.state import Game
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build
from test_human_pile_to_hand import HandTable
from test_rosie_upgrade_tokens import GUIDS, ORDER, SLOTS, SLUG, near

SPOTS = {"0": [list(s) for s in SLOTS]}


class TokenTable(HandTable):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.upgrade_tokens = {g: {"pos": list(s), "rot_z": 0.0} for g, s in zip(ORDER, SLOTS)}
        self.upgrade_writes: list[dict] = []
        self.upgrade_pings: list[list[str]] = []
        self.missing_upgrade_tokens: set[str] = set()

    def do_set_upgrade_tokens(self, s):
        row = s.split("local ROW =")[1].split("local ACTIVE")[0]
        rows = [(g, float(a), float(i)) for g, a, i in re.findall(r'\{"(\w+)", ([-\d.]+), ([-\d.]+)\}', row)]
        active = int(re.search(r"local ACTIVE = (\d+)", s).group(1))
        tail = s.split("local SLOTS = ")[1].split("\n")[0]
        slots = None if tail.strip() == "nil" else [tuple(float(v) for v in m) for m in re.findall(r"\{([-\d.]+), ([-\d.]+), ([-\d.]+)\}", tail)]
        found, flipped, moved, touched, before = 0, 0, 0, [], []
        for i, (guid, on_z, off_z) in enumerate(rows):
            tok = self.upgrade_tokens.get(guid)
            if tok is None or guid in self.missing_upgrade_tokens:
                continue
            found += 1
            before.append(list(tok["pos"]))
            changed = False
            want = on_z if i < active else off_z
            if near(tok["rot_z"], want) > 1:
                tok["rot_z"] = want % 360
                flipped += 1
                changed = True
            if slots is not None and (abs(tok["pos"][0] - slots[i][0]) > 0.3 or abs(tok["pos"][2] - slots[i][2]) > 0.3):
                tok["pos"] = [slots[i][0], slots[i][1] + 0.3, slots[i][2]]
                moved += 1
                changed = True
            if changed:
                touched.append(guid)
        self.upgrade_writes.append({"flipped": flipped, "moved": moved})
        if touched:
            self.upgrade_pings.append(touched)
        return {"found": found, "total": len(rows), "before": before, "flipped": flipped, "moved": moved, "guids": touched}

    def faces(self):
        return {g: round(t["rot_z"]) for g, t in self.upgrade_tokens.items()}

    def xs(self, order):
        return [round(self.upgrade_tokens[g]["pos"][0]) for g in order]


def row_guids(game, player=0):
    return [GUIDS[u["id"]] for u in upgrades.row(game, player)]


def step(session, table, game, player=0):
    session_rosie.track(session)
    click(session, table, Event.MANEUVER)


@pytest.fixture
def bots(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, SLUG, "hellboy", ("We Can Do It!", "Full Metal"), table_cls=TokenTable)
    session_rosie.forget(session)
    session_rosie.track(session, announce=True)
    click(session, table, Event.MANEUVER)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


@pytest.fixture
def mine(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", SLUG, (), table_cls=TokenTable)
    session_rosie.forget(session)
    session_rosie.track(session, announce=True)
    click(session, table, Event.MANEUVER)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def test_the_first_look_keeps_the_tokens_where_they_lie_as_the_four_spots_and_turns_nothing(bots):
    session, table, game, fake, cfg = bots
    assert session.upgrade_slots == SPOTS
    assert table.faces() == {g: 0 for g in ORDER} and table.upgrade_pings == []


def test_when_the_bots_rosie_activates_an_upgrade_the_token_turns_up_and_is_pinged(bots):
    session, table, game, fake, cfg = bots
    bot_turn(session, table, [])                                # its turn starts: the first upgrade is activated
    assert upgrades.count(game, 0) == 1
    assert table.faces() == {GUIDS["merlin_engine"]: 180, GUIDS["cavity_magnetron"]: 0, GUIDS["sedgley_fist_gun"]: 0, GUIDS["whizbang"]: 0}
    assert table.upgrade_pings[-1] == [GUIDS["merlin_engine"]]


def test_a_deactivation_turns_the_token_down_sends_it_to_the_end_of_the_row_and_pings_what_moved(bots):
    session, table, game, fake, cfg = bots
    upgrades.activate(game, 0, 2)
    step(session, table, game)
    upgrades.deactivate(game, 0)                                # merlin goes face down to the end of the row
    step(session, table, game)
    row = row_guids(game)
    assert row[-1] == GUIDS["merlin_engine"]
    assert table.xs(row) == [10, 11, 12, 13]                    # the row lies left to right in the new order
    assert table.faces()[GUIDS["merlin_engine"]] == 0 and table.faces()[GUIDS["cavity_magnetron"]] == 180
    assert set(table.upgrade_pings[-1]) == set(ORDER)           # all four changed place


def test_the_reset_at_the_end_of_the_turn_turns_all_four_down_again(bots):
    session, table, game, fake, cfg = bots
    upgrades.activate(game, 0, 4)
    step(session, table, game)
    assert set(table.faces().values()) == {180}
    game.fx.set_counter(0, "upgrades", 0)
    step(session, table, game)
    assert set(table.faces().values()) == {0}


def test_an_unchanged_row_writes_nothing(bots):
    session, table, game, fake, cfg = bots
    before = len(table.upgrade_writes)
    step(session, table, game)
    assert len(table.upgrade_writes) == before


def test_a_missing_token_is_said_and_the_game_goes_on(bots):
    session, table, game, fake, cfg = bots
    told, say = [], session.say
    session.say = lambda text, *a, **k: (told.append(text), say(text, *a, **k))[1]
    table.missing_upgrade_tokens.add(GUIDS["whizbang"])
    upgrades.activate(game, 0)
    step(session, table, game)
    assert any("no encuentro" in m.lower() and "Rosie" in m for m in told), told
    assert upgrades.count(game, 0) == 1


def test_a_resumed_game_puts_the_tokens_back_as_the_saved_engine_row_says_using_the_saved_spots(bots):
    session, table, game, fake, cfg = bots
    upgrades.activate(game, 0, 3)
    upgrades.deactivate(game, 0)                                 # cavity, sedgley active; row: cavity, sedgley, whizbang, merlin
    step(session, table, game)
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["upgrade_slots"] == SPOTS
    for g, s in zip(ORDER, SLOTS):                               # the player knocked the tokens about while the bot was off
        table.upgrade_tokens[g] = {"pos": list(s), "rot_z": 0.0}
    twin = Session(Game.new(cfg.board, seed=3, controllers={}, bot_player=0, heroes=cfg.heroes), session.client, MedusaAI(0), session.cfg)
    twin.game_id = session.game_id
    twin.load_dict(saved)
    assert twin.upgrade_slots == SPOTS
    session_rosie.track(twin, announce=True)
    click(twin, table, Event.MANEUVER)
    row = row_guids(twin.game)
    assert row[0] == GUIDS["cavity_magnetron"] and row[-1] == GUIDS["merlin_engine"]
    assert table.xs(row) == [10, 11, 12, 13]
    assert [table.faces()[g] for g in row] == [180, 180, 0, 0]


def test_a_human_rosie_gets_the_chat_and_the_bot_touches_no_token(mine):
    session, table, game, fake, cfg = mine
    told, say = [], session.say
    session.say = lambda text, *a, **k: (told.append(text), say(text, *a, **k))[1]
    upgrades.activate(game, 1)
    step(session, table, game)
    assert any("activa" in m for m in told) and table.upgrade_writes == [] and session.upgrade_slots == {}


def test_a_bad_saved_spot_list_is_ignored():
    assert session_rosie.read_slots({"0": [[1, 2, 3]] * 3, "1": "x", "7": [[1, 2, 3]] * 4}) == {}
    good = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [1, 1, 1]]
    assert session_rosie.read_slots({"0": good}) == {"0": [[float(v) for v in p] for p in good]}
    assert session_rosie.read_slots(None) == {}
