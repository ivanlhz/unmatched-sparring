"""C4 hidden information: look_hand / reveal / look_deck / search_deck / return_to_deck / put_in_hand on real cards,
and Ivan's rule that the bot reads the human hand ONLY while resolving an effect that says so.

`KnownHand` of player P is what P knows about P's rival. Players: 0 is the bot, 1 the human, unless a test says so."""
import random
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from sparring import persist
from sparring.cards import Card
from sparring.effects.choose import ControllerChooser, PanelChooser, ScriptedChooser
from sparring.effects.run import Ctx, EffectRun
from sparring.search.adapter import EngineState, Knowledge, card_worth
from sparring.search.controller import IsmctsMedusa
from sparring.search.ismcts import SearchConfig
from sparring.state import Game, KnownHand

from conftest import Scripted, card, place
from test_search_tactics import act_key, medusa_hand, rival_hand


def mk(bprd, bot, human, seed=1):
    ctl = {0: Scripted(), 1: Scripted()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=(bot, human))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    return g


def set_hand(g, player, *titles):
    """Replaces the hand with those titles (the old hand goes back to the deck)."""
    st = g.players[player]
    st.deck.extend(st.hand)
    st.hand.clear()
    for t in titles:
        c = next(x for x in st.deck + st.discard if x.title == t)
        (st.deck if c in st.deck else st.discard).remove(c)
        st.hand.append(c)
    return list(st.hand)


def card_run(g, slug, title, moment, owner=0, chooser=None, **ctx):
    run = EffectRun.for_card(slug, title, moment, Ctx(owner=owner, this_fid=g.hero(owner).fid, **ctx))
    return run, run.run(g, chooser or ScriptedChooser())


def ids(cards):
    return [c.card_id for c in cards]


class HandSpy(list):
    """A hand that raises when it is READ while armed (len and writes stay free)."""
    armed = False

    def _trip(self, what):
        if self.armed:
            raise AssertionError(f"bot code read the human hand ({what})")

    def __iter__(self):
        self._trip("iter")
        return super().__iter__()

    def __getitem__(self, i):
        self._trip("getitem")
        return super().__getitem__(i)

    def __contains__(self, x):
        self._trip("contains")
        return super().__contains__(x)

    def index(self, *a):
        self._trip("index")
        return super().index(*a)

    def copy(self):
        self._trip("copy")
        return super().copy()


class GuardedChooser(ControllerChooser):
    """The bot's chooser with the spy armed for the whole decision: this is 'bot code'."""

    def __init__(self, spy):
        self.spy = spy

    def choose(self, game, req):
        self.spy.armed = True
        try:
            return super().choose(game, req)
        finally:
            self.spy.armed = False


class PeekingChooser(ControllerChooser):
    """A cheater: reads the human hand to pick. The tripwire must catch it."""

    def __init__(self, spy, game):
        self.spy, self.game = spy, game

    def choose(self, game, req):
        self.spy.armed = True
        try:
            return [max((c for c in self.game.players[1].hand), key=card_worth).card_id]
        finally:
            self.spy.armed = False


HELLBOY_HAND = ("Second Shot", "Service Pistol", "Glimpse Of Hell", "Confront Any Demon or God", "Horseshoes And Hand Grenades")


# ---------------------------------------------------------------- the rule: look_hand is the only reader

def test_look_hand_is_the_only_caller_of_observe_hand_in_the_source():
    root = Path(__file__).resolve().parent.parent / "sparring"
    callers = {p.relative_to(root).as_posix() for p in root.rglob("*.py")
               if re.search(r"\bobserve_hand\(", p.read_text(encoding="utf-8"))}
    assert callers == {"state.py", "effects/ops_info.py"}, callers


def test_confront_bot_reads_the_hand_only_inside_look_hand_and_discards_the_best_seen_card(bprd):
    g = mk(bprd, "hellboy", "abe-sapien")
    hand = set_hand(g, 1, "Faster. Stronger.", "Secure The Scene", "Leap Away", "Concussion Device",
                    "Advanced Psychometry")
    spy = HandSpy(g.players[1].hand)
    g.players[1].hand = spy
    reads = []
    real = Game.observe_hand
    Game.observe_hand = lambda self, viewer, cards: (reads.append((viewer, ids(cards))), real(self, viewer, cards))[1]
    try:
        card_run(g, "hellboy", "Confront Any Demon or God", "after", chooser=GuardedChooser(spy),
                 combat_result="lost")
    finally:
        Game.observe_hand = real
    assert reads == [(0, ids(hand))]                              # one look, by the owner, of the whole hand
    best = max(hand, key=lambda c: (card_worth(c), -c.card_id))
    assert best in g.players[1].discard and len(g.players[1].hand) == 4
    assert g.players[0].known.seen == [i for i in ids(hand) if i != best.card_id]    # the rest stays remembered


