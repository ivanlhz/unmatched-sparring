# Yennenga (Battle of Legends, Volume Two)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 319 on sheet 3) on 2026-11-20. Verified on FakeTTS only: nothing of Yennenga has been seen on a real table (see `docs/live-checklist.md`).

## Summary
- Ranged hero, 15 life, move 2. Sidekick **Archer**: two of them (fids `archer1`, `archer2`), ranged, 2 life each, move 2. Hero fid `yennenga`. The hero card prints the move once (2) for both.
- Ability: **If Yennenga would take damage, you may assign any amount of that damage to one or more Archers in her zone instead. (You may not assign more damage to an Archer than their remaining health.)** It is the passive `yennenga:assign_damage` of her effects file, read by the damage code (`sparring/effects/plugins_yennenga.py`).
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176), restriction bands YENNENGA, ANY (Surprise Volley, Skirmish, Momentous Shift) and ARCHER (Pin the Prey, Divide and Conquer: only the Archers play them). The deck object of the save holds 31 cards (the 30 plus the character card `319`).
- Table: Yennenga's miniature `3ec3d1` (**Houdini's miniature has the same GUID**, told apart by name) and dial `1fc8df` (max 15); the two Archer models `cbb5f5` and `b19614`, **with no life dial** (see below).
- **She shares CardIDs 17600-17629 with Medusa, the turtles, Strange, Bigfoot, Luke Cage and the rest of sheet 176**: her deck is told apart by deck image and owner (docs/card-identity.md), never by a bare CardID. `tests/test_yennenga_matrix.py` plays her against every other hero in both seats.

## `hasTokens: true` in unmatched-memory
It means nothing for the table. Her bag holds **no token**: the two models nicknamed `Archer` (description "Sidekick Token") are the Archers themselves. She has no counter, no token and no form.

## The Archers have no life dial
The save gives the Archers 2 life but no dial (every other sidekick with more than 1 life has one). `data/tts/yennenga.json` marks them `no_dial: true` (the overlay says `"tts": {"no_dial": ["archer1", "archer2"]}`; `tools/import_save.py` and `sparring/tts/hero_table.py` accept the combination only when asked). Consequences, all deliberate:
- The engine is the only place their life lives; the chat says what each Archer took (`archer1 takes 2 of the damage meant for yennenga`) and when one falls.
- A fallen Archer: the bot's is taken off the board by the bot; the human's miniature is removed by the human (the usual chat line). A returned Archer (Surprise Volley, Shield Formation): the bot puts its own; the human places theirs by hand where the chat says.
- Nothing is written to or read from a dial for an Archer, so `--read-only` and the dial check do not mention them.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Who | Effect |
|---|---|---|---|---|---|---|
| Rain of Arrows | attack | 3 | 3 | 3 | Yennenga | AFTER: VOLLEY, a second attack of 3 (double attack) |
| Surprise Volley | attack | 3 | 3 | 3 | any | IMMEDIATELY: you may return a defeated Archer to a space in the opposing fighter's zone, it becomes the attacker; if not, gain 1 action |
| Point Blank | versatile | 2 | 2 | 3 | Yennenga | AFTER: if the opposing fighter is adjacent to Yennenga, 2 damage to it |
| Stallion Charge | versatile | 3 | 3 | 3 | Yennenga | AFTER: move Yennenga up to 5, through opposing fighters; 1 damage to each one she moved through |
| Jaws of the Beast | versatile | 3 | 3 | 3 | Yennenga | DURING: +1 for each zone the opposing fighter is in |
| Skirmish | versatile | 4 | 2 | 2 | any | AFTER: if you won, move a fighter of the combat up to 2 |
| Momentous Shift | versatile | 3 | 2 | 3 | any | DURING: if your fighter started this turn in a different space, the value is 5 |
| Pin the Prey | versatile | 1 | 2 | 2 | Archer | AFTER: move the opposing fighter up to 4; your opponent discards 1 card |
| Divide and Conquer | versatile | 2 | 1 | 2 | Archer | DURING: if your fighter is not in Yennenga's zone, the value is 4 |
| Shield Formation | defense | 3 | 3 | 2 | Yennenga | IMMEDIATELY: your opponent may discard a card; if they don't, return a defeated Archer to a space in Yennenga's zone |
| One With The Land | scheme | - | 2 | 2 | Yennenga | Move each of your fighters up to 2, each recovers 1 health, draw 1 |
| Master of the Hunt | scheme | - | 3 | 2 | Yennenga | Gain 2 actions |

