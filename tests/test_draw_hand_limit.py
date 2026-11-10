"""F-DRAW-HAND-LIMIT: a card drawn past the hand limit is worth nothing to the bot (live 10/11: Hellboy held 8 cards with one
action left, played Pancakes! for "draw 2" and discarded 2 to the hand limit when the turn ended)."""
import pytest

from conftest import Scripted, give
from sparring.ai_medusa import CARD_VALUE, MedusaAI, hand_room, keep_value, kept_hand_value
from sparring.board import Board
from sparring.state import Game

LIVE_HAND = ("Pancakes!", "Posthumous Power", "And Upon His Brow Is Set A Crown Of Flame", "Right Hand Of Doom", "Planned Recklessness",
             "Horseshoes And Hand Grenades", "B.P.R.D. Training", "Posthumous Power")
HELLBOY_AT = 2


def table(heroes, hand, turn=0, actions=1):
    g = Game.new(Board.load("bprd-hq"), seed=3, controllers={0: MedusaAI(0), 1: Scripted()}, bot_player=0, heroes=heroes)
    g.turn, g.turn_no = 0, 3
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    seen = {}
    for title in hand:
        seen[title] = seen.get(title, -1) + 1
        give(g, 0, title, seen[title])
    rival = g.players[1]
    while len(rival.hand) < 5:
        rival.hand.append(rival.deck.pop(0))
    g.turn, g.actions_left = turn, actions
    return g


def hellboy(hand=LIVE_HAND, hp=None, discard=(), actions=1):
    g = table(("hellboy", "yennefer-triss"), hand, actions=actions)
    g.fighters["hellboy"].pos = HELLBOY_AT
    me = g.players[0]
    for title in discard:
        card = next(c for c in me.deck if c.title == title)
        me.deck.remove(card)
        me.discard.append(card)
    if hp is not None:
        g.fighters["hellboy"].hp = hp
    return g


def play_pancakes(g):
    me = g.players[0]
    g.play_scheme(0, g.hero(0), next(c for c in me.hand if c.title == "Pancakes!"))
    return me


def test_the_live_scene_does_not_spend_pancakes_on_a_full_hand():
    g = hellboy()
    assert hand_room(g, 0) == 7 and len(g.players[0].hand) == 8
    act = g.controllers[0].plan(g)
    assert not (act.kind == "scheme" and act.card.title == "Pancakes!"), "nothing to heal, nothing to return, no room to draw"


def test_pancakes_on_a_full_hand_never_takes_the_draw():
    me = play_pancakes(hellboy())
    assert len(me.hand) == 7, "the two cards would only be discarded by the hand limit"


def test_pancakes_on_a_full_hand_heals_and_returns_instead_of_drawing():
    g = hellboy(hp=10, discard=("Excalibur", "Service Pistol"))
    deck = len(g.players[0].deck)
    me = play_pancakes(g)
    assert g.fighters["hellboy"].hp == 12 and len(me.hand) == 7
    assert len(me.deck) == deck + 2 and {c.title for c in me.deck[-2:]} == {"Excalibur", "Service Pistol"}
    again = hellboy(hp=10, discard=("Excalibur", "Service Pistol"))
    act = again.controllers[0].plan(again)
    assert act.kind == "scheme" and act.card.title == "Pancakes!", "with something to heal the card is still worth its action"


@pytest.mark.parametrize("hp, discard", [(None, ()), (10, ("Excalibur", "Service Pistol"))])
def test_pancakes_on_a_short_hand_still_draws(hp, discard):
    me = play_pancakes(hellboy(LIVE_HAND[:3], hp=hp, discard=discard))
    assert len(me.hand) == 4, "two cards left after the scheme, two drawn"


def test_a_draw_that_half_fits_is_still_taken():
    me = play_pancakes(hellboy(LIVE_HAND[:7], hp=10, discard=("Excalibur", "Service Pistol")))
    assert len(me.hand) == 8, "six cards after the scheme: one of the two drawn stays"


def test_with_an_action_left_the_draw_is_not_refused_outright():
    """The next action may play a card and make room: the choice is left to the evaluation (the hand is worth its best 7)."""
    g = hellboy(hp=10, actions=2)
    ai = g.controllers[0].effect_ai()
    assert g.actions_left == 2 and not ai._draws_past_limit(g, 0, {"ops": [{"op": "draw", "player": "owner", "amount": 2}]})
    g.actions_left = 0
    assert ai._draws_past_limit(g, 0, {"ops": [{"op": "draw", "player": "owner", "amount": 2}]})
    assert not ai._draws_past_limit(g, 0, {"ops": [{"op": "heal", "target": "hero", "amount": 2}]})


