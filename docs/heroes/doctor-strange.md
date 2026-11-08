# Doctor Strange (Marvel, Brains and Brawn)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 337 on sheet 3) on 2026-11-02.

## Summary
- Ranged hero, 14 life, move 2. Sidekick **Wong**: one, ranged, 6 life, move 2 (fid `wong`). Hero fid `strange`.
- Ability **DARK PACT**: after each combat, if Doctor Strange played a card, you may deal 1 damage to him. If you do, put that card on the bottom of your deck and draw 1 card.
- Deck: 30 cards, `CardID = 17600 + idx`, restriction bands DOCTOR STRANGE, WONG and ANY. The deck object in the save holds 31 cards (the 30 plus the character card 337), hence `card_count 31` in the catalog (`card_ids [337, 17629]` there is the min and max of those 31).
- Table: miniature `bb001d`, life dial `d95e8b` (max 14); Wong's token `9256f2` and dial `02474c` (max 6). No piece GUID is shared with another hero.

## Card identity: the shared CardID range
His deck is sheet 176 like Medusa's and the four turtles': the same CardIDs 17600-17629, a different image (`data/tts/doctor-strange.json`, `deck.identity`). Nothing in the code reads a card by a bare CardID (docs/card-identity.md):

- **Engine and session**: a `Card` is a frozen value (title, restriction, numbers and text differ), so `==` and `in` never confuse decks; every lookup goes through `Game.card_of(id, owner)` / `Game.cards_by_id(owner)` / `players[side].full_set`. The new code follows it: the plugins take cards from `game.players[owner]`, `session_rage` resolves what the table reports against the human's `full_set`, `ChoiceRequest.card_owner` names whose deck a request is about.
- **Table**: every Lua builder that moves a Strange card (`card_to_deck_bottom`, `card_to_deck_top`, `card_to_discard`, `return_hand_to_deck`, `shuffle_deck`) gets the side's `id_range` AND its `identity`, so a card of Medusa's or a turtle's with the same CardID is never taken. Detection (`hero_detect`) and `hero_table.table_defaults` use range plus image and refuse two decks with the same images.
- **Proof**: `tests/test_hero_doctor_strange_data.py` (ranges equal, images disjoint from Medusa's and each turtle's, no card equal across decks, `is_medusa_card` false for all 30, detection in both seats against all nine, catalog entry, no shared piece GUID), `tests/test_card_identity.py` (Strange is in `SHARING`) and `tests/test_doctor_strange_matrix.py` (Strange against each of the nine heroes in both seats, passive and attacking human, plus headless games).

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Who | Effect |
|---|---|---|---|---|---|---|
| The Winds of Watoomb | attack | 4 | 1 | 3 | Strange | AFTER: the rival places Strange in a starting space; you place the opposing fighter in another one; all decks are shuffled |
| The Rings of Raggadorr | attack | 4 | 1 | 3 | any | AFTER: if you won, your fighter and each friendly fighter next to it recover the damage dealt |
| Bolts of Balthakk | attack | 2 | 3 | 4 | any | DURING: you may BLIND BOOST (1): declare 0 or 1. AFTER: if you won, gain 1 action |
| Seven Suns of Cinnibus | versatile | 3 | 2 | 3 | Strange | DURING: you may BLIND BOOST up to 2 times: declare 0, 1 or 2; a total above 7 counts for nothing |
| Cloak of Levitation | versatile | 2 | 1 | 2 | Strange | DURING: if Strange is next to the opposing fighter, ignore the value of the opponent's card |
| Feint | versatile | 2 | 1 | 2 | any | IMMEDIATELY: cancel all effects on the opponent's card |
| Master of Kamar-Taj | versatile | 2 | 2 | 3 | any | DURING: if Strange and Wong are adjacent, the value is 4 |
| Steadfast Disciple | versatile | 2 | 2 | 3 | Wong | AFTER: if Wong is next to the opposing fighter, 1 damage to it and draw 1 |
| The Mists of Munnopor | defense | 2 | 2 | 3 | Strange | IMMEDIATELY: discard the opponent's card; they reveal from their deck until an attack or versatile card they can play and play it; the rest go to the bottom of their deck at random |
| No, Really, I'm a Doctor | scheme | - | 3 | 2 | Strange | Reveal a card from your hand and put it on top of your deck; Strange or a friendly fighter next to him recovers its BOOST value |
| Eye of Agamotto | scheme | - | 2 | 2 | Strange | Shuffle your hand into your deck, draw 5, gain 1 action |

