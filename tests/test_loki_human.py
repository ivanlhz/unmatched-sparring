"""Loki at the table (FakeTTS sessions): the TRICKs that change hands physically. The bot is Loki and gives the human the TRICKs it plays; the
human plays and discards them; or the human is Loki and the bot takes, plays and returns them. Design: docs/heroes/loki.md, "At the table".
The other hero is Hellboy (CardIDs 19700+), so the fake table's per-seat lists of CardIDs never see two decks with the same id; the collision
itself (sheet 176 against sheet 176) is in tests/test_loki_effects.py and the ledger tests at the end of this file."""
from __future__ import annotations

import re

import pytest

from sparring import session_bot_effects as bot_effects, session_choices as choices, tricks
from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import FxTable, build, bot_turn, human_hand

BALDR, FREYJA, SINDRI, LURE = "Trick: Baldr's Downfall", "Trick: Freyja's Rescue", "Trick: Sindri's Bet", "Trick: Svadilfari's Lure"


class LokiTable(FxTable):
    """The fake table where a Loki card is one object with one GUID (`h<CardID>`) wherever it lies: the bot's hand, its combat spot, the human's
    hand, spot or pile. The base fake keeps one list of CardIDs per place; a card of Loki's deck (`loki_ids`) is moved between those lists."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.loki_ids: set[int] = set()
        self.zones = {"bot": None, "human": None}              # GUIDs of the two discard zones

    # ---- one GUID for a Loki card, wherever the base fake would label it
    def _relabel(self, rows):
        return [{**r, "guid": f"h{r['id']}"} if r["id"] in self.loki_ids else r for r in rows]

    def snapshot_state(self):
        snap = super().snapshot_state()
        for key in ("bot_hand", "bot_discard", "human_discard", "face_bot"):
            snap[key] = self._relabel(snap[key])
        return snap

    def do_read_hand(self, s):
        return self._relabel(super().do_read_hand(s))

    def do_read_discard(self, s):
        return self._relabel(super().do_read_discard(s))

    # ---- where a Loki card is
    def _places(self):
        return {"bot_hand": self.bot_hand, "bot_play": self.bot_play, "bot_discard": self.bot_discard, "human_hand": self.human_hand,
                "human_discard": self.human_discard, "bot_deck": self.bot_deck, "human_deck": self.human_deck}

    def _take(self, i):
        """Takes the card `i` off wherever it is (the lists and the human's spot rows)."""
        for lst in self._places().values():
            if i in lst:
                lst.remove(i)
        for rows in (self.face_down, self.face_up):
            for r in [r for r in rows if r["id"] == i]:
                rows.remove(r)

    def _put(self, i, where):
        self._places()[where].append(i)
        self.human_count = len(self.human_hand)

    @staticmethod
    def _id(s):
        m = re.search(r'getObjectFromGUID\("h(\d+)"\)', s)
        return int(m.group(1)) if m else None

    def do_return_card_to_hand(self, s):
        i = self._id(s)
        if i is None or i not in self.loki_ids:
            return super().do_return_card_to_hand(s)
        self._take(i)
        self._put(i, "human_hand" if 'Player["Red"]' in s else "bot_hand")
        self.returned.append(f"h{i}")
        return {"returned": f"h{i}"}

    def do_pile_card_to_hand(self, s):
        i = int(re.search(r"\.CardID == (\d+)", s).group(1))
        if i not in self.loki_ids or i not in self.human_discard + self.bot_discard:
            return {"moved": False}
        self._take(i)
        self._put(i, "human_hand" if 'Player["Red"]' in s else "bot_hand")
        return {"moved": True, "guid": f"h{i}"}

    def do_card_to_discard(self, s):
        i = self._id(s)
        if i is None or i not in self.loki_ids:
            return super().do_card_to_discard(s)
        self._take(i)
        self._put(i, "human_discard" if self.zones["human"] in s else "bot_discard")
        return {"moved": [i], "count": 1, "zone": True}

    def do_card_to_deck_top(self, s):
        i = self._id(s)
        if i is None or i not in self.loki_ids:
            return super().do_card_to_deck_top(s)
        self._take(i)
        human = self._human_side(s)
        (self.human_deck if human else self.bot_deck).insert(0, i)
        self.deck_moves.append(("top", [i]))
        return {"placed": True, "deck": "DECK1", "quantity": 1}

    def do_discard_cards(self, s):
        """The real script finds a card of the bot's deck at the human's combat spot (a TRICK the human played) and puts it on the bot's pile."""
        for i in [int(x) for x in re.findall(r"\[(\d+)\]=\{", s)]:
            for rows in (self.face_up, self.face_down):
                for r in [r for r in rows if r["id"] == i and r["id"] in self.loki_ids]:
                    rows.remove(r)
                    self.bot_play.append(i)
        return super().do_discard_cards(s)


def rig(tmp_path, bot, human, hand):
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=LokiTable)
    scfg = cfg.session_config()
    table.zones = {"bot": scfg.bot_discard_zone, "human": scfg.human_discard_zone}
    table.loki_ids = {c.card_id for c in game.players[0 if bot == "loki" else 1].full_set}
    return session, table, game, fake, cfg, client


