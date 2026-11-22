"""Loki's plugins (docs/heroes/loki.md): loki:swap_values, loki:laevateinn, loki:looking_for_trouble, loki:return_trick.

A TRICK is a card of LOKI's deck that may lie in the opponent's hand (`sparring/tricks.py`): decks of sheet 176 share CardIDs, so the cards
these plugins hand around are objects, and an id that may name a card of either deck is written `tricks.qualified` (id + QUALIFIED when the
card is a TRICK of Loki's deck held by the other player) and read back with `tricks.card_from_option`.

Every decision is asked before anything moves (an op that pauses runs again and finds its answers)."""
from __future__ import annotations

from .. import tricks
from ..i18n import t
from . import modifiers, table
from .model import EffectError
from .ops_core import plugin

BOT_FULL_HAND = 7          # the bot puts a returned TRICK on top of its deck instead of its hand when that hand would be at the limit of 7


def _flow(run, name: str):
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError(f"{name}: only inside a combat")
    return flow


def _side(run) -> str:
    return "atk" if run.ctx.played_as == "attack" else "def"


# ---------------------------------------------------------------- Freyja's Rescue

@plugin("loki:swap_values")
def _swap_values(run, game, spec):
    """"Swap the values of your card and your opponent's card": the running values of the two sides at this moment (the printed value, the
    bonuses and the DURING effects that already ran) trade places. Nothing to swap with when the opponent played no card."""
    flow = _flow(run, "loki:swap_values")
    if flow.atk_card is None or flow.def_card is None:
        return
    mine = _side(run)
    theirs = "def" if mine == "atk" else "atk"
    ctx = flow.ctx
    mine_now, theirs_now = (ctx.atk_value, ctx.def_value) if mine == "atk" else (ctx.def_value, ctx.atk_value)
    label = t("cf.swap_values")
    modifiers.add_value(flow, mine, theirs_now - mine_now, label)
    modifiers.add_value(flow, theirs, mine_now - theirs_now, label)


# ---------------------------------------------------------------- Laevateinn

def _reveal_options(game, victim: int, loki: int) -> list[int]:
    """What may lie at the position Loki picked in the table player's hand: every card of their deck that is not in a public pile (one id per
    title: copies are interchangeable, and the panel holds 30 buttons at most), and the TRICKs of Loki's deck the engine knows they hold (listed first)."""
    st = game.players[victim]
    gone = {c.card_id for c in st.gone}
    by_title: dict[str, int] = {}
    for c in st.full_set:
        if c.card_id not in gone:
            by_title.setdefault(c.title, c.card_id)
    return [tricks.qualified(c) for c in tricks.tricks_in_rival_hand(game, loki)] + list(by_title.values())      # the TRICKs first: they fit the first page of the panel


@plugin("loki:laevateinn")
def _laevateinn(run, game, spec):
    """"Reveal a card in your opponent's hand. Add its BOOST value to this card's value. If you reveal a TRICK, put it in your hand."
    Loki picks blind (Ivan 2026-11-22, LO1): a uniform random position, never by hidden information. The engine's hand is revealed as it is;
    the table player's is virtual, so they say which card is at the position the bot names (`purpose: reveal`) and the engine learns it."""
    flow = _flow(run, "loki:laevateinn")
    owner = run.ctx.owner
    victim = 1 - owner
    st = game.players[victim]
    if not st.hand:
        return
    if table.physical(game, victim):
        from .ops_core import _card_title, _random_positions_text
        which = _random_positions_text(game, run, victim, 1, _card_title(game, run))
        got = run.ask(game, "cards", victim, _reveal_options(game, victim, owner), 1, 1, "show the card Loki picks", zone="hand",
                      purpose="reveal", of=victim, which=which)
        card = tricks.card_from_option(game, victim, owner, got[0])
        table.make_known(game, victim, card)
    else:
        card = run.random_sample(list(st.hand), 1)[0]
    modifiers.add_value(flow, _side(run), card.boost, t("cf.laevateinn", title=card.title, boost=card.boost))
    if tricks.is_trick(card):
        tricks.take(game, victim, owner, card)


