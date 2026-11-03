"""Bigfoot's cards and his end-of-turn ability on the interpreter, bot side (player 0 plays Bigfoot, the controllers answer).
The human side (panel, FakeTTS) is in tests/test_bigfoot_human.py and the full games in tests/test_bigfoot_matrix.py. The numbers
are the ones printed on the real cards (data/heroes/bigfoot.json)."""
from __future__ import annotations

import pytest

from conftest import card, give
from sparring.ai_medusa import MedusaAI
from sparring.state import Game
from test_effects_combat import Asking, hand_filler, hp, pair, put_adjacent


class Answers(Asking):
    """An Asking whose queued answers may be functions of the request (to pick an option without knowing the board's numbering)."""

    def choose_effect(self, game, req):
        self.requests.append(req)
        if not self.queue:
            return None
        answer = self.queue.pop(0)
        return answer(req) if callable(answer) else answer


def pick(where):
    """The option of a space request that satisfies `where(space)`, the farthest-numbered one."""
    return lambda req: [max(s for s in req.options if where(s))]


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Bigfoot = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("bigfoot", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def start_turn(g):
    """The fighters stand where they are when the turn starts (what Momentous Shift compares against)."""
    g.fx.emit("start_of_turn", g.turn)


def empty_spaces(g, near, within):
    taken = {f.pos for f in g.fighters.values() if f.alive}
    return sorted((s for s in g.board.spaces if s not in taken and 0 < g.board.distance(near, s) <= within),
                  key=lambda s: (-g.board.distance(near, s), s))


def line_of_three(board):
    for a in sorted(board.spaces):
        for b in sorted(board.adj[a]):
            for c in sorted(board.adj[b]):
                if board.distance(a, c) == 2:
                    return a, b, c


def wall(g, value=5):
    """The best defense card of the rival's deck, in hand (it beats any attack of value <= its own)."""
    best = max((c for c in g.players[1].deck if c.can_defend), key=lambda c: (c.value or 0, c.boost))
    g.players[1].deck.remove(best)
    g.players[1].hand.append(best)
    return best


def isolate(g):
    """Every opposing fighter outside Bigfoot's zone."""
    bf = g.fighters["bigfoot"]
    far = [s for s in sorted(g.board.spaces, reverse=True) if not g.board.share_zone(bf.pos, s)]
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.owner == 1], far):
        f.pos = s


# ---------------------------------------------------------------- the deck

def test_bigfoot_is_interpreted_and_has_the_printed_figures(bprd):
    g = mk(bprd)
    assert "bigfoot" in g.fx.dsl_heroes
    assert [f.fid for f in g.own(0)] == ["bigfoot", "jackalope"]
    assert (g.fighters["bigfoot"].hp, g.fighters["bigfoot"].move, g.fighters["jackalope"].hp, g.fighters["jackalope"].move) == (16, 3, 6, 3)
    assert not g.fighters["bigfoot"].ranged and not g.fighters["jackalope"].ranged
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629


def test_the_sheet_follows_the_images(bprd):
    deck = {c.card_id: c for c in mk(bprd).players[0].full_set}
    by_idx = lambda i: deck[17600 + i]
    assert [by_idx(i).title for i in (0, 3, 6, 8, 11, 14, 17, 20, 23, 25, 27)] == [
        "Larger Than Life", "Savagery", "Disengage", "Momentous Shift", "Skirmish", "Hoax", "Regroup", "Feint",
        "It's Just Your Imagination", "Crash Through the Trees", "Jackalope Horns"]
    assert by_idx(27).fighter == by_idx(29).fighter == "The Jackalope"
    assert by_idx(25).fighter == "Bigfoot" and by_idx(0).fighter == "Bigfoot" and by_idx(6).fighter == "any"
    assert [by_idx(i).type for i in (0, 6, 8, 23, 25, 27)] == ["attack", "attack", "versatile", "defense", "scheme", "scheme"]


# ---------------------------------------------------------------- Larger Than Life, Feint, It's Just Your Imagination

