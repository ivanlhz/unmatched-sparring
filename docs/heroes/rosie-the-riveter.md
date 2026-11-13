# Rosie the Riveter (Stars and Stripes)

Playable by the bot and by the human, either side, against every other hero. Data read from the real images of the tournament savegame on 2026-11-13: the deck (sheet 176), the hero card (card 402, sheet 4), the rules card of the upgrade row (card 17700, sheet 177) and the four upgrade tokens of her bag. unmatched-memory's transcription of the cards (made from screenshots, "unverified by Ivan") was compared card by card with those images: see "Verification of the transcription".

## Summary
- Melee hero, 15 life, move 2, sidekick **Wendy The Welder** (melee, 7 life, move 2, one of them). Hero fid `rosie`, sidekick fid `wendy`, slug `rosie-the-riveter`. Wendy's attack is blank in unmatched-memory; the hero card prints MELEE for her (`sidekicks[0].attack` in the overlay).
- Ability, **FREEDOM XK-II MECH SUIT**: four upgrade tokens, all inactive at the start; at the start of your turn activate an upgrade; at the end of your turn, if all four are active, deactivate all of them.
- Deck: 30 cards, `CardID = 17600 + idx`. Restriction band: ROSIE on We Can Do It!, D-Day, Overrun, Full Metal and Hasty Repairs; WENDY on Arc Welding, Rapid Development and "E" Award; ANY on Momentous Shift, Loose Lips Sink Ships! and Technological Superiority. The deck object in the save holds 31 cards (the 30 plus the hero card 402), hence `card_count 31` and `card_ids [402, 17629]` in the catalog.
- Table: bag `5a93d0` (inner `628b52`), deck `955c05`, Rosie's miniature `862e16` (a Custom_Assetbundle) and dial `facfe3` (max 15), Wendy's miniature `39768f` (a Custom_Token) and dial `45adc0` (max 7), the four upgrade tokens (`tokens` in `data/tts/rosie-the-riveter.json`: `merlin_engine` d670b6, `cavity_magnetron` e5ef35, `sedgley_fist_gun` 85c49f, `whizbang` f45e71) and the loose rules card 17700. Her life dial `facfe3` is also Wyatt Earp's (told apart by the dial name); no other GUID of hers is shared.

## The upgrades (read from the tokens, not from unmatched-memory)
The four tokens are double-sided Custom_Tokens with no nickname; the effect is printed on them (the active face has the colour, the inactive face is grey), and the numbers 1 to 4 printed on the inactive face give the order. The rules card 17700 says: "Rosie's upgrades start each game in order, numbered from 1 to 4 on the inactive side. To activate an upgrade, flip your leftmost inactive upgrade face up. To deactivate an upgrade, flip the leftmost active upgrade face down and move it to the end of the row on the right side."

| # | Upgrade | Token | Effect printed on it |
|---|---|---|---|
| 1 | MERLIN ENGINE | d670b6 | When you maneuver, Rosie may move 1 additional space. |
| 2 | CAVITY MAGNETRON | e5ef35 | After Rosie attacks, you may draw 1 card. |
| 3 | SEDGLEY FIST GUN | 85c49f | Add +1 to the value of Rosie's attacks. |
| 4 | WHIZBANG | f45e71 | Rosie is a ranged hero. |

State, as the rules card describes it: the active upgrades are always the first ones of the row, so the whole state is two numbers, kept as the hero's ability counters of the effects file: `upgrades` (how many are active, 0..4) and `upgrade_shift` (how many times the row has turned, 0..3; the row is the starting order rotated left by it). Activating flips the leftmost inactive upgrade (`upgrades` + 1); deactivating one flips the leftmost active and sends it to the end (`upgrades` - 1, `upgrade_shift` + 1); deactivating all four turns the row four times, which is the identity (the reset at the end of the turn is `counter upgrades set 0`).

