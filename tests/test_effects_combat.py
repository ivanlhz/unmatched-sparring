"""C2: combat ops and modifiers of the effects interpreter, on real cards of data/heroes/*.json with the hero in
`game.fx.dsl_heroes`. Statuses expire through `fx.emit` (start/end of turn); ONGOING plans entering play are C3, so
the Counterhex modifiers are installed with `modifiers.add_modifier` from the card's own data."""
import json

import pytest

from sparring import persist
from sparring.combat import can_boost, deck_boost
from sparring.combat_flow import CombatFlow, PendingChoice
from sparring.effects import modifiers
from sparring.effects.choose import PanelChooser, ControllerChooser, ScriptedChooser
from sparring.effects.model import load_effects
from sparring.effects.ops_core import OPS
from sparring.effects.run import Ctx, EffectRun
from sparring.state import ANUNG, DETECTIVE, Game, RuleError

from conftest import Scripted, card, give, place


class Asking(Scripted):
    """Controller whose answers to effect decisions are queued; None falls back to the generic answer."""

    def __init__(self):
        super().__init__()
        self.queue: list = []
        self.requests: list = []

    def choose_effect(self, game, req):
        self.requests.append(req)
        return self.queue.pop(0) if self.queue else None


def mk(bprd, heroes, dsl, seed=3):
    """Player 0 (bot) plays heroes[0], player 1 heroes[1]; player 0's turn, empty hands, fighters out of the way."""
    ctl = {0: Asking(), 1: Asking()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=heroes)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    g.fx.dsl_heroes = set(dsl)
    return g


def pair(g, att_fid, tgt_fid, others_away=True):
    """Puts two fighters on adjacent spaces and every other fighter far from them (distinct spaces)."""
    a = min(g.board.spaces)
    b = sorted(g.board.adj[a])[0]
    far = sorted((s for s in g.board.spaces if s not in (a, b) and not g.board.share_zone(a, s)), reverse=True)
    place(g, **{att_fid: a, tgt_fid: b})
    if others_away:
        for f, s in zip([f for f in g.fighters.values() if f.alive and f.fid not in (att_fid, tgt_fid)], far):
            f.pos = s
    return g.fighters[att_fid], g.fighters[tgt_fid]


