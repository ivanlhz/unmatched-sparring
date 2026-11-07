# Raphael (Teenage Mutant Ninja Turtles)

Set "Adventures: Teenage Mutant Ninja Turtles". Playable by the bot and by the human, either side. Data read from the real card images (sheet 176 of the tournament savegame, character card 368 on sheet 3) on 2026-11-01.

## Summary
- Melee hero, 17 life, move 2. Sidekick **Casey Jones**: one, ranged, 8 life, move 2 (fid `casey`).
- Ability **ANGER ISSUES**: on each of your turns, the first time you lose combat, gain 1 action.
- Deck: 30 cards, `CardID = 17600 + idx`. The deck object in the save holds 31 cards (the 30 plus the character card), hence `card_count 31` in the catalog. Restriction bands: RAPHAEL, CASEY, ANY.
- Table: Raphael's miniature `613334` and dial `887823` (max 17); Casey's token `c67447` and dial `a3f578` (max 8). The miniature's nickname carries a TTS colour tag (`[A32135]Raphael`); `tools/import_save.py` now ignores such tags when matching names.
- His deck is sheet 176 **like Medusa's**: the same CardID range, a different image. Detection, the Lua scripts and the config check tell them apart by image; `combat.is_medusa_card` compares the card by value with Medusa's deck (docs/card-identity.md).

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Who | Effect |
|---|---|---|---|---|---|---|
| Unbridled rage | attack | 3 | 4 | 2 | Raphael | DURING: discard any number of defense/versatile cards, +2 each (plugin `raphael:unbridled_rage`) |
| Let's do this! | attack | 1 | 3 | 3 | Raphael | AFTER: draw 1; draw 2 if you won |
| Turtle power! | attack | 3 | 3 | 2 | Raphael | DURING: you may BOOST this attack (`may_boost`) |
| Crowd control | attack | 2 | 1 | 3 | any | AFTER: draw 1 per adjacent opposing fighter, then 1 damage to each |
| Batter up! | attack | 3 | 2 | 3 | Casey | AFTER: if you won, move the opposing fighter up to 3 spaces |
| Sai | versatile | 4 | 2 | 2 | Raphael | none (vanilla) |
| Break something | versatile | 2 | 1 | 3 | Raphael | IMMEDIATELY: cancel the rival card's DURING and AFTER effects. AFTER: if none was cancelled, 2 damage to an adjacent opposing fighter |
| Payback time! | versatile | 2 | 1 | 3 | any | DURING: value 5 if you lost a combat this turn |
| Relentless | versatile | 3 | 1 | 2 | any | AFTER: shuffle this card into your deck, then draw 1 |
| Slapshot | versatile | 2 | 2 | 3 | Casey | DURING: value 6 if Casey is adjacent to the opposing fighter |
| Heroes in a half shell | defense | 5 | 2 | 2 | Raphael | none (vanilla) |
| Raphael is cool but rude | scheme | - | 2 | 2 | Raphael | 1 damage to each opposing fighter adjacent to at least one friendly fighter; draw 1 |

## Discrepancies with unmatched-memory
- Break something: unmatched-memory has the typo "AFTER COMBAR"; the card says "AFTER COMBAT". Relentless: the card says "into your deck", unmatched-memory "in your deck". Fixed with `text` in the overlay.
- Sai and Heroes in a half shell have no text on the card: they are vanilla, not missing effects. Value, boost, type and copies of all 12 titles match unmatched-memory.
- unmatched-memory has no `copies` problem for this hero (they add up to 30).

## 1v1 meaning of the Adventures wording
"Friendly fighter" is Raphael and Casey Jones; the only rival is the opponent's side. Nothing else in the set text needed translating.

## Engine additions (all additive, see docs/effects-dsl.md section 22)
The `combat_lost` event and the `combats_lost_this_turn` stat, `cancel_effects.moments` with the `effects_canceled` test, the fighter filter `adjacent_to_any`, `return_to_deck` of a card still in the combat, and the plugin `raphael:unbridled_rage`.

