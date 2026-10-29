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
- Narration of Medusa's cards: D1 narrates only the box heroes (the C5 oracle compares `applied` byte for byte). Ask Ivan whether the bot should also say what Medusa's cards did ("Aplicado: Regroup: roba 2"); if so, the C5 session/twin oracles must ignore those lines and the session goldens change.
- DONE in D2 (Ivan 29/10, required): bot Liz leaves a burning card at the bottom with Pyrotechnics (pick, order and the optional); Glimpse Of Hell / Read The Bones keep the generic rules (they shuffle or draw, nothing of theirs stays at the bottom).
- Bot Liz's Fleeting Moments / Confront make the human discard a specific card the engine chose: the chat names it; the physical move is D3's.
- Remove A Painful Memory by the bot: the human's "discard it or take 2" is a Si/No at the panel; the card named is the one the bot chose among what it saw (chat says which).

## From D2 (29/10)
- A bot scheme that asks the human (Pact Of Secrecy: the human keeps 2) returns an Await from `MedusaAI.execute`; the session ignores it today (the card would stay unfinished). E2 must drive it like `Session.play_effect`.
- `MedusaAI.plan`'s two-level lookahead values an attack on a hero at 1 hp as highly as the scheme that kills it for sure (expected attacks never set `winner`); with one action left the sure kill wins. Pre-existing, left as is.
- The search's rollout plays no schemes (attacks and maneuvers only), as before; scheme lines are explored by the tree only.
- `ongoing.worth` gives the symmetric pact rules 0: whether a Pact Of Time / Secrecy favours the bot is left to what the tree simulates after it.
- Session chat for a bot scheme (`_action_text`, kind "scheme") says the title, the discards and the moves; what the card did (draws, the ONGOING replaced) is not narrated yet (D3 / E2, `effects/narrate.py` for schemes).
