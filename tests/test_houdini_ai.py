"""The bot's AI with Houdini: it prices the BOOSTED WITH of a card when it chooses what to boost with, uses ESCAPE ARTIST to leave a
threat or to land next to a target, plays Bess's scheme, and the search AI (ISMCTS) places Houdini on boosted Maneuvers legally."""
from __future__ import annotations

import random

import pytest

from conftest import give
from sparring.cards import Card
from sparring.ai_medusa import MedusaAI, Model, boost_effect_value, cancels_effects, free_boosts, scheme_fighter
from sparring.search.controller import IsmctsMedusa
from sparring.search.ismcts import SearchConfig
from sparring.state import Game
from test_effects_combat import hand_filler, pair


def mk(bprd, foe="hellboy", seed=3):
    """Houdini = player 0 with the real AI; its turn, empty hands, the rival's pieces far away."""
    g = Game.new(bprd, seed, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=("houdini", foe), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def far_from(g, fid, fids):
    taken = {f.pos for f in g.fighters.values() if f.alive}
    return max((s for s in g.board.spaces if s not in taken),
               key=lambda s: min(g.board.distance(s, g.fighters[o].pos) for o in fids))


# ---------------------------------------------------------------- what a BOOSTED WITH is worth

def test_boost_effect_values_follow_the_text_of_the_card(bprd):
    g = mk(bprd)
    flourish, bess, stage = give(g, 0, "Flourish"), give(g, 0, "And the Beautiful Bess!"), give(g, 0, "Set the Stage")
    assert boost_effect_value(g, 0, flourish) == pytest.approx(0.4)                        # one unknown card
    assert boost_effect_value(g, 0, bess) > 0.5                                           # an action on its own turn
    g.turn = 1
    assert boost_effect_value(g, 0, bess) == 0                                            # none on the rival's: "if it's your turn"
    assert boost_effect_value(g, 0, stage) == 0                                           # the rival has no hand to look at
    give(g, 1, "Excalibur")
    assert boost_effect_value(g, 0, stage) > 1
    assert boost_effect_value(g, 0, give(g, 0, "For My Next Trick")) == 0                  # no BOOSTED WITH


def test_all_part_of_the_show_boost_is_worth_the_health_it_gives_back(bprd):
    g = mk(bprd)
    card = give(g, 0, "All Part of the Show")
    full = boost_effect_value(g, 0, card)
    g.fighters["houdini"].hp = 8
    assert full == 0 and boost_effect_value(g, 0, card) > 2


def test_misdirection_boost_is_worth_a_kill_on_a_weak_rival(bprd):
    g = mk(bprd)
    card = give(g, 0, "Misdirection")
    base = boost_effect_value(g, 0, card)
    g.fighters["lobster"].hp = 2
    assert boost_effect_value(g, 0, card) > base + 2          # it kills Lobster Johnson


def test_bess_plays_set_the_stage_and_houdini_cannot(bprd):
    g = mk(bprd)
    stage = give(g, 0, "Set the Stage")
    assert scheme_fighter(g, 0, stage).fid == "bess"
    assert scheme_fighter(g, 0, give(g, 0, "A Magician Never Reveals His Secrets")).fid == "houdini"
    g.damage(g.fighters["bess"], 5)
    assert scheme_fighter(g, 0, stage) is None


def test_the_bot_plays_a_scheme_only_bess_can_play(bprd):
    g = mk(bprd)
    give(g, 0, "Set the Stage")
    hand_filler(g, 0, 2, avoid=("Set the Stage",))
    g.actions_left = 2
    acts = MedusaAI(0).candidates(g, __import__("sparring.ai_medusa", fromlist=["Model"]).Model(g, 0))
    assert any(a.kind == "scheme" and a.fid == "bess" for a in acts)


# ---------------------------------------------------------------- choosing what to boost a Maneuver with

def test_the_boost_card_with_a_boosted_with_is_the_one_spent_on_a_maneuver(bprd):
    g = mk(bprd)
    trick, flourish = give(g, 0, "For My Next Trick"), give(g, 0, "Flourish")                  # both boost 2: only Flourish draws
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is not None and act.boost.title == "Flourish"


def test_a_boost_that_gains_an_action_is_chosen_to_get_the_action_back(bprd):
    g = mk(bprd)
    give(g, 0, "And the Beautiful Bess!")
    give(g, 0, "For My Next Trick")
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is not None and act.boost.title == "And the Beautiful Bess!"


def test_the_expected_state_after_a_boosted_maneuver_counts_the_action_it_gains(bprd):
    g = mk(bprd)
    bess = give(g, 0, "And the Beautiful Bess!")
    ai = MedusaAI(0)
    from sparring.ai_medusa import Act
    after = ai.apply_expected(g, Act("maneuver", moves={}, boost=bess))
    assert after.actions_left == g.actions_left            # one spent, one gained
    plain = ai.apply_expected(g, Act("maneuver", moves={}))
    assert plain.actions_left == g.actions_left - 1


# ---------------------------------------------------------------- ESCAPE ARTIST

def test_the_bot_places_houdini_next_to_the_rival_to_attack_when_it_has_a_boost_card(bprd):
    g = mk(bprd)
    hellboy, houdini = g.fighters["hellboy"], g.fighters["houdini"]
    hellboy.pos = far_from(g, "hellboy", ["houdini", "bess"])
    give(g, 0, "Flourish")
    give(g, 0, "Flourish", 1)
    give(g, 0, "The Big Reveal")
    assert g.board.distance(houdini.pos, hellboy.pos) > houdini.move + 3
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is not None
    assert g.board.adjacent(act.moves["houdini"], hellboy.pos)           # he lands in reach: the second action attacks


def test_the_bot_leaves_the_rival_when_it_is_threatened_and_holds_a_boost_card(bprd):
    g = mk(bprd)
    houdini, hellboy = pair(g, "houdini", "hellboy")
    houdini.hp = 3
    give(g, 0, "Flourish")
    give(g, 0, "Misdirection")
    for c in ("Excalibur", "Service Pistol", "Right Hand Of Doom"):
        give(g, 1, c)
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is not None
    assert g.board.distance(act.moves["houdini"], hellboy.pos) > hellboy.move + 1      # out of the rival's reach next turn


def test_without_a_boost_card_he_walks_like_any_hero(bprd):
    g = mk(bprd)
    houdini = g.fighters["houdini"]
    g.fighters["hellboy"].pos = far_from(g, "hellboy", ["houdini", "bess"])
    act = MedusaAI(0).plan(g)
    if act.kind == "maneuver":
        assert act.boost is None and g.board.distance(houdini.pos, act.moves.get("houdini", houdini.pos)) <= houdini.move


def test_the_planned_maneuver_is_always_legal_for_the_engine(bprd):
    """Whatever the heuristic plans with ESCAPE ARTIST, `Game.maneuver` accepts it."""
    for seed in range(6):
        g = mk(bprd, seed=seed)
        rng = random.Random(seed)
        for _ in range(3):
            hand_filler(g, 0, 2)
        for f in g.own(1):
            f.pos = rng.choice(sorted(s for s in g.board.spaces if all(o.pos != s for o in g.fighters.values() if o.alive)))
        g.actions_left = 2
        act = MedusaAI(0).plan(g)
        MedusaAI(0).execute(g, act)


# ---------------------------------------------------------------- the search AI

@pytest.mark.parametrize("foe", ["hellboy", "medusa", "raphael"])
def test_the_search_places_and_boosts_legally_and_never_falls_back(bprd, foe):
    g = mk(bprd, foe)
    g.controllers[0] = ai = IsmctsMedusa(0, SearchConfig(time_budget=30.0, iterations=6, seed=1))
    for _ in range(2):
        hand_filler(g, 0, 2)
    g.actions_left = 2
    for _ in range(2):
        if g.winner is None and g.actions_left > 0:
            ai.execute(g, ai.plan(g))
    assert ai.fallbacks == 0


# ---------------------------------------------------------------- hit and run (play style derived from the hero's data)

def rival_hand(g, n, avoid=()):
    return hand_filler(g, 1, n, avoid=avoid)


def discard_all(g, player, title):
    st = g.players[player]
    for c in [c for c in st.full_set if c.title == title]:
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)