def put_adjacent(g, fid, to_fid):
    spot = next(s for s in sorted(g.board.adj[g.fighters[to_fid].pos])
                if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.fighters[fid].pos = spot
    return spot


def hand_filler(g, player, n, avoid=()):
    """n more cards in the hand that are not the cards named in `avoid`."""
    pool = [c for c in g.players[player].deck if c.title not in avoid][:n]
    for c in pool:
        g.players[player].deck.remove(c)
        g.players[player].hand.append(c)
    return pool


def hp(g, *fids):
    return [g.fighters[f].hp for f in fids]


# ---------------------------------------------------------------- may_boost replaces text detection

def test_can_boost_reads_the_effects_data(bprd):
    g = mk(bprd, ("liz-sherman", "baba-yaga"), [])
    assert can_boost(card(g, 1, "Out Of Time"))                  # "BOOST this card": the old text search missed it
    assert deck_boost(card(g, 0, "Flame Lash")) and can_boost(card(g, 0, "Flame Lash"))
    assert not can_boost(card(g, 0, "Feint")) and not deck_boost(card(g, 1, "Out Of Time"))
    h = mk(bprd, ("medusa", "hellboy"), [])
    assert can_boost(card(h, 1, "Second Shot")) and not can_boost(card(h, 0, "Second Shot"))     # Medusa: own rule


def test_shared_card_titles_have_the_same_boost_and_cancel_flags_in_every_hero():
    """combat.can_boost only sees a Card, so the flags are looked up by title: a title in two heroes must agree."""
    from sparring.effects.model import EFFECTS_DIR
    seen: dict[str, tuple] = {}
    for path in sorted(EFFECTS_DIR.glob("*.json")):
        if path.stem == "schema":
            continue
        for title, c in load_effects(path.stem).cards.items():
            flags = (c.may_boost, c.uncancelable, modifiers.draws_bottom_for_boost(type("C", (), {"title": title})))
            assert seen.setdefault(title, flags) == flags, title


def test_second_shot_asks_a_boost_and_a_card_without_boost_value_is_refused(bprd):
    g = mk(bprd, ("liz-sherman", "hellboy"), ["hellboy"])
    g.turn = 1
    lobster, liz = pair(g, "lobster", "liz")
    shot = give(g, 1, "Second Shot")
    flow = CombatFlow(g, lobster, liz, shot, None)
    wait = flow.run()
    assert wait.choice.kind == "boost" and wait.choice.player == 1 and wait.choice.card_id == shot.card_id
    dud = card(g, 0, "Fireball")                                  # Liz's burning-style cards have BOOST 0
    assert dud.boost == 0
    g.players[1].full_set.append(dud)                              # lent to Hellboy: the flow resolves answers by owner
    g.players[1].hand.append(dud)
    flow.resume(dud)
    with pytest.raises(RuleError, match="impulso"):
        flow.run()
    assert dud in g.players[1].hand
    good = next(c for c in g.players[1].deck if c.boost > 0)
    g.players[1].hand.append(good)
    flow.resume(good)
    assert flow.run() is None
    assert flow.result.atk_value == shot.value + good.boost and flow.result.boost_card is good


def test_out_of_time_boosts_a_defense_from_the_hand(bprd):
    g = mk(bprd, ("liz-sherman", "baba-yaga"), ["baba-yaga"])
    liz, baba = pair(g, "liz", "baba")
    flame = give(g, 0, "Fireball")
    oot = give(g, 1, "Out Of Time")
    flow = CombatFlow(g, liz, baba, flame, oot)
    wait = flow.run()
    assert wait.choice.kind == "boost" and wait.choice.player == 1 and wait.choice.card_id == oot.card_id
    boost = give(g, 1, "Iron Teeth")
    flow.resume(boost)
    assert flow.run() is None
    assert flow.result.def_value == oot.value + boost.boost
    assert boost in g.players[1].discard
    assert g.actions_left == 0                                            # AFTER: "End the turn" cuts the attacker's turn


def test_out_of_time_declined_boost_adds_nothing(bprd):
    g = mk(bprd, ("liz-sherman", "baba-yaga"), ["baba-yaga"])
    liz, baba = pair(g, "liz", "baba")
    flow = CombatFlow(g, liz, baba, give(g, 0, "Fireball"), give(g, 1, "Out Of Time"))
    assert flow.run().choice.kind == "boost"
    flow.resume(None)
    assert flow.run() is None and flow.result.def_value == 2


# ---------------------------------------------------------------- cancel_effects

def test_feint_cancels_the_attackers_effects(bprd):
    """Abe's Shock And Awe becomes 4 after a move and makes Liz discard; Liz's Feint (defender, resolves first) stops both."""
    def play(feint):
        g = mk(bprd, ("liz-sherman", "abe-sapien"), ["liz-sherman", "abe-sapien"])
        g.turn = 1
        abe, liz = pair(g, "abe", "liz")
        g.fx.turn_start_pos["abe"] = 99
        shock = give(g, 1, "Shock And Awe")
        hand_filler(g, 0, 3)
        res = g.attack(abe, liz, shock, give(g, 0, "Feint") if feint else None)
        return res, len(g.players[0].hand)
    plain, hand_plain = play(False)
    cancelled, hand_cancelled = play(True)
    assert plain.atk_value == 4 and hand_plain == 2
    assert cancelled.atk_value == 2 and hand_cancelled == 3 and cancelled.cancelled == {"atk"}


def test_ward_and_prepare_cancels_but_not_incinerate(bprd, monkeypatch):
    monkeypatch.setitem(OPS, "put_in_hand", lambda run, game, spec: None)       # AFTER of Ward: C4
    def fireball(defend):
        g = mk(bprd, ("liz-sherman", "abe-sapien"), ["liz-sherman", "abe-sapien"])
        liz, abe = pair(g, "liz", "abe")
        put_adjacent(g, "agent1", "abe")
        agent = g.fighters["agent1"]
        before = agent.hp
        res = g.attack(liz, abe, give(g, 0, "Fireball"), give(g, 1, "Ward And Prepare") if defend else None)
        return res, before - agent.hp
    (open_res, open_lost), (ward_res, ward_lost) = fireball(False), fireball(True)
    assert open_lost == 1 and ward_lost == 0 and ward_res.cancelled == {"atk"}

    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["liz-sherman", "abe-sapien"])
    liz, abe = pair(g, "liz", "abe")
    hand_filler(g, 1, 3)
    g.controllers[1].queue = [[True]]
    res = g.attack(liz, abe, give(g, 0, "Incinerate"), give(g, 1, "Ward And Prepare"))
    assert res.cancelled == set()                                       # uncancelable
    assert [r.kind for r in g.controllers[1].requests][0] == "optional"


@pytest.mark.parametrize("form", [DETECTIVE, ANUNG])
def test_planned_recklessness_shields_effect_damage_and_cancels_only_as_detective(bprd, form):
    g = mk(bprd, ("liz-sherman", "hellboy"), ["liz-sherman", "hellboy"])
    if form == ANUNG:
        g.players[1].discard += [c for c in g.players[1].full_set if c.destiny][:6]
    assert g.form(1) == form
    liz, hb = pair(g, "liz", "hellboy")
    put_adjacent(g, "lobster", "hellboy")
    res = g.attack(liz, hb, give(g, 0, "Fireball"), give(g, 1, "Planned Recklessness"))
    assert hp(g, "lobster") == [g.fighters["lobster"].max_hp]           # Fireball's 1 damage: cancelled or shielded
    assert res.cancelled == ({"atk"} if form == DETECTIVE else set())
    assert {s["fid"] for s in g.fx.statuses} == {"hellboy", "lobster"}
    g.end_turn()                                                        # "this turn": the statuses end with the turn
    assert g.fx.statuses == []


