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
  (`card in players[p].full_set`, never by id)**: `tricks.home_of(game, holder, card)`. Cards of different decks are never equal
  (docs/card-identity.md), so this is exact.
- Where a request carries a card id it must carry the deck the id belongs to. The effect run knows the card being resolved: `Ctx.card_home`
  (the deck of the card, which is the player's own unless the card is a borrowed TRICK) is what `EffectRun.ask` puts in
  `ChoiceRequest.card_owner`, so panels, prompts and the choosers read the right deck.

### Effects of a card you do not own

`data/heroes/effects/loki.json` lends its four TRICKs (`"lent": true`) to every other hero: `HeroEffects.card(title)` falls back to
the lent cards when the player's own file has no such title. A TRICK played by a Medusa player is therefore resolved by the
interpreter with that player as `ctx.owner`: "your card", "your hero" and "your opponent" are the player's, and the LOKI / NOT LOKI
parts are a condition on the player's hero (`exists` an own hero named Loki). No plugin is needed for the split.

### Where a TRICK goes (all in `sparring/tricks.py`)

| Event | Rule | Code |
|---|---|---|
| a combat card or a scheme is settled (`inventions.settle_played`) | played by Loki: to the opponent's hand; played by the other player: to LOKI's discard | `tricks.settled` |
| a TRICK leaves the opponent's hand by a discard (`Game.discard_card`, every route: effect, hand limit, random) | it is not put on the opponent's pile: it goes to Loki's hand at once and the `card_discarded` trigger of Loki's ability lets Loki move it to the top of his deck | `tricks.discarded`, ability trigger `mischief_return` |
| a TRICK is played and goes back to a hand (Looking For Trouble, Sleight of Hand) | to the hand of whoever played it, as any card | unchanged |

Nothing else moves a TRICK, except the cards that name it (Laevateinn takes a revealed one: `tricks.take`; the trigger puts a returned one on
top of Loki's deck: `tricks.to_deck_top`). Every move is also a table intent (`trick_given`, `trick_to_discard`, `trick_returned`,
`trick_to_deck`, `trick_taken`) so the session can write it. Only a game with Loki in it reads the tag (`tricks.in_game`): a random pick in any
other game never looks at what it picks.

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

## The cards

| Card | What it does here |
|---|---|
| Ragnarok (attack 0, boost 3, uncancelable) | +3 per TRICK in the opponent's hand (the tracked ones) |
| Shapeshifter (attack 0, boost 2) | choose: +1 per card in their hand, or gain an action (the printed BOOST is 2; unmatched-memory says 3) |
| Looking For Trouble (attack 4, boost 3) | plugin: their card goes back to their hand, Loki looks at it and chooses what they play, a TRICK included (LO4) |
| Trick: Baldr's Downfall (attack 4, ANY) | Loki: draw 1. Not Loki: 2 damage to the player's own hero |
| God Of Mischief (versatile 2, boost 3) | their TRICK: its value is ignored (`set_value ignore`); any other card: its effects are cancelled |
| Malicious Flyting (versatile 3, boost 3) | draw 1, or 2 if they played a TRICK |
| Underhanded (versatile 3, boost 2) | 6 if they hold more cards than Loki (compared in DURING, the card already out of his hand) |
| Laevateinn (versatile 2, boost 3) | a blind (random) card of their hand is revealed, its BOOST is added, a TRICK goes to Loki's hand |
| Trick: Freyja's Rescue (versatile 2, ANY) | Loki: swap the running values of the two cards (plugin). Not Loki: Loki recovers 3 |
| Trick: Sindri's Bet (defense 3, ANY) | Loki: the opponent may discard a card, else -3 to their card. Not Loki: Loki returns the top card of HIS discard pile to his hand |
| Trick: Svadilfari's Lure (scheme, ANY) | Loki: place an opposing fighter adjacent to Loki. Not Loki: a random card of the player's hand is discarded (Loki's blind pick) |

## The AI

- **Search (`--ai ismcts`)**: the rollouts play the real effects through the engine, so the TRICKs move as they do in the game. `Knowledge.from_game` adds
  Loki's `foreign` TRICKs to the known cards of the rival's hand; `determinize` never deals a TRICK to Loki's sampled hand while it lies in the
  observer's own hand. The move cache and the pure-loss cache key a borrowed TRICK by `tricks.zone_id` (a TRICK and an own card of the same CardID
  were one key). `tests/test_loki_ai.py` (mutation-checked: removing either line fails 12 tests) and the headless matrix play it in both seats.
- **Heuristic (`sparring/ai_loki.py`)**: the value of Ragnarok, Shapeshifter, Underhanded and Laevateinn from the hands, the draw of Baldr's Downfall and
  Malicious Flyting, and the cost of the NOT LOKI part to a player who is not Loki (Baldr's two damage, Freyja's three hit points, Sindri's returned
  card), so a bot that holds a TRICK treats it as a hot potato. Looking For Trouble's choice (`EffectAI._trouble_card`): the weakest defense, a TRICK
  first. A returned TRICK goes on top of the bot's deck only when its hand would be at the limit (`plugins_loki.BOT_FULL_HAND`).

## At the table (the human holds or plays a Loki card)

The TRICK is one physical card; the bot moves it with the Lua writes it already has, naming the images of the deck the card BELONGS to (`session_tricks`).
`Session.trick_guids` is a ledger `{GUID: [home player, CardID]}` of the TRICKs that are away from their deck; it is saved with the game. A row of any
read of the human's side is a borrowed TRICK if and only if its GUID is in the ledger.

| What happens | What the bot does | What it reads back |
|---|---|---|
| the bot (Loki) plays a TRICK | after the combat, `return_card_to_hand(guid, human seat)`; the ledger learns the GUID; chat line | the human's hand count, as for any card |
| the human plays a TRICK they hold | nothing at the reveal: the card at their combat spot is recognised by its GUID (`_reveal`); after the combat the engine's discard of the bot moves it (the card is of the bot's deck) | the combat spot |
| the human discards a TRICK (hand limit, an effect) | `settle_discards` finds the ledger's GUID on their pile at the next read; the engine discards it from their hand (it returns to Loki's hand or deck top) and the bot takes it from the pile (`pile_card_to_hand`) | their discard pile (the ledger's rows are not their own cards) |
| the human (Loki) plays a TRICK | after the combat `trick_given`: the bot takes it from their spot into ITS hand; the ledger learns the GUID | the combat spot |
| the bot plays the human's TRICK | `play_card_face_down` with the human's range and images; afterwards `card_to_discard` to the human's pile | its own spot |
| the bot discards the human's TRICK | `return_card_to_hand(guid, human seat)` (or `card_to_deck_top` of the human's deck when they say so) | nothing |
| Laevateinn (bot's) | the engine picks a position at random and asks the human which card lies there (one button per title, the TRICKs they hold first, paged by the panel); a TRICK goes to the bot's hand and the bot takes it from the human's hand by GUID | the human's answer |
| Looking For Trouble (bot's) | the bot reads the human's hand (`look_hand`, once), names the card, and the human takes their defense back and lays the named one (the existing `play` mode of `session_rage`) | the combat spot |

Hidden information: the bot never reads the human's hand to find a TRICK. It knows where each one is because it moved it there (the ledger) or
because it was played face up. The only read of the hand is `look_hand` (Looking For Trouble), and a row whose GUID is in the ledger is read as the TRICK.

Where the code resolved a CardID against the human's own deck the ledger is consulted instead: `_reveal`, `read_human_hand`, `read_bot_hand`,
`sync_human` (the pile read skips the ledger's GUIDs), `session_rage` (`verdict`, `_verdict_play`), `_trim_virtual_hand` (a TRICK is a real card, never a
placeholder) and `effects.table.make_known`. A snapshot of the zones (`zones`) writes a borrowed TRICK as `id + QUALIFIED`; a saved combat, a saved
pending combat (`bot_card`) and the options of a request do the same.

The fake table cannot hold two cards of one CardID in one seat, so the session tests (`tests/test_loki_human.py`) play Loki against Hellboy, whose
CardIDs are 19700+; the collision itself is tested in the engine (`tests/test_loki_effects.py`).

## Rulings and readings used

- Ivan 2026-11-22: LO1 (blind pick = uniform random, never by hidden information), LO2 (ANY fighter of the opponent may play a TRICK), LO3 (Sindri's
  Bet: the opponent may discard a card, else -3; played by the opponent, Loki returns the top card of Loki's discard pile), LO4 (Loki may choose a TRICK
  as the card they defend with).
- REGLAS-PENDIENTES section 2: a TRICK Loki plays goes to the opponent's hand, the opponent's to Loki's discard; a TRICK in a hand counts for the limit
  of 7; "discards a TRICK from their hand" is any discard from the hand, and Loki chooses hand or top of his deck; +1 to the move for each TRICK in
  opponents' hands; TRICKs have BOOST 0 and cannot boost.

## Pending Ivan (nothing here is ruled; the most literal reading is implemented)

1. **Freyja's Rescue, "swap the values"**: the running totals of the two cards when the effect runs (printed value, bonuses and the DURING effects that
   already resolved; the defender's effects resolve first), not the printed numbers. A BOOST added later is added to the swapped totals.
2. **Looking For Trouble's timing**: the old defense card's IMMEDIATELY has already run (the defender's goes first); the chosen card's runs after Loki's, not
   in the defender's turn of the phase. A chosen card must be able to defend for that fighter (a TRICK is ANY). With no card played it does nothing.
3. **Both cards of the combat are Loki's** (Loki's attack and a TRICK the opponent plays): the Discord ruling says Loki chooses the order of the cleanup.
   The engine settles the attacker's card first, then the defender's; the order only decides which card ends on top of Loki's discard pile (Sindri's Bet's
   NOT LOKI part reads the top BEFORE the combat, so it does not depend on it). Not asked.
4. **A TRICK Loki plays as a scheme** (Svadilfari's Lure) goes to the opponent's hand when its ops are done.
5. **A TRICK discarded for the hand limit** counts as one of the cards owed; for the human at the table the bot takes it back when it reads the pile, but the
   count of discards owed is not adjusted for it (they may be asked for one more).
6. **Laevateinn at the table**: the human states which card lies at the position the bot named; the bot cannot check it (their hand is hidden, and Loki
   reveals it to himself only through that statement). The TRICKs they hold are listed first and are tracked, so a human who names another card keeps
   the TRICK in hand: a TRICK is taken only when they name it.
7. **The real `discard_cards` finds a card of the bot's deck lying at the human's combat spot** (a TRICK the human played): assumed from its scope
   (hands, discard zones, combat spots, `ours` by images); the FakeTTS models it. To verify live, with the first TRICK the human plays against a bot Loki.
8. **Resume with a TRICK in play**: the ledger, the combat flow, the pending combat of the bot and the zone snapshots are saved with qualified ids;
   other saved structures that hold a bare CardID of a played card (a second attack, the boost wait) are not adapted.
9. **Looking For Trouble at the table** reuses the `play` mode of `session_rage` (written for Do my bidding): its chat text speaks of the attacker; the flip and
   the tidy-up of the human's old defense card at the end of the combat are the existing ones.

## Tests

`tests/test_hero_loki_data.py` (overlay, HeroDef, effects, table data, shared range), `tests/test_loki_effects.py` (35: the routing both ways, every card, the
collision), `tests/test_loki_ai.py` (the determinization, mutation-checked, and the figures), `tests/test_loki_human.py` (FakeTTS: the TRICKs change hands
in both seats, Laevateinn, Looking For Trouble), `tests/test_loki_matrix.py` (every other hero in both seats, headless with both AIs; FakeTTS against the
heroes the fake table can tell apart).
