"""Doctor Strange's plugins (docs/effects-dsl.md, section "Doctor Strange"): `strange:blind_boost`,
`strange:mists_of_munnopor` and `strange:reveal_to_top`.

All three touch cards that the human holds or whose order only their deck decides, so each has two variants, chosen
with `table.physical` (the player who sits at the real table):

- the engine's player (the bot, a simulation, a search clone) is fully resolved here: its own deck is known to the
  engine, the rival hand is never read;
- the human is asked a `cards` request with `table_discard` and a `pile_mode`; the session tells them what to put where,
  reads the table (`session_rage`) and answers with the cards it found, so the engine never sees their hand or deck."""
from __future__ import annotations

from ..i18n import t
from . import modifiers, table
from .model import EffectError
from .ops_core import plugin


def _flow(run, name: str):
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError(f"{name}: only inside a combat")
    return flow


def _title(run, game) -> str:
    card = None if run.ctx.card_id is None else game.card_of(run.ctx.card_id, run.ctx.owner)
    return card.title if card is not None else t("cause.effect")


def _unplayed(st) -> list[int]:
    """The cards of a player that may still be in their hand or deck (not in a pile apart)."""
    gone = {c.card_id for c in st.gone}
    return [c.card_id for c in st.full_set if c.card_id not in gone]


# ---------------------------------------------------------------- BLIND BOOST

@plugin("strange:blind_boost")
def _blind_boost(run, game, spec):
    """"You may BLIND BOOST this card (up to N times)": the top card of the owner's deck is discarded and its BOOST value
    added to the card's value; the owner decides each time. For the human the real top cards are laid on their discard
    pile by them (a `cards` request up to N) and the engine drops them from its virtual deck."""
    flow = _flow(run, "strange:blind_boost")
    args = spec.get("args") or {}
    times, limit = int(args["times"]), args.get("ignore_above")
    owner = run.ctx.owner
    side = "atk" if run.ctx.played_as == "attack" else "def"
    st, label = game.players[owner], _title(run, game)
    if table.physical(game, owner):
        got = run.ask(game, "cards", owner, _unplayed(st), 0, times, "blind boost", zone="discard", purpose="bonus",
                      of=owner, table_discard=True, pile_mode="blind", times=times)
        by_id = {c.card_id: c for c in st.full_set}
        for card_id in got:
            card = by_id[card_id]
            table.take_from_deck(game, owner, card)
            st.discard.append(card)
            game.fx.emit("card_discarded", owner, card, "deck")
            modifiers.add_value(flow, side, card.boost, t("cf.blind_boost", title=card.title, boost=card.boost))
        return
    for done in range(times):
        if not st.deck:
            return
        mine, theirs = (flow.ctx.atk_value, flow.ctx.def_value) if side == "atk" else (flow.ctx.def_value, flow.ctx.atk_value)
        yes = run.ask(game, "optional", owner, [True, False], 1, 1, "blind boost?", blind_boost=True, left=times - done,
                      attacking=side == "atk", margin=mine - theirs, value=mine, limit=limit, target=flow.tgt.fid)[0]
        if not yes:
            return
        top = st.deck.pop(0)
        st.discard.append(top)
        game.players[1 - owner].known.drop_top(top.card_id)
        run.flags.setdefault("deck_discards", []).append(top.card_id)
        game.fx.emit("card_discarded", owner, top, "deck")
        modifiers.add_value(flow, side, top.boost, t("cf.blind_boost", title=top.title, boost=top.boost))


# ---------------------------------------------------------------- The Mists of Munnopor

@plugin("strange:mists_of_munnopor")
def _mists(run, game, spec):
    """"Discard your opponent's card. They reveal cards from their deck until they reveal an attack or versatile card
    they can play. They play that card and randomly put the rest of the revealed cards on the bottom of their deck."
    The attacker's card is replaced inside the running combat (`CombatFlow.replace_attack_card`). The rival is the
    engine's player: its deck is revealed here (`reveal_deck` intent: the session names the cards). The rival is the
    human: they reveal by hand and play what they find; the session reads it from their combat spot."""
    flow = _flow(run, "strange:mists_of_munnopor")
    if run.ctx.played_as != "defense":
        return
    rival, attacker = flow.att.owner, flow.att
    st = game.players[rival]
    old = flow.atk_card
    if table.physical(game, rival):
        options = [i for i in _unplayed(st) if _playable(game.card_of(i, rival), attacker)]
        got = run.ask(game, "cards", rival, options, 0, 1, "play the card the reveal finds", zone="discard", purpose="bonus",
                      of=rival, table_discard=True, pile_mode="play", old=old.card_id, attacker=attacker.fid)
        new = None if not got else game.card_of(got[0], rival)
        if new is not None:
            table.take_from_deck(game, rival, new)     # it came off their real deck into play
        game.players[1 - rival].known.clear_top()
        flow.replace_attack_card(new)
        return
    revealed, found = [], None
    for card in st.deck:
        revealed.append(card)
        if _playable(card, attacker):
            found = card
            break
    rest = [c for c in revealed if c is not found]
    order = run.random_sample(rest, len(rest)) if rest else []
    for card in revealed:
        st.deck.remove(card)
    st.deck.extend(order)
    game.players[1 - rival].known.clear_top()
    table.intent(game, op="reveal_deck", player=rival, revealed=[c.card_id for c in revealed],
                 found=None if found is None else found.card_id, source=old.card_id)
    flow.replace_attack_card(found)


def _playable(card, attacker) -> bool:
    return card.can_attack and card.usable_by(attacker.name)


# ---------------------------------------------------------------- No, Really, I'm a Doctor

@plugin("strange:reveal_to_top")
def _reveal_to_top(run, game, spec):
    """"Reveal a card from your hand and put it on top of your deck": the owner picks it, the rival sees it (it becomes
    the known top card of that deck) and the card is bound (`as`) for the heal. The bot picks the card that heals
    most for the least it loses (`EffectAI`: a `cards` request with `purpose: "reveal_top"`). The human lays the card
    on their discard pile, the bot reads it there and puts it on top of their deck (`stack_top` intent)."""
    owner, name = run.ctx.owner, (spec.get("args") or {})["as"]
    st = game.players[owner]
    if table.physical(game, owner):
        got = run.ask(game, "cards", owner, _unplayed(st), 1, 1, "reveal a card", zone="discard", purpose="reveal_top",
                      of=owner, table_discard=True, pile_mode="reveal")
        card = {c.card_id: c for c in st.full_set}[got[0]]
        table.make_known(game, owner, card)
        st.hand.remove(card)
        st.deck.insert(0, card)
        table.intent(game, op="stack_top", player=owner, card=card.card_id)
    else:
        if not st.hand:
            run.bind("cards", name, [])
            return
        got = run.ask(game, "cards", owner, [c.card_id for c in st.hand], 1, 1, "reveal a card", zone="hand",
                      purpose="reveal_top", of=owner, missing=sum(f.max_hp - f.hp for f in game.own(owner)))
        card = {c.card_id: c for c in st.hand}[got[0]]
        st.hand.remove(card)
        st.deck.insert(0, card)
        table.intent(game, op="return_to_deck", player=owner, zone="hand", cards=[card.card_id], position="top")
    game.players[1 - owner].known.set_top([card.card_id])
    run.bind("cards", name, [card.card_id])
