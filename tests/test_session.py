import json
import os
import re

import pytest

from fake_tts import FakeTTS
from sparring.ai_medusa import Act, MedusaAI
from sparring.session import Pending, Session, SessionConfig
from sparring.state import Game
from sparring.tts.client import TTSClient
from sparring.tts.ui import Event
from conftest import place

NICK = {"medusa": "Medusa", "harpy1": "Harpy 1", "harpy2": "Harpy 2", "harpy3": "Harpy 3",
        "hellboy": "Hellboy", "lobster": "Lobster Johnson"}
PIECES = {fid: "pc" + fid for fid in NICK}
BATCH = bool(os.environ.get("SPARRING_BATCH"))     # SPARRING_BATCH=1 pasa toda la bateria por el modo rapido
GUID_NAME = {PIECES[fid]: NICK[fid] for fid in NICK}   # solo para Medusa vs Hellboy; la mesa lleva el suyo


class Table:
    """Mesa de TTS falsa con estado: manos, mazo, descartes, cartas boca abajo y miniaturas."""

    def __init__(self, nick: dict[str, str] | None = None, pieces: dict[str, str] | None = None, bot_cards: int = 17600):
        self.nick = nick or NICK                          # fid -> nombre (por defecto Medusa vs Hellboy)
        self.pieces = pieces or PIECES                    # fid -> GUID de pieza
        self.guid_name = GUID_NAME if pieces is None else {g: self.nick[f] for f, v in pieces.items()
                                                           for g in ([v] if isinstance(v, str) else v)}
        self.bot_cards = bot_cards                        # primer CardID del mazo del bot
        self.positions: dict[str, int] = {}
        self.bot_hand: list[int] = []
        self.bot_deck: list[int] = []
        self.bot_play: list[int] = []
        self.bot_discard: list[int] = []
        self.human_discard: list[int] = []
        self.human_count = 5
        self.face_down: list[dict] = []
        self.scripts: list[str] = []
        self.moves: list[tuple[str, int]] = []
        self.flips: list[str] = []
        self.fail_play = False
        self.fail_flip = False
        self.human_hand: list[int] = []     # solo lo lee la sesion para validar; vacio = no legible
        self.unflips: list[str] = []
        self.returned: list[str] = []
        self.lag = 0                         # lecturas de la mesa que tardan en ver los movimientos de cartas
        self._queued: list = []
        self._flying: set[int] = set()
        self._reads = 0
        self.deal_calls: list[int] = []
        self.human_deals: list[int] = []            # n de cada reparto al mazo del humano
        self.human_deal_fails = False
        self.human_deck_cards = 20
        self.discard_calls: list[list[int]] = []
        self.broadcasts: list[str] = []
        self.broadcast_colors: list[tuple[float, float, float]] = []
        self.dupes: set[str] = set()
        self.missing_guids: set[str] = set()
        self.piece_dist: dict[str, float] = {}      # nickname -> distancia a su casilla (lejos = fuera del tablero)
        self.missing_pieces: set[str] = set()       # GUID de pieza que no existe
        self.move_fails: set[str] = set()           # GUID de pieza que no se deja mover
        self.dials: dict[str, dict] = {}            # GUID de dial -> respuesta de read_health_dials
        self.hand_zones: dict[str, list[str]] = {}  # GUID de zona -> zonas de mano solapadas
        self.stray_near_deck: list[dict] = []       # objetos Card sueltos cerca del mazo (CardID, guid)
        self.discard_spots: dict[int, tuple[float, float, float]] = {}   # CardID -> sitio pedido al descartar
        self.markings: list[str] = []
        self.dial_writes: list[tuple[str, int]] = []
        self.piece_names: dict[str, str] = {}
        self.placed: list[tuple[str, float, float, float]] = []
        self.shuffles = 0
        self.returns = 0
        self.dial_ignores_writes = False
        self.stray_bot: list[dict] = []             # cartas del bot boca abajo en su punto de carta o de mazo
        self.bot_ongoing: list[int] = []            # CardIDs on each ONGOING spot (E2)
        self.human_ongoing: list[int] = []
        self.ongoing_spots: dict[str, tuple[float, float]] = {}   # "bot"/"human" -> (x, z) the classic reads match
        self.sent: list[str] = []                   # una entrada por MENSAJE a TTS: la etiqueta del script
        self.panels: list[tuple[str, dict]] = []    # (estado, {id: (pulsable, visible)}) de cada set_panel
        self.wseq = 0                               # ultima escritura que el compuesto anoto en el panel (wseq)
        self.composite_waits = True                 # el compuesto espera dentro de TTS a que todo se asiente

    def __call__(self, msg):
        s = msg["script"]
        tag = re.match(r"-- sparring:(\w+)", s).group(1)
        self.sent.append(tag)
        if tag == "composite":
            return json.dumps(self.do_composite(s))
        self.scripts.append(s)
        out = getattr(self, "do_" + tag)(s)
        return out if isinstance(out, dict) and "__error__" in out else json.dumps(out)

    def do_composite(self, s):
        """Ejecuta cada operacion con su do_<etiqueta> (que se anota en `scripts`) y devuelve la mesa resultante."""
        results = []
        self.msglog = getattr(self, "msglog", [])
        self.msglog.append(re.findall(r"^-- sparring:(\w+)$", s, re.M)[1:])
        for text, tag in re.findall(r"(-- sparring:(\w+)\n.*?)end\) or \{\}\n", s.split("local results = {}", 1)[1], re.S):
            self.scripts.append(text)
            out = getattr(self, "do_" + tag)(text)
            results.append({"__err": out["__error__"]} if isinstance(out, dict) and "__error__" in out else out)
        res = {"ops": results}
        if "local function sparringSnapshot" in s:
            self.wseq = int(re.search(r"local SEQ = (\d+)", s).group(1))
            if self.composite_waits and not self.lag:
                for fn in self._queued:
                    fn()
                self._queued.clear()
            res["state"] = self.snapshot_state()
        return res

    def snapshot_state(self):
        self._tick()
        pieces = {}
        for name, g in ((self.nick[f], self.pieces[f] if isinstance(self.pieces[f], str) else self.pieces[f][0]) for f in self.nick):
            pieces[g] = (self.do_piece_spaces_by_guid(f'local wanted = {{"{g}"}}')[g])
        return {"bot_hand": [{"id": i, "guid": f"g{i}"} for i in self.bot_hand], "human_count": self.human_count,
                "bot_discard": [{"id": i, "guid": f"g{i}"} for i in self.bot_discard],
                "human_discard": [{"id": i, "guid": f"g{i}"} for i in self.human_discard],
                "face_bot": self.stray_bot + [{"id": i, "guid": f"g{i}"} for i in self.bot_play],
                "face_human": self.face_down, "pieces": pieces, "human_deck_qty": getattr(self, "human_deck_qty", -1),
                "ongoing_bot": [{"id": i, "guid": f"g{i}"} for i in self.bot_ongoing],
                "ongoing_human": [{"id": i, "guid": f"g{i}"} for i in self.human_ongoing],
                "dials": {g: v for g, v in self.dials.items()}, "seq": self.wseq}

    def do_snapshot(self, s):
        return self.snapshot_state()

    def do_set_panel(self, s):
        status = re.search(r'panel\.UI\.setValue\("status", "(.*?)"\)', s).group(1)
        states = {i: (a == "true", b == "true") for i, a, b in
                  re.findall(r'\["(\w+)"\]=\{(true|false), (true|false)\}', s)}
        self.panels.append((status, states))
        return {"panel": True}

    def do_piece_spaces_by_guid(self, s):
        guids = re.findall(r'"(\w+)"', re.search(r"local wanted = \{(.*?)\}", s).group(1))
        out = {}
        for g in guids:
            name = self.guid_name[g]
            if g in self.missing_pieces or name not in self.positions:
                out[g] = {"found": False}
            else:
                out[g] = {"found": True, "space": self.positions[name], "dist": self.piece_dist.get(name, 0.1),
                          "type": "Custom_Token", "name": name}
        return out

    def do_move_piece(self, s):
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s.split("local target")[1]).group(1)
        space = int(re.search(r"spaceWorld\((\d+)\)", s).group(1))
        if guid in self.move_fails or guid in self.missing_pieces:
            return {"moved": False}
        self.moves.append((self.guid_name[guid], space))
        self.positions[self.guid_name[guid]] = space
        self.piece_dist.pop(self.guid_name[guid], None)
        return {"moved": guid}

    def do_read_health_dials(self, s):
        guids = re.findall(r'"(\w+)"', re.search(r"ipairs\(\{(.*?)\}\)", s).group(1))
        return {g: self.dials.get(g, {"found": False}) for g in guids}

    def do_return_hand_to_deck(self, s):
        self.returns += 1
        n = len(self.bot_hand)
        self.bot_deck.extend(self.bot_hand)
        self.bot_hand.clear()
        return {"returned": n, "deck": True}

    def do_shuffle_deck(self, s):
        self.shuffles += 1
        return {"shuffled": True, "quantity": len(self.bot_deck)}

    def do_reset_deck(self, s):
        """Todas las cartas de un bando vuelven a su mazo (mano, descarte, boca abajo y sueltas)."""
        self.resets = getattr(self, "resets", [])
        if int(re.search(r"id < (\d+) or id > \d+", s).group(1)) == self.bot_cards:
            self.bot_deck.extend(self.bot_hand + self.bot_play + self.bot_discard + [r["id"] for r in self.stray_bot])
            self.bot_hand, self.bot_play, self.bot_discard, self.stray_bot = [], [], [], []
            self.resets.append("bot")
            return {"deck": True, "quantity": len(self.bot_deck)}
        self.human_discard, self.face_down, self.human_hand, self.human_count = [], [], [], 0
        self.resets.append("human")
        return {"deck": True, "quantity": 30}

    def do_reset_plan(self, s):
        """Lo que reset_deck juntaria, sin mover nada: una entrada por bando, en el orden del script."""
        out = []
        for lo in re.findall(r"id < (\d+) or id > \d+", s):
            if int(lo) == self.bot_cards:
                total = len(self.bot_deck + self.bot_hand + self.bot_play + self.bot_discard) + len(self.stray_bot)
            else:
                total = 30
            out.append({"deck": True, "loose": 0, "total": total})
        return out

    def do_hand_identities(self, s):
        return {"pairs": [{"face": "https://img.test/face", "back": "https://img.test/back"}]}

    def do_deck_identities(self, s):
        n = len(re.findall(r'\{"\w+", (?:nil|\{)', s))
        return [{"found": True, "pairs": [{"face": "https://img.test/face", "back": "https://img.test/back"}]}
                for _ in range(n)]

    def do_place_piece(self, s):
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        x, y, z = (float(v) for v in re.search(r"Vector\(([^)]*)\)", s).group(1).split(","))
        if guid in self.move_fails or guid in self.missing_pieces:
            return {"moved": False}
        self.placed.append((self.guid_name[guid], x, y, z))
        self.piece_dist[self.guid_name[guid]] = 99.0          # apartada: lejos de cualquier casilla
        return {"moved": guid}

    def do_name_pieces(self, s):
        rows = re.findall(r'\["(\w+)"\]="([^"]*)"', s)
        self.piece_names.update(dict(rows))
        return {"named": [g for g, _ in rows]}

    def do_set_health_dials(self, s):
        rows = re.findall(r'\["(\w+)"\]=(\d+)', s)
        for g, v in rows:
            if g in self.dials and not self.dial_ignores_writes:
                self.dials[g] = {**self.dials[g], "value": int(v)}
            self.dial_writes.append((g, int(v)))
        return {g: {"found": g in self.dials, "written": True, "value": int(v)} for g, v in rows}

    def do_zone_overlaps(self, s):
        guids = re.findall(r'"(\w+)"', re.search(r"ipairs\(\{(.*?)\}\)", s).group(1))
        return {g: {"found": True, "hands": self.hand_zones.get(g, [])} for g in guids}

    def do_inspect_guids(self, s):
        guids = re.findall(r'"(\w+)"', re.search(r"ipairs\(\{(.*?)\}\)", s).group(1))
        return {g: ({"found": True, "type": "Deck", "name": "", "quantity": 20, "x": 1.0, "y": 2.0, "z": 3.0}
                    if g not in self.missing_guids else {"found": False}) for g in guids}

    def do_inspect_objects(self, s):
        guids = re.findall(r'"(\w+)"', re.search(r"ipairs\(\{(.*?)\}\)", s).group(1))
        return {g: {"found": True, "type": "Custom_Token", "name": "", "rot_x": 0.0, "rot_y": 0.0, "rot_z": 180.0}
                for g in guids}

    def do_hold(self, s):
        self.holds = getattr(self, "holds", []) + [float(re.search(r"math.max\(holdFor or 0, ([\d.]+)\)", s).group(1))]
        return {"held": self.holds[-1]}

    def do_broadcast(self, s):
        self.broadcasts.append(re.search(r'broadcastToAll\("(.*?)"', s).group(1))
        self.broadcast_colors.append(tuple(float(v) for v in re.search(r"\{([\d.]+), ([\d.]+), ([\d.]+)\}\)", s).groups()))
        return {"shown": True}

    def do_create_panel(self, s):
        return {"panel": "pan1"}

    def do_draw_markings(self, s):
        self.markings.append(s)
        return {"drawn": 4, "labels": 0, "panel": True}

    def do_clear_markings(self, s):
        return {"removed": 0}

    def _tick(self):
        self._reads += 1
        if self._reads > self.lag:
            for fn in self._queued:
                fn()
            self._queued.clear()

    def _later(self, fn):
        if self.lag:
            self._queued.append(fn)
        else:
            fn()

    def do_read_hand(self, s):
        self._tick()
        if 'Player["Red"]' in s:
            return [{"id": i, "guid": f"h{i}"} for i in self.human_hand]
        return [{"id": i, "guid": f"g{i}"} for i in self.bot_hand]

    def do_count_hand(self, s):
        return {"count": self.human_count}

    def do_read_discard(self, s):
        self._tick()
        ids = self.bot_discard if '"BOTZ"' in s else self.human_discard
        return [{"id": i, "guid": f"g{i}"} for i in ids]

    def do_deal_cards(self, s):
        """Mazo realista: con 2 o mas cartas es un Deck (su GUID existe); con 1 queda una Card suelta que
        solo se halla por posicion (rama `if d == nil`); vacio no reparte nada."""
        n = int(re.search(r"math\.min\((\d+)", s).group(1))
        if "d.deal(k, Red)" in s or 'd.deal(k, "Red")' in s:    # el mazo del humano: solo cuenta cartas
            self.human_deals.append(n)
            k = 0 if self.human_deal_fails else min(n, self.human_deck_cards)
            self.human_deck_cards -= k
            self.human_count += k
            self.human_deck_qty = self.human_deck_cards
            return {"dealt": k}
        self.deal_calls.append(n)
        if len(self.bot_deck) >= 2:
            k = min(n, len(self.bot_deck))
        elif len(self.bot_deck) == 1 and "if d == nil then" in s and n >= 1:
            k = 1
        else:
            k = 0
        drawn = [self.bot_deck.pop(0) for _ in range(k)]
        self._later(lambda: self.bot_hand.extend(drawn))
        return {"dealt": k}

    def do_discard_cards(self, s):
        """Descarte realista: con 2 o mas cartas el descarte es un Deck; una Card suelta solo se halla si
        es la unica. Si el script sabe mirar dentro de los Deck (`o.type == "Deck"`), las halla ahi."""
        ids = [int(x) for x in re.findall(r"\[(\d+)\]=\{", s)]
        for i, xyz in re.findall(r"\[(\d+)\]=\{([^}]*)\}", s):
            self.discard_spots[int(i)] = tuple(float(v) for v in xyz.split(","))
        self.discard_calls.append(ids)
        sees_decks = 'o.type == "Deck"' in s
        moved = []
        for i in ids:
            for zone in (self.bot_hand, self.bot_play, self.bot_ongoing):
                if i in zone:
                    zone.remove(i)
                    self._flying.add(i)
                    self._later(lambda i=i: (self._flying.discard(i), self.bot_discard.append(i)))
                    moved.append(i)
                    break
            else:
                loose = i in self._flying or (i in self.bot_discard and len(self.bot_discard) == 1)
                in_deck = i in self.bot_discard and len(self.bot_discard) >= 2
                if loose or (in_deck and sees_decks):
                    moved.append(i)
                elif sees_decks and i in self.bot_deck and len(self.bot_deck) >= 2:   # takeObject out of the draw deck
                    self.bot_deck.remove(i)
                    self._later(lambda i=i: self.bot_discard.append(i))
                    moved.append(i)
        return {"moved": moved}

    def do_place_card_face_up(self, s):
        i = int(re.search(r"CardID == (\d+)", s).group(1))
        if i not in self.bot_hand:
            return {"placed": False}
        self.bot_hand.remove(i)
        self.bot_ongoing.append(i)
        return {"placed": f"g{i}"}

    def do_read_cards_at(self, s):
        x = float(re.search(r"p\.x - (-?[\d.]+)\)", s).group(1))
        z = float(re.search(r"p\.z - (-?[\d.]+)\)", s).group(1))
        for side, (sx, sz) in self.ongoing_spots.items():
            if abs(sx - x) < 0.01 and abs(sz - z) < 0.01:
                ids = self.bot_ongoing if side == "bot" else self.human_ongoing
                return [{"id": i, "guid": f"g{i}"} for i in ids]
        return []

    def do_play_card_face_down(self, s):
        i = int(re.search(r"CardID == (\d+)", s).group(1))
        if self.fail_play or i not in self.bot_hand:
            return {"played": False}
        self.bot_hand.remove(i)
        self.bot_play.append(i)
        return {"played": f"g{i}"}

    def do_read_face_down_cards(self, s):
        z = float(re.search(r"p\.z - (-?[\d.]+)\)", s).group(1))
        if z > 0:                                   # punto de carta del bot (z 5.0) o del mazo (z 3.0)
            return self.stray_bot + [{"id": i, "guid": f"g{i}"} for i in self.bot_play]
        return self.face_down

    def do_flip_card(self, s):
        if self.fail_flip:
            return {"__error__": "no se pudo girar"}
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        (self.unflips if ", 180.0)" in s else self.flips).append(guid)
        return {"flipped": guid}

    def do_return_card_to_hand(self, s):
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        i = int(guid[1:])
        stray = [r for r in self.stray_bot if r["guid"] == guid]
        if stray:
            self.stray_bot.remove(stray[0])
            self._later(lambda: self.bot_hand.append(i))
            return {"returned": guid}
        if i in self.bot_play or i in self._flying:
            if i in self.bot_play:
                self.bot_play.remove(i)
                self._flying.add(i)
                self._later(lambda: (self._flying.discard(i), self.bot_hand.append(i)))
            self.returned.append(guid)
            return {"returned": guid}
        if i in self.bot_discard:                   # a card lying face up on the discard (Wildfire's burning card)
            self.bot_discard.remove(i)
            self._later(lambda: self.bot_hand.append(i))
            self.returned.append(guid)
            return {"returned": guid}
        return {"returned": False}

    def do_show_hand_row(self, s):
        """La mano del bot pasa a una fila boca arriba en la mesa (fuera de su mano)."""
        self.look_row = getattr(self, "look_row", [])
        self.look_spots = {int(i): tuple(float(v) for v in xyz.split(","))
                           for i, xyz in re.findall(r"\[(\d+)\]=\{([^}]*)\}", s)}
        shown = []
        for i in self.look_spots:
            if i in self.bot_hand and i not in getattr(self, "look_refuse", ()):
                self.bot_hand.remove(i)
                self.look_row.append(i)
                shown.append({"id": i, "guid": f"g{i}"})
        return {"shown": shown}

    def do_resolve_hand_row(self, s):
        """Cierra la fila: la elegida (por GUID, o la unica boca abajo) al descarte y el resto a la mano."""
        guids = re.findall(r'"(\w+)"', re.search(r"for _, g in ipairs\(\{(.*?)\}\) do", s).group(1))
        row = [int(g[1:]) for g in guids if int(g[1:]) in self.look_row]
        down = [i for i in row if i in getattr(self, "look_down", set())]
        pick = re.search(r'local pick = (nil|"(\w+)")', s).group(2)
        chosen = int(pick[1:]) if pick else None
        if "if true then" in s:
            if len(down) != 1:
                return {"discarded": False, "returned": [], "found": len(row), "down": len(down)}
            chosen = down[0]
        elif pick and chosen not in row:
            return {"discarded": False, "returned": [], "found": len(row), "down": len(down)}
        returned = [i for i in row if i != chosen]
        for i in row:
            self.look_row.remove(i)
        if chosen is not None:
            self._later(lambda: self.bot_discard.append(chosen))
        self._later(lambda: self.bot_hand.extend(returned))
        self.resolve_args = {"chosen": chosen, "returned": returned,
                             "spot": tuple(float(v) for v in re.search(
                                 r"o\.setPosition\(Vector\(([^)]*)\)\)\n    discarded", s).group(1).split(","))}
        return {"discarded": chosen if chosen is not None else False, "returned": returned, "found": len(row),
                "down": len(down)}

    def do_set_look_row(self, s):
        self.look_vars = getattr(self, "look_vars", [])
        self.look_vars.append(re.search(r'setVar\("lookRow", "(.*?)"\)', s).group(1))
        return {"set": 1}

    def count(self, tag):
        return sum(s.startswith(f"-- sparring:{tag}") for s in self.scripts)


