"""Eredin on the engine, bot side (player 0 plays him, the controllers answer): KING OF THE WILD HUNT (ENRAGED while no Red Rider is
alive: +1 to every combat card, move 3), the two cards that change what can be played (Implacable as an attack, Foul Purpose at any
range), the price of a Red Rider (`defeat`), Portal Defense's new defender, Might Of The Aen Elle's ONGOING and every card with the
numbers printed on it. The human side (panel, FakeTTS) is in tests/test_eredin_human.py and the full games in
tests/test_eredin_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import enraged
from sparring.ai_medusa import MedusaAI, Model
from sparring.effects.events import default_choosers
from sparring.effects.modifiers import is_uncancelable, plays_face_up
from sparring.persist import apply_game, game_to_dict
from sparring.state import Game, RuleError
from test_bigfoot_effects import Answers, wall
from test_effects_combat import pair, put_adjacent

RIDERS = ["rider1", "rider2", "rider3", "rider4"]


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Eredin = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("eredin", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def enrage(g):
    """Every Red Rider falls (the way a rival's blow would defeat them)."""
    for fid in RIDERS:
        g.defeat(g.fighters[fid])
    assert enraged.is_enraged(g, 0)


def clear(g, fid):
    """A fighter off the board without a trace (so it is neither alive nor a defeated one the effects may bring back)."""
    f = g.fighters[fid]
    f.alive, f.pos = False, None


def riders_away(g, near):
    """The Red Riders far from `near` (not in its zone), each on its own space."""
    far = [s for s in sorted(g.board.spaces, reverse=True) if not g.board.share_zone(near, s)]
    for fid, s in zip(RIDERS, far):
        if g.fighters[fid].alive:
            g.fighters[fid].pos = s


def free_next_to(g, fid, anchor, exclude=()):
    return next(s for s in sorted(g.board.adj[g.fighters[anchor].pos])
                if s not in exclude and all(f.pos != s for f in g.fighters.values() if f.alive))


def foe_card(g, pred, player=1):
    """A card of `player`'s deck that satisfies `pred`, put in the hand."""
    c = next(c for c in g.players[player].full_set if pred(c))
    if c in g.players[player].deck:
        g.players[player].deck.remove(c)
    g.players[player].hand.append(c)
    return c


# ---------------------------------------------------------------- the hero

def test_eredin_is_a_melee_hero_with_four_red_riders(bprd):
    g = mk(bprd)
    e = g.fighters["eredin"]
    assert (e.hp, e.move, e.ranged, e.reach, e.name) == (14, 2, False, 0, "Eredin")
    assert [f.fid for f in g.own(0)] == ["eredin"] + RIDERS
    assert all((f.hp, f.max_hp, f.move, f.ranged, f.name) == (1, 1, 2, False, "Red Rider") for f in map(g.fighters.get, RIDERS))
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert "eredin" in g.fx.dsl_heroes


def test_the_deck_has_the_printed_bands_and_numbers(bprd):
    g = mk(bprd)
    seen = {}
    for c in g.players[0].full_set:
        seen.setdefault(c.title, (c.type, c.value, c.boost, c.fighter, 0))
        t = seen[c.title]
        seen[c.title] = t[:4] + (t[4] + 1,)
    assert seen == {
        "Backhand": ("attack", 4, 3, "Eredin", 3), "Brutal Strike": ("attack", 2, 3, "Eredin", 3),
        "Foul Purpose": ("attack", 3, 2, "any", 2), "Unyielding Hordes": ("attack", 1, 2, "Red Rider", 3),
        "Icy Guile": ("versatile", 2, 1, "any", 3), "Wild Hunt": ("versatile", 3, 2, "any", 3),
        "Skirmish": ("versatile", 4, 1, "any", 3), "Implacable": ("defense", 3, 3, "Eredin", 3),
        "Portal Defense": ("defense", 0, 1, "Eredin", 2), "Might Of The Aen Elle": ("scheme", None, 2, "Eredin", 2),
        "Close For The Kill": ("scheme", None, 4, "any", 3)}


# ---------------------------------------------------------------- KING OF THE WILD HUNT

def test_eredin_is_not_enraged_while_a_red_rider_lives(bprd):
    g = mk(bprd)
    assert not enraged.is_enraged(g, 0) and enraged.bonus_parts(g, 0) == [] and g.fighters["eredin"].move == 2
    for fid in RIDERS[:3]:
        g.defeat(g.fighters[fid])
    assert not enraged.is_enraged(g, 0) and g.fighters["eredin"].move == 2


def test_the_last_red_rider_falling_enrages_him_move_three(bprd):
    g = mk(bprd)
    enrage(g)
    assert g.fighters["eredin"].move == 3
    assert enraged.bonus_parts(g, 0) == [(1, "KING OF THE WILD HUNT")]


def test_the_rival_is_never_enraged_by_the_ability(bprd):
    g = mk(bprd)
    enrage(g)
    assert not enraged.is_enraged(g, 1) and g.fighters["hellboy"].move == 2


def test_a_red_rider_killed_by_damage_enrages_too(bprd):
    g = mk(bprd)
    for fid in RIDERS:
        g.damage(g.fighters[fid], 5, "effect")
    assert enraged.is_enraged(g, 0) and g.fighters["eredin"].move == 3


def test_a_red_rider_coming_back_ends_the_rage(bprd):
    g = mk(bprd)
    enrage(g)
    g.controllers[0].queue = [lambda req: [min(req.options)]]
    revive_one(g)
    assert not enraged.is_enraged(g, 0) and g.fighters["eredin"].move == 2


def revive_one(g):
    """Plays the IMMEDIATELY of Unyielding Hordes through the interpreter, the way a combat does."""
    from sparring.effects.run import Ctx, EffectRun
    run = EffectRun.for_card("eredin", "Unyielding Hordes", "immediately", Ctx(owner=0, this_fid="rider1"))
    pending = run.run(g, default_choosers(g))
    assert pending is None


def test_the_move_value_survives_a_save(bprd):
    g = mk(bprd)
    enrage(g)
    d = game_to_dict(g)
    g2 = mk(bprd)
    apply_game(g2, d)
    assert g2.fighters["eredin"].move == 3 and enraged.is_enraged(g2, 0)
    assert g2.clone().fighters["eredin"].move == 3


def test_the_bonus_is_added_to_an_attack(bprd):
    g = mk(bprd)
    e, h = pair(g, "eredin", "hellboy")
    res = g.attack(e, h, give(g, 0, "Backhand"), None)
    assert res.atk_value == 4
    enrage(g)
    g.actions_left = 2
    res = g.attack(e, h, give(g, 0, "Brutal Strike", 1), None)
    assert res.atk_value == 3                                             # 2 printed + 1 from the ability
    assert any("KING OF THE WILD HUNT" in p for p in res.atk_parts)


def test_the_bonus_is_added_to_a_defense(bprd):
    g = mk(bprd, turn=1)
    e, h = pair(g, "eredin", "hellboy")
    g.actions_left = 2
    attack = foe_card(g, lambda c: c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    res = g.attack(h, e, attack, give(g, 0, "Implacable"))
    assert res.def_value == 3
    enrage(g)
    g.actions_left = 2
    res = g.attack(h, e, foe_card(g, lambda c: c.can_attack and (c.value or 0) == 3 and c.usable_by("Hellboy")), give(g, 0, "Implacable", 1))
    assert res.def_value == 4


# ---------------------------------------------------------------- Backhand

def test_backhand_puts_a_random_card_of_the_rival_hand_on_top_of_their_deck(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    hand = [g.players[1].deck.pop(0) for _ in range(3)]
    g.players[1].hand.extend(hand)
    shield = wall(g)
    deck_before, pile = len(g.players[1].deck), len(g.players[1].discard)
    g.attack(e, leo, give(g, 0, "Backhand"), shield)
    assert len(g.players[1].hand) == 2                                    # the shield was played, one random card went back
    assert len(g.players[1].deck) == deck_before + 1
    assert g.players[1].deck[0] in hand and len(g.players[1].discard) == pile + 1


def test_backhand_discards_the_card_instead_while_enraged(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    enrage(g)
    hand = [g.players[1].deck.pop(0) for _ in range(3)]
    g.players[1].hand.extend(hand)
    shield = wall(g)
    deck_before, pile = len(g.players[1].deck), len(g.players[1].discard)
    g.attack(e, leo, give(g, 0, "Backhand"), shield)
    assert len(g.players[1].deck) == deck_before
    assert len(g.players[1].discard) == pile + 2 and len(g.players[1].hand) == 2      # the shield and the random card


# ---------------------------------------------------------------- Brutal Strike

def test_brutal_strike_cannot_be_canceled(bprd):
    g = mk(bprd, "hellboy")
    assert is_uncancelable(give(g, 0, "Brutal Strike"))


def test_brutal_strike_ignores_a_card_that_has_an_immediately_effect(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    with_immediately = foe_card(g, lambda c: c.can_defend and "IMMEDIATELY:" in c.text)
    res = g.attack(e, leo, give(g, 0, "Brutal Strike"), with_immediately)
    assert res.def_value == 0 and res.atk_value == 2 and res.attacker_won


def test_brutal_strike_leaves_a_plain_card_alone(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    plain = foe_card(g, lambda c: c.can_defend and "IMMEDIATELY:" not in c.text and (c.value or 0) >= 2)
    res = g.attack(e, leo, give(g, 0, "Brutal Strike"), plain)
    assert res.def_value == plain.value


def test_brutal_strike_against_no_card_has_nothing_to_ignore(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    res = g.attack(e, leo, give(g, 0, "Brutal Strike"), None)
    assert res.def_value == 0 and leo.hp == leo.max_hp - 2


def test_a_cancel_cannot_touch_brutal_strike(bprd):
    """The rival's Flash Of Steel-like IMMEDIATELY cancel leaves Brutal Strike's DURING working."""
    g = mk(bprd, "hellboy")
    e, h = pair(g, "eredin", "hellboy")
    cancels = foe_card(g, lambda c: c.can_defend and "cancel" in c.text.lower() and "IMMEDIATELY:" in c.text)
    flow = g.begin_attack(e, h, give(g, 0, "Brutal Strike"), cancels)
    flow.run()
    assert "atk" not in flow.result.cancelled and flow.result.def_value == 0


# ---------------------------------------------------------------- Unyielding Hordes

def test_unyielding_hordes_is_played_by_a_red_rider_and_returns_a_fallen_one(bprd):
    g = mk(bprd, "leonardo")
    rider, leo = pair(g, "rider1", "leonardo")
    g.defeat(g.fighters["rider2"])
    g.controllers[0].queue = [lambda req: [free_next_to(g, "leonardo", "leonardo", exclude=(rider.pos,))]]
    hordes = give(g, 0, "Unyielding Hordes")
    assert hordes.usable_by("Red Rider") and not hordes.usable_by("Eredin")
    g.attack(rider, leo, hordes, wall(g))
    back = g.fighters["rider2"]
    assert back.alive and back.hp == 1 and back.pos in g.board.adj[leo.pos]


def test_unyielding_hordes_adds_one_per_other_friendly_fighter_next_to_the_target(bprd):
    g = mk(bprd, "leonardo")
    rider, leo = pair(g, "rider1", "leonardo")
    put_adjacent(g, "eredin", "leonardo")
    spot = free_next_to(g, "leonardo", "leonardo", exclude=(g.fighters["eredin"].pos,))
    g.fighters["rider2"].pos = spot
    res = g.attack(rider, leo, give(g, 0, "Unyielding Hordes"), None)
    assert res.atk_value == 1 + 2                                          # Eredin and rider2, not the attacker itself


def test_unyielding_hordes_with_no_fallen_rider_just_attacks(bprd):
    g = mk(bprd, "leonardo")
    rider, leo = pair(g, "rider1", "leonardo")
    res = g.attack(rider, leo, give(g, 0, "Unyielding Hordes"), None)
    assert res.atk_value == 1 and all(g.fighters[f].alive for f in RIDERS)


# ---------------------------------------------------------------- Icy Guile

def test_icy_guile_ignores_the_rival_value_for_a_red_rider(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    g.controllers[0].queue = [[True], ["rider2"]]
    res = g.attack(e, leo, give(g, 0, "Icy Guile"), wall(g))
    assert not g.fighters["rider2"].alive and res.def_value == 0 and res.attacker_won


def test_icy_guile_may_be_declined(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    g.controllers[0].queue = [[False]]
    good = wall(g)
    res = g.attack(e, leo, give(g, 0, "Icy Guile"), good)
    assert all(g.fighters[f].alive for f in RIDERS) and res.def_value == good.value


def test_icy_guile_cannot_be_paid_without_a_red_rider(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    enrage(g)
    good = wall(g)
    res = g.attack(e, leo, give(g, 0, "Icy Guile"), good)
    assert res.def_value == good.value                                    # no option was asked and nothing was ignored
    assert g.controllers[0].requests == [] or all(r.kind != "optional" for r in g.controllers[0].requests)


def test_icy_guile_cancels_the_rival_effects_only_while_enraged(bprd):
    g = mk(bprd, "tomoe-gozen")
    e, t = pair(g, "eredin", "tomoe")
    refuse = lambda c: c.title == "Refuse to Retreat"                     # a defense with an IMMEDIATELY and nothing that cancels
    first = foe_card(g, refuse)
    flow = g.begin_attack(e, t, give(g, 0, "Icy Guile"), first)
    flow.run()
    assert "def" not in flow.result.cancelled
    enrage(g)
    g.actions_left = 2
    again = next(c for c in g.players[1].full_set if refuse(c) and c is not first)
    g.players[1].hand.append(again)
    flow = g.begin_attack(e, t, give(g, 0, "Icy Guile", 1), again)
    flow.run()
    assert "def" in flow.result.cancelled


def test_the_last_red_rider_paid_in_a_combat_adds_the_rage_bonus_at_once(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    for fid in RIDERS[1:]:
        g.defeat(g.fighters[fid])
    g.controllers[0].queue = [[True], ["rider1"]]
    res = g.attack(e, leo, give(g, 0, "Icy Guile"), wall(g))
    assert enraged.is_enraged(g, 0) and res.atk_value == 2 + 1 and res.def_value == 0


def test_a_defeated_red_rider_is_not_damage(bprd):
    """Might Of The Aen Elle protects Eredin only; the price of Icy Guile is no damage whatever statuses are in play."""
    g = mk(bprd, "leonardo")
    g.defeat(g.fighters["rider1"])
    assert not g.fighters["rider1"].alive and g.fighters["rider1"].died_at is not None


# ---------------------------------------------------------------- Wild Hunt

def test_wild_hunt_hits_each_opposing_fighter_next_to_a_friendly_one(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    splinter = g.fighters["splinter"]
    splinter.pos = free_next_to(g, "leonardo", "leonardo", exclude=(e.pos,))
    g.fighters["rider1"].pos = free_next_to(g, "splinter", "splinter", exclude=(e.pos, leo.pos))      # a rider next to Splinter
    before = (leo.hp, splinter.hp)
    g.attack(e, leo, give(g, 0, "Wild Hunt"), wall(g))
    assert leo.hp == before[0] - 1 and splinter.hp == before[1] - 1       # the shield stopped the combat damage


def test_wild_hunt_does_nothing_to_a_fighter_no_friendly_fighter_touches(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    splinter = g.fighters["splinter"]
    splinter.pos = next(s for s in sorted(bprd.spaces, reverse=True)
                        if all(s not in bprd.adj[f.pos] for f in g.own(0)) and all(f.pos != s for f in g.fighters.values() if f.alive))
    hp = splinter.hp
    g.attack(e, leo, give(g, 0, "Wild Hunt"), wall(g))
    assert splinter.hp == hp


def test_wild_hunt_deals_two_while_enraged(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    enrage(g)
    hp = leo.hp
    g.attack(e, leo, give(g, 0, "Wild Hunt"), wall(g))
    assert leo.hp == hp - 2


# ---------------------------------------------------------------- Skirmish

def test_skirmish_moves_a_fighter_of_the_combat_after_a_win(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[0]], lambda req: seen.append(req) or [req.options[0]]]
    g.attack(e, leo, give(g, 0, "Skirmish"), None)
    assert seen and seen[-1].extra["steps"] == 2


# ---------------------------------------------------------------- Implacable

def test_implacable_is_a_defense_that_may_boost(bprd):
    from sparring.effects.modifiers import may_boost
    g = mk(bprd)
    c = give(g, 0, "Implacable")
    assert c.can_defend and not c.can_attack and may_boost(c) and (c.value, c.boost) == (3, 3)


def test_implacable_cannot_attack_while_eredin_is_not_enraged(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    c = give(g, 0, "Implacable")
    with pytest.raises(RuleError):
        g.attack(e, leo, c, None)
    assert c in g.players[0].hand and g.actions_left == 2
    assert not enraged.may_attack_with(g, 0, c)


def test_implacable_attacks_while_enraged_and_may_boost(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    enrage(g)
    c = give(g, 0, "Implacable")
    assert enraged.may_attack_with(g, 0, c)
    res = g.attack(e, leo, c, None)
    assert res.atk_value == 3 + 1 and leo.hp == leo.max_hp - 4


def test_the_ai_offers_implacable_as_an_attack_only_while_enraged(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    give(g, 0, "Implacable")
    ai = MedusaAI(0)
    g.actions_left = 2
    assert ai.attack_acts(g, Model(g, 0)) == []
    enrage(g)
    assert [a.card.title for a in ai.attack_acts(g, Model(g, 0))] == ["Implacable"]


# ---------------------------------------------------------------- Foul Purpose

def far_apart(g, a_fid, b_fid):
    """Two fighters that are neither adjacent nor share a zone (Eredin is melee: adjacent is his only reach)."""
    for a in sorted(g.board.spaces):
        for b in sorted(g.board.spaces, reverse=True):
            if not g.board.share_zone(a, b) and b not in g.board.adj[a]:
                g.fighters[a_fid].pos, g.fighters[b_fid].pos = a, b
                for f in g.fighters.values():
                    if f.alive and f.fid not in (a_fid, b_fid):
                        f.pos = next(s for s in sorted(g.board.spaces) if s not in (a, b) and all(o.pos != s for o in g.fighters.values() if o.alive and o is not f))
                return
    raise AssertionError("no far pair")


def test_foul_purpose_cannot_reach_a_far_fighter_while_not_enraged(bprd):
    g = mk(bprd, "leonardo")
    far_apart(g, "eredin", "leonardo")
    e, leo = g.fighters["eredin"], g.fighters["leonardo"]
    c = give(g, 0, "Foul Purpose")
    assert not g.can_attack(e, leo, c) and not g.attack_card_reaches(e, leo, c)
    with pytest.raises(RuleError):
        g.attack(e, leo, c, None)


def test_foul_purpose_targets_any_space_while_enraged_and_lies_face_up(bprd):
    g = mk(bprd, "leonardo")
    far_apart(g, "eredin", "leonardo")
    e, leo = g.fighters["eredin"], g.fighters["leonardo"]
    for fid in RIDERS:
        clear(g, fid)
    c = give(g, 0, "Foul Purpose")
    assert enraged.is_enraged(g, 0) and g.can_attack(e, leo, c) and g.attack_card_reaches(e, leo, c)
    assert plays_face_up(c, g, e, leo)
    res = g.attack(e, leo, c, None)
    assert res.attacker_won and leo.hp == leo.max_hp - (3 + 1)


def test_foul_purpose_in_reach_is_played_like_any_attack(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    enrage(g)
    c = give(g, 0, "Foul Purpose")
    assert not plays_face_up(c, g, e, leo)


def test_a_far_target_is_named_by_the_human_only_while_enraged(bprd):
    g = mk(bprd, "leonardo")
    far_apart(g, "eredin", "leonardo")
    e, leo = g.fighters["eredin"], g.fighters["leonardo"]
    assert not g.can_declare_attack(e, leo)
    for fid in RIDERS:
        clear(g, fid)
    assert g.can_declare_attack(e, leo)


def test_the_ai_aims_foul_purpose_at_a_far_fighter_only_while_enraged(bprd):
    g = mk(bprd, "leonardo")
    far_apart(g, "eredin", "leonardo")
    give(g, 0, "Foul Purpose")
    ai = MedusaAI(0)
    g.actions_left = 2
    assert [a for a in ai.attack_acts(g, Model(g, 0)) if a.fid == "eredin"] == []
    for fid in RIDERS:
        clear(g, fid)
    assert {a.target for a in ai.attack_acts(g, Model(g, 0)) if a.fid == "eredin"} >= {"leonardo"}


def test_foul_purpose_returns_to_the_hand_for_a_red_rider(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    g.controllers[0].queue = [[True], ["rider3"]]
    c = give(g, 0, "Foul Purpose")
    g.attack(e, leo, c, wall(g))
    assert not g.fighters["rider3"].alive and c in g.players[0].hand and c not in g.players[0].discard


def test_foul_purpose_goes_to_the_discard_pile_when_declined(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    g.controllers[0].queue = [[False]]
    c = give(g, 0, "Foul Purpose")
    g.attack(e, leo, c, wall(g))
    assert all(g.fighters[f].alive for f in RIDERS) and c in g.players[0].discard


def test_foul_purpose_cannot_return_without_a_red_rider(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    enrage(g)
    c = give(g, 0, "Foul Purpose")
    g.attack(e, leo, c, wall(g))
    assert c in g.players[0].discard


# ---------------------------------------------------------------- Portal Defense

def defended_by_portal(bprd, *, enraged_hero=False, foe="hellboy"):
    g = mk(bprd, foe, turn=1)
    e, h = pair(g, "eredin", foe)
    rider = g.fighters["rider1"]
    rider.pos = free_next_to(g, "eredin", "eredin", exclude=(h.pos,))
    if enraged_hero:
        for fid in RIDERS[1:]:
            g.defeat(g.fighters[fid])
    g.actions_left = 2
    return g, e, h, rider


def test_portal_defense_swaps_eredin_with_a_friendly_fighter_who_is_now_the_defender(bprd):
    g, e, h, rider = defended_by_portal(bprd)
    g.controllers[0].queue = [lambda req: [req.options[0]]]
    b = rider.pos
    attack = foe_card(g, lambda c: c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    flow = g.begin_attack(h, e, attack, give(g, 0, "Portal Defense"))
    flow.run()
    assert e.pos == b and flow.tgt is rider and not rider.alive                          # a 4 against a 0 and a single hit point
    assert e.hp == e.max_hp


def test_portal_defense_with_no_adjacent_friendly_fighter_just_defends(bprd):
    g = mk(bprd, "hellboy", turn=1)
    e, h = pair(g, "eredin", "hellboy")
    attack = foe_card(g, lambda c: c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    res = g.attack(h, e, attack, give(g, 0, "Portal Defense"))
    assert e.hp == e.max_hp - 4 and res.def_value == 0


def test_portal_defense_draws_two_only_while_enraged(bprd):
    g, e, h, rider = defended_by_portal(bprd)
    g.controllers[0].queue = [lambda req: [req.options[0]]]
    g.attack(h, e, foe_card(g, lambda c: c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy")), give(g, 0, "Portal Defense"))
    assert len(g.players[0].hand) == 0
    g = mk(bprd, "hellboy", turn=1)
    e, h = pair(g, "eredin", "hellboy")
    enrage(g)
    g.actions_left = 2
    g.attack(h, e, foe_card(g, lambda c: c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy")), give(g, 0, "Portal Defense"))
    assert len(g.players[0].hand) == 2


# ---------------------------------------------------------------- Might Of The Aen Elle

def play_might(g, nth=0):
    might = give(g, 0, "Might Of The Aen Elle", nth)
    g.play_scheme(0, g.fighters["eredin"], might)
    return might


def test_might_of_the_aen_elle_draws_one_and_gains_an_action(bprd):
    g = mk(bprd)
    g.actions_left = 2
    might = give(g, 0, "Might Of The Aen Elle")
    pile = len(g.players[0].deck)
    g.play_scheme(0, g.fighters["eredin"], might)
    assert len(g.players[0].hand) == 1 and len(g.players[0].deck) == pile - 1
    assert g.actions_left == 2                                            # one spent, one gained
    assert g.fx.ongoing_card_id(0) == might.card_id


def test_while_it_is_in_play_effect_damage_does_not_hurt_eredin_but_combat_damage_does(bprd):
    g = mk(bprd, "hellboy")
    play_might(g)
    e = g.fighters["eredin"]
    assert g.damage(e, 3, "effect") == 0 and e.hp == 14
    assert g.damage(g.fighters["rider1"], 3, "effect") > 0                  # the riders are not protected
    assert g.damage(e, 2, "combat") == 2 and e.hp == 12
    assert g.damage(e, 2, "exhaustion") == 2 and e.hp == 10


def test_it_lapses_at_the_end_of_a_turn_with_no_attack(bprd):
    g = mk(bprd, "hellboy")
    play_might(g)
    g.end_turn()
    assert g.fx.ongoing_card_id(0) is None
    assert g.damage(g.fighters["eredin"], 2, "effect") == 2


def test_it_stays_when_eredin_attacked_that_turn_and_lapses_the_next_one_without_an_attack(bprd):
    g = mk(bprd, "hellboy")
    e, h = pair(g, "eredin", "hellboy")
    g.actions_left = 3
    might = play_might(g)
    g.attack(e, h, give(g, 0, "Skirmish"), None)
    g.actions_left = 1
    g.end_turn()
    assert g.fx.ongoing_card_id(0) == might.card_id                      # it protected him through the rival's turn
    assert g.damage(e, 2, "effect") == 0
    g.begin_turn()
    g.end_turn()                                                         # the rival's turn passes (their end_of_turn is not the owner's)
    assert g.fx.ongoing_card_id(0) == might.card_id
    g.begin_turn()
    g.end_turn()                                                         # Eredin's turn with no attack
    assert g.fx.ongoing_card_id(0) is None


def test_another_ongoing_replaces_it(bprd):
    g = mk(bprd, "hellboy")
    g.actions_left = 4
    first = play_might(g)
    second = play_might(g, 1)
    assert g.fx.ongoing_card_id(0) == second.card_id and first in g.players[0].discard


# ---------------------------------------------------------------- Close For The Kill

def test_close_for_the_kill_draws_two_and_moves_every_fighter_through_the_rivals(bprd):
    g = mk(bprd, "leonardo")
    e, leo = pair(g, "eredin", "leonardo")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[-1]] for _ in range(5)]
    g.actions_left = 2
    close = give(g, 0, "Close For The Kill")
    g.play_scheme(0, e, close)
    assert len(g.players[0].hand) == 2
    assert seen and all(r.extra["steps"] == 3 and r.extra["through"] is True for r in seen)
    assert len(seen) == len(g.own(0))


# ---------------------------------------------------------------- engine pieces

def test_defeat_op_needs_a_fighter_and_is_not_damage(bprd):
    from sparring.effects.run import Ctx, EffectRun
    g = mk(bprd)
    play_might(g)
    ops = [{"op": "defeat", "target": {"side": "own", "name": "Red Rider"}}]
    g.controllers[0].queue = [["rider4"]]
    EffectRun(ops, Ctx(owner=0, this_fid="eredin")).run(g, default_choosers(g))
    assert not g.fighters["rider4"].alive and g.fighters["rider4"].hp == 0


def test_the_search_clone_keeps_the_rage(bprd):
    g = mk(bprd)
    enrage(g)
    c = g.clone()
    assert enraged.is_enraged(c, 0) and c.fighters["eredin"].move == 3
    c.heal(c.fighters["eredin"], 0)


# ---------------------------------------------------------------- what the bot pays a Red Rider for

def pays(g, riders_left, *, ignores, stake=0, hp=14):
    from sparring.ai_effects import EffectAI
    from sparring.effects.choose import ChoiceRequest
    for fid in RIDERS[riders_left:]:
        g.defeat(g.fighters[fid])
    alive = [f for f in RIDERS if g.fighters[f].alive]
    extra = {"defeats": {"fighters": alive, "returns": not ignores, "ignores": ignores}, "at_stake": stake, "hp": hp}
    req = ChoiceRequest("optional", 0, [True, False], 1, 1, None, "k", "", extra, 0)
    return EffectAI._fighter_pays(g, req)


@pytest.mark.parametrize("left", [4, 3, 2])
def test_the_bot_does_not_pay_a_rider_for_nothing_in_icy_guile(bprd, left):
    assert not pays(mk(bprd), left, ignores=True, stake=0)


def test_the_bot_pays_the_last_rider_for_icy_guile_because_it_enrages_him(bprd):
    assert pays(mk(bprd), 1, ignores=True, stake=0)          # ENRAGE_BONUS (2) reaches RIDER_PRICE (2)


@pytest.mark.parametrize("left", [4, 3])
def test_the_bot_pays_a_rider_for_icy_guile_only_when_the_blow_is_big_enough(bprd, left):
    assert pays(mk(bprd), left, ignores=True, stake=3)


@pytest.mark.parametrize("left", [4, 3])
def test_the_bot_does_not_burn_a_rider_to_get_foul_purpose_back_while_many_remain(bprd, left):
    assert not pays(mk(bprd), left, ignores=False)


@pytest.mark.parametrize("left", [2, 1])
def test_the_bot_takes_foul_purpose_back_when_few_riders_remain(bprd, left):
    assert pays(mk(bprd), left, ignores=False)


# ---------------------------------------------------------------- Might Of The Aen Elle and the map hazards

def test_might_of_the_aen_elle_also_stops_hazard_damage_but_nothing_else_does(bprd):
    g = mk(bprd, "hellboy")
    e = g.fighters["eredin"]
    assert g.damage(e, 1, "hazard") == 1                      # no ONGOING in play: a hazard hurts
    play_might(g)
    assert g.damage(e, 1, "hazard") == 0 and e.hp == 13
    assert g.damage(g.fighters["rider1"], 1, "hazard") == 1    # the Riders are not protected
    assert g.damage(e, 1, "combat") == 1


def test_a_status_from_another_card_does_not_stop_hazards(bprd):
    from sparring.effects.run import Ctx, EffectRun
    g = mk(bprd, "hellboy")
    ops = [{"op": "status", "name": "immune_to_effect_damage", "target": "hero", "until": {"event": "end_of_turn"}}]
    EffectRun(ops, Ctx(owner=0, this_fid="eredin")).run(g, default_choosers(g))
    e = g.fighters["eredin"]
    assert g.damage(e, 2, "effect") == 0 and g.damage(e, 1, "hazard") == 1


def test_the_table_note_for_a_returned_piece_names_its_miniature():
    from sparring.effects import table
    line = table.line({"op": "revive", "fid": "rider2", "name": "Aleksei", "where": {"any": True}, "hp": 1})
    assert "Aleksei" in line and "rider2" not in line
