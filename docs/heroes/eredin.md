# Eredin (The Witcher: Realms Fall)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 350 on sheet 3) on 2026-11-09.

## Summary
- Melee hero, 14 life, move 2, **four Red Riders** (melee, 1 life each, move 2, all on the board at the start, none in reserve). Hero fid `eredin`, sidekick group `rider` (`rider1`..`rider4`), slug `eredin`.
- Ability **KING OF THE WILD HUNT**: "While all of your Red Riders are defeated, Eredin is ENRAGED. If Eredin is ENRAGED, add +1 to the value of your combat cards, and your move value is 3." ENRAGED is derived from the roster (no sidekick alive); it is the HeroDef passive `{"effect": "enraged", "combat_bonus": 1, "move": 3}` read by `sparring/enraged.py` (docs/effects-dsl.md, section 36).
- Deck: 30 cards, `CardID = 17600 + idx`. Bands: EREDIN on Backhand, Brutal Strike, Implacable, Portal Defense and Might Of The Aen Elle; **RED RIDER** on Unyielding Hordes (3 copies, played by a Red Rider); ANY on Foul Purpose, Icy Guile, Wild Hunt, Skirmish and Close For The Kill. The deck object in the save holds 31 cards (the 30 plus the character card 350), hence `card_count 31` and `card_ids [350, 17629]` in the catalog.
- Table: bag `9183b3` (inner `7fa54d`), miniature `dd0bc4`, life dial `a0a36e` (max 14, the model with the `Hero Health` script), deck `b0cd3e`, and four Red Rider tokens `a954e5` Maxwell, `bb3949` Aleksei, `63fb79` Adrian, `dc3fc9` Norman (Custom_Token in the save; **real TTS reports them as "Tile"**, nothing that reads or moves a piece looks at the type: tests/test_eredin_human.py checks the by-name lookup and the removal with Tile objects). A Red Rider has 1 life: no dial, it just leaves the board when defeated. No GUID is shared with any other hero.

## Card identity: the shared CardID range
Eredin's deck is sheet 176 like Medusa's, the four turtles', Doctor Strange's, Bigfoot's, Daredevil's, Luke Cage's, Bullseye's, Golden Bat's, Jill Trent's, She-Hulk's and Tomoe Gozen's: the CardIDs repeat and only `deck.identity` (his own image pair in `data/tts/eredin.json`) tells the decks apart. See docs/card-identity.md; `tests/test_hero_eredin_data.py` and the matrix are the proof.

