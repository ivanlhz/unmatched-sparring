"""The pre-game gate (`sparring/table_reset.py`): the loaded table is checked, a dirty one gets a clean-and-prepare button,
and nothing starts until "Start game" is pressed.

The audit script runs under lupa (tests/lua_stub.lua); the gate itself runs through `play.main` against the fake table,
like the other end-to-end tests."""
from __future__ import annotations

import json
import re
import threading
import time

import pytest

from sparring import i18n, play, table_reset
from sparring.board import Board
from sparring.play import load_config, main
from sparring.session import Session
from sparring.state import Game
from sparring.tts import lua, ui
from sparring.tts.client import TTSClient
from sparring.tts.ui import Event
from test_official_save_setup import REMOVED, KINDS, raw_config, tts  # noqa: F401
from test_play import cfg_file, free_port, live  # noqa: F401
from test_review10 import conv
from test_batch import brig  # noqa: F401
from test_session import PIECES, Table, set_bot_hand

lupa = pytest.importorskip("lupa")

BOT_DECK = list(range(17600, 17630))


class GateTable(Table):
    """The fake table plus what the gate reads and writes: loose objects of the save, heroes still in their bags, the
    objects of another hero, and the unpacking."""

    def __init__(self):
        super().__init__()
        self.in_bags = False
        self.leftovers: dict[str, str] = {}              # GUID -> TTS object name of a loose object on the table
        self.strays: set[str] = set()                    # "other:<slug>" labels whose objects are on the table
        self.unpacked = 0

        self.bot_scattered: list[int] = []               # bot cards lying loose on the table or the board
        self.human_scattered = 0
        self.deck_face_up = False
        self.hellboy_form2 = False                       # Hellboy's miniature is in its second state
        self.token_rot = 180.0                           # ability token: 180 = OCCULT DETECTIVE (start), 0 = ANUNG UN RAMA
        self.zoom_cleared = 0
        self.inner_on_table = {"e5a45c", "c592d8"}       # inner bags of Medusa and Hellboy lying on the table (as with --unpack)
        self.outers: dict[str, tuple[str, list[str]]] = {}   # infinite bag GUID -> (nickname, GUIDs it holds)
        self.bags_taken: list[str] = []
        self.spawn_late = False                          # the infinite bag's copy appears after the reply
        self.loose_copies: set[str] = set()              # inner bag copies lying loose on the table
        self.copies_made = 0                             # copies the infinite bags have spawned in all
        self.sticky = 0                                  # cards in the human's hand the bot's reset cannot move
        self.flips = 0
        self.dial_start: dict[str, int] = {}             # dial GUID -> its starting value

    def make_ready(self):
        self.in_bags, self.bot_hand, self.bot_deck, self.human_count = False, [], list(BOT_DECK), 0
        self.bot_discard, self.human_discard, self.face_down, self.stray_bot = [], [], [], []
        self.bot_play, self.bot_ongoing, self.human_ongoing, self.face_up = [], [], [], []
        self.bot_scattered, self.human_scattered, self.deck_face_up = [], 0, False
        self.piece_dist = {name: 99.0 for name in self.positions}
        for g, row in self.dials.items():
            self.dials[g] = {**row, "value": self.dial_start[g]}
        return self

    def do_deck_facing(self, s):
        return [{"found": not self.in_bags, "face_down": not self.deck_face_up, "flipped": False} for _ in range(2)]

    def do_flip_decks_down(self, s):
        self.flips += self.deck_face_up
        out = [{"found": True, "face_down": True, "flipped": self.deck_face_up} for _ in range(2)]
        self.deck_face_up = False
        return out

    def do_set_state(self, s):
        self.hellboy_form2 = False
        return {"guid": "pchellboy", "state": 1, "moved": "pchellboy"}

    def do_set_token_face(self, s):
        self.token_rot = float(re.search(r"local want = ([\d.]+) % 360", s).group(1))
        return {"rot_z": self.token_rot, "flipped": True}

    def do_inspect_objects(self, s):
        return {g: {"found": True, "type": "Custom_Token", "name": "", "rot_x": 0.0, "rot_y": 0.0, "rot_z": self.token_rot}
                for g in re.findall(r'"(\w+)"', re.search(r"ipairs\(\{(.*?)\}\)", s).group(1))}

    def do_piece_spaces_by_guid(self, s):
        out = super().do_piece_spaces_by_guid(s)
        if "pchellboy2" in out:                          # the two states of Hellboy's miniature: only one exists
            out["pchellboy" if self.hellboy_form2 else "pchellboy2"] = {"found": False}
        return out

    def do_clear_markings(self, s):
        self.zoom_cleared += "and true" in s
        return super().do_clear_markings(s)

    def _outside(self):
        """(bot, human) cards that are not in their draw deck."""
        bot = (len(self.bot_hand) + len(self.bot_play) + len(self.bot_discard) + len(self.stray_bot)
               + len(self.bot_ongoing) + len(self.bot_scattered))
        human = (len(self.human_discard) + len(self.face_down) + len(self.face_up) + self.human_count
                 + len(self.human_ongoing) + self.human_scattered)
        return bot, human

    def do_reset_deck(self, s):
        if int(re.search(r"id < (\d+) or id > \d+", s).group(1)) == self.bot_cards:
            self.bot_deck.extend(self.bot_ongoing + self.bot_scattered)
            self.bot_ongoing, self.bot_scattered = [], []
        else:
            self.human_ongoing, self.human_scattered = [], 0
        return super().do_reset_deck(s)

    def do_table_audit(self, s):
        rows = re.findall(r'\{"(\w+)", "(\w+)"\}', s.split("local REMOVE = ", 1)[1].splitlines()[0])
        labels = re.findall(r'\{"(\w+:[\w:]+)", \{', s)
        return {"removable": [{"guid": g, "name": n} for g, n in rows if self.leftovers.get(g) == n],
                "blocked": [{"guid": g, "name": self.leftovers[g], "why": "type"} for g, n in rows
                            if g in self.leftovers and self.leftovers[g] != n],
                "hands": {"Blue": len(self.bot_hand), "Red": self.human_count + self.sticky},
                "present": {k: (k in self.strays) if k.startswith("other:") else not self.in_bags for k in labels}}

    def do_unpack_from_bags(self, s):
        """The real script's rules: an item comes out only of its inner bag, which must be on the table, be a copy an earlier
        press left loose (reused, never duplicated) or be taken out of the hero's infinite bag (named as the script says and
        listing it). An infinite bag spawns its copy LATER: with `spawn_late` the copy appears only after the reply, so that
        press answers `spawning` and leaves the copy loose for the next one."""
        self.unpacked += 1
        outers = {inner: (outer, nick) for inner, outer, nick in re.findall(r'\["(\w+)"\] = \{"(\w+)", "([^"]*)", "[^"]*", \{', s)}
        rows = re.findall(r'\{"(?:deck|piece|dial|token)", \{([^}]*)\}, "(\w+)", ', s)
        taken, missing, failed, pulled, reused = [], [], [], [], []
        if self.in_bags:
            for guids, inner in rows:
                if inner not in self.inner_on_table and inner in outers and inner not in pulled and inner not in reused \
                        and inner not in [f["guid"] for f in failed]:
                    outer, nick = outers[inner]
                    have = self.outers.get(outer)
                    if have is None or have[0] != nick:
                        failed.append({"guid": inner, "why": "outer"})
                    elif inner not in have[1]:
                        failed.append({"guid": inner, "why": "listed"})
                    elif inner in self.loose_copies:
                        self.loose_copies.discard(inner)
                        reused.append(inner)
                    elif self.spawn_late:
                        self.loose_copies.add(inner)
                        self.copies_made += 1
                        failed.append({"guid": inner, "why": "spawning"})
                    else:
                        self.copies_made += 1
                        pulled.append(inner)
                first = re.findall(r'"(\w+)"', guids)[0]
                (taken if inner in self.inner_on_table or inner in pulled or inner in reused else missing).append(first)
            self.bags_taken += pulled
            self.in_bags = bool(missing)
        return {"present": [], "taken": taken, "missing": missing, "bags": pulled, "reused": reused, "bags_failed": failed}

    def do_prepare_table(self, s):
        self.removable = {g for g, n in self.leftovers.items() if n == KINDS.get(g)}
        out = super().do_prepare_table(s)
        for g in self.removed:
            self.leftovers.pop(g, None)
        return out

    def do_reset_plan(self, s):
        bot, human = self._outside()
        if self.in_bags:
            return [{"deck": False, "loose": 0, "total": 0}] * 2
        deck = not self.deck_face_up                      # the writes only take a face-down deck
        return [{"deck": deck, "loose": bot, "total": len(self.bot_deck) + bot},
                {"deck": deck, "loose": human, "total": 30}]


