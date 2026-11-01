# Liz Sherman (Hellboy box)

Data and effect specification (F07, step 13). No engine: the interpreter did not read `effects/` yet at the time.

## Summary
- Ranged hero (RANGED on the card), 16 life, moves 3. No sidekicks or tokens: Liz's bag in the tournament save only holds the miniature, the life dial (0..16) and the deck. The "melee" the project's memory recalled was unmatched-memory's empty sidekick (`name ""`, `hasSidekicks false`), which is ignored.
- Deck: sheet 199 of the save (8x4), `CardID = 19900 + idx`; character card 19800. All 30 cards carry the LIZ SHERMAN band (none ANY). The loose cards of the save use key 188 with the same images.
- Ability WILDFIRE: (a) every burning card discarded from the hand or the deck returns to the hand; (b) at the start of the turn she discards the bottom of the deck: if it is burning, 1 damage to another fighter in Liz's zone; if not, Liz moves up to 2.

## Burning cards (the 15 of the plan)
It is a printed property: a flame icon next to the title and no boost circle (BOOST 0). There is no counter or token.

| Card | Copies | Type | Value | Boost |
|---|---|---|---|---|
| Incinerate | 1 | attack | 7 | 0 |
| Fireball | 2 | attack | 5 | 0 |
| Flame Lash | 3 | attack | 1 | 0 |
| Burning Barrier | 3 | versatile | 2 | 0 |
| Pyrotechnics | 3 | versatile | 3 | 0 |
| Searing Clarity | 3 | scheme | - | 0 |

The other 15 (Fleeting Moments x3, B.P.R.D. Training x2, Rekindle x2, Feint x3, Evade x2, Fight Or Flight x3) are not burning and do have a boost.

## Files
- `data/heroes/overlay/liz-sherman.json`: CardID sheet, restriction, `burning` tag, `wildfire_start` trigger and `wildfire_return` passive as data.
- `data/heroes/liz-sherman.json`: generated with `tools/import_hero.py liz-sherman`; `--check --all` passes.
- `data/heroes/effects/liz-sherman.json`: ops per card, selectors, primitive extensions, plugins, hidden information and questions.
- `tests/test_hero_liz_sherman_data.py`: 4 data tests (no TTS).

