# Dr. Jill Trent, Science Sleuth (Adventures: Tales to Amaze)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 348 on sheet 3) on 2026-11-08. Verified on FakeTTS only: nothing of Jill Trent has been seen on a real table (see `docs/live-checklist.md`).

## Summary
- Melee hero, 13 life, move 2. Sidekick **Daisy**: one, melee, 6 life, move 2 (fid `daisy`). Hero fid `jill`. The hero card prints the move once (2) for both. Project slug `jill-trent` (unmatched-memory: `dr-jill-trent`; the catalog files her as `dr-jill-trent-science-sleuth`, which is also the name of her bag in the save).
- Ability **GADGETOLOGY** (two paragraphs on the card): "At the start of your turn, activate one of your gadgets." and "Whenever Jill Trent attacks, resolve the active gadget's effect." The two gadgets are not on the character card; their texts come from unmatched-memory (the Ultrabiotic Tonic token in her bag carries the same text as the Tonic below):
  - **Hypnoray Blaster**, DURING COMBAT: if your card's printed value is lower than your opponent's, reveal the top card of your opponent's deck. Increase the value of your attack by the BOOST value of the revealed card.
  - **Ultrabiotic Tonic**, AFTER COMBAT: if your card's printed value is higher than your opponent's, Jill Trent recovers 1 health.
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176), restriction bands JILL TRENT, DAISY and ANY. The deck object of the save holds 31 cards (the 30 plus the character card `348`).
- Table: Jill's miniature `448a24` (Custom_Assetbundle) and dial `9bb234` (max 13); Daisy's token `0bf463` and dial `e10c99` (max 6); bag `55b9e4` (inner `35d821`), deck `f918b9`. The inner bag also holds a gadget token `8af285` (the Ultrabiotic Tonic face), the hero token `gadget` (`token_names` in the overlay; see "Gadget token on the table"). **Daisy's token has the same GUID as Abe Sapien's agent Carla** (`0bf463`): told apart by name, docs/card-identity.md "Piece identity". **She shares CardIDs 17600-17629 with Medusa, the turtles, Doctor Strange, Bigfoot and the Marvel decks**: told apart by deck image and owner (docs/card-identity.md). `tests/test_jill_trent_matrix.py` plays her against every other hero in both seats.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Who | Effect |
|---|---|---|---|---|---|---|
| Battle of Wits | attack | 2 | 4 | 3 | Jill | AFTER: reveal the top card of both decks; if yours has the higher BOOST, 3 damage to the opposing fighter |
| Energizing Spray | attack | 5 | 1 | 2 | any | AFTER: gain 1 action |
| Utility Belt | versatile | 3 | 3 | 3 | Jill | AFTER: choose one: Jill recovers 1 / move Jill exactly 1 space / draw 1 |
| Stasis Diffuser | versatile | 3 | 1 | 2 | any | IMMEDIATELY: the opponent's card is worth its printed value and nothing changes it (`lock_value`) |
| Laser Pen | versatile | 2 | 2 | 3 | any | AFTER: 1 damage to the opposing fighter |
| Insightful Deduction | versatile | 3 | 2 | 2 | any | AFTER: reveal the top 3 cards of the opponent's deck, one to the bottom, the rest on top in any order |
| Caught Red-Handed | versatile | 1 | 2 | 2 | any | AFTER: the opponent discards 1 card (2 if you won) |
| Gyroscopic Jetpack | versatile | 4 | 2 | 3 | any | AFTER: move your fighter up to 2 spaces, through opposing fighters |
| Ace Fighter | versatile | 5 | 3 | 2 | Daisy | AFTER: draw 1 |
| Sisters in Arms | versatile | 3 | 1 | 2 | Daisy | cannot be canceled; Daisy attacking with Jill adjacent resolves the active gadget |
| Hypnotist | defense | 3 | 1 | 2 | Jill | IMMEDIATELY: with the Hypnoray Blaster active, cancel all effects on the opponent's card |
| Indestructible Cloth | defense | 5 | 2 | 2 | any | IMMEDIATELY: this combat, your fighter takes no damage from effects |
| Helpful Assistant | scheme | - | 3 | 2 | Daisy | shuffle up to 3 Jill Trent cards from the discard pile into the deck; draw 1 |

## Discrepancies with unmatched-memory
- Type, value, boost and copies of the 13 titles agree with the images; the restriction bands (JILL TRENT / DAISY / ANY) are not in unmatched-memory (read from the images).
- Utility Belt is printed as three bullets (`Jill Trent recovers 1 health`, `move Jill Trent 1 space`, `draw 1 card`); unmatched-memory joins them in one line. The HeroDef keeps unmatched-memory's text; the labels of the panel buttons are the card's.
- The character card has no gadget text: the two gadgets are on physical gadget cards (a token of one of them is in the bag), whose text is unmatched-memory's `specialAbility`.

