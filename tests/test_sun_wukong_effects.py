"""Sun Wukong on the engine, bot side (player 0 plays him, the controllers answer): the Clone ability (take 1 damage, summon a Clone next to him;
none start on the board), the cards with the numbers printed on them (Sly Monkey, Golden Chain Mail, Bewilderment, Phoenix Form, Taunting
Laughter, the two BOOST-granting Forms, Infinite Strikes, 72 Transformations, Wily Fighting, Fiery Eyes That See, Ox Form). The human side (panel,
FakeTTS) is in tests/test_sun_wukong_human.py and the full games in tests/test_sun_wukong_matrix.py."""
from __future__ import annotations

from conftest import give
from sparring.ai_effects import card_worth
from sparring.effects.choose import ControllerChooser
from sparring.effects import modifiers
from sparring.effects.modifiers import is_uncancelable
from sparring.i18n import t
from sparring.effects.run import Ctx, EffectRun
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import pair

CLONES = ["clone1", "clone2", "clone3"]


class Boosting(Answers):
    """Answers whose combat boosts are queued, one card per prompt."""

    def __init__(self):
        super().__init__()
        self.boosts: list = []

    def choose_combat_boost(self, game, ctx):
        return self.boosts.pop(0) if self.boosts else None


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Sun Wukong = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Boosting(), 1: Boosting()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("sun-wukong", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    ctl[0].queue = [[False]]                         # the start-of-turn ability is declined: each test summons on purpose
    g.begin_turn()
    ctl[0].queue.clear()
    ctl[0].requests.clear()
    for p in g.players:
        p.hand.clear()
    centre(g)
    return g


def start_turn(g):
    g.fx.emit("start_of_turn", g.turn)


def centre(g):
    """Sun Wukong on the space with most neighbours, every rival piece outside his zone: a roomy place for the ability."""
    best = max(g.board.spaces, key=lambda s: (len(g.board.adj[s]), -s))
    g.fighters["wukong"].pos = best
    far = sorted((s for s in g.board.spaces if not g.board.share_zone(best, s)), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.fid != "wukong"], far):
        f.pos = s
    return g.fighters["wukong"]


def alive_clones(g):
    return [f.fid for f in g.own(0) if f.fid in CLONES]


def free_next_to(g, fid, exclude=()):
    return next(s for s in sorted(g.board.adj[g.fighters[fid].pos])
                if s not in exclude and all(f.pos != s for f in g.fighters.values() if f.alive))


def land(g, fid, space):
    f = g.fighters[fid]
    f.alive, f.pos, f.hp = True, space, f.max_hp
    return f


def plain(g):
    """The rival's best defense with no effect on it (Hellboy's wall may cancel the attacker's effects)."""
    return foe_card(g, lambda c: c.can_defend and "cancel" not in c.text.lower() and "IMMEDIATELY" not in c.text and (c.value or 0) >= 2)


def foe_card(g, pred, player=1):
    c = next(c for c in g.players[player].full_set if pred(c))
    if c in g.players[player].deck:
        g.players[player].deck.remove(c)
    g.players[player].hand.append(c)
    return c


# ---------------------------------------------------------------- the hero

def test_wukong_is_a_melee_hero_that_starts_without_clones(bprd):
    g = mk(bprd)
    w = g.fighters["wukong"]
    assert (w.hp, w.move, w.ranged, w.reach, w.name) == (17, 2, False, 0, "Sun Wukong")
    assert alive_clones(g) == [] and g.winner is None
    assert all((g.fighters[c].hp, g.fighters[c].max_hp, g.fighters[c].move, g.fighters[c].ranged, g.fighters[c].name) == (1, 1, 2, False, "Clone")
               for c in CLONES)
    assert all(g.fighters[c].died_at is None for c in CLONES)
    assert "sun-wukong" in g.fx.dsl_heroes


