"""Loki's TRICK cards move between hands (MISCHIEF-MONGER, docs/heroes/loki.md).

A TRICK is a `Card` of LOKI's deck (tag `trick`) wherever it lies: nothing is copied or renumbered. Decks of sheet 176 share CardIDs,
so the deck a card comes from is told by value (`card in players[p].full_set`), never by its id.

  settled(game, player, card)     a played card has been resolved: Loki's TRICK goes to the opponent's hand, the opponent's to LOKI's discard
  discarded(game, player, card)   a TRICK left the opponent's hand by a discard: it goes to Loki's hand (the trigger `mischief_return` lets him
                                  put it on top of his deck instead)

Loki's side keeps the TRICKs it knows are in the rival's hand in `KnownHand.foreign` (public information: a TRICK arrives there by a card
played face up and leaves by a play or a discard). Every move is also a table intent for the session."""
from __future__ import annotations

TRICK = "trick"


def in_game(game) -> bool:
    """Loki is one of the heroes in play: only then does a card get looked at for the tag (a random pick must not read what it picks)."""
    return game.players[0].hero.slug == "loki" or game.players[1].hero.slug == "loki"


def is_trick(card) -> bool:
    return TRICK in card.tags


def home_of(game, holder: int, card) -> int | None:
    """The player whose deck `card` belongs to (a card is never equal to one of another deck); `holder` is who plays or holds it."""
    if card in game.players[holder].full_set:
        return holder
    if card in game.players[1 - holder].full_set:
        return 1 - holder
    return None


def borrowed(game, holder: int, card) -> bool:
    """`card` is a TRICK of the OTHER player's deck, held or played by `holder`."""
    return in_game(game) and is_trick(card) and card not in game.players[holder].full_set


def tricks_in_rival_hand(game, loki: int) -> list:
    """The TRICKs of `loki`'s deck that lie in the other player's hand (the engine tracks the table player's too)."""
    own = game.players[loki].full_set
    return [c for c in game.players[1 - loki].hand if is_trick(c) and c in own]


def _intent(game, **fields) -> None:
    from .effects import table
    table.intent(game, **fields)


def settled(game, player: int, card) -> bool:
    """`card`, played by `player`, has been resolved (a combat card at the end of its combat, a scheme when its ops are done). Returns True
    when it was a TRICK and has been placed: Loki's own goes to the opponent's hand, the opponent's goes to LOKI's discard pile."""
    if not in_game(game) or not is_trick(card):
        return False
    home = home_of(game, player, card)
    if home is None:
        return False
    if home == player:
        game.players[1 - player].hand.append(card)
        game.players[player].known.foreign.append(card.card_id)
        _intent(game, op="trick_given", player=player, card=card.card_id, to=1 - player)
    else:
        game.players[home].discard.append(card)
        _intent(game, op="trick_to_discard", player=player, card=card.card_id, to=home)
    return True


def discarded(game, player: int, card, cause: str | None = None) -> None:
    """A TRICK of Loki's deck left `player`'s hand by a discard (any route). It is in Loki's hand at once; the trigger `mischief_return` of his
    ability asks Loki whether it goes to the top of his deck instead (`to_deck_top`)."""
    home = 1 - player
    game.players[home].hand.append(card)
    _intent(game, op="trick_returned", player=player, card=card.card_id, to=home)
    game.fx.emit("card_discarded", player, card, "hand", cause)


def to_deck_top(game, loki: int, card) -> None:
    """The returned TRICK goes from Loki's hand to the top of his deck."""
    st = game.players[loki]
    if card in st.hand:
        st.hand.remove(card)
        st.deck.insert(0, card)
        _intent(game, op="trick_to_deck", player=loki, card=card.card_id)


QUALIFIED = 100_000       # an option list may hold a card of either deck: a TRICK of the other deck is written id + QUALIFIED


def qualified(card) -> int:
    """The id of a TRICK of Loki's deck inside an option list that also holds the other deck's cards (whose ids may repeat it)."""
    return card.card_id + QUALIFIED


def card_from_option(game, holder: int, loki: int, option: int):
    """The card an option of a request names: `holder`'s own card, or (`QUALIFIED` + id) a TRICK of `loki`'s deck."""
    if option >= QUALIFIED:
        return game.card_of(option - QUALIFIED, loki)
    return game.card_of(option, holder)


def take(game, holder: int, loki: int, card) -> None:
    """`card` (a TRICK) leaves `holder`'s hand for Loki's: Laevateinn revealed it."""
    st = game.players[holder]
    if card in st.hand:
        st.hand.remove(card)
        game.card_left_hand(holder, card)
    game.players[loki].hand.append(card)
    _intent(game, op="trick_taken", player=loki, card=card.card_id, to=loki, source=holder)


def note_in_hand(game, holder: int, card) -> None:
    """The rival of `holder` has seen `card` go back into `holder`'s hand: a card of the holder's deck is a seen card, a TRICK of the other
    deck (Loki's) is a `foreign` one."""
    if borrowed(game, holder, card):
        known = game.players[1 - holder].known
        if card.card_id not in known.foreign:
            known.foreign.append(card.card_id)
    else:
        game.players[1 - holder].known.add(card, game.turn_no)
