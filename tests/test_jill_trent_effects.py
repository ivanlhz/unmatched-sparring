"""Jill Trent on the engine, bot side (player 0 plays Jill, the controllers answer): GADGETOLOGY (the choice at the start of the
turn, Hypnoray Blaster, Ultrabiotic Tonic, and Daisy borrowing them through Sisters In Arms) and every card with the numbers printed
on it. The human side (panel, FakeTTS) is in tests/test_jill_trent_human.py and the full games in tests/test_jill_trent_matrix.py."""
from __future__ import annotations

import pytest

from conftest import card, give
from sparring.effects.select import counter_value
from sparring.state import Game
from test_bigfoot_effects import Answers, pick, start_turn
from test_effects_combat import pair, put_adjacent

HYPNORAY, TONIC = 1, 2


def mk(bprd, foe="hellboy", seed=3, turn=0, gadget=HYPNORAY):
    """Jill = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands, the gadget already active."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("jill-trent", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    g.fx.set_counter(0, "gadget", gadget)
    return g


def on_top(g, player, title):
    """The first card of `title` goes to the top of the player's deck (and its identity is returned)."""
    c = next(c for c in g.players[player].deck if c.title == title)
    g.players[player].deck.remove(c)
    g.players[player].deck.insert(0, c)
    return c


def wall(g, title="B.P.R.D. Training"):
    """A defense of the rival's, in hand, that cancels nothing and is worth 3 (Hellboy's own `wall` is Planned Recklessness, which does)."""
    c = next(c for c in g.players[1].deck if c.title == title)
    g.players[1].deck.remove(c)
    g.players[1].hand.append(c)
    return c


class Smart(Answers):
    """The bot's own judgement (EffectAI) answers what the queue does not."""

    def choose_effect(self, game, req):
        from sparring.ai_effects import EffectAI
        answer = super().choose_effect(game, req)
        return answer if answer is not None else EffectAI(self_player(game, self)).choose_effect(game, req)


def self_player(game, ctl) -> int:
    return next(p for p, c in game.controllers.items() if c is ctl)


# ---------------------------------------------------------------- the hero and the deck

def test_jill_is_a_melee_hero_with_daisy(bprd):
    g = mk(bprd)
    jill, daisy = g.fighters["jill"], g.fighters["daisy"]
    assert (jill.hp, jill.move, jill.ranged, jill.reach) == (13, 2, False, 0)
    assert (daisy.hp, daisy.move, daisy.ranged, daisy.hero) == (6, 2, False, False)
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629


# ---------------------------------------------------------------- GADGETOLOGY: the choice at the start of the turn

def test_the_gadget_is_chosen_at_the_start_of_every_turn_of_hers(bprd):
    g = mk(bprd)
    ctl = g.controllers[0]
    ctl.queue = [[1]]
    start_turn(g)
    assert counter_value(g, 0, "gadget") == TONIC
    req = ctl.requests[-1]
    assert req.kind == "effect" and req.extra["tag"] == "gadget" and req.extra["labels"] == ["Hypnoray Blaster", "Ultrabiotic Tonic"]
    ctl.queue = [[0]]
    start_turn(g)
    assert counter_value(g, 0, "gadget") == HYPNORAY


def test_the_rivals_turn_does_not_ask_for_a_gadget(bprd):
    g = mk(bprd)
    before = len(g.controllers[0].requests)
    g.fx.emit("start_of_turn", 1)
    assert len(g.controllers[0].requests) == before and counter_value(g, 0, "gadget") == HYPNORAY


def test_no_gadget_is_active_before_her_first_turn(bprd):
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("jill-trent", "hellboy"), bot_player=0)
    assert counter_value(g, 0, "gadget") == 0


def test_the_bot_chooses_the_tonic_when_hurt_and_the_blaster_with_a_hypnotist_in_hand(bprd):
    from sparring.ai_effects import EffectAI
    from sparring.effects.choose import ChoiceRequest
    g = mk(bprd)
    req = ChoiceRequest(kind="effect", player=0, options=[0, 1], min=1, max=1, key="gadgetology", prompt="choose an effect",
                        extra={"labels": ["Hypnoray Blaster", "Ultrabiotic Tonic"], "tag": "gadget"})
    ai = EffectAI(0)
    assert ai.choose_effect(g, req) == [0]
    g.fighters["jill"].hp -= 5
    assert ai.choose_effect(g, req) == [1]
    give(g, 0, "Hypnotist")
    assert ai.choose_effect(g, req) == [0]