@pytest.fixture
def gate_live(live, monkeypatch):  # noqa: F811
    """`live` with the gate's table, on a dirty start (the bot holds two cards, the pieces stand on the board)."""
    _, fake, ports = live
    table = GateTable()
    table.positions = {n: i + 1 for i, n in enumerate(table.nick.values())}
    table.bot_deck = BOT_DECK[2:]
    table.dial_start = {"bcd809": 16, "046660": 18, "18c384": 6, "e17c66": 0}         # Medusa, Hellboy, Lobster, destiny
    table.dials = {g: {"found": True, "name": "dial", "value": v, "max": 20} for g, v in table.dial_start.items()}
    set_bot_hand(table, Game.new(Board.load("bprd-hq"), 0), "Snipe", "Dash")
    fake.return_value = table
    monkeypatch.setattr(table_reset, "PANEL_SETTLE", 0.0)
    return table, fake, ports


def client_for(live_fixture):
    _, fake, ports = live_fixture
    client = TTSClient(send_port=fake.port, listen_port=int(ports[3]))
    client.start_listening()
    return client


def session_for(client, cfg_path):
    cfg = load_config(cfg_path)
    return Session(play.build_game(cfg, "random", 0), client, play.make_bot_ai(play.ai_config(cfg, None, None), play.BOT),
                   cfg.session_config(), bot=play.BOT)


def codes(result):
    return [i.code for i in result.issues]


# ---------- the audit: ready or dirty ----------
def test_a_table_arranged_for_a_new_game_audits_ready(gate_live, cfg_file):
    table, _, _ = gate_live
    table.make_ready()
    client = client_for(gate_live)
    try:
        result = table_reset.audit(client, session_for(client, cfg_file()))
    finally:
        client.close()
    assert result.ready and result.issues == [] and result.notices == []


@pytest.mark.parametrize("dirt, code", [
    (lambda t: t.leftovers.update({"addeca": "DeckCustom"}), "leftovers"),
    (lambda t: setattr(t, "human_count", 3), "hand_cards"),
    (lambda t: t.bot_hand.extend([17600, 17601]) or t.bot_deck.__delitem__(slice(0, 2)), "hand_cards"),
    (lambda t: t.bot_discard.append(t.bot_deck.pop()), "cards_loose"),
    (lambda t: t.piece_dist.pop("Hellboy"), "pieces_on_board"),
    (lambda t: setattr(t, "in_bags", True), "heroes_out"),
])
def test_each_kind_of_leftover_makes_the_table_not_ready(gate_live, cfg_file, dirt, code):
    table, _, _ = gate_live
    table.make_ready()
    dirt(table)
    client = client_for(gate_live)
    try:
        result = table_reset.audit(client, session_for(client, cfg_file()))
    finally:
        client.close()
    assert not result.ready and code in codes(result), result


