"""Sidekick policy "guard": the sidekick stands where the rivals' paths to its hero are blocked (Bigfoot + Jackalope)."""
import pytest

from sparring.search.adapter import SIDEKICK_POLICIES, EngineState, sidekick_plan
from conftest import give
from sparring.state import Game
from test_bigfoot_effects import mk
from test_effects_combat import hand_filler

# the heuristic's cover is off for release (HEURISTIC_GUARD); these tests keep it specified and turn it on. The search tests
# in this file do not read the switch
pytestmark = pytest.mark.usefixtures("heuristic_guard_on")


@pytest.fixture
def corridor(bprd):
    """Bigfoot at 0; Hellboy at 12 gets at Bigfoot through space 1 (four steps: his move and a boost of 2);
    the Jackalope at 3 can reach space 1. Lobster is out, so the only rival is the melee one. Hellboy's cards that boost
    more than 2 are in his discard pile: with one of them he would walk round the Jackalope (five steps) and space 1
    would not be the only way in."""
    g = mk(bprd, foe="hellboy")
    lobster = g.fighters["lobster"]
    lobster.alive, lobster.pos = False, None
    for fid, pos in (("bigfoot", 0), ("jackalope", 3), ("hellboy", 12)):
        g.fighters[fid].pos = pos
    play_out(g, 1, [c for c in g.players[1].full_set if c.boost > 2])
    return g


def static_value(game, player, hero_dest, policy):
    """Static end-of-turn value of the placement for `player`: rival exposure minus own exposure (as `_placements`)."""
    st = EngineState(game, observer=player)
    st.phase, st.partial = "maneuver_place", (None,)
    plan = sidekick_plan(st.game, player, 0, policy, hero_dest=hero_dest)
    st.game.fighters["bigfoot"].pos = hero_dest
    for fid, dest in plan:
        st.game.fighters[fid].pos = dest
    return st._exposure(1 - player, True) - st._exposure(player, True), dict(plan)


def test_guard_is_a_policy():
    assert "guard" in SIDEKICK_POLICIES


def test_guard_blocks_the_only_path_and_beats_the_other_policies(corridor):
    scores = {p: static_value(corridor, 0, 0, p) for p in SIDEKICK_POLICIES}
    guard_value, guard_plan = scores["guard"]
    assert guard_plan["jackalope"] == 1, "the sidekick stands in the corridor"
    for policy in ("stay", "advance", "retreat"):
        assert guard_value > scores[policy][0], policy


def test_placements_propose_the_guarding_placement(corridor):
    st = EngineState(corridor, observer=0)
    st.apply(("maneuver", None))
    guarding = [m for m in st.legal_moves() if m[2] == "guard"]
    assert guarding, "the tree gets a guard placement"
    blocked = [m for m in guarding
               if sidekick_plan(st.game, 0, 0, "guard", hero_dest=m[1])[0][1] != st.game.fighters["jackalope"].pos]
    assert blocked, "and the sidekick actually moves to cover"


def test_guard_reduces_threat_on_bigfoot_versus_stay(corridor):
    def threat_after(policy):
        st = EngineState(corridor, observer=0)
        for fid, dest in sidekick_plan(st.game, 0, 0, policy, hero_dest=0):
            st.game.fighters[fid].pos = dest
        return st.threat(0, True)

    assert threat_after("stay")[0] > 0
    assert threat_after("guard")[0] < threat_after("stay")[0]


def test_guard_with_no_sidekick_or_no_threat_is_harmless(bprd):
    g = mk(bprd, foe="hellboy")
    for fid in ("lobster", "hellboy"):
        g.fighters[fid].alive, g.fighters[fid].pos = False, None
    plan = sidekick_plan(g, 0, 0, "guard", hero_dest=3)
    assert plan[0][0] == "jackalope" and plan[0][1] in g.board.reachable(0, 3, {3}, set()) | {0}


