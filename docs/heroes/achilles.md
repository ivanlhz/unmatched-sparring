# Achilles (Battle of Legends, Volume Two)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 318 on sheet 3) and from unmatched-memory (`achilles.json`) on 2026-11-20; they agree. Nothing of him has been seen on a real table yet.

## Summary
- Melee hero, 18 life, move 2, sidekick **Patroclus** (melee, 6 life, move 2, one of them). Hero fid `achilles`, sidekick fid `patroclus`, slug `achilles` (the same in unmatched-memory).
- Ability: "When Patroclus is defeated, discard 2 random cards. While Patroclus is defeated: add +2 to the value of all Achilles' attacks; if Achilles wins combat, draw 1 card."
  - the **trigger** (`fighter_defeated` of Patroclus) is DSL: `discard` of 2 cards of the owner's hand with `pick: random`;
  - the **+2** is an engine passive (HeroDef `{"effect": "sidekick_defeated_bonus", "sidekick": "patroclus", "n": 2}`, `sparring/vengeance.py`), read by `Game.attack_bonus_parts` / `Game.attack_bonus` like the Raptors' pack bonus and Eredin's rage; only attacks of Achilles himself, never a defense and never Patroclus (who is defeated anyway);
  - the **draw** is the hero's own AFTER (`ability.after`, DSL): after a combat Achilles' owner won, with Patroclus defeated and the fighter being Achilles himself (a Patroclus that wins a combat and falls in it, as with The Day of Your Doom, does not draw).
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
3. **Draw on a win**: "if Achilles wins combat" is read for the combats Achilles is in, attacking or defending (a defender who takes no damage wins). Not for a combat Patroclus is in.
4. **Under Achilles' Helm**: Patroclus anywhere on the board (no range check); after the swap he takes the blow with the card's 2 as the defender, his AFTER effects included. The bot decides with the same rule as Smoke And Mirrors (whoever loses less takes the blow), and Patroclus' fall is priced in his kill value.
5. **The Day of Your Doom**: Patroclus plays it (it is his band), so the 2 damage is to the fighter that plays it. It may defeat him: Achilles then discards 2 random cards and arms himself.
6. **Spear Throw**: any opposing fighter in a zone of Achilles' space (his own space included); with several, the owner chooses; with none the scheme is played for nothing.
7. **Battle Hardened**: any card of the owner's discard pile; the card just played is not in the pile yet, so it cannot choose itself. When the pile holds a single card it is taken without asking (the table tells the human to pick it up).
8. **Achilles' Heel**: "gains 1 action" only counts while it is the opponent's turn (it is the engine's `gain_action`: a defense played on the opponent's turn gives them the action).
9. **Brothers In Arms**: Patroclus is checked when the AFTER runs (he may have fallen in this combat).

## Pending Ivan
1. **Does the +2 apply to the second attack of Test For Weakness?** Implemented as YES (the double-attack engine's reading, docs/combat-flow.md "Pending Ivan" 3: a hero's attack bonus passives apply to the second attack). With Patroclus down a Test For Weakness is 1+2 then 3+2.
2. **Does the draw ("if Achilles wins combat") count the second attack too?** Implemented as no: the card's `won/lost` is the first combat's (double-attack Pending Ivan 2), and the second combat has no effects of the attacker's. A WIN of the defender's second card would be that card's own.
3. **The draw when Achilles wins as the defender without playing a card** (he took no damage): the hero's own AFTER runs only in combats whose owner played a card (the interpreter's rule for every hero ability), so there is no draw there. Literally "if Achilles wins combat" would draw.

## AI
- `sparring/ai_achilles.py`: **the fall of Patroclus is a trade.** `fall_net` = edge (+2 on every attack and a draw per win, 3.0 hit-point weights) minus 1.2 per card he is about to throw away (at most 2): it is subtracted from `kill_value`, so a bot with Achilles weighs his own sidekick's death as a small prize or loss (more cards in hand, a smaller edge) and a bot facing Achilles values the kill of Patroclus less. The search leaf (`search.adapter._vengeance`, in both evaluations) adds `LEAF_EDGE` (0.4 of a life) to an Achilles whose Patroclus is down; the discard is not priced there, the engine already took the cards out of the simulated hand.
- Measured with the search AI (`make_bot("ismcts", iterations=40)`, 8 games as Achilles against the scripted chasing Hellboy, bot player 0): with the edge at 0 one game was won and Patroclus fell in 4; at 0.12 three were won; at 0.3 five; at 0.5 six and Patroclus fell in 7 of 8. Chosen 0.4. Sanity checks against a scripted rival, not a balance statement.
- `The Day of Your Doom`: `card_value` is 5 when the bot will pay (`doom_pays`: the extra points of blow against the hit points it costs Patroclus, the fall counted when it kills him).
- Under Achilles' Helm: `EffectAI._swap_combatant` (shared with Houdini, Luke Cage and Washington) through `kill_value`.

## Tests
`tests/test_hero_achilles_data.py` (data and card identity), `tests/test_achilles_effects.py` (the ability, every card, the double attack), `tests/test_achilles_human.py` (FakeTTS, the panel: the random discard, +2, the draw, the Helm Yes/No, The Day of Your Doom, Spear Throw, Battle Hardened, Test For Weakness in both directions), `tests/test_achilles_ai.py` (the AI's pricing and the leaf), `tests/test_achilles_matrix.py` (full games against 31 heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
