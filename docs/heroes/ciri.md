# Ciri (The Witcher: Steel & Silver)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 344 on sheet 3) on 2026-11-09.

## Summary
- Melee hero, 15 life, move 2, with the sidekick **Ihuarraquax** (melee, 7 life, move 2; one miniature). Hero fid `ciri`, sidekick fid `ihuarraquax`, slug `ciri`.
- Ability **UNCONTAINABLE POWER**: "SOURCE 7: Effects on Ciri's cards cannot be canceled." A passive rule with a `while` (`cards_uncancelable`, docs/effects-dsl.md section 36).
- The **SOURCE** (the orb with a number on the card text) is the number of Source cards in her discard pile (see "Rule decisions"): the HeroDef counter `source`, tag `source` on the 13 cards that carry the orb on the art band. The bag's Source dial (`46aa92`, MAX_VALUE 13 = those 13 cards) mirrors it.
- Deck: 30 cards, `CardID = 17600 + idx`; the Ciri band on 19 cards, the IHUARRAQUAX band on 6 (Bane of the Aen Elle, Searching strike), ANY on 5 (Parry, Unicorn ally). The deck object in the save holds 31 cards (the 30 plus the character card 344), hence `card_count 31` in the catalog.
- Table: bag `45ae7e` (inner `f2c999`), Ciri `f6fea4` (life dial `e6da98`, 15), Ihuarraquax `4ec239` (a `Custom_Token`, life dial `341412`, 7), Source dial `46aa92`, deck `9bd73c`. No GUID is shared with another hero.

## Card identity: the shared CardID range
Her deck is sheet 176 like Medusa's, the turtles', Doctor Strange's, Bigfoot's, Daredevil's, Luke Cage's, Bullseye's, Golden Bat's, Jill Trent's, She-Hulk's and Tomoe Gozen's: the same CardIDs 17600-17629, a different image (`data/tts/ciri.json`, `deck.identity`). Everything in docs/card-identity.md applies; the proof is `tests/test_hero_ciri_data.py`, `tests/test_card_identity.py` (she is in `SHARING`) and `tests/test_ciri_matrix.py`.

## Cards (as implemented)

SOURCE n: is the printed orb with the number n. A card with two lines applies the highest one the Source reaches, never both.

| Title | Type | Value | Boost | Copies | Band | Effect |
|---|---|---|---|---|---|---|
| Lion cub of Cintra (orb) | attack | 2 | 2 | 3 | Ciri | DURING: SOURCE 1: value 4 instead; SOURCE 5: value 7 instead |
| Channel the source | attack | 2 | 3 | 3 | Ciri | DURING: discard any number of Source cards from your hand, +2 to this card's value for each (plugin `ciri:channel_the_source`) |
| Bane of the Aen Elle | attack | 4 | 4 | 3 | Ihuarraquax | AFTER: move Ihuarraquax up to 4, he may move through opposing fighters; then 1 damage to an opposing fighter he moved through |
| Pushed to the brink (orb) | versatile | 3 | 2 | 3 | Ciri | AFTER: SOURCE 2: 1 damage to the opposing fighter; SOURCE 7: 2 damage to an opposing fighter within 3 spaces of Ciri |
| Zireael (orb) | versatile | 2 | 2 | 3 | Ciri | DURING: SOURCE 3: value 4 instead; SOURCE 5: value 4 instead and the opponent discards 1 random card |
| The lady of space and time (orb) | versatile | 2 | 2 | 2 | Ciri | AFTER: SOURCE 3: return a card from your discard pile to the top of your deck; SOURCE 8: return a card from your discard pile to your hand and draw 1 |
| Blink | versatile | 4 | 1 | 3 | Ciri | AFTER: move Ciri up to 3, she may move through opposing fighters |
| Searching strike | versatile | 3 | 3 | 3 | Ihuarraquax | AFTER: if you won, you may search your deck for a Source card, reveal it and add it to your hand |
| Parry | defense | 3 | 1 | 3 | any | IMMEDIATELY: cancel all effects on your opponent's card |
| Child of the Elder Blood (orb) | scheme | - | 2 | 2 | Ciri | SOURCE 4: 1 damage to each other fighter in Ciri's zone; SOURCE 9: 3 damage to each other fighter in Ciri's zone |
| Unicorn ally | scheme | - | 2 | 2 | any | Ciri recovers 2 health. ONGOING: after each combat your fighter is in, draw 1 card; discard this card at the end of your turn if you have 5 or more cards in your hand |

