# Bullseye (Marvel, Hell's Kitchen)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 339 on sheet 3) on 2026-11-07.

## Summary
- Ranged hero, 14 life, move 2, **no sidekick** (unmatched-memory has an empty sidekick entry, ignored). Hero fid `bullseye`.
- Ability: **"Bullseye can attack from up to 5 spaces away (ignoring zones)."** It is data, not an effect: HeroDef `reach_spaces: 5` (overlay), read by the engine's attack validation, the bot's positioning and the search (docs/effects-dsl.md, section 31).
- Deck: 30 cards, `CardID = 17600 + idx`, every card on the BULLSEYE band (none ANY). The deck object in the save holds 31 cards (the 30 plus the character card 339), hence `card_count 31` in the catalog (`card_ids [339, 17629]` there is the min and max of those 31).
- Table: bag `4c1656` (inner `3db866`), miniature `ca1bc5`, life dial `166320` (max 14), deck `303a39`. No piece GUID is shared with another hero.

## Card identity: the shared CardID range
His deck is sheet 176 like Medusa's, the four turtles', Doctor Strange's and Bigfoot's: the same CardIDs 17600-17629, a different image (`data/tts/bullseye.json`, `deck.identity`). Everything in docs/card-identity.md applies; the proof is `tests/test_hero_bullseye_data.py` (ranges equal, images disjoint from the other seven, no card equal across decks, detection in both seats against all twelve, catalog entry, no shared piece GUID), `tests/test_card_identity.py` (Bullseye is in `SHARING`) and `tests/test_bullseye_matrix.py`.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| World's Greatest Assassin | attack | 4 | 3 | 2 | IMMEDIATELY: if you already won a combat this turn, ignore the value of the opponent's card |
| I Planned To Be Here | attack | 2 | 3 | 2 | DURING: if you started your turn in your current space, the value is 5 |
| I Never Miss | attack | 3 | 2 | 4 | DURING: you may BOOST this attack; if you don't, draw 1 card |
| For My Next Trick | attack | 2 | 2 | 3 | AFTER: move Bullseye up to 1 space, draw 1, gain 1 action |
| Feint | versatile | 2 | 2 | 2 | IMMEDIATELY: cancel all effects on the opponent's card |
| Arrogant But Effective | versatile | 2 | 2 | 3 | AFTER: you are considered to have won this combat; move Bullseye up to 2 spaces |
| I'm Better And I'll Prove It | versatile | 2 | 2 | 2 | DURING: if you already won a combat this turn, the value is 6 |
| Master Strategist | versatile | 3 | 3 | 2 | AFTER: move Bullseye exactly 4 spaces, through opposing fighters if you want |
| Ricochet | versatile | 3 | 2 | 3 | AFTER: if the opposing fighter was not defeated, 1 damage to a fighter in its zone |
| Right Between The Eyes | versatile | 3 | 3 | 2 | IMMEDIATELY: if you already won a combat this turn, the opponent discards 1 card |
| Tactical Retreat | defense | 3 | 2 | 3 | AFTER: place Bullseye in a space that shares no zones with his current space |
| Study The Target | scheme | - | 3 | 2 | draw 2; if you won a combat this turn, draw 1 more and gain 1 action |

## Discrepancies with unmatched-memory
- For My Next Trick: the card says "Move Bullseye up to 1 space"; unmatched-memory has "Move one of your fighters up to 1 space" (identical with no sidekick). The overlay carries the card's text.
- Study The Target: one scheme whose text sits on two lines; unmatched-memory has no space after "Draw 2 cards.". The overlay normalises it.
- Value, boost, type and copies of all 12 titles match unmatched-memory.

## Engine additions (all additive, docs/effects-dsl.md section 31)
HeroDef/Fighter `reach_spaces` with `Board.spaces_apart` and `can_reach_target(..., reach)`; the stat `combats_won_this_turn` (`fx.won`, next to `fx.lost`); the op `consider_won` (`CombatFlow.considered_won` / `won_by`); the card's `effects.unboosted` ops; the SpaceSel `no_zone_of`; the chat lines `narr.considered_won.*` and `tbl.where.no_zone*`. The hero detection limit `lua.MAX_HERO_RANGES` went from 12 to 24 (the thirteenth hero made every detection fall back to Medusa / Hellboy).

