"""Ciri played BY THE HUMAN through the panel (FakeTTS, batch mode): the SOURCE (read from the human's discard pile on the table), the
tiers of her cards, Channel the source (the Source cards the human lays on the pile), Searching strike (the human searches their own
deck), the end-of-turn Unicorn ally and UNCONTAINABLE POWER against a bot that cancels. The bot's side of the same cards is in
tests/test_ciri_effects.py and in tests/test_ciri_bot_table.py (the Source dial and the deck search at the table)."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_attack, human_hand, said, set_hand
from test_e2_human_cards import human_scheme, labels, press, put_adjacent

TRAINING = "B.P.R.D. Training"      # Hellboy's defense of value 3


@pytest.fixture
def rig(request, tmp_path):
    bot, bot_hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, "ciri", bot_hand)
    put_adjacent(game, table, cfg, "ciri", "hellboy" if bot == "hellboy" else "liz")
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def rigged(*bot_hand, bot="hellboy"):
    return pytest.mark.parametrize("rig", [(bot, bot_hand)], indirect=True)


def defends(session, game, monkeypatch, title=None):
    card = None if title is None else next(c for c in game.players[0].hand if c.title == title)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: card)
    return card


def attack(session, table, game, attacker, title, target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def human_source(table, game, n, played=None):
    """`n` Source cards of the human's deck on their discard pile, on the table and in the engine, never the first copy of the card
    titled `played` (the one a test plays by title)."""
    st = game.players[1]
    first = None if played is None else next(c for c in st.full_set if c.title == played)
    cards = [c for c in st.full_set if "source" in c.tags and c is not first]
    for c in cards[len(cards) - n:] if n else []:
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)
        table.human_discard.append(c.card_id)
        if c.card_id in table.human_hand:
            table.human_hand.remove(c.card_id)
    assert game.counter(1, "source") == n


def give_up(table, game, *titles):
    """The human puts these cards of their hand on their discard pile (what Channel the source waits for)."""
    ids = []
    for title in titles:
        cid = next(i for i in card_ids(game, 1, title) if i in table.human_hand)
        ids.append(cid)
        table.human_hand.remove(cid)
        table.human_discard.append(cid)
        table.human_count -= 1
    return ids


def done(session, table):
    return click(session, table, Event.CHOICE, {"i": 1})


# ---------------------------------------------------------------- the Source counts the human's discard pile

@pytest.mark.parametrize("source,value", [(0, 2), (1, 4), (5, 7)])
@rigged(TRAINING)
def test_lion_cub_of_cintra_has_the_value_the_source_of_the_table_gives(rig, monkeypatch, source, value):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    human_hand(table, game, "Lion cub of Cintra", "Blink")
    human_source(table, game, source, played="Lion cub of Cintra")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "ciri", "Lion cub of Cintra")
    assert game.fighters["hellboy"].hp == hp - value


@rigged(TRAINING, "Service Pistol", "Right Hand Of Doom")
def test_zireael_at_source_five_makes_the_bot_discard_a_random_card_and_the_table_follows(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    human_hand(table, game, "Zireael", "Blink")
    human_source(table, game, 5, played="Zireael")
    cards = len(game.players[0].hand)
    pile = len(table.bot_discard)
    msgs = attack(session, table, game, "ciri", "Zireael")
    assert len(game.players[0].hand) == cards - 1 and len(table.bot_discard) == pile + 1, msgs


@rigged(TRAINING)
def test_pushed_to_the_brink_at_source_seven_asks_which_fighter_within_three_spaces_takes_two(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    human_hand(table, game, "Pushed to the brink", "Blink")
    human_source(table, game, 7, played="Pushed to the brink")
    lobster = game.fighters["lobster"]
    ciri = game.fighters["ciri"]
    near = next(s for s in sorted(game.board.spaces) if game.board.spaces_apart(ciri.pos, s) == 3 and all(f.pos != s for f in game.fighters.values() if f.alive))
    lobster.pos = near
    table.positions[cfg.nicknames["lobster"]] = near
    hellboy_hp, lobster_hp = game.fighters["hellboy"].hp, lobster.hp
    msgs = attack(session, table, game, "ciri", "Pushed to the brink")
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "fighter", msgs
    assert set(session.effect_run.awaiting.options) == {"hellboy", "lobster"}
    press(session, table, "lobster")
    assert lobster.hp == lobster_hp - 2 and game.fighters["hellboy"].hp == hellboy_hp - 3
    assert cfg.session_config().dials["lobster"] in {g for g, _ in table.dial_writes}


@rigged(TRAINING)
def test_pushed_to_the_brink_at_source_two_hits_the_opposing_fighter_for_one_with_no_question(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    human_hand(table, game, "Pushed to the brink", "Blink")
    human_source(table, game, 2, played="Pushed to the brink")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "ciri", "Pushed to the brink")
    assert session.effect_run is None and game.fighters["hellboy"].hp == hp - 1


@rigged(TRAINING)
def test_child_of_the_elder_blood_hits_every_other_fighter_in_her_zone_and_the_dials_follow(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Child of the Elder Blood", "Blink")
    human_source(table, game, 9, played="Child of the Elder Blood")
    ciri = game.fighters["ciri"]
    free = [s for s in sorted(game.board.spaces) if s != ciri.pos and game.board.share_zone(ciri.pos, s)
            and all(f.pos != s for f in game.fighters.values() if f.alive)]
    for fid, s in (("lobster", free[0]), ("ihuarraquax", free[1])):
        game.fighters[fid].pos = s
        table.positions[cfg.nicknames[fid]] = s
    hp = {fid: game.fighters[fid].hp for fid in ("hellboy", "lobster", "ihuarraquax")}
    human_scheme(session, table, game, "Child of the Elder Blood")
    for fid, before in hp.items():
        assert game.fighters[fid].hp == before - 3, fid
    assert game.fighters["ciri"].hp == game.fighters["ciri"].max_hp
    assert cfg.session_config().dials["ihuarraquax"] in {g for g, _ in table.dial_writes}


# ---------------------------------------------------------------- Channel the source

@rigged(TRAINING)
def test_channel_the_source_waits_for_the_source_cards_on_the_pile_and_counts_two_each(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    human_hand(table, game, "Channel the source", "Lion cub of Cintra", "Zireael", "Blink")
    msgs = attack(session, table, game, "ciri", "Channel the source")
    req = session.effect_run.awaiting
    assert req.kind == "cards" and req.min == 0 and req.extra["tag"] == "source"
    assert not any(i in req.options for i in card_ids(game, 1, "Blink"))
    assert said(msgs, "cartas de Source"), msgs
    hp = game.fighters["hellboy"].hp
    give_up(table, game, "Lion cub of Cintra", "Zireael")
    msgs = done(session, table)
    assert said(msgs, "+4"), msgs
    assert session.effect_run is None and game.fighters["hellboy"].hp == hp - 6
    assert game.counter(1, "source") == 2


@rigged(TRAINING)
def test_channel_the_source_refuses_a_card_without_the_orb_says_why_and_accepts_it_once_taken_back(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    human_hand(table, game, "Channel the source", "Lion cub of Cintra", "Blink")
    attack(session, table, game, "ciri", "Channel the source")
    lion, blink = give_up(table, game, "Lion cub of Cintra", "Blink")
    msgs = done(session, table)
    assert said(msgs, "Blink (sin orbe de Source)"), msgs
    assert session.effect_run is not None
    table.human_discard.remove(blink)
    table.human_hand.append(blink)
    table.human_count += 1
    msgs = done(session, table)
    assert session.effect_run is None and said(msgs, "+2"), msgs


@rigged(TRAINING)
def test_channel_the_source_with_nothing_given_up_is_just_a_two(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    human_hand(table, game, "Channel the source", "Lion cub of Cintra")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "ciri", "Channel the source")
    done(session, table)
    assert game.fighters["hellboy"].hp == hp - 2


# ---------------------------------------------------------------- Searching strike, Lady of space and time, Unicorn ally

@rigged(TRAINING)
def test_searching_strike_asks_yes_no_when_she_wins_then_tells_the_human_to_search_their_deck(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    put_adjacent(game, table, cfg, "ihuarraquax", "hellboy")
    human_hand(table, game, "Searching strike", "Blink")
    msgs = attack(session, table, game, "ihuarraquax", "Searching strike")
    assert session.effect_run.awaiting.kind == "optional", msgs
    msgs = press(session, table, True)
    assert session.effect_run is None
    assert said(msgs, "Source") or said(msgs, "mazo"), msgs


@rigged(TRAINING)
def test_searching_strike_is_not_asked_when_she_loses(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, TRAINING)
    put_adjacent(game, table, cfg, "ihuarraquax", "hellboy")
    human_hand(table, game, "Searching strike", "Blink")
    attack(session, table, game, "ihuarraquax", "Searching strike")
    assert session.effect_run is None


@rigged(TRAINING)
def test_the_lady_of_space_and_time_at_source_three_asks_for_a_card_of_the_pile(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    human_hand(table, game, "The lady of space and time", "Blink")
    human_source(table, game, 3, played="The lady of space and time")
    attack(session, table, game, "ciri", "The lady of space and time")
    req = session.effect_run.awaiting
    assert req is not None and req.kind == "cards" and len(req.options) == 3


@rigged(TRAINING)
def test_unicorn_ally_heals_two_and_stays_on_the_ongoing_spot(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Unicorn ally", "Blink")
    game.fighters["ciri"].hp = 10
    human_scheme(session, table, game, "Unicorn ally")
    assert game.fighters["ciri"].hp == 12
    assert game.fx.ongoing_card_id(1) in card_ids(game, 1, "Unicorn ally")


@rigged("Service Pistol", TRAINING)
def test_unicorn_ally_draws_for_the_human_after_a_combat_the_bot_starts(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Unicorn ally", "Blink")
    human_scheme(session, table, game, "Unicorn ally")
    click(session, table, Event.END_ACTION)
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="ciri", card=pistol)])
    msgs = click(session, table, Event.REVEAL)                  # the human defends with nothing
    assert said(msgs, "Unicorn ally: robas 1"), msgs


@rigged(TRAINING)
def test_bane_of_the_aen_elle_by_hand_leaves_the_walk_to_the_human_and_asks_which_rival_he_passed(rig, monkeypatch):
    """The engine cannot see a miniature walked by hand (Party wagon! / Through Adversity): the chat says to move him, and the panel offers
    every rival with a 'none' answer; the one named takes the damage."""
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    put_adjacent(game, table, cfg, "ihuarraquax", "hellboy")
    human_hand(table, game, "Bane of the Aen Elle", "Blink")
    hp = {f: game.fighters[f].hp for f in ("hellboy", "lobster")}
    msgs = attack(session, table, game, "ihuarraquax", "Bane of the Aen Elle")
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and req.extra["op"] == "damage" and set(req.options) == {"hellboy", "lobster"} and req.min == 0, req
    assert labels(session)[-1] == "Ninguna"
    msgs = press(session, table, "lobster")
    assert session.effect_run is None and said(msgs, "mueve a ihuarraquax hasta 4 casillas"), msgs
    assert game.fighters["lobster"].hp == hp["lobster"] - 1 and game.fighters["hellboy"].hp == hp["hellboy"] - 4


@rigged(TRAINING)
def test_bane_of_the_aen_elle_by_hand_passing_nobody_hurts_nobody(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    put_adjacent(game, table, cfg, "ihuarraquax", "hellboy")
    human_hand(table, game, "Bane of the Aen Elle", "Blink")
    hp = game.fighters["lobster"].hp
    attack(session, table, game, "ihuarraquax", "Bane of the Aen Elle")
    click(session, table, Event.CHOICE, {"i": len(labels(session))})                           # "None"
    assert session.effect_run is None and game.fighters["lobster"].hp == hp


@rigged(TRAINING)
def test_blink_leaves_the_move_through_rivals_to_the_human(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch)
    human_hand(table, game, "Blink", "Zireael")
    msgs = attack(session, table, game, "ciri", "Blink")
    assert said(msgs, "mueve a ciri hasta 3 casillas") and said(msgs, "puede atravesar"), msgs
    assert session.effect_run is None


# ---------------------------------------------------------------- UNCONTAINABLE POWER

@pytest.mark.parametrize("source,canceled", [(6, True), (7, False)])
@rigged("Feint", bot="liz-sherman")
def test_the_bots_feint_cancels_the_humans_ciri_card_below_source_seven_only(rig, monkeypatch, source, canceled):
    session, table, game, fake, cfg = rig
    defends(session, game, monkeypatch, "Feint")
    put_adjacent(game, table, cfg, "ciri", "liz")
    human_hand(table, game, "Pushed to the brink", "Blink")
    human_source(table, game, source, played="Pushed to the brink")
    hp = game.fighters["liz"].hp
    attack(session, table, game, "ciri", "Pushed to the brink", target="liz")
    lost = hp - game.fighters["liz"].hp
    assert (lost < 2) is canceled, lost
