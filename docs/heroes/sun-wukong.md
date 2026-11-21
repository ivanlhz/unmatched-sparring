# Sun Wukong (Battle of Legends, Volume Two)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 320 on sheet 3) on 2026-11-20.

## Summary
- Melee hero, 17 life, move 2, **three Clones** (melee, 1 life each, move 2) that are **not on the board at the start**: they wait in the reserve (`start_on_board 0`) and come out through the ability and Sly Monkey. Hero fid `wukong`, sidekick group `clone` (`clone1`..`clone3`), slug `sun-wukong`.
- Ability (a start-of-turn trigger, `clone_summon`): "At the start of your turn, you may take 1 damage to summon a Clone in an empty space adjacent to Sun Wukong. Do not start with any Clones on the board." Not offered with three Clones on the board or no empty space next to him.
- Deck: 30 cards, `CardID = 17600 + idx`, every card is band ANY. The deck object in the save holds 31 cards (the 30 plus the character card 320). Order on the sheet: Ox Form 0-1, Ruyi Jingo Bang 2-4, Taunting Laughter 5-7, Infinite Strikes 8-10, Sly Monkey 11-14, 72 Transformations 15-17, Wily Fighting 18-20, Bewilderment 21-22, Tortoise Form 23-24, Golden Chain Mail 25-26, Fiery Eyes That See 27-28, Phoenix Form 29. The three Forms (Ox, Tortoise, Phoenix) carry the tag `form`, which 72 Transformations looks for.
- Table: bag `ce28ea` (inner `2a729b`), miniature `dad584`, life dial `bfe46d` (max 17, the model with the `Hero Health` script), deck `63ee45`, three Clone tokens `9fdce3`, `582f73`, `d17daa` (Custom_Token, 1 life, no dial; real TTS may report them as "Tile": nothing that reads or moves a piece looks at the type).

## Card identity: the shared CardID range
His deck is sheet 176 like Medusa's, the turtles', Doctor Strange's, Eredin's and the rest: the CardIDs repeat and only `deck.identity` (his own image pair in `data/tts/sun-wukong.json`) tells the decks apart. See docs/card-identity.md; `tests/test_hero_sun_wukong_data.py` and the matrix are the proof.

