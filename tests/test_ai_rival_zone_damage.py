"""The rival hero's start-of-turn damage to a fighter in its zone (Medusa's gaze, read from the effects data) weighs on the
bot's end-of-turn position, in the heuristic and in the search's threat."""
from __future__ import annotations

import pytest

from sparring import ai_medusa
from sparring.ai_hazards import ZONE_COVER_RELIEF, zone_cover_factor, zone_damage
from sparring.ai_medusa import MedusaAI, Model
from sparring.search.adapter import EngineState, attack_values
from sparring.state import Game


def rig(bprd, bot="bigfoot", foe="medusa"):
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=(bot, foe), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    return g


def free_spots(g):
    """(inside, outside): free spaces in and out of the rival hero's zone, far from every rival piece but its hero's zone."""
    rival = g.hero(1)
    taken = {f.pos for f in g.fighters.values() if f.alive}
    free = [s for s in g.board.spaces if s not in taken]
    return (max((s for s in free if g.board.share_zone(s, rival.pos)), key=lambda s: g.board.distance(s, rival.pos)),
            min((s for s in free if not g.board.share_zone(s, rival.pos)), key=lambda s: g.board.distance(s, rival.pos)))


def test_zone_damage_is_read_from_the_rivals_effects_data(bprd):
    assert zone_damage(rig(bprd), 1) == pytest.approx(1.0)               # Medusa's gaze: 1 damage
    assert zone_damage(rig(bprd, foe="hellboy"), 1) == 0.0               # a start-of-turn draw is no damage


def test_a_maneuver_destination_outside_medusas_zone_beats_one_inside(bprd, monkeypatch):
    """Same destinations ranked with and without the zone damage: outside costs nothing, inside costs the gaze (1 damage on the hero)."""
    g = rig(bprd)
    g.players[0].hand.clear()       # a defense in hand would ease the cost (see the cover factor below)
    ai = MedusaAI(0)
    monkeypatch.setattr(ai, "hit_and_run", lambda game: False)
    inside, outside = free_spots(g)
    me = g.hero(0).fid
    with_gaze, without = Model(g, 0), Model(g, 0)
    without.zone_hazard = lambda game: (0.0, 0.0)
    assert with_gaze.zone_dmg > 0
    delta = lambda spot: ai.position_value(g, with_gaze, {me: spot}) - ai.position_value(g, without, {me: spot})
    assert delta(outside) == pytest.approx(0.0)
    assert delta(inside) <= -ai_medusa.W_MEDUSA_HP + 1e-9


def test_the_penalty_follows_the_rival_hero_not_the_bots(bprd, monkeypatch):
    g = rig(bprd, foe="hellboy")
    ai = MedusaAI(0)
    model = Model(g, 0)
    assert model.zone_dmg == 0.0
    me = g.hero(0)
    taken = {f.pos for f in g.fighters.values() if f.alive}
    shared = next(s for s in g.board.spaces if s not in taken and g.board.share_zone(s, g.hero(1).pos))
    assert ai.zone_hazard_cost(g, model, {me.fid: shared, g.hero(1).fid: g.hero(1).pos}, [me]) == 0.0


def test_the_search_threat_counts_the_gaze_only_inside_the_zone(bprd, monkeypatch):
    g = rig(bprd)
    g.players[0].hand.clear()
    me, rival = g.hero(0), g.hero(1)
    inside, outside = free_spots(g)
    for f in g.foes(0):
        if not f.hero:
            f.alive = False
    threat = lambda spot: (setattr(me, "pos", spot), EngineState(g, observer=0).threat(0, urgent=True))[1]
    t_in, t_out = threat(inside), threat(outside)
    monkeypatch.setattr("sparring.search.adapter.zone_damage", lambda game, rival: 0.0)
    assert threat(outside) == t_out                                 # outside her zone the gaze adds nothing
    assert t_in[0] == pytest.approx(threat(inside)[0] + 1 / me.hp)    # inside it adds 1 damage over the hero's HP


def test_a_big_payoff_strike_keeps_out_of_medusas_reach_with_no_defense_in_hand(bprd):
    from test_houdini_ai import far_setup, final_spot_after_first_action, strikable_next_turn
    g, medusa = far_setup(bprd, True, defense=None)       # her Feints are gone; Houdini holds two Big Reveals and two Sleights
    assert Model(g, 0).zone_dmg > 0
    assert not any(c.can_defend for c in g.players[0].hand)
    _, spot = final_spot_after_first_action(g, MedusaAI(0))
    assert not strikable_next_turn(g, medusa, spot)


