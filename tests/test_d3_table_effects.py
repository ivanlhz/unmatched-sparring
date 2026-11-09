"""D3: the bot's card effects act on the real table during a live session (`sparring/session_bot_effects.py`).

FakeTTS sessions with the box heroes on the bot's side, in batch mode (one combined script per step):
  * `look_hand` reads the human's real hand from the table exactly when the op runs (one extra message), never
    otherwise (tripwire: no read of the human seat across a whole bot turn and a combat without a look card);
  * bot Hellboy's form change swaps the miniature state, flips the ability token 1644a3 and pings both;
  * the human's miniatures a bot effect moves (Right Hand Of Doom, Foul Journey) travel in the step's script;
  * bot Abe's Intuition tokens: a copy of 5a17e9 per active point, removed when spent;
  * a named discard of the human's card (Confront lost, Remove A Painful Memory) is owed through `pending_discard`
    and protected from the table sync until the human moves it; a random one (Fleeting Moments) is the human's pick;
  * the bot's own deck: hand to the bottom (Pyrotechnics), discard shuffled back (Rekindle), a scheme recovered to
    the hand (Ward And Prepare), the card Every Possible Angle names for the top of the human's deck;
  * a combat paused at the human's choice (E1) resumes from a save and still projects (the snapshot is in the save).
"""
from __future__ import annotations

import json
import re

import pytest

from sparring import play
from sparring.ai_medusa import Act, MedusaAI
from sparring.effects import narrate
from sparring.session import Session
from sparring.spaces import describe
from sparring.state import ANUNG, DETECTIVE, Game
from sparring.tts.client import TTSClient
from sparring.tts.ui import Event
from fake_tts import FakeTTS
from test_batch import click
from test_choice_infra import visible_choices
from test_multihero_bridge import config_for
from test_session import Table, human_plays

HUMAN_SEAT_READ = 'Player["Red"]'


class FxTable(Table):
    """The fake table plus the F1 pieces D3 writes: multi-state miniatures, tokens, token copies and deck moves."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.states: list[tuple[str, int]] = []
        self.flipped: list[str] = []
        self.pings: list[list[list[str]]] = []
        self.point_pings: list[int] = []
        self.tokens: list[str] = []
        self.hand_moves: list[tuple[str, list[int]]] = []
        self.deck_moves: list[tuple[str, list[int]]] = []
        self.human_deck: list[int] = []
        self.intuition = {"total": 2, "active": 0}          # the human Abe's physical tokens
        self.intuition_turns: list[tuple[bool, int]] = []
        self.token_moves: list[tuple[str, tuple[float, float, float], tuple[float, float, float]]] = []   # (GUID, position, rotation) of each move_token
        self.missing_tokens: set[str] = set()               # GUIDs of tokens the player took off the table

    def snapshot_state(self):
        snap = super().snapshot_state()
        for v in self.pieces.values():                      # every state of a miniature, not only the first
            for g in (v if isinstance(v, list) else [v]):
                snap["pieces"][g] = self.do_piece_spaces_by_guid(f'local wanted = {{"{g}"}}')[g]
        return snap

    def do_set_state(self, s):
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        n = int(re.search(r"setState\((\d+)\)", s).group(1))
        if guid in self.missing_pieces:
            return {"changed": False}
        fid = next(f for f, v in self.pieces.items() if isinstance(v, list) and guid in v)
        new = self.pieces[fid][n - 1]
        self.missing_pieces.add(guid)
        self.missing_pieces.discard(new)
        self.states.append((guid, n))
        return {"guid": new, "state": n, "moved": new}

    def do_set_intuition_tokens(self, s):
        target = int(re.search(r"local TARGET = (\d+)", s).group(1))
        box = self.intuition
        before = box["active"]
        if box["total"] == 0:
            return {"total": 0, "active": 0, "after": 0, "flipped": 0, "guids": []}
        box["active"] = min(target, box["total"])
        done = abs(box["active"] - before)
        if done:
            self.intuition_turns.append((box["active"] > before, done))
        return {"total": box["total"], "active": before, "after": box["active"], "flipped": done,
                "guids": [f"i{k}" for k in range(done)]}

    def do_move_token(self, s):
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        if guid in self.missing_tokens:
            return {"found": False, "moved": False}
        vec = [tuple(float(v) for v in m) for m in re.findall(r"Vector\(([-\d.]+), ([-\d.]+), ([-\d.]+)\)", s)]
        self.token_moves.append((guid, vec[0], vec[1]))
        return {"found": True, "moved": True}

    def do_flip_token(self, s):
        self.flipped.append(re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1))
        return {"rot_z": 0, "flipped": True}

    def do_ping_objects(self, s):
        groups = re.search(r"local groups = \{(.*)\}\nlocal function", s, re.S).group(1)
        self.pings.append([re.findall(r'"(\w+)"', g) for g in re.findall(r"\{([^{}]*)\}", groups)])
        return {"queued": len(self.pings[-1])}

    def do_ping_points(self, s):
        n = len(re.findall(r"Vector\(", re.search(r"local points = \{(.*)\}\nfor i", s, re.S).group(1)))
        self.point_pings.append(n)
        return {"queued": n}

    def do_take_token_copy(self, s):
        guid = f"tok{len(self.tokens) + 1}"
        self.tokens.append(guid)
        return {"taken": guid, "moved": guid, "via": "takeObject"}

    def do_remove_token(self, s):
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        if guid not in self.tokens:
            return {"removed": False}
        self.tokens.remove(guid)
        return {"removed": True}

    def do_hand_to_deck(self, s):
        ids = [int(i) for i in re.search(r"local order = \{(.*?)\}", s).group(1).split(",") if i.strip()]
        kind = "bottom" if "(r.z + 180)" in s else "shuffle" if "deck.shuffle()" in s else "top"
        placed = [i for i in ids if i in self.bot_hand]
        for i in placed:
            self.bot_hand.remove(i)
            self.bot_deck.append(i)
        self.hand_moves.append((kind, placed))
        return {"placed": placed, "deck": "DECK1", "quantity": len(self.bot_deck)}

    human_deck_guid = None                        # set by `build` from the session config
    stuck_in_pile: set = frozenset()              # CardIDs the table cannot take out of the pile (a shuffle moves the rest)

    def _human_side(self, s):
        """True when the script targets the HUMAN's deck: those cards move from the human pile to `human_deck`."""
        return self.human_deck_guid is not None and f'findDeck("{self.human_deck_guid}")' in s

    def _deck_insert(self, s, kind):
        m = re.search(r"CardID == (\d+)", s)
        i = int(m.group(1)) if m else int(re.search(r'local card = \(?.*?getObjectFromGUID\("g(\d+)"\)', s, re.S).group(1))
        deck = self.human_deck if self._human_side(s) else self.bot_deck
        # a loose card is found wherever it lies: the discard pile or, for the bot, its combat spot (DARK PACT at a paused combat)
        pile = next((p for p in ([self.human_discard] if self._human_side(s) else [self.bot_discard, self.bot_play]) if i in p), None)
        if pile is None:
            return {"placed": False}
        pile.remove(i)
        deck.append(i)
        self.deck_moves.append((kind, [i]))
        return {"placed": True, "deck": "DECK1", "quantity": len(deck)}

    def do_card_to_deck_bottom(self, s):
        return self._deck_insert(s, "bottom")

    def do_card_to_deck_top(self, s):
        return self._deck_insert(s, "top")

    def do_shuffle_into_deck(self, s):
        """As the real script: a loose card of ours (the discard pile, the bot's combat spot) goes in. TTS has NO deck object
        when the last card was drawn: then only a script that lays the first card down as the new deck (its `home`) can work."""
        wanted = re.findall(r'"([gh])(\d+)"', re.search(r"local wanted = \{(.*?)\}", s).group(1))
        human = self._human_side(s)
        pile, deck = ((self.human_discard, self.human_deck) if human else (self.bot_discard, self.bot_deck))
        if not deck and "-- an empty draw deck is no object in TTS" not in s:
            return {"added": 0, "deck": False, "moved": []}
        on_spot = {r["id"] for r in self.face_down}          # the human's card at the combat spot (Relentless): GUID h<id>
        added = [(k, int(g)) for k, g in wanted if int(g) not in self.stuck_in_pile
                 and (int(g) in pile or (k == "h" and int(g) in on_spot and human) or (k == "g" and not human and int(g) in self.bot_play))]
        for k, i in added:
            if k == "h":
                self.face_down = [r for r in self.face_down if r["id"] != i]
            elif i in self.bot_play:
                self.bot_play.remove(i)
            else:
                pile.remove(i)
            deck.append(i)
        self.deck_moves.append(("shuffle", [i for _, i in added]))
        return {"added": len(added), "moved": [f"{k}{i}" for k, i in added], "deck": "DECK1" if deck else False, "quantity": len(deck)}

    def do_return_card_to_hand(self, s):
        i = int(re.search(r'getObjectFromGUID\("g(\d+)"\)', s).group(1))
        if i in self.bot_discard:
            self.bot_discard.remove(i)
            self.bot_hand.append(i)
            return {"returned": f"g{i}"}
        return super().do_return_card_to_hand(s)


