# Bigfoot (Robin Hood vs. Bigfoot)

Set "Robin Hood vs. Bigfoot". Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 309 on sheet 3) on 2026-11-03. Verified on FakeTTS only: nothing of Bigfoot has been seen on a real table (see `docs/live-checklist.md`).

## Summary
- Melee hero, 16 life, move 3. Sidekick **The Jackalope**: one, melee, 6 life, move 3 (fid `jackalope`). The hero card prints the move once (3) for both.
- Ability: **at the end of your turn, if there are no opposing fighters in Bigfoot's zone, you may draw 1 card.** An `end_of_turn` trigger of the interpreter (`bigfoot_draw`); the zone is the board's zone of the space Bigfoot stands on (`share_zone`), the same selector as Medusa's gaze. An opposing hero or sidekick in his zone switches it off; his own Jackalope does not, and only Bigfoot's zone counts, never the Jackalope's.
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176), restriction bands BIGFOOT, THE JACKALOPE and ANY. The deck object of the save holds 31 cards (the 30 plus the character card `309`).
- Table: Bigfoot's miniature `dc0472` and dial `de393d` (max 16); the Jackalope's token `b31c7a` (nickname "Jackalope", the dial is called "The Jackalope") and dial `18c384` (max 6).
- **He shares CardIDs 17600-17629 with Medusa, the four turtles and Doctor Strange**: his deck is told apart by deck image and owner (docs/card-identity.md), never by a bare CardID. `tests/test_bigfoot_matrix.py` plays him against every other hero in both seats.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Who | Effect |
|---|---|---|---|---|---|---|
| Larger Than Life | attack | 6 | 3 | 3 | Bigfoot | No text |
| Savagery | attack | 4 | 3 | 3 | Bigfoot | AFTER: if you won, 1 damage to each fighter adjacent to Bigfoot |
| Disengage | attack | 4 | 2 | 2 | any | AFTER: choose an empty space in this fighter's zone and place this fighter there (won or not) |
| Momentous Shift | versatile | 3 | 1 | 3 | any | DURING: if your fighter started this turn in a different space, the value is 5 |
| Skirmish | versatile | 4 | 1 | 3 | any | AFTER: if you won, choose one of the fighters in the combat and move them up to 2 spaces |
| Hoax | versatile | 4 | 2 | 3 | any | AFTER: move your fighter up to 5 spaces, through opposing fighters (won or not) |
| Regroup | versatile | 1 | 2 | 3 | any | AFTER: draw 1 card; 2 if you won |
| Feint | versatile | 2 | 2 | 3 | any | IMMEDIATELY: cancel all effects on the opponent's card |
| It's Just Your Imagination | defense | 3 | 3 | 2 | any | IMMEDIATELY: cancel all effects on the opponent's card |
| Crash Through the Trees | scheme | - | 3 | 2 | Bigfoot | Move Bigfoot up to 5 spaces, through opposing fighters |
| Jackalope Horns | scheme | - | 2 | 3 | The Jackalope | Move the Jackalope up to 5 spaces, through opposing fighters; then 2 damage to any one fighter adjacent to the Jackalope |

No engine concept is new for the cards: every one is written with ops that already existed (Skirmish is Houdini's Vanishing Act with 2 spaces and no passing through; Momentous Shift uses Shock And Awe's condition; Jackalope Horns has Party Wagon's shape).

## Discrepancies with unmatched-memory
None: type, value, boost, copies and text of the 11 titles agree with the images. The restriction bands come from the images (unmatched-memory has none).

## Collisions found in the save
- **CardIDs 17600-17629**: shared with Medusa, Leonardo, Donatello, Michelangelo, Raphael and Doctor Strange (and Black Panther, who has no data here). Solved as for Strange: `data/tts/bigfoot.json` carries its own `deck.identity` (face and back images) and every lookup is per owner; `tests/test_hero_bigfoot_data.py` pins that no card is equal to a card of another deck of the range and that the images differ, and the matrix proves it on FakeTTS. The bag of the catalog also lists 309 (character card) and 17629 as its `card_ids`: the same range.
- **GUID `18c384`**: the save gives The Jackalope's life dial (inside Bigfoot's bag) the same GUID as Lobster Johnson's life dial (inside Hellboy's bag). It is a dial, not a miniature, so `session_pieces` (which re-points miniatures and tokens by name) does not cover it. Consequence if both heroes are on the table: TTS gives the second dial it loads a new GUID and the configured one would read or write the other sidekick's dial. What is done: the collision is pinned in `tests/test_piece_identity.py` (`18c384: bigfoot + hellboy`), the start-up check `shared_guids` already warns about two dials with one GUID, the dial verification (`dials.warn`) reports a dial whose value differs from the engine, and `docs/live-checklist.md` asks to check it live. **Not fixed**: Hellboy against Bigfoot at a real table may need the Lobster / Jackalope dial set by hand (see the open questions).
- Bigfoot's miniature and dial have the same nickname "Bigfoot"; the importer tells them apart by `MAX_VALUE` (the dial). `de393d`, his dial, is also in the save under Muhammad Ali and Krang (heroes without data here).

