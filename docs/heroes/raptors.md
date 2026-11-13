# Raptors (Jurassic Park: InGen vs. Raptors)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 176 for the 30 cards, sheet 3 index 13 for the character card of the tournament savegame) on 2026-11-13.

## Summary
- Melee, 7 life and move 3 **each**: three Raptors, Blue, Delta and Echo. HeroDef slug `raptors`, fighters `blue` (name "Raptor Blue"), `delta` and `echo`.
- Ability: "Raptors add 1 to the value of their attack cards for each of your other Raptors adjacent to the defender." Implemented as the HeroDef passive `{"effect": "pack_bonus", "n": 1}` read by `sparring/pack.py` (below).
- Deck: 30 cards, `CardID = 17600 + idx`, every card band ANY (read from the images; unmatched-memory has no bands). The deck object in the save holds 31 cards (the 30 plus the character card 313), hence `card_count 31` in the catalog. Every card carries the tag `raptors` (overlay): Feint (band ANY, same numbers and text) is also Doctor Strange's idx 16 card, and no two cards of different decks may compare equal (docs/card-identity.md).
- Table: bag `230e58` (inner `9f42d9`), deck `ab0add`, three miniatures (Custom_Assetbundle, description "Hero": `1a2945` Raptor Blue, `4573de` Raptor Delta, `b5c3d5` Raptor Echo) and three life dials (Custom_Model "Hero Health", MAX_VALUE 7: `950174`, `c93049`, `deff03`). No token, no counter dial, no GUID shared with another hero.

