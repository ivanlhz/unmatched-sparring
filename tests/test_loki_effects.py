"""Loki on the interpreter, bot side (player 0 plays Loki, the controllers answer): MISCHIEF-MONGER (a TRICK changes hands, a discarded TRICK
returns, +1 to the move per TRICK in the rival's hand) and every card of the deck with the numbers printed on it (sheet 176, read from the
images on 2026-11-22). Loki as the HUMAN's hero and the human holding his cards are in tests/test_loki_human.py; the full games in
tests/test_loki_matrix.py; the AI in tests/test_loki_ai.py. Design: docs/heroes/loki.md."""
from __future__ import annotations

import pytest

from conftest import give
from sparring import tricks
from sparring.effects.choose import ControllerChooser
from sparring.effects.run import Ctx, EffectRun
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import hand_filler, pair, put_adjacent


BALDR, FREYJA, SINDRI, LURE = "Trick: Baldr's Downfall", "Trick: Freyja's Rescue", "Trick: Sindri's Bet", "Trick: Svadilfari's Lure"
TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def mk(bprd, foe="medusa", seed=3, turn=0):
    """Loki = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands. Medusa shares Loki's CardIDs (sheet 176)."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("loki", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


class ByKind(Answers):
    """Answers a request by its kind (`{"optional": [False]}`), whatever order the other cards ask in; anything else gets the generic answer."""

    def __init__(self, answers):
        super().__init__()
        self.answers = answers

    def choose_effect(self, game, req):
        self.requests.append(req)
        a = self.answers.get(req.kind)
        return a(req) if callable(a) else a


def lend(g, to, title):
    """A TRICK of Loki's deck in `to`'s hand, as the game puts it there (Loki is player 0)."""
    card = next(c for c in g.players[0].full_set if c.title == title and c not in g.players[0].discard and c not in g.players[1].hand)
    if card in g.players[0].deck:
        g.players[0].deck.remove(card)
    if card in g.players[0].hand:
        g.players[0].hand.remove(card)
    g.players[to].hand.append(card)
    if to == 1:
        g.players[0].known.foreign.append(card.card_id)
    return card


# ---------------------------------------------------------------- the hero

def test_loki_is_a_melee_hero_without_sidekicks_and_has_the_printed_deck(bprd):
    g = mk(bprd)
    loki = g.fighters["loki"]
    assert (loki.hp, loki.move, loki.ranged, loki.name) == (16, 2, False, "Loki")
    assert [f.fid for f in g.own(0)] == ["loki"]
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert "loki" in g.fx.dsl_heroes


def test_the_sheet_follows_the_images(bprd):
    deck = {c.card_id: c for c in mk(bprd).players[0].full_set}
    by_idx = lambda i: deck[17600 + i]
    assert [by_idx(i).title for i in (0, 2, 6, 9, 12, 15, 18, 21, 24, 26, 28)] == [
        "Ragnarök", "Shapeshifter", "Looking For Trouble", BALDR, "God Of Mischief", "Malicious Flyting", "Underhanded", "Laevateinn",
        FREYJA, SINDRI, LURE]
    assert [(by_idx(i).type, by_idx(i).value, by_idx(i).boost) for i in (0, 2, 6, 9, 12, 15, 18, 21, 24, 26, 28)] == [
        ("attack", 0, 3), ("attack", 0, 2), ("attack", 4, 3), ("attack", 4, 0), ("versatile", 2, 3), ("versatile", 3, 3),
        ("versatile", 3, 2), ("versatile", 2, 3), ("versatile", 2, 0), ("defense", 3, 0), ("scheme", None, 0)]


def test_the_four_tricks_are_tagged_any_fighter_and_cannot_boost(bprd):
    deck = mk(bprd).players[0].full_set
    tricky = [c for c in deck if tricks.is_trick(c)]
    assert len(tricky) == 9 and {c.title for c in tricky} == {BALDR, FREYJA, SINDRI, LURE}
    assert {c.fighter for c in tricky} == {"any"} and all(c.boost == 0 for c in tricky)
    assert not any(tricks.is_trick(c) for c in deck if c not in tricky)


# ---------------------------------------------------------------- MISCHIEF-MONGER: where a TRICK goes

def test_a_trick_loki_plays_goes_to_the_opponents_hand_not_to_his_discard(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    trick = give(g, 0, BALDR)
    g.attack(loki, foe, trick, None)
    assert trick in g.players[1].hand and trick not in g.players[0].discard
    assert g.players[0].known.foreign == [trick.card_id]
    assert g.counter(0, "trick_in_rival_hand") == 1


def test_a_trick_the_opponent_plays_goes_to_lokis_discard(bprd):
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    trick = lend(g, 1, BALDR)
    g.attack(foe, loki, trick, None)
    assert trick in g.players[0].discard and trick not in g.players[1].discard and trick not in g.players[1].hand
    assert g.players[0].known.foreign == []


def test_a_card_that_is_not_a_trick_goes_to_its_players_discard_as_always(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    card = give(g, 0, "Underhanded")
    g.attack(loki, foe, card, None)
    assert card in g.players[0].discard and not g.players[1].hand


def test_a_trick_discarded_from_the_opponents_hand_returns_to_loki(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[False]]
    trick = lend(g, 1, SINDRI)
    g.discard_card(1, trick, cause="hand_limit")
    assert trick in g.players[0].hand and trick not in g.players[1].discard and trick not in g.players[1].hand
    assert g.players[0].known.foreign == []


def test_the_bot_puts_a_returned_trick_on_top_of_its_deck_when_its_hand_is_full(bprd):
    g = mk(bprd)
    hand_filler(g, 0, 6)
    trick = lend(g, 1, SINDRI)
    g.discard_card(1, trick)
    assert trick not in g.players[0].hand and g.players[0].deck[0] is trick and len(g.players[0].hand) == 6


def test_the_hand_limit_discard_of_a_trick_returns_it_too(bprd):
    g = mk(bprd, turn=1)
    trick = lend(g, 1, LURE)
    hand_filler(g, 1, 7)
    g.controllers[1].discards = [trick]                                              # the foe chooses the TRICK as the card the hand limit takes
    g.end_turn()
    assert len(g.players[1].hand) == 7 and trick in g.players[0].hand and trick not in g.players[1].discard
    assert g.players[0].known.foreign == []


def test_a_random_discard_that_takes_a_trick_returns_it_to_loki(bprd):
    g = mk(bprd)
    trick = lend(g, 1, FREYJA)
    g.players[1].hand[:] = [trick]                                                   # the only card: the random pick cannot miss it
    ops = [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "pick": "random", "amount": 1}}]
    EffectRun(ops, Ctx(owner=0, this_fid="loki")).run(g, {0: ControllerChooser(), 1: ControllerChooser()})
    assert trick in g.players[0].hand and trick not in g.players[1].discard and not g.players[1].hand


# ---------------------------------------------------------------- +1 to the move per TRICK in an opponent's hand

def test_each_trick_in_the_rivals_hand_adds_a_space_to_the_maneuver(bprd):
    g = mk(bprd)
    assert g.maneuver_bonus(0) == 0
    lend(g, 1, BALDR)
    lend(g, 1, FREYJA)
    assert g.maneuver_bonus(0) == 2 and g.maneuver_bonus(1) == 0


# ---------------------------------------------------------------- the deck, card by card (Loki attacks or defends)

def attack(g, title, foe_card=None, trick_in_hand=0, foe_hand=0):
    loki, foe = pair(g, "loki", "medusa")
    card = give(g, 0, title)
    for _ in range(trick_in_hand):
        lend(g, 1, BALDR if len([c for c in g.players[1].hand if tricks.is_trick(c)]) < 3 else FREYJA)
    if foe_hand:
        hand_filler(g, 1, foe_hand, avoid=("Hiss and Slither",))
    defense = give(g, 1, foe_card) if foe_card else None
    return g.attack(loki, foe, card, defense)


def test_ragnarok_adds_three_per_trick_in_the_rivals_hand_and_cannot_be_canceled(bprd):
    g = mk(bprd)
    assert attack(g, "Ragnarök", trick_in_hand=2).atk_value == 6
    g = mk(bprd)
    assert attack(g, "Ragnarök").atk_value == 0
    g = mk(bprd)
    assert attack(g, "Ragnarök", "Feint", trick_in_hand=1).atk_value == 3          # Feint cancels the effects of the card it meets, not this one


def test_shapeshifter_adds_one_per_card_in_the_rivals_hand(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[0]]
    assert attack(g, "Shapeshifter", foe_hand=4).atk_value == 4


def test_shapeshifter_may_gain_an_action_instead(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[1]]
    res = attack(g, "Shapeshifter", foe_hand=4)
    assert res.atk_value == 0 and g.actions_left == 2


def test_underhanded_is_six_when_the_rival_holds_more_cards(bprd):
    g = mk(bprd)
    assert attack(g, "Underhanded", foe_hand=2).atk_value == 6
    g = mk(bprd)
    hand_filler(g, 0, 2)
    assert attack(g, "Underhanded", foe_hand=2).atk_value == 3                       # 2 against 2: not more


def test_god_of_mischief_cancels_the_effects_of_a_card_that_is_not_a_trick(bprd):
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    res = g.attack(foe, loki, give(g, 1, "Snipe"), give(g, 0, "God Of Mischief"))      # Snipe draws a card after combat
    assert (res.atk_value, res.def_value) == (3, 2) and not g.players[1].hand
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    g.attack(foe, loki, give(g, 1, "Snipe"), give(g, 0, "Underhanded"))               # control: without it the card is drawn
    assert len(g.players[1].hand) == 1


def test_god_of_mischief_ignores_the_value_of_a_trick(bprd):
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    trick = lend(g, 1, BALDR)
    res = g.attack(foe, loki, trick, give(g, 0, "God Of Mischief"))
    assert res.atk_value == 0 and res.def_value == 2


def test_malicious_flyting_draws_one_or_two_if_the_rival_played_a_trick(bprd):
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    flyting = give(g, 0, "Malicious Flyting")
    g.attack(foe, loki, give(g, 1, "Dash"), flyting)
    assert len(g.players[0].hand) == 1
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    flyting = give(g, 0, "Malicious Flyting")
    g.attack(foe, loki, lend(g, 1, BALDR), flyting)
    assert len(g.players[0].hand) == 2


# ---------------------------------------------------------------- the TRICKs as Loki plays them and as the opponent plays them

def test_baldrs_downfall_draws_for_loki_and_hurts_the_hero_of_anyone_else(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    g.attack(loki, foe, give(g, 0, BALDR), None)
    assert len(g.players[0].hand) == 1                                          # the drawn card; the TRICK went to the other hand
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    hp = foe.hp
    res = g.attack(foe, loki, lend(g, 1, BALDR), None)
    assert res.atk_value == 4 and foe.hp == hp - 2 and len(g.players[0].hand) == 0


def test_freyjas_rescue_swaps_the_values_for_loki(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    res = g.attack(loki, foe, give(g, 0, FREYJA), give(g, 1, "Dash"))           # 2 against 3: swapped
    assert (res.atk_value, res.def_value) == (3, 2)


def test_freyjas_rescue_played_by_the_opponent_heals_loki_three(bprd):
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    loki.hp = 10
    g.attack(foe, loki, lend(g, 1, FREYJA), None)
    assert loki.hp == 11                                                        # 10 - 2 (the attack, no defense) + 3


def test_sindris_bet_loki_side_takes_three_unless_the_opponent_discards(bprd):
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    g.controllers[1] = ByKind({"optional": [False]})
    res = g.attack(foe, loki, give(g, 1, "Dash"), give(g, 0, SINDRI))
    assert (res.atk_value, res.def_value) == (0, 3)                             # Dash 3 - 3 = 0
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    spare = hand_filler(g, 1, 1)[0]
    g.controllers[1] = ByKind({"optional": [True], "cards": lambda req: [spare.card_id]})
    res = g.attack(foe, loki, give(g, 1, "Dash"), give(g, 0, SINDRI))
    assert res.atk_value == 3 and spare in g.players[1].discard


def test_sindris_bet_with_nothing_to_discard_costs_three(bprd):
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    res = g.attack(foe, loki, give(g, 1, "Dash"), give(g, 0, SINDRI))
    assert res.atk_value == 0


def test_sindris_bet_played_by_the_opponent_returns_the_top_of_lokis_discard(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    old = g.players[0].full_set[0]
    g.players[0].deck.remove(old)
    g.players[0].discard.append(old)
    g.attack(loki, foe, give(g, 0, "Underhanded"), lend(g, 1, SINDRI))
    assert old in g.players[0].hand and old not in g.players[0].discard


def test_svadilfaris_lure_places_an_opposing_fighter_next_to_loki(bprd):
    g = mk(bprd, foe="hellboy")
    loki, hell = g.fighters["loki"], g.fighters["hellboy"]
    far = max(g.board.spaces, key=lambda s: g.board.distance(loki.pos, s) if hasattr(g.board, "distance") else s)
    card = give(g, 0, LURE)
    g.controllers[0].queue = [lambda req: [req.options[0]], lambda req: [req.options[0]]]
    g.play_scheme(0, loki, card)
    assert hell.pos in g.board.adj[loki.pos]
    assert card in g.players[1].hand


def test_svadilfaris_lure_played_by_the_opponent_discards_a_random_card_of_their_hand(bprd):
    g = mk(bprd, turn=1)
    foe = g.fighters["medusa"]
    hand_filler(g, 1, 3)
    card = lend(g, 1, LURE)
    before = len(g.players[1].hand)
    g.play_scheme(1, foe, card)
    assert len(g.players[1].hand) == before - 2 and len(g.players[1].discard) <= 1       # the scheme left the hand, a random card was discarded
    assert card in g.players[0].discard


# ---------------------------------------------------------------- Laevateinn

def test_laevateinn_adds_the_boost_of_the_card_it_reveals(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    give(g, 1, "Gaze of Stone")                                                    # BOOST 4, the only card of the hand
    res = g.attack(loki, foe, give(g, 0, "Laevateinn"), None)
    assert res.atk_value == 2 + 4


def test_laevateinn_with_an_empty_hand_reveals_nothing(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    assert g.attack(loki, foe, give(g, 0, "Laevateinn"), None).atk_value == 2


def test_laevateinn_that_reveals_a_trick_puts_it_in_lokis_hand_and_adds_nothing(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    trick = lend(g, 1, FREYJA)
    res = g.attack(loki, foe, give(g, 0, "Laevateinn"), None)
    assert res.atk_value == 2 and trick in g.players[0].hand and not g.players[1].hand
    assert g.players[0].known.foreign == [] and g.counter(0, "trick_in_rival_hand") == 0


def test_laevateinn_picks_blind_every_card_of_the_hand_can_be_the_one(bprd):
    seen = set()
    for seed in range(40):
        g = mk(bprd, seed=seed)
        loki, foe = pair(g, "loki", "medusa")
        give(g, 1, "Gaze of Stone")
        give(g, 1, "Dash")
        seen.add(g.attack(loki, foe, give(g, 0, "Laevateinn"), None).atk_value)
    assert seen == {2 + 4, 2 + 1}


# ---------------------------------------------------------------- Looking For Trouble

def test_looking_for_trouble_makes_the_rival_play_the_card_loki_chooses(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    regroup = give(g, 1, "Regroup")
    hiss = give(g, 1, "Hiss and Slither")
    g.controllers[0] = ByKind({"cards": [regroup.card_id]})
    res = g.attack(loki, foe, give(g, 0, "Looking For Trouble"), hiss)
    assert res.def_card == regroup and res.def_value == 1
    assert hiss in g.players[1].hand and regroup in g.players[1].discard
    assert hiss in g.players[0].known.cards(g.players[1])                        # Loki saw it come back


def test_looking_for_trouble_may_choose_the_card_they_already_played(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    give(g, 1, "Regroup")
    hiss = give(g, 1, "Hiss and Slither")
    g.controllers[0] = ByKind({"cards": [hiss.card_id]})
    res = g.attack(loki, foe, give(g, 0, "Looking For Trouble"), hiss)
    assert res.def_card == hiss and res.def_value == 4


def test_looking_for_trouble_may_choose_a_trick_of_their_hand(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    trick = lend(g, 1, SINDRI)
    hiss = give(g, 1, "Hiss and Slither")
    g.controllers[0] = ByKind({"cards": [tricks.qualified(trick)]})
    res = g.attack(loki, foe, give(g, 0, "Looking For Trouble"), hiss)
    assert res.def_card == trick and res.def_value == 3 and hiss in g.players[1].hand
    assert trick in g.players[0].discard and trick not in g.players[1].hand       # played by the opponent: Loki's discard


def test_looking_for_trouble_against_no_card_does_nothing(bprd):
    g = mk(bprd)
    loki, foe = pair(g, "loki", "medusa")
    give(g, 1, "Regroup")
    res = g.attack(loki, foe, give(g, 0, "Looking For Trouble"), None)
    assert res.def_card is None and res.atk_value == 4


# ---------------------------------------------------------------- decks that share CardIDs

def test_a_trick_and_a_card_of_the_opponent_with_the_same_id_are_told_apart(bprd):
    g = mk(bprd, turn=1)
    loki, foe = pair(g, "loki", "medusa")
    trick = lend(g, 1, BALDR)                                                    # 17609 .. in Loki's deck
    twin = next(c for c in g.players[1].full_set if c.card_id == trick.card_id)
    assert twin != trick and twin.title == "Dash"
    g.players[1].hand.append(twin)
    res = g.attack(foe, loki, trick, None)
    assert res.atk_card == trick and res.atk_value == 4
    assert twin in g.players[1].hand and trick in g.players[0].discard
    assert g.players[0].known.cards(g.players[1]) == []                          # nothing of the rival's own deck is "seen"
