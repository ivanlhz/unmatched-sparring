"""Luke Cage's ability and cards on the interpreter, bot side (player 0 plays Luke Cage, the controllers answer). The human side
(panel, FakeTTS) is in tests/test_luke_cage_human.py and the full games in tests/test_luke_cage_matrix.py. The numbers are the
ones printed on the real cards (data/heroes/luke-cage.json)."""
from __future__ import annotations

from conftest import give
from sparring.state import Game
from test_bigfoot_effects import Answers, empty_spaces, pick
from test_effects_combat import hp, pair, put_adjacent


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Luke Cage = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("luke-cage", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def foe_attack(g, title="Service Pistol"):
    return give(g, 1, title)


# ---------------------------------------------------------------- the figures and the sheet

def test_luke_cage_is_interpreted_and_has_the_printed_figures(bprd):
    g = mk(bprd)
    assert "luke-cage" in g.fx.dsl_heroes
    assert [f.fid for f in g.own(0)] == ["luke", "misty"]
    luke, misty = g.fighters["luke"], g.fighters["misty"]
    assert (luke.hp, luke.move, misty.hp, misty.move) == (13, 2, 6, 2)
    assert not luke.ranged and misty.ranged
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629


def test_the_sheet_follows_the_images(bprd):
    deck = {c.card_id: c for c in mk(bprd).players[0].full_set}
    by_idx = lambda i: deck[17600 + i]
    assert [by_idx(i).title for i in (0, 2, 4, 7, 10, 12, 15, 17, 19, 21, 23, 26, 28)] == [
        "Sweet Christmas!", "Get Paid", "Hero For Hire", "Commanding Impact", "Still Standing", "Regroup", "Pushback",
        "Daughter of the Dragon", "Power Man", "Skin Like Titanium", "Trash Talk", "Got My Back?", "Where's My Money?"]
    assert {by_idx(i).fighter for i in (15, 16, 17, 18, 26, 27)} == {"Misty Knight"}
    assert {by_idx(i).fighter for i in (7, 10, 12, 23)} == {"any"}
    assert by_idx(21).value == 0 and by_idx(21).type == "defense"          # Skin Like Titanium prints 0, unmatched-memory says nothing


# ---------------------------------------------------------------- the ability

def test_luke_takes_two_less_combat_damage_when_he_defends(bprd):
    g = mk(bprd, turn=1)
    hellboy, luke = pair(g, "hellboy", "luke")
    atk = foe_attack(g)
    res = g.attack(hellboy, luke, atk, None)
    assert res.damage == atk.value - 2 and luke.hp == 13 - (atk.value - 2) and res.attacker_won
    assert any("2" in line for line in res.applied)                                   # the chat says the ability took 2 off


def test_a_blow_of_two_or_less_is_a_win_for_the_defender_even_without_a_card(bprd):
    g = mk(bprd, turn=1)
    hellboy, luke = pair(g, "hellboy", "luke")
    res = g.attack(hellboy, luke, foe_attack(g), None, values=(-3, 0))                # a 5 played as a 2
    assert res.damage == 0 and not res.attacker_won and luke.hp == 13


def test_the_reduction_applies_on_top_of_a_defense_card_and_never_goes_below_zero(bprd):
    g = mk(bprd, turn=1)
    hellboy, luke = pair(g, "hellboy", "luke")
    atk = foe_attack(g)
    defense = give(g, 0, "Trash Talk")
    res = g.attack(hellboy, luke, atk, defense)
    assert res.damage == max(0, atk.value - defense.value - 2) and luke.hp == 13 - res.damage


def test_misty_has_no_reduction_and_effect_damage_is_never_reduced(bprd):
    g = mk(bprd, turn=1)
    hellboy, misty = pair(g, "hellboy", "misty")
    atk = foe_attack(g)
    res = g.attack(hellboy, misty, atk, None)
    assert res.damage == atk.value and misty.hp == max(0, 6 - atk.value)
    luke = g.fighters["luke"]
    before = luke.hp
    g.damage(luke, 3, "effect")
    assert luke.hp == before - 3


def test_luke_attacking_takes_no_damage_and_the_reduction_does_not_touch_his_blows(bprd):
    g = mk(bprd)
    luke, hellboy = pair(g, "luke", "hellboy")
    res = g.attack(luke, hellboy, give(g, 0, "Sweet Christmas!"), None)
    assert res.damage == 6 and hellboy.hp == hellboy.max_hp - 6 and luke.hp == 13


def test_the_rival_luke_is_hit_through_the_reduction_in_the_other_seat(bprd):
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("hellboy", "luke-cage"), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    hellboy, luke = pair(g, "hellboy", "luke")
    atk = give(g, 0, "Service Pistol")
    res = g.attack(hellboy, luke, atk, None)
    assert res.damage == atk.value - 2 and luke.hp == 13 - res.damage


# ---------------------------------------------------------------- the plain and the drawing attacks

def test_sweet_christmas_is_a_plain_six(bprd):
    g = mk(bprd)
    luke, hellboy = pair(g, "luke", "hellboy")
    res = g.attack(luke, hellboy, give(g, 0, "Sweet Christmas!"), None)
    assert res.atk_value == 6 and not g.players[0].hand


def test_get_paid_draws_two_only_when_won(bprd):
    g = mk(bprd)
    luke, hellboy = pair(g, "luke", "hellboy")
    res = g.attack(luke, hellboy, give(g, 0, "Get Paid"), None)
    assert res.attacker_won and len(g.players[0].hand) == 2
    g2 = mk(bprd, "leonardo")
    luke, leo = pair(g2, "luke", "leonardo")
    wall = max((c for c in g2.players[1].deck if c.can_defend), key=lambda c: c.value or 0)
    g2.players[1].deck.remove(wall)
    g2.players[1].hand.append(wall)
    res = g2.attack(luke, leo, give(g2, 0, "Get Paid"), wall)
    assert not res.attacker_won and not g2.players[0].hand


def test_commanding_impact_draws_one_win_or_lose(bprd):
    g = mk(bprd, "leonardo")
    luke, leo = pair(g, "luke", "leonardo")
    wall = max((c for c in g.players[1].deck if c.can_defend), key=lambda c: c.value or 0)
    g.players[1].deck.remove(wall)
    g.players[1].hand.append(wall)
    res = g.attack(luke, leo, give(g, 0, "Commanding Impact"), wall)
    assert not res.attacker_won and len(g.players[0].hand) == 1


def test_regroup_draws_two_when_won_and_one_when_not(bprd):
    g = mk(bprd)
    luke, hellboy = pair(g, "luke", "hellboy")
    res = g.attack(luke, hellboy, give(g, 0, "Regroup"), None)
    assert res.attacker_won and len(g.players[0].hand) == 2
    g2 = mk(bprd, "leonardo")
    luke, leo = pair(g2, "luke", "leonardo")
    wall = max((c for c in g2.players[1].deck if c.can_defend), key=lambda c: c.value or 0)
    g2.players[1].deck.remove(wall)
    g2.players[1].hand.append(wall)
    res = g2.attack(luke, leo, give(g2, 0, "Regroup"), wall)
    assert not res.attacker_won and len(g2.players[0].hand) == 1


def test_hero_for_hire_may_boost_itself(bprd):
    from sparring.combat import can_boost
    g = mk(bprd)
    assert can_boost(give(g, 0, "Hero For Hire"))
    assert not can_boost(give(g, 0, "Sweet Christmas!"))


# ---------------------------------------------------------------- Still Standing

def test_still_standing_won_shuffles_two_chosen_discarded_cards_into_the_deck(bprd):
    g = mk(bprd)
    luke, hellboy = pair(g, "luke", "hellboy")
    p = g.players[0]
    junk = [give(g, 0, "Regroup", i) for i in range(3)]
    for c in junk:
        p.hand.remove(c)
        p.discard.append(c)
    deck_before = len(p.deck)
    g.controllers[0].queue = [lambda req: [req.options[0], req.options[1]]]
    res = g.attack(luke, hellboy, give(g, 0, "Still Standing"), None)
    assert res.attacker_won
    assert len(p.discard) == 1 + 1 and len(p.deck) == deck_before + 2         # 3 junk - 2 back + the played card


def test_still_standing_lost_returns_nothing(bprd):
    g = mk(bprd, "leonardo")
    luke, leo = pair(g, "luke", "leonardo")
    p = g.players[0]
    c = give(g, 0, "Regroup")
    p.hand.remove(c)
    p.discard.append(c)
    wall = max((x for x in g.players[1].deck if x.can_defend), key=lambda x: x.value or 0)
    g.players[1].deck.remove(wall)
    g.players[1].hand.append(wall)
    deck_before = len(p.deck)
    res = g.attack(luke, leo, give(g, 0, "Still Standing"), wall)
    assert not res.attacker_won and len(p.deck) == deck_before and c in p.discard


# ---------------------------------------------------------------- Pushback and Power Man

def test_pushback_moves_the_opposing_fighter_up_to_three_spaces_win_or_lose(bprd):
    g = mk(bprd, "leonardo")
    misty, leo = pair(g, "misty", "leonardo")
    start = leo.pos
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options, key=lambda s: g.board.distance(start, s))]]
    wall = max((x for x in g.players[1].deck if x.can_defend), key=lambda x: x.value or 0)
    g.players[1].deck.remove(wall)
    g.players[1].hand.append(wall)
    g.attack(misty, leo, give(g, 0, "Pushback"), wall)
    assert seen[0].extra["steps"] == 3 and seen[0].extra["up_to"] is True and not seen[0].extra.get("through")
    assert leo.pos != start and g.board.distance(start, leo.pos) <= 3


