# Philippa (The Witcher: Realms Fall)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 349 on sheet 3) on 2026-11-13. Nothing of her has been seen on a real table yet.

## Summary
- Ranged hero, 12 life, move 2, sidekick **Dijkstra** (melee, 6 life, move 2, one of them). Hero fid `philippa`, sidekick fid `dijkstra`, slug `philippa` (the same in unmatched-memory).
- Ability **TWO STEPS AHEAD**: "At the end of your turn, you may draw until you have a hand of 4 cards." A trigger on `end_of_turn` that is only offered with fewer than 4 cards in hand and draws the Amount `{"hand_deficit": 4}` (docs/effects-dsl.md, section 40).
- Deck: 30 cards, `CardID = 17600 + idx`. Restriction band read from the images: PHILIPPA on Owlform, Lightning bolt, Chain lightning, Spellbreaker, Paralyzing fetters, Blinding dust, Polymorphy and Backup plan; DIJKSTRA on Spymaster's ruse; ANY on Regicide, Cunning, Redanian plot and Do my bidding. The deck object holds 31 cards (the 30 plus character card 349).
- Table: bag `4dc6f9` (inner `859216`), deck `ea91d3`, Philippa's miniature `e91869` and dial `684429` (max 12), Dijkstra's token `c97270` (a Custom_Token, like Daisy and The Porter) and dial `ec1f51` (max 6). No GUID of hers is shared with another hero.

## Card identity: the shared CardID range
Her deck is sheet 176 like Medusa's, the turtles', Doctor Strange's and the other sheet-176 decks: the same CardIDs 17600-17629, a different image (`data/tts/philippa.json`, `deck.identity`). Everything in docs/card-identity.md applies; the proof is `tests/test_hero_philippa_data.py` (ranges equal, images disjoint from every other deck of the sheet, no card equal across decks, detection in both seats, catalog entry, no shared GUID), `tests/test_card_identity.py` (she is in `SHARING`) and `tests/test_philippa_matrix.py`.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Fighter | Effect |
|---|---|---|---|---|---|---|
| Owlform | attack | 3 | 3 | 3 | Philippa | DURING: discard any number of cards from the hand, +1 to the value for each |
| Lightning bolt | attack | 3 | 1 | 3 | Philippa | AFTER: if no Maneuver was taken this turn, 1 damage to each opposing fighter in Philippa's zone |
| Chain lightning | attack | 2 | 3 | 2 | Philippa | AFTER: choose a zone Philippa is in, 1 damage to each opposing fighter in it |
| Regicide | attack | 4 | 2 | 2 | any | DURING: 6 instead if the opposing fighter is a hero |
| Spellbreaker | versatile | 2 | 2 | 3 | Philippa | IMMEDIATELY: cancel all effects on the opponent's card; AFTER: end the turn |
| Cunning | versatile | 4 | 1 | 2 | any | AFTER: the opponent may discard 1 card; if not, 2 damage to the opposing fighter |
| Redanian plot | versatile | 2 | 1 | 3 | any | IMMEDIATELY: the opponent may discard 1 card; if not, their card's value is ignored |
| Paralyzing fetters | defense | 2 | 3 | 2 | Philippa | IMMEDIATELY: the opponent's card keeps its printed value, which cannot be changed |
| Blinding dust | defense | 2 | 2 | 2 | Philippa | AFTER: you may discard 1 card; if you do, damage to the opposing fighter equal to the discarded card's BOOST |
| Do my bidding | defense | 3 | 3 | 2 | any | IMMEDIATELY: the opponent's card goes back to their hand; look at it and choose a card for them to play (may be the same) |
| Polymorphy | scheme | - | 3 | 2 | Philippa | Place Philippa in any space. ONGOING: her move value is 5; discard at the end of your turn if she is not in a zone with an opposing fighter |
| Backup plan | scheme | - | 2 | 2 | Philippa | Choose one: set Philippa's health to 5, or draw 3 cards |
| Spymaster's ruse | scheme | - | 2 | 2 | Dijkstra | The opponent reveals 4 cards of their hand, you choose 2 of them to be discarded, then they draw 2 |

