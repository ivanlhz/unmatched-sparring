"""The TMNT cards still untested from the human's seat, played through the panel (FakeTTS, batch mode, the rig of
tests/test_e2_human_cards.py): Raphael's Batter up! and Raphael is cool but rude; Donatello's Shift focus, Short circuit,
Untested enhancements, Donatello does machines, The future of Ninjutsu and Party wagon!; Michelangelo's Hard-Hitting
Investigation, Let's Go!!, Back For Seconds and Michelangelo Is A Party Dude!!. Each test ends on the table / engine state
the card should leave. The rival is Hellboy."""
from __future__ import annotations

from sparring.tts.ui import Event
from test_batch import click
from sparring.ai_medusa import Act
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import (bot_defends_with, bot_defends_with_nothing, by_hand, human_scheme, labels, press,  # noqa: F401
                                 put_adjacent, rig, with_rig)

TRAINING = "B.P.R.D. Training"
RAPH = ("hellboy", "raphael", TRAINING)
DON = ("hellboy", "donatello", TRAINING)
MIKEY = ("hellboy", "michelangelo", TRAINING)


# ---------------------------------------------------------------- Raphael

@with_rig(*RAPH)
def test_batter_up_won_asks_the_human_to_move_the_bots_fighter_by_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "casey", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Batter up!", "Break something")
    human_attack(session, table, game, "casey", "hellboy", "Batter up!")
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "hellboy" and req.card_owner == 1, req
    dest = req.options[-1]
    by_hand(session, table, cfg, "hellboy", dest)
    assert session.pending is None and game.fighters["hellboy"].pos == dest
    assert not any(m[0] == cfg.nicknames["hellboy"] for m in table.moves), "the human moved it: the bot does not touch the miniature"


@with_rig(*RAPH)
def test_batter_up_lost_does_not_ask_for_a_move(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "casey", "hellboy")
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Batter up!", "Break something")
    human_attack(session, table, game, "casey", "hellboy", "Batter up!")
    click(session, table, Event.REVEAL)
    assert session.effect_run is None and session.pending is None, "lost: the move is not asked"


@with_rig(*RAPH)
def test_raphael_is_cool_but_rude_hurts_the_rivals_next_to_a_friend_and_deals_you_a_card(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "raphael", "hellboy")
    far = max(game.board.spaces)
    game.fighters["lobster"].pos = far
    table.positions[cfg.nicknames["lobster"]] = far
    human_hand(table, game, "Raphael is cool but rude", "Break something")
    hp, lobster = game.fighters["hellboy"].hp, game.fighters["lobster"].hp
    msgs = human_scheme(session, table, game, "Raphael is cool but rude")
    assert game.fighters["hellboy"].hp == hp - 1 and game.fighters["lobster"].hp == lobster, msgs
    assert table.human_deals == [1] and len(game.players[1].hand) == 1 + 1
    assert cfg.session_config().dials["hellboy"] in {g for g, _ in table.dial_writes}


# ---------------------------------------------------------------- Donatello

@with_rig(*DON)
def test_shift_focus_asks_which_other_fighter_in_the_zone_and_the_human_moves_it_by_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "donatello", "hellboy")
    put_adjacent(game, table, cfg, "metalhead", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Shift focus", "Quick strike")
    human_attack(session, table, game, "donatello", "hellboy", "Shift focus")
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and req.card_owner == 1 and "donatello" not in req.options, req
    assert "metalhead" in req.options
    msgs = press(session, table, "hellboy")                     # the bot's fighter: where it goes is asked, by hand
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "hellboy", req
    dest = req.options[-1]
    by_hand(session, table, cfg, "hellboy", dest)
    assert session.pending is None and game.fighters["hellboy"].pos == dest
    assert not any(m[0] == cfg.nicknames["hellboy"] for m in table.moves)


@with_rig(*DON)
def test_shift_focus_on_your_own_fighter_leaves_the_move_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "donatello", "hellboy")
    put_adjacent(game, table, cfg, "metalhead", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Shift focus", "Quick strike")
    human_attack(session, table, game, "donatello", "hellboy", "Shift focus")
    click(session, table, Event.REVEAL)
    msgs = press(session, table, "metalhead")
    assert session.pending is None and session.effect_run is None
    assert said(msgs, "en la mesa: mueve a metalhead hasta 3 casillas"), msgs


@with_rig(*DON)
def test_short_circuit_cancels_only_the_after_and_the_chat_says_so(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "donatello", "hellboy")
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Short circuit", "Quick strike")
    bot_hand = len(game.players[0].hand)
    human_attack(session, table, game, "donatello", "hellboy", "Short circuit")
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "cancela los efectos de B.P.R.D. Training despues del combate"), msgs
    assert len(game.players[0].hand) == bot_hand - 1, "its AFTER COMBAT draw was cancelled"
    assert session.pending is None