# ---------------------------------------------------------------- Hypnoray Blaster

def test_hypnoray_adds_the_boost_of_the_rivals_top_card_when_her_printed_value_is_lower(bprd):
    g = mk(bprd)
    jill, foe = pair(g, "jill", "hellboy")
    top = on_top(g, 1, "Second Shot")
    attack = give(g, 0, "Battle of Wits")                       # printed 2
    defense = wall(g)                                           # printed value above 2
    assert (defense.value or 0) > 2 and defense.title == 'B.P.R.D. Training'
    g.fx.intents = []
    res = g.attack(jill, foe, attack, defense)
    assert res.atk_value == 2 + top.boost
    assert {"op": "reveal_top", "player": 1, "viewer": 0, "cards": [top.card_id]} in g.fx.intents
    assert top not in g.players[1].discard                                # revealed, not discarded


def test_hypnoray_does_nothing_when_her_printed_value_is_not_lower(bprd):
    g = mk(bprd)
    jill, foe = pair(g, "jill", "hellboy")
    on_top(g, 1, "Second Shot")
    res = g.attack(jill, foe, give(g, 0, "Energizing Spray"), None)       # printed 5, no card against: 0
    assert res.atk_value == 5


def test_hypnoray_is_for_her_attacks_only_not_her_defenses(bprd):
    g = mk(bprd, turn=1)
    jill, foe = pair(g, "jill", "hellboy")
    on_top(g, 1, "Second Shot")
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) == 5))
    res = g.attack(foe, jill, attack, give(g, 0, "Hypnotist"))
    assert res.def_value == 3


def test_hypnoray_runs_even_when_the_card_was_cancelled(bprd):
    """The gadget is on the hero, not on the card: a Feint cancels Battle of Wits, not the Blaster."""
    g = mk(bprd, "bullseye")
    jill, foe = pair(g, "jill", "bullseye")
    top = on_top(g, 1, "Master Strategist")                              # BOOST 3
    res = g.attack(jill, foe, give(g, 0, "Caught Red-Handed"), give(g, 1, "Feint"))       # printed 1 against 2
    assert res.cancelled and res.atk_value == 1 + top.boost


def test_hypnoray_reveals_nothing_on_an_empty_deck(bprd):
    g = mk(bprd)
    jill, foe = pair(g, "jill", "hellboy")
    defense = wall(g)
    g.players[1].deck.clear()
    res = g.attack(jill, foe, give(g, 0, "Battle of Wits"), defense)
    assert res.atk_value == 2


def test_the_tonic_gadget_does_not_reveal_anything(bprd):
    g = mk(bprd, gadget=TONIC)
    jill, foe = pair(g, "jill", "hellboy")
    on_top(g, 1, "Second Shot")
    res = g.attack(jill, foe, give(g, 0, "Battle of Wits"), wall(g))
    assert res.atk_value == 2


# ---------------------------------------------------------------- Ultrabiotic Tonic

def test_the_tonic_heals_one_when_her_printed_value_is_higher(bprd):
    g = mk(bprd, gadget=TONIC)
    jill, foe = pair(g, "jill", "hellboy")
    jill.hp = 8
    g.attack(jill, foe, give(g, 0, "Energizing Spray"), None)           # 5 against nothing
    assert jill.hp == 9


def test_the_tonic_does_nothing_when_her_printed_value_is_not_higher(bprd):
    g = mk(bprd, gadget=TONIC)
    jill, foe = pair(g, "jill", "hellboy")
    jill.hp = 8
    g.attack(jill, foe, give(g, 0, "Battle of Wits"), wall(g))
    assert jill.hp == 8


def test_the_tonic_does_not_heal_when_daisy_attacks_without_sisters_in_arms(bprd):
    g = mk(bprd, gadget=TONIC)
    daisy, foe = pair(g, "daisy", "hellboy")
    g.fighters["jill"].hp = 8
    g.attack(daisy, foe, give(g, 0, "Ace Fighter"), None)
    assert g.fighters["jill"].hp == 8