## Cards (as implemented)
1. **Ruyi Jingo Bang** (attack 0 / boost 3): a DOUBLE ATTACK. AFTER, if the opponent played a card against it (a defense card), a second attack of 4 (`second_attack`, docs/effects-dsl.md section 45; the mechanic, who may defend it, Feint and Skirmish are the double-attack engine's).
2. **Ox Form** (attack 7 / 2): `uncancelable`. The opponent's card may be BOOSTED (`allow_boost`), only when the opponent played a card. DURING as printed (Ivan 2026-11-20, W6): the engine offers the defender's BOOST right after the attacker's DURING grants it (`combat_flow._late_boost`; `grants_boost` also reads DURING so the table asks the human at Reveal).
3. **Taunting Laughter** (attack 3 / 2): IMMEDIATELY the opponent may discard 1 card of their hand; if they do not, the value of their card is ignored (`optional` with a discard `cost` and an `else` with `set_value ignore`, chooser the opponent). Nothing is asked when they played no card.
4. **Infinite Strikes** (attack 2 / 2): DURING +1 for each other friendly fighter adjacent to the opposing fighter; AFTER gain 1 action.
5. **Sly Monkey** (versatile 2 / 3): AFTER, if Sun Wukong played it, summon a Clone in his space, then place him in a space of his zone. With the three Clones already out, one of them (the owner chooses) is repositioned to his space instead (Ivan 2026-11-20, W5). With no empty space in his zone, none of it happens (Ivan 2026-11-21).
6. **72 Transformations** (versatile 2 / 2): AFTER take an Ox Form, Tortoise Form or Phoenix Form from the discard pile into the hand.
7. **Wily Fighting** (versatile 3 / 1): AFTER 1 damage to each opposing fighter adjacent to the fighter that played it.
8. **Bewilderment** (defense 0 / 2): DURING prevent all combat damage (`cap_combat_damage` 0 on both combatants); AFTER you may place your fighter in any space.
9. **Tortoise Form** (defense 5 / 2): DURING the attacker may BOOST their attack.
10. **Golden Chain Mail** (defense 4 / 2): DURING the combat damage the fighter would take is dealt to the opposing fighter (`redirect_damage` from `this` to `attacker`, combat).
11. **Fiery Eyes That See** (scheme, boost 1): look at the opponent's hand, choose a card, put it at the bottom of their deck, both draw 1 (owner first).
12. **Phoenix Form** (scheme, boost 1): Sun Wukong recovers 1 health per Clone on the board (alive when it resolves).

## Discrepancies with unmatched-memory
- **Bewilderment**: the card says "Prevent all **combat** damage"; unmatched-memory says "Prevent all damage". The card wins (`text` in the overlay). Effect damage is not prevented.
- Everything else (titles, types, values, boosts, copies, 30 cards) agrees with the images.

## Engine notes (additive; shared code touched)
- `modifiers._owner_run(game, owner, flow)`: the bare run that reads a combat redirection now knows the attacker and the defender, so `redirect_damage` can name `{"role": "attacker"}` (Golden Chain Mail). Baba Yaga's redirect named a fighter by name and never needed it.
- Ox Form's BOOST grant is DURING as printed (Ivan 2026-11-20, W6). The defender's DURING runs before the attacker's, so after the attacker's DURING the flow offers the defender its BOOST (`_late_boost`, answers keyed by the side the boost is for); a defender that already had its free BOOST (a `may_boost` card) is not asked twice. Tortoise Form (a defense granting the attacker) was already in order.
- `table.ENGINE_RUN_TRIGGERS` (`clone_summon`): this trigger is run by the engine for the table player (a yes/no on the panel, the 1 damage on the dial written by the bot, the Clone placed by hand and read from the table), not left to the table. Keyed by trigger id, not by op, so Medusa's GAZE (optional + damage) stays the table's (regression test `test_the_human_medusas_gaze_is_still_the_tables_to_do`).
- Setup: a fighter in the reserve (`start_on_board 0`) is not asked to be placed and does not block Ready (`Session._in_reserve`); a summoned Clone the human has not yet taken out of the bag is not reported as missing; the first summon is narrated as "summoned" with names (`narr.fighter.summoned`).
- Test harness: a fighter in the reserve has no position, so `tests/test_d3_table_effects.build` leaves it out of the fake table (a Clone in the bag is not on the table).
- `session_bot_effects._human_cards`: a card the bot chose in the human's hand after a look (Fiery Eyes That See puts it at the bottom) is named to the human ("Pon X de tu mano en el fondo de tu mazo"); before, only a card the bot had seen BEFORE the step was named and the rest was "return N cards, you choose".

## AI
- The generic answer to an optional is "yes": the bot would have paid CLONES with 1 hit point left. `ai_wukong.summon_pays` (hooked in `EffectAI._optional` by the trigger id `clone_summon`) is built like DARK PACT's: never below `FLOOR` (5) hit points, never when the hit point raises the chance of dying in the rival's next turn (`MedusaAI.death_risk`) to `SURVIVAL_P` or by more than `RISK_STEP`; otherwise when the Clone is worth more than the hit point: a body (`HARPY_VALUE + BODY`, less each Clone already out: the third adds a third as much) plus what it does for the cards in hand (Infinite Strikes, Phoenix Form while he is hurt, Wily Fighting).
- Cards are valued like every interpreted hero's: the search plays the real engine (the Clone, the extra action, the damage, the second attack), the heuristic through `card_value` and the generic AFTER simulation.
- Strength (information only, `sun-wukong` as the bot against the chasing scripted Hellboy of `sim.play(rival="chaser")`, bprd-hq, wins of the bot): heuristic AI, 60 games, CLONES by `ai_wukong` 43, never summon 38, always summon (the generic yes) 39; a floor of 8 hit points 42. Search AI (`ai_iterations 60`), 40 games: `ai_wukong` 23, never summon 23, a floor of 10 hit points 20. So the policy is neutral to positive; the search does not yet plan around the Clones (it counts them as bodies), which is why it gains nothing from them.

## Rule decisions (taken without a ruling: the most literal reading, applied)
1. **A defeated Clone returns to the supply and can be summoned again** (the DSL reads it as "if a Clone is defeated, revive it, else summon from the reserve"). The hero card gives him three Clones and says nothing about losing them for good; with fewer the ability would end after three deaths.
2. **The ability's 1 damage is effect damage on himself** and can defeat him at 1 health (the card does not forbid it). The bot never does it (the floor).
3. **Sly Monkey** summons only when Sun Wukong (not a Clone) played the card, and the Clone appears on his current space for that instant (`empty: false`); he is then placed on an empty space of his zone, so the space he stood on is the Clone's. With three Clones already out one of them is repositioned to his space (the owner chooses which; the human moves the Clone and Wukong by hand, End action reads both) and he is placed (Ivan 2026-11-20, W5); with no empty space in his zone nobody moves. **If his zone has no empty space to place him, the Clone is not summoned at all** (no summon, no revive, no repositioning, nothing else happens; Ivan 2026-11-21, live: Clone and Wukong ended on the same space); the DSL guards the whole effect with `exists space {zone_of: this}`. **If Sun Wukong cannot leave his space** (Burning Barrier's `cannot_leave_space`, test `can_move`) no Clone is summoned either (Ivan 2026-11-21). In both cases the human is ALWAYS told, whoever plays the card: the card's line carries the reason through the `notice` op (`narr.notice.sly_monkey_no_space`, `narr.notice.sly_monkey_pinned`: "Sly Monkey: no tiene efecto: no hay casillas libres en la zona de Sun Wukong"). With the three Clones out and one of them inside his zone but no other free space it is the same: nothing moves (no swap trick) and it is announced. He may be placed on the space he already holds only when no Clone took it.
4. **Bewilderment** prevents combat damage to both fighters of the combat; its placement is optional (a "may") and goes to any empty space; a Clone that plays it is placed instead of Sun Wukong ("your fighter").
5. **Golden Chain Mail**: the damage goes to the attacker whatever its range; effect damage is not redirected; the defender WON the combat and the attacker lost it (Ivan 2026-11-20, W3: see Decided below), because the damage is taken by the attacker; the attacker's "if you lost" effects fire (Hellboy's Confront Any Demon or God looks at the hand and discards).
6. **Ox Form and Tortoise Form** (Ox Form: DURING, Ivan 2026-11-20 W6): one free BOOST, after the booster's own DURING, from the booster's hand, like Houdini's An Illusion Of My Own Design (docs/heroes/houdini.md). A cancelled side gets none.
7. **Taunting Laughter**: with no opponent card there is nothing to ignore and nothing is asked; a rival with an empty hand cannot pay, so the value is ignored.
8. **Infinite Strikes**: "other friendly fighter" excludes only the fighter that plays the card, so a Clone attacking counts Sun Wukong when he stands next to the target.
9. **72 Transformations** looks in the discard pile when its AFTER resolves, so it can never return itself and a Form played in the same combat is not there yet.
10. **Fiery Eyes That See**: the card goes to the bottom without shuffling; with an empty hand nothing is chosen and both players still draw.
11. **Phoenix Form** counts the Clones alive on the board when it resolves.
12. **A card played to defend is a defense card** for Ruyi Jingo Bang (a versatile card played as a defense counts).
13. **The human's ability** is a yes/no on the panel at the start of the turn (the first turn too); on yes the dial loses 1 and the human puts a Clone from the bag on an empty adjacent space; the next End action reads it from the table.

