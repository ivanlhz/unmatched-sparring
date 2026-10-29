"""C3: events, ability triggers and the ONGOING slot, on real cards of data/heroes/*.json.

Every test sets `fx.dsl_heroes` only for the hero under test; with it empty the engine is untouched (goldens)."""
import json

import pytest

from sparring import persist
from sparring.effects import events, ongoing
from sparring.effects.choose import ScriptedChooser
from sparring.effects.ops_core import OPS
from sparring.effects.run import Ctx, EffectRun
from sparring.effects.select import amount, condition
from sparring.state import Game

from conftest import Scripted, card, give, place

ABE, BABA, LIZ = "abe-sapien", "baba-yaga", "liz-sherman"


def mk(bprd, heroes, dsl, seed=1):
    """Player 0 plays heroes[0], player 1 heroes[1]; it is player 0's turn, begun BEFORE the flag is raised."""
    g = Game.new(bprd, seed, controllers={0: Scripted(), 1: Scripted()}, heroes=heroes)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    g.fx.dsl_heroes |= set(dsl)
    return g


def run_ops(g, ops, owner=0, this="abe", chooser=None, **ctx):
    run = EffectRun(ops, Ctx(owner=owner, this_fid=this, **ctx))
    return run, run.run(g, chooser or ScriptedChooser())


def pass_turns(g, n):
    """End the current turn and begin the next one, n times."""
    for _ in range(n):
        g.end_turn()
        g.begin_turn()


@pytest.fixture
def abe_baba(bprd):
    return mk(bprd, (ABE, BABA), {ABE, BABA})


@pytest.fixture
def liz_baba(bprd):
    return mk(bprd, (LIZ, BABA), {LIZ, BABA})


def deck_with_bottom(g, player, burning: bool):
    """Puts a card of the wanted kind at the bottom of the deck and returns it."""
    p = g.players[player]
    pick = next(c for c in reversed(p.deck) if ("burning" in c.tags) == burning)
    p.deck.remove(pick)
    p.deck.append(pick)
    return pick


# ---------------------------------------------------------------- one ONGOING per player

def test_playing_a_second_pact_replaces_the_first_and_the_old_one_is_discarded(abe_baba):
    g = abe_baba
    peace, freedom = give(g, 1, "Pact Of Peace"), give(g, 1, "Pact Of Freedom")
    baba = g.fighters["baba"]
    ongoing.resolve_scheme(g, 1, baba, peace, ScriptedChooser())
    assert g.fx.ongoing_card_id(1) == peace.card_id and peace not in g.players[1].discard
    ongoing.resolve_scheme(g, 1, baba, freedom, ScriptedChooser())
    assert g.fx.ongoing_card_id(1) == freedom.card_id
    assert peace in g.players[1].discard and freedom not in g.players[1].discard + g.players[1].hand


def test_each_player_keeps_their_own_ongoing_counterhex_next_to_a_pact(abe_baba):
    g = abe_baba
    hex1, hex2 = give(g, 0, "Counterhex Shield", 0), give(g, 0, "Counterhex Shield", 1)
    pact = give(g, 1, "Pact Of Peace")
    ongoing.resolve_scheme(g, 0, g.fighters["abe"], hex1, ScriptedChooser())
    ongoing.resolve_scheme(g, 1, g.fighters["baba"], pact, ScriptedChooser())
    assert g.fx.ongoing_card_id(0) == hex1.card_id and g.fx.ongoing_card_id(1) == pact.card_id
    ongoing.resolve_scheme(g, 0, g.fighters["abe"], hex2, ScriptedChooser())      # the rival's Pact is untouched
    assert g.fx.ongoing_card_id(0) == hex2.card_id and g.fx.ongoing_card_id(1) == pact.card_id
    assert hex1 in g.players[0].discard and pact not in g.players[1].discard