## Discrepancies with unmatched-memory
- The Rings of Raggadorr: unmatched-memory carries a Black Panther text (a BOOST up to two times that draws cards). The card says "If you won the combat, your fighter and each friendly fighter adjacent to them recover health equal to the damage dealt." (`text` in the overlay).
- "No, Really, I'm a Doctor" has commas on the card (unmatched-memory has none); the overlay uses `memory_title`. Value, boost, type and copies of all 11 titles match unmatched-memory.

## Engine additions (all additive, docs/effects-dsl.md section 26)
Event `after_combat`, op `shuffle_deck`, SpaceSel `start`, Amount `combat_value`, fighter filter `is_or_adjacent_to`, `CombatFlow.replace_attack_card`, the three plugins `strange:blind_boost`, `strange:mists_of_munnopor` and `strange:reveal_to_top`, the table translators `stack_top`, `reveal_deck`, `shuffle_deck` and `hand_to_deck_all`, the pile modes of `session_rage` (`blind`, `reveal`, `play`) and, for the human's BLIND BOOST, `session_blind` with the Lua builder `deck_top_to_discard`.

## DARK PACT
A trigger on `after_combat` for `fighter: hero`: one run per card played in the combat, fired when the combat reaches DONE, after the AFTER effects, once the played cards are in their discard piles.

- **Bot**: `EffectAI._dark_pact`. It never pays when the hit point would leave Strange below `PACT_FLOOR` (4) hit points, nor when it raises the chance of dying in the rival's next turn (`MedusaAI.death_risk`: every rival that can move into reach, hitting twice against the defenses in the bot's hand) to `SURVIVAL_P` or by more than `PACT_RISK_STEP`. Otherwise it pays when the draw (an average unseen card) plus the recycled card (its keep value, weighted by how soon the deck brings it back: `PACT_RECYCLE / (deck size + 1)`) outweigh the hit point, which costs more below `PACT_COMFORT` (8) hit points. With nobody around it pays down to 6 hit points; with Hellboy next to Strange and a hand of attacks it pays only from 11. Without an opinion (any chooser that is not `EffectAI`) the answer is no (`default_answer`); a rollout of the search pays only above `PACT_SAFE_HP`. The card goes to the bottom of the bot's deck by CardID (`card_to_deck_bottom`) before the draw.
- **Human**: the buttons (Yes / No, prompt `choice.prompt.ability.dark_pact`) appear only after a combat in which Strange himself played a card, as a parked trigger the panel shows right after the combat; every other button waits and nothing is greyed otherwise. Yes: the engine pays the hit point (the dial follows) and the bot moves the card from their combat spot (the GUID read at the Reveal, `Session.combat_guids`) to the BOTTOM of their deck, then deals the draw; if the table refuses (no deck GUID, identity, a card already moved to the pile or a failed write) the chat says to put it at the bottom by hand (`strange.combat_to_bottom*`). No: nothing happens and they discard the card as usual. The parked decision is saved and survives `--resume`.

## BLIND BOOST
"BLIND BOOST this card" (rule of Iván, 2026-11-07): BEFORE any card is taken the owner DECLARES how many blind boosts: Bolts of Balthakk 0 or 1, Seven Suns of Cinnibus 0, 1 or 2. Then that many cards are discarded from the TOP of the owner's deck, face up, and their BOOST values are added automatically, together with the card's own rules (Seven Suns: a total above 7 counts for nothing). There is no stopping after seeing the first card. No card of the hand is used. A cancelled card (Feint, Break something...) has no DURING, so no blind boost. The plugin asks one `amount` request (`blind_count`) and, with no cards in the deck, asks nothing.

- **Bot**: `EffectAI._blind_boost` picks the count by expected score over the composition of its own deck (it knows it): for each count, the average score of the blow over every set of that many cards it can still turn up, minus `BLIND_COST` per card milled. A Seven Suns total above 7 scores 0, so the overshoot of count 2 weighs in before anything is seen; a tie keeps the smaller count. A rollout (`SyntheticChooser`) declares the largest count that cannot push Seven Suns over 7 (`MAX_BOOST` per card). The cards then come off the top of the deck and reach the discard pile as before.
- **Human**: the panel shows the buttons "0 / 1" (Bolts) or "0 / 1 / 2" (Seven Suns) only when the card is played; no other button is shown meanwhile and none is greyed. After the answer the BOT moves that many cards from the top of the human's physical deck to their discard pile, face up (`lua.deck_top_to_discard`, one write through the session's queue), reads their CardIDs from the result, adds their BOOST values and says in the chat what was discarded and the bonus (`blind.auto`); the combat's own line gives the new total. The engine's virtual deck gives up those cards (`table.take_from_deck`). The CardIDs go to the plugin in `run.flags["blind_cards"]` (saved with the run). The declaration is a parked choice: it survives `--resume`. If the table refuses (no deck GUID or zone, the deck is not theirs, fewer cards moved than asked) the chat says so (`blind.auto_failed`) and the plugin asks a `cards` request (`pile_mode: blind`, exactly the declared number) that tells them to lay the top cards on their discard pile and press Done; the cards the table did move already count there.
- **Short deck**: the engine has no rule for discarding from a short deck (drawing from an empty deck costs exhaustion damage, discarding does not), so the owner gets what is there: declared 2 with 1 card left discards that one; an empty deck asks nothing. CONFIRMED by Iván on 2026-11-07.