def test_the_hit_and_run_style_comes_from_the_hero_data(bprd):
    assert MedusaAI(0).hit_and_run(mk(bprd))
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=("medusa", "hellboy"), bot_player=0)
    assert not MedusaAI(0).hit_and_run(g)


def test_a_healthy_houdini_in_reach_with_no_big_blow_blinks_out_of_reach(bprd):
    g = mk(bprd)
    houdini, hellboy = pair(g, "houdini", "hellboy")
    give(g, 0, "Vanishing Act")
    give(g, 0, "Sleight of Hand")
    give(g, 0, "Misdirection")
    rival_hand(g, 4)
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is not None
    assert g.board.distance(act.moves["houdini"], hellboy.pos) > hellboy.move + 1


def far_setup(bprd, discard_cancels):
    g = mk(bprd, "medusa")
    medusa = g.fighters["medusa"]
    medusa.pos = far_from(g, "medusa", ["houdini", "bess"])
    for title, nth in (("The Big Reveal", 0), ("The Big Reveal", 1), ("Sleight of Hand", 0), ("Sleight of Hand", 1), ("Flourish", 0)):
        give(g, 0, title, nth)
    rival_hand(g, 3, avoid=("Feint",))
    if discard_cancels:
        discard_all(g, 1, "Feint")
    g.actions_left = 2
    return g, medusa


