"""Doctor Strange played BY THE HUMAN through the panel (FakeTTS, batch mode): DARK PACT's buttons and what the bot does on the
table for it, BLIND BOOST and the card No, Really, I'm a Doctor reveals (the cards the human lays on their discard pile), The Mists
of Munnopor in both directions, The Winds of Watoomb and Eye of Agamotto. The bot's side of the same cards is in
tests/test_doctor_strange_effects.py.

His deck is sheet 176 like Medusa's and the turtles': every id the table reports is resolved against the human's deck."""
from __future__ import annotations

import re

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_choice_infra import visible_choices
from test_d3_table_effects import build, card_ids, human_attack, human_hand, said, set_hand
from test_donatello_session import SPOTS, AsideTable
from test_e2_human_cards import human_scheme, put_adjacent


class StrangeTable(AsideTable):
    """The fake table where a card at a combat spot can go into a deck by GUID, the face-up cards of the human's combat spot
    are readable and a card can be laid on a discard pile by GUID (what the TTS scripts of the session do)."""

    def _source(self, s):
        gm = re.search(r'local card = \(?.*?getObjectFromGUID\("([gh])(\d+)"\)', s, re.S)
        cm = re.search(r"CardID == (\d+)", s)
        return (gm.group(1), int(gm.group(2))) if gm else ("c", int(cm.group(1)))

    def _deck_insert(self, s, kind):
        prefix, i = self._source(s)
        human = self._human_side(s)
        piles = [self.human_discard] if human else [self.bot_discard, self.bot_play]
        if human and prefix == "h" and i in {r["id"] for r in self.face_down}:
            self.face_down = [r for r in self.face_down if r["id"] != i]
        else:
            pile = next((p for p in piles if i in p), None)
            if pile is None:
                return {"placed": False}
            pile.remove(i)
        (self.human_deck if human else self.bot_deck).append(i)
        self.deck_moves.append((kind, [i]))
        return {"placed": True, "deck": "DECK1", "quantity": len(self.human_deck if human else self.bot_deck)}

    def do_read_cards_at(self, s):
        x = float(re.search(r"p\.x - (-?[\d.]+)\)", s).group(1))
        z = float(re.search(r"p\.z - (-?[\d.]+)\)", s).group(1))
        if (x, z) == tuple(self.human_card_spot):
            return list(self.face_down)
        return super().do_read_cards_at(s)

    human_card_spot = (-20.0, 4.0)
    hand_returns: list = []

    def do_card_to_discard(self, s):
        prefix, i = self._source(s)
        if prefix == "h" and i in {r["id"] for r in self.face_down}:
            self.face_down = [r for r in self.face_down if r["id"] != i]
            self.human_discard.append(i)
            return {"moved": [i], "count": 1, "zone": True}
        return {"moved": [], "count": 0, "zone": True}

    top_discard_fail = None              # "deck": no deck of theirs found; "short": one card fewer than asked
    top_discards: list = []

    def do_deck_top_to_discard(self, s):
        """The top cards of the human's deck (`human_deck`, the first is the top) face up onto their discard pile."""
        n = int(re.search(r"for _ = 1, (\d+) do", s).group(1))
        self.top_discards.append(n)
        if self.top_discard_fail == "deck":
            return {"moved": [], "count": 0, "deck": False, "zone": True}
        n = n - 1 if self.top_discard_fail == "short" else n
        moved = [self.human_deck.pop(0) for _ in range(min(n, len(self.human_deck)))]
        self.human_discard += moved
        return {"moved": moved, "count": len(moved), "deck": True, "zone": True}

    def do_shuffle_deck(self, s):
        self.shuffles += 1
        return {"shuffled": True, "quantity": len(self.bot_deck)}

    hand_return_fails = False

    def do_return_hand_to_deck(self, s):
        if 'Player["Red"]' not in s:                  # the bot's seat: the mulligan
            return super().do_return_hand_to_deck(s)
        if self.hand_return_fails:
            return {"returned": 0, "deck": False}
        n = self.human_count
        self.hand_returns.append(n)
        self.human_count, self.human_hand = 0, []
        self.human_deck_cards += n
        return {"returned": n, "deck": True}


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=StrangeTable, **SPOTS)
    table.human_card_spot = tuple(cfg.session_config().human_card_spot)
    table.human_deck = []
    table.hand_returns = []
    table.top_discards = []
    put_adjacent(game, table, cfg, game.hero(1).fid, game.hero(0).fid)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(*bot_hand, bot="hellboy", human="doctor-strange"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


def defends(session, game, monkeypatch, title):
    card = next((c for c in game.players[0].hand if c.title == title), None)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: card)
    return card


