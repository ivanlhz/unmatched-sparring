# Daredevil (Marvel, Hell's Kitchen)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 of the tournament savegame, character card 338 on sheet 3) on 2026-11-07.

## Summary
- Melee hero, 17 life, move 3, **no sidekick**. Hero fid `daredevil`.
- Ability (DURING COMBAT): if you have 2 or fewer cards in your hand, you may BLIND BOOST your attack or defense. "If you have other DURING COMBAT effects, choose the order."
- Deck: **22 playing cards**, `CardID = 17600 + idx` (17600-17621), every card carries the DAREDEVIL band. The deck object in the save holds **23** cards (the 22 plus the character card 338): that is correct, CONFIRMED by Iván on 2026-11-07, it is not a broken deck. `data/catalog/heroes.json` says `card_count 23, card_ids [338, 17621]` and `HeroDef.deck_size` is 22 (the usual 30 for every other hero).
- Table: miniature `ae91f4` (Custom_Assetbundle), life dial `cfc705` (max 17). No piece GUID is shared with another hero.

## Card identity: the shared CardID range
His deck is sheet 176 like Medusa's, the turtles', Doctor Strange's and Bigfoot's: CardIDs 17600-17621 repeat there, with a different image (`data/tts/daredevil.json`, `deck.identity`). Nothing reads a card by a bare CardID (docs/card-identity.md); the new code follows the same rule (cards are taken from `game.players[owner]`, requests carry `card_owner`). The only new fact is the size: `HeroDef.deck_size`, read by `hero_table` (range check) and `tools/import_save.py` (`deck_sheet(deck, size)`), so a 22-card deck is found and validated like a 30-card one. Proof: `tests/test_hero_daredevil_data.py` (ranges, images disjoint from every other sheet-176 deck, no equal card across decks, detection in both seats against eleven heroes, the catalog's 23), `tests/test_card_identity.py` (Daredevil is in `SHARING`, his range is (17600, 17621)) and `tests/test_daredevil_matrix.py`.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| Devil of Hell's Kitchen | attack | 4 | 3 | 2 | DURING: with no cards in your deck the value is 8 instead. AFTER: shuffle this card and the last 4 cards that reached your discard pile into your deck (5 cards in all) |
| Man Without Fear | attack | 2 | 3 | 2 | DURING: you may BLIND BOOST this attack (in addition to the ability's) |
| Feint | versatile | 2 | 1 | 3 | IMMEDIATELY: cancel all effects on the opponent's card |
| Grappling Hook | versatile | 3 | 2 | 3 | AFTER: move Daredevil up to 2 spaces |
| Take A Knee | versatile | 3 | 2 | 3 | AFTER: discard the top card of your deck; Daredevil recovers its BOOST value |
| Son Of A Boxer | defense | 3 | 2 | 3 | AFTER: if you lost the combat, 2 damage to a fighter adjacent to Daredevil |
| Through Adversity | scheme | - | 2 | 3 | Move Daredevil up to 4 spaces through opposing fighters; 1 damage to each opposing fighter he moved through |
| Breather | scheme | - | 2 | 3 | Return an attack, defense or versatile card from your discard pile to your hand |

## Discrepancies with unmatched-memory
None in the cards: titles, types, values, boosts, copies and every text agree with the card images word for word. The only differences are structural: unmatched-memory counts 22 copies and the save object holds 23 cards (22 + the character card); its `sidekicks` holds one empty entry (the importer skips it).

## Engine additions (all additive, docs/effects-dsl.md section 29)
`ability.during` (the hero's own DURING COMBAT effects: `[{id, condition?, ops}]`) with `ops_combat.during_with_ability` and the rule `dsl_during_hero_ability`; CardSel `pick: last`; `HeroDef.deck_size`; the `confirm` flag of `EffectRun.ask`; the plugin file `plugins_daredevil.py` (`daredevil:blind_boost` is Doctor Strange's plugin under Daredevil's id, `daredevil:take_a_knee`); `plugins_strange.discard_top` (the shared "discard N cards from the top of the deck" the BLIND BOOST now uses); a `pick: all` selector over a path nobody saw asks the human which fighters (`select.pick_fighters`); in `session_blind` the one-button `top_discard` request next to the BLIND BOOST declaration.

## The special ability: BLIND BOOST with 2 or fewer cards in hand
Written as data, `ability.during[0]` of `data/heroes/effects/daredevil.json`: under the condition `hand_size <= 2` the plugin `daredevil:blind_boost` (`times: 1`, `ability: true`) runs in the DURING of every combat in which the owner played a card, attacking or defending. The blind boost is Doctor Strange's rule for this repo (docs/heroes/doctor-strange.md, "BLIND BOOST"): the owner DECLARES the count (0 or 1) before anything is seen, then the cards are discarded from the TOP of the deck and their BOOST added automatically; a short deck discards what is there; an empty deck asks nothing.

- **Hand size**: counted when the DURING resolves. The card being played has already left the hand (it is at the combat spot); the cards of a free BOOST come out of the hand later. So "2 or fewer" means the hand after playing the card.
- **The ability is on the hero, not on the card.** A rival's Feint, Mists... that cancels the effects of his card does NOT cancel the ability: a cancelled side still gets the ability's DURING (`combat_flow.dsl_during_hero_ability`, which only runs for a cancelled side of a hero with `ability.during`). Without a card played (defending with nothing) there is no attack or defense to boost and nothing is asked.
- **The order** ("choose the order"): when the ability applies AND the card has DURING ops of its own (Man Without Fear's blind boost, Devil of Hell's Kitchen's value 8), the owner chooses (`choose_effect` of the two orders, request flag `during_order`; the labels are "ability first, then the card" and "card first, then the ability"). With no DURING of the card, or a hand over two, nothing is asked. It matters for the Devil: the ability first can take the last card of the deck and make it worth 8.
- **Bot**: `EffectAI._blind_boost` picks the count (ability and card alike) by expected score over its own deck; for the Devil with a blind boost that would empty the deck it counts the +4 (8 instead of 4). The order is always "ability first" (never worse: nothing in his cards is hurt by a blind boost done earlier). A rollout (`SyntheticChooser`) declares the largest count that cannot overshoot a limit.
- **Human**: buttons "0 / 1" only when it applies and only then, named "la habilidad especial de Daredevil" in the chat (`blind.ability_name`); the bot moves the real top card of the human's deck to their discard pile (`lua.deck_top_to_discard`), reads its CardID and adds its BOOST. If the table refuses the chat asks them to lay the card by hand (`pile_mode: blind`). The declaration is a parked choice: it survives `--resume`.

## Devil of Hell's Kitchen
Real text: "Shuffle this card and the top four cards of your discard pile into your deck." Iván (2026-11-07): as printed, 5 cards in all: itself plus the 4 that most recently reached the pile. So two `return_to_deck` ops, both `shuffle`: the 4 cards that most recently reached the discard pile (new CardSel `pick: last`, newest first) and then `this` (still at the combat spot, zone `combat`, as Relentless / Raphael's cards). "Last played" is the order in which cards reached the discard pile: the engine's `PlayerState.discard` is a list that only ever appends (boosts and blind-boosted cards of this combat are already in it, the played card arrives last), so the order is tracked for free. For the human's pile the engine learns arrivals when it reads the table: cards that appear between two readings are ordered by CardID (open question below).
The DURING reads the deck as it is when the card resolves (`not exists deck`).
- **Table**: the discard cards are moved by the bot by GUID into the human's deck and the deck is shuffled (`_human_discard_to_deck`, same as Pancakes! / Searing Clarity), then the card at the combat spot goes in and the deck is shuffled again (`combat_card_to_deck`, as Raphael's cards): two shuffles, same distribution as one.

## Take A Knee
`daredevil:take_a_knee` discards the top card of the owner's deck face up and binds it; the heal is plain DSL (`heal hero by {attr boost of $knee}`, capped at his maximum). An empty deck discards and heals nothing. The bot reads its own deck. For the human the engine does not know their deck: the panel shows ONE button ("1", prompt "Take A Knee: press to discard the top card of your deck (...)"; `EffectRun.ask(..., confirm=True)` so a single forced option is still asked), the bot then moves the top card to their pile (the same `session_blind` path as the BLIND BOOST) and the heal uses its real BOOST. Refused table: the usual `cards` fallback (lay the top card by hand). Survives `--resume`.

## Through Adversity: the jump
Written like Donatello's Party wagon! (docs/heroes/donatello.md, decision 5): `move` of `hero` up to 4 with `through_enemies`, `as: mover`; then `damage 1` to `{side: enemy, filter: {passed_by: $mover}, pick: all}`. "Moved through" is an opposing fighter on some path of at most 4 spaces from where he started to where he ended.
- **Bot**: the engine knows the path, every fighter passed takes 1 automatically (all of them). The bot chooses the square valuing the damage to the fighters passed (CONFIRMED by Iván 2026-11-07): `EffectAI._dest_with_pass_damage` scores each destination as position value minus hazard plus the blow value of 1 damage on each rival crossed (`blow_value`: the AI's usual weights, a kill worth `kill_value`, so finishing 1-HP sidekicks or a 1-HP hero is worth a lot). Its usual square is one of the candidates, so with nothing to gain it keeps that one. The scheme's value is the simulation (`scheme_outcome` + `material_delta`), which goes through that same choice, so the bot plays Through Adversity when the jump kills. Unlike Party wagon! (donatello.md, decision 5) it does plan for the damage.
- **Human**: they walk the miniature by hand and the engine cannot see the path. After the move the panel asks which opposing fighters he passed through: one button per opposing fighter plus "None" (a multi-pick: press each one he passed, then confirm), and each fighter named takes 1 damage. New in `select.pick_fighters`: a `pick: all` selector with an unseen path asks the human instead of hitting every rival.

## Breather
`put_in_hand` of one non-scheme card of the owner's discard pile (the same selector as Donatello does machines). Public information: the bot reads the pile; the human picks on the panel and takes the card back to their hand themselves (the chat says "pick up ...").

## Rules decisions
1. The ability is read as the hero's, not the card's: it survives a cancellation of the card's effects (see above).
2. "2 or fewer cards in your hand" counts the hand after the card was played.
3. Son Of A Boxer: "a fighter adjacent to Daredevil" is any fighter (the owner chooses; with no sidekick only the rival's can be there). "If you lost the combat" follows the engine: a tie is lost by the attacker.
4. Grappling Hook moves Daredevil up to 2 spaces after the combat; if he was defeated nothing happens.
5. Take A Knee heals the BOOST of the discarded card (0 for none) and stops at 17. As a defense it heals after the combat.
6. Devil of Hell's Kitchen: 5 cards in all (itself + the 4 most recent of the pile; CONFIRMED by Iván on 2026-11-07, as printed); fewer if the pile is short. A cancelled Devil (Feint) shuffles nothing and keeps the value 4 (its DURING is cancelled too).
7. Through Adversity: the path is not fixed, every rival on some path of at most 4 spaces counts; the human names who. The bot picks its square for the damage it deals, kills first, see above (CONFIRMED by Iván 2026-11-07).
8. Breather offers every non-scheme card of the pile; with none there is nothing to return.
9. The human's discard order is read from the table; several cards laid between two readings are ordered by CardID (CONFIRMED by Iván 2026-11-07 as acceptable; a physical read of the pile would refine it).
10. The ability survives a cancellation such as Feint (it is on the hero; CONFIRMED by Iván 2026-11-07).
11. The order labels are English text in the effects file, shown as is in the Spanish panel (CONFIRMED by Iván 2026-11-07).
12. Take A Knee for the human needs one press so the bot can move the real top card (CONFIRMED by Iván 2026-11-07).
13. A deck of 1 card with the ability: declaring 1 empties the deck; with Devil of Hell's Kitchen and the ability first the Devil is worth 8 that combat (CONFIRMED by Iván 2026-11-07, as written).

## Open questions for Iván
- Order of the ability versus the card DURING COMBAT: still open (the engine asks the owner which goes first).

## AI
The AI profile comes from the data (one fighter, role `hero`). The bot's hints: BLIND BOOST by `EffectAI._blind_boost` (with the Devil's +4 when the boost empties the deck, ability first), Take A Knee and Breather valued as any heal and recover effects, Through Adversity as any scheme (simulated), Son Of A Boxer as a defense with an AFTER hit. Simulator check (`python -m sparring.sim`, heuristic AI, 20 games per opponent against the simulator's scripted player, 2026-11-07): Daredevil as the bot won 182 of 240 games (76 %), between 11/20 (Hellboy, Raphael) and 20/20 (Donatello), with no error and no unfinished game; for comparison Doctor Strange won 20/20 and Bigfoot 19/20 against Hellboy under the same player. The bot uses all eight cards (Through Adversity, Breather, Take A Knee, the Devil and Man Without Fear appear in real plays) and the ability applies in about 40 % of its combat plays. Tests below.

## Tests
`tests/test_hero_daredevil_data.py` (data, 22-card deck, card identity, catalog's 23), `tests/test_daredevil_effects.py` (every card, the ability, the order, the Devil's empty deck and shuffle, the bot's declaration), `tests/test_daredevil_human.py` (FakeTTS, the panel: declaration, order, Take A Knee's button and table move, Devil's shuffle by GUID, Through Adversity by hand, Breather, resume), `tests/test_daredevil_matrix.py` (full games against the twelve other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
