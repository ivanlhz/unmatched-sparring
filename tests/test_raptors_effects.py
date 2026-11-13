"""Raptors on the engine, bot side (player 0 plays them, the controllers answer): the three Raptors (Blue the hero fighter, Delta and
Echo the team), the loss only when all three are defeated, the PACK BONUS (+1 to their attack cards per other Raptor next to the
defender) and every card with the numbers printed on it. The human side (panel, FakeTTS) is in tests/test_raptors_human.py, the AI
in tests/test_raptors_ai.py and the full games in tests/test_raptors_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import pack
from sparring.persist import apply_game, game_to_dict
from sparring.state import Game
from test_bigfoot_effects import Answers, wall
from test_effects_combat import pair, put_adjacent

TEAM = ["blue", "delta", "echo"]


@pytest.fixture(autouse=True)
def raptors_are_interpreted(monkeypatch):
    """The effects of the Raptors run on the interpreter; until `INTERPRETED_HEROES` lists them (a shared file) the tests list them themselves."""
    from sparring.effects import state
    monkeypatch.setattr(state, "INTERPRETED_HEROES", state.INTERPRETED_HEROES | {"raptors"})


def mk(bprd, foe="leonardo", seed=3, turn=0):
    """Raptors = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("raptors", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def around(g, target, fids):
    """Each fighter of `fids` on its own free space next to `target`."""
    for fid in fids:
        put_adjacent(g, fid, target)


def free_spaces(g, near=None, within=None):
    taken = {f.pos for f in g.fighters.values() if f.alive}
    out = [s for s in sorted(g.board.spaces) if s not in taken]
    if near is not None:
        out = [s for s in out if g.board.distance(near, s) <= within]
    return out


# ---------------------------------------------------------------- the team

def test_the_raptors_are_three_melee_fighters_of_seven_life_and_move_three(bprd):
    g = mk(bprd)
    assert [f.fid for f in g.own(0)] == TEAM
    assert all((f.hp, f.max_hp, f.move, f.ranged, f.reach) == (7, 7, 3, False, 0) for f in g.own(0))
    assert [f.name for f in g.own(0)] == ["Raptor Blue", "Raptor Delta", "Raptor Echo"]
    assert [f.fid for f in g.own(0) if f.hero] == ["blue"]
    assert g.players[0].hero.team and not g.players[1].hero.team
    assert "raptors" in g.fx.dsl_heroes


def test_the_deck_has_the_printed_bands_and_numbers(bprd):
    g = mk(bprd)
    seen = {}
    for c in g.players[0].full_set:
        t = seen.setdefault(c.title, [c.type, c.value, c.boost, c.fighter, 0])
        t[4] += 1
    assert {k: tuple(v) for k, v in seen.items()} == {
        "Eviscerate": ("attack", 5, 3, "any", 2), "Pack Hunters": ("attack", 4, 2, "any", 2),
        "Clever Girl": ("attack", 3, 3, "any", 3), "Disengage": ("attack", 4, 2, "any", 2),
        "Ambush": ("attack", 2, 3, "any", 3), "They Remember": ("attack", 2, 2, "any", 4),
        "Feint": ("versatile", 2, 1, "any", 3), "Eaten Alive": ("versatile", 4, 2, "any", 3),
        "Decoy": ("defense", 3, 1, "any", 4), "Coordinated Attack Pattern": ("scheme", None, 2, "any", 2),
        "Working Things Out": ("scheme", None, 2, "any", 2)}
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629


def test_the_raptors_lose_only_when_all_three_are_defeated(bprd):
    g = mk(bprd)
    g.defeat(g.fighters["blue"])
    assert g.winner is None
    g.defeat(g.fighters["delta"])
    assert g.winner is None
    g.defeat(g.fighters["echo"])
    assert g.winner == 1


def test_when_blue_falls_the_first_raptor_standing_is_the_hero_fighter(bprd):
    g = mk(bprd)
    g.defeat(g.fighters["blue"])
    assert g.hero(0).fid == "delta" and g.fighters["delta"].hero and not g.fighters["blue"].hero
    g.defeat(g.fighters["delta"])
    assert g.hero(0).fid == "echo"


def test_a_sidekick_raptor_falling_first_changes_nothing_about_the_hero(bprd):
    g = mk(bprd)
    g.defeat(g.fighters["echo"])
    assert g.hero(0).fid == "blue" and g.winner is None


def test_the_rival_still_loses_the_moment_its_hero_falls(bprd):
    g = mk(bprd)
    g.defeat(g.fighters["leonardo"])
    assert g.winner == 0


def test_a_saved_game_where_blue_is_down_gives_the_hero_to_the_next_raptor(bprd):
    g = mk(bprd)
    g.defeat(g.fighters["blue"])
    saved = game_to_dict(g)
    fresh = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("raptors", "leonardo"), bot_player=0)
    apply_game(fresh, saved)
    assert fresh.winner is None and fresh.hero(0).fid == "delta" and fresh.hero(0).alive


