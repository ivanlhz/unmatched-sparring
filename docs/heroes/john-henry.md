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
2. **Moving** him: entering a space with a track token costs nothing. A walk of N steps may enter any number of track spaces plus N other spaces (a Maneuver, a boosted one, Striking Fire, Hear That Cold Steel Ring, the human's hand moves). The starting space is never counted; he cannot end on an occupied space nor cross a rival (unless the card says so), tokens or not; the hazard edges he crosses on the way are still charged (the edge is crossed whether or not the space costs a step). Only HIS moves: the rival's fighters walk as ever, except that **Power Through** moves any fighter of the combat (the rival's too, the owner chooses which and where) without counting the track spaces, whoever the mover is.
3. **Paths**: see Pending Ivan 1. Literal reading used: the track spaces he ENTERED while moving this turn, four different ones needed. Both the bot's and the human's moves count (the human's by the two ends the table shows: the route is the cheapest walk through the most track spaces).
4. **HAMMER** is the card tag `hammer` on the seven cards titled "...-pound Hammer" (the images print no keyword). Bring Down The Mountain counts them in the discard pile with a `count_cards` Amount (the card in play is not in the pile yet).
5. **Knock Them Silly**: the result is not known at IMMEDIATELY, so `cancel_effects` with `if_won` is registered then and settled when the combat damage is known, before any AFTER effect resolves. If the owner won (the attacker if it dealt damage, the defender otherwise, a tie is the defender's), the rival card loses its AFTER COMBAT effects (the owner's own are untouched; a card that cannot be cancelled keeps them).
6. **Hear That Cold Steel Ring**: "a free action to attack" is one extra action (`fx.attack_credit`) that only an attack can spend: a Maneuver or a scheme refuses it (`err.attack_only`), an attack spends it first (so the real action stays free for anything else). It is lost at the end of the turn. The bot's planners, the search, both scripted rivals and the session's loop treat a turn whose only action left is that one as over when no attack is possible (`tracks.turn_goes_on`).
7. **Twelve-pound Hammer**: with four paths the owner may (a Yes / No) place one fighter of the combat, his own or the rival's, on an empty space with a track token. With no such space nothing happens.
8. **Nine-pound Hammer**: "his zone" is the zone of John Henry's space; every opposing fighter there, the combat's target or not, a sidekick included, takes 2.
9. **Momentous Shift** is word for word Sinbad's and Bigfoot's card: same data.
10. **Human at the table**: his start-of-turn summon is physical (the panel waits for End action, like Wildfire): the human takes a token out of their stack, lays it on a space of his zone and presses End action; the bot reads every track token on the board by its picture (`lua.read_tokens_by_image`) and adopts those spaces (`session_tracks.sync`, before the table's positions are read), so the human can also move or take one away. **Bot as John Henry**: the engine chooses the space (`ai_john.pick_track_space`) and the session takes a copy from the stack and lays it there (`lua.place_token_at_space`, intent `track`); a stack that gives nothing makes the chat ask the human to lay one (the same "the table wins" rule as every other projection).

## Pending Ivan
1. **What is a "path"?** The cards never define it and no card or sheet says (4 cards: "If John Henry used at least 4 different paths this turn"). Implemented: a path is a **track space John Henry entered while moving this turn**, four different ones; passing through one counts, ending on one counts, starting on one does not, the same one twice counts once; the set resets at the start of every turn. For a move the engine only sees as two ends (the human's hand moves) it takes the cheapest walk that goes through the most track spaces. Alternatives: (a) a path is each separate move he made this turn (four moves is almost out of reach with two actions: it would make the hammers nearly dead); (b) a path is a maximal row of connected track spaces; (c) only track spaces he LEFT count. The change is one function (`tracks.record_walk` / `john:paths`).
2. **One token per space?** Implemented: yes (a space either is a path or is not). Consequence: a zone has few spaces (5 on B.P.R.D. HQ around his start), so if he never leaves his zone the summons run out after 5 turns; once he moves to another zone they go on up to 10. If several tokens may share a space the supply would never be the limit.
3. **Is a token ever removed or moved?** Implemented: never (no card says it). The human may pick one up (the table wins), the bot never does.
4. **HAMMER**: tagged by title (Nine-, Twelve- and Eighteen-pound Hammer, 7 cards). Larger Than Life is not a hammer. No card art prints the keyword.
5. **"Free action to attack"**: implemented as an extra action that only an attack can use, lost at end of turn (see rule 6). Alternative: an ordinary extra action (gain 1 action), which would also let him Maneuver with it.
6. **Knock Them Silly** wins retroactively (the result is read at the damage, the rival's AFTER is cancelled before the defender's AFTER resolves, whichever side resolves first). Alternative: only when the rival's AFTER has not resolved yet, which would make it do nothing against a defender.
7. **Twelve-pound Hammer** places a fighter "in any space with a track token": implemented as an EMPTY space (two fighters never share a space). It may be declined.
8. **Power Through** gives the free walk to the fighter it moves, rival included (the card says "do not count spaces with track tokens" with no owner).

## Engine additions (all additive, docs/effects-dsl.md section 41)
- Board state `fx.tracks`, `fx.paths`, `fx.attack_credit` (cloned, saved only when non-empty, reset per turn for the last two); `sparring/tracks.py`.
- `Board.reachable(..., free=)` (0-1 search), `walk_cost`, `track_route`, `hazard_path(..., free=)`; `Game.legal_moves` / `move_fighter` / `walk` / `hazard_edges` take `over_tracks`; `Game.use_action(attack=)`, `Game.attack_only`.
- DSL: the passive rule `track_free_move`, `move.over_tracks`, SpaceSel `track`, `cancel_effects.if_won`, `gain_action.only`; plugins `john:summon_track` and the test `john:paths`.
- Table: Lua `place_token_at_space` and `read_tokens_by_image`, intent `track`, `session_tracks`; the move hint (`moves.over_tracks`, `tbl.over_tracks`) and the placement text (`tbl.where.track`).
- ISMCTS: `search/adapter.py` signs the tracks and the free action in its memo key (a destination computed for another set of tokens is never replayed), `reach()` skips its cache for a hero with free spaces, the free action offers only attacks, the rollout attacks with it.

## AI
- Where to summon (`ai_john.pick_track_space`): of the free spaces of his zone, the one that leaves the shortest free walk to a space from which he can strike a rival fighter (the tokens already on the board counted), preferring a space that joins his own or an existing track and then one far from the rival.
- The movement he gains comes for free: the planners (`MedusaAI.maneuver_acts`, the search's reach) ask `Game.legal_moves`, which counts the tracks. A turn whose only action left is the free action to attack plays an attack or ends (`candidates`, the search's `_generate_moves`, `turn_goes_on`).
- The hammers' conditions (four paths) are priced like any other card text; the AI has no special planning for the count.

## Tests
`tests/test_hero_john_henry_data.py` (data, the transcription check, the track image, GUIDs, detection), `tests/test_john_henry_board.py` (free spaces, route, hazards), `tests/test_john_henry_lua.py` (the two Lua builders on the stub), `tests/test_john_henry_effects.py` (the ability, the paths, every card, the free action, the state), `tests/test_john_henry_human.py` (FakeTTS: the human's tokens read from the table, hand walks, the cards' texts, the bot laying tokens), `tests/test_john_henry_matrix.py` (full games against all twenty-five other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