@pytest.fixture
def medusa_screen(game):
    """Medusa at 6 with her three Harpies behind her; Hellboy at 12 reaches her through open ground; Lobster is out."""
    lobster = game.fighters["lobster"]
    lobster.alive, lobster.pos = False, None
    for fid, pos in (("medusa", 6), ("hellboy", 12), ("harpy1", 7), ("harpy2", 8), ("harpy3", 9)):
        game.fighters[fid].pos = pos
    return game


def threat_with(game, policy):
    st = EngineState(game, observer=0)
    plan = sidekick_plan(st.game, 0, 0, policy, hero_dest=6)
    for fid, dest in plan:
        st.game.fighters[fid].pos = dest
    return st.threat(0, True)[0], dict(plan)


def test_guard_with_three_sidekicks_lowers_threat_and_spreads_them(medusa_screen):
    stay, _ = threat_with(medusa_screen, "stay")
    guard, plan = threat_with(medusa_screen, "guard")
    assert stay > 0 and guard < stay
    assert len(set(plan.values())) == 3, "no two Harpies share a space"


def test_guard_leaves_a_pinned_sidekick_where_it_is(medusa_screen, monkeypatch):
    pinned = medusa_screen.fighters["harpy1"]
    can_move = type(medusa_screen.fx).can_move
    monkeypatch.setattr(type(medusa_screen.fx), "can_move", lambda fx, f: f is not pinned and can_move(fx, f))
    plan = dict(sidekick_plan(medusa_screen, 0, 0, "guard", hero_dest=6))
    assert plan["harpy1"] == 7


def test_heuristic_ai_offers_the_guard_placement(corridor):
    from sparring.ai_medusa import MedusaAI, Model
    from sparring.guard import guard_dest
    acts = MedusaAI(0).maneuver_acts(corridor, Model(corridor, 0))
    plans = [a.moves for a in acts if a.boost is None and a.moves["bigfoot"] == 0]
    expected = guard_dest(corridor, 0, corridor.legal_moves(corridor.fighters["jackalope"], 3) | {3}, "jackalope",
                          {"bigfoot": 0, "jackalope": 3})
    assert expected == 1 and any(m["jackalope"] == 1 for m in plans)


def test_heuristic_ai_offers_the_guard_placement_with_an_attack_card_in_hand(corridor):
    """Bigfoot is not hit and run: the guard maneuver is always offered and the position value decides."""
    from sparring.ai_medusa import MedusaAI, Model
    give(corridor, 0, "Larger Than Life")
    assert any(c.can_attack and c.usable_by("Bigfoot") for c in corridor.players[0].hand)
    acts = MedusaAI(0).maneuver_acts(corridor, Model(corridor, 0))
    assert any(a.boost is None and a.moves["jackalope"] == 1 for a in acts)


def test_a_hit_and_run_hero_holding_an_attack_and_a_defense_gets_no_guard_placement(bprd, monkeypatch):
    """Bess may cover Houdini. Only with both a poke and a defense in hand no guard maneuver is built: his pokes (POKE_FLOOR)
    are calibrated against lines that do not trade a position gain for them. With no card, or with an attack card and nothing
    to defend with, Bess is offered the guard."""
    from sparring import ai_medusa
    from sparring.ai_medusa import MedusaAI, Model
    from test_houdini_ai import mk as houdini
    asked = []
    monkeypatch.setattr(ai_medusa, "guard_dest", lambda game, hero_pos, options, fid, own: asked.append(fid) or own[fid])
    g = houdini(bprd)
    ai = MedusaAI(0)
    assert ai.hit_and_run(g)

    def offered():
        asked.clear()
        ai.maneuver_acts(g, Model(g, 0))
        assert set(asked) <= {"bess"}
        return bool(asked)

    assert offered(), "empty hand"
    give(g, 0, "Flourish")
    assert offered(), "an attack card and no defense"
    give(g, 0, "Grand Escape")
    assert not offered(), "an attack card and a defense"


