# Backlog for the remaining phases (Hellboy box, both sides)

From reviews (28/10):
- Human maneuver boost with BOOST 0 (Liz burning card) is accepted silently; add chat warning (docs/heroes/liz-sherman.md:71 claims it warns).
- Game.maneuver not atomic: BOOST 0 RuleError after use_action() + draw(); validate before. Same for attack _check_boost after IMMEDIATELY.
- Tests for BOOST 0 use patched cards; add tests with real Liz burning cards.
- Bot Flame Lash: DURING (bottom-of-deck boost) not applied for the bot (no controller passes boost). Effects phase.
- "One ONGOING per player" only covers combat_bonus; Baba Yaga pacts not modeled yet. Effects phase.
- Incinerate "tu opcion" announced after damage applied: human fixes with +1/-1. Choices phase should make it a real choice.
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
- EffectState.copy() returns a bare state when is_empty() (ignores parked/choosers): search clones inherit fx.choosers only sometimes. When human DSL heroes get triggers, give the search its own choosers (D1/D2).
- Cold Iron with human_deck_guid set: the draw block is only a chat line; a physical draw is accepted by sync_human. Probably unavoidable in TTS; decide in E2.
- Spanish comments added by E1 in ui.py:31,45,185 and lua.py:1187-1188: translate (translation phase).
- No test resumes a save taken at a pause after the bot already moved/boosted mid-combat (projection-then-resume path). Add in F2.
- CANCEL is refused during a pause: if every option is refused, the combat can only be left with Restart.
- Look grant ignores card conditions (Confront only when lost, Psychometry only if adjacent): button appears whenever the card is played.
- Priced optionals on the attacker's side never pay (worth_paying sees at_stake 0); revisit in D1.
- set_panel labels via UI.setValue on a Button: verify live.