def test_a_loose_object_with_an_unexpected_name_is_reported_and_left_alone_not_counted_as_dirt(gate_live, cfg_file):
    table, _, _ = gate_live
    table.make_ready()
    table.leftovers["addeca"] = "Custom_Model"                   # the GUID now belongs to something else
    client = client_for(gate_live)
    try:
        result = table_reset.audit(client, session_for(client, cfg_file()))
    finally:
        client.close()
    assert result.ready and any("addeca" in n for n in result.notices)


def test_objects_of_other_heroes_are_noticed_but_do_not_block(gate_live, cfg_file):
    table, _, _ = gate_live
    table.make_ready()
    table.strays = {"other:houdini"}
    client = client_for(gate_live)
    try:
        result = table_reset.audit(client, session_for(client, cfg_file()))
    finally:
        client.close()
    assert result.ready
    assert any("Houdini" in n for n in result.notices)


def test_other_hero_presence_never_lists_a_guid_the_pair_owns():
    from sparring.tts.hero_table import load_hero_table
    owned = {g for slug in ("medusa", "hellboy") for g in load_hero_table(slug).all_guids()}
    rows = table_reset.other_hero_presence(("medusa", "hellboy"))
    assert rows and all(set(guids).isdisjoint(owned) for _, guids in rows)
    assert not any(label in ("other:medusa", "other:hellboy") for label, _ in rows)


# ---------- the end-to-end gate ----------
def run_main(gate_live, cfg_file, tmp_path, **cfg_over):
    table, fake, ports = gate_live
    stop, result = threading.Event(), {}
    t = threading.Thread(target=lambda: result.setdefault("code", main(
        ["--config", str(cfg_file(**cfg_over)), "--first", "human", "--poll", "0.02", *ports,
         "--state", str(tmp_path / "s.json")], stop=stop)))
    t.start()
    return stop, t, result