# ---------- the heuristic values the block (position_value) ----------
def test_path_steps_walks_around_the_blocked_spaces(bprd):
    from sparring.guard import path_steps, strike_spots
    spots = strike_spots(bprd, 1, False)                 # next to space 1: 0, 2 and 15
    assert spots == {0, 2, 15}
    assert path_steps(bprd, 13, spots, frozenset({1}), 9) == bprd.distance(13, 15) == 2
    assert path_steps(bprd, 13, spots, frozenset({1, 14}), 9) == 6          # 14 taken: the long way round
    assert path_steps(bprd, 13, spots, frozenset({1, 12, 14, 17}), 9) == 9  # walled in: the cap
    assert path_steps(bprd, 13, spots, frozenset({1, 14}), 5) == 5          # farther than the cap is the cap
    assert path_steps(bprd, 15, spots, frozenset({1, 14}), 9) == 0


def test_a_sidekick_in_the_rivals_way_is_worth_more_than_one_beside_it(bprd):
    """A hurt Bigfoot at 1, Hellboy (move 2) at 13, two steps from striking him through 14. The Jackalope next to Hellboy on 14
    is not on a strike spot but leaves him six steps away; on 12 or 17, just as close to Hellboy, it blocks nothing."""
    from sparring.ai_medusa import MedusaAI, Model
    g = mk(bprd, foe="hellboy")
    lobster = g.fighters["lobster"]
    lobster.alive, lobster.pos = False, None
    for fid, pos in (("bigfoot", 1), ("jackalope", 3), ("hellboy", 13)):
        g.fighters[fid].pos = pos
    g.fighters["bigfoot"].hp = 6
    hand_filler(g, 1, 3)
    ai, model = MedusaAI(0), Model(g, 0)
    value = lambda space: ai.position_value(g, model, {"jackalope": space})
    assert value(14) > value(12) + 1 and value(14) > value(17) + 1


def test_a_sidekick_at_its_last_hit_point_is_no_wall(bprd):
    """The same scene with the Jackalope at 1 hit point: any blow that lands kills it and the way is open again, so standing
    on 14 takes nothing off Hellboy's threat on Bigfoot. At 2 it still closes the way."""
    from sparring.ai_medusa import WALL_MIN_HP, MedusaAI, Model
    g = mk(bprd, foe="hellboy")
    lobster = g.fighters["lobster"]
    lobster.alive, lobster.pos = False, None
    for fid, pos in (("bigfoot", 1), ("jackalope", 3), ("hellboy", 13)):
        g.fighters[fid].pos = pos
    g.fighters["bigfoot"].hp = 6
    hand_filler(g, 1, 3)
    ai, model = MedusaAI(0), Model(g, 0)
    value = lambda space: ai.position_value(g, model, {"jackalope": space})
    assert WALL_MIN_HP == 2
    g.fighters["jackalope"].hp = 2
    assert value(14) > value(12) + 1
    g.fighters["jackalope"].hp = 1
    assert value(14) < value(12) + 0.2 and value(14) < value(17) + 0.2


def test_only_the_sidekicks_that_hold_are_walls_never_the_hero(bprd, monkeypatch):
    """The rival's walk goes round the Jackalope while it holds and round nobody once it is at 1 hit point: Bigfoot himself
    is never an obstacle between a rival and his sidekick."""
    from sparring import ai_medusa
    from sparring.ai_medusa import MedusaAI, Model
    g = mk(bprd, foe="hellboy")
    for fid, pos in (("bigfoot", 14), ("jackalope", 1), ("hellboy", 13), ("lobster", 30)):
        g.fighters[fid].pos = pos
    hand_filler(g, 1, 3)
    walls = []
    real = ai_medusa.path_steps
    monkeypatch.setattr(ai_medusa, "path_steps", lambda board, start, targets, blocked, cap: (
        walls.append(blocked), real(board, start, targets, blocked, cap))[1])
    ai, model = MedusaAI(0), Model(g, 0)
    ai.position_value(g, model)
    assert walls and set(walls) == {frozenset({1})}
    walls.clear()
    g.fighters["jackalope"].hp = 1
    ai.position_value(g, model)
    assert walls and set(walls) == {frozenset()}