def test_two_fight_or_flight_are_one_bonus_and_a_pact_does_not_touch_it(liz_baba):
    g = liz_baba
    f1, f2 = give(g, 0, "Fight Or Flight", 0), give(g, 0, "Fight Or Flight", 1)
    ongoing.resolve_scheme(g, 0, g.fighters["liz"], f1, ScriptedChooser())
    ongoing.resolve_scheme(g, 1, g.fighters["baba"], give(g, 1, "Pact Of Peace"), ScriptedChooser())
    assert g.combat_bonus_parts(0) == [(1, "Fight Or Flight")]
    ongoing.resolve_scheme(g, 0, g.fighters["liz"], f2, ScriptedChooser())
    assert g.combat_bonus_parts(0) == [(1, "Fight Or Flight")] and g.combat_bonus_total(0) == 1
    assert f1 in g.players[0].discard and g.combat_bonus_parts(1) == []


def test_the_new_scheme_replaces_before_its_own_ops_run(abe_baba):
    """Pact Of Peace's "gain 1 action" must not be blocked by the Pact Of Time it replaces."""
    g = abe_baba
    g.turn = 1
    ongoing.enter_play(g, 1, give(g, 1, "Pact Of Time"))
    assert not g.fx.can_gain_actions(1)
    g.actions_left = 2
    ongoing.resolve_scheme(g, 1, g.fighters["baba"], give(g, 1, "Pact Of Peace"), ScriptedChooser())
    assert g.actions_left == 3


def test_in_play_card_can_be_discarded_by_an_effect(abe_baba):
    g = abe_baba
    pact = give(g, 1, "Pact Of Time")
    ongoing.enter_play(g, 1, pact)
    run_ops(g, [{"op": "discard", "cards": {"zone": "in_play", "player": "owner"}}], owner=1, this="baba")
    assert g.fx.ongoing_card_id(1) is None and pact in g.players[1].discard
    assert not list(ongoing.active_modifiers(g))


# ---------------------------------------------------------------- the view and the save format

def test_combat_bonus_is_a_view_over_the_slot_and_saves_like_before(liz_baba):
    g = liz_baba
    g.add_combat_bonus(0, 1, "Fight Or Flight")
    assert g.fx.ongoing[0] == {"card_id": None, "bonus": 1, "label": "Fight Or Flight"}
    d = persist.game_to_dict(g)
    assert d["combat_bonus"] == [[[1, "Fight Or Flight"]], []] and "ongoing" not in d.get("fx", {})
    g.fx.dsl_heroes.clear()
    assert "fx" not in persist.game_to_dict(g)         # a game without effects saves byte-identical to before


def test_a_dsl_ongoing_saves_in_fx_and_reloads_with_its_bonus(liz_baba):
    g = liz_baba
    fof = give(g, 0, "Fight Or Flight")
    ongoing.enter_play(g, 0, fof)
    d = json.loads(json.dumps(persist.game_to_dict(g)))
    assert "combat_bonus" not in d and d["fx"]["ongoing"] == [{"card_id": fof.card_id}, None]
    fresh = g.clone()
    fresh.fx.take_ongoing(0)
    persist.apply_game(fresh, d)
    assert fresh.combat_bonus_parts(0) == [(1, "Fight Or Flight")] and fresh.combat_bonus == [[(1, "Fight Or Flight")], []]
    fresh.begin_turn()
    assert fresh.combat_bonus_parts(0) == []                                  # reloaded game is attached: it still expires


def test_a_dsl_ongoing_replaced_by_a_legacy_one_goes_to_the_discard_pile(liz_baba):
    g = liz_baba
    fof = give(g, 0, "Fight Or Flight")
    ongoing.enter_play(g, 0, fof)
    assert g.add_combat_bonus(0, 3, "Otro") == "Fight Or Flight"
    assert fof in g.players[0].discard and g.combat_bonus_parts(0) == [(3, "Otro")]


# ---------------------------------------------------------------- Pact of Peace / Secrecy / Time

