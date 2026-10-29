"""D1-prep: EffectAI answers every ChoiceRequest kind for the bot, on real heroes, without ever reading the human's
hidden hand and cheaply enough to run inside a combat."""
import time

import pytest

from sparring import ai_effects
from sparring.ai_effects import EffectAI, blind_clone
from sparring.ai_medusa import MedusaAI
from sparring.effects.choose import ChoiceRequest, ControllerChooser, ScriptedChooser, default_answer, worth_paying
from sparring.effects.model import EffectError
from sparring.effects.run import Ctx, EffectRun
from sparring.search.controller import IsmctsMedusa
from sparring.search.ismcts import SearchConfig
from sparring.state import Game

from conftest import Scripted, place
from test_effects_info import HandSpy, set_hand


def mk(bprd, bot="medusa", human="hellboy", seed=3):
    ctl = {0: MedusaAI(0), 1: Scripted()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=(bot, human))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    return g


def req(kind, options, player=0, lo=1, hi=1, card_id=None, key="", **extra):
    return ChoiceRequest(kind, player, list(options), lo, min(hi, len(options)), card_id, key, "", extra)


def by_title(g, player, title):
    return next(c for c in g.players[player].full_set if c.title == title)


@pytest.fixture
def ai():
    return EffectAI(0)


# ---------------------------------------------------------------- fighter

