"""combat_flow.card_by_id must resolve by (owner, card_id): in a mirror match both decks share card ids."""
import copy

from sparring.combat_flow import CombatFlow
from sparring.state import Game

from conftest import Scripted


def mirror(bprd):
    """Game.new refuses the same hero twice, so the mirror is built by giving player 1 copies of player 0's cards."""
    g = Game.new(bprd, 1, controllers={0: Scripted(), 1: Scripted()}, heroes=("hellboy", "medusa"))
    g.players[1].full_set = [copy.copy(c) for c in g.players[0].full_set]
    return g


def test_card_by_id_resolves_by_owner_in_a_mirror_match(bprd):
    g = mirror(bprd)
    card0 = g.players[0].full_set[3]
    card1 = next(c for c in g.players[1].full_set if c.card_id == card0.card_id)
    assert card1 is not card0
    att = next(f for f in g.fighters.values() if f.owner == 0)
    tgt = next(f for f in g.fighters.values() if f.owner == 1)
    flow = CombatFlow(g, att, tgt, card0, None)
    assert flow.card_by_id(card0.card_id, 0) is card0
    assert flow.card_by_id(card0.card_id, 1) is card1