def test_pact_of_peace_hurts_each_hero_that_attacked_at_the_end_of_every_turn(abe_baba):
    g = abe_baba
    ongoing.enter_play(g, 1, give(g, 1, "Pact Of Peace"))
    abe, koschei = g.fighters["abe"], g.fighters["koschei"]
    place(g, abe=sorted(g.board.adj[koschei.pos])[0])
    atk = next(c for c in g.players[0].full_set if c.can_attack and c.usable_by(abe.name) and (c.value or 0) > 0)
    g.players[0].hand.append(atk)
    hp, baba_hp = abe.hp, g.fighters["baba"].hp
    g.attack(abe, koschei, atk)
    assert g.fx.attacked == ["abe"]
    g.end_turn()
    assert abe.hp == hp - 1 and g.fighters["baba"].hp == baba_hp
    g.begin_turn()                                     # the other player's turn: nobody attacked
    g.end_turn()
    assert abe.hp == hp - 1


def test_pact_of_secrecy_cuts_the_hand_to_three_at_end_turn_and_not_after_it_leaves(abe_baba):
    g = abe_baba
    secrecy = give(g, 1, "Pact Of Secrecy")
    ongoing.enter_play(g, 1, secrecy)
    assert g.fx.hand_limit(0, 7) == 3
    hand = g.players[0].hand
    while len(hand) < 6:
        give(g, 0, next(c.title for c in g.players[0].deck))
    g.end_turn()
    assert len(g.players[0].hand) == 3 and len(g.players[0].discard) == 3
    g.begin_turn()
    ongoing.leave_play(g, 1)
    assert g.fx.hand_limit(1, 7) == 7


def test_pact_of_time_blocks_gain_action_for_everybody_until_it_leaves(abe_baba):
    g = abe_baba
    pact = give(g, 1, "Pact Of Time")
    ongoing.enter_play(g, 1, pact)
    g.actions_left = 2
    run_ops(g, [{"op": "gain_action", "amount": 1}])
    assert g.actions_left == 2
    ongoing.leave_play(g, 1)
    run_ops(g, [{"op": "gain_action", "amount": 1}])
    assert g.actions_left == 3


def test_the_pact_rules_are_read_from_the_card_in_play(abe_baba):
    g = abe_baba
    assert not ongoing.rules(g, "effect_damage_bonus")
    ongoing.enter_play(g, 1, give(g, 1, "Pact Of Mortality"))
    assert ongoing.rule_total(g, "effect_damage_bonus") == 1
    ongoing.enter_play(g, 1, give(g, 1, "Pact Of Freedom"))
    assert ongoing.rule_total(g, "effect_damage_bonus") == 0
    assert [m["rule"] for m in ongoing.rules(g, "no_attack_as_first_action")] == ["no_attack_as_first_action"]


# ---------------------------------------------------------------- Pact expiry: 2+ combat damage to Baba in one combat

@pytest.mark.parametrize("target,n,source,expires", [
    ("baba", 3, "effect", False),            # effect damage never counts
    ("baba", 5, "exhaustion", False),
    ("baba", 1, "combat", False),            # one point
    ("koschei", 4, "combat", False),         # redirected to Koschei: Baba did not take it
    ("abe", 4, "combat", False),
    ("baba", 2, "combat", True),
    ("baba", 3, "combat", True),
])
def test_pact_expiry_needs_two_combat_damage_to_baba(abe_baba, target, n, source, expires):
    g = abe_baba
    pact = give(g, 1, "Pact Of Peace")
    ongoing.enter_play(g, 1, pact)
    g.damage(g.fighters[target], n, source)
    assert (g.fx.ongoing_card_id(1) is None) is expires
    assert (pact in g.players[1].discard) is expires


def test_two_separate_combats_of_one_damage_do_not_add_up(abe_baba):
    g = abe_baba
    ongoing.enter_play(g, 1, give(g, 1, "Pact Of Time"))
    g.damage(g.fighters["baba"], 1, "combat")
    g.damage(g.fighters["baba"], 1, "combat")
    assert g.fx.ongoing_card_id(1) is not None