## The reach: up to 5 spaces away, zones ignored (added to the ranged zone shot)
- Measured in spaces along the printed adjacency of the map (`Board.spaces_apart`): never through secret passages or one-way edges, and no line of sight needed (the card does not ask for it). He is RANGED on his card, so the usual ranged rule (adjacent or sharing a zone) holds, and the reach ADDS to it: the attack is legal when the target is adjacent, or shares a zone, or is `1 <= spaces_apart <= 5` away whatever the zones. A target in his zone 6 or more spaces away is therefore in reach (on bprd-hq, space 8 against space 27), and one out of every shared zone 6 or more spaces away is not.
- **Human**: attacking from up to 5 spaces away goes through `Game.can_attack` like any attack and is accepted; from 6 the chat says "bullseye no alcanza a ..." and nothing is spent. The table is read for positions as always, so the human puts Bullseye where they want and counts the spaces themselves.
- **Bot**: `strike_spots(board, target_pos, ranged, reach)` is "every space from which the attacker's reach covers the target", used in the evaluation of where a fighter stands (the fear of a rival's reach and the bot's own approach). A ranged bot does not need to stand next to the rival (`APPROACH_PULL` pulls it to the nearest strike spot, which for Bullseye is any space within 5): the pull is zero once inside. The rival's own reach is read the same way: a melee rival is feared up to its Move + 1 away.

## "Already won a combat this turn" and "considered to have won"
The tally of combats won in the current turn (whoever's turn it is) is `fx.won`, recorded only when some loaded hero's data reads it. The combat being resolved is not counted until its damage is dealt, so IMMEDIATELY and DURING read "already won". The engine's win is "dealt damage" for the attacker and "took none" for the defender (a tie is won by the defender).

Arrogant But Effective (`consider_won`): from its AFTER on the combat counts as won by Bullseye's side for the effects that read it later (the rival's AFTER when Bullseye attacked, since the defender resolves first) and for the turn's tally; the damage already dealt is not undone, and the chat says "you are considered to have won the combat".

## I Never Miss
The free BOOST of `may_boost` (the human is offered it after Reveal, the bot decides with `choose_combat_boost`). When the owner declines it, or has no card to spend, the `unboosted` ops run right after in the DURING: draw 1 (the human is dealt it). A card cancelled before DURING (Feint) has no BOOST question and draws nothing.

## Rules decisions (the user is away: the most reasonable reading, applied)
Every item below is also an open question for Iván.