def test_larger_than_life_is_a_plain_six(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    res = g.attack(bigfoot, hellboy, give(g, 0, "Larger Than Life"), None)
    assert res.atk_value == 6 and res.attacker_won and hellboy.hp == hellboy.max_hp - 6


@pytest.mark.parametrize("title", ["Feint", "It's Just Your Imagination"])
def test_the_cancel_cards_cancel_the_attackers_effects_on_defense(bprd, title):
    g = mk(bprd, "liz-sherman")
    g.turn, g.actions_left = 1, 2
    bigfoot, liz = pair(g, "bigfoot", "liz")
    liz_atk = give(g, 1, "Flame Lash")                       # DURING: the bottom card of the deck boosts it; AFTER: an action
    res = g.attack(liz, bigfoot, liz_atk, give(g, 0, title))
    assert "atk" in res.cancelled and res.atk_value == liz_atk.value and g.actions_left == 1


def test_feint_cancels_the_defenders_effects_on_attack(bprd):
    g = mk(bprd, "liz-sherman")
    bigfoot, liz = pair(g, "bigfoot", "liz")
    liz_def = give(g, 1, "Burning Barrier")
    res = g.attack(bigfoot, liz, give(g, 0, "Feint"), liz_def)
    assert "def" in res.cancelled


# ---------------------------------------------------------------- Savagery

def savagery_scene(bprd, foe="hellboy"):
    g = mk(bprd, foe)
    bigfoot, rival = pair(g, "bigfoot", g.hero(1).fid)
    jackalope = g.fighters["jackalope"]
    jackalope.pos = next(s for s in sorted(g.board.adj[bigfoot.pos]) if s != rival.pos)
    side = next(f for f in g.own(1) if not f.hero)
    side.pos = next(s for s in sorted(g.board.adj[bigfoot.pos]) if s not in (rival.pos, jackalope.pos))
    return g, bigfoot, rival, jackalope, side


def test_savagery_won_hits_every_fighter_next_to_bigfoot_for_one(bprd):
    g, bigfoot, hellboy, jackalope, lobster = savagery_scene(bprd)
    before = (hellboy.hp, lobster.hp, jackalope.hp, bigfoot.hp)
    res = g.attack(bigfoot, hellboy, give(g, 0, "Savagery"), None)
    assert res.attacker_won and res.atk_value == 4
    assert (hellboy.hp, lobster.hp, jackalope.hp, bigfoot.hp) == (before[0] - 4 - 1, before[1] - 1, before[2] - 1, before[3])


def test_savagery_does_nothing_when_the_combat_is_not_won(bprd):
    g, bigfoot, leonardo, jackalope, side = savagery_scene(bprd, "leonardo")
    wall(g)
    before = (leonardo.hp, side.hp, jackalope.hp)
    res = g.attack(bigfoot, leonardo, give(g, 0, "Savagery"), g.players[1].hand[0])
    assert not res.attacker_won
    assert (leonardo.hp, side.hp, jackalope.hp) == before


def test_savagery_does_not_reach_a_fighter_that_is_not_adjacent(bprd):
    g, bigfoot, hellboy, jackalope, lobster = savagery_scene(bprd)
    lobster.pos = max(g.board.spaces, key=lambda s: g.board.distance(bigfoot.pos, s))
    g.attack(bigfoot, hellboy, give(g, 0, "Savagery"), None)
    assert lobster.hp == lobster.max_hp


# ---------------------------------------------------------------- Disengage

def test_disengage_places_the_fighter_on_an_empty_space_of_its_zone_win_or_lose(bprd):
    g = mk(bprd, "leonardo")
    bigfoot, leonardo = pair(g, "bigfoot", "leonardo")
    wall(g)
    zone = [s for s in g.board.spaces if s != bigfoot.pos and g.board.share_zone(bigfoot.pos, s)
            and all(f.pos != s for f in g.fighters.values() if f.alive)]
    assert zone
    asked, bigfoot_start = [], bigfoot.pos
    g.controllers[0].queue = [lambda req: asked.append(req.options) or [zone[-1]]]
    res = g.attack(bigfoot, leonardo, give(g, 0, "Disengage"), g.players[1].hand[0])
    assert not res.attacker_won and bigfoot.pos == zone[-1]
    assert set(asked[0]) <= set(zone) and bigfoot_start not in asked[0]     # only OTHER empty spaces of the zone: staying is not allowed (Iván, 2026-11-03)


# ---------------------------------------------------------------- Momentous Shift

def test_momentous_shift_is_three_when_the_fighter_began_the_turn_where_it_stands(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    start_turn(g)
    assert g.attack(bigfoot, hellboy, give(g, 0, "Momentous Shift"), None).atk_value == 3


def test_momentous_shift_is_five_when_the_fighter_began_the_turn_elsewhere(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    start_turn(g)
    bigfoot.pos = next(s for s in sorted(g.board.adj[hellboy.pos]) if s != bigfoot.pos and all(f.pos != s for f in g.fighters.values() if f.alive))
    assert g.attack(bigfoot, hellboy, give(g, 0, "Momentous Shift"), None).atk_value == 5


def test_momentous_shift_as_a_defense_reads_the_turn_start_of_the_turn_being_played(bprd):
    g = mk(bprd, turn=1)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    start_turn(g)
    g.actions_left = 2
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack))
    assert g.attack(hellboy, bigfoot, attack, give(g, 0, "Momentous Shift")).def_value == 3
    g = mk(bprd, turn=1)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    start_turn(g)
    g.actions_left = 2
    bigfoot.pos = next(s for s in sorted(g.board.adj[hellboy.pos]) if s != bigfoot.pos and all(f.pos != s for f in g.fighters.values() if f.alive))
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack))
    assert g.attack(hellboy, bigfoot, attack, give(g, 0, "Momentous Shift")).def_value == 5


