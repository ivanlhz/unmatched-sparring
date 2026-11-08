"""Golden Bat on the engine, bot side (player 0 plays Golden Bat, the controllers answer): THE FIRST SUPERHERO (+2 to his attacks while
the owner has not taken a Maneuver action this turn), the zone punch, the random discard, Sight Beyond Sight's look and reorder,
Terrifying Roar's status on every fighter, the zone test of Like a Flash of Golden Light, the pile cards and the two schemes, with the
numbers printed on the cards. The human side (panel, FakeTTS) goes through the same interpreter: tests/test_golden_bat_matrix.py plays
full games in both seats."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.ai_effects import EffectAI
from sparring.effects.choose import ChoiceRequest
from sparring.effects.events import tracked
from sparring.effects.state import EffectState
from sparring.search.adapter import card_worth
from sparring.state import Game
from test_bigfoot_effects import Answers, start_turn, wall
from test_effects_combat import pair


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Golden Bat = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("golden-bat", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def in_zone_of(g, fid, avoid=()):
    """A free space that shares a zone with `fid`'s space (not adjacent to it, when there is one)."""
    here = g.fighters[fid].pos
    free = [s for s in sorted(g.board.spaces) if s != here and g.board.share_zone(here, s) and s not in avoid
            and all(f.pos != s for f in g.fighters.values() if f.alive)]
    return next((s for s in free if s not in g.board.adj[here]), free[0])


def rival_attack(g, at_least):
    """The weakest card of the rival's own hero that attacks with at least that printed value, in hand."""
    options = [c for c in g.players[1].deck if c.can_attack and c.fighter == g.hero(1).name and (c.value or 0) >= at_least]
    return give(g, 1, min(options, key=lambda c: (c.value, c.card_id)).title)


# ---------------------------------------------------------------- the hero card

def test_golden_bat_is_a_melee_hero_with_18_life_move_3_and_no_sidekick(bprd):
    g = mk(bprd)
    b = g.fighters["bat"]
    assert (b.hp, b.move, b.ranged, b.reach) == (18, 3, False, 0)
    assert [f.fid for f in g.own(0)] == ["bat"]
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629


# ---------------------------------------------------------------- THE FIRST SUPERHERO