def test_the_interpreter_tells_the_pick_what_the_op_does(bprd):
    """`pick_fighters` puts the op and its amount in the request: the bot scores the candidates for what is coming."""
    g = mk(bprd)
    place(g, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    hb, lob = g.fighters["hellboy"], g.fighters["lobster"]
    sel = {"side": "enemy", "where": {"adjacent_to": "this"}}
    for ops, expect in [([{"op": "damage", "target": sel, "amount": 2}], {"op": "damage", "amount": 2}),
                        ([{"op": "heal", "target": sel, "amount": 1}], {"op": "heal", "amount": 1}),
                        ([{"op": "move", "target": sel, "amount": 2, "up_to": True}],
                         {"op": "move", "amount": 2, "through": False})]:
        chooser = ScriptedChooser([[hb.fid], []])
        assert g.board.distance(g.fighters["medusa"].pos, hb.pos) == 1 == g.board.distance(4, lob.pos)
        EffectRun(ops, Ctx(owner=0, this_fid="medusa")).run(g, chooser)
        first = chooser.requests[0]
        assert first.kind == "fighter" and sorted(first.options) == ["hellboy", "lobster"]
        assert {k: first.extra[k] for k in expect} == expect
    hb.hp = lob.hp = hb.max_hp


def test_a_killing_blow_on_a_sidekick_beats_a_scratch_on_the_hero(bprd, ai):
    g = mk(bprd)
    g.fighters["lobster"].hp = 1
    assert ai.choose_effect(g, req("fighter", ["hellboy", "lobster"], op="damage", amount=1)) == ["lobster"]


def test_a_lethal_blow_on_the_hero_beats_everything(bprd, ai):
    g = mk(bprd)
    g.fighters["hellboy"].hp = 2
    g.fighters["lobster"].hp = 1
    assert ai.choose_effect(g, req("fighter", ["hellboy", "lobster"], op="damage", amount=3)) == ["hellboy"]


def test_without_a_kill_the_rival_hero_is_the_target(bprd, ai):
    g = mk(bprd)
    assert ai.choose_effect(g, req("fighter", ["lobster", "hellboy"], op="damage")) == ["hellboy"]


def test_among_own_fighters_the_most_hurt_is_healed(bprd, ai):
    g = mk(bprd)
    g.fighters["medusa"].hp = g.fighters["medusa"].max_hp - 3
    assert ai.choose_effect(g, req("fighter", ["medusa", "harpy1", "harpy2"], op="heal", amount=3)) == ["medusa"]


def test_a_heal_among_mixed_candidates_never_goes_to_the_rival(bprd, ai):
    g = mk(bprd)
    g.fighters["hellboy"].hp = 1                  # the most hurt piece on the table is the rival hero
    g.fighters["harpy1"].hp = 1
    r = req("fighter", ["hellboy", "harpy1", "medusa"], op="heal", amount=2)
    assert ai.choose_effect(g, r) == ["harpy1"]
    g.fighters["harpy1"].hp = g.fighters["harpy1"].max_hp
    assert ai.choose_effect(g, r) in (["harpy1"], ["medusa"])     # nothing to heal: still an own piece


def test_damage_among_mixed_candidates_takes_the_lethal_enemy(bprd, ai):
    g = mk(bprd)
    g.fighters["medusa"].hp = 1                   # the bot's own hero is the weakest piece in the list
    g.fighters["lobster"].hp = 2
    assert ai.choose_effect(g, req("fighter", ["medusa", "lobster", "hellboy"], op="damage", amount=2)) == ["lobster"]


def test_damage_among_own_fighters_spares_the_hero(bprd, ai):
    g = mk(bprd)
    g.fighters["medusa"].hp = 2                   # the rival makes the bot choose who takes the hit
    assert ai.choose_effect(g, req("fighter", ["medusa", "harpy1"], op="damage", amount=2)) == ["harpy1"]


def test_set_hp_is_a_blow_or_a_heal_by_the_number(bprd, ai):
    g = mk(bprd)
    g.fighters["medusa"].hp = g.fighters["hellboy"].hp = 3
    assert ai.choose_effect(g, req("fighter", ["medusa", "hellboy"], op="set_hp", amount=1)) == ["hellboy"]
    assert ai.choose_effect(g, req("fighter", ["medusa", "hellboy"], op="set_hp", amount=10)) == ["medusa"]
    assert ai.choose_effect(g, req("fighter", ["medusa", "hellboy"], op="set_hp")) is None


def test_a_move_pick_goes_to_the_piece_whose_relocation_gains_most(bprd, ai):
    g = mk(bprd)
    place(g, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    r = req("fighter", ["hellboy", "lobster", "medusa"], op="move", amount=2, through=False)
    got = ai.choose_effect(g, r)
    model = ai_effects.Model(g, 0)
    value = lambda fid, s: ai.medusa(0).position_value(g, model, {fid: s})

    def gain(fid):
        f = g.fighters[fid]
        return max((value(fid, s) for s in g.legal_moves(f, 2, False)), default=value(fid, f.pos)) - value(fid, f.pos)
    assert got[0] in r.options and gain(got[0]) == max(map(gain, r.options))


def test_a_fighter_pick_for_an_unknown_op_is_left_to_the_controller_default(bprd, ai):
    g = mk(bprd)
    assert ai.choose_effect(g, req("fighter", ["hellboy", "lobster"])) is None
    r = req("fighter", ["hellboy", "lobster"], op="status", amount=1)
    assert ai.choose_effect(g, r) is None
    assert ControllerChooser().choose(g, r) == default_answer(r)


# ---------------------------------------------------------------- space

def test_the_hero_moves_where_the_legacy_kiting_rule_would(bprd, ai):
    g = mk(bprd)
    place(g, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    options = sorted(g.legal_moves(g.fighters["medusa"], 3, False))
    r = req("space", options, fighter="medusa", op="move", steps=3, through=False)
    assert ai.choose_effect(g, r) == [MedusaAI(0).choose_move(g, g.fighters["medusa"], 3, False)]


def test_a_sidekick_placement_follows_the_harpy_score(bprd, ai):
    g = mk(bprd)
    place(g, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    h = g.fighters["harpy1"]
    options = sorted(g.legal_moves(h, 3, False))
    r = req("space", options, fighter="harpy1", op="place")
    assert ai.choose_effect(g, r) == [MedusaAI(0).choose_placement(g, h, options)]


def test_a_rival_piece_is_put_where_it_hurts_the_bot_least(bprd, ai):
    g = mk(bprd)
    place(g, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    hb = g.fighters["hellboy"]
    options = sorted(g.legal_moves(hb, 3, True) - {hb.pos})
    answer = ai.choose_effect(g, req("space", options, fighter="hellboy", op="move", steps=3, through=True))[0]
    model = ai_effects.Model(g, 0)
    value = lambda s: ai.medusa(0).position_value(g, model, {"hellboy": s})
    assert value(answer) == max(value(s) for s in options)


def test_an_optional_move_stays_put_when_every_space_is_worse(bprd, ai):
    g = mk(bprd)
    place(g, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    far = max(g.board.spaces, key=lambda s: g.board.distance(s, g.fighters["hellboy"].pos))
    g.fighters["medusa"].pos = far
    only = [s for s in g.legal_moves(g.fighters["medusa"], 1, False) if s != far][:1]
    r = req("space", only, lo=0, fighter="medusa", op="move", steps=1, through=False)
    best = ai.choose_effect(g, r)
    assert best in ([], only)


# ---------------------------------------------------------------- cards

def test_the_discard_gives_up_the_least_useful_cards(bprd, ai):
    g = mk(bprd)
    set_hand(g, 0, "Gaze of Stone", "Dash", "Second Shot", "Feint")
    hand = g.players[0].hand
    ids = [c.card_id for c in hand]
    worst = [c.card_id for c in MedusaAI(0).choose_discard(g, 0, 2, "")]
    got = ai.choose_effect(g, req("cards", ids, lo=2, hi=2, zone="hand", purpose="discard", of=0))
    assert sorted(got) == sorted(worst)
    assert by_title(g, 0, "Gaze of Stone").card_id not in got


def test_a_search_of_the_own_deck_takes_the_best_card(bprd, ai):
    g = mk(bprd)
    ids = [c.card_id for c in g.players[0].deck[:6]]
    got = ai.choose_effect(g, req("cards", ids, zone="deck", purpose="search", of=0))
    cards = {c.card_id: c for c in g.players[0].full_set}
    assert ai_effects.card_worth(cards[got[0]]) == max(ai_effects.card_worth(cards[i]) for i in ids)


def test_recovering_from_the_own_discard_takes_the_best(bprd, ai):
    g = mk(bprd)
    pile = g.players[0].deck[:4]
    g.players[0].discard.extend(pile)
    del g.players[0].deck[:4]
    got = ai.choose_effect(g, req("cards", [c.card_id for c in pile], zone="discard", purpose="recover", of=0))
    assert ai_effects.card_worth(next(c for c in pile if c.card_id == got[0])) == max(map(ai_effects.card_worth, pile))


def test_the_rival_hand_is_ranked_only_by_what_a_look_showed(bprd, ai):
    g = mk(bprd)
    hand = set_hand(g, 1, "Second Shot", "Service Pistol", "Glimpse Of Hell", "Horseshoes And Hand Grenades")
    spy = HandSpy(g.players[1].hand)
    g.players[1].hand = spy
    ids = [c.card_id for c in hand]
    g.players[0].known.observe([hand[1], hand[2]], g.turn_no)
    spy.armed = True
    got = ai.choose_effect(g, req("cards", ids, zone="hand", purpose="discard", of=1))
    spy.armed = False
    assert got[0] in (hand[1].card_id, hand[2].card_id)


def test_a_blind_rival_hand_pick_is_the_chooser_position_pick(bprd, ai):
    """Nothing seen: the pick is C4's (`ControllerChooser._from_rival_hand`), a position drawn from the game rng."""
    g = mk(bprd)
    ids = [c.card_id for c in g.players[1].hand]
    state = g.rng.getstate()
    got = ai.choose_effect(g, req("cards", ids, zone="hand", purpose="discard", of=1))
    g.rng.setstate(state)
    assert got == ControllerChooser._from_rival_hand(g, req("cards", ids, zone="hand", purpose="discard", of=1), 1)
    assert len(got) == 1 and got[0] in ids


# ---------------------------------------------------------------- order and amount

def test_own_cards_are_ordered_best_first_and_the_rivals_worst_first(bprd, ai):
    g = mk(bprd)
    mine = [c.card_id for c in g.players[0].deck[:4]]
    cards = {c.card_id: c for c in g.players[0].full_set}
    got = ai.choose_effect(g, req("order", mine, lo=4, hi=4, zone="deck", purpose="order"))
    worth = [ai_effects.card_worth(cards[i]) for i in got]
    assert worth == sorted(worth, reverse=True)
    theirs = [c.card_id for c in g.players[1].full_set[:4]]
    rc = {c.card_id: c for c in g.players[1].full_set}
    got = ai.choose_effect(g, req("order", theirs, lo=4, hi=4, zone="deck", purpose="order"))
    worth = [ai_effects.card_worth(rc[i]) for i in got]
    assert worth == sorted(worth)


def test_fighters_to_order_go_by_value(bprd, ai):
    g = mk(bprd)
    got = ai.choose_effect(g, req("order", ["lobster", "hellboy"], lo=2, hi=2))
    assert got == ["hellboy", "lobster"]


def test_the_amount_is_the_largest_the_deck_allows(bprd, ai):
    g = mk(bprd)
    assert ai.choose_effect(g, req("amount", [0, 1, 2, 3])) == [3]
    del g.players[0].deck[2:]
    assert ai.choose_effect(g, req("amount", [0, 1, 2, 3])) == [2]


# ---------------------------------------------------------------- effect and optional, by simulation

def posthumous(bprd, hurt_team=True, kill_chance=False):
    g = mk(bprd, "hellboy", "liz-sherman")
    far = max(g.board.spaces, key=lambda s: g.board.distance(s, 3))
    place(g, hellboy=3, lobster=4, liz=far)
    if hurt_team:
        g.fighters["hellboy"].hp = 1
        g.fighters["lobster"].hp = max(1, g.fighters["lobster"].max_hp - 2)
    if kill_chance:
        g.fighters["liz"].hp = 1
    card_id = by_title(g, 0, "Posthumous Power").card_id
    return g, req("effect", [0, 1, 2], card_id=card_id, key="after/0:0", labels=["heal", "damage", "move"])


def test_a_hurt_team_heals(bprd):
    g, r = posthumous(bprd)
    assert EffectAI(0).choose_effect(g, r) == [0]


def test_a_chance_to_finish_the_rival_hero_deals_the_damage(bprd):
    g, r = posthumous(bprd, hurt_team=False, kill_chance=True)
    assert EffectAI(0).choose_effect(g, r) == [1]


def incinerate(bprd, hp, at_stake=7, hand=("Faster. Stronger.", "Secure The Scene", "Leap Away", "Concussion Device"),
               **extra):
    """Liz's Incinerate (printed 7) asks Abe's bot to discard 2 cards to ignore it; the request carries what the
    interpreter's `_cost_context` sends: `cost_cards`, `at_stake` (attack minus defense) and `hp`."""
    g = mk(bprd, "abe-sapien", "liz-sherman")
    set_hand(g, 0, *hand)
    card = by_title(g, 1, "Incinerate")
    g.fighters["abe"].hp = hp
    context = {"cost_cards": 2, "at_stake": at_stake, "hp": hp} if at_stake is not None else {}
    r = req("optional", [True, False], card_id=card.card_id, key="during/0:0", **context, **extra)
    return g, r


def test_a_lethal_incinerate_is_worth_two_cards(bprd):
    g, r = incinerate(bprd, hp=2)
    assert EffectAI(0).choose_effect(g, r) == [True] == [worth_paying(r)]


def test_a_harmless_incinerate_is_not_worth_two_cards(bprd):
    g, r = incinerate(bprd, hp=12, at_stake=0)
    assert EffectAI(0).choose_effect(g, r) == [False] == [worth_paying(r)]


def test_incinerate_is_paid_only_while_the_combat_outcome_changes(bprd):
    printed = 7
    g, r = incinerate(bprd, hp=12)
    assert by_title(g, 1, "Incinerate").value == printed
    assert EffectAI(0).choose_effect(g, r) == [True]            # seven damage avoided is worth two cards
    g, r = incinerate(bprd, hp=12, at_stake=1)                  # the defense already leaves a single point
    assert EffectAI(0).choose_effect(g, r) == [False]
    g, r = incinerate(bprd, hp=1, at_stake=1)                   # ... unless that point is the last hit point
    assert EffectAI(0).choose_effect(g, r) == [True]


@pytest.mark.parametrize("hp,at_stake,cost", [(12, 6, 2), (12, 5, 2), (12, 3, 1), (12, 2, 1), (3, 3, 2), (4, 3, 2),
                                             (12, 0, 1), (1, 1, 3)])
def test_a_priced_optional_is_the_one_chooser_policy_wherever_it_is_asked(bprd, hp, at_stake, cost):
    g, r = incinerate(bprd, hp=hp, at_stake=at_stake)
    r.extra["cost_cards"] = cost
    assert EffectAI(0).choose_effect(g, r) == [worth_paying(r)]
    g.controllers[0] = MedusaAI(0)
    assert ControllerChooser().choose(g, r) == [worth_paying(r)]


def test_incinerate_without_a_combat_context_never_raises(bprd):
    """Incinerate's op is `set_value ... ignore: true` (no `amount`): a decision helper must never raise into the
    live combat; without the interpreter's context the price is not paid."""
    g, r = incinerate(bprd, hp=2, at_stake=None)
    answer = EffectAI(0).choose_effect(g, r)
    assert answer is None or r.validate(answer) == answer
    g, r = incinerate(bprd, hp=2, at_stake=None, cost_cards=2)
    assert EffectAI(0).choose_effect(g, r) == [False]


def test_a_price_the_bot_cannot_pay_still_gets_a_legal_answer(bprd):
    g, r = incinerate(bprd, hp=2, hand=("Leap Away",))
    answer = EffectAI(0).choose_effect(g, r)
    assert answer in ([False], [True])      # the interpreter never asks it (_can_pay is false)


def test_a_simulation_swallows_only_the_interpreter_errors(bprd, monkeypatch):
    g, r = posthumous(bprd)

    def bug(self, game, choosers):
        raise RuntimeError("a bug in an op")
    monkeypatch.setattr(EffectRun, "run", bug)
    with pytest.raises(RuntimeError, match="a bug in an op"):
        EffectAI(0).choose_effect(g, r)

    def refuse(self, game, choosers):
        raise EffectError("only inside a combat")
    monkeypatch.setattr(EffectRun, "run", refuse)
    answer = EffectAI(0).choose_effect(g, r)
    assert answer is None or r.validate(answer) == answer


# ---------------------------------------------------------------- the anti-cheat rule

class Opaque:
    """A card of the human's real hand: any look at it explodes."""
    card_id = 999999

    def __getattr__(self, name):
        raise AssertionError(f"the bot read the human hand ({name})")


def all_requests(g):
    liz = by_title(g, 1, "Incinerate") if any(c.title == "Incinerate" for c in g.players[1].full_set) else None
    hero_card = by_title(g, 0, "Posthumous Power") if any(c.title == "Posthumous Power"
                                                           for c in g.players[0].full_set) else None
    deck = [c.card_id for c in g.players[0].deck[:4]]
    mine, theirs = g.hero(0).fid, g.hero(1).fid
    out = [req("fighter", [f.fid for f in g.fighters.values() if f.alive], op="damage", amount=2),
           req("fighter", [f.fid for f in g.fighters.values() if f.alive], op="move", amount=2, through=True),
           req("space", sorted(g.legal_moves(g.fighters[theirs], 2, True)), fighter=theirs, op="place"),
           req("space", sorted(g.legal_moves(g.fighters[mine], 2, False)), fighter=mine, op="move",
               steps=2, through=False),
           req("cards", deck, zone="deck", purpose="search", of=0),
           req("cards", [c.card_id for c in g.players[0].hand], lo=1, hi=1, zone="hand", purpose="discard", of=0),
           req("cards", [c.card_id for c in g.players[1].hand], zone="hand", purpose="discard", of=1),
           req("order", deck, lo=4, hi=4, zone="deck", purpose="order"),
           req("amount", [0, 1, 2])]
    if hero_card is not None:
        out.append(req("effect", [0, 1, 2], card_id=hero_card.card_id, key="after/0:0"))
    if liz is not None:
        out.append(req("optional", [True, False], card_id=liz.card_id, key="during/0:0"))
    return out


@pytest.mark.parametrize("bot,human", [("medusa", "hellboy"), ("hellboy", "medusa"), ("abe-sapien", "liz-sherman")])
def test_no_request_reads_the_human_hand_identities(bprd, bot, human):
    g = mk(bprd, bot, human)
    reqs = all_requests(g)
    spy = HandSpy([Opaque() for _ in g.players[1].hand])
    g.players[1].hand = spy
    ai = EffectAI(0)
    spy.armed = True
    try:
        for r in reqs:
            if r.kind == "cards" and r.extra.get("zone") == "hand" and r.extra.get("of") == 1:
                r = req("cards", [1, 2, 3], zone="hand", purpose="discard", of=1)
            ai.choose_effect(g, r)
    finally:
        spy.armed = False


def test_the_tripwire_bites_when_the_clone_is_a_plain_copy(bprd, monkeypatch):
    g, r = posthumous(bprd)
    spy = HandSpy([Opaque() for _ in g.players[1].hand])
    g.players[1].hand = spy
    monkeypatch.setattr(ai_effects, "blind_clone", lambda game, me, rng: Game.clone(game))
    spy.armed = True
    try:
        with pytest.raises(AssertionError, match="read the human hand|bot code read"):
            EffectAI(0).choose_effect(g, r)
    finally:
        spy.armed = False


def test_the_clone_keeps_what_a_look_showed_and_hides_the_rest(bprd):
    import random
    g = mk(bprd)
    hand = set_hand(g, 1, "Second Shot", "Service Pistol", "Glimpse Of Hell", "Horseshoes And Hand Grenades",
                    "Excalibur")
    g.players[0].known.observe(hand[:2], g.turn_no)
    seen = {c.card_id for c in hand[:2]}
    clones = [blind_clone(g, 0, random.Random(i)) for i in range(6)]
    for c in clones:
        assert seen <= {x.card_id for x in c.players[1].hand}
        assert len(c.players[1].hand) == 5
        assert not {x.card_id for x in c.players[1].hand} & {x.card_id for x in c.players[1].discard}
    assert len({tuple(sorted(x.card_id for x in c.players[1].hand)) for c in clones}) > 1


def test_the_clone_does_not_copy_the_real_rival_deck_order(bprd):
    import random
    g = mk(bprd)
    real = [c.card_id for c in g.players[1].deck]
    shuffled = [tuple(c.card_id for c in blind_clone(g, 0, random.Random(i)).players[1].deck) for i in range(3)]
    assert all(s != tuple(real) for s in shuffled)


def test_the_real_game_is_left_untouched(bprd):
    g, r = posthumous(bprd)
    before = (g.rng.getstate(), [c.card_id for c in g.players[1].hand], [c.card_id for c in g.players[1].deck],
              {k: (f.hp, f.pos) for k, f in g.fighters.items()})
    EffectAI(0).choose_effect(g, r)
    after = (g.rng.getstate(), [c.card_id for c in g.players[1].hand], [c.card_id for c in g.players[1].deck],
             {k: (f.hp, f.pos) for k, f in g.fighters.items()})
    assert before == after


# ---------------------------------------------------------------- determinism, speed, wiring

def test_the_same_request_gets_the_same_answer(bprd):
    answers = []
    for _ in range(3):
        g, r = posthumous(bprd)
        answers.append(EffectAI(0, seed=7).choose_effect(g, r))
    assert answers[0] == answers[1] == answers[2]
    g, r = incinerate(bprd, hp=5)
    assert EffectAI(0, seed=7).choose_effect(g, r) == EffectAI(0, seed=7).choose_effect(g, r)


def test_a_decision_takes_well_under_50_ms(bprd):
    g, r = posthumous(bprd)
    ai = EffectAI(0)
    ai.choose_effect(g, r)                                      # warm caches (effect files, board)
    slow = []
    for _ in range(5):
        t = time.perf_counter()
        ai.choose_effect(g, r)
        slow.append(time.perf_counter() - t)
    assert sorted(slow)[2] < 0.05, slow
    g, r = incinerate(bprd, hp=5)
    t = time.perf_counter()
    ai.choose_effect(g, r)
    assert time.perf_counter() - t < 0.05


def test_the_controllers_delegate_and_the_chooser_uses_them(bprd):
    g, r = posthumous(bprd)
    heuristic = MedusaAI(0)
    assert heuristic.choose_effect(g, r) == [0]
    ismcts = IsmctsMedusa(0, SearchConfig(iterations=5, seed=1))
    assert ismcts.choose_effect(g, r) == [0]
    g.controllers = {0: heuristic, 1: Scripted()}
    assert ControllerChooser().choose(g, r) == [0]


def test_every_kind_gets_a_legal_answer_on_every_hero_pair(bprd):
    pairs = [("medusa", "hellboy"), ("hellboy", "abe-sapien"), ("abe-sapien", "baba-yaga"),
             ("baba-yaga", "liz-sherman"), ("liz-sherman", "medusa")]
    for bot, human in pairs:
        g = mk(bprd, bot, human)
        ai = EffectAI(0)
        for r in all_requests(g):
            if r.kind == "cards" and r.extra.get("of") == 1:
                continue
            answer = ai.choose_effect(g, r)
            assert answer is None or r.validate(answer) == answer