# ---------------------------------------------------------------- Skirmish

def test_skirmish_won_moves_the_fighter_the_owner_picks_up_to_two_spaces(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    start = hellboy.pos
    g.controllers[0].queue = [["hellboy"], pick(lambda s: True)]
    res = g.attack(bigfoot, hellboy, give(g, 0, "Skirmish"), None)
    assert res.attacker_won and hellboy.pos != start and g.board.distance(start, hellboy.pos) <= 2


def test_skirmish_can_move_bigfoot_himself(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    start = bigfoot.pos
    g.controllers[0].queue = [["bigfoot"], pick(lambda s: True)]
    g.attack(bigfoot, hellboy, give(g, 0, "Skirmish"), None)
    assert bigfoot.pos != start and g.board.distance(start, bigfoot.pos) <= 2


def test_skirmish_lost_moves_nobody(bprd):
    g = mk(bprd, "leonardo")
    bigfoot, leonardo = pair(g, "bigfoot", "leonardo")
    wall(g)
    where = (bigfoot.pos, leonardo.pos)
    g.controllers[0].queue = [["leonardo"], pick(lambda s: True)]
    res = g.attack(bigfoot, leonardo, give(g, 0, "Skirmish"), g.players[1].hand[0])
    assert not res.attacker_won and (bigfoot.pos, leonardo.pos) == where and len(g.controllers[0].queue) == 2


# ---------------------------------------------------------------- Hoax

def test_hoax_moves_the_fighter_up_to_five_spaces_through_opposing_fighters(bprd):
    g = mk(bprd, "leonardo")
    a, b, c = line_of_three(g.board)
    bigfoot, leonardo = g.fighters["bigfoot"], g.fighters["leonardo"]
    parked = [s for s in sorted(g.board.spaces, reverse=True) if s not in (a, b, c)]
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.fid not in ("bigfoot", "leonardo")], parked):
        f.pos = s
    bigfoot.pos, leonardo.pos = a, b
    wall(g)
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [c]]
    res = g.attack(bigfoot, leonardo, give(g, 0, "Hoax"), g.players[1].hand[0])
    assert not res.attacker_won and bigfoot.pos == c               # c lies behind Leonardo: reached through him
    assert seen[0].extra["steps"] == 5 and seen[0].extra["through"] is True and seen[0].extra["up_to"] is True


