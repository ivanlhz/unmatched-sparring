"""The future of Ninjutsu at the live table (FakeTTS, batch mode), both sides: "look at the top card of ANY deck".

The human plays it: they choose a deck on the panel; the bot's deck shows its engine top card face up in the row (pinged,
said in the chat) and the game waits for leave / bottom; the bot puts the card back on top or at the bottom of its physical
deck. The bot plays it: it may read the human's real top card from the table and put it at the bottom (it only says that
it looked, never the card)."""
from __future__ import annotations

import json
import re

import pytest

from sparring.ai_effects import EffectAI
from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import FxTable, bot_turn, build, human_hand, said, twin_session
from test_e2_human_cards import human_scheme, labels, press

OWN, RIVAL = 0, 1
LEAVE, BOTTOM = 0, 1


class DeckTable(FxTable):
    """The fake table that models the order of both decks (top first) and a row for the card the bot shows."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.row: list[int] = []
        self.bot_deck_fails = False
        self.depth = 0                              # > 0 while a composite script is running its operations
        self.reads: list[bool] = []                 # for each peek_deck_top / deck_top_to_bottom: was it inside a composite?
        self.moves: list[bool] = []
        self.opens: list[bool] = []
        self.lone = False                           # the whole deck was one card and it lies face up in the row: no deck to find
        self.homes: list[bool] = []
        self.reorders: list[tuple] = []             # (seen, top, bottom, inside a composite) of each deck_reorder

    def do_composite(self, s):
        self.depth += 1
        try:
            return super().do_composite(s)
        finally:
            self.depth -= 1

    def do_deck_card_to_spot(self, s):
        self.opens.append(self.depth > 0)
        card_id = int(re.search(r"CardID ~= (\d+)", s).group(1))
        if self.bot_deck_fails or card_id not in self.bot_deck:
            return {"taken": False}
        alone = len(self.bot_deck) == 1
        self.bot_deck.remove(card_id)
        self.row.append(card_id)
        self.lone = alone
        if alone:
            return {"taken": True, "guid": f"g{card_id}", "single": True, "home": [3.0, 1.0, 4.0], "rot": [0.0, 90.0, 180.0]}
        return {"taken": True, "guid": f"g{card_id}"}

    def do_card_home(self, s):
        self.homes.append(self.depth > 0)
        card_id = int(re.search(r'getObjectFromGUID\("g(\d+)"\)', s).group(1))
        if card_id not in self.row:
            return {"placed": False}
        self.row.remove(card_id)
        self.bot_deck.append(card_id)
        self.lone = False
        return {"placed": True, "guid": f"g{card_id}"}

    def _deck_insert(self, s, kind):
        if self.lone and not self._human_side(s):
            return {"placed": False, "deck": False}       # a face-up card is no deck: TTS finds nothing to put it into
        if self._human_side(s) or not self.row:
            return super()._deck_insert(s, kind)
        card_id = int((re.search(r"getData\(\)\.CardID == (\d+)", s) or re.search(r'getObjectFromGUID\("g(\d+)"\)', s)).group(1))
        if card_id not in self.row:
            return {"placed": False}
        self.row.remove(card_id)
        self.bot_deck.insert(0, card_id) if kind == "top" else self.bot_deck.append(card_id)
        self.deck_moves.append((kind, [card_id]))
        return {"placed": True, "deck": "DECK1", "quantity": len(self.bot_deck)}

    def do_peek_deck_top(self, s):
        self.reads.append(self.depth > 0)
        if not self.human_deck:
            return {"found": False}
        return {"found": True, "id": self.human_deck[0], "quantity": len(self.human_deck)}

    def do_deck_reorder(self, s):
        """The blind reorder of the human's real deck: the top must still be what was read, else nothing moves. The cards never
        leave the deck face down, so nothing is added to `row`, `face_down` or any other zone, and the count does not change."""
        seen, top, bottom = (list(map(int, re.findall(r"\d+", part)))
                             for part in re.search(r"local seen, top, bottom = \{([^}]*)\}, \{([^}]*)\}, \{([^}]*)\}", s).groups())
        self.reorders.append((seen, top, bottom, self.depth > 0))
        if not self.human_deck:
            return {"reordered": False, "deck": False}
        if self.human_deck[:len(seen)] != seen:
            return {"reordered": False, "mismatch": True}
        was = len(self.human_deck)
        self.human_deck[:len(seen)] = []
        self.human_deck[:0] = top
        self.human_deck.extend(bottom)
        return {"reordered": True, "moved": True, "quantity": len(self.human_deck), "was": was, "order": top,
                "last": self.human_deck[-1], "deck": "DECK1"}

    def do_deck_top_to_bottom(self, s):
        self.moves.append(self.depth > 0)
        expect = int(re.search(r"first\.CardID ~= (\d+)", s).group(1))
        if not self.human_deck or self.human_deck[0] != expect:
            return {"moved": False}
        self.human_deck.append(self.human_deck.pop(0))
        return {"moved": True, "deck": "DECK1"}


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=DeckTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(bot, human, *hand):
    return pytest.mark.parametrize("rig", [(bot, human, hand)], indirect=True)


HUMAN_PLAYS = ("hellboy", "donatello", "Service Pistol", "Excalibur", "Right Hand Of Doom")
BOT_PLAYS = ("donatello", "hellboy", "The future of Ninjutsu", "Quick strike", "Bo staff")


def to_the_bots_deck(session, table, game):
    """The human plays the card and chooses the bot's deck: returns the engine's top card of the bot's deck."""
    human_hand(table, game, "The future of Ninjutsu", "Bo staff")
    top = game.players[0].deck[0]
    table.bot_deck.remove(top.card_id)
    table.bot_deck.insert(len(table.bot_deck) // 2, top.card_id)      # the table's order is not the engine's
    human_scheme(session, table, game, "The future of Ninjutsu")
    return top


# ---------------------------------------------------------------- the human plays it

@with_rig(*HUMAN_PLAYS)
def test_the_human_chooses_between_their_deck_and_the_bots_with_two_buttons(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "The future of Ninjutsu", "Bo staff")
    human_scheme(session, table, game, "The future of Ninjutsu")
    assert labels(session) == ["Tu mazo", "El mazo del bot"]
    assert session.effect_run.awaiting.extra["future"] == "deck"


@with_rig(*HUMAN_PLAYS)
def test_the_bots_engine_top_card_is_taken_out_of_its_physical_deck_by_card_id_and_shown(rig):
    session, table, game, fake, cfg = rig
    top = to_the_bots_deck(session, table, game)
    assert table.bot_deck[0] != top.card_id, "the table's order is not the engine's: only the CardID finds it"
    pings = len(table.point_pings)
    msgs = press(session, table, RIVAL)
    assert table.row == [top.card_id] and top.card_id not in table.bot_deck
    assert len(table.point_pings) == pings + 1
    assert said(msgs, f"la pongo boca arriba") or said(msgs, top.title)
    assert said(msgs, top.title)
    assert labels(session) == ["Dejar arriba", "Poner abajo"]
    assert session.peek["card"] == top.card_id and session.peek["taken"] is True
    assert table.opens == [True], "the card comes out of the deck inside the step's one combined script"
    assert game.players[0].deck[0] is top and game.drawn[1] == 0, "the game waits: nothing else happened"
    click(session, table, Event.END_ACTION)
    assert table.row == [top.card_id], "the effect is pending: another button does not move on"


@with_rig(*HUMAN_PLAYS)
def test_putting_it_at_the_bottom_moves_the_physical_card_and_the_engine_deck_and_goes_on(rig):
    session, table, game, fake, cfg = rig
    top = to_the_bots_deck(session, table, game)
    press(session, table, RIVAL)
    actions = game.actions_left
    msgs = press(session, table, BOTTOM)
    assert table.row == [] and table.bot_deck[-1] == top.card_id
    assert game.players[0].deck[-1] is top and game.players[0].deck[0] is not top
    assert session.peek is None and session.effect_run is None
    assert said(msgs, f"Pongo {top.title} debajo de mi mazo")
    assert table.human_deals == [1] and game.actions_left == actions + 1


@with_rig(*HUMAN_PLAYS)
def test_the_order_chosen_for_the_bots_deck_survives_rereads_and_a_save_and_ends_when_the_card_is_drawn(rig):
    session, table, game, fake, cfg = rig
    top = to_the_bots_deck(session, table, game)
    press(session, table, RIVAL)
    press(session, table, BOTTOM)
    session.read_bot_hand()
    assert game.players[0].deck[-1] is top, "the engine's deck is rebuilt from the table at every hand read"
    twin = twin_session(session, cfg, json.loads(json.dumps(session.to_dict())))
    assert twin.peek_pins == {"top": [], "bottom": [top.card_id]}
    table.bot_hand.append(top.card_id)                       # the bot drew it: nothing to remember any more
    session.read_bot_hand()
    assert session.peek_pins == {"top": [], "bottom": []} and top in game.players[0].hand


@with_rig(*HUMAN_PLAYS)
def test_a_card_left_on_top_stays_the_engines_top_card_after_a_reread(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "The future of Ninjutsu", "Bo staff")
    deck = game.players[0].deck
    last = deck.pop()
    deck.insert(0, last)                                      # the engine's top card is the last of the table's reading
    human_scheme(session, table, game, "The future of Ninjutsu")
    press(session, table, RIVAL)
    assert table.row == [last.card_id]
    press(session, table, LEAVE)
    session.read_bot_hand()
    assert game.players[0].deck[0] is last


@with_rig(*HUMAN_PLAYS)
def test_leaving_it_puts_the_physical_card_back_on_top(rig):
    session, table, game, fake, cfg = rig
    top = to_the_bots_deck(session, table, game)
    press(session, table, RIVAL)
    msgs = press(session, table, LEAVE)
    assert table.row == [] and table.bot_deck[0] == top.card_id
    assert game.players[0].deck[0] is top and session.peek is None
    assert said(msgs, f"Devuelvo {top.title} encima de mi mazo")
    assert table.human_deals == [1]


@with_rig(*HUMAN_PLAYS)
def test_the_own_deck_keeps_the_current_flow_and_touches_no_card_of_the_bot(rig):
    session, table, game, fake, cfg = rig
    to_the_bots_deck(session, table, game)
    deck = list(table.bot_deck)
    press(session, table, OWN)
    assert session.effect_run.awaiting.kind == "optional" and session.peek is None
    press(session, table, False)
    assert table.row == [] and table.bot_deck == deck and table.human_deals == [1]
    assert not [s for s in table.scripts if s.startswith("-- sparring:deck_card_to_spot")]


@with_rig(*HUMAN_PLAYS)
def test_a_table_that_does_not_give_the_card_still_lets_the_human_decide(rig):
    session, table, game, fake, cfg = rig
    table.bot_deck_fails = True
    top = to_the_bots_deck(session, table, game)
    msgs = press(session, table, RIVAL)
    assert said(msgs, "No he podido sacar") and said(msgs, top.title)
    assert session.peek["taken"] is False
    deck = list(table.bot_deck)
    press(session, table, BOTTOM)
    assert game.players[0].deck[-1] is top and table.bot_deck == deck and table.row == []
    assert table.human_deals == [1]


@pytest.mark.parametrize("answer", [LEAVE, BOTTOM])
@with_rig(*HUMAN_PLAYS)
def test_a_one_card_deck_goes_back_face_down_to_where_the_deck_was(rig, answer):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "The future of Ninjutsu", "Bo staff")
    top = game.players[0].deck[0]
    table.bot_deck = [top.card_id]
    human_scheme(session, table, game, "The future of Ninjutsu")
    press(session, table, RIVAL)
    assert table.row == [top.card_id] and table.bot_deck == [] and session.peek["home"] == [3.0, 1.0, 4.0]
    assert twin_session(session, cfg, json.loads(json.dumps(session.to_dict()))).peek == session.peek, "home and turn are saved"
    msgs = press(session, table, answer)
    assert table.row == [] and table.bot_deck == [top.card_id] and table.homes == [True]
    assert not said(msgs, "No he podido"), msgs
    assert table.human_deals == [1]


