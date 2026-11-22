# Elektra (Marvel: Hell's Kitchen)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character cards 340 / 341 on sheet 3) on 2026-11-22. Rulings: Ivan 2026-11-22 (`RULINGS-batch4`: E1-E4 kept by silence) and the readings of `REGLAS-PENDIENTES-batch4` section 2.

## Summary
- Melee hero, **7 life** (character card; unmatched-memory agrees), move 2, **four Hand** (The Hand: melee, 1 life, move 2). Hero fid `elektra`, sidekick group `hand` (`hand1`..`hand4`), slug `elektra`.
- Resurrected side (character card 341): 9 life, same move, same sidekicks.
- Deck: 20 cards, `CardID = 17600 + idx` (sheet 176 shared with the other Hell's Kitchen heroes; `HeroDef.deck_size` 20). Order on the sheet: Mystic Assassin 0-1, Hands of Red 2-3, The Fist 4-5, Cloaked In Shadow 6-7, Sai 8-9, Whirlwind 10-11, Ninjitsu 12-13, Intercept 14-15, Snakeroot Clan 16-17, Mesmerize 18-19. The deck object holds 22 cards: the 20 and the character cards 340 and 341.
- Bands read from the card backs. **Slips in unmatched-memory**: it has no bands. The Fist is **THE HAND** (only a Hand can play it, not Elektra), Ninjitsu is **ANY**, every other card is **ELEKTRA**. Values, BOOSTs and copies agree with the images. Intercept names the card in quotation marks ("Sai").
- Table: bag `85cef8` (inner `070893`), miniature `e5bac5` (one figure for both sides), life dial `aace96` (max 7) and the flipped dial `c32f50` "Elektra Resurrected" (max 9), four Hand Ninja tokens (`d72373`, `8f67bf`, `9bdc1d`, `b771c8`, 1 life, no dial), deck `7d538d`.

## The new engine state: fighters off the board, not defeated
Before Elektra the engine knew two ways of being off the board: *defeated* (`alive = False`, `died_at` set, the owner may lose) and *in reserve* (`alive = False`, never placed, `died_at` None). Her ability needs a third: removed, to come back as a block.

**Design.** `Fighter.off_board: bool` (saved by `persist`, copied by `Game.clone`). A removed fighter has `alive = False`, `pos = None` and `off_board = True`, so every check that already means "not on the board" (targeting, adjacency, the owner's `own()` list, range, space occupancy, the search's piece counts) treats it right without a change. What differs is only what the flag decides:
- `Game._fall` (the single place every defeat goes through: combat damage, effect damage, exhaustion, `defeat`) asks `effects.plugins_elektra.intercept_defeat(game, fighter)` first. For Elektra's hero fighter in her first life it removes her and all Hand that are on the board (`off_board`, no `fighter_defeated` event, no `died_at`, no winner) and returns True; `_fall` stops there. Hands that were already defeated stay defeated.
- `select.defeated(f)` is False for an off-board fighter: nothing that "returns a defeated Hand" can bring back a removed one (Hands of Red cannot be played anyway while she is off, and Ninjitsu does not return her early).
- `Game.hero()` keeps returning her; a hero that is not alive has always ended the bot's turn loop, which is what an off-board hero must do too.
- No winner is set while the hero is off the board: the only thing that ends a game is `_fall` reaching the loss, and it does not.

**Her life** is an ability counter `life` of the effects file: 0 first life, 1 off the board, 2 resurrected. The RESURRECTED symbol is `counter life >= 2`; the removal sets 1 and the Resurrect sets 2. The counter is saved with the effects state and cloned with the game, so the search sees it.

**When she comes back.** The ability trigger `resurrect` (`start_of_turn` of the owner, condition `life == 1`) runs at the start of her next turn. A removal on the opponent's turn comes back at the very next start of her turn; a removal on her own turn (Mystic Assassin, a Fist) waits for the opponent's whole turn, because the trigger only fires at a start of turn. Nothing else can bring her back early (Ninjitsu: "your fighter" is not on the board).

**Resurrect.** Ops of the trigger: `elektra:flip` (the counter to 2, `max_hp` 9, the removed fighters stop being "off the board" and count as defeated for the selectors, `died_at` is the space they left), `return_to_deck` the whole discard pile with `shuffle`, then three `revive`: Elektra (9 life), the four Hand (1 life each, also those defeated earlier: E1) each in a zone no other fighter of hers is in (new SpaceSel `apart_from_own`), and the ones left over (not enough zones) in any empty space (E2). Her owner chooses every space (E2). After that every RESURRECTED line applies, also for a card a Hand plays (the fighter that plays it is the reference of "adjacent" and "your fighter"); by the bands only Ninjitsu and The Fist can be played by a Hand and neither has a RESURRECTED line, so in practice it is Elektra's.

**While she is off the board** the opponent plays a normal turn and nobody can attack her fighters. If it happens in her own turn the bot ends the turn; the human may still play schemes. The opponent's evaluation must not read the removal as a win (`search`, see Tests).

**The removal at the table** is a normal "falls" for the table (the bot sets the miniatures aside; for the human's Elektra the bot sets the human's pieces aside when a fallen zone exists, else the chat tells the human to take Elektra and all four Hand off the board); the chat says she is NOT defeated and when she comes back. See "Table".

## Cards (as implemented)
1. **Mystic Assassin** (attack 6 / 1, ELEKTRA): AFTER Elektra takes 3 damage; RESURRECTED: no damage. If it takes her out the Resurrect waits for her next turn.
2. **The Fist** (attack 3 / 3, THE HAND): AFTER the owner MAY deal 1 damage to the attacking fighter (cost); if so return this card to the hand and gain 1 action, even if that damage defeated the attacker (E4).
3. **Hands of Red** (attack 4 / 2, ELEKTRA): AFTER return a defeated Hand to a space in Elektra's zone (1 life).
4. **Snakeroot Clan** (defense 1 / 2, ELEKTRA): IMMEDIATELY Elektra may swap spaces with a Hand (any Hand on the board); if she does that Hand is the defender, with no range check (`elektra:replace_combatant`, the Smoke And Mirrors machinery).
5. **Cloaked In Shadow** (versatile 2 / 1, ELEKTRA): IMMEDIATELY cancel all effects on the opponent's card; AFTER RESURRECTED: move Elektra up to 3 spaces.
6. **Intercept** (defense 3 / 4, ELEKTRA): DURING RESURRECTED: the owner may reveal a Sai from the hand; if so the value is 5 instead (`set_value amount`).
7. **Mesmerize** (scheme, boost 2, ELEKTRA): look at the opponent's hand, gain 1 action; RESURRECTED: choose 1 card of it for them to discard.
8. **Ninjitsu** (versatile 3 / 2, ANY): AFTER place your fighter in any space.
9. **Sai** (versatile 4 / 3, ELEKTRA): no effect.
10. **Whirlwind** (versatile 2 / 1, ELEKTRA): AFTER RESURRECTED: 1 damage to each adjacent opposing fighter.

## Table (what the bot does, what the chat asks, what the bot reads back)
- **Pieces**: the miniature `e5bac5` serves both sides; the two health dials are two objects (`aace96` max 7 and `c32f50` "Elektra Resurrected" max 9) and both come out of the bag with her (`dial_flipped` in `data/tts/elektra.json`, `flip_dials` of the session configuration). The four Hand are identical tokens named "Hand Ninja": the importer drops a nickname that several tokens share and the bot numbers them (The Hand 1..4) like Harpies.
- **The removal** (her first defeat) uses the machinery of a fall: the bot sets the miniatures aside (its own at its fallen zone; the human's at theirs when a zone exists, else the chat tells the human to take them off), but the chat says "<name> leaves the board (not defeated)", never "falls", and the game does not end. The dial of a fighter that is away shows 0.
- **The Resurrect, the bot's Elektra**: the engine chooses the spaces (one to a zone, her owner's choice is the bot's) and the bot moves each miniature to the space ("<name> returns to the game: I placed it ..."); the chat says she resurrects and that the bot flipped her dial: from then on her life is written on the Elektra Resurrected dial (9).
- **The Resurrect, the human's Elektra**: the trigger `resurrect` is run by the engine for the table player (`effects/table.py` `ENGINE_RUN_TRIGGERS`) and the chat lists what to do: "put Elektra on the board (any space) with 9 health, put The Hand 1.. in a zone none of your other fighters is in", then shuffle the discard pile into the deck (said when the pile holds cards). The human puts the five miniatures down; the bot reads them back at "End action" (the same read-back as any piece put down by hand: `game.placing`) and adopts where they stand. Whether each is in a different zone is the human's to respect: the bot does not refuse a placement for it. A "flip your health dial" line follows and the bot writes the life on the 9-dial from then on.
- **Save and resume** in the middle of any of it: off the board (`off_board` and the maximum health are saved), with the five pieces still to be put down (`game.placing`), and after the flip (the session re-flips the dial from the saved `life` counter; the fingerprint of the table keeps the configured dial). `tests/test_elektra_human.py`.
- **The human's cards**: Snakeroot Clan is a yes/no and then a button per Hand (names, any distance); the bot swaps the two miniatures and the Hand fights. Intercept (RESURRECTED) is a yes/no whose prompt carries the card text: the human shows a Sai if they have one and answers; the bot cannot read their hand, so it trusts the answer (hidden information stays hidden).
- **The bot's Elektra at the human's table**: the bot reveals a Sai from its (engine) hand for Intercept; Mesmerize lets her look at the human's hand once and, resurrected, choose the discard; The Fist is only played by a Hand.
- **When she falls in her own turn** (Mystic Assassin, a Fist) the bot ends its turn (no fighter on the board); the human may still play schemes. The Resurrect comes at the start of her next turn, after the opponent's whole turn.

## AI
- The search treats a hero off the board as a fresh hero a turn behind (`OFF_BOARD_LIFE`, the life term of the evaluation) and nothing can hit her while she is away; before this a removal read as a dead hero and a kill for whoever caused it (`sparring/search/adapter.py`, `_hero_life`).
- A mover with no fighter on the board ends its turn inside the search (`_advance`), which also stopped a crash (`KeyError: None` from the reach of a hero with no position).
- The Resurrect placements are asked as ordinary `space` requests, so the search and the effect AI answer them like any placement; the bot's choices always land in different zones when the board has them.

## Pending Ivan
1. **Who can play her cards.** REGLAS-PENDIENTES section 2 and the brief say the RESURRECTED lines also apply to "a card a Hand plays" (Intercept, Whirlwind, Cloaked In Shadow). The card backs say otherwise: every card except The Fist (THE HAND) and Ninjitsu (ANY) is band ELEKTRA, so a Hand cannot play them. Implemented as printed on the cards; the effects themselves already measure "adjacent" and "your fighter" from the fighter that plays the card (and "Elektra" is her hero), so if the band is meant as "Elektra or a Hand" the only change is in the overlay.
2. **Exhaustion order.** An empty deck costs every fighter 2 health, the hero first. If that takes her out, the Hand are removed with her (not defeated); otherwise each Hand (1 health) is defeated by its own 2 damage as usual, and "return all Hand" at the Resurrect brings them back anyway (E1). The rules do not say whether the Hand are hit before or after her.
3. **The human's Intercept** trusts the answer about the Sai (no way to read their hand).
4. **Physical flip.** The save has the 9-dial as a separate object, not a second face of one: the bot writes to whichever is current and leaves the other where it is; verify live that this is what Ivan wants to see (Pending live).
5. **Mystic Assassin on her own turn.** She is removed in her own turn and the bot ends the turn without playing its remaining actions (a human Elektra may still play schemes).
6. **Hands of Red** returns only a DEFEATED Hand. A Hand removed with Elektra comes back with her, not before (she is off the board while they are).
