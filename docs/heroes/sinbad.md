# Sinbad (Battle of Legends, Volume One)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 303 on sheet 3) on 2026-11-09.

## Summary
- Melee hero, 15 life, move 2, sidekick **The Porter** (melee, 6 life, move 2, one of them). Hero fid `sinbad`, sidekick fid `porter`, slug `sinbad`.
- Ability: "When you maneuver, you may move your fighters +1 space for each VOYAGE card in your discard pile." (the card says "your fighters"; unmatched-memory says "fighters"). Implemented as the passive rule `maneuver_move_per_counter` (docs/effects-dsl.md, section 38).
- **VOYAGE** is the tag `voyage` on seven cards (`data/heroes/overlay/sinbad.json`) and the HeroDef counter `voyage` (`pile: discard`, like Hellboy's destinies): the number of VOYAGE cards in the owner's discard pile.
- Deck: 30 cards, `CardID = 17600 + idx`. Restriction band: SINBAD on the seven VOYAGE cards, Toil and Danger and Riches Beyond Compare; THE PORTER on By Fortune and Fate; ANY on the rest. The deck object in the save holds 31 cards (the 30 plus the character card 303), hence `card_count 31` in the catalog (`card_ids [303, 17629]` there is the min and max of those 31).
- Table: bag `6e6722` (inner `e22b3b`), deck `09f73c`, Sinbad's miniature `ff509a` and dial `c48fac` (max 15), The Porter's miniature `36ccb4` (a Custom_Token, like Daisy's) and dial `7859ab` (max 6), and the **Voyages** model `10bbcb`, a counter dial 0-7 that the savegame's script describes (`MIN_VALUE 0`, `MAX_VALUE 7`): `counter_dials.voyage` in `data/tts/sinbad.json`. No GUID of his is shared with another hero.

## Card identity: the shared CardID range
His deck is sheet 176 like Medusa's, the four turtles', Doctor Strange's, Bigfoot's, Daredevil's, Luke Cage's, Bullseye's, Golden Bat's, Jill Trent's, She-Hulk's and Tomoe Gozen's: the same CardIDs 17600-17629, a different image (`data/tts/sinbad.json`, `deck.identity`). Everything in docs/card-identity.md applies; the proof is `tests/test_hero_sinbad_data.py` (ranges equal, images disjoint from the other decks, no card equal across decks, detection in both seats against all nineteen, catalog entry, no shared GUID), `tests/test_card_identity.py` (he is in `SHARING`) and `tests/test_sinbad_matrix.py`.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Fighter | Effect |
|---|---|---|---|---|---|---|
| Voyage Home | attack | 2 | 1 | 1 | Sinbad | DURING: +1 per other VOYAGE card in the discard pile; AFTER: all the other VOYAGE cards of the discard pile go to the hand |
| Voyage to the Valley of the Giant Snakes | attack | 2 | - | 1 | Sinbad | DURING: +1 per other VOYAGE; AFTER: look at the opponent's hand |
| Voyage to the Island That Was a Whale | attack | 2 | - | 1 | Sinbad | DURING: +1 per other VOYAGE; AFTER: Sinbad recovers 2 |
| Voyage to the Creature With Eyes Like Coals of Fire | attack | 2 | - | 1 | Sinbad | DURING: +1 per other VOYAGE; AFTER: the opponent discards 1 random card |
| Voyage to the City of the Man-Eating Apes | attack | 2 | - | 1 | Sinbad | DURING: +1 per other VOYAGE; AFTER: 2 damage to the opposing fighter |
| Voyage to the City of the King of Serendib | attack | 2 | - | 1 | Sinbad | DURING: +1 per other VOYAGE; AFTER: draw 1 |
| Voyage to the Cannibals With the Root of Madness | attack | 2 | - | 1 | Sinbad | DURING: +1 per other VOYAGE; AFTER: you may move Sinbad up to 2 |
| Commanding Impact | attack | 5 | 2 | 1 | any | AFTER: draw 1 |
| By Fortune and Fate | attack | 3 | 1 | 3 | The Porter | AFTER: draw 2 |
| Momentous Shift | versatile | 3 | 1 | 3 | any | DURING: if your fighter started this turn in a different space, the value is 5 |
| Regroup | versatile | 1 | 1 | 3 | any | AFTER: draw 1; 2 instead if you won the combat |
| Toil and Danger | versatile | 3 | 1 | 4 | Sinbad | AFTER: move Sinbad up to 3 |
| Leap Away | versatile | 4 | 1 | 2 | any | AFTER: if you won, choose one of the fighters in the combat and move them up to 4 |
| Feint | versatile | 2 | 1 | 3 | any | IMMEDIATELY: cancel all effects on the opponent's card |
| Exploit | versatile | 4 | 1 | 2 | any | AFTER: draw 1 |
| Riches Beyond Compare | scheme | - | 1 | 2 | Sinbad | draw 3 |

## Discrepancies with unmatched-memory
- The ability reads "your fighters" on the card; unmatched-memory has "fighters".
- Six VOYAGE cards print no BOOST value (unmatched-memory: null); the overlay writes boost 0, so by the global ruling (28/10) a card without a boost value cannot be spent as a boost. Voyage Home prints BOOST 1.
- Titles, types, values, copies and texts of all 16 titles match unmatched-memory.
- Momentous Shift, Regroup, Leap Away, Feint, Commanding Impact and Exploit are word for word cards other heroes already have (Bigfoot, Luke Cage, Abe Sapien, Baba Yaga); `tests/test_hero_sinbad_data.py` pins that their effects are the very same data.

## Engine additions (all additive, docs/effects-dsl.md section 38)
- The passive rule `maneuver_move_per_counter` (+ the `counter` field of a rule modifier): `sparring/effects/maneuver.py`, reached through `Game.maneuver_bonus(player, boost=None)`. `Game.maneuver` adds it to the move of every fighter of the Maneuver; the bot's planners (`MedusaAI.maneuver_acts`, the search's `_extra`, the scripted rival of the simulator) add it to the reach they consider, and the search's estimate of a rival's reach (`free_steps`) counts it for the rival's Sinbad.
- `ai_sinbad.own_value` prices Momentous Shift by title, so it also changes Bigfoot's AI: his Momentous Shift is now valued 5 after his fighter moved this turn (instead of the printed 3) in `MedusaAI.card_value` and in the defense evaluation (`ai_medusa.py`, `eval_defense`). Intended: the card really is worth 5 then.
- Nothing else: the VOYAGE cards use `modify_value` with the amount `{"counter": "voyage"}` (the counter of the HeroDef, as Hellboy's destinies are read), `put_in_hand` of a CardSel with `pick: all` and a tag filter, and ops that already existed. No plugin.

## Fixes that came with him (found by his games, not specific to him)
- The search memoizes the legal moves by a signature of the state: a Maneuver whose reach depends on the pile (`Game.maneuver_bonus`) needs it in the signature (`EngineState._signature`), or a destination computed for a bigger pile is replayed against a smaller one and the engine refuses it (`tests/test_sinbad_effects.py`, the last test).
- The scripted rival of the simulator (`hellboy_script.try_attack`) now respects `Game.attack_card_reaches`: it offered Tomoe Gozen's adjacent-only Witness My Last Battle against a fighter that was not adjacent (a RuleError that only the 10-game runs exposed).
- `session_pieces.PIECE_TYPES` also lists "Tile" and "Token": a token imported from a save (The Porter, Daisy) is reported by TTS with those types, as `lua.TOKEN_TYPES` already says.

## Rule decisions (the most literal reading of the card, no ruling asked: see "Open questions")
1. **The ability** widens the reach of every fighter of Sinbad's player in a Maneuver by the number of VOYAGE cards in his discard pile when the fighters move: the hero and The Porter alike ("your fighters"). "You may" costs nothing (moving less is always allowed). The boost card of that same Maneuver is already in the discard pile when the fighters move, so a VOYAGE card spent as the boost counts (only Voyage Home has a BOOST value: it adds 1 to its own Maneuver; the planners count it too). Only a Maneuver action gets the bonus: moves of effects (Toil and Danger, Leap Away...) keep the numbers on their cards.
2. **VOYAGE cards' value**: printed 2 + the VOYAGE cards in the discard pile. The card being played is not in the pile until its combat ends, so "other" needs no exclusion. Cancelling the effects of a card (Feint) also cancels the DURING bonus, like any DURING effect.
3. **Voyage Home**: takes every VOYAGE card of the discard pile (0 included, no choice), never the one just played (it is not in the pile yet), and the card then goes to the discard pile as usual, so it can be taken back by the next Voyage Home.
4. **Voyage to the Creature**: the card is drawn by chance (`pick: random`): the bot's hand loses a random card on the table; a human's hand loses the position the bot names in the chat, which the human discards by hand.
5. **Momentous Shift**: "your fighter" is the fighter that plays the card, and "started this turn in a different space" compares it with where it stood when the turn began (the same bookkeeping as Bigfoot's identical card). On the rival's turn (a defense) the fighter started the turn where it was unless an effect moved it.
6. **Toil and Danger / Cannibals**: "Move Sinbad up to N" is a move of the hero (0 included) chosen by the owner, whatever the combat result; the human moves his own miniature by hand and presses End action like with any move of his own fighters. The Porter can never play either card (SINBAD band).
7. **Leap Away / Regroup**: "if you won the combat" is the engine's result (global rule, Iván 2026-11-07/08): the attacker wins only if combat damage lands; a tie or no damage is a win for the defender. Leap Away moves one fighter of the combat of the owner's choice (the rival's too; a fighter defeated in the combat cannot be chosen), exactly as Abe Sapien's card.
8. **By Fortune and Fate** can only be played by The Porter: with The Porter defeated the three copies are dead cards in hand (they still count for the hand limit and are discarded like any card).
9. **Exhaustion** applies as everywhere (Riches Beyond Compare with a short deck draws what is left and each empty draw deals 2 to each fighter).

## Open questions for Iván
1. **Does the ability reach The Porter?** Implemented: yes ("your fighters"). Alternative: Sinbad only (unmatched-memory says "fighters" too).
2. **Does the boost card count?** Implemented: yes, a VOYAGE card spent as the Maneuver's boost is already in the pile when the fighters move (only Voyage Home can be one). Alternative: count the pile as it was when the Maneuver began.
3. **Momentous Shift's "your fighter"**: implemented as the fighter that plays the card. Alternative: any fighter of yours (Sinbad's walk would then pay for a Porter's card).
4. **The Voyages dial** (`10bbcb`): it is unpacked and laid with Sinbad's other objects (a counter-dial slot of the layout), but the bot does not write it: the count of VOYAGE cards is read from the discard pile it already tracks. Should the bot keep it in step like Hellboy's destiny dial? (Today only a hero with forms writes a counter dial: `session.py` `_put_dials`.)
5. The chat hint of the Maneuver ("VOYAGE: your fighters may move up to +N spaces") only appears for the human's Sinbad; the human's moves are not range-checked (as for every hero), so it is a hint, not a rule check.

## AI
- The AI profile comes from the data (`ai_profile` of the importer: Sinbad `hero`, melee; The Porter `striker`). Name-based values live in `sparring/ai_sinbad.py`: `MedusaAI.card_value` and the defense evaluation read a VOYAGE card as 2 + the pile and Momentous Shift as 5 when its fighter started the turn elsewhere; the rival model (`Model`) fears a rival Sinbad's VOYAGE cards for what they will be worth.
- The Maneuver planners count the ability's bonus (`Game.maneuver_bonus`), so Sinbad walks farther the more VOYAGE cards he holds in the pile; the rest (draws, heal, damage, moves) is priced from the data like any other hero.

## Strength (simulator, heuristic AI, bprd-hq)
`python -m sparring.sim`, the bot's hero against the scripted rival (it chases and attacks with its best card, plays no schemes and resolves no text effects, so the numbers are only a sanity check of the pairing, never a balance statement). Bot's Sinbad, 10 games against each of the 18 other heroes (seed 100) and 20 against Tomoe Gozen: **196 wins to 4 over 200 games** (Medusa 9-1, Raphael 9-1, She-Hulk 8-2, every other rival 10-0 and Tomoe Gozen 20-0). The scripted Sinbad as the human's hero (a bot rival, seed 200, 10 games each over 19 rivals): 27 wins to 163, which only says the script plays him badly (it neither maneuvers for the VOYAGE bonus nor plays his schemes). With the search AI (`--ai ismcts --iterations 30`): 4-0 against Hellboy, 11-1 against Leonardo, and Medusa 12-0 against the scripted Sinbad. Zero crashes in all of them.

## Tests
`tests/test_hero_sinbad_data.py` (data and card identity), `tests/test_sinbad_effects.py` (the ability's reach, every card, the AI's valuation), `tests/test_sinbad_human.py` (FakeTTS, the panel: the human's cards, the table moves, the bot's Sinbad playing the same cards against a human), `tests/test_sinbad_matrix.py` (full games against all nineteen other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