def test_with_the_rivals_cancels_gone_houdini_places_next_to_it_and_plays_the_big_reveal_with_two_boosts(bprd):
    g, medusa = far_setup(bprd, True)
    ai = MedusaAI(0)
    assert g.board.distance(g.fighters["houdini"].pos, medusa.pos) > 5
    first = ai.plan(g)
    assert first.kind == "maneuver" and first.boost is not None
    assert g.board.adjacent(first.moves["houdini"], medusa.pos)
    ai.execute(g, first)
    second = ai.plan(g)
    assert second.kind == "attack" and (second.via or second.card).title == "The Big Reveal"
    assert len(free_boosts(g, 0, second.via or second.card, g.players[0].hand)) == 2


def strikable_next_turn(g, rival, pos):
    """A free space within the rival's Move from which its attack reaches `pos`."""
    board, taken = g.board, {f.pos for f in g.fighters.values() if f.alive}
    return any(board.can_reach_target(s, pos, rival.ranged) and board.distance(rival.pos, s) <= rival.move
               and (s == rival.pos or s not in taken) for s in board.spaces)


def final_spot_after_first_action(g, ai):
    first = ai.plan(g)
    return first, (first.moves["houdini"] if first.kind == "maneuver" and "houdini" in first.moves else g.fighters["houdini"].pos)


def test_only_the_rivals_public_cancel_risk_flips_the_strike_into_keeping_out_of_reach(bprd, monkeypatch):
    """The same scene (the rival's Feints are in its discard pile: nothing else about the estimates changes) played twice; the
    only difference is the chance `Model.p_holds` reports for a full cancel in the rival's hand. At its real value (0) Houdini
    places himself next to Medusa to strike; told the risk is 0.9 he ends out of her reach next turn."""
    g, medusa = far_setup(bprd, True)
    strike, strike_spot = final_spot_after_first_action(g, MedusaAI(0))
    assert strike.kind == "maneuver" and g.board.adjacent(strike_spot, medusa.pos)
    assert strikable_next_turn(g, medusa, strike_spot)

    g, medusa = far_setup(bprd, True)
    real = Model.p_holds
    monkeypatch.setattr(Model, "p_holds", lambda self, pred: 0.9 if pred is cancels_effects else real(self, pred))
    _, away_spot = final_spot_after_first_action(g, MedusaAI(0))
    assert not strikable_next_turn(g, medusa, away_spot)


def test_a_hero_with_a_two_boost_card_but_no_placement_rule_is_not_hit_and_run(bprd, monkeypatch):
    from sparring.ai_profile import STYLE_FINISHER, STYLE_HIT_AND_RUN, derive_style
    assert derive_style(False, 2) == frozenset({STYLE_FINISHER})
    assert derive_style(True, 0) == frozenset({STYLE_HIT_AND_RUN})
    g = mk(bprd)
    monkeypatch.setattr(type(g.fx), "hero_rule", lambda self, player, rule: False)       # Houdini's data without ESCAPE ARTIST
    ai = MedusaAI(0)
    assert not ai.hit_and_run(g) and STYLE_FINISHER in ai.style(g)