def ids(game, player, *titles):
    out, used = [], set()
    for t in titles:
        c = next(c for c in game.players[player].full_set if c.title == t and c.card_id not in used)
        used.add(c.card_id)
        out.append(c.card_id)
    return out


def card(game, player, title, nth=0):
    return [c for c in game.players[player].full_set if c.title == title][nth]


@pytest.fixture
def rig(bprd):
    table = Table()
    fake = FakeTTS(return_value=table)
    client = TTSClient(send_port=fake.port, listen_port=0)
    fake.reply_port = client.start_listening().port
    game = Game.new(bprd, seed=3, controllers={})
    cfg = SessionConfig("Blue", "Red", NICK, (0.0, 1.0, 5.0), (0.0, -5.0), (5.0, 1.0, 5.0), "BOTZ", "DECK1", "HUMZ",
                        (0.0, 3.0), PIECES, settle_tries=4, settle_wait=0.0, batch=BATCH)
    session = Session(game, client, MedusaAI(0), cfg)
    game.turn, game.turn_no = 1, 2
    game.begin_turn()
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    table.positions = {NICK[f]: g.pos for f, g in game.fighters.items()}
    set_bot_hand(table, game, "Snipe", "Dash")
    session.read_bot_hand()
    yield session, table, game
    client.close()
    fake.close()