## Discrepancies with unmatched-memory
- **`hasTokens: true`**: no token exists (above).
- **Point Blank** reads "deal 2 damage to that fighter" on the card; unmatched-memory has "deal them 2 damage". The overlay carries the printed text.
- The restriction bands are not in unmatched-memory at all. Type, value, boost, copies and the rest of the texts of the 12 titles agree with the images.
- Farm slip: `UNMATCHED_MEMORY=/memory/data/heroes` makes `tools/import_hero.py` look one folder too deep; it works with `UNMATCHED_MEMORY=/memory`.

## Collisions found in the save
- **CardIDs 17600-17629**: shared with the other sheet-176 decks. Solved as for them: `data/tts/yennenga.json` carries its own `deck.identity` and every lookup is per owner; `tests/test_hero_yennenga_data.py` pins that no card is equal to a card of another deck of the range and that the images differ.
- **Her miniature GUID `3ec3d1` is Houdini's miniature too.** The two heroes in one game resolve their pieces by name (docs/card-identity.md, "Piece identity"), as Bullseye and George Washington do for a dial; pinned in `tests/test_piece_identity.py` and `tests/test_hero_yennenga_data.py`, and exercised by the Houdini pairs of the matrix.

## How the ability works (engine)
The damage never changes hands after it landed: the choice comes BEFORE.
- **Combat damage.** Before the DAMAGE phase of a combat in which Yennenga is the victim and some Archer of hers stands in her zone, the flow runs a small effect run (`flow.runs["damage:def"]`, plugin op `yennenga:assign_damage`). It asks Yennenga's OWNER, once per Archer in fighter id order, "how many of the points still to assign does this Archer take?": options from 0 to the lesser of the points left and the Archer's remaining life. The human answers on the panel (the combat is saved paused, `--resume` repeats the question); the bot answers by `ai_yennenga.archer_share`. Then the damage lands: the Archers' shares as combat damage on each Archer (the events fire for them, an Archer at 0 falls), the rest on Yennenga. The combat's result still says the full blow landed (the attacker won the combat) and the chat adds one line per Archer.
- **Effect damage** (a `damage` op aimed at her): the same questions inside the op; each share is effect damage on the Archer.
- Reductions that apply to her (a blow cut by a hero's ability, a damage cap) are applied first: she and the Archers split what would really land. A blow of 0 asks nothing. With no Archer in her zone nothing is asked.
- The second attack of a double attack is a combat of its own: it asks again.

## Rules decisions (the most literal reading, applied)
Every item that is a real doubt is also under "Pending Ivan".

1. **"In her zone"**: a living Archer of hers sharing a zone of the board with the space she stands on (`Game.zone_mates`), adjacent or not.
2. **"Would take damage"**: the damage of a combat (the blow that lands after every reduction) and effect damage. **Exhaustion damage is not assigned**: each fighter takes it separately when the deck runs out and no decision is asked there.
3. **The blow still counts as landed** for who won the combat: damage given to the Archers is damage the attack dealt; nothing in the engine reads "damage taken by the hero" afterwards, so AFTER effects that look at damage taken (Skin Like Titanium of Luke Cage) read the full blow.
4. **Surprise Volley**: "a defeated Archer" returns at its starting life (2) to a free space of the opposing fighter's zone chosen by the owner; it takes the attacker's place for this combat (the card stays in play for it, `CombatFlow.replace_combatant`, the machinery of Smoke And Mirrors); the first attacker does not fight any more. "If not" is the declined case and the case with no defeated Archer or no free space: gain 1 action. An Archer may play the card too (band ANY) and is replaced the same way. The bot always returns the Archer when it can.
5. **Shield Formation**: the opponent chooses between discarding one card of their hand and letting an Archer come back (full life, a free space of Yennenga's zone). With an empty hand, or the card chosen by a player who cannot pay, the Archer returns. With no defeated Archer the "if they don't" part does nothing.
6. **Stallion Charge** moves Yennenga only (the card is hers), up to 5, through opposing fighters; "moved through" is the set of opposing fighters standing on some path of at most 5 spaces from the space she started on to the one she ended on (the same reading as Power Man's, CONFIRMED by Iván 2026-11-07), 1 effect damage each. Not conditional on winning. The human walks her miniature by hand and names who was passed.
7. **Momentous Shift** "started this turn in a different space": the fighter stands on another space than the one it started the turn on (also in defense, on the opponent's turn).
8. **Divide and Conquer**: "not in Yennenga's zone" = the Archer's space shares no zone with hers.
9. **Jaws of the Beast**: +1 per zone the opposing fighter's space belongs to, read when its DURING runs.
10. **Pin the Prey**: both parts are unconditional (win or lose); a fighter defeated by the combat is not moved.
11. **One With The Land**: every living fighter of hers (Yennenga and each Archer) moves up to 2, then recovers 1 (never above its maximum); one card is drawn.
12. **Cards only an Archer can play** (Pin the Prey, Divide and Conquer) are dead in the hand while both Archers are down and nothing of the deck can bring one back.

## Pending Ivan
1. **Exhaustion**: should the damage of an empty deck to Yennenga also be assignable to the Archers? (Today it is not: each fighter takes its own.)
2. **Damage taken**: should an effect that reads "the damage you took" (Luke Cage's Skin Like Titanium against her) see the whole blow or only what landed on Yennenga? (Today the whole blow.)
3. **Surprise Volley** returns the Archer with its starting 2 life: confirm. And whether the Archer that returns may be one that fell THIS turn (today yes).
4. **Rain of Arrows**: how the second attack interacts with her ability, boosts and bonuses (the double-attack rulings pending in docs/combat-flow.md): today the second attack is a combat of its own against the same defender, so the question of the Archers' share is asked again for it.
5. **Archers on the table**: with no dial the human cannot see an Archer's life on the table, only in the chat. Does Iván want a marker (a die or a nickname with the life) next to them?

## AI
- The AI profile comes from the data (Yennenga `hero`, the Archers `striker`; exclusive cards: Pin the Prey and Divide and Conquer for the Archers).
- **Assignment** (`sparring/ai_yennenga.py`, one policy for the live bot, the search and the rollouts): the split of the damage that is worth most for her owner, in the units of the rest of the evaluation: a point on the hero costs more than a point on an Archer, a fallen Archer costs its kill value, and the chance that what is left of her dies in the rival's next turn is priced at LETHAL (`MedusaAI.death_risk`, left out in the rollouts). While the Archers can keep her alive she is never left to fall; with a hero out of reach of the rival the Archers keep their life.
- Shield Formation, when the bot is the opponent: decided by the generic optional (simulating a discard against the Archer's return).
- Surprise Volley: the bot returns the Archer whenever it can.
- **Not done in the heuristic**: the card-value hooks of `MedusaAI` (Momentous Shift worth 5 after a move, Divide and Conquer 4 away from her, Jaws of the Beast +zones, Point Blank / Stallion Charge as damage). The search plays the real engine and sees them; the heuristic reads the printed values.
- **Measured** (ISMCTS 30 iterations, scripted "chaser" Hellboy, 12 games, bot seat): Yennenga wins 1 of 12, Luke Cage 10, Sinbad 10, Jill Trent 1 of 8, Golden Bat 2 of 8; the heuristic bot wins 15 of 20 (Luke Cage 17, Chupacabra 16). Her Archers (2 life) are killed by turn 4-6 in most games; marking them `keep_away` changed nothing (1 of 12). Not tuned further: a candidate is a position bonus for Archers standing in her zone.

## Human side
- The panel asks, for each Archer of hers in her zone, a number (the buttons 0, 1, 2); `--resume` repeats the question.
- Surprise Volley and Shield Formation: the chat says where the Archer returns; you place your own miniature by hand. Stallion Charge: you move her miniature and name the fighters you passed.
- The Archers' life is not on the table: the chat keeps it.

## Tests
`tests/test_hero_yennenga_data.py` (data, card identity, detection, the `no_dial` flag), `tests/test_yennenga_effects.py` (the ability and every card on the interpreter, Rain of Arrows on the double-attack engine), `tests/test_yennenga_human.py` (FakeTTS panel: the questions, a resume, the blow left after a defense), `tests/test_yennenga_ai.py` (the assignment policy, the bot playing her with the heuristic and with ISMCTS), `tests/test_yennenga_matrix.py` (full games against every other hero in both seats, passive and attacking human, headless with the heuristic and the search AI).