## Engine additions (all additive, docs/effects-dsl.md section 33)
`ability.after` (the hero's own AFTER effects, next to `ability.during`), the op `lock_value` (`CombatFlow.value_locked`), the status expiry `after_attack`, the `tag` of `choose_effect`, the plugins of `plugins_jill.py` (`jill:hypnoray`, `jill:reveal_tops` with its test `higher_boost`, `jill:insightful_deduction`), the table intents `reveal_top` and `deck_order` (`session_jill.py`; the bot's reorder of the human's deck is `lua.deck_reorder`), the reading of the top N cards of the human's deck (`Game.deck_reader(player, n)`, `lua.peek_deck_top(count=N)`), the bot's judgement of the gadget (`EffectAI._gadget`), `token_names` for the importers and `table.start_of_turn_is_physical` no longer counting a trigger made only of `optional`, `draw`, `choose_effect` and `counter`.

## Rules decisions (the user is away: the most literal reading, applied)
The doubts that were open here were all answered by Iván on 2026-11-08 (see "Rule decisions" below).

1. **Gadget state**: the counter `gadget` (0 = none, 1 = Hypnoray Blaster, 2 = Ultrabiotic Tonic). At the start of each of her own turns she activates exactly one (mandatory; the other is switched off), so before her first turn (her side plays second) no gadget is active. **Duration (Iván asked for the literal card text, 2026-11-08)**: the gadget chosen at the start of HER turn stays active until the start of her next turn, so it is still active during the opponent's turn. Reason: Hypnotist is a DEFENSE card (played in the opponent's turn) and reads "If your active gadget is Hypnoray Blaster"; if the gadget were switched off at the end of her turn the card could never fire. Gadgetology itself only resolves the gadget "whenever Jill Trent attacks", which only happens in her own turn.
2. **"Whenever Jill Trent attacks"**: only Jill (never Daisy by herself), only when she attacks (never when she defends), with whatever card, effects cancelled or not: the gadget is on the hero, not on the card, so a Feint on her card does not stop it (the same ruling as Daredevil's BLIND BOOST, section 29). It resolves before the card's own effects of that moment.
3. **Printed value**: the number printed on the card, not the running value. A defender who played no card has a printed value of 0: Hypnoray never triggers against no card, the Tonic does (any card of hers is higher).
4. **Hypnoray Blaster**: the top card of the opponent's deck is revealed (the bot names it in the chat; the bot reads the human's real top card from the table only at that moment) and stays on top; its BOOST is added to the value of her attack. An empty deck reveals nothing.
5. **Ultrabiotic Tonic** heals the fighter that resolves it 1, up to its maximum: Jill when she attacks, Daisy through Sisters in Arms (Iván, 2026-11-08).
6. **Sisters in Arms**: Daisy attacking with Jill alive on an adjacent space resolves the active gadget: the printed value compared is the value of Sisters in Arms, the Blaster raises Daisy's attack, and the Tonic heals DAISY, who resolves it (Iván, 2026-11-08). The card cannot be canceled. If Jill is far, or Daisy defends, the card is a plain value 3.
7. **Hypnotist** cancels only while the active gadget is the Hypnoray Blaster; with the Tonic (or before any gadget) it is a plain defense of 3.
8. **Stasis Diffuser**: at IMMEDIATELY the opponent's total goes back to the printed value of their card (bonuses and extras so far are dropped) and the side is locked for the rest of the combat: value effects, BOOSTS and ONGOING bonuses of that side add nothing. The boost cards are still discarded and their own effects still run. No card against it: nothing.
9. **Indestructible Cloth** lasts exactly this combat (it expires when the combat is over, after every AFTER effect): no effect damage to the fighter that played it, from either side's effects (`immune_to_effect_damage`); combat damage lands as usual.
10. **Battle of Wits**: both top cards are revealed; the damage needs the owner's BOOST to be strictly higher; if either deck is empty there is nothing to compare. The cards stay on top.
11. **Insightful Deduction**: the owner (not the opponent) chooses which of the revealed cards goes to the bottom and the order of the others. With fewer than 3 cards it does what it can. The bot buries the card the rival would like most (`card_worth`) and puts the weakest on top. Against the human's real deck the bot reveals the three cards (the card says reveal: the chat names them, `reveal_top`) and **rearranges the real deck itself, blind** (Iván's decision, 2026-11-08): `lua.deck_reorder` checks that the top is still the cards read, sends the buried one to the bottom and puts the others back on top in the bot's order, face down, and the chat says only "he reordenado las 3 cartas superiores de tu mazo y he mandado 1 al fondo" (`order.blind_bottom`), never which one went where. If the top changed, nothing moves and the bot says so (`order.blind_failed`). The human's choices for the bot's deck are pinned (`Session.peek_pins`).
12. **Utility Belt** is a JILL TRENT-band card, so only Jill plays it; its effects name Jill. "Move Jill Trent 1 space" is exactly 1 (with no space exactly 1 away the move is cancelled, as every "exactly N" move).
13. **Helpful Assistant**: "Jill Trent cards" are the cards of her own band (JILL TRENT: Battle of Wits, Utility Belt, Hypnotist), not the ANY cards nor Daisy's; up to 3 of them in the discard pile (the card just played is not in it yet).
14. **Caught Red-Handed**: the opponent chooses what to discard (the bot with its usual judgement, the human at the panel); 2 cards if the owner won the combat, 1 if not.
15. **Gyroscopic Jetpack**: "your fighter" is the fighter that played the card (Jill or Daisy).
16. **Laser Pen** and **Battle of Wits** hit the opposing fighter of the combat only if it is still alive.