def test_the_first_superhero_adds_two_to_an_attack_when_no_maneuver_was_taken(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    res = g.attack(b, h, give(g, 0, "Super Strength"), None)
    assert res.atk_value == 5 + 2 and h.hp == h.max_hp - 7
    assert res.atk_parts[1] == "THE FIRST SUPERHERO (+2)"


def test_the_first_superhero_is_lost_for_the_turn_after_a_maneuver_and_back_the_next_turn(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.actions_left = 3
    assert g.attack_bonus(b, h) == 2
    g.maneuver(0, {})
    assert g.fx.maneuvers == 1 and g.attack_bonus(b, h) == 0
    res = g.attack(b, h, give(g, 0, "Super Strength"), None)
    assert res.atk_value == 5
    start_turn(g)
    assert g.fx.maneuvers == 0 and g.attack_bonus(b, h) == 2


def test_other_actions_do_not_take_the_bonus_away(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.actions_left = 3
    g.attack(b, h, give(g, 0, "Super Strength"), None)
    assert g.fx.maneuvers == 0
    assert g.attack(b, h, give(g, 0, "Super Strength", 1), None).atk_value == 7


def test_the_bonus_is_for_attacks_not_for_a_defense(bprd):
    g = mk(bprd, turn=1)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.actions_left = 2
    attack = rival_attack(g, 5)
    res = g.attack(h, b, attack, give(g, 0, "He Laughs at Your Feebleness"))
    assert res.def_value == 5


def test_a_versatile_card_played_as_an_attack_gets_the_bonus(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    assert g.attack(b, h, give(g, 0, "Skirmish"), None).atk_value == 4 + 2


def test_the_rivals_attacks_never_get_it_and_a_rival_maneuver_does_not_count(bprd):
    g = mk(bprd, turn=1)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    assert g.attack_bonus(h, b) == 0 and not g.fx.maneuvered(0)
    g.fx.maneuvers = 1
    assert g.fx.maneuvered(1) and not g.fx.maneuvered(0)


def test_the_maneuver_tally_is_tracked_only_for_him_saved_cloned_and_loaded(bprd):
    g = mk(bprd)
    assert "maneuvers" in tracked(frozenset(g.fx.dsl_heroes))
    g.fx.maneuvers = 1
    assert EffectState.from_dict(g.fx.to_dict()).maneuvers == 1 and g.fx.copy().maneuvers == 1
    assert "maneuvers" not in EffectState().to_dict()
    other = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("bullseye", "hellboy"), bot_player=0)
    assert "maneuvers" not in tracked(frozenset(other.fx.dsl_heroes))


# ---------------------------------------------------------------- Super Strength, He Laughs at Your Feebleness

def test_super_strength_and_he_laughs_have_no_effects(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.maneuver(0, {})
    res = g.attack(b, h, give(g, 0, "Super Strength"), None)
    assert res.atk_value == 5 and h.hp == h.max_hp - 5
    g2 = mk(bprd, turn=1)
    b2, h2 = pair(g2, "bat", "hellboy")
    attack = rival_attack(g2, 4)
    assert g2.attack(h2, b2, attack, give(g2, 0, "He Laughs at Your Feebleness")).def_value == 5 and b2.hp == b2.max_hp


# ---------------------------------------------------------------- Vaporizing Eyebeams

def test_vaporizing_eyebeams_makes_the_rival_discard_one_random_card(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    others = list(g.players[1].deck[:3])
    for c in others:
        g.players[1].deck.remove(c)
        g.players[1].hand.append(c)
    g.attack(b, h, give(g, 0, "Vaporizing Eyebeams"), None)
    gone = [c for c in others if c in g.players[1].discard]
    assert len(g.players[1].hand) == 2 and len(gone) == 1


def test_vaporizing_eyebeams_with_an_empty_rival_hand_does_nothing(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    g.attack(b, h, give(g, 0, "Vaporizing Eyebeams"), None)
    assert g.players[1].hand == [] and g.players[1].discard == []


def test_vaporizing_eyebeams_discards_a_card_even_when_the_combat_is_lost(bprd):
    g = mk(bprd, "leonardo")
    b, leo = pair(g, "bat", "leonardo")
    start_turn(g)
    block = wall(g)
    spare = [c for c in g.players[1].deck][:1]
    g.players[1].deck.remove(spare[0])
    g.players[1].hand.append(spare[0])
    res = g.attack(b, leo, give(g, 0, "Vaporizing Eyebeams"), block)
    assert not res.attacker_won and spare[0] in g.players[1].discard


# ---------------------------------------------------------------- A Punch to Shake the Earth

def test_the_punch_hits_each_opposing_fighter_in_his_zone_for_two_when_he_won(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    lobster = g.fighters["lobster"]
    lobster.pos = in_zone_of(g, "bat", avoid=(h.pos,))
    start_turn(g)
    g.maneuver(0, {})                                    # no bonus: the value is the printed 1
    res = g.attack(b, h, give(g, 0, "A Punch to Shake the Earth"), None)
    assert res.attacker_won and h.hp == h.max_hp - 1 - 2           # 1 of combat, 2 of effect
    assert lobster.hp == lobster.max_hp - 2


def test_the_punch_deals_one_when_the_combat_was_not_won(bprd):
    g = mk(bprd, "leonardo")
    b, leo = pair(g, "bat", "leonardo")
    start_turn(g)
    block = wall(g)
    res = g.attack(b, leo, give(g, 0, "A Punch to Shake the Earth"), block)
    assert not res.attacker_won and leo.hp == leo.max_hp - 1


def test_the_punch_leaves_alone_the_rival_fighters_outside_the_zone_and_never_hits_his_own_side(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    lobster = g.fighters["lobster"]
    assert not bprd.share_zone(b.pos, lobster.pos)
    start_turn(g)
    g.maneuver(0, {})
    g.attack(b, h, give(g, 0, "A Punch to Shake the Earth"), None)
    assert lobster.hp == lobster.max_hp and b.hp == b.max_hp


# ---------------------------------------------------------------- Sight Beyond Sight

def test_sight_beyond_sight_puts_the_rivals_top_three_back_in_the_order_the_owner_chooses(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    top = [c.card_id for c in g.players[1].deck[:3]]
    rest = [c.card_id for c in g.players[1].deck[3:]]
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or list(reversed(req.options))]
    g.attack(b, h, give(g, 0, "Sight Beyond Sight"), None)
    assert len(seen) == 1 and seen[0].kind == "order" and seen[0].extra["of"] == 1 and sorted(seen[0].options) == sorted(top)
    assert [c.card_id for c in g.players[1].deck] == list(reversed(top)) + rest
    assert len(g.players[1].hand) == 0 and len(g.players[1].discard) == 0


def test_the_bot_orders_the_rivals_top_cards_worst_first(bprd):
    g = mk(bprd)
    top = g.players[1].deck[:3]
    req = ChoiceRequest("order", 0, [c.card_id for c in top], 3, 3, None, "k", "order", {"zone": "deck", "purpose": "order", "of": 1}, 0)
    got = EffectAI(0).choose_effect(g, req)
    worth = {c.card_id: card_worth(c) for c in top}
    assert sorted(got) == sorted(worth) and [worth[i] for i in got] == sorted(worth.values())


def test_sight_beyond_sight_with_a_short_deck_looks_at_what_there_is(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    del g.players[1].deck[2:]
    two = [c.card_id for c in g.players[1].deck]
    g.controllers[0].queue = [lambda req: list(reversed(req.options))]
    g.attack(b, h, give(g, 0, "Sight Beyond Sight"), None)
    assert [c.card_id for c in g.players[1].deck] == list(reversed(two))


def test_the_bot_does_not_read_a_humans_real_deck(bprd):
    """The human's deck at the table is physical: the engine holds placeholders, so the bot's card reads and reorders nothing."""
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.controllers[1].human = True                       # the table player: `effects.table.physical` is true for their seat
    before = [c.card_id for c in g.players[1].deck]
    g.controllers[0].queue = []
    g.attack(b, h, give(g, 0, "Sight Beyond Sight"), None)
    assert [c.card_id for c in g.players[1].deck] == before
    assert g.players[0].known.top_of_deck == []


# ---------------------------------------------------------------- Terrifying Roar

def test_terrifying_roar_pins_every_fighter_for_the_turn(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.actions_left = 3
    g.attack(b, h, give(g, 0, "Terrifying Roar"), None)
    pinned = sorted(s["fid"] for s in g.fx.statuses if s["name"] == "cannot_leave_space")
    assert pinned == sorted(f.fid for f in g.fighters.values() if f.alive)       # his own side too
    assert not any(g.fx.can_move(f) for f in g.fighters.values())


def test_terrifying_roar_lasts_until_the_end_of_the_turn_only(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.attack(b, h, give(g, 0, "Terrifying Roar"), None)
    assert g.fx.statuses
    g.end_turn()
    assert not [s for s in g.fx.statuses if s["name"] == "cannot_leave_space"]


def test_terrifying_roar_stops_a_later_move_effect_of_the_same_turn(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.actions_left = 3
    g.attack(b, h, give(g, 0, "Terrifying Roar"), None)
    here = b.pos
    g.controllers[0].queue = [lambda req: [req.options[-1]] if req.options else []]
    g.attack(b, h, give(g, 0, "Like a Flash of Golden Light"), None)
    assert b.pos == here


def test_terrifying_roar_played_in_defense_pins_the_attackers_turn(bprd):
    g = mk(bprd, turn=1)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.actions_left = 2
    attack = rival_attack(g, 4)
    g.attack(h, b, attack, give(g, 0, "Terrifying Roar"))
    assert len([s for s in g.fx.statuses if s["name"] == "cannot_leave_space"]) == 3
    assert all(s["until"] == {"event": "end_of_turn"} for s in g.fx.statuses)


def test_terrifying_roar_cancelled_by_a_feint_does_nothing(bprd):
    g = mk(bprd, "bullseye")
    b, bu = pair(g, "bat", "bullseye")
    start_turn(g)
    res = g.attack(b, bu, give(g, 0, "Terrifying Roar"), give(g, 1, "Feint"))
    assert "atk" in res.cancelled and not g.fx.statuses


# ---------------------------------------------------------------- Skirmish

def test_skirmish_moves_a_fighter_of_the_combat_up_to_two_spaces_when_he_won(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    seen = []
    g.controllers[0].queue = [["hellboy"], lambda req: seen.append(req) or [max(req.options)]]
    start = h.pos
    res = g.attack(b, h, give(g, 0, "Skirmish"), None)
    assert res.attacker_won and seen[0].extra["steps"] == 2 and seen[0].extra["up_to"] and seen[0].extra["fighter"] == "hellboy"
    assert h.pos == max(seen[0].options) != start and bprd.distance(start, h.pos) <= 2


def test_skirmish_may_move_golden_bat_himself(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.controllers[0].queue = [["bat"], lambda req: [max(req.options)]]
    start = b.pos
    g.attack(b, h, give(g, 0, "Skirmish"), None)
    assert b.pos != start and bprd.distance(start, b.pos) <= 2


def test_skirmish_does_nothing_when_the_combat_was_lost(bprd):
    g = mk(bprd, "leonardo")
    b, leo = pair(g, "bat", "leonardo")
    start_turn(g)
    g.maneuver(0, {})                                      # no +2: 4 against the wall's 5
    block = wall(g)
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options)]]
    here, there = b.pos, leo.pos
    res = g.attack(b, leo, give(g, 0, "Skirmish"), block)
    assert not res.attacker_won and not seen and (b.pos, leo.pos) == (here, there)


# ---------------------------------------------------------------- Like a Flash of Golden Light

def _far_from_start(g):
    """After start_turn: a free space where Golden Bat shares no zone with the one he started the turn in, with a free neighbour."""
    start = g.fighters["bat"].pos
    return next(s for s in sorted(g.board.spaces) if not g.board.share_zone(start, s)
                and any(all(f.pos != n for f in g.fighters.values() if f.alive) for n in g.board.adj[s])
                and all(f.pos != s for f in g.fighters.values() if f.alive))


def test_flash_is_four_when_he_shares_no_zone_with_the_space_he_started_in(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.maneuver(0, {})
    b.pos = _far_from_start(g)
    h.pos = next(n for n in sorted(bprd.adj[b.pos]) if all(f.pos != n for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [lambda req: []]
    assert g.attack(b, h, give(g, 0, "Like a Flash of Golden Light"), None).atk_value == 4


def test_flash_is_two_when_he_has_not_moved_or_still_shares_a_zone(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.actions_left = 4
    g.maneuver(0, {})
    g.controllers[0].queue = [lambda req: [], lambda req: []]
    assert g.attack(b, h, give(g, 0, "Like a Flash of Golden Light"), None).atk_value == 2
    near = next(s for s in sorted(bprd.adj[b.pos]) if bprd.share_zone(b.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    b.pos = near
    h.pos = next(n for n in sorted(bprd.adj[b.pos]) if all(f.pos != n for f in g.fighters.values() if f.alive))
    assert g.attack(b, h, give(g, 0, "Like a Flash of Golden Light", 1), None).atk_value == 2


def test_flash_moves_him_up_to_five_spaces_after_the_combat_won_or_lost(bprd):
    g = mk(bprd, "leonardo")
    b, leo = pair(g, "bat", "leonardo")
    start_turn(g)
    block = wall(g)
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options)]]
    start = b.pos
    res = g.attack(b, leo, give(g, 0, "Like a Flash of Golden Light"), block)
    assert not res.attacker_won and seen[0].extra["steps"] == 5 and seen[0].extra["up_to"]
    assert b.pos == max(seen[0].options) != start


def test_flash_as_a_defense_reads_the_start_of_the_attackers_turn(bprd):
    g = mk(bprd, turn=1)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    g.actions_left = 2
    g.controllers[0].queue = [lambda req: []]
    attack = rival_attack(g, 2)
    assert g.attack(h, b, attack, give(g, 0, "Like a Flash of Golden Light")).def_value == 2


# ---------------------------------------------------------------- Insight of the Ancients

def test_insight_returns_a_random_card_of_the_discard_pile_when_he_won(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    start_turn(g)
    pile = [c for c in g.players[0].deck if c.title in ("Super Strength", "Imposing Presence", "Skirmish")][:3]
    for c in pile:
        g.players[0].deck.remove(c)
        g.players[0].discard.append(c)
    g.attack(b, h, give(g, 0, "Insight of the Ancients"), None)
    back = [c for c in pile if c in g.players[0].hand]
    assert len(back) == 1 and len(g.players[0].discard) == 3 - 1 + 1       # one left, the played card arrived


def test_insight_does_nothing_when_the_combat_was_lost_or_the_pile_is_empty(bprd):
    g = mk(bprd, "leonardo")
    b, leo = pair(g, "bat", "leonardo")
    start_turn(g)
    pile = list(g.players[0].deck[:2])
    for c in pile:
        g.players[0].deck.remove(c)
        g.players[0].discard.append(c)
    res = g.attack(b, leo, give(g, 0, "Insight of the Ancients"), wall(g))
    assert not res.attacker_won and not any(c in g.players[0].hand for c in pile)
    g2 = mk(bprd)
    b2, h2 = pair(g2, "bat", "hellboy")
    g2.attack(b2, h2, give(g2, 0, "Insight of the Ancients"), None)
    assert g2.players[0].hand == []


def test_insight_is_decided_by_the_games_rng_not_by_the_deck_order(bprd):
    picks = set()
    for seed in range(1, 9):
        g = mk(bprd, seed=seed)
        b, h = pair(g, "bat", "hellboy")
        pile = [c for c in g.players[0].deck if c.title in ("Super Strength", "Imposing Presence", "Skirmish")][:3]
        for c in pile:
            g.players[0].deck.remove(c)
            g.players[0].discard.append(c)
        g.attack(b, h, give(g, 0, "Insight of the Ancients"), None)
        picks |= {c.title for c in pile if c in g.players[0].hand}
    assert len(picks) >= 2


# ---------------------------------------------------------------- Imposing Presence

def test_imposing_presence_cancels_the_rivals_effects(bprd):
    g = mk(bprd, "bullseye", turn=1)
    b, bu = pair(g, "bat", "bullseye")
    start_turn(g)
    g.actions_left = 2
    res = g.attack(bu, b, give(g, 1, "For My Next Trick"), give(g, 0, "Imposing Presence"))
    assert "atk" in res.cancelled and g.actions_left == 1             # no gained action: the effects are gone


# ---------------------------------------------------------------- the schemes

def test_arrive_just_in_time_places_him_on_any_empty_space(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    g.actions_left = 2
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options)]]
    g.play_scheme(0, b, give(g, 0, "Arrive Just in Time"))
    free = {s for s in bprd.spaces if all(f.pos != s for f in g.fighters.values() if f.alive and f is not b)}
    assert set(seen[0].options) <= free and len(seen[0].options) > 20
    assert b.pos == max(seen[0].options)


def test_alpine_fortress_shuffles_a_discard_card_in_draws_two_and_moves_up_to_four(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    g.actions_left = 2
    pile = [c for c in g.players[0].deck if c.title in ("Super Strength", "Skirmish")][:2]
    for c in pile:
        g.players[0].deck.remove(c)
        g.players[0].discard.append(c)
    alpine = give(g, 0, "Alpine Fortress")
    deck_before = len(g.players[0].deck)
    seen = []
    g.controllers[0].queue = [[pile[0].card_id], lambda req: seen.append(req) or [max(req.options)]]
    g.play_scheme(0, b, alpine)
    assert pile[0] not in g.players[0].discard and pile[1] in g.players[0].discard
    assert len(g.players[0].hand) == 2 and len(g.players[0].deck) == deck_before + 1 - 2          # one in, two out
    assert seen[-1].extra["steps"] == 4 and seen[-1].extra["up_to"] and b.pos == max(seen[-1].options)


def test_alpine_fortress_with_an_empty_pile_just_draws_and_moves(bprd):
    g = mk(bprd)
    b, h = pair(g, "bat", "hellboy")
    g.actions_left = 2
    g.controllers[0].queue = [lambda req: []]
    g.play_scheme(0, b, give(g, 0, "Alpine Fortress"))
    assert len(g.players[0].hand) == 2 and [c.title for c in g.players[0].discard] == ["Alpine Fortress"]


# ---------------------------------------------------------------- the data the validator and the AI read

def test_every_card_text_matches_what_the_effects_do():
    import json
    from sparring.heroes import HEROES_DIR
    data = json.loads((HEROES_DIR / "effects" / "golden-bat.json").read_text(encoding="utf-8"))
    from sparring.heroes import load_hero
    deck = {c.title: c.text for c in load_hero("golden-bat").deck()}
    for c in data["cards"]:
        assert c["text"] == deck[c["title"]], c["title"]
