"""Ciri on the engine, bot side (player 0 plays her, the controllers answer): the SOURCE counter (the Source cards in her discard pile),
UNCONTAINABLE POWER (her cards' effects cannot be canceled at SOURCE 7), the tiered cards at every threshold, Ihuarraquax's two cards,
Channel the source, Searching strike and the ongoing Unicorn ally. The human side (panel, FakeTTS) is in tests/test_ciri_human.py and the
full games in tests/test_ciri_matrix.py."""
from __future__ import annotations

import pytest

from conftest import card, give
from sparring.state import Game
from test_bigfoot_effects import Answers, wall
from test_effects_combat import hand_filler, pair, put_adjacent


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Ciri = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("ciri", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def set_source(g, n, player=0, played=None):
    """Exactly `n` Source cards in the discard pile of `player`, never the first copy of the card titled `played` (the one a test gives
    by title)."""
    st = g.players[player]
    st.discard.clear()
    first = None if played is None else next(c for c in st.full_set if c.title == played)
    source = [c for c in st.full_set if "source" in c.tags and c is not first]
    for c in source[len(source) - n:] if n else []:
        for pile in (st.deck, st.hand):
            if c in pile:
                pile.remove(c)
        st.discard.append(c)
    assert g.counter(player, "source") == n


def at_range(g, fid, near="ciri", spaces=1, free=True):
    """Moves `fid` to a free space exactly `spaces` along the adjacency from `near`."""
    taken = {f.pos for f in g.fighters.values() if f.alive and f.fid != fid}
    spot = next(s for s in sorted(g.board.spaces) if g.board.spaces_apart(g.fighters[near].pos, s) == spaces and s not in taken)
    g.fighters[fid].pos = spot
    return spot


# ---------------------------------------------------------------- the hero and the counter

def test_ciri_is_a_melee_hero_with_ihuarraquax_and_a_source_counter(bprd):
    g = mk(bprd)
    c, i = g.fighters["ciri"], g.fighters["ihuarraquax"]
    assert (c.hp, c.move, c.ranged, c.name) == (15, 2, False, "Ciri")
    assert (i.hp, i.move, i.ranged, i.hero, i.name) == (7, 2, False, False, "Ihuarraquax")
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert "ciri" in g.fx.dsl_heroes
    assert sum("source" in c.tags for c in deck) == 13                 # the 13 orbs: the dial of the bag goes to 13


def test_the_source_is_the_number_of_source_cards_in_the_discard_pile(bprd):
    g = mk(bprd)
    assert g.counter(0, "source") == 0
    g.players[0].discard.append(card(g, 0, "Lion cub of Cintra"))
    g.players[0].discard.append(card(g, 0, "Blink"))                  # no orb
    g.players[0].discard.append(card(g, 0, "Zireael"))
    assert g.counter(0, "source") == 2
    assert g.counters(0) == {"source": 2}


# ---------------------------------------------------------------- Lion cub of Cintra, Zireael

@pytest.mark.parametrize("source,value", [(0, 2), (1, 4), (4, 4), (5, 7), (12, 7)])
def test_lion_cub_of_cintra_is_two_four_or_seven(bprd, source, value):
    g = mk(bprd)
    c, h = pair(g, "ciri", "hellboy")
    set_source(g, source, played="Lion cub of Cintra")
    res = g.attack(c, h, give(g, 0, "Lion cub of Cintra"), None)
    assert res.atk_value == value and h.hp == h.max_hp - value


@pytest.mark.parametrize("source,value", [(2, 2), (3, 4), (5, 4), (12, 4)])
def test_zireael_is_two_or_four_attacking(bprd, source, value):
    g = mk(bprd)
    c, h = pair(g, "ciri", "hellboy")
    set_source(g, source, played="Zireael")
    assert g.attack(c, h, give(g, 0, "Zireael"), None).atk_value == value


def test_zireael_is_four_defending_too(bprd):
    g = mk(bprd, turn=1)
    c, h = pair(g, "ciri", "hellboy")
    g.actions_left = 2
    set_source(g, 3, played="Zireael")
    attack = give(g, 1, next(x.title for x in g.players[1].deck if x.can_attack and (x.value or 0) == 4))
    assert g.attack(h, c, attack, give(g, 0, "Zireael")).def_value == 4


def test_zireael_at_source_five_makes_the_opponent_discard_a_random_card(bprd):
    g = mk(bprd)
    c, h = pair(g, "ciri", "hellboy")
    set_source(g, 5, played="Zireael")
    hand_filler(g, 1, 3)
    pile = len(g.players[1].discard)
    g.attack(c, h, give(g, 0, "Zireael"), None)
    assert len(g.players[1].hand) == 2 and len(g.players[1].discard) == pile + 1


@pytest.mark.parametrize("source", [3, 4])
def test_zireael_below_source_five_takes_no_card(bprd, source):
    g = mk(bprd)
    c, h = pair(g, "ciri", "hellboy")
    set_source(g, source, played="Zireael")
    hand_filler(g, 1, 3)
    g.attack(c, h, give(g, 0, "Zireael"), None)
    assert len(g.players[1].hand) == 3


def test_zireael_with_the_opponents_hand_empty_discards_nothing(bprd):
    g = mk(bprd)
    c, h = pair(g, "ciri", "hellboy")
    set_source(g, 5, played="Zireael")
    g.attack(c, h, give(g, 0, "Zireael"), None)
    assert g.players[1].hand == []


# ---------------------------------------------------------------- Pushed to the brink

@pytest.mark.parametrize("source,damage", [(0, 0), (1, 0), (2, 1), (6, 1)])
def test_pushed_to_the_brink_deals_one_damage_from_source_two(bprd, source, damage):
    g = mk(bprd, "leonardo")
    c, leo = pair(g, "ciri", "leonardo")
    set_source(g, source, played="Pushed to the brink")
    g.attack(c, leo, give(g, 0, "Pushed to the brink"), wall(g))
    assert leo.hp == leo.max_hp - damage


def test_pushed_to_the_brink_at_source_seven_hits_for_two_instead_of_one(bprd):
    g = mk(bprd, "leonardo")
    c, leo = pair(g, "ciri", "leonardo")
    set_source(g, 7, played="Pushed to the brink")
    g.attack(c, leo, give(g, 0, "Pushed to the brink"), wall(g))
    assert leo.hp == leo.max_hp - 2                                     # the highest tier only, not 1 + 2


def test_pushed_to_the_brink_at_seven_picks_among_the_fighters_within_three(bprd):
    g = mk(bprd, "hellboy")
    c, h = pair(g, "ciri", "hellboy")
    set_source(g, 7, played="Pushed to the brink")
    lobster = g.fighters["lobster"]
    at_range(g, "lobster", spaces=3)
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or ["lobster"]]
    g.attack(c, h, give(g, 0, "Pushed to the brink"), None)
    assert len(seen) == 1 and set(seen[0].options) == {"hellboy", "lobster"}          # both are within 3 spaces
    assert lobster.hp == lobster.max_hp - 2 and h.hp == h.max_hp - 3                  # the 3 of the combat on him, the 2 of the card on the one she picked