## Decided (Ivan 2026-11-20)
- **W3, who wins when the damage is redirected**: "won / lost the combat" depends on WHO TOOK the combat damage. The attacker wins only if the defending fighter took combat damage; otherwise the defender wins. With Golden Chain Mail the damage lands on the attacker, so the defender wins and the attacker lost (live case: bot Hellboy's Confront Any Demon or God, total 5 against Golden Chain Mail 4: Wukong took 0, Hellboy 1, so Confront's "if you lost" must fire). Implemented in `CombatFlow._damage` (`attacker_won`), read by `won_by`, the `combat_result` test, the `combat_lost` tally and the second attack of a double attack. Tests: `tests/test_combat_winner_redirect.py`.

## Pending Ivan
1. **Do defeated Clones come back?** (rule decision 1). Alternative: a defeated Clone is gone for good and "up to 3 Clones" is the lifetime supply.
2. **May the ability kill him?** (decision 2). Alternative: it cannot be used with 1 health.
4. Bewilderment: Ivan confirmed the printed "combat damage" (2026-11-20, W4); reading unchanged.
6. **The double-attack points** (boost of the second attack, "won/lost", Ruyi Jingo Bang when the first defense is cancelled) are the double-attack agent's list in docs/combat-flow.md.
7. **The first turn**: the ability is offered at the start of the very first turn like any other (Wukong may open with a Clone).

## Tests
- `tests/test_sun_wukong_effects.py` (bot side: the ability, every card, Ruyi Jingo Bang as a double attack), `tests/test_sun_wukong_human.py` (the panel, both seats: the ability by hand, Sly Monkey, Golden Chain Mail, Bewilderment, Phoenix Form, the bot's Fiery Eyes and its Clones on the table), `tests/test_sun_wukong_ai.py` (the CLONES policy and whole games with the search AI), `tests/test_sun_wukong_matrix.py` (full games against every other hero in both seats, FakeTTS and simulator), `tests/test_hero_sun_wukong_data.py` (data, card identity, the table data).
