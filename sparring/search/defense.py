"""The defense against a face-down attack, settled by the combat itself when the tree cannot tell the options apart.

Why: at a defense the tree has a handful of options and a couple of hundred iterations, and its leaf prices a defense card kept for the
rival's next blows about as much as the damage it stops now, so the root values come out within their own noise (Hellboy against a
Clone of Sun Wukong, 20/11: no defense 0.579, Glimpse Of Hell 0.564, B.P.R.D. Training 0.551 at 50 visits each) and the visit counts
chose no defense twice in a row, against an attack that could have been Ox Form's 7. The ledger is the part of that decision that
needs no sampling of the future: every card the rival may have played (its set minus the public piles, each copy weighed by its
chance of being in a hand of that size; a card known to be there counts whole) is fought against every defense through the engine,
the second part of a double attack included (Ivan D8: Ruyi Jingo Bang's TRICKED YOU only when a card is played), and what the
defender loses is added up in hit points, a card spent and not drawn back being `card_hp` of them.

The tree keeps the decision whenever it is sure of it: the ledger replaces its move only by one the ledger finds clearly cheaper
(`CLEAR_HP`) and the tree does not rate clearly below (`GAIN_SIGMAS` standard errors of its own values), and never to spend the last
card of the hand (Ivan, 16/11). Nothing here reads the rival's hand or the face-down card: only its size, the public piles and what a
look effect showed (`Knowledge`)."""
from __future__ import annotations

import random

from ..cards import Card
from ..combat import resolve_combat
from .adapter import EngineState, by_title
from .ismcts import SearchReport
from .plans import GAIN_SIGMAS

CLEAR_HP = 1.0      # what the ledger's move must save over the tree's, in hit points (card prices included), to replace it
WORLDS = 3          # determinizations each attack card is fought in (the defender's draws and the rival's other cards differ)
FALLEN = 100.0      # the defender's hero falling, off any scale of hit points


def beliefs(state: EngineState) -> list[tuple[Card, float]]:
    """(card, probability) for every title the face-down attack may be, as `EngineState.determinize` deals it: the known cards of the
    rival's hand are in it, each unseen card with the chance of a hand of that size holding it."""
    g = state.game
    attacker = g.fighters[state.pending[0]]
    p = attacker.owner
    st = g.players[p]
    gone = st.gone
    known = [c for c in state.knowledge.known_in_hand.get(p, ()) if c not in gone]
    top = [c for c in state.knowledge.top_of_deck.get(p, ()) if c not in gone and c not in known]
    pool = [c for c in st.full_set if c not in gone and c not in known and c not in top]
    usable = lambda cards: [c for c in cards if c.can_attack and c.usable_by(attacker.name)]
    share = max(0, len(st.hand) - len(known)) / len(pool) if pool else 0.0
    weighed = [(c, 1.0) for c in usable(known)] + [(c, share) for c in usable(pool) if share]
    if not weighed:         # what is public does not explain the attack: any attack card still unseen
        weighed = [(c, 1.0) for c in usable(pool)]
    total = sum(w for _, w in weighed)
    titles: dict[str, list] = {}
    for c, w in weighed:
        titles.setdefault(c.title, [c, 0.0])[1] += w / total
    return [(c, w) for c, w in titles.values()]


def ledger(root: EngineState, seed: int) -> dict:
    """move -> expected loss of the defender's side in the combat, in hit points: those its fighters lose (less those they recover), the
    cards its hand ends short of at `card_hp` each, and the hero falling. Empty when no attack card can be named."""
    me = root.player_to_move()
    att, tgt, _ = root.pending
    moves = root.legal_moves()
    price = root.weights.card_hp or root.weights.defend_card_hp
    cards = beliefs(root)
    loss = dict.fromkeys(moves, 0.0) if cards else {}
    rng = random.Random(seed)
    for card, weight in cards:
        for _ in range(WORLDS):
            world = root.clone()
            world.determinize(me, rng)
            world.commit(card)
            stream = rng.getrandbits(64)
            for move in moves:
                g = world.clone().game
                g.rng = random.Random(stream)       # the same shuffles and draws for every defense
                mine = g.players[me]
                hp, held = sum(f.hp for f in g.own(me)), len(mine.hand)      # of the fighters standing: one in the supply (a Clone) holds hit points too
                resolve_combat(g, g.fighters[att], g.fighters[tgt], card, by_title(mine.hand, move[1]) if move[1] is not None else None)
                lost = hp - sum(f.hp for f in g.own(me)) + price * (held - len(mine.hand))
                loss[move] += weight / WORLDS * (lost + (FALLEN if g.winner == 1 - me else 0.0))
    return loss


def settle(root: EngineState, report: SearchReport | None, move, seed: int):
    """The defense to play: the tree's `move`, or the one the ledger finds at least `CLEAR_HP` cheaper among those the tree does not
    rate clearly below it. The report keeps what was measured."""
    if root.pending is None or root.pending[2] is not None or report is None or not report.values:
        return move         # an attack played face up is one known card: the tree fought exactly that combat
    loss = ledger(root, seed)
    if not loss:
        return move
    last_card = len(root.game.players[root.player_to_move()].hand) <= 1

    def open_to(other) -> bool:
        if other == move or (other[1] is not None and last_card) or loss[move] - loss[other] < CLEAR_HP:
            return False
        if move not in report.errors or other not in report.errors:
            return True         # too few visits to say anything
        noise = (report.errors[move] ** 2 + report.errors[other] ** 2) ** 0.5
        return report.values[move] - report.values[other] <= GAIN_SIGMAS * noise

    best = min((m for m in loss if open_to(m)), key=lambda m: loss[m], default=move)
    report.ledger = {"loss": {str(m[1]): round(v, 3) for m, v in loss.items()}, "tree": move[1], "settled": best[1]}
    report.move = best
    return best