def set_bot_hand(table, game, *titles):
    table.bot_hand = ids(game, 0, *titles)
    table.bot_deck = [c.card_id for c in game.players[0].full_set if c.card_id not in table.bot_hand]


def human_plays(table, game, title, nth=0):
    c = card(game, 1, title, nth)
    table.face_down = [{"id": c.card_id, "guid": f"h{c.card_id}"}]
    return c


# ---------- flujo basico ----------
def test_maneuver_spends_action_draws_and_end_action_syncs_positions(rig):
    session, table, game = rig
    session.handle(Event.MANEUVER)
    assert game.actions_left == 1
    table.positions["Hellboy"] = 2
    session.handle(Event.END_ACTION)
    assert game.fighters["hellboy"].pos == 2 and game.turn == 1


def test_scheme_spends_action(rig):
    session, _, game = rig
    session.handle(Event.SCHEME)
    assert game.actions_left == 1


def test_value_event_stores_number(rig):
    session, _, game = rig
    session.handle(Event.VALUE, {"value": 3})
    assert session.pending_value == 0, "sin combate pendiente el valor no se registra (no se arrastra al siguiente)"
    session.pending = Pending("human_attacks", game.fighters["hellboy"], game.fighters["medusa"], None)
    session.handle(Event.VALUE, {"value": 3})
    assert session.pending_value == 3
    session.handle(Event.VALUE, {"value": None})
    assert session.pending_value == 0


