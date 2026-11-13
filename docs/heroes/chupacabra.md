# Chupacabra (Battle of Legends, Volume Three)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 360 on sheet 3) on 2026-11-13.

## Summary
- Melee hero, 14 life, move 3, **no sidekicks**. Hero fid `chupacabra`, slug `chupacabra`.
- Ability **THE HUNGER**: "After you attack, you may draw a card." An `after_attack` trigger with an `optional` draw (`docs/effects-dsl.md`, Michelangelo's PIZZA PARTY has the same event); no engine addition.
- Deck: 30 cards, `CardID = 17600 + idx`, every card restricted to CHUPACABRA. The deck object in the save holds 31 cards (the 30 plus the character card 360), hence `card_count 31` and `card_ids [360, 17629]` in the catalog.
- Table: bag `a20352` (inner `d980fa`), deck `3516ce`, miniature `4137cf` (an asset bundle) and life dial `ca8e35` (max 14). **The dial GUID `ca8e35` is also Donatello's and Tomoe Gozen's** (and Little Red's, not in the project): the save reuses it for every hero's Custom_Model dial, told apart by the dial's name like the other collisions of the save (`session_pieces.resolve_dials`, docs/card-identity.md "Piece identity"). His matrix against both in both seats is the proof on FakeTTS (`tests/test_chupacabra_matrix.py`); `tests/test_hero_chupacabra_data.py` pins that this is the only GUID he shares.

## Card identity: the shared CardID range
His deck is sheet 176 like Medusa's, the turtles' and every other hero's of the project: CardIDs 17600-17629, a different image (`data/tts/chupacabra.json`, `deck.identity`). Everything in docs/card-identity.md applies; the proof is `tests/test_hero_chupacabra_data.py`, `tests/test_card_identity.py` (he is in `SHARING`) and `tests/test_chupacabra_matrix.py`.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| The More They Struggle | attack | 0 | 3 | 3 | DURING: the value is twice the printed value of the opponent's card |
| Ambush | attack | 2 | 3 | 2 | DURING: the opponent discards 1 random card; add its BOOST value to the value (plugin) |
| Feeding | attack | 4 | 2 | 3 | AFTER: with 7 or less health, gain 1 action and recover 1 |
| Blood in the Air | attack | 4 | 4 | 3 | DURING: if you already won a combat this turn, you may BOOST this card |
| Wounded Beast | versatile | 3 | 1 | 3 | DURING: with 7 or less health the value is 5 |
| Tooth and Tail | versatile | 2 | 2 | 3 | AFTER: 1 damage to up to 2 adjacent fighters; recover 1 for each damaged (plugin) |
| Feint | versatile | 2 | 2 | 3 | IMMEDIATELY: cancel all effects on the opponent's card |
| Ravenous Lunge | versatile | 3 | 2 | 3 | AFTER: recover 1; 2 if you won |
| Natural Toughness | defense | 3 | 3 | 2 | AFTER: if you lost the combat, return this card to your hand |
| Traveler of the Night | scheme | - | 3 | 3 | move up to 4 through opposing fighters; gain 1 action |
| Unsettle | scheme | - | 2 | 2 | if an opposing fighter is in his zone: the rival discards 1 card, or 2 if you deal 2 damage to Chupacabra |

## Discrepancies with unmatched-memory
- unmatched-memory (transcribed from screenshots on 2026-11-13, unverified) gives the two schemes a value of 0; the cards print none. The overlay writes `value: null` for them (idx 25-29). The More They Struggle prints a real 0.
- The title casing: unmatched-memory has "The more they struggle", "Blood in the air", "Wounded beast", "Tooth and tail", "Ravenous lunge", "Natural toughness", "Traveler of the night"; the cards print Title Case, kept as the title (the overlay's `memory_title` maps them).
- Everything else (types, values, boosts, copies, texts, 14 life, move 3, the ability) agrees with the images. The START HEALTH digit of the character card is half hidden by the icon in the image; unmatched-memory says 14 and the save's dial maximum is 14.
- Feint is word for word Sinbad's and Bigfoot's card; `tests/test_hero_chupacabra_data.py` pins that its effects are the very same data.

## Engine additions
- `sparring/effects/plugins_chupacabra.py`, two plugins and nothing else (no new op, event, rule or schema field):
  - `chupacabra:ambush` (via the shared helper `sparring/effects/random_discard.py`, `discard_random_known`): for a bot or simulated rival the card is drawn from the engine's hand (`run.random_sample`), discarded, and its BOOST added (`cf.ambush`). For the human (Ivan, 2026-11-13) the bot says a position from the hand size ("the card N of your hand counting from the left", `ops_core._random_positions_text`), the human discards THAT card onto their discard pile and presses Done, and the bot DETECTS the card on the table by its identity (`session_rage`, `pile_mode: reveal` with `ambush`) and adds its BOOST. An empty hand discards nothing and adds 0. The request is saved with the run, so a resume mid-flow asks the same question.
  - `chupacabra:tooth_and_tail`: "up to 2 fighters" has no DSL form. The fighters adjacent to Chupacabra are taken in order (all of them when two or fewer, a `fighter` request of 0 to 2 when more), each takes 1 effect damage and he recovers 1 for each that really took it (an immune fighter does not count).
- Everything else is existing DSL: `modify_value` with `{"attr": "value", "of": "opponent_card", "times": 2}`, `allow_boost` of `this` behind a `combats_won_this_turn` test, `set_value`, `stat hp`, `put_in_hand` of `this`, `move ... through_enemies`, `optional` with a `cost` and an `else`.

## Rule decisions (the most literal reading, no ruling asked: see "Pending Ivan")
1. **THE HUNGER** fires for every attack of the player after the combat (and its AFTER effects) is over, also when the attack was defended or dealt no damage, never when he defends (Michelangelo's precedent). The draw is optional: the bot decides with its evaluation, the human answers Yes / No.
2. **The More They Struggle**: twice the PRINTED value of the rival's card (a boost or an effect on the rival's side never counts); against no card or a card cancelled before DURING it is 0. Attack only.
3. **Ambush**: "its BOOST value" is the printed BOOST of the card discarded. A rival with an empty hand discards nothing and adds 0. A cancelled Ambush (the rival's card cancels the effects) discards nothing.
4. **Blood in the Air**: "already won a combat this turn" is the engine's `combats_won_this_turn` tally (the combat being resolved is not counted, a combat won on the rival's turn counts for that turn). The BOOST is the free BOOST of `may_boost` cards, asked after DURING.
5. **Feeding / Wounded Beast**: the 7 or less health test is Chupacabra's (the hero's) health when the effect runs: for Feeding after the combat damage, for Wounded Beast during the combat. Feeding's action only exists on his own turn.
6. **Ravenous Lunge / Natural Toughness**: "if you won / lost the combat" is the engine's result (global rule, Iván 2026-11-07/08): the attacker wins only if combat damage lands, a tie or no damage is a win for the defender. So Natural Toughness (defense) returns to the hand only when the attacker's damage lands.
7. **Tooth and Tail** damages any fighter adjacent to him (there are no friendly ones: he has no sidekicks), read after the combat. With three or more adjacent the owner picks which two; with one or two all of them take the damage.
8. **Traveler of the Night**: "your fighter" is Chupacabra (his only fighter). Up to 4, through opposing fighters, then 1 action back (the scheme itself costs 1). The human moves his miniature by hand like with any move of his own fighters.
9. **Unsettle**: "choose an opponent" is the rival (two players). The condition is an opposing fighter in his zone when the card is played. The rival chooses what they discard (the human from their hand by hand, the bot by its own judgement). The 2 damage is the `cost` of an `optional` paid before the discards, and nothing forbids paying it with 2 or less health left (the AI never does, see below).

## AI
- The AI profile comes from the data (`ai_profile` of the importer: Chupacabra `hero`, melee, no exclusive cards beyond his own deck). Name-based values live in `sparring/ai_chupacabra.py` and are read by `MedusaAI` (attack value of The More They Struggle, Ambush and Wounded Beast; the AFTER of Feeding, Ravenous Lunge, Tooth and Tail and Natural Toughness in `attack_outcome` and `eval_defense`). Without them the heuristic read The More They Struggle as an attack worth 0 and never played it.
- THE HUNGER is the `_free_draw` of `EffectAI` (always taken when the deck holds a card); Unsettle's price (2 damage for a second discard) is an `optional` with a `cost` that `EffectAI._optional` simulates against the alternative (the bot pays at full health, refuses when hurt).
- Checked with the search (`make_bot_ai({"ai": "ismcts"})`): games against Hellboy, Bigfoot, Liz Sherman, Medusa and Sinbad, no fallbacks (`ai.fallbacks == 0`), 18 of 20 won against the scripted rival.

## Tests
`tests/test_hero_chupacabra_data.py` (data and card identity), `tests/test_chupacabra_effects.py` (THE HUNGER, every card and both plugins on the engine), `tests/test_chupacabra_human.py` (FakeTTS, the panel: the human's cards, THE HUNGER's Yes / No, the bot's Ambush reading the card the human lays on their pile, Unsettle, Tooth and Tail), `tests/test_chupacabra_matrix.py` (full games against all twenty-three other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).

## Decided by Ivan (2026-11-13)
1. **Unsettle's cost**: the 2 damage may be paid at any health (the owner may even defeat himself). The bot's AI never pays when it would die.
2. **Start health**: 14.
3. **Tooth and Tail**: damages automatically when 2 or fewer fighters are adjacent; the owner only chooses when there are 3 or more.
4. **Ambush against the human**: the bot says a number from 1 to the size of the human's hand, the human discards that card and presses Done, the bot detects the discarded card on the table and adds its BOOST (the same flow as the Raptors' Ambush; no BOOST value is typed).

## Pending Ivan
1. **The More They Struggle against a card whose value an effect changes**: the PRINTED value is used, as the card says.