## Rules decisions
1. **The ability is optional and asked only when it can apply.** The condition is checked when the turn ends; if it holds the owner decides, else nothing is asked. It happens before the hand limit is enforced (`Game.end_turn` emits the event first), so the drawn card may be the one discarded for the limit.
2. **Bot**: draws unless the deck is shorter than the draw (an empty deck hurts every own fighter: exhaustion) or the hand is already at its limit (the card would only be discarded). Generic rule for any free optional draw (`EffectAI._free_draw`, fed by `draws` in the request context); Hellboy's OCCULT DETECTIVE draw uses it too.
3. **Human**: Yes / No on the panel, hidden when the condition does not hold (nothing is asked); Yes: the bot deals the card ("You draw 1: do it on the table") and the hand count follows. The prompt is `choice.prompt.ability.bigfoot_draw`.
4. **"Each fighter adjacent to Bigfoot" (Savagery) and "any one fighter adjacent to the Jackalope" (Jackalope Horns) include the player's own fighters**, as Medusa's A Momentary Glance does (Iván, 28/10). The bot never hurts its own unless it must (the Horns' damage is mandatory when someone is adjacent).
5. **Jackalope Horns is played by the Jackalope.** The bot already chose the fighter of a scheme from the card's restriction (`scheme_fighter`); the human's scheme used to be run always as the hero's, which would have moved Bigfoot, so `session_effects.play_scheme` now asks `scheme_fighter` too (generic: a scheme restricted to a sidekick is that sidekick's).
6. **The human moves the Jackalope by hand and the damage hangs from where it ends.** The engine does not see a miniature the human moved: after the move the panel offers every other fighter, "None" included, and the human names who is next to the Jackalope (`select._anchor_unknown`; the same idea as Party Wagon's `passed_by`). The chat tells them to move the Jackalope by hand.
7. **Disengage** offers the spaces of the zone the engine finds empty; the fighter's own space is among the options (staying is a legal no-op). With nobody to choose it does nothing.
8. **Skirmish** moves one fighter of the combat, the owner's or the rival's, up to 2 spaces without passing through opposing fighters (the card does not say so). A fighter defeated in the combat is not there any more.
9. **Momentous Shift as a defense** compares with where the fighter stood when the rival's turn began (the turn-start positions the interpreter records at every start of turn). A defender moved by an effect during that turn counts as having started elsewhere only if it began that turn on another space.
10. **Regroup** draws 2 if you won (never 3) and 1 otherwise.

## Open questions for Iván
- **Savagery and the Jackalope**: "each fighter adjacent to Bigfoot" is read as including his own Jackalope when it stands next to him. If it should only hit opposing fighters, change the selector's `side` to `enemy`.
- **Jackalope Horns on your own Bigfoot**: allowed (the card says "any one fighter"). The damage is mandatory, so with only Bigfoot next to the Jackalope the bot must hit him; with anyone else it never does (same as Medusa's Glance).
- **Momentous Shift in defense**: read from the rival's turn start (a defender that did not move on its own turn but was pushed by an effect counts as "different"). Say if "started this turn" should mean only the owner's own turn.
- **The drawn card and the hand limit**: the ability draws before the hand limit is enforced, so with a full hand you can draw and then discard back to the limit (cycling a card). The bot refuses that; the human may do it.
- **Disengage's own space**: the engine lists the fighter's current space among the legal placements (a no-op). Harmless; say if the card should force a different space.
- **GUID 18c384 (Jackalope and Lobster dials)**: if Hellboy and Bigfoot are on the same table, one of the two sidekick dials gets a new GUID in TTS. Tell me what you see; the fix is a name-based dial resolution like the one miniatures have (`session_pieces`).

## AI
- The AI profile comes from the data (`ai_profile`, computed by the importer): Bigfoot `hero`; the Jackalope `striker` (a melee piece with 3 or more life) with Jackalope Horns as its exclusive card (impact 2.4: killing it early prevents up to three 2-damage schemes).
- No hero-name case in the AI code. Jackalope Horns and Crash Through the Trees are valued by simulating the scheme (`scheme_act`) with the right fighter; Savagery, Disengage, Hoax and Skirmish are priced by the generic after-combat evaluation; the end-of-turn draw by `EffectAI._free_draw`.
- Headless games with the heuristic and with ISMCTS against every other hero: `tests/test_bigfoot_matrix.py`.

## Tests
- `tests/test_hero_bigfoot_data.py`: overlay, generated HeroDef, effects, table data, the shared range and the GUID collision.
- `tests/test_bigfoot_effects.py`: every card and the ability, bot side.
- `tests/test_bigfoot_human.py`: the panel (Yes / No, hidden when the condition fails, moves by hand, the Jackalope's scheme).
- `tests/test_bigfoot_session.py`: the bot's draw, Jackalope Horns and Savagery on the fake table.
- `tests/test_bigfoot_matrix.py`: Bigfoot against each of the 11 other heroes in both seats (passive human, attacking human, heuristic and ISMCTS headless games).
