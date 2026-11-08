"""She-Hulk on the engine, bot side (player 0 plays She-Hulk, the controllers answer): JUST THROW SOMETHING at the start of the turn,
every card with the numbers printed on it, the additional action of The Savage She-Hulk (op `spend_action`) and the mill of Lady
Justice (plugin `shehulk:mill`). The human side (panel, FakeTTS) is in tests/test_she_hulk_human.py and the full games in
tests/test_she_hulk_matrix.py."""
from __future__ import annotations

from conftest import card, give
from sparring.ai_effects import EffectAI
from sparring.effects.choose import ChoiceRequest
from sparring.effects.model import load_effects
from sparring.state import Game
from test_bigfoot_effects import Answers, start_turn, wall
from test_effects_combat import hand_filler, hp, pair


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """She-Hulk = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("she-hulk", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def zone_pair(g):
    """She-Hulk and Hellboy in the same zone but not next to each other (the other fighters far away)."""
    b = g.board
    for a in sorted(b.spaces):
        for c in sorted(b.spaces):
            if a != c and b.share_zone(a, c) and not b.adjacent(a, c):
                far = sorted((s for s in b.spaces if s not in (a, c) and not b.share_zone(a, s) and not b.share_zone(c, s)), reverse=True)
                g.fighters["shehulk"].pos, g.fighters["hellboy"].pos = a, c
                for f, s in zip([f for f in g.fighters.values() if f.alive and f.fid not in ("shehulk", "hellboy")], far):
                    f.pos = s
                return g.fighters["shehulk"], g.fighters["hellboy"]
    raise AssertionError("no such pair on the map")


def out_of_zone(g):
    """Hellboy and every other rival fighter out of She-Hulk's zone."""
    sh = g.fighters["shehulk"]
    far = sorted((s for s in g.board.spaces if not g.board.share_zone(sh.pos, s)), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.owner == 1], far):
        f.pos = s


def hellboys(g, kind, value):
    """The title of a Hellboy card of the rival's deck that attacks (`kind` "attack") or defends and has that printed value."""
    return next(c.title for c in g.players[1].deck
                if (c.can_attack if kind == "attack" else c.can_defend) and (c.value or 0) == value and c.usable_by("Hellboy") and not c.is_scheme)


# ---------------------------------------------------------------- the hero and the deck

def test_she_hulk_is_a_melee_hero_with_twenty_health_and_no_sidekick(bprd):
    g = mk(bprd)
    sh = g.fighters["shehulk"]
    assert (sh.name, sh.hp, sh.move, sh.ranged, sh.reach) == ("She-Hulk", 20, 2, False, 0)
    assert [f.fid for f in g.own(0)] == ["shehulk"]
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert "she-hulk" in g.fx.dsl_heroes


# ---------------------------------------------------------------- JUST THROW SOMETHING

def throw(g, card_id):
    g.controllers[0].queue = [[card_id]]
    start_turn(g)


def test_the_ability_discards_a_card_and_deals_its_boost_to_the_opposing_fighter_in_her_zone(bprd):
    g = mk(bprd)
    sh, h = zone_pair(g)
    c = give(g, 0, "Cease and Desist")                                   # BOOST 2
    before = h.hp
    throw(g, c.card_id)
    assert c in g.players[0].discard and c not in g.players[0].hand
    assert h.hp == before - 2 and sh.hp == 20


def test_declining_discards_nothing(bprd):
    g = mk(bprd)
    sh, h = zone_pair(g)
    c = give(g, 0, "Cease and Desist")
    g.controllers[0].queue = [[]]
    start_turn(g)
    assert c in g.players[0].hand and h.hp == h.max_hp


def test_no_opposing_fighter_in_her_zone_asks_nothing(bprd):
    g = mk(bprd)
    pair(g, "shehulk", "hellboy")
    out_of_zone(g)
    c = give(g, 0, "Cease and Desist")
    g.controllers[0].queue = []
    start_turn(g)
    assert c in g.players[0].hand and g.controllers[0].requests == []


