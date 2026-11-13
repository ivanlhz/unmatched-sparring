"""George Washington on the engine, bot side (player 0 plays him, the controllers answer): ESPIONAGE (four ruse tokens, a token on the
attack, the rival's discard that takes it off, the token cleared when the combat ends), every card with the numbers printed on it and
the effects of the [RUSE] cards with and without the token. The human side (panel, FakeTTS) is in tests/test_george_washington_human.py,
the AI's two decisions in tests/test_george_washington_ai.py and the full games in tests/test_george_washington_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.effects.events import default_choosers
from sparring.effects.run import Ctx, EffectRun
from sparring.persist import apply_game, game_to_dict
from sparring.state import Game
from test_bigfoot_effects import Answers, start_turn, wall
from test_effects_combat import pair, put_adjacent

SPIES = ["spy1", "spy2", "spy3"]
RUSE_CARDS = ["Agent 711", "Circumvent", "Sabotage", "Allies Everywhere"]


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Washington = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("george-washington", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def ruse(g, player=0):
    return g.fx.counter_value(player, "ruse_tokens", 4), g.fx.counter_value(player, "ruse", 0)


def stock(g, n, player=1):
    """`n` cards of the rival's deck in their hand."""
    cards = [g.players[player].deck.pop(0) for _ in range(n)]
    g.players[player].hand.extend(cards)
    return cards


def plain_defense(g, player=1):
    """The best defense of the rival's deck that has no IMMEDIATELY (nothing that cancels the attack), in their hand."""
    best = max((c for c in g.players[player].deck if c.can_defend and "IMMEDIATELY" not in c.text), key=lambda c: (c.value or 0, c.boost))
    g.players[player].deck.remove(best)
    g.players[player].hand.append(best)
    return best


def open_pair(g, att_fid, tgt_fid):
    """Like `pair`, on a space with at least three neighbours so a fighter can come back next to the attacker."""
    a = next(s for s in sorted(g.board.spaces) if len(g.board.adj[s]) >= 3)
    b = sorted(g.board.adj[a])[0]
    far = sorted((s for s in g.board.spaces if s not in (a, b) and not g.board.share_zone(a, s)), reverse=True)
    g.fighters[att_fid].pos, g.fighters[tgt_fid].pos = a, b
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.fid not in (att_fid, tgt_fid)], far):
        f.pos = s
    return g.fighters[att_fid], g.fighters[tgt_fid]


def hit(bprd, title="Agent 711", foe="hellboy", answers=(), removal=None, def_card=None, hand=3, who="washington", nth=0):
    """Washington attacks `foe` with `title`. `answers`: his own answers to the questions of the combat (the first is the ruse token);
    `removal`: None = the rival is not asked, True / False = what they answer when they are."""
    g = mk(bprd, foe)
    att, tgt = pair(g, who, foe)
    card = give(g, 0, title, nth)
    stock(g, hand)
    g.controllers[0].queue = list(answers)
    if removal is not None:
        g.controllers[1].queue = [[removal]]
    res = g.attack(att, tgt, card, def_card)
    return g, res, tgt


# ---------------------------------------------------------------- the hero

def test_washington_is_a_melee_hero_with_three_spies(bprd):
    g = mk(bprd)
    w = g.fighters["washington"]
    assert (w.hp, w.move, w.ranged, w.reach, w.name) == (14, 2, False, 0, "George Washington")
    assert [f.fid for f in g.own(0)] == ["washington"] + SPIES
    assert all((f.hp, f.max_hp, f.move, f.ranged, f.name) == (1, 1, 2, False, "Spy") for f in map(g.fighters.get, SPIES))
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 18700 and deck[-1].card_id == 18729
    assert "george-washington" in g.fx.dsl_heroes


