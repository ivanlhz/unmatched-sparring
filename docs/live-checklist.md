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
- [ ] **Cowabunga!!** counts the cards played this turn (including the defenses on the rival's turn).

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
- [ ] **BLIND BOOST (H)**: playing Bolts of Balthakk or Seven Suns the chat asks you to put the top card(s) of your deck on your discard pile and press Done (up to 1 / 2): the chat counts them and the combat shows the boosted value; more than allowed is refused; Done with nothing is no boost; Seven Suns over 7 counts 0. **(B)**: the bot discards the top card of its deck for the boost (the card reaches its discard grid).
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

## 4. Panel and buttons

- [x] The choice buttons of a card **only appear when it is played** (hidden, **never greyed out**). *(OK 30/10)*
- [x] The labels change (`UI.setValue` on a Button): "Value 3", "Discard X", "Take 2". If they do not update, note it (**verify live** item). *(OK 29/10)*
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

## 7. What to note if something fails

For each failure:
- [ ] What you were doing (hero, side H/B, card, moment, button), what you expected and what happened.
- [ ] The bot's **chat lines** and the terminal output (with the traceback if any).
- [ ] `state\session.json` (or `estado\sesion.json` for an old game) **right after** the failure (before playing on); the TTS save if the table was left odd.
- [ ] Screenshot of the table and the panel.
- [ ] The `--read-only` report (detection/calibration) or the `--timing` output (latency).
- [ ] If you reloaded: with or without `--resume`; and remember you have the "pre-sparring" save.
