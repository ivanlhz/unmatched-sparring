# Tomoe Gozen (Sun's Origin)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 354 on sheet 3) on 2026-11-08.

## Summary
- Ranged hero, 14 life, move 2, **no sidekick** (unmatched-memory has an empty sidekick entry, ignored). Hero fid `tomoe`, slug `tomoe-gozen`.
- Ability **ATTACK OF OPPORTUNITY**: "When an opposing hero leaves Tomoe Gozen's zone, deal 1 damage to that hero." (unmatched-memory appends the flavour quote "If only I could find a worthy foe."; the overlay drops it). It is an ability trigger on the new event `left_zone` (docs/effects-dsl.md, section 35).
- Deck: 30 cards, `CardID = 17600 + idx`, every card on the TOMOE GOZEN band (none ANY). The deck object in the save holds 31 cards (the 30 plus the character card 354), hence `card_count 31` in the catalog (`card_ids [354, 17629]` there is the min and max of those 31).
- Table: bag `c5fe82` (inner `5b6a57`), miniature `66c85f`, life dial `ca8e35` (max 14), deck `abfd59`. **The dial GUID `ca8e35` is also Donatello's** (and Chupacabra's and Little Red's in the save): the third cross-hero GUID collision, told apart by the dial's name (`session_pieces.resolve_dials`, docs/card-identity.md "Piece identity"; `tests/test_piece_identity.py`). Her matrix against Donatello in both seats is the proof on FakeTTS.