# ---------------------------------------------------------------- Looking For Trouble

def _trouble_pool(game, run, owner: int, rival: int, defender, flow, old) -> list[int]:
    """The cards the owner may choose for the rival to play as their defense: the cards of their hand that can defend (a TRICK of Loki's included,
    LO4) and the returned card, which always qualifies. The table player's hand is what the look showed."""
    st = game.players[rival]
    if table.physical(game, rival):
        cards = [game.card_of(i, rival) for i in game.players[owner].known.seen] + tricks.tricks_in_rival_hand(game, owner)
    else:
        cards = list(st.hand)
    cards.append(old)
    seen, out = set(), []
    for c in cards:
        key = tricks.qualified(c) if tricks.borrowed(game, rival, c) else c.card_id
        if key in seen or not (c.can_defend and c.usable_by(defender.name)):
            continue
        seen.add(key)
        out.append(key)
    return sorted(out)


@plugin("loki:looking_for_trouble")
def _looking_for_trouble(run, game, spec):
    """"If your opponent played a card, return it to their hand, look at their hand, and choose a card for them to play." Loki's card attacks, so
    the opponent's card is their defense: it goes back to their hand and the card Loki chooses (it may be the same one, or a TRICK, LO4)
    is played instead (`CombatFlow.replace_defense_card`): its value takes the old one's place and its IMMEDIATELY runs now."""
    flow = _flow(run, "loki:looking_for_trouble")
    if run.ctx.played_as != "attack" or flow.def_card is None:
        return
    owner, rival, defender, old = run.ctx.owner, flow.tgt.owner, flow.tgt, flow.def_card
    from .ops_core import OPS
    OPS["look_hand"](run, game, {"op": "look_hand", "player": "opponent"})
    options = _trouble_pool(game, run, owner, rival, defender, flow, old)
    own_key = tricks.qualified(old) if tricks.borrowed(game, rival, old) else old.card_id
    if len(options) < 2:
        return                                  # only the returned card: it is played again
    lo = 0 if table.physical(game, owner) else 1
    got = run.ask(game, "cards", owner, options, lo, 1, "choose the card they play", zone="hand", purpose="trouble", of=rival,
                  trouble={"fighter": defender.fid, "attacker": flow.att.fid, "old": old.card_id})
    if not got or got[0] == own_key:
        return
    new = tricks.card_from_option(game, rival, owner, got[0])
    if table.physical(game, rival):
        picked = run.ask(game, "cards", rival, [got[0]], 0, 1, "play the card they chose", zone="discard", purpose="swap_defense",
                         of=rival, table_discard=True, pile_mode="play", sleight=True, trouble=True, old=old.card_id, fighter=defender.fid)
        if not picked:
            return
        table.make_known(game, rival, new)
    flow.replace_defense_card(new)
    run.flags["swapped"] = {"old": old.card_id, "new": new.card_id}


# ---------------------------------------------------------------- MISCHIEF-MONGER, the returned TRICK

@plugin("loki:return_trick")
def _return_trick(run, game, spec):
    """The TRICK an opponent discarded from their hand is in Loki's hand already (`tricks.discarded`): Loki may put it on top of his deck
    instead. The human Loki answers one yes / no ("on top of your deck?"); the bot decides by the size of its hand (a card in hand is a card it
    can play now, but a hand at the limit would have to discard)."""
    owner = run.ctx.owner
    ids = run.bound("card", "cards")
    card = next((c for c in game.players[owner].hand if c.card_id == ids[0] and tricks.is_trick(c)), None)
    if card is None:
        return
    if table.physical(game, owner):          # Loki is at the table: they say it on the panel
        on_top = run.ask(game, "optional", owner, [True, False], 1, 1, "put it on top of your deck?", trick_deck=card.title)[0]
    else:                                    # the bot keeps the card in hand to play it, unless the hand is full: then it waits on top of the deck
        on_top = len(game.players[owner].hand) >= BOT_FULL_HAND
    if on_top:
        tricks.to_deck_top(game, owner, card)
