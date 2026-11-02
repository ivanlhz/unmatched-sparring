"""Hidden-information ops (docs/effects-dsl.md section 3 and rule 6): look_hand, reveal, look_deck, search_deck,
return_to_deck, put_in_hand.

Ivan's rule: the bot may read the human hand ONLY while a card effect says so. `look_hand` is the only place that
reads a rival hand for its owner (through `Game.observe_hand`, the only caller of that method). Everything else here
moves cards and keeps the rival's `KnownHand` honest:

- a card that leaves a hand in plain sight (played, discarded, chosen by the rival) is forgotten exactly;
- a card that leaves face down (shuffled or put at the bottom by its owner) degrades what the rival saw to "possible";
- a card put on top of a deck in plain sight becomes the known `top_of_deck`; any other change of that deck's top
  makes the rival forget it.

`KnownHand` of player P describes what P knows about P's RIVAL, so what the rival of a deck owner knows about that
deck lives in `game.players[deck_owner ^ 1].known`.

Order convention for `order` / `rest` lists: top of the deck first. Atomic like every op: all decisions (choices,
orders, random permutations) are obtained before the first mutation."""
from __future__ import annotations

from . import modifiers, table
from .ops_core import _cards_of, op
from .select import _matches, amount, card_ref, locate, player_of, players_of, select_cards


def _watcher(game, deck_owner: int):
    """The KnownHand that holds what the rival of `deck_owner` knows about that deck's top."""
    return game.players[1 - deck_owner].known


def _remember_in_hand(game, holder: int, card) -> None:
    """The rival of `holder` has now seen `card` in `holder`'s hand."""
    known = game.players[1 - holder].known
    if card.card_id in known.possible:
        known.forget(card)               # it was only possible; the bounds shrink and it is added as certain below
    if card.card_id not in known.seen:
        known.add(card, game.turn_no)


# ---------------------------------------------------------------- looking

@op("look_hand")
def _look_hand(run, game, spec):
    """The live session installs `Game.hand_reader` (D3): the real table hand is read exactly here, never elsewhere;
    a clone or a simulation has no reader and looks at its own (determinized) hand."""
    owner, target = run.ctx.owner, player_of(game, run, spec["player"])
    if target != owner and _shield_cancels(run, game, owner, target):
        return
    if target != owner:
        reader = game.hand_reader
        cards = list(game.players[target].hand) if reader is None else reader(target)
        game.observe_hand(owner, cards)
        run.flags["looked_hand"] = True      # the narration says "looks at" only for a look, not for a changed `seen`


def _shield_cancels(run, game, owner: int, target: int) -> bool:
    """A card of `target`'s deck that cancels a look at their hand (`look_shield`): the holder is asked whether to reveal it.
    The bot's hand is its own, so only a held card asks. The table player's is virtual, so the engine cannot know: it asks
    unless the card is already in their discard pile. Revealed: the looker sees that card and nothing else, and what the
    effect would have picked among the cards it never saw fizzles (`look_cancelled`)."""
    st = game.players[target]
    shield = next((c for c in st.full_set if modifiers.look_shield(c)), None)
    if shield is None:
        return False
    if table.physical(game, target):
        if shield in st.discard or shield in st.tucked or shield in st.removed:
            return False
    elif shield not in st.hand:
        return False
    if not run.ask(game, "optional", target, [True, False], 1, 1, "reveal the shield", shield=shield.title)[0]:
        return False
    run.flags["look_cancelled"] = True
    _remember_in_hand(game, target, shield)           # the looker has seen that card in that hand, and nothing else
    return True


@op("reveal")
def _reveal(run, game, spec):
    cards = spec["cards"]
    if isinstance(cards, str):
        found = [(locate(game, c), c) for c in card_ref(game, run, cards)]
    else:
        found = [((p.player, p.zone), p.card) for p in select_cards(game, run, cards, "reveal")]
    shown = run.flags.setdefault("revealed", {})
    for seer in players_of(game, run, spec["to"]):
        for where, card in found:
            if where is None:             # in combat (face down on the table): the run keeps what was shown
                shown.setdefault(str(seer), []).append(card.card_id)
                continue
            holder, zone = where
            if holder == seer:
                continue
            if zone == "hand":
                _remember_in_hand(game, holder, card)
                run.flags["looked_hand"] = True
            elif zone == "deck" and game.players[holder].deck[:1] == [card]:
                _watcher(game, holder).set_top([card.card_id])