## The Mists of Munnopor
`CombatFlow.replace_attack_card`: the attacker's card is discarded (without effects) and the card the reveal finds takes its place before that side's own IMMEDIATELY, so its IMMEDIATELY, DURING and AFTER effects run as usual; the attack keeps its bonuses (`values`, hero passives). The rival must be able to play the card: attack or versatile and usable by the attacking fighter's restriction. The unplayable cards revealed go to the bottom of the deck in random order. No playable card in the whole deck: the attack has no card (value 0 plus bonuses, effects cancelled).

- **Bot as the rival**: the engine reveals its deck from the top; the chat names the revealed cards and the one it plays (`strange.reveal`, the cards are public: they are revealed); the played card is taken from the physical deck by CardID by the usual discard writes.
- **Human as the rival** (a `cards` request with `pile_mode: play`): the chat says to reveal from the top of their deck until an attack or versatile card the attacker can play, put it face up on the combat spot instead of the discarded one, put the rest at the bottom in random order and press Done. The bot reads the face-up cards of their combat spot (rows are bare CardIDs, so only ids that exist in the human's own deck are kept, the spot is the human's, and the later move by GUID re-checks the deck image in Lua), checks the new one is playable (type and restriction, with the reason if not), moves the discarded card to their discard pile by GUID if they left it there, remembers the new card's GUID and goes on. No card found: Done with nothing new. The boost of a `may_boost` card they put on the table before the Reveal is not offered when the rival plays Mists (`session_boost.offered` dry-runs it and sees the card replaced).

## Winds of Watoomb, Eye of Agamotto, No, Really, I'm a Doctor on the table
- **Winds**: `place` with `chooser: opponent` for Strange and `chooser: owner` for the opposing fighter, both on `where: {start: true}`. A piece the human places (Strange when the bot plays it; the bot's fighter when they play it) is moved by them (`session_moves`: Done validates the space); the bot moves a human piece by GUID. The bot shuffles its draw pile (`shuffle_deck`); the human is told to shuffle theirs ("on the table: shuffle your deck").
- **Eye of Agamotto** (human): the whole hand into the deck has nothing to choose, so the bot puts their seat's hand into their deck and shuffles it (`return_hand_to_deck` + `shuffle_deck`, the mulligan's writes), then deals the 5 cards. If the table refuses, they are told to do it by hand and to draw the 5 themselves (the owed draw is not dealt before the hand went back).
- **No, Really, I'm a Doctor** (human): a `cards` request with `pile_mode: reveal` (exactly one): they put the revealed card on their discard pile, the bot reads it and puts it on top of their deck by GUID (`stack_top`); the bot learns it is the top card (`KnownHand.top_of_deck`: it was shown). The heal then asks Strange or Wong (when next to him) on the panel. The bot picks the card that heals most for the least it is worth in hand (`EffectAI._card_to_reveal`).

## Rules decisions (the user is away: the most reasonable reading, applied)
Every item below is also an open question for Iván.

