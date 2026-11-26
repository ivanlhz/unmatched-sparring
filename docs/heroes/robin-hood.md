# Robin Hood (Battle of Legends, Volume Three, with four Outlaws)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 308 on sheet 3) on 2026-11-22. Rulings of Ivan 2026-11-22 are cited as such; the readings applied from the designers, Discord and RulesPal are in `REGLAS-PENDIENTES-batch4.md` section 2 of the farm brief and are repeated here where they decide a card.

## Summary
- Ranged hero, 13 life, move 2, **four Outlaws** (melee, 1 life, move 2, no life dial). Hero fid `robin`, sidekick fid `outlaw` (`outlaw1` to `outlaw4`), slug `robin-hood`. All five start on the board like any sidekick.
- Ability: "After you attack, you may move your attacking fighter up to 2 spaces." One `after_attack` trigger (`move_after_attack`) with a `move` of up to 2 on the `$attacker` of the event; no engine addition. Any attack of the player triggers it, also an Outlaw's ("your attacking fighter"), once the combat is over, after every AFTER COMBAT effect of both cards (Ivan 2026-11-22). It does not fire for a fighter the combat (or an AFTER effect) defeated: the selector of the event only sees living fighters. A defeated defender changes nothing: the attacker moves. The move is ordinary movement (printed adjacency, not through opposing fighters) and optional by itself (a move "up to 2" may stay): there is no Yes / No in front of it.
- Deck: 30 cards, `CardID = 17600 + idx`. The deck object in the save holds 31 cards (the 30 plus the character card 308), hence `card_count 31` and `card_ids [308, 17629]` in the catalog.
- Table: infinite bag `ee2fcc` (inner `6c439e`), deck `462e4d`, miniature `5aa21a`, life dial `1fc8df` (max 13), four Outlaw tokens `88a446`, `0d8360`, `821507`, `dc6b24` (Custom_Token: one image, no second face, all nicknamed Outlaw; real TTS may report them as "Tile"). **The dial GUID `1fc8df` is also Yennenga's dial and Nikola Tesla's miniature** (he is not in the project): the save reuses it for models named after their hero, told apart by name (`session_pieces.resolve_dials`, docs/card-identity.md "Piece identity"). `tests/test_robin_hood_dials.py` plays the pair in both seats and both ways round; the brief called it a miniature, the save says it is the dial ("Hero Health").