def test_the_finisher_count_ignores_cards_the_hero_cannot_play(bprd, monkeypatch):
    from sparring.ai_profile import STYLE_FINISHER
    g = mk(bprd)
    monkeypatch.setattr("sparring.ai_medusa.boost_limit", lambda c: 2 if c.title == "The Big Reveal" else 1)
    assert STYLE_FINISHER in MedusaAI(0).style(g)
    monkeypatch.setattr(Card, "usable_by", lambda self, name: self.title != "The Big Reveal" and self.fighter in ("any", name))
    assert STYLE_FINISHER not in MedusaAI(0).style(g)


def test_the_position_value_of_a_dead_hero_does_not_raise(bprd):
    """Seen in a simulated game (Houdini vs Abe Sapien, seed 34): Houdini dies in the combat and the rival's AFTER effect
    (Concussion Device) still asks the bot where to move; the evaluation looked up the dead hero's square (KeyError)."""
    g = mk(bprd, "abe-sapien")
    houdini = g.fighters["houdini"]
    houdini.hp, houdini.alive, houdini.pos = -1, False, None
    MedusaAI(0).position_value(g, Model(g, 0))


# ---------------------------------------------------------------- the cards Iván 3/11 saw wasted in the live game

def test_all_part_of_the_show_is_not_spent_as_a_boost_when_hurt(bprd):
    """Live 3/11: at 12 health the bot boosted a Maneuver with it for the 2 health it heals. Its keep value grows as Houdini
    drops, so the Maneuver spends the small boost card instead."""
    g = mk(bprd)
    give(g, 0, "All Part of the Show")
    give(g, 0, "Misdirection")
    for hp in (12, 8, 5):
        g.fighters["houdini"].hp = hp
        act = MedusaAI(0).plan(g)
        assert act.kind == "maneuver" and act.boost is not None and act.boost.title != "All Part of the Show"


def test_all_part_of_the_show_is_kept_harder_the_closer_houdini_is_to_dying(bprd):
    from sparring.ai_medusa import keep_value, situational_keep
    g = mk(bprd)
    card = give(g, 0, "All Part of the Show")
    keep = lambda: keep_value(card, [card]) + situational_keep(g, 0, card, [card])
    g.fighters["houdini"].hp = 14
    healthy = keep()
    g.fighters["houdini"].hp = 5
    assert keep() > healthy + 1
    assert healthy > keep_value(give(g, 0, "Grand Escape"), []) + 1           # never a plain defense card's price


def test_all_part_of_the_show_is_played_as_a_defense_only_when_the_blow_is_likely_lethal(bprd):
    g = mk(bprd)
    houdini, hellboy = pair(g, "houdini", "hellboy")
    card = give(g, 0, "All Part of the Show")
    ai = MedusaAI(0)
    assert ai.choose_defense(g, hellboy, houdini) is None            # a healthy Houdini does not waste it
    houdini.hp = 1
    assert ai.choose_defense(g, hellboy, houdini) is card            # a blow that may kill: it brings him back


def keep_order(g, cards):
    g.players[0].hand[:] = cards
    return [c.title for c in MedusaAI(0).choose_discard(g, 0, len(cards), "limit")]


def test_sleight_of_hand_is_kept_while_the_big_reveal_plan_is_possible(bprd):
    g = mk(bprd)
    discard_all(g, 0, "The Big Reveal")
    cards = [give(g, 0, t) for t in ("Sleight of Hand", "Flourish", "Misdirection")]
    assert keep_order(g, cards)[0] == "Sleight of Hand"                     # no finisher left: just a weak attack
    g = mk(bprd)
    cards = [give(g, 0, t) for t in ("Sleight of Hand", "Flourish", "Misdirection", "The Big Reveal")]
    assert keep_order(g, cards)[0] != "Sleight of Hand"