@pytest.fixture
def loki_rig(tmp_path):
    """Loki is the bot (player 0), Hellboy the human holding three cards of his own."""
    session, table, game, fake, cfg, client = rig(tmp_path, "loki", "hellboy", (BALDR, "Underhanded", "Ragnarök", LURE, FREYJA))
    human_hand(table, game, "Service Pistol", "B.P.R.D. Training", "Excalibur")
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


@pytest.fixture
def human_loki_rig(tmp_path):
    """Loki is the human (player 1, with three cards of his deck in hand), Hellboy the bot."""
    session, table, game, fake, cfg, client = rig(tmp_path, "hellboy", "loki", ("Service Pistol", "B.P.R.D. Training", "Excalibur", "Right Hand Of Doom", "Second Shot"))
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def lend_to_human(session, table, game, title=BALDR):
    """The state after the bot gave the human a TRICK: in the engine's hand, in the ledger and in the real hand."""
    trick = next(c for c in game.players[0].full_set if c.title == title and c.card_id not in table.human_hand)
    for pile in (game.players[0].hand, game.players[0].deck):
        if trick in pile:
            pile.remove(trick)
    for ids in (table.bot_hand, table.bot_deck):
        if trick.card_id in ids:
            ids.remove(trick.card_id)
    game.players[1].hand.append(trick)
    game.players[0].known.foreign.append(trick.card_id)
    table.human_hand.append(trick.card_id)
    table.human_count = len(table.human_hand)
    session.trick_guids[f"h{trick.card_id}"] = [0, trick.card_id]
    return trick


# ---------------------------------------------------------------- the bot is Loki

def test_a_trick_the_bot_plays_lands_in_the_humans_hand(loki_rig):
    session, table, game, fake, cfg = loki_rig
    baldr = next(c for c in game.players[0].hand if c.title == BALDR)
    bot_turn(session, table, [Act("attack", fid="loki", target="hellboy", card=baldr)])
    assert session.pending is not None and session.pending.kind == "bot_attacks"
    table.face_down = []
    click(session, table, Event.REVEAL)
    assert baldr in game.players[1].hand and baldr not in game.players[0].discard
    assert baldr.card_id in table.human_hand and baldr.card_id not in table.bot_play + table.bot_discard
    assert session.trick_guids == {f"h{baldr.card_id}": [0, baldr.card_id]}
    assert game.players[0].known.foreign == [baldr.card_id] and game.counter(0, "trick_in_rival_hand") == 1


def test_the_human_plays_the_trick_they_hold_and_it_goes_to_lokis_discard(loki_rig):
    session, table, game, fake, cfg = loki_rig
    trick = lend_to_human(session, table, game)
    game.turn, game.turn_no = 1, 3
    game.begin_turn()
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    click(session, table, Event.ATTACK, {"target": "loki"})
    table.face_down = [{"id": trick.card_id, "guid": f"h{trick.card_id}"}]
    table.human_hand.remove(trick.card_id)
    table.human_count = len(table.human_hand)
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.REVEAL)
    assert trick in game.players[0].discard and trick not in game.players[1].hand
    assert game.fighters["hellboy"].hp <= hp - 2                      # NOT LOKI: 2 damage to the hero of whoever plays it
    assert session.trick_guids == {} and trick.card_id in table.bot_discard and not table.face_down + table.face_up


