# Golden Bat (Adventures: Tales to Amaze)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 345 on sheet 3) on 2026-11-08. Verified on FakeTTS only: nothing of Golden Bat has been seen on a real table (see `docs/live-checklist.md`).

## Summary
- Melee hero, 18 life, move 3. **No sidekick**: unmatched-memory lists "Daisy" (flagged `hasSidekicks: false`; she is Jill Trent's sidekick) but the hero card names none and the savegame has a single miniature (GUIDs `b0ebcc` piece, `0f46cb` dial, both named Golden Bat). Hero fid `bat`.
- Ability **THE FIRST SUPERHERO**: "If you haven't taken a Maneuver action this turn, add +2 to the value of Golden Bat's attacks." A HeroDef passive `attack_bonus` (n 2) with `unless: maneuver` (docs/effects-dsl.md section 32): the combat reveal adds it, and the bot's estimates of Golden Bat's next attack (`Game.attack_bonus`) read the same thing.
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176), every card under the GOLDEN BAT band (none ANY). The deck object of the save holds 31 cards (the 30 plus the character card `345`).
- Table: bag `4732a0`, deck `29a029`. **He shares CardIDs 17600-17629 with Medusa, the four turtles, Doctor Strange, Bigfoot, Daredevil (22 cards), Luke Cage and Bullseye**: his deck is told apart by deck image and owner (docs/card-identity.md), never by a bare CardID. `tests/test_golden_bat_matrix.py` plays him against every other hero in both seats.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| Super Strength | attack | 5 | 1 | 2 | No text |
| Vaporizing Eyebeams | attack | 2 | 2 | 3 | AFTER: your opponent discards 1 random card |
| A Punch to Shake the Earth | attack | 1 | 1 | 3 | AFTER: 1 damage to each opposing fighter in your zone; 2 if you won |
| Sight Beyond Sight | versatile | 2 | 1 | 3 | AFTER: look at the top 3 cards of the opponent's deck, put them back in any order |
| Terrifying Roar | versatile | 3 | 1 | 3 | IMMEDIATELY: fighters cannot leave their spaces for the rest of the turn |
| Skirmish | versatile | 4 | 1 | 2 | AFTER: if you won, move one of the fighters in the combat up to 2 spaces |
| Like a Flash of Golden Light | versatile | 2 | 2 | 3 | DURING: value 4 if he shares no zone with the space he started the turn in. AFTER: move up to 5 |
| Insight of the Ancients | versatile | 3 | 2 | 2 | AFTER: if you won, a random card of your discard pile returns to your hand |
| Imposing Presence | defense | 3 | 2 | 2 | IMMEDIATELY: cancel all effects on the opponent's card |
| He Laughs at Your Feebleness | defense | 5 | 3 | 2 | No text |
| Arrive Just in Time | scheme | - | 2 | 2 | Place Golden Bat in any space |
| Alpine Fortress | scheme | - | 3 | 3 | Shuffle a chosen discard card into the deck, draw 2, move up to 4 |

## Discrepancies with unmatched-memory
- **A Punch to Shake the Earth** reads "each opposing fighter in **your** zone" on the card; unmatched-memory says "in Golden Bat's zone" (the same: he is the only fighter). The HeroDef carries the card's text.
- **Skirmish** reads "move one of the fighters in the combat up to 2 spaces"; unmatched-memory "choose one of the fighters in the combat and move them up to 2 spaces" (the same).
- Daisy (unmatched-memory) is Jill Trent's sidekick, not his; she is not on the card or in the save. Restriction bands are not in unmatched-memory at all. Type, value, boost and copies of the 12 titles agree with the images.

## Collisions found in the save
- **CardIDs 17600-17629** shared with the nine other decks of sheet 176. Solved as for them: `data/tts/golden-bat.json` carries its own `deck.identity` and every lookup is per owner; `tests/test_hero_golden_bat_data.py` pins that no card is equal to a card of another deck of the range and that the images differ.
- No piece GUID is shared with another hero (pinned in `tests/test_hero_golden_bat_data.py`).

## Rule decisions (Iván, 2026-11-08)
Confirmed by Iván; the rest of the list is the most literal reading, applied.