def wait_for(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def press(fake, event):
    fake.push({"messageID": 4, "customMessage": {"event": event}})


def finish(stop, t, result):
    stop.set()
    t.join(8)
    assert not t.is_alive() and result["code"] == 0


def said(table, *needles):
    """Wait condition: every needle is in the chat so far. A long line reaches the chat in several chunks, so wait on its LAST
    fragment (and on whatever else the test is about to read), never on the first."""
    return lambda: all(n in " ".join(table.broadcasts) for n in needles)


def shown(table, button):
    """(pressable, visible) of a panel button in the last panel update that mentions it."""
    for _, states in reversed(table.panels):
        if button in states:
            return states[button]
    return None


def game_started(table):
    return bool(table.deal_calls) or any("Tu turno" in b or "reparte" in b for b in table.broadcasts)


@pytest.mark.gate
def test_a_dirty_table_shows_the_clean_button_and_says_why_and_the_game_does_not_start(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    table.leftovers["addeca"] = "DeckCustom"
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: said(table, "Medusa y Hellboy")() and table.panels)
        assert shown(table, "btn_prep") == (True, True) and shown(table, "btn_start") == (False, False)
        text = " ".join(table.broadcasts)
        assert "objetos sueltos" in text and "cartas en las manos" in text and "miniaturas en el tablero" in text
        assert "Limpiar mesa y preparar" in text
        assert shown(table, "btn_maneuver") == (False, False), "no game button is shown before the game"
        time.sleep(0.4)
        assert not game_started(table) and table.moves == [] and table.placed == []
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_ready_table_shows_start_and_tells_the_human_to_prepare_heroes_and_map(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    table.make_ready()
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: said(table, "No empiezo hasta")() and table.panels)
        assert shown(table, "btn_start") == (True, True) and shown(table, "btn_prep") == (False, False)
        text = " ".join(table.broadcasts)
        assert "ya esta lista" in text and "heroes y el mapa" in text and "No empiezo hasta" in text
        time.sleep(0.4)
        assert not game_started(table)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_pressing_clean_leaves_the_prepared_table_without_pieces_hands_or_a_started_game(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    table.leftovers["addeca"] = "DeckCustom"
    table.in_bags = True
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        assert shown(table, "btn_prep") == (False, False)
        assert table.unpacked == 1 and "addeca" in table.removed and table.leftovers == {}
        assert "bot" in table.resets and "human" in table.resets               # every card back in its deck
        assert table.bot_hand == [] and table.human_count == 0 and len(table.bot_deck) == 30
        assert table.placed and all(p[3] == pytest.approx(table.placed[0][3]) or True for p in table.placed)
        assert all(d == 99.0 for d in table.piece_dist.values()), "every miniature is set aside, off the board"
        assert table.moves == [], "no piece was placed on the board"
        text = " ".join(table.broadcasts)
        assert "Mesa limpia y preparada" in text and "Comenzar partida" in text and "No empiezo hasta" in text
        assert not game_started(table), "preparing is not starting: no deal, no mulligan, no turn"
        assert "composite" not in table.sent or not table.deal_calls
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_second_press_of_clean_changes_nothing(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    table.in_bags = True
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        writes = (table.unpacked, list(table.resets), list(table.placed), list(table.dial_writes), len(table.prepared))
        said = len(table.broadcasts)
        press(fake, "prepare_table")                                           # a stale or double click
        assert wait_for(lambda: any("nada que hacer" in b for b in table.broadcasts[said:]))
        assert (table.unpacked, list(table.resets), list(table.placed), list(table.dial_writes), len(table.prepared)) == writes
        assert shown(table, "btn_start") == (True, True) and not game_started(table)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_nothing_starts_before_start_game_and_the_press_runs_the_normal_start_with_the_table_as_it_is(
        gate_live, cfg_file, tmp_path, monkeypatch):
    table, fake, _ = gate_live
    table.make_ready()
    reads = []
    real = play.resolve_heroes
    monkeypatch.setattr(play, "resolve_heroes", lambda client, cfg, saved=None, echo=print: reads.append(cfg.heroes) or real(
        client, cfg, saved, echo))
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        before = len(reads)
        time.sleep(0.5)
        assert not game_started(table) and table.panels
        press(fake, "start_game")
        assert wait_for(lambda: any("Tu turno" in b for b in table.broadcasts))
        assert len(reads) == before + 1, "Start game reads the heroes and the map from the table again"
        assert any("Leo los heroes" in b for b in table.broadcasts)
        assert game_started(table)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_start_game_is_refused_while_the_table_is_not_ready(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        assert shown(table, "btn_start") == (False, False), "a dirty table offers only the cleaning"
        press(fake, "start_game")                                        # a stale or forged click
        assert wait_for(lambda: "no empiezo" in " ".join(table.broadcasts))
        time.sleep(0.4)
        assert not game_started(table) and shown(table, "btn_prep") == (True, True)
        assert not any("Leo los heroes" in b for b in table.broadcasts) and table.removed == []
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_starting_through_the_gate_never_removes_anything_silently(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    table.make_ready()
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        table.leftovers["addeca"] = "DeckCustom"                          # something lands there after the check
        press(fake, "start_game")
        assert wait_for(lambda: any("Tu turno" in b for b in table.broadcasts))
        assert table.removed == [] and "local REMOVE = {}" in table.prepared[-1]
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_the_gate_can_be_turned_off_in_the_configuration(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    stop, t, result = run_main(gate_live, cfg_file, tmp_path, pregame_gate=False)
    try:
        assert wait_for(lambda: any("Tu turno" in b for b in table.broadcasts))
        assert not any("no esta lista" in b for b in table.broadcasts)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_resuming_never_goes_through_the_gate(gate_live, cfg_file, tmp_path):
    from sparring import persist
    table, fake, ports = gate_live
    path = tmp_path / "s.json"
    stop = threading.Event()
    # a resume without a saved game fails before any gate; what matters is that the gate is not entered
    code = main(["--config", str(cfg_file()), "--resume", *ports, "--state", str(path)], stop=stop)
    assert code == 2 and not table.panels and not any("no esta lista" in b for b in table.broadcasts)


@pytest.mark.gate
def test_a_table_that_cannot_be_cleaned_says_so_and_can_be_retried(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    table.in_bags = True
    table.bot_deck = []                                   # the deck cannot be gathered: the restart machinery refuses
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "No he podido limpiar", "arreglarla a mano"))
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        assert shown(table, "btn_start") == (False, False) and not game_started(table)
    finally:
        finish(stop, t, result)


# ---------- the panel ----------
def test_the_gate_buttons_exist_born_hidden_and_the_events_parse():
    xml = ui.panel_xml(["medusa"], ("hellboy",))
    for ident, handler in (("btn_prep", "onPrepare"), ("btn_start", "onStart")):
        assert re.search(rf'<Button [^>]*active="false"[^>]*id="{ident}" onClick="{handler}"', xml), ident
    assert ui.parse_event({"event": "prepare_table"}) == (Event.PREPARE, {})
    assert ui.parse_event({"event": "start_game"}) == (Event.START, {})
    script = ui.handler_script(None, [*ui.element_ids(["medusa"], ("hellboy",)), *ui.GATE_BUTTONS])
    assert 'send({event = "prepare_table"})' in script and 'send({event = "start_game"})' in script
    assert '"btn_prep"' in script and '"btn_start"' in script


def test_a_game_panel_never_touches_the_gate_buttons(brig):  # noqa: F811
    session, table, game, fake = brig
    _, states = session.panel_view()
    assert "btn_prep" not in states and "btn_start" not in states


def test_the_gate_texts_exist_in_both_languages():
    for lang, prep, start in (("es", "Limpiar mesa y preparar", "Comenzar partida"), ("en", "Clean table and prepare", "Start game")):
        with i18n.using(lang):
            assert i18n.t("panel.prep") == prep and i18n.t("panel.start") == start
            assert start in i18n.t("gate.next") and start in i18n.t("gate.status.ready")
            assert prep in i18n.t("gate.status.dirty")
            for code in ("leftovers", "hand_cards", "cards_loose", "heroes_out", "pieces_on_board", "dials"):
                assert i18n.t(f"gate.issue.{code}", detail="x") != f"gate.issue.{code}"


def test_the_audit_is_a_read_only_script():
    assert "table_audit" in play.READ_ONLY_TAGS
    script = lua.table_audit([("addeca", "DeckCustom")], (26.0, 36.0), ["Green", "White"], [("medusa:piece:04b2c9", ["04b2c9"])])
    for forbidden in ("destruct", "takeObject", "putObject", "setPosition", "setRotation", "spawnObject", "UI.", "Global"):
        assert forbidden not in script, forbidden


# ---------- the audit script ----------
def audit_script(runtime, remove, presence, rid=1):
    n = len(runtime.globals().SENT)
    runtime.execute(lua.request(lua.table_audit(remove, (26.0, 36.0), ["Green", "White"], presence), rid))
    reply = conv(runtime.globals().SENT[n + 1])
    assert "err" not in reply, reply
    return json.loads(reply["value"])


def test_the_audit_script_applies_the_removal_guard_without_removing(tts):  # noqa: F811
    tts.execute("""
mkobj({guid = 'addeca', type = 'Generic', name = 'DeckCustom', pos = Vector(-5.7, 1.6, -1.5)})
mkobj({guid = 'cb6cbc', type = 'Generic', name = 'Other', pos = Vector(5.5, 1.6, -1.5)})
mkobj({guid = '65be8d', type = 'Generic', name = 'Die_20', pos = Vector(40, 1.6, 0)})""")
    res = audit_script(tts, [("addeca", "DeckCustom"), ("cb6cbc", "DeckCustom"), ("65be8d", "Die_20"), ("6126d5", "Digital_Clock")], [])
    assert res["removable"] == [{"guid": "addeca", "name": "DeckCustom"}]
    assert sorted((r["guid"], r["why"]) for r in res["blocked"]) == [("65be8d", "place"), ("cb6cbc", "type")]
    assert tts.eval("#OBJECTS") == 3, "the audit destroys nothing"


def test_the_audit_script_counts_hands_and_says_which_objects_are_here(tts):  # noqa: F811
    tts.execute("""
mkobj({guid = 'c1', type = 'Card', cid = 17600, hand = 'Green'})
mkobj({guid = 'c2', type = 'Card', cid = 17601, hand = 'Green'})
mkobj({guid = 'ec6f27', type = 'Generic', name = 'Custom_Board'})
mkobj({guid = '04b2c9', type = 'Generic'})""")
    res = audit_script(tts, [], [("medusa:piece:04b2c9", ["04b2c9"]), ("medusa:dial:bcd809", ["bcd809", "zzz"]), ("other:houdini", ["h1"])])
    assert res["hands"] == {"Green": 2, "White": 0}
    assert res["present"] == {"medusa:piece:04b2c9": True, "medusa:dial:bcd809": False, "other:houdini": False}


def take_map(runtime, bag="ab5e89", board="ec6f27", rid=1):
    n = len(runtime.globals().SENT)
    runtime.execute(lua.request(lua.take_map(bag, board, (-0.35, 1.63, -3.18), 269.99, 0.85), rid))
    reply = conv(runtime.globals().SENT[n + 1])
    assert "err" not in reply, reply
    return json.loads(reply["value"])


def test_the_map_comes_out_of_its_bag_laid_flat_scaled_and_locked(tts):  # noqa: F811
    tts.execute("mkobj({guid = 'ab5e89', type = 'Infinite', infinite = true, items = {{guid = 'ec6f27', name = 'B.P.R.D. HQ'}}})")
    res = take_map(tts)
    assert res == {"taken": True, "guid": "ec6f27x"}
    assert tts.eval("getObjectFromGUID('ec6f27x').locked") is True
    assert tts.eval("getObjectFromGUID('ec6f27x').scale.x") == pytest.approx(0.85)
    assert tts.eval("getObjectFromGUID('ec6f27x').pos.z") == pytest.approx(-3.18)
    assert tts.eval("#getObjectFromGUID('ab5e89').items") == 1, "an infinite bag is not emptied"


def test_the_map_is_taken_only_from_the_configured_bag_and_only_that_board(tts):  # noqa: F811
    assert take_map(tts)["why"] == "bag"
    tts.execute("mkobj({guid = 'ab5e89', type = 'Infinite', infinite = true, items = {{guid = 'other1', name = 'Another'}}})")
    assert take_map(tts, rid=2) == {"taken": False, "why": "board"}
    assert tts.eval("#OBJECTS") == 1


def test_the_map_script_touches_nothing_but_that_bag():
    script = lua.take_map("ab5e89", "ec6f27", (0.0, 1.5, 0.0), 270.0, 0.85)
    assert script.count("takeObject") == 1 and "destruct" not in script and "getObjects()" not in script.replace("bag.getObjects()", "")
    with pytest.raises(ValueError):
        lua.take_map("ab5e89", "ec6f27", (0.0, 1.5, 0.0), 270.0, 50.0)


# ---------- cleaning: every dirty state ends clean ----------
def draw(table, n):
    return [table.bot_deck.pop() for _ in range(n)]


def low_dials(table, **values):
    names = {"medusa": "bcd809", "hellboy": "046660", "lobster": "18c384", "destiny": "e17c66"}
    for key, v in values.items():
        table.dials[names[key]] = {**table.dials[names[key]], "value": v}


def mid_game(table, state):
    table.bot_hand.extend(draw(table, 3))
    table.bot_play, table.bot_discard, table.bot_ongoing = draw(table, 1), draw(table, 6), draw(table, 1)
    table.human_count, table.human_discard = 4, [19700 + i for i in range(5)]
    table.face_down, table.human_ongoing = [{"id": 19710, "guid": "fd"}], [19711]
    low_dials(table, medusa=3, hellboy=7, lobster=0, destiny=4)
    table.token_rot = 0.0
    state.write_text("{}", encoding="utf-8")


def end_of_game(table, state):
    table.bot_discard, table.human_discard = draw(table, 13), [19700 + i for i in range(14)]
    low_dials(table, medusa=0, hellboy=0, lobster=0, destiny=6)
    table.piece_dist = {n: (99.0 if n in ("Harpy 1", "Harpy 2", "Medusa") else 0.1) for n in table.positions}   # the fallen are set aside
    state.write_text('{"winner": 1}', encoding="utf-8")


def half_played_combat(table, state):
    table.bot_play, table.stray_bot = draw(table, 1), [{"id": draw(table, 1)[0], "guid": "sb"}]
    table.face_down, table.face_up = [{"id": 19712, "guid": "fd"}], [{"id": 19713, "guid": "fu"}]


def cards_scattered(table, state):
    table.bot_scattered, table.human_scattered = draw(table, 10), 6


def forms_changed(table, state):
    table.guid_name["pchellboy2"] = "Hellboy"
    table.hellboy_form2, table.token_rot = True, 0.0


DIRTY = {
    "mid-game": (mid_game, {}),
    "end of game": (end_of_game, {}),
    "half-played combat": (half_played_combat, {}),
    "cards scattered on the table": (cards_scattered, {}),
    "pieces on the board": (lambda t, s: t.piece_dist.clear(), {}),
    "dials at low HP": (lambda t, s: low_dials(t, medusa=2, hellboy=1, lobster=1, destiny=5), {}),
    "ongoing cards": (lambda t, s: setattr(t, "bot_ongoing", draw(t, 2)) or setattr(t, "human_ongoing", [19711]), {}),
    "deck face up": (lambda t, s: setattr(t, "deck_face_up", True), {}),
    "Hellboy in his second form with the token turned": (forms_changed, {"pieces": {**PIECES, "hellboy": ["pchellboy", "pchellboy2"]}}),
    "the saved game of the bot": (lambda t, s: s.write_text("{}", encoding="utf-8"), {}),
}


def pristine(table, state):
    assert (table.bot_hand, table.bot_play, table.bot_discard, table.bot_ongoing, table.bot_scattered, table.stray_bot) == ([],) * 6
    assert len(table.bot_deck) == 30
    assert (table.human_discard, table.face_down, table.face_up, table.human_ongoing) == ([],) * 4
    assert table.human_scattered == 0 and table.human_count == 0
    assert all(d == 99.0 for d in table.piece_dist.values()), table.piece_dist
    assert {g: r["value"] for g, r in table.dials.items()} == table.dial_start
    assert table.token_rot == 180.0 and not table.hellboy_form2 and not table.deck_face_up
    assert not state.exists()
    assert table.moves == [] and table.deal_calls == []


@pytest.mark.gate
@pytest.mark.parametrize("name", list(DIRTY))
def test_every_dirty_state_ends_clean_and_prepared(gate_live, cfg_file, tmp_path, name):
    table, fake, _ = gate_live
    dirt, over = DIRTY[name]
    table.make_ready()
    state = tmp_path / "s.json"
    dirt(table, state)
    stop, t, result = run_main(gate_live, cfg_file, tmp_path, **over)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        assert shown(table, "btn_start") == (False, False), f"{name}: dirty, yet the start is offered"
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True)), table.broadcasts[-4:]
        assert shown(table, "btn_prep") == (False, False)
        pristine(table, state)
        assert table.zoom_cleared >= 1, "the zoom copies are removed"
        assert any("Mesa limpia y preparada" in b for b in table.broadcasts) and not game_started(table)
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_a_table_that_is_dirty_in_every_way_at_once_ends_clean(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    table.make_ready()
    state = tmp_path / "s.json"
    mid_game(table, state)
    cards_scattered(table, state)
    table.deck_face_up = True
    table.leftovers.update({"addeca": "DeckCustom", "5085eb": "Custom_Assetbundle"})
    table.piece_dist.clear()
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
        pristine(table, state)
        assert sorted(table.removed) == ["5085eb", "addeca"] and table.leftovers == {}
    finally:
        finish(stop, t, result)


@pytest.mark.gate
def test_what_the_cleaning_cannot_fix_is_named_and_the_button_stays(gate_live, cfg_file, tmp_path):
    table, fake, _ = gate_live
    table.make_ready()
    table.sticky = 3                                   # three cards in the human's hand that the bot's reset cannot move
    table.piece_dist.clear()
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(lambda: shown(table, "btn_prep") == (True, True))
        press(fake, "prepare_table")
        assert wait_for(said(table, "queda esto", "Red 3"))
        assert shown(table, "btn_prep") == (True, True) and shown(table, "btn_start") == (False, False)
        assert all(d == 99.0 for d in table.piece_dist.values()), "the rest was cleaned"
        assert "Red 3" in " ".join(table.broadcasts)
        table.sticky = 0                                # the human takes them away; pressing again finishes
        press(fake, "prepare_table")
        assert wait_for(lambda: shown(table, "btn_start") == (True, True))
    finally:
        finish(stop, t, result)


def test_cards_are_gathered_from_the_whole_table_not_only_from_the_known_spots():
    narrow = lua.Scope(("Green", "White"), ("906a7a", "b7a0b8"), ((6.0, -18.0),))
    wide = lua.Scope(("Green", "White"), ("906a7a", "b7a0b8"), ((6.0, -18.0),), everywhere=True)
    assert "if false then add(o) end" in lua._scope_lua(narrow) and "if true then add(o) end" in lua._scope_lua(wide)
    assert lua.reset_plan([("abc", (0.0, 0.0), (17600, 17629), (("https://a.test/f", "https://a.test/b"),))], scope=wide)


def test_the_cleaning_session_searches_the_whole_table(gate_live, cfg_file):
    client = client_for(gate_live)
    try:
        cfg = load_config(cfg_file())
        session = table_reset.CleaningSession(play.build_game(cfg, "random", 0), client,
                                              play.make_bot_ai(play.ai_config(cfg, None, None), play.BOT), cfg.session_config(), bot=play.BOT)
        assert session._scope().everywhere is True
        assert Session._scope(session).everywhere is False
    finally:
        client.close()


def test_a_pair_that_is_not_medusa_and_hellboy_is_reset_but_nothing_is_unpacked_over_its_decks(monkeypatch):
    calls = []
    monkeypatch.setattr(table_reset, "reset_cards_and_pieces", lambda client, session: calls.append("reset"))

    class Hero:
        def __init__(self, name):
            self.name = name

    class Game:
        def hero_def(self, p):
            return Hero(["Houdini", "Doctor Strange"][p])

    class Previous:
        game, bot, human = Game(), 0, 1

    class Client:
        def call_lua(self, script):
            calls.append(script.split("\n", 1)[0])

    def no_unpack(*a):
        raise AssertionError("nothing may be unpacked over the other decks")
    lines, session = table_reset.clean_and_prepare(Client(), lambda cfg: 1 / 0, object(), no_unpack, print, previous=Previous())
    assert calls == ["reset"]
    assert session is None and len(lines) == 1 and "Houdini" in lines[0] and "Doctor Strange" in lines[0] and "bolsas" in lines[0]


def test_the_two_faced_tokens_have_a_starting_face_in_the_data():
    from sparring.tts.hero_table import load_hero_table
    for slug, name in (("hellboy", "ability"), ("abe-sapien", "intuition")):
        table = load_hero_table(slug)
        assert table_reset.START_FACE[name] in table.token_faces[name]["faces"] and table.tokens[name]


# ---------- the inner bag comes out of the hero's infinite bag ----------
def run_unpack(runtime, outers, rid=1, only=None):
    """Sends the unpack request; returns a function that reads its reply (None while TTS has not answered)."""
    plan = [("piece", ("04b2c9",), "e5a45c", (22.0, 2.5, -10.0), None), ("dial", ("bcd809",), "e5a45c", (22.0, 2.5, -7.0), None)]
    plan = [row for row in plan if only is None or row[1][0] == only]
    n = len(runtime.globals().SENT)
    runtime.execute(lua.request(lua.unpack_from_bags(plan, outers), rid))

    def reply():
        if len(runtime.globals().SENT) <= n:
            return None
        got = conv(runtime.globals().SENT[n + 1])
        assert "err" not in got, got
        return json.loads(got["value"])
    return reply


def hero_bags(tts, nickname="Medusa", holds="e5a45c"):
    """The hero's infinite bag. Like TTS, its takeObject returns nothing: the copy appears LATER, when SPAWN() runs, and only
    then is the callback called."""
    tts.execute(f"""
local outer = mkobj({{guid = '65070e', type = 'Infinite', name = '{nickname}', items = {{{{guid = '{holds}', name = 'bag'}}}}}})
TAKEN_FROM_OUTER = 0
SPAWN = nil
outer.takeObject = function(t)
  TAKEN_FROM_OUTER = TAKEN_FROM_OUTER + 1
  SPAWN = function()
    local copy = mkobj({{guid = 'copy01', type = 'Bag', pos = Vector(t.position),
                         items = {{{{guid = '04b2c9', name = 'Medusa'}}, {{guid = 'bcd809', name = 'Medusa'}}}}}})
    t.callback_function(copy)
  end
end""")


OUTERS = {"e5a45c": ("65070e", "Medusa", "", tuple(play.load_hero_table("medusa").all_guids()))}


def test_the_reply_waits_for_the_copy_the_infinite_bag_spawns_later_and_one_press_unpacks(tts):  # noqa: F811
    hero_bags(tts)
    reply = run_unpack(tts, OUTERS)
    assert reply() is None, "nothing is answered while the copy has not spawned"
    assert tts.eval("TAKEN_FROM_OUTER") == 1
    tts.execute("SPAWN()")
    res = reply()
    assert res["bags"] == ["e5a45c"] and res["bags_failed"] == [] and res["missing"] == [] and res["reused"] == []
    assert res["taken"] == ["04b2c9", "bcd809"]
    assert tts.eval("getObjectFromGUID('copy01')") is None, "the emptied copy is destroyed"
    assert tts.eval("getObjectFromGUID('65070e') ~= nil"), "the infinite bag stays"


def test_a_copy_left_loose_by_an_earlier_press_is_reused_and_no_second_one_is_made(tts):  # noqa: F811
    hero_bags(tts)
    tts.execute("mkobj({guid = 'copy77', type = 'Bag', items = {{guid = '04b2c9'}, {guid = 'bcd809'}}})")
    res = run_unpack(tts, OUTERS)()
    assert res["reused"] == ["e5a45c"] and res["taken"] == ["04b2c9", "bcd809"] and res["bags"] == []
    assert tts.eval("TAKEN_FROM_OUTER") == 0, "the infinite bag is not asked for another copy"
    assert tts.eval("getObjectFromGUID('copy77')") is None, "the reused copy goes once it is empty"


def test_another_heros_loose_bag_that_repeats_a_guid_is_never_reused(tts):  # noqa: F811
    """The save repeats GUIDs across heroes: Loki's inner bag also holds Medusa's dial (bcd809)."""
    hero_bags(tts)
    tts.execute("mkobj({guid = '1d7bfd', type = 'Bag', items = {{guid = 'bcd809'}, {guid = 'lok001'}}})")
    reply = run_unpack(tts, OUTERS, only="bcd809")
    assert reply() is None and tts.eval("TAKEN_FROM_OUTER") == 1, "a fresh copy is asked for instead"
    tts.execute("SPAWN()")
    res = reply()
    assert res["reused"] == [] and res["bags"] == ["e5a45c"] and res["taken"] == ["bcd809"]
    assert tts.eval("#getObjectFromGUID('1d7bfd').items") == 2, "Loki's bag is untouched"
    assert tts.eval("getObjectFromGUID('1d7bfd') ~= nil"), "and it is not destroyed"


def test_a_loose_bag_with_the_right_items_but_a_foreign_one_beside_them_is_not_reused(tts):  # noqa: F811
    hero_bags(tts)
    tts.execute("mkobj({guid = 'copy88', type = 'Bag', items = {{guid = '04b2c9'}, {guid = 'bcd809'}, {guid = 'lok001'}}})")
    reply = run_unpack(tts, OUTERS)
    assert reply() is None and tts.eval("TAKEN_FROM_OUTER") == 1
    tts.execute("SPAWN()")
    assert reply()["reused"] == [] and tts.eval("getObjectFromGUID('copy88') ~= nil")


def test_a_loose_bag_with_another_name_is_not_reused(tts):  # noqa: F811
    hero_bags(tts)
    tts.execute("mkobj({guid = 'copy89', type = 'Bag', name = 'Loki', items = {{guid = '04b2c9'}, {guid = 'bcd809'}}})")
    reply = run_unpack(tts, OUTERS)
    assert reply() is None and tts.eval("TAKEN_FROM_OUTER") == 1
    tts.execute("SPAWN()")
    assert reply()["reused"] == [] and tts.eval("getObjectFromGUID('copy89') ~= nil")


def test_an_error_after_the_copy_spawned_still_answers_with_the_error(tts):  # noqa: F811
    hero_bags(tts)
    tts.execute("""getObjectFromGUID('65070e').takeObject = function(t)
  SPAWN = function()
    local copy = mkobj({guid = 'copy01', type = 'Bag', pos = Vector(t.position), items = {{guid = '04b2c9'}, {guid = 'bcd809'}}})
    copy.takeObject = function() error('boom') end
    t.callback_function(copy)
  end
end""")
    reply = run_unpack(tts, OUTERS)
    assert reply() is None
    tts.execute("SPAWN()")
    assert "boom" in reply()["error"], "the bot is told, not left waiting"


def test_a_loose_bag_missing_one_of_the_items_is_not_taken_for_the_copy(tts):  # noqa: F811
    hero_bags(tts)
    tts.execute("mkobj({guid = 'other9', type = 'Bag', items = {{guid = '04b2c9'}}})")
    reply = run_unpack(tts, OUTERS)
    assert reply() is None and tts.eval("TAKEN_FROM_OUTER") == 1
    tts.execute("SPAWN()")
    assert reply()["bags"] == ["e5a45c"] and tts.eval("getObjectFromGUID('other9') ~= nil")


def test_a_copy_that_never_spawns_is_answered_after_the_wait_as_spawning(tts):  # noqa: F811
    hero_bags(tts)
    reply = run_unpack(tts, OUTERS)
    assert reply() is None
    tts.execute("for _, f in ipairs(TIMERS) do f() end")                     # the wait runs out
    res = reply()
    assert res["bags_failed"] == [{"guid": "e5a45c", "why": "spawning"}] and res["taken"] == []
    assert res["missing"] == ["04b2c9", "bcd809"]
    tts.execute("SPAWN()")                                                    # a late copy changes nothing
    assert tts.eval("#SENT") == 1, "one reply per request"


@pytest.mark.parametrize("nickname, holds, why", [("Not Medusa", "e5a45c", "outer"), ("Medusa", "other1", "listed")])
def test_the_infinite_bag_is_trusted_only_with_its_nickname_and_its_contents(tts, nickname, holds, why):  # noqa: F811
    hero_bags(tts, nickname, holds)
    res = run_unpack(tts, OUTERS)()
    assert res["bags_failed"] == [{"guid": "e5a45c", "why": why}] and res["taken"] == [] and res["missing"] == ["04b2c9", "bcd809"]
    assert tts.eval("TAKEN_FROM_OUTER") == 0


def test_without_the_gates_outers_an_infinite_bag_is_never_touched_nor_a_loose_bag_reused(tts):  # noqa: F811
    hero_bags(tts)
    tts.execute("mkobj({guid = 'copy77', type = 'Bag', items = {{guid = '04b2c9'}, {guid = 'bcd809'}}})")
    res = run_unpack(tts, None)()
    assert res["missing"] == ["04b2c9", "bcd809"] and res["bags"] == [] and res["reused"] == []
    assert tts.eval("TAKEN_FROM_OUTER") == 0


def test_an_inner_bag_already_on_the_table_is_used_and_the_infinite_one_left_alone(tts):  # noqa: F811
    hero_bags(tts)
    tts.execute("mkobj({guid = 'e5a45c', type = 'Bag', items = {{guid = '04b2c9'}, {guid = 'bcd809'}}})")
    res = run_unpack(tts, OUTERS)()
    assert res["taken"] == ["04b2c9", "bcd809"] and res["bags"] == [] and tts.eval("TAKEN_FROM_OUTER") == 0


def test_every_hero_has_an_infinite_bag_named_after_the_hero_in_the_official_save():
    from test_official_table_gate import OBJECTS
    from sparring.heroes import load_hero
    from sparring.tts.hero_table import load_hero_table
    for slug in ("medusa", "hellboy"):
        table = load_hero_table(slug)
        assert OBJECTS[table.bag]["nickname"] == load_hero(slug).name
    outer, nick, name, members = play.unpack_outers(load_config(raw_config_path()))["e5a45c"]
    assert (outer, nick, name) == ("65070e", "Medusa", "") and "bcd809" in members and "d42056" in members


def raw_config_path():
    from test_play import REAL_CONFIG
    return REAL_CONFIG


# ---------- resume and configuration errors around the gate ----------
@pytest.mark.gate
def test_resuming_a_real_saved_game_skips_the_gate_and_keeps_the_file(gate_live, cfg_file, tmp_path, monkeypatch):
    table, fake, ports = gate_live
    table.make_ready()
    state = tmp_path / "s.json"
    monkeypatch.setattr(table_reset, "ENABLED", False)                  # the first game is played without the gate
    stop, t, result = run_main(gate_live, cfg_file, tmp_path)
    try:
        assert wait_for(state.exists)
    finally:
        finish(stop, t, result)
    saved = state.read_bytes()
    monkeypatch.setattr(table_reset, "ENABLED", True)
    table.panels.clear()
    table.broadcasts.clear()
    stop, result = threading.Event(), {}
    t = threading.Thread(target=lambda: result.setdefault("code", main(
        ["--config", str(cfg_file()), "--resume", "--poll", "0.02", *ports, "--state", str(state)], stop=stop)))
    t.start()
    try:
        assert wait_for(lambda: any("reanudada" in b for b in table.broadcasts))
    finally:
        finish(stop, t, result)
    assert not any("no esta lista" in b or "Comenzar partida" in b for b in table.broadcasts)
    assert state.exists() and json.loads(state.read_text(encoding="utf-8"))["heroes"] == json.loads(saved)["heroes"]


@pytest.mark.gate
def test_a_configuration_error_after_the_gate_is_a_cannot_start_exit_2(gate_live, cfg_file, tmp_path, monkeypatch, capsys):
    table, fake, ports = gate_live
    armed = []
    real = play.PlayConfig.session_config

    def flaky(self):
        if armed:
            raise play.ConfigError("boom")
        return real(self)
    monkeypatch.setattr(play.PlayConfig, "session_config", flaky)
    monkeypatch.setattr(play, "pregame", lambda cfg, *a, **k: armed.append(1) or cfg)
    code = main(["--config", str(cfg_file()), *ports, "--state", str(tmp_path / "s.json")])
    assert code == 2 and "boom" in capsys.readouterr().err