def medusa_next_to_hellboy():
    """Medusa on 0 next to Hellboy on 1, her three Harpies (1 hit point each) on 20, 21 and 22, the Lobster far on 27; her
    hand is Gaze of Stone alone, Second Shot is the next card of her deck and she has both actions. With a boost the Harpies
    reach 0, 2 and 15: every space next to Hellboy."""
    from sparring.ai_medusa import MedusaAI
    from sparring.board import Board
    from sparring.hellboy_script import ScriptedHellboy
    ai = MedusaAI(0)
    g = Game.new(Board.load("bprd-hq"), seed=3, controllers={0: ai, 1: ScriptedHellboy(1, 0)})
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for fid, pos in dict(medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22).items():
        g.fighters[fid].pos = pos
    st = g.players[0]
    cards = st.hand + st.deck
    gaze, shot = (next(c for c in cards if c.title == title) for title in ("Gaze of Stone", "Second Shot"))
    st.hand, st.deck = [gaze], [shot] + [c for c in cards if c is not gaze and c is not shot]
    g.actions_left = 0
    g.end_turn()
    g.begin_turn()
    assert (g.turn, g.actions_left) == (0, 2)
    return g, ai


def test_harpies_around_hellboy_do_not_take_him_off_medusa(bprd):
    """Three Harpies on the spaces next to Hellboy leave him no walk to Medusa, but each dies of one blow: her danger is the
    one of the open board (closing the ring was worth 3.6 when they counted as walls)."""
    from sparring.ai_medusa import Model
    g, ai = medusa_next_to_hellboy()
    model = Model(g, 0)
    ring = {"medusa": 3, "harpy1": 0, "harpy2": 2, "harpy3": 15}
    assert {0, 2, 15} == set(bprd.adj[1])
    loose = {"medusa": 3, "harpy1": 0, "harpy2": 21, "harpy3": 15}        # space 2 left open: Hellboy walks through it
    assert ai.position_value(g, model, ring) < ai.position_value(g, model, loose) + 1


def test_medusa_does_not_burn_her_only_card_to_ring_hellboy_with_harpies_and_attacks_instead():
    """Neither as a boost to wall him in (path) nor to put the Harpies on her strike spots afterwards (guard placement):
    the turn has no boosted maneuver and has an attack."""
    g, ai = medusa_next_to_hellboy()
    assert ai.plan(g).boost is None
    played = []
    attack, maneuver = g.attack, g.maneuver
    g.attack = lambda att, tgt, card, *a, **k: (played.append(("attack", card.title)), attack(att, tgt, card, *a, **k))[1]
    g.maneuver = lambda pl, moves, boost_card=None: (played.append(("maneuver", boost_card and boost_card.title)),
                                                     maneuver(pl, moves, boost_card))[1]
    ai.take_turn(g)
    assert [kind for kind, _ in played] == ["maneuver", "attack"] and played[0][1] is None


def test_a_sidekick_at_its_last_hit_point_gets_no_guard_placement(corridor, monkeypatch):
    """`maneuver_acts` asks `guard_dest` for a Jackalope that holds, not for one a single blow kills."""
    from sparring import ai_medusa
    from sparring.ai_medusa import MedusaAI, Model
    asked = []
    monkeypatch.setattr(ai_medusa, "guard_dest", lambda game, hero_pos, options, fid, own: asked.append(fid) or own[fid])
    MedusaAI(0).maneuver_acts(corridor, Model(corridor, 0))
    assert asked and set(asked) == {"jackalope"}
    asked.clear()
    corridor.fighters["jackalope"].hp = 1
    MedusaAI(0).maneuver_acts(corridor, Model(corridor, 0))
    assert not asked