# ---------- S1: el humano elige atacante; nits de objetivo ----------
def test_attack_needs_attacker_first_and_unknown_target_is_a_message(rig):
    session, _, game = rig
    msgs = session.handle(Event.ATTACK, {"target": "medusa"})
    assert session.pending is None and any("quien ataca" in m for m in msgs)
    session.handle(Event.ATTACKER, {"attacker": "att_hellboy"})
    msgs = session.handle(Event.ATTACK, {"target": "nadie"})
    assert session.pending is None and any("Objetivo no valido" in m for m in msgs)
    msgs = session.handle(Event.ATTACKER, {"attacker": "medusa"})
    assert any("no valido" in m for m in msgs) and session.chosen_attacker == "hellboy"


def test_chosen_attacker_is_the_one_who_attacks(rig):
    session, table, game = rig
    place(game, hellboy=40 if 40 in game.board.spaces else 31, lobster=0 + 1)
    table.positions.update({"Hellboy": game.fighters["hellboy"].pos, "Lobster Johnson": game.fighters["lobster"].pos})
    session.handle(Event.ATTACKER, {"attacker": "lobster"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    assert session.pending.attacker.fid == "lobster"


def test_wrong_fighter_restriction_keeps_pending_and_explains(rig):
    session, table, game = rig
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Second Shot")  # carta solo de Lobster Johnson
    msgs = session.handle(Event.REVEAL)
    assert any("Lobster Johnson" in m and "ilegal" in m for m in msgs)
    assert session.pending is not None and game.actions_left == 2 and table.flips == []


# ---------- B1: reveal valido o nada ----------
def start_human_attack(session, table, game, title="Service Pistol"):
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None
    return human_plays(table, game, title)


def test_human_attack_reveal_resolves_with_value_and_waits_for_end_action(rig):
    session, table, game = rig
    pistol = start_human_attack(session, table, game)
    session.handle(Event.VALUE, {"value": 2})
    chosen = []
    real = session.ai.choose_defense
    session.ai.choose_defense = lambda g, a, t: chosen.append(real(g, a, t)) or chosen[-1]
    msgs = session.handle(Event.REVEAL)
    bot_card = chosen[0]
    assert any("Combate" in m for m in msgs)
    assert session.pending is None and session.pending_value == 0
    assert game.fighters["medusa"].hp == 16 - max(0, 7 - (bot_card.value if bot_card else 0))
    assert pistol in game.players[1].discard
    # S3: no avanza solo; el humano resuelve efectos y pulsa Fin de accion
    assert game.turn == 1 and game.actions_left == 1
    assert any("Fin de accion" in m for m in msgs)
    msgs = session.handle(Event.END_ACTION)
    assert any("Te quedan 1" in m for m in msgs) and (BATCH or table.count("piece_spaces") >= 2)


def test_reveal_without_pending(rig):
    session, _, _ = rig
    assert any("No hay combate" in m for m in session.handle(Event.REVEAL))


@pytest.mark.parametrize("branch", ["no_card", "defense_only_card", "two_cards", "flip_error"])
def test_human_attack_reveal_failures_keep_a_working_state(rig, branch):
    session, table, game = rig
    start_human_attack(session, table, game)
    good = table.face_down
    flips_before = len(table.flips)
    if branch == "no_card":
        table.face_down = []
    elif branch == "defense_only_card":
        human_plays(table, game, "On Earth As It Is In Hell")
    elif branch == "two_cards":
        table.face_down = good + [{"id": card(game, 1, "Excalibur").card_id, "guid": "hx"}]
    elif branch == "flip_error":
        table.fail_flip = True
    if BATCH and branch == "flip_error":
        pytest.skip("en modo rapido el giro se encola ya aceptado el combate (ver test_batch.py)")
    msgs = session.handle(Event.REVEAL)
    assert session.pending is not None, msgs
    assert game.actions_left == 2 and len(table.flips) == flips_before
    assert game.fighters["medusa"].hp == 16
    table.fail_flip = False
    # siempre queda un boton que funciona: cambiar la carta y revelar de nuevo
    human_plays(table, game, "Service Pistol")
    session.handle(Event.REVEAL)
    assert session.pending is None and game.actions_left == 1


def test_bot_attacks_human_reveals_illegal_defense_session_not_frozen(rig):
    session, table, game = rig
    set_bot_hand(table, game, "Gaze of Stone")
    session.read_bot_hand()
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert session.pending is not None and session.pending.kind == "bot_attacks"
    bot_actions = game.actions_left
    human_plays(table, game, "Excalibur")  # ataque, no defensa
    msgs = session.handle(Event.REVEAL)
    assert any("Carta ilegal" in m and "Excalibur" in m for m in msgs)
    assert session.pending is not None and game.actions_left == bot_actions
    assert table.flips == [] and 17600 + 3 not in table.bot_discard
    table.face_down = []  # el humano retira la carta: sin defensa
    session.handle(Event.REVEAL)
    assert session.pending is None and game.actions_left == bot_actions - 1


def test_bot_card_among_face_down_cards_is_ignored_by_ownership(rig):
    session, table, game = rig
    pistol = start_human_attack(session, table, game)
    bot_id = session.pending.bot_card.card_id if session.pending.bot_card else card(game, 0, "Snipe").card_id
    table.face_down = [{"id": bot_id, "guid": "gbot"}] + table.face_down
    session.handle(Event.REVEAL)
    assert pistol in game.players[1].discard


def test_game_attack_is_transactional(rig):
    _, table, game = rig
    from sparring.state import RuleError
    place(game, medusa=0, hellboy=1)
    med, hb = game.fighters["medusa"], game.fighters["hellboy"]
    game.turn = 0
    game.begin_turn()
    gaze = card(game, 0, "Gaze of Stone")
    game.players[0].hand[:] = [gaze]
    bad_def = card(game, 1, "Excalibur")
    game.players[1].hand[:] = [bad_def]
    with pytest.raises(RuleError):
        game.attack(med, hb, gaze, def_card=bad_def)
    assert game.actions_left == 2 and gaze in game.players[0].hand and bad_def in game.players[1].hand


# ---------- B2: la mesa manda ----------
def test_bot_hand_comes_from_table_and_deck_is_the_unseen_pile(rig):
    session, table, game = rig
    st = game.players[0]
    assert sorted(c.card_id for c in st.hand) == sorted(table.bot_hand)
    assert len(st.deck) == 28 and not set(c.card_id for c in st.deck) & set(table.bot_hand)


def test_bot_maneuver_draws_physically_and_hand_matches_table(rig, monkeypatch):
    session, table, game = rig
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    game.actions_left = 0
    n = len(table.bot_hand)
    session.handle(Event.END_ACTION)
    assert table.count("deal_cards") == 2  # una maniobra por accion
    assert len(table.bot_hand) == n + 2
    assert sorted(c.card_id for c in game.players[0].hand) == sorted(table.bot_hand)


def test_bot_physical_discards_are_confirmed(rig, monkeypatch):
    session, table, game = rig
    boost = card(game, 0, "Dash")
    set_bot_hand(table, game, "Snipe", "Dash")
    session.read_bot_hand()
    acts = iter([Act("maneuver", moves={"medusa": 0}, boost=boost)])
    monkeypatch.setattr(session.ai, "plan", lambda g: next(acts, None) or Act("maneuver", moves={"medusa": 0}))
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert boost.card_id in table.bot_discard
    assert {c.card_id for c in game.players[0].discard} == set(table.bot_discard)


def test_failed_play_aborts_the_action_without_resolving(rig, monkeypatch):
    session, table, game = rig
    dash = card(game, 0, "Dash")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: dash)
    table.fail_play = True
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Service Pistol")
    msgs = session.handle(Event.REVEAL)
    assert any("Error de mesa" in m for m in msgs)
    assert session.pending is not None and not session.pending.defended
    assert game.actions_left == 2 and not game.players[0].discard
    table.fail_play = False
    session.handle(Event.REVEAL)
    assert session.pending is None, "tras el error el boton vuelve a funcionar"


def test_bot_play_failure_in_its_own_attack_aborts(rig, monkeypatch):
    session, table, game = rig
    gaze = card(game, 0, "Gaze of Stone")
    set_bot_hand(table, game, "Gaze of Stone")
    session.read_bot_hand()
    table.fail_play = True
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("attack", fid="medusa", target="hellboy", card=gaze))
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert any("Error de mesa" in m for m in msgs)
    assert session.pending is None and game.fighters["hellboy"].hp == 17  # solo la habilidad de inicio de turno
    assert not game.players[0].discard


