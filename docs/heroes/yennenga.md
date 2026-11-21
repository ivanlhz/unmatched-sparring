# Yennenga (Battle of Legends, Volume Two)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 319 on sheet 3) on 2026-11-20. Verified on FakeTTS only: nothing of Yennenga has been seen on a real table (see `docs/live-checklist.md`).

## Summary
- Ranged hero, 15 life, move 2. Sidekick **Archer**: two of them (fids `archer1`, `archer2`), ranged, 2 life each, move 2. Hero fid `yennenga`. The hero card prints the move once (2) for both.
- Ability: **If Yennenga would take damage, you may assign any amount of that damage to one or more Archers in her zone instead. (You may not assign more damage to an Archer than their remaining health.)** It is the passive `yennenga:assign_damage` of her effects file, read by the damage code (`sparring/effects/plugins_yennenga.py`).
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176), restriction bands YENNENGA, ANY (Surprise Volley, Skirmish, Momentous Shift) and ARCHER (Pin the Prey, Divide and Conquer: only the Archers play them). The deck object of the save holds 31 cards (the 30 plus the character card `319`).
- Table: Yennenga's miniature `3ec3d1` (**Houdini's miniature has the same GUID**, told apart by name) and dial `1fc8df` (max 15); the two Archer models `cbb5f5` and `b19614`, **with no life dial: a two-sided token** (see below).
- **She shares CardIDs 17600-17629 with Medusa, the turtles, Strange, Bigfoot, Luke Cage and the rest of sheet 176**: her deck is told apart by deck image and owner (docs/card-identity.md), never by a bare CardID. `tests/test_yennenga_matrix.py` plays her against every other hero in both seats.

## `hasTokens: true` in unmatched-memory
It means nothing for the table. Her bag holds **no token**: the two models nicknamed `Archer` (description "Sidekick Token") are the Archers themselves. She has no counter, no token and no form.