def reassigned_guid(table, guid: str) -> str:
    """What TTS does with two objects that share a GUID (the tournament save gives 4fdf31 to Abe Sapien's and Donatello's
    miniatures): the first one out keeps it, the next gets a new random one. `table.guid_name` is filled in config order,
    so a GUID already there belongs to the first."""
    return guid if guid not in table.guid_name else guid + "x"


def build(tmp_path, bot, human, hand, table_cls=FxTable, **over):
    """A batch session with `bot` vs `human` (seats Blue / Red), the bot holding the cards titled in `hand`."""
    cfg = config_for(tmp_path, bot, human, **over)
    scfg = cfg.session_config()
    table = table_cls(cfg.nicknames, dict(scfg.pieces), bot_cards=scfg.bot_card_ids[0])
    table.guid_name = {}
    for fid, v in scfg.pieces.items():
        table.pieces[fid] = [reassigned_guid(table, g) for g in play.piece_guids(v)]
        table.pieces[fid] = table.pieces[fid][0] if isinstance(v, str) else table.pieces[fid]
        for g in play.piece_guids(table.pieces[fid]):
            table.guid_name[g] = cfg.nicknames[fid]
    fake = FakeTTS(return_value=table)
    client = TTSClient(send_port=fake.port, listen_port=0)
    fake.reply_port = client.start_listening().port
    table.human_deck_guid = scfg.human_deck_guid
    scfg.settle_wait, scfg.settle_tries = 0.0, 4
    game = Game.new(cfg.board, seed=3, controllers={}, bot_player=0, heroes=cfg.heroes)
    session = Session(game, client, MedusaAI(0), scfg)
    table.session = session
    game.turn, game.turn_no = 1, 2
    game.begin_turn()
    bot_fids, human_fids = [f.fid for f in game.own(0)], [f.fid for f in game.own(1)]
    spaces = sorted(game.board.spaces)
    game.fighters[bot_fids[0]].pos, game.fighters[human_fids[0]].pos = spaces[0], spaces[1]
    for i, fid in enumerate(bot_fids[1:]):
        game.fighters[fid].pos = spaces[20 + i]
    for i, fid in enumerate(human_fids[1:]):
        game.fighters[fid].pos = spaces[-1 - i]
    table.positions = {cfg.nicknames[f]: g.pos for f, g in game.fighters.items()}
    for fid, g in scfg.dials.items():
        table.dials[g] = {"found": True, "name": g, "value": game.fighters[fid].hp, "max": game.fighters[fid].hp}
        session.dials_written[g] = game.fighters[fid].hp
    if scfg.destiny_dial:
        table.dials[scfg.destiny_dial] = {"found": True, "name": "destinos", "value": 0, "max": 11}
    set_hand(session, table, game, *hand)
    session._preload_identities()                               # as `_begin_game` does: no identity read mid-game
    return session, table, game, fake, cfg, client