def test_a_real_combat_that_hurts_baba_for_two_ends_the_pact(abe_baba):
    g = abe_baba
    pact = give(g, 1, "Pact Of Secrecy")
    ongoing.enter_play(g, 1, pact)
    abe, baba = g.fighters["abe"], g.fighters["baba"]
    place(g, abe=sorted(g.board.adj[baba.pos])[0])
    atk = next(c for c in g.players[0].full_set if c.can_attack and c.usable_by(abe.name) and (c.value or 0) >= 2)
    g.players[0].hand.append(atk)
    g.attack(abe, baba, atk)                                   # Scripted defends with nothing
    assert g.fx.ongoing_card_id(1) is None and pact in g.players[1].discard


# ---------------------------------------------------------------- Wildfire

def test_wildfire_returns_a_burning_card_discarded_from_hand_and_it_is_public(liz_baba):
    g = liz_baba
    fireball, dash = give(g, 0, "Fireball"), give(g, 0, "Evade")
    n = len(g.players[0].hand)
    g.discard_card(0, dash)
    g.discard_card(0, fireball)
    assert fireball in g.players[0].hand and fireball not in g.players[0].discard
    assert dash in g.players[0].discard and len(g.players[0].hand) == n - 1
    assert fireball.card_id in g.players[1].known.seen


def test_wildfire_returns_a_burning_card_discarded_from_the_deck(liz_baba):
    g = liz_baba
    p = g.players[0]
    burning = next(c for c in p.deck if "burning" in c.tags)
    p.deck.remove(burning)
    p.deck.insert(0, burning)
    run_ops(g, [{"op": "discard", "cards": {"zone": "deck", "player": "owner", "pick": "top"}}], this="liz")
    assert burning in p.hand and burning not in p.discard
    plain = next(c for c in p.deck if "burning" not in c.tags)
    p.deck.remove(plain)
    p.deck.insert(0, plain)
    run_ops(g, [{"op": "discard", "cards": {"zone": "deck", "player": "owner", "pick": "top"}}], this="liz")
    assert plain in p.discard and plain not in p.hand


def test_wildfire_does_not_return_a_played_burning_scheme_nor_a_rival_burning_card(liz_baba):
    g = liz_baba
    clarity = give(g, 0, "Searing Clarity")
    g.discard_card(0, clarity, played=True)
    assert clarity in g.players[0].discard
    other = give(g, 1, "Pact Of Peace")
    g.discard_card(1, other)
    assert other in g.players[1].discard


def test_wildfire_start_of_turn_burning_bottom_card_hits_one_other_fighter_in_the_zone(liz_baba):
    g = liz_baba
    liz, baba, koschei = g.fighters["liz"], g.fighters["baba"], g.fighters["koschei"]
    place(g, baba=liz.pos, koschei=sorted(g.board.adj[liz.pos])[0])          # two rivals share Liz's zone
    bottom = deck_with_bottom(g, 0, burning=True)
    g.fx.choosers = {0: ScriptedChooser([["koschei"]]), 1: ScriptedChooser()}
    g.turn = 0
    hp = (baba.hp, koschei.hp, liz.hp)
    g.begin_turn()
    assert (baba.hp, koschei.hp, liz.hp) == (hp[0], hp[1] - 1, hp[2])        # exactly ONE target, the one Iván's player chose
    assert bottom in g.players[0].hand and bottom not in g.players[0].deck   # and the burning card came back


def test_wildfire_damage_is_mandatory_when_the_only_target_is_alone(liz_baba):
    g = liz_baba
    liz, baba = g.fighters["liz"], g.fighters["baba"]
    place(g, baba=sorted(g.board.adj[liz.pos])[0])
    g.fighters["koschei"].pos = max(g.board.spaces)                            # out of the zone
    assert not g.board.share_zone(liz.pos, g.fighters["koschei"].pos)
    deck_with_bottom(g, 0, burning=True)
    hp = baba.hp
    g.begin_turn()
    assert baba.hp == hp - 1