## Rule decisions (Iván, 2026-11-08)
- **Combat win (global, 2026-11-07/08)**: the DEFENDER wins when its defense value is >= the attack value; the ATTACKER wins only if the attack value is > the defense value. Caught Red-Handed ("2 cards if you won") reads the engine's result; tests in `tests/test_jill_trent_ties.py`.
- **Gadgets**: exactly one gadget is active, chosen at the start of Jill's turn; none before her first turn. It lasts until her next turn (see rule 1 above for the reading and why).
- **Bot choice of the gadget**: the Hypnoray Blaster almost always (Iván's own play: about 99 %). The Ultrabiotic Tonic only when the bot expects to attack WITH JILL this turn (she is alive, holds a card she can attack with and can reach an opposing fighter after moving) AND either the rival cannot defend (an empty hand, or a hand the bot has seen whole with no defense card in it; only legitimately known information) or Jill holds Energizing Spray (the 5). Replaces the older heuristic (heal when hurt, Blaster with a Hypnotist in hand).
- **No card from the opponent counts as value 0** in every gadget comparison (decided, applied consistently: the Tonic's "higher than" fires, the Blaster's "lower than" never does, Daisy through Sisters in Arms included). Test in `tests/test_jill_trent_ties.py`.
- **Stasis Diffuser** also freezes the opponent's value against BOOSTS (decided, current behaviour).
- **Sisters in Arms and the Tonic**: DAISY heals, not Jill (changed).
- **Cancellation**: the gadget effects still apply when Jill's card is cancelled (decided, current behaviour).
- **Utility Belt** moves EXACTLY 1 space, never 0 (decided, current behaviour).
- **Gyroscopic Jetpack**: "your fighter" is the fighter that played the card (decided, current behaviour).
- **Helpful Assistant** recovers ONLY cards with the JILL TRENT band (decided, current behaviour). Bot AI: it prefers returning Utility Belts (`EffectAI._cards`, own discard back into the deck).

## Open questions for Iván
None. All closed by Iván on 2026-11-08 (see the decisions above): a missing card counts as value 0; Stasis Diffuser against BOOSTS; the Tonic through Sisters in Arms; gadgets after a cancellation; Utility Belt's move; Gyroscopic Jetpack's fighter; Helpful Assistant's band; Insightful Deduction against the human (the bot moves your cards itself, blind: rule 11).

## AI
- The profile comes from the data (Jill `hero`, Daisy `striker`; exclusive cards: Battle of Wits, Utility Belt and Hypnotist for Jill; Ace Fighter, Sisters in Arms and Helpful Assistant for Daisy).
- The gadget (`EffectAI._gadget`, the request carries the tag `gadget`): the Hypnoray Blaster, except the Tonic when she is expected to attack and the rival cannot defend or she holds Energizing Spray (see "Rule decisions (Iván, 2026-11-08)").
- Card hints in `ai_medusa.AFTER_BONUS`: Energizing Spray (the action), Utility Belt, Battle of Wits, Laser Pen, Insightful Deduction, Caught Red-Handed, Gyroscopic Jetpack, Ace Fighter. Hypnotist, Stasis Diffuser, Cloth and Helpful Assistant are valued by simulating their ops like the other heroes' schemes and defenses.
- The bot's Insightful Deduction buries the best card of the rival's top three and leaves the weakest on top.

## Gadget token on the table (Iván's decision, 2026-11-08)
The active gadget must be VISIBLE on the table, not only said in the chat. Her bag holds ONE token, `8af285` (Custom_Token, no nickname, a single face: the Ultrabiotic Tonic with its AFTER COMBAT text). The character card (CardID 348, sheet 3, index 48, read from the image on 2026-11-08) prints only GADGETOLOGY, so it does NOT print the Hypnoray Blaster and there is no Blaster piece.
- **Convention**: the token lies ON Jill's character card while the Tonic is the active gadget; BESIDE the card when the Blaster is active or no gadget is (before her first turn). The two places per side are `token_slots.gadget.<side>` in `data/tts/jill-trent.json` (index 0 beside, 1 on the card), derived from the `character_card` slot of that side in `config/table.json` `layout` (the same in every entry of `config/map_setups.json`, checked by a test): on the card = its x and z at y + 0.12; beside = past the deck, away from the map (bot 4.98, 1.76, 21.1, where Iván put it live on B.P.R.D. HQ on 2026-11-08: the first guess, 2.6 units toward lower z, lay under the board; human -6.6, 1.76, 21.17, its mirror); rot Y the card's (90 bot, 270 human), rot Z 0 (face up). The on-card spot, the human's beside spot and the rot Z are still not checked live (`docs/live-checklist.md`).
- **Moves**: `sparring/session_gadget.py` compares the engine counter `gadget` (0 none, 1 Blaster, 2 Tonic) with what it last showed, at every step, game start, restart and resume, and when it differs writes `lua.move_token` (`setPosition` + `setRotation`, instant, messageID 3 through the normal write queue, never the Global UI). Whoever plays Jill: the bot's AI choice and the human's panel choice both end in the counter. The chat line that announces the gadget is unchanged. The `counter` translator skips this token (`PLACED_TOKEN`): it is moved, never copied like Abe's.
- **Lifecycle**: Prepare puts it beside the card (the layout's token slot 0, like every other hero token, through `table_layout.plan`); the first look of a game or a resume always writes, so `--resume` re-places it from the saved counter; Clean table removes it by GUID with the other hero pieces (`all_guids`); the gate recognises her bag with it (it is a normal token of the hero, `unpack_items`, `all_guids`).
- **Safety**: a token that is not on the table (the player removed it) is said once per game in the chat (`gadget.token_missing`) and the game carries on; nothing waits for it. A failed write is a different line (`gadget.write_failed`, once per game) and the move is retried at the next step.
- **Importers**: the overlay's `token_names` ({GUID: name}) makes `tools/import_hero.py` write it to the HeroDef and `tools/import_save.py` file the nameless token under `tokens.gadget`; `token_slots` is kept on a re-import like Abe's.

## Human side
- Buttons appear only when asked (never greyed): the two gadgets at the start of your turn, Utility Belt's three options, the card for the bottom and the order for Insightful Deduction, the up-to-3 cards of Helpful Assistant. Every choice is a parked run saved with the game and survives `--resume`.
- The chat names every revealed card (Hypnoray Blaster, Battle of Wits, Insightful Deduction) with `Reveladas arriba de mi mazo` / `Reveladas arriba de tu mazo`.

## Tests
`tests/test_hero_jill_trent_data.py` (data, card identity, detection, piece GUIDs), `tests/test_jill_trent_ties.py` (tied combats, attack and defense), `tests/test_jill_trent_effects.py` (the ability and every card on the interpreter, bot side), `tests/test_jill_trent_human.py` (FakeTTS panel: the gadget choice, Hypnoray, Utility Belt, Insightful Deduction in both directions, the pins, the blind reorder with no title in its line), `tests/test_jill_trent_lua.py` (the read of the top N cards on the Lua stub), `tests/test_jill_gadget_token.py` (the gadget token: places, set-up, bot and human seat, resume, missing token, Clean table, the Lua of the move, re-import), `tests/test_jill_trent_matrix.py` (full games against the fifteen other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).

## Revealed cards are shown large (Ivan, 2026-11-08, global)
"Reveal" in a card text means every player sees those cards. Wired here: Hypnoray Blaster (and Sisters in Arms), Battle of Wits (both top cards in one row) and Insightful Deduction (the three cards are shown BEFORE the owner decides, once). The bot lays a large face-up copy of each revealed card side by side over the board (`reveal_spot`, `reveal_scale`, `reveal_step` in `config/table.json`), they stay until the human presses **Stop revealing** on the panel (hidden when nothing is revealed, never greyed out) and play carries on meanwhile. A new reveal replaces them; New game, Restart, Clean table and `--resume` remove them. The originals never move and no deck order is touched. The chat still names the cards (a reveal is public). Looking is not revealing: in Insightful Deduction the bury and the reorder of the human's deck are done blind by the bot (`lua.deck_reorder`): the shown copies stay in the order the cards were revealed, never the new order, and the chat only counts the cards reordered. See `sparring/session_reveal.py`.