def card_ids(game, player, *titles):
    out, used = [], set()
    for t in titles:
        c = next(c for c in game.players[player].full_set if c.title == t and c.card_id not in used)
        used.add(c.card_id)
        out.append(c.card_id)
    return out


def set_hand(session, table, game, *titles):
    table.bot_hand = card_ids(game, 0, *titles)
    table.bot_deck = [c.card_id for c in game.players[0].full_set
                      if c.card_id not in table.bot_hand and c.card_id not in table.bot_discard]
    session.read_bot_hand()
    session.snap = None


def to_bot_discard(session, table, game, *titles, ids=None):
    """Cards already in the bot's discard, on the table and in the engine."""
    st = game.players[0]
    ids = card_ids(game, 0, *titles) if ids is None else list(ids)
    for i in ids:
        c = next(c for c in st.full_set if c.card_id == i)
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)
        table.bot_discard.append(i)
        session.bot_discarded.add(i)
        if i in table.bot_hand:
            table.bot_hand.remove(i)
        if i in table.bot_deck:
            table.bot_deck.remove(i)
    return ids


def human_hand(table, game, *titles):
    table.human_hand = card_ids(game, 1, *titles)
    table.human_count = len(table.human_hand)
    return table.human_hand


def human_reads(table):
    return [s for s in table.scripts if s.startswith("-- sparring:read_hand") and HUMAN_SEAT_READ in s]


def said(msgs, text):
    return any(text in m for m in msgs)


def answers(**by_kind):
    """A `choose_effect` for the bot: the answer per request kind (a callable of the request or a list)."""
    def choose(game, req):
        pick = by_kind.get(req.kind)
        return pick(req) if callable(pick) else pick
    return choose


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def hellboy_rig(f):
    return pytest.mark.parametrize("rig", [("hellboy", "abe-sapien", ("Confront Any Demon or God", "Right Hand Of Doom",
                                                                      "Service Pistol", "Excalibur", "B.P.R.D. Training"))],
                                    indirect=True)(f)


def abe_rig(f):
    return pytest.mark.parametrize("rig", [("abe-sapien", "hellboy", ("Perfect Shot", "Ward And Prepare", "Every Possible Angle",
                                                                      "Faster. Stronger.", "Secure The Scene"))],
                                    indirect=True)(f)


def liz_rig(f):
    return pytest.mark.parametrize("rig", [("liz-sherman", "hellboy", ("Pyrotechnics", "Rekindle", "Fleeting Moments",
                                                                       "Evade", "Fireball"))], indirect=True)(f)


def baba_rig(f):
    return pytest.mark.parametrize("rig", [("baba-yaga", "hellboy", ("Foul Journey", "Remove A Painful Memory",
                                                                     "Iron Teeth", "Exploit", "Deathless"))], indirect=True)(f)


def bot_turn(session, table, acts):
    """The human ends the turn (two maneuvers); the bot plays `acts` in order, then maneuvers."""
    plan = list(acts)
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    return click(session, table, Event.END_ACTION)


def human_attack(session, table, game, attacker, target, title, value=0):
    click(session, table, Event.ATTACKER, {"attacker": f"att_{attacker}"})
    click(session, table, Event.ATTACK, {"target": target})
    if value:
        click(session, table, Event.VALUE, {"value": value})
    played = human_plays(table, game, title)
    if played.card_id in table.human_hand:                      # the card leaves the real hand
        table.human_hand.remove(played.card_id)
    table.human_count -= 1


# ---------------------------------------------------------------- look_hand and the tripwire

@hellboy_rig
def test_confront_lost_reads_the_human_hand_once_and_the_named_discard_is_owed_until_it_is_on_the_pile(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    confront = next(c for c in game.players[0].hand if c.title == "Confront Any Demon or God")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: confront)
    human_hand(table, game, "Faster. Stronger.", "Leap Away", "Concussion Device", "Secure The Scene", "Advanced Psychometry")
    human_attack(session, table, game, "abe", "hellboy", "Faster. Stronger.", value=5)     # 5 + 5 > 3: the bot loses
    real = list(table.human_hand)                               # what is really in your hand after playing
    assert human_reads(table) == []
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)
    # the look is one extra message; Abe's combat damage turns one of his Intuition tokens on the table, another
    assert fake.lua_messages - n <= 3 + 2, "the look and the token are the extra messages"
    assert len(human_reads(table)) == 1
    known = game.players[0].known
    gone = [i for i in real if i not in known.seen]
    assert len(gone) == 1 and sorted(known.seen) == sorted(i for i in real if i != gone[0])
    title = next(c.title for c in game.players[1].full_set if c.card_id == gone[0])
    assert said(msgs, f"Aplicado: Confront Any Demon or God: roba 1; descartas {title}; mira tu mano")
    assert said(msgs, f"Pon {title} de tu mano en tu descarte (efectos del combate)")    # E2: your card ran too
    assert session.pending_discard["cards"] == [gone[0]] and session.pending_discard["n"] == 0
    st = game.players[1]
    for _ in range(2):                                          # the table does not show it yet: owed, never demoted
        msgs = click(session, table, Event.END_ACTION)
        assert said(msgs, f"Aun no veo en tu descarte {title}") and session.pending_discard is not None
        assert gone[0] in [c.card_id for c in st.discard] and gone[0] not in [c.card_id for c in st.deck]
    table.human_discard += [card_ids(game, 1, "Faster. Stronger.")[0], gone[0]]
    table.human_count = len(real) - 1
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and said(msgs, "Te quedan 2 accion")
    assert len(human_reads(table)) == 1, "no other read of the human hand, ever"


