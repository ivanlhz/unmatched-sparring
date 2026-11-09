# Checklist for the live tests (TTS)

> Note: the game texts quoted below are the English ones (`language: "en"`); with the default `es` catalog the same lines come out in Spanish (`data/i18n/es.json`). Tick `- [ ]` as you go. Items marked **(E2)** depend on phase E2 (ONGOING zone, ability gate, scheme buttons); if it is not merged when you read this, skip them.
> Marked *(OK 29/10)*: checked in the first real game (bot Hellboy vs a human Liz). The rest is verified against FakeTTS only. This is what has NEVER been seen on a real table.

## 1. Before starting

- [x] **Backup of the save**: in TTS, Save as "pre-sparring" (and copy the `.json` from `saves\`). If something breaks, reload that one. *(OK 29/10)*
- [x] Table open with the game loaded (B.P.R.D. HQ, Green = bot, White = you). Terminal in the project folder. *(OK 29/10)*
- [x] Commands (PowerShell): *(OK 29/10)*
  - Only read / calibrate / detect heroes (changes nothing): `uv run python -m sparring.play --config config\table.json --read-only`
  - Play: `uv run python -m sparring.play --config config\table.json --first human` (`--first bot|random`, `--seed N`)
  - Resume after closing it or after a TTS reload: `uv run python -m sparring.play --config config\table.json --resume` (the game keeps the language it was saved in unless you give `--language`)
  - Take out of the inner bag whatever is missing on the table (never with `--resume`): `--unpack`
  - Force heroes: `--bot-hero <slug> --human-hero <slug>` (medusa, hellboy, abe-sapien, baba-yaga, liz-sherman; not the same on both sides)
  - Measure messages and times per button: `--timing`. Search AI: `--ai ismcts`. Bot pause: `--bot-pause N`.
  - Old names: `config\partida.json` is read as `config	able.json` with a deprecation notice; a save at `estado\sesion.json` (and its `partida.log`) is moved once to `state\session.json` / `state\session.log`, with a notice.
- [x] Ctrl+C exits cleanly (the floor rectangles and labels are erased on exit). *(OK 29/10)*

### Position calibration (`config\table.json`)
With `--read-only` look at the report and fix whatever is wrong. Try with a card in each spot.
- [ ] `bot_card_spot` / `human_card_spot` (combat zone, face down) and `off_board_dist` (4.0 is an estimate; compare with the distances in the report).
- [ ] `bot_discard_spot` / `bot_discard_bounds` / `bot_discard_step` / `bot_discard_rows`: the bot's discard ends up in an ordered grid inside zone 906a7a.
- [ ] `dead_spot` / `human_dead_spot` (where fallen miniatures are set aside, 1.5 apart in x between pieces; they are estimates).
- [ ] `look_spot` / `look_step` (row of the **Look at bot's hand** button: in front of your seat, not over the panel, hands, discards or combat boxes; start-up warns if it overlaps something).
- [ ] `bot_row_spot` / `bot_row_step` (row opened by your cards that look at the bot's hand: Confront, Advanced Psychometry, Remove A Painful Memory, Every Possible Angle; next to its combat and ONGOING zones).
- [ ] `token_spot` (where the bot leaves Abe's Intuition tokens; without the key, next to its deck).
- [x] **(E2)** `human_ongoing_spot` / `bot_ongoing_spot`: ONGOING zone below the combat zone, on both sides. *(OK 29/10)*
- [ ] `panel_position` / `panel_scale`: the panel is seen and pressed well from your seat; the floor DISCARD/COMBAT rectangles do not end up under the panel.
- [ ] `bot_unpack_spot` / `human_unpack_spot` only if you use `--unpack`.
- [ ] Deck zones (optional): create a Scripting zone over each deck spot, copy the GUIDs into `bot_deck_zone` / `human_deck_zone` and check that `--read-only` prints `deck: found (GUID ...) inside the Scripting zone ...` for both; push the deck out of the zone and check the report says it was NOT found and where it looked. Without zones: a deck with a new GUID up to 2.9 from its spot is still found.

### Hero detection (`--read-only`)
- [x] With `bot_hero`/`human_hero` on `"auto"`: the report gives the right hero for each side (a LOOSE Deck or Card with a CardID of its range, the closest to `*_deck_spot`). If in doubt, it refuses to start and says so. *(OK 29/10)*
- [x] Repeat with each pair of heroes you are going to try (changing what is on the table). *(OK 30/10)*
- [x] The report gives no "not found" for miniatures, dials, deck, discard or tokens (1644a3 Hellboy, 5a17e9 Abe). *(OK 30/10)*
- [x] Bridge objects report (type/rotation/states): note the **type** of 5a17e9 (bag / infinite bag / pile / loose token) and of 1644a3, and the current rotZ of 1644a3. *(OK 30/10)*

## 2. Start-up

- [x] Without `--read-only`: it draws the DISCARD and COMBAT rectangles of both sides and creates the panel (`SparringPanel`). No errors in the terminal. *(OK 29/10)*
- [x] Setup (`setup`): the bot deals 5, mulligan (once); if the bot starts, it places its pieces; you place yours and press **Ready**. **Mulligan** / **Ready** appear only when due. *(OK 30/10)*
- [x] The panel answers the first click ("Processing..." and it re-enables). *(OK 29/10)*
- [x] (`--timing`) notes messages and time of a normal button (expected ~1 message, ~0.5 s per message). *(OK 30/10)*
- [ ] Bot announcement pause (`action_announce_hold`, 2 s): each bot action is announced in the chat, waits and is then written on the table; yours do not wait. Since 682c769 also when you attack and the bot answers by moving cards or pieces (Incinerate). *(31/10: looks better, still under test)*

## 3. Per hero

Each hero has two blocks: **H** (you play it) and **B** (the bot plays it). What holds for both sides goes under **H and B**.

### Common template (repeat it for each hero and each side)
- [ ] Correct initial state (pieces on their starting spaces, dials at maximum, deck of 30, hand of 5).
- [ ] An **IMMEDIATELY** card: applied once; the chat narrates it.
- [ ] A **DURING** card: affects the right damage/value.
- [ ] An **AFTER** card: applied after resolving; the combat does not hang.
- [ ] A **scheme**: effect + card to the discard.
- [ ] An **ONGOING** and then another that **replaces** it (only one per player; the first goes to the discard). **(E2)** the card stays physically in its side's ONGOING zone and the replacement takes its place.
- [ ] The hero's **ability**.
- [ ] B: the chat says what each card did and names what you have to discard.
- [x] H **(E2)**: start-of-turn ability gate on the panel: it blocks the actions until **End action**. *(OK 30/10)*
- [ ] H **(E2)**: optional moves offer **None**.

### Medusa
**B (bot)**
- [x] Moves Harpies; Winged Frenzy **always** returns a fallen Harpy (mandatory, first free space of its zone). *(OK, confirmed by Ivan 31/10)*
- [x] Fallen pieces (Harpies) go to the `dead_spot`. *(OK, confirmed by Ivan 31/10)*

**H (you)**
- [ ] Out Of Time ("BOOST this card" = boost from the hand, as always).

### Hellboy
**H and B**
- [x] Setup: token **1644a3** on **OCCULT DETECTIVE** (blue, rotZ 180). *The turn is unconditional: it must start like this.* *(OK 29/10)*
- [x] Crown Of Flame (**(E2)** waits for your discard), Planned Recklessness, Second Shot, Horseshoes, Right Hand Of Doom, B.P.R.D. Training, On Earth. *(OK 30/10)*
- [ ] Glimpse Of Hell, Confront (see Hidden information).

**B (bot)**
- [x] Change to **ANUNG UN RAMA**: `set_state` between the miniatures f9789a <-> e6f06e, token 1644a3 turns (rotZ 180 = OCCULT DETECTIVE, rotZ 0 = ANUNG UN RAMA) and a **ping** on token and miniature; no duplicated miniatures. *(OK 29/10)*
- [x] Return to OCCULT DETECTIVE (fewer than 6 destinies) turns back and pings. *(OK 31/10)*
- [x] The **Destiny Dial** (e17c66) follows the destinies in the bot's discard (goes up and down). *(OK 31/10, after fix bf91f02)*
- [ ] Start of its turn, announced before moving on the table: discards and moves (ANUNG) *(OK 31/10)*; draws 2 if it starts in DETECTIVE **on your starting space** *(still to be seen)*.
- [x] **Pancakes!**: picks two effects that do something and the chat names both ("recovers 2 (11 -> 13) and draws 2"). *(OK 31/10)*
- [ ] `card_to_deck_bottom` in Pancakes!: the cards it returns go **to the bottom** of its deck.
- [ ] AI (31/10, 2c92014 and 24cd9c3): in ANUNG it attacks more (counts its +2), makes almost no maneuvers without moving anyone, uses Lobster when it has a shot, and does not burn the deck if the game will last longer than it.

**H (you)**
- [x] **(E2)** start-of-turn ability gate (draw / ANUNG) blocks until **End action**. *(OK 30/10)*
- [x] **(E2)** schemes with a **Pancakes!** and **Posthumous Power** button; resume mid-scheme. *(OK 30/10)*
- [ ] Glimpse Of Hell defending against a bot AFTER that makes you discard (Fleeting Moments): first you draw 2 and put 1 into the deck, End action; then the random discard over your hand at that moment, End action; and then the card you draw (81132f9, 19bbe67).

### Abe Sapien
**B (bot)**
- [ ] Shows 0/1/2 Intuition tokens **taking copies of 5a17e9** (`take_token_copy`: takeObject or clone depending on the type). Expected: they appear at `token_spot`, distinct from the original, without moving the source.
- [ ] When one is spent, `remove_token` removes the last copy (the copy disappears, not the original).

**H (you)**
- [ ] You place the tokens by hand; the counter syncs.

**H and B**
- [ ] Faster. Stronger., Secure The Scene, Leap Away, Concussion Device, B.P.R.D. Training, Utility Belt, Arcane Dampener, Cold Iron (block), Ward And Prepare, Counterhex Shield, Shock And Awe.
- [ ] UNCANNY INTUITION and Perfect Shot: see Hidden information.

### Baba Yaga
**H and B**
- [x] Setup: **Koschei is already on the board** at the start (if not, check `start_on_board` in `data/heroes/baba-yaga.json`). *(OK 30/10)*
- [ ] Pacts: ONGOING, only one at a time; **Pact Of Freedom** (no attacking as the first action) and **Cold Iron** block on the panel (section 4).
- [ ] Iron Teeth, Death's Release, Foul Journey, Hasten Towards Death, Deathless, Exploit, The Time For Deals Is Done, Bound In Blood, Out Of Time.
- [ ] Koschei falls/returns: miniature to the `dead_spot`; "Summon" puts it as close as possible to Baba Yaga with 3 life.

**H (you)**
- [ ] FATEFUL BARGAINS (Koschei in the same zone, effect damage): **(E2)** asks with a button.
- [x] **Pact Of Secrecy**: **(E2)** buttons **0 / 1 / 2**; hand limit 3 for everyone. *(OK 31/10)* Chat summary without "you look at the bot's hand" and separate per player (f527ae5): *still to be seen*.
- [ ] Pact Of Time: you move the card from the discard to the deck yourself and press **Done** (bb95930).

**B (bot)**
- [ ] FATEFUL BARGAINS: it decides and says so.
- [ ] Pact Of Secrecy: the bot asks you which one you keep (the titles may come out as placeholders). The bot's Pact Of Secrecy / Time on you: chat only; the table syncs by count.
- [ ] Read The Bones: what it takes comes out as a draw from the top (the real order of the deck is not known).

### Liz Sherman
**H and B**
- [ ] Pyrotechnics (leaves a burning card at the bottom of the deck), Fireball, Burning Barrier, B.P.R.D. Training.

**B (bot)**
- [ ] **Burning** cards (BOOST 0): it does not use them as a boost; discarded by Wildfire they return to the hand.
- [ ] **Wildfire** (start of its turn): discards the bottom card and it is projected on the table; costs 1 extra message before its first action (note whether it bothers).
- [ ] **Exception**: a burning card discarded for the hand limit (7) at the end of the turn does **NOT** return to the hand; it stays in the discard.
- [ ] The bot's **Incinerate**: you answer Yes/No on the panel before the damage.
- [ ] The bot's Fleeting Moments / Confront: the chat **names the card** you must discard; you discard it.
- [ ] Wildfire returns a card your Confront made it discard: the chat says "The bot keeps X (Wildfire returns it)".

**H (you)**
- [x] **(E2)** start-of-turn ability gate (Wildfire) and Fight Or Flight. *(OK 29/10)*
- [x] **Fight Or Flight** as an ONGOING: the +1 lasts until the start of your next turn and goes away then. *(OK 31/10)*
- [x] Your ONGOING that expires or leaves play: the bot pings, says why, waits `ongoing_hold` and puts it **on top of your discard** (`card_to_discard`). *(OK 31/10: expired Fight Or Flight)*
- [x] **Feint**. *(OK 31/10)*
- [x] **Evade**: you draw 1. *(OK 31/10)*
- [ ] Evade defending against an attack that makes you discard (the Harpies' Clutching Claws): the Evade card reaches you **before** you are asked for the discard and counts for it (1e8709c).
- [ ] **Flame Lash**: a real DURING with the card from the **bottom of the deck** as the boost **(E2)**.
- [ ] **Incinerate** against the bot **(E2)**: the chat says whether it pays, does not pay or cannot; if it pays, it names the 2 cards, waits the announcement pause and then moves them (6c14d9c, 682c769).
- [x] Searing Clarity with panel buttons. *(OK 29/10; since bb95930 there are no buttons, see the next line)*
- [ ] Searing Clarity and Rekindle **without buttons**: you move the card from the discard to the deck yourself and press **Done**; the bot recognizes it; then "Press End action when you finish"; also try with the discard stacked (bb95930).

### Leonardo

Pending on a real table (TMNT box; nothing of Leonardo has been seen live):

- Hero detection: Leonardo's deck has Medusa's CardIDs 17600-17629; with Medusa on the other side check that "auto" reads both by image and that each hand reads from its own seat.
- The `[016099]Leonardo` miniature (colour tag in the nickname) is found by GUID `729fb1`; check it moves and the dial `88f451` follows.
- TEAM TACTICS (human): the panel waits for End action; moving the bot's miniature by hand is read at End action. Bot: it moves one fighter at the start of its turn, said in the chat; check the miniature move on the table.
- For Sensei, Eat, sleep, and breathe ninjutsu: the bot's piece the human relocates ("put it there and press Done"); Protective father swap by hand (both miniatures) and the heal on both dials.
- I have a plan / For Sensei price: the extra discard from your hand is noted and settled at End action.
- Spatial awareness / Wise beyond his years: zone counts on the real board (spaces with several zones).
- Same CardIDs, other decks (docs/card-identity.md): play Medusa vs a turtle and a turtle vs another turtle in both seats; hands, discards, the combat spots and the deck shuffles must only touch each side's own cards.

### Donatello
Everything here is new (1/11) and has only run against FakeTTS. The deck shares Medusa's CardIDs: check detection (`--read-only`) names Donatello on the right side, also when the other side plays Medusa.

**H and B**
- [ ] Detection with `bot_hero` / `human_hero` on `auto`: "Donatello" is recognised from his deck image (sheet 176, the Donatello face), not mistaken for Medusa or another TMNT deck.
- [ ] Metalhead (token) and both life dials (14 and 7) are found and written.
- [ ] Party wagon!: move a friendly fighter up to 5 through rivals, then 2 damage to one it passed through. Bot: the chat says which; human: you move by hand, the panel asks which rival you passed through (or none), and the 2 damage is mandatory once you name one.
- [ ] Short circuit cancels only the AFTER COMBAT of the rival card (its IMMEDIATELY and DURING still happen).
- [ ] Untested enhancements: you put the real bottom card of your deck in the discard (boost wait), as Flame Lash does.
- [ ] The future of Ninjutsu / Thinking ahead / Donatello does machines: the card goes to or from the right pile.

**B (bot)**
- [ ] INVENTIVE: after its maneuver it draws one more card and puts one card from its hand at the bottom of its deck (the same script as Pyrotechnics, `hand_to_deck`); it never puts an invention there.
- [ ] Invention played: Electro grenade / Self defense grid / Smoke bomb end at `bot_tuck_spot` face up (not in its discard pile) and the bonus applies from the next combat or scheme; the discard zone still reads the same cards as the engine.
- [ ] Cards it removes from the game go to `bot_removed_spot`. Calibrate both spots (estimates in `config\table.json`): outside its discard zone and its combat zone.
- [ ] Without the spots (delete the keys) it only says what to move; the table mismatch warning that follows is expected.

**H (you)**
- [ ] INVENTIVE: after Maneuver the panel asks Yes/No; Yes deals you one more card and the chat says "put 1 card from the top of your deck..." for the card you put at the bottom (by hand).
- [ ] **The future of Ninjutsu, any deck (7/11, new, FakeTTS and the Lua stub only)**. You play it: the panel shows exactly two buttons, "Tu mazo" / "El mazo del bot" (hidden the rest of the time, never greyed). "Tu mazo": the old flow (you look at your deck yourself, Yes/No to put it at the bottom, you draw 1, you gain the action).
- [ ] You play it, "El mazo del bot": the game waits; ONE card of the bot's deck is taken out of its deck (not necessarily the physical top one) and lies face up in the row at `bot_row_spot`, pinged, and the chat names it. Buttons "Dejar arriba" / "Poner abajo". Other buttons say an effect is pending. Check the card is really from the bot's deck (right image) and that `bot_row_spot` is clear of other cards.
- [ ] "Dejar arriba": the card goes back on top of the bot's deck (look at its next draw: it deals that card); "Poner abajo": it goes under the deck (turn the deck over once to check). In both cases you then draw 1 and get the action. Do it with the bot's deck at 2 and at 1 cards (a Deck turns into a loose Card; with 1 card it must go back FACE DOWN to the deck's spot and the bot's next draw must deal it).
- [ ] Ctrl+C with the card still in the row, `--resume`: the chat says why the game waits and the buttons come back; answering puts the card back.
- [ ] The bot plays it (bot_hero Donatello): the chat says it looked at the top card of YOUR deck and whether it left it or put it at the bottom, and it NEVER names the card. Check the top card of your deck really went under it (turn your deck over) when it says so; with your deck at 1 card nothing visible changes. If the chat says it could not read your deck it used its own: check `human_deck_guid` and your deck's zone. It reads your deck with one extra message; nothing else of your hand or deck is read. Verify live that the FIRST card of the deck's contents is the top card (`peek_deck_top` reads it; `deck_top_to_bottom` takes the top one with `takeObject()`).
- [ ] After the bot left your top card on top, draw: the bot plays as if it did not know your next card (it forgets as soon as you draw). Put at the bottom: it knows nothing of your new top card.
- [ ] An invention you play: the chat says to tuck it under your hero card; leave it anywhere outside your discard pile (or leave it there: the bot does not take it back into your discard) and keep going.
- [ ] Electro grenade / Self defense grid / Smoke bomb: the panel lists the cards of your discard pile you may remove (up to 4, types by card); you move them aside by hand.
- [ ] Resume (`--resume`) after tucking: the tucked and removed cards are still out of the discard pile and the bonus still applies.
### Michelangelo
**H and B**
- [ ] The **table data** (`data/tts/michelangelo.json`): miniature `[E77204]Michelangelo`, April's standee and both dials found by `--read-only`; `auto` detects the deck (CardIDs 17600..17629 plus character card 366). Medusa and the turtles share the CardIDs and are told apart by the deck image: also try Medusa vs Michelangelo and a turtle vs a turtle (docs/card-identity.md).
- [ ] **Opening hand 3** and the mulligan (return 3, deal 3); the bot says "3" in the set-up lines.
- [ ] **PIZZA PARTY**: after an attack or a scheme of Michelangelo the extra card is dealt (the human's) or taken (the bot's); nothing is dealt after a defense.
- [ ] **Hand limit 3** at the end of the turn: the chat says "down to 3"; the bot discards to 3.
- [ ] Hi-Yaaaaah!!, Guaranteed Delivery, Shell Insertion: the card put on the **bottom of the deck** from the hand (yours by hand, the bot's by script).
- [ ] **Shell Insertion**: the four buttons (two picks, labels short), the rival's discard, the 2 random discards shuffled back (by GUID).
- [ ] **Nunchaku**: +1 to every attack of Michelangelo that turn (the chat line lists it), not April's.
- [ ] **Cowabunga!!** counts only the cards played on your own turn: as a defense on the rival's turn it gets +0.

### Raphael (Teenage Mutant Ninja Turtles)

Nothing of Raphael has been seen on a real table. His deck is sheet 176 like Medusa's: the first thing to check is that the table is read correctly.
- [ ] **Detection (auto)**: with Raphael's deck at one spot and any other hero's at the other, the start-up line names Raphael (not "unknown deck"); with Medusa on the other side both decks are told apart by their images (the CardID range is the same, 17600-17629).
- [ ] Pieces: Raphael's miniature and dial (17), Casey Jones' token and dial (8) are found by GUID; the dials follow the engine.
- [ ] **ANGER ISSUES (H)**: you attack and lose (value lower or equal): the chat says "Your ability: ANGER ISSUES" and the panel shows one more action; the second lost combat of the same turn gives nothing; losing as defender on the bot's turn gives nothing.
- [ ] **ANGER ISSUES (B)**: the bot attacks as Raphael and loses: it gets one more action in the same turn.
- [ ] **Relentless (H)**: after the combat the chat says "I put Relentless from your combat zone into your deck and shuffle it" and then "I gave you 1 card": the card leaves your combat spot for your deck (deck count +1, then -1 for the draw), the deck is shuffled, the card is NOT in your discard pile and there is no mismatch warning. If the table refuses the chat falls back to "Put Relentless from your combat zone into your deck and shuffle it": do it by hand. **(B)**: the card leaves the bot's combat spot for its deck (translator `return_to_deck`, intent zone "discard"; the card is still in the combat zone when it runs).
- [ ] **Unbridled rage (H)**: the chat tells you to put in your discard pile the defense or versatile cards you give up and press Done (no option buttons; the status line says the same). Put 2 and press Done: the chat counts them (+4) and the combat resolves with them; put an attack card: it is refused by name ("Let's do this! (attack) cannot be given up...") and the panel keeps waiting until you take it back to your hand; Done with nothing new is 0 cards. The hand and the pile match afterwards (no mismatch warning).
- [ ] **Boost cancelled (H)**: you attack with Turtle power! (or Second Shot / Out Of Time as a defense) against a Feint, Planned Recklessness as OCCULT DETECTIVE or Break something: at Reveal the chat says the rival takes the boost away and the combat resolves with no "put a card in your discard pile / Continue" prompt. Against Short circuit (cancels only AFTER) the boost prompt still appears. **(B)**: the bot's Turtle power! / Second Shot into your Feint / Break something is not boosted (no card of its deck goes to its discard for the boost). **(B)**: the bot discards defense/versatile cards from its hand; the discards reach its discard grid.
- [ ] **Break something**: the rival's DURING/AFTER effects do not apply but its IMMEDIATELY does (check with the bot attacking with Burning Barrier or Fireball while you defend with it); with a vanilla rival card, 2 damage to an adjacent rival that YOU choose (H) or the bot chooses (B).
- [ ] **Batter up! (H)**: Casey wins: the panel asks where the bot's fighter goes (up to 3 spaces) or you move the bot's miniature; **(B)**: the bot moves YOUR miniature (`move_piece` by GUID, else "move it yourself").
- [ ] **Raphael is cool but rude (H)**: damage to the bot's fighters adjacent to Raphael or Casey; the dials follow; you draw 1.
- [ ] Payback time! (5 after a lost combat this turn) and Slapshot (6 with Casey adjacent): the combat line shows the new value.
- [ ] Turtle power!: you may boost the attack (the engine reads the boost card you put on the table).

### Doctor Strange (Marvel, Brains and Brawn)

Nothing of Doctor Strange has been seen on a real table. His deck is sheet 176 like Medusa's and the turtles': the first thing to check is that the table is read correctly (docs/heroes/doctor-strange.md has the whole protocol).
- [ ] **Detection (auto)**: with his deck at one spot and any other hero's at the other (Medusa and a turtle included), the start-up line names Doctor Strange; both decks are told apart by their images (same CardID range 17600-17629).
- [ ] Pieces: Doctor Strange's miniature `bb001d` and dial `d95e8b` (14), Wong's token `9256f2` and dial `02474c` (6) are found by GUID; the dials follow the engine.
- [ ] **DARK PACT (H)**: after a combat in which Doctor Strange played a card (attack or defense) the panel shows Yes / No (and nothing else) with the prompt; after one where he played none, or Wong played, nothing appears. Yes: his dial drops by 1, the chat says "I put <card> from your combat zone at the bottom of your deck", the card leaves your combat spot for the bottom of your deck (turn the deck over to check) and you are dealt 1 card after it; no mismatch warning afterwards. No: nothing happens and you discard the card by hand. If the table refuses the chat says to put it at the bottom yourself. **(B)**: the bot pays it sometimes (its dial drops by 1) and its played card leaves its combat spot for the bottom of its deck; it never pays at 4 hit points or fewer.
- [ ] **BLIND BOOST (H)**: playing Bolts of Balthakk (buttons 0 / 1) or Seven Suns (0 / 1 / 2) the panel asks how many blind boosts BEFORE any card is taken; then the bot moves that many cards from the top of your real deck to your discard pile, face up, and the chat names them and the combat shows the boosted value; 0 is no boost; Seven Suns over 7 counts 0; if the table refuses the chat asks you to lay the top cards by hand. Check the physical top cards really are the ones moved (the bot reads their CardIDs from the table). **(B)**: the bot declares the count itself and discards that many top cards of its deck (the cards reach its discard grid).
- [ ] **The Mists of Munnopor (H as the rival)**: the bot defends with it against your attack: the chat tells you to reveal from your deck, put the attack/versatile card you can play face up on your combat spot, the rest at the bottom in random order, and press Done; the bot moves your discarded card to your pile by GUID and the combat uses the new card; a wrong card is refused by name. **(B as the rival)**: you play it against the bot's attack: the chat names the cards the bot reveals and the one it plays; the combat uses it.
- [ ] **The Winds of Watoomb**: the bot places your Strange (or you place the bot's, by hand and Done) in a starting space and the opposing fighter in another one; the bot shuffles its draw pile and tells you to shuffle yours.
- [ ] **Eye of Agamotto (H)**: the bot puts your whole hand in your deck, shuffles it and deals 5, in that order, no mismatch warning.
- [ ] **No, Really, I'm a Doctor (H)**: you put the revealed card on your discard pile, press Done, the bot puts it on top of your deck, and the panel asks whom to heal (Strange / Wong when next to him).
- [ ] Master of Kamar-Taj (4 with Wong adjacent), Cloak of Levitation (the rival's value ignored when Strange is adjacent), The Rings of Raggadorr (heal by the damage dealt) and Steadfast Disciple (1 damage and a draw with Wong adjacent): the combat line shows the new values and the dials follow.

### Houdini (Houdini vs. The Genie)

Nothing of Houdini has been seen on a real table. His deck is sheet 178 (CardIDs 17800-17829) with the character card on a sheet of its own (177): no other hero shares his CardIDs.
- [ ] **Detection (auto)**: with Houdini's deck at one spot and any other hero's at the other, the start-up line names Houdini (not "unknown deck"); the bag holds two images (the character card's and the cards').
- [ ] Pieces: Houdini's miniature (`3ec3d1`, a Custom_Assetbundle) and dial (`fdb21e`, 14), Bess's token (`a73e79`) and dial (`ede1d4`, 5) are found by GUID; the dials follow the engine.
- [ ] **ESCAPE ARTIST (B)**: the bot maneuvers spending a boost card and Houdini ends far from Bess; the chat names where, and the miniature really moves there. **(H)**: you put a boost card in your discard pile, place Houdini anywhere and press End action: no warning about the move.
- [ ] **Maneuver boost button (H, 7/11)**: after the Maneuver draw the panel shows **Boost** (not before, not after boosting). Put Flourish in your discard pile and press it: the chat announces the boost value and, for Houdini, that he may be PLACED anywhere (ESCAPE ARTIST); Flourish's draw is dealt and the card is in your hand (nothing like "DISCARD: P1 <card>" in the log at the bot's turn start); the turn does NOT end. Then place Houdini far away and press End action: it ends. Old habit (discard + End action at once): effects run, the turn waits for a second End action. A boost with a choice (Misdirection, Set the Stage) waits for your answer first.
- [ ] **BOOSTED WITH in a Maneuver (H)**: Flourish / Sleight of Hand draw one card for you (the bot deals it), And The Beautiful Bess! gives the action back (the panel shows 2 actions), Misdirection asks which fighter takes 2 damage (the dials follow), All Part of the Show heals Houdini 2, Set the Stage shows the bot's hand and asks which card it discards. **(B)**: the bot's line says "<card>, spent as a boost: draws 1 / gains 1 action" and the hand on the table matches.
- [ ] **Boost in a combat (H)**: attack with Flourish / Grand Escape / An Illusion of My Own Design / The Big Reveal: after Reveal the cards stay face up and the chat asks for the boost card(s); The Big Reveal takes up to two (a third is refused by name) and then asks which boosted card you take back to your hand (you move it from your discard pile yourself).
- [ ] **An Illusion (B)**: the bot attacks with it: at Reveal your card, any card, may be boosted (the prompt appears even for a card without a boost of its own). **(H)**: the bot's defense may be boosted (its card goes to its discard grid with the boost).
- [ ] **Smoke and Mirrors (H)**: the panel asks Yes / No; with Yes the chat says "swap the miniatures of houdini and bess" and the combat line names Bess as the one who fought. **(B)**: the bot swaps its two miniatures on the table (`move_piece` by GUID) and the combat line names the fighter that fought.
- [ ] **All Part of the Show**: Houdini at 1-4 HP defends and the blow would kill him: the game does NOT end; **(H)** the chat tells you to put Houdini on any space at 4 health and the dial shows 4; **(B)** the bot puts his miniature back on the board (the dead spot, then the chosen space) and the dial shows 4.
- [ ] **Vanishing Act / Grand Escape / For My Next Trick (H)**: the chat tells you to move or place the miniature by hand ("up to 3 spaces, through the opposing fighters", "any space"); **(B)**: the bot moves its piece or yours (`move_piece`).
- [ ] **Set the Stage (B)** as a boost: the bot reads your hand exactly once (one `read_hand`), names a card and tells you to put it in your discard pile; played as a scheme by Bess it draws three and puts one on top of its deck.
- [ ] **A Magician Never Reveals His Secrets**: when the bot's card is about to look at your hand (Confront Any Demon or God after it loses) the panel asks whether to reveal it; with Yes nothing is read from your hand and the bot's row does not open.
- [ ] **And The Beautiful Bess!**: the bot's effect (Confront, Shock And Awe...) makes you discard her: draw 1 card by hand (the bot does not know it was its effect; nothing warns you).
- [ ] **Sleight of Hand (B)**: the bot attacks with it (adjacent, Houdini or Bess, with attack/versatile cards in hand): after Reveal the chat announces "Sleight of Hand: the bot takes it back to its hand and puts X face up...", waits, and on the table Sleight of Hand really goes from its combat spot to the bot's hand (its hand count is the same as before) and X lies face up on the combat spot with the card zoom showing X; the result line names X; X goes to the discard pile afterwards. If you defend with a high card the bot keeps Sleight (nothing moves). A refusing table: the chat says what to move.
- [ ] **Sleight of Hand (H)**: you attack with it (face down, Reveal): the panel shows Yes / No only then (hidden before and after). No: you attack with a value 1. Yes: the chat says to take Sleight of Hand back to your hand and put the new card face up on your combat spot; do it and press Done: the combat continues with the new card (value, effects, AFTER as normal), Sleight of Hand is in your hand again. Try: a defense card (refused by name), Bess's card with Houdini, the other copy of Sleight of Hand (refused), two cards on the spot, leaving Sleight next to the new card (the bot takes it to your hand), Done with nothing on the spot (refused), and quitting the program at the question and resuming with --resume. Expected known gap: if the new card has a free BOOST (Flourish) you are not asked to boost it.

### Bigfoot (Robin Hood vs. Bigfoot)

Nothing of Bigfoot has been seen on a real table. His deck is sheet 176 like Medusa's, the turtles' and Doctor Strange's: the first thing to check is that the table is read right.
- [ ] **Detection (auto)**: with his deck at one spot and any other hero's at the other (Medusa, a turtle and Doctor Strange included), the start-up line names Bigfoot; the bag holds a deck of 31 cards (character card 309).
- [ ] Pieces: Bigfoot's miniature `dc0472` and dial `de393d` (16), the Jackalope's token `b31c7a` (named "Jackalope") and dial `18c384` (6) are found by GUID; the dials follow the engine.
- [ ] **GUID `18c384` is also Lobster Johnson's dial (Hellboy's bag)**: play Hellboy against Bigfoot (and the reverse) with both bags out. Expected: the start-up warns about the shared GUID; at the first dial write the chat says which dial it followed instead (the one named like the fighter, `dial.resolved`), and the Jackalope's and Lobster's dials show the right life after a hit on each. If the chat says it cannot tell them apart (`dial.unresolved`) it writes neither: set both by hand. Note which one TTS gave the new GUID.
- [ ] **Ability (H)**: at the end of your turn with no bot fighter in Bigfoot's zone the panel shows Yes / No with the prompt "End of your turn, and no opposing fighter is in Bigfoot's zone: do you draw 1 card?"; with a bot fighter in his zone nothing is asked. Yes: the bot deals you 1 card (the chat line says you draw 1) and the hand count matches. **(B)**: the bot draws at the end of its turn only when no fighter of yours is in its Bigfoot's zone and its hand is below 7; the table's hand matches the engine's.
- [ ] **Savagery**: winning with it hits every fighter adjacent to Bigfoot for 1 (the Jackalope too if it stands next to him); the dials follow.
- [ ] **Disengage / Hoax / Crash Through the Trees (H)**: the chat says to place / move Bigfoot by hand ("on the table: place bigfoot in your hero's zone" / "move bigfoot up to 5 spaces", through the `tbl.*` texts); the table sync reads where you put him. When the Jackalope plays Disengage the line names the Jackalope's zone, not the hero's. **(B)**: the bot moves its Bigfoot on the table.
- [ ] **Skirmish (H)**: after a win the panel asks which fighter of the combat (yours or the bot's) and the bot moves ITS miniature, or you move yours by hand. Up to 2 spaces.
- [ ] **Jackalope Horns (H)**: the card is played by the Jackalope (the chat line says to move the Jackalope, never Bigfoot); the chat first tells you to move the Jackalope by hand (up to 5, through rivals) and the panel shows Done; only after Done does the question "Choose a fighter adjacent to The Jackalope" come (not asked when only one fighter, or none, is next to it): that fighter takes 2 (the dial follows). With the Jackalope down the card is refused with a chat line (`scheme.no_fighter`) and Bigfoot does not play it. **(B)**: the bot announces it, moves the Jackalope's miniature and hits the adjacent fighter of yours.
- [ ] Regroup (2 cards on a win, 1 otherwise, dealt by the bot), Momentous Shift (5 when the fighter started the turn elsewhere, also when defending), Feint and It's Just Your Imagination (cancel), Larger Than Life (plain 6).

### Daredevil (Marvel, Hell's Kitchen)

Nothing of Daredevil has been seen on a real table. His deck is sheet 176 like Medusa's, the turtles', Doctor Strange's and Bigfoot's, with 22 playing cards (CardIDs 17600-17621) plus the character card 338 (23 in the bag): the first thing to check is that the table is read right. Full protocol: docs/heroes/daredevil.md.
- [ ] **Detection (auto)**: with his deck at one spot and any other hero's at the other (Medusa, a turtle, Doctor Strange and Bigfoot included), the start-up line names Daredevil; the bag holds a deck of 23 cards and no warning says the deck is short.
- [ ] Pieces: Daredevil's miniature `ae91f4` and dial `cfc705` (17) are found by GUID; the dial follows the engine. He has no sidekick.
- [ ] **Ability (H)**: attack or defend with 2 or fewer cards left in your hand after playing the card: the panel shows 0 / 1 (prompt "BLIND BOOST: how many cards do you discard...") and nothing else; with 3 or more nothing is asked and no button is greyed. 1: the bot moves the top card of your real deck to your discard pile face up and the chat names it as "la habilidad especial de Daredevil" with its bonus; the combat shows the new value. 0: no boost. If the table refuses the chat asks you to lay the card by hand. **(B)**: the bot declares it sometimes (its deck loses a card face up on its discard grid).
- [ ] **The order (H)**: play Man Without Fear (or Devil of Hell's Kitchen) with 2 or fewer cards left: there is NO order question: the panel asks the ability's blind boost (0/1) first, then the card's own (Man Without Fear). With Devil and exactly 1 card left in your deck, declaring 1 for the ability empties the deck and the Devil is worth 8.
- [ ] **A cancelled card keeps the ability**: the bot plays Feint against your Man Without Fear: you are still asked the ability's 0 / 1, but not the card's own blind boost.
- [ ] **Take A Knee (H)**: after the combat the panel shows ONE button ("1") with the prompt "Take A Knee: press to discard the top card of your deck..."; pressing it the bot moves the top card of your deck to your discard pile, face up, and Daredevil's dial goes up by that card's BOOST (at most to 17). With an empty deck nothing is asked. **(B)**: the bot discards its top card and its dial goes up.
- [ ] **Devil of Hell's Kitchen (H)**: AFTER the combat the bot moves the card from your combat spot into your deck and shuffles, and the 4 cards that most recently reached your discard pile into your deck and shuffles (two shuffles; the Devil plus 4 = 5 cards in all): check the discard pile lost exactly those 4 and the chat names them; the order of the pile is the one the engine believes. With no cards in your deck it is worth 8.
- [ ] **Through Adversity (H)**: the chat tells you to move Daredevil up to 4 spaces through opposing fighters by hand; the panel then asks which opposing fighters you passed (one button each + "None", confirm): each one named takes 1 and the dials follow. **(B)**: the bot moves him and every rival he passed takes 1 (the chat line says who); it picks the square for that damage and plays the scheme when the jump kills (a 1-HP sidekick on the way).
- [ ] Breather (pick a non-scheme card from your discard pile and take it to your hand), Grappling Hook (the chat tells you to move him up to 2 spaces), Son Of A Boxer (after a lost combat, the panel asks which adjacent fighter takes 2), Feint (cancel).

### Luke Cage (Marvel, Redemption Row)

Nothing of Luke Cage has been seen on a real table. His deck is sheet 176 like Medusa's, the turtles', Doctor Strange's and Bigfoot's: the first thing to check is that the table is read correctly (docs/heroes/luke-cage.md has the whole protocol).
- [ ] **Detection (auto)**: with his deck at one spot and any other hero's at the other (Medusa, a turtle, Strange and Bigfoot included), the start-up line names Luke Cage; both decks are told apart by their images (same CardID range 17600-17629).
- [ ] Pieces: Luke Cage's miniature `b56d0d` and dial `63d2ef` (13), Misty Knight's token `2b710e` and dial `d35f8c` (6) are found by GUID; the dials follow the engine.
- [ ] **The ability (H and B)**: a blow on Luke Cage is two lighter: the chat says "luke recibe 2 de dano de combate menos" and his dial drops by the reduced damage only. A blow of 2 or less (after his defense card) does nothing and he wins the combat, with or without a defense card (Trash Talk then ends the bot's turn). Misty takes the full blow.
- [ ] **Power Man (H)**: after the combat the panel/chat tells you to move the bot's attacker up to 3 spaces (by hand, then Done); the attacker loses 1, and so does each other bot fighter that could lie on the path you took. **(B)**: the bot moves your piece by GUID where it chose and hurts it for 1 (and the fighters it crossed).
- [ ] **Got My Back? (H)**: when Misty defends with it the panel asks Yes / No (and only then); Yes: the chat says to swap the two miniatures (yours), Luke takes the blow with his 2 less and Misty's dial does not move; No: Misty takes it. **(B)**: the bot swaps by GUID when Luke is the better one to hit.
- [ ] **Where's My Money? (H)**: the chat says "on the table: place luke on a space next to the nearest opposing fighter"; you place him by hand and press End action; you keep your action count (the scheme gives one back). **(B)**: the bot moves its Luke next to your nearest piece.
- [ ] **Still Standing (H)**: after winning, the chat asks you to take 2 cards out of your discard pile and shuffle them into your deck, then press Done; the bot reads the change. **(B)**: the bot puts its two cards back by GUID and shuffles.
- [ ] Skin Like Titanium (the attacker loses what Luke lost, only when he lost the combat), Trash Talk (cancel, and a win ends the bot's turn), Daughter of the Dragon (6 with Misty adjacent to the target, also defending), Pushback, Regroup / Get Paid / Commanding Impact (cards dealt by the bot): the combat line shows the right values and the dials follow.

### Bullseye (Hell's Kitchen, no sidekick)

Nothing of Bullseye has been seen on a real table. His deck is sheet 176 like Medusa's, the turtles', Doctor Strange's and Bigfoot's: the first thing to check is that the table is read right (and that 13 heroes with TTS data still detect: `MAX_HERO_RANGES` went from 12 to 24).
- [ ] **Detection (auto)**: with his deck at one spot and any other hero's at the other (Medusa, a turtle, Doctor Strange and Bigfoot included), the start-up line names Bullseye; the bag `4c1656` holds a deck of 31 cards (character card 339).
- [ ] Pieces: Bullseye's miniature `ca1bc5` and dial `166320` (14) are found by GUID; the dial follows the engine. He has no sidekick: nothing else comes out of his bag.
- [ ] **Reach, human (H)**: put Bullseye 5 spaces from a bot fighter, in no zone you share with it (count the spaces along the lines of the board, not through the secret passages), press Attack and pick it: accepted. A target in a zone you share is accepted however far (6+ spaces, e.g. space 8 against 27 on bprd-hq). From 6 spaces and out of every shared zone the chat says "bullseye no alcanza a ..." and nothing is spent. Note any pair of spaces where the bot's count differs from yours (adjacency of the map data).
- [ ] **Reach, bot (B)**: the bot's Bullseye walks to a space 5 or fewer spaces from you instead of next to you, attacks from there, and keeps out of your reach when it can; no attack is announced from more than 5 spaces.
- [ ] **I Never Miss (H)**: after Reveal the panel offers the free BOOST; No boost: the bot deals you 1 card (chat: you draw 1, hand count matches); boosting (a card of your hand on your discard pile + Boost): no card is dealt. **(B)**: the bot's Bullseye draws 1 when it does not boost.
- [ ] **Already won a combat this turn (H)**: after a combat you won, I'm Better And I'll Prove It counts 6, World's Greatest Assassin ignores the bot's card (its value reads 0 on the result line), Right Between The Eyes makes the bot discard a card (the bot's hand count drops by one), Study The Target deals 3 cards and gives the action back; before any win this turn none of that happens (Study The Target deals 2). Also when defending on the bot's turn. **(B)** the same from the bot's side.
- [ ] **Arrogant But Effective (H)**: lost on the damage, the chat says "you are considered to have won the combat" and the card after it reads the win; then the chat tells you to move Bullseye up to 2 spaces by hand. Open question: whether the rival's own AFTER should then read a loss.
- [ ] **Tactical Retreat (H)**: when the bot attacks you and you defend with it, the chat says to place Bullseye in a space that shares no zone with his current space; the table sync reads where you put him. **(B)**: the bot moves its Bullseye there.
- [ ] **Master Strategist (H)**: "move bullseye exactly 4 spaces (may go through rivals)"; the engine accepts any final space the table shows (it only reads where you ended). With no space exactly 4 away you are NOT asked to move: the chat says the move is cancelled and nothing happens, no stall (Iván 2026-11-07). **(B)**: the bot walks exactly 4 through your fighters, never ending on one, or does not move when no space is exactly 4 away.
- [ ] **Ricochet (H)**: the panel asks which fighter in the opposing fighter's zone takes 1 damage (the opposing fighter itself is one of the options); the dial follows. Nothing is asked when the opposing fighter was defeated. **(B)** the bot never picks its own fighter.
- [ ] **I Planned To Be Here**: 5 only when Bullseye has not moved this turn (a Maneuver or an effect that moved him makes it 2).
- [ ] **For My Next Trick (H)**: after the combat, win or not: move Bullseye up to 1 space by hand, the bot deals you 1 card, you get an action back.
- [ ] Feint (cancel), World's Greatest Assassin (4) and the rest of the numbers as printed.

### Golden Bat (Tales to Amaze, no sidekick)

Nothing of Golden Bat has been seen on a real table. His deck is sheet 176 like the other ten: the first thing to check is that the table is read right.
- [ ] **Detection (auto)**: with his deck at one spot and any other hero's at the other, the start-up line names Golden Bat; the bag `4732a0` holds a deck of 31 cards (character card 345). His miniature `b0ebcc` and dial `0f46cb` (18) are found by GUID; nothing else comes out of his bag.
- [ ] **THE FIRST SUPERHERO (H)**: attack without any Maneuver this turn: the result line reads "THE FIRST SUPERHERO (+2)"; after pressing Maneuver (and the card or draw it asks) the same attack has no +2 until the next turn. With a draw prevented (the bot's Cold Iron) the Maneuver does NOT count and the +2 stays; with your deck empty it does count (and each of your fighters takes 2 of exhaustion). The bot's Golden Bat gets no +2 on an attack taken after its own Maneuver.
- [ ] **Terrifying Roar (H)**: played by you (attack or defense), the chat says every fighter is held in place for the turn; try to move yours and the bot's pieces by hand (the engine ignores a move the table shows, the chat should flag it). **(B)**: the bot's Golden Bat does not move for the rest of the turn.
- [ ] **Like a Flash of Golden Light (H)**: value 4 only when your Golden Bat is on a space that shares no zone with the one he started the turn on (also when defending: the space he was on when the bot's turn began); then "move up to 5 spaces" by hand. **(B)** the same from the bot's side.
- [ ] **Sight Beyond Sight (H)**: the panel shows the bot's top 3 cards by name and asks the order; the bot's deck order follows (check its next draws). **(B)**: the bot reads your REAL top 3 (check the physical cards): the chat does NOT say which it saw: it says only "he reordenado las 3 cartas superiores de tu mazo" and the bot has really reordered your physical deck (Iván, 2026-11-08): the 3 cards stay face down on your deck in the bot's order (worst for you first), nothing else on the table moves, the deck count is the same and no card is flipped or shown. Verify live on the real TTS: the cards go back to the same deck (not a new pile beside it), a deck of 3 or fewer cards is rebuilt in place, and nothing lands in a hand zone. Pull one card out of the top 3 before the step to check the abort: nothing moves and the chat says "no he podido reordenar tu mazo". When you draw, discard or shuffle afterwards the bot forgets them. If the table cannot be read, the chat says it does nothing.
- [ ] **Vaporizing Eyebeams**: the bot discards a random card of your hand (the table draws it at random) and vice versa; **Insight of the Ancients** (a random card of the discard pile returns to the hand when he won).
- [ ] **A Punch to Shake the Earth (H)**: each rival fighter in Golden Bat's zone takes 1 (2 if he won); the dials follow. Skirmish: after a win the panel asks which fighter of the combat moves up to 2 (the bot's piece is moved by hand and you press Done).
- [ ] **Sight Beyond Sight (H), order on the table (Iván, 2026-11-08, `order_by_hand`, never seen live)**: attack or defend with it and press Reveal. (a) The bot takes its REAL top 3 off its deck and lays them FACE UP in a row at `order_spot` (default [-10.5, 2.5, 22.5], step [0, 3.4]: a column along z on the human's far side, cards at z 19.1, 22.5, 25.9): are they clear of the decks, dials, pieces, the discards, the panel and the board, and of the White hand zone (check this one first), readable from your seat, not in your hand? Note the spot to move if it is wrong. They are the engine's top 3, not the physical top of the deck; the chat says "he puesto mis 3 cartas de arriba boca arriba en la mesa ..." and the panel shows only Hecho. (b) Pick them up, look at them and drop them face down on the bot's deck in the order you want: the FIRST you drop must end UNDER the others and the LAST one on TOP (TTS puts a card dropped on a deck on top; if a face-up card dropped on the face-down deck stays face up inside, say so). Press Hecho: "Anoto el orden ..."; draw/discard checks later: the bot's next draws take the cards in the order you stacked. (c) Mismatch: leave one card on the table and press Hecho: the chat names the missing card and nothing moves; put it on top and Hecho again works. Put one of the bot's other cards on top: the chat only counts it ("Hay 1 carta(s) mas encima ...") and never names it. (d) Save and `--resume` while the cards lie on the table: the chat says the instruction again and the cards are NOT laid a second time. (e) Insightful Deduction played by you (Jill): after choosing the card that goes under the deck, the bot itself puts that card at the bottom of its deck (check the bottom card of the physical deck is it) and lays the other 2 the same way; if the move fails the chat says so. (f) With `order_by_hand: false`, or if the lay fails, the panel shows the old buttons (one per card name).
- [ ] **Alpine Fortress (B)**: the bot shuffles a card of its discard pile into its deck and draws 2: its hand count on the table agrees with the engine. **(H)**: the chat says to shuffle a chosen card into your deck, draw 2 and move Golden Bat up to 4. **Arrive Just in Time**: place Golden Bat in any space.
- [ ] Imposing Presence (cancel), Super Strength (5), He Laughs at Your Feebleness (5 defense) and the numbers as printed.

### Dr. Jill Trent (Tales to Amaze, with Daisy)

Nothing of Jill Trent has been seen on a real table. Her deck is sheet 176 like Medusa's, the turtles', Doctor Strange's, Bigfoot's and the Marvel decks': the first thing to check is that the table is read right (16 heroes with TTS data).
- [ ] **Detection (auto)**: with her deck at one spot and any other hero's at the other, the start-up line names Dr. Jill Trent; the bag `55b9e4` holds a deck of 31 cards (character card 348) and the Ultrabiotic Tonic token `8af285`, which is her gadget token now (see below).
- [ ] Pieces: Jill's miniature `448a24` and dial `9bb234` (13), Daisy's token `0bf463` and dial `e10c99` (6) found by GUID and name (Abe Sapien's agent Carla is also `0bf463`: with both heroes in play the second piece out of its bag gets a new GUID and the session follows it by name).
- [ ] **Gadget, human (H)**: at the start of your turn the panel shows two buttons, Hypnoray Blaster and Ultrabiotic Tonic; the chat says which is active. **(B)**: the bot's Jill picks one each turn (the Tonic when hurt by 3 or more, the Blaster otherwise).
- [ ] **Gadget token (bot's spot measured 2026-11-08; the rest still calculated)**: after Prepare the token `8af285` lies at its single spot past Jill's deck (bot half x 4.98, z 21.1; human half x -6.6, z 21.17), face up, not on the board, the deck, the dial or off the table; if not, correct `token_slots.gadget` in `data/tts/jill-trent.json` (one entry per side). It is double-sided and only turns in place: Ultrabiotic Tonic active = Tonic face up; Hypnoray Blaster active = flipped (the Blaster face shows); no gadget yet (Jill plays second) = Tonic face up turned 90 degrees. Check for both seats (**H** panel choice, **B** the bot's choice) that the token stays at its spot and only turns. The chat line that announces the gadget is still there. `--resume` puts it back where the saved gadget says; Clean table and New game remove it; take it off the table by hand: the chat says once that it cannot find it and the game goes on.
- [ ] **Gadget token face**: confirm that rotation Z 0 shows the Ultrabiotic Tonic readable face up and Z 180 shows the Hypnoray Blaster (the save stores the token at Z 180 inside the bag); if they are the other way round, swap them in `sparring/session_gadget.py` `spot`.
- [ ] **Hypnoray Blaster (H)**: attack with a card whose printed value is lower than the bot's defense: the chat names the top card of the bot's deck (it stays on top) and your attack is worth its BOOST more. **(B)**: the bot's Jill does the same on you: the bot reads the real top card of your deck (one read message) and names it in the chat.
- [ ] **Ultrabiotic Tonic**: with a printed value higher than the rival's (or no card against it) Jill recovers 1 (the dial follows). Not for Daisy, unless she plays Sisters In Arms next to Jill (then Jill recovers).
- [ ] **Battle of Wits**: the chat names both top cards; 3 damage only when yours has the strictly higher BOOST.
- [ ] **Insightful Deduction (H)**: the panel asks which of the bot's top three goes to the bottom, then the order of the other two; the bot's next draws follow it. **(B)**: the bot reads your real top three (one read message), the chat names the three revealed cards (the card says reveal) and says "he reordenado las 3 cartas superiores de tu mazo y he mandado 1 al fondo" without saying which: the bot moves your physical deck itself, blind (Iván, 2026-11-08), face down, the count unchanged (same live checks as Sight Beyond Sight).
- [ ] **Stasis Diffuser**: the rival's card is worth its printed value (a boost or a value effect of theirs adds nothing).
- [ ] **Indestructible Cloth**: no effect damage to your fighter in that combat, from either side; combat damage lands.
- [ ] **Utility Belt (H)**: three buttons (recover 1, move Jill 1 space, draw 1); with the move you place Jill by hand. **Helpful Assistant (H)**: pick up to 3 of your Jill cards in your discard pile; shuffle them into your deck by hand. **Caught Red-Handed**: the bot discards 1 (2 if you won); against you the bot asks you to discard.
- [ ] Hypnotist (cancel only with the Blaster active), Gyroscopic Jetpack (up to 2, through rivals), Ace Fighter, Energizing Spray and Laser Pen as printed.

### She-Hulk (Brains and Brawn, no sidekick)

Nothing of She-Hulk has been seen on a real table. Her deck is sheet 176 like Medusa's, the turtles', Doctor Strange's, Bigfoot's and the Hell's Kitchen heroes'.
- [ ] **Detection (auto)**: with her deck at one spot and any other hero's at the other, the start-up line names She-Hulk; the bag `04711f` holds a deck of 31 cards (character card 336). Her miniature `95f90a` and dial `268982` (20) are found by GUID; she has no sidekick.
- [ ] **Card identity**: play every card you can see and compare the title the chat says with the card you played; note which ones differ.
- [ ] **JUST THROW SOMETHING (H)**: at the start of your turn with an opposing fighter in her zone the chat says LANZA ALGO / JUST THROW SOMETHING and the panel waits for End action; you discard a card and lower the rival's dial by the card's BOOST by hand; with nobody in her zone nothing is asked. **(B)**: the bot says "JUST THROW SOMETHING: the bot discards X (BOOST n) ..." at the start of its turn, the card is on its discard pile and your fighter's dial goes down by n.
- [ ] **The Savage She-Hulk (H)**: after Reveal the panel asks Yes / No for the additional action; Yes: the value is 9 and you have one action fewer (the chat counts them); with no action left after the attack nothing is asked. **(B)**: the bot spends the action when the extra damage is worth it.
- [ ] **Lady Justice, played by the bot against you (B)**: the panel shows one button ("Press to let the bot discard the top card of your deck"); after it the bot moves your REAL top card to your discard pile, face up, and the chat names it; the defense is 2 x its BOOST. If the table refuses, the chat asks you to lay the card yourself. **(H)**: when you play it, the bot's top card goes to the bot's discard pile and the defense is 0 + 2 x its BOOST.
- [ ] **Omega-Level Threat (H)**: dealing 2 or more combat damage makes the bot discard 2 random cards (its hand count drops); below 2 nothing. **(B)**: you are asked to discard 2 random positions.
- [ ] **Legalese (H)**: won, the bot chooses (both draw / both discard) and says it in the chat; lost, you choose on the panel. Both draw: you are dealt a card and the bot draws; both discard: you discard one by hand and the bot one.
- [ ] **Jennifer Walters, Esq. / Leap Toward (H)**: "place shehulk on a starting space" and "move up to 4 (may go through rivals)" by hand; Leap Toward gives the action back only if she ends next to an opposing fighter. **(B)**: the bot places / moves her miniature.
- [ ] Nerve Cluster Strike (the opposing fighter cannot leave its space this turn when she is adjacent), Cease and Desist (4 attacking, cancel), Green Energy (1 to every fighter next to her when she wins), The Defense Rests (cards dealt equal to the damage taken), Sensational (a card of the discard pile back into the deck when she wins), Double Jeopardy (2 cards, 2 health): the combat lines show the right numbers and the dials follow.

### Tomoe Gozen (Sun's Origin, no sidekick)

Nothing of Tomoe Gozen has been seen on a real table. Her deck is sheet 176 like Medusa's, the turtles', Doctor Strange's, Bigfoot's, Daredevil's, Luke Cage's and Bullseye's, and her life dial `ca8e35` is also Donatello's: the first things to check are the detection and the dials.
- [ ] **Detection (auto)**: with her deck at one spot and any other hero's at the other (any deck of sheet 176 included), the start-up line names Tomoe Gozen; the bag `c5fe82` holds a deck of 31 cards (character card 354).
- [ ] **Pieces and the shared dial**: her miniature `66c85f` and dial `ca8e35` (14) are found; with Donatello on the other side the chat says the dial was resolved by name (`dial.resolved`) and both life dials follow the engine (neither is written onto the other hero's dial).
- [ ] **ATTACK OF OPPORTUNITY (H)**: with the bot's Tomoe Gozen, drag your hero out of her zone (a Maneuver, then End action): the chat says "ATTACK OF OPPORTUNITY: ... loses 1 HP" and your dial drops by 1 at once; staying in her zone costs nothing; moving a sidekick out costs nothing. **(B)**: the bot's hero prefers to stay in her zone and, when it leaves, the dial of the bot's hero follows.
- [ ] **ATTACK OF OPPORTUNITY by effects**: her A Warrior's Way and Skirmish (a rival hero moved out of her zone) cost the rival hero 1 health; a swap with her (Fearsome Strength) costs nothing.
- [ ] **Witness My Last Battle (H)**: against a fighter that is not adjacent the Reveal says it can only target an adjacent fighter and nothing is spent; against an adjacent one the bot defends seeing the card (the chat says it is played face up), the damage is 7 minus the defense and the turn ends (the panel passes to the bot). **(B)**: the bot's card is flipped face up on the table and the chat says its value.
- [ ] **Deeds Of Valor (H)**: against a big attack the bot's chat line says "recibe como mucho 2 de dano de combate" and your dial loses at most 2.
- [ ] **Lord Kiso's Final Stand (H)**: the panel asks heal 2 / gain 1 action; the chat says to move Tomoe Gozen up to 3 spaces by hand (may pass through sidekicks) and the table sync reads where you put her. **(B)**: the bot moves her through your sidekicks (never through your hero).
- [ ] **Five Against Thousands (H)**: adjacent to the opposing fighter the panel asks Yes / No; Yes: you put one card of your hand on your discard pile and Five Against Thousands goes back to your hand (the chat says it came back); the bot knows it is in your hand. **(B)**: the bot discards a weak card and takes the card from its combat spot back to its hand.
- [ ] **A Warrior's Way (H)**: the bot decides where your hero goes (up to 3) and you move it; then the chat tells you to place Tomoe Gozen adjacent to it by hand (not asked against a sidekick). **(B)**: the bot moves your piece and places its own.
- [ ] **Refuse to Retreat (H)**: your Maneuver is refused (she cannot leave her space) for the rest of the turn; the bot discards a card when the opposing fighter is adjacent.
- [ ] Piercing Shot (2 cards), A Worthy Opponent (5 against a hero), Flash of Steel (cancel against a hero, 1 damage when adjacent), Fearsome Strength (swap and 1 damage), Confront Any Demon or God and Skirmish (as Hellboy's and Bigfoot's) and the numbers as printed.

### Ciri (The Witcher: Steel & Silver, sidekick Ihuarraquax)

Nothing of Ciri has been seen on a real table. Her deck is sheet 176 like Medusa's, the turtles', Doctor Strange's, Bigfoot's, Daredevil's, Luke Cage's, Bullseye's and Tomoe Gozen's; her Source is a dial of the bag (`46aa92`, a Custom_Model like Hellboy's destiny dial) and Ihuarraquax's miniature is a `Custom_Token` (`4ec239`): the first things to check are the detection, the pieces and the dials.
- [ ] **Detection (auto)**: with her deck at one spot and any other hero's at the other, the start-up line names Ciri; the bag `45ae7e` holds a deck of 31 cards (character card 344).
- [ ] **Pieces and dials**: Ciri `f6fea4` (life dial `e6da98`, 15), Ihuarraquax `4ec239` (a token: it moves like a miniature, check the height it lands at; life dial `341412`, 7) and the Source dial `46aa92` come out of the bag; the three dials follow the engine.
- [ ] **The Source dial**: it shows the number of Source cards (the orb on the art band) in Ciri's discard pile: it goes up when she plays or discards one, down when The lady of space and time takes one out of the pile; **(H)** the bot writes it for you too; a value you edit by hand is respected (warning) and not overwritten.
- [ ] **UNCONTAINABLE POWER**: with the Source at 7 or more, a Parry or Feint against any Ciri card cancels nothing (the chat says the card keeps its effects); at 6 it does.
- [ ] **Lion cub of Cintra / Zireael (H)**: the damage uses 2, 4 or 7 (Lion cub) and 2 or 4 (Zireael) according to the Source on your pile at the moment of the Reveal; **(B)** the same for the bot. Zireael at Source 5: the bot discards a random card (the table follows), or the chat tells you to discard the position it names.
- [ ] **Pushed to the brink (H)**: Source 2-6 hits the opposing fighter for 1; Source 7+ asks which opposing fighter within 3 spaces of Ciri takes 2. **(B)** the bot picks one.
- [ ] **Child of the Elder Blood (H)**: every other fighter in Ciri's zone (Ihuarraquax included) takes 1 (Source 4) or 3 (Source 9) and the dials follow; nothing below Source 4.
- [ ] **Channel the source (H)**: the panel tells you to put the Source cards you give up on your discard pile and press Done; a card without the orb is refused with the reason; +2 each. **(B)**: the bot discards Source cards from its hand.
- [ ] **Searching strike (H)**: after a win the panel asks Yes / No; Yes: you search your deck for a Source card, show it, take it and shuffle (the chat says so). **(B)**: the chat says "The bot searches its deck and reveals X" and the card really leaves the bot's deck for its hand (`deck_card_to_hand`; if the table refuses the chat says to move it yourself).
- [ ] **The lady of space and time (H)**: Source 3-7 asks for a card of your discard pile to put on top of your deck (you move it), Source 8+ asks for one to take into your hand and you draw 1. **(B)** the bot's cards move by themselves.
- [ ] **Bane of the Aen Elle / Blink**: Ihuarraquax moves up to 4 (Blink: Ciri up to 3) through rival fighters; Bane then hurts one rival he crossed. **(H)** you walk the miniature and the panel asks which rival he passed.
- [ ] **Unicorn ally (H)**: Ciri recovers 2; the card stays on your ONGOING spot; after every combat of either player the chat tells you to draw 1; at the end of your turn with 5 or more cards in hand it goes to your discard pile. **(B)**: the bot's copy rests on its ONGOING spot and leaves the same way.
- [ ] Parry (cancel) and the numbers as printed.
### Eredin (The Witcher: Realms Fall, four Red Riders)

Nothing of Eredin has been seen on a real table. His deck is sheet 176 like Medusa's, the turtles', Tomoe Gozen's and the rest, and his four Red Riders are tokens (Custom_Token in the save, "Tile" in real TTS): the first things to check are the detection and the tokens.
- [ ] **Detection (auto)**: with his deck at one spot and any other hero's at the other, the start-up line names Eredin; the bag `9183b3` holds a deck of 31 cards (character card 350).
- [ ] **Pieces**: his miniature `dd0bc4`, his dial `a0a36e` (14) and the four tokens Maxwell `a954e5`, Aleksei `bb3949`, Adrian `63fb79`, Norman `dc3fc9` are found by GUID (obj.type "Tile" for the tokens); a defeated Red Rider leaves the table (the bot's go to the dead spot, the human's: the chat asks to remove them) and a returned one is put back.
- [ ] **KING OF THE WILD HUNT (H)**: when your last Red Rider falls the chat says nothing special but every card of yours is worth +1 ("KING OF THE WILD HUNT (+1)" in the combat line) and the Maneuver may go 3 spaces. **(B)**: the bot's Eredin walks 3 once all four Riders are gone and its cards carry the +1; a Rider returned by Unyielding Hordes ends it.
- [ ] **Icy Guile (H)**: Yes / No, then four buttons named after the miniatures (Maxwell, Aleksei, Adrian, Norman); the chosen one is defeated, the bot's card value goes to 0 and the chat tells you to remove the miniature. **(B)**: the bot pays a Rider only when it matters and its miniature goes to the dead spot.
- [ ] **Foul Purpose (H)**: enraged, name any fighter (even one far away) and play it face up: the bot's defense is chosen seeing it; not enraged, a far target is refused. After the combat Yes / No: defeat a Rider and the card goes back to your hand. **(B)**: the bot flips it face up on the table when the target is out of its reach.
- [ ] **Implacable (H)**: not enraged, put it as an attack and the Reveal refuses it ("Carta ilegal"); enraged it attacks, with its free BOOST offered. As a defense it works as usual.
- [ ] **Portal Defense (H)**: defending with a Rider next to Eredin, the chat says to swap the two miniatures by hand and the Rider takes the blow; the damage never reaches Eredin. With nobody adjacent Eredin defends. Enraged, you draw 2 afterwards. **(B)**: the bot swaps its own pieces.
- [ ] **Unyielding Hordes (H)**: played by a Red Rider; a fallen Rider comes back where you place it (the chat asks you to place it; count it next to the opposing fighter for the +1). **(B)**: the bot places the returned token itself.
- [ ] **Backhand (H)**: the bot puts one random card of its hand on top of its deck (the chat says it, the real deck gets it on top, not shuffled); enraged it discards it. **(B)**: the chat tells you to put one random card of your hand on top of your deck (or in your discard when he is enraged); the card number from the left is given.
- [ ] **Might Of The Aen Elle (H)**: draw 1, one action back, the card stays in your ONGOING zone; effect damage to Eredin (e.g. the bot's Horseshoes, Wild-Hunt-like effects) does nothing, combat damage does; at the end of a turn with no attack it leaves play. **(B)**: the bot's copy goes to its ONGOING zone and leaves at the right time.
- [ ] **Close For The Kill (H)**: draw 2, the chat lists a move of up to 3 for each of your fighters (through opposing fighters). **(B)**: the bot moves each of its pieces.
- [ ] **Wild Hunt (H/B)**: every opposing fighter next to one of yours takes 1 (2 enraged); the dials follow.
- [ ] Brutal Strike (cannot be cancelled; ignores a rival card whose text says IMMEDIATELY), Skirmish (as Bigfoot's) and the numbers as printed.
### Sinbad (Battle of Legends, Volume One, with The Porter)

Nothing of Sinbad has been seen on a real table. His deck is sheet 176 like Medusa's, the turtles', Doctor Strange's, Bigfoot's and the Tales to Amaze decks': the first things to check are the detection, the Porter's token and the Voyages dial.
- [ ] **Detection (auto)**: with his deck at one spot and any other hero's at the other (any deck of sheet 176 included), the start-up line names Sinbad; the bag `6e6722` holds a deck of 31 cards (character card 303).
- [ ] **Pieces**: Sinbad's miniature `ff509a` and dial `c48fac` (15), The Porter's token `36ccb4` (a Custom_Token: check it is found as a piece, like Daisy) and dial `7859ab` (6) are found; both life dials follow the engine.
- [ ] **The Voyages dial `10bbcb`** (a counter 0-7, `MAX_VALUE 7`) comes out of the inner bag with his other objects and is laid on a counter-dial slot (or reported as unplaced). The bot does NOT write it: set it by hand if you like (open question 4 of docs/heroes/sinbad.md).
- [ ] **The Maneuver reach (H)**: put VOYAGE cards on your discard pile and press Maneuver: the chat says "VOYAGE: your fighters may move up to +N spaces" with N the VOYAGE cards on the pile; moving Sinbad and The Porter that far is accepted. **(B)**: with VOYAGE cards in the bot's pile its Sinbad (and the Porter) walk farther in a Maneuver than 2 spaces.
- [ ] **VOYAGE value (H)**: attack with a VOYAGE card with N other VOYAGE cards on your discard pile: the combat line shows 2 + N. **(B)**: the bot's VOYAGE card is worth the same (the chat line shows the total).
- [ ] **Voyage Home (H)**: after the combat the bot moves the other VOYAGE cards from your discard pile into your hand (one script per card, by GUID, CardID and your deck's image) and says so; a card it cannot move is left for you to pick up. **(B)**: the bot takes its own VOYAGE cards from its pile back to its hand and says so.
- [ ] **Creature (H)**: the bot discards a random card and the pile follows. **(B)**: the chat names the position of your hand to discard (counting from the left) and you discard it by hand.
- [ ] **Giant Snakes (H)**: the chat shows the bot's hand. **(B)**: the bot reads your hand once.
- [ ] **Man-Eating Apes / Whale (H and B)**: the rival's dial drops by 2 / Sinbad's dial goes up by 2 (never above 15).
- [ ] **Cannibals, Toil and Danger (H)**: the chat tells you to move Sinbad up to 2 / 3 spaces by hand and End action reads it. **Leap Away (H)**: the panel asks which fighter of the combat; for the bot's piece you move it where the bot says (up to 4).
- [ ] **Serendib, Exploit, Regroup, By Fortune and Fate, Riches Beyond Compare (H)**: the bot deals 1 / 1 / 1-2 / 2 / 3 cards to your seat. **Momentous Shift**: 5 after your fighter moved this turn.
### Yennefer & Triss (The Witcher: Realms Fall; one hero, one sidekick, two variants)

Nothing of Yennefer & Triss has been seen on a real table. The deck is sheet 176 like Medusa's and ten more, and both variants share one bag (`2b339c`, inner `eaf05e`) and one deck (`7b2a33`, 32 cards: the 30 plus the character cards 351 Yennefer and 352 Triss). Variant `yennefer-triss`: hero miniature `cd27f6` (dial `d4701d`, 14), sidekick token `905f88` (Triss, dial `00da50`, 6). Variant `triss-yennefer`: hero miniature `d1b3b9` (dial `799107`, 14), sidekick token `de2677` (Yennefer, dial `4dbc76`, 6). **Check first what the savegame objects really are**: the save has two separate single-faced sidekick tokens, Iván describes one double-sided token.
- [ ] **Detection**: take ONE hero miniature out of the bag (the chosen heroine's) next to the deck: the start-up line names Yennefer (`yennefer-triss`) or Triss (`triss-yennefer`); with no hero miniature out, or both, the start-up refuses with `hero.variant_unclear` (use `--bot-hero` / `--human-hero` with the slug). The pre-game gate (Preparar) does not know the variants yet.
- [ ] **Pieces and dials**: the hero miniature and its 14 dial, the sidekick token and its 6 dial are found for both variants and both seats; the dial that is not used stays in the bag.
- [ ] **SORCERESS OF VENGERBERG (H, hero Yennefer)**: every attack of Yennefer (any card) stops at Reveal with "<card> revelado: si quieres potenciar", you put a card in your discard and press Boost (or No boost); her sidekick Triss never gets it; with Triss as the hero nobody has it; the bot's card cancelling effects (Feint, Telepathy) does not remove the question. **(B)**: the bot boosts Yennefer's attacks with a card it can spare.
- [ ] **MERIGOLD THE FEARLESS (H, hero Triss)**: after you play any scheme the chat says 2 damage to a fighter adjacent to Triss (the panel asks which when several; one adjacent: at once) and the dial follows; it can hit your own Yennefer if she is the only one adjacent. **(B)**: the bot picks a rival fighter.
- [ ] **Advisor to the king**: every own fighter heals 1, you draw 1; while it is in play your BOOST values (Maneuver and combat) are +1; at the end of your turn it goes to the pile if none of your fighters attacked, else it stays; the ONGOING spot shows it.
- [ ] **Lodge of sorceresses (H)**: the panel asks which card you reveal (one button per title), then the bot's revealed card is shown face up; both draw that card's BOOST (you draw by hand: the chat says how many) and the one who drew most (both on a tie) takes that much damage to their hero. **(B)**: the bot's card is shown and you are asked.
- [ ] **Merigold's Hailstorm**: the opponent chooses (the panel asks you when the bot plays it): discard 2 (you discard by hand), 3 damage to your hero, or the top 4 cards of your deck (one button, the bot moves your four real top cards to your pile, face up).
- [ ] **Echoing blast (B)**: when the bot's attack wins the card goes from its combat spot back to the bot's hand; **(H)** when yours wins you take it back to your hand (the chat says it).
- [ ] Incinerate (the bot decides whether to pay 2 cards), Portal to anywhere (any fighter of the combat, then an action), Telepathy, Quick and ready (their zone), Ball lightning, Paralyzing fetters, Magical barrier and the numbers as printed.

### Hidden information (cards that look at the bot's hand, and the bot's on you)
- [ ] **The bot's hand row**: when playing Confront Any Demon or God (only if you lose), Advanced Psychometry (adjacent), Remove A Painful Memory (with an ONGOING) or Every Possible Angle, the bot lays its hand **face up in a row** at `bot_row_spot` and **pings** each card (`ping_points`). The **Look at bot's hand** button uses another row, at `look_spot`.
- [ ] **The bot's own pings do not choose for you** (9335eab): with the row open, the bot does not "choose" a card by itself. *(31/10 failure with Remove A Painful Memory: it chose Posthumous Power within 1 s; fixed, still to be seen. If it happens again, widen `BOT_PING_WINDOW`.)*
- [ ] Reading your hand happens **only once per look** (one `read_hand` message), only when a card of the bot looks at you; otherwise, never.
- [ ] **Choose by ping** (Tab on the card, `onPlayerPing`) **or by panel button** (the buttons name the card). Expected: Confront -> to its discard; the rest return to its hand. Plan B: one face-down card + End action.
- [ ] **Every Possible Angle**: the chosen card goes **on top of the deck** of the bot (`putObject` on the deck, same turn); also try with the deck at 1 card.
- [ ] **Look only** (Reveal): closes with End action or Cancel (everything to the hand); a ping is rejected.
- [ ] **Remove A Painful Memory**: yours -> the bot says "discards X" / "keeps X" and the summary does not say "draws -1"; the bot's -> buttons "Discard <card>" / "Take 2".
- [ ] **Perfect Shot**: B places, **turns face up** in the same script and announces the prediction. H: at **Reveal** **Value 0..7** appear (+ "More" -> **Face down**, second page) before the bot defends; face up is public and the bot knows it.
- [ ] **UNCANNY INTUITION**: B attacks -> face-down card that is **turned** face up in the same script, named in the chat. H attacks the bot's Abe -> the chat warns on Attack; at Reveal the bot spends the token and draws **before** choosing a defense (the drawn card may be the defense); put the attack face down (it is turned at Reveal).
- [ ] Partial failure (one card does not move): the row stays, the bot says so once and you choose by button; the table wins on the next read.

### Official save set-up (F20)
Nothing of this has been seen on a real table. Load "Unmatched Official Tournament Table October 2026 (Hellboy)" (no discard zones, loose decks / d20 / Dice Cannon / clocks) and start the bot.
- [ ] **Zones created**: the chat says the bot and human discard zones were created (with a GUID); the white floor rectangles appear where the hand-made ones were (bot x 10.7..19.3, human x -18..-7), straight along z, and the bot's discard grid fills its zone from the first discard.
- [ ] **Size honoured**: select a created zone with the zone tool: scale about 35.4 x 5.1 x 8.5 (bot) and 33.2 x 5.1 x 11.0 (human), rotation 0 / 270 / 0. If the scale is 1 x 1 x 1, `spawnObject` dropped it and `setScale` did not help.
- [ ] **Pre-sparring save**: on "Unmatched Sparring Bot Base" the bot says it straightened both zones (269.09 / 269.43 -> 270) and creates nothing; start the bot a second time: it says nothing (already straight).
- [ ] **Table cleaned**: the two decks, the d20, the Dice Cannon (locked) and the two digital clocks disappear, one chat line each; the two hand cards counters (White's and Green's), the hand zones and the board stay, and the B.P.R.D. HQ board can be placed in the centre. Also on the pre-sparring save the two clocks (z 27.2) go; the template Digital_Clock in the Timers bag is not touched. A `--resume` removes nothing; a second fresh start finds nothing to remove and says nothing. Loading the save again brings the objects back (the file is untouched).
- [ ] **Resume**: Ctrl+C, then `--resume`: the same created zones are used (no third zone appears), the objects in the centre are not touched, the discards already on the pile are still read.
- [ ] **Fresh restart without reloading TTS**: the leftover created zones are reused (no duplicate zone on top of them).
- [ ] **TTS reload after creating the zones** (load another save): the bot stops with the missing-GUID message; restart it.

### Pre-game gate: check, clean and prepare the table (F22; partly superseded by F23 above)
Nothing of this has been seen on a real table. The definition of a ready table is the docstring of `sparring/table_reset.py`. Start the bot (fresh, not `--resume`) on a table left in a game, then on the official save.
- [ ] **THE MAIN CASE: the official tournament save, just loaded** (nothing prepared, no map out). Start the bot: it does NOT stop on "no map"; the chat says the table is not ready and lists: loose objects (the six GUIDs), no map, discard zones missing, Medusa and Hellboy in their bags. Press the button: the six centre objects disappear (decks, d20, Dice Cannon, clocks), two discard zones appear (straight, rotation 0/270/0), the B.P.R.D. HQ map is laid on the pad board in the middle (check it sits where it did in earlier games: the deck spots, discard grid and combat spots fall on it), Medusa's and Hellboy's decks, dials, pieces and tokens come out of their bags (decks at the deck spots, pieces and dials in the unpack rows or at the dead spots, none on the map), no hand is dealt. Everything else stays: all hero and map bags, counters, hand zones, pad boards. The chat ends with "prepare the table ... and press Comenzar partida".
- [ ] **Infinite bags (learned live, 4/11)**: `getObjects()` of an infinite bag does NOT list its content, so nothing may require the GUID to be listed: the map bag and the heroes' outer bags are asked with `takeObject` WITHOUT a GUID (a copy of the single object), the copy arrives later and the script finishes and answers in `callback_function` (the map: scale, lock, GM notes `sparring-map`, must be a `Board`; the inner hero bag: must be a `Bag`). Check: one press lays the map and unpacks both heroes, no loose copy is left, a second press reuses what is there. If the chat says "No he podido sacar el mapa ... (bag/board/take/spawning)", copy the reason.
- [ ] **No map on the table**: the audit never fails on it (pieces read answers `no_board`, every piece counts as off the board); one failing side read (pieces, dials, tokens) no longer kills the audit. The console shows ONE short line ("Aun no he leido el mapa ni los heroes") instead of the two start-up read errors, and no old "faltan en la mesa ... el bot no saca nada de una bolsa infinita" warning.
- [ ] **Heroes emptied by hand anywhere**: dump both inner bags on the table in clusters away from the deck spots. The audit says the deck is "en la mesa pero fuera de su sitio" (never "en la bolsa"); one press brings each deck (a Deck with a new GUID, face up or face down, plus loose cards) face down and shuffled to its deck spot, pieces and dials to the dead spots; a failure names the button of the gate ("Limpiar mesa y preparar"), not "Reiniciar partida".
- [ ] **Buttons**: the right panel shows only "Limpiar mesa y preparar" (table not ready) or only "Comenzar partida" (ready), no game button; the labels fit; in a normal game both are hidden. They sit beside Mulligan and Ready.
- [ ] **Panel timing**: the first status line and buttons appear (`PANEL_SETTLE` 0.7 s after creating the panel is enough; if the buttons stay as in the XML, raise it).
- [ ] **Chat**: a dirty table lists what is out of place, briefly; a ready one says so; both end with "prepare the table with the heroes and map and press Comenzar partida".
- [ ] **Cleaning from a mid-game table**: hands, discards, combat cards, ONGOING cards, the look row and a zoom copy are gone; every card of Medusa and Hellboy is back in its own deck (30 cards each, face down, shuffled, at the deck spot, also a deck left face up); cards dropped loose on the board come back too; nothing of other card games moves.
- [ ] **Pieces and dials**: miniatures end at the dead spots (not on the board), life dials full, destiny 0, Hellboy's miniature in his first form (OCCULT DETECTIVE) with the ability token at rotZ 180.
- [ ] **Abe's Intuition tokens** (only if Abe was on the table when pressing): they end inactive; see the Abe item for which rotation is which.
- [ ] **Leftovers**: the six objects of the official save are destroyed only if their `o.name` matches (F20); one that does not match is named in the chat and left alone.
- [ ] **Bags**: with Medusa and Hellboy still in their infinite bags (nicknames "Medusa" and "Hellboy") the button first takes each inner bag (e5a45c, c592d8) out of the infinite one with `takeObject` (a copy, possibly with another GUID; the bot uses the object it got and destroys it once empty), then their deck, pieces, dials and token out of it. The infinite bag spawns the copy later, so the script waits for `takeObject`'s callback, takes the items out of the copy there and answers from the callback (up to 4 s): ONE press must unpack both heroes with no timeout message and no loose bag copy left on the table. If a press says the inner bag "aun se estaba creando", note it: the copy it left is reused by the next press (check that no second copy appears). If TTS refuses, the chat says which hero and how to do it by hand ("A mano: ..."), and the button stays.
- [ ] **Another pair on the table** (e.g. Houdini and Strange): their cards go back to their decks and miniatures off the board, nothing is unpacked over their decks, and the chat asks to put them in their bags and press again.
- [ ] **Saved game**: after cleaning `state/session.json` is gone, so `--resume` finds nothing.
- [ ] **Second press** changes nothing and says so; a table the bot cannot fully clean names what is left and keeps the button.
- [ ] **Start game**: nothing is dealt or placed before the press; the press reads the heroes and the map from the table and the normal flow starts (deal, mulligan, placement).

### The player sets the table: Clean table, drag, Prepare, calibrate (F23)
Replaces the single button of F22 below (its items about unpacking from the infinite bags no longer apply: the player drags the copies). Nothing of this has been seen on a real table. Start the bot (fresh, not `--resume`) on the official save.
- [ ] **Buttons**: the right panel shows "Limpiar mesa" and "Preparar" (and "Comenzar partida" once ready), the captions fit, none shows in a game.
- [ ] **Clean table** on a table left in a game: every hero object and the map disappear (also cards in hands and the character cards); the six leftovers of the save go; the roster of infinite bags and the pads stay; the chat says how many objects were removed and asks you to drag the map and the heroes.
- [ ] **What dragging gives**: drag Medusa's bag from the roster. It is a Bag copy; Prepare must recognise it (Bot: Medusa). Note its GUID and whether the items inside keep the GUIDs of `data/tts/medusa.json`.
- [ ] **Closed bags**: map + Medusa's bag on the +x half + Hellboy's bag on the -x half, then Prepare: chat "Bot: Medusa, Tu: Hellboy, Mapa: ..."; the map goes to its calibrated transform; everything lands on the slots; the empty bag copies are gone.
- [ ] **Opened contents**: same, but open the bags and spread the contents by hand first: same result, nothing duplicated.
- [ ] **Swapped halves and other heroes**: Hellboy on the bot's side, Medusa on yours; then a pair like Bigfoot and Houdini on another map.
- [ ] **Refusals**: both heroes on one half; no map; the same hero twice; a hero the bot cannot play (e.g. Blackbeard): each is named in the chat and nothing moves.
- [ ] **Uncalibrated map** (any map but B.P.R.D. HQ): the map stays as dropped, the chat prints `python -m sparring.calibrate --map <key>`.
- [ ] **Calibrate**: arrange a map and both heroes by hand, close the bot, run that command. `config\map_setups.json` gets the entry; clean the table, drag the same things again and Prepare: they land where you had put them. Check `--dry-run` writes nothing.
- [ ] **In game**: after Prepare and Start game the bot finds both decks (draws, discards) on that map.

### Maps of the official save (F21)
Nothing of this has been seen on a real table. Load the official save, take a map out of its bag in the map area and put it on the table, then start the bot (or run `--read-only`).
- [ ] **TTS returns what the script reads**: `o.type` of a loose Custom_Board is `Board`, and `getCustomObject().image` is the image URL whose last 40 hex characters are the SHA-1 in `data/maps/catalog.json` (the script reads `guid` and `image` of every `Board`; if the report says "image ?" the URL has another shape).
- [ ] **A board with a new GUID is found**: with B.P.R.D. HQ taken out of its bag, the console says "Map on the table: B.P.R.D. Headquarters", `--read-only` lists the new GUID as the board, and the miniatures are placed on the right spaces (it used to crash with `board.positionToWorld` on nil).
- [ ] **Each map you confirmed in `tools\map_checker.py`**: take it out, start with `--read-only`, then play a few turns: miniatures land on the circles, the start spaces 1 and 2 are the diamonds numbered 1 and 2, a move and an attack respect the connectors; note any wrong edge or zone (map and space ids).
- [ ] **Refusals**: an excluded map (Navy Pier, Heorot), an unverified one (Yukon), an unavailable one (Venice) and two maps at once each stop the start-up with a message that names the map and lists the supported ones, and nothing on the table is touched.
- [ ] **The table's own decorative boards** (the locked pad board 6bd0e3 and the small Phone Booth / Bathroom Stall boards if you pull them out) do not stop the start-up while one map is on the table.
- [ ] **Resume** on another map than the saved game is rejected by the table identity check.

## 4. Panel and buttons

- [x] The choice buttons of a card **only appear when it is played** (hidden, **never greyed out**). *(OK 30/10)*
- [x] The labels change (`UI.setValue` on a Button): "Value 3", "Discard X", "Take 2". If they do not update, note it (**verify live** item). *(OK 29/10)*
- [ ] **New game** (pressed twice within 3 s) mid-game and at game over: the panel goes back to Clean / Prepare / Start; a different map and heroes are detected and the new game starts. At game over check that "Undo game over" and "New game" both fit in their shared row.
- [ ] **Cancel** during a combat pause: it works; if every option is rejected and you cannot get out, note which (the way out is Restart).
- [ ] **Blocked** restrictions (not just warned): Pact Of Freedom, Cold Iron (if you draw physically anyway, the bot accepts it when syncing and says so).
- [ ] Maneuver with BOOST 0 (Liz's burning card): it should warn in the chat (pending item; if it does not warn, note it).
- [ ] **Look at bot's hand**: **hidden** unless a card allows it; it spends no action.
- [ ] 0/1/2, "None", Yes/No, Value 0..7: no button is left half-done after a double click.

## 5. Saving and resuming

For each case: Ctrl+C (and reload TTS if you like), then `--resume`. Expected: nothing repeats or is announced again; the panel returns to the same point.
- [ ] In the middle of a **combat pause** (waiting for Reveal or an effect button).
- [ ] Pause after the bot moved/boosted in the middle of a combat (projection -> resume path; **no test**).
- [x] In the middle of a **scheme** waiting for your answer (Pact Of Secrecy, Pancakes!, Posthumous Power) **(E2)**. *(OK 30/10: resume mid-scheme, line 71)*
- [ ] In the middle of a **hidden-information row** (`look_spot`): the row comes back and the mode notice (`pick` / `reveal`) is repeated.
- [ ] In the middle of Perfect Shot (prediction buttons) and of FATEFUL BARGAINS **(E2)**.
- [ ] After a turn change with Wildfire pending.
- [ ] A foreign/old/other-table save: `--resume` rejects it with a clear message.
- [ ] In the middle of the pause between two AFTERs (after your Glimpse, before Fleeting) and in the middle of a discard with a pending draw: nothing repeats and the owed card arrives once.
- [x] A save from before the bot's Destiny Dial was configured: `--resume` accepts it. *(OK 31/10)*
- [ ] **Language kept (1/11)**: start a game with `language: "es"`, Ctrl+C, then `--resume` without `--language`: panel, chat and console stay in Spanish. `--resume --language en` warns (console) that lines already saved may stay in Spanish and then speaks English.

## 6. TTS bridge (primitives never seen on a real table)

Note OK / failure and what happened. A projection failure is said **once** ("do it yourself"); there is no retry.
- [ ] `card_to_deck_bottom`: card from the bot's discard goes **to the bottom** of the deck (the bot's Pancakes!).
- [ ] `shuffle_into_deck`: card(s) from the discard to the deck and shuffle.
- [ ] `hand_to_deck`: card from the bot's hand to the deck (`putObject` straight from the hand zone; "bottom" = turned deck).
- [ ] `return_card_to_hand`: card from the discard (or from the combat, when cancelling) returns to the bot's hand.
- [ ] `move_piece`: the bot moves a **miniature of yours** by effect (by GUID); if it fails it says "move it yourself".
- [ ] **Phase 2 translators (1/11)**: what the bot already did by effect now comes from a registry of translators (`session_translators`) and the cards say how (`return_to_deck` with position, `put_in_hand`, `search_deck`, `counter`, `form`, `ongoing`, and `place` / `swap` / `revive` / `summon` of **your** miniatures with the same `move_piece`). It must look **the same as before**; note any card whose effect on the table changes: Glimpse Of Hell / Pyrotechnics (bot's hand -> bottom of the deck), the bot's Rekindle / Pancakes! (discard -> deck), Ward And Prepare, Pact Of Freedom (`place` of your miniature), a swap of spaces, Abe (tokens) and Hellboy (form).
- [ ] **Crown Of Flame without checking the title (1/11)**: the bot still discards **your whole hand** by itself (the whole-hand discard is marked by the effect itself, `pick: all`); if the table rejects it, it says "I could not discard your hand" and asks you to discard it by hand.
- [ ] `set_state` + `flip_token` + `ping_objects` (Hellboy) and `take_token_copy` / `remove_token` (Abe): see section 3.
- [ ] `onPlayerPing` reaches the panel script with your seat and the expected object (if TTS gives no object, the row card within 1.6 is used).
- [ ] `read_hand` of your seat: one message per look; the bot never reads your hand outside a look.
- [ ] Card face up right after placing it (`play_card_face_down` + turn in the same script): it looks as you expect.
- [ ] Messages and latency (`--timing`): normal button ~1 message; Liz's turn with Wildfire +1; a look +1. Note any button that takes more than a few seconds.
- [ ] Slow-TTS warnings: if "TTS returned no value (it is busy, paused or reloading...)" shows up, note the time and what you were doing (568c6bf: it now waits 8 s more before warning).
- [ ] verify_live: a whole game with `language: "en"` (or `--language en`): setup and mulligan, a turn of yours (Maneuver, Scheme, attack with Reveal, Continue / No boost, End action, +1 / -1, Look at bot's hand) and a bot turn (attack, defense, Wildfire / ANUNG if Liz or Hellboy plays). Panel: buttons and status line in English and not cut off (90 characters at most). Chat: no sentence in Spanish (TTS warnings that arrive with their own technical error text do not count); card titles and hero names stay as printed. Note any phrase that sounds odd or comes out in Spanish. The console of `play.py` (stderr, `--help`, the `hero_detect` report, start-up configuration / save errors) now follows the language too.

- [ ] **Piece identity, Abe Sapien vs Donatello (1/11)**: both miniatures share GUID `4fdf31` in the data. Play Abe vs Donatello (and the reverse): take both heroes out of their bags and start. The console/chat says ONE `piece.resolved` line naming the hero whose miniature got a new GUID, plus the `piece.shared` warning; each miniature moves on its own, attacks reach, nobody sits on the other's space. Ctrl+C, `--resume`: no new resolution line and the same pieces are followed. If one miniature is still in its bag, you read `piece.unresolved` once and no more.

- [ ] **Card zoom (`card_zoom`, never seen live)**: the bot's combat card when revealed (or discarded without a flip), its schemes, its ONGOING placed face up and the card Wildfire discards each show a BIG copy of the card. Check: (a) it appears WITH the reveal, after the chat announce and not before; (b) size (`card_zoom_scale` 4) and height (`card_zoom_spot` y 12) are readable from the White seat without covering the panel or the dials; (c) rotation: upright and not mirrored from the human seat (flat, same turn as the look row); if it needs to lean toward the camera, set `card_zoom_rot` with an x tilt and note the value; (d) it disappears by itself after `card_zoom_seconds` (6) and a second card replaces the first (never two at once); (e) the copy is locked and cannot be picked up, hovered or put in a hand (`interactable = false`); (f) it is never taken for a card: hands, discards, the combat count and the next snapshot are right while it floats, and `--read-only` / the hero detection do not see an extra card; (g) the real card did not move or flip because of it; (h) `--no-card-zoom` and `"card_zoom": false` turn it off; (i) no extra TTS message per card (`--timing`). If `spawnObjectData` with the card's `getData()` renders a blank face, note it: the face URL comes from the card's own CustomDeck (copied under key 999).
- [ ] **Game-over dialog**: when a hero falls (combat, +1/-1 to 0, Remove), a modal appears in the middle of the human's screen (`human_seat`): "You win! <hero> has fallen." or "The bot wins: <hero> has fallen." (Spanish with `language: "es"`), once only; the chat/broadcast lines stay; Undo game over and a new fall shows it again. If the dialog never shows, the game still ends normally (it fails silently).
- [ ] **Human Abe: Intuition tokens (3/11)**: with Abe as the human the chat says the engine's count at start/resume ("Abe Sapien has N of 2 Intuition tokens active"). Then, verify_live in real TTS: (a) activate: Abe deals combat damage to an adjacent fighter -> the bot turns one Intuition token to its ACTIVE face (green with yellow stripes), pings it, and the chat says "I turned 1 token to the active side and pinged the spot" with the count; (b) spend: the bot attacks Abe with a token active -> BEFORE you choose a defense the chat says the token is spent, one token is turned back to the dark face and pinged, you were dealt 1 card (it can be your defense) and the bot's attack is face up; the summary line says "the attack is played face up", not "you look at the bot's hand"; (c) the tokens are found by the nickname "Intuition Token" (or GUID 5a17e9). The two tokens may be ONE stack (Custom_Token_Stack, Number 2): the bot takes one out with takeObject so the other keeps its face. Check that a stack of 2 is split correctly and that a second flip finds the loose token, AND that a token taken out of the stack with takeObject still shows the green/yellow face when turned: the back image is a glued ChildObject (b75787) of the stack and may not travel with the token (if it shows blank/dark on both sides, split the stack another way or ask the human to take the tokens out first); (d) which Z rotation is which face: `data/tts/abe-sapien.json` `token_faces.intuition.faces` says inactive 0 / active 180, INFERRED from the save (the stack rests at rotZ 0 in its start state); if the bot turns the wrong way, swap the two numbers; (e) mismatch: turn a token by hand (engine says 0 active, table shows 1) and trigger an activation: the chat warns "the table shows 1 active ... I counted 0" and keeps the engine's count; (f) fallback: hide/remove the tokens and trigger one: the chat asks you to flip the token yourself and says why.
- [ ] **Blind reorder success line (8/11)**: after a REAL reorder of the human's deck (Golden Bat's Sight Beyond Sight, Jill's Insightful Deduction played by the bot) the chat must show the "he reordenado ..." success line, never the failure one. `check()` relies on `getData` reflecting the `putObject` calls made in the same frame; if the failure line shows although the deck was reordered, that assumption is wrong on the real TTS. Also press End action a few times afterwards: no card the bot read is ever named.
- [ ] **Revealed cards large (Ivan, 2026-11-08, `reveal_display`, never seen live)**: Jill's Hypnoray Blaster / Battle of Wits / Insightful Deduction, Strange's No, Really, I'm a Doctor and Houdini's A Magician Never Reveals His Secrets lay a LARGE face-up copy of each revealed card in a row over the board (estimate `reveal_spot` [0, 14, 0], scale 2.5, 6.2 apart: calibrate; they must not hide the panel nor sit inside a zone). They stay until you press **Dejar de revelar** (the button exists only then); a second reveal replaces them; the copies are locked, cannot be grabbed and are never read as cards (draw, discard, hand reads still right). Insightful Deduction: the three appear before you choose and stay while the bot reorders your deck (the order of the copies is the original one). New game, Restart, Clean table and `--resume` leave no copy. Sight Beyond Sight shows nothing.
- [ ] **Insight of the Ancients moves the card itself (Ivan, 2026-11-08, `pile_card_to_hand`, never seen live)**: with Golden Bat as the human, win a combat with Insight (with 2 or more cards on your discard pile, then with exactly 1 and a pile of 2 cards, to see a stacked pile dissolve). The chat says "Tu carta: Insight of the Ancients: X vuelve a tu mano" and then "He puesto X de tu descarte en tu mano."; the card X leaves your REAL discard pile and shows up in your White hand (check it really joins the hand zone, face up to you, and does not stay lying on the table near the hand: the move is `setRotation` + `setPosition` to `getHandTransform`, the same as `return_card_to_hand`, not `deal`). Press End action: no "Aun no veo...", no extra card named, the hand count is right. Then make it fail (put X somewhere else first, e.g. in your hand): the old line "Recoge X de tu descarte a tu mano (efectos del combate)" shows instead. Make sure a card YOU pick (Ward And Prepare as Abe) still shows "Recoge ..." and the bot does not move it.

## 7. What to note if something fails

For each failure:
- [ ] What you were doing (hero, side H/B, card, moment, button), what you expected and what happened.
- [ ] The bot's **chat lines** and the terminal output (with the traceback if any).
- [ ] `state\session.json` (or `estado\sesion.json` for an old game) **right after** the failure (before playing on); the TTS save if the table was left odd.
- [ ] Screenshot of the table and the panel.
- [ ] The `--read-only` report (detection/calibration) or the `--timing` output (latency).
- [ ] If you reloaded: with or without `--resume`; and remember you have the "pre-sparring" save.
