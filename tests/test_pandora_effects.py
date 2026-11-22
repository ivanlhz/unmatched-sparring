"""Pandora on the engine, bot side (player 0 plays her, the controllers answer): Pandora's Box (the mandatory first reveal, the choice to keep
revealing, three feathers, the damage, the seven Miseries, the shuffle back at the end of her turn) and the twelve cards with the numbers printed
on them. The human side (panel, FakeTTS) is in tests/test_pandora_human.py, the AI in tests/test_pandora_ai.py and the full games in
tests/test_pandora_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.effects import modifiers, plugins_pandora
from sparring.effects.run import EffectRun
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import pair

IDX = {"Woe": 0, "Toil": 1, "Pain": 2, "Misfortune": 3, "Hope": 4, "Greed": 5, "Confusion": 6}
KAKO = ["kakodaemon1", "kakodaemon2"]


@pytest.fixture
def order(monkeypatch):
    """The Miseries the Box turns up, in order (the engine draws them at random when they are revealed): a list to extend."""
    seq: list[int] = []

    def sample(self, items, n):
        want = seq.pop(0)
        assert want in items, f"{want} is not among the unrevealed {items}"
        return [want]

    monkeypatch.setattr(EffectRun, "random_sample", sample)
    return seq


class Boxed(Answers):
    """Answers the 'keep revealing?' question from `keeps` (True when it runs out) and everything else from the queue."""

    def __init__(self):
        super().__init__()
        self.keeps: list[bool] = []

    def choose_effect(self, game, req):
        if req.kind == "optional" and req.extra.get("box") == "open":
            self.requests.append(req)
            return [self.keeps.pop(0) if self.keeps else True]
        return super().choose_effect(game, req)


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Pandora = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands, the start of the turn not run yet."""
    ctl = {0: Boxed(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("pandora", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn(emit=False)
    for p in g.players:
        p.hand.clear()
    centre(g)
    return g


def start_turn(g):
    g.fx.emit("start_of_turn", g.turn)


def centre(g):
    """Pandora on the space with most neighbours, every rival piece outside her zone."""
    best = max(g.board.spaces, key=lambda s: (len(g.board.adj[s]), -s))
    g.fighters["pandora"].pos = best
    far = sorted((s for s in g.board.spaces if not g.board.share_zone(best, s)), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.alive and f.fid != "pandora"], far):
        f.pos = s
    return g.fighters["pandora"]


def counter(g, name, player=0):
    return g.fx.counter_value(player, name)


def kakodaemons(g):
    return [f.fid for f in g.own(0) if f.fid in KAKO]


def keep_asks(g):
    return [r for r in g.controllers[0].requests if r.kind == "optional" and r.extra.get("box") == "open"]


def free_next_to(g, fid, exclude=()):
    return next(s for s in sorted(g.board.adj[g.fighters[fid].pos])
                if s not in exclude and all(f.pos != s for f in g.fighters.values() if f.alive))


def plain(g):
    c = next(c for c in g.players[1].full_set if c.can_defend and "cancel" not in c.text.lower() and "IMMEDIATELY" not in c.text and (c.value or 0) >= 2)
    if c in g.players[1].deck:
        g.players[1].deck.remove(c)
    g.players[1].hand.append(c)
    return c


# ---------------------------------------------------------------- the hero

def test_pandora_is_a_melee_hero_that_starts_without_kakodaemons(bprd):
    g = mk(bprd)
    p = g.fighters["pandora"]
    assert (p.hp, p.move, p.ranged, p.name) == (14, 2, False, "Pandora")
    assert kakodaemons(g) == []
    assert all((g.fighters[k].hp, g.fighters[k].move, g.fighters[k].ranged, g.fighters[k].name) == (1, 2, False, "Kakodaemon") for k in KAKO)
    assert all(g.fighters[k].died_at is None for k in KAKO)
    assert "pandora" in g.fx.dsl_heroes


def test_the_deck_has_the_printed_bands_and_numbers(bprd):
    g = mk(bprd)
    seen = {}
    for c in g.players[0].full_set:
        t = seen.setdefault(c.title, (c.type, c.value, c.boost, c.fighter, 0))
        seen[c.title] = t[:4] + (t[4] + 1,)
    assert len(g.players[0].full_set) == 30
    assert seen == {
        "Hera's Curiosity": ("attack", 3, 4, "Pandora", 3), "Hindsight": ("attack", 3, 2, "Pandora", 3),
        "Aphrodite's Beauty": ("attack", 0, 3, "any", 3), "Spite": ("attack", 3, 2, "Kakodaemon", 2),
        "Divine Intervention": ("versatile", 3, 1, "Pandora", 2), "Feint": ("versatile", 2, 2, "any", 3),
        "Guided by the Fates": ("versatile", 2, 3, "any", 3), "Malice": ("versatile", 2, 2, "Kakodaemon", 2),
        "Offering to the Gods": ("defense", 2, 1, "Pandora", 2), "Celestial Raiments": ("defense", 0, 3, "Pandora", 2),
        "Zeus's Mischief": ("scheme", None, 1, "Pandora", 2), "Forged by Hephaestus": ("scheme", None, 1, "any", 3)}


def test_only_a_kakodaemon_plays_spite_and_malice(bprd):
    g = mk(bprd)
    for title in ("Spite", "Malice"):
        c = give(g, 0, title)
        assert c.usable_by("Kakodaemon") and not c.usable_by("Pandora")


# ---------------------------------------------------------------- Pandora's Box

def test_the_first_reveal_is_mandatory_and_asks_nothing(bprd, order):
    g = mk(bprd)
    order.append(IDX["Misfortune"])
    g.controllers[0].keeps = [False]
    start_turn(g)
    asks = keep_asks(g)
    assert len(asks) == 1 and asks[0].extra["revealed"] == 1 and asks[0].extra["feathers"] == 2
    assert counter(g, "revealed") == 1 and g.fighters["pandora"].hp == 14


def test_declining_to_keep_revealing_costs_no_damage(bprd, order):
    g = mk(bprd)
    order.extend([IDX["Toil"], IDX["Hope"], IDX["Greed"]])      # Hope looks at the next one, Greed, and she leaves it there
    g.controllers[0].keeps = [True, False]
    start_turn(g)
    assert counter(g, "revealed") == 2 and g.fighters["pandora"].hp == 14 and counter(g, "box_done") == 1
    assert counter(g, "box_top") == IDX["Greed"] + 1            # it stays on top until the Box is shuffled


def test_three_feathers_stop_her_and_cost_one_damage_per_revealed_miseries(bprd, order):
    g = mk(bprd)
    order.extend([IDX["Toil"], IDX["Pain"], IDX["Greed"]])        # 1 + 1 + 1 feathers
    g.controllers[0].keeps = [True, True]
    start_turn(g)
    assert len(keep_asks(g)) == 2                                 # nothing is asked after the third
    assert counter(g, "revealed") == 3 and g.fighters["pandora"].hp == 14 - 3
    assert len(g.players[0].hand) == 1                            # Greed's card


def test_a_two_feather_misery_counts_two_and_the_one_that_reaches_three_is_counted(bprd, order):
    g = mk(bprd)
    order.extend([IDX["Misfortune"], IDX["Hope"], IDX["Greed"]])     # 2, 2, 3 feathers
    g.controllers[0].keeps = [True, True]
    g.controllers[0].requests.clear()
    start_turn(g)
    assert g.fighters["pandora"].hp == 14 - 3 and counter(g, "revealed") == 3


def test_misfortune_then_a_one_feather_misery_stops_with_two_damage(bprd, order):
    g = mk(bprd)
    order.extend([IDX["Misfortune"], IDX["Toil"]])
    g.controllers[0].keeps = [True]
    start_turn(g)
    assert g.fighters["pandora"].hp == 14 - 2 and len(keep_asks(g)) == 1


@pytest.mark.parametrize("seed", range(40))
def test_revealing_to_the_end_always_stops_at_three_feathers_and_costs_the_revealed_count(bprd, seed):
    g = mk(bprd, seed=seed)
    g.fighters["pandora"].hp = g.fighters["pandora"].max_hp = 40
    g.controllers[0].keeps = [True] * 8                       # she always keeps revealing
    start_turn(g)
    mask = counter(g, "box_mask")
    assert plugins_pandora.feathers(mask) >= 3 and counter(g, "box_done") == 1
    assert g.fighters["pandora"].hp == 40 - len(plugins_pandora.revealed(mask)) == 40 - counter(g, "revealed")


def test_the_miseries_are_shuffled_back_at_the_end_of_her_turn(bprd, order):
    g = mk(bprd)
    order.extend([IDX["Toil"], IDX["Hope"], IDX["Greed"]])
    g.controllers[0].keeps = [True, False]
    start_turn(g)
    assert counter(g, "box_mask") != 0
    g.end_turn()
    assert [counter(g, n) for n in ("box_mask", "revealed", "box_top", "box_done", "box_current")] == [0, 0, 0, 0, 0]


def test_the_revealed_count_is_zero_once_her_turn_is_over(bprd, order):
    g = mk(bprd)
    order.extend([IDX["Toil"], IDX["Pain"], IDX["Greed"]])
    start_turn(g)
    assert counter(g, "revealed") == 3
    g.end_turn()                                        # the rival's turn: the Miseries are back in the Box
    assert counter(g, "revealed") == 0
    g.end_turn()
    g.actions_left = 2
    p, h = pair(g, "pandora", "hellboy")
    assert g.attack(p, h, give(g, 0, "Hera's Curiosity"), plain(g)).atk_value == 3


def _wall(g):
    """A defense of 3 with nothing that touches Pandora (B.P.R.D. Training), in the rival's hand: a 3 attack does not get through it."""
    c = next(c for c in g.players[1].full_set if c.title == "B.P.R.D. Training")
    g.players[1].deck.remove(c)
    g.players[1].hand.append(c)
    return c


def _any_attack(g):
    c = next(c for c in g.players[1].full_set if c.can_attack and not c.text.count("IMMEDIATELY"))
    g.players[1].hand.append(c)
    return c


# ---------------------------------------------------------------- the seven Miseries

def test_woe_summons_a_kakodaemon_in_pandoras_zone(bprd, order):
    g = mk(bprd)
    order.append(IDX["Woe"])
    g.controllers[0].keeps = [False]
    start_turn(g)
    out = kakodaemons(g)
    assert len(out) == 1
    k, p = g.fighters[out[0]], g.fighters["pandora"]
    assert k.hp == 1 and g.board.share_zone(k.pos, p.pos) and k.pos != p.pos


def test_woe_with_both_kakodaemons_out_does_nothing(bprd, order):
    g = mk(bprd)
    for fid in KAKO:
        f = g.fighters[fid]
        f.alive, f.hp, f.pos = True, 1, free_next_to(g, "pandora", exclude=[x.pos for x in g.fighters.values() if x.alive])
    order.append(IDX["Woe"])
    g.controllers[0].keeps = [False]
    start_turn(g)
    assert sorted(kakodaemons(g)) == KAKO and all(g.fighters[k].hp == 1 for k in KAKO)


def test_woe_brings_back_a_defeated_kakodaemon_before_taking_one_from_the_reserve(bprd, order):
    g = mk(bprd)
    k = g.fighters["kakodaemon1"]
    k.alive, k.hp, k.died_at = False, 0, 1
    order.append(IDX["Woe"])
    g.controllers[0].keeps = [False]
    start_turn(g)
    assert kakodaemons(g) == ["kakodaemon1"] and k.hp == 1


def test_toil_adds_one_to_pandoras_attacks_this_turn_and_not_to_a_kakodaemons(bprd, order):
    g = mk(bprd)
    order.append(IDX["Toil"])
    g.controllers[0].keeps = [False]
    start_turn(g)
    g.actions_left = 5
    p, h = pair(g, "pandora", "hellboy")
    assert g.attack(p, h, give(g, 0, "Hindsight"), None).atk_value == 3 + 1
    k = g.fighters["kakodaemon1"]
    k.alive, k.hp = True, 1
    k2, h = pair(g, "kakodaemon1", "hellboy")
    assert g.attack(k2, h, give(g, 0, "Spite"), None).atk_value == 3
    g.end_turn()
    g.end_turn()
    g.actions_left = 2
    p, h = pair(g, "pandora", "hellboy")
    assert g.attack(p, h, give(g, 0, "Hindsight"), None).atk_value == 3          # it lasted the turn


def test_pain_hurts_each_opposing_fighter_adjacent_to_pandora_and_nobody_else(bprd, order):
    g = mk(bprd)
    p = g.fighters["pandora"]
    near, far = g.fighters["hellboy"], g.fighters["lobster"]
    near.pos = free_next_to(g, "pandora")
    ally = g.fighters["kakodaemon1"]
    ally.alive, ally.hp, ally.pos = True, 1, free_next_to(g, "pandora", exclude=[near.pos])
    order.append(IDX["Pain"])
    g.controllers[0].keeps = [False]
    hp0 = (near.hp, far.hp)
    start_turn(g)
    assert (near.hp, far.hp) == (hp0[0] - 1, hp0[1]) and ally.hp == 1 and p.hp == 14


def test_greed_draws_a_card(bprd, order):
    g = mk(bprd)
    order.append(IDX["Greed"])
    g.controllers[0].keeps = [False]
    start_turn(g)
    assert len(g.players[0].hand) == 1


def test_confusion_moves_pandora_up_to_one_space(bprd, order):
    g = mk(bprd)
    p = g.fighters["pandora"]
    here = p.pos
    order.append(IDX["Confusion"])
    spot = free_next_to(g, "pandora")
    g.controllers[0].queue = [[spot]]
    g.controllers[0].keeps = [False]
    start_turn(g)
    assert p.pos == spot and spot in g.board.adj[here]


def test_hope_fixes_the_top_card_and_the_next_reveal_is_that_card(bprd, order):
    g = mk(bprd)
    order.extend([IDX["Hope"], IDX["Misfortune"]])           # the second is what Hope looks at
    g.controllers[0].keeps = [True, False]
    start_turn(g)
    ask = keep_asks(g)[0]
    assert ask.extra["top"] == IDX["Misfortune"]
    assert counter(g, "revealed") == 2 and counter(g, "box_mask") == 1 << IDX["Hope"] | 1 << IDX["Misfortune"]
    assert order == []


def test_a_dead_pandora_ends_the_box(bprd, order):
    g = mk(bprd)
    g.fighters["pandora"].hp = 2
    order.extend([IDX["Toil"], IDX["Pain"], IDX["Greed"]])
    g.controllers[0].keeps = [True, True]
    start_turn(g)
    assert g.winner == 1 and not g.fighters["pandora"].alive


# ---------------------------------------------------------------- the cards

def test_hera_adds_one_per_revealed_misery_and_looks_at_the_hand_after(bprd):
    g = mk(bprd)
    g.fx.set_counter(0, "revealed", 3)
    p, h = pair(g, "pandora", "hellboy")
    res = g.attack(p, h, give(g, 0, "Hera's Curiosity"), plain(g))
    assert res.atk_value == 3 + 3


def test_aphrodite_cancels_and_heals_per_revealed_misery(bprd):
    g = mk(bprd)
    g.fx.set_counter(0, "revealed", 2)
    p, h = pair(g, "pandora", "hellboy")
    p.hp = 10
    g.attack(p, h, give(g, 0, "Aphrodite's Beauty"), plain(g))
    assert p.hp == 12


def test_a_kakodaemon_playing_aphrodite_heals_pandora(bprd):
    g = mk(bprd)
    g.fx.set_counter(0, "revealed", 2)
    k = g.fighters["kakodaemon1"]
    k.alive, k.hp = True, 1
    k, h = pair(g, "kakodaemon1", "hellboy")
    g.fighters["pandora"].hp = 10
    g.attack(k, h, give(g, 0, "Aphrodite's Beauty"), plain(g))
    assert g.fighters["pandora"].hp == 12


def test_spite_hurts_every_fighter_next_to_the_one_that_plays_it(bprd):
    g = mk(bprd)
    k = g.fighters["kakodaemon1"]
    k.alive, k.hp = True, 1
    k, h = pair(g, "kakodaemon1", "hellboy")
    ally = g.fighters["kakodaemon2"]
    ally.alive, ally.hp, ally.pos = True, 2, free_next_to(g, "kakodaemon1", exclude=[h.pos])
    ally.max_hp = 2
    hp0 = h.hp
    g.attack(k, h, give(g, 0, "Spite"), plain(g))
    assert ally.hp == 1 and h.hp <= hp0


def test_malice_makes_the_rival_discard_a_card_of_their_choice(bprd):
    g = mk(bprd)
    k = g.fighters["kakodaemon1"]
    k.alive, k.hp = True, 1
    k, h = pair(g, "kakodaemon1", "hellboy")
    spare = [g.players[1].deck.pop(), g.players[1].deck.pop()]
    g.players[1].hand.extend(spare)
    g.controllers[1].queue = [[spare[1].card_id]]
    g.attack(k, h, give(g, 0, "Malice"), None)
    assert g.players[1].hand == [spare[0]] and spare[1] in g.players[1].discard


def test_divine_intervention_moves_pandora_up_to_five_spaces(bprd):
    g = mk(bprd)
    p, h = pair(g, "pandora", "hellboy")
    one_step = g.legal_moves(p, 1) | {p.pos}
    far = max(s for s in g.legal_moves(p, 5) if s not in one_step)
    g.controllers[0].queue = [[far]]
    g.attack(p, h, give(g, 0, "Divine Intervention"), plain(g))
    assert p.pos == far


def test_guided_by_the_fates_adds_the_boost_of_the_top_card_and_heals_on_a_win(bprd):
    g = mk(bprd)
    p, h = pair(g, "pandora", "hellboy")
    p.hp = 10
    top = g.players[0].deck[0]
    res = g.attack(p, h, give(g, 0, "Guided by the Fates"), None)
    assert res.atk_value == 2 + top.boost and p.hp == 12 and top in g.players[0].discard


def test_guided_by_the_fates_does_not_heal_when_she_loses(bprd):
    g = mk(bprd)
    p, h = pair(g, "pandora", "hellboy")
    p.hp = 10
    low = next(c for c in g.players[0].deck if c.boost == 1)
    g.players[0].deck.remove(low)
    g.players[0].deck.insert(0, low)                           # 2 + 1 = 3 against a defense of 3: no damage, she did not win
    strong = _wall(g)
    g.attack(p, h, give(g, 0, "Guided by the Fates"), strong)
    assert p.hp == 10


def test_hindsight_returns_a_card_from_the_discard_pile_to_the_top_when_she_wins(bprd):
    g = mk(bprd)
    p, h = pair(g, "pandora", "hellboy")
    old = give(g, 0, "Feint")
    g.players[0].hand.remove(old)
    g.players[0].discard.append(old)
    g.controllers[0].queue = [[old.card_id]]
    g.attack(p, h, give(g, 0, "Hindsight"), None)
    assert g.players[0].deck[0] is old and old not in g.players[0].discard


def test_hindsight_returns_nothing_when_she_loses(bprd):
    g = mk(bprd)
    p, h = pair(g, "pandora", "hellboy")
    old = give(g, 0, "Feint")
    g.players[0].hand.remove(old)
    g.players[0].discard.append(old)
    g.attack(p, h, give(g, 0, "Hindsight"), _wall(g))
    assert old in g.players[0].discard and g.players[0].deck[0] is not old


def test_celestial_raiments_ignores_the_value_of_the_attack(bprd):
    g = mk(bprd)
    h, p = pair(g, "hellboy", "pandora")
    res = g.attack(h, p, _any_attack(g), give(g, 0, "Celestial Raiments"))
    assert res.atk_value == 0 and p.hp == 14 and res.damage == 0


def test_offering_to_the_gods_hurts_the_attacker_by_two_when_the_defense_holds(bprd):
    g = mk(bprd)
    h, p = pair(g, "hellboy", "pandora")
    atk = min((c for c in g.players[1].full_set if c.type == "attack" and "IMMEDIATELY" not in c.text), key=lambda c: c.value)
    g.players[1].hand.append(atk)
    hp0 = h.hp
    res = g.attack(h, p, atk, give(g, 0, "Offering to the Gods"))
    assert res.damage == 0 and h.hp == hp0 - 2


def test_offering_to_the_gods_does_nothing_when_it_loses(bprd):
    g = mk(bprd)
    h, p = pair(g, "hellboy", "pandora")
    atk = max((c for c in g.players[1].full_set if c.type == "attack" and "IMMEDIATELY" not in c.text), key=lambda c: c.value)
    g.players[1].hand.append(atk)
    hp0 = h.hp
    g.attack(h, p, atk, give(g, 0, "Offering to the Gods"))
    assert h.hp == hp0 and p.hp < 14


def test_offering_to_the_gods_may_be_boosted_for_free(bprd):
    from sparring.effects.model import load_effects
    assert load_effects("pandora").card("Offering to the Gods").may_boost


def test_zeus_draws_one_per_revealed_misery_moves_a_rival_and_gains_an_action(bprd):
    g = mk(bprd)
    g.fx.set_counter(0, "revealed", 3)
    g.actions_left = 2
    h = g.fighters["hellboy"]
    where = h.pos
    spot = sorted(g.board.adj[where])[0]
    g.controllers[0].queue = [["hellboy"], [spot]]
    g.play_scheme(0, g.fighters["pandora"], give(g, 0, "Zeus's Mischief"))
    assert len(g.players[0].hand) == 3 and g.actions_left == 2


def test_forged_by_hephaestus_places_the_fighter_and_gains_an_action(bprd):
    g = mk(bprd)
    g.actions_left = 2
    spot = max(s for s in g.board.spaces if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[spot]]
    g.play_scheme(0, g.fighters["pandora"], give(g, 0, "Forged by Hephaestus"))
    assert g.fighters["pandora"].pos == spot and g.actions_left == 2