def test_a_hit_and_run_hero_never_gets_its_sidekick_priced_as_a_shield(bprd, monkeypatch):
    """Bess on 14 lengthens Hellboy's walk to Houdini: priced as any hero's sidekick her danger would drop (cover), but
    Houdini is hit and run and her danger stays whole, with or without the cover."""
    from sparring.ai_medusa import MedusaAI, Model
    from test_houdini_ai import mk as houdini
    g = houdini(bprd)
    lobster = g.fighters["lobster"]
    lobster.alive, lobster.pos = False, None
    for fid, pos in (("houdini", 1), ("bess", 14), ("hellboy", 13)):
        g.fighters[fid].pos = pos
    hand_filler(g, 1, 3)
    ai, model = MedusaAI(0), Model(g, 0)
    assert ai.hit_and_run(g)
    assert ai.position_value(g, model) == ai.position_value(g, model, cover=False)
    monkeypatch.setattr(MedusaAI, "hit_and_run", lambda self, game: False)
    assert ai.position_value(g, model) > ai.position_value(g, model, cover=False) + 0.05, "the scene does shield"


@pytest.fixture
def armed_corridor(corridor):
    """The corridor with three cards in the rival's hand: Hellboy's blow next turn is a real threat."""
    hand_filler(corridor, 1, 3)
    return corridor


def spend_the_horns(g):
    """Every Jackalope Horns is in the discard pile: the Jackalope's death no longer costs Bigfoot a card to come."""
    st = g.players[0]
    for c in [c for c in st.full_set if c.title == "Jackalope Horns"]:
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)


def bot_turn(g):
    from sparring.ai_medusa import MedusaAI
    g.controllers[0] = ai = MedusaAI(0)
    ai.take_turn(g)
    return g.fighters["bigfoot"].pos, g.fighters["jackalope"].pos


def test_covering_a_pinned_bigfoot_is_worth_more_than_staying_or_advancing_and_the_turn_ends_on_it(armed_corridor, monkeypatch):
    from sparring.ai_medusa import MedusaAI, Model
    g = armed_corridor
    can_move = type(g.fx).can_move
    monkeypatch.setattr(type(g.fx), "can_move", lambda fx, f: f.fid != "bigfoot" and can_move(fx, f))
    ai = MedusaAI(0)
    total = {a.moves["jackalope"]: a.total for a in ai.candidates(g, Model(g, 0)) if a.kind == "maneuver" and a.boost is None}
    assert set(total) > {1, 3}, "cover (1), stay (3) and an advance are all candidates"
    assert all(total[1] > value for dest, value in total.items() if dest != 1)
    assert bot_turn(g) == (0, 1)


def test_a_weak_jackalope_covers_only_once_its_horns_are_spent(armed_corridor):
    """A hurt Jackalope may die of the blow it takes in the corridor: while a Jackalope Horns is still to come its death costs
    that card too (kill_value), so covering is worth less than with the Horns spent, and at 2 hit points it does not cover
    with them to come and does once they are spent."""
    from sparring.ai_medusa import MedusaAI, Model

    def covering(g):
        return next(a.total for a in MedusaAI(0).candidates(g, Model(g, 0))
                    if a.kind == "maneuver" and a.boost is None and a.moves == {"bigfoot": 0, "jackalope": 1})

    for hp in (4, 2):
        armed_corridor.fighters["jackalope"].hp = hp
        spent = armed_corridor.clone()
        spend_the_horns(spent)
        assert covering(spent) > covering(armed_corridor) + 0.3, hp
    assert bot_turn(armed_corridor)[1] != 1
    assert bot_turn(spent) == (0, 1)


def test_with_two_defenses_in_hand_the_jackalope_does_not_end_the_turn_covering(armed_corridor):
    for nth in (0, 1):
        give(armed_corridor, 0, "It's Just Your Imagination", nth)
    assert bot_turn(armed_corridor)[1] != 1