def test_wildfire_start_of_turn_non_burning_bottom_card_moves_liz_up_to_two(liz_baba):
    g = liz_baba
    liz = g.fighters["liz"]
    bottom = deck_with_bottom(g, 0, burning=False)
    dest = max(g.legal_moves(liz, 2) - {liz.pos})
    g.controllers[0].moves["liz"] = dest
    g.begin_turn()
    assert liz.pos == dest and g.players[0].discard[-1] is bottom and bottom not in g.players[0].hand


def test_wildfire_start_of_turn_with_an_empty_deck_does_nothing(liz_baba):
    g = liz_baba
    g.players[0].deck.clear()
    liz = g.fighters["liz"]
    pos, hp, hand, discard = liz.pos, liz.hp, list(g.players[0].hand), list(g.players[0].discard)
    g.begin_turn()
    assert (liz.pos, liz.hp, g.players[0].hand, g.players[0].discard) == (pos, hp, hand, discard)


def test_wildfire_only_fires_on_its_owners_turn(liz_baba):
    g = liz_baba
    deck = list(g.players[0].deck)
    g.turn = 1
    g.begin_turn()
    assert g.players[0].deck == deck


def test_fight_or_flight_lapses_at_the_start_of_its_owners_next_turn_before_the_wildfire_discard(liz_baba):
    g = liz_baba
    liz = g.fighters["liz"]
    fof = give(g, 0, "Fight Or Flight")
    ongoing.resolve_scheme(g, 0, liz, fof, ScriptedChooser())
    assert g.combat_bonus_total(0) == 1
    pass_turns(g, 1)                                                   # the rival's turn: still on
    assert g.combat_bonus_total(0) == 1
    bottom = deck_with_bottom(g, 0, burning=False)
    g.end_turn()
    g.turn = 0                                                         # (end_turn already handed it over)
    assert g.begin_turn() == [(1, "Fight Or Flight")]
    assert g.combat_bonus_total(0) == 0 and g.fx.ongoing_card_id(0) is None
    assert g.players[0].discard[-2:] == [fof, bottom]


# ---------------------------------------------------------------- Uncanny Intuition

def abe_attacker_card(g):
    return next(c for c in g.players[0].full_set if c.can_attack and c.usable_by("Abe Sapien") and (c.value or 0) >= 2)


@pytest.fixture
def abe_baba_abe_only(bprd):
    return mk(bprd, (ABE, BABA), {ABE})


def test_uncanny_intuition_fires_before_the_defense_is_chosen(abe_baba_abe_only, monkeypatch):
    g = abe_baba_abe_only
    revealed = []
    monkeypatch.setitem(OPS, "reveal", lambda run, game, spec: revealed.append(run.ctx.attack_card_id))   # C4 owns reveal
    g.fx.set_counter(0, "intuition", 1)
    g.turn = 1
    baba, abe = g.fighters["baba"], g.fighters["abe"]
    place(g, abe=sorted(g.board.adj[baba.pos])[0])
    atk = next(c for c in g.players[1].full_set if c.can_attack and c.usable_by(baba.name))
    g.players[1].hand.append(atk)
    seen = []
    g.controllers[0].choose_defense = lambda game, a, t: seen.append(
        (game.fx.counter_value(0, "intuition"), len(game.players[0].hand), list(revealed))) or None
    hand = len(g.players[0].hand)
    g.attack(baba, abe, atk)
    assert seen == [(0, hand + 1, [atk.card_id])]          # token spent, card drawn, attack revealed: all before choosing