def test_the_tripwire_bites_when_the_bot_peeks(bprd):
    g = mk(bprd, "hellboy", "abe-sapien")
    set_hand(g, 1, "Leap Away", "Concussion Device", "Secure The Scene")
    spy = HandSpy(g.players[1].hand)
    g.players[1].hand = spy
    with pytest.raises(AssertionError, match="read the human hand"):
        card_run(g, "hellboy", "Confront Any Demon or God", "after", chooser=PeekingChooser(spy, g),
                 combat_result="lost")


def test_no_look_hand_no_knowledge_the_bot_chooses_by_position_only(bprd):
    """If a choice among the rival hand is asked without a look (should not happen: the validator forbids it), the
    bot picks by position with the rng; the real identities never rank the answer."""
    g = mk(bprd, "hellboy", "abe-sapien")
    set_hand(g, 1, "Leap Away", "Concussion Device", "Secure The Scene")
    spy = HandSpy(g.players[1].hand)
    g.players[1].hand = spy
    ops = [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "owner"}}]
    run = EffectRun(ops, Ctx(owner=0, this_fid="hellboy"))
    assert run.run(g, GuardedChooser(spy)) is None
    assert len(g.players[1].hand) == 2 and g.players[0].known.is_empty()


def test_fleeting_moments_random_pick_is_a_position_not_an_identity(bprd):
    """The discard is a position drawn by the rng: the same seed discards the same position whatever the cards are."""
    outcome = []
    for titles in (("Leap Away", "Concussion Device", "Secure The Scene", "Advanced Psychometry"),
                   ("Counterhex Shield", "B.P.R.D. Utility Belt", "Cold Iron And Holy Water", "Ward And Prepare")):
        g = mk(bprd, "liz-sherman", "abe-sapien", seed=5)
        hand = set_hand(g, 1, *titles)
        ops = [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 1}}]
        EffectRun(ops, Ctx(owner=0, this_fid="liz")).run(g, ScriptedChooser())
        outcome.append(hand.index(g.players[1].discard[0]))
    assert outcome[0] == outcome[1]


@dataclass(frozen=True, eq=False)
class SpyCard(Card):
    """A card that logs reads of its identity (title, type, value...) in a shared list."""
    log: list = None

    def __getattribute__(self, name):
        if name in ("title", "type", "value", "boost", "text", "tags", "fighter"):
            object.__getattribute__(self, "log").append(name)
        return object.__getattribute__(self, name)

    __eq__ = object.__eq__
    __hash__ = object.__hash__


def test_random_pick_reads_no_identity_attributes(bprd):
    g = mk(bprd, "liz-sherman", "abe-sapien", seed=5)
    log = []
    hand = [SpyCard(c.card_id, c.title, c.fighter, c.type, c.value, c.boost, c.text, c.tags, log)
            for c in set_hand(g, 1, "Leap Away", "Concussion Device", "Secure The Scene", "Advanced Psychometry")]
    g.players[1].hand[:] = hand
    ops = [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 1}}]
    EffectRun(ops, Ctx(owner=0, this_fid="liz")).run(g, ScriptedChooser())
    assert log == [] and len(g.players[1].discard) == 1 and len(g.players[1].hand) == 3


# ---------------------------------------------------------------- seen cards are forgotten as they leave

def look(g, owner=0):
    EffectRun([{"op": "look_hand", "player": "opponent"}], Ctx(owner=owner, this_fid=g.hero(owner).fid)).run(
        g, ScriptedChooser())


def test_look_hand_remembers_everything_and_each_card_is_forgotten_when_it_leaves(bprd):
    g = mk(bprd, "hellboy", "abe-sapien")
    a, b, c, d, e = set_hand(g, 1, "Faster. Stronger.", "Secure The Scene", "Leap Away", "Concussion Device",
                             "Advanced Psychometry")
    look(g)
    known = g.players[0].known
    assert known.seen == ids([a, b, c, d, e]) and known.turn_no == g.turn_no
    g.take_from_hand(1, a)                          # played in combat
    g.discard_card(1, b)                            # discarded
    assert known.seen == ids([c, d, e])
    g.players[1].hand.remove(c)
    g.card_left_hand(1, c)                          # lost by any other route
    assert [x.card_id for x in g.hidden_hand(0)[0]] == ids([d, e])
    g.draw(1)                                       # a drawn card is unknown: nothing is added
    assert known.seen == ids([d, e])