## Rules decisions (follow the engine's and the other heroes')
1. A combat is won by the attacker only if it deals at least 1 damage; on a tie or a lower value the attacker loses and the defender wins (tie won by the defender: CONFIRMED by Ivan 2026-11-07; ANGER ISSUES stays as is). ANGER ISSUES and Payback time! use that.
2. ANGER ISSUES counts combats lost in the current turn and gives its action right after the damage (before the AFTER effects); a defense lost on the rival's turn gives nothing.
3. Break something: "no effects were canceled this way" means the rival card had no DURING or AFTER effect (or could not be cancelled: Incinerate, or no card). Its IMMEDIATELY effects stay when Raphael defends.
4. Unbridled rage: only defense and versatile cards count; zero is allowed. The bot weighs the keep value of each card against the damage the next +2 adds. The human puts the cards they give up in their discard pile and presses Done: the bot reads the pile by CardID (`session_rage`), checks each new card is a defense or versatile card of theirs (an attack or scheme is refused by name, with its type, and goes back to the hand; the panel keeps waiting) and adds +2 per valid card. Done with nothing new is 0 cards.
5. Relentless is shuffled before the draw (the draw may bring it back). Played by the human, the bot moves the card from their combat spot into their deck by GUID, shuffles the deck and then deals the draw (`session_translators.combat_card_to_deck`); only if the table refuses (no deck GUID, no identity, the card is not loose) does the chat ask them to do it by hand.
6. The free BOOST of a `may_boost` card (Turtle power!, Second Shot, Out Of Time, Flame Lash...) is a DURING effect of the card, so it follows the cancel moments: a rival IMMEDIATELY that cancels everything (Feint, Ward And Prepare, Planned Recklessness as OCCULT DETECTIVE, an accepted Leonardo / Michelangelo cancel) or only DURING and AFTER (Break something) removes it; a cancel of only AFTER (Short circuit) does not. The bot never boosts a cancelled card (the combat rule is skipped for a cancelled side). For the human the boost is read from the table before the combat runs, so at Reveal `session_boost.offered` dry-runs the combat on a clone of the game up to DURING and asks whether the human's side is cancelled there; if it is, the panel does not ask for a boost, says why and resolves the combat.

## Open questions for Iván
- Break something: is "no effects were canceled" about effects that existed on the card, as implemented, or about effects that would have done something?
- Human Relentless: the bot moves it into your deck; if a save is resumed between the reveal and the AFTER, the combat spot GUID is lost and you are asked to do it by hand (not seen live).
- Human Unbridled rage: the cards are detected on the discard pile, but the engine cannot verify that they left your HAND (they could come from anywhere you hold); only the types are checked.
- The boost dry run uses the bot's own controllers for its IMMEDIATELY choices (Leonardo's and Michelangelo's optional cancels): if the bot would decide differently in the real run, the prompt may be shown or hidden wrongly once.
- Hand limit and ANGER ISSUES: an action gained when you have 0 left lets you still attack; not seen live.

## AI
- The AI profile comes from the data (Raphael `hero`, Casey `striker` because ranged; exclusive cards Batter up! and Slapshot). `ai_medusa` has small hints: the draws of Let's do this! and Crowd control, the cancel of Break something, the real values of Slapshot (6 with Casey adjacent) and Payback time! (5 after a lost combat).
- The scheme is valued by simulating it (the same way as the other heroes'), so the bot plays it when a rival stands next to its fighters.

## Tests
`tests/test_hero_raphael_data.py` (data), `tests/test_raphael_effects.py` (every card and the ability, bot side), `tests/test_raphael_human.py` (panel flows at the table), `tests/test_raphael_session.py` (FakeTTS, ten pairs, whole games), `tests/test_raphael_sim.py` (headless matrix with the heuristic and ISMCTS), `tests/test_raphael_detect.py`.
