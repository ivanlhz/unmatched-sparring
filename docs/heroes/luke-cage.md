# Luke Cage (Marvel, Redemption Row)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 322 on sheet 3) on 2026-11-07. Verified on FakeTTS only: nothing of Luke Cage has been seen on a real table (see `docs/live-checklist.md`).

## Summary
- Melee hero, 13 life, move 2. Sidekick **Misty Knight**: one, ranged, 6 life, move 2 (fid `misty`). Hero fid `luke`. The hero card prints the move once (2) for both.
- Ability (two paragraphs on the card): **Luke Cage takes 2 less combat damage from attacks.** and **When defending, Luke Cage wins combat if he takes no damage even if he didn't play a card.** The first is the passive rule `combat_damage_reduction` (amount 2) of the interpreter; the second needs no data: the engine already names the winner by the damage that landed (a defender who takes none wins, with or without a card).
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176), restriction bands LUKE CAGE, MISTY KNIGHT and ANY. The deck object of the save holds 31 cards (the 30 plus the character card `322`).
- Table: Luke Cage's miniature `b56d0d` and dial `63d2ef` (max 13); Misty Knight's token `2b710e` and dial `d35f8c` (max 6). No piece GUID is shared with another hero.
- **He shares CardIDs 17600-17629 with Medusa, the four turtles, Doctor Strange and Bigfoot**: his deck is told apart by deck image and owner (docs/card-identity.md), never by a bare CardID. `tests/test_luke_cage_matrix.py` plays him against every other hero in both seats.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Who | Effect |
|---|---|---|---|---|---|---|
| Sweet Christmas! | attack | 6 | 1 | 2 | Luke | No text |
| Get Paid | attack | 4 | 2 | 2 | Luke | AFTER: if you won, draw 2 |
| Hero For Hire | attack | 3 | 1 | 3 | Luke | DURING: you may BOOST this attack |
| Commanding Impact | attack | 5 | 1 | 3 | any | AFTER: draw 1 |
| Still Standing | attack | 4 | 2 | 2 | any | AFTER: if you won, choose 2 cards in your discard pile and shuffle them into your deck |
| Regroup | versatile | 1 | 3 | 3 | any | AFTER: draw 1; 2 if you won |
| Pushback | versatile | 2 | 3 | 2 | Misty | AFTER: move the opposing fighter up to 3 spaces |
| Daughter of the Dragon | versatile | 2 | 2 | 2 | Misty | DURING: if Misty is adjacent to the opposing fighter, the value is 6 |
| Power Man | defense | 2 | 1 | 2 | Luke | AFTER: move the opposing fighter up to 3 spaces; 1 damage to them and to each other fighter of theirs they moved through |
| Skin Like Titanium | defense | 0 | 1 | 2 | Luke | AFTER: if you lost, damage to the opposing fighter equal to the combat damage you took |
| Trash Talk | defense | 2 | 1 | 3 | any | IMMEDIATELY: cancel all effects on the opponent's card. AFTER: if you won, end the turn |
| Got My Back? | defense | 1 | 2 | 2 | Misty | IMMEDIATELY: Misty may swap spaces with Luke; if she does, Luke is now the defender |
| Where's My Money? | scheme | - | 1 | 2 | Luke | Place Luke adjacent to the nearest opposing fighter; gain 1 action |

## Discrepancies with unmatched-memory
- **The ability has a second paragraph** on the card ("When defending, Luke Cage wins combat if he takes no damage even if he didn't play a card.") that unmatched-memory lacks. The HeroDef carries both (`ability` in the overlay).
- **Skin Like Titanium prints value 0**; unmatched-memory has `null` (the importer refuses a null value on anything but a scheme). The overlay carries `value: 0` in its two sheet entries, read by `tools/import_hero.py` (a printed `value` wins, like the printed `boost`).
- The restriction bands are not in unmatched-memory at all. Type, boost, copies and text of the 13 titles agree with the images.

## Collisions found in the save
- **CardIDs 17600-17629**: shared with Medusa, the turtles, Doctor Strange and Bigfoot. Solved as for them: `data/tts/luke-cage.json` carries its own `deck.identity` and every lookup is per owner; `tests/test_hero_luke_cage_data.py` pins that no card is equal to a card of another deck of the range and that the images differ.
- No piece GUID is shared with another hero (pinned in `tests/test_hero_luke_cage_data.py`).

## Rules decisions (the user is away: the most reasonable reading, applied)
Every item that is a real doubt is also an open question below.

