# Pandora (Battle of Legends, Volume Three)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, the seven MISERIES on sheet 177, character card 359 on sheet 3) on 2026-11-22.

## Summary
- Melee hero, 14 life, move 2, **two Kakodaemons** (melee, 1 life each, move 2) that are **not on the board at the start**: they wait in the reserve (`start_on_board 0`) and come out only through the Miseries (Ivan 2026-11-22, PA1: "the Kakodaemons enter the board only through the MISERIES"). Hero fid `pandora`, sidekick group `kakodaemon` (`kakodaemon1`, `kakodaemon2`), slug `pandora`. Their tokens are called Thanatos and Olethros in the save (`tts_tokens` in the overlay).
- Ability, **Pandora's Box**: at the start of her turn she opens the Box, a deck of seven MISERIES. The first reveal is mandatory; she may keep revealing one at a time; with three feathers or more among the revealed cards she must stop and takes 1 damage for each revealed Misery (the one that reached three included); the revealed Miseries go back into the Box at the end of her turn, so on the rival's turn the revealed count is 0. The hero card prints only "Do not start with any Kakodaemons on the board. At the start of your turn, open Pandora's Box."; the rest is the rulebook's.
- Deck: 30 cards, `CardID = 17600 + idx`. Order on the sheet: Hera's Curiosity 0-2, Hindsight 3-5, Aphrodite's Beauty 6-8, Spite 9-10, Divine Intervention 11-12, Feint 13-15, Guided by the Fates 16-18, Malice 19-20, Offering to the Gods 21-22, Celestial Raiments 23-24, Zeus's Mischief 25-26, Forged by Hephaestus 27-29. Bands: PANDORA on six titles, **KAKODAEMON on Spite and Malice** (only a Kakodaemon plays them), ANY on Aphrodite's Beauty, Feint, Guided by the Fates and Forged by Hephaestus.
- The seven MISERIES (sheet 177, `CardID 17700 + idx`): **Woe** (summon a Kakodaemon in Pandora's zone), **Toil** (1 feather: +1 to the value of Pandora's attacks this turn), **Pain** (1 feather: 1 damage to each opposing fighter adjacent to Pandora), **Misfortune** (2 feathers, no effect), **Hope** (look at the top card of the Box before deciding whether to reveal it), **Greed** (1 feather: draw 1 card), **Confusion** (move Pandora up to 1 space). Five feathers in all.
- Table: bag `15414a` (inner `30d94f`), miniature `8603fa`, life dial `eeaab5` (max 14, the model with the `Hero Health` script), deck `b24a1c`, Kakodaemon tokens `7cd57e` (Thanatos) and `fed318` (Olethros), Custom_Token with no dial (real TTS may report them as "Tile": nothing that reads or moves a piece looks at the type). The Misery deck `4581f8` is in the inner bag and the bot never reads it.

## Card identity: the shared CardID range
Her deck is sheet 176 like Medusa's and the rest: only `deck.identity` (her own image pair in `data/tts/pandora.json`) tells the decks apart (docs/card-identity.md; `tests/test_hero_pandora_data.py` and the matrix are the proof). One card needed help: her **Feint** is word for word Medusa's Feint and Medusa's idx 15 has the same CardID 17615, which would make two equal `Card` values in two decks (`test_card_identity` forbids it); the three Feints carry the tag `pandora` in the overlay so that they differ. Nothing reads the tag.

