# Hellboy (Hellboy + Lobster Johnson)

Data and specification so the bot can play Hellboy (F07, Hellboy box). Done on 2026-10-28 on the `data/hellboy` branch, data only: neither `sparring/` nor `features.json` change.

## Files
- `data/heroes/overlay/hellboy.json`: verified CardID sheet (it already existed; it is verified, not redone).
- `data/heroes/hellboy.json`: HeroDef regenerated with `tools/import_hero.py hellboy`; `--all --check` passes.
- `data/heroes/effects/hellboy.json`: ability, 13 cards with ops, extended primitives, 1 plugin, hidden information, table objects and open questions.
- `tests/test_hero_hellboy_data.py`: 6 tests without FakeTTS or sockets.

## The hero in two lines
Hellboy, 18 HP, movement 2, melee; Lobster Johnson, 6 HP, movement 2, ranged, 1 miniature that starts on the board (nothing in reserve). Deck of 30 with 11 destiny cards (crown). The form is not a state: with 5 or fewer destinies in the discard it is OCCULT DETECTIVE (if the turn starts on the rival start space, he may draw 2), with 6 or more it is ANUNG UN RAMA (at turn start he discards 1 and moves Hellboy up to the BOOST of the discarded one; +2 to Hellboy's attacks).

## Sheet verification (card by card)
Source: FaceURL of CustomDeck 197 of deck `00dc9a` of the tournament save (the 30 loose cards carry key 187 with the same images; 19600 is the character card, CustomDeck 196). The 30 positions of the 8x4 sheet match the overlay in title, printed copies (x1, x4, x1, x3, x2, x2, x3, x3, x2, x3, x2, x2, x2), value, boost, type, fighter and destiny crown. Total 30; destinies 11 (Excalibur 1, Right Hand of Doom 4, Confront 2, On Earth 2, Crown of Flame 2). Pancakes! is NOT destiny.

## Discrepancies (the real card wins)
Text only; none changes values or copies:
- Second Shot: the card says "You may BOOST this card"; unmatched-memory, "this attack".
- Confront Any Demon or God: "choose a card for them to discard"; unmatched-memory, "choose 1 card" (and a surplus leading space in `effectAfter`).
- Pancakes!: "Choose two different effects"; unmatched-memory, "Chose".
- unmatched-memory has neither fighter restrictions nor the destiny tag (already known): they come from the sheet.
unmatched-memory is not corrected (read only) and, on purpose, the text is not overwritten in the HeroDef either: the importer accepts `"text"` in an entry of the overlay sheet (convention of the data/liz-sherman branch: `"text": entry.get("text") or card_text(src)`), but using it here would change the golden deck of `tests/golden/decks.json` (it compares `text`) and would break `combat.can_boost`, which recognizes Second Shot by "boost this attack". When the DSL replaces those shortcuts, the three wordings are corrected with that same `text` key without touching anything else.

## Decisions
1. No new ops. Everything fits the common vocabulary and two argument conventions declared in `primitives_needed`: `bind`/`ref` (Second Shot adds the boost of the discarded card; ANUNG UN RAMA moves up to the boost of the discarded one; On Earth sets its value to the destiny counter) and `options` with `label` in `choose_n` (Posthumous Power chooses 1 of 3, Pancakes! 2 different of 3).
2. `move` with `amount` is always "up to N" (0 included), as in the rulebook; there are no mandatory moves in Hellboy.
3. Damage carries `source: effect|combat` so that Planned Recklessness' shield (`status immune_to_effect_damage` until the end of the current turn) stops only effect damage. That is what `Game.effect_shield` already does.
4. Forms are not "set": they are queried with the `form_is` condition. The engine recomputes them from the discard; Pancakes! can lower the counter and return Hellboy to OCCULT DETECTIVE (a form lever, not just recycling).
5. The only plugin, `hellboy:form_change_on_table`, is not a rule: it is the table choreography when the bot plays Hellboy and crosses the threshold (Ivan's rule: it changes the miniature itself, turns the token to the red side and pings both).
6. `start_on_board`/`reserve` are added to the sidekick in the overlay; the importer propagates the keys and `parse_hero` ignores them, so the engine does not change.

## Save objects for the form change
All inside the bag `3efeee` "Hellboy" > bag `c592d8`:
- Ability token: `1644a3` (Custom_Token, scale 0.5) with a child `30d50e` glued face to face. Face of `1644a3` = ANUNG UN RAMA (red); face of `30d50e` = OCCULT DETECTIVE (blue). Turning `1644a3` changes the visible face. In the save it has rotZ 180, which by the child's geometry leaves the blue face (start) up: rotZ 180 = blue, rotZ 0 = red. Confirm live.
- Hellboy's miniature: `f9789a` ("Hellboy", OCCULT DETECTIVE) with `States {2: e6f06e}` ("Anung Un Rama"). `setState(2)` turns `f9789a` into `e6f06e` at the same position; `setState(1)` turns it back. `config/table.json` (formerly `table.json`) already lists both GUIDs in `pieces.hellboy`.
- Lobster Johnson: `e33604` (Custom_Token). Dials: `046660` Hellboy (18), `18c384` Lobster (6), `e17c66` Destiny Dial (the bot already adjusts it).
- Proposed sequence: announce, setState of the miniature, flip the token only if it does not already show the new face (look at rotZ), ping the token and ~1 s later the miniature (two pings in a row step on each other; `lua._ping_lua` already waits 1 s), destiny dial. All in `pcall`.

## Hidden information (Ivan's rule)
- Confront Any Demon or God is the only Hellboy card that looks at the rival's hand. The bot reads it ONLY when resolving that AFTER after losing the combat, chooses the card to discard, keeps the rest as KnownHand and discounts it as the human plays, discards or returns cards to the deck; what it draws afterwards is unknown. If the human plays it and loses, the bot reveals its hand and the human chooses with buttons.
- Glimpse Of Hell played by the human: a seen card may have gone back to the deck face down, so the seen ones degrade to "possible", not certainty.
- Crown of Flame played by the human: empty KnownHand + 2 unknown. Pancakes!: the cards returned to the bottom of the deck are public for both.

## Coverage
13/13 titles (30/30 cards) with an entry: 11 titles with ops (28 cards), 2 with no text and no ops (Excalibur, Service Pistol). 0 cards with a plugin. Whole ability with ops (2 triggers + 1 passive). Vocabulary used: draw, discard, move, damage, heal, if, optional, for_each, choose_n, modify_value, status, cancel_effects, look_hand, return_to_deck, gain_action.

## Ivan's decisions (28/10)

- Right Hand Of Doom: OCCULT DETECTIVE is evaluated before the card itself reaches the discard.
- Pancakes!: the chosen options resolve in printed order.
- form change with the bot: it changes miniature and token and pings both.
- the human's choices (Confront, Posthumous Power, Pancakes!) by panel buttons that ONLY appear when the card is played; meanwhile they are not shown (not even greyed out).
- Confront played by the human and lost (confirmed, E3): the bot lays its hand face up in the look_spot row and pings; the human chooses with a ping (Tab) on the card or with its panel button (the buttons carry the titles of the bot's cards). Only if it lost: the engine evaluates the condition when resolving the card.
- (29/10, E2) The human's start-of-turn ability (OCCULT DETECTIVE's draw on the rival start space, ANUNG UN RAMA's discard and move): the human does it on the table; the panel announces it and BLOCKS the other buttons (only End action and the HP ones) until they press End action; it resumes from a save.
- (29/10, E2) Own ONGOING zone below the combat zone (`human_ongoing_spot` / `bot_ongoing_spot`): the human leaves their ONGOING scheme there and the session recognizes it there; when it expires the chat asks to move it to the discard. The bot puts its own face up there and sends it to its discard when it expires. Without those values in the configuration it is recognized in the discard (with a warning).
- (29/10, E2) And Upon His Brow Is Set A Crown Of Flame: End action waits for the hand discards to be on the pile (confirmed).

## Open questions

- Ability token 1644a3: the reading 'rotZ 180 = OCCULT DETECTIVE up' comes from the child 30d50e (blue face) being glued turned 180 degrees; confirm live with --read-only before the bot turns it by itself.

## Evidence
```
.venv\Scripts\python tools\import_hero.py hellboy          -> written
.venv\Scripts\python tools\import_hero.py --all --check    -> 0
.venv\Scripts\python -m pytest tests\test_hero_hellboy_data.py tests\test_heroes.py -q   -> 16 passed
```
Control mutation: with an op outside the vocabulary and a changed copy in the effects file, the test fails (`assert 3 == 4` in Right Hand Of Doom; unknown op in the vocabulary test).