## Discrepancies with unmatched-memory
- Polymorphy prints an ONGOING that unmatched-memory leaves out (read from the image): the overlay carries the printed text.
- Titles, types, values, boosts, copies and the other texts of all 13 titles match unmatched-memory.
- Paralyzing fetters is word for word the card Yennefer & Triss and Jill Trent's Stasis Diffuser print: `tests/test_hero_philippa_data.py` pins that the effect is the very same data.

## Engine additions (all additive, docs/effects-dsl.md section 40)
- Amount `{"hand_deficit": N}` (`select.amount`): what the owner's hand lacks to reach N cards. `ops_core._choice_context` treats an optional draw of it like any free draw (`draws`), so `EffectAI._free_draw` refuses it at the end of the turn when the deck holds fewer cards than it would draw.
- ONGOING rule `hero_move` (`amount`): the owner's hero moves that many spaces (`enraged.ongoing_move`). `enraged.sync_move` (which already followed the roster for Eredin) applies it, and `EffectState.set_ongoing` / `take_ongoing` call it, so `Fighter.move` is 5 the moment Polymorphy is in play and 2 again the moment it leaves. Every planner reads `Fighter.move`, so the bot, the search and the human's Maneuver all use it. `ongoing.worth` prices it (`HERO_MOVE_HP` per extra space).
- Plugins (`sparring/effects/plugins_philippa.py`): `philippa:owlform`, `philippa:chain_lightning`, `philippa:blinding_dust`, `philippa:do_my_bidding`, `philippa:spymaster_ruse`.
- `ControllerChooser.choose`: a pick among the RIVAL's hand that the controller judges itself (`OWN_JUDGEMENT_PURPOSES`: `bidding`, `ruse`) is asked of the controller (`EffectAI`) instead of always taking the most valuable known card; `default_answer` takes none for `purpose: dust`.
- Table side (`session_rage`): `tag: any` for Owlform's panel text, `dust` for Blinding dust (pile mode `reveal`: the card the human lays on their pile), `bidding` for Do my bidding (pile mode `play`, like Sleight Of Hand's, with the card named by the bot).

## Rule decisions (the most literal reading of the card, no ruling asked: see "Pending Ivan")
1. **TWO STEPS AHEAD** runs at the end of the hero's own turn, before the hand limit is enforced, and is only offered with fewer than 4 cards in hand. The bot refuses it when its deck holds fewer cards than it would draw.
2. **Owlform**: zero cards is fine; any card of the hand counts (not only attack or versatile ones). The human lays the cards on their discard pile and presses Done.
3. **Lightning bolt**: "a maneuver action this turn" is the stat `maneuvers_this_turn` (Golden Bat's): a Maneuver that was prevented from drawing does not count. The damage reaches every zone her space belongs to; the combat target is included when it is still alive.
4. **Chain lightning**: a space can belong to several zones; with more than one the owner chooses (an `effect` request with the zone names as labels), with one nothing is asked.
5. **Regicide**: "the opposing fighter is a hero": the other fighter of the combat. The 6 replaces the printed 4 (bonuses stay).
6. **Spellbreaker**: its AFTER ends the CURRENT turn, whoever's it is: played as a defense it ends the attacker's turn. If its effects are cancelled the turn does not end.
7. **Redanian plot / Cunning**: the opponent decides; with an empty hand they cannot pay and take the else branch.
8. **Do my bidding**: it runs in the defender's IMMEDIATELY, so the rival's new card still has its own IMMEDIATELY run afterwards. The chosen card must be an attack or versatile card the attacking fighter can play against that target (adjacent-only cards included). If the opponent holds no other such card the returned card is played again. The bot picks the weakest card for the rival (value, then worth). For a human rival the bot reads their hand (`look_hand`), names the card and the human takes the old card back and puts the new one on their combat spot. For a human Philippa the bot's hand is laid out and the human clicks one; picking none means "the same card" (the returned card is on the bot's combat spot, not in its hand row).
9. **Polymorphy**: "any space" is any EMPTY space. The ONGOING leaves play at the end of YOUR turn when no opposing fighter shares a zone with Philippa then (a fighter in the same zone, sidekick or hero, keeps it). Another ONGOING replaces it as for every ONGOING (one per player). Her move value goes back to 2 as soon as the card leaves play.
10. **Backup plan**: "set Philippa's health to 5" also RAISES her from below 5 (literal reading). Draw 3 is the other option.
11. **Spymaster's ruse**: the opponent chooses which 4 cards they reveal (all of them with fewer than 4; Ivan, 2026-11-13). The owner chooses 2 of those; the opponent then draws 2 whatever happened. The revealed cards become known to the owner. Only Dijkstra can play it: with Dijkstra defeated the two copies are dead cards.
12. **Blinding dust**: "its BOOST value": the discarded card's BOOST (the nearest antecedent). A card with no BOOST value deals 0.