1. **A Maneuver action is counted the moment it is taken** (`Game.maneuver`, the session's Maneuver button), with one exception: **a Maneuver whose draw is PREVENTED by an effect (Cold Iron) does not count**, so he keeps the +2. **An empty deck still draws** (an exhaustion draw), so that Maneuver counts and the +2 is lost. Exhaustion is the global rule (`Game.draw`): drawing from an empty deck deals `EXHAUST_DAMAGE` 2 to each of the player's living fighters, never capped or shielded, and no damage at all when an effect prevents the draw; it is the same for every hero (nothing hero-specific reads it). Other actions (attack, scheme, a gained action, the free BOOST) never count. The tally is of the running turn: it is the owner's own turn when it matters (attacks), and it starts again at every `start_of_turn`.
2. **THE FIRST SUPERHERO** applies to every attack Golden Bat makes on his own turn, whichever card (a versatile one played as an attack included), after any other bonus; never to a defense. It needs no maneuver to be missing in the rival's turn: the rival's attacks never get it.
3. **Terrifying Roar** pins every living fighter, his own side included ("fighters"; confirmed by Iván), with `cannot_leave_space` until the end of the current turn (the attacker's, when played in defense), the status Liz Sherman's Burning Barrier uses: no walk, push or effect move takes a fighter out of its space; placing or swapping is not "leaving". It does not stop attacks. His own AFTER moves (Like a Flash, Skirmish, Alpine Fortress) after a Roar in the same turn therefore do nothing.
4. **A Punch to Shake the Earth** hits the rival's living fighters on any space that shares a zone with Golden Bat's (the opposing fighter of the combat included while alive); his own side is never hit. "If you won the combat" is the card owner's result: 2 each, otherwise 1 each.
5. **Like a Flash of Golden Light**: "the space he started this turn in" is where he stood at the start of the turn that is running (also the rival's turn when the card is played in defense). A Golden Bat that has not moved, or still shares a zone with it, gets the printed 2. The printed value becomes 4 (bonuses stay).
6. **Sight Beyond Sight** (confirmed by Iván: the bot really reads): the owner looks at the top 3 (fewer if the deck is shorter) and puts all of them back on top in the order he chooses (the first of the order ends on top); no card is taken. The human orders the bot's real top cards ON THE TABLE (Iván, 2026-11-08; buttons named after the bot's cards were useless live: he does not know them, and two copies of a title look the same): see the Human side section. **The bot reads the human's real top 3 through the table reader** (`Game.deck_reader(player, 3)`, `session_peek.read_top`, `lua.peek_deck_top(count=3)`, the Jill Trent infrastructure): it orders them worst first for the human, keeps them as `KnownHand.top_of_deck` (the same slot Donatello's The future of Ninjutsu fills, so the AI plans with them), and **reorders the human's real deck itself, blind** (Iván, 2026-11-08): intent `deck_order` (`seen` = the cards as read, `top` = the bot's order, no bottom card) becomes `lua.deck_reorder`, which checks that the top of the deck is still the cards read, takes them off and puts them back face down in the bot's order (nothing else on the table moves, no card is turned or shown). The chat says only "he reordenado las 3 cartas superiores de tu mazo" (`order.blind`), never which cards or in what order; if the top changed since the read, nothing moves, the chat says it could not reorder (`order.blind_failed`) and the bot forgets the order. It forgets the cards as soon as one is drawn, discarded or the deck is shuffled, and never says in the chat that it revealed them. A table that cannot be read shows the bot nothing: the card does nothing and says so (`tbl.look_foreign_deck`). In headless games and with the search AI both decks are known to the engine and the bot orders them worst first.
7. **Insight of the Ancients** returns one card at random from the discard pile (the engine's rng); the card just played is not in the pile yet. An empty pile: nothing.
8. **Skirmish**: after a win the owner picks either fighter of the combat (the one that was defeated cannot move) and moves it up to 2 spaces (0 allowed); a rival piece is moved by the owner, not through other fighters.
9. **Vaporizing Eyebeams** discards the card even when the combat is lost; the card is chosen at random (the table draws it; the bot never looks).
10. **Alpine Fortress** in printed order: the chosen card is shuffled into the deck (mandatory when the pile is not empty; the scheme card itself is not in the pile yet), then 2 cards are drawn (the shuffled card may be one of them), then up to 4 spaces of move.
11. **Arrive Just in Time**: any empty space, his own included (placing may leave him where he is).
12. **No sidekick**: Golden Bat has none. Daisy is Jill Trent's sidekick, not his (unmatched-memory's entry for him is wrong; ignored).

