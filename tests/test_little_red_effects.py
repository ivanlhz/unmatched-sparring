"""Little Red on the engine, bot side (player 0 plays her, the controllers answer): THE BASKET (the symbol of the top card of her discard pile, the
starting Basket and a star card wild = one symbol her player chooses, Ivan 2026-11-22 LR1), the ORDER of the discard pile that makes it, every card of
the deck with the numbers and symbols printed on it, and the Huntsman's cards using the same basket. The human side (panel, FakeTTS) is in
tests/test_little_red_human.py and the full games in tests/test_little_red_matrix.py.

The rival is Leonardo: Katana (attack 6) and Heroes in a half shell (defense 5) have no effect text, so what happens is hers."""
from __future__ import annotations

import json

import pytest

from conftest import give
from sparring.effects.plugins_little_red import WILD, basket, top_card
from sparring.persist import apply_game, game_to_dict
from sparring.state import Game
from test_effects_combat import Asking, pair

SLUG = "little-red-riding-hood"
FOE = "leonardo"
OPTION = {"wolf": 0, "rose": 1, "axe": 2}


def mk(bprd, foe=FOE, seed=3, turn=0):
    """Little Red = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands, an empty discard pile (only the Basket lies there)."""
    ctl = {0: Asking(), 1: Asking()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=(SLUG, foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    for c in ctl.values():
        c.requests.clear()
    return g


def pile(g, *titles, player=0):
    """The discard pile of `player` is exactly these cards, the last one on top (a title twice takes the next copy)."""
    st = g.players[player]
    st.discard.clear()
    used = {}
    for title in titles:
        nth = used.get(title, 0)
        used[title] = nth + 1
        c = [x for x in st.full_set if x.title == title][nth]
        for zone in (st.deck, st.hand):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)


def asked(g, player, kind):
    return [r for r in g.controllers[player].requests if r.kind == kind]


def wild_asked(g):
    return [r for r in asked(g, 0, "effect") if r.extra.get("tag") == "basket"]


def says(g, *symbols):
    """The answers the bot's controller gives to the question about a wild basket."""
    g.controllers[0].queue = [[OPTION[s]] for s in symbols]


def katana(g):
    return give(g, 1, "Katana")


def wall(g):
    return give(g, 1, "Heroes in a half shell")


def red_attacks(g, title, foe_card=None, attacker="red"):
    red, foe = pair(g, attacker, FOE)
    g.attack(red, foe, give(g, 0, title), foe_card)
    return red, foe


def foe_attacks(g, title, foe_card=None):
    foe, red = pair(g, FOE, "red")
    g.attack(foe, red, give(g, 1, "Katana") if foe_card is None else foe_card, give(g, 0, title))
    return red, foe


# ---------------------------------------------------------------- the hero

def test_little_red_is_a_melee_hero_with_a_ranged_huntsman_and_both_use_the_interpreter(bprd):
    g = mk(bprd)
    red, hunter = g.fighters["red"], g.fighters["huntsman"]
    assert (red.hp, red.move, red.ranged, red.name) == (14, 2, False, "Little Red")
    assert (hunter.hp, hunter.move, hunter.ranged, hunter.name) == (9, 2, True, "Huntsman")
    assert SLUG in g.fx.dsl_heroes and g.winner is None
    assert len(g.players[0].full_set) == 30


def test_the_starting_basket_is_not_a_card(bprd):
    g = Game.new(bprd, 3, controllers={0: Asking(), 1: Asking()}, heroes=(SLUG, FOE), bot_player=0)
    st = g.players[0]
    assert st.discard == [] and top_card(g, 0) is None and basket(g, 0) == WILD
    assert len(st.deck) + len(st.hand) == 30          # the Basket is in no pile of cards: it is never drawn, counted or returned


# ---------------------------------------------------------------- the pile is ordered and its top is the basket

def test_the_basket_is_wild_with_nothing_in_the_pile_and_the_symbol_of_the_top_card_otherwise(bprd):
    g = mk(bprd)
    assert basket(g, 0) == WILD
    pile(g, "The Wolf's Skin", "Once Upon a Time")
    assert basket(g, 0) == "rose" and top_card(g, 0).title == "Once Upon a Time"
    pile(g, "Once Upon a Time", "The Wolf's Skin")
    assert basket(g, 0) == "axe"
    pile(g, "What's That In My Basket?")
    assert basket(g, 0) == WILD


def test_a_card_discarded_becomes_the_top_and_a_card_taken_from_the_middle_leaves_the_rest_in_order(bprd):
    g = mk(bprd)
    st = g.players[0]
    cards = [give(g, 0, t) for t in ("The Wolf's Skin", "Once Upon a Time", "Never Leave the Path")]
    for c in cards:
        g.discard_card(0, c)
    assert [c.title for c in st.discard] == ["The Wolf's Skin", "Once Upon a Time", "Never Leave the Path"] and basket(g, 0) == "wolf"
    st.discard.remove(cards[1])
    assert [c.title for c in st.discard] == ["The Wolf's Skin", "Never Leave the Path"] and basket(g, 0) == "wolf"
    st.discard.remove(cards[2])
    assert basket(g, 0) == "axe"


def test_the_order_survives_a_clone_and_a_save(bprd):
    g = mk(bprd)
    pile(g, "The Wolf's Skin", "Once Upon a Time", "Never Leave the Path")
    ids = [c.card_id for c in g.players[0].discard]
    assert [c.card_id for c in g.clone().players[0].discard] == ids
    fresh = mk(bprd)
    apply_game(fresh, json.loads(json.dumps(game_to_dict(g))))
    assert [c.card_id for c in fresh.players[0].discard] == ids and basket(fresh, 0) == "wolf"


def test_the_combat_card_reaches_the_pile_last_on_top_of_what_was_there(bprd):
    g = mk(bprd)
    pile(g, "The Wolf's Skin")
    red_attacks(g, "Once Upon a Time")
    assert [c.title for c in g.players[0].discard] == ["The Wolf's Skin", "Once Upon a Time"]


# ---------------------------------------------------------------- a line with a symbol resolves only if the basket shows it

@pytest.mark.parametrize("under,draws", [("Never Leave the Path", 2), ("The Wolf's Skin", 0), ("Once Upon a Time", 0)])
def test_the_wolfs_skin_draws_two_only_with_a_wolf_on_top(bprd, under, draws):
    g = mk(bprd, turn=1)
    pile(g, under)
    hand = len(g.players[0].hand)
    foe_attacks(g, "The Wolf's Skin")
    assert len(g.players[0].hand) == hand + draws and not wild_asked(g)


@pytest.mark.parametrize("under,hits", [("The Wolf's Skin", True), ("Never Leave the Path", False), ("Once Upon a Time", False)])
def test_once_upon_a_time_deals_three_to_the_opposing_fighter_only_with_an_axe_on_top(bprd, under, hits):
    g = mk(bprd)
    pile(g, under)
    red, foe = pair(g, "red", FOE)
    before = foe.hp
    g.attack(red, foe, give(g, 0, "Once Upon a Time"), wall(g))           # 2 against 5: no combat damage, only the effect
    assert before - foe.hp == (3 if hits else 0) and not wild_asked(g)


def test_the_terrible_big_mouth_hits_back_with_the_printed_value_of_their_card_when_the_basket_is_a_wolf(bprd):
    g = mk(bprd, turn=1)
    pile(g, "Never Leave the Path")
    foe_hp = g.fighters[FOE].hp
    red, foe = foe_attacks(g, "What a Terrible Big Mouth You Have")
    assert foe_hp - foe.hp == 6 and red.hp == 14 - 4              # Katana's printed 6 as effect damage; 6 against 2 hurts her for 4


def test_the_terrible_big_mouth_does_nothing_with_another_symbol(bprd):
    g = mk(bprd, turn=1)
    pile(g, "Once Upon a Time")
    foe_hp = g.fighters[FOE].hp
    red, foe = foe_attacks(g, "What a Terrible Big Mouth You Have")
    assert foe.hp == foe_hp and red.hp == 14 - 4


# ---------------------------------------------------------------- the basket is read when the line resolves

def test_a_card_discarded_in_the_middle_of_the_combat_changes_the_basket_for_the_lines_that_follow(bprd):
    """Chupacabra's Ambush makes Little Red discard a random card of her hand in the DURING; it lands on her pile, so the AFTER line of
    The Wolf's Skin (a wolf) reads the rose that is now on top and draws nothing. Without the discard the wolf under it draws two."""
    results = []
    for in_hand in (False, True):
        g = mk(bprd, foe="chupacabra", turn=1)
        pile(g, "Never Leave the Path")                              # a wolf
        if in_hand:
            give(g, 0, "Once Upon a Time")                           # the only card Ambush can take: a rose
        chupa, red = pair(g, "chupacabra", "red")
        hand = len(g.players[0].hand)
        g.attack(chupa, red, give(g, 1, "Ambush"), give(g, 0, "The Wolf's Skin"))
        results.append((len(g.players[0].hand) - hand, basket(g, 0)))
    assert results[0][0] == 2                                          # nothing was discarded: the wolf still draws two
    assert results[1][0] == -1 and results[1][1] == "axe"              # the rose was discarded, then the played card (an axe) went on top; no draw


# ---------------------------------------------------------------- the wild basket: one symbol, chosen by the player

@pytest.mark.parametrize("chosen,draws", [("wolf", 2), ("rose", 0), ("axe", 0)])
def test_with_only_the_basket_in_the_pile_the_player_chooses_which_symbol_it_counts_as(bprd, chosen, draws):
    g = mk(bprd, turn=1)
    says(g, chosen)
    hand = len(g.players[0].hand)
    foe_attacks(g, "The Wolf's Skin")
    assert len(wild_asked(g)) == 1 and wild_asked(g)[0].options == [0, 1, 2]
    assert len(g.players[0].hand) == hand + draws


def test_a_star_card_on_top_is_wild_too(bprd):
    g = mk(bprd, turn=1)
    pile(g, "What's That In My Basket?")
    says(g, "wolf")
    hand = len(g.players[0].hand)
    foe_attacks(g, "The Wolf's Skin")
    assert len(wild_asked(g)) == 1 and len(g.players[0].hand) == hand + 2


def test_the_wild_basket_is_one_symbol_for_the_whole_card_so_never_leave_the_path_asks_once(bprd):
    g = mk(bprd)
    says(g, "rose", "wolf")                                       # the second answer must never be used
    g.actions_left = 2
    hand = len(g.players[0].hand)
    g.play_scheme(0, g.fighters["red"], give(g, 0, "Never Leave the Path"))
    assert len(wild_asked(g)) == 1
    assert len(g.players[0].hand) == hand + 3                     # the three cards of the rose line; no placing, no damage, no action
    assert g.actions_left == 1


def test_a_wild_basket_chosen_as_a_wolf_places_her_and_gives_an_action_back(bprd):
    g = mk(bprd)
    target = max(s for s in g.board.spaces if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[OPTION["wolf"]], [target]]
    g.actions_left = 2
    g.play_scheme(0, g.fighters["red"], give(g, 0, "Never Leave the Path"))
    assert g.fighters["red"].pos == target and g.actions_left == 2


def test_a_wild_basket_chosen_as_an_axe_hits_every_opposing_fighter_in_her_zone_for_two(bprd):
    g = mk(bprd)
    says(g, "axe")
    red, foe = pair(g, "red", FOE)
    before = foe.hp
    g.play_scheme(0, red, give(g, 0, "Never Leave the Path"))
    assert before - foe.hp == 2


def test_the_choice_is_asked_again_for_the_next_card_when_the_basket_is_wild_again(bprd):
    g = mk(bprd, turn=1)
    says(g, "wolf", "wolf")
    foe_attacks(g, "The Wolf's Skin")
    assert len(wild_asked(g)) == 1
    pile(g)                                                       # the pile is empty again: only the Basket
    g.turn, g.actions_left = 1, 1
    foe, red = g.fighters[FOE], g.fighters["red"]
    g.attack(foe, red, katana(g), give(g, 0, "The Wolf's Skin", 1))
    assert len(wild_asked(g)) == 2


# ---------------------------------------------------------------- What Large Hands You Have: the card or the top card comes back

def hands_attack(g):
    red, foe = pair(g, "red", FOE)
    card = give(g, 0, "What Large Hands You Have")
    g.attack(red, foe, card, wall(g))
    return card


def test_large_hands_with_a_non_rose_basket_may_return_itself_to_the_hand(bprd):
    g = mk(bprd)
    pile(g, "Never Leave the Path")                            # a wolf: the line without a symbol is the only one
    g.controllers[0].queue = [[True]]
    card = hands_attack(g)
    assert card in g.players[0].hand and card not in g.players[0].discard


def test_large_hands_returning_itself_is_optional(bprd):
    g = mk(bprd)
    pile(g, "Never Leave the Path")
    g.controllers[0].queue = [[False]]
    card = hands_attack(g)
    assert card not in g.players[0].hand and g.players[0].discard[-1] == card


def test_with_a_rose_on_top_the_top_card_comes_back_instead_of_this_card(bprd):
    g = mk(bprd)
    pile(g, "The Wolf's Skin", "Once Upon a Time")             # a rose on top
    g.controllers[0].queue = [[True]]
    card = hands_attack(g)
    assert [c.title for c in g.players[0].hand] == ["Once Upon a Time"]
    assert [c.title for c in g.players[0].discard] == ["The Wolf's Skin", "What Large Hands You Have"]      # the rose line REPLACED the return of this card
    assert card in g.players[0].discard


def test_with_a_rose_on_top_bringing_the_card_back_is_optional_too(bprd):
    g = mk(bprd)
    pile(g, "The Wolf's Skin", "Once Upon a Time")
    g.controllers[0].queue = [[False]]
    hands_attack(g)
    assert g.players[0].hand == [] and [c.title for c in g.players[0].discard] == ["The Wolf's Skin", "Once Upon a Time", "What Large Hands You Have"]


def test_with_the_starting_basket_chosen_as_a_rose_there_is_nothing_to_return_and_the_card_does_not_return(bprd):
    g = mk(bprd)
    says(g, "rose")
    card = hands_attack(g)
    assert card not in g.players[0].hand and g.players[0].discard == [card]
    assert not asked(g, 0, "optional")                          # nothing was offered


def test_with_the_starting_basket_chosen_as_a_wolf_the_card_may_return(bprd):
    g = mk(bprd)
    says(g, "wolf")
    g.controllers[0].queue.append([True])
    card = hands_attack(g)
    assert card in g.players[0].hand


# ---------------------------------------------------------------- the other cards

@pytest.mark.parametrize("under,ignored", [("Once Upon a Time", True), ("The Wolf's Skin", False)])
def test_big_eyes_ignore_the_value_of_their_card_only_with_a_rose_on_top(bprd, under, ignored):
    g = mk(bprd, turn=1)
    pile(g, under)
    red, foe = foe_attacks(g, "What Big Eyes You Have")
    assert (red.hp == 14) == ignored                              # Katana's 6 ignored: 0 against 3; otherwise 6 against 3 hurts her


def test_big_eyes_cancel_the_effects_of_their_card_with_any_basket(bprd):
    g = mk(bprd, foe="chupacabra", turn=1)
    pile(g, "The Wolf's Skin")                                    # an axe: only the cancel
    give(g, 0, "Once Upon a Time")                                 # what Ambush would take
    chupa, red = pair(g, "chupacabra", "red")
    g.attack(chupa, red, give(g, 1, "Ambush"), give(g, 0, "What Big Eyes You Have"))
    assert len(g.players[0].hand) == 1 and [c.title for c in g.players[1].discard] == ["Ambush"]       # cancelled: she discarded nothing


def test_long_have_i_sought_you_is_six_with_the_huntsman_next_to_the_target_and_four_otherwise(bprd):
    g = mk(bprd)
    hunter, foe = pair(g, "huntsman", FOE)
    before = foe.hp
    g.attack(hunter, foe, give(g, 0, "Long Have I Sought You"), None)
    assert before - foe.hp == 6                                   # the Huntsman is the attacker and next to the target
    g2 = mk(bprd)
    red, foe2 = pair(g2, "red", FOE)
    g2.fighters["huntsman"].pos = next(s for s in sorted(g2.board.spaces) if s not in (red.pos, foe2.pos) and not g2.board.share_zone(foe2.pos, s))
    before = foe2.hp
    g2.attack(red, foe2, give(g2, 0, "What Big Ears You Have"), None)       # not his card: only the printed 4
    assert before - foe2.hp == 4


def test_long_have_i_sought_you_stays_four_when_the_huntsman_is_far_from_the_target(bprd):
    g = mk(bprd)
    hunter, foe = pair(g, "huntsman", FOE)
    far = next(s for s in sorted(g.board.spaces) if s != foe.pos and s not in g.board.adj[foe.pos] and s != hunter.pos
               and g.board.can_reach_target(hunter.pos, foe.pos, True, 0))
    hunter.pos = far if far in g.board.spaces else hunter.pos
    if hunter.pos in g.board.adj[foe.pos]:
        pytest.skip("this map has no far space within the Huntsman's reach")
    before = foe.hp
    g.attack(hunter, foe, give(g, 0, "Long Have I Sought You"), None)
    assert before - foe.hp == 4


@pytest.mark.parametrize("under,healed", [("The Wolf's Skin", 2), ("Never Leave the Path", 4)])
def test_a_grimm_tale_heals_little_red_two_and_a_wolf_basket_heals_four_instead(bprd, under, healed):
    g = mk(bprd)
    pile(g, under)
    g.fighters["red"].hp = 5
    g.play_scheme(0, g.fighters["huntsman"], give(g, 0, "A Grimm Tale"))
    assert g.fighters["red"].hp == 5 + healed


def test_into_the_woods_moves_her_up_to_three_and_gives_an_action_with_any_basket(bprd):
    g = mk(bprd)
    g.actions_left = 2
    g.play_scheme(0, g.fighters["red"], give(g, 0, "Into the Woods"))
    assert g.actions_left == 2 and not wild_asked(g)
    assert any(r.extra.get("op") == "move" and r.extra.get("steps") == 3 for r in asked(g, 0, "space"))


def test_stones_in_the_belly_makes_the_rival_discard_a_random_card_and_adds_its_boost_with_an_axe(bprd):
    g = mk(bprd)
    pile(g, "The Wolf's Skin")                                   # an axe
    red, foe = pair(g, "red", FOE)
    give(g, 1, "Katana")
    give(g, 1, "Heroes in a half shell")
    before = foe.hp
    g.attack(red, foe, give(g, 0, "Stones in the Belly"), None)
    gone, = g.players[1].discard
    assert len(g.players[1].hand) == 1
    assert before - foe.hp == 2 + gone.boost


def test_stones_in_the_belly_does_nothing_without_an_axe(bprd):
    g = mk(bprd)
    pile(g, "Once Upon a Time")                                  # a rose
    red, foe = pair(g, "red", FOE)
    give(g, 1, "Katana")
    before = foe.hp
    g.attack(red, foe, give(g, 0, "Stones in the Belly"), None)
    assert not g.players[1].discard and before - foe.hp == 2


def test_stones_in_the_belly_against_an_empty_hand_adds_nothing(bprd):
    g = mk(bprd)
    pile(g, "The Wolf's Skin")
    red, foe = pair(g, "red", FOE)
    before = foe.hp
    g.attack(red, foe, give(g, 0, "Stones in the Belly"), None)
    assert before - foe.hp == 2


def test_the_huntsmans_cards_use_her_basket(bprd):
    g = mk(bprd)
    pile(g, "Never Leave the Path")
    g.fighters["red"].hp = 3
    g.play_scheme(0, g.fighters["huntsman"], give(g, 0, "A Grimm Tale"))
    assert g.fighters["red"].hp == 7


def test_the_hero_cards_are_for_her_and_the_huntsman_cards_for_him(bprd):
    g = mk(bprd)
    by = {c.title: c for c in g.players[0].full_set}
    assert by["Long Have I Sought You"].usable_by("Huntsman") and not by["Long Have I Sought You"].usable_by("Little Red")
    assert by["A Grimm Tale"].usable_by("Huntsman") and not by["A Grimm Tale"].usable_by("Little Red")
    assert by["Never Leave the Path"].usable_by("Little Red") and not by["Never Leave the Path"].usable_by("Huntsman")
    assert by["Once Upon a Time"].usable_by("Huntsman") and by["Once Upon a Time"].usable_by("Little Red")


# ---------------------------------------------------------------- What Big Ears You Have: an attack that may defend

def test_big_ears_may_be_played_as_a_defense_with_an_axe_on_top_with_its_printed_four(bprd):
    g = mk(bprd, turn=1)
    pile(g, "The Wolf's Skin")                                     # an axe
    red, foe = foe_attacks(g, "What Big Ears You Have")
    assert red.hp == 14 - (6 - 4) and [c.title for c in g.players[0].discard][-1] == "What Big Ears You Have"


def test_big_ears_may_be_played_as_a_defense_when_the_basket_is_wild(bprd):
    g = mk(bprd, turn=1)
    red, foe = foe_attacks(g, "What Big Ears You Have")             # only the Basket: it may count as an axe
    assert red.hp == 14 - 2 and not wild_asked(g)


@pytest.mark.parametrize("under", ["Never Leave the Path", "Once Upon a Time"])
def test_big_ears_cannot_defend_with_a_wolf_or_a_rose_on_top(bprd, under):
    from sparring.state import RuleError
    g = mk(bprd, turn=1)
    pile(g, under)
    foe, red = pair(g, FOE, "red")
    with pytest.raises(RuleError):
        g.attack(foe, red, katana(g), give(g, 0, "What Big Ears You Have"))


def test_big_ears_is_still_an_attack_with_any_basket(bprd):
    g = mk(bprd)
    pile(g, "Never Leave the Path")
    red, foe = pair(g, "red", FOE)
    before = foe.hp
    g.attack(red, foe, give(g, 0, "What Big Ears You Have"), None)
    assert before - foe.hp == 4