def test_a_trick_the_human_discards_goes_back_to_lokis_hand(loki_rig):
    session, table, game, fake, cfg = loki_rig
    trick = lend_to_human(session, table, game, SINDRI)
    table._take(trick.card_id)
    table._put(trick.card_id, "human_discard")                         # laid on their own pile by hand
    click(session, table, Event.MANEUVER)
    assert trick in game.players[0].hand and trick not in game.players[1].hand
    assert trick.card_id in table.bot_hand and trick.card_id not in table.human_discard
    assert session.trick_guids == {} and game.players[0].known.foreign == []


# ---------------------------------------------------------------- the human is Loki

def test_a_trick_the_human_plays_is_taken_into_the_bots_hand(human_loki_rig):
    session, table, game, fake, cfg = human_loki_rig
    trick = next(c for c in game.players[1].full_set if c.title == BALDR)
    game.players[1].hand.append(trick)
    table.human_hand.append(trick.card_id)
    table.human_count = len(table.human_hand)
    game.turn, game.turn_no = 1, 3
    game.begin_turn()
    click(session, table, Event.ATTACKER, {"attacker": "att_loki"})
    click(session, table, Event.ATTACK, {"target": "hellboy"})
    table.face_down = [{"id": trick.card_id, "guid": f"h{trick.card_id}"}]
    table.human_hand.remove(trick.card_id)
    table.human_count = len(table.human_hand)
    click(session, table, Event.REVEAL)
    assert trick in game.players[0].hand and trick not in game.players[1].discard
    assert trick.card_id in table.bot_hand and not table.face_down + table.face_up
    assert session.trick_guids == {f"h{trick.card_id}": [1, trick.card_id]}


def given_to_bot(session, table, game, title=BALDR):
    """The state after the human (Loki) gave the bot a TRICK: in the bot's engine hand and real hand, and in the ledger."""
    trick = next(c for c in game.players[1].full_set if c.title == title)
    for pile in (game.players[1].hand, game.players[1].deck):
        if trick in pile:
            pile.remove(trick)
    table._take(trick.card_id)
    game.players[0].hand.append(trick)
    table.bot_hand.append(trick.card_id)
    session.trick_guids[f"h{trick.card_id}"] = [1, trick.card_id]
    return trick


def test_the_bot_plays_the_humans_trick_with_his_images_and_it_goes_to_his_pile(human_loki_rig):
    session, table, game, fake, cfg = human_loki_rig
    trick = given_to_bot(session, table, game)
    bot_turn(session, table, [Act("attack", fid="hellboy", target="loki", card=trick)])
    assert session.pending is not None and session.pending.kind == "bot_attacks"
    script = next(s for s in table.scripts if s.startswith("-- sparring:play_card_face_down"))
    assert cfg.session_config().human_card_ids[0] <= trick.card_id <= cfg.session_config().human_card_ids[1]
    assert "17600" in script and f"CardID == {trick.card_id}" in script
    table.face_down = []
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.REVEAL)
    assert trick in game.players[1].discard and trick not in game.players[0].hand and trick not in game.players[0].discard
    assert trick.card_id in table.human_discard and trick.card_id not in table.bot_play + table.bot_hand
    assert session.trick_guids == {} and game.fighters["hellboy"].hp <= hp - 2                  # NOT LOKI: the bot's hero takes 2


def test_a_trick_the_bot_discards_goes_back_to_the_humans_hand(human_loki_rig):
    session, table, game, fake, cfg = human_loki_rig
    trick = given_to_bot(session, table, game, SINDRI)
    before = bot_effects.snapshot(session)
    game.discard_card(0, trick, cause="hand_limit")                         # the bot's hand limit (or an effect) takes it
    session._project_effects(before)()
    assert trick in game.players[1].hand and trick not in game.players[0].hand and trick not in game.players[0].discard
    assert trick.card_id in table.human_hand and trick.card_id not in table.bot_hand
    assert session.trick_guids == {}