13. **Combat win (global, Iván 2026-11-07/08)**: the attacker wins only if combat damage lands (Luke Cage's text makes the difference explicit); a tie or no damage = the defender wins. Every "if you won / lost" of this hero reads the engine's result (`CombatFlow.won_by`), with no card-side handling of ties; tied-combat tests in `tests/test_golden_bat_ties.py`.

## Open questions for Iván
None.

## AI
- The AI profile comes from the data (hero `hero`, no sidekick; exclusive cards: all twelve titles).
- `Game.attack_bonus` carries THE FIRST SUPERHERO: the bot values an attack of his next turn with the +2 and no longer takes it once it has maneuvered, so attacking from where he stands (without a Maneuver) is worth more than walking up with one.
- Card hints and values come from the generic simulation of the ops (moves, draws, discards, zone damage, cancels); Sight Beyond Sight's order is the shared `EffectAI._order` (worst cards of the rival's deck first), Like a Flash of Golden Light's DURING value is simulated like every other `set_value`.

## Human side
- **Sight Beyond Sight, the order of the bot's top cards (`sparring/session_order.py`)**: the bot takes its engine's top N cards off its deck by CardID and deck image (`lua.deck_card_to_spot`, the table's own order is not the engine's) and lays them FACE UP in a row at `order_spot` / `order_step` (config/table.json, an estimate: a column along z at x -10.5 on the human's far side, cards at z 19.1, 22.5 and 25.9, clear of every layout slot of both maps; calibrate it live, especially against the White hand zone). They go on the table and never in the human's hand, which the bot reads. The chat says: "he puesto mis 3 cartas de arriba boca arriba en la mesa ... ponlas boca abajo encima de mi mazo: la primera que pongas quedara debajo de las otras y la ultima, arriba. Luego pulsa Hecho". The rule is TTS's: a card dropped on a deck goes ON TOP of it, so the first card put ends under the others and the LAST one put is the top card. The panel shows only Done. On Done the bot reads the top N of its deck (`lua.peek_deck_top`, image identity plus CardID, never a bare CardID: sheet-176 decks share CardIDs) and checks they are exactly the N it laid. If so, that order (top first) answers the request, the same answer a panel button gave: the engine deck, the pinned engine order (`Session.peek_pins`) and the human's `KnownHand.top_of_deck` match the table. If not (a card still on the table, a card of the deck or a foreign object on top) the chat names the missing cards (the human saw them), only COUNTS any extra card (it is face down, naming it would leak it) and the request keeps waiting; the bot moves nothing. The row is `Session.order_row`, saved with the game: a `--resume` says the instruction again and never lays the cards twice. If the table does not give the cards, the chat says so and the request falls back to the old panel buttons (after a partial lay, the cards left on the table are the human's to put back, and the engine order and the physical order stay decoupled); `order_by_hand: false` keeps them always. Insightful Deduction played by the human (Jill Trent) asks the same `order` request for the two cards left after the buried one, so it uses the same flow. Headless games and the search AI do not go through it (the engine-only path is unchanged).
- Buttons appear only when the card is played (never greyed): the order of Sight Beyond Sight's three cards is the exception above (a single Done), the card of Alpine Fortress's discard pile, the fighter and space choices of Skirmish, Like a Flash and Alpine Fortress (the bot's piece is moved by hand and you press Done), the placement of Arrive Just in Time. Every choice is a parked run saved with the game and survives `--resume`.
- A bot card that shuffles a discard card into its deck and draws in the same step (Alpine Fortress) is translated as a shuffle into the real deck followed by the draws (`session_bot_effects._bot_cards`, `drawn_back`).

## Tests
`tests/test_hero_golden_bat_data.py` (data, card identity, detection), `tests/test_golden_bat_effects.py` (the ability and every card on the interpreter), `tests/test_golden_bat_order_by_hand.py` (the human's Sight Beyond Sight: the cards laid, the stacking order, the mismatches, the resume and the fallback), `tests/test_golden_bat_human.py` (the bot's Sight Beyond Sight at the FakeTTS table: the blind reorder, no card named, and the abort when the top changed), `tests/test_deck_reorder_lua.py` (`lua.deck_reorder` on the Lua stub: decks of 1, 2, 3 and more cards, mismatch, face down only), `tests/test_golden_bat_matrix.py` (full games against the fifteen other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).

## Not a reveal (Ivan, 2026-11-08)
Sight Beyond Sight only LOOKS at the human's top cards: nothing is shown, no Stop revealing button, and the bot reorders blind (`lua.deck_reorder`). The global reveal rule is in docs/heroes/jill-trent.md.