## Decisions
1. **Wildfire (superseded: it is no longer a plugin, it is the `wildfire_return` trigger of the `card_discarded` event)**: it changes the destination of any burning discard from the hand or the deck, whoever triggers it (ability, Flame Lash, Fleeting Moments, rival effects). Never by boosting: a burning card has no boost value and cannot be used to boost (Ivan, 28/10). It is not a card op: it is a hook on the `discard` primitive. The start-of-turn trigger does go in ops (`discard from deck_bottom` + `if card_has_tag burning`).
2. **`liz:incinerate` is not needed**: it fits with `optional` (the rival chooses and pays) + `modify_value set 0` + a card attribute `uncancelable` that `cancel_effects` must respect. If the interpreter does not admit those three extensions, it goes back to being a plugin.
3. **The real card wins**: Fight Or Flight has an ONGOING that unmatched-memory does not carry. The overlay admits `text` per sheet entry and `tools/import_hero.py` prefers it to unmatched-memory's text (one line). It is the only change outside data and tests.
4. No counter: `burning` is a card tag, not counted in any pile (unlike Hellboy's destinies).
5. Liz's row comes from `test_rest_of_the_hellboy_box_loads_basic_data_but_cannot_deal_a_deck` (it already deals a deck); the new test covers it.

## Discrepancies with unmatched-memory
- Fight Or Flight: the whole ONGOING is missing ("Add +1 to the value of your combat cards. Discard this at the start of your next turn."). Corrected via overlay.
- Incinerate: the card says "effects" (plural) where unmatched-memory says "effect"; no consequences.
- Evade: `effectAfter` with a leading space in unmatched-memory; no consequences.
- Empty sidekick with `attack: melee`: ignored.

## Effect coverage
12 titles, 12 with ops (100 %), 0 with a `plugin` on the card. One global plugin (`liz:wildfire`). Argument extensions declared on vocabulary ops: `discard from deck_bottom`, `modify_value set / ref`, `status cannot_leave_space`, `if card_has_tag`, `choose_n from/filter/min/max`, `return_to_deck bottom|shuffle`, `optional cost`, `move up_to/through_enemies`, `persistent_scheme until/then`, and the card attribute `uncancelable`.

## Hidden information (Iván's rule: it is only looked at when a card says so)
- Bottom of the deck (ability, Flame Lash): nobody knows it until it is discarded; the bot values Flame Lash with the remaining deck, except for what it put there itself with Pyrotechnics (it remembers it in order). Shuffling (Rekindle, Searing Clarity) erases that memory.
- Fleeting Moments: the rival's random discard is drawn by the human or by a uniform index; the discarded card is public and is discounted from KnownHand. Its draw is an unseen card.
- Incinerate: the rival chooses which 2 to discard; public when discarded.
- Wildfire: the burning card that returns to the hand is public: it becomes part of the rival's known hand.
- Wildfire, the only exception (Iván, 28/10): a burning card discarded for the hand limit at the end of the turn does NOT return to the hand; it stays in the discard (`card_discarded` event with `cause: hand_limit`, filtered with `cause_not` in `wildfire_return`).
- Pyrotechnics: cards face down to the bottom; the bot does not read which ones they were when the human plays Liz (counts only).

## Ivan's decisions (28/10)

- 'bottom card of your deck' is the lowest card of the deck (the last), not the top one that is drawn. It is the one Wildfire uses at turn start and Flame Lash.
- empty deck at turn start or with Flame Lash: nothing happens (no damage or movement; Flame Lash adds 0).
- Wildfire's damage at turn start is mandatory if there is a target, and only to ONE fighter.
- an effect that ignores the PRINTED VALUE does not remove Fight Or Flight's +1; one that ignores the VALUE does.
- with the bot playing Liz, the bot turns the bottom of the deck at the start of its turn.
- (29/10, general rule for all heroes) Searing Clarity / Rekindle: if the HUMAN chooses with the panel buttons a card of their own DISCARD (public) for an effect to put into their deck (shuffle / top / bottom), the BOT moves it (by GUID, with the human's deck GUID) and shuffles the human's deck if the effect says so. The bot still does not touch their hand nor read/reorder their deck beyond that. Chat: "I put X into your deck and shuffle it". If the card is no longer in the discard (the human did it), it says it is already done, with no error.
- E3 (29/10): Fleeting Moments played by the human: the bot's card is chosen by the engine's rng (nobody looks at any hand) and the human's discard is theirs (pending End action).
- Ivan (29/10): if the human makes the bot's Liz discard a burning card (Confront), Wildfire returns it and the chat says so: "The bot keeps X (Wildfire returns it)".
- Incinerate: the rival may discard 2 cards from the hand, IN ADDITION to the card it defends with, to ignore Incinerate's value (it stays at 0); if it did not defend with a card, discarding 2 also works. With fewer than 2 cards in hand it cannot pay.
- Burning Barrier: cannot_leave_space blocks all movement of the rival fighter (own or by effects); an effect can move Liz. The later damage is to each rival in Liz's zone.
- a card with no boost value cannot be used to boost: burning cards (BOOST 0) are never discarded as a boost.
- a single active ONGOING PER PLAYER; playing another replaces the player's own active one (two Fight Or Flight = +1). Code pending: Game.combat_bonus still accumulates.
- a card's value never drops below 0 at EACH step, and effects resolve in moment order (IMMEDIATELY before DURING; same moment, the defender first): Flame Lash (1) against Arcane Dampener (IMMEDIATELY -3) ends at 0, and then Flame Lash's boost in DURING (+3) leaves it at 3.
- (29/10, E2) WILDFIRE at the start of the human's turn (card from the bottom of the deck): the human does it on the table (damage with -1, movement by hand); the panel announces it and BLOCKS the other buttons (only End action and the HP ones) until they press End action; it resumes from a save.
- (29/10, E2) The return to the hand by Wildfire is narrated in the same line as the card: "you discard Fireball (Wildfire returns it to your hand)", not in a separate line.
- (29/10, E2) The human's Fight Or Flight is left in their ONGOING zone (`human_ongoing_spot`, below the combat zone), not in the discard; when it expires the chat asks to move it to the discard. The bot's goes face up to `bot_ongoing_spot` and to its discard when it expires.

## Open questions

- Order at the start of Liz's turn: first Fight Or Flight is discarded and then Wildfire's bottom card. An assumption; they do not interact.

## Fight Or Flight in the engine (ONGOING)
- `Game.combat_bonus[player]` keeps the live (bonus, tag) pairs. The session adds it when it detects the scheme in the human's discard; `resolve_scheme` adds it if the bot plays it. Iván's rule of 28/10 (a single active ONGOING per player): `add_combat_bonus` replaces the active one and returns its tag (the session warns "X replaces Y"); two Fight Or Flight give +1. An old save with several bonuses loads only the last. The rival's ONGOING is not touched.
- Boost (28/10): `cards.can_be_boost(card)` (BOOST > 0) is the single rule. The engine raises `RuleError` if an attack or a maneuver is boosted with a card with no boost value; the AI and the ISMCTS only generate legal boosts; if the human discards a BOOST 0 card as a boost, the session warns "X has no boost value: it does not count" and keeps waiting. Exception: Flame Lash's card from the bottom of the deck adds whatever it is worth (0 included).
- It adds to the value of every combat card of the owner: attack on their turn (via `attack_bonus_parts`, next to the hero's passives) and defense on the rival's, also if the card is worth 0, is cancelled or is On Earth (it is added after fixing the value). Without a defense card there is no value to add to. The panel's "extra value" is separate and adds up.
- It expires in the owner's `begin_turn()` (which returns it so as to warn). It is saved in the save's `game` `combat_bonus`, only if there is something; an old save without the key loads as 0.
- AI: `Model.defense_dist` and `attack_dist` read it (it is public); the ISMCTS sees it through `resolve_combat` and `attack_bonus` in the clone. If the bot plays it, the engine applies it; Medusa's AI does not evaluate it for itself (it is not her card).
- The physical discard of the scheme when it expires is done by the human (the chat reminds them).
