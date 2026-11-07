# Donatello (TMNT, "Adventures: Teenage Mutant Ninja Turtles")

Data, effects and table support on both sides (feature F20-donatello). Verified against FakeTTS only: nothing of this has been seen on a real table (docs/live-checklist.md, "Donatello").

## Summary
- Melee hero, 14 life, MOVE 2. Sidekick Metalhead: melee, 7 life, MOVE 2. The set is co-op ("each other friendly player"); in 1v1 that phrase matches nobody.
- Deck: sheet 176 of the tournament save (8x4), `CardID = 17600 + idx`, 30 cards (31 in the physical deck with the character card, CardID 364 on sheet 3). **Medusa and every other TMNT deck use the same 17600-17629**: only the deck image (FaceURL, BackURL in `data/tts/donatello.json`) tells them apart. Consequences: `combat.is_medusa_card` compares the card with Medusa's own cards instead of reading the id range, `table_defaults` accepts overlapping ranges when the images differ, and a mirror of ids between Donatello and Medusa is fine because every pile of the engine is per player.
- Ability INVENTIVE: (a) when you maneuver you may draw 2 instead of 1 and then put a card of your hand on the bottom of your deck; (b) after you play an invention, tuck it under the hero card: its invention bonus applies for the rest of the game.

## Cards as implemented (read card by card from the image)