## Cards (as implemented)
1. **Backhand** (attack 4 / boost 3, Eredin): AFTER COMBAT the opponent puts 1 random card of their hand on top of their deck; ENRAGED: they discard it instead. `return_to_deck` / `discard` of `pick: random` on the rival hand (nothing is read). The bot's own hand card is put on top of its deck on the table (not shuffled); the human's is theirs to move (the chat says "pon 1 carta de tu mano encima de tu mazo" or, enraged, "Descarta 1 carta (al azar...)").
2. **Brutal Strike** (attack 2 / 3, Eredin): `uncancelable`. DURING: if the opponent's card has an IMMEDIATELY effect, ignore its value. Plugin test `eredin:opponent_card` (`has_immediately`): the printed text of the rival's card says IMMEDIATELY.
3. **Unyielding Hordes** (attack 1 / 2, **Red Rider**): IMMEDIATELY return a defeated Red Rider to any space (`revive`, 1 hit point); DURING +1 for each other friendly fighter adjacent to the opposing fighter (`modify_value` by `count`).
4. **Icy Guile** (versatile 2 / 1): IMMEDIATELY, if ENRAGED, cancel all effects on the rival's card; DURING you may defeat a Red Rider (the price, `defeat`) to ignore the value of the rival's card (`set_value ... ignore`).
5. **Close For The Kill** (scheme, boost 4): draw 2, move each of your fighters up to 3 spaces, through opposing fighters.
6. **Foul Purpose** (attack 3 / 2, ANY): if ENRAGED you may play it face up to target a fighter in any space (card tag `any_space_if_enraged`); AFTER you may defeat a Red Rider to return it to your hand (`optional` with a `defeat` cost and `put_in_hand` of `this`).
7. **Implacable** (defense 3 / 3, Eredin): if ENRAGED you may play it as an attack (card tag `attack_if_enraged`); DURING you may BOOST it (`may_boost`, attacking or defending).
8. **Might Of The Aen Elle** (scheme, boost 2, Eredin): draw 1, gain 1 action; ONGOING Eredin does not take damage except combat damage or from exhaustion (status `immune_to_effect_damage` on the hero); discard it at the end of your turn if you did not attack (`until end_of_turn` of the owner with `unless_attacked`).
9. **Portal Defense** (defense 0 / 1, Eredin): IMMEDIATELY Eredin swaps spaces with an adjacent friendly fighter, which is now the defender (`swap` + plugin `eredin:replace_combatant`, Houdini's mechanism); AFTER, if ENRAGED, draw 2.
10. **Wild Hunt** (versatile 3 / 2): AFTER deal 1 damage to each opposing fighter adjacent to at least one of your fighters; ENRAGED: 2.
11. **Skirmish** (versatile 4 / 1): word for word Bigfoot's and Tomoe Gozen's (Golden Bat's reads slightly differently).

## Discrepancies with unmatched-memory
- **Might Of The Aen Elle** has an ONGOING (immunity to effect damage, discarded at the end of the turn without an attack) that unmatched-memory dropped: the real card (the image) wins.
- Portal Defense ("ow the defender") and Icy Guile ("Red Riper") are typos in unmatched-memory; the overlay carries the real text. Close For The Kill has a line break unmatched-memory prints between its two sentences; the card reads as one paragraph.
- Titles are lower case in unmatched-memory ("Brutal strike"); the cards print them in capitals (the overlay uses `memory_title` to bridge).

## Engine additions (all additive, docs/effects-dsl.md section 36)
The op `defeat`; the `until` flag `unless_attacked`; `target: "hero"` on an ONGOING status; the HeroDef passive `enraged` and the two card tags (`sparring/enraged.py`); `Game.defeat`, `Game.can_declare_attack`, `Game.can_attack(card=)`; `plays_face_up(card, game, attacker, target)`; the plugins `eredin:replace_combatant` and `eredin:opponent_card` (`sparring/effects/plugins_eredin.py`); a random card of the bot's hand put on top of its deck on the table; the panel names the four Red Riders by their miniatures; the bot never moves a miniature the human was told to place.

## Rule decisions (taken without a ruling: the most literal reading, applied)
1. **ENRAGED is checked live**: the condition is "no Red Rider alive" at the moment each effect, bonus or move is read. The +1 is added to a card when it is revealed; a Red Rider that falls in the middle of a combat (the price of Icy Guile) gives the card in play the +1 at once; one that comes back in the middle of a combat does not take it back.
2. **The +1 goes to every combat card the owner plays**, attack or defense, whichever fighter plays it (it does not apply to a BOOST card or to a value set by an effect after: `set_value` replaces the printed value and keeps the bonuses, as for every hero).
3. **Move value 3**: Eredin's own Maneuver and the engine's free-move rules use it; an effect that says "move up to N" is not changed.
4. **"Defeat a Red Rider"** is no damage: nothing that stops or changes damage applies (Might Of The Aen Elle does not protect the Rider). The owner chooses which Red Rider (the one playing the card included). With none alive the option does not exist.
5. **Unyielding Hordes**: the IMMEDIATELY is mandatory (a defeated Red Rider is returned to a space the owner chooses, with 1 hit point); the DURING counts after it, so the returned one counts when it stands next to the opposing fighter. The human places the miniature by hand; until the table is read the engine counts it next to the opposing fighter (the best case) when a free space is.
6. **Foul Purpose, far shot**: no range, no line of sight; the target is any opposing fighter. It is played face up (the defense is chosen knowing it) only when the target is out of the usual reach; against a target in reach it is an ordinary attack. The AFTER "defeat a Red Rider to return this card" needs a Red Rider, so it cannot be used while enraged (there are none).
7. **Implacable as an attack**: only while enraged; its printed value 3 (+1 from the rage) and its free BOOST apply as an attack. A defense card of the human played face down as an attack with Eredin not enraged is refused at the Reveal ("Carta ilegal").
8. **Brutal Strike** reads the PRINTED text of the opponent's card (a card whose IMMEDIATELY was cancelled or is conditional still "has an IMMEDIATELY effect"); with no opponent card there is nothing to ignore. Its own effects cannot be cancelled by anything (Icy Guile's cancel, the rival's).
9. **Portal Defense**: the swap is not optional (the card says "swaps") but needs an adjacent friendly fighter (with none, nothing happens); the new defender gets the card's value and AFTER effects and takes the combat damage; the attacker's card stays aimed at the same space. The AFTER draw reads ENRAGED when it resolves.
10. **Might Of The Aen Elle**: the immunity covers `effect` damage (effects of both players); combat damage and exhaustion hurt him (the card says so); **map hazard damage is not stopped** (the engine tells it apart from effect damage: open question). It lapses at the end of the owner's turn only if the owner took no attack action in that turn (any of his fighters); when he attacked it stays through the rival's turn and the next turn of the owner decides again. Like every ONGOING it is replaced by the next one the player plays.
11. **Wild Hunt**: effect damage to every opposing fighter (hero or sidekick) adjacent to at least one friendly fighter alive at the AFTER (the fighter that played the card and a sidekick included); a fighter the combat just defeated is not there.
12. **Close For The Kill**: every friendly fighter alive moves up to 3 spaces (0 included), may cross opposing fighters and never ends on one; sidekicks are asked before the hero (the order every `move` over several fighters uses).
13. **Backhand**: with an empty hand nothing happens; the card taken is random (the human's is theirs to pick by position: the chat gives the number, like every random discard).

## Open questions for Iván
1. **Hazard damage and Might Of The Aen Elle.** "Eredin does not take damage except combat damage or from exhaustion": read literally a map hazard does not hurt him either. The engine tells hazard damage from effect damage and today it is NOT stopped. Alternative: stop it while the card is in play (one line in `modifiers.adjust_damage`).
2. **The rage in the middle of a combat.** Applied: a Red Rider that falls to Icy Guile's price enrages him at once and the card in play gets +1; a Red Rider that returns (Hordes) does not take it back. Alternative: the state is fixed when the cards are revealed.
3. **Foul Purpose, face up or not.** Applied: face up only when the target is out of the usual reach. Alternative: always face up whenever he is enraged (as the card reads: "you may play this card face-up").
4. **Icy Guile's price with a Rider that plays the card**: the card's own Red Rider may be the one defeated. Alternative: only another one.
5. **Portal Defense is mandatory** (the swap) and the new defender is chosen by the owner among the adjacent friendly fighters. Alternative: optional, or only Red Riders.
6. **Brutal Strike and a cancelled IMMEDIATELY**: the printed text counts. Alternative: only an IMMEDIATELY that actually resolved.
7. **Hordes placed by the human** is counted as if next to the opposing fighter; the human should place it there to get the +1 (the chat does not say so).

## AI
- The AI profile comes from the data (Eredin `hero`, melee; the Red Riders `striker`, 4 of them). Card values live where the other heroes' do (`ai_medusa.card_value` and friends): Might Of The Aen Elle is valued by the ONGOING slot (`ongoing.worth`: an immunity status), Wild Hunt and Skirmish by their AFTER ops through the generic simulation.
- The price of a Red Rider is decided by `EffectAI._fighter_pays`: for Icy Guile it is paid when the damage the combat swings reaches `RIDER_PRICE` (2), counting `ENRAGE_BONUS` (2) when it is the last Rider (the rage is worth +1 to every card and a longer move) or when it decides a kill; for Foul Purpose it is paid while at most `RIDER_KEEP` (2) Riders are left or when it enrages him. Which Rider goes is the cheapest to lose (`hp_change`).
- Enraged the bot attacks with Implacable as an attack and aims Foul Purpose at any fighter (`MedusaAI.attack_acts`, the search's `_attack_moves` / `_attack_titles` / `to_act` through `Game.can_declare_attack` and `enraged.may_attack_with`).
- The bot never plays a Red Rider's Unyielding Hordes unless a Red Rider can attack (the card is `RED RIDER` only).

## Strength (simulator, heuristic AI, bprd-hq)
Information only; see the simulation block at the end of this file.

## Tests
- `tests/test_eredin_effects.py` (bot side: the ability, every card, the AI's offers), `tests/test_eredin_human.py` (the panel, both seats), `tests/test_eredin_matrix.py` (full games against every other hero in both seats, FakeTTS and simulator), `tests/test_hero_eredin_data.py` (data, card identity, the table data).
