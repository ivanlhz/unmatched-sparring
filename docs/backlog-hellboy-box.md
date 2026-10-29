# Backlog for the remaining phases (Hellboy box, both sides)

From reviews (28/10):
- Human maneuver boost with BOOST 0 (Liz burning card) is accepted silently; add chat warning (docs/heroes/liz-sherman.md:71 claims it warns).
- Game.maneuver not atomic: BOOST 0 RuleError after use_action() + draw(); validate before. Same for attack _check_boost after IMMEDIATELY.
- Tests for BOOST 0 use patched cards; add tests with real Liz burning cards.
- DONE in D1: Bot Flame Lash's DURING (bottom-of-deck boost) is applied by the interpreter.
- "One ONGOING per player" only covers combat_bonus; Baba Yaga pacts not modeled yet. Effects phase.
- DONE in D1 (bot's Incinerate): the human answers Si/No at the panel (E1 buttons) before the damage; the human's own Incinerate against the bot is E2's.
- Reserve sidekicks count as dead in side_c (latent, no hero uses reserve).
- Hero detection: needs live --read-only test (Iván tests at the end).
- Translation phase: all code, files, dirs, docs, README in English (README: how it works, usage, config, what works / doesn't, roadmap). Only TTS buttons and in-game chat in Spanish. Commands change (config/partida.json -> config/game.json?, estado/ -> state/), old saves must still load.
- Confront played by human and lost: bot reveals hand face up + ping (assumed by analogy with Every Possible Angle; open question to Iván).
- Iván UX rule: choice buttons only appear when the card is played; hidden (not grey) otherwise.
- combat_flow.card_by_id picks first match across both full_sets: wrong in a mirror match (same hero both sides). Fix in E1.
- Combat diff test patches combat.resolve_combat but search/adapter imports it at load: ISMCTS internals not diffed.

## Iván's answers (28/10, 2nd batch) - record in docs/heroes/*.md + effects notes in the next phase that touches them
- Confront played by human and lost: bot reveals its hand face up + ping (confirmed). E3.
- Abe Intuition tokens: data/tts/abe-sapien.json has one token GUID (5a17e9); Iván: "from the same token you can take another" (it's a source/stack you can draw copies from). Bot shows 0/1/2 active by taking copies from it. Verify live with --read-only. D3/F1.
- Koschei starts on the board (confirmed). Check baba-yaga.json start_on_board.
- Out Of Time "BOOST this card": boost from HAND (as usual). C2.
- Winged Frenzy: returning a defeated Harpy is MANDATORY (text). DONE in C5: the interpreter returns it even when choose_placement answers None (first free space of Medusa's zone); no golden changed because the AIs never decline (tests/test_medusa_dsl_diff.py pins the divergence).
- Restrictions on the human (Pact Of Freedom no attack as first action, Cold Iron no draws...): the PANEL BLOCKS them (not just warn). E1/E2.
- "Mirar mano del bot" button: HIDE it unless a card allows it. E1.
- Unanswered (keep assumption): Liz start of turn: Fight Or Flight expires before the Wildfire bottom discard.
- RULING (Iván 28/10): Wildfire exception: a burning card discarded because the hand is over 7 (end-of-turn hand limit) does NOT return to hand; it stays in the discard. Only exception. Apply in C3 (end_turn hand_limit discard -> no card_discarded bounce) AND in the live session (_human_wildfire / hand-limit handling in session.py) + docs/heroes/liz-sherman.md + liz-sherman.json notes.
- C4 residual: seen cards stay certain when unseen ones can be trimmed (combat facedown vs Glimpse/Pyro drop indistinct). E2.
- Bot Liz hand-limit discard via force_discard -> card_discarded: Wildfire exception must apply there too (C3 fix covers engine end_turn; verify).
- Out Of Time: human attacking now gets boost prompt (flag off) per ruling.

## From the E1 / D1-prep reviews (29/10)
- DONE in D1: EffectState.copy() never carries choosers or parked; clones decide with their own controllers.
- Cold Iron with human_deck_guid set: the draw block is only a chat line; a physical draw is accepted by sync_human. Probably unavoidable in TTS; decide in E2.
- Spanish comments added by E1 in ui.py:31,45,185 and lua.py:1187-1188: translate (translation phase).
- No test resumes a save taken at a pause after the bot already moved/boosted mid-combat (projection-then-resume path). Add in F2.
- CANCEL is refused during a pause: if every option is refused, the combat can only be left with Restart.
- Look grant ignores card conditions (Confront only when lost, Psychometry only if adjacent): button appears whenever the card is played.
- DONE in D1: `_cost_context` gives the attacker a stake (the damage the defense blocks); no box card asks it today (Incinerate is attack-only).
- set_panel labels via UI.setValue on a Button: verify live.

## From D1 (29/10)
- Perfect Shot: the bot plays it face down (no prediction, no +2) until E3 wires the prediction at play time (`flags["prediction"]` of the IMMEDIATELY run; the bot announces, the human gets buttons).
- DONE in D3 (Ivan, 29/10): the bot narrates Medusa's cards too; the C5 oracles ignore the narration lines only.
- Bot Pyrotechnics / Glimpse Of Hell / Read The Bones use the generic card rules of EffectAI (lowest keep_value goes back, best card_worth is taken): no Liz-specific play (a burning card at the bottom for Wildfire). D2 if it matters.
- DONE in D3: a specific human card the bot discards is owed by name (`pending_discard["cards"]`); Fleeting Moments' random pick is the human's (force_discard route).
- Remove A Painful Memory by the bot: the human's "discard it or take 2" is a Si/No at the panel; the card named is the one the bot chose among what it saw (chat says which).

## From D3 (29/10)
- verify_live: bot Hellboy's form change (`set_state` f9789a <-> e6f06e, `flip_token` 1644a3: the flip is unconditional, so the token must start on OCCULT DETECTIVE; `ping_objects` on both); Abe's Intuition copies taken from 5a17e9 (`take_token_copy`: takeObject or clone by object type) and `remove_token` of a copy; `hand_to_deck` (putObject straight from the bot's hand zone, bottom = deck turned over) and `card_to_deck_bottom`; `return_card_to_hand` of a discard-pile card; `move_piece` of the human's miniature by the bot; the `read_hand` of the human seat at a look (one message); `token_spot` (default beside the bot's deck: calibrate).
- Every Possible Angle by the bot: the human puts the named card on top of their own deck by hand; the session only skips that card when padding the virtual hand. Pact Of Secrecy / Pact Of Time on the human: chat only, the sync follows the counts.
- Read The Bones (bot): the engine's deck order is not the real one; the card it took becomes a draw from the top (`drawn`). A real "look at 5, pick 1" on the table (`deal_row`) is not wired.
- A bot scheme card that pauses for the human stays physically in the bot's hand until the answer; an ONGOING scheme of the bot is never placed on the table (D2).
- The human's choice among their own virtual hand (Pact Of Secrecy: which 2 to keep) shows placeholder titles at the panel (E2: the human's own cards).
- Bot Liz's Wildfire start-of-turn effects now reach the table (they did not before D3): one message before her first action (test_multihero_bridge budget).
- A failed projection (piece move, state swap, token, deck move) is said once ("hazlo tu"); the table wins at the next read, no retry queue.
