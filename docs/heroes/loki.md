# Loki (Battle of Legends, Volume Three)

16 health, melee, move 2, no sidekick. Deck: sheet 176 (CardID 17600-17629), character card 361. His deck shares CardIDs with
Medusa, the turtles and the other sheet-176 decks and is told apart by its images (`data/tts/loki.json` `deck.identity`,
docs/card-identity.md).

## The ability and what it asks of the engine

MISCHIEF-MONGER:

1. After Loki plays a TRICK, that card goes to the opponent's hand instead of Loki's discard pile (the cleanup step of the card).
2. If an opponent discards a TRICK from their hand (any discard from the hand: hand limit, random, an effect), Loki returns it to his
   hand or the top of his deck (Loki chooses).
3. +1 to Loki's move value for each TRICK in an opponent's hand.

Rulings that apply (Ivan 2026-11-22, `RULINGS-batch4.md`; defaults in `REGLAS-PENDIENTES-batch4.md` section 2):

- LO1: "reveal a card in the opponent's hand" (Laevateinn; Svadilfari's Lure, NOT LOKI side): Loki chooses and he does not see the hand,
  so the choice is blind: a position in the hand, never by hidden information. In the engine a uniform random pick (`pick: random`).
- LO2: a TRICK in an opponent's hand can be played by ANY fighter of that opponent (sidekicks included): the four TRICKs carry the
  band ANY.
- LO3: Sindri's Bet played by Loki: the opponent may discard a card, otherwise -3 to their card's value. Played by the opponent: Loki
  returns the top card of LOKI's discard pile to his hand (what is on top when the AFTER runs: Loki's own card of the combat reaches
  the pile only at the cleanup).
- LO4: Looking For Trouble: Loki may choose a TRICK of the opponent's hand as the card they play.
- A TRICK played by Loki goes to the opponent's hand; one played by the opponent goes to LOKI's discard pile (Discord). If both cards of
  the combat are Loki's, Loki orders the two cleanups (see "Open").
- A TRICK in the opponent's hand counts for their hand limit of 7.
- TRICKs have BOOST 0: they cannot be used to boost (`cards.can_be_boost`).
- "If your opponent played a TRICK": a card of the rival's combat with the tag `trick`.

## The design: whose card is it, where is it, who knows

### Identity: a card belongs to the deck it came from, wherever it lies

The engine rule of docs/card-identity.md stands: a CardID means a card only together with its owner (a deck). A TRICK that sits in the
opponent's hand is still a `Card` of Loki's `full_set`; nothing is copied or renumbered. Two consequences:

- `Game.card_of(id, owner)` already falls back to the rival's deck, but decks of sheet 176 share ids, so the fallback is only safe
  when the id does not exist in the owner's deck. The rule for TRICKs is therefore: **the owner of a card is looked up by value
  (`card in players[p].full_set`, never by id)**: `tricks.home(game, card)`. Cards of different decks are never equal
  (docs/card-identity.md), so this is exact.
- Where a request carries a card id it must carry the deck the id belongs to. The effect run knows the card being resolved: `Ctx.card_home`
  (the deck of the card, which is the player's own unless the card is a borrowed TRICK) is what `EffectRun.ask` puts in
  `ChoiceRequest.card_owner`, so panels, prompts and the choosers read the right deck.

### Effects of a card you do not own

`data/heroes/effects/loki.json` lends its four TRICKs (`"lent": true`) to every other hero: `HeroEffects.card(title)` falls back to
the lent cards when the player's own file has no such title. A TRICK played by a Medusa player is therefore resolved by the
interpreter with that player as `ctx.owner`: "your card", "your hero" and "your opponent" are the player's, and the LOKI / NOT LOKI
parts are a condition on the player's hero (`exists` an own hero named Loki). No plugin is needed for the split.

### Where a TRICK goes (all in `sparring/tricks.py`, called from three places)

| Event | Rule | Code |
|---|---|---|
| a combat card or a scheme is settled (`inventions.settle_played`) | played by Loki: to the opponent's hand; played by the other player: to LOKI's discard | `tricks.settled` |
| a TRICK leaves the opponent's hand by a discard (`Game.discard_card`, every route: effect, hand limit, random) | it is not put on the opponent's pile: it goes to Loki's hand at once and the `card_discarded` trigger of Loki's ability lets Loki move it to the top of his deck | `tricks.discarded`, ability trigger `mischief_return` |
| a TRICK is played and goes back to a hand (Looking For Trouble, Sleight of Hand) | to the hand of whoever played it, as any card | unchanged |

Nothing else moves a TRICK. Every move is also a table intent (`trick_given`, `trick_to_discard`, `trick_returned`) so the session can
write it.

### Who knows what (hidden information, the search)

The location of a TRICK is public: it was played face up, or discarded face up. So:

- Loki's side (`players[loki].known`) keeps `foreign`: the TRICKs it knows are in the opponent's hand (a list of ids resolved against
  Loki's OWN deck, never the opponent's). It is exact, never "possible": the opponent cannot hide it (a TRICK left the hand only by a
  play or a discard, both public). It is cleared by `Game.card_left_hand`, the one place that forgets seen cards.
- The opponent's side learns nothing it does not see: a TRICK the human (Loki) plays lands in the bot's own hand, which the bot knows.
  When the bot discards one it goes back to Loki's hidden hand or deck top: in the bot's search it simply returns to Loki's unseen
  pool (it is in the pool of Loki's full set minus the public piles, which already holds it).
- The search (`EngineState.determinize`): the opponent's hand is rebuilt as `known + sample`; `Knowledge.from_game` adds Loki's
  `foreign` TRICKs to `known_in_hand[opponent]` (cards of the OBSERVER's deck, never in the opponent's pool), and the pool of a
  non-observer deck leaves out the cards of that deck that lie in the observer's hand. The hand size the sampler keeps is the
  engine's, which already counts the TRICK.
- The bot never reads the human's hand for it: counting `trick_in_rival_hand` (the +1 to the move, Ragnarök, Underhanded) uses the engine's
  tracked TRICKs, the same ones the table projection wrote.

### +1 to the move value

A HeroDef counter `trick_in_rival_hand` (`pile: "rival_hand"`, tag `trick`) counts the TRICKs in the other player's hand;
the existing passive `maneuver_move_per_counter` (Sinbad's) adds that many spaces to Loki's Maneuver. Loki has no card that reads
"move value" elsewhere.

## At the table (the human holds or plays a Loki card)

*(See the section "Table story" below; filled in as it is built.)*

## Pending Ivan

*(filled in as it is built)*