1. DARK PACT applies only when **Doctor Strange himself** played the card: a card Wong played, or Strange defending with no card, does not count. CONFIRMED by Iván on 2026-11-07: a card Wong plays does not trigger it.
2. DARK PACT fires after the combat is fully resolved (its AFTER effects included) and not at all when the combat ended the game. The damage is effect damage on himself: Pact Of Mortality adds 1, an immunity stops it. The human may pay even when it kills Strange (the game ends); the bot never does.
3. DARK PACT with an empty deck: the card goes to the bottom and the draw takes it back, with no exhaustion damage.
4. BLIND BOOST (Iván, 2026-11-07): the owner declares the count first (Bolts 0 or 1, Seven Suns 0, 1 or 2), then that many top cards of the deck are discarded face up and their BOOST values added; no choice of card, no cost in hand, and no stopping after seeing a card ("up to two times" is a declared count, not a sequence of optional steps).
5. Seven Suns: "if the value of this card is above 7, ignore its value" is applied after the blind boosts, to the total (bonuses included). The opponent's DURING effects that resolve later can still change the total.
6. "A starting space" is any of the four starting spaces of the board (free ones); "another starting space" is any other free one. The rival chooses where Strange goes; the owner chooses where the opposing fighter goes. A defeated opposing fighter is not placed. Both decks are shuffled even when the combat was lost.
7. The Mists of Munnopor: the new card must be an attack or versatile card the attacking fighter's restriction allows; its effects all run; no playable card in the rival's deck leaves the attack with no card (value 0), CONFIRMED by Iván on 2026-11-07. The original card is discarded at once (it is not "played").
8. Cloak of Levitation needs Strange himself next to the opposing fighter; the opposing card's whole value (bonuses included) counts for 0.
9. Master of Kamar-Taj: both alive and adjacent; the printed value becomes 4 (bonuses stay).
10. The Rings of Raggadorr: "damage dealt" is the combat damage of the combat won; "adjacent to them" is next to the fighter who played the card (Strange or Wong; it is an ANY card); healing stops at the maximum.
11. Steadfast Disciple: Wong must still be next to the opposing fighter after the combat and the fighter must be alive.
12. No, Really, I'm a Doctor: the revealed card stays on top face up, so the opponent knows the top card of the deck; the heal goes to Strange or to Wong when he is next to Strange, the owner's choice.
13. Eye of Agamotto: the scheme card itself is already played, so it is not shuffled; with fewer than 5 cards in the deck the draws run into exhaustion as always.
14. The effects text "Dr. Strange" on the cards is Doctor Strange himself, never Wong.
15. BLIND BOOST with fewer cards in the deck than declared discards what is there; with an empty deck there is nothing to declare; CONFIRMED by Iván on 2026-11-07 ("you can only take what is there").

## Open questions for Iván
- Starting spaces: confirm all four numbered spaces of the board count in a 2-player game (and not only the two in use).
- The Mists of Munnopor against an attack whose card has an IMMEDIATELY effect: read as that effect resolving in the same step (after Strange's own, as the defender goes first).
- Human Mists: the bot cannot check the cards they revealed or where they put the rest; only the card at their combat spot is read.
- Resuming a save between the reveal and DARK PACT's answer keeps the GUID of the played card, but a card the human already moved by hand falls back to the chat instruction.
- A defense `values` bonus (the human's +/- dial) stays with an attack replaced by the Mists.

## AI
- The AI profile comes from the data (Strange `hero`, Wong `striker`; exclusive cards: Steadfast Disciple for Wong). `ai_medusa` has hints for the cards: the expected blind boost of Bolts and Seven Suns (the bot knows its deck, `BLIND_BOOST`, capped at 7; an estimate for planning, the real count is declared by `EffectAI._blind_boost` when the card resolves), Master of Kamar-Taj worth 4 next to Wong, Cloak ignoring the defense when Strange is beside the target (attack and defense), the heal of The Rings of Raggadorr (only what is missing counts), the action of Bolts, the draw of Steadfast Disciple, and The Mists of Munnopor as a defense (the attack becomes a random playable card of the rival's deck: its public pool, never its hand).
- The schemes are valued by simulating them like the other heroes' (Eye of Agamotto when the hand is poor and the deck deep, No, Really, I'm a Doctor when Strange or Wong is hurt).
- DARK PACT, BLIND BOOST and the card to reveal are decided by `EffectAI` (above); the search's rollouts use `SyntheticChooser` (`PACT_SAFE_HP`, the largest blind boost count that cannot push Seven Suns over 7).

## Tests
`tests/test_hero_doctor_strange_data.py` (data and card identity), `tests/test_doctor_strange_effects.py` (every card and DARK PACT on the interpreter, the bot's decisions), `tests/test_doctor_strange_human.py` (FakeTTS, the panel: DARK PACT, the BLIND BOOST declaration and its table move, the reveal, Eye, Winds, Mists in both directions, resume), `tests/test_deck_top_to_discard.py` (the Lua builder on the stub table), `tests/test_doctor_strange_matrix.py` (full games against all nine heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).

## Revealed cards are shown large (Ivan, 2026-11-08, global)
"Reveal" in a card text means every player sees those cards. Wired here: No, Really, I'm a Doctor (the revealed card, by the bot or the human) and The Mists of Munnopor when the engine's (the bot's) deck is the one revealed. When the human reveals their own deck for the Mists they do it by hand, so there is nothing to copy. The bot lays a large face-up copy of each revealed card side by side over the board (`reveal_spot`, `reveal_scale`, `reveal_step` in `config/table.json`), they stay until the human presses **Stop revealing** on the panel (hidden when nothing is revealed, never greyed out) and play carries on meanwhile. A new reveal replaces them; New game, Restart, Clean table and `--resume` remove them. The originals never move and no deck order is touched. The chat still names the cards (a reveal is public). Looking is not revealing: nothing in this hero's deck only looks. See `sparring/session_reveal.py`.