def test_a_seen_card_is_never_playable_after_it_left(bprd):
    g = mk(bprd, "hellboy", "abe-sapien")
    a, b = set_hand(g, 1, "Faster. Stronger.", "Secure The Scene")[:2]
    look(g)
    g.discard_card(1, a)
    knowledge = Knowledge.from_game(g, 0)
    assert knowledge.known_in_hand[1] == (b,)
    assert a not in knowledge.known_in_hand[1]


def test_known_hand_does_not_read_the_rival_hand(bprd):
    g = mk(bprd, "hellboy", "abe-sapien")
    set_hand(g, 1, "Faster. Stronger.", "Secure The Scene")
    look(g)
    spy = HandSpy(g.players[1].hand)
    g.players[1].hand = spy
    spy.armed = True
    assert len(g.players[0].known.cards(g.players[1])) == 2
    assert Knowledge.from_game(g, 0).known_in_hand[1]
    g.hidden_hand(0)


def test_every_possible_angle_puts_the_chosen_card_on_top_and_it_is_the_next_draw(bprd):
    g = mk(bprd, "abe-sapien", "baba-yaga")
    hand = set_hand(g, 1, "Iron Teeth", "Deathless", "Exploit", "Foul Journey", "Out Of Time")
    best = max(hand, key=lambda c: (card_worth(c), -c.card_id))
    run, pending = card_run(g, "abe-sapien", "Every Possible Angle", "scheme", chooser=GuardedChooser(HandSpy()))
    assert pending is None
    assert g.players[1].deck[0] == best and best not in g.players[1].hand
    known = g.players[0].known
    assert best.card_id not in known.seen and known.top_of_deck == [best.card_id]
    assert g.hidden_hand(0)[0] == [c for c in hand if c != best] and known.top(g.players[1]) == [best]
    g.draw(1)                                       # the rival draws it: now it is a seen card again
    assert known.top_of_deck == [] and best.card_id in known.seen and best in g.players[1].hand


def test_a_blind_draw_makes_the_known_top_untrustworthy(bprd):
    g = mk(bprd, "abe-sapien", "baba-yaga")
    set_hand(g, 1, "Iron Teeth", "Deathless")
    known = g.players[0].known
    known.set_top([123456])             # not the real top: some other unknown card is drawn first
    g.draw(1)
    assert known.top_of_deck == []


def test_the_every_possible_angle_pick_comes_from_the_seen_cards_only(bprd):
    """A card drawn after the look is unknown to the bot: it can never be the one it chooses."""
    g = mk(bprd, "abe-sapien", "baba-yaga")
    set_hand(g, 1, "Iron Teeth", "Deathless")
    look(g)
    seen_best = max(card_worth(c) for c in g.players[1].hand)
    newcomer = max((c for c in g.players[1].deck), key=card_worth)          # the most tempting card of all
    assert card_worth(newcomer) > seen_best
    g.players[1].hand.append(newcomer)
    g.players[1].deck.remove(newcomer)
    EffectRun([{"op": "return_to_deck", "cards": {"zone": "hand", "player": "opponent", "amount": 1,
                                                  "chooser": "owner"}, "position": "top"}],
              Ctx(owner=0, this_fid="abe")).run(g, ControllerChooser())
    assert g.players[1].deck[0] != newcomer and newcomer in g.players[1].hand


# ---------------------------------------------------------------- degrade to possible

def test_glimpse_of_hell_by_the_human_degrades_what_the_bot_saw(bprd):
    g = mk(bprd, "abe-sapien", "hellboy")
    hand = set_hand(g, 1, "Second Shot", "Service Pistol", "Horseshoes And Hand Grenades", "Right Hand Of Doom", "Glimpse Of Hell")
    look(g)
    played = hand[4]
    g.take_from_hand(1, played)                     # Glimpse leaves for the combat
    known = g.players[0].known
    assert known.seen == ids(hand[:4])
    run, pending = card_run(g, "hellboy", "Glimpse Of Hell", "after", owner=1)
    assert pending is None
    assert known.seen == [] and sorted(known.possible) == sorted(ids(hand[:4]))
    # 4 seen, 2 drawn unseen, 1 shuffled back face down: at least 3 and at most 4 of the seen are still there
    assert (known.possible_lo, known.possible_hi) == (3, 4)
    assert g.hidden_hand(0)[0] == []                 # nothing is certain any more
    assert len(g.players[1].hand) == 5


