# Backlog for the remaining phases (Hellboy box, both sides)

From reviews (28/10):
- DONE in E2: Human maneuver boost with BOOST 0 (Liz burning card) is warned at Fin de accion (`maneuver_baseline`).
- DONE in E2: Game.maneuver validates the boost card and the movers before use_action() + draw(). The attack's _check_boost after IMMEDIATELY is covered by the session (the boost is checked at Continuar and a RuleError restores the snapshot).
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
- DONE in E2 (decision): a physical draw under Cold Iron cannot be blocked in TTS; sync_human warns once ("Tu mano ha crecido...") and counts the card (the table wins).
- Spanish comments added by E1 in ui.py:31,45,185 and lua.py:1187-1188: translate (translation phase).
- No test resumes a save taken at a pause after the bot already moved/boosted mid-combat (projection-then-resume path). Add in F2.
- DONE in E2: Cancelar during a pause answers the request with nothing ("No" / none picked) when the card allows it; a forced pick says so (the card is played).
- Look grant ignores card conditions (Confront only when lost, Psychometry only if adjacent): button appears whenever the card is played.
- DONE in E3: with the human's hero interpreted the look happens inside the card's run (conditions are the engine's) and the bot shows its hand then; the grant-a-button route stays only for a hero outside the interpreter.
- DONE in D1: `_cost_context` gives the attacker a stake (the damage the defense blocks); no box card asks it today (Incinerate is attack-only).
- set_panel labels via UI.setValue on a Button: verify live.

## From D1 (29/10)
- DONE in E3: Perfect Shot's plugin asks its owner; the bot predicts (`predict_value`) and announces when it places the card, the human gets the buttons at Revelar before the bot defends.
- Narration of Medusa's cards: D1 narrates only the box heroes (the C5 oracle compares `applied` byte for byte). Ask Ivan whether the bot should also say what Medusa's cards did ("Aplicado: Regroup: roba 2"); if so, the C5 session/twin oracles must ignore those lines and the session goldens change.
- DONE in D2 (Ivan 29/10, required): bot Liz leaves a burning card at the bottom with Pyrotechnics (pick, order and the optional); Glimpse Of Hell / Read The Bones keep the generic rules (they shuffle or draw, nothing of theirs stays at the bottom).
- Bot Liz's Fleeting Moments / Confront make the human discard a specific card the engine chose: the chat names it; the physical move is D3's.
- DONE in E3: Remove A Painful Memory by the bot: the buttons read "Descartar <carta>" / "Coger 2" and the prompt names the trade.

## From D2 (29/10)
- A bot scheme that asks the human (Pact Of Secrecy: the human keeps 2) returns an Await from `MedusaAI.execute`; the session ignores it today (the card would stay unfinished). E2 must drive it like `Session.play_effect`.
- `MedusaAI.plan`'s two-level lookahead values an attack on a hero at 1 hp as highly as the scheme that kills it for sure (expected attacks never set `winner`); with one action left the sure kill wins. Pre-existing, left as is.
- The search's rollout plays no schemes (attacks and maneuvers only), as before; scheme lines are explored by the tree only.
- `ongoing.worth` gives the symmetric pact rules 0: whether a Pact Of Time / Secrecy favours the bot is left to what the tree simulates after it.
- Session chat for a bot scheme (`_action_text`, kind "scheme") says the title, the discards and the moves; what the card did (draws, the ONGOING replaced) is not narrated yet (D3 / E2, `effects/narrate.py` for schemes).
- DONE in D3 (Ivan, 29/10): the bot narrates Medusa's cards too; the C5 oracles ignore the narration lines only.
- Bot Pyrotechnics / Glimpse Of Hell / Read The Bones use the generic card rules of EffectAI (lowest keep_value goes back, best card_worth is taken): no Liz-specific play (a burning card at the bottom for Wildfire). D2 if it matters.
- DONE in D3: a specific human card the bot discards is owed by name (`pending_discard["cards"]`); Fleeting Moments' random pick is the human's (force_discard route).
- DONE in E3 (see above).

## From D3 (29/10)
- verify_live: bot Hellboy's form change (`set_state` f9789a <-> e6f06e, `flip_token` 1644a3: the flip is unconditional, so the token must start on OCCULT DETECTIVE; `ping_objects` on both); Abe's Intuition copies taken from 5a17e9 (`take_token_copy`: takeObject or clone by object type) and `remove_token` of a copy; `hand_to_deck` (putObject straight from the bot's hand zone, bottom = deck turned over) and `card_to_deck_bottom`; `return_card_to_hand` of a discard-pile card; `move_piece` of the human's miniature by the bot; the `read_hand` of the human seat at a look (one message); `token_spot` (default beside the bot's deck: calibrate).
- Every Possible Angle by the bot: the human puts the named card on top of their own deck by hand; the session only skips that card when padding the virtual hand. Pact Of Secrecy / Pact Of Time on the human: chat only, the sync follows the counts.
- Read The Bones (bot): the engine's deck order is not the real one; the card it took becomes a draw from the top (`drawn`). A real "look at 5, pick 1" on the table (`deal_row`) is not wired.
- A bot scheme card that pauses for the human stays physically in the bot's hand until the answer; an ONGOING scheme of the bot is never placed on the table (D2).
- DONE in E2: a pick out of the human's own hand is never shown at the panel: the op leaves a table note ("quedate con 2 cartas de tu mano, pon el resto en tu mazo y baraja") and the sync follows the counts.
- Bot Liz's Wildfire start-of-turn effects now reach the table (they did not before D3): one message before her first action (test_multihero_bridge budget).
- A failed projection (piece move, state swap, token, deck move) is said once ("hazlo tu"); the table wins at the next read, no retry queue.
- (D3 review) Bot Liz pays one extra script at turn start (Wildfire discard projected at the turn change), a deviation from "one combined script per step"; fold it into the first action's composite if latency matters live.

## From E2 (29/10)
- Ivan's answers (29/10) applied: (1) a dedicated ONGOING zone below each combat zone (`human_ongoing_spot` (x, z), `bot_ongoing_spot` (x, y, z), config/partida.json, calibrate with --read-only): the human leaves their ONGOING there and the session recognizes it there (`session_effects.recognize_scheme`, snapshot keys `ongoing_human` / `ongoing_bot`, builder `read_cards_at`); when it leaves play the card is owed to the discard pile ("pasala de tu zona ONGOING a tu descarte"); the bot's ONGOING goes face up there (`place_card_face_up`) and to its discard when it leaves play (the spot is in the discard scope). Without the spots: the discard-pile route plus one warning. (2) The human's start-of-turn ability (Hellboy draw / ANUNG, Wildfire) stays physical but the panel announces it and hides every button but Fin de accion and the hit points until it is done (`Session.ability_wait`, saved, `--resume` repeats it). (3) Crown Of Flame keeps blocking Fin de accion until the discards are on the pile. (4) Wildfire's return is folded into the card's own line (`narrate._fold_triggers`).
- Wildfire's start-of-turn (the human's Liz) and Hellboy's start-of-turn ability stay physical (the engine does not know the real deck order / the discarded card): the chat says what to do; the human applies the damage with -1 and moves by hand. If a `read_bottom_card` builder is wanted, it is F1's.
- Ivan (29/10, from E3's review): a cancelled attack on bot Abe whose UNCANNY INTUITION already fired carries its declaration to the same attack repeated (`Session.declared_carry`, saved; `Pending.declared["revealed"]` keeps the face-up): no second token, no second draw; a different attacker or target declares normally and the earlier spend stands.
- After the merge with E3: the search's `_choose_defense` returns no card when the root resolved the only legal defense itself (the attack known through UNCANNY INTUITION and a hand without a defense card); before, it read the next attack move as a card title and fell back to the heuristic (ISMCTS matrix, bot Abe vs Hellboy, seed 3). `ScriptedHellboy.choose_defense` takes `attack_card`.
- After the merge with E3: a card the look row moved (`session_hidden.close_row`) is in `fx_in_flight`, and `session_bot_effects.project` never moves it again in the same button (Every Possible Angle by the human as a recognized scheme).
- Review of dc3a859: `_grant_look_for` steps aside for an interpreted hero (the card itself looks: the human's Confront lost picks the bot's card at the panel, once, no look button; E3's row replaces the buttons). `_combat_step_done` projects with the right cause.
- Loss of branches (E2): the explicit opt-out route (`dsl_heroes: []` in a save, `human_card_outside_the_interpreter`) only narrates the text of Horseshoes / On Earth / Flame Lash now (the legacy engine-applied parts moved to the test oracle); and the search no longer branches the human Hellboy's ANUNG discard and move (the dispatcher decides it at `begin_turn` through `SearchController`), so those lines are not explored by the tree.
- The human's Confront / Every Possible Angle / Remove A Painful Memory pick among the bot's hand at the panel by title until E3's row and ping land (E3 wraps `session_effects.human_chooser`).
- An ONGOING scheme of the human sits on their discard pile while in play (recognized there); `sync_human` skips the card in play. The alternative (the card in front of the player) would need a read of that spot.
- The narration of a human card that discards a burning card from the deck (Flame Lash) says "descartas X" and the Wildfire return is a separate "Tu habilidad" line at the end of the button; a combined wording is cosmetic.
- A card the human returns from the discard to the hand (Ward And Prepare) is moved by the engine and asked for on the table; if the human has not moved it by the next read, the sync re-adopts it into the discard (the table wins) and the bot forgets it is in the hand.
- The search now enumerates the human's schemes too (`adapter._scheme_moves` for any interpreted hero): watch `test_play_ismcts` budgets.
- verify_live (E2, Ivan's answers): `human_ongoing_spot` / `bot_ongoing_spot` (default 4 units below the combat spots in config/partida.json: calibrate with --read-only, outside the discard zones and the hand zones); the bot's `place_card_face_up` leaves its ONGOING face up on its spot and `discard_cards` finds it there when it expires; the human's ONGOING is read on their spot (face up or down); the start-of-turn gate hides every button but Fin de accion and the hit points (and the status line says so).
- verify_live (E2): the choice buttons of a human scheme (Pancakes!, Posthumous Power) and a resume mid-scheme; Pact Of Secrecy's "0/1/2" amount buttons; the FATEFUL BARGAINS prompt; the "Ninguna" button of an optional move; Flame Lash with the real bottom card (burning and not); a Counterhex Shield / Fight Or Flight left on the discard pile while in play.

## From E3 (29/10)
- verify_live: `ping_points` over the row spots (the bot pings its own face-up hand); `resolve_hand_row(deck_guid=)` (`putObject` of a loose row card onto the bot's deck: Every Possible Angle by the human); the bot's attack card flipped face up right after `play_card_face_down` in the same script (Perfect Shot, UNCANNY INTUITION on the human's Abe); the prediction buttons' second page ("Mas" then "Boca abajo").
- The human's hero must be in `fx.dsl_heroes` for E3's human side (E2 switches it on); until then Confront / Psychometry / Every Possible Angle / Remove A Painful Memory by the human keep E1's button and the chat text.
- DONE (Ivan, 29/10): the human's Perfect Shot face up is public, the bot's defense knows it (`session_hidden.declare_attack`).
- DONE (Ivan, 29/10): UNCANNY INTUITION of the bot's Abe keeps the engine's order: the `attacked` event (token spent, card drawn and dealt) before the defense is chosen, so the drawn card may be the defense; `Game._declare_attack` does the same headless and passes `attack_card` to the defense when the ability reveals it. Still open: the human puts the attack face down (the face-down reader identifies it) and it is turned at Revelar; a face-up reader in the combat zone would let them play it face up directly. The event is raised outside `_resolve_combat`'s rollback (a combat refused after it keeps the spent token).
- DONE (Ivan, 29/10): the chat says "El bot se queda X (Wildfire la devuelve)" when Wildfire bounces a card the human's Confront discarded.
- E3 review fixes: a partial row keeps `mode`/`purpose` (`_look_shown` rebuilds only the list keys), a card the table left in the hand is picked by its button and reaches the pile through the reconciliation; `resolve_hand_row(deck_guid=)` handles a one-card deck (a Card: the chosen card is dropped on it with the same facing); `TTSClient.send` retries WinError 10048 like `FakeTTS.push`; `EffectState.interprets` is the one "hero on the interpreter" helper.
- Every Possible Angle by the human then asks the move of Abe at the panel (a `space` request); E2's table mode should make that announce-only (the human moves the miniature).
- The engine's order of the bot's deck is rebuilt from the table at every `read_bot_hand`: a card put on top (Every Possible Angle by the human) is on top of the REAL deck only; the human's `KnownHand.top_of_deck` records it.
- Remove A Painful Memory by the human: the bot's answer is said as where the card ended ("descarta X" / "se queda X"); the 2 damage shows in the dials and the combat text, not in a dedicated line. When bot Liz's Wildfire returns a burning card the human's Confront made her discard, the chat names it ("se queda X (Wildfire la devuelve)").
- A bot defense that draws before the human's look (Evade, Exploit, B.P.R.D. Training): the pick request is built with a placeholder for the card the table has not dealt yet; `show_row` refreshes the request's options from the re-identified hand (tests/test_e3_hidden_info.py, the Evade case). The dealt card is in the row.
- After E2 lands: `session_bot_effects._bot_cards` would also see the hand -> deck move of Every Possible Angle if a scheme of the human were projected; `close_row` already moved it (use `fx_in_flight`, which `project` resets, or skip ids the row moved).
- (Ivan 29/10) ONGOING zone: only face-up ONGOING cards count there; a non-ONGOING scheme left on the spot is ignored and the human is told to move it to the discard. read_cards_at / the batch snapshot read face-up cards only (a face-down card is never read).
- (Ivan 29/10) Start-of-turn gate: HP (+1/-1) and Retirar stay visible during the wait (Wildfire damage). Start-of-turn abilities (Wildfire bottom card, Hellboy draw/ANUNG): the human does them when he plays the hero; when the bot plays the hero they run automatically (already the case since D2/D3). No read_bottom_card builder.
- (Ivan 29/10) Random discard from the HUMAN's hand (Fleeting Moments...): the engine draws the position(s) with the game rng from the hand size only and the chat says 'al azar: la carta K de tu mano contando desde la izquierda'; memoized in run.flags so a resume names the same positions.