## Discrepancies with unmatched-memory
- The numbered orbs: unmatched-memory writes them as the orb emoji and "x n"; the HeroDef text says `SOURCE n:` (overlay `text`, the same text in the effects file).
- Unicorn ally: unmatched-memory only has "Ciri recovers 2 health."; the card also prints the two ONGOING lines (read from the image).
- Channel the source and Searching strike say "Source card" where unmatched-memory has the orb emoji.
- The ability: same text with `SOURCE 7:` for the orb. Titles, types, values, boosts and copies of all 11 titles match unmatched-memory.

## Engine additions (all additive, docs/effects-dsl.md section 36)
The passive rule `cards_uncancelable` with a `while` (`modifiers.is_uncancelable(card, game)`: `cancel_effects`, the legacy `_cancel_rival` and the bot's `_cancellable_moments` pass the game); the fighter filter `within` (`Board.spaces_apart`); `plugins_raphael.discard_for_bonus` extracted from Unbridled rage and reused by `ciri:channel_the_source` (`plugins_ciri.py`); the intent `search_deck` carries `exact` and the CardIDs when the take has a filter; a Source dial on the table (`session_source.py`, `source_dial` of the session configuration, hooks in `Session._put_dials` / `_track_destiny`); `session_search.py` and `tts/lua_search.py` (the bot's table take by CardID); `ai_ciri.py` (what the Source tiers are worth to the heuristic AI).

