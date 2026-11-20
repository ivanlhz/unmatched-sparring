# Bloody Mary (Battle of Legends, Volume Two)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 321 on sheet 3) on 2026-11-20. Verified on FakeTTS only: nothing of Bloody Mary has been seen on a real table (see `docs/live-checklist.md`).

## Summary
- Melee hero, 16 life, move 3. **No sidekick**: unmatched-memory lists "Patroclus" (flagged `hasSidekicks: false`; he is Achilles' sidekick) but the hero card names none and the savegame has a single miniature (GUIDs `98d2b5` piece, `51c4a7` dial, both named Bloody Mary). Hero fid `mary`.
- Ability: "At the start of your turn, if you have exactly 3 cards in hand, gain 1 action." A start-of-turn trigger of the effects file (`three_cards_one_action`, a `hand_size == 3` condition and `gain_action 1`), run by the engine for the bot and for the human (the table does nothing by hand: `table.start_of_turn_is_physical` treats a trigger that only gains an action as the engine's).
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176), every card under the BLOODY MARY band (none ANY). The deck object of the save holds 31 cards (the 30 plus the character card `321`).
- Table: bag `a3a6c6`, deck `48a6aa`. **She shares CardIDs 17600-17629 with Medusa, the turtles, Doctor Strange, Bigfoot, Daredevil (22 cards), Luke Cage and the other sheet-176 heroes**: her deck is told apart by deck image and owner (docs/card-identity.md), never by a bare CardID. `tests/test_bloody_mary_matrix.py` plays her against every other hero in both seats.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| Speak Three Times | attack | 3 | 2 | 2 | DURING: value 7 if this is your third action this turn |
| Bloody Requiem | attack | 3 | 4 | 3 | DOUBLE ATTACK. AFTER: BLOODY REPRISE, a second attack worth the printed value of the card the opponent played against it |
| Out Of The Mirror | attack | 1 | 2 | 2 | DURING: the opponent discards a random card, add its BOOST. AFTER: draw 1 if this is your third action |
| Ghostly Touch | attack | 1 | 2 | 2 | DURING: you may BOOST this attack. AFTER: recover 3 health if this is your third action this turn |
| Feint | versatile | 2 | 2 | 2 | IMMEDIATELY: cancel all effects on the opponent's card |
| Jump Scare | versatile | 3 | 2 | 2 | DURING: value 6 if she shares no zone with the space she started the turn in |
| Infinity Mirror | versatile | 4 | 2 | 2 | AFTER: choose one fighter in the combat, move it up to 4 spaces |
| Broken Glass | versatile | 3 | 2 | 3 | DURING: you may add or take 1 from the value. AFTER: if the value matches the opponent's card, draw 1 and the opposing fighter takes 2 |
| Trick of the Light | versatile | 2 | 3 | 3 | AFTER: you may place her in any empty space adjacent to the opposing fighter |
| Evade | defense | 3 | 1 | 3 | AFTER: draw 1 |
| Mirror Image | defense | 0 | 2 | 2 | DURING: its value is the printed value of the opponent's card |
| Closer Than She Appears | scheme | - | 2 | 2 | Move her up to 1 space, draw 1, gain 1 action |
| Stolen Memories | scheme | - | 3 | 2 | Look at the opponent's hand, choose a card: they discard it or their hero takes damage equal to its BOOST |

## Discrepancies with unmatched-memory
- **Closer Than She Appears** reads "Move **Bloody Mary** up to 1 space" on the card; unmatched-memory says "Move your fighter" (the same: she is the only fighter). The HeroDef carries the card's text.
- "Patroclus" (unmatched-memory's sidekick entry) is Achilles' sidekick; not on her card or in the save; ignored (overlay `sidekicks: []`).
- Type, value, boost and copies of the 13 titles agree with the images; restriction bands are not in unmatched-memory at all.

## Collisions found in the save
- **CardIDs 17600-17629** shared with the other sheet-176 decks. Solved as for them: `data/tts/bloody-mary.json` carries its own `deck.identity` and every lookup is per owner; `tests/test_hero_bloody_mary_data.py` pins that no card is equal to a card of another deck of the range and that the images differ.
- **A card taken from the rival's hand and bound with `as` (Stolen Memories' `$memory`)** used to be looked up in the CASTER's deck first, and with shared CardIDs that is another card: its BOOST was read off the wrong card (found by `tests/test_bloody_mary_effects.py`). Fixed in the shared interpreter: `EffectRun.bind(..., owners=)` records whose deck each bound id belongs to (`choose` and `discard` do) and `select.card_ref` honours it. Out Of The Mirror reads the card object itself (the plugin), like Chupacabra's Ambush.
- No piece GUID is shared with another hero (pinned in `tests/test_hero_bloody_mary_data.py`).

## Rule decisions
The most literal reading, applied. Each point Ivan has not ruled is under "Pending Ivan".

1. **"Third action this turn"** (Speak Three Times, Out Of The Mirror, Ghostly Touch) is `actions_taken_this_turn == 3`: the number of actions the owner has SPENT this turn, the one this card is played with included. Every kind of action counts (Maneuver, attack, scheme, a free action to attack), and a granted action counts once it is spent, not when it is gained. So with the base two actions she reaches a third only through Closer Than She Appears (it spends one action and gives one back, and it still counts as taken), and with the ability (3 cards at the start of the turn) the third action is the last one. A fourth action is not a third (`==`, not `>=`). The tally is `fx.taken` (the same one Pact Of Freedom's "first action" reads), reset at every start of turn and recorded for her because her effects name the stat.
2. **Ability**: the hand is counted when her turn starts, before anything else of the turn (before any draw), and the extra action is a normal `gain_action`: `cannot_gain_actions` and `no_gain_actions` stop it. It never fires on the rival's turn.
3. **Mirror Image** copies the PRINTED value of the opponent's card: not what a boost, a bonus (Golden Bat's +2) or an effect added to it. With no opposing card it is 0 (a defense always meets an attack, so this does not happen).
4. **Broken Glass**: the choice is +1, -1 or nothing (never below 0), made in the DURING. The AFTER compares the two cards' TOTAL values in this combat (printed value, boosts and bonuses, the DURING choice included) and needs the opponent to have played a card (no card: no match, even at 0). A match draws 1 card and deals 2 effect damage to the opposing fighter.
5. **Out Of The Mirror**: the discard is random and public; for the human it is the position the bot names (the Ambush flow: they lay that card on their discard pile and the bot reads which card it was). A rule that forbids forced discards leaves nothing discarded and nothing added; an empty hand adds 0.
6. **Stolen Memories**: she looks at the whole hand (the only time the bot reads the human's hand, and only when this scheme resolves), names one card, and the rival chooses: discard it, or their HERO takes damage equal to its BOOST (effect damage; the card stays in their hand). An empty hand asks nothing. When the bot plays it the human's panel reads "Discard <card>" / "Take <n>"; when the human plays it the bot's hand is laid face up in the row and the human pings a card.
7. **Jump Scare**: the same test as Golden Bat's Like a Flash of Golden Light. In defense "this turn" is the rival's turn and the space she started it on.
8. **Trick of the Light**: optional; the empty spaces next to the opposing fighter (her own is not empty, so she may also simply stay). Nothing happens if the opposing fighter was defeated.
9. **Infinity Mirror**: the owner picks ONE of the two fighters in the combat (the rival's too), won or not, and where it goes, up to 4 spaces (0 allowed).
10. **Feint**: cancels every effect of the opponent's card, a double attack's second attack included (it is an AFTER effect, docs/combat-flow.md "Double attack").
11. **Bloody Requiem**: a double attack. The first part is a plain attack of 3; BLOODY REPRISE is the second attack, worth the printed value of the card the opponent played against BLOODY REQUIEM (the card of the FIRST combat; 0 when they played none), written as `second_attack` with `{attr: value, of: opponent_card}`. The mechanic (who may defend the second attack, Feint, Skirmish) belongs to the double-attack engine (docs/combat-flow.md).
12. **No sidekick**: Bloody Mary has none. "Patroclus" (unmatched-memory) is Achilles'.

## Pending Ivan
1. **What counts as an action for "your third action"**: read as the third action SPENT this turn, whatever it was and however it was gained (point 1 above). Alternatives: only actions printed on the turn (the base 2 plus the ability's), or only attacks. Closer Than She Appears is the case that matters: it spends one action and gains one, and here it counts as the first of three.
2. **Is the third action an `==` or a `>=`?** A fourth action (two Closer Than She Appears, say) does not trigger "third action" cards here.
3. **Broken Glass**: "the value of this card matches your opponent's card" read as the two TOTAL values in the combat after the DURING choice, boosts and bonuses included; the alternative is the printed values.
4. **Mirror Image against a boosted or buffed attack** loses by the difference (it copies only the PRINTED value): read literally from "printed value of your opponent's card".
5. **Stolen Memories**: the damage is read from the BOOST of the card she named (not of a card the rival chooses); "their hero" is the opposing hero even when another fighter of theirs is next to her.
6. **Bloody Requiem's second attack** is worth the printed value of the card the opponent played in the first combat. If the opponent defends the second attack with a new card (docs/combat-flow.md, Pending Ivan 1-8 of the double attack), the value she copies is still the first card's.
7. **Which card the bot names with Stolen Memories** is the one the shared `choose` ranks highest (`card_worth`), not the card whose BOOST would hurt most; a better choice (high BOOST the rival cannot afford to take) is not implemented.

## AI
`sparring/ai_mary.py`, called by the heuristic (`ai_medusa`) and by the search (`search/adapter`); `tests/test_bloody_mary_ai.py` runs both (`make_bot_ai({"ai": "ismcts"})` is the one the live games use).
- **Plans the third action (Speak Three Times)**: the first version left it to the search and the search never found it: with three cards at the start of the turn (so three actions) and an undefended rival next to her, ISMCTS at 1500 iterations (about 1.7 s, the live budget is 3 s) played Speak Three Times first, for 3, in 4 seeds out of 4 (its rollouts play the cards of a turn in random order and the tree is flat to a difference of 4 damage). `ai_mary.holds_for_third` is a hard gate on the card, like `held_for_plan`: while this turn can still give her a third action (the actions taken plus the ones left plus the Closer Than She Appears in her hand that give one back) and no hero of the rival would be finished by its 3, the card is not an option; the bot spends the actions before it and plays it as the third for 7. Now both AIs maneuver first and deal exactly 7 in 8 seeds of 8 (heuristic and ISMCTS at 300 iterations; the cards the Maneuvers draw cannot attack in that position, so Speak Three Times is her only blow: with ordinary draws the bot may spend a drawn attack instead, which is also fine); with the gate removed 13 of the 26 tests of the file fail. The hold also ends when the Maneuvers before it would draw from an empty deck.
- **Figures** (the heuristic's `card_value` and `eval_defense`, the search through the engine): Speak Three Times 7 as the third action, Jump Scare 6 away from where she started the turn, Out Of The Mirror 1 plus the mean BOOST of the cards the rival may still hold, Mirror Image priced as the copy it is (the attack's printed value: only a bonus gets through), the AFTER of Evade (a card), of the third-action Out Of The Mirror (a card) and of the third-action Ghostly Touch (up to 3 hit points).
- **Tempo of the ability**: a hand of exactly 3 cards at the end of her turn is worth `EXTRA_ACTION_CARDS` cards of hand: the heuristic's `kept_hand_value` and the search leaf's `tempo` term (`EngineState._side_terms`), for either side (the bot counts the rival Bloody Mary's too). Measured as the share of her turn starts with exactly 3 cards in ISMCTS games against a scripted Hellboy (`sim.play`, 30 turns, turn starts counted on the live game only): at 60 iterations 20 % with no term (n=99), 24 % at 1.5 cards (n=101), 24 % at 4 (n=90), 37 % at 8 (n=101); at 300 iterations 19 % at 0 (n=75), 13 % at 1.5 (n=84), 22 % at 3 (n=77); at 1200 iterations (about the live budget) 24 % at 0 (n=54) against 34 % at 3 cards (n=59). So the term points the right way and gets stronger with the budget, but it is not significant at these sample sizes (about 1 sigma at 1200): the search's values are flat to a card or two, and only a weight of 8 cards moved the share clearly. It stays at 3 cards, the honest price of the action (one more blow, about 3 hit points), because a larger weight would make her skip attacks to keep a hand count. The planning that IS guaranteed is the hold of Speak Three Times above.
- **Broken Glass**: the choice is tagged `broken_glass`; the request carries the two totals of the combat (`values`, filled by `ops_core._choose_effect` for any tagged choice inside a combat) and `ai_mary.pick_broken_glass` takes the step that makes them equal (a draw and 2 damage), else the extra point. Without it the generic pick (`EffectAI._effect`: every option scores the same outside the combat) always took +1 and never matched on purpose.
- **Not done**: which card the bot names with Stolen Memories (the shared ranking `card_worth` takes the most valuable card, not the one whose BOOST hurts most); the decision log has no Mary-specific fields; the bot never holds Out Of The Mirror or Ghostly Touch for a third action (only Speak Three Times, whose 7 is worth the wait).

## Human side
- The human's turn with exactly 3 cards gets a third action with no button (the engine gains it at the start of the turn; the chat does not announce it yet).
- Stolen Memories by the human: the bot's hand is laid face up at `bot_row_spot` and the human pings a card; the bot answers discard-or-take with its evaluation (`EffectAI._discard_or_take`).
- Stolen Memories by the bot: the human's panel reads "Descartar <card>" / "Coger <n>" (`discards` and `else_damage` of the choice context, the BOOST read from the named card).
- Out Of The Mirror: the Ambush flow of Chupacabra and the Raptors.
- Closer Than She Appears and Trick of the Light: the human moves or places the miniature by hand and presses Done.

## Tests
`tests/test_hero_bloody_mary_data.py` (data, card identity, detection), `tests/test_bloody_mary_effects.py` (the ability and every card on the interpreter), `tests/test_bloody_mary_human.py` (the ability and the cards at the FakeTTS table, both seats), `tests/test_bloody_mary_matrix.py` (full games against every other hero in both seats).