# ---------- S2: movimientos del motor proyectados ----------
def bot_positions(game):
    return {NICK[f.fid]: f.pos for f in game.own(0)}


def run_bot_attack_with(session, table, game, monkeypatch, titles, fid, target, card_title):
    set_bot_hand(table, game, *titles)
    session.read_bot_hand()
    c = card(game, 0, card_title)
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("attack", fid=fid, target=target, card=c))
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert session.pending is not None


def test_dash_move_while_defending_is_projected(rig, monkeypatch):
    session, table, game = rig
    dash = card(game, 0, "Dash")
    set_bot_hand(table, game, "Dash")
    session.read_bot_hand()
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: dash)
    before = bot_positions(game)
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Service Pistol")
    table.moves.clear()
    session.ai.choose_move = lambda g, f, steps, through=False: min(g.legal_moves(f, steps))
    session.handle(Event.REVEAL)
    after = bot_positions(game)
    diff = {n: p for n, p in after.items() if before[n] != p}
    assert diff, "Dash debia mover a Medusa"
    assert dict(table.moves) == diff and len(table.moves) == len(diff)


def test_hounds_moves_every_harpy_and_all_are_projected(rig, monkeypatch):
    session, table, game = rig
    place(game, harpy1=2, hellboy=1, medusa=0)
    table.positions.update({"Harpy 1": 2})
    session.sync_positions()
    run_bot_attack_with(session, table, game, monkeypatch, ["The Hounds of Mighty Zeus"], "harpy1", "hellboy",
                        "The Hounds of Mighty Zeus")
    before = bot_positions(game)
    session.ai.choose_move = lambda g, f, steps, through=False: min(g.legal_moves(f, steps))
    table.face_down = []
    table.moves.clear()
    session.handle(Event.REVEAL)
    after = bot_positions(game)
    diff = {n: p for n, p in after.items() if before[n] != p}
    living = {NICK[f.fid] for f in game.own(0) if f.name == "Harpy"}
    assert living == {"Harpy 1", "Harpy 2", "Harpy 3"}
    assert living <= set(diff), "Hounds mueve a cada Harpia viva y todas se proyectan"
    assert dict(table.moves) == diff and len(table.moves) == len(diff)
    assert all(table.positions[NICK[f.fid]] == f.pos for f in game.own(0))


