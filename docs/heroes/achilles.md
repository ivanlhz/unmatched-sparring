# Achilles (Battle of Legends, Volume Two)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 318 on sheet 3) and from unmatched-memory (`achilles.json`) on 2026-11-20; they agree. Played live by Ivan (by 2026-11-23).

## Summary
- Melee hero, 18 life, move 2, sidekick **Patroclus** (melee, 6 life, move 2, one of them). Hero fid `achilles`, sidekick fid `patroclus`, slug `achilles` (the same in unmatched-memory).
- Ability: "When Patroclus is defeated, discard 2 random cards. While Patroclus is defeated: add +2 to the value of all Achilles' attacks; if Achilles wins combat, draw 1 card."
  - the **trigger** (`fighter_defeated` of Patroclus) is DSL: `discard` of 2 cards of the owner's hand with `pick: random`;
  - the **+2** is an engine passive (HeroDef `{"effect": "sidekick_defeated_bonus", "sidekick": "patroclus", "n": 2}`, `sparring/vengeance.py`), read by `Game.attack_bonus_parts` / `Game.attack_bonus` like the Raptors' pack bonus and Eredin's rage; only attacks of Achilles himself, never a defense and never Patroclus (who is defeated anyway);
  - the **draw** is the hero's own AFTER (`ability.after`, DSL, entry `vengeance_draw` flagged `cardless` and `second_attack`): after a combat Achilles wins, with Patroclus defeated and the fighter being Achilles himself (a Patroclus that wins a combat and falls in it, as with The Day of Your Doom, does not draw). Ivan 2026-11-20: it counts the second attack (winning both parts of Test For Weakness draws 2; defending a rival's double attack and winning its second combat draws too) and a defense with no card played (a defender who takes no damage wins and draws).
- Deck: 30 cards, `CardID = 17600 + idx`. Bands read from the images: ACHILLES on Achilles' Heel, Under Achilles' Helm and Spear Throw; PATROCLUS on Battle Frenzy and The Day of Your Doom; ANY on the other seven titles. The deck object holds 31 cards (the 30 plus character card 318).
- Table: bag `e9df2a` (inner `42ac50`), deck `70a2b2`, Achilles' miniature `6b0ddb` and dial `feaa22` (max 18), Patroclus' token `978237` (a Custom_Token, like Daisy and The Porter) and dial `ec605e` (max 6). No GUID of his is shared with another hero.

## Card identity: the shared CardID range
His deck is sheet 176 like Medusa's, the turtles' and the other sheet-176 decks: the same CardIDs 17600-17629, a different image (`data/tts/achilles.json`, `deck.identity`). Everything in docs/card-identity.md applies; the proof is `tests/test_hero_achilles_data.py` (ranges equal, images disjoint from every other deck of the sheet, no card equal across decks, detection in both seats, catalog entry, no shared GUID), `tests/test_card_identity.py` (he is in `SHARING`) and `tests/test_achilles_matrix.py`.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Fighter | Effect |
|---|---|---|---|---|---|---|
| Brothers In Arms | attack | 4 | 2 | 3 | any | AFTER: if Patroclus is not defeated, gain 1 action |
| Test For Weakness | attack | 1 | 3 | 3 | any | AFTER: RELENTLESS ASSAULT, a second attack of 3 (DOUBLE ATTACK) |
| Battle Frenzy | attack | 3 | 2 | 2 | Patroclus | AFTER: 2 damage to both fighters in the combat |
| The Day of Your Doom | attack | 3 | 2 | 2 | Patroclus | DURING: you may deal 2 damage to Patroclus; if you do, the value of this attack is 5 instead |
| Battle Hardened | versatile | 2 | 2 | 2 | any | AFTER: return a card of your discard pile to your hand |
| Wily Fighting | versatile | 3 | 1 | 2 | any | AFTER: 1 damage to each opposing fighter adjacent to your fighter |
| Skirmish | versatile | 4 | 1 | 3 | any | AFTER: if you won, move one of the fighters in the combat up to 2 spaces |
| Feint | versatile | 2 | 1 | 3 | any | IMMEDIATELY: cancel all effects on your opponent's card |
| Blessed By Hermes | versatile | 3 | 1 | 2 | any | AFTER: move each of your fighters up to 3 spaces, through opposing fighters |
| Achilles' Heel | defense | 4 | 2 | 3 | Achilles | AFTER: if you lost the combat, your opponent gains 1 action |
| Under Achilles' Helm | defense | 2 | 4 | 3 | Achilles | IMMEDIATELY: if Patroclus is not defeated, Achilles may swap spaces with him; if he does, Patroclus is now the defender |
| Spear Throw | scheme | - | 1 | 2 | Achilles | 2 damage to an opposing fighter in Achilles' zone |

## Discrepancies with unmatched-memory
- None on titles, copies, types, values, boosts or texts. The restriction bands are not in unmatched-memory (read from the images).

## Engine additions
- `sparring/vengeance.py` (the +2) hooked in `Game.attack_bonus_parts` and `Game.attack_bonus` (`sparring/state.py`).
- Plugin `achilles:replace_combatant` (`sparring/effects/plugins_achilles.py`): Houdini's and Luke Cage's mechanism for Under Achilles' Helm (Patroclus takes Achilles' place as the defender).
- AI: `sparring/ai_achilles.py` (below). Everything else is existing DSL: `fighter_defeated` trigger, `discard` random, `second_attack` (docs/effects-dsl.md section 45), `swap`, `put_in_hand`, `move` through enemies, `gain_action` for the opponent.

