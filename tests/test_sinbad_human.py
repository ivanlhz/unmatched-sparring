"""Sinbad on the table through the panel (FakeTTS, batch mode), both seats: the human's VOYAGE cards (value from the pile on the table,
Voyage Home taking the others back to the hand, the random discard, the look, the damage, the heal), the human's draws dealt by the
bot, a move the human makes by hand (Toil and Danger, Leap Away), the Maneuver reach the chat reports, and the bot's Sinbad playing
the same cards against a human. The bot's side of the same cards is in tests/test_sinbad_effects.py.

His deck is sheet 176 like the other nine: every id the table reports is resolved against the owner's deck."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_hand, said
from test_d3_table_effects import human_attack as human_plays_attack
from test_e2_human_cards import (bot_defends_with_nothing, by_hand, human_scheme, press, put_adjacent,  # noqa: F401
                                 rig, with_rig)
from test_human_pile_to_hand import HandTable

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3
VOYAGES = ["Voyage Home", "Voyage to the Valley of the Giant Snakes", "Voyage to the Island That Was a Whale",
           "Voyage to the Creature With Eyes Like Coals of Fire", "Voyage to the City of the Man-Eating Apes",
           "Voyage to the City of the King of Serendib", "Voyage to the Cannibals With the Root of Madness"]


def attack(session, table, game, title, attacker="sinbad", target="hellboy"):
    human_plays_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def pile(session, table, game, side, *titles):
    """`titles` of `side`'s (0 bot, 1 human) deck already on its discard pile, on the table and in the engine."""
    st = game.players[side]
    ids = card_ids(game, side, *titles)
    for i in ids:
        c = next(c for c in st.full_set if c.card_id == i)
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)
    if side == 1:
        table.human_discard = [*table.human_discard, *ids]
    else:
        table.bot_discard.extend(ids)
        session.bot_discarded.update(ids)
        table.bot_hand = [i for i in table.bot_hand if i not in ids]
        table.bot_deck = [i for i in table.bot_deck if i not in ids]
    return ids


def human_rig(tmp_path, bot="hellboy", hand=(TRAINING,), table_cls=HandTable):
    return build(tmp_path, bot, "sinbad", hand, table_cls=table_cls)


@pytest.fixture
def mine(tmp_path):
    session, table, game, fake, cfg, client = human_rig(tmp_path)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