def test_a_big_payoff_strike_approaches_medusa_despite_the_gaze_with_a_defense_in_hand(bprd):
    from test_houdini_ai import far_setup
    g, medusa = far_setup(bprd, True, defense="Grand Escape")
    ai = MedusaAI(0)
    assert Model(g, 0).zone_dmg > 0
    first = ai.plan(g)
    assert first.kind == "maneuver" and first.boost is not None
    assert g.board.adjacent(first.moves["houdini"], medusa.pos)
    ai.execute(g, first)
    second = ai.plan(g)
    assert second.kind == "attack" and (second.via or second.card).title == "The Big Reveal"
    assert len(ai_medusa.free_boosts(g, 0, second.via or second.card, g.players[0].hand)) == 2


# ---------- defenses in hand ease the hit points, never the lethal part ----------
def hold_defenses(g, n):
    """The bot's hand becomes its `n` best defense cards for its hero; returns their values."""
    st, hero = g.players[0], g.hero(0)
    st.deck.extend(st.hand)
    st.hand.clear()
    best = sorted((c for c in st.deck if c.can_defend and c.usable_by(hero.name)), key=lambda c: (-c.value, c.card_id))[:n]
    for c in best:
        st.deck.remove(c)
        st.hand.append(c)
    return [c.value for c in best]


def test_the_cover_factor_goes_from_one_with_no_defense_down_to_its_floor():
    relief = ZONE_COVER_RELIEF
    assert relief == 0.5
    assert zone_cover_factor([], 4.0) == 1.0
    assert zone_cover_factor([3], 4.0) == pytest.approx(1 - relief * 3 / 8)          # one card stops 3 of the 2 x 4 it could face
    assert zone_cover_factor([2, 3], 4.0) == pytest.approx(1 - relief * 5 / 8)
    assert zone_cover_factor([1, 6, 5, 9], 4.0) == pytest.approx(1 - relief)         # the two best, each capped at the blow
    assert zone_cover_factor([1, 1, 1], 4.0) == pytest.approx(1 - relief * 2 / 8)    # a third defense adds nothing
    assert zone_cover_factor([9], 4.0) == pytest.approx(1 - relief / 2)              # a single card covers half at most


def test_defenses_in_hand_discount_the_gazes_hit_points_and_never_its_lethal_part(bprd):
    g = rig(bprd)
    ai, me, rival = MedusaAI(0), g.hero(0), g.hero(1)
    pos = {me.fid: shared_spot(g), rival.fid: rival.pos}
    blows = [(p, v) for p, v in Model(g, 0).attack_dist(rival) if v is not None]
    blow = sum(p * v for p, v in blows) / sum(p for p, _ in blows)
    full = ai_medusa.W_MEDUSA_HP * zone_damage(g, 1)
    costs = []
    for n in (0, 1, 2, 3):
        held = hold_defenses(g, n)
        assert len(held) == n
        costs.append(ai.zone_hazard_cost(g, Model(g, 0), pos, [me]))
        assert costs[-1] == pytest.approx(full * zone_cover_factor(held, blow))
    assert costs[0] == pytest.approx(full)
    assert full > costs[1] > costs[2] >= full * (1 - ZONE_COVER_RELIEF) - 1e-9
    assert costs[3] == pytest.approx(costs[2])                       # a third defense adds nothing
    me.hp = 1                                                        # the gaze kills: the whole LETHAL stays whatever is held
    assert ai.zone_hazard_cost(g, Model(g, 0), pos, [me]) == pytest.approx(costs[3] + ai_medusa.LETHAL)


def test_the_search_threat_scales_the_gaze_by_the_same_cover_and_keeps_its_kill(bprd, monkeypatch):
    g = rig(bprd)
    me, rival = g.hero(0), g.hero(1)
    inside, _ = free_spots(g)
    me.pos = inside
    for f in g.foes(0):
        if not f.hero:
            f.alive = False
    held = hold_defenses(g, 2)
    values = attack_values(g.players[1], rival.name)
    factor = zone_cover_factor(held, sum(values) / len(values))
    assert 1 - ZONE_COVER_RELIEF <= factor < 1
    threat = lambda: EngineState(g, observer=0).threat(0, urgent=True)
    with_gaze = threat()
    me.hp = 1
    assert threat()[1] == 1.0                                        # at 1 HP the gaze kills, defenses or not
    me.hp = me.max_hp
    monkeypatch.setattr("sparring.search.adapter.zone_damage", lambda game, rival: 0.0)
    assert with_gaze[0] == pytest.approx(threat()[0] + factor / me.hp)


# ---------- a damage that needs a card of the rival's hand or deck ----------
def test_she_hulk_throws_nothing_with_an_empty_hand_and_the_throw_costs_her_the_card(bprd):
    from sparring.ai_hazards import zone_hazard
    g = rig(bprd, foe="she-hulk")
    st = g.players[1]
    assert st.hand
    pool = [c for c in st.full_set if c not in st.gone]
    assert zone_hazard(g, 1) == (pytest.approx(sum(c.boost for c in pool) / len(pool)), 1.0)     # the average boost, one card paid
    st.deck.extend(st.hand)
    st.hand.clear()
    assert zone_hazard(g, 1) == (0.0, 0.0)
    assert zone_damage(g, 1) == 0.0


