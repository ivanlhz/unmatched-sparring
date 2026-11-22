# Sherlock Holmes (Cobble & Fog)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, the hero card 304 on sheet 3) on 2026-11-22. Rulings: the readings of `REGLAS-PENDIENTES-batch4` section 2 (designers on BGG via RulesPal, Discord via the rulings archive) apply as written; Ivan 2026-11-22 corrected nothing for this hero.

## Summary
- Melee hero, 16 life, move 2, and **Dr. Watson** (ranged, 8 life, move 2), on the board from the start. Hero fid `holmes`, sidekick fid `watson`, slug `sherlock-holmes`.
- Ability: effects on HOLMES and DR. WATSON cards cannot be canceled by an opponent; effects on ANY cards (Feint, Education Never Ends, Study Methods) can be. "Ignore the value" is not a cancel. Watson cannot play HOLMES cards (the engine's band check, `Card.usable_by`).
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176, shared with Medusa and the rest: only `deck.identity` in `data/tts/sherlock-holmes.json` tells the decks apart, docs/card-identity.md). Order on the sheet: The Game is Afoot 0-1, Service Revolver 2-3, Deduce Strategy 4-6, Counterpunch 7-9, Study Methods 10-11, Education Never Ends 12-13, Feint 14-16, Fixed Point in a Changing Age 17-18, Elementary 19-20, Master of Disguise 21-22, Confirm Suspicion 23-25, Eliminate the Impossible 26-27, Administer Aid 28-29.
- Table: bag `248c8e` (inner `0d01e1`), Holmes' miniature `7c5cc7` and life dial `feaa22` (max 16), Watson's miniature `c0fd6e` (a Custom_Token, like Daisy and Dijkstra) and life dial `ec605e` (max 8), deck `9b3289`. Both dials share a GUID with another hero's dial (`feaa22` is Achilles', `ec605e` is Patroclus'); every one is a Custom_Model named after its fighter, so they are told apart by name (`session_pieces.resolve_dials`, `tests/test_piece_identity.py`).

## The ability: HOLMES and DR. WATSON cards cannot be canceled
Every HOLMES and DR. WATSON card carries the engine's `uncancelable` flag (`data/heroes/effects/sherlock-holmes.json`): `cancel_effects`, the legacy cancel, `settle_win_cancels` and the bot's `_cancellable_moments` already skip such a card (Incinerate, Ciri's cards). An ANY card does not, so the rival's Feint stops Holmes' own Feint, Education Never Ends and Study Methods. A value ignored by an effect (Highway Robbery, Incinerate's price) is not a cancel: the effects of the card still resolve.

## Cards (as implemented)
1. **The Game is Afoot** (attack 5 / 2, HOLMES): AFTER move Holmes up to 3 spaces (ordinary movement).
2. **Service Revolver** (attack 5 / 3, WATSON): no effect.
3. **Deduce Strategy** (versatile 3 / 1, HOLMES): DURING, an `optional` `set_value` of the rival's card to its BOOST (a card with no BOOST counts 0): the printed value becomes N, bonuses and a BOOST played on top still add; the defender's DURING resolves first. Nothing is asked when no card was played against it.
4. **Counterpunch** (versatile 3 / 1, HOLMES): AFTER, 2 damage to the opposing fighter if Holmes is adjacent to it.
5. **Study Methods** (versatile 3 / 2, ANY): AFTER, if Holmes' side won, `look_hand` (the bot reads the human's hand only then).
6. **Education Never Ends** (versatile 3 / 1, ANY): AFTER, won: the opponent draws 1; lost (a tie is lost): the owner draws 2.
7. **Feint** (versatile 2 / 1, ANY): IMMEDIATELY cancel all effects on the opponent's card. unmatched-memory files it under DURING; the card says IMMEDIATELY. The three Feints carry the tag `sherlock` (word for word Medusa's, Doctor Strange's and Pandora's; nothing reads the tag).
8. **Fixed Point in a Changing Age** (versatile 3 / 1, WATSON): AFTER, if Watson is adjacent to Holmes, each recovers 1.
9. **Elementary** (defense 3 / 3, HOLMES): see below.
10. **Master of Disguise** (scheme, boost 2, HOLMES): Holmes swaps spaces with the rival's hero (any distance, not a move), then 1 damage to that hero. If the swap cannot happen (a status that keeps a fighter in place) there is no damage (`swap ... as swapped`, then a test on the binding).
11. **Confirm Suspicion** (scheme, boost 1, HOLMES): see below.
12. **Eliminate the Impossible** (scheme, boost 2, HOLMES): `look_hand` on the rival, then the owner names 1 card for them to discard.
13. **Administer Aid** (scheme, boost 2, WATSON): Watson is placed on a space adjacent to Holmes (no free space: nothing), Holmes recovers 1, draw 1.