# ---------------------------------------------------------------- values

def test_incinerate_opponent_may_pay_two_cards_on_top_of_the_defense(bprd):
    def play(answers, hand=3, defend=True, bonus=0):
        g = mk(bprd, ("liz-sherman", "abe-sapien"), ["liz-sherman"])
        liz, abe = pair(g, "liz", "abe")
        if bonus:
            g.add_combat_bonus(0, bonus, "Fight Or Flight")
        filler = hand_filler(g, 1, hand)
        g.controllers[1].queue = [a(filler) if callable(a) else a for a in answers]
        res = g.attack(liz, abe, give(g, 0, "Incinerate"), give(g, 1, "Arcane Dampener") if defend else None)
        return g, res, filler

    g, res, filler = play([[True], lambda f: [f[0].card_id, f[1].card_id]])
    assert res.atk_value == 0 and res.damage == 0 and filler[0] in g.players[1].discard and filler[1] in g.players[1].discard
    g, res, _ = play([[False]])
    assert res.atk_value == 7 and res.damage == 7 - 2                       # declined: Dampener cannot even reach (Liz is not adjacent-checked)
    g, res, _ = play([[True], lambda f: [f[0].card_id, f[1].card_id]], defend=False)
    assert res.atk_value == 0                                                # paying also works with no defense card
    g, res, _ = play([[True], lambda f: [f[0].card_id, f[1].card_id]], bonus=1)
    assert res.atk_value == 0                                                # "ignore its value" drops Fight Or Flight too
    g, res, _ = play([], hand=1)
    assert res.atk_value == 7 and g.controllers[1].requests == []            # fewer than 2 cards: no option at all


def test_arcane_dampener_subtracts_three_and_clamps_at_zero(bprd):
    def play(attack):
        g = mk(bprd, ("liz-sherman", "abe-sapien"), ["abe-sapien"])
        liz, abe = pair(g, "liz", "abe")
        return g.attack(liz, abe, give(g, 0, attack), give(g, 1, "Arcane Dampener"))
    assert play("Incinerate").atk_value == 4
    low = play("Flame Lash")
    assert low.atk_value == 0 and low.damage == 0
    assert "Arcane Dampener (-1)" in low.atk_parts


def test_arcane_dampener_does_nothing_when_the_attacker_is_not_adjacent(bprd):
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["abe-sapien"])
    liz, abe = pair(g, "liz", "abe")
    abe.pos = next(s for s in sorted(g.board.spaces) if g.board.share_zone(liz.pos, s) and s != liz.pos
                   and s not in g.board.adj[liz.pos])
    res = g.attack(liz, abe, give(g, 0, "Incinerate"), give(g, 1, "Arcane Dampener"))      # Liz shoots from range
    assert res.atk_value == 7


def test_shock_and_awe_becomes_four_after_moving_and_keeps_bonuses(bprd):
    def play(moved, bonus=0):
        g = mk(bprd, ("liz-sherman", "abe-sapien"), ["abe-sapien"])
        g.turn = 1
        abe, liz = pair(g, "abe", "liz")
        if moved:
            g.fx.turn_start_pos["abe"] = 99
        if bonus:
            g.add_combat_bonus(1, bonus, "Fight Or Flight")
        hand_filler(g, 0, 2)
        res = g.attack(abe, liz, give(g, 1, "Shock And Awe"), None)
        return g, res
    assert play(False)[1].atk_value == 2
    g, res = play(True)
    assert res.atk_value == 4 and res.atk_parts[0] == "Shock And Awe (4)" and len(g.players[0].hand) == 1
    assert play(True, bonus=1)[1].atk_value == 5                             # "becomes 4" is the printed value only


def test_on_earth_with_fight_or_flight_matches_the_legacy_engine(bprd):
    def play(dsl, cancelled):
        g = mk(bprd, ("liz-sherman", "hellboy"), dsl)
        g.players[1].discard += [c for c in g.players[1].full_set if c.destiny][:3]
        g.add_combat_bonus(1, 1, "Fight Or Flight")
        liz, hb = pair(g, "liz", "hellboy")
        res = g.attack(liz, hb, give(g, 0, "Feint" if cancelled else "Fireball"), give(g, 1, "On Earth As It Is In Hell"))
        return res.def_value, res.def_parts, res.damage, res.cancelled, g.fighters["hellboy"].hp
    for cancelled in (False, True):
        both, legacy_hb = play(["liz-sherman", "hellboy"], cancelled), play(["liz-sherman"], cancelled)
        assert both == legacy_hb
    assert play(["liz-sherman", "hellboy"], False)[0] == 3 + 1
    assert play(["liz-sherman", "hellboy"], True)[0] == 0 + 1