def hellboy_next_to_baba_yaga(actions):
    """Hellboy on 12 next to Baba Yaga (13) with the Lobster on 14, also in her reach; Koschei far away on 30. From 15 Hellboy
    would have the Lobster between Baba Yaga and himself. His hand holds two Right Hand Of Doom and cards to boost with."""
    from sparring.ai_medusa import MedusaAI
    from sparring.board import Board
    from sparring.hellboy_script import ScriptedHellboy
    ai = MedusaAI(0)
    g = Game.new(Board.load("bprd-hq"), 5, {0: ai, 1: ScriptedHellboy(1, 0)}, bot_player=0, heroes=("hellboy", "baba-yaga"))
    for fid, pos in (("hellboy", 12), ("lobster", 14), ("baba", 13), ("koschei", 30)):
        g.fighters[fid].pos = pos
    assert [c.title for c in g.players[0].hand].count("Right Hand Of Doom") == 2
    g.turn, g.actions_left = 0, actions
    return g, ai


def test_walking_out_of_a_held_blow_is_valued_without_the_cover_and_hiding_behind_the_lobster_ranks_below_the_blow():
    """The shielding sidekick's cheaper danger is not for a maneuver that takes the hero out of a blow it holds and has not
    played this turn: with one action left, spending a card to stand behind the Lobster ranks below the blow on Baba Yaga, and
    no maneuver out of her reach is valued with the cover. (Which action the plan picks is not pinned here beyond its not
    being that hiding maneuver.)"""
    from sparring.ai_medusa import Model
    g, ai = hellboy_next_to_baba_yaga(actions=1)
    model = Model(g, 0)
    hide = {"hellboy": 15, "lobster": 14}
    assert ai.position_value(g, model, hide) > ai.position_value(g, model) + 5, "standing behind the Lobster is the better square"
    ranked = ai.candidates(g, model)
    blow = next(a for a in ranked if a.kind == "attack" and (a.fid, a.target) == ("hellboy", "baba"))
    hiding = [a for a in ranked if a.kind == "maneuver" and a.moves == hide]
    assert hiding and all(a.boost is not None and a.total < blow.total for a in hiding)
    away = [a for a in ranked if ai.walks_out(g, a)]
    assert len(away) > len(hiding)
    for a in away:
        bare = ai.position_value(ai.apply_expected(g, a), model, cover=False)
        assert a.total == pytest.approx(a.value + bare + ai.terminal_value(ai.apply_expected(g, a), model))
    assert ai.plan(g).moves != hide


def test_walking_out_of_a_blow_first_and_drawing_after_does_not_earn_the_cover_either():
    """With both actions left the turn still has a blow in it: hiding first and maneuvering again is not a way round."""
    g, ai = hellboy_next_to_baba_yaga(actions=2)
    attacks = []
    real_attack = g.attack
    g.attack = lambda *a, **k: (attacks.append(a), real_attack(*a, **k))[1]
    ai.take_turn(g)
    assert attacks


def test_a_hero_that_already_struck_this_turn_may_step_behind_its_sidekick():
    """The same maneuver after Hellboy's blow gives up nothing: the Lobster's danger is the shielding one."""
    from sparring.ai_medusa import Model
    g, ai = hellboy_next_to_baba_yaga(actions=1)
    hide = {"hellboy": 15, "lobster": 14}
    total = lambda: next(a.total for a in ai.candidates(g, Model(g, 0)) if a.kind == "maneuver" and a.moves == hide)
    held_back = total()
    g.fx.attacked.append("hellboy")
    assert total() > held_back + 5


def test_the_random_rollout_never_picks_the_guard_placement(corridor):
    """The tree offers guard for this maneuver, the playout does not: its path analysis costs more than a random game is worth."""
    import random
    st = EngineState(corridor, observer=0)
    st.apply(("maneuver", None))
    assert any(m[2] == "guard" for m in st.legal_moves())
    rng = random.Random(7)
    picked = {st.rollout_move(rng)[2] for _ in range(200)}
    assert picked == {"stay", "advance", "retreat"}