Where each piece lives (all of it is data of the HeroDef passive `freedom_xk_ii`, `data/heroes/overlay/rosie-the-riveter.json`, read by `sparring/upgrades.py`):
- `row` is the starting order with the `grants` of each upgrade: `maneuver_move` 1 (Merlin Engine), `draw_after_attack` 1 (Cavity Magnetron), `attack_bonus` 1 (Sedgley Fist Gun), `ranged` (Whizbang). Changing what an upgrade does is changing that entry.
- **Sedgley Fist Gun**: the hero's own DURING (`ability.during` of the effects file, condition: the hero fighter attacks and the upgrade is active) runs the plugin `rosie:attack_bonus`, which adds the `attack_bonus` grants of the active upgrades to the attack (the combat chat shows "SEDGLEY FIST GUN (+1)"). It is on the hero, not on the card, so cancelling the card's effects does not take it away; Wendy's attacks and Rosie's defenses do not get it. It is read when DURING resolves, so We Can Do It! flipping it in IMMEDIATELY counts for that very attack.
- **Whizbang**: `Fighter.ranged` of the hero is kept in step with the counters (`upgrades.sync`, called by `EffectState.set_counter` and when a save is loaded), so the reach rules, the bot's positioning and the search all see her as a ranged hero while it is active. Wendy stays melee.
- **Merlin Engine**: the hero's move value is the printed 2 plus the `maneuver_move` grants of the active upgrades (`upgrades.sync` keeps `Fighter.move` in step); the move value is only read where a Maneuver is planned or done, so Rosie moves 3 in a Maneuver (4 with a BOOST 1 card) and every planner, the search and the estimate of a rival's reach see it. Wendy gets nothing. Effects that move Rosie keep the numbers on their cards.
- **Cavity Magnetron**: a trigger of the effects file (`after_attack`, hero, condition `rosie:upgrade cavity_magnetron`): an `optional` draw 1 for the owner (panel for the human, the bot takes a free draw unless its hand is full).

## Card identity: the shared CardID range
Her deck is sheet 176 like Medusa's and every other deck of the sheet: the same CardIDs 17600-17629, a different image (`data/tts/rosie-the-riveter.json`, `deck.identity`). Everything in docs/card-identity.md applies; the proof is `tests/test_hero_rosie_the_riveter_data.py` (ranges equal, images disjoint from the other decks, no card equal across decks, detection in both seats against every other hero, catalog entry, no shared GUID), `tests/test_card_identity.py` (she is in `SHARING`) and `tests/test_rosie_the_riveter_matrix.py`. The loose rules card has CardID 17700, the same number as Houdini's hero card (another image); nothing reads it and detection by image still tells the heroes apart.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Fighter | Effect |
|---|---|---|---|---|---|---|
| We Can Do It! | attack | 4 | 2 | 2 | Rosie | IMMEDIATELY: activate an upgrade |
| D-Day | attack | 3 | 1 | 3 | Rosie | AFTER: gain 1 free action to attack; if all four upgrades were already active, 1 damage to the opposing fighter and Rosie recovers 1, otherwise activate all of them |
| Overrun | attack | 3 | 1 | 3 | Rosie | AFTER: move Rosie up to 3 through opposing fighters, then 1 damage to each one she moved through |
| Full Metal | versatile | 1 | 3 | 3 | Rosie | DURING: +1 for each active upgrade |
| Momentous Shift | versatile | 3 | 1 | 3 | any | DURING: if your fighter started this turn in a different space, the value is 5 |
| Loose Lips Sink Ships! | versatile | 2 | 2 | 3 | any | DURING: reveal the top card of the opponent's deck, their card is worth its BOOST value less |
| Technological Superiority | versatile | 3 | 2 | 3 | any | IMMEDIATELY: with 3 or more active upgrades, cancel all effects on the opponent's card |
| Arc Welding | versatile | 3 | 3 | 3 | Wendy | AFTER: choose one: activate an upgrade, or 1 damage to each adjacent opposing fighter |
| Hasty Repairs | defense | 1 | 2 | 3 | Rosie | AFTER: with any active upgrade, deactivate one and Rosie recovers 3 |
| Rapid Development | scheme | - | 3 | 2 | Wendy | draw 2, activate or deactivate an upgrade, gain 1 free action to attack |
| "E" Award | scheme | - | 3 | 2 | Wendy | activate or deactivate an upgrade, move each of your fighters up to 3 |