@hellboy_rig
def test_confront_lost_owed_discard_is_met_by_another_copy_of_the_same_title(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    confront = next(c for c in game.players[0].hand if c.title == "Confront Any Demon or God")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: confront)
    human_hand(table, game, "Faster. Stronger.", "Advanced Psychometry", "Advanced Psychometry", "Advanced Psychometry", "Leap Away")
    human_attack(session, table, game, "abe", "hellboy", "Faster. Stronger.", value=5)
    real = list(table.human_hand)
    click(session, table, Event.REVEAL)
    named = session.pending_discard["cards"][0]
    st = game.players[1]
    title = next(c.title for c in st.full_set if c.card_id == named)
    other = next(c.card_id for c in st.full_set if c.title == title and c.card_id != named and c.card_id in real)
    table.human_discard += [card_ids(game, 1, "Faster. Stronger.")[0], other]
    table.human_count = len(real) - 1
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and not said(msgs, "Aun no veo en tu descarte"), msgs
    assert sum(c.title == title for c in st.discard) == 1
    assert named not in [c.card_id for c in st.discard]


@hellboy_rig
def test_a_bot_turn_and_a_combat_without_a_look_card_never_read_the_human_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Faster. Stronger.", "Leap Away", "Concussion Device", "Secure The Scene")
    assert game.hand_reader is not None and game.clone().hand_reader is None, "clones determinize, they never read"
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: pistol)
    human_attack(session, table, game, "abe", "hellboy", "Faster. Stronger.")
    click(session, table, Event.REVEAL)
    click(session, table, Event.END_ACTION)
    bot_turn(session, table, [])
    assert human_reads(table) == [] and game.players[0].known.is_empty()


@abe_rig
def test_every_possible_angle_by_the_bot_looks_once_and_names_the_card_for_the_top_of_your_deck(rig):
    session, table, game, fake, cfg = rig
    real = human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    epa = next(c for c in game.players[0].hand if c.title == "Every Possible Angle")
    msgs = bot_turn(session, table, [Act("frenzy", card=epa)])
    assert len(human_reads(table)) == 1
    known = game.players[0].known
    assert len(known.top_of_deck) == 1 and known.top_of_deck[0] in real
    top = known.top_of_deck[0]
    title = next(c.title for c in game.players[1].full_set if c.card_id == top)
    assert said(msgs, f"Pon {title} de tu mano en la parte superior de tu mazo (efecto del bot)")
    assert game.turn == 1
    st = game.players[1]
    click(session, table, Event.MANEUVER)                       # the sync pads your hand without the known top card...
    assert len(human_reads(table)) == 1
    assert top in [c.card_id for c in st.hand] and top in known.seen   # ...and the maneuver's draw is that very card


# ---------------------------------------------------------------- the bot's form

@hellboy_rig
def test_bot_hellboy_form_change_swaps_the_miniature_flips_the_token_and_pings_both(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    destiny = [c for c in game.players[0].full_set if "destiny" in c.tags and c.title != "Confront Any Demon or God"]
    to_bot_discard(session, table, game, ids=[c.card_id for c in destiny[:5]])
    fuel = destiny[5]                                           # the sixth destiny card: the bot defends with it
    set_hand(session, table, game, "Service Pistol")            # no other destiny card in the hand
    table.bot_hand.append(fuel.card_id)
    table.bot_deck.remove(fuel.card_id)
    session.read_bot_hand()
    session.snap = None
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: fuel)
    assert game.form(0) == DETECTIVE
    human_hand(table, game, "Faster. Stronger.", "Leap Away", "Concussion Device")
    human_attack(session, table, game, "abe", "hellboy", "Faster. Stronger.")
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)
    assert fake.lua_messages - n <= 3 and game.form(0) == ANUNG
    assert table.states == [("f9789a", 2)] and table.flipped == ["1644a3"]
    assert table.pings[-1] == [["1644a3"], ["f9789a", "e6f06e"]]
    assert said(msgs, "Hellboy (bot) pasa a ANUNG UN RAMA (6 destiny): cambio su miniatura y giro su ficha de habilidad; ping sobre las dos")
    ops = [op for step in table.msglog[-3:] for op in step]
    assert ops.index("set_state") < ops.index("flip_token") < ops.index("ping_objects")
    click(session, table, Event.END_ACTION)                     # the swapped miniature is found by its new GUID
    assert not said(session.messages, "No encuentro la pieza") and game.fighters["hellboy"].alive