def test_liz_fires_no_wildfire_with_an_empty_deck(bprd):
    from sparring.ai_hazards import zone_hazard
    g = rig(bprd, foe="liz-sherman")
    st = g.players[1]
    pool = [c for c in st.full_set if c not in st.gone]
    burning = sum("burning" in c.tags for c in pool)
    assert 0 < burning < len(pool)
    assert zone_hazard(g, 1) == (pytest.approx(burning / len(pool)), 0.0)        # the bottom card costs her nothing
    st.hand.extend(st.deck)
    st.deck.clear()
    assert zone_damage(g, 1) == 0.0                                              # cards in hand only: nothing to burn
    st.discard.extend(st.hand)
    st.hand.clear()
    assert zone_damage(g, 1) == 0.0                                              # every card played: no pool at all


def shared_spot(g):
    taken = {f.pos for f in g.fighters.values() if f.alive}
    return next(s for s in g.board.spaces if s not in taken and g.board.share_zone(s, g.hero(1).pos))


def test_the_position_pays_she_hulks_throw_less_the_card_it_costs_her(bprd):
    g = rig(bprd, foe="she-hulk")
    g.players[0].hand.clear()
    ai, model, me, rival = MedusaAI(0), Model(g, 0), g.hero(0), g.hero(1)
    pos = {me.fid: shared_spot(g), rival.fid: rival.pos}
    assert ai.zone_hazard_cost(g, model, pos, [me]) == pytest.approx(ai_medusa.W_MEDUSA_HP * model.zone_dmg - ai_medusa.CARD_VALUE)


def test_a_model_built_earlier_does_not_keep_the_damage_once_the_rivals_hand_or_deck_is_gone(bprd):
    """The position valued may be a later one than the model's (my action emptied her hand): the cost follows the game given."""
    for foe, zone in (("she-hulk", "hand"), ("liz-sherman", "deck")):
        g = rig(bprd, foe=foe)
        ai, model, me, rival = MedusaAI(0), Model(g, 0), g.hero(0), g.hero(1)
        pos = {me.fid: shared_spot(g), rival.fid: rival.pos}
        assert ai.zone_hazard_cost(g, model, pos, [me]) > 0
        later = g.clone()
        st = later.players[1]
        st.discard.extend(getattr(st, zone))
        getattr(st, zone).clear()
        assert ai.zone_hazard_cost(later, model, pos, [me]) == 0.0, foe
        assert ai.zone_hazard_cost(g, model, pos, [me]) > 0, foe           # and the earlier position still pays


# ---------- a sidekick in the zone ----------
def jackalope_in_the_zone(bprd):
    """Bigfoot outside Medusa's zone, the Jackalope inside it: the gaze can only pick the sidekick."""
    g = rig(bprd)
    g.players[0].hand.clear()
    inside, outside = free_spots(g)
    me, jack, rival = g.hero(0), g.fighters["jackalope"], g.hero(1)
    cost = lambda: MedusaAI(0).zone_hazard_cost(g, Model(g, 0), {me.fid: outside, jack.fid: inside, rival.fid: rival.pos}, [me, jack])
    return g, jack, cost


def test_a_sidekick_in_the_zone_costs_its_share_of_hit_points_eased_by_the_defenses_in_hand(bprd):
    g, jack, cost = jackalope_in_the_zone(bprd)
    assert jack.hp == jack.max_hp == 6 and zone_damage(g, 1) == pytest.approx(1.0)
    bare = cost()
    assert bare == pytest.approx(ai_medusa.HARPY_VALUE * jack.max_hp * 1 / 6)
    jack.hp = 3                                   # the same point is a bigger share of what is left
    assert cost() == pytest.approx(ai_medusa.HARPY_VALUE * jack.max_hp * 1 / 3)
    defense = next(c for c in g.players[0].deck if c.can_defend and c.usable_by(jack.name) and c.value)
    g.players[0].hand.append(defense)
    assert ai_medusa.HARPY_VALUE * jack.max_hp / 3 * (1 - ZONE_COVER_RELIEF) <= cost() < ai_medusa.HARPY_VALUE * jack.max_hp / 3


def test_a_sidekick_the_zone_damage_kills_for_sure_is_lost_whole_whatever_the_hand(bprd):
    """At 1 hit point the gaze kills the Jackalope and no defense stops it: the cover factor does not apply."""
    g, jack, cost = jackalope_in_the_zone(bprd)
    jack.hp = 1
    assert cost() == pytest.approx(ai_medusa.HARPY_VALUE * jack.max_hp)
    g.players[0].hand.extend(c for c in g.players[0].deck if c.can_defend and c.usable_by(jack.name) and c.value)
    assert len(g.players[0].hand) >= 2
    assert cost() == pytest.approx(ai_medusa.HARPY_VALUE * jack.max_hp)