def test_pushed_to_the_brink_at_seven_never_picks_a_fighter_farther_than_three(bprd):
    g = mk(bprd, "hellboy")
    c, h = pair(g, "ciri", "hellboy")
    set_source(g, 7, played="Pushed to the brink")
    lobster = g.fighters["lobster"]
    lobster.pos = next(s for s in sorted(bprd.spaces) if bprd.spaces_apart(c.pos, s) > 3 and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.attack(c, h, give(g, 0, "Pushed to the brink"), None)
    assert lobster.hp == lobster.max_hp and h.hp == h.max_hp - 3 - 2                  # the only one in range takes both


# ---------------------------------------------------------------- Child of the Elder Blood

def zone_mates(g, *fids):
    """Puts each fid in Ciri's zone (other than her own space), distinct free spaces."""
    c = g.fighters["ciri"]
    taken = {f.pos for f in g.fighters.values() if f.alive and f.fid not in fids}
    spots = [s for s in sorted(g.board.spaces) if s != c.pos and g.board.share_zone(c.pos, s) and s not in taken]
    for fid, s in zip(fids, spots):
        g.fighters[fid].pos = s


@pytest.mark.parametrize("source,damage", [(3, 0), (4, 1), (8, 1), (9, 3), (11, 3)])
def test_child_of_the_elder_blood_hits_every_other_fighter_in_her_zone(bprd, source, damage):
    g = mk(bprd, "hellboy")
    g.actions_left = 2
    c, h = pair(g, "ciri", "hellboy")
    zone_mates(g, "hellboy", "lobster", "ihuarraquax")
    set_source(g, source, played="Child of the Elder Blood")
    far = next(s for s in sorted(bprd.spaces) if not bprd.share_zone(c.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.players[0].hand.clear()
    g.play_scheme(0, c, give(g, 0, "Child of the Elder Blood"))
    for fid in ("hellboy", "lobster", "ihuarraquax"):                       # her own sidekick is an "other fighter" too
        assert g.fighters[fid].hp == g.fighters[fid].max_hp - damage, fid
    assert c.hp == c.max_hp


def test_child_of_the_elder_blood_leaves_the_fighters_outside_her_zone_alone(bprd):
    g = mk(bprd, "hellboy")
    g.actions_left = 2
    c, h = pair(g, "ciri", "hellboy")
    zone_mates(g, "hellboy")
    outside = next(s for s in sorted(bprd.spaces) if not bprd.share_zone(c.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.fighters["lobster"].pos = outside
    set_source(g, 9, played="Child of the Elder Blood")
    g.play_scheme(0, c, give(g, 0, "Child of the Elder Blood"))
    assert g.fighters["lobster"].hp == g.fighters["lobster"].max_hp and h.hp == h.max_hp - 3


# ---------------------------------------------------------------- Bane of the Aen Elle, Blink (movement through fighters)

def corridor(board):
    """(a, b, c): c is two spaces from a and b is the only space between them."""
    for a in sorted(board.spaces):
        for b in sorted(board.adj[a]):
            for c in sorted(board.adj[b]):
                if c != a and c not in board.adj[a] and board.adj[a] & board.adj[c] == {b}:
                    return a, b, c
    raise AssertionError("no corridor on this map")


def test_blink_moves_ciri_up_to_three_through_opposing_fighters(bprd):
    g = mk(bprd, "leonardo")
    c, leo = pair(g, "ciri", "leonardo")
    a, b, far = corridor(bprd)
    c.pos, leo.pos = a, b
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [far] if far in req.options else [req.options[-1]]]
    g.attack(c, leo, give(g, 0, "Blink"), wall(g))
    assert seen and seen[0].extra["steps"] == 3 and seen[0].extra["through"]
    assert c.pos == far                                                    # she crossed the rival standing between


def test_blink_is_up_to_three_so_ciri_may_stay(bprd):
    g = mk(bprd, "leonardo")
    c, leo = pair(g, "ciri", "leonardo")
    spot = c.pos
    g.controllers[0].queue = [[]]
    g.attack(c, leo, give(g, 0, "Blink"), wall(g))
    assert c.pos == spot


def test_bane_of_the_aen_elle_moves_ihuarraquax_and_hurts_a_rival_he_crossed(bprd):
    g = mk(bprd, "leonardo")
    i, leo = pair(g, "ihuarraquax", "leonardo")
    a, b, far = corridor(bprd)
    i.pos, leo.pos = a, b
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [far] if far in req.options else [req.options[-1]]]
    g.attack(i, leo, give(g, 0, "Bane of the Aen Elle"), wall(g))
    assert seen[0].extra["steps"] == 4 and seen[0].extra["through"]
    assert i.pos == far and leo.hp == leo.max_hp - 1                       # only the move and 1 damage: the combat was walled


def test_bane_of_the_aen_elle_without_crossing_anybody_hurts_nobody(bprd):
    g = mk(bprd, "leonardo")
    i, leo = pair(g, "ihuarraquax", "leonardo")
    spot = i.pos
    g.controllers[0].queue = [[]]
    g.attack(i, leo, give(g, 0, "Bane of the Aen Elle"), wall(g))
    assert i.pos == spot and leo.hp == leo.max_hp


def test_bane_of_the_aen_elle_is_ihuarraquaxs_card_and_blink_is_cirs(bprd):
    g = mk(bprd)
    bane, blink = card(g, 0, "Bane of the Aen Elle"), card(g, 0, "Blink")
    assert bane.usable_by("Ihuarraquax") and not bane.usable_by("Ciri")
    assert blink.usable_by("Ciri") and not blink.usable_by("Ihuarraquax")
    assert card(g, 0, "Parry").usable_by("Ihuarraquax") and card(g, 0, "Parry").usable_by("Ciri")


# ---------------------------------------------------------------- Channel the source

def test_channel_the_source_discards_source_cards_for_two_each(bprd):
    g = mk(bprd)
    c, h = pair(g, "ciri", "hellboy")
    channel = give(g, 0, "Channel the source")
    sources = [give(g, 0, "Lion cub of Cintra"), give(g, 0, "Zireael"), give(g, 0, "Pushed to the brink")]
    blink = give(g, 0, "Blink")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [sources[0].card_id, sources[1].card_id]]
    res = g.attack(c, h, channel, None)
    assert set(seen[0].options) == {s.card_id for s in sources}              # the card without an orb is not offered
    assert seen[0].extra["per_card"] == 2 and seen[0].extra["tag"] == "source"
    assert res.atk_value == 2 + 2 * 2 and h.hp == h.max_hp - 6
    assert sources[0] in g.players[0].discard and sources[1] in g.players[0].discard and blink in g.players[0].hand
    assert g.counter(0, "source") == 2                                      # what she gave up feeds the Source


def test_channel_the_source_may_discard_nothing(bprd):
    g = mk(bprd)
    c, h = pair(g, "ciri", "hellboy")
    give(g, 0, "Lion cub of Cintra")
    g.controllers[0].queue = [[]]
    res = g.attack(c, h, give(g, 0, "Channel the source"), None)
    assert res.atk_value == 2 and g.counter(0, "source") == 0


def test_channel_the_source_with_no_source_card_in_hand_asks_nothing(bprd):
    g = mk(bprd)
    c, h = pair(g, "ciri", "hellboy")
    give(g, 0, "Blink")
    res = g.attack(c, h, give(g, 0, "Channel the source"), None)
    assert res.atk_value == 2


# ---------------------------------------------------------------- Parry and UNCONTAINABLE POWER

def test_parry_cancels_the_effects_of_an_opposing_card(bprd):
    g = mk(bprd, "liz-sherman", turn=1)
    c, liz = pair(g, "ciri", "liz")
    g.actions_left = 2
    set_source(g, 0)
    flow = g.begin_attack(liz, c, give(g, 1, next(x.title for x in g.players[1].deck if x.can_attack)), give(g, 0, "Parry"))
    flow.run()
    assert "atk" in flow.result.cancelled


@pytest.mark.parametrize("source,canceled", [(6, True), (7, False), (12, False)])
def test_uncontainable_power_at_source_seven_protects_her_cards_from_cancelling(bprd, source, canceled):
    g = mk(bprd, "liz-sherman")
    c, liz = pair(g, "ciri", "liz")
    set_source(g, source, played="Pushed to the brink")
    flow = g.begin_attack(c, liz, give(g, 0, "Pushed to the brink"), give(g, 1, "Feint"))
    flow.run()
    assert ("atk" in flow.result.cancelled) is canceled


def test_uncontainable_power_covers_ihuarraquaxs_cards_too(bprd):
    g = mk(bprd, "liz-sherman")
    i, liz = pair(g, "ihuarraquax", "liz")
    set_source(g, 7)
    flow = g.begin_attack(i, liz, give(g, 0, "Bane of the Aen Elle"), give(g, 1, "Feint"))
    flow.run()
    assert "atk" not in flow.result.cancelled


def test_uncontainable_power_does_not_protect_the_rivals_cards_from_parry(bprd):
    g = mk(bprd, "liz-sherman", turn=1)
    c, liz = pair(g, "ciri", "liz")
    g.actions_left = 2
    set_source(g, 13)
    flow = g.begin_attack(liz, c, give(g, 1, next(x.title for x in g.players[1].deck if x.can_attack)), give(g, 0, "Parry"))
    flow.run()
    assert "atk" in flow.result.cancelled


def test_the_effects_of_a_ciri_card_run_as_printed_through_a_cancel_at_source_seven(bprd):
    g = mk(bprd, "liz-sherman")
    c, liz = pair(g, "ciri", "liz")
    set_source(g, 7, played="Pushed to the brink")
    flow = g.begin_attack(c, liz, give(g, 0, "Pushed to the brink"), give(g, 1, "Feint"))
    flow.run()
    assert liz.hp <= liz.max_hp - 2                                           # the AFTER of SOURCE 7 dealt its 2 damage


# ---------------------------------------------------------------- Searching strike

def test_searching_strike_takes_a_source_card_from_the_deck_when_she_wins(bprd):
    g = mk(bprd, "hellboy")
    i, h = pair(g, "ihuarraquax", "hellboy")
    strike = give(g, 0, "Searching strike")
    deck = len(g.players[0].deck)
    g.controllers[0].queue = [[True], lambda req: [req.options[0]]]
    g.attack(i, h, strike, None)
    taken = [x for x in g.players[0].hand if "source" in x.tags]
    assert len(taken) == 1 and len(g.players[0].deck) == deck - 1


def test_searching_strike_offers_only_source_cards(bprd):
    g = mk(bprd, "hellboy")
    i, h = pair(g, "ihuarraquax", "hellboy")
    seen = []
    g.controllers[0].queue = [[True], lambda req: seen.append(req) or [req.options[0]]]
    g.attack(i, h, give(g, 0, "Searching strike"), None)
    by_id = {c.card_id: c for c in g.players[0].full_set}
    assert seen and all("source" in by_id[x].tags for x in seen[0].options)


def test_searching_strike_does_nothing_when_she_loses(bprd):
    g = mk(bprd, "leonardo")
    i, leo = pair(g, "ihuarraquax", "leonardo")
    strike = give(g, 0, "Searching strike")
    deck = len(g.players[0].deck)
    g.attack(i, leo, strike, wall(g))
    assert len(g.players[0].deck) == deck and not g.players[0].hand


def test_a_tie_is_not_a_win_so_searching_strike_finds_nothing(bprd):
    """The global rule (Iván, 2026-11-07/08): on a tie the defender wins, the attacker only wins if combat damage lands."""
    g = mk(bprd, "hellboy")
    i, h = pair(g, "ihuarraquax", "hellboy")
    strike = give(g, 0, "Searching strike")
    training = give(g, 1, "B.P.R.D. Training")                        # a defense of value 3 against the 3 of the strike
    deck = len(g.players[0].deck)
    res = g.attack(i, h, strike, training)
    assert res.atk_value == res.def_value == 3 and not res.attacker_won
    assert len(g.players[0].deck) == deck


def test_searching_strike_with_no_source_card_left_in_the_deck_takes_nothing(bprd):
    g = mk(bprd, "hellboy")
    i, h = pair(g, "ihuarraquax", "hellboy")
    g.players[0].deck[:] = [c for c in g.players[0].deck if "source" not in c.tags]
    g.controllers[0].queue = [[True]]
    g.attack(i, h, give(g, 0, "Searching strike"), None)
    assert not [x for x in g.players[0].hand if "source" in x.tags]


def test_searching_strike_is_a_may_the_bot_can_decline(bprd):
    g = mk(bprd, "hellboy")
    i, h = pair(g, "ihuarraquax", "hellboy")
    strike = give(g, 0, "Searching strike")
    deck = len(g.players[0].deck)
    g.controllers[0].queue = [[False]]
    g.attack(i, h, strike, None)
    assert len(g.players[0].deck) == deck


# ---------------------------------------------------------------- The lady of space and time

def test_the_lady_returns_a_discarded_card_to_the_top_of_the_deck_from_source_three(bprd):
    g = mk(bprd, "leonardo")
    c, leo = pair(g, "ciri", "leonardo")
    set_source(g, 3, played="The lady of space and time")
    target = g.players[0].discard[0]
    g.controllers[0].queue = [lambda req: [target.card_id]]
    g.attack(c, leo, give(g, 0, "The lady of space and time"), wall(g))
    assert g.players[0].deck[0] == target and target not in g.players[0].discard
    assert not g.players[0].hand


def test_the_lady_at_source_eight_puts_the_card_in_the_hand_and_draws_one(bprd):
    g = mk(bprd, "leonardo")
    c, leo = pair(g, "ciri", "leonardo")
    set_source(g, 8, played="The lady of space and time")
    target = g.players[0].discard[0]
    g.controllers[0].queue = [lambda req: [target.card_id]]
    g.attack(c, leo, give(g, 0, "The lady of space and time"), wall(g))
    assert target in g.players[0].hand and len(g.players[0].hand) == 2
    assert g.players[0].deck[0] != target


def test_the_lady_below_source_three_does_nothing(bprd):
    g = mk(bprd, "leonardo")
    c, leo = pair(g, "ciri", "leonardo")
    set_source(g, 2, played="The lady of space and time")
    top = g.players[0].deck[0]
    g.attack(c, leo, give(g, 0, "The lady of space and time"), wall(g))
    assert g.players[0].deck[0] == top and not g.players[0].hand


# ---------------------------------------------------------------- Unicorn ally

def play_unicorn(g, c):
    g.actions_left = 2
    g.play_scheme(0, c, give(g, 0, "Unicorn ally"))


def test_unicorn_ally_heals_two_and_stays_in_play(bprd):
    g = mk(bprd, "hellboy")
    c, h = pair(g, "ciri", "hellboy")
    c.hp = 10
    play_unicorn(g, c)
    assert c.hp == 12
    assert g.fx.ongoing_card_id(0) is not None


def test_unicorn_ally_heal_stops_at_her_maximum(bprd):
    g = mk(bprd, "hellboy")
    c, h = pair(g, "ciri", "hellboy")
    c.hp = 14
    play_unicorn(g, c)
    assert c.hp == 15


def test_unicorn_ally_draws_a_card_after_each_combat_ciri_or_her_sidekick_is_in(bprd):
    g = mk(bprd, "leonardo")
    c, leo = pair(g, "ciri", "leonardo")
    play_unicorn(g, c)
    g.players[0].hand.clear()
    g.attack(c, leo, give(g, 0, "Lion cub of Cintra"), wall(g))
    assert len(g.players[0].hand) == 1                                       # the card it played is gone, one was drawn
    g.actions_left = 2
    i = g.fighters["ihuarraquax"]
    put_adjacent(g, "ihuarraquax", "leonardo")
    g.attack(i, leo, give(g, 0, "Searching strike"), wall(g))
    assert len(g.players[0].hand) == 2


def test_unicorn_ally_draws_after_the_rivals_attack_too(bprd):
    g = mk(bprd, "leonardo", turn=1)
    c, leo = pair(g, "ciri", "leonardo")
    g.turn = 0
    play_unicorn(g, c)
    g.turn = 1
    g.actions_left = 2
    g.players[0].hand.clear()
    attack = give(g, 1, next(x.title for x in g.players[1].deck if x.can_attack))
    g.attack(leo, c, attack, None)
    assert len(g.players[0].hand) == 1


def test_unicorn_ally_is_discarded_at_the_end_of_the_turn_with_five_cards_in_hand(bprd):
    g = mk(bprd, "hellboy")
    c, h = pair(g, "ciri", "hellboy")
    play_unicorn(g, c)
    g.players[0].hand.clear()
    hand_filler(g, 0, 5)
    card_id = g.fx.ongoing_card_id(0)
    g.end_turn()
    assert g.fx.ongoing_card_id(0) is None
    assert any(x.card_id == card_id for x in g.players[0].discard)


def test_unicorn_ally_stays_with_four_cards_in_hand(bprd):
    g = mk(bprd, "hellboy")
    c, h = pair(g, "ciri", "hellboy")
    play_unicorn(g, c)
    g.players[0].hand.clear()
    hand_filler(g, 0, 4)
    g.end_turn()
    assert g.fx.ongoing_card_id(0) is not None


def test_unicorn_ally_is_replaced_by_the_next_ongoing_scheme(bprd):
    g = mk(bprd, "hellboy")
    c, h = pair(g, "ciri", "hellboy")
    play_unicorn(g, c)
    first = g.fx.ongoing_card_id(0)
    g.actions_left = 2
    g.play_scheme(0, c, give(g, 0, "Unicorn ally", 1))
    assert g.fx.ongoing_card_id(0) not in (None, first)


# ---------------------------------------------------------------- every card is on the interpreter, with the printed numbers

REAL = {
    "Lion cub of Cintra": ("attack", 2, 2, 3), "Channel the source": ("attack", 2, 3, 3), "Bane of the Aen Elle": ("attack", 4, 4, 3),
    "Pushed to the brink": ("versatile", 3, 2, 3), "Zireael": ("versatile", 2, 2, 3), "The lady of space and time": ("versatile", 2, 2, 2),
    "Blink": ("versatile", 4, 1, 3), "Searching strike": ("versatile", 3, 3, 3), "Parry": ("defense", 3, 1, 3),
    "Child of the Elder Blood": ("scheme", None, 2, 2), "Unicorn ally": ("scheme", None, 2, 2),
}


def test_every_card_has_its_printed_numbers_and_an_entry_in_the_effects(bprd):
    from sparring.effects.model import load_effects
    g = mk(bprd)
    fx = load_effects("ciri")
    deck = g.players[0].full_set
    for title, (kind, value, boost, copies) in REAL.items():
        cards = [c for c in deck if c.title == title]
        assert len(cards) == copies and (cards[0].type, cards[0].value, cards[0].boost) == (kind, value, boost), title
        assert fx.card(title) is not None
    assert sum(c for *_, c in REAL.values()) == 30