@with_rig(*DON)
def test_untested_enhancements_takes_the_real_bottom_card_you_put_in_the_discard_and_adds_its_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "metalhead", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Untested enhancements", "Quick strike")
    hp = game.fighters["hellboy"].hp
    human_attack(session, table, game, "metalhead", "hellboy", "Untested enhancements")
    msgs = click(session, table, Event.REVEAL)
    assert session.pending.wait is not None and session.pending.wait.deck and said(msgs, "carta del FONDO de tu mazo")
    bottom = next(c for c in game.players[1].full_set if c.title == "Heroes in a half shell")    
    table.human_discard.append(bottom.card_id)                  # the real bottom card, put by hand on the discard
    msgs = click(session, table, Event.BOOST)
    st = game.players[1]
    assert bottom.card_id in [c.card_id for c in st.discard] and bottom.card_id not in [c.card_id for c in st.deck]
    assert hp - game.fighters["hellboy"].hp == 3 + bottom.boost, msgs
    assert said(msgs, "Tu carta: Untested enhancements: descartas Heroes in a half shell"), msgs


@with_rig(*DON)
def test_donatello_does_machines_returns_the_discarded_attack_and_tells_you_to_pick_it_up(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Donatello does machines", "Bo staff")
    old = card_ids(game, 1, "Quick strike")[0]
    st = game.players[1]
    qs = next(c for c in st.full_set if c.card_id == old)
    for zone in (st.hand, st.deck):
        if qs in zone:
            zone.remove(qs)
    st.discard.append(qs)
    table.human_discard.append(old)
    human_scheme(session, table, game, "Donatello does machines")
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.card_owner == 1, req
    msgs = press(session, table, True)
    assert session.effect_run is None and session.pending is None
    assert qs in st.hand and qs not in st.discard, "the only candidate is taken without asking"
    assert table.human_deals == [1] and said(msgs, "Recoge Quick strike de tu descarte a tu mano"), msgs


@with_rig(*DON)
def test_donatello_does_machines_declined_still_draws(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Donatello does machines", "Bo staff")
    human_scheme(session, table, game, "Donatello does machines")
    press(session, table, False)
    assert session.effect_run is None and table.human_deals == [1]


@with_rig(*DON)
def test_the_future_of_ninjutsu_draws_gains_an_action_and_asks_about_the_top_card(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "The future of Ninjutsu", "Bo staff")
    actions = game.actions_left
    msgs = human_scheme(session, table, game, "The future of Ninjutsu")
    assert session.effect_run is not None, msgs
    req = session.effect_run.awaiting
    assert req.kind == "optional", req
    press(session, table, False)
    assert session.effect_run is None
    assert game.actions_left == actions - 1 + 1 and table.human_deals == [1]


def party_wagon_to_the_damage_question(session, table, game, cfg):
    put_adjacent(game, table, cfg, "donatello", "hellboy")
    human_hand(table, game, "Party wagon!", "Quick strike")
    human_scheme(session, table, game, "Party wagon!")
    msgs = press(session, table, "donatello")                   # the miniature is moved by hand: the engine sees no path
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and req.min == 0 and req.extra["op"] == "damage", req
    assert labels(session) == ["Hellboy", "Lobster Johnson", "Ninguna"]
    return msgs


@with_rig(*DON)
def test_party_wagon_by_hand_naming_a_rival_deals_the_two_damage(rig):
    session, table, game, fake, cfg = rig
    party_wagon_to_the_damage_question(session, table, game, cfg)
    hp = game.fighters["hellboy"].hp
    msgs = press(session, table, "hellboy")
    assert session.effect_run is None and game.fighters["hellboy"].hp == hp - 2, msgs
    assert cfg.session_config().dials["hellboy"] in {g for g, _ in table.dial_writes}


@with_rig(*DON)
def test_party_wagon_by_hand_passing_nobody_deals_no_damage(rig):
    session, table, game, fake, cfg = rig
    party_wagon_to_the_damage_question(session, table, game, cfg)
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.CHOICE, {"i": 3})               # "None": nobody was passed
    assert session.effect_run is None and game.fighters["hellboy"].hp == hp


# ---------------------------------------------------------------- Michelangelo

@with_rig(*MIKEY)
def test_hard_hitting_investigation_deals_one_and_gives_the_action_back(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "april", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Hard-Hitting Investigation", "Nunchaku")
    hp, actions = game.fighters["hellboy"].hp, game.actions_left
    human_attack(session, table, game, "april", "hellboy", "Hard-Hitting Investigation")
    msgs = click(session, table, Event.REVEAL)
    assert hp - game.fighters["hellboy"].hp >= 1, msgs
    assert game.actions_left == actions, "the attack cost 1 and the card gave it back"
    assert cfg.session_config().dials["hellboy"] in {g for g, _ in table.dial_writes}
    assert session.pending is None and session.effect_run is None


@with_rig(*MIKEY)
def test_lets_go_asks_which_friendly_fighter_and_leaves_the_move_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "mikey", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Let's Go!!", "Nunchaku")
    human_attack(session, table, game, "mikey", "hellboy", "Let's Go!!")
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and set(req.options) == {"mikey", "april"} and req.card_owner == 1, req
    msgs = press(session, table, "april")
    assert session.effect_run is None and session.pending is None
    assert said(msgs, "en la mesa: mueve a april hasta 3 casillas"), msgs


@with_rig("hellboy", "michelangelo", "Excalibur")
def test_back_for_seconds_defending_shuffles_two_cards_of_your_discard_into_your_deck(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "mikey", "hellboy")
    human_hand(table, game, "Back For Seconds")
    earlier = card_ids(game, 1, "Nunchaku", "Cowabunga!!", "Heroes In A Half Shell")
    st = game.players[1]
    for i in earlier:
        c = next(c for c in st.full_set if c.card_id == i)
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)
    table.human_discard = list(earlier)
    back = card_ids(game, 1, "Back For Seconds")[0]
    excalibur = next(c for c in game.players[0].hand if c.title == "Excalibur")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="mikey", card=excalibur)])
    table.face_down = [{"id": back, "guid": f"h{back}"}]
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is None and session.effect_run is None
    assert said(msgs, "Back For Seconds"), msgs
    assert said(msgs, "en tu mazo y lo barajo"), msgs
    assert len(st.discard) == 3 - 2 + 1, "two cards left the pile for the deck, Back For Seconds went in"
    assert "Back For Seconds" in {c.title for c in st.discard}
    assert len(set(earlier) & set(table.human_discard)) == 1, "the bot took two of the three cards off the human's pile"