@hellboy_rig
def test_bot_hellboy_destiny_dial_follows_the_bot_discard_up_and_down(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    dial = cfg.session_config().destiny_dial
    assert dial == "e17c66" and table.dials[dial]["value"] == 0
    destiny = [c for c in game.players[0].full_set if "destiny" in c.tags and c.title != "Confront Any Demon or God"]
    to_bot_discard(session, table, game, ids=[c.card_id for c in destiny[:5]])
    fuel = destiny[5]
    set_hand(session, table, game, "Service Pistol")
    table.bot_hand.append(fuel.card_id)
    table.bot_deck.remove(fuel.card_id)
    session.read_bot_hand()
    session.snap = None
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: fuel)
    human_hand(table, game, "Faster. Stronger.", "Leap Away", "Concussion Device")
    human_attack(session, table, game, "abe", "hellboy", "Faster. Stronger.")
    msgs = click(session, table, Event.REVEAL)
    assert game.destiny_count(0) == 6 and table.dials[dial]["value"] == 6
    assert session.destiny_seen == (6, ANUNG)
    assert not said(msgs, "dale la vuelta") and not said(msgs, "Destinos de Hellboy")
    st = game.players[0]
    st.discard.remove(next(c for c in st.discard if c.card_id == destiny[0].card_id))     # a card leaves the pile
    assert session._write_dials()
    assert table.dials[dial]["value"] == 5


@hellboy_rig
def test_bot_hellboy_hand_limit_discard_of_a_destiny_card_moves_the_dial(rig):
    session, table, game, fake, cfg = rig
    dial = cfg.session_config().destiny_dial
    st = game.players[0]
    destiny = [c for c in st.full_set if "destiny" in c.tags][:9]
    assert len(destiny) >= 9
    table.bot_hand = [c.card_id for c in destiny]
    table.bot_deck = [c.card_id for c in st.full_set if c.card_id not in table.bot_hand]
    session.read_bot_hand()
    session.snap = None
    assert table.dials[dial]["value"] == 0
    bot_turn(session, table, [])
    assert game.destiny_count(0) >= 1
    assert table.dials[dial]["value"] == game.destiny_count(0)
    assert session.destiny_seen[0] == game.destiny_count(0)


@hellboy_rig
def test_bot_hellboy_destiny_cards_leaving_the_discard_lower_the_dial(rig):
    session, table, game, fake, cfg = rig
    dial = cfg.session_config().destiny_dial
    destiny = [c for c in game.players[0].full_set if "destiny" in c.tags]
    to_bot_discard(session, table, game, ids=[c.card_id for c in destiny[:3]])
    session._write_dials()
    assert table.dials[dial]["value"] == 3
    st = game.players[0]
    gone = next(c for c in st.discard if c.card_id == destiny[0].card_id)
    st.discard.remove(gone)                                     # back to the hand, on the table and in the engine
    st.hand.append(gone)
    table.bot_discard.remove(gone.card_id)
    table.bot_hand.append(gone.card_id)
    session.bot_discarded.discard(gone.card_id)
    bot_turn(session, table, [])
    assert table.dials[dial]["value"] == game.destiny_count(0) == 2


@hellboy_rig
def test_bot_hellboy_does_not_give_the_human_miniature_instructions(rig):
    session, table, game, fake, cfg = rig
    destiny = [c for c in game.players[0].full_set if "destiny" in c.tags]
    to_bot_discard(session, table, game, ids=[c.card_id for c in destiny[:6]])
    session.say = lambda *a, **k: pytest.fail(f"unexpected chat line {a}")
    session._track_destiny()
    assert session.destiny_seen is None or session.destiny_seen[0] == 6


# ---------------------------------------------------------------- the human's miniatures

@hellboy_rig
def test_right_hand_of_doom_moves_your_fighter_in_the_combat_script(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    abe = game.fighters["abe"]
    dest = next(s for s in sorted(game.board.adj[abe.pos]) if all(f.pos != s for f in game.fighters.values()))
    monkeypatch.setattr(session.ai, "choose_effect", answers(
        fighter=["abe"], space=lambda req: [dest] if req.extra.get("fighter") == "abe" else []))
    rhod = next(c for c in game.players[0].hand if c.title == "Right Hand Of Doom")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="abe", card=rhod)])
    assert session.pending is not None and session.pending.kind == "bot_attacks"
    table.face_down = []
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)
    assert fake.lua_messages - n <= 3 and abe.pos == dest
    nick = cfg.nicknames["abe"]
    assert (nick, dest) in table.moves and table.positions[nick] == dest
    assert said(msgs, f"{nick} se mueve a {describe(game, dest, ('abe',), session._name)}: lo he movido yo (efecto del bot)")
    assert "move_piece" in [op for step in table.msglog[-3:] for op in step]


@baba_rig
def test_foul_journey_places_your_hero_anywhere_and_the_table_follows(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hb = game.fighters["hellboy"]
    far = max((s for s in game.board.spaces if all(f.pos != s for f in game.fighters.values())),
              key=lambda s: (game.board.distance(s, hb.pos), -s))
    monkeypatch.setattr(session.ai, "choose_effect", answers(fighter=["hellboy"], space=[far]))
    journey = next(c for c in game.players[0].hand if c.title == "Foul Journey")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: journey)
    human_attack(session, table, game, "hellboy", "baba", "Service Pistol")
    msgs = click(session, table, Event.REVEAL)
    assert hb.pos == far and ("Hellboy", far) in table.moves and table.positions["Hellboy"] == far
    assert said(msgs, f"Hellboy se mueve a {describe(game, far, ('hellboy',), session._name)}: lo he movido yo (efecto del bot)")
    click(session, table, Event.END_ACTION)                     # the sync agrees with what the bot moved
    assert hb.pos == far