def test_pyrotechnics_by_the_human_degrades_two(bprd):
    g = mk(bprd, "abe-sapien", "liz-sherman")
    hand = set_hand(g, 1, "Fireball", "Evade", "Rekindle", "Searing Clarity", "Fleeting Moments")
    look(g)
    card_run(g, "liz-sherman", "Pyrotechnics", "after", owner=1, chooser=ScriptedChooser([[True]]))
    known = g.players[0].known
    assert known.seen == [] and sorted(known.possible) == sorted(ids(hand))
    assert (known.possible_lo, known.possible_hi) == (3, 3)        # no draw: exactly three of the five remain


def test_the_same_degrade_applies_to_what_the_human_saw_of_the_bot(bprd):
    """The bot plays Glimpse Of Hell: what the human saw of its hand is no longer certain either."""
    g = mk(bprd, "hellboy", "abe-sapien")
    hand = set_hand(g, 0, *HELLBOY_HAND)
    g.players[1].known.observe(hand, g.turn_no)
    g.take_from_hand(0, hand[2])                                      # Glimpse Of Hell goes to the combat
    card_run(g, "hellboy", "Glimpse Of Hell", "after", owner=0, chooser=ControllerChooser())
    seen = g.players[1].known
    assert seen.seen == [] and len(seen.possible) == 4 and len(g.players[0].hand) == 5
    assert (seen.possible_lo, seen.possible_hi) == (3, 4)