def test_bot_flame_lash_discards_the_bottom_card_and_adds_its_boost(bprd):
    def play(burning):
        g = mk(bprd, ("liz-sherman", "hellboy"), ["liz-sherman"])
        liz, hb = pair(g, "liz", "hellboy")
        deck = g.players[0].deck
        bottom = next(c for c in deck if ("burning" in c.tags) == burning and (burning or c.boost >= 2))
        deck.remove(bottom)
        deck.append(bottom)
        lash = give(g, 0, "Flame Lash")
        left = len(deck) - 1
        actions = g.actions_left
        res = g.attack(liz, hb, lash, None)
        assert len(g.players[0].deck) == left
        assert g.actions_left == actions                                    # spent one, AFTER COMBAT gains one
        return g, res, bottom, lash
    g, res, bottom, lash = play(False)
    assert bottom in g.players[0].discard
    assert res.atk_value == lash.value + bottom.boost and bottom.boost >= 2
    g, res, bottom, lash = play(True)
    assert bottom.boost == 0 and res.atk_value == lash.value               # a burning card adds nothing
    assert bottom in g.players[0].hand and bottom not in g.players[0].discard   # WILDFIRE brings it back (C3)


def test_flame_lash_with_an_empty_deck_adds_nothing(bprd):
    g = mk(bprd, ("liz-sherman", "hellboy"), ["liz-sherman"])
    liz, hb = pair(g, "liz", "hellboy")
    g.players[0].deck.clear()
    lash = give(g, 0, "Flame Lash")
    assert g.attack(liz, hb, lash, None).atk_value == lash.value


# ---------------------------------------------------------------- statuses

def run_ops(g, ops, owner, this):
    run = EffectRun(ops, Ctx(owner=owner, this_fid=this))
    assert run.run(g, ControllerChooser()) is None
    return run


def test_cold_iron_blocks_drawing_and_actions_until_the_end_of_the_turn(bprd):
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["abe-sapien"])
    ops = load_effects("abe-sapien").moment_ops("Cold Iron And Holy Water", "immediately")
    run_ops(g, ops, 1, "abe")
    hand, actions = len(g.players[0].hand), g.actions_left
    assert g.draw(0, 2) == [] and len(g.players[0].hand) == hand
    g.grant_actions(1)
    assert g.actions_left == actions
    assert len(g.draw(1, 1)) == 1                                             # only the opponent is blocked
    g.end_turn()
    assert g.fx.statuses == [] and len(g.draw(0, 1)) == 1


def test_burning_barrier_pins_the_enemy_fighter_for_every_source_but_not_liz(bprd):
    g = mk(bprd, ("liz-sherman", "hellboy"), ["liz-sherman", "hellboy"])
    liz, hb = pair(g, "liz", "hellboy")
    res = g.attack(liz, hb, give(g, 0, "Burning Barrier"), None)
    assert [s["name"] for s in g.fx.statuses] == ["cannot_leave_space"] and g.fx.statuses[0]["fid"] == "hellboy"
    assert g.legal_moves(hb, 3) == {hb.pos}                                  # his own maneuver
    start = hb.pos
    move = [{"op": "move", "target": {"side": "enemy", "kind": "hero"}, "amount": 3, "up_to": True}]
    run_ops(g, move, 0, "liz")
    place_op = [{"op": "place", "target": {"side": "enemy", "kind": "hero"}, "where": {"any": True}}]
    run_ops(g, place_op, 0, "liz")
    assert hb.pos == start
    assert g.legal_moves(liz, 3) - {liz.pos}                                  # Liz is not pinned
    run_ops(g, [{"op": "place", "target": "hero", "where": {"any": True}}], 1, "hellboy")
    assert hb.pos == start                                                    # not even by his own effects


def test_next_attack_bonus_is_consumed_by_the_first_attack(bprd):
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["abe-sapien"])
    g.turn = 1
    abe, liz = pair(g, "abe", "liz")
    run_ops(g, [{"op": "status", "name": "next_attack_bonus", "player": "owner", "amount": 1,
                 "until": {"event": "end_of_turn"}}], 1, "abe")
    hand_filler(g, 0, 2)
    cards = [give(g, 1, "Faster. Stronger."), give(g, 1, "Faster. Stronger.", 1)]
    first = g.attack(abe, liz, cards[0], None)
    assert first.atk_value == cards[0].value + 1 and "(+1)" in " ".join(first.atk_parts)
    assert g.attack(abe, liz, cards[1], None).atk_value == cards[1].value


