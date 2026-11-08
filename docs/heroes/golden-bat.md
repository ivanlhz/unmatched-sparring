# Golden Bat (Adventures: Tales to Amaze)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 345 on sheet 3) on 2026-11-08. Verified on FakeTTS only: nothing of Golden Bat has been seen on a real table (see `docs/live-checklist.md`).

## Summary
- Melee hero, 18 life, move 3. **No sidekick**: unmatched-memory lists "Daisy" (flagged `hasSidekicks: false`) but the hero card names none and the savegame has a single miniature (GUIDs `b0ebcc` piece, `0f46cb` dial, both named Golden Bat). Hero fid `bat`.
- Ability **THE FIRST SUPERHERO**: "If you haven't taken a Maneuver action this turn, add +2 to the value of Golden Bat's attacks." A HeroDef passive `attack_bonus` (n 2) with `unless: maneuver` (docs/effects-dsl.md section 32): the combat reveal adds it, and the bot's estimates of Golden Bat's next attack (`Game.attack_bonus`) read the same thing.
- Deck: 30 cards, `CardID = 17600 + idx` (sheet 176), every card under the GOLDEN BAT band (none ANY). The deck object of the save holds 31 cards (the 30 plus the character card `345`).
- Table: bag `4732a0`, deck `29a029`. **He shares CardIDs 17600-17629 with Medusa, the four turtles, Doctor Strange, Bigfoot, Daredevil (22 cards), Luke Cage and Bullseye**: his deck is told apart by deck image and owner (docs/card-identity.md), never by a bare CardID. `tests/test_golden_bat_matrix.py` plays him against every other hero in both seats.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| Super Strength | attack | 5 | 1 | 2 | No text |
| Vaporizing Eyebeams | attack | 2 | 2 | 3 | AFTER: your opponent discards 1 random card |
| A Punch to Shake the Earth | attack | 1 | 1 | 3 | AFTER: 1 damage to each opposing fighter in your zone; 2 if you won |
| Sight Beyond Sight | versatile | 2 | 1 | 3 | AFTER: look at the top 3 cards of the opponent's deck, put them back in any order |
| Terrifying Roar | versatile | 3 | 1 | 3 | IMMEDIATELY: fighters cannot leave their spaces for the rest of the turn |
| Skirmish | versatile | 4 | 1 | 2 | AFTER: if you won, move one of the fighters in the combat up to 2 spaces |
| Like a Flash of Golden Light | versatile | 2 | 2 | 3 | DURING: value 4 if he shares no zone with the space he started the turn in. AFTER: move up to 5 |
| Insight of the Ancients | versatile | 3 | 2 | 2 | AFTER: if you won, a random card of your discard pile returns to your hand |
| Imposing Presence | defense | 3 | 2 | 2 | IMMEDIATELY: cancel all effects on the opponent's card |
| He Laughs at Your Feebleness | defense | 5 | 3 | 2 | No text |
| Arrive Just in Time | scheme | - | 2 | 2 | Place Golden Bat in any space |
| Alpine Fortress | scheme | - | 3 | 3 | Shuffle a chosen discard card into the deck, draw 2, move up to 4 |

## Discrepancies with unmatched-memory
- **A Punch to Shake the Earth** reads "each opposing fighter in **your** zone" on the card; unmatched-memory says "in Golden Bat's zone" (the same: he is the only fighter). The HeroDef carries the card's text.
- **Skirmish** reads "move one of the fighters in the combat up to 2 spaces"; unmatched-memory "choose one of the fighters in the combat and move them up to 2 spaces" (the same).
- Daisy (unmatched-memory) is not on the card or in the save. Restriction bands are not in unmatched-memory at all. Type, value, boost and copies of the 12 titles agree with the images.

## Collisions found in the save
- **CardIDs 17600-17629** shared with the nine other decks of sheet 176. Solved as for them: `data/tts/golden-bat.json` carries its own `deck.identity` and every lookup is per owner; `tests/test_hero_golden_bat_data.py` pins that no card is equal to a card of another deck of the range and that the images differ.
- No piece GUID is shared with another hero (pinned in `tests/test_hero_golden_bat_data.py`).

## Rules decisions (the user is away: the most literal reading, applied)
Every item that is a real doubt is also an open question below.