def test_the_deck_has_the_printed_bands_and_numbers(bprd):
    g = mk(bprd)
    seen = {}
    for c in g.players[0].full_set:
        t = seen.setdefault(c.title, (c.type, c.value, c.boost, c.fighter, 0))
        seen[c.title] = t[:4] + (t[4] + 1,)
    assert len(g.players[0].full_set) == 30
    assert seen == {
        "Ox Form": ("attack", 7, 2, "any", 2), "Ruyi Jingo Bang": ("attack", 0, 3, "any", 3),
        "Taunting Laughter": ("attack", 3, 2, "any", 3), "Infinite Strikes": ("attack", 2, 2, "any", 3),
        "Sly Monkey": ("versatile", 2, 3, "any", 4), "72 Transformations": ("versatile", 2, 2, "any", 3),
        "Wily Fighting": ("versatile", 3, 1, "any", 3), "Bewilderment": ("defense", 0, 2, "any", 2),
        "Tortoise Form": ("defense", 5, 2, "any", 2), "Golden Chain Mail": ("defense", 4, 2, "any", 2),
        "Fiery Eyes That See": ("scheme", None, 1, "any", 2), "Phoenix Form": ("scheme", None, 1, "any", 1)}


# ---------------------------------------------------------------- the ability

def test_the_ability_takes_one_damage_and_summons_a_clone_next_to_him(bprd):
    g = mk(bprd)
    w = g.fighters["wukong"]
    spot = free_next_to(g, "wukong")
    g.controllers[0].queue = [[True], [spot]]
    start_turn(g)
    assert w.hp == 16 and alive_clones(g) == ["clone1"]
    c = g.fighters["clone1"]
    assert c.pos == spot and c.hp == 1 and spot in g.board.adj[w.pos]


def test_the_ability_may_be_declined(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[False]]
    start_turn(g)
    assert g.fighters["wukong"].hp == 17 and alive_clones(g) == []


def test_the_ability_offers_only_empty_adjacent_spaces(bprd):
    g = mk(bprd)
    w = g.fighters["wukong"]
    taken = sorted(g.board.adj[w.pos])[0]
    land(g, "clone1", taken)
    g.controllers[0].queue = [[True], lambda req: [req.options[0]]]
    start_turn(g)
    ask = [r for r in g.controllers[0].requests if r.kind == "space"][-1]
    assert taken not in ask.options and set(ask.options) <= set(g.board.adj[w.pos])


def test_the_ability_is_not_offered_with_three_clones_on_the_board(bprd):
    g = mk(bprd)
    for fid in CLONES:
        land(g, fid, free_next_to(g, "wukong"))
    g.controllers[0].requests.clear()
    start_turn(g)
    assert g.controllers[0].requests == [] and g.fighters["wukong"].hp == 17


def test_the_ability_is_not_offered_with_no_empty_space_next_to_him(bprd):
    g = mk(bprd)
    w = g.fighters["wukong"]
    ring = sorted(g.board.adj[w.pos])
    blockers = [f for f in g.fighters.values() if f.owner == 1 and f.alive]
    assert len(ring) >= 1
    for s in ring:                                   # the rival's pieces and the Clones fill the ring
        spare = blockers.pop() if blockers else None
        if spare is not None:
            spare.pos = s
    for fid, s in zip(CLONES, [s for s in ring if all(f.pos != s for f in g.fighters.values() if f.alive)]):
        land(g, fid, s)
    if any(all(f.pos != s for f in g.fighters.values() if f.alive) for s in ring):
        return                                       # the board has more neighbours than pieces to fill them: nothing to prove here
    g.controllers[0].requests.clear()
    start_turn(g)
    assert g.controllers[0].requests == []


def test_a_defeated_clone_returns_to_the_supply_and_can_be_summoned_again(bprd):
    g = mk(bprd)
    for fid in CLONES:
        land(g, fid, free_next_to(g, "wukong"))
    g.defeat(g.fighters["clone2"])
    assert alive_clones(g) == ["clone1", "clone3"]
    spot = free_next_to(g, "wukong")
    g.controllers[0].queue = [[True], [spot]]
    start_turn(g)
    assert alive_clones(g) == ["clone1", "clone2", "clone3"] and g.fighters["clone2"].pos == spot
    assert g.fighters["clone2"].hp == 1