## Verification of the transcription (unmatched-memory vs the real cards)
Every title, type, value, boost, copy count, restriction band and text of the eleven titles was compared with the images of sheet 176. **No mismatch of a value, a boost, a copy count, a band or a text.** Differences that are not errors:
- The transcription lists the titles in another order than the sheet (We Can Do It!, Overrun, D-Day, ... against the sheet's We Can Do It!, D-Day, Overrun, ...); the overlay follows the sheet (the CardID of each copy depends on it). Sheet order: We Can Do It! 0-1, D-Day 2-4, Overrun 5-7, Full Metal 8-10, Momentous Shift 11-13, Loose Lips Sink Ships! 14-16, Technological Superiority 17-19, Arc Welding 20-22, Hasty Repairs 23-25, Rapid Development 26-27, "E" Award 28-29.
- Wendy's `attack` is blank in the transcription; the hero card prints MELEE.
- `"E" Award` is printed with curly quotes on the card; the data keeps the straight ones of unmatched-memory (the title only has to be the same string in the overlay and the data).
- Momentous Shift has `sourceId: 5` (the others 798-807): a transcription artefact with no effect.
- The special ability text matches the hero card word for word. The `_source` note about "[RUSE]" marks is Washington's, not hers.

## Rule decisions (the most literal reading of the card; see "Decided by Ivan" and "Pending Ivan")
1. **Start of turn**: the leftmost inactive upgrade is activated (nothing when all four already are: a card on the rival's turn may have done it). The trigger runs for both seats in the engine; for the human it is only a chat line.
2. **End of turn**: only when all four are active; they are all deactivated and the row keeps its order. A card that activates the fourth upgrade on your turn therefore gives its benefit for that turn only.
3. **Whose cards count**: "you have N active upgrades" is the whole row (the player's), not per fighter. The upgrades' own effects belong to Rosie, the hero fighter, never to Wendy.
4. **Technological Superiority**: "3 or more active upgrades" is read when IMMEDIATELY resolves (the defender resolves first). Full Metal reads the count when DURING resolves.
5. **Loose Lips Sink Ships!**: the revealed card stays on top of the deck (revealing is not discarding). The top card is revealed even if the opponent played no card (a defender who did not defend); the value change then has nothing to act on. The value never goes below 0. For the human's deck the bot reads the real top card through the table (Jill Trent's route) and a table that cannot be read shows nothing.
6. **Momentous Shift**: as Sinbad's and Bigfoot's identical card.
7. **Overrun**: as Daredevil's Through Adversity: "moved through" is an opposing fighter on some path of at most 3 spaces. The human moves the miniature by hand and the panel asks which opposing fighters she passed.
8. **Arc Welding**: the printed list "choose one" is a `choose_effect` of one option; "each adjacent opposing fighter" is each opposing fighter adjacent to the fighter that played the card (Wendy), at the time the AFTER resolves.
9. **"Activate or deactivate an upgrade"** (Rapid Development, "E" Award): a choice of the owner (panel for the human, the bot's EffectAI decides). An option that cannot do anything (all four active; none active) does nothing.
10. **Hasty Repairs**: read literally, both "deactivate one" and "Rosie recovers 3 health" depend on having an active upgrade.
11. **D-Day**: "Activate all of your upgrades. If they were already active, ..." is read as: all four were already active before the card activated them.

## Engine additions (additive: docs/effects-dsl.md, section 44)
- `sparring/upgrades.py`: the row of upgrades as data, its two counters, `activate` / `deactivate`, the bonus parts and `sync_ranged`.
- `EffectState.set_counter` keeps `Fighter.ranged` and `Fighter.move` of the hero in step with the counters (`upgrades.sync`); `persist.apply_game` does it after a load. Nothing else of the engine changes: Sedgley Fist Gun is the hero's DURING, Merlin Engine is the hero's move value.
- Plugins (`sparring/effects/plugins_rosie.py`): `rosie:deactivate`, `rosie:attack_bonus`, the test `rosie:upgrade` and `rosie:loose_lips`.
- The session (`sparring/session_rosie.py`) says every change of the row in the chat, for either seat, and flips and pings the physical tokens for the bot's Rosie (`sparring/tts/lua_rosie.py`).
- AI (`sparring/ai_rosie.py`): Full Metal is priced at 1 + the active upgrades; the effects of We Can Do It!, D-Day, Overrun, Arc Welding and Hasty Repairs are priced in the AFTER evaluation. The bot's estimate of an attack (`Game.attack_bonus`) does not include Sedgley Fist Gun's +1 (it is a DURING effect); the combat itself does (open question 8).

## Decided by Ivan (2026-11-13)
1. **The four upgrade effects** as read from the tokens (MERLIN ENGINE, CAVITY MAGNETRON, SEDGLEY FIST GUN, WHIZBANG: table above) are confirmed.
2. **"Gain 1 free action to attack"** (D-Day, Rapid Development) is attack-only: `gain_action` with `only: attack` (`fx.attack_credit`, as John Henry's; Wyatt Earp's own free actions use `Game.free_attacks`); a Maneuver or a scheme cannot spend it, an attack can (the free one is spent first).
3. **D-Day "if they were already active"** means all four upgrades were active before the card.
4. **Hasty Repairs**: the heal also needs an active upgrade.
5. **The bot flips the physical upgrade tokens** when the engine activates or deactivates an upgrade, re-orders them by the row rule and pings each token it flips or moves (see "The tokens on the table"); the chat message stays. A human Rosie flips her own tokens by hand following the chat.

## Pending Ivan
1. **Cavity Magnetron for the bot** takes the draw unless its hand is already at the limit.
2. **Card 17700** (the rules card in her bag) has Houdini's hero-card CardID. Nothing reads it today.
3. **The AI does not count Sedgley Fist Gun's +1 when it chooses an attack** (the engine does when the combat resolves). Putting it in `Game.attack_bonus` needs a hook in `sparring/state.py`; not done.
4. **Token faces and spots, to verify live** (`token_faces.*.verify_live` in `data/tts/rosie-the-riveter.json`): the inactive face is up at Z rotation 0 and the active face at 180 (Abe Sapien's Intuition tokens, confirmed live, are the same kind of object); the four resting spots are taken from where the tokens lie when a game starts (the start order 1 to 4 left to right; the layout of the table gate lays them in the order of the bag).

## The tokens on the table
`sparring/tts/lua_rosie.py` (`set_upgrade_tokens`) puts the four tokens as the engine has them, in one write: the first `active` tokens of the row on their active face (Z 180), the rest inactive (Z 0), and each token on the resting spot of its place in the row (a deactivation sends the token to the end of the row, so the others shift one spot left). A token already right is left alone; every token it flips or moves is pinged, `PING_GAP` apart (the pinger of the other token scripts). Only token-type objects are touched. `session_rosie.track` calls it for the bot's Rosie whenever the engine state differs from what it last put there, and always at the first look of a game or a resume (an absolute write, like Jill Trent's gadget token). The four spots are kept in `Session.upgrade_slots` and saved with the session (`upgrade_slots`); a resume with none reads them from the tokens' positions in the row's current order. A token that cannot be found, or a write that fails, is said once in the chat (`rosie.token_missing`, `rosie.token_failed`) and the game goes on; the table gate's reset turns the four tokens back to their inactive face (`table_reset.START_FACE`). Tests: `tests/test_rosie_upgrade_tokens.py` (the Lua on the lupa stub: live-like objects with a Z rotation, flips, swaps, pings) and `tests/test_rosie_upgrade_tokens_session.py` (FakeTTS with live-like tokens, resume included).

## AI
- The AI profile comes from the data (`ai_profile`: Rosie `hero`, melee; Wendy `striker`). The reach of Whizbang and Merlin's extra space are the fighter's `ranged` and `move`, which every planner reads, so they see the active upgrades; Sedgley Fist Gun's +1 is only in the combat, not in the AI's estimate of a blow.
- Activate-or-deactivate choices are decided by the generic effect AI (it takes the option that helps most in a simulation; on a tie, activate).

## Tests
`tests/test_hero_rosie_the_riveter_data.py` (data, card identity, the transcription check), `tests/test_rosie_the_riveter_effects.py` (the upgrade row, the ability, every card, the AI's valuation), `tests/test_rosie_the_riveter_human.py` (FakeTTS, the panel: the human's cards and tokens), `tests/test_rosie_the_riveter_matrix.py` (full games against every other hero in both seats).