## Elementary (plugin `holmes:elementary`)
"Play this card face up. Predict the printed attack value of the opponent's card. DURING COMBAT: if you predicted the correct value, cancel all effects on your opponent's card and ignore its attack value."
- It is Abe's Perfect Shot mirrored. The plugin asks its owner once, in the defender's IMMEDIATELY, for a number 0 to 7 (an `effect` request with `op: predict` and `elementary: true`) and keeps it in the run's flags; the DURING compares it with the PRINTED value of the attacker's card (a versatile card is predicted by its printed value, a card with no printed value counts 0).
- Right number: `cancel_effects` with `force: true` (works on an uncancelable card too, REGLAS section 2, Discord) and `set_value ignore` (the whole total of that card is 0 at that moment; a later BOOST still adds, the engine's reading of "ignore the value"). The attacker's IMMEDIATELY has already resolved (timing order: IMMEDIATELY, DURING, AFTER).
- **Bot Holmes** (`ai_sherlock.predict_attack_value`): the commonest printed value among the cards the attacking fighter may still play (its deck list minus what is gone, restricted by band and attack type; a card a `look_hand` showed if any); ties go to the higher. It never reads a face-down card: the heuristic and the search defend without it, and in the rollouts the number is still the public estimate. Live, the bot places Elementary, turns it face up and says the number (`hidden.bot_defense_placed`).
- **Human Holmes**: at Reveal of the bot's attack the panel asks the number with buttons (0 to 4, then "Mas": 5 to 7) BEFORE the bot's card is turned (`session_hidden.ask_elementary`, saved in `Pending.predict`, so a resume lands on the same question). The answer is kept in `Pending.prediction["defense"]` and the combat resolves in the same click. The human plays the card face up; the chat tells them to.

## Confirm Suspicion (plugin `holmes:confirm_suspicion`)
"Name a value. Your opponent must choose and discard one card matching that attack or defense value. Their hero takes damage equal to the BOOST value of the discarded card. If they do not have a card of the named value, they must reveal their hand instead."
- Any number may be named (0 to 7 on the panel); a card matches when its printed value is that number (a versatile card by its value, a scheme never, no printed value counts 0). The damage is effect damage on the rival's HERO.
- **Rival is the bot (or a simulation)**: the engine lists the matching cards of its hand; the rival chooses (the usual give-up pricing: the least valuable card). None: `look_hand`, so Holmes' player sees the hand (`KnownHand`); the human sees the bot's hand in the row like any other look.
- **Rival is the human at the table**: the engine cannot know their hand. A `cards` request (`pile_mode: reveal`, `confirm: N`): the chat asks them to lay a card of that value on their discard pile and press Done, or press Done with nothing; the bot reads the pile (`session_rage`, the verdict refuses a card that does not match and says which). Nothing laid: the hand is read (`look_hand`, the one place the bot reads it) and a matching card found there is demanded again (`phase: recheck`, "your hand shows a card of value N").
- **Naming the value**: the bot names it by price (`ai_sherlock.name_value`: the chance that the rival holds a card of the value, from the rival's deck list minus what is gone and the size of their hand, times the least BOOST they could discard plus the card, against the look a miss gives). The human names it on the panel (an `amount` request, buttons 0 to 7).
- A rule against forced discards (Counterhex Shield) leaves the rival alone: nothing is discarded and nothing is revealed.

## AI (`sparring/ai_sherlock.py`)
- Elementary and Confirm Suspicion: above. Deduce Strategy: `deduce_pays`, yes when the printed value drops (the BOOST is lower than the value), no otherwise.
- The search plays the real engine, so these three decisions are what its simulated opponents and its own turns answer with (`EffectAI._effect` / `_amount` / `_optional`, `SyntheticChooser`); `tests/test_sherlock_ai.py` plays whole games with `make_bot_ai({"ai": "ismcts"})` on both seats.

## Table (what the bot does, what the chat asks, what the bot reads back)
- **Pieces**: Holmes' miniature and dial come out of the bag like any hero's; Watson is a Custom_Token with a life dial; the Watson dial and the Holmes dial share a GUID with Patroclus' and Achilles' (resolved by name).
- **Bot as Holmes**: Elementary is placed, turned face up and announced with its number; Confirm Suspicion names its value in the chat and asks the human for the discard; Master of Disguise swaps the two miniatures (the bot moves its own, the chat tells the human to move theirs and the bot reads it back, the `swap` translator); Administer Aid places Watson by the bot; the looks (Eliminate, Study Methods, a miss of Confirm Suspicion) read the human's hand once, when the card says so.
- **Human as Holmes**: Elementary as above; Confirm Suspicion is named on the panel and the bot answers; the other cards go through the interpreter: the human moves their pieces by hand (Game is Afoot, Administer Aid, Master of Disguise) and the bot reads them back.

## Tests
`tests/test_sherlock_effects.py` (the deck, the ability, Elementary, Deduce Strategy), `tests/test_sherlock_cards.py` (the schemes and AFTER cards), `tests/test_sherlock_human.py` (the panel, both seats), `tests/test_sherlock_ai.py` (the policies and whole games), `tests/test_sherlock_matrix.py` (full games against every other hero in both seats, FakeTTS), `tests/test_hero_sherlock_holmes_data.py` (overlay, HeroDef, effects and table data against the real cards).

## Pending Ivan (nothing ruled; the most literal reading is implemented)
1. **Elementary against a card whose IMMEDIATELY already ran**: the cancel happens in DURING, so the attacker's IMMEDIATELY effects (a Feint of the rival, Sleight Of Hand) have resolved before it; only DURING and AFTER are stopped. The card says DURING COMBAT.
2. **Naming a value above 7**: the panel offers 0 to 7 for every prediction (Ivan 28/10); no printed value in the game is higher.
3. **Confirm Suspicion with a card of no printed value** (Stones in the Belly, counted 0): it matches the value 0.
4. **A human who says "none" while holding a match**: the bot reads the hand and demands the card; the alternative is to trust the human.
5. **Administer Aid with Watson defeated**: the card cannot be played (a WATSON card needs Watson on the board).
6. **Deduce Strategy** is decided by the owner's panel yes/no for the human; the bot takes it only when it lowers the value.