## The Archers have no life dial: the token is flipped (Ivan, 2026-11-20)
The save gives the Archers 2 life but no dial: each is a single `Custom_Model` (one mesh, one diffuse image, no states, no second image, no script), flagged `no_dial: true` in `data/tts/yennenga.json` (overlay `"tts": {"no_dial": [...], "life_faces": {...}}`) so the table layer accepts 2 life with no dial. Ivan's rule, with photos of the real component: **each Archer is a two-sided token; the face with a small yellow "2" in the top-right corner is 2 health, the face with no number is 1 health; life is tracked by flipping the token** (there is no dial and none is needed).
- The save has no second face to read, so `faces` (Z rotation that shows each life, **2 = 0, 1 = 180**) was a guess copied from Abe's and Rosie's convention; **verified live by Ivan 2026-11-21** (the '2' face is up as the save ships, the flipped face has no number).
- **The bot's Archers** (`sparring/session_archers.py`, called wherever the session tracks Rosie's tokens): whenever the engine's life of one changes (a hit, One With The Land, a return from defeat at 2) the bot turns the piece to that face, only if it is not there already, and says it in the chat (`archer.flipped`). At the start of a game, a restart or a resume every Archer is put on the "2" face. A defeated Archer is not touched; it comes back on the "2" face.
- **The human's Archers** (Ivan, 2026-11-21: "xq cuando le hacen un dano a una arquera no le das la vuelta a la ficha?"): the bot flips them too, exactly as its own, whenever the engine's life changes, the same way it sets the life dials of both sides. Between changes every look reads the Z rotation of each living one (`lua.archer_faces`); a token the human turned by hand to another life is NOT turned back: the chat says so, asks the human to flip it (`archer.human_flip`) and pings the piece, once per disagreement (as a dial touched by hand). The engine stays the authority and neither side is trusted silently.
- A fallen Archer is removed by whoever plays it (the bot's by the bot); a returned one is placed by hand where the chat says.

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
- **Effect damage** (a `damage` op aimed at her): the same questions inside the op, asked about the blow AFTER the +N modifiers (they apply once to the whole blow, never per share); each share is effect damage on the Archer, applied as already modified. An op that also hits an Archer itself (an area effect) reserves that hit: a share never exceeds the life the Archer will have left after it. The fighter the op binds with `as` stays Yennenga whoever soaked the damage.
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

## Decided (Ivan 2026-11-20)
- **Exhaustion damage is NOT assignable to the Archers**: every fighter takes it at once. This is what the engine does.
- **Area damage**: damage is always dealt to the sidekicks first; if they survive, Yennenga may then redirect her damage to them or take it. This confirms the reading applied: an Archer's share leaves room for the hit the same effect deals that Archer, so no point is lost on a fighter the effect already killed.

## Pending Ivan
0. **Archers' share and who "won"**: DECIDED (Ivan 2026-11-20): damage that lands on the defender's own side (her Archers, or Baba Yaga's Koschei) counts as taken by the defender, so the attacker WINS. Only damage redirected to the attacker's side (Golden Chain Mail) makes the defender win. This is what `CombatFlow._damage` already does (`victim.owner != att.owner`).
1. **Damage taken**: should an effect that reads "the damage you took" (Luke Cage's Skin Like Titanium against her) see the whole blow or only what landed on Yennenga? (Today the whole blow.)
2. **Surprise Volley** returns the Archer with its starting 2 life: confirm. And whether the Archer that returns may be one that fell THIS turn (today yes).
3. **Rain of Arrows**: how the second attack interacts with her ability, boosts and bonuses (the double-attack rulings pending in docs/combat-flow.md): today the second attack is a combat of its own against the same defender, so the question of the Archers' share is asked again for it.
4. **Archer token faces**: on the real table the Archer token may not show a different face when flipped (the save has one `Custom_Model` with a single image), so the two-faces rule (Ivan 2026-11-20) needs a live check of what, if anything, a flip shows.

## AI
- The AI profile comes from the data (Yennenga `hero`, the Archers `striker`; exclusive cards: Pin the Prey and Divide and Conquer for the Archers).
- **Assignment** (`sparring/ai_yennenga.py`, one policy for the live bot, the search and the rollouts): the split of the damage that is worth most for her owner, in the units of the rest of the evaluation: a point on the hero costs more than a point on an Archer, a fallen Archer costs its kill value, and the chance that what is left of her dies in the rival's next turn is priced at LETHAL (`MedusaAI.death_risk`, left out in the rollouts). While the Archers can keep her alive she is never left to fall; with a hero out of reach of the rival the Archers keep their life.
- Shield Formation, when the bot is the opponent: decided by the generic optional (simulating a discard against the Archer's return).
- Surprise Volley: the bot returns the Archer whenever it can.
- **Not done in the heuristic**: the card-value hooks of `MedusaAI` (Momentous Shift worth 5 after a move, Divide and Conquer 4 away from her, Jaws of the Beast +zones, Point Blank / Stallion Charge as damage). The search plays the real engine and sees them; the heuristic reads the printed values.
- **Measured** (the reviewer's numbers, ISMCTS against the scripted chaser Hellboy, 12 games, bot seat): Yennenga 4 of 12 with the ability and 3 of 12 without it, the heuristic bot 10 of 12, 0 fallbacks. An earlier figure of mine (1 of 12) did not reproduce and is withdrawn. It is a search-versus-heuristic weakness of this deck (low printed values, fragile Archers), like Jill Trent's and Golden Bat's, not a fault of the ability. Marking the Archers `keep_away` changed nothing. Not tuned further; a candidate is a position bonus for Archers standing in her zone.

## Human side
- The panel asks, for each Archer of hers in her zone, a number (the buttons 0, 1, 2); `--resume` repeats the question.
- Surprise Volley and Shield Formation: the chat says where the Archer returns; you place your own miniature by hand. Stallion Charge: you move her miniature and name the fighters you passed.
- The Archers' life is the face of their token: the bot flips it when the engine's life changes and says it; if you turn one by hand to another life, the chat asks you to put it back and pings it.

## Tests
`tests/test_hero_yennenga_data.py` (data, card identity, detection, the `no_dial` flag), `tests/test_yennenga_effects.py` (the ability and every card on the interpreter, Rain of Arrows on the double-attack engine), `tests/test_yennenga_human.py` (FakeTTS panel: the questions, a resume, the blow left after a defense), `tests/test_yennenga_faces.py` (the Archer token faces, FakeTTS, both seats), `tests/test_yennenga_ai.py` (the assignment policy, the bot playing her with the heuristic and with ISMCTS), `tests/test_yennenga_matrix.py` (full games against every other hero in both seats, passive and attacking human, headless with the heuristic and the search AI).
