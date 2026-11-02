"""Doctor Strange's cards and DARK PACT on the interpreter, bot side (player 0 plays Doctor Strange, controllers answer).

The human side (panel, FakeTTS) is in tests/test_doctor_strange_human.py. Every card has a test here; the numbers are the
ones printed on the real cards (data/heroes/doctor-strange.json)."""
from __future__ import annotations

import json

import pytest

from conftest import give
from sparring import persist
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import SURVIVAL_P, Model
from sparring.effects.choose import ChoiceRequest
from sparring.state import Game
from test_d1_bot_cards import kill
from test_effects_combat import Asking, hp, pair, put_adjacent

STRANGE_DECK = ["The Winds of Watoomb", "The Rings of Raggadorr", "Bolts of Balthakk", "Seven Suns of Cinnibus",
                "Cloak of Levitation", "Feint", "Master of Kamar-Taj", "Steadfast Disciple", "The Mists of Munnopor",
                "No, Really, I'm a Doctor", "Eye of Agamotto"]


def mk(bprd, foe="hellboy", seed=3):
    """Doctor Strange = player 0 (the bot), `foe` = player 1; player 0's turn, empty hands."""
    ctl = {0: Asking(), 1: Asking()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("doctor-strange", foe), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def decline_pact(g):
    """Doctor Strange's DARK PACT is a decision of his player; most tests are about the card, so it is declined."""
    g.controllers[0].queue = []

    def choose(game, req):
        return [False] if "pact" in req.extra else None
    g.controllers[0].choose_effect = choose


def on_top(g, player, *titles):
    """The cards titled so go to the top of the deck, in that order."""
    deck = g.players[player].deck
    cards = []
    for t in titles:
        c = next(c for c in deck if c.title == t and c not in cards)
        cards.append(c)
    for c in cards:
        deck.remove(c)
    deck[:0] = cards
    return cards


# ---------------------------------------------------------------- the deck and the switch

def test_doctor_strange_is_interpreted_with_wong_and_his_ability_is_a_trigger_on_after_combat(bprd):
    g = mk(bprd)
    assert "doctor-strange" in g.fx.dsl_heroes
    assert [f.fid for f in g.own(0)] == ["strange", "wong"]
    assert (g.fighters["strange"].hp, g.fighters["wong"].hp) == (14, 6)
    assert g.fighters["strange"].ranged and g.fighters["wong"].ranged
    titles = {c.title for c in g.players[0].full_set}
    assert titles == set(STRANGE_DECK) and len(g.players[0].full_set) == 30


# ---------------------------------------------------------------- attack cards

def test_rings_heal_strange_and_the_friendly_fighters_beside_him_by_the_damage_dealt(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    put_adjacent(g, "wong", "strange")
    s.hp, g.fighters["wong"].hp = 8, 3
    res = g.attack(s, liz, give(g, 0, "The Rings of Raggadorr"), None)
    assert res.damage == 4 and hp(g, "strange", "wong", "liz") == [12, 6, 12]          # +4 and +4 (capped at 6)


def test_rings_do_nothing_when_the_combat_is_lost(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    s.hp = 8
    res = g.attack(s, liz, give(g, 0, "The Rings of Raggadorr"), give(g, 1, "Evade"))   # 4 vs 2: won, damage 2
    assert res.damage == 1 and s.hp == 9                     # 4 vs 3: Evade is worth 3
    s.hp = 8
    g.actions_left = 2
    res = g.attack(s, liz, give(g, 0, "The Rings of Raggadorr", 1), give(g, 1, "Evade", 1), values=(0, 5))   # 4 vs 3 + 5: lost
    assert not res.attacker_won and s.hp == 8


def test_bolts_gain_an_action_when_they_win_and_blind_boost_adds_the_top_card_of_the_deck(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    (top,) = on_top(g, 0, "Bolts of Balthakk")
    g.controllers[0].choose_effect = lambda game, req: [True] if req.extra.get("blind_boost") else ([False] if "pact" in req.extra else None)
    g.actions_left = 2
    card = give(g, 0, "Bolts of Balthakk", 1)
    deck_before = len(g.players[0].deck)
    res = g.attack(s, liz, card, None)
    assert res.atk_value == 2 + top.boost == 5 and top in g.players[0].discard
    assert len(g.players[0].deck) == deck_before - 1
    assert res.attacker_won and g.actions_left == 2           # 2 - 1 spent + 1 gained


def test_bolts_without_a_blind_boost_use_nothing_and_a_lost_combat_gives_no_action(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    g.controllers[0].choose_effect = lambda game, req: [False]
    g.actions_left = 2
    card = give(g, 0, "Bolts of Balthakk")
    deck_before = len(g.players[0].deck)
    res = g.attack(s, liz, card, give(g, 1, "Evade"))                  # 2 vs 2: a tie, lost
    assert res.atk_value == 2 and len(g.players[0].deck) == deck_before and not res.attacker_won and g.actions_left == 1


def test_seven_suns_blind_boost_twice_and_a_total_above_seven_counts_for_nothing(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    on_top(g, 0, "Bolts of Balthakk", "Bolts of Balthakk")        # boost 3 each: 3 + 3 + 3 = 9 > 7
    g.controllers[0].choose_effect = lambda game, req: [True] if req.extra.get("blind_boost") else ([False] if "pact" in req.extra else None)
    res = g.attack(s, liz, give(g, 0, "Seven Suns of Cinnibus"), None)
    assert res.atk_value == 0 and res.damage == 0 and not res.attacker_won


def test_seven_suns_stay_at_seven_or_below_and_are_boosted_up_to_two_times_only(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    on_top(g, 0, "Master of Kamar-Taj", "Feint", "Eye of Agamotto")      # boosts 2, 1 (scheme boost 2)
    asked = []

    def choose(game, req):
        if req.extra.get("blind_boost"):
            asked.append(req.extra["left"])
            return [True]
        return [False] if "pact" in req.extra else None
    g.controllers[0].choose_effect = choose
    res = g.attack(s, liz, give(g, 0, "Seven Suns of Cinnibus"), None)
    assert asked == [2, 1] and res.atk_value == 3 + 2 + 1 == 6 and res.attacker_won


# ---------------------------------------------------------------- versatile cards

def test_cloak_ignores_the_rivals_value_when_strange_is_next_to_the_opposing_fighter(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    res = g.attack(s, liz, give(g, 0, "Cloak of Levitation"), give(g, 1, "Burning Barrier"))
    assert res.def_value == 0 and res.atk_value == 2 and res.attacker_won and res.damage == 2


def test_cloak_does_nothing_when_strange_is_not_adjacent(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    far = next(sp for sp in sorted(g.board.spaces) if sp not in {f.pos for f in g.fighters.values() if f.alive}
               and g.board.distance(sp, liz.pos) == 2 and g.board.can_reach_target(sp, liz.pos, True))
    s.pos = far
    res = g.attack(s, liz, give(g, 0, "Cloak of Levitation"), give(g, 1, "Burning Barrier"))
    assert res.def_value == 2 and not res.attacker_won


def test_master_of_kamar_taj_is_four_with_wong_beside_strange_and_two_without(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    put_adjacent(g, "wong", "strange")
    res = g.attack(s, liz, give(g, 0, "Master of Kamar-Taj"), None)
    assert res.atk_value == 4
    g2 = mk(bprd, "liz-sherman")
    decline_pact(g2)
    s2, liz2 = pair(g2, "strange", "liz")
    res = g2.attack(s2, liz2, give(g2, 0, "Master of Kamar-Taj"), None)
    assert res.atk_value == 2


def test_steadfast_disciple_hits_for_one_and_draws_when_wong_is_next_to_the_opposing_fighter(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    wong, liz = pair(g, "wong", "liz")
    card = give(g, 0, "Steadfast Disciple")
    before, liz_hp = len(g.players[0].hand), liz.hp
    res = g.attack(wong, liz, card, None)
    assert res.damage == 2 and liz.hp == liz_hp - 2 - 1 and len(g.players[0].hand) == before - 1 + 1


def test_steadfast_disciple_from_a_distance_only_does_combat_damage(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    wong, liz = pair(g, "wong", "liz")
    wong.pos = next(sp for sp in sorted(g.board.spaces) if sp not in {f.pos for f in g.fighters.values() if f.alive}
                    and g.board.distance(sp, liz.pos) == 2 and g.board.can_reach_target(sp, liz.pos, True))
    card = give(g, 0, "Steadfast Disciple")
    before, liz_hp = len(g.players[0].hand), liz.hp
    res = g.attack(wong, liz, card, None)
    assert liz.hp == liz_hp - 2 and len(g.players[0].hand) == before - 1


def test_feint_cancels_the_rivals_effects(bprd):
    g = mk(bprd, "liz-sherman")
    g.turn, g.actions_left = 1, 2
    s, liz = pair(g, "strange", "liz")
    liz_atk = give(g, 1, "Flame Lash")                       # DURING: the bottom card of the deck boosts it; AFTER: an action
    res = g.attack(liz, s, liz_atk, give(g, 0, "Feint"))
    assert "atk" in res.cancelled and res.atk_value == liz_atk.value and g.actions_left == 1


# ---------------------------------------------------------------- The Mists of Munnopor

def test_mists_replace_the_attackers_card_with_the_first_playable_one_of_its_deck(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    g.turn, g.actions_left = 1, 2
    s, liz = pair(g, "strange", "liz")
    deck = g.players[1].deck
    first_two = on_top(g, 1, "Burning Barrier", "Evade", "Fireball")          # Burning Barrier / Evade are versatile? see below
    attacker_card = give(g, 1, "Flame Lash")
    playable = next(c for c in deck if c.can_attack and c.usable_by("Liz Sherman"))
    skipped = deck[:deck.index(playable)]
    mists = give(g, 0, "The Mists of Munnopor")
    hand_before = len(g.players[1].hand)
    res = g.attack(liz, s, attacker_card, mists)
    assert res.atk_card == playable and attacker_card in g.players[1].discard
    assert playable in g.players[1].discard                          # the replacement was played: it ends in the discard
    assert all(c in g.players[1].deck[-len(skipped):] for c in skipped) if skipped else True
    assert len(g.players[1].hand) == hand_before - 1                 # the card played from the hand was the original one


def test_mists_leave_the_attacker_without_a_card_when_no_playable_card_is_in_the_deck(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    g.turn, g.actions_left = 1, 2
    s, liz = pair(g, "strange", "liz")
    g.players[1].deck[:] = [c for c in g.players[1].deck if not (c.can_attack and c.usable_by("Liz Sherman"))]
    attacker_card = give(g, 1, "Fireball")
    res = g.attack(liz, s, attacker_card, give(g, 0, "The Mists of Munnopor"))
    assert res.atk_value == 0 and "atk" in res.cancelled and not res.attacker_won
    assert attacker_card in g.players[1].discard


def test_mists_new_card_resolves_its_own_effects(bprd):
    g = mk(bprd, "hellboy")
    decline_pact(g)
    g.turn, g.actions_left = 1, 2
    s, hb = pair(g, "strange", "hellboy")
    on_top(g, 1, "Posthumous Power", "Excalibur")                    # a Lobster Johnson card Hellboy cannot play is skipped
    attacker_card = give(g, 1, "Service Pistol")
    res = g.attack(hb, s, attacker_card, give(g, 0, "The Mists of Munnopor"))
    assert res.atk_card.title == "Excalibur" and res.atk_value == 6 and res.damage == 4
    assert g.players[1].deck[-1].title == "Posthumous Power"          # the revealed card it could not play went to the bottom


# ---------------------------------------------------------------- the schemes

def test_eye_of_agamotto_shuffles_the_hand_into_the_deck_draws_five_and_gains_an_action(bprd):
    g = mk(bprd, "liz-sherman")
    for t in ("Feint", "Bolts of Balthakk", "Cloak of Levitation"):
        give(g, 0, t)
    eye = give(g, 0, "Eye of Agamotto")
    deck_before = len(g.players[0].deck)
    g.actions_left = 2
    assert g.play_scheme(0, g.fighters["strange"], eye) is None
    mine = g.players[0]
    assert len(mine.hand) == 5 and len(mine.deck) == deck_before + 3 - 5 and eye in mine.discard
    assert g.actions_left == 2                                       # 2 - 1 spent + 1 gained


def test_no_really_im_a_doctor_reveals_a_card_puts_it_on_top_and_heals_its_boost_value(bprd):
    g = mk(bprd, "liz-sherman")
    s = g.fighters["strange"]
    s.hp = 6
    doc = give(g, 0, "No, Really, I'm a Doctor")
    low, high = give(g, 0, "Feint"), give(g, 0, "Bolts of Balthakk")      # boost 1 and 3
    g.controllers[0].choose_effect = lambda game, req: [high.card_id] if req.kind == "cards" else None
    g.actions_left = 2
    assert g.play_scheme(0, s, doc) is None
    assert g.players[0].deck[0] is high and high not in g.players[0].hand and low in g.players[0].hand
    assert s.hp == 9
    assert g.players[1].known.top_of_deck == [high.card_id] or g.players[1].known.top_of_deck == (high.card_id,) \
        or list(g.players[1].known.top_of_deck) == [high.card_id]       # the rival saw it


def test_no_really_the_heal_goes_to_wong_when_he_is_next_to_strange_and_the_owner_chooses_him(bprd):
    g = mk(bprd, "liz-sherman")
    s, wong = g.fighters["strange"], g.fighters["wong"]
    pair(g, "strange", "liz")
    put_adjacent(g, "wong", "strange")
    s.hp, wong.hp = 10, 2
    doc = give(g, 0, "No, Really, I'm a Doctor")
    card = give(g, 0, "Bolts of Balthakk")
    g.controllers[0].choose_effect = lambda game, req: ([card.card_id] if req.kind == "cards" else [wong.fid] if req.kind == "fighter" else None)
    g.actions_left = 2
    assert g.play_scheme(0, s, doc) is None
    assert wong.hp == 5 and s.hp == 10


# ---------------------------------------------------------------- The Winds of Watoomb

def test_winds_put_strange_where_the_rival_says_and_the_opposing_fighter_in_another_starting_space(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    starts = sorted(g.board.starts.values())
    g.controllers[1].choose_placement = lambda game, fighter, options: options[-1]      # the rival picks the last free one
    g.controllers[0].choose_placement = lambda game, fighter, options: options[0]
    order_before = [list(p.deck) for p in g.players]
    res = g.attack(s, liz, give(g, 0, "The Winds of Watoomb"), None)
    assert s.pos in starts and liz.pos in starts and s.pos != liz.pos
    assert s.pos == max(p for p in starts if p != liz.pos) or s.pos == starts[-1]
    assert [list(p.deck) for p in g.players] != order_before             # both decks were shuffled


def test_winds_do_not_place_a_defeated_opposing_fighter(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    liz.hp = 1
    g.attack(s, liz, give(g, 0, "The Winds of Watoomb"), None)
    assert not liz.alive and liz.pos is None


# ---------------------------------------------------------------- DARK PACT

def pact_fight(g, card_title="Feint", def_title=None, attacker="strange"):
    s, liz = pair(g, "strange", "liz")
    card = give(g, 0, card_title)
    return s, liz, card, g.attack(s, liz, card, give(g, 1, def_title) if def_title else None)


def test_dark_pact_accepted_costs_one_hit_point_puts_the_card_at_the_bottom_and_draws_one(bprd):
    g = mk(bprd, "liz-sherman")
    g.controllers[0].choose_effect = lambda game, req: [True] if "pact" in req.extra else None
    s, liz = pair(g, "strange", "liz")
    card = give(g, 0, "Feint")
    hand_before, deck_before = len(g.players[0].hand), len(g.players[0].deck)
    g.attack(s, liz, card, None)
    mine = g.players[0]
    assert s.hp == 13 and card in mine.deck and mine.deck[-1] is card and card not in mine.discard
    assert len(mine.hand) == hand_before - 1 + 1 and len(mine.deck) == deck_before + 1 - 1


def test_dark_pact_declined_leaves_the_card_in_the_discard_pile(bprd):
    g = mk(bprd, "liz-sherman")
    decline_pact(g)
    s, liz = pair(g, "strange", "liz")
    card = give(g, 0, "Feint")
    g.attack(s, liz, card, None)
    assert s.hp == 14 and card in g.players[0].discard


def test_dark_pact_asks_on_the_defense_too_but_only_when_strange_played_a_card(bprd):
    g = mk(bprd, "liz-sherman")
    asked = []
    g.controllers[0].choose_effect = lambda game, req: (asked.append(req.extra["pact"]) or [False]) if "pact" in req.extra else None
    g.turn, g.actions_left = 1, 2
    s, liz = pair(g, "strange", "liz")
    g.attack(liz, s, give(g, 1, "Fireball"), None)                          # Strange defends with no card: nothing to recycle
    assert asked == []
    g.attack(liz, s, give(g, 1, "Fireball", 1), give(g, 0, "Feint"))
    assert len(asked) == 1 and asked[0]["damage"] == 1 and asked[0]["fighter"] == "strange"


def test_dark_pact_is_not_asked_for_a_card_wong_played(bprd):
    g = mk(bprd, "liz-sherman")
    asked = []
    g.controllers[0].choose_effect = lambda game, req: (asked.append(1) or [False]) if "pact" in req.extra else None
    wong, liz = pair(g, "wong", "liz")
    g.attack(wong, liz, give(g, 0, "Steadfast Disciple"), None)
    assert asked == []


def test_dark_pact_follows_the_combat_even_when_the_card_is_a_boosted_bolts(bprd):
    g = mk(bprd, "liz-sherman")
    g.controllers[0].choose_effect = lambda game, req: [True]               # blind boost yes, pact yes
    s, liz = pair(g, "strange", "liz")
    card = give(g, 0, "Bolts of Balthakk")
    boosted = g.players[0].deck[0]
    g.attack(s, liz, card, None)
    assert g.players[0].deck[-1] is card and boosted in g.players[0].discard and card not in g.players[0].discard


def test_dark_pact_that_kills_strange_ends_the_game(bprd):
    g = mk(bprd, "liz-sherman")
    g.controllers[0].choose_effect = lambda game, req: [True] if "pact" in req.extra else None
    s, liz = pair(g, "strange", "liz")
    s.hp = 1
    g.attack(s, liz, give(g, 0, "Feint"), None)
    assert g.winner == 1 and not s.alive


def test_dark_pact_is_not_asked_when_the_combat_already_ended_the_game(bprd):
    g = mk(bprd, "liz-sherman")
    asked = []
    g.controllers[0].choose_effect = lambda game, req: (asked.append(1) or [True]) if "pact" in req.extra else None
    s, liz = pair(g, "strange", "liz")
    liz.hp = 1
    g.attack(s, liz, give(g, 0, "Bolts of Balthakk"), None)
    assert g.winner == 0 and asked == []


# ---------------------------------------------------------------- how the bot decides DARK PACT

def pact_request(g, hp_left=None, card_title="Bolts of Balthakk"):
    """The request DARK PACT sends the bot after a combat, with the card in the discard pile."""
    s = g.fighters["strange"]
    if hp_left is not None:
        s.hp = hp_left
    card = next(c for c in g.players[0].full_set if c.title == card_title)
    for zone in (g.players[0].hand, g.players[0].deck):
        if card in zone:
            zone.remove(card)
    g.players[0].discard.append(card)
    return ChoiceRequest("optional", 0, [True, False], 1, 1, None, "dark_pact/x:0", "do it?",
                         {"pact": {"fighter": "strange", "damage": 1, "card": card.card_id, "draws": 1}}, 0)


def far_apart(g):
    far = sorted(g.board.spaces, key=lambda s: -g.board.distance(s, min(g.board.spaces)))
    g.fighters["strange"].pos = min(g.board.spaces)
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.fid != "strange"], far):
        f.pos = s


def test_the_bot_pays_dark_pact_while_it_is_healthy_and_the_rival_is_far_and_stops_when_hit_points_run_low(bprd):
    g = mk(bprd, "liz-sherman")
    far_apart(g)
    for _ in range(3):
        give(g, 0, "Feint")
    ai = EffectAI(0)
    verdicts = {h: ai._dark_pact(g, pact_request(g, hp_left=h)) for h in range(1, 15)}
    assert all(verdicts[h] for h in range(8, 15))             # plenty of hit points and nobody around: the card and the draw are worth it
    assert not any(verdicts[h] for h in range(1, 5))          # never leaves Doctor Strange with fewer than PACT_FLOOR
    assert verdicts[6] and not verdicts[5]                    # in between, each hit point costs more


def test_the_bot_never_pays_dark_pact_when_the_hit_point_would_kill_it(bprd):
    g = mk(bprd, "liz-sherman")
    far_apart(g)
    assert EffectAI(0)._dark_pact(g, pact_request(g, hp_left=1)) is False


def test_the_bot_does_not_pay_dark_pact_when_the_hit_point_leaves_it_in_lethal_range(bprd):
    g = mk(bprd, "hellboy")
    pair(g, "strange", "hellboy")                          # Hellboy beside him with a hand of attacks, and few defenses for Strange
    g.players[1].hand[:] = [c for c in g.players[1].full_set if c.can_attack][:5]
    for title in ("The Mists of Munnopor", "Feint", "Feint", "Cloak of Levitation"):
        give(g, 0, title)
    ai = EffectAI(0)
    risk = {h: ai.medusa(0).death_risk(g, Model(g, 0), g.fighters["strange"], h) for h in range(1, 15)}
    paid = [h for h in range(1, 15) if ai._dark_pact(g, pact_request(g, hp_left=h))]
    assert paid and all(risk[h - 1] < SURVIVAL_P for h in paid)           # never into a chance of dying that high
    assert min(paid) > 9 and not any(h < min(paid) for h in paid)
    assert risk[8] > 0.05 and not ai._dark_pact(g, pact_request(g, hp_left=9))      # a point more risk than it brings


def test_a_blind_boost_that_could_push_seven_suns_over_seven_is_declined_and_a_safe_one_taken(bprd):
    g = mk(bprd, "liz-sherman")
    s, liz = pair(g, "strange", "liz")
    ai = EffectAI(0)

    def ask(value, limit):
        extra = {"blind_boost": True, "left": 1, "attacking": True, "margin": value - 4, "value": value, "limit": limit,
                 "target": "liz"}
        return ai._blind_boost(g, ChoiceRequest("optional", 0, [True, False], 1, 1, None, "during/x:0", "", extra, 0))
    assert ask(3, 7) is True and ask(6, 7) is False and ask(2, None) is True


def test_dark_pact_without_an_opinion_is_never_paid(bprd):
    from sparring.effects.choose import default_answer
    assert default_answer(pact_request(mk(bprd))) == [False]


# ---------------------------------------------------------------- saves and clones

def test_a_game_with_doctor_strange_survives_a_save_and_a_clone(bprd):
    g = mk(bprd, "liz-sherman")
    s, liz = pair(g, "strange", "liz")
    g.controllers[0].choose_effect = lambda game, req: [True] if "pact" in req.extra else None
    g.attack(s, liz, give(g, 0, "Feint"), None)
    clone = g.clone()
    assert clone.fighters["strange"].hp == 13 and clone.players[0].deck[-1].title == "Feint"
    saved = json.loads(json.dumps(persist.game_to_dict(g)))
    loaded = Game.new(bprd, 0, controllers={}, heroes=("doctor-strange", "liz-sherman"))
    persist.apply_game(loaded, saved)
    assert loaded.fighters["strange"].hp == 13 and loaded.players[0].deck[-1].title == "Feint"