def no_defense(session, monkeypatch):
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)


def attack(session, table, game, title, attacker="strange", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def done(session, table, i=1):
    return click(session, table, Event.CHOICE, {"i": i})


def sid(game, title, n=0):
    return [c.card_id for c in game.players[1].full_set if c.title == title][n]


def pause_labels(session):
    lab = session.panel_labels()
    return [lab[i] for i in visible_choices(session)]


# ---------------------------------------------------------------- DARK PACT

@with_rig()
def test_dark_pact_is_offered_after_a_combat_in_which_strange_played_a_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint", "Bolts of Balthakk")
    msgs = attack(session, table, game, "Feint")
    run = session._paused()[2]
    assert run.label == "dark_pact" and run.awaiting.kind == "optional"
    assert said(msgs, "PACTO OSCURO: infliges 1 de dano a Doctor Strange") and pause_labels(session) == ["Si", "No"]
    assert game.fighters["strange"].hp == 14                                   # nothing is paid until they answer
    assert session.pending is None and session._paused() is not None


@with_rig()
def test_dark_pact_paid_moves_the_card_to_the_bottom_of_their_deck_by_guid_and_deals_the_draw(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint", "Bolts of Balthakk")
    feint = sid(game, "Feint")
    attack(session, table, game, "Feint")
    msgs = done(session, table, 1)                                              # Yes
    assert game.fighters["strange"].hp == 13 and table.dials[cfg.session_config().dials["strange"]]["value"] == 13
    assert said(msgs, "Pongo Feint de tu zona de combate en el fondo de tu mazo")
    assert table.deck_moves == [("bottom", [feint])] and table.human_deck == [feint] and table.face_down == []
    assert table.human_deals == [1] and said(msgs, "Te he dado 1 carta")        # the draw comes after the card went down
    assert [c.card_id for c in game.players[1].deck][-1] == feint and feint not in [c.card_id for c in game.players[1].discard]
    assert session._paused() is None
    assert len(game.players[1].hand) == table.human_count
    session.snap = None
    click(session, table, Event.HP, {"fighter": "hellboy", "delta": 0})        # the next reading flags nothing
    assert feint in [c.card_id for c in game.players[1].deck] and feint not in [c.card_id for c in game.players[1].discard]


@with_rig()
def test_dark_pact_declined_changes_nothing_and_the_card_is_discarded_by_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint", "Bolts of Balthakk")
    attack(session, table, game, "Feint")
    msgs = done(session, table, 2)                                              # No
    assert game.fighters["strange"].hp == 14 and table.deck_moves == [] and table.human_deals == []
    assert session._paused() is None and not said(msgs, "Pongo Feint")


@with_rig()
def test_dark_pact_falls_back_to_the_instruction_when_the_table_refuses(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint", "Bolts of Balthakk")
    table.face_down_stuck = True
    feint = sid(game, "Feint")
    original = table._deck_insert
    table._deck_insert = lambda s, kind: {"placed": False}
    attack(session, table, game, "Feint")
    msgs = done(session, table, 1)
    assert said(msgs, "No he podido poner Feint en el fondo de tu mazo: ponla tu") and table.deck_moves == []
    assert game.fighters["strange"].hp == 13 and table.human_deals == [1]       # the engine already paid and drew
    assert feint in [c.card_id for c in game.players[1].deck]


@with_rig()
def test_dark_pact_is_not_offered_when_strange_played_no_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Feint")
    session.game.turn = 0                                                       # the bot attacks Doctor Strange, who defends with nothing
    bot_hero = game.fighters["hellboy"]
    hand = [c for c in game.players[0].full_set if c.title == "Service Pistol"]
    table.bot_hand = [hand[0].card_id] + [c.card_id for c in game.players[0].full_set if c.title == "Excalibur"][:1]
    session.read_bot_hand()
    assert game.fx.parked == [] and session._paused() is None


@with_rig()
def test_dark_pact_is_not_offered_for_a_card_wong_played(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    put_adjacent(game, table, cfg, "wong", "hellboy")
    human_hand(table, game, "Steadfast Disciple")
    msgs = attack(session, table, game, "Steadfast Disciple", attacker="wong")
    assert session._paused() is None and game.fx.parked == []
    assert game.fighters["hellboy"].hp < game.fighters["hellboy"].max_hp


# ---------------------------------------------------------------- BLIND BOOST

def on_deck(table, game, *titles):
    """The physical top of the human's deck, in order (the first is the top)."""
    table.human_deck = [sid(game, title, titles[:k].count(title)) for k, title in enumerate(titles)]
    return list(table.human_deck)


def shrink_deck_at_the_plugin(monkeypatch, game, keep):
    """The engine's virtual deck of the human is rebuilt as the table is read: cut it to `keep` cards just as the plugin starts."""
    from sparring.effects import plugins_strange
    real = plugins_strange._flow

    def flow(run, name):
        del game.players[1].deck[keep:]
        return real(run, name)
    monkeypatch.setattr(plugins_strange, "_flow", flow)


@with_rig()
def test_bolts_ask_zero_or_one_up_front_with_two_buttons_and_nothing_moves_until_they_answer(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Bolts of Balthakk", "Feint")
    on_deck(table, game, "Master of Kamar-Taj")
    msgs = attack(session, table, game, "Bolts of Balthakk")
    req = session.effect_run.awaiting
    assert req.kind == "amount" and req.options == [0, 1] and req.extra["blind_count"] and req.extra["times"] == 1
    assert pause_labels(session) == ["0", "1"]
    assert said(msgs, "IMPULSO A CIEGAS: cuantas cartas descartas de arriba de tu mazo (hasta 1)")
    assert session.panel_view()[0].startswith("IMPULSO A CIEGAS")
    assert table.top_discards == [] and table.human_discard == [], "the cards are taken only after the declaration"


@with_rig()
def test_declaring_one_moves_the_top_card_to_the_pile_face_up_and_adds_its_boost_value(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Bolts of Balthakk", "Feint")
    top, second = on_deck(table, game, "Master of Kamar-Taj", "Feint")           # boost 2
    attack(session, table, game, "Bolts of Balthakk")
    deck_before = len(game.players[1].deck)
    msgs = done(session, table, 2)                                                # "1"
    assert table.top_discards == [1] and table.human_discard == [top] and table.human_deck == [second]
    assert said(msgs, "descarto las 1 de arriba de tu mazo, boca arriba: Master of Kamar-Taj. +2 al valor")
    assert said(msgs, "Doctor Strange ataca con Bolts of Balthakk (2)") and said(msgs, "total 4")
    assert top in [c.card_id for c in game.players[1].discard] and len(game.players[1].deck) == deck_before - 1
    assert len(game.players[1].hand) == table.human_count                      # the hand did not change, the deck did
    assert not said(msgs, "No he podido mover") and not said(session.messages, "no coincide")
    assert session._paused() is not None and session._paused()[2].label == "dark_pact"


@with_rig()
def test_declaring_zero_takes_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Bolts of Balthakk", "Feint")
    on_deck(table, game, "Master of Kamar-Taj")
    attack(session, table, game, "Bolts of Balthakk")
    msgs = done(session, table, 1)                                                # "0"
    assert table.top_discards == [] and table.human_discard == []
    assert said(msgs, "no potencias") and said(msgs, "total 2") and session._paused()[2].label == "dark_pact"


@with_rig()
def test_seven_suns_offer_zero_one_or_two_and_two_cards_move_in_one_write(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Seven Suns of Cinnibus", "Feint")
    first, second = on_deck(table, game, "Master of Kamar-Taj", "Feint")         # boosts 2 and 1
    attack(session, table, game, "Seven Suns of Cinnibus")
    assert session.effect_run.awaiting.options == [0, 1, 2] and pause_labels(session) == ["0", "1", "2"]
    msgs = done(session, table, 3)                                                # "2"
    assert table.top_discards == [2] and table.human_discard == [first, second]
    assert said(msgs, "Master of Kamar-Taj, Feint") and said(msgs, "+3 al valor") and said(msgs, "total 6")


@with_rig()
def test_seven_suns_over_seven_after_the_declared_boosts_count_for_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Seven Suns of Cinnibus", "Feint")
    on_deck(table, game, "Bolts of Balthakk", "Bolts of Balthakk")              # boost 3 + 3: 3 + 6 = 9 > 7
    attack(session, table, game, "Seven Suns of Cinnibus")
    hp = game.fighters["hellboy"].hp
    msgs = done(session, table, 3)
    assert said(msgs, "total 0") and game.fighters["hellboy"].hp == hp


@with_rig()
def test_the_buttons_only_appear_for_a_card_that_allows_a_blind_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint", "Bolts of Balthakk")
    on_deck(table, game, "Master of Kamar-Taj")
    attack(session, table, game, "Feint")
    assert session._paused()[2].label == "dark_pact" and pause_labels(session) == ["Si", "No"]
    assert table.top_discards == []


@with_rig()
def test_an_empty_deck_asks_nothing_and_boosts_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Bolts of Balthakk", "Feint")
    shrink_deck_at_the_plugin(monkeypatch, game, 0)
    attack(session, table, game, "Bolts of Balthakk")
    assert session._paused()[2].label == "dark_pact" and table.top_discards == []


@with_rig()
def test_a_deck_with_one_card_left_gives_that_one_when_two_were_declared(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Seven Suns of Cinnibus", "Feint")
    (only,) = on_deck(table, game, "Feint")
    shrink_deck_at_the_plugin(monkeypatch, game, 1)
    attack(session, table, game, "Seven Suns of Cinnibus")
    msgs = done(session, table, 3)
    assert table.top_discards == [1] and table.human_discard == [only] and said(msgs, "total 4")


@with_rig()
def test_when_the_table_refuses_the_chat_asks_them_to_lay_the_top_cards_and_the_bot_reads_them(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Seven Suns of Cinnibus", "Feint")
    first, _ = on_deck(table, game, "Master of Kamar-Taj", "Feint")
    table.top_discard_fail = "deck"
    attack(session, table, game, "Seven Suns of Cinnibus")
    msgs = done(session, table, 3)                                                # "2"
    req = session._paused()[2].awaiting
    assert said(msgs, "No he podido mover las cartas de arriba de tu mazo para Seven Suns of Cinnibus")
    assert req.kind == "cards" and req.extra["pile_mode"] == "blind" and req.min == req.max == 2
    assert said(msgs, "IMPULSO A CIEGAS x2") and session.panel_view()[0].startswith("Pon en tu descarte las 2 cartas")
    table.human_discard += [first]
    msgs = done(session, table)
    assert said(msgs, "has declarado 2 pero solo veo 1") and session._paused()[2].awaiting.kind == "cards"
    table.human_discard += [sid(game, "Feint")]
    msgs = done(session, table)
    assert said(msgs, "cuento Feint, Master of Kamar-Taj") and said(msgs, "total 6")
    assert session._paused()[2].label == "dark_pact"


@with_rig()
def test_a_table_that_moves_fewer_cards_than_declared_is_a_failure_and_the_moved_one_still_counts_by_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Seven Suns of Cinnibus", "Feint")
    first, _ = on_deck(table, game, "Master of Kamar-Taj", "Feint")
    table.top_discard_fail = "short"
    attack(session, table, game, "Seven Suns of Cinnibus")
    msgs = done(session, table, 3)
    assert table.human_discard == [first] and said(msgs, "No he podido mover") and session._paused()[2].awaiting.kind == "cards"
    table.human_discard += [sid(game, "Feint")]
    assert said(done(session, table), "cuento Feint, Master of Kamar-Taj")


@with_rig()
def test_the_declaration_waiting_at_the_panel_survives_a_save_and_a_restore(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Seven Suns of Cinnibus", "Feint")
    first, _ = on_deck(table, game, "Master of Kamar-Taj", "Feint")
    attack(session, table, game, "Seven Suns of Cinnibus")
    session._restore(session.to_dict())                          # what --resume does
    game = session.game
    req = session._paused()[2].awaiting
    assert req.kind == "amount" and req.options == [0, 1, 2] and pause_labels(session) == ["0", "1", "2"]
    assert table.top_discards == []
    msgs = done(session, table, 2)                               # "1" after the restore
    assert table.human_discard == [first] and said(msgs, "total 5")


@with_rig()
def test_the_cards_the_bot_read_are_saved_with_the_run_so_a_rerun_of_the_plugin_does_not_ask_again(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Bolts of Balthakk", "Feint")
    first, _ = on_deck(table, game, "Master of Kamar-Taj", "Feint")
    attack(session, table, game, "Bolts of Balthakk")
    run = session._paused()[2]
    from sparring.session_blind import declared
    declared(session, run, [1])
    assert run.flags["blind_cards"] == {run.awaiting.key.rsplit(":", 1)[0]: [first]}
    assert run.to_dict()["flags"]["blind_cards"]


# ---------------------------------------------------------------- No, Really, I'm a Doctor

@with_rig()
def test_no_really_im_a_doctor_reads_the_revealed_card_from_the_pile_and_puts_it_on_top_of_the_deck(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    game.fighters["strange"].hp = 8
    human_hand(table, game, "No, Really, I'm a Doctor", "Bolts of Balthakk", "Feint")
    msgs = human_scheme(session, table, game, "No, Really, I'm a Doctor")
    req = session.effect_run.awaiting
    assert req.kind == "cards" and req.extra["pile_mode"] == "reveal" and req.min == req.max == 1
    assert said(msgs, "pon en tu descarte la carta de tu mano que revelas")
    bolts = sid(game, "Bolts of Balthakk")
    msgs = done(session, table)                                                  # nothing on the pile yet
    assert said(msgs, "no veo ninguna carta nueva") and session.effect_run is not None
    table.human_discard.append(bolts)
    table.human_count -= 1
    msgs = done(session, table)
    assert said(msgs, "reveleas Bolts of Balthakk (POTENCIA 3)")
    assert said(msgs, "Pongo Bolts of Balthakk de tu descarte encima de tu mazo")
    assert table.deck_moves == [("top", [bolts])] and table.human_deck == [bolts] and bolts not in table.human_discard
    assert game.players[1].deck[0].card_id == bolts
    assert game.players[0].known.top_of_deck == [bolts]                           # the bot saw it: it is the top card of their deck
    assert game.fighters["strange"].hp == 11 and session.effect_run is None       # Wong is not beside him: no choice to make
    assert len(game.players[1].hand) == table.human_count


@with_rig()
def test_no_really_the_heal_goes_to_strange_or_to_wong_beside_him_at_the_players_choice(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "wong", "strange")
    game.fighters["strange"].hp, game.fighters["wong"].hp = 8, 2
    human_hand(table, game, "No, Really, I'm a Doctor", "Bolts of Balthakk")
    human_scheme(session, table, game, "No, Really, I'm a Doctor")
    table.human_discard.append(sid(game, "Bolts of Balthakk"))
    table.human_count -= 1
    done(session, table)
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and sorted(req.options) == ["strange", "wong"]
    click(session, table, Event.CHOICE, {"i": req.options.index("wong") + 1})
    assert game.fighters["wong"].hp == 5 and game.fighters["strange"].hp == 8 and session.effect_run is None


# ---------------------------------------------------------------- Eye of Agamotto

def tags_of(table):
    return [tag for batch in table.msglog for tag in batch]


@with_rig()
def test_eye_of_agamotto_has_the_bot_shuffle_the_hand_into_the_deck_and_deal_five_after(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Eye of Agamotto", "Bolts of Balthakk", "Feint", "Feint")
    table.human_count = 4
    msgs = human_scheme(session, table, game, "Eye of Agamotto")
    assert said(msgs, "Barajo tu mano en tu mazo")
    assert table.hand_returns == [3] and table.human_deals == [5]                 # the hand went back first, then the 5 cards came
    tags = tags_of(table)
    assert tags.index("return_hand_to_deck") < tags.index("shuffle_deck") < len(tags) - 1 - tags[::-1].index("deal_cards")
    assert game.actions_left == 2 and len(game.players[1].hand) == 5 == table.human_count
    assert not any(c.title == "Eye of Agamotto" for c in game.players[1].hand)


@with_rig()
def test_eye_of_agamotto_asks_the_human_to_do_it_when_the_table_refuses(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Eye of Agamotto", "Feint")
    table.hand_return_fails = table.human_deal_fails = True
    msgs = human_scheme(session, table, game, "Eye of Agamotto")
    assert said(msgs, "No he podido meter tu mano en tu mazo") and table.hand_returns == []


# ---------------------------------------------------------------- The Mists of Munnopor

MISTS = "The Mists of Munnopor"


def bot_strange_defends(session, game, monkeypatch):
    card = next(c for c in game.players[0].hand if c.title == MISTS)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: card)
    no_pact(session, monkeypatch)


def no_pact(session, monkeypatch):
    """The bot's DARK PACT is a decision of its own; these tests are about the card."""
    real = session.ai.choose_effect
    monkeypatch.setattr(session.ai, "choose_effect", lambda g, req: [False] if "pact" in req.extra else real(g, req))


def hid(game, title, n=0):
    return [c.card_id for c in game.players[1].full_set if c.title == title][n]


@with_rig(MISTS, "Feint", bot="doctor-strange", human="hellboy")
def test_mists_against_the_humans_attack_asks_them_to_reveal_and_play_the_card_they_find(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_strange_defends(session, game, monkeypatch)
    human_hand(table, game, "Right Hand Of Doom", "Service Pistol")
    old, new = hid(game, "Right Hand Of Doom"), hid(game, "Excalibur")
    msgs = attack(session, table, game, "Right Hand Of Doom", attacker="hellboy", target="strange")
    req = session.effect_run.awaiting
    assert req.kind == "cards" and req.extra["pile_mode"] == "play" and req.min == 0 and req.max == 1
    assert said(msgs, "The Mists of Munnopor: tu carta de hellboy se descarta") or said(msgs, "tu carta de hellboy se descarta")
    assert session.panel_view()[0].startswith("Pon la carta que encuentres en tu zona de combate")
    table.face_down = [{"id": old, "guid": f"h{old}"}, {"id": new, "guid": f"h{new}"}]       # Excalibur is the card the reveal found
    hp = game.fighters["strange"].hp
    msgs = done(session, table)
    assert said(msgs, "The Mists of Munnopor: juegas Excalibur en su lugar")
    assert said(msgs, "Hellboy ataca con Excalibur (6)")
    assert old in table.human_discard and [r["id"] for r in table.face_down] == [new]          # the bot moved the discarded card
    assert old in [c.card_id for c in game.players[1].discard]
    assert game.fighters["strange"].hp == hp - (6 - 2) and session.combat_guids == {new: f"h{new}"}
    assert len(game.players[1].hand) == table.human_count


@with_rig(MISTS, "Feint", bot="doctor-strange", human="hellboy")
def test_mists_with_no_playable_card_left_the_attack_has_no_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_strange_defends(session, game, monkeypatch)
    human_hand(table, game, "Right Hand Of Doom")
    old = hid(game, "Right Hand Of Doom")
    attack(session, table, game, "Right Hand Of Doom", attacker="hellboy", target="strange")
    hp = game.fighters["strange"].hp
    msgs = done(session, table)
    assert said(msgs, "no hay ninguna carta jugable en tu mazo") and old in table.human_discard
    assert game.fighters["strange"].hp == hp and "Hellboy ataca con Right Hand Of Doom (0)" in " ".join(msgs)


@with_rig(MISTS, "Feint", bot="doctor-strange", human="hellboy")
def test_mists_refuses_a_card_the_attacker_cannot_play_and_waits(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_strange_defends(session, game, monkeypatch)
    human_hand(table, game, "Right Hand Of Doom", "On Earth As It Is In Hell")
    old, bad = hid(game, "Right Hand Of Doom"), hid(game, "On Earth As It Is In Hell")
    attack(session, table, game, "Right Hand Of Doom", attacker="hellboy", target="strange")
    table.face_down = [{"id": old, "guid": f"h{old}"}, {"id": bad, "guid": f"h{bad}"}]
    msgs = done(session, table)
    assert said(msgs, "On Earth As It Is In Hell (defensa) no es una carta de ataque o versatil") and session.effect_run is not None


@with_rig("Excalibur", "Service Pistol")
def test_mists_played_by_the_human_replaces_the_bots_attack_with_a_card_from_its_deck(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    from sparring.ai_medusa import Act
    from test_d3_table_effects import bot_turn
    human_hand(table, game, MISTS, "Feint")
    top = next(c for c in game.players[0].deck if c.title == "Right Hand Of Doom")
    game.players[0].deck.remove(top)
    game.players[0].deck.insert(0, top)
    excalibur = next(c for c in game.players[0].hand if c.title == "Excalibur")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="strange", card=excalibur)])
    mists = hid(game, MISTS)
    table.face_down = [{"id": mists, "guid": f"h{mists}"}]
    table.human_hand.remove(mists)
    table.human_count -= 1
    hp = game.fighters["strange"].hp
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Revela Right Hand Of Doom de su mazo y juega Right Hand Of Doom")
    assert said(msgs, "Hellboy ataca con Right Hand Of Doom (4)")
    assert game.fighters["strange"].hp == hp - (4 - 2) and session._paused()[2].label == "dark_pact"
    assert excalibur in game.players[0].discard and top in game.players[0].discard
    heads = [h for ops in table.msglog for h in ops]
    assert "place_card_face_up" not in heads and "return_card_to_hand" not in heads       # Sleight Of Hand's swap, not the Mists'
    assert not said(msgs, "la recoge en su mano")


# ---------------------------------------------------------------- The Winds of Watoomb

@with_rig()
def test_winds_played_by_the_human_the_bot_places_strange_and_the_human_places_the_bots_fighter(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "The Winds of Watoomb", "Feint")
    starts = sorted(game.board.starts.values())
    msgs = attack(session, table, game, "The Winds of Watoomb")
    paused = session._paused()
    if paused is not None and paused[2].label == "after" and paused[2].awaiting.kind == "space":
        req = paused[2].awaiting
        assert req.extra["fighter"] == "hellboy" and set(req.options) <= set(starts)
        table.positions[cfg.nicknames["hellboy"]] = req.options[0]
        msgs = done(session, table)
    assert game.fighters["strange"].pos in starts and game.fighters["hellboy"].pos in starts
    assert game.fighters["strange"].pos != game.fighters["hellboy"].pos
    assert any(name == cfg.nicknames["strange"] and space in starts for name, space in table.moves)    # the bot moved Strange by GUID
    assert said(msgs, "baraja tu mazo")                                                   # "all players shuffle their decks": yours is by hand


@with_rig("The Winds of Watoomb", "Feint", bot="doctor-strange", human="hellboy")
def test_winds_played_by_the_bot_the_human_places_strange_by_hand_and_the_bot_places_the_humans_fighter(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    from sparring.ai_medusa import Act
    from test_d3_table_effects import bot_turn
    human_hand(table, game, "Service Pistol", "B.P.R.D. Training")
    winds = next(c for c in game.players[0].hand if c.title == "The Winds of Watoomb")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)
    bot_turn(session, table, [Act("attack", fid="strange", target="hellboy", card=winds)])
    table.face_down = []
    click(session, table, Event.REVEAL)
    paused = session._paused()
    starts = sorted(game.board.starts.values())
    assert paused is not None and paused[2].awaiting.kind == "space" and paused[2].awaiting.extra["fighter"] == "strange"
    assert set(paused[2].awaiting.options) <= set(starts)
    table.positions[cfg.nicknames["strange"]] = paused[2].awaiting.options[0]
    msgs = done(session, table)
    assert game.fighters["strange"].pos in starts and game.fighters["hellboy"].pos in starts
    assert game.fighters["strange"].pos != game.fighters["hellboy"].pos
    assert any(name == cfg.nicknames["hellboy"] and space in starts for name, space in table.moves)   # the bot moved the human's piece
    assert table.shuffles >= 1


# ---------------------------------------------------------------- DARK PACT of the bot's Doctor Strange

@with_rig("Feint", "Bolts of Balthakk", "The Rings of Raggadorr", bot="doctor-strange", human="hellboy")
def test_the_bots_dark_pact_puts_its_played_card_at_the_bottom_of_its_deck_on_the_table(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    from sparring.ai_medusa import Act
    from test_d3_table_effects import bot_turn
    human_hand(table, game, "Service Pistol", "B.P.R.D. Training")
    feint = next(c for c in game.players[0].hand if c.title == "Feint")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)
    seen = []
    real = session.ai.choose_effect
    monkeypatch.setattr(session.ai, "choose_effect", lambda g, req: (seen.append(req) or [True]) if "pact" in req.extra else real(g, req))
    bot_turn(session, table, [Act("attack", fid="strange", target="hellboy", card=feint)])
    table.face_down = []
    click(session, table, Event.REVEAL)
    assert seen and game.fighters["strange"].hp == 13
    assert feint in game.players[0].deck and feint not in game.players[0].discard
    assert table.deck_moves[-1] == ("bottom", [feint.card_id]) and table.bot_deck[-1] == feint.card_id
    assert feint.card_id not in table.bot_discard and feint.card_id not in table.bot_play


# ---------------------------------------------------------------- resuming

@with_rig()
def test_dark_pact_waiting_at_the_panel_survives_a_save_and_a_restore(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint", "Bolts of Balthakk")
    feint = sid(game, "Feint")
    attack(session, table, game, "Feint")
    saved = session.to_dict()
    session._restore(saved)                                   # what --resume does: the game, the parked run and the GUIDs come back
    game = session.game
    assert session._paused() is not None and session._paused()[2].label == "dark_pact"
    assert session.combat_guids == {feint: f"h{feint}"}
    done(session, table, 1)
    assert game.fighters["strange"].hp == 13 and table.deck_moves == [("bottom", [feint])] and table.human_deals == [1]


@with_rig()
def test_while_dark_pact_waits_the_other_buttons_are_refused(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint", "Bolts of Balthakk")
    attack(session, table, game, "Feint")
    turn = game.turn
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "Hay una eleccion de efecto pendiente") and game.turn == turn and session._paused() is not None
    assert len(visible_choices(session)) == 2                                                  # only Yes / No are shown


@with_rig()
def test_dark_pact_that_kills_strange_ends_the_game_and_moves_and_deals_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    game.fighters["strange"].hp = 1
    table.dials[cfg.session_config().dials["strange"]]["value"] = session.dials_written[cfg.session_config().dials["strange"]] = 1
    human_hand(table, game, "Feint", "Bolts of Balthakk")
    attack(session, table, game, "Feint")
    assert session._paused()[2].label == "dark_pact"              # still offered at 1 hit point: the rules allow it
    msgs = done(session, table, 1)
    assert game.winner == 0 and not game.fighters["strange"].alive
    assert said(msgs, "Fin de la partida") or said(msgs, "Game over") or any("gan" in m.lower() for m in msgs)
    assert table.deck_moves == [] and table.human_deals == [] and not said(msgs, "Resuelve los efectos de despues")


@with_rig()
def test_a_trigger_parked_after_a_combat_on_another_event_keeps_the_closing_line(rig, monkeypatch):
    """The hold-back of "Resolve the effects after the combat" is only for after_combat triggers (michelangelo / raphael parked
    runs on after_attack or combat_lost say it at once, as before)."""
    from sparring.effects import events
    real = events.Ctx
    monkeypatch.setattr(events, "Ctx", lambda **kw: real(**{**kw, "moment": "after_attack"}))
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Feint")
    msgs = attack(session, table, game, "Feint")
    assert session._paused() is not None and session._paused()[2].ctx.moment == "after_attack"
    assert said(msgs, "Resuelve los efectos de despues del combate")
