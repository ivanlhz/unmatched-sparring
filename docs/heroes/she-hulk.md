# She-Hulk (Marvel, Brains and Brawn)

Playable by the bot and by the human, either side, against every other hero. Data: the hero card (character card 336, sheet 3 of the tournament savegame) was read from its image on 2026-11-08; the 30 cards were read from the sheet 176 image and agree with unmatched-memory. Verified on FakeTTS only: nothing of She-Hulk has been seen on a real table (see `docs/live-checklist.md`).

## Summary
- Melee hero, 20 life, move 2, no sidekick (fid `shehulk`). One fighter: every "fighter" of the cards is She-Hulk.
- Ability **JUST THROW SOMETHING**: "At the start of your turn, you may discard a card to deal damage equal to its BOOST value to a fighter in your zone." A start-of-turn trigger of the effects file (plugin `shehulk:throw`).
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176), every card restricted to SHE-HULK. The deck object of the save holds 31 cards (the 30 plus the character card `336`).
- Table: miniature `95f90a` and dial `268982` (max 20), bag `04711f`, deck `346c1b`. No piece GUID is shared with another hero.
- **She shares CardIDs 17600-17629 with Medusa, the four turtles, Doctor Strange, Bigfoot, Daredevil, Luke Cage and Bullseye**: her deck is told apart by deck image and owner (docs/card-identity.md), never by a bare CardID. `tests/test_she_hulk_matrix.py` plays her against every other hero in both seats.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| Omega-Level Threat | attack | 5 | 2 | 2 | AFTER: if you dealt 2 or more combat damage, the opponent discards 2 random cards |
| The Savage She-Hulk | attack | 3 | 3 | 2 | DURING: you may spend an additional action to make the value 9 |
| Sensational | attack | 4 | 2 | 3 | AFTER: if you won, you may choose a card of your discard pile and shuffle it into your deck |
| Legalese | versatile | 2 | 1 | 3 | AFTER: if you won, the opponent chooses (both draw 1 / both discard 1); if you lost, you choose |
| Nerve Cluster Strike | versatile | 3 | 1 | 3 | IMMEDIATELY: if she is adjacent to the opposing fighter, it may not leave its space this turn |
| Cease and Desist | versatile | 1 | 2 | 3 | IMMEDIATELY: cancel all effects on the opponent's card. DURING: attacking, the value is 4 |
| Green Energy | versatile | 4 | 1 | 3 | AFTER: if you won, 1 damage to each fighter adjacent to She-Hulk |
| Lady Justice | defense | 0 | 2 | 3 | DURING: discard the top card of the OPPONENT's deck; +2 x its BOOST to the value |
| The Defense Rests | defense | 2 | 2 | 2 | AFTER: draw cards equal to the combat damage you took |
| Jennifer Walters, Esq. | scheme | - | 1 | 2 | Place She-Hulk on a starting space. Draw 1. Gain 1 action |
| Leap Toward | scheme | - | 1 | 2 | Move her up to 4 (through opposing fighters). Then, if adjacent to an opposing fighter, gain 1 action |
| Double Jeopardy | scheme | - | 2 | 2 | Draw 2 and recover 2 health |

## The sheet
Sheet 176 (8x4 grid) holds her 30 cards left to right, top to bottom: Omega-Level Threat x2, The Savage She-Hulk x2, Sensational x3, Legalese x3, Green Energy x3, Cease and Desist x3, Nerve Cluster Strike x3, Lady Justice x3, The Defense Rests x2, Double Jeopardy x2, Jennifer Walters, Esq. x2, Leap Toward x2 (`CardID = 17600 + idx`).

## Discrepancies with unmatched-memory
- unmatched-memory spells the hero "She Hulk"; the card says SHE-HULK (overlay `name`: "She-Hulk").
- **Lady Justice** is a defense card with printed value 0 (unmatched-memory has `null`; the importer refuses a null on anything but a scheme, so the overlay carries `value: 0`), like Luke Cage's Skin Like Titanium. Its text raises the value when it defends.
- The restriction band is not in unmatched-memory at all: every card is SHE-HULK.

## Rules decisions (the user is away: the most literal reading, applied)
Every item that is a real doubt is also an open question below.