@hellboy_rig
def test_a_failed_piece_move_asks_you_to_move_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    abe = game.fighters["abe"]
    dest = next(s for s in sorted(game.board.adj[abe.pos]) if all(f.pos != s for f in game.fighters.values()))
    monkeypatch.setattr(session.ai, "choose_effect", answers(
        fighter=["abe"], space=lambda req: [dest] if req.extra.get("fighter") == "abe" else []))
    table.move_fails.add(cfg.session_config().pieces["abe"])
    rhod = next(c for c in game.players[0].hand if c.title == "Right Hand Of Doom")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="abe", card=rhod)])
    table.face_down = []
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, f"se mueve a {describe(game, dest, ('abe',), session._name)} por un efecto del bot: no he podido mover su miniatura, muevela tu")


# ---------------------------------------------------------------- Abe's Intuition tokens

@abe_rig
def test_abe_intuition_token_copies_are_taken_when_activated_and_removed_when_spent(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    shot = next(c for c in game.players[0].hand if c.title == "Perfect Shot")
    bot_turn(session, table, [Act("attack", fid="abe", target="hellboy", card=shot)])
    table.face_down = []
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)                  # 3 combat damage to the adjacent Hellboy
    assert fake.lua_messages - n <= 3 and game.fx.counter_value(0, "intuition") == 1
    assert table.tokens == ["tok1"] and session.token_copies == {"intuition": ["tok1"]}
    assert said(msgs, "Abe Sapien (bot) activa 1 ficha de intuition: 1 activa(s)")
    script = next(s for s in table.scripts if s.startswith("-- sparring:take_token_copy"))
    assert '"5a17e9"' in script
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["token_copies"] == {"intuition": ["tok1"]}
    click(session, table, Event.END_ACTION)                     # the bot's second action, then your turn
    assert game.turn == 1
    human_attack(session, table, game, "hellboy", "abe", "Service Pistol")
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)                  # attacked with an active token: spent
    # one more message than a plain reveal: the card the trigger draws is dealt BEFORE the bot chooses its
    # defense, so it can be that defense (Ivan, 29/10; E3)
    assert fake.lua_messages - n <= 4 and game.fx.counter_value(0, "intuition") == 0
    assert table.tokens == [] and session.token_copies == {"intuition": []}
    assert said(msgs, "Abe Sapien (bot) gasta 1 ficha de intuition: 0 activa(s)")


# ---------------------------------------------------------------- the bot's own deck and discard

@liz_rig
def test_pyrotechnics_puts_two_hand_cards_at_the_bottom_of_the_bot_deck_in_the_same_script(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    pyro = next(c for c in game.players[0].hand if c.title == "Pyrotechnics")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: pyro)
    monkeypatch.setattr(session.ai, "choose_effect", answers(
        optional=[True], cards=lambda req: list(req.options)[:req.max], order=lambda req: list(req.options)))
    human_attack(session, table, game, "hellboy", "liz", "Service Pistol")
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)
    assert fake.lua_messages - n <= 3
    assert len(table.hand_moves) == 1 and table.hand_moves[0][0] == "bottom" and len(table.hand_moves[0][1]) == 2
    assert said(msgs, "El bot pone 2 cartas de su mano en el fondo de su mazo")
    assert sorted(c.card_id for c in game.players[0].hand) == sorted(table.bot_hand)
    assert table.bot_deck[-2:] == table.hand_moves[0][1]
    assert not said(msgs, "no coincide")


@liz_rig
def test_rekindle_shuffles_three_discard_cards_back_into_the_bot_deck(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    burnt = to_bot_discard(session, table, game, "Flame Lash", "Burning Barrier", "Fireball")
    rekindle = next(c for c in game.players[0].hand if c.title == "Rekindle")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: rekindle)
    monkeypatch.setattr(session.ai, "choose_effect", answers(cards=lambda req: list(req.options)[:req.max]))
    human_attack(session, table, game, "hellboy", "liz", "Service Pistol")
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)
    assert fake.lua_messages - n <= 3
    assert table.deck_moves == [("shuffle", burnt)] or table.deck_moves == [("shuffle", sorted(burnt))]
    assert said(msgs, "El bot baraja Flame Lash, Burning Barrier y Fireball de su descarte en su mazo")
    st = game.players[0]
    assert all(i not in session.bot_discarded for i in burnt)
    assert all(i in [c.card_id for c in st.deck] for i in burnt) and all(i not in table.bot_discard for i in burnt)
    assert not said(msgs, "La mesa manda") and not said(msgs, "no coincide")


@abe_rig
def test_ward_and_prepare_recovers_a_scheme_from_the_discard_to_the_bot_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    scheme = to_bot_discard(session, table, game, "B.P.R.D. Utility Belt")[0]
    ward = next(c for c in game.players[0].hand if c.title == "Ward And Prepare")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: ward)
    human_attack(session, table, game, "hellboy", "abe", "Service Pistol")
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)
    assert fake.lua_messages - n <= 3
    assert said(msgs, "El bot recupera B.P.R.D. Utility Belt de su descarte a su mano")
    assert scheme in table.bot_hand and scheme not in table.bot_discard and scheme not in session.bot_discarded
    assert scheme in [c.card_id for c in game.players[0].hand]
    assert not said(msgs, "La mesa manda") and not said(msgs, "no coincide")


@liz_rig
def test_fleeting_moments_names_a_random_position_of_your_hand_without_reading_it(rig):
    """Ivan 29/10: the engine draws the position (it knows only how many cards you hold), you discard that card."""
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    fleeting = next(c for c in game.players[0].hand if c.title == "Fleeting Moments")
    bot_turn(session, table, [Act("attack", fid="liz", target="hellboy", card=fleeting)])
    table.face_down = []
    before = list(game.players[1].discard)
    msgs = click(session, table, Event.REVEAL)
    assert session.pending_discard["n"] == 1 and "cards" not in session.pending_discard
    line = next(m for m in msgs if "Descarta 1 carta(s) (Fleeting Moments, al azar: la carta " in m)
    pos = int(line.split("la carta ")[1].split(" ")[0])
    assert 1 <= pos <= len(game.players[1].hand) and "de tu mano contando desde la izquierda" in line
    assert game.players[1].discard == before, "the engine never names a placeholder card of your hand"
    assert human_reads(table) == []