def test_status_expiry_events(bprd):
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["abe-sapien"])
    fx = g.fx
    modifiers.add_status(fx, "cannot_draw", owner=1, player=0, until={"event": "start_of_turn", "player": "owner"})
    modifiers.add_status(fx, "cannot_draw", owner=1, player=0, until={"event": "end_of_turn"})
    fx.emit("start_of_turn", 0)
    assert len(fx.statuses) == 2                                              # owner is player 1
    fx.emit("start_of_turn", 1)
    assert len(fx.statuses) == 1
    fx.emit("end_of_turn", 1)
    assert fx.statuses == []
    with pytest.raises(Exception):
        modifiers.add_status(fx, "bogus", owner=0, until={"event": "end_of_turn"}, player=0)


# ---------------------------------------------------------------- Counterhex Shield (ONGOING modifiers)

def counterhex(g, owner):
    ongoing = load_effects("abe-sapien").card("Counterhex Shield").ongoing
    for m in ongoing["modifiers"]:
        modifiers.add_modifier(g.fx, owner, 999, m)


def test_counterhex_blocks_enemy_effect_damage_moves_and_forced_discards(bprd):
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["liz-sherman", "abe-sapien"])
    liz, abe = pair(g, "liz", "abe")
    counterhex(g, 1)
    hit = [{"op": "damage", "target": {"side": "enemy", "kind": "hero"}, "amount": 3}]
    run_ops(g, hit, 0, "liz")
    assert abe.hp == abe.max_hp
    run_ops(g, [{"op": "damage", "target": "hero", "amount": 1}], 1, "abe")      # his own effects still work
    assert abe.hp == abe.max_hp - 1
    start = abe.pos
    run_ops(g, [{"op": "move", "target": {"side": "enemy", "kind": "hero"}, "amount": 3, "up_to": True}], 0, "liz")
    assert abe.pos == start
    hand_filler(g, 1, 3)
    discard = [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "opponent"}}]
    run_ops(g, discard, 0, "liz")
    assert len(g.players[1].hand) == 3
    assert not g.fx.can_force_discard(1, 0) and g.fx.can_force_discard(1, 1) and g.fx.can_force_discard(0, 1)
    assert g.force_discard(1, 1, "effect", 0) == [] and len(g.players[1].hand) == 3
    assert len(g.force_discard(1, 1, "hand limit")) == 1                      # no source: the player's own discard
    assert g.damage(abe, 2, "combat") == 2                                       # combat damage is not an effect
    modifiers.remove_modifiers(g.fx, 999)
    run_ops(g, hit, 0, "liz")
    assert abe.hp == abe.max_hp - 1 - 2 - 3


def test_counterhex_does_not_stop_the_rivals_voluntary_discard_cost(bprd):
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["liz-sherman"])
    liz, abe = pair(g, "liz", "abe")
    counterhex(g, 1)
    filler = hand_filler(g, 1, 3)
    g.controllers[1].queue = [[True], [filler[0].card_id, filler[1].card_id]]
    res = g.attack(liz, abe, give(g, 0, "Incinerate"), None)
    assert res.atk_value == 0                                                    # Incinerate's cost is the payer's choice


# ---------------------------------------------------------------- redirected damage

def baba_game(bprd, same_zone=True):
    g = mk(bprd, ("liz-sherman", "baba-yaga"), ["liz-sherman", "baba-yaga"])
    liz, baba = pair(g, "liz", "baba")
    if same_zone:
        put_adjacent(g, "koschei", "baba")
        assert g.board.share_zone(baba.pos, g.fighters["koschei"].pos)
    return g, liz, baba


def test_fateful_bargains_asks_the_owner_and_redirects_effect_damage(bprd):
    hit = [{"op": "damage", "target": {"side": "enemy", "kind": "hero"}, "amount": 2}]
    g, liz, baba = baba_game(bprd)
    g.controllers[1].queue = [[True]]
    run_ops(g, hit, 0, "liz")
    req = g.controllers[1].requests[0]
    assert req.kind == "optional" and req.player == 1 and req.extra["to"] == "koschei"
    assert hp(g, "baba", "koschei") == [baba.max_hp, g.fighters["koschei"].max_hp - 2]
    g, liz, baba = baba_game(bprd)
    g.controllers[1].queue = [[False]]
    run_ops(g, hit, 0, "liz")
    assert hp(g, "baba", "koschei") == [baba.max_hp - 2, g.fighters["koschei"].max_hp]


def test_fateful_bargains_needs_koschei_in_the_zone_and_alive(bprd):
    hit = [{"op": "damage", "target": {"side": "enemy", "kind": "hero"}, "amount": 2}]
    g, liz, baba = baba_game(bprd, same_zone=False)
    run_ops(g, hit, 0, "liz")
    assert g.controllers[1].requests == [] and baba.hp == baba.max_hp - 2
    g, liz, baba = baba_game(bprd)
    g.fighters["koschei"].alive, g.fighters["koschei"].pos = False, None
    run_ops(g, hit, 0, "liz")
    assert g.controllers[1].requests == [] and baba.hp == baba.max_hp - 2