def test_uncanny_intuition_does_nothing_without_a_token(abe_baba_abe_only, monkeypatch):
    g = abe_baba_abe_only
    monkeypatch.setitem(OPS, "reveal", lambda run, game, spec: pytest.fail("no token, nothing revealed"))
    g.turn = 1
    baba, abe = g.fighters["baba"], g.fighters["abe"]
    place(g, abe=sorted(g.board.adj[baba.pos])[0])
    atk = next(c for c in g.players[1].full_set if c.can_attack and c.usable_by(baba.name))
    g.players[1].hand.append(atk)
    hand = len(g.players[0].hand)
    g.attack(baba, abe, atk)
    assert len(g.players[0].hand) == hand and g.fx.counter_value(0, "intuition") == 0


def test_abe_dealing_combat_damage_to_an_adjacent_target_activates_a_token(abe_baba_abe_only):
    g = abe_baba_abe_only
    abe, baba = g.fighters["abe"], g.fighters["baba"]
    place(g, abe=sorted(g.board.adj[baba.pos])[0])
    atk = abe_attacker_card(g)
    g.players[0].hand.append(atk)
    g.attack(abe, baba, atk)
    assert g.fx.counter_value(0, "intuition") == 1


def test_abe_dealing_damage_from_afar_does_not_activate_a_token(abe_baba_abe_only):
    g = abe_baba_abe_only
    abe, baba = g.fighters["abe"], g.fighters["baba"]
    far = next(s for s in g.board.spaces if g.board.can_reach_target(s, baba.pos, True) and s not in g.board.adj[baba.pos]
               and s != baba.pos and s not in {f.pos for f in g.fighters.values()})
    place(g, abe=far)
    atk = abe_attacker_card(g)
    g.players[0].hand.append(atk)
    g.attack(abe, baba, atk)
    assert baba.hp < baba.max_hp and g.fx.counter_value(0, "intuition") == 0


def test_abe_defending_and_dealing_combat_damage_to_an_adjacent_attacker_also_counts(abe_baba_abe_only):
    """Ivan's ruling (28/10): the token also comes when Abe defends and hurts the adjacent attacker."""
    g = abe_baba_abe_only
    abe, baba = g.fighters["abe"], g.fighters["baba"]
    place(g, abe=sorted(g.board.adj[baba.pos])[0])
    g.turn = 1
    g.damage(baba, 2, "combat", by=abe)
    assert g.fx.counter_value(0, "intuition") == 1
    g.damage(baba, 2, "combat", by=abe)
    g.damage(baba, 2, "combat", by=abe)
    assert g.fx.counter_value(0, "intuition") == 2          # capped by the ability's max


def test_a_combat_damage_event_without_a_known_dealer_is_ignored(abe_baba_abe_only):
    g = abe_baba_abe_only
    g.damage(g.fighters["baba"], 2, "combat")
    assert g.fx.counter_value(0, "intuition") == 0


# ---------------------------------------------------------------- hooks and bookkeeping

def test_actions_taken_this_turn_counts_spent_actions_and_resets(abe_baba):
    g = abe_baba
    taken = lambda: amount(g, EffectRun([], Ctx(owner=0)), {"stat": "actions_taken_this_turn"})
    assert taken() == 0
    g.maneuver(0, {})
    g.maneuver(0, {})
    assert taken() == 2
    assert amount(g, EffectRun([], Ctx(owner=1)), {"stat": "actions_taken_this_turn", "player": "owner"}) == 0
    g.end_turn()
    g.begin_turn()
    g.end_turn()
    g.begin_turn()
    assert taken() == 0


def test_moved_this_turn_is_filled_at_the_start_of_the_turn(abe_baba):
    g = abe_baba
    g.begin_turn()
    abe = g.fighters["abe"]
    start = abe.pos
    assert g.fx.turn_start_pos["abe"] == start
    cond, run = {"test": "moved_this_turn", "fighter": "this"}, EffectRun([], Ctx(owner=0, this_fid="abe"))
    assert not condition(g, run, cond)
    abe.pos = next(s for s in g.board.spaces if s not in {f.pos for f in g.fighters.values()})
    assert condition(g, run, cond)