def test_the_hand_is_worth_the_cards_the_limit_leaves_on_the_own_turn_only():
    g = hellboy()
    hand = g.players[0].hand
    keeps = sorted((keep_value(c, hand) for c in hand), reverse=True)
    assert kept_hand_value(g, 0) == pytest.approx(sum(keeps[:7])) and keeps[7] > 0
    g.turn = 1                      # the rival's turn: the limit falls a whole own turn away
    assert hand_room(g, 0) is None and kept_hand_value(g, 0) == pytest.approx(sum(keeps))


def test_the_evaluation_gives_nothing_for_cards_past_the_limit():
    """Two more cards worse than every card kept: the evaluation of the own turn does not move, that of the rival's does."""
    def score(extra, turn):
        g = hellboy(LIVE_HAND[1:] + ("Pancakes!",) * extra, actions=0)
        g.turn = turn
        hand = g.players[0].hand
        assert all(keep_value(c, hand) < min(keep_value(k, hand) for k in hand[:7]) for c in hand[7:])
        return g.controllers[0].effect_ai().evaluate(g, 0)
    assert score(2, turn=0) == pytest.approx(score(0, turn=0))
    assert score(2, turn=1) > score(0, turn=1) + 1.0


def test_michelangelo_keeps_three():
    hand = ("Cowabunga!!", "Boisterous Beatdown", "Nunchaku", "Shell Insertion", "Guaranteed Delivery")
    g = table(("michelangelo", "hellboy"), hand)
    cards = g.players[0].hand
    keeps = sorted((keep_value(c, cards) for c in cards), reverse=True)
    assert hand_room(g, 0) == 3
    assert kept_hand_value(g, 0) == pytest.approx(sum(keeps[:3]))
    ai = g.controllers[0].effect_ai()
    full = ai.evaluate(g, 0)
    worst = min(cards, key=lambda c: keep_value(c, cards))
    cards.remove(worst)
    assert ai.evaluate(g, 0) == pytest.approx(full), "the fifth card of a hand of three was worth nothing"
    assert ai._draws_past_limit(g, 0, {"ops": [{"op": "draw", "player": "owner", "amount": 1}]}) is False     # one action left
    g.actions_left = 0
    assert ai._draws_past_limit(g, 0, {"ops": [{"op": "draw", "player": "owner", "amount": 1}]})


def test_an_ongoing_hand_limit_counts():
    """Pact Of Secrecy: every player keeps three."""
    g = table(("hellboy", "baba-yaga"), LIVE_HAND, actions=0)
    loose = g.controllers[0].terminal_value(g)
    assert hand_room(g, 0) == 7
    g.fx.set_ongoing(1, next(c for c in g.players[1].full_set if c.title == "Pact Of Secrecy").card_id)
    hand = g.players[0].hand
    assert hand_room(g, 0) == 3
    assert kept_hand_value(g, 0) == pytest.approx(sum(sorted((keep_value(c, hand) for c in hand), reverse=True)[:3]))
    assert g.controllers[0].terminal_value(g) < loose - 1.0, "the end of the turn discards down to three"


def riches(hand_size):
    filler = ("Voyage to the Valley of the Giant Snakes", "Voyage to the City of the King of Serendib", "Voyage Home", "Exploit", "Leap Away",
              "Toil and Danger", "Momentous Shift")
    g = table(("sinbad", "hellboy"), ("Riches Beyond Compare",) + filler[:hand_size - 1])
    card = g.players[0].hand[0]
    return g, g.controllers[0].scheme_act(g, card)


def test_a_scheme_that_draws_is_credited_only_the_cards_that_fit():
    """Riches Beyond Compare draws 3: all of them count from a hand of five, one from a hand of seven, none from eight."""
    values = {n: riches(n)[1].value for n in (5, 7, 8)}
    assert values[5] == pytest.approx(values[7] + 2 * CARD_VALUE) and values[7] == pytest.approx(values[8] + CARD_VALUE)
    g, act = riches(8)
    assert len(act.sim.players[0].hand) == 10, "the simulation drew them: the limit takes them at the end of the turn"


def test_a_scheme_that_does_nothing_is_an_act_only_with_an_empty_deck():
    """With cards to draw the maneuver is the better way to pass; with none, the scheme is the pass that does not exhaust."""
    g = hellboy()
    ai, me = g.controllers[0], g.players[0]
    pancakes = me.hand[0]
    assert ai.scheme_act(g, pancakes) is None
    me.removed.extend(me.deck)
    me.deck.clear()
    act = ai.scheme_act(g, pancakes)
    assert act is not None and act.value == pytest.approx(-CARD_VALUE)