def test_the_tonic_heals_even_when_her_card_is_cancelled(bprd):
    g = mk(bprd, "bullseye", gadget=TONIC)
    jill, foe = pair(g, "jill", "bullseye")
    jill.hp = 8
    res = g.attack(jill, foe, give(g, 0, "Energizing Spray"), give(g, 1, "Feint"))
    assert res.cancelled and jill.hp == 9


# ---------------------------------------------------------------- Sisters In Arms

def test_daisy_borrows_the_blaster_when_jill_is_next_to_her(bprd):
    g = mk(bprd)
    daisy, foe = pair(g, "daisy", "hellboy")
    put_adjacent(g, "jill", "daisy")
    top = on_top(g, 1, "Second Shot")
    res = g.attack(daisy, foe, give(g, 0, "Sisters in Arms"), wall(g))       # printed 3 against the wall's 3 or more
    printed = wall_value = res.def_value
    assert res.atk_value == 3 + (top.boost if 3 < (res.def_card.value or 0) else 0)


def test_daisy_does_not_borrow_the_blaster_when_jill_is_far(bprd):
    g = mk(bprd)
    daisy, foe = pair(g, "daisy", "hellboy")
    g.fighters["jill"].pos = max(g.board.spaces)
    assert not g.board.adj[daisy.pos].__contains__(g.fighters["jill"].pos)
    on_top(g, 1, "Second Shot")
    res = g.attack(daisy, foe, give(g, 0, "Sisters in Arms"), wall(g))
    assert res.atk_value == 3


def test_daisy_borrows_the_tonic_and_it_is_jill_who_recovers(bprd):
    g = mk(bprd, gadget=TONIC)
    daisy, foe = pair(g, "daisy", "hellboy")
    put_adjacent(g, "jill", "daisy")
    g.fighters["jill"].hp, daisy.hp = 8, 4
    g.attack(daisy, foe, give(g, 0, "Sisters in Arms"), None)           # printed 3 against nothing
    assert g.fighters["jill"].hp == 9 and daisy.hp == 4


def test_sisters_in_arms_cannot_be_cancelled(bprd):
    from sparring.effects.model import load_effects
    assert load_effects("jill-trent").cards["Sisters in Arms"].uncancelable


# ---------------------------------------------------------------- Hypnotist

def test_hypnotist_cancels_the_rivals_effects_only_with_the_blaster_active(bprd):
    for gadget, cancelled in ((HYPNORAY, True), (TONIC, False)):
        g = mk(bprd, turn=1, gadget=gadget)
        jill, foe = pair(g, "jill", "hellboy")
        hurt = give(g, 1, "Second Shot") if any(c.title == "Second Shot" for c in g.players[1].full_set) else None
        attack = give(g, 1, next(c.title for c in g.players[1].deck if c.type == "attack" and c.text.strip()))
        res = g.attack(foe, jill, attack, give(g, 0, "Hypnotist"))
        assert (0 in res.cancelled or 1 in res.cancelled or "atk" in res.cancelled) is cancelled, gadget


def test_hypnotist_does_nothing_before_a_gadget_was_ever_activated(bprd):
    g = mk(bprd, turn=1, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.type == "attack" and c.text.strip()))
    res = g.attack(foe, jill, attack, give(g, 0, "Hypnotist"))
    assert not res.cancelled


# ---------------------------------------------------------------- Stasis Diffuser