def test_a_game_with_no_dsl_hero_keeps_every_hook_inert(bprd):
    g = mk(bprd, (ABE, BABA), set())
    assert g.fx.is_empty() and g.fx.hand_limit(0, 7) == 7 and g.fx.can_gain_actions(0)
    g.maneuver(0, {})
    g.damage(g.fighters["baba"], 3, "combat", by=g.fighters["abe"])
    g.end_turn()
    assert g.fx.is_empty()


def test_clone_is_attached_to_the_clone_and_independent(abe_baba):
    g = abe_baba
    ongoing.enter_play(g, 1, give(g, 1, "Pact Of Time"))
    c = g.clone()
    assert c.fx.ongoing_card_id(1) == g.fx.ongoing_card_id(1) and c.fx.game() is c and g.fx.game() is g
    c.damage(c.fighters["baba"], 2, "combat")
    assert c.fx.ongoing_card_id(1) is None and g.fx.ongoing_card_id(1) is not None


def test_an_unattached_effect_state_with_a_dsl_hero_fails_loudly():
    from sparring.effects.state import EffectState
    fx = EffectState()
    fx.dsl_heroes.add("liz-sherman")
    with pytest.raises(RuntimeError, match="not attached"):
        fx.emit("start_of_turn", 0)


def test_a_paused_trigger_is_parked_not_lost(liz_baba):
    from sparring.effects.choose import PanelChooser
    g = liz_baba
    liz, baba = g.fighters["liz"], g.fighters["baba"]
    place(g, baba=liz.pos, koschei=sorted(g.board.adj[liz.pos])[0])
    deck_with_bottom(g, 0, burning=True)
    g.fx.choosers = {0: PanelChooser(), 1: PanelChooser()}
    g.begin_turn()
    assert len(g.fx.parked) == 1 and g.fx.parked[0].awaiting.kind == "fighter"


# ---------------------------------------------------------------- Wildfire and the hand limit

@pytest.mark.parametrize("secrecy,limit", [(False, 7), (True, 3)])
def test_burning_cards_discarded_for_the_hand_limit_stay_in_the_discard(liz_baba, secrecy, limit):
    g = liz_baba
    if secrecy:
        ongoing.enter_play(g, 1, give(g, 1, "Pact Of Secrecy"))
    hand = g.players[0].hand
    burning = [give(g, 0, t) for t in ("Fireball", "Flame Lash", "Incinerate", "Burning Barrier", "Pyrotechnics")]
    while len(hand) < 14:
        give(g, 0, next(c.title for c in g.players[0].deck if "burning" not in c.tags))
    g.controllers[0].discards = burning + [c for c in hand if c not in burning]
    g.end_turn()
    assert len(g.players[0].hand) == limit
    assert all(c in g.players[0].discard and c not in g.players[0].hand for c in burning)    # not brought back


def test_a_burning_card_forced_to_discard_by_an_effect_still_returns(liz_baba):
    g = liz_baba
    fire = give(g, 0, "Fireball")
    g.controllers[0].discards = [fire]
    g.force_discard(0, 1, "effect")
    assert fire in g.players[0].hand


# ---------------------------------------------------------------- Pact Of Freedom

def test_no_attack_as_first_action_blocks_the_first_attack_of_the_turn_only(abe_baba):
    g = abe_baba
    ongoing.enter_play(g, 1, give(g, 1, "Pact Of Freedom"))
    abe, baba = g.fighters["abe"], g.fighters["baba"]
    place(g, abe=sorted(g.board.adj[baba.pos])[0])
    atk = abe_attacker_card(g)
    g.players[0].hand.append(atk)
    assert not g.can_attack(abe, baba)
    with pytest.raises(Exception, match="primera accion"):
        g.attack(abe, baba, atk)
    assert g.actions_left == 2 and atk in g.players[0].hand
    g.maneuver(0, {})
    assert g.can_attack(abe, baba)
    g.attack(abe, baba, atk)


