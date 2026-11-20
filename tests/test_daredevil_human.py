"""Daredevil played BY THE HUMAN through the panel (FakeTTS, batch mode): the special ability's BLIND BOOST declaration (only with
2 or fewer cards in hand, never greyed buttons otherwise), the order choice, Take A Knee's one button and the card the bot moves,
Devil of Hell's Kitchen's shuffle back, Through Adversity by hand, Breather, and the saved choices after a restore. The bot's side
of the same cards is in tests/test_daredevil_effects.py.

His deck is sheet 176 like Medusa's and the turtles': every id the table reports is resolved against the human's deck."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build, human_attack, human_hand, said
from test_donatello_session import SPOTS
from test_doctor_strange_human import StrangeTable, attack, done, no_defense, on_deck, pause_labels, sid
from test_e2_human_cards import human_scheme, labels, press, put_adjacent

DEVIL = "Devil of Hell's Kitchen"


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


def with_rig(*bot_hand, bot="hellboy", human="daredevil"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


def hit(session, table, game, title, hand):
    """The human holds `hand` (the card they play included) and attacks Hellboy with `title`; the bot defends with nothing."""
    human_hand(table, game, *hand)
    return attack(session, table, game, title, attacker="daredevil", target="hellboy")


# ---------------------------------------------------------------- the special ability

@with_rig()
def test_the_ability_offers_zero_or_one_blind_boost_when_two_or_fewer_cards_stay_in_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    on_deck(table, game, "Breather")
    msgs = hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather"])
    req = session.effect_run.awaiting
    assert req.kind == "amount" and req.options == [0, 1] and req.extra["blind_count"] and req.extra["ability"]
    assert pause_labels(session) == ["0", "1"] and said(msgs, "IMPULSO A CIEGAS")
    assert table.top_discards == [], "nothing moves until they declare"


@with_rig()
def test_declaring_one_moves_the_top_card_to_the_pile_and_adds_its_boost_naming_the_ability(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, second = on_deck(table, game, DEVIL, "Feint")                               # boost 3
    hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather"])
    hp = game.fighters["hellboy"].hp
    msgs = done(session, table, 2)                                                    # "1"
    assert table.top_discards == [1] and table.human_discard == [top] and table.human_deck == [second]
    assert said(msgs, "la habilidad especial de Daredevil: descarto las 1 de arriba de tu mazo, boca arriba: Devil of Hell's Kitchen. +3 al valor")
    assert game.fighters["hellboy"].hp == hp - 6 or hp - game.fighters["hellboy"].hp >= 6      # 3 + 3 against no defense
    assert len(game.players[1].hand) == table.human_count


@with_rig()
def test_declaring_zero_takes_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    on_deck(table, game, DEVIL)
    hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather"])
    msgs = done(session, table, 1)                                                    # "0"
    assert table.top_discards == [] and said(msgs, "la habilidad especial de Daredevil: no potencias")


@with_rig()
def test_with_three_cards_left_in_hand_the_ability_asks_nothing_and_no_button_is_shown(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    on_deck(table, game, DEVIL)
    hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather", "Son Of A Boxer"])
    assert session.effect_run is None or session.effect_run.awaiting is None
    assert table.top_discards == [] and visible_none(session)


def visible_none(session):
    from test_choice_infra import visible_choices
    return visible_choices(session) == []


@with_rig()
def test_a_card_with_its_own_during_effect_asks_the_ability_first_then_the_card_with_no_order_choice(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    first, second = on_deck(table, game, "Breather", "Feint")
    hit(session, table, game, "Man Without Fear", ["Man Without Fear", "Feint", "Breather"])
    req = session.effect_run.awaiting
    assert req.kind == "amount" and req.extra["blind_count"] and req.extra["ability"] is True
    done(session, table, 2)                                                           # 1 from the ability
    req = session.effect_run.awaiting
    assert req.extra["blind_count"] and not req.extra.get("ability")
    done(session, table, 2)                                                           # 1 from the card
    assert table.human_discard == [first, second] and table.top_discards == [1, 1]


def lag_virtual_hand(session, game, keep):
    """The engine's virtual hand falls behind the table's after the last read (the live 18/11 case): it holds `keep` cards."""
    real = session.sync_human

    def lagging():
        real()
        st = game.players[1]
        while len(st.hand) > keep:
            st.deck.append(st.hand.pop())
    session.sync_human = lagging


@with_rig()
def test_the_ability_asks_nothing_when_the_table_hand_is_bigger_than_the_engines_virtual_one(rig, monkeypatch):
    """Live 18/11 (Man Without Fear): the human held more than 2 cards but the virtual hand lagged behind, so the offer came anyway."""
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    on_deck(table, game, "Breather")
    human_hand(table, game, "Grappling Hook", "Feint", "Breather")
    table.human_count = 5                                                            # the table: 4 stay in hand once the card is played
    lag_virtual_hand(session, game, 1)
    attack(session, table, game, "Grappling Hook", attacker="daredevil", target="hellboy")
    assert session.effect_run is None or session.effect_run.awaiting is None
    assert table.top_discards == [] and visible_none(session)


@with_rig()
def test_man_without_fear_with_a_full_hand_offers_only_its_own_blind_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    on_deck(table, game, "Breather", "Feint")
    human_hand(table, game, "Man Without Fear", "Feint", "Breather")
    table.human_count = 5
    lag_virtual_hand(session, game, 1)
    attack(session, table, game, "Man Without Fear", attacker="daredevil", target="hellboy")
    req = session.effect_run.awaiting
    assert req.extra["blind_count"] and not req.extra.get("ability"), "only the card's own blind boost"
    done(session, table, 2)
    assert table.top_discards == [1] and session.effect_run is None


@with_rig()
def test_a_blind_boosted_card_is_never_owed_from_the_hand(rig, monkeypatch):
    """Live 18/11: the bot moved the top card to the pile, yet the projection asked the human to put it there from their hand."""
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, _ = on_deck(table, game, "Feint", "Breather")
    hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather"])
    msgs = done(session, table, 2)
    assert table.human_discard == [top]
    assert session.pending_discard is None and not said(msgs, "de tu mano en tu descarte")
    assert not any("descartas" in m and "mazo a tu mano" in m for m in msgs)


@with_rig()
def test_two_blind_boosts_of_one_combat_owe_nothing_from_the_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    on_deck(table, game, "Breather", "Feint")
    hit(session, table, game, "Man Without Fear", ["Man Without Fear", "Feint", "Breather"])
    done(session, table, 2)
    msgs = done(session, table, 2)
    assert table.top_discards == [1, 1]
    assert session.pending_discard is None and not said(msgs, "de tu mano en tu descarte")


@with_rig()
def test_a_named_debt_whose_card_was_shuffled_into_the_deck_is_forgiven_and_said(rig, monkeypatch):
    """Devil of Hell's Kitchen shuffles the top of the pile into the deck: a card still owed by name there cannot be paid."""
    session, table, game, fake, cfg = rig
    st = game.players[1]
    gone = st.deck[0]
    session.pending_discard = {"n": 0, "baseline": len(st.discard), "kind": "cards", "cards": [gone.card_id]}
    session.messages.clear()
    assert session._discard_done() is True
    assert said(session.messages, f"Dejo de esperar {gone.title} en tu descarte")