@op("look_deck")
def _look_deck(run, game, spec):
    owner, target = run.ctx.owner, player_of(game, run, spec["player"])
    n, from_top = int(amount(game, run, spec["amount"])), spec.get("from", "top") == "top"
    if table.physical(game, target) and target == owner:     # the human looks at their real deck: the engine's is virtual
        table.note(run, op="look_deck", amount=n, top=from_top)
        if "as" in spec:
            run.bind("cards", spec["as"], [])
        return
    deck = game.players[target].deck
    looked = deck[:n] if from_top else deck[::-1][:n]
    if "as" in spec:
        run.bind("cards", spec["as"], [c.card_id for c in looked])
    if target != owner and from_top:
        _watcher(game, target).set_top([c.card_id for c in looked])


# ---------------------------------------------------------------- deck changes

def _ask_order(game, run, player: int, cards: list, **extra) -> list:
    ids = run.ask(game, "order", player, [c.card_id for c in cards], len(cards), len(cards), "order",
                  ordered=True, zone="deck", purpose="order", **extra)
    by_id = {c.card_id: c for c in cards}
    return [by_id[i] for i in ids]


def _permutation(run, n: int) -> list[int]:
    return run.random_sample(list(range(n)), n)


@op("search_deck")
def _search_deck(run, game, spec):
    owner, target = run.ctx.owner, player_of(game, run, spec["player"])
    chooser = player_of(game, run, spec.get("chooser", "owner"))
    if table.physical(game, target) and chooser == target:     # the engine does not know the order of their deck
        take = spec["take"]
        table.note(run, op="search_deck", look=spec["look"], take=int(amount(game, run, take.get("amount", 1))),
                   rest=spec.get("rest", "bottom_random"))
        if "as" in spec:
            run.bind("cards", spec["as"], [])
        return
    deck, hand = game.players[target].deck, game.players[target].hand
    looked = deck[:len(deck) if spec["look"] == "all" else int(spec["look"])]
    take = spec["take"]
    n_take, flt = int(amount(game, run, take.get("amount", 1))), take.get("filter") or {}
    eligible = [c for c in looked if _matches(c, flt)]
    lo = 0 if take.get("up_to") else min(n_take, len(eligible))
    got = run.ask(game, "cards", chooser, [c.card_id for c in eligible], lo, n_take, "search the deck",
                  zone="deck", purpose="search", of=target)
    taken = [c for c in eligible if c.card_id in got]
    rest = [c for c in looked if c not in taken]
    mode = spec.get("rest", "bottom_random")
    if mode in ("bottom_ordered", "top_ordered"):
        rest = _ask_order(game, run, chooser, rest, position=mode.split("_")[0])
    elif mode == "bottom_random":
        rest = run.random_sample(rest, len(rest))
    perm = _permutation(run, len(deck) - len(taken)) if mode == "shuffle" else None

    for c in taken:
        deck.remove(c)
        hand.append(c)
    if mode == "shuffle":
        deck[:] = [deck[i] for i in perm]
    else:
        for c in rest:
            deck.remove(c)
        if mode == "top_ordered":
            deck[:0] = rest
        else:
            deck.extend(rest)
    watcher = _watcher(game, target)
    for c in taken:
        watcher.drop_top(c.card_id)
        if target != owner:                 # the owner took them in plain sight
            _remember_in_hand(game, target, c)
    if target != owner and mode == "top_ordered":
        watcher.set_top([c.card_id for c in rest])
    else:
        watcher.clear_top()
    if taken:
        table.intent(game, op="search_deck", player=target, cards=[c.card_id for c in taken])
    if "as" in spec:
        run.bind("cards", spec["as"], [c.card_id for c in taken])