def test_the_first_action_rule_is_per_player_and_needs_the_pact(abe_baba, bprd):
    g = abe_baba
    assert g.fx.may_attack(0)                              # no pact in play
    ongoing.enter_play(g, 1, give(g, 1, "Pact Of Freedom"))
    assert not g.fx.may_attack(0) and g.fx.may_attack(1)   # only the player whose turn it is has a "first action"
    ongoing.leave_play(g, 1)
    assert g.fx.may_attack(0)
    assert mk(bprd, (ABE, BABA), set()).fx.may_attack(0)


# ---------------------------------------------------------------- Hellboy: DSL triggers agree with the engine wrappers

def hellboy_game(bprd, dsl=True):
    g = mk(bprd, ("medusa", "hellboy"), {"hellboy"} if dsl else set())
    g.turn = 1
    return g


def test_hellboy_detective_draw_trigger_matches_the_engine_wrapper(bprd):
    a, b = hellboy_game(bprd, dsl=False), hellboy_game(bprd)
    for g in (a, b):
        g.fighters["hellboy"].pos = g.start_spaces[0]
    assert a.hellboy_detective_draw(1) is True
    pending = events.run_trigger(b, 1, "detective_draw", {0: ScriptedChooser(), 1: ScriptedChooser([[True]])})
    assert pending is None and b.players[1].hand == a.players[1].hand and len(a.players[1].hand) == len(
        hellboy_game(bprd).players[1].hand) + 2
    c = hellboy_game(bprd)                                   # not on the rival's start space: no draw either way
    n = len(c.players[1].hand)
    assert c.hellboy_detective_draw(1) is False
    events.run_trigger(c, 1, "detective_draw", {0: ScriptedChooser(), 1: ScriptedChooser()})
    assert len(c.players[1].hand) == n


def test_hellboy_anung_trigger_matches_the_engine_wrapper(bprd):
    a, b = hellboy_game(bprd, dsl=False), hellboy_game(bprd)
    for g in (a, b):
        g.players[1].discard = [c for c in g.players[1].full_set if c.destiny][:6]       # ANUNG UN RAMA
        assert g.form(1) == "ANUNG UN RAMA"
    fuel = next(c for c in a.players[1].hand if c.boost)
    dest = sorted(a.legal_moves(a.fighters["hellboy"], fuel.boost) - {a.fighters["hellboy"].pos})[0]
    a.hellboy_anung_start(1, fuel, dest)
    fuel_b = next(c for c in b.players[1].hand if c.card_id == fuel.card_id)
    events.run_trigger(b, 1, "anung_discard_move", {0: ScriptedChooser(), 1: ScriptedChooser([[fuel_b.card_id], [dest]])})
    assert b.fighters["hellboy"].pos == a.fighters["hellboy"].pos == dest
    assert [c.card_id for c in b.players[1].discard] == [c.card_id for c in a.players[1].discard]


def test_flag_off_the_wrappers_drive_hellboy_and_begin_turn_does_nothing(bprd):
    g = hellboy_game(bprd, dsl=False)
    g.fighters["hellboy"].pos = g.start_spaces[0]
    n = len(g.players[1].hand)
    g.begin_turn()
    assert len(g.players[1].hand) == n
    assert g.hellboy_detective_draw(1) is True and len(g.players[1].hand) == n + 2


def test_flag_on_begin_turn_runs_the_dsl_trigger_and_the_wrappers_are_inert(bprd):
    g = hellboy_game(bprd)
    g.fighters["hellboy"].pos = g.start_spaces[0]
    n = len(g.players[1].hand)
    g.begin_turn()
    assert len(g.players[1].hand) == n + 2
    assert g.hellboy_detective_draw(1) is False and len(g.players[1].hand) == n + 2      # no double firing
    hand, pos = list(g.players[1].hand), g.fighters["hellboy"].pos
    g.hellboy_anung_start(1, hand[0], pos)
    assert g.players[1].hand == hand and g.fighters["hellboy"].pos == pos
