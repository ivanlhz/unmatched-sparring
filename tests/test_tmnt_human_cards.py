"""The TMNT cards that had only been played by the bot, now played by the HUMAN at the table (FakeTTS, batch mode, the rig
of tests/test_e2_human_cards.py): Leonardo's I have a plan, Wise beyond his years, Spatial awareness and Fearless leader;
Michelangelo's Hi-Yaaaaah!!, Guaranteed Delivery and Shell Insertion. The rival is Hellboy; the human's cards share their
CardIDs with Medusa and with each other's decks, so every id the table reports is resolved against the human's deck."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, human_attack, human_hand, said
from test_e2_human_cards import (bot_defends_with, bot_defends_with_nothing, human_scheme, labels, press,  # noqa: F401
                                 put_adjacent, rig, with_rig)

LEO = ("hellboy", "leonardo", "Excalibur", "Service Pistol", "B.P.R.D. Training")
MIKEY = ("hellboy", "michelangelo", "Excalibur", "Service Pistol", "B.P.R.D. Training")


def zone_count(game, pos: int) -> int:
    return len(game.board.zones(pos))


def place_with_more_zones(game, table, cfg, mover: str, anchor: str) -> None:
    """`mover` on a free space adjacent to `anchor` that belongs to MORE zones than the anchor's space (so the anchor's
    fighter is in fewer zones than the mover)."""
    pos = game.fighters[anchor].pos
    taken = {f.pos for f in game.fighters.values() if f.alive}
    space = next((s for s in sorted(game.board.adj[pos]) if s not in taken and zone_count(game, s) > zone_count(game, pos)), None)
    if space is None:                                           # none next to this space: move the anchor to the pair
        pair = next((a, b) for a in sorted(game.board.spaces) for b in sorted(game.board.adj[a])
                    if zone_count(game, a) < zone_count(game, b) and a not in taken and b not in taken)
        game.fighters[anchor].pos, space = pair
        table.positions[cfg.nicknames[anchor]] = pair[0]
    game.fighters[mover].pos = space
    table.positions[cfg.nicknames[mover]] = space


# ---------------------------------------------------------------- Leonardo

@with_rig(*LEO)
def test_fearless_leader_adds_2_for_the_other_friendly_fighter_next_to_the_target(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "leonardo", "hellboy")
    put_adjacent(game, table, cfg, "splinter", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Fearless leader", "Katana")
    before = game.fighters["hellboy"].hp
    human_attack(session, table, game, "leonardo", "hellboy", "Fearless leader")
    click(session, table, Event.REVEAL)
    assert before - game.fighters["hellboy"].hp == 3 + 2


@with_rig(*LEO)
def test_fearless_leader_alone_is_a_plain_3(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "leonardo", "hellboy")
    game.fighters["splinter"].pos = max(game.board.spaces)
    table.positions[cfg.nicknames["splinter"]] = max(game.board.spaces)
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Fearless leader", "Katana")
    before = game.fighters["hellboy"].hp
    human_attack(session, table, game, "leonardo", "hellboy", "Fearless leader")
    click(session, table, Event.REVEAL)
    assert before - game.fighters["hellboy"].hp == 3


@with_rig(*LEO)
def test_wise_beyond_his_years_deals_2_more_when_the_rival_is_in_fewer_zones(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    place_with_more_zones(game, table, cfg, "leonardo", "hellboy")
    assert zone_count(game, game.fighters["hellboy"].pos) < zone_count(game, game.fighters["leonardo"].pos)
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Wise beyond his years", "Katana")
    before = game.fighters["hellboy"].hp
    human_attack(session, table, game, "leonardo", "hellboy", "Wise beyond his years")
    msgs = click(session, table, Event.REVEAL)
    assert before - game.fighters["hellboy"].hp == 2 + 2, msgs


@with_rig(*LEO)
def test_wise_beyond_his_years_does_nothing_extra_in_the_same_number_of_zones(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "leonardo", "hellboy")
    pos_l, pos_h = game.fighters["leonardo"].pos, game.fighters["hellboy"].pos
    if zone_count(game, pos_h) < zone_count(game, pos_l):
        pytest.skip("this layout puts the rival in fewer zones")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Wise beyond his years", "Katana")
    before = game.fighters["hellboy"].hp
    human_attack(session, table, game, "leonardo", "hellboy", "Wise beyond his years")
    click(session, table, Event.REVEAL)
    assert before - game.fighters["hellboy"].hp == 2


@with_rig(*LEO)
def test_spatial_awareness_hits_for_1_more_and_deals_you_a_card_when_the_rival_is_in_fewer_zones_than_splinter(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    place_with_more_zones(game, table, cfg, "splinter", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Spatial awareness", "Katana")
    before = game.fighters["hellboy"].hp
    human_attack(session, table, game, "splinter", "hellboy", "Spatial awareness")
    msgs = click(session, table, Event.REVEAL)
    assert before - game.fighters["hellboy"].hp == 3 + 1, msgs
    assert table.human_deals == [1]
    assert len(game.players[1].hand) == 2 - 1 + 1


@with_rig(*LEO)
def test_i_have_a_plan_cancels_the_rivals_card_and_ignores_its_value_when_you_pay_a_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "leonardo", "hellboy")
    bot_defends_with(session, game, "B.P.R.D. Training", monkeypatch)
    human_hand(table, game, "I have a plan", "Katana", "Quick strike")
    before = game.fighters["hellboy"].hp
    human_attack(session, table, game, "leonardo", "hellboy", "I have a plan")
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.card_owner == 1, req
    press(session, table, True)
    paid = card_ids(game, 1, "Katana")[0]                       # the price: the human puts a card on their pile
    table.human_discard.append(paid)
    table.human_count -= 1
    click(session, table, Event.CHOICE, {"i": 1})
    assert session.pending is None, session.pending
    assert before - game.fighters["hellboy"].hp == 2            # B.P.R.D. Training's defense was ignored


@with_rig(*LEO)
def test_i_have_a_plan_declined_leaves_the_rivals_card_alone(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "leonardo", "hellboy")
    bot_defends_with(session, game, "B.P.R.D. Training", monkeypatch)
    human_hand(table, game, "I have a plan", "Katana")
    before = game.fighters["hellboy"].hp
    human_attack(session, table, game, "leonardo", "hellboy", "I have a plan")
    click(session, table, Event.REVEAL)
    press(session, table, False)
    assert game.fighters["hellboy"].hp == before


# ---------------------------------------------------------------- Michelangelo

@with_rig(*MIKEY)
def test_hi_yaaaaah_hits_an_adjacent_rival_for_1_and_gains_an_action_for_a_card_on_the_deck_bottom(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "mikey", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Hi-Yaaaaah!!", "Boisterous Beatdown", "Nunchaku")
    before, actions = game.fighters["hellboy"].hp, game.actions_left
    human_attack(session, table, game, "mikey", "hellboy", "Hi-Yaaaaah!!")
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.card_owner == 1, req
    press(session, table, True)
    table.human_count -= 1                                       # the card goes to the bottom of their deck by hand
    click(session, table, Event.CHOICE, {"i": 1})
    lost = before - game.fighters["hellboy"].hp
    assert lost >= 1 + 1, lost                                   # the blow and the 1 damage of the AFTER
    assert game.actions_left == actions                          # the attack cost 1 and the card gave 1 back


@with_rig(*MIKEY)
def test_guaranteed_delivery_asks_for_the_card_by_hand_and_finishes_the_combat(rig, monkeypatch):
    """The human puts the price (a hand card) on the bottom of their deck by hand; the engine does not know which card it was,
    so the AFTER's "if your hand is empty" still reads the engine's hand (live-only risk, docs/heroes/michelangelo.md)."""
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "mikey", "hellboy")
    bot_defends_with(session, game, "B.P.R.D. Training", monkeypatch)
    human_hand(table, game, "Guaranteed Delivery", "Nunchaku")
    human_attack(session, table, game, "mikey", "hellboy", "Guaranteed Delivery")
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.card_owner == 1, req
    press(session, table, True)
    table.human_count -= 1                                       # their card goes to the bottom of the deck, by hand
    click(session, table, Event.CHOICE, {"i": 1})
    assert session.pending is None and session.effect_run is None


@with_rig(*MIKEY)
def test_guaranteed_delivery_declined_changes_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "mikey", "hellboy")
    bot_defends_with(session, game, "B.P.R.D. Training", monkeypatch)
    human_hand(table, game, "Guaranteed Delivery", "Nunchaku")
    human_attack(session, table, game, "mikey", "hellboy", "Guaranteed Delivery")
    click(session, table, Event.REVEAL)
    press(session, table, False)
    assert session.pending is None and session.effect_run is None


@with_rig(*MIKEY)
def test_shell_insertion_offers_four_effects_and_two_different_ones_are_applied(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Shell Insertion", "Nunchaku")
    foe_hand = len(game.players[0].hand)
    human_scheme(session, table, game, "Shell Insertion")
    req = session.effect_run.awaiting
    assert req.kind == "effect" and req.card_owner == 1 and len(req.options) == 4, req
    shown = labels(session)
    assert len(shown) >= 4
    click(session, table, Event.CHOICE, {"i": 1})                # Opponent discards 1 card
    assert session.effect_run is not None, "two different effects: a second pick is asked"
    second = session.effect_run.awaiting
    assert second.kind == "effect" and 0 not in second.options and len(second.options) == 3
    click(session, table, Event.CHOICE, {"i": 3})                # a different one (the card on the bottom + an action)
    assert len(game.players[0].hand) == foe_hand - 1


# ---------------------------------------------------------------- the same CardID on both sides

SHARING = [(b, h) for b in ("medusa", "leonardo", "donatello", "michelangelo", "raphael")
           for h in ("leonardo", "donatello", "michelangelo", "raphael") if b != h]


def same_id_cards(game, bot_fighter, human_fighter):
    """(human attack card, bot defense card) with the SAME CardID: the table reports one number for two different cards."""
    mine = {c.card_id: c for c in game.players[1].full_set if c.can_attack and c.usable_by(human_fighter.name)}
    for c in game.players[0].full_set:
        if c.card_id in mine and c.can_defend and c.usable_by(bot_fighter.name):
            return mine[c.card_id], c
    return None


@pytest.mark.parametrize("bot,human", SHARING, ids=lambda p: p)
def test_a_card_id_shared_by_both_decks_means_each_sides_own_card_in_a_combat(tmp_path, bot, human, monkeypatch):
    from test_d3_table_effects import build
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, ())
    try:
        found = same_id_cards(game, game.hero(0), game.hero(1))
        if found is None:
            pytest.skip("no CardID pair attack/defense usable by both heroes")
        attack, defense = found
        assert attack.card_id == defense.card_id and attack != defense
        table.bot_hand = [defense.card_id]                      # exactly these two cards: the same number, two cards
        table.bot_deck = [c.card_id for c in game.players[0].full_set if c != defense]
        session.read_bot_hand()
        session.snap = None
        table.human_hand, table.human_count = [attack.card_id], 1
        put_adjacent(game, table, cfg, game.hero(1).fid, game.hero(0).fid)
        monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: next(c for c in g.players[0].hand if c == defense))
        human_attack(session, table, game, game.hero(1).fid, game.hero(0).fid, attack.title)
        msgs = click(session, table, Event.REVEAL)
        if session.pending is not None and session.pending.kind != "human_attacks" or said(msgs, "potenciar"):
            msgs += click(session, table, Event.NO_BOOST)            # Turtle power! offers its free BOOST
        assert said(msgs, f"ataca con {attack.title}") and said(msgs, f"defiende con {defense.title}"), msgs
        assert not said(msgs, "ilegal")
    finally:
        client.close()
        fake.close()
