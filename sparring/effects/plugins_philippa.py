"""Philippa's plugins (docs/effects-dsl.md, section 40, docs/heroes/philippa.md).

  philippa:owlform          Owlform: discard any number of cards, +1 to the card's value for each (Raphael's mechanism, every card allowed).
  philippa:chain_lightning  Chain lightning: choose one of the zones Philippa's space belongs to, 1 damage to every opposing fighter in it.
  philippa:blinding_dust    Blinding dust: you may discard a card; if you do, damage to the opposing fighter equal to THAT card's BOOST.
  philippa:do_my_bidding    Do my bidding: the rival's card goes back to their hand and the owner chooses the card they play instead.
  philippa:spymaster_ruse   Spymaster's ruse: the opponent reveals 4 cards of their hand, the owner chooses 2 of them to be discarded.

Every decision is asked before anything moves (an op that pauses runs again and finds its answers). The table player's hand is
virtual in the engine: what they name or lay on the table is read back and swapped in with `table.make_known`, as in Lodge of
sorceresses and Sleight Of Hand."""
from __future__ import annotations

from . import table
from .model import EffectError
from .ops_core import OPS, plugin
from .ops_info import _remember_in_hand
from .plugins_raphael import discard_for_bonus
from .plugins_strange import _unplayed

RUSE_REVEALED = 4        # cards the opponent reveals
RUSE_DISCARDED = 2       # cards of those the owner has discarded


def _flow(run, name: str):
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError(f"{name}: only inside a combat")
    return flow


# ---------------------------------------------------------------- Owlform

@plugin("philippa:owlform")
def _owlform(run, game, spec):
    """"Discard any number of cards from your hand. Add +1 to this card's value for each card discarded." (`tag: any`: the table
    player's panel says every card counts, not only the defense or versatile ones of Raphael's.)"""
    discard_for_bonus(run, game, int((spec.get("args") or {}).get("per_card", 1)), lambda c: True, "philippa:owlform", tag="any")


# ---------------------------------------------------------------- Chain lightning

def zone_foes(game, owner: int, zone: str) -> list:
    """The opposing fighters standing on a space of `zone`."""
    return [f for f in game.fighters.values()
            if f.owner != owner and f.alive and f.pos is not None and zone in game.board.zones(f.pos)]


@plugin("philippa:chain_lightning")
def _chain_lightning(run, game, spec):
    """"Choose a zone Philippa is in. Deal 1 damage to each opposing fighter in that zone." One zone: no question. Several: an `effect`
    request (`tag: zone`, `labels` = the zone names, `hits` = how many opposing fighters each holds, for the bot)."""
    owner = run.ctx.owner
    hero = game.hero(owner)
    if not hero.alive or hero.pos is None:
        return
    zones = sorted(game.board.zones(hero.pos))
    if not zones:
        return
    if len(zones) == 1:
        zone = zones[0]
    else:
        k = run.ask(game, "effect", owner, list(range(len(zones))), 1, 1, "choose a zone", labels=list(zones), tag="zone",
                    hits=[[f.fid for f in zone_foes(game, owner, z)] for z in zones])[0]
        zone = zones[k]
    for f in sorted(zone_foes(game, owner, zone), key=lambda x: x.fid):
        game.damage(f, 1, "effect")
        if game.winner is not None:
            return
    run.flags["chain_zone"] = zone


# ---------------------------------------------------------------- Blinding dust

@plugin("philippa:blinding_dust")
def _blinding_dust(run, game, spec):
    """"You may discard 1 card. If you do, deal damage to the opposing fighter equal to its BOOST value": 'its' is the discarded card.
    The bot's hand is known: one `cards` request (`purpose: dust`, empty = no) that `EffectAI` prices by the blow against the card's
    keep value. The table player says yes or no, then lays the card on their discard pile (`pile_mode: reveal`, `dust`) and the bot
    reads which one it was."""
    flow = _flow(run, "philippa:blinding_dust")
    owner = run.ctx.owner
    foe = flow.att if flow.tgt.owner == owner else flow.tgt
    st = game.players[owner]
    if not st.hand or not foe.alive:
        return
    info = {"foe": foe.fid, "foe_hp": foe.hp}
    if table.physical(game, owner):
        if not run.ask(game, "optional", owner, [True, False], 1, 1, "discard a card for Blinding dust?", dust=info)[0]:
            return
        got = run.ask(game, "cards", owner, _unplayed(st), 1, 1, "put the card in your discard pile", zone="discard", purpose="dust",
                      of=owner, table_discard=True, pile_mode="reveal", dust=True)
        card = {c.card_id: c for c in st.full_set}[got[0]]
        table.make_known(game, owner, card)
    else:
        got = run.ask(game, "cards", owner, [c.card_id for c in st.hand], 0, 1, "discard a card for Blinding dust", zone="hand",
                      purpose="dust", of=owner, **info)
        if not got:
            return
        card = {c.card_id: c for c in st.hand}[got[0]]
    game.discard_card(owner, card)
    if card.boost > 0:
        OPS["damage"](run, game, {"op": "damage", "target": {"role": "opposing"}, "amount": card.boost})


# ---------------------------------------------------------------- Do my bidding