def test_sleight_of_hand_is_played_to_launch_the_big_reveal(bprd):
    """The rival's card is face up before the swap, so Sleight Of Hand is the way to open The Big Reveal: the act is the
    Sleight (what is played) standing for the finisher (`via`); without a Big Reveal it is a plain value-1 attack."""
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    sleight, reveal = give(g, 0, "Sleight of Hand"), give(g, 0, "The Big Reveal")
    give(g, 0, "Flourish")
    rival_hand(g, 3, avoid=("Misdirection", "Feint"))
    g.actions_left = 2
    ai = MedusaAI(0)
    attacks = [a for a in ai.attack_acts(g, Model(g, 0)) if a.fid == "houdini"]
    opener = next(a for a in attacks if a.card is sleight)
    assert opener.via is reveal
    assert opener.value > next(a for a in attacks if a.card is reveal).value
    g.players[0].hand.remove(reveal)
    plain = next(a for a in ai.attack_acts(g, Model(g, 0)) if a.card is sleight)
    assert plain.via is None and plain.value < 1


def test_a_feint_drawn_out_by_the_bait_is_worth_something(bprd, monkeypatch):
    """Sleight Of Hand is a bait: if the rival answers it with a cancel (no swap is offered), the cancel is spent and cannot stop the
    Big Reveal later. The act is worth more than a plain Sleight and the bait value is what makes the difference."""
    import sparring.ai_medusa as m
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    sleight = give(g, 0, "Sleight of Hand")
    give(g, 0, "The Big Reveal")
    rival_hand(g, 3)
    ai = MedusaAI(0)
    monkeypatch.setattr(Model, "p_holds", lambda self, pred: 1.0 if pred is cancels_effects else 0.0)
    opener = lambda: next(a for a in ai.attack_acts(g, Model(g, 0)) if a.card is sleight)
    with_bait = opener().value
    monkeypatch.setattr(m, "CANCEL_BAIT", 0.0)
    assert with_bait == pytest.approx(opener().value + 1.2)
    assert with_bait > 0                                       # a value-1 attack that costs a card is a loss without the bait


def test_the_magician_is_a_big_reveal_boost_not_a_scheme_to_draw(bprd):
    from sparring.ai_medusa import situational_keep
    g = mk(bprd)
    magician, reveal = give(g, 0, "A Magician Never Reveals His Secrets"), give(g, 0, "The Big Reveal")
    give(g, 0, "Flourish")
    ai = MedusaAI(0)
    assert situational_keep(g, 0, magician, g.players[0].hand) > 2          # kept for the finisher
    assert not any(a.kind == "scheme" and a.card is magician for a in ai.candidates(g, Model(g, 0))[:1])
    _, hellboy = pair(g, "houdini", "hellboy")
    assert free_boosts(g, 0, reveal, g.players[0].hand)[0] is magician      # its 4 is the first boost of the finisher
    ctx = type("Ctx", (), dict(target=hellboy, atk_card=reveal, atk_value=2, def_value=2))()
    assert ai.choose_combat_boost(g, ctx) is magician                       # spent on the finisher without counting the plan against it
    g.players[0].hand.remove(reveal)
    discard_all(g, 0, "The Big Reveal")
    assert situational_keep(g, 0, magician, g.players[0].hand) == 0         # the finisher is gone: the draw is all it is for
    assert any(a.kind == "scheme" and a.card is magician for a in ai.candidates(g, Model(g, 0)))


def test_the_big_reveal_is_never_spent_as_a_boost_not_even_to_survive(bprd):
    """Iván 3/11, absolute: not in a Maneuver (ESCAPE ARTIST included), not in a combat, not as the boost of another Big Reveal;
    and the hand limit gives up other cards first."""
    g = mk(bprd)
    reveal, other = give(g, 0, "The Big Reveal"), give(g, 0, "The Big Reveal", 1)
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver" and act.boost is None
    assert free_boosts(g, 0, other, g.players[0].hand) == []
    houdini, hellboy = pair(g, "houdini", "hellboy")
    houdini.hp = 2                                                  # a blow that kills: a boost would save him, and still it is not spent
    ctx = type("Ctx", (), dict(target=houdini, atk_card=None, atk_value=6, def_value=2))()
    assert MedusaAI(0).choose_combat_boost(g, ctx) is None
    cards = [reveal, give(g, 0, "Flourish"), give(g, 0, "Smoke and Mirrors")]
    assert keep_order(g, cards)[-1] == "The Big Reveal"