# ---------------------------------------------------------------- PACK BONUS

def test_the_attack_is_worth_one_more_for_each_other_raptor_next_to_the_defender(bprd):
    values = []
    for mates in ([], ["delta"], ["delta", "echo"]):
        g = mk(bprd)
        blue, leo = pair(g, "blue", "leonardo")
        around(g, "leonardo", mates)
        res = g.attack(blue, leo, give(g, 0, "Eviscerate"), None)
        values.append(res.atk_value)
    assert values == [5, 6, 7]


def test_the_bonus_shows_in_the_parts_with_its_label(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    around(g, "leonardo", ["delta", "echo"])
    assert g.attack_bonus_parts(blue, leo) == [(2, "PACK BONUS")]
    assert g.attack_bonus(blue, leo) == 2


def test_the_attacker_itself_and_a_raptor_away_from_the_defender_do_not_count(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    assert pack.mates_adjacent(g, blue, leo) == []         # Blue is next to him but is the attacker; the others stand far away
    around(g, "leonardo", ["echo"])
    assert [f.fid for f in pack.mates_adjacent(g, blue, leo)] == ["echo"]
    assert g.attack_bonus(g.fighters["echo"], leo) == 1        # for Echo, Blue is the other Raptor beside the defender


def test_a_defeated_raptor_next_to_the_defender_is_not_counted(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    around(g, "leonardo", ["delta"])
    g.defeat(g.fighters["delta"])
    assert g.attack_bonus(blue, leo) == 0


def test_a_rival_fighter_beside_the_defender_does_not_count(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    put_adjacent(g, "splinter", "leonardo")
    assert g.attack_bonus(blue, leo) == 0


def test_a_versatile_card_gets_the_bonus_as_an_attack_and_not_as_a_defense(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    around(g, "leonardo", ["delta"])
    assert g.attack(blue, leo, give(g, 0, "Eaten Alive"), None).atk_value == 4 + 1
    around(g, "leonardo", ["echo"])
    assert g.defense_bonus_parts(0) == []                    # "their attack cards": nothing is added to a defense


def test_the_rival_hero_has_no_pack_bonus(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    assert g.attack_bonus(leo, blue) == 0 and pack.bonus_parts(g, leo, blue) == []


# ---------------------------------------------------------------- the cards

def test_eviscerate_has_no_effect_and_hits_for_five(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    res = g.attack(blue, leo, give(g, 0, "Eviscerate"), None)
    assert res.atk_value == 5 and leo.hp == leo.max_hp - 5


def test_pack_hunters_deals_one_damage_for_each_raptor_next_to_the_opposing_fighter_after_a_win(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    around(g, "leonardo", ["delta"])
    g.attack(blue, leo, give(g, 0, "Pack Hunters"), None)
    # 4 + 1 (pack bonus) combat damage, then 1 for Blue and 1 for Delta, both next to him
    assert leo.hp == leo.max_hp - 5 - 2


def test_pack_hunters_does_nothing_when_the_combat_is_lost(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    hp = leo.hp
    assert g.attack(blue, leo, give(g, 0, "Pack Hunters"), wall(g)).atk_value == 4       # alone beside him: no bonus, 4 against his 5
    assert leo.hp == hp


def test_pack_hunters_counts_every_raptor_beside_the_opposing_fighter_even_if_the_blow_barely_wins(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    around(g, "leonardo", ["delta", "echo"])
    hp = leo.hp
    res = g.attack(g.fighters["delta"], leo, give(g, 0, "Pack Hunters"), wall(g))       # 4 + 2 (Blue and Echo beside him) against his best defense
    assert res.atk_value == 6 and leo.hp == hp - 1 - 3          # still a win by one point: 1 combat damage and then 1 per Raptor beside him


def test_pack_hunters_counts_the_attacker_only_when_it_stands_next_to_the_defender(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    g.attack(blue, leo, give(g, 0, "Pack Hunters"), None)
    assert leo.hp == leo.max_hp - 4 - 1                            # Blue alone next to him: 4 combat damage + 1


def test_disengage_places_the_raptor_on_another_space_of_her_zone(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    start = blue.pos
    asked = []
    g.controllers[0].queue = [lambda req: asked.append(req) or [req.options[-1]]]
    g.attack(blue, leo, give(g, 0, "Disengage"), wall(g))
    assert asked and start not in asked[0].options
    assert blue.pos != start and g.board.share_zone(start, blue.pos)


def test_they_remember_gains_an_action_even_when_the_combat_is_lost(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    g.attack(blue, leo, give(g, 0, "They Remember"), wall(g))
    assert g.actions_left == 2                       # the attack cost one, the card gave it back


def test_clever_girl_gains_an_action_with_a_raptor_next_to_the_opposing_fighter(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    g.attack(blue, leo, give(g, 0, "Clever Girl"), wall(g))
    assert g.actions_left == 2                       # Blue herself is next to him: "one or more of your Raptors"


def test_eaten_alive_deals_one_damage_to_an_adjacent_opposing_fighter_after_a_win(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    splinter = g.fighters["splinter"]
    put_adjacent(g, "splinter", "blue")
    hp = splinter.hp
    g.controllers[0].queue = [lambda req: ["splinter"]]
    g.attack(blue, leo, give(g, 0, "Eaten Alive"), None)
    assert splinter.hp == hp - 1


def test_eaten_alive_does_nothing_when_the_combat_is_lost(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    hp = leo.hp
    g.attack(blue, leo, give(g, 0, "Eaten Alive"), wall(g))
    assert leo.hp == hp


def test_feint_cancels_the_effects_of_the_opponents_card(bprd):
    g = mk(bprd, turn=1)
    leo, blue = pair(g, "leonardo", "blue")
    c = next(c for c in g.players[1].deck if c.title == "Eat, sleep, and breathe ninjutsu")
    g.players[1].deck.remove(c)
    g.players[1].hand.append(c)
    before = [f.pos for f in g.fighters.values()]
    g.attack(leo, blue, c, give(g, 0, "Feint"))
    assert [f.pos for f in g.fighters.values()] == before        # the card's AFTER effect (it moves fighters) was cancelled


def test_ambush_discards_a_random_card_of_the_opponent_and_adds_its_boost(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    victim = g.players[1]
    victim.hand.extend(victim.deck[:3])
    del victim.deck[:3]
    held = list(victim.hand)
    res = g.attack(blue, leo, give(g, 0, "Ambush"), None)
    gone = [c for c in held if c not in victim.hand]
    assert len(gone) == 1 and gone[0] in victim.discard
    assert res.atk_value == 2 + (gone[0].boost or 0)


def test_ambush_against_an_empty_hand_adds_nothing(bprd):
    g = mk(bprd)
    blue, leo = pair(g, "blue", "leonardo")
    assert g.attack(blue, leo, give(g, 0, "Ambush"), None).atk_value == 2


def answers(*steps):
    """Answers for a queue: a function of the request for each decision, by kind (the rest takes the first option / the given order)."""
    def answer(req):
        got = steps[0].get(req.kind) if steps else None
        if got is not None:
            return got(req) if callable(got) else got
        return list(req.options) if req.kind == "order" else [req.options[0]]
    return answer


def foe_plain_attack(g):
    """A card of the rival's deck that attacks and says nothing, in its hand."""
    c = next(c for c in g.players[1].deck if c.can_attack and not c.text)
    g.players[1].deck.remove(c)
    g.players[1].hand.append(c)
    return c


def test_decoy_places_another_raptor_next_to_the_opposing_fighter(bprd):
    g = mk(bprd, turn=1)
    leo, blue = pair(g, "leonardo", "blue")
    delta = g.fighters["delta"]
    assert delta.pos not in g.board.adj[leo.pos]
    g.controllers[0].queue = [answers({"fighter": ["delta"]})] * 4
    g.attack(leo, blue, foe_plain_attack(g), give(g, 0, "Decoy"))
    assert delta.pos in g.board.adj[leo.pos] and delta.pos != blue.pos


def test_decoy_offers_only_the_other_raptors(bprd):
    g = mk(bprd, turn=1)
    leo, blue = pair(g, "leonardo", "blue")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[0]]] * 4
    g.attack(leo, blue, foe_plain_attack(g), give(g, 0, "Decoy"))
    asked = [r for r in seen if r.kind == "fighter"]
    assert asked and all(set(r.options) == {"delta", "echo"} for r in asked)


def test_working_things_out_moves_each_raptor_up_to_three_and_gains_an_action(bprd):
    g = mk(bprd)
    before = {f.fid: f.pos for f in g.own(0)}
    g.controllers[0].queue = [answers({"space": lambda req: [req.options[-1]]})] * 12
    g.play_scheme(0, g.fighters["blue"], give(g, 0, "Working Things Out"))
    after = {f.fid: f.pos for f in g.own(0)}
    assert after != before and len(set(after.values())) == 3
    assert all(g.board.distance(before[k], after[k]) <= 3 for k in TEAM)
    assert g.actions_left == 2                       # the scheme cost one action, the card gives one back


def test_working_things_out_may_cross_the_opposing_fighters_and_stay_put(bprd):
    g = mk(bprd)
    asked = []
    g.controllers[0].queue = [lambda req: asked.append(req) or ([req.options[0]] if req.kind != "order" else list(req.options))] * 12
    g.play_scheme(0, g.fighters["blue"], give(g, 0, "Working Things Out"))
    moves = [r for r in asked if r.kind == "space"]
    assert len(moves) == 3 and all(r.extra["through"] and r.extra["up_to"] and r.extra["steps"] == 3 for r in moves)


def test_coordinated_attack_pattern_places_the_other_raptors_in_the_chosen_raptors_zone(bprd):
    g = mk(bprd)
    blue = g.fighters["blue"]
    far = [s for s in sorted(g.board.spaces, reverse=True) if not g.board.share_zone(blue.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive)]
    g.fighters["delta"].pos, g.fighters["echo"].pos = far[0], far[1]
    g.controllers[0].queue = [answers({"effect": [0]})] * 8              # option 0: the anchor is Blue
    g.play_scheme(0, blue, give(g, 0, "Coordinated Attack Pattern"))
    assert g.board.share_zone(blue.pos, g.fighters["delta"].pos) and g.board.share_zone(blue.pos, g.fighters["echo"].pos)
    assert g.actions_left == 1


def test_coordinated_attack_pattern_may_leave_a_raptor_where_it_is(bprd):
    g = mk(bprd)
    blue = g.fighters["blue"]
    spots = {f.fid: f.pos for f in g.own(0)}
    g.controllers[0].queue = [answers({"effect": [0], "optional": [False]})] * 8
    g.play_scheme(0, blue, give(g, 0, "Coordinated Attack Pattern"))
    assert {f.fid: f.pos for f in g.own(0)} == spots


def test_coordinated_attack_pattern_never_moves_the_chosen_raptor(bprd):
    g = mk(bprd)
    delta = g.fighters["delta"]
    spot = delta.pos
    g.controllers[0].queue = [answers({"effect": [1]})] * 8             # option 1: the anchor is Delta
    g.play_scheme(0, g.fighters["blue"], give(g, 0, "Coordinated Attack Pattern"))
    assert delta.pos == spot
    assert all(g.board.share_zone(spot, g.fighters[k].pos) for k in ("blue", "echo"))


def test_coordinated_attack_pattern_skips_a_defeated_raptor(bprd):
    g = mk(bprd)
    g.defeat(g.fighters["echo"])
    g.controllers[0].queue = [answers({"effect": [0]})] * 8
    g.play_scheme(0, g.fighters["blue"], give(g, 0, "Coordinated Attack Pattern"))
    assert not g.fighters["echo"].alive and g.fighters["echo"].pos is None
