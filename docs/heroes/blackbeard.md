# Blackbeard (Battle of Legends, Volume Three)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 2 of the tournament savegame, the hero card 362 on sheet 3) on 2026-11-22. Rulings: Ivan 2026-11-22 (`RULINGS-batch4`: BB1, BB2) and the readings of `REGLAS-PENDIENTES-batch4` section 2.

## Summary
- Ranged hero, 13 life, move 2, **two Sea Dogs** (melee, 1 life, move 2) that are on the board from the start. Hero fid `blackbeard`, sidekick group `seadog` (`seadog1`, `seadog2`), slug `blackbeard`.
- Ability (PRIVATEER TURNED PIRATE): three doubloons in all, he starts with 2 and the Treasury with 1. At the start of his turn he MAY pay 1 doubloon (to the Treasury) for 1 action. When BLACKBEARD (not a Sea Dog) takes combat damage he pays 1 doubloon to the Treasury.
- RANSOM: the cards say "unless N doubloons" at the end of an effect line. Any opponent may pay N doubloons FROM THE TREASURY (they go to Blackbeard) to ignore that one line.
- Deck: 30 cards, `CardID = 200 + idx` (a sheet of its own, key 2; the deck object holds 32 cards: the 30, the loose rules card 500 and the hero card 362). Order on the sheet: A Brace of Primed Pistols 0-1, Avast Ye! 2-3, Give No Quarter 4-6, Light the Fuse 7-9, Queen Anne's Revenge 10-11, Fearsome and Calculating 12-14, Show a Leg! 15-16, No Prey, No Pay 17-19, Parley 20-22, Intimidating Visage 23-24, Plunder 25-27, Scourge of the Seven Seas 28-29. Bands read from the card backs: BLACKBEARD (Brace, Avast Ye!, Queen Anne's Revenge, Fearsome and Calculating, Intimidating Visage, Plunder, Scourge), SEA DOG (Light the Fuse), ANY (Give No Quarter, Show a Leg!, No Prey, No Pay, Parley).
- Table: bag `af6cfa` (inner `541533`), miniature `8841d2`, life dial `81e2ff` (max 13), deck `2bfd21`, the Sea Dog tokens `e815fe` ("Hands") and `265d90` ("Caesar"), the Treasury tile `442da0` and the doubloon stack `a3b09d` (3 tokens in one stack).

## How the doubloons are kept
Two counters of Blackbeard's player (`ability.counters` of `data/heroes/effects/blackbeard.json`): `doubloons` (the ones he holds, start 2) and `treasury` (start 1). They always add up to 3; every move of a doubloon is a pair of `counter` ops (one up, one down), so the total cannot drift (`test_the_three_doubloons_always_add_up_to_three...`). The engine is the truth: the table has the Treasury tile and the doubloon stack, but the session does not read coins back from the table (see "Table" below).