def test_fateful_bargains_is_off_when_baba_is_not_a_dsl_hero(bprd):
    g, liz, baba = baba_game(bprd)
    g.fx.dsl_heroes = {"liz-sherman"}
    run_ops(g, [{"op": "damage", "target": {"side": "enemy", "kind": "hero"}, "amount": 2}], 0, "liz")
    assert g.controllers[1].requests == [] and baba.hp == baba.max_hp - 2


def test_bound_in_blood_sends_the_combat_damage_to_koschei(bprd):
    g, liz, baba = baba_game(bprd)
    bound = give(g, 1, "Bound In Blood")
    res = g.attack(liz, baba, give(g, 0, "Incinerate"), bound)
    assert res.damage == 7 - bound.value
    assert hp(g, "baba") == [baba.max_hp] and g.fighters["koschei"].hp == g.fighters["koschei"].max_hp - res.damage \
        or not g.fighters["koschei"].alive
    assert any("koschei" in line for line in res.applied)


def test_bound_in_blood_does_nothing_without_koschei_in_the_zone(bprd):
    g, liz, baba = baba_game(bprd, same_zone=False)
    res = g.attack(liz, baba, give(g, 0, "Incinerate"), give(g, 1, "Bound In Blood"))
    assert baba.hp == baba.max_hp - res.damage and res.damage > 0


def in_play(g, player, title):
    """Puts a real card of `player` in their ONGOING slot the way C3 does (no copy into fx.modifiers)."""
    pile = g.players[player]
    c = next(c for c in pile.full_set if c.title == title)
    for zone in (pile.hand, pile.deck, pile.discard):
        if c in zone:
            zone.remove(c)
    g.fx.set_ongoing(player, c.card_id)
    return c


def test_counterhex_in_play_as_ongoing_is_enforced_without_add_modifier(bprd):
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["liz-sherman", "abe-sapien"])
    liz, abe = pair(g, "liz", "abe")
    in_play(g, 1, "Counterhex Shield")
    assert not g.fx.modifiers
    run_ops(g, [{"op": "damage", "target": {"side": "enemy", "kind": "hero"}, "amount": 3}], 0, "liz")
    assert abe.hp == abe.max_hp
    start = abe.pos
    run_ops(g, [{"op": "move", "target": {"side": "enemy", "kind": "hero"}, "amount": 3, "up_to": True}], 0, "liz")
    assert abe.pos == start
    assert not g.fx.can_force_discard(1, 0) and g.fx.can_force_discard(0, 1)
    g.fx.take_ongoing(1)
    assert g.fx.can_force_discard(1, 0)


def test_pacts_in_play_as_ongoing_add_effect_damage_and_block_actions(bprd):
    g = mk(bprd, ("liz-sherman", "baba-yaga"), ["liz-sherman", "baba-yaga"])
    liz, baba = pair(g, "liz", "baba")
    in_play(g, 1, "Pact Of Mortality")
    assert g.damage(liz, 2, "effect") == 3 and g.damage(liz, 2, "combat") == 2
    in_play(g, 1, "Pact Of Time")
    actions = g.actions_left
    g.grant_actions(1)
    assert g.actions_left == actions
    assert g.damage(liz, 1, "effect") == 1                                      # Mortality was replaced


def test_pact_of_mortality_style_damage_bonus_skips_exhaustion_and_combat(bprd):
    g = mk(bprd, ("liz-sherman", "baba-yaga"), ["baba-yaga"])
    liz, baba = pair(g, "liz", "baba")
    modifiers.add_modifier(g.fx, 1, 50, {"kind": "rule", "rule": "effect_damage_bonus", "amount": 1})
    assert g.damage(liz, 2, "effect") == 3 and g.damage(liz, 2, "combat") == 2 and g.damage(liz, 2, "exhaustion") == 2
    modifiers.add_modifier(g.fx, 1, 51, {"kind": "rule", "rule": "no_gain_actions"})
    actions = g.actions_left
    g.grant_actions(1)
    assert g.actions_left == actions


# ---------------------------------------------------------------- an effect paused inside a combat

def incinerate_flow(bprd, seed=5):
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["liz-sherman"], seed=seed)
    liz, abe = pair(g, "liz", "abe")
    hand_filler(g, 1, 3)
    flow = CombatFlow(g, liz, abe, give(g, 0, "Incinerate"), give(g, 1, "Arcane Dampener"))
    flow.choosers = {0: ControllerChooser(), 1: PanelChooser()}
    return g, flow


