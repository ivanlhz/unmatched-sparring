# Abe Sapien (Hellboy box)

Data verified on 28/10/2026 against the tournament save (`saves\Unmatched Official Tournament Table October 2026 (Hellboy).json`): card sheet 194 (8x4, FaceURL of the "Abe Sapien" bag, GUID a959bb), hero card 19500 and tokens. Data and specification only; the engine did not run any of this yet at the time.

## Summary

- Life 13, movement 2, ranged. Ability UNCANNY INTUITION: two intuition tokens; when Abe deals combat damage to an adjacent fighter he activates one; when Abe is attacked with one active, it is deactivated, he draws 1 and the attack is played face up.
- Sidekicks: B.P.R.D. Agents, life 1, movement 2, ranged, x3. In TTS they are three tokens called Victor, Carla and Kate. In the engine: one `agent` sidekick with count 3 (agent1..agent3).
- Deck (30): 11 cards only for Abe (Faster. Stronger. x2, Advanced Psychometry x3, Perfect Shot x2, Every Possible Angle x2, Counterhex Shield x2, B.P.R.D. Utility Belt x2), 3 only for the agents (Secure The Scene) and 16 ANY.
- CardID = 19400 + idx (sheet 194). Character card: 19500.

## Files

- `data/heroes/overlay/abe-sapien.json`: CardID sheet, restrictions, sidekicks with `start_on_board`/`reserve`/`tts_tokens`, the two triggers of the ability as data.
- `data/heroes/abe-sapien.json`: HeroDef regenerated with `tools/import_hero.py abe-sapien` (`--check --all` passes).
- `data/heroes/effects/abe-sapien.json`: ability and 14 cards as ops of the common vocabulary, new primitives, plugins, hidden information and questions.
- `tests/test_hero_abe_sapien_data.py`: sheet, copies, HeroDef, effect coverage and vocabulary.

## Decisions

1. **Agents: 3 on the board, 0 in reserve.** The hero card marks "START HEALTH" with three dots and "x3", the same notation as Medusa's Harpies (which all start on the table); the save has three tokens and nothing that acts as a reserve. "Summon a B.P.R.D. Agent in Abe's zone" (Secure The Scene): `revive` of a defeated agent with its 1 life; with no fallen agents, the owner takes a living one and places it (`place`) in Abe's zone (Ivan's decision, 28/10).
2. **Uncanny Intuition does NOT need a plugin.** It is two triggers with three primitives: a token `counter` (0..2), `draw` and `reveal` of the attack before the defense. The "face-up attack" is shared with Perfect Shot, so it is a primitive and not one hero's code. The plan foresaw `abe:uncanny_intuition`; it remains as a fallback only if the engine does not want token counters or the `attacked` moment.
3. **Perfect Shot is a plugin** (`abe:perfect_shot`): deciding when playing whether it goes face up, announcing a prediction and comparing it in DURING COMBAT does not fit the DSL (there is no "when played" moment nor "save and compare") and it is the only card of the box that needs it.
4. Op conventions: a `target` with a choice is made by `who_chooses` (owner by default); `same` repeats the last chosen target; `push` moves a rival and is directed by the effect's owner; `modify_value` with `set` fixes the value (Shock And Awe "becomes 4").

## Coverage

- 14 cards: 13 with primitives, 1 with a plugin (Perfect Shot). Ability with primitives.
- New or extended primitives requested: `recover_from_discard` (Ward And Prepare), token `counter`, `reveal` of the attack card, `modify_value` with `set`, `status` with names and expiry (cannot_gain_actions, cannot_draw, next_attack_bonus, immune_to_enemy_effects), trigger moments `combat_damage_dealt` and `attacked`.
- Hidden information: Advanced Psychometry and Every Possible Angle (looking at the hand), Perfect Shot and the ability (face-up attack), Shock And Awe (discard chosen by the rival) and Ward And Prepare (public discard). Rule: the bot reads the hand only when the card says so, remembers it in KnownHand and discounts it as cards leave. Every Possible Angle also leaves known the next card the rival will draw (KnownHand needs a `top_of_deck`).

## Discrepancies with unmatched-memory