@with_rig()
def test_a_named_debt_whose_card_went_back_to_the_hand_is_not_forgiven(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    st = game.players[1]
    kept = st.hand[0]
    session.pending_discard = {"n": 0, "baseline": len(st.discard), "kind": "cards", "cards": [kept.card_id]}
    assert session._discard_done() is False


@with_rig()
def test_when_the_table_refuses_and_they_lay_the_blind_card_by_hand_it_is_not_owed_from_the_hand_either(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, _ = on_deck(table, game, "Feint", "Breather")
    table.top_discard_fail = "deck"
    hit(session, table, game, "Grappling Hook", ["Grappling Hook", "Feint", "Breather"])
    msgs = done(session, table, 2)
    assert session.effect_run.awaiting.extra["pile_mode"] == "blind"
    table.human_discard += [top]
    msgs = done(session, table)
    assert session.pending_discard is None and not said(msgs, "de tu mano en tu descarte")


def hiss_sequence(rig, monkeypatch, discard_before_end: bool):
    """Daredevil attacks with the Devil, blind boosts the top Feint, Medusa defends with Hiss and Slither, the human discards one
    real hand card for it and the Devil's AFTER shuffles the pile back: what the chat says, End action by End action."""
    session, table, game, fake, cfg = rig
    hiss = next(c for c in game.players[0].hand if c.title == "Hiss and Slither")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: hiss)
    on_deck(table, game, "Feint", "Breather")
    human_hand(table, game, DEVIL, "Son Of A Boxer", "Grappling Hook")
    attack(session, table, game, DEVIL, attacker="daredevil", target="medusa")
    out = done(session, table, 2)                                                    # blind boost 1: the top Feint
    feint, boxer = sid(game, "Feint"), sid(game, "Son Of A Boxer")
    assert table.human_discard == [feint] and session.pending_discard["n"] == 1 and not session.pending_discard.get("cards")

    def discard_for_hiss():
        table.human_discard.append(boxer)
        table.human_hand.remove(boxer)
        table.human_count -= 1
    if discard_before_end:
        discard_for_hiss()
    out += click(session, table, Event.END_ACTION)                                   # the Devil's AFTER: the bot shuffles the pile cards
    assert feint not in table.human_discard, "the bot moved the Feint back into the deck"
    if not discard_before_end:
        discard_for_hiss()
    out += click(session, table, Event.END_ACTION)                                   # the first one closed the combat's AFTER; this one checks the debt
    assert not said(out, "de tu mano en tu descarte") and not said(out, "Aun no veo")
    assert session.pending_discard is None, (out, session.pending_discard)


@with_rig("Hiss and Slither", bot="medusa")
def test_live_sequence_devil_blind_boost_hiss_then_shuffle_never_blocks_end_action(rig, monkeypatch):
    """Live 18/11 (16:13-16:15): the blind-boosted Feint was owed from the hand, the Devil's AFTER shuffled it away, End action blocked."""
    hiss_sequence(rig, monkeypatch, discard_before_end=False)


@with_rig("Hiss and Slither", bot="medusa")
def test_live_sequence_with_the_hiss_discard_already_on_the_pile_at_the_first_end_action(rig, monkeypatch):
    hiss_sequence(rig, monkeypatch, discard_before_end=True)


@with_rig()
def test_the_deck_discard_marks_are_cleared_on_every_button_even_one_refused_early(rig):
    session, table, game, fake, cfg = rig
    game.fx.deck_discarded.update({17604, 17605})
    click(session, table, Event.STOP_REVEAL)                                         # an early return of `_handle`
    assert game.fx.deck_discarded == set()
    game.fx.deck_discarded.add(17604)
    click(session, table, Event.REVEAL)                                              # "no pending combat": a refused button
    assert game.fx.deck_discarded == set()


@with_rig()
def test_the_table_hand_counts_the_draws_still_owed_after_a_pending_discard(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Feint", "Breather", "Grappling Hook")
    session.pending_discard = {"n": 1, "baseline": 0, "kind": "cards", "hand": True}
    game.drawn[1] = session.human_dealt + 2
    assert session._table_hand_size(1) == 3 + 2


# ---------------------------------------------------------------- Take A Knee

@with_rig()
def test_take_a_knee_shows_one_button_then_the_bot_discards_the_top_card_and_daredevil_recovers_its_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, _ = on_deck(table, game, DEVIL, "Feint")                                    # boost 3
    game.fighters["daredevil"].hp = 10
    hit(session, table, game, "Take A Knee", ["Take A Knee", "Feint", "Breather", "Son Of A Boxer"])
    req = session.effect_run.awaiting
    assert req.kind == "amount" and req.options == [1] and req.extra["top_discard"] and pause_labels(session) == ["1"]
    assert table.top_discards == [] and game.fighters["daredevil"].hp == 10
    msgs = done(session, table, 1)
    assert table.top_discards == [1] and table.human_discard == [top]
    assert said(msgs, "Take A Knee: descarto la carta de arriba de tu mazo, boca arriba: Devil of Hell's Kitchen")
    assert game.fighters["daredevil"].hp == 13 and table.dials[cfg.session_config().dials["daredevil"]]["value"] == 13
    assert session.effect_run is None and len(game.players[1].hand) == table.human_count


@with_rig()
def test_take_a_knee_with_an_empty_deck_asks_and_moves_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    from sparring.effects.ops_core import PLUGINS
    real = PLUGINS["daredevil:take_a_knee"]

    def empty_first(run, g, spec):                         # the engine's copy of their deck is rebuilt as the table is read
        g.players[1].deck.clear()
        return real(run, g, spec)
    monkeypatch.setitem(PLUGINS, "daredevil:take_a_knee", empty_first)
    hit(session, table, game, "Take A Knee", ["Take A Knee", "Feint", "Breather", "Son Of A Boxer"])
    assert (session.effect_run is None or session.effect_run.awaiting is None) and table.top_discards == []


@with_rig()
def test_take_a_knee_falls_back_to_laying_the_card_by_hand_when_the_table_refuses(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, _ = on_deck(table, game, DEVIL, "Feint")
    table.top_discard_fail = "deck"
    game.fighters["daredevil"].hp = 10
    hit(session, table, game, "Take A Knee", ["Take A Knee", "Feint", "Breather", "Son Of A Boxer"])
    msgs = done(session, table, 1)
    req = session.effect_run.awaiting
    assert said(msgs, "No he podido mover las cartas de arriba de tu mazo") and req.kind == "cards" and req.extra["pile_mode"] == "blind"
    table.human_discard += [top]
    done(session, table)
    assert game.fighters["daredevil"].hp == 13


@with_rig()
def test_the_one_button_waiting_at_the_panel_survives_a_save_and_a_restore(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    top, _ = on_deck(table, game, DEVIL, "Feint")
    game.fighters["daredevil"].hp = 10
    hit(session, table, game, "Take A Knee", ["Take A Knee", "Feint", "Breather", "Son Of A Boxer"])
    session._restore(session.to_dict())
    game = session.game
    assert session.effect_run.awaiting.extra["top_discard"] and pause_labels(session) == ["1"] and table.top_discards == []
    done(session, table, 1)
    assert table.human_discard == [top] and game.fighters["daredevil"].hp == 13


# ---------------------------------------------------------------- Devil of Hell's Kitchen

@with_rig()
def test_the_devil_puts_itself_and_the_last_four_cards_of_the_pile_back_in_the_deck(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    old = [sid(game, "Feint", 2), sid(game, "Breather", 2), sid(game, "Grappling Hook", 0), sid(game, "Take A Knee", 0), sid(game, "Son Of A Boxer", 0)]       # none is in their hand
    table.human_discard += old
    for c in game.players[1].full_set:
        if c.card_id in old and c not in game.players[1].discard:
            for zone in (game.players[1].deck, game.players[1].hand):
                if c in zone:
                    zone.remove(c)
            game.players[1].discard.append(c)
    on_deck(table, game, "Man Without Fear")
    msgs = hit(session, table, game, DEVIL, [DEVIL, "Feint", "Breather", "Son Of A Boxer"])
    ids = [i for _, moved in table.deck_moves for i in moved]
    devil = sid(game, DEVIL)
    assert sorted(ids) == sorted([devil, *old[1:]]), (ids, msgs)                     # itself + the last 4 (Ivan, 2026-11-07)
    assert old[0] in table.human_discard and all(i not in table.human_discard for i in old[1:])
    assert [kind for kind, _ in table.deck_moves] == ["shuffle", "shuffle"]
    assert said(msgs, "Meto Devil of Hell's Kitchen de tu zona de combate en tu mazo y lo barajo")


# ---------------------------------------------------------------- Through Adversity and Breather

@with_rig()
def test_through_adversity_by_hand_asks_which_rivals_he_passed_and_each_named_one_takes_one_damage(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Through Adversity", "Feint")
    human_scheme(session, table, game, "Through Adversity")
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and req.min == 0 and req.max == 2 and req.extra["op"] == "damage", req
    assert labels(session) == ["Hellboy", "Lobster Johnson", "Ninguna"]
    hp = {f: game.fighters[f].hp for f in ("hellboy", "lobster")}
    press(session, table, "hellboy")
    assert session.effect_run is not None, "a multi-pick: it waits for the confirm button"
    press(session, table, "lobster")
    assert game.fighters["hellboy"].hp == hp["hellboy"] and game.fighters["lobster"].hp == hp["lobster"]
    click(session, table, Event.CHOICE, {"i": 3})                                      # the confirm slot
    assert session.effect_run is None
    assert game.fighters["hellboy"].hp == hp["hellboy"] - 1 and game.fighters["lobster"].hp == hp["lobster"] - 1


@with_rig()
def test_through_adversity_by_hand_naming_only_one_rival_hits_only_that_one(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Through Adversity", "Feint")
    human_scheme(session, table, game, "Through Adversity")
    hp = {f: game.fighters[f].hp for f in ("hellboy", "lobster")}
    press(session, table, "hellboy")
    click(session, table, Event.CHOICE, {"i": 3})
    assert game.fighters["hellboy"].hp == hp["hellboy"] - 1 and game.fighters["lobster"].hp == hp["lobster"]


@with_rig()
def test_through_adversity_by_hand_passing_nobody_deals_nothing(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Through Adversity", "Feint")
    human_scheme(session, table, game, "Through Adversity")
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.CHOICE, {"i": len(labels(session))})                   # "None"
    assert game.fighters["hellboy"].hp == hp and session.effect_run is None


@with_rig()
def test_breather_lets_them_pick_a_non_scheme_card_from_their_discard_pile(rig):
    session, table, game, fake, cfg = rig
    a, b = sid(game, "Son Of A Boxer", 0), sid(game, "Feint", 0)
    table.human_discard += [a, b]
    human_hand(table, game, "Breather", "Grappling Hook")
    human_scheme(session, table, game, "Breather")
    req = session.effect_run.awaiting
    assert req.kind == "cards" and sorted(req.options) == sorted([a, b])
    press(session, table, a)
    assert session.effect_run is None and a in [c.card_id for c in game.players[1].hand]


@with_rig()
def test_the_devil_goes_back_into_a_human_deck_that_is_gone_from_the_table(rig, monkeypatch):
    """The human's deck is empty: TTS has no Deck object, so the cards are laid down as the new deck instead of being refused
    (the Relentless-style move of the card at the combat spot and the move of the pile cards, both by the bot)."""
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    old = [sid(game, "Feint", 2), sid(game, "Breather", 2), sid(game, "Grappling Hook", 0), sid(game, "Take A Knee", 0), sid(game, "Son Of A Boxer", 0)]
    table.human_discard += old
    for c in game.players[1].full_set:
        if c.card_id in old and c not in game.players[1].discard:
            for zone in (game.players[1].deck, game.players[1].hand):
                if c in zone:
                    zone.remove(c)
            game.players[1].discard.append(c)
    table.human_deck = []
    msgs = hit(session, table, game, DEVIL, [DEVIL, "Feint", "Breather", "Son Of A Boxer"])
    devil = sid(game, DEVIL)
    assert sorted(table.human_deck) == sorted([devil, *old[1:]]), (table.human_deck, msgs)
    assert not said(msgs, "no he podido") and not said(msgs, "hazlo"), msgs
    assert old[0] in table.human_discard and all(i not in table.human_discard for i in old[1:])


@with_rig()
def test_the_devil_shuffles_back_the_card_its_blind_boost_just_laid_on_the_pile(rig, monkeypatch):
    """Live 20/11 (10:22, 0.9.0): the blind-boosted Son Of A Boxer was the newest card of the pile, the engine sent it back into
    the deck with the Devil, but the bot only moved the three older ones on the table: the pile and the engine parted."""
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    old = [sid(game, "Feint", 2), sid(game, "Breather", 2), sid(game, "Grappling Hook", 0), sid(game, "Take A Knee", 0)]
    table.human_discard += old
    for c in game.players[1].full_set:
        if c.card_id in old and c not in game.players[1].discard:
            for zone in (game.players[1].deck, game.players[1].hand):
                if c in zone:
                    zone.remove(c)
            game.players[1].discard.append(c)
    top, _ = on_deck(table, game, "Son Of A Boxer", "Man Without Fear")
    hit(session, table, game, DEVIL, [DEVIL, "Feint", "Breather"])
    msgs = done(session, table, 2)                                                    # the ability: "1"
    ids = [i for _, moved in table.deck_moves for i in moved]
    assert top in ids and top not in table.human_discard, (ids, table.human_discard, msgs)
    assert sorted(ids) == sorted([sid(game, DEVIL), top, *old[1:]]), (ids, msgs)