def test_an_empty_hand_asks_nothing(bprd):
    g = mk(bprd)
    sh, h = zone_pair(g)
    g.controllers[0].requests.clear()
    start_turn(g)
    assert g.controllers[0].requests == [] and h.hp == h.max_hp


def test_the_ability_runs_only_on_her_own_turn(bprd):
    g = mk(bprd, turn=1)
    sh, h = zone_pair(g)
    c = give(g, 0, "Cease and Desist")
    g.controllers[0].requests.clear()
    start_turn(g)                                                          # the rival's turn starts
    assert g.controllers[0].requests == [] and c in g.players[0].hand


def test_a_scheme_has_a_boost_too_and_the_damage_is_effect_damage(bprd):
    g = mk(bprd)
    sh, h = zone_pair(g)
    c = give(g, 0, "Double Jeopardy")                                      # BOOST 2
    throw(g, c.card_id)
    assert h.hp == h.max_hp - 2


def test_the_damage_may_kill_the_opposing_hero(bprd):
    g = mk(bprd)
    sh, h = zone_pair(g)
    h.hp = 2
    c = give(g, 0, "The Savage She-Hulk")                                  # BOOST 3
    throw(g, c.card_id)
    assert g.winner == 0


def test_she_hulk_never_throws_at_herself_the_ability_needs_an_enemy_in_the_zone(bprd):
    fx = load_effects("she-hulk")
    trig, = fx.triggers
    assert trig["condition"] == {"test": "exists", "fighters": {"side": "enemy", "where": {"zone_of": "hero"}}}


# ---------------------------------------------------------------- the bot's decision to throw

def throw_request(g, me=0):
    hand = g.players[me].hand
    return ChoiceRequest("cards", me, [c.card_id for c in hand], 0, 1, None, "k", "throw a card",
                         {"zone": "hand", "purpose": "throw", "of": me, "targets": ["hellboy"]}, me)


def test_the_bot_throws_a_high_boost_card_it_does_not_need(bprd):
    g = mk(bprd)
    zone_pair(g)
    savage = give(g, 0, "The Savage She-Hulk")                              # BOOST 3
    keepers = [give(g, 0, "Omega-Level Threat"), give(g, 0, "Omega-Level Threat", 1), give(g, 0, "Cease and Desist")]
    ai = EffectAI(g)
    assert ai._card_to_throw(g, throw_request(g)) == [savage.card_id]
    assert all(c in g.players[0].hand for c in keepers)


def test_the_bot_keeps_every_card_when_none_is_worth_the_blow(bprd):
    g = mk(bprd)
    zone_pair(g)
    give(g, 0, "Nerve Cluster Strike")                                      # BOOST 1: one point of damage for a versatile card
    ai = EffectAI(g)
    assert ai._card_to_throw(g, throw_request(g)) == []


def test_the_bot_throws_the_card_that_finishes_the_rival(bprd):
    g = mk(bprd)
    sh, h = zone_pair(g)
    h.hp = 3
    give(g, 0, "Nerve Cluster Strike")
    finisher = give(g, 0, "The Savage She-Hulk")                            # BOOST 3 = exactly his health
    ai = EffectAI(g)
    assert ai._card_to_throw(g, throw_request(g)) == [finisher.card_id]


# ---------------------------------------------------------------- the schemes

def test_jennifer_walters_places_she_hulk_on_a_starting_space_draws_and_gives_the_action_back(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options)]]
    g.actions_left = 2
    jennifer = give(g, 0, "Jennifer Walters, Esq.")
    hand0, deck0 = len(g.players[0].hand), len(g.players[0].deck)
    g.play_scheme(0, sh, jennifer)
    assert seen and sh.pos == max(seen[0].options)
    assert g.actions_left == 2                                              # one spent, one gained
    assert len(g.players[0].hand) == hand0 - 1 + 1 and len(g.players[0].deck) == deck0 - 1        # the scheme left the hand, one card was drawn