## Ransom (BB1, Ivan 2026-11-22)
A ransom is an `optional` op whose `chooser` is the OPPONENT, whose `cost` moves N doubloons from `treasury` to `doubloons` and whose `else` is the effect line:
- Paying ignores THAT line only (the optional's own branch does nothing). It does not cancel the card, so it works against an uncancelable card.
- The option exists only when the Treasury holds N (`plugins_blackbeard.can_pay`, asked by `ops_core._can_pay`): with fewer, the line simply happens.
- It is decided AFTER the target or the random card is known: A Brace of Primed Pistols picks its victim first (`for_each` over the chosen fighter, then the ransom), Fearsome and Calculating `choose`s the card first, Avast Ye! draws the random card first (`blackbeard:random_discard`: for the table player the engine names a position of their hand and they lay that card on their discard pile if they do not pay).
- Each line is its own ransom, decided when it resolves: Scourge of the Seven Seas has three, so the Treasury may have run out for the later ones; Avast Ye! has two (the discard and the damage).
- Queen Anne's Revenge (`blackbeard:queens_revenge`): the opponent pays any number from 0 to the Treasury's stock, 2 off the card's value each (never below 0). It is a payment, so it also works on an uncancelable card.

## Cards (as implemented)
1. **A Brace of Primed Pistols** (attack 2 / 2, BLACKBEARD): AFTER, 3 damage to an opposing fighter in Blackbeard's zone unless 2 doubloons. The owner chooses the fighter, then the ransom.
2. **Avast Ye!** (attack 5 / 3, BLACKBEARD): IMMEDIATELY the opponent discards 1 random card unless 1 doubloon; AFTER 1 damage to each opposing fighter in Blackbeard's zone unless 1 doubloon.
3. **Give No Quarter** (attack 3 / 1, ANY): DURING its value is 5 instead if another friendly fighter is adjacent to the opposing fighter (`other` leaves out the fighter that plays it); AFTER gain 1 action unless 1 doubloon.
4. **Light the Fuse** (attack 2 / 3, SEA DOG): AFTER move your fighter up to 2 spaces, then 1 damage to each fighter adjacent to them (friends included, Blackbeard too).
5. **Queen Anne's Revenge** (versatile 7 / 3, BLACKBEARD): `uncancelable`; DURING the opponent pays 0..Treasury, -2 per doubloon.
6. **Fearsome and Calculating** (versatile 3 / 1, BLACKBEARD): IMMEDIATELY look at the opponent's hand and choose 1 card for them to discard unless 1 doubloon.
7. **Show a Leg!** (versatile 2 / 2, ANY): AFTER summon a Sea Dog in Blackbeard's zone.
8. **No Prey, No Pay** (versatile 2 / 2, ANY): `may_boost`; AFTER if you won the combat, draw 1 card.
9. **Parley** (versatile 3 / 2, ANY): IMMEDIATELY cancel all effects on the opponent's card unless 2 doubloons.
10. **Intimidating Visage** (defense 4 / 1, BLACKBEARD): AFTER if Blackbeard is adjacent to an opposing fighter he recovers 2 health.
11. **Plunder** (scheme, boost 2, BLACKBEARD): move each of your fighters up to 3 spaces, through opposing fighters; steal 1 doubloon from the Treasury (nothing with it empty).
12. **Scourge of the Seven Seas** (scheme, boost 2, BLACKBEARD): Blackbeard recovers 2 health unless 1 doubloon; summon a Sea Dog in any space unless 1 doubloon; gain 1 action unless 1 doubloon.

## "Summon a Sea Dog" (BB2, Ivan 2026-11-22)
The Sea Dogs start on the board like any sidekick, so the engine's `summon` (a fighter never placed, from the reserve: Sun Wukong's Clones) does not apply. "Summon a Sea Dog" is: a DEFEATED Sea Dog returns (`revive`, 1 health) into an empty space of the named place (Blackbeard's zone for Show a Leg!, any space for Scourge); if none is defeated, Blackbeard's owner MAY reposition one of the Sea Dogs on the board (`optional` + `place`, into that same place). With no empty space in the zone nothing happens and the card's line says so (`narr.notice.seadog_no_space`).

## Discrepancies with unmatched-memory
- The card texts: unmatched-memory draws a doubloon as a coin glyph ("unless 🪙 🪙"); the cards say it with that symbol. The HeroDef spells it out ("unless 2 doubloons"; `text` in the overlay).
- Restrictions: unmatched-memory has none; the card backs say BLACKBEARD / SEA DOG / ANY (above). Light the Fuse can only be played by a Sea Dog.
- Titles are spelled as printed ("A Brace of Primed Pistols", "Avast Ye!"), memory writes them in sentence case (`memory_title`). The sidekick is "Seadog" in memory and SEA DOGS on the card; the HeroDef says "Sea Dog".
- Everything else (values, boosts, copies, 30 cards, 13 health, move 2) agrees with the images.

## Pending Ivan
(none yet; see the end of the page for what the final report lists)