def test_the_deck_has_the_printed_bands_and_numbers(bprd):
    g = mk(bprd)
    seen = {}
    for c in g.players[0].full_set:
        seen.setdefault(c.title, (c.type, c.value, c.boost, c.fighter, 0))
        t = seen[c.title]
        seen[c.title] = t[:4] + (t[4] + 1,)
    assert seen == {
        "Lead Astray": ("attack", 5, 2, "George Washington", 2), "Agent 711": ("attack", 4, 3, "George Washington", 2),
        "Allies Everywhere": ("attack", 1, 3, "George Washington", 3), "Circumvent": ("attack", 3, 2, "any", 2),
        "Sabotage": ("attack", 3, 3, "any", 2), "Network Of Spies": ("versatile", 2, 2, "George Washington", 2),
        "Make A Stand": ("versatile", 3, 1, "any", 3), "Recruit To The Ring": ("versatile", 2, 1, "any", 2),
        "Misinformation": ("versatile", 4, 2, "any", 3), "Feint": ("versatile", 2, 3, "any", 3),
        "Undercover Agent": ("defense", 1, 2, "George Washington", 2), "Gather Information": ("scheme", None, 2, "George Washington", 2),
        "Sympathetic Stain": ("scheme", None, 3, "Spy", 2)}


def test_only_the_four_cards_with_a_ruse_triangle_carry_the_ruse_tag(bprd):
    g = mk(bprd)
    assert sorted({c.title for c in g.players[0].full_set if "ruse" in c.tags}) == sorted(RUSE_CARDS)


# ---------------------------------------------------------------- ESPIONAGE

def test_washington_starts_with_four_ruse_tokens_and_none_on_a_card(bprd):
    g = mk(bprd)
    assert ruse(g) == (4, 0)
    assert g.fx.counter_value(1, "ruse_tokens", 4) == 4          # the default of a hero that has none: only Washington is ever asked


def test_a_token_on_the_attack_spends_one_and_is_cleared_when_the_combat_ends(bprd):
    g, res, h = hit(bprd, "Agent 711", answers=[[True]], removal=False)
    assert ruse(g) == (3, 0)
    assert res.atk_value == 4 and h.hp == h.max_hp - 4 - 7


def test_the_token_is_on_the_card_while_the_combat_runs(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 2)
    seen = []
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [lambda req: seen.append(ruse(g)) or [False]]
    g.attack(w, h, give(g, 0, "Agent 711"), None)
    assert seen == [(3, 1)]                               # the rival is asked after the token went on
    assert ruse(g) == (3, 0)


