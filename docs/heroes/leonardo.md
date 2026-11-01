# Leonardo (Adventures: Teenage Mutant Ninja Turtles)

Data read from the real cards of the tournament save (Leonardo deck, sheet 176, 8x4; character card 363, sheet 3) on 2026-11-01.
Files: `data/heroes/overlay/leonardo.json` (CardID sheet), `data/heroes/leonardo.json` (generated HeroDef),
`data/heroes/effects/leonardo.json` (structured effects), `data/tts/leonardo.json` (table data),
`tests/test_hero_leonardo_data.py`, `tests/test_hero_leonardo_effects.py` (bot side), `tests/test_leonardo_table.py`
(human side), `tests/test_leonardo_full_games.py` (whole FakeTTS games).

## Summary

- Leonardo: 16 life, movement 2, melee. Miniature `729fb1` (nicknamed `[016099]Leonardo`), dial `88f451` (max 16).
- Splinter: 1 sidekick, 9 life, melee, movement 2. Miniature `663c11`, dial `8e70c6` (max 9). Starts on the board.
- Ability TEAM TACTICS: at the start of your turn you may move any fighter 1 space.
- No forms, counters or tokens. CardID = 17600 + idx, the same range as Medusa's (DeckID 176 is shared by every TMNT
  deck and Medusa in the tournament save); decks are told apart by their images (`deck.identity`).
- Deck: 30 cards. Leonardo 11 (Katana x2, Turtle power! x2, Wise beyond his years x3, Heroes in a half shell x2,
  Leonardo leads x2), Splinter 5 (Spatial awareness x3, Protective father x2), ANY 14 (For Sensei x2, Fearless leader x3,
  Quick strike x3, Eat, sleep, and breathe ninjutsu x3, I have a plan x3).

| Card | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| Katana | attack | 6 | 2 | 2 | none |
| Turtle power! | attack | 3 | 2 | 2 | DURING: may BOOST this card |
| For Sensei | attack | 4 | 1 | 2 | AFTER: move both fighters of the combat up to 1 space; you may discard 1 card to gain 1 action |
| Fearless leader | attack | 3 | 2 | 3 | DURING: +2 per other friendly fighter adjacent to the opposing fighter |
| Wise beyond his years | versatile | 2 | 2 | 3 | AFTER: if the opposing fighter is in fewer zones than Leonardo, 2 damage to it |
| Quick strike | versatile | 3 | 3 | 3 | AFTER: draw 1 |
| Eat, sleep, and breathe ninjutsu | versatile | 3 | 1 | 3 | AFTER: place each fighter adjacent to your fighter in another space of its zone |
| I have a plan | versatile | 2 | 1 | 3 | IMMEDIATELY: you may discard 1 card; if you do, cancel the opponent card's effects and ignore its value |
| Spatial awareness | versatile | 3 | 3 | 3 | AFTER: if the opposing fighter is in fewer zones than Splinter, 1 damage to it and draw 1 |
| Heroes in a half shell | defense | 5 | 3 | 2 | none |
| Leonardo leads | scheme | - | 4 | 2 | move each friendly fighter up to 3 spaces; draw 1 |
| Protective father | scheme | - | 2 | 2 | Splinter may swap with another friendly fighter; if he does both recover 2; gain 1 action |

## Decisions (1v1 reading of the co-op cards)

- "Other friendly fighter" is the player's other fighter: Splinter for Leonardo, Leonardo for Splinter (there is no other
  friendly player). Fearless leader therefore adds at most +2; Protective father can only swap Splinter and Leonardo.
- "Zones" = how many zones the fighter's space belongs to (map data `zones`). Compared when the AFTER resolves. A fighter
  that fell in the combat is in no zone.
- TEAM TACTICS reads "you may move any fighter 1 space" as optional and up to 1 space; "any fighter" includes the rival's
  (the owner of the ability chooses where). Played by the bot, the bot does it at the start of its turn. Played by the
  human, the panel says it and waits: only End action works until it is done (the human moves the miniature by hand,
  the rival's too), the same rule as the other start-of-turn abilities.
- Protective father: the swap is optional, the action is not.
- Moves of the human's own miniatures are done by hand (table note); the bot's pieces a human card moves are chosen on the
  panel (the human puts the miniature there and presses Done) and, for the bot's own effects, the bot moves them.
- Eat, sleep, and breathe ninjutsu: the group of adjacent fighters is fixed when the AFTER starts, each is placed on an
  empty space of its own zone other than the one it stands on, one after another; one with no free space stays.

## Discrepancies with unmatched-memory (the card wins)

- "Eat, sleep, and breathe ninjutsu": memory says "breath" (overlay `memory_title` keeps the lookup).
- "I have a plan": memory says "Of you do".
- "Fearless leader": memory says "this card value"; the card says "this card's value".
- TEAM TACTICS: the card says "you may move any fighter 1 space" (memory: "move any fighter up to 1 space").
- The catalog says 31 cards: 30 playing cards plus the character card.

## Engine additions made for Leonardo (documented in `docs/effects-dsl.md`, section "Leonardo")

- Amount `{"stat": "zones", "fighter": ...}`; SpaceSel flag `other`; `as` on `swap`, and `swap` of two of the table player's
  miniatures is left to them (table note).
- Cards of decks that share a CardID (Leonardo and Medusa, and the other TMNT heroes) resolve by owner: `find_card(owner)`,
  `side_of` by value, and `is_medusa_card` checks the card, not only the range (all unified in docs/card-identity.md). The configuration accepts overlapping
  CardID ranges when the deck images differ.

## Ivan's decisions

(none yet: the first live game is pending)

## Open questions for Iván

1. Spatial awareness when the opposing fighter fell in the combat: read as "no draw" (a fallen fighter is in no zone).
2. TEAM TACTICS on the rival's fighters: allowed ("any fighter"); the rival's miniature is moved by the owner of the ability.
3. TEAM TACTICS "1 space": up to 1 (it may be declined or the fighter stay).
4. Fearless leader / Eat, sleep, and breathe ninjutsu: "friendly" read as the player's own other fighter.
5. I have a plan: the extra card is discarded from the hand in addition to the card already played.