def test_laevateinn_asks_which_card_lies_at_the_position_and_a_trick_goes_to_lokis_hand(tmp_path):
    session, table, game, fake, cfg, client = rig(tmp_path, "loki", "hellboy", ("Laevateinn", "Underhanded", "Ragnarök", LURE, FREYJA))
    try:
        human_hand(table, game, "Service Pistol", "B.P.R.D. Training")
        trick = lend_to_human(session, table, game, SINDRI)
        lae = next(c for c in game.players[0].hand if c.title == "Laevateinn")
        bot_turn(session, table, [Act("attack", fid="loki", target="hellboy", card=lae)])
        table.face_down = []
        msgs = click(session, table, Event.REVEAL)
        req = session.effect_run.awaiting
        assert req.kind == "cards" and req.extra["purpose"] == "reveal" and tricks.qualified(trick) in req.options
        assert choices.option_label(game, req, tricks.qualified(trick)) == "Trick: Sindri's Bet"        # the button is named by the TRICK's title
        click(session, table, Event.CHOICE, {"i": req.options.index(tricks.qualified(trick)) + 1})
        assert trick in game.players[0].hand and trick not in game.players[1].hand
        assert trick.card_id in table.bot_hand and trick.card_id not in table.human_hand and session.trick_guids == {}
        assert game.players[0].known.foreign == []
    finally:
        client.close()
        fake.close()


def test_looking_for_trouble_makes_the_human_play_the_trick_the_bot_names(tmp_path):
    session, table, game, fake, cfg, client = rig(tmp_path, "loki", "hellboy", ("Looking For Trouble", "Underhanded", "Ragnarök", LURE, FREYJA))
    try:
        human_hand(table, game, "B.P.R.D. Training", "Excalibur")
        trick = lend_to_human(session, table, game, SINDRI)
        training = next(c for c in game.players[1].full_set if c.title == "B.P.R.D. Training")
        lfr = next(c for c in game.players[0].hand if c.title == "Looking For Trouble")
        bot_turn(session, table, [Act("attack", fid="loki", target="hellboy", card=lfr)])
        table.face_down = [{"id": training.card_id, "guid": f"h{training.card_id}"}]       # their defense
        table.human_hand.remove(training.card_id)
        table.human_count = len(table.human_hand)
        click(session, table, Event.REVEAL)
        req = session.effect_run.awaiting
        assert req.extra["purpose"] == "swap_defense" and req.options == [tricks.qualified(trick)]       # the bot looked at the hand and named the TRICK (LO4)
        table.face_down = []
        table.face_up = [{"id": training.card_id, "guid": f"h{training.card_id}"}, {"id": trick.card_id, "guid": f"h{trick.card_id}"}]     # the chosen card lies beside their defense, which the bot takes back
        table.human_hand.remove(trick.card_id)
        table.human_hand.append(training.card_id)
        table.human_count = len(table.human_hand)
        click(session, table, Event.CHOICE, {"i": 1})                                          # Done
        assert game.players[1].hand and training in game.players[1].hand
        assert trick in game.players[0].discard and trick not in game.players[1].hand        # played by the opponent: Loki's discard
        assert session.trick_guids == {} and trick.card_id in table.bot_discard and trick.card_id not in table.human_hand
    finally:
        client.close()
        fake.close()


def test_a_trick_the_bot_plays_as_a_scheme_lands_in_the_humans_hand(loki_rig):
    session, table, game, fake, cfg = loki_rig
    lure = next(c for c in game.players[0].hand if c.title == LURE)
    msgs = bot_turn(session, table, [Act("frenzy", card=lure)])                         # any scheme is an Act "frenzy" in these rigs
    assert lure in game.players[1].hand and lure not in game.players[0].discard
    assert lure.card_id in table.human_hand and lure.card_id not in table.bot_hand + table.bot_discard
    assert session.trick_guids == {f"h{lure.card_id}": [0, lure.card_id]}
    assert any("va a tu mano" in m for m in msgs), msgs


def test_the_ledger_is_saved_and_resumed_with_the_game(loki_rig):
    import json
    session, table, game, fake, cfg = loki_rig
    trick = lend_to_human(session, table, game, SINDRI)
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["trick_guids"] == {f"h{trick.card_id}": [0, trick.card_id]}
    session.trick_guids.clear()
    session.load_dict(saved)
    assert session.trick_guids == {f"h{trick.card_id}": [0, trick.card_id]}
    assert trick in session.game.players[1].hand and session.game.players[0].known.foreign == [trick.card_id]