# ---------- S3: la resolucion del humano manda ----------
def test_bot_combat_waits_for_end_action_before_continuing(rig, monkeypatch):
    session, table, game = rig
    run_bot_attack_with(session, table, game, monkeypatch, ["Gaze of Stone", "Snipe"], "medusa", "hellboy",
                        "Gaze of Stone")
    table.face_down = []
    session.handle(Event.REVEAL)
    assert game.turn == 0 and session.pending is None
    reads = table.count("piece_spaces")
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    session.handle(Event.END_ACTION)
    assert (BATCH or table.count("piece_spaces") > reads), "start/continue siempre sincroniza antes"
    assert game.turn == 1


def test_start_bot_turn_syncs_human_first(rig, monkeypatch):
    session, table, game = rig
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    game.actions_left = 0
    table.positions["Hellboy"] = 2
    session.handle(Event.END_ACTION)
    assert game.fighters["hellboy"].pos == 2


# ---------- S4: descartes del humano ----------
def test_forced_discard_is_announced_and_learned_from_table(rig, monkeypatch):
    session, table, game = rig
    claws = card(game, 0, "Clutching Claws")
    set_bot_hand(table, game, "Clutching Claws")
    session.read_bot_hand()
    place(game, harpy1=2)
    table.positions["Harpy 1"] = 2
    run_bot_attack_with(session, table, game, monkeypatch, ["Clutching Claws"], "harpy1", "hellboy",
                        "Clutching Claws")
    game.players[1].hand[:] = [card(game, 1, "Glimpse Of Hell", 0), card(game, 1, "Glimpse Of Hell", 1)]
    table.human_count = 2
    table.face_down = []
    msgs = session.handle(Event.REVEAL)
    assert any("Descarta 1 carta" in m for m in msgs)
    assert len(game.players[1].hand) == 2, "el motor no inventa que carta se descarta"
    assert game.players[1].discard == []
    msgs = session.handle(Event.END_ACTION)  # aun no ha descartado
    assert any("Aun falta" in m for m in msgs) and session.pending_discard is not None
    assert session.handle(Event.MANEUVER)  # bloqueado mientras debe descartar
    chosen = card(game, 1, "Glimpse Of Hell", 1)
    table.human_discard = [chosen.card_id]
    table.human_count = 1
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    session.handle(Event.END_ACTION)
    assert chosen in game.players[1].discard and session.pending_discard is None
    assert claws.card_id in table.bot_discard