## Rule decisions (the most literal reading, applied)
1. **The Source counts the Source cards in her discard pile.** The hero card prints only the 7 threshold, and the cards print the numbers, but nothing in the images says how the Source is gained. The Source dial of the bag goes to 13, exactly the number of orb cards in her deck, so the Source is read like Hellboy's destinies: the cards with the orb in her discard pile (the discard is counted for Channel the source's discards and for hand-limit discards too; a card that leaves the pile lowers it). The card being resolved is not in the pile yet (Hellboy's rule).
2. **Tiers replace each other.** Zireael's SOURCE 5 line repeats "value is 4", Lion cub's 5 line says "7 instead", The lady of space and time's 8 line takes the card to the hand where the 3 line puts it on the deck: only the highest threshold reached applies. Pushed to the brink at Source 7 deals 2, not 1 + 2.
3. **UNCONTAINABLE POWER** protects every card of her deck, Ihuarraquax's included and whoever plays it, from `cancel_effects` (Parry, Feint, Short circuit...), read at the moment of the cancellation. A cancel that is not stopped (Source 6 or less) works as for any card. The rival's own cards are not protected by it.
4. **Searching strike**: "if you won the combat" reads the engine's result (the attacker wins only if combat damage lands, a tie goes to the defender: the global rule). "You may" is an optional. The whole deck is searched for a Source card (none: nothing happens), the card goes to the hand shown to the rival and the deck is shuffled.
5. **Bane of the Aen Elle**: "moved through" is Donatello's Party wagon! reading (an opposing fighter on some path of at most 4 spaces from where he started to where he ended; the human who walks him by hand answers which rivals he passed). The damage is mandatory when somebody was passed; win or lose.
6. **Pushed to the brink**: "within 3 spaces" is counted along the printed adjacency (Bullseye's reach measure), whatever the zones; the 1 damage to "the opposing fighter" does nothing if it was defeated. Hero or sidekick, the owner picks.
7. **Child of the Elder Blood**: "each other fighter in Ciri's zone" is every living fighter that shares a zone with her space except her, hers (Ihuarraquax) included.
8. **Zireael** at SOURCE 5: against the human's hand the engine draws the position from the hand size, like the other random discards.
9. **Unicorn ally**: "each combat your fighter is in" counts every combat of either player (a combat always has one of your fighters in it) and fires after its AFTER effects like Michelangelo's PIZZA PARTY; "at the end of your turn if you have 5 or more cards" needs no ruling: the hand limit trims to 7, which is at least 5. Another ONGOING replaces it as usual. The heal is capped at her maximum.
10. **Combat win (global, Iván 2026-11-07/08)**: the attacker wins only if combat damage lands; a tie or no damage = the defender wins. Every "if you won" here reads the engine's result.

## Open questions for Iván
1. **How is the Source gained?** Read as "Source cards in her discard pile" (see rule decision 1). If the rulebook says otherwise (a counter that only goes up, or one raised by playing the cards), the change is the counter definition in the overlay plus `session_source`; the cards would not change.
2. **Several numbered lines on one card**: highest only (decision 2). The alternative is that every line the Source reaches applies (Pushed to the brink at 7 would deal 1 + 2; The lady at 8 would return to the deck and to the hand).
3. **Searching strike's "reveal it"**: DECIDED: "show it to the rival" (the bot says the card in the chat and physically shuffles its real deck after the take; the human shows it), then the deck is shuffled.
4. **Channel the source** can discard Source cards that are also in the Source count: they raise the Source for the rest of the combat, since they enter the pile at once.

## AI
- The AI profile comes from the data (the importer's `ai_profile`: Ciri `hero`, Ihuarraquax a sidekick). The Source-dependent values live in `ai_ciri.py`, hooked at three places of `ai_medusa.py` (`card_value`, `during_gain`, `attack_outcome`): Lion cub of Cintra and Zireael are valued at the value the current Source gives them, Channel the source at +2 per spare Source card in the hand (half counted: the cards are not free), Pushed to the brink at the damage its AFTER does now, The lady at the cards it returns, Searching strike at a card when it wins and the deck still has a Source card.
- Parry is not wasted on a card that cannot be canceled (`_cancellable_moments` passes the game: UNCONTAINABLE POWER).
- The effect decisions (Bane's and Blink's moves, Pushed to the brink's target, the Lady's card, Searching strike's yes / no) go through the generic `EffectAI` and the controllers' choosers.

## Strength (simulator, heuristic AI, bprd-hq, seeds 100-107)
Bot's Ciri (`--bot-hero ciri`) against each scripted rival (`python -m sparring.sim`, the rival chases and attacks with its best card), 8 games each: 150 wins to 9 losses over 19 rivals (Medusa 8-0, Hellboy 7-1, Abe 8-0, Baba Yaga 8-0, Liz 6-2, Leonardo 8-0, Donatello 8-0, Michelangelo 8-0, Raphael 6-2, Doctor Strange 8-0, Houdini 8-0, Bigfoot 8-0, Daredevil 6-2, Luke Cage 6-2, Bullseye 8-0, Golden Bat 8-0, Jill Trent 8-0, She-Hulk 8-0, Tomoe Gozen 8-0). The same pairs with Ciri as the scripted human (`--human-hero ciri`, the weakest seat of the simulator: the scripted human only chases and attacks): 6 wins to 146 losses; those numbers say nothing about her strength, only that every pairing plays to game over with no error (304 games in all, plus 8 with the search AI at 10 iterations, zero errors). The simulator's scripted human used to crash with Tomoe Gozen's Witness My Last Battle against a fighter that is not adjacent; `hellboy_script.try_attack` now skips a card that does not reach (`Game.attack_card_reaches`). The matrix proves every pairing on FakeTTS.

## Tests
`tests/test_hero_ciri_data.py` (data, tiers in the effects file, card identity, the shared range, detection, the Source dial in the session defaults), `tests/test_ciri_effects.py` (the bot side on the engine: the counter, every tier at every threshold, Channel the source, UNCONTAINABLE POWER, Searching strike, the Lady, Unicorn ally), `tests/test_ciri_human.py` (FakeTTS, the panel: the Source read from the human's pile, the tiers, Pushed to the brink's question, Child of the Elder Blood, Channel the source with its refusals, Searching strike, the Lady, Unicorn ally, UNCONTAINABLE POWER against the bot's Feint), `tests/test_ciri_table.py` (the Source dial on either side and next to Hellboy's, the bot's Searching strike taking the card out of its real deck, the builder), `tests/test_ciri_matrix.py` (full games against every other hero in both seats, passive and attacking human, headless with the heuristic and the search AI).

## What only a live table can show
- The deck search by CardID (`lua_search.deck_card_to_hand`) and its hand insertion; a card that lies in the middle of a stacked deck.
- The Source dial as a `Custom_Model` (its number written by `set_health_dials`, like Hellboy's destiny dial) and the dial of a hand-edit warning.
- Ihuarraquax's miniature is a `Custom_Token` (real TTS reports flat tokens as `Tile`/`Token`): move, ping and placement height.
- The Unicorn ally ONGOING resting on the ONGOING spot and leaving it at the end of the turn.
- The human searching their own deck for Searching strike (table note only: the bot never sees their deck).