1. Reach: he is ranged (adjacent or same zone, as any ranged fighter) and "up to 5 spaces away (ignoring zones)" adds targets within 5 spaces along the adjacency whatever the zones. Secret passages do not shorten the distance.
2. "Already won a combat this turn" counts every combat of the current turn the player won, attacking or defending, on either player's turn; a combat won because of "considered to have won" counts too.
3. Arrogant But Effective: the whole result moves to Bullseye's side from its AFTER (tally, `combat_result` of later effects); the damage dealt is not undone. A combat Bullseye already won is left as it is.
4. World's Greatest Assassin: "ignore the value" is Incinerate's `set_value ignore` at IMMEDIATELY: the rival card's whole value counts for 0 at that moment; a later BOOST or effect of theirs still adds.
5. I Planned To Be Here: "started your turn in your current space" is "has not moved this turn" (the space at the start of the turn against the one now): a Maneuver or an effect that moved him makes it 2.
6. I Never Miss: the card draws when the BOOST is declined and also when there was nothing to boost with; boosting with a card (even a 0) means no draw.
7. For My Next Trick: the move is up to 1 and optional; the draw and the action happen win or lose; a defeated Bullseye does not move.
8. Master Strategist: "exactly 4" is only the destinations exactly 4 spaces away (by walking); when there is none the effect is cancelled and he does not move (CONFIRMED by Iván 2026-11-07). Through opposing fighters, never ending on one. The human moves by hand and the table is read; with no exact space the human is not asked to move and the chat says the move is cancelled (`move_none` note), and the bot is never asked (no fallback).
9. Ricochet: "a fighter in the opposing fighter's zone" includes the opposing fighter itself (if it survived) and Bullseye's own fighter if he stands there; the owner chooses and the bot never hits its own. Effect damage.
10. Right Between The Eyes: the rival chooses the card to discard, at IMMEDIATELY (before their DURING); the card they play in this combat is already out of their hand.
11. Tactical Retreat: any empty space none of whose zones is a zone of his current space; a teleport (no path, no range). No such space: nothing happens.
12. Study The Target: draws 2, then 1 more and 1 action when a combat was won this turn; the scheme itself costs its action first.
13. Ricochet may hit the opposing fighter itself (if it survived), not only another fighter in its zone (CONFIRMED by Iván 2026-11-07).
14. Master Strategist with no space exactly 4 away: no move (CONFIRMED by Iván 2026-11-07, see 8).
15. World's Greatest Assassin: a BOOST or an effect of the opponent's card that resolves after IMMEDIATELY still adds to a value that was ignored (CONFIRMED by Iván 2026-11-07).
16. A combat won as the defender (the attacker dealt no damage) counts as "won a combat this turn" (CONFIRMED by Iván 2026-11-07).

## Open questions for Iván
- Reach: do the secret passages shorten the 5-space count? (Read as no.)
- Arrogant But Effective: should the rival's AFTER ("if you won" / "if you lost") read the changed result too, or only Bullseye's own effects and the turn's tally?

## AI
- The AI profile comes from the data (Bullseye `hero`, ranged: the importer's `ai_profile`). No hero-name case in the engine: the conditional values are read from the turn's record (`fx.won`, `fx.turn_start_pos`) in `ai_medusa.card_value`: I'm Better And I'll Prove It is worth 6 after a win (also as a defense in `eval_defense`), I Planned To Be Here 5 while he has not moved, World's Greatest Assassin ignores the rival's card after a win (`ignores_defense`, shared with Cloak of Levitation), Right Between The Eyes strips a card after a win (`STRIP_VALUE`). `AFTER_BONUS` prices the draws and moves of I Never Miss, Arrogant But Effective, Master Strategist, Ricochet and Tactical Retreat; For My Next Trick already had Houdini's entry (the same effect). Study The Target is valued by simulating it like the other schemes.
- `choose_combat_boost` charges the card a declined I Never Miss would have drawn (`declined_draws`, read from the `unboosted` ops): the bot boosts only when the boost is worth more than the card it gives up plus the draw it forgoes.
- Positioning is the generic ranged rule on his reach (above). The matrix below shows the bot plays him to game over in every pairing with no errors and no stalls.

## Strength (simulator, heuristic AI, bprd-hq, seeds 0-19)
- Bot's Bullseye against each scripted rival (`python -m sparring.sim`, the rival chases and attacks with its best card): 216 wins to 24 losses over 12 rivals and 20 games each (80 to 100 % against each).
- Bot against bot (both seats heuristic AI, 20 games per seat per rival): 162 wins, 318 losses, none unfinished: weakest against Medusa (3-37), Hellboy (3-37) and Bigfoot (2-38), even against Michelangelo (32-8) and Houdini (27-13). His cards are low (attack values 2-4, 6 only after a win), so the stronger decks outrun him; Doctor Strange, the previous new hero, scores comparably against Medusa.

## Tests
`tests/test_hero_bullseye_data.py` (data, reach in the HeroDef and card identity), `tests/test_bullseye_effects.py` (the reach on the board and the engine, the tally, every card and the AI's strike spots), `tests/test_bullseye_human.py` (FakeTTS, the panel: attacks from 5 and 6 spaces, I Never Miss's BOOST and draw, Study The Target, moves and placements by hand, Ricochet's question across a restore, Right Between The Eyes), `tests/test_bullseye_matrix.py` (full games against all twelve heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