## Rule decisions (the most literal reading of the card, no ruling asked: see "Pending Ivan")
1. **Patroclus' fall**: the 2 random cards go the instant he is defeated, whatever defeats him (a combat, an effect, exhaustion), once; with fewer than 2 cards in hand the owner discards what they hold. At the table the engine names two random positions of the human's hand ("cards 5 and 7 of 7, counting from the left") and the human lays them on their discard pile.
2. **+2 to "all Achilles' attacks"**: attack cards and versatile cards played as an attack, on every attack Achilles makes (his turn or, as a free attack, any other); defenses keep their printed value.
3. **Draw on a win** (Ivan 2026-11-20): "if Achilles wins combat" is read for every combat Achilles is in, attacking or defending, with or without a card played, and for each combat on its own: the first part and the second attack of a double attack are two combats (`ops_combat.hero_after`, flags `cardless` and `second_attack` on the ability entry; other heroes' won/lost readings are unchanged). Not for a combat Patroclus is in.
4. **Under Achilles' Helm**: Patroclus anywhere on the board (no range check); after the swap he takes the blow with the card's 2 as the defender, his AFTER effects included. The bot decides with the same rule as Smoke And Mirrors (whoever loses less takes the blow), and Patroclus' fall is priced in his kill value.
5. **The Day of Your Doom**: Patroclus plays it (it is his band), so the 2 damage is to the fighter that plays it. It may defeat him: Achilles then discards 2 random cards and arms himself.
6. **Spear Throw**: any opposing fighter in a zone of Achilles' space (his own space included); with several, the owner chooses; with none the scheme is played for nothing.
7. **Battle Hardened**: any card of the owner's discard pile; the card just played is not in the pile yet, so it cannot choose itself. When the pile holds a single card it is taken without asking (the table tells the human to pick it up).
8. **Achilles' Heel**: "gains 1 action" only counts while it is the opponent's turn (it is the engine's `gain_action`: a defense played on the opponent's turn gives them the action).
9. **Brothers In Arms**: Patroclus is checked when the AFTER runs (he may have fallen in this combat).

## Decided by Ivan (2026-11-20)
1. The +2 applies to the second attack of Test For Weakness (with Patroclus down it is 1+2, then 3+2).
2. "If Achilles wins combat, draw 1" counts the second attack: winning the second combat draws 1 (both: 2), also when he defends a rival's double attack.
3. Defending without a card and winning the combat draws 1.

## Pending Ivan
None open for Achilles.

## AI
- `sparring/ai_achilles.py`: **the fall of Patroclus is a trade.** `fall_net` = edge (+2 on every attack and a draw per win, `FALL_EDGE` 3.0 hit-point weights) minus 1.2 per card he is about to throw away (at most 2): it is subtracted from `kill_value`, so a bot with Achilles weighs his own sidekick's death as a small prize or loss (more cards in hand, a smaller edge) and a bot facing Achilles values the kill of Patroclus less.
- The search leaf (`search.adapter.EngineState._vengeance` -> `ai_achilles.leaf_term`) values a fallen Patroclus at `LEAF_HP` = `FALL_EDGE` hit points **in the unit of the evaluation it is in**: `1/(2*REFERENCE_HP)` lives per hit point in the normalized evaluation, `1/max_hp` of the hero in the default one. (Round 1 used 0.4 lives, about 12.8 hit points in the normalized unit, four times the heuristic's edge: a 2-HP Patroclus falling then looked like a windfall to Achilles' own search and the rival's search avoided finishing him.) The discard is not priced in the leaf: the engine already took the two cards out of the simulated hand.
- Reproducible with `tools/measure_achilles_ai.py` (committed): `python tools/measure_achilles_ai.py leaf` and `... games 24 40 0 3.0 6.0`.
  - `leaf` (a 2-HP Patroclus falls, hand 4 -> 2): default evaluation, Achilles' advantage -1.1 hit points, leaf for the rival's search 0.595 -> 0.622 (+0.027); normalized evaluation, Achilles' advantage -7.5 hit points, rival 0.614 -> 0.689 (+0.075). Finishing Patroclus is good for the rival in both.
  - `games` (search AI, 40 iterations, 24 seeded games on bprd-hq against the scripted chasing rival; leaf edge 0 / 3.0 / 6.0 hit points). Seat `achilles-bot` (bot is Achilles): bot won 12 / 10 / 13 of 24, Patroclus fell in 7 / 11 / 12. Seat `rival-bot` (bot is Hellboy, the scripted rival plays Achilles): bot won 1 / 6 / 9 of 24, Patroclus fell in 22 / 22 / 17. At 3.0 the bot with Achilles spends Patroclus more often (7 -> 11 games) with no loss of games won, and the bot facing Achilles still finishes him in 22 of 24. Sanity checks against a scripted rival with a small sample (noise is a few games), not a balance statement.
- `The Day of Your Doom`: `card_value` is 5 when the bot will pay (`doom_pays`: the extra points of blow against the hit points it costs Patroclus, the fall counted when it kills him).
- Under Achilles' Helm: `EffectAI._swap_combatant` (shared with Houdini, Luke Cage and Washington) through `kill_value`.

## Tests
`tests/test_hero_achilles_data.py` (data and card identity), `tests/test_achilles_effects.py` (the ability, every card, the double attack), `tests/test_achilles_human.py` (FakeTTS, the panel: the random discard, +2, the draw, the Helm Yes/No, The Day of Your Doom, Spear Throw, Battle Hardened, Test For Weakness in both directions), `tests/test_achilles_ai.py` (the AI's pricing and the leaf), `tests/test_achilles_matrix.py` (full games against every other playable hero in both seats, `available_heroes()`, passive and attacking human, headless with the heuristic and the search AI).