def _bidding_pool(run, game, owner: int, rival: int, attacker, flow, old) -> list[int]:
    """The cards the owner may choose for the rival to play: the cards of their hand the attacking fighter can play against the target
    (the returned card included, which always qualifies), after the look. The table player's hand is what the look showed."""
    st = game.players[rival]
    if table.physical(game, rival):
        ids = list(game.players[owner].known.seen)
        cards = [game.card_of(i, rival) for i in ids]
    else:
        cards = list(st.hand)
    cards.append(old)
    seen, out = set(), []
    for c in cards:
        if c.card_id in seen or not (c.can_attack and c.usable_by(attacker.name) and game.attack_card_reaches(attacker, flow.tgt, c)):
            continue
        seen.add(c.card_id)
        out.append(c.card_id)
    return sorted(out)


@plugin("philippa:do_my_bidding")
def _do_my_bidding(run, game, spec):
    """"Return your opponent's card to their hand. Look at their hand and choose a card for them to play. (It may be the same card.)"
    It runs in the defender's IMMEDIATELY, before the attacker's own effects, so the rival's new card has its IMMEDIATELY run as normal.
    The card goes back to the rival's hand and the chosen one takes its place in the running combat
    (`CombatFlow.replace_attack_card(back_to_hand=True)`: the value of the new card replaces the old one's, the bonuses stay). The same card
    changes nothing. The rival is the engine's player: its table card is swapped by `session_sleight.bot_swap`. The rival is the table
    player: the bot reads their hand (`look_hand`), names the card and they put it at their combat spot instead (`pile_mode: play`)."""
    flow = _flow(run, "philippa:do_my_bidding")
    if run.ctx.played_as != "defense" or flow.atk_card is None or flow.att.owner == run.ctx.owner:
        return
    owner, rival, attacker, old = run.ctx.owner, flow.att.owner, flow.att, flow.atk_card
    OPS["look_hand"](run, game, {"op": "look_hand", "player": "opponent"})
    options = _bidding_pool(run, game, owner, rival, attacker, flow, old)
    if len(options) < 2:
        return                                  # only the returned card: it is played again
    info = {"fighter": attacker.fid, "target": flow.tgt.fid, "old": old.card_id, "atk_value": flow.ctx.atk_value, "def_value": flow.ctx.def_value}
    lo = 0 if table.physical(game, owner) else 1       # the table player sees the bot's hand laid out: the returned card is on its combat spot, so "the same card" is no pick at all
    got = run.ask(game, "cards", owner, options, lo, 1, "choose the card they play", zone="hand", purpose="bidding", of=rival, bidding=info)
    if not got or got[0] == old.card_id:
        return
    new = game.card_of(got[0], rival)
    if table.physical(game, rival):
        picked = run.ask(game, "cards", rival, [new.card_id], 0, 1, "play the card they chose", zone="discard", purpose="swap_attack",
                         of=rival, table_discard=True, pile_mode="play", sleight=True, bidding=True, old=old.card_id, attacker=attacker.fid)
        if not picked:
            return
        table.make_known(game, rival, new)
    flow.replace_attack_card(new, back_to_hand=True)
    flow.again = False                          # Sleight Of Hand re-runs its own side; here the defender's own IMMEDIATELY is done
    run.flags["swapped"] = {"old": old.card_id, "new": new.card_id}


# ---------------------------------------------------------------- Spymaster's ruse

@plugin("philippa:spymaster_ruse")
def _spymaster_ruse(run, game, spec):
    """"Choose an opponent. They reveal 4 cards from their hand. Choose 2 of those cards for them to discard. Then, they draw 2 cards."
    (The draw is the next op of the card.) The opponent chooses the 4 cards (all of them with fewer): the bot reveals its least valuable
    ones (`purpose: ruse_reveal`), the table player names theirs on the panel. The owner then chooses 2 of exactly those (`purpose: ruse`).
    The bot's discards are the engine's; the human's are named in the chat for them to move (the intent `discard` with `cards`)."""
    owner = run.ctx.owner
    rival = 1 - owner
    st = game.players[rival]
    n = min(RUSE_REVEALED, len(st.hand))
    if n <= 0:
        return
    physical = table.physical(game, rival)
    pool = _unplayed(st) if physical else [c.card_id for c in st.hand]
    revealed = run.ask(game, "cards", rival, pool, n, n, "reveal 4 cards", zone="hand", purpose="ruse_reveal", of=rival)
    cards = {c.card_id: c for c in st.full_set}
    shown = [cards[i] for i in revealed]
    k = min(RUSE_DISCARDED, len(shown))
    chosen = run.ask(game, "cards", owner, [c.card_id for c in shown], k, k, "choose 2 cards to discard", zone="hand",
                     purpose="ruse", of=rival)
    done = run.flags.setdefault("ruse_done", {}).setdefault(run._op_key, [])
    if "shown" not in done:
        done.append("shown")
        for card in shown:
            if physical:
                table.make_known(game, rival, card, keep=tuple(shown))
            _remember_in_hand(game, rival, card)
        table.intent(game, op="reveal_show", player=rival, cards=[c.card_id for c in shown])
    if "discarded" not in done:
        done.append("discarded")
        gone = [cards[i] for i in chosen]
        for card in gone:
            game.discard_card(rival, card)
        if physical and gone:
            table.intent(game, op="discard", zone="hand", player=rival, cards=[c.card_id for c in gone], n=len(gone),
                         reason="Spymaster's ruse")