def test_leap_toward_moves_four_through_opposing_fighters_and_gains_an_action_next_to_one(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    dest = next(s for s in sorted(g.board.adj[h.pos]) if s != sh.pos and all(f.pos != s for f in g.fighters.values() if f.alive)
                and g.board.distance(sh.pos, s) >= 2)
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or ([dest] if dest in req.options else [])]
    g.actions_left = 2
    g.play_scheme(0, sh, give(g, 0, "Leap Toward"))
    assert seen[0].extra["steps"] == 4 and seen[0].extra["through"] is True
    assert sh.pos == dest and g.actions_left == 2


def test_leap_toward_ending_away_from_every_rival_gains_nothing(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    out_of_zone(g)
    away = next(s for s in sorted(g.board.spaces) if 0 < g.board.distance(sh.pos, s) <= 4
                and all(g.board.distance(s, f.pos) > 1 for f in g.fighters.values() if f.alive and f.owner == 1))
    g.controllers[0].queue = [[away]]
    g.actions_left = 2
    g.play_scheme(0, sh, give(g, 0, "Leap Toward"))
    assert sh.pos == away and g.actions_left == 1


def test_double_jeopardy_draws_two_cards_and_heals_two(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    sh.hp = 10
    g.actions_left = 2
    g.play_scheme(0, sh, give(g, 0, "Double Jeopardy"))
    assert sh.hp == 12 and len(g.players[0].hand) == 2 and g.actions_left == 1
    sh.hp = 19
    g.play_scheme(0, sh, give(g, 0, "Double Jeopardy", 1))
    assert sh.hp == 20                                                       # never above her 20


# ---------------------------------------------------------------- the attacks

def test_omega_level_threat_makes_the_rival_discard_two_random_cards_when_it_deals_two_or_more(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    hand_filler(g, 1, 4, avoid=("B.P.R.D. Training",))
    res = g.attack(sh, h, give(g, 0, "Omega-Level Threat"), None)
    assert res.attacker_won and len(g.players[1].hand) == 2 and len(g.players[1].discard) == 2


def test_omega_level_threat_does_nothing_below_two_damage(bprd):
    g = mk(bprd, "luke-cage")                                               # Luke Cage takes 2 less: a 5 against his 2 lands 1
    sh, luke = pair(g, "shehulk", "luke")
    hand_filler(g, 1, 4, avoid=("Power Man",))
    res = g.attack(sh, luke, give(g, 0, "Omega-Level Threat"), give(g, 1, "Power Man"))
    assert res.damage == 1 and len(g.players[1].hand) == 4


def test_omega_level_threat_with_a_short_hand_discards_what_there_is(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    hand_filler(g, 1, 1)
    g.attack(sh, h, give(g, 0, "Omega-Level Threat"), None)
    assert g.players[1].hand == []


def test_sensational_shuffles_a_card_of_the_discard_pile_into_the_deck_when_it_wins(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    old = card(g, 0, "Green Energy")
    g.players[0].deck.remove(old) if old in g.players[0].deck else None
    g.players[0].discard.append(old)
    g.controllers[0].queue = [[old.card_id]]
    g.attack(sh, h, give(g, 0, "Sensational"), None)
    assert old in g.players[0].deck and old not in g.players[0].discard


def test_sensational_may_choose_nothing_and_does_nothing_when_it_loses(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    old = card(g, 0, "Green Energy")
    g.players[0].deck.remove(old) if old in g.players[0].deck else None
    g.players[0].discard.append(old)
    g.controllers[0].queue = [[]]
    g.attack(sh, h, give(g, 0, "Sensational"), None)
    assert old in g.players[0].discard
    h2 = mk(bprd)
    sh2, hh2 = pair(h2, "shehulk", "hellboy")
    old2 = card(h2, 0, "Green Energy")
    h2.players[0].deck.remove(old2) if old2 in h2.players[0].deck else None
    h2.players[0].discard.append(old2)
    h2.controllers[0].queue = [[old2.card_id]]
    h2.attack(sh2, hh2, give(h2, 0, "Sensational"), wall(h2))
    assert old2 in h2.players[0].discard and h2.controllers[0].queue == [[old2.card_id]]       # lost: nothing is asked


def test_the_savage_she_hulk_is_a_three_unless_an_additional_action_is_spent(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    g.actions_left = 2
    g.controllers[0].queue = [[False]]
    res = g.attack(sh, h, give(g, 0, "The Savage She-Hulk"), None)
    assert res.atk_value == 3 and g.actions_left == 1
    g.actions_left = 2
    g.controllers[0].queue = [[True]]
    res = g.attack(sh, h, give(g, 0, "The Savage She-Hulk", 1), None)
    assert res.atk_value == 9 and g.actions_left == 0                        # the attack's action and the additional one


def test_the_savage_she_hulk_asks_nothing_with_no_action_left_to_spend(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    g.actions_left = 1
    g.controllers[0].requests.clear()
    res = g.attack(sh, h, give(g, 0, "The Savage She-Hulk"), None)
    assert res.atk_value == 3 and g.actions_left == 0
    assert not [r for r in g.controllers[0].requests if r.kind == "optional"]


def test_the_bot_pays_the_action_for_a_blow_that_matters_and_not_for_one_that_does_not(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    ai = EffectAI(g)
    info = {"gain": 6, "mine": 3, "theirs": 0, "attacking": True, "target": "hellboy"}

    def ask(**over):
        return ai._action_for_value(g, ChoiceRequest("optional", 0, [True, False], 1, 1, None, "k", "do it?",
                                                     {"action_buys": {**info, **over}}, 0))
    assert ask() is True                                                      # 3 more damage and more: worth an action
    assert ask(theirs=20) is False                                            # a wall of 20: 9 does not get through either
    assert ask(attacking=False) is False


# ---------------------------------------------------------------- the versatile cards

def test_cease_and_desist_cancels_the_rivals_effects_and_is_four_when_attacking_and_one_defending(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    res = g.attack(sh, h, give(g, 0, "Cease and Desist"), None)
    assert res.atk_value == 4
    g2 = mk(bprd, turn=1)
    sh2, h2 = pair(g2, "shehulk", "hellboy")
    attack = give(g2, 1, next(c.title for c in g2.players[1].deck if c.can_attack and (c.value or 0) == 5))
    res2 = g2.attack(h2, sh2, attack, give(g2, 0, "Cease and Desist"))
    assert res2.def_value == 1


def test_cease_and_desist_cancels_the_rivals_card_effects(bprd):
    def hellboy_hits_with_right_hand_of_doom(defense):
        g = mk(bprd, turn=1)
        sh, h = pair(g, "shehulk", "hellboy")
        g.attack(h, sh, give(g, 1, "Right Hand Of Doom"), give(g, 0, defense))
        return [r.kind for r in g.controllers[1].requests]
    assert hellboy_hits_with_right_hand_of_doom("Nerve Cluster Strike")                  # its AFTER asks Hellboy's owner where to move
    assert hellboy_hits_with_right_hand_of_doom("Cease and Desist") == []                # cancelled before it could


def test_nerve_cluster_strike_freezes_the_opposing_fighter_only_when_she_is_next_to_it(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    g.attack(sh, h, give(g, 0, "Nerve Cluster Strike"), None)
    assert [(s["name"], s["fid"]) for s in g.fx.statuses] == [("cannot_leave_space", "hellboy")]
    g2 = mk(bprd, "bullseye", turn=1)                                          # a shooter attacks her from 3 spaces away: not adjacent
    sh2, b2 = g2.fighters["shehulk"], g2.fighters["bullseye"]
    sh2.pos = min(bprd.spaces)
    b2.pos = next(s for s in sorted(bprd.spaces) if bprd.spaces_apart(sh2.pos, s) == 3)
    g2.attack(b2, sh2, give(g2, 1, "World's Greatest Assassin"), give(g2, 0, "Nerve Cluster Strike"))
    assert g2.fx.statuses == []


def test_green_energy_hurts_every_fighter_next_to_her_when_it_wins(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    lobster = g.fighters["lobster"]
    spot = next(s for s in sorted(g.board.adj[sh.pos]) if s != h.pos and all(f.pos != s for f in g.fighters.values() if f.alive))
    lobster.pos = spot
    before = hp(g, "hellboy", "lobster", "shehulk")
    res = g.attack(sh, h, give(g, 0, "Green Energy"), None)
    assert res.attacker_won
    assert hp(g, "lobster")[0] == before[1] - 1
    assert h.hp == before[0] - res.damage - 1 and sh.hp == before[2]


def test_green_energy_does_nothing_when_it_loses(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    before = h.hp
    res = g.attack(sh, h, give(g, 0, "Green Energy"), wall(g))
    if not res.attacker_won:
        assert h.hp == before and sh.hp == 20


def legalese(g, sh, h, win, answers):
    g.controllers[0].queue = list(answers[0])
    g.controllers[1].queue = list(answers[1])
    return g.attack(sh, h, give(g, 0, "Legalese"), None if win else give(g, 1, hellboys(g, "defense", 2)))        # a tie: she did not win


def test_legalese_won_the_opponent_chooses_both_draw(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    legalese(g, sh, h, True, ([], [[0]]))
    assert len(g.players[0].hand) == 1 and len(g.players[1].hand) == 1


def test_legalese_won_the_opponent_may_choose_both_discard(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    mine = hand_filler(g, 0, 2)
    theirs = hand_filler(g, 1, 2)
    g.controllers[0].discards = [mine[0]]
    g.controllers[1].discards = [theirs[0]]
    legalese(g, sh, h, True, ([], [[1]]))
    assert len(g.players[0].hand) == 1 and len(g.players[1].hand) == 1       # both gave up a card (Legalese itself was played)
    assert mine[0] in g.players[0].discard and theirs[0] in g.players[1].discard


def test_legalese_lost_she_chooses(bprd):
    g = mk(bprd)
    sh, h = pair(g, "shehulk", "hellboy")
    hand_filler(g, 0, 1)
    hand_filler(g, 1, 1, avoid=(hellboys(g, "defense", 2),))
    res = legalese(g, sh, h, False, ([[0]], []))
    assert not res.attacker_won
    assert [r.kind for r in g.controllers[0].requests] == ["effect"]          # she was asked ...
    assert not [r for r in g.controllers[1].requests if r.kind == "effect"]   # ... not the rival
    assert len(g.players[0].hand) == 2                                         # the first option: both drew a card


# ---------------------------------------------------------------- the defenses

def test_the_defense_rests_draws_as_many_cards_as_the_combat_damage_taken(bprd):
    g = mk(bprd, turn=1)
    sh, h = pair(g, "shehulk", "hellboy")
    attack = give(g, 1, hellboys(g, "attack", 5))
    defense = give(g, 0, "The Defense Rests")
    before = len(g.players[0].hand)
    res = g.attack(h, sh, attack, defense)
    assert res.damage == 3 and len(g.players[0].hand) == before - 1 + 3


def test_the_defense_rests_draws_nothing_when_she_takes_no_damage(bprd):
    g = mk(bprd, turn=1)
    sh, h = pair(g, "shehulk", "hellboy")
    attack = give(g, 1, hellboys(g, "attack", 2))                                # value 2 against her 2
    defense = give(g, 0, "The Defense Rests")
    before = len(g.players[0].hand)
    res = g.attack(h, sh, attack, defense)
    assert res.damage == 0 and len(g.players[0].hand) == before - 1


def test_lady_justice_mills_the_top_card_of_the_rivals_deck_and_adds_twice_its_boost(bprd):
    g = mk(bprd, turn=1)
    sh, h = pair(g, "shehulk", "hellboy")
    attack = give(g, 1, hellboys(g, "attack", 5))
    top = g.players[1].deck[0]
    deck_before = len(g.players[1].deck)
    res = g.attack(h, sh, attack, give(g, 0, "Lady Justice"))
    assert top in g.players[1].discard and len(g.players[1].deck) == deck_before - 1
    assert res.def_value == 0 + 2 * top.boost


def test_lady_justice_with_an_empty_rival_deck_stays_at_zero(bprd):
    g = mk(bprd, turn=1)
    sh, h = pair(g, "shehulk", "hellboy")
    attack = give(g, 1, hellboys(g, "attack", 5))
    g.players[1].discard.extend(g.players[1].deck)
    g.players[1].deck.clear()
    res = g.attack(h, sh, attack, give(g, 0, "Lady Justice"))
    assert res.def_value == 0


def test_lady_justice_is_a_defense_of_value_zero_and_a_bot_prices_its_mill(bprd):
    from sparring.ai_medusa import MedusaAI
    g = mk(bprd)
    lady = card(g, 0, "Lady Justice")
    assert (lady.value, lady.boost, lady.type) == (0, 2, "defense")
    assert MedusaAI(0).rival_average_boost(g) > 0


def lady_vs_plain_defense(bprd, keep):
    """The defense the bot's She-Hulk picks (Lady Justice or a plain value-2 defense) when the rival's discard pile holds every
    card whose BOOST fails `keep`, so the average of what is left is public and fixed."""
    from sparring.ai_medusa import MedusaAI
    g = mk(bprd, turn=1)
    sh, h = pair(g, "shehulk", "hellboy")
    rival = g.players[1]
    rival.discard = [c for c in rival.full_set if not keep(c.boost)]
    rival.deck = [c for c in rival.full_set if keep(c.boost)]
    ai = MedusaAI(0)
    plain = next(c for c in g.players[0].full_set if c.title != "Lady Justice" and c.can_defend and c.value == 2 and c.usable_by("She-Hulk"))
    lady = give(g, 0, "Lady Justice")
    g.players[0].hand.append(plain)
    return ai.rival_average_boost(g), ai.choose_defense(g, h, sh), lady, plain


def test_the_bot_defends_with_lady_justice_when_the_rivals_remaining_boost_is_high(bprd):
    average, picked, lady, _ = lady_vs_plain_defense(bprd, lambda b: b >= 2)
    assert average >= 1.5
    assert picked is lady


def test_the_bot_keeps_lady_justice_when_the_rivals_remaining_boost_is_low(bprd):
    average, picked, lady, plain = lady_vs_plain_defense(bprd, lambda b: b <= 1)
    assert average < 1.5
    assert picked is not lady


def test_the_price_of_lady_justice_reads_only_the_public_composition_of_the_rivals_deck(bprd):
    from sparring.ai_medusa import MedusaAI
    g = mk(bprd, turn=1)
    rival = g.players[1]
    before = MedusaAI(0).rival_average_boost(g)
    rival.deck.reverse()                                                         # the real order of the deck changes nothing
    assert MedusaAI(0).rival_average_boost(g) == before


# ---------------------------------------------------------------- the op, the narration

def test_spend_action_takes_actions_and_counts_them_and_the_chat_says_so(bprd):
    from sparring.effects import narrate
    from sparring.effects.run import Ctx, EffectRun
    g = mk(bprd)
    g.actions_left = 2
    run = EffectRun([{"op": "spend_action", "amount": 1}], Ctx(owner=0, this_fid="shehulk"))
    before = narrate.snapshot(g)
    run.run(g, {0: g.controllers[0], 1: g.controllers[1]})
    assert g.actions_left == 1
    assert "accion adicional" in narrate.describe(g, before, run, title="x")