# ---------------------------------------------------------------- a pause of the human (E1) survives the save

@baba_rig
def test_remove_a_painful_memory_pauses_for_you_and_resumes_from_a_save_with_the_named_discard(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    st = game.players[0]
    pact = next(c for c in st.deck if c.title == "Pact Of Peace")
    st.deck.remove(pact)
    game.fx.set_ongoing(0, pact.card_id)                        # an active ongoing scheme: the card's condition
    table.bot_deck.remove(pact.card_id)
    memory = next(c for c in st.hand if c.title == "Remove A Painful Memory")
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    bot_turn(session, table, [Act("attack", fid="baba", target="hellboy", card=memory)])
    table.face_down = []
    click(session, table, Event.REVEAL)
    p = session.pending
    assert p is not None and p.flow is not None and session.effect_run.awaiting.kind == "optional"
    assert visible_choices(session) == ["btn_choice_1", "btn_choice_2"] and len(human_reads(table)) == 1
    assert "fx" in p.combat and isinstance(p.combat["fx"]["human"]["hand"], list)
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    assert twin.game.hand_reader == twin._read_human_hand and twin.effect_run.awaiting.kind == "optional"
    hp = twin.game.fighters["hellboy"].hp
    msgs = click(twin, table, Event.CHOICE, {"i": 1})           # Si: you discard the card the bot named
    assert twin.pending is None and twin.pending_discard is not None
    named = twin.pending_discard["cards"]
    assert len(named) == 1 and named[0] in table.human_hand
    title = next(c.title for c in twin.game.players[1].full_set if c.card_id == named[0])
    assert said(msgs, f"Pon {title} de tu mano en tu descarte (efecto del bot)")
    assert twin.game.fighters["hellboy"].hp == hp and len(human_reads(table)) == 1


def twin_session(session, cfg, saved):
    twin = Session(Game.new(cfg.board, seed=3, controllers={}, bot_player=0, heroes=cfg.heroes), session.client,
                   MedusaAI(0), session.cfg)
    twin.game_id = session.game_id
    twin.load_dict(saved)
    return twin


def answer_pause(session, table):
    """Presses the choice buttons until the pending request is answered: single picks at once, multi-picks by
    toggling the first `min` options and confirming."""
    from sparring.session_choices import layout
    req = session.effect_run.awaiting
    if req.min == 1 and req.max == 1:
        return click(session, table, Event.CHOICE, {"i": 1})
    for i in range(1, max(req.min, 1) + 1):
        msgs = click(session, table, Event.CHOICE, {"i": i})
    if session._paused() is not None and session.effect_run.awaiting is req:
        slots = layout(session.game, req, session.choice_ui)
        msgs = click(session, table, Event.CHOICE, {"i": next(k for k, s in enumerate(slots, 1) if s.action == "confirm")})
    return msgs


@baba_rig
def test_a_bot_scheme_that_asks_you_pauses_the_bot_turn_survives_a_save_and_finishes_when_answered(rig):
    """Pact Of Secrecy: you choose the 2 cards you keep. The scheme's run is parked (E1's pause), the bot's turn
    waits at the panel, a save resumes it and, answered, the card ends in the bot's discard and the turn goes on."""
    session, table, game, fake, cfg = rig
    pact = next(c for c in game.players[0].deck if c.title == "Pact Of Secrecy")
    game.players[0].deck.remove(pact)
    game.players[0].hand.append(pact)
    table.bot_deck.remove(pact.card_id)
    table.bot_hand.append(pact.card_id)
    session.snap = None
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell", "Pancakes!")
    msgs = bot_turn(session, table, [Act("frenzy", card=pact)])
    assert game.turn == 0 and session._paused() is not None and session._paused()[0] == "parked"
    assert said(msgs, "El bot juega Pact Of Secrecy") and visible_choices(session)
    assert game.fx.parked and game.fx.parked[0].flags["scheme"] == {"player": 0, "card_id": pact.card_id}
    assert pact.card_id not in [c.card_id for c in game.players[0].hand + game.players[0].discard]
    assert human_reads(table) == []
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    twin.ai.plan = lambda g: Act("maneuver", moves={})
    twin.ai.pick_ability_target = lambda g: None
    assert twin._paused() is not None and twin._paused()[0] == "parked" and twin.game.turn == 0
    guard = 0
    while twin._paused() is not None and guard < 6:
        msgs = answer_pause(twin, table)
        guard += 1
    assert twin._paused() is None and twin.game.fx.parked == []
    st = twin.game.players[0]
    assert twin.game.fx.ongoing_card_id(0) == pact.card_id, "an ONGOING scheme stays in play"
    assert pact.card_id not in [c.card_id for c in st.hand + st.discard + st.deck]
    assert said(msgs, "Efecto resuelto") and twin.game.turn == 1, "the bot's turn went on to its end"
    # the card itself still sits in the table hand (placing the bot's ONGOING on the table is D2's); never a hand card
    assert sorted(c.card_id for c in st.hand) == sorted(i for i in table.bot_hand if i != pact.card_id)


# ---------------------------------------------------------------- narration

def test_a_card_line_is_recorded_once_and_an_idle_moment_never_repeats_or_hides_an_effect():
    applied = []
    narrate.record(applied, "Perfect Shot: sin efecto")
    narrate.record(applied, "Perfect Shot: sin efecto")
    assert applied == ["Perfect Shot: sin efecto"]
    narrate.record(applied, "Flame Lash: sin efecto")
    narrate.record(applied, "Flame Lash: gana 1 accion")
    assert applied == ["Perfect Shot: sin efecto", "Flame Lash: gana 1 accion"]
    narrate.record(applied, "Flame Lash: sin efecto")
    assert applied == ["Perfect Shot: sin efecto", "Flame Lash: gana 1 accion"]


def test_the_bot_narrates_medusa_cards_too(bprd):
    from conftest import Scripted, give
    ctl = {0: Scripted(), 1: Scripted()}
    g = Game.new(bprd, seed=3, controllers=ctl, bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    g.fighters["medusa"].pos, g.fighters["hellboy"].pos = 0, 1
    ctl[0].moves["medusa"] = 3
    res = g.attack(g.fighters["medusa"], g.fighters["hellboy"], give(g, 0, "Dash"), None)
    assert res.applied == [f"Dash: medusa se mueve a {describe(g, 3, ('medusa',))}"]


# ---------------------------------------------------------------- configuration

def test_token_spot_reaches_the_session_config_and_is_validated(tmp_path):
    cfg = config_for(tmp_path, "abe-sapien", "hellboy")
    assert cfg.session_config().token_spot is None
    cfg.raw["token_spot"] = [1, 2, 3]
    assert cfg.session_config().token_spot == (1.0, 2.0, 3.0)
    cfg.raw["token_spot"] = [1, 2]
    with pytest.raises(play.ConfigError):
        cfg.session_config()


@hellboy_rig
def test_bot_hellboy_anung_start_of_turn_says_the_discard_and_the_move_and_projects_them(rig, tmp_path):
    session, table, game, fake, cfg = rig
    session.game_log.path = tmp_path / "session.log"
    session.game_log.observe(game, session._name)
    destiny = [c for c in game.players[0].full_set if "destiny" in c.tags and c.title != "Confront Any Demon or God"]
    to_bot_discard(session, table, game, ids=[c.card_id for c in destiny[:6]])
    set_hand(session, table, game, "Service Pistol")             # the only card: the one ANUNG must discard
    assert game.form(0) == ANUNG
    start = game.fighters["hellboy"].pos
    msgs = bot_turn(session, table, [])
    line = next(m for m in msgs if m.startswith("ANUNG UN RAMA: el bot descarta Service Pistol"))
    pistol = next(c for c in game.players[0].discard if c.title == "Service Pistol")
    moved = game.fighters["hellboy"].pos != start
    assert f"(BOOST {pistol.boost})" in line and ("y mueve Hellboy hasta" in line) == moved
    assert pistol.card_id in table.bot_discard
    log = (tmp_path / "session.log").read_text(encoding="utf-8")
    assert "(P0) starts" in log and "DISCARD: P0 Service Pistol" in log and log.count("DISCARD: P0 Service Pistol") == 1
    assert (log.count("MOVE: Hellboy") >= 1) == moved


@hellboy_rig
def test_the_game_log_keeps_the_turn_start_of_the_bot_and_the_events_of_each_step(rig, tmp_path):
    session, table, game, fake, cfg = rig
    session.game_log.path = tmp_path / "session.log"
    session.game_log.observe(game, session._name)
    bot_turn(session, table, [])
    text = (tmp_path / "session.log").read_text(encoding="utf-8")
    assert "(P0) starts" in text and "(P1) starts" in text


@hellboy_rig
def test_bot_hellboy_anung_start_move_reaches_the_table_and_the_chat_names_the_place(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    destiny = [c for c in game.players[0].full_set if "destiny" in c.tags and c.title != "Confront Any Demon or God"]
    to_bot_discard(session, table, game, ids=[c.card_id for c in destiny[:6]])
    set_hand(session, table, game, "Service Pistol")
    start = game.fighters["hellboy"].pos
    monkeypatch.setattr(session.ai, "choose_move", lambda g, f, steps, through=False: max(g.legal_moves(f, steps, through)))
    msgs = bot_turn(session, table, [])
    hellboy = game.fighters["hellboy"]
    assert hellboy.pos != start
    assert any(m.startswith("ANUNG UN RAMA: el bot descarta Service Pistol (BOOST 2) y mueve Hellboy hasta 2: ") for m in msgs)
    assert table.positions[table.nick["hellboy"]] == hellboy.pos


@hellboy_rig
def test_bot_hellboy_detective_draw_is_said_and_the_two_cards_reach_the_table_hand(rig, tmp_path):
    session, table, game, fake, cfg = rig
    session.game_log.path = tmp_path / "session.log"
    session.game_log.observe(game, session._name)
    assert game.form(0) == DETECTIVE
    game.fighters["hellboy"].pos = game.start_spaces[1]          # the rival's starting zone
    table.positions[table.nick["hellboy"]] = game.start_spaces[1]
    msgs = bot_turn(session, table, [])
    lines = [m for m in msgs if m.startswith("OCCULT DETECTIVE:")]
    assert len(lines) == 1 and "roba 2" in lines[0], msgs
    assert sorted(table.bot_hand) == sorted(c.card_id for c in game.players[0].hand)
    log = (tmp_path / "session.log").read_text(encoding="utf-8")
    assert log.count("DRAW: P0 draws 2") == 1


@hellboy_rig
def test_bot_hellboy_detective_outside_the_rival_start_zone_says_nothing(rig):
    session, table, game, fake, cfg = rig
    assert game.fighters["hellboy"].pos != game.start_spaces[1]
    msgs = bot_turn(session, table, [])
    assert not any(m.startswith("OCCULT DETECTIVE:") for m in msgs)