@pytest.fixture
def bots(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "sinbad", "hellboy", ("Exploit", "Regroup"), table_cls=HandTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


# ---------------------------------------------------------------- the human plays his cards

def test_riches_beyond_compare_deals_three_cards_to_the_human(mine):
    session, table, game, fake, cfg = mine
    human_hand(table, game, "Riches Beyond Compare", "Exploit")
    msgs = human_scheme(session, table, game, "Riches Beyond Compare")
    assert table.human_deals == [3] and said(msgs, "Te he dado 3 cartas")
    assert len(game.players[1].hand) == 1 + 3 and game.actions_left == 1


def test_a_voyage_attack_is_worth_the_voyage_cards_on_the_humans_pile(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    human_hand(table, game, "Voyage to the City of the King of Serendib", "Exploit")
    pile(session, table, game, 1, VOYAGES[1], VOYAGES[2], VOYAGES[4], "Exploit")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Voyage to the City of the King of Serendib")
    assert game.fighters["hellboy"].hp == hp - (2 + 3), msgs
    assert table.human_deals == [1]                                  # Serendib: draw 1, dealt by the bot


def test_voyage_home_takes_the_others_from_the_pile_to_the_hand_by_the_bot(tmp_path):
    session, table, game, fake, cfg, client = human_rig(tmp_path)
    try:
        bot_defends_with_nothing_plain(session)
        put_adjacent(game, table, cfg, "sinbad", "hellboy")
        human_hand(table, game, "Voyage Home", "Exploit")
        ids = pile(session, table, game, 1, VOYAGES[1], VOYAGES[5], "Exploit")
        voyage_ids = ids[:2]
        msgs = attack(session, table, game, "Voyage Home")
        assert sorted(i for i in table.human_hand if i in voyage_ids) == sorted(voyage_ids), msgs
        assert all(i not in table.human_discard for i in voyage_ids) and ids[2] in table.human_discard
        assert sorted(c.title for c in game.players[1].hand if "voyage" in c.tags) == sorted([VOYAGES[1], VOYAGES[5]])
        assert said(msgs, "vuelve a tu mano") or said(msgs, "Recoge"), msgs
    finally:
        client.close()
        fake.close()


def test_the_creature_makes_the_bot_discard_a_random_card_and_the_table_follows(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    human_hand(table, game, "Voyage to the Creature With Eyes Like Coals of Fire", "Exploit")
    before = len(game.players[0].hand)
    msgs = attack(session, table, game, "Voyage to the Creature With Eyes Like Coals of Fire")
    assert before >= 1 and len(game.players[0].hand) == before - 1 and len(table.bot_discard) == 1, msgs
    gone = game.players[0].discard[-1]
    assert said(msgs, f"El bot descarta {gone.title}") and gone.card_id in table.bot_discard


def test_the_snakes_show_the_humans_chat_the_bots_hand(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    human_hand(table, game, "Voyage to the Valley of the Giant Snakes", "Exploit")
    titles = [c.title for c in game.players[0].hand]
    msgs = attack(session, table, game, "Voyage to the Valley of the Giant Snakes")
    assert titles and all(said(msgs, title) for title in titles), msgs


def test_the_apes_hurt_the_bots_fighter_and_its_dial_follows(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    human_hand(table, game, "Voyage to the City of the Man-Eating Apes", "Exploit")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "Voyage to the City of the Man-Eating Apes")
    assert game.fighters["hellboy"].hp == hp - 2 - 2
    assert cfg.session_config().dials["hellboy"] in {g for g, _ in table.dial_writes}


def test_the_whale_heals_the_human_sinbad_and_the_dial_follows(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    game.fighters["sinbad"].hp = 9
    human_hand(table, game, "Voyage to the Island That Was a Whale", "Exploit")
    attack(session, table, game, "Voyage to the Island That Was a Whale")
    assert game.fighters["sinbad"].hp == 11
    assert cfg.session_config().dials["sinbad"] in {g for g, _ in table.dial_writes}


def test_toil_and_danger_leaves_the_move_of_sinbad_to_the_human(mine, monkeypatch):
    """His own miniature is the human's to move (the chat says how far); End action reads where it ended."""
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    human_hand(table, game, "Toil and Danger", "Exploit")
    msgs = attack(session, table, game, "Toil and Danger")
    assert session.pending is None and said(msgs, "mueve a sinbad hasta 3 casillas"), msgs
    start = game.fighters["sinbad"].pos
    dest = next(s for s in sorted(game.board.spaces) if game.board.distance(start, s) == 3 and all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["sinbad"]] = dest
    click(session, table, Event.END_ACTION)
    assert game.fighters["sinbad"].pos == dest


def test_leap_away_asks_which_fighter_and_the_human_moves_the_bots_piece(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    human_hand(table, game, "Leap Away", "Exploit")
    msgs = attack(session, table, game, "Leap Away")
    assert session.effect_run.awaiting.kind == "fighter" and set(session.effect_run.awaiting.options) == {"sinbad", "hellboy"}
    press(session, table, "hellboy")
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "hellboy" and req.extra["steps"] == 4
    dest = req.options[0]
    by_hand(session, table, cfg, "hellboy", dest)
    assert session.pending is None and game.fighters["hellboy"].pos == dest


def test_regroup_deals_two_when_the_human_won(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    human_hand(table, game, "Regroup", "Exploit")
    attack(session, table, game, "Regroup")
    assert table.human_deals == [2]


def test_momentous_shift_is_five_for_a_fighter_that_moved_this_turn(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    game.fx.emit("start_of_turn", game.turn)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    human_hand(table, game, "Momentous Shift", "Exploit")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "Momentous Shift")
    assert game.fighters["hellboy"].hp == hp - 5


# ---------------------------------------------------------------- the Maneuver reach the human reads in the chat

def test_the_human_sinbad_is_told_how_far_his_fighters_may_move(mine):
    session, table, game, fake, cfg = mine
    pile(session, table, game, 1, VOYAGES[1], VOYAGES[2])
    msgs = click(session, table, Event.MANEUVER)
    assert said(msgs, "VOYAGE") and said(msgs, "+2"), msgs


def test_without_voyage_cards_the_chat_says_nothing_about_the_reach(mine):
    session, table, game, fake, cfg = mine
    msgs = click(session, table, Event.MANEUVER)
    assert not said(msgs, "VOYAGE"), msgs


# ---------------------------------------------------------------- the bot plays Sinbad against the human

def bots_attack(tmp_path, title, human_cards=(TRAINING, "Excalibur", "Service Pistol"), others=("Exploit",)):
    """A rig with the bot's Sinbad holding `title`, a rival Hellboy holding `human_cards`, both next to each other."""
    session, table, game, fake, cfg, client = build(tmp_path, "sinbad", "hellboy", (title, *others), table_cls=HandTable)
    put_adjacent(game, table, cfg, "sinbad", "hellboy")
    human_hand(table, game, *human_cards)
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    return session, table, game, fake, cfg, client


def run_bot_attack(session, table, game, title):
    card = next(c for c in game.players[0].hand if c.title == title)
    first = bot_turn(session, table, [Act("attack", fid="sinbad", target="hellboy", card=card)])
    return [*first, *click(session, table, Event.REVEAL)]       # the human leaves no defense on the table and reveals


def test_the_bots_serendib_draws_a_card_to_its_table_hand(tmp_path):
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "Voyage to the City of the King of Serendib")
    try:
        was = list(table.bot_hand)
        msgs = run_bot_attack(session, table, game, "Voyage to the City of the King of Serendib")
        assert said(msgs, "Voyage to the City of the King of Serendib: roba 1"), msgs
        drawn = [i for i in table.bot_hand if i not in was]
        assert len(drawn) == 1 and len(table.bot_hand) == len(was)          # played one, the table dealt one
        assert [c.card_id for c in game.players[0].hand if c.card_id not in was] == drawn
    finally:
        client.close()
        fake.close()


def test_the_bots_voyage_home_takes_its_voyage_cards_back_to_the_table_hand(tmp_path):
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "Voyage Home")
    try:
        ids = pile(session, table, game, 0, VOYAGES[1], VOYAGES[5])
        msgs = run_bot_attack(session, table, game, "Voyage Home")
        assert all(i in table.bot_hand and i not in table.bot_discard for i in ids), (table.bot_hand, table.bot_discard, msgs)
        assert sorted(c.title for c in game.players[0].hand if "voyage" in c.tags) == sorted([VOYAGES[1], VOYAGES[5]])
        assert said(msgs, "Voyage to the City of the King of Serendib") and said(msgs, "vuelve")
    finally:
        client.close()
        fake.close()


def test_the_bots_creature_makes_the_human_discard_a_random_card(tmp_path):
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "Voyage to the Creature With Eyes Like Coals of Fire")
    try:
        msgs = run_bot_attack(session, table, game, "Voyage to the Creature With Eyes Like Coals of Fire")
        assert said(msgs, "al azar: la carta"), msgs                  # the human discards the random position by hand
    finally:
        client.close()
        fake.close()


def test_the_bots_apes_hurt_the_human_hero_and_the_dial_follows(tmp_path):
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "Voyage to the City of the Man-Eating Apes")
    try:
        hp = game.fighters["hellboy"].hp
        run_bot_attack(session, table, game, "Voyage to the City of the Man-Eating Apes")
        assert game.fighters["hellboy"].hp == hp - 2 - 2
        assert cfg.session_config().dials["hellboy"] in {g for g, _ in table.dial_writes}
    finally:
        client.close()
        fake.close()


def test_the_bots_snakes_read_the_humans_hand_once(tmp_path):
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "Voyage to the Valley of the Giant Snakes")
    try:
        from test_d3_table_effects import human_reads
        run_bot_attack(session, table, game, "Voyage to the Valley of the Giant Snakes")
        assert len(human_reads(table)) >= 1
    finally:
        client.close()
        fake.close()


def test_the_bots_whale_heals_its_sinbad_and_the_dial_follows(tmp_path):
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "Voyage to the Island That Was a Whale")
    try:
        game.fighters["sinbad"].hp = 8
        table.dials[cfg.session_config().dials["sinbad"]]["value"] = 8
        session.dials_written[cfg.session_config().dials["sinbad"]] = 8
        run_bot_attack(session, table, game, "Voyage to the Island That Was a Whale")
        assert game.fighters["sinbad"].hp >= 10 - 3                       # healed 2 (the human's rival card may have hit back)
        assert cfg.session_config().dials["sinbad"] in {g for g, _ in table.dial_writes}
    finally:
        client.close()
        fake.close()


def test_the_bot_maneuvers_further_with_voyage_cards_in_its_pile(bots):
    session, table, game, fake, cfg = bots
    human_hand(table, game, TRAINING)
    pile(session, table, game, 0, VOYAGES[1], VOYAGES[2], VOYAGES[4])
    sinbad = game.fighters["sinbad"]
    start = sinbad.pos
    dest = next(s for s in sorted(game.board.spaces) if game.board.distance(start, s) == 5 and all(f.pos != s for f in game.fighters.values() if f.alive))
    plan = [Act("maneuver", moves={"sinbad": dest})]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    assert game.fighters["sinbad"].pos == dest


def bot_defends_with_nothing_plain(session):
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
