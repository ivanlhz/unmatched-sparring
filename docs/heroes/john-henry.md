# John Henry (Stars and Stripes)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 187 of the tournament savegame, character card 403 on sheet 4) on 2026-11-13. He was first added from a transcription of Iván's screenshots (unmatched-memory, unverified): every title, value, boost, copy count and text of it was compared with the images, and **nothing differed** (see "Transcription check").

## Summary
- Melee hero, 17 life, move 2, **no sidekick**. Hero fid `john`, slug `john-henry`.
- Ability **STEEL-DRIVING MAN**: "You have 10 track tokens. At the start of your turn, summon a track token in a space in John Henry's zone. When you move John Henry, do not count spaces with track tokens." The first hero with tokens ON the board: `fx.tracks` (the spaces of each player's tokens), `sparring/tracks.py`, the plugin `john:summon_track` (docs/effects-dsl.md, section 41).
- Deck: 30 cards, `CardID = 18700 + idx`, every card restricted to JOHN HENRY. The deck object of the save holds 31 cards (the 30 plus the character card 403), hence `card_count 31` in the catalog (`card_ids [403, 18729]` is the min and max of those 31). Sheet 187 is NOT his alone: Wyatt Earp (`0e4426`) and George Washington (`15548c`) have decks with the same CustomDeck key and Wyatt the same CardIDs 18700-18729 (plus about sixty loose Hellboy / Baba Yaga cards use key 187), so his cards are told apart by deck image and owner, never by a bare CardID (docs/card-identity.md).
- Table: bag `845f05` (inner `646707`), deck `c3109e`, miniature `041a3d` (a Custom_Assetbundle), life dial `887823` (max 17) and a **stack of 10 track tokens** `8ba84f` (a Custom_Token_Stack with no nickname; its picture, ending `7E9563244F2F4DA4659AA9164EC339BCDC766607`, is how a token taken out of it is recognised on the table). The dial GUID `887823` is also Raphael's: `session_pieces.resolve_dials` tells them apart by the dial's name (the Lobster / Jackalope and Tomoe Gozen / Donatello case); `tests/test_hero_john_henry_data.py` pins that it is the only GUID he shares and the matrix plays the pair.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| Nine-pound Hammer (HAMMER) | attack | 3 | 2 | 3 | AFTER: if he used at least 4 different paths this turn, 2 damage to each opposing fighter in his zone |
| Twelve-pound Hammer (HAMMER) | attack | 4 | 2 | 2 | AFTER: if 4 paths, you may place a fighter in the combat on any empty space with a track token |
| Eighteen-pound Hammer (HAMMER) | attack | 6 | 2 | 2 | IMMEDIATELY: if 4 paths, cancel all effects on the opponent's card |
| Hear That Cold Steel Ring | attack | 2 | 3 | 2 | AFTER: draw 1, move him up to 1, gain 1 free action to attack |
| Larger Than Life | attack | 6 | 4 | 2 | - |
| Bring Down The Mountain | versatile | 3 | 1 | 2 | DURING: +1 for each HAMMER card in your discard pile |
| Knock Them Silly | versatile | 4 | 1 | 3 | IMMEDIATELY: if you win this combat, cancel all AFTER COMBAT effects on the opponent's card |
| Momentous Shift | versatile | 3 | 1 | 3 | DURING: if he started this turn in a different space, the value becomes 5 |
| Power Through | versatile | 3 | 3 | 3 | AFTER: move a fighter in the combat up to 2 spaces, not counting the spaces with track tokens |
| Deeds Of Valor | defense | 2 | 2 | 2 | DURING: he cannot take more than 2 combat damage this combat |
| Cool Drink Of Water | defense | 0 | 2 | 3 | AFTER: he recovers 3 health, draw 1 |
| Striking Fire | scheme | - | 2 | 3 | move him up to 4 spaces, gain 1 action |

## Transcription check (Iván had not verified unmatched-memory's `john-henry.json`)
All 30 cards of the image were read one by one (sheet 187 is 8 x 4; idx 0-2 Nine-pound, 3-4 Twelve-pound, 5-6 Eighteen-pound, 7-8 Hear That, 9-10 Larger Than Life, 11-12 Bring Down, 13-15 Knock Them Silly, 16-18 Momentous Shift, 19-21 Power Through, 22-23 Deeds Of Valor, 24-26 Cool Drink, 27-29 Striking Fire) and the hero card too. Titles, type (the colour of the banner), value, boost (the number in the circle), the copy count (the "x3" printed on each card, and the number of physical copies in the deck), the text of each moment and the hero card's 17 HP / MOVE 2 / MELEE / ability all agree with the transcription. The only differences are how the importer writes them: the printed text is rendered with its moment label ("AFTER COMBAT: ...") and Larger Than Life has no text. **Mismatches: none.**

## Rule decisions (the most literal reading of the card, no ruling asked: see "Pending Ivan")
1. **Track tokens** are board state: a list of spaces per player (`fx.tracks`, at most 10, one per space, never taken off). One is summoned at the start of every turn of the owner (also the first), on any space of John Henry's zone that has none: his own space and a space with a fighter on it included ("in a space in John Henry's zone"). With no such space, or all 10 on the board, nothing is summoned.
2. **Moving** him: entering a space with a track token costs nothing. A walk of N steps may enter any number of track spaces plus N other spaces (a Maneuver, a boosted one, Striking Fire, Hear That Cold Steel Ring, the human's hand moves). The starting space is never counted; he cannot end on an occupied space nor cross a rival (unless the card says so), tokens or not; the hazard edges he crosses on the way are still charged (the edge is crossed whether or not the space costs a step). Only HIS moves: the rival's fighters walk as ever, **Power Through included**: it moves any fighter of the combat (the rival's too, the owner chooses which and where) but only John Henry's own walk skips the track spaces (Iván, 2026-11-13).
3. **Paths** (decided by Ivan, corrected 2026-11-20): a path is a connection between two spaces (an edge of the board), not a track space. Four different paths he CROSSED while moving this turn are needed, with or without track tokens on them, in either direction (an edge crossed twice counts once). Both the bot's and the human's moves count (only the two ends are known, the table's and the bot's: the engine takes the walk within the steps he had that crosses the most paths not used yet, `Board.most_paths`; a space may be entered again, so a loop over the track spaces, such as a triangle of tokens, counts even when he ends on the space he began on: `Game.move_fighter` to his own space, and the human's Maneuver read at End action when the miniature is back where it began and no walk was read meanwhile).
4. **HAMMER** is the card tag `hammer` on the seven cards titled "...-pound Hammer" (the images print no keyword). Bring Down The Mountain counts them in the discard pile with a `count_cards` Amount (the card in play is not in the pile yet).
5. **Knock Them Silly**: the result is not known at IMMEDIATELY, so `cancel_effects` with `if_won` is registered then and settled when the combat damage is known, before any AFTER effect resolves. If the owner won (the attacker if it dealt damage, the defender otherwise, a tie is the defender's), the rival card loses its AFTER COMBAT effects (the owner's own are untouched; a card that cannot be cancelled keeps them).
6. **Hear That Cold Steel Ring**: "a free action to attack" is one extra action (`fx.attack_credit`) that only an attack can spend: a Maneuver or a scheme refuses it (`err.attack_only`), an attack spends it first (so the real action stays free for anything else). It is lost at the end of the turn. The bot's planners, the search, both scripted rivals and the session's loop treat a turn whose only action left is that one as over when no attack is possible (`tracks.turn_goes_on`).
7. **Twelve-pound Hammer**: with four paths the owner may (a Yes / No) place one fighter of the combat, his own or the rival's, on an empty space with a track token. With no such space nothing happens.
8. **Nine-pound Hammer**: "his zone" is the zone of John Henry's space; every opposing fighter there, the combat's target or not, a sidekick included, takes 2.
9. **Momentous Shift** is word for word Sinbad's and Bigfoot's card: same data.
10. **Human at the table**: his start-of-turn summon is physical (the panel waits for End action, like Wildfire): the human takes a token out of their stack, lays it on a space of his zone and presses End action; the bot reads every track token on the board by its picture (`lua.read_tokens_by_image`) and adopts those spaces (`session_tracks.sync`, before the table's positions are read), so the human can also move or take one away. **Bot as John Henry**: the engine chooses the space (`ai_john.pick_track_space`) and the session takes a copy from the stack and lays it there (`lua.place_token_at_space`, intent `track`); a stack that gives nothing makes the chat ask the human to lay one (the same "the table wins" rule as every other projection).

## Decided by Ivan (2026-11-13)
- "4 different paths" = 4 distinct edges John Henry crossed while moving this turn (Ivan, 2026-11-20; it was 4 track spaces before).
- One token per space; tokens are never removed; the supply is 10.
- HAMMER by title (Nine-, Twelve- and Eighteen-pound Hammer).
- "Free action to attack" is attack-only.
- Power Through: the free walk over track spaces is John Henry's alone; a rival it moves pays full cost.

## Pending Ivan
1. **Knock Them Silly** wins retroactively (the result is read at the damage, the rival's AFTER is cancelled before the defender's AFTER resolves, whichever side resolves first). Alternative: only when the rival's AFTER has not resolved yet, which would make it do nothing against a defender.
2. **Twelve-pound Hammer** places a fighter "in any space with a track token": implemented as an EMPTY space (two fighters never share a space). It may be declined.

## Engine additions (all additive, docs/effects-dsl.md section 41)
- Board state `fx.tracks`, `fx.paths`, `fx.attack_credit` (cloned, saved only when non-empty, reset per turn for the last two); `sparring/tracks.py`.
- `Board.reachable(..., free=)` (0-1 search), `walk_cost`, `track_route`, `edge_route`, `most_paths`, `hazard_path(..., free=)`; `Game.legal_moves` / `move_fighter` / `walk` / `hazard_edges` take `over_tracks`; `Game.use_action(attack=)`, `Game.attack_only`.
- DSL: the passive rule `track_free_move`, `move.over_tracks`, SpaceSel `track`, `cancel_effects.if_won`, `gain_action.only`; plugins `john:summon_track` and the test `john:paths`.
- Table: Lua `place_token_at_space` and `read_tokens_by_image`, intent `track`, `session_tracks`; the move hint (`moves.over_tracks`, `tbl.over_tracks`) and the placement text (`tbl.where.track`).
- ISMCTS: `search/adapter.py` signs the tracks and the free action in its memo key (a destination computed for another set of tokens is never replayed), `reach()` skips its cache for a hero with free spaces, the free action offers only attacks, the rollout attacks with it.

## AI
- Where to summon (`ai_john.pick_track_space`): of the free spaces of his zone, the one that leaves the shortest free walk to a space from which he can strike a rival fighter (the tokens already on the board counted), preferring a space that joins his own or an existing track and then one far from the rival.
- The movement he gains comes for free: the planners (`MedusaAI.maneuver_acts`, the search's reach) ask `Game.legal_moves`, which counts the tracks. A turn whose only action left is the free action to attack plays an attack or ends (`candidates`, the search's `_generate_moves`, `turn_goes_on`).
- The hammers' conditions (four paths) are priced like any other card text; the AI has no special planning for the count.

## Tests
`tests/test_hero_john_henry_data.py` (data, the transcription check, the track image, GUIDs, detection), `tests/test_john_henry_board.py` (free spaces, route, hazards), `tests/test_john_henry_lua.py` (the two Lua builders on the stub), `tests/test_john_henry_effects.py` (the ability, the paths, every card, the free action, the state), `tests/test_john_henry_human.py` (FakeTTS: the human's tokens read from the table, hand walks, the cards' texts, the bot laying tokens), `tests/test_john_henry_matrix.py` (full games against all twenty-five other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