def poke(bprd, monkeypatch, title, fighter, boost_title, floor_table):
    """The bot's last action with `title` and `boost_title` in hand, `fighter` next to Hellboy (4 cards in his hand): does it attack?"""
    import sparring.ai_medusa as m
    monkeypatch.setattr(m, "POKE_FLOOR", floor_table)
    g = mk(bprd)
    pair(g, fighter, "hellboy")
    give(g, 0, title)
    give(g, 0, boost_title)
    rival_hand(g, 4, avoid=("Feint", "Misdirection"))
    g.actions_left = 1
    act = MedusaAI(0).plan(g)
    return act.kind == "attack" and act.card.title == title and act.fid == fighter


# (card, fighter, the boost card that makes the blow decent but not a big one): each attacks with the poke table and does not without it
POKES = [("Flourish", "houdini", "Grand Escape"), ("An Illusion of My Own Design", "houdini", "Vanishing Act"),
         ("Flourish", "bess", "Vanishing Act")]


def test_bess_never_defends_with_all_part_of_the_show_and_houdini_not_against_a_blow_that_will_not_kill(bprd):
    g = mk(bprd)
    ai = MedusaAI(0)
    card = give(g, 0, "All Part of the Show")
    hellboy, bess = pair(g, "hellboy", "bess")
    bess.hp = 1                                        # her defeat does not save Houdini: the card is not for her
    assert ai.choose_defense(g, hellboy, bess) is not card
    houdini, hellboy = pair(g, "houdini", "hellboy")
    houdini.hp = 8
    assert ai.choose_defense(g, hellboy, houdini) is not card


def test_the_search_bans_the_big_reveal_and_the_rescue_card_as_the_bots_maneuver_boost_only(bprd):
    from sparring.search.adapter import EngineState
    g = mk(bprd)
    for t in ("The Big Reveal", "All Part of the Show", "Flourish"):
        give(g, 0, t)
    bot = {c.title if c else None for c in EngineState(g, observer=0)._boost_variants(0)}
    assert bot == {None, "Flourish"}
    modelled = {c.title if c else None for c in EngineState(g, observer=1)._boost_variants(0)}
    assert {"The Big Reveal", "All Part of the Show"} <= modelled


def magician_turn(bprd, hp):
    g = mk(bprd)
    g.fighters["houdini"].hp = hp
    magician = give(g, 0, "A Magician Never Reveals His Secrets")
    give(g, 0, "The Big Reveal")
    hand_filler(g, 0, 2, avoid=("The Big Reveal", "A Magician Never Reveals His Secrets"))
    rival_hand(g, 4)
    g.actions_left = 1
    MedusaAI(0).take_turn(g)
    return g, magician


@pytest.mark.parametrize("hp", [14, 8, 5])
def test_the_magician_is_not_played_as_a_scheme_while_a_big_reveal_is_unseen(bprd, monkeypatch, hp):
    """Through the planner (`take_turn`), not just the ranking. The control: with the plan "dead" (no finisher seen) the same scene plays it."""
    g, magician = magician_turn(bprd, hp)
    assert magician in g.players[0].hand and magician not in g.players[0].discard
    import sparring.ai_medusa as m
    monkeypatch.setattr(m, "finisher_plan", lambda *a, **k: None)
    g, magician = magician_turn(bprd, hp)
    assert magician in g.players[0].discard


def test_all_part_of_the_show_is_never_a_maneuver_boost_in_a_whole_turn_at_low_life(bprd):
    for hp in (9, 5, 2):
        g = mk(bprd)
        g.fighters["houdini"].hp = hp
        card = give(g, 0, "All Part of the Show")
        give(g, 0, "Sleight of Hand")
        give(g, 0, "The Big Reveal")
        hand_filler(g, 0, 1, avoid=("The Big Reveal", "All Part of the Show", "Sleight of Hand"))
        g.actions_left = 2
        MedusaAI(0).take_turn(g)
        assert card in g.players[0].hand


@pytest.mark.parametrize("title,fighter,boost", POKES)
def test_flourish_and_the_illusion_are_played_as_pokes_by_houdini_and_bess(bprd, monkeypatch, title, fighter, boost):
    from sparring.ai_medusa import POKE_FLOOR
    assert poke(bprd, monkeypatch, title, fighter, boost, POKE_FLOOR)
    assert not poke(bprd, monkeypatch, title, fighter, boost, {})