| Card | Copies | Type | Value | Boost | Restriction | Effect |
|---|---|---|---|---|---|---|
| Turtle power! | 2 | attack | 3 | 3 | any | You may BOOST this card (free boost from the hand). |
| Thinking ahead | 3 | attack | 3 | 2 | any | AFTER: if you won, you may put a card of your discard pile at the bottom of your deck. |
| Shift focus | 3 | versatile | 2 | 2 | Donatello | AFTER: move another fighter in Donatello's zone up to 3 spaces, through other fighters. |
| Short circuit | 3 | versatile | 3 | 2 | any | IMMEDIATELY: cancel the AFTER COMBAT effects of the opposing card (only that moment). |
| Quick strike | 3 | versatile | 3 | 1 | any | AFTER: draw 1. |
| Untested enhancements | 3 | versatile | 3 | 2 | Metalhead | DURING: discard the bottom card of your deck, add its BOOST to this card's value. |
| Heroes in a half shell | 2 | defense | 5 | 1 | Donatello | No effect. |
| Bo staff | 2 | defense | 3 | 2 | Donatello | AFTER: 1 damage to an opposing fighter adjacent to Donatello; draw 1. |
| Donatello does machines | 2 | scheme | - | 3 | Donatello | You may return an attack, versatile or defense card from your discard pile to your hand; draw 1. |
| Party wagon! | 2 | scheme | - | 2 | Donatello | Move a friendly fighter up to 5 spaces through opposing fighters; then 2 damage to an opposing fighter it moved through. |
| The future of Ninjutsu | 2 | scheme | - | 1 | Metalhead | Look at the top card of ANY deck (yours or the rival's), you may put it at the bottom; draw 1; gain 1 action. |
| Electro grenade (invention) | 1 | attack | 2 | 3 | Donatello | DURING: remove up to 4 attack or versatile cards of your discard pile from the game, +1 value each. Bonus: +1 to your attacks. |
| Self defense grid (invention) | 1 | defense | 2 | 3 | Donatello | AFTER: remove up to 4 defense or versatile cards of your discard pile from the game, Donatello heals that much. Bonus: +1 to your defenses. |
| Smoke bomb (invention) | 1 | scheme | - | 3 | Donatello | Remove up to 4 scheme cards of your discard pile from the game, gain that many actions. Bonus: when you play a scheme, gain 1 action. |

## Files
- `data/heroes/overlay/donatello.json` (sheet, restrictions, texts of the real cards, `invention` tag), `data/heroes/donatello.json` (generated), `data/heroes/effects/donatello.json` (ops, the `inventive` trigger, the `invention` blocks), `data/tts/donatello.json` (read from the save).
- Tests: `tests/test_hero_donatello_data.py` (data), `tests/test_donatello_effects.py` (every effect on the engine), `tests/test_donatello_ai.py`, `tests/test_donatello_session.py` (bot and human at the table, tucks, removals, INVENTIVE, resume) and `tests/test_donatello_games.py` (whole FakeTTS games against the five other heroes on either side) and, for The future of Ninjutsu on any deck, `tests/test_donatello_future.py` (engine and the bot's judgement), `tests/test_donatello_future_lua.py` (the three table builders on the Lua stub) and `tests/test_donatello_future_session.py` (both seats at the table).

## Discrepancies with unmatched-memory (the real card wins)
- Shift focus says "other fighters" (memory: "oothe"); Self defense grid says "discard pile" (memory: "descard"); Short circuit says "Cancel all AFTER COMBAT effects" (memory repeats "effects").
- The inventions' bonus is a separate purple band at the bottom of the card; memory writes "PERMANENT." in front of it. The hero card only says "After you play an invention, tuck it under this card.": that is the printed ability text of the HeroDef.
- Multi-paragraph texts (Bo staff, Donatello does machines, Party wagon!, The future of Ninjutsu) are joined in one line.
- No fighter restrictions in memory: they come from the banner of each card.

## Decisions
1. **Tucked and removed cards** live in `PlayerState.tucked` / `PlayerState.removed` (saved only when non-empty). They are in no pile, public, and `PlayerState.gone` (discard + tucked + removed) is what the rival's unseen pool, `Model` and the search leave out. The bonus is read from the card's `invention` block, never copied.
2. **When is an invention tucked?** After the combat (or the scheme) in which it was played, whether or not its effects were cancelled; a played card boosted or discarded for another reason is discarded normally. The new bonus does not help the combat or scheme that tucks it ("after you play").
3. **"Your attacks / your defenses"** in an invention bonus means a card played as an attack / as a defense, a versatile card included. Short circuit and the other cancels do not touch it (it is not an effect of a card).
4. **INVENTIVE (a)** is the trigger `inventive` on `after_maneuver`: draw one more card and put a card of the hand at the bottom. The end state is the same as "draw 2, put 1 at the bottom"; the only difference is that the extra card cannot be the maneuver's boost card. It is not offered with an empty deck (the extra draw would exhaust you). The bot always takes it and buries its least valuable card (inventions are never buried); the human is asked on the panel, the card to the bottom is theirs to move.
5. **Party wagon! "moved through"**: an opposing fighter on some path of at most 5 spaces from where the mover started to where it ended. When the human walks their own miniature the engine cannot see the path: the panel lists the opposing fighters plus the none button (press it if you passed nobody) and the 2 damage is not optional once you name one. With the bot's move the engine knows who was passed: the damage is automatic, and you only pick which rival when it passed several. The bot's destination is chosen by its usual movement rules, so it only hits when the best square also passes a rival (it does not plan the wagon for the damage).
6. **Co-op phrases** (`each other friendly player`): ignored in 1v1; the owner is the only one who returns a card.
7. **The future of Ninjutsu, "any deck"** (CONFIRMED by Ivan 2026-11-07, rules video; it replaces the old reading "the owner's own deck"). Whoever plays it chooses the deck, theirs or the rival's, and then the printed text: look at the top card, you may put it at the bottom, draw 1, gain 1 action. The engine part is the plugin `donatello:future_of_ninjutsu` (`sparring/effects/plugins_donatello.py`); the card's `if` runs the old own-deck flow when the own deck is the one looked at.
   - **The human plays it.** The panel shows two buttons, "Your deck" / "The bot's deck" (only while the card is being played; never greyed). Own deck: the old flow. The bot's deck: the game pauses and the bot takes its ENGINE top card out of its physical deck by CardID and deck image (`lua.deck_card_to_spot`; the table's order is not the engine's, so the physical top card is not it), lays it face up at `bot_row_spot` (the row of Painful Memory / Advanced Psychometry / Every Possible Angle), pings it and names it in the chat. The human looks and presses "Leave on top" or "Put on bottom": that button is the continue. The bot puts the card back on top or at the bottom of its physical deck (`card_to_deck_top` / `_bottom`) and the engine's deck follows (`Session.peek_pins`: a card left on top stays the engine's top card and one put at the bottom its last through every reread of the bot's hand, until the bot draws it). The row is saved (`Session.peek`), so `--resume` says it again; Cancel is refused (the card is already played).
   - **The bot plays it.** It chooses the deck with `EffectAI._future_deck` BEFORE it can know the rival's card: its own deck when its own top card is worth less than the average card still to come (burying it is a sure gain), otherwise the human's (to take the best card out of their reach). The human's deck is read from the table (`Game.deck_reader` -> `lua.peek_deck_top`, identity by CardID and deck image, one extra message like `look_hand`); a clone, a missing deck GUID or an unreadable table is a failed read and the bot uses its own deck (the chat says so). It then puts the card at the bottom when it is worth more than the average card the human still holds (`EffectAI._future_peek`, `card_worth`), and moves it itself (`lua.deck_top_to_bottom`, only if the top card is still the one it read, in the step's one combined script). The chat says only that the bot looked at the top card of the human's deck and whether it left it or put it at the bottom: the card is not public and is never named. The bot remembers the card only as the known top of their deck (`KnownHand.top_of_deck`) while it is legitimately known; their next draw erases it, and putting it at the bottom clears it.
8. **Removed from the game**: from the discard pile only (as printed). The cards cannot come back through Thinking ahead or Donatello does machines. The bot removes as many as allowed, the cheapest first (a card value of +1 each is worth more than the card itself in the discard).
9. **Bot AI hints** (`ai_medusa`): `INVENTION_KEEP` makes inventions the last cards it gives up, `INVENTION_PLAY` makes playing one worth more, Electro grenade and Untested enhancements count their DURING gain, Turtle power! counts its free boost like Second Shot, and `ongoing.worth` counts tucked inventions for the search.

## Confirmed by Iván
- **2026-11-07, rules video**: The future of Ninjutsu can target ANY deck, the rival's included, and the human may look at the bot's deck (Decision 7; this closes the old open question about it).
- **2026-11-07 (no code change)**: "Shell Insertion" is not a Donatello card (it is April O'Neil's, Michelangelo's set): ignore it here. Decision 2 (a tucked invention does not help the combat or scheme that tucks it) stays as the reading, still not confirmed by video.

## Open questions for Iván
- Does a tucked invention help in the combat or scheme that tucks it? (Decision 2: no; the video did not settle it.)
- Which path counts as "moved through" when the mover could have walked several? (Decision 5: any path within the move.)
- Is the extra INVENTIVE draw allowed with exactly one card left in the deck? (Yes: it only exhausts at the next draw.)
- The card played as a boost for the maneuver may not be an invention of the same hand turn? (Not restricted: only "playing" tucks.)

## Engine and shared-file changes (for the merge)
See the section "Donatello" of docs/effects-dsl.md.

## Live-only risks
`bot_tuck_spot` and `bot_removed_spot` are estimates (outside the discard and combat zones); `discard_cards` to those spots has only run on the fake table; the human's tucked and removed cards stay on their pile until they move them (the sync ignores them, a reminder is in the chat); INVENTIVE's panel prompt is shown on the status line (ASCII only); the same CardIDs as Medusa and the other turtles are handled by docs/card-identity.md (every lookup is per owner, every table write and search filters by the deck image); live-only: two turtle decks in the same combat zone. The future of Ninjutsu on any deck has only run against FakeTTS and the Lua stub: `deck_card_to_spot` (a card taken out of the middle of a Deck with `takeObject({guid=...})`), `peek_deck_top` (the first of `ContainedObjects` is read as the top card, the one `takeObject()` gives), `deck_top_to_bottom` (a 2-card deck turns into a loose Card when its top is taken: the rest is then found by position, never run live; a mismatch between the card read and the card taken puts it back on top and nothing moves), `card_home` (the bot's lone last card shown in the row goes back face down to the deck's spot, stub only) and the `bot_row_spot` row are unseen on a real table; the human's deck is read just before the move, so a draw queued in the same step can make the bot refuse the move (it then tells you to do it); a shuffle effect on the bot's own deck is not forgotten by `peek_pins` (the pin stays until the card is drawn).