def test_sync_makes_engine_discard_equal_to_table_including_removals(rig):
    session, table, game = rig
    destiny = [c for c in game.players[1].full_set if c.destiny][:6]
    table.human_discard = [c.card_id for c in destiny]
    session.sync_human()
    assert game.form(1) == "ANUNG UN RAMA" and {c.card_id for c in game.players[1].discard} == set(table.human_discard)
    table.human_discard = table.human_discard[:5]  # Pancakes! devuelve una al mazo
    session.sync_human()
    assert game.form(1) == "ANUNG UN RAMA", "una lectura sin la carta no baja el contador"
    session._epoch += 1                             # otro boton: sigue faltando, ahora si se cuenta
    session.sync_human()
    assert game.form(1) == "OCCULT DETECTIVE" and len(game.players[1].discard) == 5
    assert destiny[5] in game.players[1].deck


def test_hand_limit_makes_the_human_discard_before_bot_turn(rig, monkeypatch):
    session, table, game = rig
    table.human_count = 9
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert any("Descarta 2 carta" in m for m in msgs) and game.turn == 1
    table.human_count = 7
    session.handle(Event.END_ACTION)
    assert game.turn == 1 and game.actions_left == 2 and session.pending is None  # el bot ya jugo y paso


def test_human_discard_zone_and_deck_spot_are_required():
    with pytest.raises(TypeError):
        SessionConfig("Blue", "Red", NICK, (0, 1, 5), (0, -5), (5, 1, 5), "BOTZ", "DECK1", "HUMZ")
    with pytest.raises(TypeError):
        SessionConfig("Blue", "Red", NICK, (0, 1, 5), (0, -5), (5, 1, 5), "BOTZ", "DECK1")


# ---------- nits: inicio de turno sin inventar la mano ----------
def test_human_start_of_turn_effects_are_announced_not_applied(rig, monkeypatch):
    session, table, game = rig
    game.players[1].discard = [c for c in game.players[1].full_set if c.destiny][:6]
    table.human_discard = [c.card_id for c in game.players[1].discard]
    session.sync_human()
    hand_before = list(game.players[1].hand)
    discard_before = list(game.players[1].discard)
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    game.actions_left = 0
    game.turn = 1
    msgs = session.handle(Event.END_ACTION)
    assert any("ANUNG" in m and "descarta 1" in m for m in msgs)
    assert game.players[1].discard == discard_before
    assert len(game.players[1].hand) == len(hand_before)


# ---------- revision 3: atasco por ataque pendiente imposible ----------
def lobster_rig(table, game):
    """Lobster al lado de Medusa y el humano solo con cartas que Lobster no puede jugar para atacar."""
    place(game, hellboy=40 if 40 in game.board.spaces else 31, lobster=1, medusa=0)
    table.positions.update({"Hellboy": game.fighters["hellboy"].pos, "Lobster Johnson": 1})
    table.human_hand = ids(game, 1, "On Earth As It Is In Hell", "Pancakes!")


def test_an_attacker_without_a_legal_card_is_refused_at_reveal_not_at_attack(rig):
    session, table, game = rig
    lobster_rig(table, game)
    placed = table.count("play_card_face_down")
    session.handle(Event.ATTACKER, {"attacker": "lobster"})
    session.handle(Event.ATTACK, {"target": "medusa"})      # Atacar ya no lee la mano del humano
    assert session.pending is not None and table.count("play_card_face_down") == placed
    human_plays(table, game, "Pancakes!")                   # un plan: no ataca
    msgs = session.handle(Event.REVEAL)
    assert any("Carta ilegal" in m for m in msgs)
    assert session.pending is not None and table.count("play_card_face_down") == placed, "sin defensa del bot"
    session.handle(Event.CANCEL)                            # salida limpia
    assert session.pending is None and session.chosen_attacker is None


def test_unreadable_human_hand_does_not_block_the_attack(rig):
    session, table, game = rig
    table.human_hand = []  # la mano no se lee (conteo 5): se confia en el humano
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None


def test_cancel_returns_the_bot_defense_card_and_unfreezes_the_game(rig, monkeypatch):
    session, table, game = rig
    dash = card(game, 0, "Dash")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: dash)
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None and table.bot_play == []
    session._bot_defends(session.pending)    # la defensa ya puesta (p. ej. respuesta tardia recuperada)
    assert dash.card_id in table.bot_play
    human_plays(table, game, "Second Shot")  # ilegal para Hellboy: Revelar falla siempre
    session.handle(Event.REVEAL)
    assert session.pending is not None
    assert any("Revela primero" in m for m in session.handle(Event.END_ACTION))
    session.pending_value = 3
    msgs = session.handle(Event.CANCEL)
    assert session.pending is None and session.chosen_attacker is None and session.pending_value == 0
    assert dash.card_id in table.bot_hand and table.bot_play == [] and table.returned == [f"g{dash.card_id}"]
    assert dash in game.players[0].hand and game.actions_left == 2 and not game.players[0].discard
    assert game.fighters["medusa"].hp == 16 and any("cancel" in m.lower() for m in msgs)
    session.handle(Event.MANEUVER)  # los demas botones vuelven a funcionar
    assert game.actions_left == 1


def test_cancel_without_bot_card_and_without_pending(rig, monkeypatch):
    session, table, game = rig
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: None)
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    session.handle(Event.CANCEL)
    assert session.pending is None and table.returned == [] and game.actions_left == 2
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})  # solo hay atacante elegido
    session.handle(Event.CANCEL)
    assert session.chosen_attacker is None


def test_cancel_cannot_undo_a_bot_attack(rig):
    session, table, game = rig
    set_bot_hand(table, game, "Gaze of Stone")
    session.read_bot_hand()
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert session.pending.kind == "bot_attacks"
    msgs = session.handle(Event.CANCEL)
    assert session.pending is not None and table.returned == [] and msgs


def test_cancel_return_failure_keeps_pending_for_retry(rig, monkeypatch):
    session, table, game = rig
    dash = card(game, 0, "Dash")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: dash)
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    session._bot_defends(session.pending)
    table.lag = 99  # la carta no llega a la mano
    msgs = session.handle(Event.CANCEL)
    assert any("Error de mesa" in m for m in msgs) and session.pending is not None
    table.lag = 0
    session.handle(Event.CANCEL)
    assert session.pending is None and dash.card_id in table.bot_hand