def test_daughter_of_the_dragon_is_six_with_misty_next_to_the_opposing_fighter(bprd):
    g = mk(bprd)
    misty, hellboy = pair(g, "misty", "hellboy")
    res = g.attack(misty, hellboy, give(g, 0, "Daughter of the Dragon"), None)
    assert res.atk_value == 6
    g2 = mk(bprd)
    misty, hellboy = pair(g2, "misty", "hellboy")
    misty.pos = next(s for s in sorted(g2.board.spaces) if g2.board.share_zone(hellboy.pos, s) and s not in g2.board.adj[hellboy.pos]
                     and s != hellboy.pos and all(f.pos != s for f in g2.fighters.values() if f.alive))
    res = g2.attack(misty, hellboy, give(g2, 0, "Daughter of the Dragon"), None)
    assert res.atk_value == 2


def power_man_scene(bprd):
    """Luke defends on Hellboy's turn; Lobster stands behind Hellboy on a line a - b - c, with a free space d beyond Lobster."""
    g = mk(bprd, turn=1)
    luke, hellboy, lobster = g.fighters["luke"], g.fighters["hellboy"], g.fighters["lobster"]
    for a in sorted(g.board.spaces):
        for b in sorted(g.board.adj[a]):
            for c in sorted(g.board.adj[b]):
                for d in sorted(g.board.adj[c]):
                    if len({a, b, c, d}) == 4 and g.board.distance(b, d) == 2 and g.board.distance(a, c) == 2:
                        parked = [s for s in sorted(g.board.spaces, reverse=True) if s not in (a, b, c, d)]
                        others = [f for f in g.fighters.values() if f.alive and f.fid not in ("luke", "hellboy", "lobster")]
                        for f, s in zip(others, parked):
                            f.pos = s
                        luke.pos, hellboy.pos, lobster.pos = a, b, c
                        return g, luke, hellboy, lobster, d
    raise AssertionError("no line of four")