1. **A Maneuver action is counted the moment it is taken** (`Game.maneuver`, the session's Maneuver button), even if the draw is then blocked (Cold Iron) or the deck is empty. Other actions (attack, scheme, a gained action, the free BOOST) never count. The tally is of the running turn: it is the owner's own turn when it matters (attacks), and it starts again at every `start_of_turn`.
2. **THE FIRST SUPERHERO** applies to every attack Golden Bat makes on his own turn, whichever card (a versatile one played as an attack included), after any other bonus; never to a defense. It needs no maneuver to be missing in the rival's turn: the rival's attacks never get it.
3. **Terrifying Roar** pins every living fighter, his own side included ("fighters"), with `cannot_leave_space` until the end of the current turn (the attacker's, when played in defense), the status Liz Sherman's Burning Barrier uses: no walk, push or effect move takes a fighter out of its space; placing or swapping is not "leaving". It does not stop attacks.
4. **A Punch to Shake the Earth** hits the rival's living fighters on any space that shares a zone with Golden Bat's (the opposing fighter of the combat included while alive); his own side is never hit. "If you won the combat" is the card owner's result: 2 each, otherwise 1 each.
5. **Like a Flash of Golden Light**: "the space he started this turn in" is where he stood at the start of the turn that is running (also the rival's turn when the card is played in defense). A Golden Bat that has not moved, or still shares a zone with it, gets the printed 2. The printed value becomes 4 (bonuses stay).
6. **Sight Beyond Sight**: the owner looks at the top 3 (fewer if the deck is shorter) and puts all of them back on top in the order he chooses (the first of the order ends on top); no card is taken. The human reads the bot's real top cards on the panel. **The bot cannot read a human's real deck at the table** (the engine's copy is placeholders and the bot never reads hidden information except where a card says so, by a channel that exists): the bot's Sight Beyond Sight against a human does nothing but say so in the chat. In headless games and with the search AI, both decks are known to the engine and the bot orders them worst first.
7. **Insight of the Ancients** returns one card at random from the discard pile (the engine's rng); the card just played is not in the pile yet. An empty pile: nothing.
8. **Skirmish**: after a win the owner picks either fighter of the combat (the one that was defeated cannot move) and moves it up to 2 spaces (0 allowed); a rival piece is moved by the owner, not through other fighters.
9. **Vaporizing Eyebeams** discards the card even when the combat is lost; the card is chosen at random (the table draws it; the bot never looks).
10. **Alpine Fortress** in printed order: the chosen card is shuffled into the deck (mandatory when the pile is not empty; the scheme card itself is not in the pile yet), then 2 cards are drawn (the shuffled card may be one of them), then up to 4 spaces of move.
11. **Arrive Just in Time**: any empty space, his own included (placing may leave him where he is).
12. **No sidekick**: Daisy is ignored (see above).

## Open questions for Iván
1. Is the bot's **Sight Beyond Sight** against a human at the live table acceptable as a no-op (it cannot read your real deck)? The alternative is a new read of your deck's top 3 through a table channel (like the bot's hand row), which would make the bot's look real.
2. **Terrifying Roar** pins Golden Bat's own fighters too, so his own AFTER moves (Like a Flash, Skirmish, Alpine Fortress) after a Roar in the same turn do nothing. Literal reading of "Fighters cannot leave their spaces"; should it exclude him?
3. The Maneuver count includes a Maneuver whose draw is blocked or whose deck is empty. OK?
4. Daisy: is there really no sidekick in the physical set (only unmatched-memory lists her)?

## AI
- The AI profile comes from the data (hero `hero`, no sidekick; exclusive cards: all twelve titles).
- `Game.attack_bonus` carries THE FIRST SUPERHERO: the bot values an attack of his next turn with the +2 and no longer takes it once it has maneuvered, so attacking from where he stands (without a Maneuver) is worth more than walking up with one.
- Card hints and values come from the generic simulation of the ops (moves, draws, discards, zone damage, cancels); Sight Beyond Sight's order is the shared `EffectAI._order` (worst cards of the rival's deck first), Like a Flash of Golden Light's DURING value is simulated like every other `set_value`.

## Human side
- Buttons appear only when the card is played (never greyed): the order of Sight Beyond Sight's three cards, the card of Alpine Fortress's discard pile, the fighter and space choices of Skirmish, Like a Flash and Alpine Fortress (the bot's piece is moved by hand and you press Done), the placement of Arrive Just in Time. Every choice is a parked run saved with the game and survives `--resume`.
- A bot card that shuffles a discard card into its deck and draws in the same step (Alpine Fortress) is translated as a shuffle into the real deck followed by the draws (`session_bot_effects._bot_cards`, `drawn_back`).

## Tests
`tests/test_hero_golden_bat_data.py` (data, card identity, detection), `tests/test_golden_bat_effects.py` (the ability and every card on the interpreter), `tests/test_golden_bat_matrix.py` (full games against the fifteen other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