def test_pact_of_secrecy_leaves_exactly_two_of_the_five_seen_cards(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    hand = set_hand(g, 1, "Faster. Stronger.", "Secure The Scene", "Leap Away", "Concussion Device",
                    "Advanced Psychometry")
    look(g)

    class NoDraw:
        def choose(self, game, req):
            return [0] if req.kind == "amount" else list(req.options[:req.min])

    run = EffectRun.for_card("baba-yaga", "Pact Of Secrecy", "scheme", Ctx(owner=0, this_fid="baba"))
    assert run.run(g, NoDraw()) is None
    known = g.players[0].known
    assert len(g.players[1].hand) == 2
    assert sorted(known.possible) == sorted(ids(hand)) and known.seen == []
    assert (known.possible_lo, known.possible_hi) == (2, 2)


def test_pact_of_secrecy_when_the_hand_was_small_keeps_certainty(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    hand = set_hand(g, 1, "Faster. Stronger.", "Secure The Scene")
    look(g)

    class NoDraw:
        def choose(self, game, req):
            return [0] if req.kind == "amount" else list(req.options[:req.min])

    EffectRun.for_card("baba-yaga", "Pact Of Secrecy", "scheme", Ctx(owner=0, this_fid="baba")).run(g, NoDraw())
    assert g.players[0].known.seen == ids(hand)         # nothing went back: still certain


def test_known_hand_bounds_unit():
    k = KnownHand(seen=[1, 2, 3], turn_no=4)
    k.degrade(1, 3)
    assert k.seen == [] and k.possible == [1, 2, 3] and (k.possible_lo, k.possible_hi) == (2, 3)
    cards = [Card(i, f"c{i}", "any", "attack", 1, 1) for i in (1, 2, 3)]
    assert k.forget(cards[0]) and k.possible == [2, 3] and (k.possible_lo, k.possible_hi) == (1, 2)
    assert k.forget(cards[1]) and k.possible == [3] and (k.possible_lo, k.possible_hi) == (0, 1)
    assert k.forget(cards[2]) and k.is_empty() and k.turn_no is None
    k = KnownHand(seen=[1, 2], turn_no=1)
    k.degrade(1, 2)                                   # one of the two seen went face down; the hand has 2 cards
    assert (k.possible_lo, k.possible_hi) == (1, 2)
    k.degrade(1, 1)
    assert k.possible == [1, 2] and (k.possible_lo, k.possible_hi) == (0, 1)
    k = KnownHand(seen=[1], turn_no=1)
    k.degrade(1, 0)                                   # the hand is empty: nothing remains possible
    assert k.is_empty()
    k = KnownHand(seen=[1, 2], turn_no=1)
    k.degrade(0, 2)                                   # nothing left: unchanged
    assert k.seen == [1, 2]


def test_known_hand_roundtrips_through_the_save_and_an_empty_one_adds_nothing(bprd):
    g = mk(bprd, "abe-sapien", "baba-yaga")
    assert "known" not in persist.game_to_dict(g)["players"][0]
    k = g.players[0].known
    k.seen, k.turn_no = [7], 3
    k.possible, k.possible_lo, k.possible_hi = [8, 9], 1, 2
    k.top_of_deck = [11, 12]
    saved = persist.game_to_dict(g)
    g2 = mk(bprd, "abe-sapien", "baba-yaga")
    persist.apply_game(g2, saved)
    k2 = g2.players[0].known
    assert (k2.seen, k2.turn_no, k2.possible, k2.possible_lo, k2.possible_hi, k2.top_of_deck) == \
           ([7], 3, [8, 9], 1, 2, [11, 12])
    assert persist.game_to_dict(g2) == saved
    assert g.clone().players[0].known.top_of_deck == [11, 12]


# ---------------------------------------------------------------- search: determinization respects KnownHand

def test_determinize_keeps_the_known_cards_the_top_and_the_possible_bounds(game):
    medusa_hand(game, "Second Shot", "Gaze of Stone", "Dash")
    rival_hand(game, 6)
    hand = list(game.players[1].hand)
    top = game.players[1].deck[0]
    game.observe_hand(0, hand[:2])
    game.players[0].known.set_top([top.card_id])
    game.players[0].known.seen.append(hand[2].card_id)
    k = game.players[0].known
    k.degrade(1, 3)                                  # three seen cards, one may be gone: 2..3 of them in the hand
    assert (k.possible_lo, k.possible_hi) == (2, 3)
    knowledge = Knowledge.from_game(game, 0)
    assert knowledge.top_of_deck[1] == (top,) and len(knowledge.possible_in_hand[1]) == 3
    counts = set()
    for seed in range(40):
        st = EngineState(game, observer=0, knowledge=knowledge)
        st.determinize(0, random.Random(seed))
        rival = st.game.players[1]
        assert len(rival.hand) == 6 and rival.deck[0] == top and top not in rival.hand
        counts.add(sum(1 for c in hand[:3] if c in rival.hand))
    assert counts <= {2, 3} and counts == {2, 3}


def test_determinize_without_extra_knowledge_is_unchanged_in_shape(game):
    medusa_hand(game, "Second Shot", "Gaze of Stone", "Dash")
    rival_hand(game, 5)
    game.observe_hand(0, game.players[1].hand[:2])
    st = EngineState(game, observer=0, knowledge=Knowledge.from_game(game, 0))
    st.determinize(0, random.Random(3))
    assert st.game.players[1].hand[:2] == game.players[1].hand[:2] and len(st.game.players[1].hand) == 5


def test_plan_is_identical_when_only_the_unseen_cards_change(game):
    ai = IsmctsMedusa(0, SearchConfig(iterations=300, seed=11))
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Gaze of Stone", "Dash", "Regroup", "A Momentary Glance")
    rival_hand(game, 5)
    game.observe_hand(0, game.players[1].hand[:2])           # two cards are known; three are not
    other = game.clone()
    p = other.players[1]
    unseen = p.hand[2:]
    p.hand[2:], p.deck = p.deck[:3], unseen + p.deck[3:]
    assert ids(p.hand[2:]) != ids(game.players[1].hand[2:])
    assert act_key(ai.plan(game)) == act_key(ai.plan(other))
    assert ai.fallbacks == 0


def test_search_never_reads_the_rival_hand_after_a_look(game):
    ai = IsmctsMedusa(0, SearchConfig(iterations=200, seed=11))
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Gaze of Stone", "Dash")
    rival_hand(game, 5)
    game.observe_hand(0, game.players[1].hand[:3])
    game.players[0].known.set_top([game.players[1].deck[0].card_id])

    class Mine:
        card_id = 999999
        destiny = False

        def __getattr__(self, name):
            raise AssertionError(f"the search read the real rival hand ({name})")

    game.players[1].hand[:] = [Mine() for _ in range(5)]
    ai.plan(game)
    assert ai.fallbacks == 0


# ---------------------------------------------------------------- own deck: look_deck and search_deck

def test_read_the_bones_takes_the_best_of_the_top_five_and_puts_the_rest_at_the_bottom(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien", seed=4)
    deck = list(g.players[0].deck)
    hand_before = len(g.players[0].hand)
    run, pending = card_run(g, "baba-yaga", "Read The Bones", "after", chooser=ControllerChooser())
    assert pending is None
    top5 = deck[:5]
    best = max(top5, key=lambda c: (card_worth(c), -c.card_id))
    st = g.players[0]
    assert len(st.hand) == hand_before + 1 and best in st.hand
    assert len(st.deck) == len(deck) - 1
    assert sorted(ids(st.deck[-4:])) == sorted(ids(c for c in top5 if c != best))      # the other four, any order
    assert st.deck[:-4] == deck[5:]
    # the same seed shuffles the same way
    g2 = mk(bprd, "baba-yaga", "abe-sapien", seed=4)
    card_run(g2, "baba-yaga", "Read The Bones", "after", chooser=ControllerChooser())
    assert ids(g2.players[0].deck) == ids(st.deck)


def test_search_deck_is_atomic_and_resumes_with_the_same_result(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien", seed=4)
    deck, hand = list(g.players[0].deck), list(g.players[0].hand)
    run = EffectRun.for_card("baba-yaga", "Read The Bones", "after", Ctx(owner=0, this_fid="baba"))
    pending = run.run(g, PanelChooser())
    assert pending is not None and g.players[0].deck == deck and g.players[0].hand == hand
    req = run.awaiting
    assert req.kind == "cards" and req.options == ids(deck[:5]) and req.extra["of"] == 0
    run.resume([req.options[2]])
    assert run.run(g, PanelChooser()) is None
    assert deck[2] in g.players[0].hand and len(g.players[0].deck) == len(deck) - 1


def test_search_deck_top_ordered_shuffle_and_filter(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien", seed=2)
    st = g.players[0]
    pact = next(c for c in st.deck if c.title == "Pact Of Secrecy")
    st.deck.remove(pact)
    st.deck.insert(2, pact)
    deck = list(st.deck)
    ops = [{"op": "search_deck", "player": "owner", "look": 4, "take": {"amount": 1, "filter": {"title": pact.title}},
            "to": "hand", "rest": "top_ordered", "chooser": "owner", "as": "got"}]
    run = EffectRun(ops, Ctx(owner=0, this_fid="baba"))
    chooser = ScriptedChooser([ids([deck[3], deck[0], deck[1]])])
    assert run.run(g, chooser) is None
    assert [r.kind for r in chooser.requests] == ["order"]                 # the single eligible card needs no question
    assert run.bound("got", "cards") == [pact.card_id] and pact in st.hand
    assert st.deck == [deck[3], deck[0], deck[1]] + deck[4:]

    g2 = mk(bprd, "baba-yaga", "abe-sapien", seed=2)
    deck2 = list(g2.players[0].deck)
    ops2 = [{"op": "search_deck", "player": "owner", "look": "all", "take": {"amount": 1}, "to": "hand",
             "rest": "shuffle", "chooser": "owner"}]
    EffectRun(ops2, Ctx(owner=0, this_fid="baba")).run(g2, ScriptedChooser())
    after = g2.players[0]
    assert sorted(ids(after.deck)) == sorted(ids(deck2[1:])) and deck2[0] in after.hand
    assert ids(after.deck) != ids(deck2[1:])


def test_look_deck_does_not_move_anything_and_binds_the_cards(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    deck = list(g.players[0].deck)
    run = EffectRun([{"op": "look_deck", "player": "owner", "amount": 3, "as": "seen"},
                     {"op": "look_deck", "player": "owner", "amount": 2, "from": "bottom", "as": "low"}],
                    Ctx(owner=0, this_fid="baba"))
    run.run(g, ScriptedChooser())
    assert g.players[0].deck == deck
    assert run.bound("seen", "cards") == ids(deck[:3]) and run.bound("low", "cards") == ids(deck[::-1][:2])
    assert g.players[1].known.top_of_deck == []        # own deck: nobody learns anything


def test_look_deck_at_the_rival_deck_gives_a_known_top(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    deck = list(g.players[1].deck)
    EffectRun([{"op": "look_deck", "player": "opponent", "amount": 2}], Ctx(owner=0, this_fid="baba")).run(
        g, ScriptedChooser())
    assert g.players[0].known.top_of_deck == ids(deck[:2])
    g.draw(1)
    assert g.players[0].known.top_of_deck == [deck[1].card_id] and deck[0].card_id in g.players[0].known.seen


# ---------------------------------------------------------------- return_to_deck: top, bottom, shuffle

def test_pancakes_puts_two_discards_at_the_bottom_in_the_chosen_order(bprd):
    g = mk(bprd, "hellboy", "abe-sapien", seed=3)
    st = g.players[0]
    set_hand(g, 0)                                              # the whole hand back into the deck
    a, b = [next(c for c in st.deck if c.title == t) for t in ("Second Shot", "Service Pistol")]
    st.deck.remove(a), st.deck.remove(b)
    st.discard.extend([a, b])
    deck = list(st.deck)
    ops =[{"op": "return_to_deck", "cards": {"zone": "discard", "player": "owner", "filter": {"type_not": "scheme"},
                                              "amount": 2, "up_to": True, "chooser": "owner"},
            "position": "bottom", "order": "owner"}]
    run = EffectRun(ops, Ctx(owner=0, this_fid="hellboy"), label="scheme")
    chooser = ScriptedChooser([ids([a, b]), ids([b, a])])
    assert run.run(g, chooser) is None
    assert [r.kind for r in chooser.requests] == ["cards", "order"]
    assert st.deck == deck + [b, a] and a not in st.discard and b not in st.discard
    assert g.players[1].known.top_of_deck == []


def test_return_to_the_bottom_of_an_empty_deck_is_a_known_top_only_when_seen(bprd):
    g = mk(bprd, "hellboy", "abe-sapien")
    st = g.players[0]
    st.discard.extend(st.deck[:2])
    del st.deck[:]
    ops = [{"op": "return_to_deck", "cards": {"zone": "discard", "player": "owner", "amount": 2, "chooser": "owner"},
            "position": "bottom", "order": "owner"}]
    EffectRun(ops, Ctx(owner=0, this_fid="hellboy")).run(g, ScriptedChooser())
    assert len(g.players[1].known.top_of_deck) == 2          # from a public pile: the rival saw which and in what order


def test_rekindle_shuffles_the_discard_in_and_the_rival_forgets_the_top(bprd):
    g = mk(bprd, "abe-sapien", "liz-sherman", seed=6)
    g.players[0].known.top_of_deck = []
    st = g.players[1]
    moved = st.deck[:5]
    del st.deck[:5]
    st.discard.extend(moved)
    g.players[0].known.set_top([st.deck[0].card_id])           # the bot knew the top of the human deck
    deck_before = list(st.deck)
    card_run(g, "liz-sherman", "Rekindle", "after", owner=1, chooser=ScriptedChooser([ids(moved[:3])]))
    assert len(st.deck) == len(deck_before) + 3 and set(moved[:3]) <= set(st.deck)
    assert sorted(ids(st.deck)) == sorted(ids(deck_before + moved[:3]))
    assert g.players[0].known.top_of_deck == []
    # reproducible: same seed and moves give the same shuffle
    g2 = mk(bprd, "abe-sapien", "liz-sherman", seed=6)
    st2 = g2.players[1]
    del st2.deck[:5]
    st2.discard.extend(moved)
    card_run(g2, "liz-sherman", "Rekindle", "after", owner=1, chooser=ScriptedChooser([ids(moved[:3])]))
    assert ids(st2.deck) == ids(st.deck)


def test_pact_of_time_returns_discards_for_both_players_in_the_open(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien", seed=8)
    for p in (0, 1):
        st = g.players[p]
        st.discard.extend(st.deck[:3])
        del st.deck[:3]
    look(g)
    seen = list(g.players[0].known.seen)
    sizes = [len(g.players[p].deck) for p in (0, 1)]
    run = EffectRun.for_card("baba-yaga", "Pact Of Time", "scheme", Ctx(owner=0, this_fid="baba"))
    assert run.run(g, ScriptedChooser()) is None
    assert [len(g.players[p].deck) for p in (0, 1)] == [s + 2 for s in sizes]
    assert len(g.players[1].discard) == 1 and len(g.players[0].discard) == 1
    assert g.players[0].known.seen == seen                    # hands are untouched by a discard-to-deck


def test_return_to_deck_from_hand_face_down_is_not_a_known_top(bprd):
    g = mk(bprd, "abe-sapien", "hellboy")
    set_hand(g, 1, "Second Shot", "Service Pistol", "Horseshoes And Hand Grenades", "Glimpse Of Hell")
    g.players[0].known.set_top([g.players[1].deck[0].card_id])
    ops = [{"op": "return_to_deck", "cards": {"zone": "hand", "player": "owner", "amount": 1, "chooser": "owner"},
            "position": "top"}]
    EffectRun(ops, Ctx(owner=1, this_fid="hellboy")).run(g, ScriptedChooser())
    assert g.players[0].known.top_of_deck == []               # a hidden card sits on top of what was known


def test_return_to_deck_atomic_with_a_panel_pause(bprd):
    g = mk(bprd, "abe-sapien", "hellboy")
    set_hand(g, 1, "Second Shot", "Service Pistol", "Horseshoes And Hand Grenades", "Glimpse Of Hell")
    hand, deck = list(g.players[1].hand), list(g.players[1].deck)
    ops = [{"op": "return_to_deck", "cards": {"zone": "hand", "player": "owner", "amount": 1, "chooser": "owner"},
            "position": "shuffle"}]
    run = EffectRun(ops, Ctx(owner=1, this_fid="hellboy"))
    assert run.run(g, PanelChooser()) is not None
    assert g.players[1].hand == hand and g.players[1].deck == deck
    run.resume([hand[1].card_id])
    assert run.run(g, PanelChooser()) is None
    assert hand[1] in g.players[1].deck and hand[1] not in g.players[1].hand and len(g.players[1].deck) == len(deck) + 1


# ---------------------------------------------------------------- put_in_hand and reveal

def test_ward_and_prepare_by_the_human_puts_a_scheme_in_hand_and_the_bot_notes_it(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    scheme = next(c for c in g.players[1].deck if c.type == "scheme")
    g.players[1].deck.remove(scheme)
    g.players[1].discard.append(scheme)
    card_run(g, "abe-sapien", "Ward And Prepare", "after", owner=1, chooser=ScriptedChooser())
    assert scheme in g.players[1].hand and scheme not in g.players[1].discard
    assert g.players[0].known.seen == [scheme.card_id]


def test_put_in_hand_from_the_deck_is_noted_only_if_the_rival_knew_the_card(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    st = g.players[1]
    known_card, hidden = st.deck[0], st.deck[5]
    g.players[0].known.set_top([known_card.card_id])
    for c in (hidden, known_card):
        run = EffectRun([{"op": "put_in_hand", "cards": "$c"}], Ctx(owner=1, this_fid="abe"),
                        bindings={"c": {"t": "cards", "v": [c.card_id]}})
        run.run(g, ScriptedChooser())
    assert hidden in st.hand and known_card in st.hand
    assert g.players[0].known.seen == [known_card.card_id] and g.players[0].known.top_of_deck == []


def test_reveal_makes_a_hand_card_seen_and_a_combat_card_a_flag(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    card_in_hand = set_hand(g, 1, "Leap Away")[0]
    EffectRun([{"op": "reveal", "cards": "$c", "to": "opponent"}], Ctx(owner=1, this_fid="abe"),
              bindings={"c": {"t": "cards", "v": [card_in_hand.card_id]}}).run(g, ScriptedChooser())
    assert g.players[0].known.seen == [card_in_hand.card_id]
    atk = set_hand(g, 1, "Concussion Device")[0]
    g.take_from_hand(1, atk)                          # played face down: in neither hand, deck nor discard
    run = EffectRun([{"op": "reveal", "cards": "attack_card", "to": "owner"}],
                    Ctx(owner=0, this_fid="baba", attack_card_id=atk.card_id))
    run.run(g, ScriptedChooser())
    assert run.flags["revealed"] == {"0": [atk.card_id]}


def test_reveal_of_the_deck_top_sets_the_known_top(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    top = g.players[1].deck[0]
    ops = [{"op": "reveal", "cards": {"zone": "deck", "player": "opponent", "pick": "top", "amount": 1},
            "to": "owner"}]
    EffectRun(ops, Ctx(owner=0, this_fid="baba")).run(g, ScriptedChooser())
    assert g.players[0].known.top_of_deck == [top.card_id]


def test_remove_a_painful_memory_asks_the_bot_for_a_seen_card_and_the_human_decides(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    hand = set_hand(g, 1, "Faster. Stronger.", "Secure The Scene", "Leap Away")
    g.fx.set_ongoing(0, card(g, 0, "Pact Of Peace").card_id)
    spy = HandSpy(g.players[1].hand)
    g.players[1].hand = spy

    class Both:
        """Bot side guarded, human side answers 'discard'."""
        bot = GuardedChooser(spy)

        def choose(self, game, req):
            return self.bot.choose(game, req) if req.player == 0 else [True]

    run = EffectRun.for_card("baba-yaga", "Remove A Painful Memory", "after", Ctx(owner=0, this_fid="baba",
                                                                                    defender_fid="abe"))
    assert run.run(g, Both()) is None
    best = max(hand, key=lambda c: (card_worth(c), -c.card_id))
    assert best in g.players[1].discard and g.players[0].known.seen == [i for i in ids(hand) if i != best.card_id]