def test_pending_choice_roundtrips_an_effect_pause(bprd):
    g, flow = incinerate_flow(bprd)
    wait = flow.run()
    raw = json.loads(json.dumps(wait.choice.to_dict()))
    back = PendingChoice.from_dict(raw, default_player=0, deck_of=lambda _: False)
    assert back.kind == "effect" and back.to_dict() == wait.choice.to_dict()
    for bad in ({**raw, "key": 3}, {**raw, "request": None}, {**raw, "player": "x"}):
        with pytest.raises(KeyError):
            PendingChoice.from_dict(bad, default_player=0, deck_of=lambda _: False)
    with pytest.raises(KeyError):
        PendingChoice.from_dict({**raw, "kind": "mystery"}, default_player=0, deck_of=lambda _: False)


def test_an_effect_pause_survives_saving_the_game_and_the_flow(bprd):
    g, flow = incinerate_flow(bprd)
    twin, twin_flow = incinerate_flow(bprd)
    for f, game in ((flow, g), (twin_flow, twin)):
        wait = f.run()
        assert wait.choice.kind == "effect" and wait.choice.extra["request"]["kind"] == "optional"
    saved_game = json.loads(json.dumps(persist.game_to_dict(g)))
    saved_flow = json.loads(json.dumps(flow.to_dict()))
    assert saved_flow["dsl"]["runs"]["during:atk"]["awaiting"]["kind"] == "optional"

    reloaded = mk(bprd, ("liz-sherman", "abe-sapien"), [], seed=5)
    persist.apply_game(reloaded, saved_game)
    restored = CombatFlow.from_dict(reloaded, saved_flow)
    restored.choosers = {0: ControllerChooser(), 1: PanelChooser()}
    assert restored.pending.kind == "effect" and restored.phase == flow.phase

    def finish(f, game):
        f.resume([True])
        wait = f.run()
        assert wait.choice.extra["request"]["kind"] == "cards"
        discards = wait.choice.extra["request"]["options"][:2]
        f.resume(discards)
        assert f.run() is None
        return (f.result.atk_value, f.result.def_value, f.result.damage, f.result.atk_parts, f.result.def_parts,
                [c.card_id for c in game.players[1].discard], [c.card_id for c in game.players[1].hand],
                game.fighters["abe"].hp)
    outcome = finish(restored, reloaded)
    assert outcome == finish(twin_flow, twin) and outcome[0] == 0


def test_flow_without_dsl_cards_serializes_exactly_as_before(bprd):
    g = mk(bprd, ("medusa", "hellboy"), [])
    med, hb = pair(g, "medusa", "hellboy")
    flow = CombatFlow(g, med, hb, give(g, 0, "Snipe"), None)
    flow.run()
    assert "dsl" not in flow.to_dict()


# ---------------------------------------------------------------- review fixes: mixed DSL / legacy transition

def test_medusas_feint_cannot_cancel_incinerate_and_medusa_gets_the_pay_option(bprd):
    for dsl in (["liz-sherman"], []):
        g = mk(bprd, ("medusa", "liz-sherman"), dsl)
        g.turn = 1
        liz, med = pair(g, "liz", "medusa")
        hand_filler(g, 0, 3)
        g.controllers[0].queue = [[True]]
        res = g.attack(liz, med, give(g, 1, "Incinerate"), give(g, 0, "Feint"))
        assert res.cancelled == set()                                       # uncancelable: the legacy Feint skips it
        if dsl:
            assert [r.kind for r in g.controllers[0].requests][:1] == ["optional"]      # Medusa may pay 2
            assert res.atk_value == 0


def test_incinerate_survives_the_planned_recklessness_cancel_too(bprd):
    g = mk(bprd, ("liz-sherman", "hellboy"), ["liz-sherman"])        # Hellboy legacy: the legacy rule runs
    liz, hb = pair(g, "liz", "hellboy")
    res = g.attack(liz, hb, give(g, 0, "Incinerate"), give(g, 1, "Planned Recklessness"))
    assert "atk" not in res.cancelled


def test_search_does_not_move_a_fighter_pinned_by_burning_barrier(bprd):
    from sparring.search.controller import IsmctsMedusa
    from sparring.search.ismcts import SearchConfig
    for seed in range(2):
        ai = IsmctsMedusa(0, SearchConfig(iterations=60, seed=seed))
        g = Game.new(bprd, seed, controllers={0: ai}, heroes=("medusa", "liz-sherman"))
        g.turn, g.turn_no = 0, 2
        g.begin_turn()
        for f in g.own(0):
            modifiers.add_status(g.fx, "cannot_leave_space", owner=1, until={"event": "end_of_turn"}, fid=f.fid)
        before = {f.fid: f.pos for f in g.own(0)}
        ai.take_turn(g)
        assert ai.fallbacks == 0
        assert {f.fid: f.pos for f in g.own(0)} == {k: v for k, v in before.items() if g.fighters[k].alive}