## Decided by Ivan (2026-11-13)
1. **Blinding dust**: "its BOOST value" is the discarded card's BOOST.
2. **Backup plan**: "set health to 5" also raises her from below 5.
3. **Polymorphy**: checked only at the end of the owner's turn; "any space" is an empty space.
4. **Do my bidding**: the new card must be an attack or versatile card the attacking fighter can play.
5. **Spymaster's ruse, the human against the bot (table flow)**: the bot chooses and lays the four cards face up in the row (`bot_row_spot`); the human takes two of them to the bot's discard pile and presses Done; the bot returns the other two to its hand, reads which two reached the pile (by identity: `session_hidden.ruse_verdict`, only revealed cards count, exactly two) and syncs the engine (`ruse_done`, `close_ruse_row`). Saves and resumes keep the row (`session.look`) and the pending request (`ruse_table`).

## Pending Ivan
1. **Do my bidding, "the same card is allowed"**: Ivan answered "yes, it may be if it comes out of the deck" (2026-11-13), which is ambiguous; asked again, nothing changed. Implemented: the returned card is a valid choice (the one the opponent already played).
2. **Spymaster's ruse, the bot against the human**: the human names the four cards they reveal on the panel (the list is their whole set that is not in a pile apart; the engine does not know their hand), then the bot names the two to discard and the human moves them by hand. Should it use a table flow like the human's direction?
3. **Do my bidding in table mode**: a human Philippa cannot point at "the same card" (it is on the bot's combat spot); choosing nothing means the same card.

## AI
- The AI profile comes from the data (`ai_profile` of the importer: Philippa `hero`, ranged; Dijkstra `striker`). The name-based pricing lives in `sparring/ai_philippa.py` and is read by `MedusaAI.card_value` (Regicide 6 against a hero), `attack_outcome` and `eval_defense` (`after_value`: the lightning's reach, Cunning, Redanian plot, Do my bidding, Paralyzing fetters; Spellbreaker's end of turn costs the actions still to spend). The choices her plugins ask for are answered by `EffectAI._cards` (`dust`: the discard whose BOOST beats its keep value; `bidding`: the weakest card for the rival; `ruse`: the two cards the rival would miss most; `ruse_reveal`: when the bot is the opponent it reveals the four it would miss least) and `EffectAI._zone` (Chain lightning: the zone with the most hit points to take).
- Her schemes are priced by simulating them (`scheme_act`); Polymorphy's value includes its move (`ongoing.worth`).
- Search: `make_bot_ai({"ai": "ismcts", "iterations": 30})` played six full games as Philippa against Hellboy, Medusa and Sinbad (the scripted chasing rival): 6 wins, zero fallbacks, zero exceptions; the heuristic AI won three of three against the chaser. These are sanity checks, not a balance statement.

## Tests
`tests/test_hero_philippa_data.py` (data and card identity), `tests/test_philippa_effects.py` (the ability, every card, Polymorphy's move), `tests/test_philippa_human.py` (FakeTTS, the panel: TWO STEPS AHEAD, Owlform, Backup plan, Polymorphy, Blinding dust, Spymaster's ruse in both directions, Do my bidding in both directions), `tests/test_philippa_ai.py` (the AI's pricing and answers to her plugin requests), `tests/test_philippa_matrix.py` (full games against 24 heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