def test_declining_the_token_keeps_the_supply_and_the_rival_is_not_asked(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    g.controllers[0].queue = [[False]]
    res = g.attack(w, h, give(g, 0, "Agent 711"), None)
    assert ruse(g) == (4, 0) and h.hp == h.max_hp - 4
    assert g.controllers[1].requests == []


@pytest.mark.parametrize("title", ["Lead Astray", "Network Of Spies", "Misinformation", "Make A Stand", "Feint", "Recruit To The Ring"])
def test_a_card_without_a_ruse_effect_is_never_offered_a_token(bprd, title):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    g.attack(w, h, give(g, 0, title), None)
    assert ruse(g) == (4, 0)
    assert all(r.extra.get("washington") != "use" for r in g.controllers[0].requests)
    assert g.controllers[1].requests == []


def test_the_rival_discards_a_random_card_to_remove_the_token_and_the_effect_is_lost(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    hand = stock(g, 3)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[True]]
    res = g.attack(w, h, give(g, 0, "Agent 711"), None)
    assert len(g.players[1].hand) == 2 and len(g.players[1].discard) == 1 and g.players[1].discard[0] in hand
    assert h.hp == h.max_hp - 4                           # the 7 damage was behind the token
    assert ruse(g) == (3, 0)                              # the token is gone: it does not return to the supply


def test_the_rival_with_an_empty_hand_is_not_asked(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    g.controllers[0].queue = [[True]]
    g.attack(w, h, give(g, 0, "Agent 711"), None)
    assert g.controllers[1].requests == [] and h.hp == h.max_hp - 4 - 7


def test_the_token_stays_when_the_rival_declines_to_discard(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    g.attack(w, h, give(g, 0, "Agent 711"), None)
    assert len(g.players[1].hand) == 3 and h.hp == h.max_hp - 4 - 7


def test_with_no_token_left_nothing_is_asked(bprd):
    g = mk(bprd)
    g.fx.set_counter(0, "ruse_tokens", 0)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    g.attack(w, h, give(g, 0, "Agent 711"), None)
    assert g.controllers[0].requests == [] and h.hp == h.max_hp - 4


def test_a_spy_may_attack_with_a_ruse_token_too(bprd):
    g = mk(bprd)
    spy, h = pair(g, "spy1", "hellboy")
    stock(g, 3)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    g.attack(spy, h, give(g, 0, "Sabotage"), None)
    assert ruse(g) == (3, 0) and len(g.players[1].discard) == 2 and len(g.players[1].hand) == 1       # Sabotage: 2 random cards


def test_the_rival_attacking_never_triggers_the_ability(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "washington", "hellboy")
    attack = next(c for c in g.players[1].full_set if c.can_attack and c.usable_by("Hellboy"))
    g.players[1].hand.append(attack)
    stock(g, 2, player=0)
    g.attack(h, w, attack, None)
    assert ruse(g) == (4, 0) and g.controllers[0].requests == [] and g.controllers[1].requests == []


def test_the_counters_survive_a_save_and_a_clone(bprd):
    g = mk(bprd)
    g.fx.set_counter(0, "ruse_tokens", 2)
    g.fx.set_counter(0, "ruse", 1)
    d = game_to_dict(g)
    g2 = mk(bprd)
    apply_game(g2, d)
    assert ruse(g2) == (2, 1) and ruse(g2.clone()) == (2, 1)


# ---------------------------------------------------------------- the four ruse cards

def test_agent_711_deals_7_more_to_the_opposing_fighter_only_with_the_token_and_a_win(bprd):
    g, res, h = hit(bprd, "Agent 711", answers=[[True]], removal=False)
    assert res.attacker_won and h.hp == h.max_hp - 4 - 7
    g, res, h = hit(bprd, "Agent 711", answers=[[False]])
    assert h.hp == h.max_hp - 4
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    res = g.attack(w, h, give(g, 0, "Agent 711"), wall(g), values=(0, 2))      # a 4 against 3 + 2: lost
    assert not res.attacker_won and h.hp == h.max_hp and ruse(g) == (3, 0)


def test_circumvent_ignores_the_value_of_the_rival_card_only_with_the_token(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 2)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    good = plain_defense(g)
    res = g.attack(w, h, give(g, 0, "Circumvent"), good)
    assert res.def_value == 0 and res.damage == 3 and good in g.players[1].discard
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    good = plain_defense(g)
    g.controllers[0].queue = [[False]]
    res = g.attack(w, h, give(g, 0, "Circumvent"), good)
    assert res.def_value == good.value


def test_sabotage_discards_two_random_cards_with_the_token_and_a_win(bprd):
    g, res, h = hit(bprd, "Sabotage", answers=[[True]], removal=False, hand=4)
    assert res.attacker_won and len(g.players[1].hand) == 2 and len(g.players[1].discard) == 2
    g, res, h = hit(bprd, "Sabotage", answers=[[False]], hand=4)
    assert len(g.players[1].hand) == 4 and g.players[1].discard == []


def test_sabotage_does_nothing_when_the_combat_is_lost(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    best = wall(g)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    res = g.attack(w, h, give(g, 0, "Sabotage"), best, values=(0, 2))
    assert not res.attacker_won and len(g.players[1].hand) == 3        # the defense card left it, nobody else


def test_allies_everywhere_gains_an_action_and_with_the_token_heals_washington_three(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    w.hp = 8
    g.actions_left = 2
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    g.attack(w, h, give(g, 0, "Allies Everywhere"), None)
    assert g.actions_left == 2 and w.hp == 11                          # 2 - 1 spent + 1 gained
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    w.hp = 8
    g.actions_left = 2
    g.controllers[0].queue = [[False]]
    g.attack(w, h, give(g, 0, "Allies Everywhere"), None)
    assert g.actions_left == 2 and w.hp == 8


def test_allies_everywhere_never_heals_above_the_maximum(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    w.hp = 13
    g.controllers[0].queue = [[True]]
    g.attack(w, h, give(g, 0, "Allies Everywhere"), None)
    assert w.hp == 14


def test_only_washington_plays_allies_everywhere_a_spy_plays_the_any_cards(bprd):
    g = mk(bprd)
    assert not give(g, 0, "Allies Everywhere").usable_by("Spy")
    assert all(give(g, 0, t).usable_by("Spy") for t in ("Sabotage", "Circumvent", "Misinformation", "Feint"))


def test_the_ruse_effect_is_lost_when_feint_cancels_the_card(bprd):
    g = mk(bprd, turn=0)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    cancel = next((c for c in g.players[1].full_set if c.can_defend and "cancel" in c.text.lower() and "IMMEDIATELY" in c.text), None)
    assert cancel is not None
    g.players[1].deck.remove(cancel) if cancel in g.players[1].deck else None
    g.players[1].hand.append(cancel)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    res = g.attack(w, h, give(g, 0, "Agent 711"), cancel)
    assert res.cancelled == {"atk"} and h.hp == h.max_hp - res.damage and ruse(g) == (3, 0)      # no 7: the token was spent, the effect cancelled


# ---------------------------------------------------------------- the other cards

def test_lead_astray_moves_a_fighter_of_the_combat_up_to_two_spaces_win_or_lose(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    where = []
    g.controllers[0].queue = [lambda req: where.append(req) or [h.fid], lambda req: where.append(req) or [req.options[-1]]]
    start = h.pos
    g.attack(w, h, give(g, 0, "Lead Astray"), plain_defense(g), values=(0, 4))      # lost (5 against 3 + 4): it still moves
    assert [r.kind for r in where] == ["fighter", "space"] and h.pos != start
    assert g.board.distance(start, h.pos) <= 2


def test_misinformation_gives_back_a_token_when_it_wins_and_never_above_four(bprd):
    g = mk(bprd)
    g.fx.set_counter(0, "ruse_tokens", 2)
    w, h = pair(g, "washington", "hellboy")
    g.attack(w, h, give(g, 0, "Misinformation"), None)
    assert ruse(g) == (3, 0)
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    g.attack(w, h, give(g, 0, "Misinformation"), None)
    assert ruse(g) == (4, 0)
    g = mk(bprd)
    g.fx.set_counter(0, "ruse_tokens", 1)
    w, h = pair(g, "washington", "hellboy")
    g.attack(w, h, give(g, 0, "Misinformation"), wall(g), values=(0, 3))        # lost (4 against 3 + 3): nothing comes back
    assert ruse(g) == (1, 0)


def test_misinformation_in_defense_gives_a_token_back_when_the_defender_wins(bprd):
    g = mk(bprd, turn=1)
    g.fx.set_counter(0, "ruse_tokens", 1)
    w, h = pair(g, "washington", "hellboy")
    attack = next(c for c in g.players[1].full_set if c.can_attack and (c.value or 0) == 2 and c.usable_by("Hellboy"))
    g.players[1].hand.append(attack)
    g.actions_left = 2
    g.attack(h, w, attack, give(g, 0, "Misinformation"))
    assert ruse(g) == (2, 0)


def test_make_a_stand_is_a_5_only_for_a_fighter_that_started_the_turn_where_it_stands(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    start_turn(g)
    res = g.attack(w, h, give(g, 0, "Make A Stand"), None)
    assert res.atk_value == 5
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    start_turn(g)
    w.pos = next(s for s in sorted(g.board.adj[w.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.fighters["hellboy"].pos = next(s for s in sorted(g.board.adj[w.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    res = g.attack(w, h, give(g, 0, "Make A Stand"), None)
    assert res.atk_value == 3


def test_make_a_stand_defending_on_the_rivals_turn_is_a_5_when_not_moved(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "washington", "hellboy")
    start_turn(g)
    attack = next(c for c in g.players[1].full_set if c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    g.players[1].hand.append(attack)
    res = g.attack(h, w, attack, give(g, 0, "Make A Stand"))
    assert res.def_value == 5 and w.hp == w.max_hp


def test_feint_cancels_every_effect_on_the_rival_card(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "washington", "hellboy")
    attack = next(c for c in g.players[1].full_set if c.can_attack and "AFTER" in c.text and c.usable_by("Hellboy"))
    g.players[1].hand.append(attack)
    flow = g.begin_attack(h, w, attack, give(g, 0, "Feint"))
    flow.run()
    assert "atk" in flow.result.cancelled


def test_recruit_to_the_ring_returns_a_defeated_spy_next_to_washington_or_anywhere_if_it_won(bprd):
    for fight, anywhere in (("lost", False), ("won", True)):
        g = mk(bprd)
        w, h = open_pair(g, "washington", "hellboy")
        g.defeat(g.fighters["spy2"])
        asked = []
        g.controllers[0].queue = [lambda req: asked.append(req) or [req.options[-1]]]
        g.attack(w, h, give(g, 0, "Recruit To The Ring"), plain_defense(g) if fight == "lost" else None, values=(0, 2) if fight == "lost" else (0, 0))
        spy = g.fighters["spy2"]
        assert spy.alive and spy.hp == 1 and asked
        if anywhere:
            assert set(g.board.adj[w.pos]) - {h.pos} < set(asked[0].options) and spy.pos == max(asked[0].options)
        else:
            assert spy.pos in g.board.adj[w.pos] and set(asked[0].options) <= set(g.board.adj[w.pos])


def test_recruit_to_the_ring_with_no_defeated_spy_just_attacks(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    res = g.attack(w, h, give(g, 0, "Recruit To The Ring"), None)
    assert res.atk_value == 2 and all(g.fighters[s].alive for s in SPIES)


def test_network_of_spies_adds_one_per_other_friendly_fighter_in_washingtons_zone(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    away = g.attack(w, h, give(g, 0, "Network Of Spies"), None)
    assert away.atk_value == 2
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    put_adjacent(g, "spy1", "washington")
    put_adjacent(g, "spy2", "washington")
    res = g.attack(w, h, give(g, 0, "Network Of Spies"), None)
    assert res.atk_value == 2 + 2


def test_network_of_spies_counts_the_fighters_of_the_zone_of_washington_not_of_the_spy(bprd):
    g = mk(bprd)
    spy, h = pair(g, "spy1", "hellboy")
    # Network Of Spies is Washington's card: a Spy cannot play it
    card = give(g, 0, "Network Of Spies")
    assert not card.usable_by("Spy")


# ---------------------------------------------------------------- Undercover Agent

def defended_by_undercover(bprd, hp=14):
    g = mk(bprd, turn=1)
    w, h = pair(g, "washington", "hellboy")
    put_adjacent(g, "spy1", "washington")
    g.actions_left = 2
    w.hp = hp
    return g, w, h, g.fighters["spy1"]


def test_undercover_agent_swaps_washington_with_an_adjacent_spy_who_is_now_the_defender(bprd):
    g, w, h, spy = defended_by_undercover(bprd)
    g.controllers[0].queue = [[True], lambda req: [req.options[0]]]
    where = spy.pos
    attack = next(c for c in g.players[1].full_set if c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    g.players[1].hand.append(attack)
    flow = g.begin_attack(h, w, attack, give(g, 0, "Undercover Agent"))
    flow.run()
    assert w.pos == where and flow.tgt is spy and not spy.alive and w.hp == w.max_hp


def test_undercover_agent_may_be_declined(bprd):
    g, w, h, spy = defended_by_undercover(bprd)
    g.controllers[0].queue = [[False]]
    attack = next(c for c in g.players[1].full_set if c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    g.players[1].hand.append(attack)
    flow = g.begin_attack(h, w, attack, give(g, 0, "Undercover Agent"))
    flow.run()
    assert flow.tgt is w and w.hp == w.max_hp - 3 and spy.alive


def test_undercover_agent_with_no_spy_next_to_him_just_defends(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "washington", "hellboy")
    g.actions_left = 2
    attack = next(c for c in g.players[1].full_set if c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    g.players[1].hand.append(attack)
    res = g.attack(h, w, attack, give(g, 0, "Undercover Agent"))
    assert w.hp == w.max_hp - 3 and res.def_value == 1 and g.controllers[0].requests == []


# ---------------------------------------------------------------- the schemes

def test_gather_information_draws_three_and_moves_every_fighter_up_to_three_through_the_rivals(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [req.options[-1]] for _ in range(5)]
    g.actions_left = 2
    g.play_scheme(0, w, give(g, 0, "Gather Information"))
    assert len(g.players[0].hand) == 3 and g.actions_left == 1
    assert seen and all(r.extra["steps"] == 3 and r.extra["through"] is True for r in seen) and len(seen) == len(g.own(0))


def sympathetic(g, spy_adjacent_to_foe: bool):
    """Washington's Spy plays Sympathetic Stain with the rival's hand in sight."""
    w, h = pair(g, "washington", "hellboy")
    if spy_adjacent_to_foe:
        put_adjacent(g, "spy1", "hellboy")
    hand = stock(g, 3)
    g.fx.set_counter(0, "ruse_tokens", 2)
    g.actions_left = 2
    g.controllers[0].queue = [lambda req: [req.options[0]]]
    g.play_scheme(0, g.fighters["spy1"], give(g, 0, "Sympathetic Stain"))
    return g, hand


def test_sympathetic_stain_with_a_spy_next_to_a_rival_discards_a_card_of_their_hand_and_regains_a_token(bprd):
    g, hand = sympathetic(mk(bprd), True)
    assert len(g.players[1].hand) == 2 and len(g.players[1].discard) == 1 and ruse(g) == (3, 0)
    assert g.players[0].known.cards(g.players[1]) is not None


def test_sympathetic_stain_without_a_spy_next_to_a_rival_only_looks(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    foes = [f.pos for f in g.own(1)]
    for spy in SPIES:
        g.fighters[spy].pos = None
        g.fighters[spy].pos = next(s for s in sorted(g.board.spaces, reverse=True) if all(f.pos != s for f in g.fighters.values() if f.alive)
                                   and not any(s in g.board.adj[p] for p in foes))
    stock(g, 3)
    g.fx.set_counter(0, "ruse_tokens", 2)
    g.actions_left = 2
    g.play_scheme(0, g.fighters["spy1"], give(g, 0, "Sympathetic Stain"))
    assert len(g.players[1].hand) == 3 and ruse(g) == (2, 0)
    assert len(g.players[0].known.cards(g.players[1])) == 3          # the look is always made


def test_sympathetic_stain_is_played_by_a_spy_and_not_by_washington(bprd):
    g = mk(bprd)
    card = give(g, 0, "Sympathetic Stain")
    assert card.usable_by("Spy") and not card.usable_by("George Washington")


# ---------------------------------------------------------------- the engine keeps working

def test_the_search_clone_keeps_the_tokens(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 3)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    g.attack(w, h, give(g, 0, "Agent 711"), None)
    c = g.clone()
    assert ruse(c) == (3, 0)
    c.fx.set_counter(0, "ruse_tokens", 0)
    assert ruse(g) == (3, 0)


def test_the_ability_trigger_run_label_names_the_question(bprd):
    g = mk(bprd)
    w, h = pair(g, "washington", "hellboy")
    stock(g, 2)
    g.controllers[0].queue = [[True]]
    g.controllers[1].queue = [[False]]
    g.attack(w, h, give(g, 0, "Agent 711"), None)
    assert [r.key.split("/")[0] for r in g.controllers[0].requests] == ["espionage"]
    assert [r.key.split("/")[0] for r in g.controllers[1].requests] == ["espionage_remove"]