@op("return_to_deck")
def _return_to_deck(run, game, spec):
    sel, position = spec["cards"], spec["position"]
    if table.hand_pick_is_physical(game, run, sel):      # the human picks the real cards out of their hand
        table.note(run, op="return_to_deck", position=position, amount=int(amount(game, run, sel.get("amount", 1))),
                   up_to=bool(sel.get("up_to")), all=sel.get("pick") == "all" and "except" not in sel,
                   rest=sel.get("pick") == "all" and "except" in sel, ordered="order" in spec)
        return
    items = _cards_of(game, run, sel, "return", in_combat=True, position=position)
    if items and position == "bottom" and isinstance(sel, dict) and sel["zone"] == "deck" \
            and table.physical(game, items[0].player):
        table.note(run, op="deck_to_bottom", amount=len(items))      # their own deck order is theirs: by hand
    chooser = None
    if isinstance(sel, dict) and sel.get("pick", "chosen") == "chosen":
        chooser = player_of(game, run, sel.get("chooser", "owner"))
    moved: dict[int, list] = {}
    zones: dict[int, str] = {}
    for holder, zone, card in items:
        moved.setdefault(holder, []).append(card)
        zones[card.card_id] = zone
    perms: dict[int, list[int]] = {}
    for holder in sorted(moved):
        if position == "shuffle":
            from_deck = sum(1 for c in moved[holder] if zones[c.card_id] == "deck")
            perms[holder] = _permutation(run, len(game.players[holder].deck) + len(moved[holder]) - from_deck)
        elif len(moved[holder]) > 1 and "order" in spec:
            moved[holder] = _ask_order(game, run, player_of(game, run, spec["order"]), moved[holder], position=position)

    for holder in sorted(moved):
        st, cards, rival = game.players[holder], moved[holder], 1 - holder
        from_hand = [c for c in cards if zones[c.card_id] == "hand"]
        plain = all(zones[c.card_id] == "discard" or (zones[c.card_id] == "hand" and chooser == rival)
                    for c in cards)         # the rival sees what goes: public pile, or a hand card it picked itself
        was_empty = not st.deck
        for c in cards:
            zone = zones[c.card_id]
            if zone == "hand":
                st.hand.remove(c)
                if chooser == rival:
                    game.card_left_hand(holder, c)
            elif zone == "discard":
                st.discard.remove(c)
            elif zone == "deck":
                st.deck.remove(c)
            elif zone == "combat":              # played in this combat: it no longer goes to the discard pile
                run.flow.played[:] = [(o, card) for o, card in run.flow.played if card is not c]
            else:
                game.fx.take_ongoing(holder)
        if from_hand and chooser != rival:
            game.players[rival].known.degrade(len(from_hand), len(st.hand))
        if position == "top":
            st.deck[:0] = cards
        else:
            st.deck.extend(cards)
        if position == "shuffle":
            st.deck[:] = [st.deck[i] for i in perms[holder]]
        for zone in ("hand", "discard"):          # the table sees these two leave; `cards` in the order the deck holds them
            moved_here = [c.card_id for c in cards if zones[c.card_id] == zone or (zone == "discard" and zones[c.card_id] == "combat")]
            if moved_here:
                table.intent(game, op="return_to_deck", player=holder, zone=zone, cards=moved_here, position=position)
        watcher, ids = _watcher(game, holder), [c.card_id for c in cards]
        for i in ids:
            if zones[i] == "deck":
                watcher.drop_top(i)
        if position == "shuffle" or (position == "top" and not plain):
            watcher.clear_top()
        elif position == "top":
            watcher.push_top(ids)
        elif was_empty:
            watcher.set_top(ids if plain else [])


@op("put_in_hand")
def _put_in_hand(run, game, spec):
    for holder, zone, card in _cards_of(game, run, spec["cards"], "recover"):
        st = game.players[holder]
        if zone == "discard":
            st.discard.remove(card)
        elif zone == "deck":
            st.deck.remove(card)
        else:
            continue
        st.hand.append(card)
        table.intent(game, op="put_in_hand", player=holder, zone=zone, cards=[card.card_id])
        watcher = _watcher(game, holder)
        was_known_top = card.card_id in watcher.top_of_deck
        watcher.drop_top(card.card_id)
        if zone == "discard" or was_known_top:       # a public pile, or a card the rival already knew
            _remember_in_hand(game, holder, card)