def test_hoax_may_stay_put(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    here = bigfoot.pos
    g.controllers[0].queue = [[]]
    g.attack(bigfoot, hellboy, give(g, 0, "Hoax"), None)
    assert bigfoot.pos == here


# ---------------------------------------------------------------- Regroup

def test_regroup_draws_two_when_won(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    res = g.attack(bigfoot, hellboy, give(g, 0, "Regroup"), None)
    assert res.attacker_won and len(g.players[0].hand) == 2             # the played card left, two came


def test_regroup_draws_one_when_not_won(bprd):
    g = mk(bprd, "leonardo")
    bigfoot, leonardo = pair(g, "bigfoot", "leonardo")
    wall(g)
    res = g.attack(bigfoot, leonardo, give(g, 0, "Regroup"), g.players[1].hand[0])
    assert not res.attacker_won and len(g.players[0].hand) == 1


# ---------------------------------------------------------------- the schemes

def test_crash_through_the_trees_moves_bigfoot_five_through_an_opposing_fighter(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    dest = empty_spaces(g, bigfoot.pos, 5)[0]
    assert g.board.distance(bigfoot.pos, dest) >= 3
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or ([dest] if dest in req.options else [])]
    g.actions_left = 2
    g.play_scheme(0, bigfoot, give(g, 0, "Crash Through the Trees"))
    assert bigfoot.pos == dest and g.actions_left == 1
    assert seen[0].extra["steps"] == 5 and seen[0].extra["through"] is True


def test_jackalope_horns_moves_the_jackalope_and_hits_one_adjacent_fighter_for_two(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    jackalope = g.fighters["jackalope"]
    next_to = set(g.board.adj[hellboy.pos])
    g.controllers[0].queue = [pick(lambda s: s in next_to), ["hellboy"]]
    before = hellboy.hp
    g.play_scheme(0, jackalope, give(g, 0, "Jackalope Horns"))
    assert jackalope.pos in next_to and hellboy.hp == before - 2


def test_jackalope_horns_with_nobody_adjacent_only_moves(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    jackalope = g.fighters["jackalope"]
    others = [f for f in g.fighters.values() if f.alive and f is not jackalope]
    g.controllers[0].queue = [pick(lambda s: all(g.board.distance(s, f.pos) > 1 for f in others))]
    before = hp(g, "hellboy", "lobster", "bigfoot")
    g.play_scheme(0, jackalope, give(g, 0, "Jackalope Horns"))
    assert hp(g, "hellboy", "lobster", "bigfoot") == before and g.controllers[0].queue == []


def test_jackalope_horns_may_be_aimed_at_the_owners_own_fighter(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    jackalope = g.fighters["jackalope"]
    put_adjacent(g, "jackalope", "bigfoot")
    g.controllers[0].queue = [[], ["bigfoot"]]
    g.play_scheme(0, jackalope, give(g, 0, "Jackalope Horns"))
    assert bigfoot.hp == bigfoot.max_hp - 2


# ---------------------------------------------------------------- the ability

def test_no_opposing_fighter_in_the_zone_and_the_owner_says_yes_draws_a_card_at_the_end_of_the_turn(bprd):
    g = mk(bprd)
    pair(g, "bigfoot", "hellboy")
    isolate(g)
    g.controllers[0].queue = [[True]]
    deck = len(g.players[0].deck)
    g.end_turn()
    assert len(g.players[0].hand) == 1 and len(g.players[0].deck) == deck - 1 and g.turn == 1


def test_an_owner_who_declines_draws_nothing(bprd):
    g = mk(bprd)
    pair(g, "bigfoot", "hellboy")
    isolate(g)
    g.controllers[0].queue = [[False]]
    g.end_turn()
    assert not g.players[0].hand


def test_an_opposing_hero_in_the_zone_switches_the_ability_off_and_nothing_is_asked(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    assert g.board.share_zone(bigfoot.pos, hellboy.pos)
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert not g.players[0].hand and g.controllers[0].queue == [[True]]


def test_an_opposing_sidekick_in_the_zone_switches_it_off_too(bprd):
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    isolate(g)
    g.fighters["lobster"].pos = next(s for s in sorted(g.board.spaces) if s != bigfoot.pos and g.board.share_zone(bigfoot.pos, s)
                                     and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert not g.players[0].hand


def test_an_own_fighter_in_the_zone_does_not_matter_and_the_jackalopes_zone_is_not_bigfoots(bprd):
    g = mk(bprd)
    pair(g, "bigfoot", "hellboy")
    isolate(g)
    put_adjacent(g, "jackalope", "bigfoot")
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert len(g.players[0].hand) == 1
    g = mk(bprd)
    bigfoot, hellboy = pair(g, "bigfoot", "hellboy")
    isolate(g)
    g.fighters["jackalope"].pos = max(g.board.spaces, key=lambda s: g.board.distance(s, bigfoot.pos))
    hellboy.pos = next(s for s in sorted(g.board.spaces) if g.board.share_zone(g.fighters["jackalope"].pos, s) and s != g.fighters["jackalope"].pos
                       and not g.board.share_zone(bigfoot.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert len(g.players[0].hand) == 1


def test_the_ability_is_not_used_at_the_end_of_the_rivals_turn(bprd):
    g = mk(bprd, turn=1)
    pair(g, "bigfoot", "hellboy")
    isolate(g)
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert not g.players[0].hand and g.controllers[0].queue == [[True]]


def test_the_ability_draws_before_the_hand_limit_is_enforced(bprd):
    g = mk(bprd)
    pair(g, "bigfoot", "hellboy")
    isolate(g)
    hand_filler(g, 0, g.hand_cap(0))
    assert len(g.players[0].hand) == g.hand_cap(0)
    g.controllers[0].queue = [[True]]
    g.controllers[0].discards = []
    g.end_turn()
    assert len(g.players[0].hand) == g.hand_cap(0)          # drew one, then discarded back to the limit


def test_the_bot_draws_when_it_can_and_not_from_an_empty_deck(bprd):
    g = mk(bprd)
    pair(g, "bigfoot", "hellboy")
    isolate(g)
    g.controllers[0] = MedusaAI(0)
    g.end_turn()
    assert len(g.players[0].hand) == 1
    g = mk(bprd)
    pair(g, "bigfoot", "hellboy")
    isolate(g)
    g.controllers[0] = MedusaAI(0)
    g.players[0].deck.clear()
    life = g.fighters["bigfoot"].hp
    g.end_turn()
    assert not g.players[0].hand and g.fighters["bigfoot"].hp == life         # no draw from an empty deck: no exhaustion damage either


def test_the_bot_does_not_draw_when_the_hand_is_already_at_the_limit(bprd):
    g = mk(bprd)
    pair(g, "bigfoot", "hellboy")
    isolate(g)
    g.controllers[0] = MedusaAI(0)
    hand_filler(g, 0, g.hand_cap(0))
    deck = len(g.players[0].deck)
    g.end_turn()
    assert len(g.players[0].hand) == g.hand_cap(0) and len(g.players[0].deck) == deck


# ---------------------------------------------------------------- the bot plays the Jackalope's scheme with the Jackalope

def test_the_ai_plays_jackalope_horns_with_the_jackalope_not_with_bigfoot(bprd):
    from sparring.ai_medusa import Model, scheme_fighter
    g = mk(bprd)
    pair(g, "bigfoot", "hellboy")
    horns = give(g, 0, "Jackalope Horns")
    assert scheme_fighter(g, 0, horns).fid == "jackalope"
    assert scheme_fighter(g, 0, give(g, 0, "Crash Through the Trees")).fid == "bigfoot"
    ai = MedusaAI(0)
    acts = [a for a in ai.scheme_acts(g, Model(g, 0)) if a.kind == "scheme"]
    assert {a.card.title: a.fid for a in acts} == {"Jackalope Horns": "jackalope", "Crash Through the Trees": "bigfoot"}


# ---------------------------------------------------------------- the free-draw rule belongs to the END of the turn

def test_hellboys_start_of_turn_draw_is_still_taken_with_a_full_hand(bprd):
    """OCCULT DETECTIVE (start of the turn) has no hand-limit reason to refuse: with 7 cards the bot still draws its 2."""
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: Asking()}, heroes=("hellboy", "medusa"), bot_player=0)
    g.turn, g.turn_no = 0, 2
    for p in g.players:
        p.hand.clear()
    hand_filler(g, 0, g.hand_cap(0))
    g.fighters["hellboy"].pos = g.start_spaces[1]            # the trigger needs Hellboy on the rival's starting space
    g.begin_turn()
    assert len(g.players[0].hand) == g.hand_cap(0) + 2


def test_bigfoots_end_of_turn_draw_is_refused_at_the_limit_and_taken_one_below(bprd):
    for filled, expect in ((6, 7), (7, 7)):
        g = mk(bprd)
        pair(g, "bigfoot", "hellboy")
        isolate(g)
        g.controllers[0] = MedusaAI(0)
        hand_filler(g, 0, filled)
        g.end_turn()
        assert len(g.players[0].hand) == expect, filled


# ---------------------------------------------------------------- zones: a space in several zones

def test_an_enemy_only_in_the_second_zone_of_bigfoots_space_switches_the_ability_off(bprd):
    """A space in two zones: an enemy that shares only the second one is in Bigfoot's zone all the same."""
    s = next(s for s in sorted(bprd.spaces) if len(bprd.zones(s)) > 1)
    first, second = sorted(bprd.zones(s))[:2]
    g = mk(bprd)
    isolate(g)
    only_second = [t for t in sorted(bprd.spaces) if t != s and second in bprd.zones(t) and first not in bprd.zones(t)
                   and all(f.pos != t for f in g.fighters.values() if f.alive)]
    assert only_second, "no space belongs to the second zone only"
    g.fighters["bigfoot"].pos = s
    g.fighters["hellboy"].pos = only_second[0]
    assert bprd.share_zone(s, only_second[0]) and not (bprd.zones(only_second[0]) & {first})
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert not g.players[0].hand and g.controllers[0].queue == [[True]]
    g = mk(bprd)                                                           # the control: nobody in either zone, the question comes
    isolate(g)
    g.fighters["bigfoot"].pos = s
    g.fighters["hellboy"].pos = next(t for t in sorted(bprd.spaces, reverse=True) if not bprd.share_zone(s, t))
    g.controllers[0].queue = [[True]]
    g.end_turn()
    assert len(g.players[0].hand) == 1


def test_disengage_with_no_other_empty_space_in_the_zone_does_nothing(bprd):
    mates = lambda sp: [t for t in sorted(bprd.spaces) if t != sp and bprd.share_zone(sp, t)]
    spot = min(sorted(bprd.spaces), key=lambda sp: len(mates(sp)))
    full = mates(spot)
    g = mk(bprd, "leonardo")
    bigfoot, leonardo = pair(g, "bigfoot", "leonardo")
    others = [f for f in g.fighters.values() if f.alive and f is not bigfoot]
    assert len(full) <= len(others), "the smallest zone of the board has more spaces than there are other fighters"
    bigfoot.pos = spot
    far = [t for t in sorted(bprd.spaces, reverse=True) if t != spot and t not in full]
    foe = next(f for f in others if f.owner == 1 and f.hero)
    next_to = next(t for t in full if bprd.adjacent(spot, t))
    foe.pos = next_to
    full.remove(next_to)
    for f in [f for f in others if f is not foe]:
        f.pos = full.pop(0) if full else far.pop(0)
    wall(g)
    attack = give(g, 0, "Disengage")
    g.controllers[0].queue = [lambda req: [spot]]
    g.attack(bigfoot, foe, attack, g.players[1].hand[0])
    assert bigfoot.pos == spot and len(g.controllers[0].queue) == 1          # nothing was asked, nothing moved