1. **JUST THROW SOMETHING never targets She-Hulk herself.** "A fighter in your zone" literally includes her; nobody would aim at themselves, so the trigger only exists when an OPPOSING fighter shares her zone (the condition `exists enemy in zone_of hero`) and the damage goes to one of those (the owner picks when there are two). It is effect damage: Pact Of Mortality, immunities and the like apply. With no card in hand nothing is asked; declining is choosing no card.
2. **The cost is paid first, whatever the card**: the discarded card needs a BOOST value (a card with 0 BOOST deals 0 and is not worth it; the bot never throws one).
3. **The human's JUST THROW SOMETHING is theirs on the table** (it reads their real hand): the chat announces it, the panel waits for End action, they put the card on their discard pile and lower the rival's dial by hand. The bot's is resolved by the engine and said in the chat.
4. **The Savage She-Hulk**: "spend an additional action" is a second action on top of the attack's own, taken while the card resolves (DURING). It is offered only when at least one action is left after the attack. The printed value becomes 9 (bonuses stay).
5. **Cease and Desist**: attacking, the value becomes 4 (printed value replaced, bonuses stay); defending it is 1. It cancels all the effects of the opponent's card (IMMEDIATELY), not its own DURING.
6. **Omega-Level Threat**: "combat damage you dealt" is the damage that really landed (after Luke Cage's reduction, for instance), not the card's value; effect damage does not count. A hand of fewer than 2 cards discards what it has.
7. **Sensational**: "you may choose a card in your discard pile": zero or one; the card just played is not in the pile yet.
8. **Legalese**: won, the opponent chooses; any other result (a tie included) counts as lost and she chooses. Each player discards a card of THEIR OWN choice (an empty hand discards nothing); both draw: the owner first.
9. **Nerve Cluster Strike**: the status is Burning Barrier's (`cannot_leave_space`, all movement of that fighter until the end of the current turn). Played in defense, "this turn" is the attacker's turn. If she is not adjacent to the opposing fighter (a shooter attacked her from afar) nothing happens.
10. **Lady Justice**: the top card of the opponent's deck goes to ITS discard pile, face up; the value is 0 + 2 x that card's BOOST (a card with no boost adds 0); an empty deck adds nothing. With the human's deck the bot moves their real top card after they press the one button the panel shows.
11. **Green Energy**: every fighter adjacent to her takes 1 (effect damage), the combat's victim included when it is still next to her.
12. **The Defense Rests**: draws as many cards as the combat damage that landed on her (0 draws nothing); a deck that runs out costs exhaustion damage as for any draw.
13. **Jennifer Walters, Esq.**: "a starting space" is any free starting space of the board, the one she is on included; the action is gained even if none is free.
14. **Leap Toward**: she moves up to 4 through opposing fighters; the extra action needs an opposing fighter adjacent to her where she ends (the one she stopped at or any other).
15. **Double Jeopardy**: heals her up to 20, never above.

## Open questions for Iván
1. **JUST THROW SOMETHING and herself**: it never hurts She-Hulk and is not offered without an opposing fighter in her zone. Is that the reading you want, or should she be allowed to target herself?
2. **Legalese on a tie**: treated as lost (she chooses). Right?
3. **The Savage She-Hulk's additional action**: it needs one action left after the attack's own (with 2 actions a turn, the attack must be the first). Right?

## AI
- The AI profile comes from the data (She-Hulk `hero`, every card exclusive to her).
- Card hints in `ai_medusa`: the bonuses of the AFTER effects, the values her own text sets (Cease and Desist 4 attacking, The Savage She-Hulk 9 when an action is left and charged for), Lady Justice priced as a defense of `2 x` the average BOOST of the rival's cards it still holds, and the cancel of Cease and Desist (already read from the data).
- `EffectAI`: `_card_to_throw` (the card whose BOOST blow on the best target beats what the card is worth in hand by `THROW_MARGIN`, a kill included, or none), `_action_for_value` (an additional action is paid when the blow it adds is worth more than `ACTION_PRICE`, and never defending), the optional choices of Legalese by simulation like any `choose_effect`.

## Human side
- Buttons appear only when a card asks: the Savage She-Hulk's Yes / No, the card choices of Sensational (the human's discard pile, by hand), Legalese's option, Lady Justice's one button when the bot plays it against their deck ("Press to let the bot discard the top card of your deck").
- Her ability waits for the human at the start of their turn (a chat text and the End action gate); Jennifer Walters, Esq. and Leap Toward ask the human to place or move her miniature by hand.

## Tests
`tests/test_hero_she_hulk_data.py` (data, card identity, detection), `tests/test_she_hulk_effects.py` (the ability, every card, the op `spend_action`, the bot's decisions), `tests/test_she_hulk_human.py` (FakeTTS panel: Lady Justice both ways, The Savage She-Hulk, the ability, Jennifer Walters), `tests/test_she_hulk_matrix.py` (full games against the fifteen other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