def test_power_man_moves_the_attacker_through_another_opposing_fighter_and_hits_both(bprd):
    g, luke, hellboy, lobster, d = power_man_scene(bprd)
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [d]]
    atk = foe_attack(g)
    before = hp(g, "hellboy", "lobster")
    res = g.attack(hellboy, luke, atk, give(g, 0, "Power Man"))
    assert seen[0].extra["steps"] == 3 and not seen[0].extra["through"]       # a fighter always crosses its own side
    assert hellboy.pos == d
    assert hp(g, "hellboy", "lobster") == [before[0] - 1, before[1] - 1]
    assert res.damage == max(0, atk.value - 2 - 2)


def test_power_man_staying_put_still_hits_the_opposing_fighter_for_one(bprd):
    g, luke, hellboy, lobster, d = power_man_scene(bprd)
    g.controllers[0].queue = [[]]
    before = hp(g, "hellboy", "lobster")
    g.attack(hellboy, luke, foe_attack(g), give(g, 0, "Power Man"))
    assert hp(g, "hellboy", "lobster") == [before[0] - 1, before[1]]


def test_power_man_does_not_hit_a_fighter_too_far_to_have_been_on_the_path(bprd):
    g, luke, hellboy, lobster, d = power_man_scene(bprd)
    lobster.pos = next(s for s in sorted(g.board.spaces, reverse=True) if g.board.distance(hellboy.pos, s) > 3
                       and all(f.pos != s for f in g.fighters.values() if f.alive))
    dest = next(s for s in empty_spaces(g, hellboy.pos, 3))
    g.controllers[0].queue = [[dest]]
    before = lobster.hp
    g.attack(hellboy, luke, foe_attack(g), give(g, 0, "Power Man"))
    assert hellboy.pos == dest and lobster.hp == before