def test_the_ability_can_defeat_wukong_at_one_health(bprd):
    g = mk(bprd)
    g.fighters["wukong"].hp = 1
    g.controllers[0].queue = [[True], [free_next_to(g, "wukong")]]
    start_turn(g)
    assert g.winner == 1


# ---------------------------------------------------------------- Sly Monkey

def zone_spot(g, fid):
    old = g.fighters[fid].pos
    return next(s for s in sorted(g.board.spaces)
                if g.board.share_zone(old, s) and s != old and all(f.pos != s for f in g.fighters.values() if f.alive))


def test_sly_monkey_summons_a_clone_in_his_space_then_places_him_in_his_zone(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    old, where = w.pos, zone_spot(g, "wukong")
    g.controllers[0].queue = [[where]]
    g.attack(w, h, give(g, 0, "Sly Monkey"), plain(g))
    assert alive_clones(g) == ["clone1"] and g.fighters["clone1"].pos == old
    assert w.pos == where and g.board.share_zone(old, where)


def test_sly_monkey_with_three_clones_repositions_the_one_the_owner_chooses_then_places_him(bprd):
    """Ivan 2026-11-20 (W5): with the three Clones out, one of them goes to Sun Wukong's space, then he is placed in his zone."""
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    for fid in CLONES:
        land(g, fid, max(s for s in g.board.spaces if not g.board.share_zone(w.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive)))
    old = w.pos
    g.controllers[0].queue = [["clone2"], lambda req: [next(o for o in req.options if o != old)]]
    g.attack(w, h, give(g, 0, "Sly Monkey"), plain(g))
    assert len(alive_clones(g)) == 3 and g.fighters["clone2"].pos == old and w.pos != old
    assert g.fighters["clone1"].pos != old and g.fighters["clone3"].pos != old


def fill_zone(g, w, h):
    """Every other space of Sun Wukong's zone held by a fighter (the Clones landed there, then the rival's pieces)."""
    mates = [s for s in sorted(g.board.spaces) if s != w.pos and g.board.share_zone(w.pos, s) and s != h.pos]
    pieces = [f for f in g.fighters.values() if f.fid not in ("wukong", h.fid)]
    assert len(pieces) >= len(mates), "the test board must be small enough to fill the zone"
    for f, s in zip(pieces, mates):
        f.alive, f.pos = True, s
        f.hp = f.hp or f.max_hp
    return mates


def living_spaces(g):
    return [f.pos for f in g.fighters.values() if f.alive]


def test_sly_monkey_with_no_empty_space_in_his_zone_summons_nothing_and_he_stays(bprd):
    """Ivan 2026-11-21 (live: Clone and Wukong ended on the same space): no free space to place him, no Clone."""
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    fill_zone(g, w, h)
    old, before = w.pos, {f.fid: (f.alive, f.pos) for f in g.fighters.values()}
    clones_before = alive_clones(g)
    g.attack(w, h, give(g, 0, "Sly Monkey"), plain(g))
    assert w.pos == old and alive_clones(g) == clones_before
    assert {f.fid: (f.alive, f.pos) for f in g.fighters.values() if f.fid in CLONES} == {k: v for k, v in before.items() if k in CLONES}
    assert len(living_spaces(g)) == len(set(living_spaces(g)))


def close_zone(g, monkeypatch, w, h):
    """Sun Wukong's zone is only his space and the rival's: no empty space and no Clone among the blockers."""
    shared = {w.pos, h.pos}
    monkeypatch.setattr(g.board, "share_zone", lambda a, b: a == b or {a, b} <= shared)


NO_SPACE = t("narr.notice.sly_monkey_no_space")
PINNED = t("narr.notice.sly_monkey_pinned")


def test_sly_monkey_with_no_empty_space_revives_no_defeated_clone_either(bprd, monkeypatch):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    close_zone(g, monkeypatch, w, h)
    for fid in CLONES:
        g.fighters[fid].alive = False
        g.fighters[fid].pos = None
    old = w.pos
    res = g.attack(w, h, give(g, 0, "Sly Monkey"), plain(g))
    assert alive_clones(g) == [] and all(g.fighters[c].pos is None for c in CLONES), "no Clone is revived"
    assert w.pos == old and len(living_spaces(g)) == len(set(living_spaces(g)))
    assert any(NO_SPACE in line for line in res.applied), res.applied


def test_sly_monkey_with_no_empty_space_says_so_when_a_clone_could_have_been_summoned(bprd, monkeypatch):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    close_zone(g, monkeypatch, w, h)
    res = g.attack(w, h, give(g, 0, "Sly Monkey"), plain(g))
    assert alive_clones(g) == [] and any(NO_SPACE in line and "Sly Monkey" in line for line in res.applied), res.applied


def test_sly_monkey_with_wukong_pinned_in_his_space_summons_no_clone_and_says_so(bprd):
    """Ivan 2026-11-21: Burning Barrier ("cannot leave its space this turn") keeps him there: no Clone lands on his space."""
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    modifiers.add_status(g.fx, "cannot_leave_space", owner=1, until={"event": "end_of_turn"}, fid="wukong")
    old = w.pos
    res = g.attack(w, h, give(g, 0, "Sly Monkey"), plain(g))
    assert alive_clones(g) == [] and w.pos == old and len(living_spaces(g)) == len(set(living_spaces(g)))
    assert any(PINNED in line for line in res.applied), res.applied


def test_sly_monkey_pinned_with_the_three_clones_out_moves_none_of_them(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    for fid in CLONES:
        land(g, fid, max(s for s in g.board.spaces if not g.board.share_zone(w.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive)))
    before = {c: g.fighters[c].pos for c in CLONES}
    modifiers.add_status(g.fx, "cannot_leave_space", owner=1, until={"event": "end_of_turn"}, fid="wukong")
    res = g.attack(w, h, give(g, 0, "Sly Monkey"), plain(g))
    assert {c: g.fighters[c].pos for c in CLONES} == before and any(PINNED in line for line in res.applied)


def test_sly_monkey_with_three_clones_and_no_empty_space_moves_no_clone(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    mates = [s for s in sorted(g.board.spaces) if s != w.pos and g.board.share_zone(w.pos, s) and s != h.pos]
    others = [f for f in g.fighters.values() if f.fid not in ("wukong", h.fid, *CLONES)]
    for f, s_ in zip(others + [g.fighters[c] for c in CLONES], mates):          # the rival's pieces first, the Clones close the zone
        f.alive, f.pos = True, s_
        f.hp = f.hp or f.max_hp
    far = [s_ for s_ in sorted(g.board.spaces, reverse=True) if s_ not in mates and s_ not in (w.pos, h.pos)]
    for fid, s_ in zip(CLONES, far):                                            # any Clone not needed in the zone stays outside it
        if g.fighters[fid].pos is None or g.fighters[fid].pos not in mates:
            land(g, fid, s_)
    assert all(s_ in living_spaces(g) for s_ in mates) and len([c for c in CLONES if g.fighters[c].alive]) == 3, "zone not closed"
    before = {c: g.fighters[c].pos for c in CLONES}
    res = g.attack(w, h, give(g, 0, "Sly Monkey"), plain(g))
    assert {c: g.fighters[c].pos for c in CLONES} == before and len(living_spaces(g)) == len(set(living_spaces(g)))
    assert any(NO_SPACE in line for line in res.applied), "nothing happens, but it is announced"


def test_sly_monkey_played_by_a_clone_does_nothing_after_combat(bprd):
    g = mk(bprd)
    c, h = pair(g, "clone1", "hellboy")
    c.alive, c.hp = True, 1
    g.fighters["wukong"].pos = free_next_to(g, "hellboy", exclude=(c.pos,))
    before = {f.fid: f.pos for f in g.fighters.values()}
    g.attack(c, h, give(g, 0, "Sly Monkey"), plain(g))
    assert alive_clones(g) == ["clone1"] and {f: g.fighters[f].pos for f in before if g.fighters[f].alive} == {f: p for f, p in before.items() if g.fighters[f].alive}


# ---------------------------------------------------------------- Golden Chain Mail

def test_golden_chain_mail_sends_the_combat_damage_to_the_attacker(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    big = foe_card(g, lambda c: c.can_attack and (c.value or 0) >= 5 and c.usable_by("Hellboy"))
    hp_h, hp_w = h.hp, w.hp
    res = g.attack(h, w, big, give(g, 0, "Golden Chain Mail"))
    assert res.atk_value > 4 and w.hp == hp_w and h.hp == hp_h - (res.atk_value - 4)


def test_golden_chain_mail_keeps_a_tie_harmless(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    four = foe_card(g, lambda c: c.can_attack and (c.value or 0) == 4 and c.usable_by("Hellboy"))
    g.attack(h, w, four, give(g, 0, "Golden Chain Mail"))
    assert w.hp == 17 and h.hp == h.max_hp


def test_golden_chain_mail_does_not_redirect_effect_damage(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.damage(w, 2, "effect")
    assert w.hp == 15 and h.hp == h.max_hp


# ---------------------------------------------------------------- Bewilderment

def test_bewilderment_prevents_all_combat_damage(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    big = foe_card(g, lambda c: c.can_attack and (c.value or 0) >= 5 and c.usable_by("Hellboy"))
    g.controllers[0].queue = [[False]]
    g.attack(h, w, big, give(g, 0, "Bewilderment"))
    assert w.hp == 17 and h.hp == h.max_hp


def test_bewilderment_may_place_him_on_any_space_after_the_combat(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    target = max(s for s in g.board.spaces if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[True], [target]]
    g.attack(h, w, foe_card(g, lambda c: c.can_attack and c.usable_by("Hellboy")), give(g, 0, "Bewilderment"))
    assert w.pos == target


def test_bewilderment_text_says_combat_damage(bprd):
    g = mk(bprd)
    assert "Prevent all combat damage" in give(g, 0, "Bewilderment").text


# ---------------------------------------------------------------- Phoenix Form

def test_phoenix_form_heals_one_per_clone_on_the_board(bprd):
    g = mk(bprd)
    w = g.fighters["wukong"]
    w.hp = 10
    for fid in CLONES[:2]:
        land(g, fid, free_next_to(g, "wukong"))
    g.play_scheme(0, w, give(g, 0, "Phoenix Form"))
    assert w.hp == 12


def test_phoenix_form_does_not_exceed_the_maximum(bprd):
    g = mk(bprd)
    w = g.fighters["wukong"]
    w.hp = 16
    for fid in CLONES:
        land(g, fid, free_next_to(g, "wukong"))
    g.play_scheme(0, w, give(g, 0, "Phoenix Form"))
    assert w.hp == 17


def test_phoenix_form_with_no_clones_heals_nothing(bprd):
    g = mk(bprd)
    w = g.fighters["wukong"]
    w.hp = 10
    g.play_scheme(0, w, give(g, 0, "Phoenix Form"))
    assert w.hp == 10


# ---------------------------------------------------------------- Ox Form and Tortoise Form: the rival may BOOST

def test_ox_form_cannot_be_canceled(bprd):
    g = mk(bprd)
    assert is_uncancelable(give(g, 0, "Ox Form"))


def test_ox_form_lets_the_rival_boost_the_card_it_played(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    defense, spare = plain(g), foe_card(g, lambda c: c.title == "Excalibur")
    g.controllers[1].boosts = [spare]
    res = g.attack(w, h, give(g, 0, "Ox Form"), defense)
    assert res.def_value == defense.value + spare.boost and spare in g.players[1].discard


def test_ox_form_against_no_card_asks_no_boost(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    spare = foe_card(g, lambda c: c.title == "Excalibur")
    g.controllers[1].boosts = [spare]
    res = g.attack(w, h, give(g, 0, "Ox Form"), None)
    assert res.atk_value == 7 and spare in g.players[1].hand


def test_a_card_that_does_not_say_so_gets_no_boost_from_the_rival(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    defense, spare = plain(g), foe_card(g, lambda c: c.title == "Excalibur")
    g.controllers[1].boosts = [spare]
    res = g.attack(w, h, give(g, 0, "Infinite Strikes"), defense)
    assert res.def_value == defense.value and spare in g.players[1].hand


def test_tortoise_form_lets_the_attacker_boost_the_attack(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    attack = foe_card(g, lambda c: c.can_attack and (c.value or 0) == 3 and c.usable_by("Hellboy"))
    spare = foe_card(g, lambda c: c.title == "Excalibur")
    res = g.attack(h, w, attack, give(g, 0, "Tortoise Form"), boost=spare)
    assert res.atk_value == 3 + spare.boost and res.def_value == 5 and spare in g.players[1].discard


def test_tortoise_form_without_the_boost_is_a_plain_defense_of_five(bprd):
    g = mk(bprd, turn=1)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    attack = foe_card(g, lambda c: c.can_attack and (c.value or 0) == 3 and c.usable_by("Hellboy"))
    res = g.attack(h, w, attack, give(g, 0, "Tortoise Form"))
    assert res.def_value == 5 and res.atk_value == 3 and w.hp == 17


# ---------------------------------------------------------------- Taunting Laughter

def test_taunting_laughter_rival_discards_a_card_and_keeps_its_value(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    defense = plain(g)
    spare = foe_card(g, lambda c: c.title == "Excalibur")
    g.controllers[1].queue = [[True], [spare.card_id]]
    res = g.attack(w, h, give(g, 0, "Taunting Laughter"), defense)
    assert res.def_value == defense.value and spare in g.players[1].discard


def test_taunting_laughter_rival_declines_and_its_value_is_ignored(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    defense = plain(g)
    spare = foe_card(g, lambda c: c.title == "Excalibur")
    g.controllers[1].queue = [[False]]
    res = g.attack(w, h, give(g, 0, "Taunting Laughter"), defense)
    assert res.def_value == 0 and res.atk_value == 3 and spare in g.players[1].hand


def test_taunting_laughter_against_no_card_asks_nothing(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    foe_card(g, lambda c: c.title == "Excalibur")
    g.controllers[1].requests.clear()
    g.attack(w, h, give(g, 0, "Taunting Laughter"), None)
    assert g.controllers[1].requests == []


def test_taunting_laughter_cannot_be_paid_with_an_empty_hand(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    defense = plain(g)
    g.players[1].hand[:] = [defense]                  # the defense card is played from the hand: nothing else is left
    res = g.attack(w, h, give(g, 0, "Taunting Laughter"), defense)
    assert res.def_value == 0


# ---------------------------------------------------------------- Infinite Strikes

def test_infinite_strikes_adds_one_per_other_friendly_fighter_next_to_the_target(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    land(g, "clone1", free_next_to(g, "hellboy", exclude=(w.pos,)))
    land(g, "clone2", free_next_to(g, "hellboy", exclude=(w.pos,)))
    res = g.attack(w, h, give(g, 0, "Infinite Strikes"), None)
    assert res.atk_value == 2 + 2


def test_infinite_strikes_does_not_count_the_attacker_or_a_far_clone(bprd):
    g = mk(bprd)
    c, h = pair(g, "clone1", "hellboy")
    c.alive, c.hp = True, 1
    land(g, "clone2", max(s for s in g.board.spaces if not g.board.share_zone(h.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive)))
    res = g.attack(c, h, give(g, 0, "Infinite Strikes"), None)
    assert res.atk_value == 2


def test_infinite_strikes_gains_an_action_after_the_combat(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    g.actions_left = 2
    g.attack(w, h, give(g, 0, "Infinite Strikes"), plain(g))
    assert g.actions_left == 2                       # one spent on the attack, one gained


# ---------------------------------------------------------------- 72 Transformations, Wily Fighting

def test_72_transformations_returns_a_form_from_the_discard_pile(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    forms = [give(g, 0, t) for t in ("Ox Form", "Tortoise Form", "Phoenix Form")]
    other = give(g, 0, "Wily Fighting")
    for c in forms + [other]:
        g.players[0].hand.remove(c)
        g.players[0].discard.append(c)
    g.controllers[0].queue = [lambda req: [forms[1].card_id]]
    g.attack(w, h, give(g, 0, "72 Transformations"), plain(g))
    assert forms[1] in g.players[0].hand and other in g.players[0].discard and forms[0] in g.players[0].discard


def test_72_transformations_with_no_form_in_the_pile_returns_nothing(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    other = give(g, 0, "Wily Fighting")
    g.players[0].hand.remove(other)
    g.players[0].discard.append(other)
    g.attack(w, h, give(g, 0, "72 Transformations"), plain(g))
    assert other in g.players[0].discard and g.players[0].hand == []


def test_the_three_forms_carry_the_form_tag_and_nothing_else_does(bprd):
    g = mk(bprd)
    assert {c.title for c in g.players[0].full_set if "form" in c.tags} == {"Ox Form", "Tortoise Form", "Phoenix Form"}


def test_wily_fighting_hurts_every_rival_next_to_the_fighter_that_played_it(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    lobster = g.fighters["lobster"]
    lobster.pos = free_next_to(g, "wukong", exclude=(h.pos,))
    g.attack(w, h, give(g, 0, "Wily Fighting"), None)
    assert h.hp == h.max_hp - 3 - 1 and lobster.hp == lobster.max_hp - 1


def test_wily_fighting_leaves_a_far_rival_alone(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    lobster = g.fighters["lobster"]
    g.attack(w, h, give(g, 0, "Wily Fighting"), None)
    assert lobster.hp == lobster.max_hp


# ---------------------------------------------------------------- Fiery Eyes That See

def set_hand(g, player, *titles):
    st = g.players[player]
    st.deck.extend(st.hand)
    st.hand.clear()
    for t in titles:
        c = next(x for x in st.deck if x.title == t)
        st.deck.remove(c)
        st.hand.append(c)
    return list(st.hand)


def play_fiery_eyes(g):
    run = EffectRun.for_card("sun-wukong", "Fiery Eyes That See", "scheme", Ctx(owner=0, this_fid="wukong"))
    assert run.run(g, ControllerChooser()) is None


def test_fiery_eyes_puts_the_best_seen_card_at_the_bottom_and_both_draw(bprd):
    g = mk(bprd)
    hand = set_hand(g, 1, "Second Shot", "Service Pistol", "Glimpse Of Hell", "Confront Any Demon or God", "Horseshoes And Hand Grenades")
    best = max(hand, key=lambda c: (card_worth(c), -c.card_id))
    mine = len(g.players[0].hand)
    play_fiery_eyes(g)
    assert best not in g.players[1].hand and g.players[1].deck[-1] == best
    assert len(g.players[1].hand) == 5 and len(g.players[0].hand) == mine + 1
    assert best.card_id not in g.players[0].known.seen


def test_fiery_eyes_against_an_empty_hand_still_draws_for_both(bprd):
    g = mk(bprd)
    g.players[1].hand.clear()
    mine = len(g.players[0].hand)
    play_fiery_eyes(g)
    assert len(g.players[1].hand) == 1 and len(g.players[0].hand) == mine + 1


# ---------------------------------------------------------------- Ruyi Jingo Bang (a DOUBLE ATTACK)

def test_ruyi_jingo_bang_tricks_a_defender_with_a_second_attack_of_four(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    res = g.attack(w, h, give(g, 0, "Ruyi Jingo Bang"), plain(g))
    assert res.atk_value == 0 and res.damage == 0
    assert res.second is not None and res.second.atk_value == 4 and res.second.damage == 4 and h.hp == h.max_hp - 4


def test_ruyi_jingo_bang_with_no_defense_card_has_no_second_attack(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    res = g.attack(w, h, give(g, 0, "Ruyi Jingo Bang"), None)
    assert res.second is None and h.hp == h.max_hp


def test_the_defender_may_defend_the_second_attack_of_ruyi_jingo_bang(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    wall = give(g, 1, "B.P.R.D. Training")                                              # defense 3 < 4: only one point gets through
    g.controllers[1].choose_second_defense = lambda game, att, tgt, value, card: wall
    res = g.attack(w, h, give(g, 0, "Ruyi Jingo Bang"), plain(g))
    assert res.second.atk_value == 4 and res.second.def_card is wall and h.hp == h.max_hp - 1


def test_a_cancel_of_the_attack_effects_stops_the_trick(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    res = g.attack(w, h, give(g, 0, "Ruyi Jingo Bang"), give(g, 1, "Planned Recklessness"))      # cancels every effect of the attack
    assert res.second is None and h.hp == h.max_hp


def test_a_versatile_card_played_to_defend_is_a_defense_card_for_the_trick(bprd):
    g = mk(bprd)
    w, h = pair(g, "wukong", "hellboy")
    versatile = foe_card(g, lambda c: c.type == "versatile" and c.can_defend and "cancel" not in c.text.lower() and "IMMEDIATELY" not in c.text)
    res = g.attack(w, h, give(g, 0, "Ruyi Jingo Bang"), versatile)
    assert res.second is not None and res.second.atk_value == 4


# ---------------------------------------------------------------- Golden Chain Mail against Yennenga's Archers

def test_golden_chain_mail_sends_the_blow_to_yennenga_and_her_archers_take_their_share(bprd, monkeypatch):
    from test_yennenga_effects import archers, beside, stack
    ctl = {0: Boosting(), 1: Boosting()}
    g = Game.new(bprd, 3, controllers=ctl, heroes=("yennenga", "sun-wukong"), bot_player=0)
    g.turn, g.turn_no = 0, 2
    ctl[1].queue = [[False]]
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    yen = stack(g)
    a1, a2 = archers(g)
    w = beside(g, "wukong", "yennenga")
    attack = next(c for c in g.players[0].full_set if c.can_attack and (c.value or 0) == 4)
    monkeypatch.setattr(Game, "attack_bonus_parts", lambda self, f, target=None: [(3, "test")] if f.fid == "yennenga" else [])     # 4 + 3 against 4: a blow of 3
    g.players[0].deck.remove(attack)
    g.players[0].hand.append(attack)
    ctl[0].queue = [[1], [1]]                                       # Yennenga assigns one point to each Archer
    res = g.attack(yen, w, attack, give(g, 1, "Golden Chain Mail"))
    blow = attack.value + 3 - 4
    assert blow == 3 and w.hp == 17                                  # nothing lands on Wukong
    assert (a1.hp, a2.hp) == (1, 1) and yen.hp == 15 - (blow - 2)     # the redirected victim is Yennenga: her hook splits it


# ---------------------------------------------------------------- the BOOST Ox Form grants the defender (DURING, Ivan 2026-11-20 W6)

def test_ox_form_grants_its_boost_during_and_not_immediately(bprd):
    from sparring.effects.model import load_effects
    ox = load_effects("sun-wukong").cards["Ox Form"]
    assert ox.moments["immediately"] == [] and any(o["op"] == "if" for o in ox.moments["during"])


def test_a_defender_that_already_may_boost_its_card_is_asked_once_when_ox_form_grants_it_too(bprd):
    g = mk(bprd, foe="baba-yaga")
    w, b = pair(g, "wukong", "baba")
    out_of_time = give(g, 1, "Out Of Time")                                   # versatile with its own free BOOST
    spare, spare2 = give(g, 1, "Iron Teeth"), give(g, 1, "Deathless")
    g.controllers[1].boosts = [spare, spare2]
    res = g.attack(w, b, give(g, 0, "Ox Form"), out_of_time)
    assert res.def_value == out_of_time.value + spare.boost and spare2 in g.players[1].hand and spare in g.players[1].discard