def test_the_human_is_never_paid_for_or_picked_from_by_the_synchronous_engine(bprd):
    from sparring.combat import resolve_combat
    from sparring.session import HumanProxy
    owed = []
    g = mk(bprd, ("liz-sherman", "hellboy"), ["liz-sherman"])
    g.controllers[1] = HumanProxy(lambda n, reason: owed.append((n, reason)))
    liz, hb = pair(g, "liz", "hellboy")
    hand_filler(g, 1, 4)
    before = list(g.players[1].hand)
    res = resolve_combat(g, liz, hb, give(g, 0, "Incinerate"), None)
    assert res.atk_value == 7 and g.players[1].hand == before and owed == []       # the option is declined, nothing paid


def test_a_forced_discard_from_the_humans_hand_is_owed_to_the_table_not_guessed(bprd):
    """C5: the human discards from their own hand at the table (`Game.force_discard` -> the controller owes it, as
    the legacy Clutching Claws did); the engine never picks the card for them."""
    from sparring.session import HumanProxy
    owed = []
    g = mk(bprd, ("abe-sapien", "liz-sherman"), ["abe-sapien"])
    g.controllers[1] = HumanProxy(lambda n, reason: owed.append((n, reason)))
    abe, liz = pair(g, "abe", "liz")
    hand_filler(g, 1, 3)
    g.fx.turn_start_pos["abe"] = 99
    before = list(g.players[1].hand)
    g.attack(abe, liz, give(g, 0, "Shock And Awe"), None)
    assert owed == [(1, "Shock And Awe")] and g.players[1].hand == before


def test_a_forced_pick_that_is_not_a_hand_discard_is_still_refused_for_the_human(bprd):
    from sparring.effects.choose import ChoiceRequest, TableChooser
    g = mk(bprd, ("abe-sapien", "liz-sherman"), ["abe-sapien"])
    with pytest.raises(NotImplementedError, match="needs the panel"):
        TableChooser().choose(g, ChoiceRequest("fighter", 1, ["abe", "liz"], 1, 1))


@pytest.mark.parametrize("defense,pays", [(None, True), ("Hiss and Slither", False)])
def test_a_bot_pays_for_incinerate_only_when_it_saves_enough(bprd, defense, pays):
    """Default policy of a bot without its own choose_effect: pay when the damage avoided is >= 3 per card (7 vs
    nothing: yes; 7 vs a 4: 3 damage < 6: no)."""
    from sparring.ai_medusa import MedusaAI
    g = mk(bprd, ("medusa", "liz-sherman"), ["liz-sherman"])
    g.controllers[0] = MedusaAI(0)
    g.turn = 1
    liz, med = pair(g, "liz", "medusa")
    hand_filler(g, 0, 3)
    res = g.attack(liz, med, give(g, 1, "Incinerate"), give(g, 0, defense) if defense else None)
    assert (res.atk_value == 0) is pays


def test_a_bot_pays_when_the_hit_would_kill_it(bprd):
    from sparring.ai_medusa import MedusaAI
    g = mk(bprd, ("medusa", "liz-sherman"), ["liz-sherman"])
    g.controllers[0] = MedusaAI(0)
    g.turn = 1
    liz, med = pair(g, "liz", "medusa")
    med.hp = 3
    hand_filler(g, 0, 3)
    res = g.attack(liz, med, give(g, 1, "Incinerate"), give(g, 0, "Hiss and Slither"))       # 3 damage = all her hp
    assert res.atk_value == 0


def test_values_are_clamped_at_zero_at_every_step_in_timing_order(bprd):
    """Ivan (28/10): Flame Lash (1) vs Arcane Dampener (IMMEDIATELY -3) is 0, and the DURING boost then adds to 0."""
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["liz-sherman", "abe-sapien"])
    liz, abe = pair(g, "liz", "abe")
    deck = g.players[0].deck
    bottom = max(deck, key=lambda c: c.boost)
    deck.remove(bottom)
    deck.append(bottom)
    assert bottom.boost == 3
    res = g.attack(liz, abe, give(g, 0, "Flame Lash"), give(g, 1, "Arcane Dampener"))
    assert res.atk_value == 3 and res.atk_parts[:2] == ["Flame Lash (1)", "Arcane Dampener (-1)"]


def test_effects_without_an_acting_player_are_the_enemys_for_damage_but_moves_stay_free(bprd):
    g = mk(bprd, ("liz-sherman", "abe-sapien"), ["abe-sapien"])
    liz, abe = pair(g, "liz", "abe")
    counterhex(g, 1)
    assert g.fx.acting is None
    assert g.damage(abe, 3) == 0                                      # legacy-path effect damage: Counterhex stops it
    assert g.legal_moves(abe, 3) - {abe.pos}                          # the player's own maneuver is not an enemy effect