## The design: one hero fighter and two team members
The character card says HERO: RAPTORS (one card, 7 life, move 3) and the save has three "Hero" miniatures with a Hero Health dial each. The engine models one hero plus sidekicks (`game.hero(player)` has 120 callers, the AI's hero model, the win condition), so:
- **Blue is the hero fighter; Delta and Echo are sidekick entries flagged `team: true`** (`SidekickDef.team`, `HeroDef.team`). The overlay carries them as sidekicks with 7 life, move 3, melee; the AI profile calls them strikers, so every sidekick mechanism (policies, strikers' reward, the guard) already applies.
- **The loss rule of a team**: the owner is beaten only when ALL three are defeated (`Game._fall`). When Blue falls the first Raptor still standing becomes the hero fighter (`Fighter.hero` moves, `Game._succeed`; `Game.hero` repeats it for a game loaded from a save, which does not keep the flag), so every "the hero" question still has an answer while the game goes on.
- Why not three hero fighters: every caller of `game.hero` and every AI term that assumes "one hero, the game ends when it falls" would have to learn "several". The flag is two fields and one rule.

## The pack bonus (`sparring/pack.py`)
`Game.attack_bonus_parts(fighter, target)` and `Game.attack_bonus(fighter, target)` (what the AI uses to measure a threat) add `n` for every OTHER undefeated Raptor of the attacker's owner standing on a space adjacent to the defender (the board's adjacency, not the zone). They label it PACK BONUS in the combat line. The attacker itself never counts, a defeated Raptor does not, a rival fighter does not, and only attacks get it ("their attack cards": a versatile card played as an attack, never a defense). It is read when the card is revealed, like the high ground. A question without a target (the AI estimating a threat in general) reads 0.

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|
| Eviscerate | attack | 5 | 3 | 2 | none |
| Pack Hunters | attack | 4 | 2 | 2 | AFTER: if you won, 1 damage to the opposing fighter for each of your Raptors adjacent to it (the attacker counts when it is adjacent) |
| Clever Girl | attack | 3 | 3 | 3 | AFTER: if one or more of your Raptors is adjacent to the opposing fighter, gain 1 action |
| Disengage | attack | 4 | 2 | 2 | AFTER: place the Raptor on another space of her zone (Bigfoot's Disengage, data word for word) |
| Ambush | attack | 2 | 3 | 3 | DURING: the opponent discards 1 random card; its BOOST is added to this card's value |
| They Remember | attack | 2 | 2 | 4 | AFTER: gain 1 action |
| Feint | versatile | 2 | 1 | 3 | IMMEDIATELY: cancel all effects on the opponent's card |
| Eaten Alive | versatile | 4 | 2 | 3 | AFTER: if you won, 1 damage to one opposing fighter adjacent to the Raptor |
| Decoy | defense | 3 | 1 | 4 | IMMEDIATELY: may place another undefeated Raptor adjacent to the opposing fighter |
| Coordinated Attack Pattern | scheme | - | 2 | 2 | choose one Raptor; may place each of the other two in any space of its zone |
| Working Things Out | scheme | - | 2 | 2 | each Raptor moves up to 3, through opposing fighters; gain 1 action |

## Discrepancies with unmatched-memory
- **Disengage** reads "Move your Raptor to any other space in her zone" on the card; unmatched-memory has Bigfoot's wording ("Choose an empty space in this fighter's zone. Place this fighter in that space"). The overlay carries the printed text; the effect is the same data as Bigfoot's (the fighter must change space, the space must be empty).
- **Ambush** reads "this card's value" (unmatched-memory: "attack value").
- unmatched-memory lists one hero (7 life, move 3, no sidekicks); the save has three miniatures with a dial each.
- Titles, types, values, boosts and copies of all 11 titles match unmatched-memory (30 cards).

## Rule decisions (taken in the owner's absence, the most literal reading)
1. **Loss**: all three Raptors defeated (see above). The card does not say; see "Pending Ivan".
2. **Pack Hunters** counts every Raptor adjacent to the opposing fighter when the AFTER resolves, the attacker included if it stands next to the defender ("each of your Raptors adjacent to them"). Effect damage, 0 when nobody is adjacent. A Raptor defeated in the combat is not counted.
3. **Eaten Alive**: "adjacent" is adjacent to the Raptor that played the card; the owner chooses which of the opposing fighters there is hit; a won defense counts as winning (the global tie rule: the attacker wins only when combat damage lands).
4. **Decoy** moves one of the OTHER undefeated Raptors (never the one that plays it) to an empty space adjacent to the opposing fighter, optionally; with no free adjacent space nothing happens. It resolves before the DURING, so it matters for what the DURING reads, not for the pack bonus of the rival (the rival has none).
5. **Coordinated Attack Pattern**: one option per Raptor (the DSL has no op that binds a chosen fighter), then a yes/no and a space for each of the other two. The chosen Raptor never moves. Choosing a defeated Raptor does nothing (the panel lists all three).
6. **Working Things Out**: each undefeated Raptor moves up to 3 spaces (0 included), through opposing fighters but never ending on one; the owner picks the order; the action is gained once. For the human every move is by hand (the same op as Eredin's Close For The Kill).
7. **Ambush**: the discard is by chance and the bonus is the discarded card's BOOST (0 for a card with none, nothing with an empty hand). Cancelling the card's effects (Feint) cancels the bonus.
8. **Clever Girl** is read when the AFTER resolves, win or lose. With a melee attacker the Raptor that played it is normally adjacent, so the action is almost always gained.
9. **Exhaustion** as everywhere: an empty deck deals 2 to each of the three Raptors.

## Pending Ivan
1. **Does the owner lose when ALL three Raptors are defeated, or when ANY one is?** Implemented: all three (unmatched-memory and the card print one hero, RAPTORS; the save has three hero miniatures with a dial each). One line in `Game._fall` flips it.
2. **Ambush against a human**: the engine cannot name the card the human discards at the table (the discard is theirs and the bot never looks at their hand), so against a human opponent the BOOST is not added (the chat says "Aplicado: Ambush: sin efecto"). Against the bot it works. Alternative: the human tells the bot the BOOST value.
3. **Who is the hero fighter once Blue falls**: the first Raptor standing (Delta, then Echo). It only matters for rival cards that say "the hero".
4. **Coordinated Attack Pattern** offers the three Raptors as three options and asks yes/no per other Raptor; a single "choose a Raptor" request would be neater but needs a new DSL op.
5. **Bands**: all 30 cards read ANY from the images.

## AI
Everything is data-driven (`ai_profile`: Blue `hero`, Delta and Echo `striker`) plus the passive `pack_bonus`; nothing names a hero. The live bot is ISMCTS (`--ai ismcts`), so everything below is in `sparring/search/adapter.py`.
- **Swarm** (Iván: super aggressive): the followers (Delta, Echo) get a placement policy of their own, `pack` (`pack_dest`): each goes to a free space next to the rival that the hero stands (or ends) nearest to, the nearest of those to itself, so every Raptor stands beside the defender. It is offered in the tree and in the rollouts only to a hero with the `pack_bonus` passive.
- **Attacks every turn it can**: with a blow to land the pack never spends its last action on a Maneuver (`_generate_moves`), and with an action to spare it may only walk to join the blow (`_placements`: policy `pack`, the hero to a space he strikes from). Measured (`tests/test_raptors_ai.py`): the search attacks in every turn where it has a card and a rival in reach, and ends with another Raptor next to the defender in about half of the attacks that could have one (19 % before).
- **Zone damage of a rival hero** (F-RIVAL-ZONE-DAMAGE, `sparring/ai_hazards.py`): for any other hero the price is the dearest of the fighters the rival picks from; for a team, `zone_exposed` lists EVERY Raptor standing in the rival's zone and the price is per fighter and adds up (each one is a target, they have 7 life each, and the game is lost only when the last one falls). Used by the search's `threat()` (`_zone_exposure`) and by the heuristic's `zone_hazard_cost`. Against Medusa (20 games, `_metrics`): 0.46 Raptors in her zone at the end of the bot's turns, against 0.57 with the awareness off and 0.59 with the old hero-only price; against a rival with no zone damage the price is 0 and they attack as before.

## Tests
`tests/test_hero_raptors_data.py` (data, card identity, the shared range, detection, GUIDs), `tests/test_raptors_effects.py` (the team, the loss rule, the pack bonus, every card on the engine), `tests/test_raptors_human.py` (the panel: the human's attacks, schemes and Decoy; the bot's Raptors against a human), `tests/test_raptors_ai.py` (ISMCTS: attack rate, pack adjacency, the zone-damage rival), `tests/test_raptors_matrix.py` (full games against every other hero in both seats).