# ---------- 5 y 6: transaccionalidad del Revelar y atacante elegido ----------
@pytest.mark.skipif(BATCH, reason="en modo rapido las cartas se giran ya aceptado el combate (ver test_batch.py)")
def test_failed_game_attack_unflips_cards_and_restores_the_human_hand_guess(rig, monkeypatch):
    from sparring.state import RuleError
    session, table, game = rig
    start_human_attack(session, table, game)
    st = game.players[1]
    hand, deck = list(st.hand), list(st.deck)

    def boom(*a, **k):
        raise RuleError("fallo simulado")
    monkeypatch.setattr(game, "begin_attack", boom)
    msgs = session.handle(Event.REVEAL)
    assert any("fallo simulado" in m for m in msgs)
    assert session.pending is not None and len(table.flips) >= 1
    assert sorted(table.unflips) == sorted(table.flips)
    assert st.hand == hand and st.deck == deck


@pytest.mark.skipif(BATCH, reason="en modo rapido las cartas se giran ya aceptado el combate (ver test_batch.py)")
def test_flip_failure_midway_unflips_the_cards_already_turned(rig):
    session, table, game = rig
    start_human_attack(session, table, game)
    real, calls = table.do_flip_card, []

    def flaky(s):
        calls.append(s)
        return {"__error__": "x"} if len(calls) == 2 and ", 180.0)" not in s else real(s)
    table.do_flip_card = flaky
    msgs = session.handle(Event.REVEAL)
    assert session.pending is not None and msgs
    assert len(table.flips) == 1 and table.unflips == table.flips
    assert game.actions_left == 2


def test_chosen_attacker_is_cleared_after_a_failed_attack_and_at_end_of_turn(rig):
    session, table, game = rig
    far = max(game.board.spaces, key=lambda s: game.board.distance(1, s))
    place(game, hellboy=1, medusa=far)
    table.positions["Hellboy"], table.positions["Medusa"] = 1, far
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    msgs = session.handle(Event.ATTACK, {"target": "medusa"})
    assert any("no alcanza" in m for m in msgs) and session.chosen_attacker is None
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert session.chosen_attacker is None


# ---------- 3: la mesa tarda en reflejar los movimientos de cartas ----------
def _frenzy_less_boost_plan(session, game, monkeypatch):
    boost = card(game, 0, "Dash")
    acts = iter([Act("maneuver", moves={"medusa": 0}, boost=boost)])
    monkeypatch.setattr(session.ai, "plan", lambda g: next(acts, None) or Act("maneuver", moves={"medusa": 0}))
    return boost


def test_reconcile_polls_until_the_table_catches_up(rig, monkeypatch):
    session, table, game = rig
    boost = _frenzy_less_boost_plan(session, game, monkeypatch)
    table.lag = 2
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert not any("Error de mesa" in m for m in msgs)
    assert boost.card_id in table.bot_discard
    assert {c.card_id for c in game.players[0].discard} == set(table.bot_discard)
    assert sorted(c.card_id for c in game.players[0].hand) == sorted(table.bot_hand)


def test_reconcile_gives_up_after_bounded_retries_without_marking_the_discard_done(rig, monkeypatch):
    session, table, game = rig
    boost = _frenzy_less_boost_plan(session, game, monkeypatch)
    table.lag = 50
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert any("Error de mesa" in m for m in msgs)
    assert boost.card_id not in session.bot_discarded, "no se da por descartada una carta sin confirmar"
    table.lag, table._reads = 0, 99
    session._reconcile_bot()  # al reintentar, con la mesa al dia, queda confirmado
    assert boost.card_id in session.bot_discarded and boost.card_id in table.bot_discard


def test_short_deal_keeps_the_undealt_count(rig):
    session, table, game = rig
    game.draw(0, 3)
    table.bot_deck = table.bot_deck[:1]
    from sparring.session import SessionError
    with pytest.raises(SessionError):
        session._reconcile_bot()
    assert game.drawn[0] == 2


# ---------- 2: arpia resucitada por Winged Frenzy ----------
def test_revived_harpy_is_placed_on_the_table_and_verified(rig):
    session, table, game = rig
    frenzy = card(game, 0, "Winged Frenzy")
    set_bot_hand(table, game, "Winged Frenzy")
    session.read_bot_hand()
    h3 = game.fighters["harpy3"]
    h3.alive, h3.pos, h3.hp = False, None, 0
    table.positions.pop("Harpy 3")
    session.ai.choose_placement = lambda g, f, options: 2 if 2 in options else options[0]
    session.ai.choose_move = lambda g, f, steps, through=False: None
    before = session._snapshot_bot()
    game.play_scheme(0, game.hero(0), frenzy)
    assert h3.alive and h3.pos is not None
    table.moves.clear()
    session.messages = []
    session._project(before)
    assert table.moves == [("Harpy 3", h3.pos)]
    assert any("Harpy 3" in m for m in session.messages) and table.positions["Harpy 3"] == h3.pos


def test_revived_harpy_not_found_on_table_asks_the_human_to_place_it(rig):
    session, table, game = rig
    h3 = game.fighters["harpy3"]
    before = {"harpy3": (None, False)}
    h3.alive, h3.pos = True, 2
    table.do_move_piece = lambda s: {"moved": False}
    session.messages = []
    session._project({**session._snapshot_bot(), **before})
    assert any("Coloca" in m and "Harpy 3" in m for m in session.messages)


def test_bot_dying_of_exhaustion_is_announced_and_turn_stops(rig, monkeypatch):
    session, table, game = rig
    table.bot_discard = list(table.bot_deck)
    table.bot_deck = []
    st = game.players[0]
    st.discard = [c for c in st.full_set if c.card_id in table.bot_discard]
    session.read_bot_hand()
    assert st.deck == []
    game.fighters["medusa"].hp = 2
    calls = []

    def plan(g):
        calls.append(1)
        return Act("maneuver", moves={"medusa": 3})
    monkeypatch.setattr(session.ai, "plan", plan)
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    text = "\n".join(msgs)
    assert game.winner == 1 and not game.fighters["medusa"].alive
    assert len(calls) == 1, "tras morir no hay segunda accion"
    assert "Accion ilegal" not in text
    assert "Medusa cae" in text
    assert "Fin de partida: gana el jugador 1" in text
    assert "Mazo vacio" in text