## Card identity: the shared CardID range
His deck is sheet 176 like Medusa's, the turtles' and every other hero's of the project: CardIDs 17600-17629, a different image (`data/tts/robin-hood.json`, `deck.identity`). Everything in docs/card-identity.md applies; the proof is `tests/test_hero_robin_hood_data.py`, `tests/test_card_identity.py` (he is in `SHARING`) and `tests/test_robin_hood_matrix.py`. His Feint (ANY, 2 / BOOST 2) is word for word Bigfoot's, so the three cards carry the tag `robin-hood` (Pandora's did the same); nothing reads the tag.

## Cards (as implemented)

| Title | Band | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|---|
| A Hunter's Eye | Robin Hood | attack | 5 | 4 | 3 | none |
| Piercing Shot | Robin Hood | attack | 2 | 3 | 2 | AFTER: draw 2 |
| Disarming Shot | Robin Hood | attack | 4 | 3 | 2 | AFTER: draw as many cards as the damage dealt to the opposing fighter |
| Ambush | any | attack | 2 | 3 | 2 | DURING: the opponent discards 1 random card from the hand; add its BOOST to the value (plugin) |
| Highway Robbery | **Outlaw** | attack | 2 | 2 | 4 | IMMEDIATELY: cancel the opponent's card and ignore its defense value |
| Regroup | any | versatile | 1 | 2 | 3 | AFTER: draw 1; 2 if you won the combat |
| Feint | any | versatile | 2 | 2 | 3 | IMMEDIATELY: cancel the opponent's card |
| Snark | any | versatile | 3 | 1 | 3 | AFTER: draw 1 if your fighter is adjacent to the opposing fighter |
| Wily Fighting | any | versatile | 3 | 1 | 3 | AFTER: 1 damage to each opposing fighter adjacent to your fighter |
| Defenders of Sherwood | any | defense | 3 | 2 | 2 | AFTER: draw 1; return a defeated Outlaw to a space in Robin Hood's zone |
| Steal From the Rich | Robin Hood | scheme | - | 3 | 3 | draw 1, the opponent may discard 1 card, if not draw 1 more |

## Discrepancies with unmatched-memory
- **Ambush** prints "this card's value" (unmatched-memory: "this card's attack value"): the overlay carries the printed text.
- unmatched-memory has no restriction band; read from the images: Highway Robbery is **OUTLAW** (only an Outlaw plays it, Robin Hood himself cannot), Hunter's Eye, Piercing Shot, Disarming Shot and Steal From the Rich are ROBIN HOOD, the rest ANY.
- Everything else (titles, types, values, BOOSTs, copies, texts, 13 life, move 2, the ability, four Outlaws of 1 life) agrees with the images; the sheet order is in the overlay notes.

## Engine additions
- `sparring/effects/plugins_robin.py`, one plugin: `robin:ambush` is the Raptors' `blue:ambush` under his own id (a plugin id carries the fid of its hero). The discard is `random_discard.discard_random_known`; a rule that forbids forced discards (Counterhex Shield) leaves nothing discarded and adds 0; the BOOST is added with `modify_value` (combat damage, not "boosting": no BOOST effect of the discarded card runs); an empty hand adds 0.
- `sparring/ai_robin.py` and four hook lines in `ai_medusa.py` / `ai_effects.py` (see AI below).
- Everything else is existing DSL: `after_attack` with `move` on `$attacker`, `draw` with `{"stat": "damage_dealt_this_combat"}`, `cancel_effects` and `set_value ignore`, `if` with `combat_result`, `exists` with `where adjacent_to this`, `damage` on `adjacent_to this`, `revive` in `zone_of hero`, `optional` with a `cost` of a hand discard and an `else`.

## Rule decisions
1. **The ability** is after all AFTER COMBAT effects (the designer, Ivan 2026-11-22), so Snark's adjacency and Wily Fighting's targets are read BEFORE the move. A human Robin does the AFTER effects first and then walks (the chat says it in that order).
2. **Disarming Shot** draws the combat damage that landed on the opposing fighter, OVERKILL INCLUDED (a 4 against a fighter with 1 health draws 4; the designer). It is what remains after the opposing hero's damage reduction (Luke Cage) and a cap; damage the combat sent elsewhere (Golden Chain Mail back at the attacker) was not dealt to the opposing fighter and counts 0. Effect damage of the same combat is not counted (see Pending Ivan).
3. **Ambush** discards from the HAND, never the deck; its BOOST is added to the attack value (combat damage, not "boosting"); an empty hand adds +0 and nothing is discarded; a cancelled Ambush discards nothing.
4. **Highway Robbery**: the cancel respects an uncancelable card, the ignore does not. "Ignore its defense value" is the engine's `set_value ignore` (the defender's whole total is 0 at that moment, a later BOOST or effect still adds). Only an Outlaw plays it.
5. **Defenders of Sherwood** may return ANY Outlaw defeated earlier in the game (the designer and Discord), with 1 health, to an empty space of Robin Hood's zone chosen by his player; with no defeated Outlaw or no empty space only the draw happens.
6. **Steal From the Rich**: with two players "choose an opponent" is the rival, who decides whether to discard (Ivan 2026-11-22: the rival decides). A rival with an empty hand cannot pay, so Robin Hood draws the second card without being asked.
7. **Regroup / Snark / Wily Fighting**: "your fighter" is the fighter that played the card (an Outlaw counts), "the opposing fighter" the other fighter of the combat, "each opposing fighter" every enemy fighter next to the first (the combat's own opposing fighter included). "Won the combat" is the engine's (the attacker wins only if combat damage lands, a tie is won by the defender).

## Table (what the bot does, what the chat asks, what the bot reads back)

| What happens | What the bot does | What the human does / what it reads back |
|---|---|---|
| The human's Robin or Outlaw attacks | after the combat the chat says "Tu habilidad: Despues de atacar: tu luchador atacante puede moverse: en la mesa: mueve a outlaw1 hasta 2 casillas" (the fighter that attacked, by its id) | the human moves that miniature by hand (or leaves it); at End action the bot reads the table and checks the walk against the permission (`game.hand_moves`: at most 2 along a legal path, no opposing fighter crossed, an occupied space refused). A walk that breaks it is refused with the reason and the engine keeps the old space until it is put right. The permission is saved: a resume mid-way asks the same |
| The bot's Robin or Outlaw attacks | chooses a space or none with its evaluation and moves the miniature itself (Lua `move_piece`, projected like every move of its own pieces) | nothing |
| The human plays Piercing Shot / Disarming Shot / Regroup / Snark | the engine counts the draws, the bot deals the cards ("Te he dado N cartas") | nothing; Disarming Shot deals what the blow dealt |
| The human plays Ambush | the bot discards a random card of its own hand and adds its BOOST | nothing |
| The bot plays Ambush against the human | names a position of the hand ("al azar: la carta N"), the human lays that card on their discard pile and presses Done | the bot reads which card it was (the pile is public), adds its BOOST; "no veo" and the same question until a card is there |
| The human plays Highway Robbery with an Outlaw | the bot's defense value counts 0 | nothing |
| The human defends with Defenders of Sherwood | deals the drawn card; returns one defeated Outlaw with no question (the four tokens are the same) | the human puts ANY defeated Outlaw token on an empty space of Robin zone and presses End action; the bot follows whichever token stands there: the two fids trade tokens, as for Yennenga Archers (session same_token, reserve_kin). The zone is told in the chat, but a piece put by hand is read where it stands, as for every placement by hand (see Pending Ivan) |
| The bot defends with Defenders of Sherwood | places the Outlaw itself (Lua) in Robin's zone | nothing |
| The human plays Steal From the Rich | the bot, as the rival, decides (see AI); if it discards, the chat says so, if not it says "no paga" and the human is dealt 2 cards | nothing |
| The bot plays Steal From the Rich | asks the human on the panel ("Descartas 1 carta para que Robin Hood no robe otra?": Yes = discard 1 card, No = Robin draws one more) | on Yes the human discards a card of their choice onto their pile and presses End action (the discard is read from the pile); the bot then draws 1, on No 2 |

Save / resume: the open walk (`hand_moves`), the Outlaw still to place (`placing`) and the human's choice in the bot's Steal From the Rich are all in the saved session and asked again; `tests/test_robin_hood_human.py` reloads each.

## AI
- The heuristic bot already wins most games with no hook (9 of 12 against the chasing Hellboy, 12 of 12 against Medusa on seeds 0-11; Chupacabra, hooks included, 10 of 12). `sparring/ai_robin.py` adds what the data-driven profile cannot price: Ambush is worth its 2 plus the mean BOOST of the cards the rival may still hold (their composition minus their discard pile, never their hand), Highway Robbery is read as a blow nothing blocks (`MedusaAI.ignores_defense`), Disarming Shot is worth the cards it draws when it wins, Snark and Wily Fighting only next to a rival, Defenders of Sherwood more with a defeated Outlaw to bring back.
- The bot as the rival of Steal From the Rich (`ai_robin.steal_pays`) discards its least useful card when that is worth less than the average of the cards Robin Hood may still draw, else lets him draw. Public information only.
- Checked with the search (`make_bot_ai({"ai": "ismcts"})`): games in both seats against Hellboy, `ai.fallbacks == 0` (`tests/test_robin_hood_ai.py`).

## Tests
`tests/test_hero_robin_hood_data.py` (data and card identity), `tests/test_robin_hood_effects.py` (the ability and every card on the engine, mutation-checked), `tests/test_robin_hood_human.py` (FakeTTS, the panel, both seats, save and resume), `tests/test_robin_hood_ai.py`, `tests/test_robin_hood_dials.py` (the dial GUID shared with Yennenga), `tests/test_robin_hood_matrix.py` (full games against every other hero in both seats, passive and attacking human, headless with the heuristic and the search AI).

## Pending Ivan
1. **Disarming Shot and effect damage**: only the COMBAT damage dealt to the opposing fighter is counted. Another effect damaging the same fighter in the same combat (the rival's own card) is not added.
2. **Highway Robbery and a later BOOST**: the ignore is the engine's "total 0 at this moment"; a free BOOST the defender is allowed afterwards (Out Of Time) still adds, as for every "ignore the value".
3. **Defenders of Sherwood on the table**: the human may lay any fallen Outlaw token (adopted, see the table), and a token put outside Robin's zone by hand is read where it stands (no check of the zone, as for every piece the human places by hand).
4. **Steal From the Rich against the bot**: the bot decides with a simple rule (its worst card against Robin Hood's average draw); the human is asked a dedicated question ("Descartas 1 carta para que Robin Hood no robe otra?": Yes = discard).
5. **Where the move is said**: the chat names the fighter by its id (`robin`, `outlaw2`) in "mueve a ..." (the engine's note for every own move by hand), while the table objects are renamed Outlaw 1 to 4 by the session.
6. **The bot's move and the human's own AFTER step**: the bot's Robin (or Outlaw) moves when the engine finishes the combat; a step the human still has to do by hand for their own card (a miniature to walk, a discard) is not waited for, so in that rare case the bot chose its destination before the human finished their AFTER effect. The AFTER gate of the combat flow only orders the two cards' effects, not this trigger.
7. **Defenders of Sherwood and the Outlaw that has just fallen**: an Outlaw that falls while defending with Defenders of Sherwood may be the one that comes back in that same combat (the card returns a defeated Outlaw in its AFTER, after the damage). The ruling said defeated earlier; the literal text does not exclude it.
