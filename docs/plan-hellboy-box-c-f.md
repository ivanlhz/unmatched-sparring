# Plan: phases C-F (effects interpreter through live readiness)

Read from master ff6fa3c. Facts: Game.observe_hand is never called; the combat-flow design defers real mid-combat pauses to E1; btn_look is always visible greyed (against Iván's hidden-not-grey rule).

## Cross-cutting
- Game.fx: EffectState in sparring/effects/state.py (cloned, persisted): statuses, the one ONGOING per player, ability counters, active rule modifiers. Flag fx.dsl_heroes: set[str] turns the interpreter on per hero; heroes not in it keep the legacy path, so each phase lands with goldens green.
- Chooser protocol (sparring/effects/choose.py):
  ChoiceRequest(kind: fighter|space|cards|effect|optional|order|amount, player, options, min, max, card_id, key (op path e.g. "after/1/then/0"), prompt)
  Chooser.choose(game, req) -> list | Await
  Impls: ControllerChooser (bot; new Controller.choose_effect(game, req), default falls back to choose_move/choose_discard/choose_placement); PanelChooser (human; Await(PendingChoice(kind="effect")) unless answer for req.key present); SyntheticChooser (ISMCTS/rollouts; policy or rng; for the hidden opponent only sees the determinized hand); ScriptedChooser (tests).
- Re-entrant runner (sparring/effects/run.py): EffectRun(owner, card_id, moment, frame stack of (ops_path, idx), bindings serialized as card ids/fids/player numbers, answers); step/run -> Await|None, resume(answer), to_dict/from_dict. Ops atomic: ask all choices before mutating; on resume only the current op reruns (same contract as CombatFlow handlers).
- Human-owned cards: run(..., table_mode=True) marks physical ops (human's own draws, discards, moves of own pieces) as announce-only; table sync reconciles them. Everything touching the bot or engine-only state runs in the engine. Bot-owned choices go to ControllerChooser even inside a human card.

## Phase C: interpreter
C1 core (first): sparring/effects/ model.py (load/index effects JSON), select.py (FighterSel, SpaceSel, CardSel, Amount, Condition, bindings), choose.py, run.py, ops_core.py (@op registry). Ops: damage, heal, set_hp, draw, discard, choose, choose_effect, move, place, swap, revive, summon, counter, gain_action, end_turn, if, optional (cost/else), for_each, plugin registry. state.py gets ALL hook stubs now as no-ops: fx.adjust_damage in damage, fx.can_draw, fx.can_gain_actions, fx.emit(event) in begin_turn/end_turn/discard_card/force_discard/attack (before choose_defense)/maneuver/death; fx in clone and persist (so C2-C4 never edit state.py). Tests: one per op on Game.new twins; selector edges (pick one with no candidates = no-op, pick all on zero); test_run_roundtrip_mid_op; test_op_atomic_no_mutation_before_await. Accept: suite + goldens unchanged (flag off); runner+ops >=90% coverage.
C2 combat + modifiers (effects/ops_combat.py, effects/modifiers.py, rules in combat_flow.py): cancel_effects (respects uncancelable), modify_value, set_value, boost, status with until, redirect_damage (op and passive), may_boost both sides (replaces text detection in combat.can_boost/deck_boost; Out Of Time can boost in defense). New CombatFlow rules dsl_immediately/dsl_during/dsl_after after the legacy rules, matching only dsl_heroes, EffectRun inside flow.to_dict. DAMAGE hook for combat-damage redirect (Bound In Blood); effect_damage_bonus except exhaustion. Tests: Feint/Planned Recklessness/Ward And Prepare cancel; Incinerate uncancelable; Arcane Dampener -3 clamps 0; Shock And Awe value 4; On Earth + Fight Or Flight; bot Flame Lash bottom-of-deck boost; Counterhex blocks enemy effect damage/moves/forced discards; FATEFUL BARGAINS redirect optional asks chooser.
C3 events/triggers/ongoing (effects/events.py, effects/ongoing.py): events of DSL §2.10, ability triggers and passives, the ONGOING slot (combat_bonus/add_combat_bonus become thin views over it; goldens unchanged); until expiry incl. Pacts' "2+ combat damage to Baba"; discard zone:in_play. Hellboy DSL triggers replace hellboy_detective_draw/hellboy_anung_start (kept as wrappers). Tests: one ONGOING per player across pairs (Pact, Counterhex, Fight Or Flight); Pact of Peace; Pact of Secrecy max hand 3 at end_turn; Pact of Time blocks gain_action; Wildfire card_discarded returns burning card (hand and deck discards); Uncanny Intuition attacked fires before defense is chosen.
C4 hidden info (effects/ops_info.py + KnownHand in state.py, which C1 does not touch): look_hand -> observe_hand(owner, ...) as the ONLY caller; reveal, look_deck, search_deck, return_to_deck, put_in_hand. KnownHand: known top_of_deck (Every Possible Angle), "degrade to possible" (Glimpse Of Hell, Pyrotechnics), subset-of-2 (Pact of Secrecy). Unify search Knowledge.known_in_hand with KnownHand. Tests: tripwire bot never reads human hand outside look_hand; seen cards forgotten as they leave; random pick never reads identities.
C5 switch Medusa (after C2-C4 merged): tests/test_medusa_dsl_diff.py: sim + FakeTTS goldens with Medusa in dsl_heroes vs out, byte-identical, plus per-card twins. Known divergence: Winged Frenzy placement mandatory in DSL, optional in engine -> keep choose_placement None legal behind compat unless Iván says otherwise. test_every_dsl_op_has_handler. Then delete _medusa_after and the Medusa branch of resolve_scheme.
  DONE (docs/effects-dsl.md section 15): Medusa interpreted by default (`INTERPRETED_HEROES`), presets carry the AI's planned targets into the runs (`effects/driven.py`), Iván's ruling applied (return mandatory; no golden changed, the AIs never decline), legacy code deleted and kept verbatim in tests/legacy_medusa.py as the oracle.
Parallel: C1 -> (C2 || C3 || C4, disjoint files since hooks landed in C1) -> C5.

## Phase D: bot plays its own hero
D1 bot combat cards (new sparring/ai_effects.py, EffectAI.choose_effect: targets by weight x damage, destinations by position_value, discards by keep_value, choose_effect/optional by clone simulation). Hellboy, Abe, Baba, Liz in dsl_heroes when bot plays them; remove _hellboy_after/_liz_after/_announce_bot_card for those; bot announces what it applied. Anti-cheat: every evaluation clone determinized (hidden_hand resample) before any look_hand runs on it. Tests: 4 heroes x all cards bot-owned scenario (state + chat line); tripwire clone evaluation never touches players[human].hand.
  DONE (docs/effects-dsl.md section 16): `BOT_INTERPRETED_HEROES` per side (the human's box hero stays legacy until E2, goldens byte-identical), `effects/narrate.py` says what each bot card did, `bot_card_after` / `_announce_bot_card` deleted (oracle copies in tests/legacy_combat.py), tests/test_d1_bot_cards.py. Perfect Shot's prediction is E3's (plugin registered, face down until then).
D2 schemes/abilities in AI and ISMCTS: heuristic scheme_acts and adapter._scheme_moves generic (one move per scheme title x SyntheticChooser variants greedy/safe); bot ONGOING placement with replacement; start-of-turn triggers in adapter._advance and ai_medusa.take_turn. Tests: ISMCTS within time budget; plays each hero's schemes; test_play_ismcts green for 4 heroes.
  DONE (docs/effects-dsl.md section 17): schemes decided inside the card by the chooser (presets only for Medusa), the heuristic values them by simulation, the search enumerates greedy/safe lines capped at 6, `ongoing.worth` scores the slot in both evaluations, `attacked` emitted in the search, Liz keeps a burning card at the bottom (Ivan 29/10), tests/test_d2_schemes.py.
D3 bot table side in session (session._bot_continue, lua.py): look_hand at resolution reads human hand from table (read_hand) then observe_hand; bot Hellboy form change lua.set_state(f9789a<->e6f06e), flip_token(1644a3), ping both; bot moves human pieces when its effect says (Concussion Device, Leap Away, Foul Journey, Pact of Freedom); Intuition token toggle for bot Abe. Tests: FakeTTS message assertions.
Parallel: D1 -> (D2 || D3).

## Phase E: human side
E1 choice infra: ui.py hidden buttons btn_choice_1..6 + Event.CHOICE {i}; lua.set_panel gains labels; Pending.effect: EffectRun|None and Session.wait_effect saved under "pending" with backward-compatible load; --resume re-shows buttons. Real mid-combat pause with game mutated: CombatFlow persisted; RuleError rollback becomes "restore from snapshot". panel_view: choice buttons visible only while a PendingChoice exists; btn_look visible only when a card grants it (Iván to confirm). Tests: test_choice_buttons_hidden_without_pending; test_resume_mid_effect; test_old_save_loads.
E2 human cards affecting bot/engine (table mode). Automatic: damage to bot fighters with dial writes; statuses/rules on the bot (Cold Iron, Counterhex, Burning Barrier, Pacts, Planned Recklessness); value mods and cancels; bot discards it chooses (Shock And Awe, Clutching Claws, Hiss and Slither); bot hand-size and deck moves (Pact of Secrecy, Pact of Time) via bridge; revives/summons the human places physically accepted by sync. Buttons: Posthumous Power, Pancakes! (choose_effect); FATEFUL BARGAINS/Koschei redirect only when effect damage hits Baba while Koschei shares her zone; bot plays Incinerate -> "discard 2"/"keep". Tests per human-played card: engine state matches; chat says what is physical.
E3 hidden info: Confront, Every Possible Angle, Remove A Painful Memory by the human -> bot hand face up + ping, human chooses by pinging that row, bot answers its own "discard or take 2"; Every Possible Angle puts the card on top of the bot's deck. Advanced Psychometry reveal only. Fleeting Moments: engine rng picks bot card. Uncanny Intuition: human Abe -> bot attack card flipped face up; bot Abe -> panel asks human to flip, bot reads only that card. Perfect Shot: prediction buttons for human; bot announces its prediction. Bot Shock And Awe: discard at human's choice through existing pending_discard. Bot Remove A Painful Memory: bot names the card, human answers "discard"/"take 2".
  DONE (docs/effects-dsl.md section 19): `sparring/session_hidden.py`; the look is the interpreter's `look_hand` (conditions are the engine's), the row answers a pending pick by ping or button and closes where the engine put the card; Perfect Shot's plugin asks and the session pre-answers (human at Revelar, bot at placement); UNCANNY INTUITION read from the trigger; tests/test_e3_hidden_info.py.
Parallel: E1 -> (E2 || E3 only if E2 lives in new sparring/session_effects.py). E1 conflicts with D3 (session.py): serialize.

## Phase F: live readiness
F1 bridge pieces (lua.py): set_state, flip_token, card_to_deck_top, shuffle_into_deck, place_from_bag (reserve/summon), ping; each tested against the Lua stub.
F2 8 FakeTTS transcripts tests/golden/session_<hero>_<side>.json; each scripted session hits every card of the hero at least once + ability + a resume mid-choice; deterministic.
F3 docs/live-checklist.md for Iván: --read-only detection, token 1644a3 orientation, per hero: setup, one card per moment, an ONGOING replacement, a look-hand, a resume.

## Card map (C = ops; D = bot owns; E = human owns). All Medusa cards -> C5.
Hellboy: Excalibur, Service Pistol none; Second Shot C2; Horseshoes, Right Hand Of Doom, B.P.R.D. Training, On Earth C1/C2 E2; Planned Recklessness C2 E2; Posthumous Power, Pancakes! C1 E2 buttons; Crown C1 E2; Glimpse Of Hell C4 E2; Confront C4 E3; ability C3 + D3 form change.
Abe: Faster. Stronger., Secure The Scene, Leap Away, Concussion Device, B.P.R.D. Training, Utility Belt C1 E2; Arcane Dampener, Cold Iron, Ward And Prepare C2 E2; Counterhex Shield C3 E2; Shock And Awe C2 E3; Advanced Psychometry, Every Possible Angle C4 E3; Perfect Shot (plugin) C2 E3; UNCANNY INTUITION C3 E3.
Baba: Iron Teeth, Death's Release, Foul Journey, Hasten Towards Death, Deathless, Exploit, The Time For Deals Is Done C1/C3 E2; Out Of Time, Bound In Blood C2 E2; Read The Bones C4 E2; Remove A Painful Memory C4 E3; 5 Pacts C3 E2; FATEFUL BARGAINS C2 E2 button.
Liz: Fireball, Burning Barrier, B.P.R.D. Training, Evade C1/C2 E2; Flame Lash C2 E2; Incinerate C2 E2 buttons; Feint C2 E2; Fleeting Moments C4 E3; Pyrotechnics, Rekindle, Searing Clarity C4 E2; Fight Or Flight C3 E2; WILDFIRE C3 E2.

## Risks
Mid-combat pause with game mutated (E1): RuleError rollback assumes nothing changed before "Continuar". Anti-cheat in clone simulation (D1/D2): determinize before look_hand on clones. ISMCTS cost: cap scheme variants. session.py (3325 lines) conflicts: new code in new modules. Medusa differential: rng order of controller calls must match legacy.

## Phase G: other savegames (Iván, 29/10)
Today everything table-specific is tied to `saves/Unmatched Official Tournament Table October 2026 (Hellboy).json`.
Goal: point the bot at another savegame and get a working setup without hand-editing GUIDs.

What is savegame-specific now:
- `data/tts/<hero>.json` (extracted by hand from the save): bag GUIDs (outer infinite bag + inner bag), deck GUID, CardID
  range + character card id, deck identity (FaceURL, BackURL), fighter pieces (GUID per state), HP dials (+ MAX_VALUE),
  tokens (Hellboy 1644a3, Abe 5a17e9). In another save the GUIDs and CardIDs change; FaceURL/BackURL may or may not.
- `config/partida.json`: board_guid, seats (Green/White), hand triggers, ScriptingTriggers to ignore, probe_guids, and
  every spot (card/discard/deck/dead/look/unpack positions) calibrated to this table's layout.
- `data/maps/<board>.json` fitted to this board's snap points (`tools/fit_map.py`).
- Card identification: CardID ranges + FaceURL/BackURL identity (the save has 12 decks sharing DeckID 176).

Plan:
G1 `tools/import_save.py <save.json>`: read-only; walks the save, finds each hero bag (by name / character card / deck
   identity), writes `data/tts/<hero>.json` (GUIDs, CardID range, identity, pieces per state, dials, tokens) and reports
   what it could not match. Golden test: regenerating from the current save reproduces today's data/tts files byte for byte.
G2 Identity by image, not by GUID or CardID: match decks/cards by (FaceURL, BackURL) + position in the sheet, so a save
   whose CardIDs differ still maps to the same card titles; GUIDs found at runtime through hero detection (aa7b1aa).
G3 Table layout: derive board, seats and hand zones from the save/live table; spots relative to the board and hand zones
   instead of absolute coordinates; `--read-only` calibration report proposes values for config. Per-save config file
   (`config/<save-name>.json`) selected by flag, current one kept as default.
G4 Board maps: `fit_map.py` run on the new board; error if the board has no map.
G5 Docs: README section "Using another savegame" + checklist; F3 live checklist gains a run on a second save.
Order: after F (live readiness), before or together with the translation phase. Needs a second savegame from Iván to test.