# ---------- the rival's boost reach is the real one of the cards it has left ----------
def play_out(g, player, cards):
    """`cards` of `player` go to its discard pile, wherever they are."""
    st = g.players[player]
    for c in cards:
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)


def test_boost_reach_is_the_biggest_boost_left_to_play_and_never_reads_the_hand(bprd):
    from sparring.guard import boost_reach
    corridor = mk(bprd, foe="hellboy")
    st = corridor.players[1]
    values = sorted({c.boost for c in st.full_set}, reverse=True)
    top = [c for c in st.full_set if c.boost == values[0]]
    assert boost_reach(corridor, 1) == values[0] == 4
    for c in top:                                   # in the hand or in the deck: the same public answer
        st.deck.remove(c)
        st.hand.append(c)
    assert boost_reach(corridor, 1) == 4
    play_out(corridor, 1, top[:1])
    assert boost_reach(corridor, 1) == 4            # one copy is still to come
    play_out(corridor, 1, top[1:])
    assert boost_reach(corridor, 1) == values[1] == 3
    play_out(corridor, 1, [c for c in st.full_set if c not in st.discard])
    assert boost_reach(corridor, 1) == 0            # no card left: no boost


def test_boost_reach_adds_what_an_effect_in_play_adds_to_the_boost_values(bprd):
    """Advisor to the king (ONGOING: your BOOST values are +1) in play: Yennefer's best boost walks one space more, as the
    engine's maneuver does. With no card left to boost with the bonus alone moves nobody."""
    from sparring.guard import boost_reach
    from test_yennefer_triss_effects import mk as yennefer
    g = yennefer(bprd)
    top = max(c.boost for c in g.players[0].full_set)
    assert boost_reach(g, 0) == top
    g.play_scheme(0, g.hero(0), give(g, 0, "Advisor to the king"))
    assert g.fx.boost_bonus(0) == 1 and boost_reach(g, 0) == top + 1
    st = g.players[0]
    advisor = g.fx.ongoing_card_id(0)
    assert advisor is not None and all(c.card_id != advisor for c in st.gone)
    play_out(g, 0, [c for c in st.full_set if c not in st.discard and c.card_id != advisor])
    assert g.fx.boost_bonus(0) == 1 and boost_reach(g, 0) == 0, "the card in play is not one left to boost with"


def test_a_rival_too_far_to_walk_threatens_only_while_a_boost_that_gets_it_there_is_left(bprd):
    """Hellboy (move 2) seven spaces from Bigfoot is six steps from striking him: he needs a boost of 4. With a card of boost 4
    still to play he is a threat and the Jackalope goes to block; with both in his discard pile (his best is then 3) he is
    none and it stays. The same position is asked twice: the memo must not answer the second with the first."""
    from sparring.guard import guard_dest
    corridor = mk(bprd, foe="hellboy")
    lobster = corridor.fighters["lobster"]
    lobster.alive, lobster.pos = False, None
    for fid, pos in (("bigfoot", 0), ("jackalope", 3), ("hellboy", 9)):
        corridor.fighters[fid].pos = pos
    board, hellboy = corridor.board, corridor.fighters["hellboy"]
    assert hellboy.move == 2 and board.distance(9, 0) == 7

    def asked():
        options = corridor.legal_moves(corridor.fighters["jackalope"], 3) | {3}
        return (EngineState(corridor, observer=0).threat(0, True)[0],
                guard_dest(corridor, 0, options, "jackalope", {"bigfoot": 0, "jackalope": 3}))

    threat, cover = asked()
    assert threat > 0 and cover != 3
    st = corridor.players[1]
    play_out(corridor, 1, [c for c in st.full_set if c.boost >= 4])
    assert asked() == (0.0, 3)