- **Counterhex Shield**: the real card adds "Ongoing: Other players' effects can't damage your fighters, move your fighters, or force you to discard cards. Discard this at the start of your next turn." unmatched-memory only has "Draw 1 card. Gain 1 action." The card wins: the two sheet entries of the overlay carry `text` with the real text and the importer prefers it to unmatched-memory's (`"text": entry.get("text") or card_text(src)`, the same convention as Liz). The source remains to be corrected if Ivan wants them to match.
- **Agents**: unmatched-memory has three entries (Carla, Kate, Victor) with equal figures; the hero card calls them "B.P.R.D. AGENTS" and the card restriction "B.P.R.D. AGENT". A single sidekick with count 3; the token names stay in `tts_tokens`.
- Values, boosts, types and copies of the 14 cards match the source.

## Ivan's decisions (28/10)

- agents: 3 on the board; summon = revive a defeated one with 1 life in Abe's zone or, with none defeated, take a living one and place it on a space of Abe's zone (Secure The Scene).
- Uncanny Intuition: also activates a token when Abe defends and deals combat damage to an adjacent attacker.
- Perfect Shot: any value from 0 to 7 can be predicted; if the rival does not defend with a card, it does not hit.
- Every Possible Angle against the bot: the bot lays its hand face up (row at look_spot, like F16) and pings the cards.
- Counterhex Shield: the real text (with ONGOING) is also corrected in unmatched-memory.
- E3 (29/10): Advanced Psychometry against the bot only shows the hand (face-up row + ping, no choice; End action or Cancel picks it up) and only if Abe is adjacent after the combat. Every Possible Angle: the card chosen by ping goes ON TOP of the bot's deck (putObject) and then the panel asks for Abe's move. Fleeting Moments against the bot: the bot's card is drawn by the engine's rng. Uncanny Intuition with a human Abe: the bot's attack is turned face up when placed and named; with a bot Abe: the chat warns when choosing the target, the attack is placed face down as always and at Reveal the bot chooses its defense seeing ONLY that card. Human Perfect Shot: buttons 'Value 0..7' and 'Face down' at Reveal, before the bot defends; bot Perfect Shot: it places it face up and announces the prediction (the most frequent value among what has been seen of your hand or, with nothing seen, among the defenses of your deck minus your discard).
- Ivan (29/10): a Perfect Shot the human plays face up is public information: the bot chooses its defense knowing that card (same as with Uncanny Intuition).
- Ivan (29/10): Uncanny Intuition with a bot Abe: the order is the engine's, first the event (spends the token and draws, and the drawn card is dealt at once) and then the defense, so the drawn card can be the defense. One token per attack.
- Ivan (29/10, E2): if a Reveal against a bot Abe with an active token is rejected and the human presses Cancel, the spent token and the drawn card stay: if they repeat the same attack (same attacker and target) it is not spent or drawn again (the declaration carries over, the attack stays face up); if they change attacker or target, the earlier spend stays and the new attack declares normally.
- a card's value never drops below 0 at EACH step, and effects resolve in moment order (IMMEDIATELY before DURING; same moment, the defender first): Flame Lash (1) against Arcane Dampener (IMMEDIATELY -3) ends at 0, and then Flame Lash's boost in DURING (+3) leaves it at 3.

## Open questions

- 6. Agent tokens in TTS: they are called Victor, Carla and Kate; the engine numbers them agent1..agent3. The fid -> GUID mapping is needed in the game configuration (step 10 of the plan), like the Harpies.
- Every Possible Angle: how the engine records the bot's card that returns on top of its deck (it becomes known to the human: it does not affect the bot's information).
- Ivan (3/11): human Abe's Intuition tokens are turned BY THE BOT on the table (`lua.set_intuition_tokens`, found by nickname "Intuition Token"/GUID 5a17e9; faces from `token_faces.intuition` in data/tts/abe-sapien.json, inferred, verify_live): activate on combat damage, spend when attacked. The spend happens when the bot's attack is placed (`session_hidden.declare_bot_attack`): token spent, card drawn and dealt before the defense. If the tokens cannot be found or turned the chat asks the human to do it; a table that disagrees with the engine is warned and the engine stays the authority.