def test_stasis_diffuser_puts_the_rivals_value_back_to_its_printed_value_and_freezes_it(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    defense = wall(g)
    boost = next(c for c in g.players[1].deck if c.boost >= 2)
    g.players[1].deck.remove(boost)
    g.players[1].hand.append(boost)
    g.controllers[1].boost = boost
    res = g.attack(jill, foe, give(g, 0, "Stasis Diffuser"), defense)
    assert res.def_value == (defense.value or 0)                    # no boost, no bonus: the printed value


def test_stasis_diffuser_ignores_a_value_effect_of_the_rival_too(bprd):
    g = mk(bprd, "bullseye", gadget=0)
    jill, foe = pair(g, "jill", "bullseye")
    attack = give(g, 0, "Stasis Diffuser")
    best = next(c for c in g.players[1].deck if c.title == "I'm Better And I'll Prove It")
    g.players[1].deck.remove(best)
    g.players[1].hand.append(best)
    g.fx.won[1] = 1                                                  # Bullseye would defend with 6
    res = g.attack(jill, foe, attack, best)
    assert res.def_value == 2


def test_stasis_diffuser_with_no_card_against_it_does_nothing(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    res = g.attack(jill, foe, give(g, 0, "Stasis Diffuser"), None)
    assert res.attacker_won and res.damage == 3


def test_the_lock_is_saved_with_the_combat(bprd):
    from sparring.combat_flow import CombatFlow
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    attack, defense = give(g, 0, "Stasis Diffuser"), wall(g)
    flow = g.begin_attack(jill, foe, attack, defense)
    while flow.phase.value != "during":
        assert flow.step() is None
    assert flow.value_locked == {"def"}
    back = CombatFlow.from_dict(g, flow.to_dict())
    assert back.value_locked == {"def"}


# ---------------------------------------------------------------- Indestructible Cloth

def ricochet_at_jill(bprd, defense_title):
    """Bullseye attacks Jill with Ricochet (value 3: 1 damage to a fighter in the zone of the opposing fighter, here Jill herself) and she
    defends with `defense_title`. Returns (game, Jill's hit points before, the result)."""
    g = mk(bprd, "bullseye", turn=1, gadget=0)
    jill, foe = pair(g, "jill", "bullseye")
    g.controllers[1].queue = [["jill"]]
    hp = jill.hp
    res = g.attack(foe, jill, give(g, 1, "Ricochet"), give(g, 0, defense_title))
    return g, hp, res


def test_without_the_cloth_the_rivals_after_effect_damages_her(bprd):
    g, hp, res = ricochet_at_jill(bprd, "Hypnotist")
    assert res.damage == 0 and g.fighters["jill"].hp == hp - 1


def test_indestructible_cloth_stops_the_effect_damage_of_the_combat(bprd):
    g, hp, res = ricochet_at_jill(bprd, "Indestructible Cloth")
    assert res.damage == 0 and g.fighters["jill"].hp == hp


def test_indestructible_cloth_lasts_this_combat_only(bprd):
    g, hp, res = ricochet_at_jill(bprd, "Indestructible Cloth")
    assert not any(st["name"] == "immune_to_effect_damage" for st in g.fx.statuses)
    assert g.damage(g.fighters["jill"], 1, "effect") == 1             # an effect damage after the combat lands again


def test_indestructible_cloth_does_not_stop_combat_damage(bprd):
    g = mk(bprd, "bullseye", turn=1, gadget=0)
    jill, foe = pair(g, "jill", "bullseye")
    hp = jill.hp
    res = g.attack(foe, jill, give(g, 1, "World's Greatest Assassin"), give(g, 0, "Indestructible Cloth"))
    assert res.damage == 0 and jill.hp == hp                           # 5 holds the 4; and with a bigger blow the damage lands
    g.players[1].discard.clear()
    res = g.attack(foe, jill, give(g, 1, "Sweet Christmas!") if False else give(g, 1, "Master Strategist"), None)
    assert res.damage > 0 and jill.hp == hp - res.damage


# ---------------------------------------------------------------- the simple cards

def test_energizing_spray_gains_an_action(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    start_turn(g)
    g.actions_left = 2
    g.attack(jill, foe, give(g, 0, "Energizing Spray"), None)
    assert g.actions_left == 2                                        # spent 1, gained 1


def test_ace_fighter_draws_a_card(bprd):
    g = mk(bprd, gadget=0)
    daisy, foe = pair(g, "daisy", "hellboy")
    hand = len(g.players[0].hand)
    g.attack(daisy, foe, give(g, 0, "Ace Fighter"), None)
    assert len(g.players[0].hand) == hand + 1                         # -1 played, +1 given, +1 drawn


def test_laser_pen_deals_one_damage_to_the_opposing_fighter(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    g.attack(jill, foe, give(g, 0, "Laser Pen"), wall(g))
    assert foe.hp == foe.max_hp - 1 and jill.hp == jill.max_hp


def test_gyroscopic_jetpack_moves_the_fighter_that_played_it_up_to_two_through_rivals(bprd):
    g = mk(bprd, gadget=0)
    daisy, foe = pair(g, "daisy", "hellboy")
    start = daisy.pos
    g.controllers[0].queue = [lambda req: None]
    g.attack(daisy, foe, give(g, 0, "Gyroscopic Jetpack"), wall(g))
    assert g.board.distance(start, daisy.pos) <= 2
    reqs = [r for r in g.controllers[0].requests if r.kind == "space"]
    assert reqs and reqs[-1].extra["through"] is True and reqs[-1].extra["fighter"] == "daisy" and reqs[-1].extra["steps"] == 2


def test_caught_red_handed_makes_the_rival_discard_one_and_two_if_it_won(bprd):
    for wins, discarded in ((False, 1), (True, 2)):
        g = mk(bprd, gadget=0)
        jill, foe = pair(g, "jill", "hellboy")
        for c in list(g.players[1].deck)[:4]:
            g.players[1].deck.remove(c)
            g.players[1].hand.append(c)
        block = None if wins else wall(g)                                  # Training: draws 1 after the combat
        before = len(g.players[1].hand)
        res = g.attack(jill, foe, give(g, 0, "Caught Red-Handed"), block)
        assert res.attacker_won is wins
        assert len(g.players[1].hand) == before - (1 if block else 0) + (1 if block else 0) - discarded, wins


def test_utility_belt_offers_the_three_options_of_the_card(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    ctl = g.controllers[0]
    jill.hp = 9
    ctl.queue = [[0]]
    g.attack(jill, foe, give(g, 0, "Utility Belt"), wall(g))
    assert ctl.requests[-1].extra["labels"] == ["Jill Trent recovers 1 health", "Move Jill Trent 1 space", "Draw 1 card"]
    assert jill.hp == 10
    ctl.queue = [[2]]
    hand = len(g.players[0].hand)
    g.attack(jill, foe, give(g, 0, "Utility Belt", 1), wall(g))
    assert len(g.players[0].hand) == hand + 1


def test_utility_belt_moves_jill_exactly_one_space(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    start = jill.pos
    ctl = g.controllers[0]
    ctl.queue = [[1], pick(lambda s: True)]
    g.attack(jill, foe, give(g, 0, "Utility Belt"), wall(g))
    assert g.board.distance(start, jill.pos) == 1


def test_battle_of_wits_hits_for_three_only_with_the_higher_boost(bprd):
    for mine_boost, theirs, expected in (("high", "low", 3), ("low", "high", 0)):
        g = mk(bprd, gadget=0)
        jill, foe = pair(g, "jill", "hellboy")
        big = max((c for c in g.players[0].deck), key=lambda c: c.boost)
        small = min((c for c in g.players[1].deck), key=lambda c: c.boost)
        big_their = max((c for c in g.players[1].deck), key=lambda c: c.boost)
        small_mine = min((c for c in g.players[0].deck if c.title != "Battle of Wits"), key=lambda c: c.boost)
        mine, rival = (big, small) if mine_boost == "high" else (small_mine, big_their)
        for p, c in ((0, mine), (1, rival)):
            g.players[p].deck.remove(c)
            g.players[p].deck.insert(0, c)
        hp = foe.hp
        g.attack(jill, foe, give(g, 0, "Battle of Wits"), wall(g) if False else None)
        dealt = hp - foe.hp - 2                                           # 2 of combat damage against no defense
        assert dealt == expected, (mine_boost, mine.boost, rival.boost)


def test_battle_of_wits_with_equal_boosts_deals_nothing(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    a = next(c for c in g.players[0].deck if c.boost == 2 and c.title != "Battle of Wits")
    b = next(c for c in g.players[1].deck if c.boost == 2)
    for p, c in ((0, a), (1, b)):
        g.players[p].deck.remove(c)
        g.players[p].deck.insert(0, c)
    hp = foe.hp
    g.attack(jill, foe, give(g, 0, "Battle of Wits"), None)
    assert hp - foe.hp == 2


def test_helpful_assistant_shuffles_up_to_three_jill_cards_back_and_draws(bprd):
    g = mk(bprd, gadget=0)
    me = g.players[0]
    jill_cards = [c for c in me.full_set if c.fighter == "Dr. Jill Trent"][:4]
    other = [c for c in me.full_set if c.fighter != "Dr. Jill Trent"][:2]
    for c in jill_cards + other:
        if c in me.deck:
            me.deck.remove(c)
        me.discard.append(c)
    scheme = give(g, 0, "Helpful Assistant")
    deck_before, hand_before = len(me.deck), len(me.hand)
    g.controllers[0].queue = [[c.card_id for c in jill_cards[:3]]]
    g.play_scheme(0, g.fighters["daisy"], scheme)
    assert len(me.deck) == deck_before + 3 - 1                         # 3 back, 1 drawn
    assert all(c.fighter == "Dr. Jill Trent" for c in me.discard if c in jill_cards[:3]) and not any(c in me.discard for c in jill_cards[:3])
    assert all(c in me.discard for c in other)
    req = next(r for r in g.controllers[0].requests if r.kind == "cards")
    assert set(req.options) == {c.card_id for c in jill_cards} and req.max == 3 and req.min == 0


# ---------------------------------------------------------------- Insightful Deduction

def test_insightful_deduction_buries_one_and_orders_the_rest(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    deck = g.players[1].deck
    top3 = list(deck[:3])
    ctl = g.controllers[0]
    ctl.queue = [[top3[0].card_id], [top3[2].card_id, top3[1].card_id]]
    g.attack(jill, foe, give(g, 0, "Insightful Deduction"), None)
    assert deck[0] is top3[2] and deck[1] is top3[1] and deck[-1] is top3[0]
    assert g.players[0].known.top_of_deck == [top3[2].card_id, top3[1].card_id]


def test_the_bot_buries_the_best_card_of_the_rival_and_leaves_the_weakest_on_top(bprd):
    from sparring.search.adapter import card_worth
    g = mk(bprd, gadget=0)
    g.controllers[0] = Smart()
    jill, foe = pair(g, "jill", "hellboy")
    deck = g.players[1].deck
    top3 = list(deck[:3])
    g.attack(jill, foe, give(g, 0, "Insightful Deduction"), None)
    best = max(top3, key=lambda c: (card_worth(c), -c.card_id))
    assert deck[-1] is best and deck[:2] == sorted([c for c in top3 if c is not best], key=lambda c: (card_worth(c), c.card_id))


def test_insightful_deduction_with_a_short_deck_does_what_it_can(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")
    deck = g.players[1].deck
    del deck[2:]
    two = list(deck)
    g.attack(jill, foe, give(g, 0, "Insightful Deduction"), None)
    assert sorted(c.card_id for c in deck) == sorted(c.card_id for c in two) and len(deck) == 2


def test_insightful_deduction_reads_the_human_deck_through_the_table_reader(bprd):
    """The rival is the table player: the bot reads their real top three through `Game.deck_reader` and the engine's placeholder
    deck is left alone (the human rearranges the real one by hand)."""
    from sparring.effects import table
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")

    class Human(Answers):
        human = True
    g.controllers[1] = Human()
    real = [c.card_id for c in g.players[1].deck[5:8]]
    g.deck_reader = lambda player, n=None: real[:n] if n else real[0]
    g.fx.intents = []
    before = [c.card_id for c in g.players[1].deck]
    g.attack(jill, foe, give(g, 0, "Insightful Deduction"), None)
    assert [c.card_id for c in g.players[1].deck] == before
    intent = next(i for i in g.fx.intents if i["op"] == "deck_order")
    assert sorted(intent["top"] + [intent["bottom"]]) == sorted(real) and intent["player"] == 1
    assert table.physical(g, 1)


def test_a_table_that_cannot_be_read_shows_nothing(bprd):
    g = mk(bprd, gadget=0)
    jill, foe = pair(g, "jill", "hellboy")

    class Human(Answers):
        human = True
    g.controllers[1] = Human()
    g.deck_reader = None
    g.fx.intents = []
    hp = foe.hp
    g.attack(jill, foe, give(g, 0, "Insightful Deduction"), None)
    assert not any(i["op"] in ("deck_order", "reveal_top") for i in g.fx.intents) and foe.hp == hp - 3