## Pandora's Box in the engine
- **State**: the ability counters of the owner, nothing else. `box_mask` (a bit per Misery revealed), `revealed` (how many: what the cards read), `box_top` (1 + index of the top card once HOPE has looked at it), `box_done` and `box_current`. The trigger `pandora_shuffle` (end of her turn) sets them all to 0.
- **No order is stored**: the next Misery is drawn at random among the unrevealed ones WHEN IT IS REVEALED (the game's rng, once per reveal), which is the same as a shuffled Box nobody has seen. So neither the bot nor the search (a determinised clone) can peek at what is not known; the only known top card is the one HOPE showed (`box_top`). The invariant (`tests/test_pandora_effects.py`, 40 seeds): always keeping on reveals ends at three feathers or more and costs exactly the revealed count.
- **The loop**: `data/heroes/effects/pandora.json` trigger `pandora_box` is `pandora:reveal` (the decision to keep revealing, then the next Misery), the effect of that Misery as plain DSL (`box_current` says which), `pandora:close` (three feathers: 1 damage per revealed Misery and the Box is closed; otherwise the plugin rewinds the run's own frame, `frames[-1].idx = -1`, so the first op runs again). The DSL has no loop and this is the smallest thing that gives one; the decisions are asked through `run.ask` like any other, so the run pauses and resumes at the panel and saves with the game.
- **The Miseries are DSL**: Woe `if a defeated Kakodaemon then revive else summon` in `{zone_of hero}` (the convention of Abe's Agents and Sun Wukong's Clones), Toil `status attack_bonus` on the hero until the end of the turn, Pain `damage` on the enemies adjacent to the hero, Hope the plugin `pandora:look`, Greed `draw`, Confusion `move` up to 1.
- **Hope** fixes the top card for its owner (the bot reads its own Box; the human looks at the real card). The next reveal is that card whatever the owner chooses; if she stops, it stays on top (known) until the Box is shuffled at the end of the turn.

## At the table
| | the bot is Pandora | the human is Pandora |
|---|---|---|
| The Box | virtual: the engine draws each Misery | the real deck of seven cards: they reveal it themselves |
| Each reveal | the chat names it and what it does (`tr.pandora.reveal`) with the feathers out; HOPE says the bot looked | the panel asks which Misery came up (`choice.prompt.misery`, buttons by name, the ones already out are not offered); then "reveal another?" (`choice.prompt.ability.pandora_box`) |
| Woe | the bot takes the Kakodaemon out of the bag and puts it on the table (the usual projection of `summon`); the chat says so | the chat says "put Thanatos on the table (a space of Pandora's zone) with 1 HP"; the human puts it and End action reads it |
| Damage at three feathers | the chat says it (`tr.pandora.stop_damage`); the dial follows | the engine writes the dial; the line of the trigger says "Pandora -N PV" |
| Greed, Zeus's Mischief | the bot deals itself the cards | the human draws them (the chat says how many) |
| Hope | the bot knows its top card (the stopping rule uses it) | the human looks at the real top card; the engine knows nothing |
- The bot never reads the human's Box: it only knows which Miseries the human has said are out. The human's answers cannot repeat a revealed Misery. What the bot does not verify is that the human's answer matches the cards on the table (as with every card the human plays by hand).
- A trigger the engine runs for the table player: `table.ENGINE_RUN_TRIGGERS` has `pandora_box` (it asks, it hurts and it summons, none of which the table would otherwise let the engine do). `pandora_shuffle` only touches counters.

## Cards (as implemented)
1. **Hera's Curiosity** (attack 3 / boost 4, Pandora): DURING +1 per revealed Misery; AFTER look at the opponent's hand.
2. **Hindsight** (attack 3 / 2, Pandora): AFTER, if she won, return a card (her choice) from her discard pile to the top of her deck.
3. **Aphrodite's Beauty** (attack **0 / boost 3**, ANY): IMMEDIATELY cancel all effects on the opponent's card; AFTER Pandora recovers 1 health per revealed Misery (Pandora, whoever played it).
4. **Spite** (attack 3 / 2, Kakodaemon): AFTER 1 damage to each fighter adjacent to the fighter that played it, friendly ones included.
5. **Divine Intervention** (versatile 3 / 1, Pandora): AFTER move Pandora up to 5 spaces.
6. **Feint** (versatile 2 / 2, ANY): IMMEDIATELY cancel all effects on the opponent's card.
7. **Guided by the Fates** (versatile 2 / 3, ANY): DURING discard the top card of her deck and add its BOOST to the value; AFTER, if she won, Pandora recovers 2.
8. **Malice** (versatile 2 / 2, Kakodaemon): AFTER the opponent discards 1 card (their choice).
9. **Offering to the Gods** (defense 2 / 1, Pandora): DURING `may_boost` (the free BOOST, the engine's convention for "You may BOOST this card"); AFTER, if she won, 2 damage to the opposing fighter.
10. **Celestial Raiments** (defense 0 / 3, Pandora): DURING `set_value ignore` on the opponent's card (its total is 0 at that moment; a later BOOST or effect still adds: the batch's convention, REGLAS-PENDIENTES section 2).
11. **Zeus's Mischief** (scheme, boost 1, Pandora): draw 1 per revealed Misery; move an opposing fighter up to 1 space; gain 1 action.
12. **Forged by Hephaestus** (scheme, boost 1, ANY): place your fighter in any space; gain 1 action.

## Discrepancies with unmatched-memory
- **Aphrodite's Beauty** is printed value 0 and BOOST 3, band ANY (unmatched-memory: 3 and 2). The card wins (`value` and `boost` in the overlay sheet).
- The ability text has typos in unmatched-memory ("Kakodamons", a missing parenthesis): the real hero card is used. Schemes have no printed value (`value: null` in the sheet).
- Everything else (titles, copies, types, values, BOOST, 30 cards, texts) agrees with the images. `loki.json`'s empty sidekick slip is not Pandora's.

## AI
- The generic answer to an optional is yes, which walks into three feathers every turn. `ai_pandora.keep_revealing` (hooked in `EffectAI._optional` by the trigger id `pandora_box`) prices it as optimal stopping over the Miseries still in the Box, which is all the bot may know (plus the top card after HOPE): `ahead(mask)` is the expected value of revealing once more and then playing on the best way, against stopping (0); each Misery is worth its effect (a Kakodaemon while one can come, +0.4 per attack in hand for Toil up to two, 1 per rival next to her for Pain, a card for Greed, a little for Hope and Confusion) and a Misery that brings three feathers costs the hit points at `W_MEDUSA_HP`, dearer the lower she is, plus the chance of dying next turn (the price of Sun Wukong's CLONES). A reveal with no feather out cannot cost anything (no card has three feathers) so it is always taken; after Misfortune it is a coin flip the bot does not take; with HOPE it takes a feather-free top card and refuses a feather one.
- The search needs nothing else: its simulations run the same start-of-turn trigger with the same policy and draw the Miseries when they are revealed (for a human Pandora too, the clone has no table player so the engine draws), so it never sees an order. Verified with `make_bot_ai({"ai": "ismcts"})` as Pandora and against Pandora (`tests/test_pandora_ai.py`).
- Strength (information only, `pandora` as the bot against the chasing scripted Hellboy of `sim.play(rival="chaser")`, bprd-hq, wins of the bot over 40 games, heuristic AI): the priced rule 11 wins (837 turns), never keep revealing 6 (936 turns), always keep revealing 0 (251 turns: she kills herself in the Box). Search AI: see the table below.

## Rule decisions (taken without a ruling: the most literal reading, applied)
1. **A defeated Kakodaemon returns to the supply and can come back** (Woe revives a defeated one before taking a new one from the reserve): the same reading as Abe's Agents and Sun Wukong's Clones. With both on the board Woe does nothing.
2. **The Misery that brings the third feather is resolved, and then she stops and pays**: "reveal the top card and resolve its effect" comes before "if there are three or more total feathers... you must stop revealing, then Pandora takes 1 damage".
3. **Hope's look is the Misery's own effect**: when Hope is resolved she looks at the top card and then decides whether to keep revealing; with three feathers out she must stop (it cannot be Hope that brought them: it has none).
4. **Toil is +1 to Pandora's attacks** (the hero fighter, not a Kakodaemon's), until the end of the turn.
5. **Pain** reads "adjacent to Pandora" and hits the opposing fighters there, whatever they are. It cannot hurt her own fighters.
6. **The Box's damage is effect damage on Pandora**, so it can defeat her at the start of her own turn (the game ends then; `tests/test_pandora_effects.py`).
7. **The human's Box answers are trusted** like every card the human plays by hand: the panel offers only the Miseries not yet revealed and the engine applies the one named.
8. **Spite** hits every fighter next to the one that plays it, friendly ones too; **Aphrodite's Beauty** heals Pandora (not the fighter that played it).
9. **Zeus's Mischief** lets the owner choose the opposing fighter and the space.

## Pending Ivan
1. **Do defeated Kakodaemons come back with Woe?** (rule decision 1). Alternative: a defeated Kakodaemon is gone for good and the two are the lifetime supply.
2. **Hope when she then stops**: the top card stays known until the Box is shuffled at the end of her turn (the real deck keeps it on top). Alternative: nothing to decide, but say so if the rulebook shuffles it earlier.
3. **The Box's damage as effect damage** (rule decision 6): it can kill her, and a "prevent effect damage" would stop it (Counterhex Shield only stops the rival's effects).
4. **Table display of the bot's Box**: the bot's Miseries are only named in the chat; nothing is moved on the table (the Misery deck stays in the bag). If Ivan wants the cards laid face up, it is a new translator (`session_pandora.py`).

## Tests
- `tests/test_pandora_effects.py` (bot side: the Box, the seven Miseries, every card), `tests/test_pandora_human.py` (the panel, both seats: which Misery, keep revealing, Woe by hand, the damage on the dial, the bot's chat), `tests/test_pandora_ai.py` (the stopping rule, whole games with the search AI), `tests/test_pandora_matrix.py` (full games against every other hero in both seats, FakeTTS and simulator), `tests/test_hero_pandora_data.py` (data, card identity, the table data).