## Card identity: the shared CardID range
Her deck is sheet 176 like Medusa's, the four turtles', Doctor Strange's, Bigfoot's, Daredevil's, Luke Cage's and Bullseye's: the same CardIDs 17600-17629, a different image (`data/tts/tomoe-gozen.json`, `deck.identity`). Everything in docs/card-identity.md applies; the proof is `tests/test_hero_tomoe_gozen_data.py` (ranges equal, images disjoint from the other ten, no card equal across decks, detection in both seats against all fifteen, catalog entry, the shared dial GUID), `tests/test_card_identity.py` (she is in `SHARING`) and `tests/test_tomoe_gozen_matrix.py`.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| Witness My Last Battle | attack | 7 | 4 | 2 | Can only target a fighter adjacent to her; played face up; AFTER: end the turn |
| Piercing Shot | attack | 2 | 1 | 3 | AFTER: draw 2 |
| A Warrior's Way | attack | 2 | 1 | 2 | AFTER: move the opposing fighter up to 3; if it is a hero, place her adjacent to it |
| Five Against Thousands | attack | 4 | 1 | 2 | AFTER: if adjacent to the opposing fighter, you may discard a card to put this card back into your hand |
| Fearsome Strength | attack | 3 | 1 | 2 | IMMEDIATELY: may swap with an adjacent fighter; AFTER: 1 damage to an adjacent fighter |
| A Worthy Opponent | versatile | 3 | 3 | 3 | DURING: against a hero the value is 5 |
| Confront Any Demon or God | versatile | 3 | 3 | 2 | AFTER: draw 1; if you lost, look at the opponent's hand and choose 1 card for them to discard (Hellboy's card, word for word) |
| Skirmish | versatile | 4 | 1 | 3 | AFTER: if you won, choose one of the fighters in the combat and move it up to 2 (Bigfoot's card, word for word) |
| Flash of Steel | versatile | 2 | 1 | 3 | IMMEDIATELY: against a hero, cancel all effects on the opponent's card; AFTER: if the opposing fighter is adjacent, 1 damage to it |
| Refuse to Retreat | defense | 3 | 2 | 2 | IMMEDIATELY: she cannot leave her space for the rest of the turn; AFTER: if the opposing fighter is adjacent, the opponent discards 1 card |
| Deeds of Valor | defense | 2 | 2 | 3 | DURING: she cannot take more than 2 combat damage this combat |
| Lord Kiso's Final Stand | scheme | - | 2 | 3 | Move her up to 3 (through sidekicks), then choose one: she recovers 2 health / gain 1 action |

## Discrepancies with unmatched-memory
- The ability: unmatched-memory adds the quote "If only I could find a worthy foe." under it; the card prints it as flavour text apart from the ability. The overlay carries the ability only.
- Titles, types, values, boosts, copies and texts of all 12 titles match unmatched-memory (Skirmish and Confront Any Demon or God are word for word the cards of Bigfoot and Hellboy).

## Engine additions (all additive, docs/effects-dsl.md section 35)
The event `left_zone` (`Game.departed(..., moved=True)` raised by `walk` and the table sync of a hand move; `place_fighter`, the `place` and `swap` ops pass `moved=False` and raise nothing); the card flags `adjacent_only` and `face_up` (`Game.attack_card_reaches`, `check_attack_target`); the op `cap_combat_damage` (`CombatFlow.damage_caps`); the `move` parameter `through_sidekicks` (`through` = `"sidekicks"`, `Board.reachable(passable=)`); `put_in_hand` of a card played in the running combat. The search's determinization now puts a face-up attack into the attacker's sampled hand (a latent gap that Witness made reachable).

## ATTACK OF OPPORTUNITY
- "Leaves her zone": the opposing hero stood in a zone of her space (the colored areas of the map: `Board.share_zone`) before the move and shares none with it after. Adjacency alone is not a zone. A fighter in two zones of hers stays "in her zone" while it keeps one.
- Only a MOVE counts (Iván, 2026-11-08), whoever causes it: its own Maneuver or hand move, the bot's or the human's effects that move it (her own A Warrior's Way and Skirmish included, the rival's own move effects). A PLACEMENT (the `place` op, `place_fighter`, a teleport such as Bullseye's Tactical Retreat) or a SWAP (with her or anyone) does NOT fire it. A hand placement by the human (a piece in `Game.placing`, or Houdini's ESCAPE ARTIST boosted Maneuver, `Session._escape_artist_placing`) is read as a placement. Her own movement never fires it. Sidekicks never trigger it (the card says "opposing hero"). 1 damage of effect damage per departure, so it can be prevented by effect immunities and it can defeat the hero.
- Human side: a move by hand is read at the next button (Maneuver, End action...): the engine compares the two ends, the chat says "ATTACK OF OPPORTUNITY: ... loses 1 HP" and the life dial is written at once (`Session._departed_by_hand`). Bot side: the bot's own moves go through the engine and it prices the damage (`MedusaAI.hazard_cost` / `exit_cost`, like a hazard edge).

## Rule decisions (Iván, 2026-11-08)
- **ATTACK OF OPPORTUNITY** fires when the enemy hero is MOVED out of her zone, including by a rival's or her own effect; it does NOT fire on a placement or a swap (changed: `Game.departed(moved=False)`). Tests: `tests/test_tomoe_gozen_rules.py`.
- **Tomoe moving away** does not fire it (decided, current behaviour).
- **Refuse to Retreat**: the pin also protects her from the rival's effects moving her (decided, current behaviour; tested).
- **A Warrior's Way**: the moved opposing fighter MAY move through fighters of its own side. The engine's general rule already lets any mover cross its own side's fighters (`Board.reachable` passes `own`); the old card note wrongly said it could not, so only the note was fixed and a test now pins it. No move flag was needed. Its own side is the only side it crosses (rival fighters still need `through_enemies`).
- **Deeds of Valor**: the cap applies only to combat damage that lands on her (decided, current behaviour).
- **Combat win (global, Iván 2026-11-07/08)**: the attacker wins only if combat damage lands (Luke Cage's text makes the difference explicit); a tie or no damage = the defender wins. Every "if you won / lost" of this hero reads the engine's result (`CombatFlow.won_by`), with no card-side handling of ties; tied-combat tests in `tests/test_tomoe_gozen_ties.py`.

## Earlier rules decisions (the user was away: the most literal reading, applied)
1. ATTACK OF OPPORTUNITY is as described above: only a MOVE out of her zone, by any cause; never a placement or a swap. 1 effect damage each, only heroes, her own moves excluded.
2. Witness My Last Battle: "adjacent" is the printed adjacency of the map (not a shared zone, not secret passages). The restriction is checked when the attack is declared (the human's Reveal, `Game._declare_attack`) and the bot never offers the card against a target out of reach. "Play it face up" makes it public information: the bot defends seeing it (like UNCANNY INTUITION's attack); the human lays it face up (or the Reveal flips it) and the bot's card is flipped on the table. The AFTER ends the turn whether she wins or loses (no actions are lost beyond the ones left); a cancelled card (Feint) does not end it.
3. Deeds Of Valor: the combat damage that lands on her is at most 2 for this combat only; effect damage and exhaustion are not capped; Luke Cage's reduction (not hers) applies first if both exist.
4. A Worthy Opponent: "the opposing fighter is a hero": the printed 3 becomes 5, bonuses stay; against a sidekick it stays 3 (attacking or defending).
5. Fearsome Strength: the swap is optional and with any adjacent fighter (the opposing one or a rival sidekick); the 1 damage of the AFTER is to an adjacent fighter she chooses, measured after the swap; it is effect damage.
6. Five Against Thousands: "adjacent to the opposing fighter" is read at the AFTER (a defeated opposing fighter is not adjacent). The price is any card of the hand (a scheme included); with an empty hand it cannot be paid. The card played goes back to the hand instead of the discard pile, and the rival knows it is there (it was face up).
7. A Warrior's Way: the owner chooses where the opposing fighter goes (up to 3, 0 included; it may cross fighters of its own side, like any move). If it is a hero (and survived) she is then placed on a free space adjacent to it, a teleport. The move can fire ATTACK OF OPPORTUNITY on the rival (it happens before she is placed).
8. Refuse to Retreat: "the rest of the turn" is the current turn, whoever's it is; the pin (`cannot_leave_space`) also stops the rival's effects from moving her. A cancelled IMMEDIATELY does not pin her. The rival chooses which card they discard (Clutching Claws' rule) at the AFTER if the opposing fighter is adjacent.
9. Lord Kiso's Final Stand: "through sidekicks" is any sidekick, hers (none) or the rival's, never a rival hero; she ends on an empty space; up to 3 includes 0. The choice (heal 2 or gain 1 action) comes after the move; the scheme costs its action first, so gaining 1 action nets zero.
10. Confront Any Demon or God and Skirmish: exactly the rulings already taken for Hellboy's and Bigfoot's cards.
11. Flash of Steel: both halves only against a hero (the cancel) or an adjacent fighter (the damage, read at the AFTER).

## Open questions for Iván
None. Closed on 2026-11-08: departures by effect (yes, moves; placements and swaps no), Tomoe moving away (no), Witness My Last Battle's adjacency (printed adjacency), Refuse to Retreat's pin (yes), A Warrior's Way's crossing (own side yes), Deeds Of Valor's cap (only combat damage that lands on her).

## AI
- The AI profile comes from the data (Tomoe Gozen `hero`, ranged: the importer's `ai_profile`). Name-based values live in `ai_medusa.card_value` / `attack_outcome` / `eval_defense` like the other heroes': A Worthy Opponent is worth 5 against a hero (attacking and defending), Deeds Of Valor caps the expected damage of a defense at 2, Witness My Last Battle is charged the actions the turn will lose (`ACTION_VALUE` per action left after the attack), and `AFTER_BONUS` prices the draws, damage and moves of Piercing Shot, A Warrior's Way, Five Against Thousands, Fearsome Strength, Flash of Steel and Refuse to Retreat (Confront Any Demon or God and Skirmish are left at 0 like Hellboy's and Bigfoot's: the same titles).
- Five Against Thousands' optional price is decided by `EffectAI._returns_card_pays`: the card comes back when it is worth more to keep than the least useful card of the hand. Lord Kiso's choice (heal / action) and Fearsome Strength's swap go through the generic simulation of `EffectAI` (a heal when she is hurt, the action otherwise).
- The bot never plays Witness against a fighter that is not adjacent (`MedusaAI.attack_acts`, the search's `_attack_titles`).
- Against her the bot prices leaving her zone (`MedusaAI.exit_cost`, `hazard_cost`): its Maneuver destinations and the destinations of its effects count the 1 damage and prefer to stay in her zone or end up out of it only when it pays.

## Strength (simulator, heuristic AI, bprd-hq, seeds 0-19)
Bot's Tomoe Gozen against each scripted rival (`python -m sparring.sim`, the rival chases and attacks with its best card), 20 games each: 259 wins to 41 losses over 15 rivals (Medusa 15-5, Hellboy 14-6, Abe 18-2, Baba Yaga 20-0, Liz 17-3, Leonardo 20-0, Donatello 20-0, Michelangelo 13-7, Raphael 10-10, Doctor Strange 19-1, Houdini 20-0, Bigfoot 19-1, Daredevil 19-1, Luke Cage 16-4, Bullseye 19-1). The matrix proves every pairing plays to game over with no errors and no stalls.

## Tests
`tests/test_hero_tomoe_gozen_data.py` (data and card identity), `tests/test_tomoe_gozen_effects.py` (the ability on the engine, every card, the damage cap across a save, the search regression, the AI's pricing), `tests/test_tomoe_gozen_human.py` (FakeTTS, the panel: Witness refused / face up / bot defense, Deeds Of Valor, Lord Kiso's Final Stand, Five Against Thousands, ATTACK OF OPPORTUNITY on a human hero that walks out by hand with the dial written), `tests/test_tomoe_gozen_matrix.py` (full games against all fifteen heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