# ---------------------------------------------------------------- Skin Like Titanium, Trash Talk

def test_skin_like_titanium_returns_the_combat_damage_luke_really_took(bprd):
    g = mk(bprd, turn=1)
    hellboy, luke = pair(g, "hellboy", "luke")
    atk = foe_attack(g)
    res = g.attack(hellboy, luke, atk, give(g, 0, "Skin Like Titanium"))
    took = atk.value - 0 - 2
    assert res.damage == took and luke.hp == 13 - took
    assert hellboy.hp == hellboy.max_hp - took                       # after the 2 less, not before


def test_skin_like_titanium_deals_nothing_when_luke_wins(bprd):
    g = mk(bprd, turn=1)
    hellboy, luke = pair(g, "hellboy", "luke")
    res = g.attack(hellboy, luke, foe_attack(g), give(g, 0, "Skin Like Titanium"), values=(-3, 0))
    assert not res.attacker_won and hellboy.hp == hellboy.max_hp and luke.hp == 13


def test_trash_talk_cancels_the_attackers_effects_and_ends_the_turn_when_luke_wins(bprd):
    g = mk(bprd, "liz-sherman", turn=1)
    g.actions_left = 2
    liz, luke = pair(g, "liz", "luke")
    liz_atk = give(g, 1, "Flame Lash")
    res = g.attack(liz, luke, liz_atk, give(g, 0, "Trash Talk"))
    assert "atk" in res.cancelled
    won = not res.attacker_won
    assert (g.actions_left == 0) == won


def test_trash_talk_ends_the_turn_on_a_win_with_a_weak_attack(bprd):
    g = mk(bprd, turn=1)
    g.actions_left = 2
    hellboy, luke = pair(g, "hellboy", "luke")
    res = g.attack(hellboy, luke, foe_attack(g), give(g, 0, "Trash Talk"), values=(-1, 0))        # 4 - 2 - 2 = 0
    assert not res.attacker_won and g.actions_left == 0


def test_trash_talk_lost_does_not_end_the_turn(bprd):
    g = mk(bprd, turn=1)
    g.actions_left = 2
    hellboy, luke = pair(g, "hellboy", "luke")
    res = g.attack(hellboy, luke, give(g, 1, "Excalibur"), give(g, 0, "Trash Talk"))        # 6 - 2 - 2 = 2 lands
    assert res.attacker_won and g.actions_left == 1                                       # the attack spent one of the two


# ---------------------------------------------------------------- Got My Back?

def test_got_my_back_swaps_misty_and_luke_and_luke_takes_the_blow_with_his_two_less(bprd):
    g = mk(bprd, turn=1)
    hellboy, misty = pair(g, "hellboy", "misty")
    luke = g.fighters["luke"]
    where_m = misty.pos
    luke.pos = next(s for s in sorted(g.board.spaces, reverse=True)
                    if all(f.pos != s for f in g.fighters.values() if f.alive) and s != where_m)
    where_l = luke.pos
    g.controllers[0].queue = [[True]]
    atk = foe_attack(g)
    res = g.attack(hellboy, misty, atk, give(g, 0, "Got My Back?"))
    assert (misty.pos, luke.pos) == (where_l, where_m)
    assert res.target == "luke" and res.damage == max(0, atk.value - 1 - 2)
    assert luke.hp == 13 - res.damage and misty.hp == 6