@with_rig(*MIKEY)
def test_michelangelo_is_a_party_dude_heals_each_friendly_fighter_by_one(rig):
    session, table, game, fake, cfg = rig
    game.fighters["mikey"].hp -= 3
    game.fighters["april"].hp -= 2
    mikey, april = game.fighters["mikey"].hp, game.fighters["april"].hp
    human_hand(table, game, "Michelangelo Is A Party Dude!!", "Nunchaku")
    msgs = human_scheme(session, table, game, "Michelangelo Is A Party Dude!!")
    assert game.fighters["mikey"].hp == mikey + 1 and game.fighters["april"].hp == april + 1, msgs
    written = {g for g, _ in table.dial_writes}
    assert {cfg.session_config().dials["mikey"], cfg.session_config().dials["april"]} <= written
    assert session.effect_run is None


@with_rig("liz-sherman", "michelangelo", TRAINING)
def test_back_for_seconds_cards_the_engine_then_draws_for_you_still_go_into_the_real_deck(rig):
    """Live 6/11: Back For Seconds against Fleeting Moments. The engine shuffles the two pile cards into your (guessed)
    deck and then draws one of them for Fleeting Moments: on the table both go into your deck, none is a pickup."""
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "mikey", "liz")
    human_hand(table, game, "Back For Seconds")       # Michelangelo's limit is 3: the two maneuvers fill it
    earlier = card_ids(game, 1, "Cowabunga!!", "Heroes In A Half Shell")
    st = game.players[1]
    for i in earlier:
        c = next(c for c in st.full_set if c.card_id == i)
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)
    table.human_discard = list(earlier)
    back = card_ids(game, 1, "Back For Seconds")[0]
    fleeting = next(c for c in game.players[0].full_set if c.title == "Fleeting Moments")
    for zone in (game.players[0].deck, game.players[0].discard):
        if fleeting in zone:
            zone.remove(fleeting)
    if fleeting not in game.players[0].hand:
        game.players[0].hand.append(fleeting)
        table.bot_deck = [c.card_id for c in game.players[0].deck]
        table.bot_discard = [c.card_id for c in game.players[0].discard]
        table.bot_hand = [c.card_id for c in game.players[0].hand]
    out = bot_turn(session, table, [Act("attack", fid="liz", target="mikey", card=fleeting)])
    assert session.pending is not None, out
    st.deck.clear()                               # the engine's draw can only take a card Back For Seconds put back
    table.face_down = [{"id": back, "guid": f"h{back}"}]
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "en tu mazo y lo barajo"), msgs
    assert not said(msgs, "de tu descarte a tu mano"), msgs
    assert not set(earlier) & set(table.human_discard), "the bot took both cards off the human's pile"
