# Michelangelo (Teenage Mutant Ninja Turtles)

Set "Adventures: Teenage Mutant Ninja Turtles". Data, effects, table data and engine support; played by the bot and by the human.

## Summary
- Melee, 14 life, moves 3. Sidekick April O'Neil: ranged, 6 life, one standee (fid `april`; hero fid `mikey`).
- Deck: sheet 176 of the tournament save (8x4), `CardID = 17600 + idx`; character card 366 (sheet 3). 30 cards: 16 band MICHELANGELO, 5 band APRIL, 9 ANY.
- Ability PIZZA PARTY: after you attack or scheme, draw 1 card; starting and maximum hand size is 3.

## Cards (read from the images, 2026-11-01)
| Card | Copies | Type | Value | Boost | Restriction | Effect |
|---|---|---|---|---|---|---|
| Hi-Yaaaaah!! | 3 | attack | 4 | 3 | Michelangelo | After: 1 damage to an adjacent opposing fighter; may put a hand card on the bottom of the deck to gain 1 action |
| Boisterous Beatdown | 3 | attack | 2 | 1 | Michelangelo | After: gain 1 action, 2 if you won |
| Turtle Power!! | 2 | attack | 3 | 3 | Michelangelo | You may BOOST this attack |
| Hard-Hitting Investigation | 3 | attack | 0 | 3 | April | After: 1 damage to the opposing fighter, gain 1 action |
| Cowabunga!! | 3 | versatile | 3 | 2 | Michelangelo | During: +1 for each other card you played this turn |
| Let's Go!! | 3 | versatile | 3 | 2 | any | After: move a friendly fighter up to 3 |
| Guaranteed Delivery | 3 | versatile | 3 | 1 | any | Immediately: may put a hand card at the bottom to cancel the rival card's effects. After: hand empty, draw 2 |
| Heroes In A Half Shell | 2 | defense | 5 | 2 | Michelangelo | none |
| Back For Seconds | 2 | defense | 2 | 1 | any | After: shuffle 2 random discards into the deck |
| Nunchaku | 2 | scheme | - | 2 | Michelangelo | +1 to Michelangelo's attacks this turn; gain 1 action |
| Michelangelo Is A Party Dude!! | 2 | scheme | - | 2 | Michelangelo | Each friendly fighter recovers 1 |
| Shell Insertion | 2 | scheme | - | 3 | April | Choose two different of four: rival discards 1; move a friendly fighter up to 2; hand card to bottom for 1 action; shuffle 2 random discards |

## Discrepancies with unmatched-memory (the card wins)
- Nunchaku: unmatched-memory has Bruce Lee's text; the card says Michelangelo's attacks.
- Titles are spelled as printed (Hi-Yaaaaah!!, Turtle Power!!, Let's Go!!, ...); the overlay links them with `memory_title`.
- Hard-Hitting Investigation and Shell Insertion carry the APRIL band: Michelangelo cannot play them. Memory has no restriction.
- The copies in memory add up to 30; the catalog's 31 is the deck plus the character card.
- The card shows no movement for April; memory says 3.

## Engine and design decisions
1. **Hand size** is data (`hand` in the overlay, `HeroDef.hand_start/hand_max`, `Game.start_hand/hand_cap`), default 5 and 7. Used by the deal, the mulligan, the end-of-turn limit (bot and human), the bot's evaluation and the search.
2. **PIZZA PARTY** is two ability triggers on events: `after_attack` (emitted when the combat reaches DONE, with the cards already in the discard) and `after_scheme` (when the scheme is finished). Any fighter of the player counts. The human's draw is dealt by the existing owed-draw path.
3. **Cowabunga!!** uses the stat `other_cards_played_this_turn`; the engine counts plays (attack, defense, scheme) per player per turn only when a loaded hero's data names it.
4. **Nunchaku** is the fighter status `attack_bonus` until the end of the turn (not an ONGOING: it stays out of the ONGOING slot).
5. **Shell Insertion** uses `choose_effect` with `distinct`; the human picks with the panel, the bot simulates each option.
6. The bot pays a card from its hand for an action (Hi-Yaaaaah!!) while another card that can use the action stays in hand, and for Guaranteed Delivery's cancel when the card it gives up is below average and the rival's card has effects (`EffectAI._card_from_hand_pays`).
7. **CardID collision**: Michelangelo and Medusa both use 17600..17629 in the tournament save; they are told apart by deck image and by owner (docs/card-identity.md). Medusa vs Michelangelo works at the table in both seats.

## Adventures wording in 1 versus 1
"Each opponent" is the one rival; "each friendly fighter" is Michelangelo and April.

## Open questions for Ivan
- Does "after you attack" include April's attacks? Assumed yes.
- Cowabunga!!: do defenses on the rival's turn count as "cards you played this turn"? Assumed yes, current turn only.
- Hi-Yaaaaah!!: "adjacent opposing fighter" is any rival fighter adjacent to the attacker, not only the one fought.
- Shell Insertion: the rival chooses which card to discard.
- Maximum hand size 3 is applied at the end of the turn (like the 7 of every hero); a Maneuver or PIZZA PARTY may take the hand above 3 during the turn.