@with_rig(*HUMAN_PLAYS)
def test_when_the_table_refuses_the_card_the_chat_says_to_put_it_back_face_down(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "The future of Ninjutsu", "Bo staff")
    table.bot_deck = [game.players[0].deck[0].card_id]
    human_scheme(session, table, game, "The future of Ninjutsu")
    press(session, table, RIVAL)
    monkeypatch.setattr(DeckTable, "do_card_home", lambda self, s: {"placed": False})
    msgs = press(session, table, BOTTOM)
    assert said(msgs, "ponla tu, boca abajo, debajo de mi mazo"), msgs


@with_rig(*HUMAN_PLAYS)
def test_the_shown_card_survives_a_resume_and_is_put_back_after_it(rig):
    session, table, game, fake, cfg = rig
    top = to_the_bots_deck(session, table, game)
    press(session, table, RIVAL)
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    assert twin.peek == session.peek and twin.effect_run.awaiting.extra["top"] == top.card_id
    twin.messages = []
    twin.say = twin.say
    twin.handle(Event.CHOICE, {"i": BOTTOM + 1})
    assert table.bot_deck[-1] == top.card_id and table.row == [] and twin.peek is None


@with_rig(*HUMAN_PLAYS)
def test_an_undone_answer_leaves_the_card_in_the_row(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    top = to_the_bots_deck(session, table, game)
    press(session, table, RIVAL)
    from sparring.state import RuleError

    def refuse(run, value):
        raise RuleError("no")
    monkeypatch.setattr(session, "_answer_run", refuse)
    press(session, table, BOTTOM)
    assert table.row == [top.card_id] and session.peek["card"] == top.card_id and session.effect_run is not None


# ---------------------------------------------------------------- the bot plays it

def bot_plays(session, table, game, monkeypatch, deck, bottom):
    monkeypatch.setattr(EffectAI, "_future_deck", lambda self, g, req: RIVAL)
    monkeypatch.setattr(EffectAI, "_future_peek", lambda self, g, req: BOTTOM if bottom else LEAVE)
    table.human_deck = list(deck)
    human_hand(table, game, "Service Pistol", "Excalibur")
    card = next(c for c in game.players[0].hand if c.title == "The future of Ninjutsu")
    return bot_turn(session, table, [Act("scheme", card=card, fid="metalhead")])


def humans_cards(game, n=4):
    return [c.card_id for c in game.players[1].full_set][:n]


@with_rig(*BOT_PLAYS)
def test_the_bot_reads_the_humans_top_card_puts_it_at_the_bottom_and_never_names_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    deck = humans_cards(game)
    bot_plays(session, table, game, monkeypatch, deck, bottom=True)
    assert table.human_deck == deck[1:] + deck[:1]
    title = next(c.title for c in game.players[1].full_set if c.card_id == deck[0])
    chat = session.messages
    assert said(chat, "he mirado la carta de arriba de tu mazo y la he puesto debajo")
    assert not said(chat, f"{title}"), "the card is not public: only that the bot looked and what it did"
    assert game.players[0].known.top_of_deck == []


@with_rig(*BOT_PLAYS)
def test_the_bot_leaving_it_on_top_moves_nothing_and_remembers_it_until_the_human_draws(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    deck = humans_cards(game)
    bot_plays(session, table, game, monkeypatch, deck, bottom=False)
    assert table.human_deck == deck
    assert said(session.messages, "he mirado la carta de arriba de tu mazo y la he dejado arriba")
    assert game.players[0].known.top_of_deck == [deck[0]]
    game.draw(1, 1)
    assert game.players[0].known.top_of_deck == [], "the human drew: the bot forgets what it saw"


@with_rig(*BOT_PLAYS)
def test_the_bot_that_cannot_move_the_card_tells_the_human_to_do_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    deck = humans_cards(game)
    monkeypatch.setattr(DeckTable, "do_deck_top_to_bottom", lambda self, s: {"moved": False})
    bot_plays(session, table, game, monkeypatch, deck, bottom=True)
    assert table.human_deck == deck
    assert said(session.messages, "no he podido moverla: pon tu la carta de arriba de tu mazo debajo")


@with_rig(*BOT_PLAYS)
def test_an_unreadable_human_deck_falls_back_to_the_bots_own_deck(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_plays(session, table, game, monkeypatch, [], bottom=True)
    assert said(session.messages, "No he podido leer la carta de arriba de tu mazo")
    assert table.human_deck == [] and game.players[0].known.top_of_deck == []
    assert session.pending is None and session.effect_run is None


@with_rig(*BOT_PLAYS)
def test_the_human_deck_is_read_in_one_message_and_the_move_travels_inside_the_steps_composite(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_plays(session, table, game, monkeypatch, humans_cards(game), bottom=True)
    assert table.reads == [False], "the decision needs the card now: one read of its own"
    assert table.moves == [True], "the write rides the step's one combined script"
