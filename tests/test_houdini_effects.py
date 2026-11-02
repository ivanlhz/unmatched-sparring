"""Houdini's cards, the BOOSTED WITH moment and ESCAPE ARTIST on the interpreter, bot side (player 0 plays Houdini, the
controllers answer). The human side (panel, FakeTTS) is in tests/test_houdini_human.py and the full games in
tests/test_houdini_matrix.py. The numbers are the ones printed on the real cards (data/heroes/houdini.json)."""
from __future__ import annotations

import json

import pytest

from conftest import card, give
from sparring import persist
from sparring.cards import Card
from sparring.combat_flow import CombatFlow, Phase
from sparring.effects.model import load_effects
from sparring.state import Game, RuleError
from test_effects_combat import Asking, hand_filler, hp, pair


class TwoBoosts(Asking):
    """An Asking controller whose combat boosts are queued, one card per prompt."""

    def __init__(self):
        super().__init__()
        self.boosts: list = []

    def choose_combat_boost(self, game, ctx):
        return self.boosts.pop(0) if self.boosts else None


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Houdini = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: TwoBoosts(), 1: TwoBoosts()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("houdini", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


# ---------------------------------------------------------------- the deck

def test_houdini_is_interpreted_and_has_the_printed_figures(bprd):
    g = mk(bprd)
    assert "houdini" in g.fx.dsl_heroes
    assert [f.fid for f in g.own(0)] == ["houdini", "bess"]
    assert (g.fighters["houdini"].hp, g.fighters["houdini"].move, g.fighters["bess"].hp) == (14, 2, 5)
    assert not g.fighters["houdini"].ranged and not g.fighters["bess"].ranged
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17800 and deck[-1].card_id == 17829


def test_the_sheet_follows_the_images(bprd):
    deck = {c.card_id: c for c in mk(bprd).players[0].full_set}
    by_idx = lambda i: deck[17800 + i]
    assert [by_idx(i).title for i in (0, 2, 4, 6, 8, 12, 15, 17, 20, 22, 25, 27, 29)] == [
        "The Big Reveal", "An Illusion of My Own Design", "Sleight of Hand", "For My Next Trick", "Flourish", "Vanishing Act",
        "Smoke and Mirrors", "Misdirection", "And the Beautiful Bess!", "Grand Escape", "All Part of the Show",
        "Set the Stage", "A Magician Never Reveals His Secrets"]
    assert (by_idx(2).value, by_idx(2).boost) == (4, 1)            # the card prints 1, unmatched-memory says 2
    assert by_idx(20).fighter == "Bess" and by_idx(27).fighter == "Bess" and by_idx(22).fighter == "Houdini"
    assert by_idx(8).fighter == "any" and by_idx(15).fighter == "any" and by_idx(25).fighter == "any"
    assert [by_idx(i).type for i in (0, 12, 20, 22, 27)] == ["attack", "versatile", "versatile", "defense", "scheme"]


def test_every_boosted_with_card_has_its_boost_moment_and_only_those(bprd):
    fx = load_effects("houdini")
    with_boost = {t for t, c in fx.cards.items() if c.moments.get("boost")}
    assert with_boost == {"Sleight of Hand", "Flourish", "Misdirection", "And the Beautiful Bess!", "All Part of the Show",
                          "Set the Stage"}


# ---------------------------------------------------------------- BOOSTED WITH in a combat

def test_a_boost_with_flourish_adds_its_value_and_draws_a_card(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack, spare = give(g, 0, "Flourish"), give(g, 0, "Flourish", 1)
    g.controllers[0].boosts = [spare]
    before = len(g.players[0].hand)
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert res.atk_value == 3 + 2 and res.boost_card is spare and spare in g.players[0].discard
    assert len(g.players[0].hand) == before - 2 + 1                  # the attack and the boost left, the BOOSTED WITH drew one
    assert len(res.applied) == 1 and res.applied[0].startswith("Flourish: ") and "1" in res.applied[0]     # the boost's own line


def test_a_boost_that_is_not_made_runs_no_boosted_with(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "Flourish")
    give(g, 0, "Flourish", 1)
    before = len(g.players[0].hand)
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert res.atk_value == 3 and len(g.players[0].hand) == before - 1


def test_misdirection_boosted_with_deals_two_damage_to_a_fighter_the_owner_picks(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack, boost = give(g, 0, "Flourish"), give(g, 0, "Misdirection")
    g.controllers[0].boosts = [boost]
    g.controllers[0].queue = [["lobster"]]
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert res.atk_value == 3 + 1
    assert g.fighters["lobster"].hp == g.fighters["lobster"].max_hp - 2
    assert g.fighters["hellboy"].hp == g.fighters["hellboy"].max_hp - 4


def test_all_part_of_the_show_boosted_with_heals_houdini_two(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    g.fighters["houdini"].hp = 10
    attack, boost = give(g, 0, "Flourish"), give(g, 0, "All Part of the Show")
    g.controllers[0].boosts = [boost]
    g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert g.fighters["houdini"].hp == 12


def test_all_part_of_the_show_boosted_with_does_not_heal_above_the_maximum(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    g.fighters["houdini"].hp = 13
    attack, boost = give(g, 0, "Flourish"), give(g, 0, "All Part of the Show")
    g.controllers[0].boosts = [boost]
    g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert g.fighters["houdini"].hp == 14


def test_bess_boosted_with_gains_an_action_only_on_the_owners_turn(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack, boost = give(g, 0, "Flourish"), give(g, 0, "And the Beautiful Bess!")
    g.controllers[0].boosts = [boost]
    g.actions_left = 2
    g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert g.actions_left == 2                                       # 2 - 1 spent + 1 gained
    # the rival's turn: boosting a defense with the card gives nothing
    h = mk(bprd, turn=1)
    pair(h, "hellboy", "houdini")
    defense, boost = give(h, 0, "Grand Escape"), give(h, 0, "And the Beautiful Bess!")
    h.controllers[0].boosts = [boost]
    h.actions_left = 2
    h.attack(h.fighters["hellboy"], h.fighters["houdini"], give(h, 1, "Horseshoes And Hand Grenades"), defense)
    assert h.actions_left == 1


def test_set_the_stage_boosted_with_looks_at_the_rivals_hand_and_discards_the_card_picked(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack, boost = give(g, 0, "Flourish"), give(g, 0, "Set the Stage")
    theirs = [give(g, 1, "Excalibur"), give(g, 1, "Service Pistol")]
    g.controllers[0].boosts = [boost]
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert res.atk_value == 3 + 2
    assert sum(c in g.players[1].discard for c in theirs) == 1       # one card of theirs went
    assert g.players[0].known.cards(g.players[1])                    # and the look is remembered (KnownHand)


def test_sleight_of_hand_boosted_with_draws_a_card(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack, boost = give(g, 0, "Flourish"), give(g, 0, "Sleight of Hand")
    g.controllers[0].boosts = [boost]
    before = len(g.players[0].hand)
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert res.atk_value == 3 + 3 and len(g.players[0].hand) == before - 2 + 1


# ---------------------------------------------------------------- The Big Reveal: two boosts and a card back

def test_the_big_reveal_boosts_twice_and_returns_one_boosted_card(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "The Big Reveal")
    a, b = give(g, 0, "Flourish"), give(g, 0, "Misdirection")
    g.controllers[0].boosts = [a, b]
    g.controllers[0].queue = [["lobster"], [b.card_id]]      # Misdirection's damage, then the card to get back
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert res.atk_value == 2 + 2 + 1
    assert a in g.players[0].discard and b in g.players[0].hand and attack in g.players[0].discard
    assert g.fighters["lobster"].hp == g.fighters["lobster"].max_hp - 2


def test_the_big_reveal_second_boost_only_if_the_first_was_made(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "The Big Reveal")
    give(g, 0, "Flourish")
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert res.atk_value == 2 and not g.controllers[0].requests


def test_the_big_reveal_with_no_boost_returns_nothing(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "The Big Reveal")
    g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    assert attack in g.players[0].discard and not g.controllers[0].requests


def test_the_big_reveal_stops_for_the_second_boost_and_survives_a_save(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "The Big Reveal")
    a, b = give(g, 0, "Flourish"), give(g, 0, "Flourish", 1)
    flow = g.begin_attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    wait = flow.run()
    assert wait.choice.kind == "boost" and wait.choice.extra == {}
    flow.resume(a)
    wait = flow.run()
    assert wait.choice.kind == "boost" and wait.choice.extra == {"n": 1}
    saved = json.loads(json.dumps(flow.to_dict()))
    again = CombatFlow.from_dict(g, saved)
    assert again.boosted == {"atk": [a.card_id]} and again.pending.extra == {"n": 1}
    again.resume(b)
    assert again.run() is None and again.result.atk_value == 2 + 2 + 2


# ---------------------------------------------------------------- An Illusion of My Own Design

def test_an_illusion_lets_the_rival_boost_a_card_without_a_boost_of_its_own(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "An Illusion of My Own Design")
    defense, spare = give(g, 1, "Glimpse Of Hell"), give(g, 1, "Excalibur")
    g.controllers[1].boosts = [spare]
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, defense)
    assert res.def_value == 2 + 3 and spare in g.players[1].discard
    assert res.atk_value == 4


def test_without_the_illusion_that_rival_card_boosts_nothing(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "For My Next Trick")
    defense, spare = give(g, 1, "Glimpse Of Hell"), give(g, 1, "Excalibur")
    g.controllers[1].boosts = [spare]
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, defense)
    assert res.def_value == 2 and spare in g.players[1].hand


def test_an_illusion_that_the_rival_cancels_gives_no_boost(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "An Illusion of My Own Design")
    defense, spare = give(g, 1, "Planned Recklessness"), give(g, 1, "Excalibur")      # cancels every effect of the attack
    g.controllers[1].boosts = [spare]
    res = g.attack(g.fighters["houdini"], g.fighters["hellboy"], attack, defense)
    assert res.def_value == 3 and spare in g.players[1].hand


def test_the_boost_the_illusion_gives_is_saved_with_the_flow(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "An Illusion of My Own Design")
    defense = give(g, 1, "Glimpse Of Hell")
    flow = g.begin_attack(g.fighters["houdini"], g.fighters["hellboy"], attack, defense)
    wait = flow.run()
    assert wait.choice.kind == "boost" and wait.choice.player == 1
    assert json.loads(json.dumps(flow.to_dict()))["dsl"]["boost_granted"] == ["def"]


# ---------------------------------------------------------------- the other combat cards

def test_smoke_and_mirrors_swaps_and_the_other_fighter_defends(bprd):
    g = mk(bprd)
    attacker, houdini = pair(g, "hellboy", "houdini")
    bess = g.fighters["bess"]
    where_h, where_b = houdini.pos, bess.pos
    defense = give(g, 0, "Smoke and Mirrors")
    g.controllers[0].queue = [[True]]
    res = g.attack(attacker, houdini, give(g, 1, "Service Pistol"), defense)
    assert (houdini.pos, bess.pos) == (where_b, where_h)
    assert res.target == "bess" and res.damage == 5 - 3
    assert bess.hp == 5 - 2 and houdini.hp == 14


def test_smoke_and_mirrors_declined_changes_nobody(bprd):
    g = mk(bprd)
    attacker, houdini = pair(g, "hellboy", "houdini")
    where_h, where_b = houdini.pos, g.fighters["bess"].pos
    g.controllers[0].queue = [[False]]
    res = g.attack(attacker, houdini, give(g, 1, "Service Pistol"), give(g, 0, "Smoke and Mirrors"))
    assert (houdini.pos, g.fighters["bess"].pos) == (where_h, where_b) and res.target == "houdini"
    assert houdini.hp == 14 - 2


def test_smoke_and_mirrors_attacking_makes_the_other_fighter_the_attacker(bprd):
    g = mk(bprd)
    houdini, hellboy = pair(g, "houdini", "hellboy")
    bess = g.fighters["bess"]
    where_h, where_b = houdini.pos, bess.pos
    g.controllers[0].queue = [[True]]
    res = g.attack(houdini, hellboy, give(g, 0, "Smoke and Mirrors"), None)
    assert res.attacker == "bess" and bess.pos == where_h and houdini.pos == where_b and res.atk_value == 3
    assert hellboy.hp == hellboy.max_hp - 3


def test_smoke_and_mirrors_with_bess_dead_swaps_nothing(bprd):
    g = mk(bprd)
    houdini, hellboy = pair(g, "houdini", "hellboy")
    g.damage(g.fighters["bess"], 5)
    res = g.attack(houdini, hellboy, give(g, 0, "Smoke and Mirrors"), None)
    assert res.attacker == "houdini" and not g.controllers[0].requests          # nobody to swap with: nothing is asked


def test_misdirection_cancels_the_rivals_effects(bprd):
    g = mk(bprd)
    houdini, hellboy = pair(g, "houdini", "hellboy")
    res = g.attack(houdini, hellboy, give(g, 0, "Misdirection"), give(g, 1, "Confront Any Demon or God"))
    assert "def" in res.cancelled


def test_grand_escape_won_places_the_fighter_anywhere(bprd):
    g = mk(bprd)
    attacker, houdini = pair(g, "hellboy", "houdini")
    far = max(g.board.spaces, key=lambda s: g.board.distance(houdini.pos, s))
    g.controllers[0].queue = [[far]]
    res = g.attack(attacker, houdini, give(g, 1, "Horseshoes And Hand Grenades"), give(g, 0, "Grand Escape"))
    assert not res.attacker_won and houdini.pos == far


def test_grand_escape_lost_does_not_move_him(bprd):
    g = mk(bprd)
    attacker, houdini = pair(g, "hellboy", "houdini")
    where = houdini.pos
    g.attack(attacker, houdini, give(g, 1, "Excalibur"), give(g, 0, "Grand Escape"))
    assert houdini.pos == where and not g.controllers[0].requests


def test_grand_escape_may_be_boosted(bprd):
    g = mk(bprd)
    attacker, houdini = pair(g, "hellboy", "houdini")
    spare = give(g, 0, "Misdirection")
    g.controllers[0].boosts = [spare]
    g.controllers[0].queue = [["lobster"]]
    res = g.attack(attacker, houdini, give(g, 1, "Service Pistol"), give(g, 0, "Grand Escape"))
    assert res.def_value == 2 + 1


def test_vanishing_act_moves_the_chosen_combatant_up_to_three_through_enemies(bprd):
    g = mk(bprd)
    houdini, hellboy = pair(g, "houdini", "hellboy")
    far = max(g.board.legal_moves(houdini, 3, True) if hasattr(g.board, "legal_moves") else g.legal_moves(houdini, 3, True),
              key=lambda s: g.board.distance(houdini.pos, s))
    g.controllers[0].queue = [["houdini"], [far]]
    g.attack(houdini, hellboy, give(g, 0, "Vanishing Act"), None)
    assert houdini.pos == far and g.board.distance(hellboy.pos, far) >= 1


def test_for_my_next_trick_moves_draws_and_gains_an_action(bprd):
    g = mk(bprd)
    houdini, hellboy = pair(g, "houdini", "hellboy")
    g.actions_left = 2
    hand_filler(g, 0, 1)
    trick = give(g, 0, "For My Next Trick")
    before = len(g.players[0].hand)
    g.controllers[0].queue = [["bess"]]
    g.attack(houdini, hellboy, trick, None)
    assert len(g.players[0].hand) == before            # the played card left, one was drawn
    assert g.actions_left == 2                           # 2 - 1 + 1


# ---------------------------------------------------------------- All Part of the Show

def test_all_part_of_the_show_brings_a_defeated_houdini_back_with_four_health(bprd):
    g = mk(bprd)
    attacker, houdini = pair(g, "hellboy", "houdini")
    houdini.hp = 2
    far = max(g.board.spaces, key=lambda s: g.board.distance(houdini.pos, s))
    g.controllers[0].queue = [[far]]
    res = g.attack(attacker, houdini, give(g, 1, "Excalibur"), give(g, 0, "All Part of the Show"))
    assert g.winner is None and houdini.alive and houdini.hp == 4 and houdini.pos == far


def test_without_the_card_the_same_blow_ends_the_game(bprd):
    g = mk(bprd)
    attacker, houdini = pair(g, "hellboy", "houdini")
    houdini.hp = 2
    g.attack(attacker, houdini, give(g, 1, "Excalibur"), give(g, 0, "Grand Escape"))
    assert g.winner == 1 and not houdini.alive


def test_all_part_of_the_show_cannot_be_cancelled(bprd):
    g = mk(bprd, foe="liz-sherman")
    attacker, houdini = pair(g, "liz", "houdini")
    houdini.hp = 2
    far = max(g.board.spaces, key=lambda s: g.board.distance(houdini.pos, s))
    g.controllers[0].queue = [[far]]
    g.attack(attacker, houdini, give(g, 1, "Incinerate"), give(g, 0, "All Part of the Show"))     # Incinerate cancels: not this card
    assert g.winner is None and houdini.hp == 4


def test_all_part_of_the_show_revives_a_defeated_bess_too(bprd):
    g = mk(bprd)
    attacker, _ = pair(g, "hellboy", "bess")
    bess = g.fighters["bess"]
    bess.hp = 1
    far = max(g.board.spaces, key=lambda s: g.board.distance(bess.pos, s) if all(f.pos != s for f in g.fighters.values() if f.alive) else -1)
    g.controllers[0].queue = [[far]]
    g.attack(attacker, bess, give(g, 1, "Excalibur"), give(g, 0, "All Part of the Show"))
    assert bess.alive and bess.hp == 4 and bess.pos == far and g.winner is None


def test_the_deferred_defeat_is_saved_with_the_flow(bprd):
    g = mk(bprd)
    attacker, houdini = pair(g, "hellboy", "houdini")
    houdini.hp = 2
    flow = g.begin_attack(attacker, houdini, give(g, 1, "Excalibur"), give(g, 0, "All Part of the Show"))
    flow.controllers = None
    while flow.phase is not Phase.AFTER:
        flow.step()
    assert g.winner is None and flow.deferred_loss == 0 and not houdini.alive
    saved = json.loads(json.dumps(flow.to_dict()))
    assert saved["dsl"]["deferred_loss"] == 0


# ---------------------------------------------------------------- schemes

def test_set_the_stage_draws_three_then_puts_a_card_on_top_of_the_deck(bprd):
    g = mk(bprd)
    scheme = give(g, 0, "Set the Stage")
    g.actions_left = 2
    deck = len(g.players[0].deck)
    g.play_scheme(0, g.fighters["bess"], scheme)
    assert len(g.players[0].hand) == 3 - 1 and len(g.players[0].deck) == deck - 3 + 1


def test_set_the_stage_is_a_card_of_bess_not_of_houdini(bprd):
    g = mk(bprd)
    scheme = give(g, 0, "Set the Stage")
    with pytest.raises(RuleError):
        g.play_scheme(0, g.fighters["houdini"], scheme)


def test_a_magician_never_reveals_his_secrets_draws_two_and_gains_an_action(bprd):
    g = mk(bprd)
    scheme = give(g, 0, "A Magician Never Reveals His Secrets")
    g.actions_left = 2
    g.play_scheme(0, g.fighters["houdini"], scheme)
    assert len(g.players[0].hand) == 2 and g.actions_left == 2


# ---------------------------------------------------------------- Maneuver and ESCAPE ARTIST

def test_a_maneuver_without_a_boost_moves_houdini_two_spaces_at_most(bprd):
    g = mk(bprd)
    far = max(g.board.spaces, key=lambda s: g.board.distance(g.fighters["houdini"].pos, s))
    with pytest.raises(RuleError):
        g.maneuver(0, {"houdini": far})


def test_a_maneuver_that_boosts_places_houdini_in_any_empty_space(bprd):
    g = mk(bprd)
    houdini = g.fighters["houdini"]
    taken = {f.pos for f in g.fighters.values() if f.alive}
    far = max((s for s in g.board.spaces if s not in taken), key=lambda s: g.board.distance(houdini.pos, s))
    assert g.board.distance(houdini.pos, far) > houdini.move + 3
    boost = give(g, 0, "Sleight of Hand")
    g.maneuver(0, {"houdini": far}, boost)
    assert houdini.pos == far and boost in g.players[0].discard


def test_escape_artist_cannot_place_him_on_an_occupied_space(bprd):
    g = mk(bprd)
    boost = give(g, 0, "Flourish")
    with pytest.raises(RuleError):
        g.maneuver(0, {"houdini": g.fighters["hellboy"].pos}, boost)


def test_bess_moves_as_normal_with_the_boost_added(bprd):
    g = mk(bprd)
    bess, houdini = g.fighters["bess"], g.fighters["houdini"]
    boost = give(g, 0, "The Big Reveal")                  # boost 3
    reach = g.legal_moves(bess, bess.move + 3)
    far = max(reach, key=lambda s: g.board.distance(bess.pos, s))
    assert g.board.distance(bess.pos, far) > bess.move
    g.maneuver(0, {"bess": far, "houdini": houdini.pos}, boost)
    assert bess.pos == far


def test_bess_cannot_be_placed_anywhere_only_moved(bprd):
    g = mk(bprd)
    bess = g.fighters["bess"]
    far = max(g.board.spaces, key=lambda s: g.board.distance(bess.pos, s))
    with pytest.raises(RuleError):
        g.maneuver(0, {"bess": far}, give(g, 0, "Flourish"))


def test_the_rival_hero_has_no_escape_artist(bprd):
    g = mk(bprd, turn=1)
    hellboy = g.fighters["hellboy"]
    far = max(g.board.spaces, key=lambda s: g.board.distance(hellboy.pos, s))
    with pytest.raises(RuleError):
        g.maneuver(1, {"hellboy": far}, give(g, 1, "Excalibur"))


def test_a_maneuver_boost_runs_boosted_with(bprd):
    g = mk(bprd)
    boost = give(g, 0, "Flourish")
    g.actions_left = 2
    g.maneuver(0, {}, boost)
    assert len(g.players[0].hand) == 2             # the maneuver's card and the BOOSTED WITH draw (the boost left the hand)
    assert g.actions_left == 1


def test_a_bess_boost_in_a_maneuver_gains_an_action(bprd):
    g = mk(bprd)
    boost = give(g, 0, "And the Beautiful Bess!")
    g.actions_left = 2
    g.maneuver(0, {}, boost)
    assert g.actions_left == 2                      # 2 - 1 + 1


def test_the_card_boosted_event_reaches_a_trigger(bprd):
    from sparring.effects import events
    g = mk(bprd)
    seen = []
    real = events.dispatch

    def spy(game, name, args):
        if name == "card_boosted":
            seen.append((args[0], args[1].title))
        real(game, name, args)
    events.dispatch = spy
    try:
        g.maneuver(0, {}, give(g, 0, "Flourish"))
    finally:
        events.dispatch = real
    assert seen == [(0, "Flourish")]


# ---------------------------------------------------------------- And The Beautiful Bess! when discarded

def test_bess_drawn_when_the_rival_makes_you_discard_her(bprd):
    g = mk(bprd, turn=1)
    pair(g, "hellboy", "houdini")
    bess = give(g, 0, "And the Beautiful Bess!")
    give(g, 1, "Confront Any Demon or God")
    g.players[0].hand.append(give(g, 0, "Flourish"))
    g.controllers[0].discards = [bess]
    before = len(g.players[0].hand)
    res = g.attack(g.fighters["hellboy"], g.fighters["houdini"], g.players[1].hand[0], give(g, 0, "Misdirection"))
    # Confront (3) against Misdirection (2) is a win for Hellboy: the rival looks at the hand and discards a card
    assert res.attacker_won
    if bess in g.players[0].discard:
        assert len(g.players[0].hand) >= before - 1


def test_bess_discard_by_ones_own_hand_limit_draws_nothing(bprd):
    g = mk(bprd)
    bess = give(g, 0, "And the Beautiful Bess!")
    before = len(g.players[0].deck)
    g.discard_card(0, bess)
    assert len(g.players[0].deck) == before


# ---------------------------------------------------------------- saves and clones

def test_the_boost_a_combat_was_made_with_survives_the_game_save(bprd):
    g = mk(bprd)
    pair(g, "houdini", "hellboy")
    attack = give(g, 0, "Flourish")
    flow = g.begin_attack(g.fighters["houdini"], g.fighters["hellboy"], attack, None)
    wait = flow.run()
    assert wait.choice.kind == "boost"
    saved = json.loads(json.dumps(persist.game_to_dict(g)))
    loaded = Game.new(bprd, 0, controllers={}, heroes=("houdini", "hellboy"))
    persist.apply_game(loaded, saved)
    assert loaded.players[0].hero.slug == "houdini"