1. **2 less combat damage** applies to Luke Cage himself (never Misty) and only to the combat damage of an attack on him, before it lands (never below 0). Effect damage, exhaustion and `set_hp` are not reduced. The blow that lands is what every later effect reads (Skin Like Titanium, the dial, who won).
2. **A defender who takes no damage wins** with or without a card: already the engine's rule (`attacker_won = damage >= 1`), so a blow of 2 or less against Luke is a win for him (Trash Talk then ends the turn).
3. **Power Man**: "them" is the opposing fighter of the combat (the attacker): it takes 1 damage even if the owner moves it 0 spaces. "Other opposing fighters" are the rival's other fighters, from Luke's side: the moved fighter's own team, which it may always cross; every such fighter on some path of at most 3 spaces from where it started to where it ended takes 1 damage as well (the owner picks the path, so the most generous one counts). Luke and Misty are never crossed.
4. **Got My Back?**: Misty plays it (she is the defender) and swaps spaces with Luke (alive). If she does, Luke becomes the defender of the same combat with Misty's card in play for him, in the space Misty had, **no range check**: the attacker's card is aimed at him from now on (his 2 less, the AFTER effects, the rival's AFTER effects on him). It is Houdini's Smoke and Mirrors machinery (`luke:replace_combatant`).
5. **Where's My Money?**: "nearest" is the board's span from Luke (as everywhere), with ties the owner may go next to any tied fighter; if he already stands next to the nearest one he may stay. The action is gained even if no space is free.
6. **Skin Like Titanium** returns the combat damage that really landed on him (after his 2 less) as effect damage on the opposing fighter, and only when he lost the combat.
7. **Still Standing** chooses exactly 2 cards from the discard pile when it holds 2 or more (fewer if fewer); the card just played is not in the pile yet. The cards are shuffled into the deck.
8. **Trash Talk** ends the turn in progress (the attacker's when defending): its remaining actions are lost; with an attack, the owner's own.
9. **Daughter of the Dragon**: Misty must be next to the opposing fighter (she is the only one who can play it); the printed value becomes 6 (bonuses stay). It is a versatile card: Misty defending next to the attacker defends with 6.
10. **Pushback** moves the opposing fighter whether or not the combat was won (as printed); not through other fighters.

## Open questions for Iván
- **Power Man, who is "moved through"**: I read "other opposing fighters" as the rival's other fighters (the moved fighter's own team), the only ones a fighter can always cross, and damage every one that could lie on some path of at most 3 spaces. If you meant Luke's own fighters (or only the ones the path really crosses), say so.
- **Power Man, the damage "to them"**: read as unconditional (also when the opposing fighter is not moved at all).
- **Got My Back?, range**: no range check on the new defender (Houdini's precedent). A ranged attacker aimed at Misty can end up hitting Luke from where he could not shoot; a melee attacker next to Misty may not be next to Luke after the swap.
- **Where's My Money?, "nearest"**: spatial distance from Luke, not the movement distance; ties choose freely.
- **Trash Talk**: "end the turn" read as ending the rival's turn when Luke defends (its unused actions are lost).
- **Skin Like Titanium** read as "the damage that actually landed" (after the 2 less), not the blow before the reduction.
- **The second ability paragraph** ("wins combat if he takes no damage even if he didn't play a card") needs no code because the engine never required a card to win a combat; check that this is also how the real rules treat a defender who plays no card against a blow of 0 damage.

## AI
- The AI profile comes from the data (Luke `hero`, Misty `striker`; exclusive cards: Pushback, Daughter of the Dragon and Got My Back? for Misty).
- `Game.combat_damage_taken` is the one place the ability is read: the bot's estimates of damage to Luke (attack outcome and probability of winning, defense evaluation, two-hit threat, combat boost, the search's boost) go through it, so it attacks a Luke it knows will take 2 less accordingly, and Luke's bot defends and swings knowing it.
- Card hints in `ai_medusa`: draws (Get Paid, Commanding Impact; Regroup already), Still Standing's refill, Pushback and Power Man's movement, Trash Talk's end of turn on a win (and its cancel, already counted by the data), Daughter of the Dragon worth 6 next to the target (attacking and defending), Skin Like Titanium's return damage, and Got My Back? priced as the cheaper of Misty or Luke taking the blow (the optional swap itself is `EffectAI._swap_combatant`, which counts the 2 less).
- Where's My Money? and the movements are valued by simulating them like the other heroes' schemes.

## Human side
- Buttons appear only when the card is played (never greyed): the Got My Back? Yes / No, the card choices of Still Standing, the space choices of Pushback and Power Man for the bot's piece (you move it by hand and press Done), the placement of Where's My Money? (a chat instruction: your own miniature, by hand). Every choice is a parked run saved with the game and survives `--resume` (`tests/test_luke_cage_human.py`).
- The chat says what the ability took off (`luke recibe 2 de dano de combate menos`) and the dials follow the damage that landed.

## Tests
`tests/test_hero_luke_cage_data.py` (data, card identity, detection), `tests/test_luke_cage_effects.py` (the ability and every card on the interpreter), `tests/test_luke_cage_human.py` (FakeTTS panel: Power Man, Got My Back?, Where's My Money?, Still Standing and a resume, the ability on the dial), `tests/test_luke_cage_matrix.py` (full games against the twelve other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