def test_got_my_back_declined_changes_nobody(bprd):
    g = mk(bprd, turn=1)
    hellboy, misty = pair(g, "hellboy", "misty")
    luke = g.fighters["luke"]
    where = (misty.pos, luke.pos)
    g.controllers[0].queue = [[False]]
    atk = foe_attack(g)
    res = g.attack(hellboy, misty, atk, give(g, 0, "Got My Back?"))
    assert (misty.pos, luke.pos) == where and res.target == "misty" and res.damage == max(0, atk.value - 1)


# ---------------------------------------------------------------- Where's My Money?

def test_wheres_my_money_places_luke_next_to_the_nearest_opposing_fighter_and_gains_an_action(bprd):
    g = mk(bprd)
    luke, hellboy = pair(g, "luke", "hellboy")
    lobster = g.fighters["lobster"]
    far = max(g.board.spaces, key=lambda s: g.board.distance(hellboy.pos, s))
    luke.pos = far
    spots = [s for s in sorted(g.board.spaces) if s not in (far, hellboy.pos) and g.board.distance(far, s) > g.board.distance(far, hellboy.pos)]
    lobster.pos = max(spots, key=lambda s: g.board.distance(far, s))                       # Lobster is farther than Hellboy
    near = hellboy if g.board.span(far, hellboy.pos) < g.board.span(far, lobster.pos) else lobster
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[0]]]
    g.actions_left = 2
    g.play_scheme(0, luke, give(g, 0, "Where's My Money?"))
    assert luke.pos in g.board.adj[near.pos] and g.actions_left == 2          # scheme spends 1, gains 1
    assert set(seen[0].options) <= set(g.board.adj[near.pos])


def test_wheres_my_money_options_are_the_free_spaces_around_the_nearest_foe_only(bprd):
    g = mk(bprd)
    luke, hellboy = pair(g, "luke", "hellboy")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[-1]]]
    g.actions_left = 2
    g.play_scheme(0, luke, give(g, 0, "Where's My Money?"))
    taken = {f.pos for f in g.fighters.values() if f.alive and f is not luke}
    assert seen and all(s in g.board.adj[hellboy.pos] and s not in taken for s in seen[0].options)


# ---------------------------------------------------------------- Daughter of the Dragon defending, and the bot's view

def test_misty_defends_with_daughter_of_the_dragon_for_six_when_next_to_the_attacker(bprd):
    g = mk(bprd, turn=1)
    hellboy, misty = pair(g, "hellboy", "misty")
    res = g.attack(hellboy, misty, foe_attack(g), give(g, 0, "Daughter of the Dragon"))
    assert res.def_value == 6 and misty.hp == 6 - max(0, res.atk_value - 6)


def test_the_bot_counts_the_two_less_when_it_weighs_a_blow_on_luke_cage(bprd, monkeypatch):
    from sparring.ai_medusa import MedusaAI, Model
    from sparring.effects.state import EffectState
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("hellboy", "luke-cage"), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    hellboy, luke = pair(g, "hellboy", "luke")
    ai = MedusaAI(0)
    model = Model(g, 0)
    pistol = give(g, 0, "Service Pistol")
    with_ability = ai.attack_outcome(g, model, hellboy, luke, pistol)
    monkeypatch.setattr(EffectState, "combat_damage_reduction", lambda self, fighter: 0)      # the same blow on a Luke Cage without the ability
    without = ai.attack_outcome(g, model, hellboy, luke, pistol)
    assert with_ability[1] < without[1]


def test_the_bot_swaps_with_got_my_back_when_misty_would_fall_and_luke_takes_the_blow_lightly(bprd):
    from sparring.ai_medusa import MedusaAI
    ai = MedusaAI(0)
    g = Game.new(bprd, 3, controllers={0: ai, 1: Answers()}, heroes=("luke-cage", "hellboy"), bot_player=0)
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    hellboy, misty = pair(g, "hellboy", "misty")
    misty.hp = 1
    res = g.attack(hellboy, misty, foe_attack(g), give(g, 0, "Got My Back?"))
    assert res.target == "luke" and g.fighters["misty"].alive
