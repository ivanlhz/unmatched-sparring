# Card effects DSL (canonical schema, version 1)

Closed specification of `data/heroes/effects/<slug>.json`. It is enforced by `data/heroes/effects/schema.json`
(JSON Schema) and `tools/validate_effects.py` (schema + semantic checks). The interpreter
(`sparring/effects/`, step 4-6 of the plan) must read ONLY what is here; what does not fit goes to a declared
`plugin`. Whatever the file does not say, the engine does not guess.

Text conventions: "owner" is the player who plays the card or who the ability belongs to;
"opponent" is the other player. In abilities, `this` is the hero.

## 1. File structure

```json
{
 "schema": 1,
 "hero": "<slug>",
 "notes": ["..."],
 "ability": {
  "text": "literal text of the hero card",
  "counters": {"intuition": {"min": 0, "max": 2, "start": 0}},
  "triggers": [Trigger],
  "passives": [Passive],
  "notes": "..."
 },
 "cards": [Card],
 "plugins": [{"id": "<slug>:<name>", "why": "..."}],
 "hidden_info": [{...}],
 "open_questions": ["..."],
 "discrepancies": [{...}],
 "table": {...}
}
```

- `schema`: always `1`. Changing the schema raises the number and the validator rejects what it does not know.
- `hero`: slug equal to that of `data/heroes/<slug>.json` (HeroDef). The validator cross-checks titles, copies and text.
- `ability.counters`: the hero's token counters (intuition tokens, rage, coils). Pile counters
  (destiny) stay in the HeroDef (`counters` + `forms`); from here they are only read (`{"counter": "destiny"}`).
- `plugins`: every `{"op": "plugin"}` or `{"kind": "plugin"}` uses an id from this list and every id in the list is used.
- `hidden_info`, `open_questions`, `discrepancies`, `table`, `notes`: free documentation; the validator only
  requires the basic types.

### Card

```json
{
 "title": "Second Shot",
 "copies": 2,
 "text": "DURING COMBAT: You may BOOST this attack.",
 "may_boost": true,
 "uncancelable": false,
 "effects": {"immediately": [], "during": [], "after": [], "scheme": [], "boost": []},
 "ongoing": null,
 "notes": "..."
}
```

- `title`, `copies` and `text` match the HeroDef (the text is that of the real card).
- `may_boost` (optional, false by default): the card allows boosting its own attack in the DURING at no cost
  ("You may BOOST this attack", "You may BOOST this card"). It is the field that replaces the text detection of
  `combat.can_boost`. It is not repeated as an op: a card with `may_boost` carries no `boost` on `this` in `during`, and
  a scheme cannot carry it. It holds in any combat in which the card is played: Second Shot is attack only,
  but Out Of Time is versatile and, played in defense, boosts the defense (today the engine only contemplates the boost of the
  human's attack; the interpreter must cover both sides).
- `uncancelable` (optional, false by default): `cancel_effects` does not erase the effects of this card.
- `effects`: the five moments, always present and always lists (empty if there is nothing):
  - `immediately`, `during`, `after`: combat. The defender resolves first at each moment.
  - `scheme`: when playing a scheme (one action). Only on cards of type scheme; the other three are empty on schemes.
  - `boost`: when THIS card is discarded as a boost card (Houdini's "BOOSTED WITH").
- `ongoing` (permanent schemes only): the card stays in play until `until`.

```json
"ongoing": {
 "modifiers": [Modifier],
 "triggers": [Trigger],
 "until": Event
}
```

## 2. Common grammar

### 2.1 Players (PlayerSel)

String: `owner` | `opponent` | `attacking_player` | `defending_player` | `all` (only in `reveal.to`) | `$var`.

### 2.2 Fighters (FighterSel)

Object; everything optional unless stated. String = shortcut for `role`.

| field | values | meaning |
|---|---|---|
| `role` | `this`, `hero`, `opposing`, `attacker`, `defender`, `combatant`, `$var` | `this`: the fighter that plays the card (in abilities, the hero). `hero`: the owner's hero. `opposing`: the other fighter of the combat. `combatant`: one of the two (`chooser` chooses). |
| `side` | `own`, `enemy`, `any` | relative to the owner. Required if there is no `role`: "any fighter" is written `{"side": "any"}`, never `{}` |
| `kind` | `hero`, `sidekick`, `any` (default `any`) | |
| `name` | fighter name from the HeroDef ("Koschei", "Harpy") | |
| `where` | SpaceSel | where it is |
| `other` | bool | excludes `this` (and the reference fighter of `where`) |
| `state` | `alive` (default), `defeated` | |
| `filter` | `{"attacked_this_turn": bool}` | rare predicates |
| `pick` | `one` (default), `all` | `one`: if there are several, `chooser` chooses. `all`: all of them, in the order the chooser says |

Examples: "an adjacent fighter" = `{"where": {"adjacent_to": "this"}}`; "each other fighter in your fighter's
zone" = `{"where": {"zone_of": "this"}, "other": true, "pick": "all"}`; "each friendly fighter" =
`{"side": "own", "pick": "all"}`; "a defeated Harpy" = `{"side": "own", "name": "Harpy", "state": "defeated"}`.

A `pick: one` selector with no candidates does nothing (the op is skipped); with `pick: all` it applies to zero.

### 2.3 Spaces (SpaceSel)

Object with any of: `any: true` | `zone_of: FighterRef` | `adjacent_to: FighterRef` | `space_of: FighterRef`
| `nearest_to: FighterRef` | `start_space_of: PlayerSel` | `empty: bool` (default true for placing). FighterRef is
a `role` string (`this`, `hero`, `opposing`, `attacker`, `defender`, `$var`).

### 2.4 Cards (CardSel and CardRef)

CardRef (string): `this` (the card being resolved), `opponent_card`, `attack_card`, `defense_card`, `$var`.

CardSel (object):

| field | values | meaning |
|---|---|---|
| `zone` | `hand`, `discard`, `deck`, `in_play` | required. `in_play`: permanent schemes on the table |
| `player` | PlayerSel | required |
| `filter` | see below | |
| `pick` | `chosen` (default), `all`, `random`, `top`, `bottom` | `chosen`: `chooser` chooses. `random`: chance (there is no "random" chooser). `top`/`bottom`: only in `deck` (the hand has no order) |
| `amount` | Amount | how many; default 1. Forbidden with `pick: all`. If there are fewer candidates, it is cut down to those there are |
| `up_to` | bool (default false) | the chooser may take fewer (0 included). Only with `pick: chosen` |
| `chooser` | PlayerSel (default `owner`) | only with `pick: chosen` |
| `except` | CardRef | leaves out those bound to that name |

CardFilter: `{"type": ..., "type_not": ..., "tag": ..., "tag_not": ..., "title": ..., "fighter": ...}`.

Hidden information: `hand` and `deck` are hidden zones. A CardSel on one of them with `pick: chosen` and a
`chooser` different from `player` is only legal if earlier in the same ops list (or in one that contains it) there was a
`look_hand` (hand) or a `look_deck`/`search_deck` (deck) on that player. The validator checks it. There is no need
to look with `pick: random | top | bottom` (nothing is chosen), with a `chooser` equal to the zone's owner, nor to
count: the `exists` test and the `count_cards` Amount on a foreign hand or deck neither choose nor show anything
(Loki and Krang need them). The discard and `in_play` are public.

### 2.5 Amounts (Amount)

An integer, a numeric event binding (`"$amount"`, see 2.10), or one of these objects (all admit
`times: int` as a multiplier):

- `{"attr": "boost" | "value", "of": CardRef}`: attribute of a bound card (`{"attr": "boost", "of": "$fuel"}`).
- `{"count": FighterSel}` or `{"count_cards": CardSel}`: how many meet the selector.
- `{"counter": "<name>", "player": PlayerSel}`: counter of the HeroDef or of `ability.counters` (default `owner`).
- `{"stat": ..., "player"|"fighter": ...}` with stat in `hand_size`, `hp`, `max_hp`, `actions_taken_this_turn`,
  `damage_dealt_this_combat`, `damage_taken_this_combat`.

### 2.6 Who chooses (chooser)

`owner` (default) | `opponent` | `$var` (player binding). It appears in everything that requires a decision (target
among several, destination, how many, option). Chance is not a chooser: it is written `pick: random` in the CardSel. When
the human chooses the panel asks; when the bot chooses its AI decides.

### 2.7 "Up to N"

A single form: `amount: N` + `up_to: bool`. `up_to: true` = the chooser decides from 0 to N. In `move` the field
`up_to` is required (no default): every "move up to N" carries `true`; a mandatory move of exactly N,
`false`. Elsewhere, default `false`.

### 2.8 Bindings

One syntax: the op that creates the binding carries `"as": "<name>"`; afterwards it is referenced as `"$<name>"` wherever
a CardRef, FighterRef, PlayerSel or Amount fits, and `{"attr": ..., "of": "$<name>"}` to read an attribute.
Each binding has a type and only holds where that type is expected (the validator checks it):

| creates the binding | type |
|---|---|
| `discard`, `draw`, `choose`, `look_deck`, `search_deck` | card(s) |
| `damage` (the fighters hit; Concussion Device) | fighter(s) |
| `for_each` over `players` / over `fighters` | player / fighter |
| events (see 2.10): `$attacker`, `$target`, `$by`, `$to`, `$fighter` / `$card` / `$amount` | fighter / card / number |

The scope is the ops list where it is created, from the next op on, and the nested ones. Reserved names (they cannot
be bound): `this`, `hero`, `opposing`, `attacker`, `defender`, `combatant`, `opponent_card`, `attack_card`,
`defense_card`.

### 2.9 Conditions (Condition)

An object with `test` or a combinator `{"all": [...]}`, `{"any": [...]}`, `{"not": {...}}`.

| test | fields | meaning |
|---|---|---|
| `form_is` | `form`, `player`? | the HeroDef's form |
| `exists` | `fighters: FighterSel` or `cards: CardSel` or `space: SpaceSel` | there is at least one |
| `fighter_at` | `fighter: FighterRef`, `space: SpaceSel` | |
| `card` | `card: CardRef`, `filter: CardFilter` | the card exists and meets the filter (no card: false) |
| `combat_result` | `result: won | lost` | for the card's owner. `lost` = did not win |
| `counter` | `name`, `min`?, `max`?, `player`? | |
| `moved_this_turn` | `fighter: FighterRef` | started the turn on another space |
| `played_as` | `side: attack | defense` | how `this` was played |
| `compare` | `left: Amount`, `op: < <= == >= > !=`, `right: Amount` | |
| `plugin` | `id`, `key` | computed by the plugin |

There are never conditions in strings.

### 2.10 Events (Event)

`{"event": "<name>", ...}`. They serve for the `when` of triggers, the `until` of statuses and permanent schemes.

| event | fields | binds |
|---|---|---|
| `start_of_turn` | `player` (default `owner`; `any`) | |
| `end_of_turn` | `player` (default `any`) | |
| `after_maneuver` | `player` | |
| `after_attack` | `fighter: FighterSel` | `$attacker`, `$target` |
| `attacked` | `target: FighterSel` | `$attacker`, `$target`, `attack_card` |
| `combat_damage_dealt` | `by: FighterSel` | `$by`, `$to`, `$amount` |
| `damage_taken` | `target: FighterSel`, `damage: effect | combat | any`, `min` | `$target`, `$amount` |
| `card_discarded` | `player`, `from: [hand, deck]`, `cause_not: hand_limit`?, `filter: CardFilter` | `$card` |
| `card_played` | `player`, `filter` | `$card` |
| `fighter_defeated` | `fighter: FighterSel` | `$fighter` |

As expiry (`until`): `{"event": "end_of_turn"}` = the current turn, whoever's it is;
`{"event": "start_of_turn", "player": "owner"}` = the owner's next turn;
`{"event": "damage_taken", "target": "hero", "damage": "combat", "min": 2}` = the Pacts. The damage type is
always called `damage` (here and in `redirect_damage`); `kind` is only the discriminator of modifiers.

Trigger: `{"id", "when": Event, "condition"?: Condition, "ops": [Op]}`. A trigger has no `optional`: an ability's
"you may" is written with the `optional` op inside `ops` (Medusa, OCCULT DETECTIVE), which is the
same form as on cards.

## 3. Ops (closed list)

Every op is `{"op": "<name>", ...args}`. Arguments not listed are an error.

| op | required args | optional | notes |
|---|---|---|---|
| `damage` | `target: FighterSel`, `amount` | `chooser`, `as` (binds the ones hit) | ALWAYS effect damage (stopped by `immune_to_effect_damage`, raised by `effect_damage_bonus`, diverted by `redirect_damage` kind effect). Combat damage is computed only by the engine. |
| `heal` | `target`, `amount` | `chooser` | does not exceed max life |
| `set_hp` | `target`, `amount` | `chooser` | sets the life |
| `draw` | `player`, `amount` | `up_to`, `chooser`, `as` | |
| `discard` | `cards: CardSel | CardRef` | `as` | from the hand, the deck (top/bottom) or `in_play` to the discard. With a CardRef it discards exactly those |
| `remove_from_game` | `cards: CardSel` (zone `discard`) | `as` | the cards leave the game for good (`PlayerState.removed`, public); see "Donatello" below |
| `choose` | `cards: CardSel`, `as` | | only binds, moves nothing |
| `choose_effect` | `options: [{label, ops}]`, `amount` | `distinct`, `chooser` | choose EFFECTS; `distinct` forbids repeating |
| `move` | `target`, `amount`, `up_to` | `through_enemies`, `chooser` | `chooser` decides the destination (default `owner`, also for rival fighters: replaces the old `push`) |
| `place` | `target`, `where: SpaceSel` | `chooser` | teleport |
| `swap` | `target`, `with: FighterSel` | `chooser` | |
| `revive` | `target` (with `state: defeated`), `where`, `hp` | `chooser` | brings back a defeated fighter |
| `summon` | `name`, `where` | `hp`, `chooser` | takes a sidekick out of the reserve (`reserve` of the HeroDef); without a reserve it does nothing |
| `cancel_effects` | `card: CardRef` | | respects `uncancelable` |
| `modify_value` | `card: CardRef`, `amount` | | adds (negative subtracts); never drops below 0 |
| `set_value` | `card` and `amount` or `ignore: true` | | `amount`: the printed value becomes N (bonuses stay); `ignore: true`: "ignore its value", the total value becomes 0 (Incinerate) |
| `boost` | `card: CardRef` | `chooser` | boosts that card now (discards the top card of its owner's deck). For the card's own free "may BOOST", `may_boost` is used |
| `status` | `name`, `until: Event` and `target: FighterSel` or `player: PlayerSel` | `amount` | see the status table |
| `counter` | `name` and `delta` or `set` | `player` | clipped to the min/max of `ability.counters` |
| `gain_action` | `amount` | `player` | blocked by `cannot_gain_actions` and the `no_gain_actions` rule |
| `end_turn` | | | |
| `look_hand` | `player` | | the owner sees `player`'s hand now (see 6) |
| `reveal` | `cards: CardSel | CardRef`, `to: PlayerSel` | | show cards |
| `look_deck` | `player`, `amount`, `as` | `from: top | bottom` | look without moving |
| `search_deck` | `player`, `look: int | "all"`, `take: {amount, up_to?, filter?}`, `to: hand`, `rest: bottom_random | bottom_ordered | top_ordered | shuffle` | `chooser`, `as` | Read The Bones, Prophecy, Lady of the Lake |
| `return_to_deck` | `cards`, `position: top | bottom | shuffle` | `order: PlayerSel` | from the hand, the discard or the rival's hand to its owner's deck |
| `put_in_hand` | `cards` | | from the discard or the deck to its owner's hand |
| `redirect_damage` | `from: FighterSel`, `to: FighterSel`, `damage: effect | combat | any` | `condition`, `optional`, `chooser` | in `during`: lasts that combat |
| `optional` | `ops` | `chooser`, `cost: [Op]`, `else: [Op]` | the `chooser` decides; `cost` is paid first (if it cannot, there is no option); `else` if it declines |
| `if` | `condition`, `then` | `else` | |
| `for_each` | `over: {"players": "all"} | {"fighters": FighterSel}`, `as`, `ops` | | order: the owner first; fighters in the order their player chooses |
| `plugin` | `id` | `args` (free object) | id declared in `plugins` |

### Statuses (`status.name`)

| name | scope | meaning |
|---|---|---|
| `immune_to_effect_damage` | fighter | no effect `damage`, own or foreign (Planned Recklessness) |
| `immune_to_enemy_effect_damage` | player | only the rival's effects (Counterhex Shield) |
| `immune_to_enemy_effect_moves` | player | the rival neither moves nor places your fighters |
| `immune_to_enemy_forced_discards` | player | |
| `cannot_gain_actions` | player | |
| `cannot_draw` | player | |
| `cannot_leave_space` | fighter | by no means |
| `next_attack_bonus` | player (`amount`) | consumed by the first own attack |

### Modifiers (`ongoing.modifiers` and `ability.passives`)

`{"kind": ..., ...}`; passives additionally carry `id` and, optionally, `while: Condition`, `optional`, `chooser`.

| kind | args | |
|---|---|---|
| `modify_value` | `cards: {player, type?, fighter?}`, `amount` | continuous +N to the cards that meet it (ANUNG +2 to Hellboy's attacks; Fight Or Flight +1) |
| `rule` | `rule`, `amount`? | `no_attack_as_first_action`, `effect_damage_bonus` (`amount`; not to exhaustion), `max_hand_size` (`amount`), `no_gain_actions` |
| `status` | like the `status` op without `until` | while the card stays in play |
| `redirect_damage` | like the op, with `optional` and `chooser` | FATEFUL BARGAINS. It is the only place where `optional` is a field and not an op: a modifier contains no ops to wrap |
| `may_boost` | `fighter: FighterSel` | that fighter may boost its attacks (King Arthur) |
| `plugin` | `id` | |

## 4. Moments and triggers

- `immediately`, `during`, `after`: combat ops. The engine resolves defender and then attacker at each moment;
  `cancel_effects` in IMMEDIATELY empties the three moments of the rival card (except `uncancelable`).
- `scheme`: when the scheme is played. If the card has `ongoing`, after the ops it stays in play: its `modifiers` hold and
  its `triggers` fire until `until`; then it goes to the discard. Ivan's rule (28/10): there is only one active ONGOING
  at a time (one per player); playing another replaces the active one (it goes to the discard).
- `boost`: when the card is used as a boost.
- `ability.triggers` and `ongoing.triggers`: a single format (Trigger with `when: Event`). An optional trigger is
  decided by `chooser`.
- `ability.passives`: continuous modifiers with an optional `while`.

## 5. Effect damage and combat damage

There is only one damage in the DSL (`damage`) and it is effect damage. Combat damage (the attacker's value minus the
defender's) belongs to the engine, as does exhaustion damage. The `effect_damage_bonus` rules, the `immune_*` statuses and
`redirect_damage` tell them apart by `kind`. A `damage` on an own fighter is as much effect damage as on the
rival (Horseshoes reaches Lobster).

## 6. Hidden information (Ivan's rule)

The bot only reads the human's hand when a card says so, at that moment. In the DSL that is `look_hand`:

1. `look_hand` is the only op that shows the owner a foreign hand. It runs exactly when due (AFTER after the
   combat, when playing the scheme...) and never earlier nor in another card.
2. What was seen is kept (`Game.observe_hand` -> `KnownHand`) and is discounted card by card when it leaves the
   rival's hand by any route (`Game.card_left_hand`). What the rival draws afterwards is unknown. A seen card that
   already left is never taken as playable.
3. Choosing a card from the rival's hand (`pick: chosen` with a `chooser` different from the hand's owner) is only legal
   after a `look_hand` in the same effect. The validator demands it.
4. `pick: random` on the rival's hand looks at nothing: the human (or the bridge) draws the card; the bot, if it has to
   do it for the rival, chooses a uniform index without looking at identities.
5. `reveal` is the route for what is played face up (Abe's attack with a token, Perfect Shot, the top card
   of the deck). The bot reads exactly those cards and nothing else.
6. When the human plays the card against the bot, the bot shows its hand (chat or face-up cards) and the human
   chooses through the panel.
7. Own hand, own deck (`look_deck`, `search_deck`) and discards are legitimate information for the bot.

Each file lists in `hidden_info` the cards that touch hidden information and the bot's rule for each one.

## 7. Permanent schemes

`ongoing` with `modifiers` (continuous rules and bonuses), `triggers` (events while it stays in play) and `until`
(the event that discards it). Ivan's rule (28/10): a single active ONGOING at a time (one per player), the new one replaces the previous one;
`discard` with `zone: in_play` removes the active one (The Time For Deals Is Done).

## 8. Plugins

`{"op": "plugin", "id": "<fid>:<name>"}` or passive `{"kind": "plugin", "plugin": "<fid>:<name>"}`, with the HeroDef's `fid`
as a prefix (`abe:`, `baba:`, `liz:`, `hellboy:`, `medusa:`). Only when no op covers it; the id is
declared in `plugins` with `why`, and every declared id is used. In the Hellboy box one remains: `abe:perfect_shot` (a decision when playing the card and
a prediction compared afterwards).

## 9. What does not fit (tested against 20 heroes of the roster)

Checked against alice, sinbad, bigfoot, king-arthur, sherlock-holmes, dracula, invisible-man, jekyll-hyde,
bloody-mary, robin-hood, beowulf, raptors, the-genie, nikola-tesla, loki, deadpool, squirrel-girl,
ancient-leshen, sun-wukong and dr-sattler. Almost everything fits: damage, heal, draw, discard (including random and from the
deck), move, place, revive, summon, cancel, add or set value, statuses, counters (rage, coils,
tokens), the Pacts' rules, looking at and choosing from the rival's hand, searching the deck, returning to the deck or the hand,
choosing effects, optional with a cost (Genie, Beowulf), for_each over players and fighters, compound conditions.

What does not fit today (left for a version 2 or for a plugin):

1. **Forms that change by decision** (Alice BIG/SMALL, Jekyll/Hyde "transform"): the HeroDef's forms are
   recomputed from a counter. An op `set_form` and forms without a counter would be needed.
2. **Tokens on the board** (Invisible Man's fog, Dr. Sattler's insight): there is no "token on a space" type nor
   `with_token` selectors. It is a whole family of ops (`place_token`, `move_token`, `remove_tokens`).
3. **Deferred effects** ("At the start of your next turn, place X": Vanish, Vanish into murder): there is no op that
   schedules ops for a future event. It would fit as `delay: {until: Event, ops}`.
4. **Locked values** ("cannot be changed by card effects": Impossible to See, Three Wishes): `set_value` has
   no `lock`.
5. **Mixing the deck with the discard when searching** and "search deck AND discard" (Lady of the Lake): `search_deck`
   looks at a single deck.
6. **Swapping values or reading the rival's printed value in `set_value`** (Loki Freyja's Rescue, Mirror Image,
   Deduce Strategy "change the printed value to its BOOST"): `set_value` admits an Amount with `attr` of
   `opponent_card`, so Mirror Image and Deduce Strategy fit; Loki's simultaneous swap does not.
7. **Predictions and declarations** (Perfect Shot, Sherlock's Elementary and Confirm Suspicion, Deadpool's Holy Mackerel):
   there is no op "declare a value or a name" nor a "guessed right" test; today it is a plugin per card. If it repeats in
   more heroes, v2 would get `predict` + a `predicted` test.
8. **Abilities on the rival that are not rules** (Sherlock "HOLMES and WATSON cannot be cancelled"): it would be
   `uncancelable` by a fighter-restriction filter, not by card. Small extension: `uncancelable` as a
   passive with a `cards` filter.
9. **Loki MISCHIEF-MONGER** (playing a card to the rival's hand, +1 movement per TRICK in rival hands):
   `card_played` exists as an event, but "putting it in the rival's hand instead of the discard" is a new destination
   for `put_in_hand` (`player: opponent`) and the extra movement is a fighter attribute modifier
   (`modify_stat: move`), which does not exist.
10. **Deadpool**: almost everything is outside the game (noises, names, food); it is not modelled.
11. **Preventing all combat damage** (Bewilderment "Prevent all damage"): there is no combat-damage immunity `status`;
    `immune_to_combat_damage` (fighter) would be added.
12. **Effects that read "how many cards I discard"** (Dracula Beastform: +1 per discarded card, free amount):
    `discard` with `up_to` binds the discarded ones, and `{"count_cards"...}` counts a CardSel, not a binding. A
    `{"count_bound": "$x"}` would be needed.

Found by the reviewer in the following boxes (not implemented; each point is a bounded v2 extension):

13. **Dice** (Krang, `?` values): there is no `roll` op nor a card value that is undetermined until it resolves.
14. **Second deck** (Pandora): `zone` knows a single deck per player; a `deck: <name>` in CardSel would be needed.
15. **Doubloons and treasury** (Blackbeard): a shared or board counter, not the hero's; `counter` only
    knows the owner's counters.
16. **Combat result in the turn and "first time per turn"** (Ali, Raphael, Chupacabra): there is no `stat`
    of combats won this turn nor a `first_time_this_turn` condition.
17. **Stances by event** (Ali): forms that change by decision or by trigger; `set_form` and
    forms without a counter are needed (the same gap as 1).
18. **Modified attack reach** (Ali Float, Shredder, Krang Missiles): there is no `attack_range` status nor modifier
    (melee at a distance, or reach N).
19. **Partial cancellation** (Raphael, Donatello): `cancel_effects` erases everything; `moments: [...]` or
    "cancel only the AFTER" would be missing.
20. **"Up to N fighters"** (Chupacabra): `pick` is `one` or `all`; `pick: {"up_to": N}` would be missing.
21. **Permanent ongoing without `until` and a `removed` zone** (Donatello): `until` is required and there is no
    "out of the game" zone.
22. **Returning `this` to the hand** (Bruce Lee, Chupacabra, Raphael): `put_in_hand` with `cards: "this"` while the
    card is still in combat; the order with respect to the final discard is not defined.
23. **Forcing a card to be played and the rival's `look_hand` on the owner** (Loki): there is no `force_play` op, and
    `look_hand` only looks from the owner toward `player`; a `viewer` would be needed.
24. **Minor ones**: conditions on specific map zones, per-turn stats (actions, moves), replacing
    the maneuver with something else, Foot Soldiers (sidekicks without a card), an initial hand other than 5.

What has already been added for the roster even though the box does not use it: `summon`, `set_hp`, `swap`, `look_deck`,
`put_in_hand`, `boost` on `opponent_card`, `attacked` / `after_attack` / `card_discarded` / `card_played` as
events, `compare` and `stat`, `choose_effect` with `distinct`, the `boost` moment.

## 10. Migration from the four files of the box (28/10/2026)

Equivalences applied:

| before | now |
|---|---|
| `bind` / `as` + `{"ref": "x.boost"}` / `"$x"` / `"kept"` | `as` + `"$x"` + `{"attr": "boost", "of": "$x"}` |
| `move amount N` (implicitly up to N) / `up_to: N` | `amount: N, up_to: true` |
| `draw up_to: true` / `choose_n min/max` | `amount` + `up_to` |
| `self_player` / `self` / `owner` | `owner` |
| `this_card` / `self_card` / `this` | `this` |
| `status: name` / `name` | `name` |
| `for_each ... ops` / `do` | `over` + `as` + `ops` |
| `optional ops+else` / `then+cost` | `ops` + `cost` + `else` |
| `source: effect` / `kind: effect` / nothing | nothing: every `damage` is effect damage |
| `for_each` + `each` / `others_in_hero_zone` | `pick: all` in the selector |
| `self_hero`, `koschei`, `adjacent_fighter`, `enemies_in_hero_zone`... | structured FighterSel |
| `persistent_scheme` (3 forms) | `ongoing` on the card |
| `return_to_deck` (3 forms) | `cards` + `position` |
| `choose_n` with `options` | `choose_effect` |
| `choose_n` with `from` | `choose` or directly the CardSel of the op that moves |
| `when: "start_of_turn"` / `"triggers"` / `effect_damage_to_self_hero` / `trigger` in `ongoing` | `triggers` with `when: Event` |
| `recover_from_discard` | `put_in_hand` |
| `push` | `move` with `chooser: owner` |
| `rule` as an op | `ongoing.modifiers` kind `rule` |
| `redirect_effect_damage` (HeroDef) / `redirect_damage` | passive kind `redirect_damage` |
| `uncancelable: true` | same (card field) |
| text "boost this attack" | `may_boost: true` |
| trigger with `optional: true` (Medusa, OCCULT DETECTIVE) | `optional` op inside `ops` |
| `discard_random` / `chooser: random` | `pick: "random"` |
| `kind: combat` in `until` | `damage: combat` |
| fighter selector without a side (`{"where": ...}`) | `side` required without `role` |

Doubtful migration decisions (see also the `notes` of each file):

1. Liz WILDFIRE (returning the burning card to the hand) moves from a plugin to a `card_discarded` trigger + `put_in_hand`. The
   plugin only said that; if the interpreter prefers a replacement of the destination, it becomes a plugin again without touching the rest.
2. Hellboy `hellboy:form_change_on_table` stops being a plugin: it was table choreography, not an effect; it stays in
   `table.choreography`.
3. Medusa "A Momentary Glance": `side: any` without `other` (the engine accepts any living fighter sharing a zone
   with Medusa, herself included).
4. Medusa "Winged Frenzy": the engine lets the controller not place the Harpy (`choose_placement` -> None); the
   text makes it mandatory if there is room. The DSL follows the text.
5. Medusa "Gaze of Stone": the 8 damage is effect damage (that is how the engine does it: `game.damage` defaults to
   `effect`, and Planned Recklessness stops it).
6. Abe "Secure The Scene": `if` there is a defeated agent -> `revive` in Abe's zone; otherwise, `place` a living agent in
   Abe's zone (3 agents on the board, reserve 0; Ivan's decision of 28/10).
7. Baba "Deathless": defeated -> `revive` next to Baba Yaga with 3; alive -> `place` next to her + `set_hp` 3 (Ivan's
   decision of 28/10).
8. Abe "Shock And Awe": `moved_this_turn` on `this` (the fighter that plays it), as before.
9. Hellboy "Confront": the discard is chosen by the owner of the hand seen: `discard` with `cards: {zone: hand, player:
   opponent, chooser: owner}` after `look_hand` (rule 3 of section 6).
10. Pact Of Secrecy: "shuffle all but 2" = `choose` 2 (`as: keep`) + `return_to_deck` of `{zone: hand, pick: all,
    except: "$keep"}` with `position: shuffle`.
11. Counterhex Shield: three separate statuses (`immune_to_enemy_effect_damage`, `..._moves`, `..._forced_discards`)
    instead of one status with a `blocks` list.
12. Abe "Leap Away" and Baba "Foul Journey": `role: combatant` (one of the two fighters of the combat, the owner chooses).

## 11. Interpreter (C1, `sparring/effects/`)

- `EffectRun(ops, Ctx(...), label)` executes one ops list. It is re-entrant: frames are `(path, idx, loop)`, bindings
  travel as card ids / fighter ids / player numbers, and `answers` is keyed by `label/op path:ask index`
  (for_each iterations add `@pos`). `to_dict` / `from_dict` round-trip through JSON.
- Ops are atomic: every decision is asked before the first mutation; a paused run (`Await`) has changed nothing and
  only the current op reruns after `resume`. Random picks are memoized in `answers`, so a rerun never rerolls.
- Choosers: `ControllerChooser` (bot, via `Controller.choose_effect`, falling back to `choose_move` /
  `choose_discard` / `choose_placement`), `PanelChooser` (human, always an `Await`), `SyntheticChooser` (search),
  `ScriptedChooser` (tests).
- `PendingChoice` / `Await` are the ones of `combat_flow.py` (imported by `effects/choose.py`); an effect pause is
  `Await(PendingChoice(kind="effect", ..., extra={"key", "request"}))`.
- Ops that later phases implement (`cancel_effects`, `modify_value`, ... `look_hand`, `put_in_hand`) are registered
  stubs raising `NotImplementedError("<op>: <phase>")`. Plugins register with `@plugin("<id>")` /
  `@plugin_condition("<id>")` in `effects/ops_core.py`.
- Decisions taken for the gaps in the spec: `summon` takes a never-placed fighter (`died_at is None`); `move` with `up_to: false` prefers spaces exactly N
  away; `gain_action` for a player whose turn it is not does nothing; `end_turn` ends the CURRENT turn whoever owns the
  card (zeroes `game.turn`'s actions, sets `run.flags["end_turn"] = game.turn`); `choose_effect` resolves the chosen
  options in printed order, not choice order; `defeated` = dead on the board: `died_at` set, or a fighter the
  HeroDef starts on the board (it was never in reserve; a Harpy dead in a save older than `died_at`), reserve fighters
  are not defeated (`select.defeated`); `moved_this_turn` reads `fx.turn_start_pos`; several fighters whose
  destinations are asked one by one (`move` with `pick: all`, placements) go in fighter id order, sidekicks before
  the hero, each seeing where the previous ones ended (the order Winged Frenzy has always used).

### C4 hidden information (`effects/ops_info.py`, `KnownHand` in `state.py`)

- `look_hand` is the only caller of `Game.observe_hand` (a test scans the source). `KnownHand` of player P is what P knows about P's RIVAL: `seen` (certain), `possible` with `possible_lo`..`possible_hi` (seen once, maybe gone face down) and `top_of_deck` (known prefix of the rival deck, top first). `KnownHand.cards` never reads the rival hand or deck: every route that takes a card out of a hand must call `Game.card_left_hand` (the old hand/deck membership check was a read of the human hand and was dropped).
- A card leaving a hand in plain sight (played, discarded, picked by the rival) is forgotten exactly. A card returned face down by its owner (Glimpse Of Hell, Pyrotechnics, Pact Of Secrecy) degrades the rival's `seen` to `possible`: `lo = certain - removed`, `hi = min(seen, hand size after)`. Pact Of Secrecy over a fully seen hand of 5 leaves exactly 2 possible of 5.
- Deck top: a rival pick put on top (Every Possible Angle), a public discard pile card put on top, or a `look_deck` of the rival deck sets `top_of_deck`; a shuffle or a hidden card on top clears it; `Game.draw` moves the known top card into `seen` and clears the prefix if an unknown card came out first.
- `return_to_deck`: `order` lists are top first (`top`: first goes on top; `bottom`: last is the very bottom); `shuffle` uses a permutation memoized in the run, so a rerun never reshuffles. `search_deck` takes from the top `look` cards, `rest` goes bottom (random: memoized permutation; ordered: asked) or top (ordered) or the whole deck is shuffled.
- `reveal` of a card in a hand adds it to the viewer's `seen`; of the deck top sets `top_of_deck`; of a card played face down in combat (attack_card) records it in `run.flags["revealed"][viewer]`.
- Choosing among the RIVAL's hand cards (`ChoiceRequest.extra["of"]` is the hand owner): `ControllerChooser` never shows the options to the controller; it picks the most valuable card of those in its `KnownHand` and, if short, fills by position with the game rng, never by identity. Own-hand discards and returns keep going through `choose_discard`; own deck/discard picks (search, recover) rank by card worth.
- Search: `Knowledge.from_game(game, observer)` is a frozen snapshot of the observer's `KnownHand` (single source of truth). `determinize` keeps the seen cards in the hand, puts the known top at the top of the deck and draws between `lo` and `hi` of the possible cards into the hand.
- Live session routes (`Session._trim_virtual_hand`): when the real human hand has fewer cards than the virtual one (Glimpse Of Hell or Pyrotechnics on the table, a waived hand limit) the model drops unseen cards first; only if a seen card must go does `KnownHand.degrade` run. A blind draw raises `possible_hi` by one without looking at the card. Ivan's ruling: a burning card discarded for the end-of-turn hand limit stays in the discard (no Wildfire return, no leniency in `_discard_done`).

## 12. Events, triggers and the ONGOING slot (C3, `effects/events.py`, `effects/ongoing.py`)

- Only for heroes in `fx.dsl_heroes`. `EffectState.emit(name, *args)` and `EffectState.on_damage(...)` call
  `events.dispatch`: bookkeeping (`fx.attacked`, `fx.turn_start_pos`, `fx.taken` = actions spent, all reset at
  `start_of_turn`), then `until` expiry of the ongoing cards in play, then triggers (the player whose turn it is
  first; ability triggers before the ongoing card's). Expiry first means Fight Or Flight lapses before the
  Wildfire discard of the same start of turn.
- Trigger decisions go to `fx.choosers` (default: the bots' controllers); a run a chooser pauses is parked in
  `fx.parked` (not persisted until E1).
- Damage events come from `Game.damage(fighter, n, source, by=None)`: `damage_taken` always, and for
  `source == "combat"` also `combat_damage_dealt` by `by` (default: the last fighter in `fx.attacked`). The events are
  raised right after the hp drop, before the fighter is marked defeated. "Baba takes 2+ combat damage" is one
  `Game.damage` call, i.e. one combat; damage redirected to Koschei hits Koschei, not her.
- `card_discarded` carries the zone (`hand`, `deck`). `Game.discard_card(..., played=True)` (a scheme being played)
  raises no event: playing a card is not discarding it (so Wildfire does not bounce Searing Clarity back).
- Hellboy has two modes. Flag off: the wrappers `Game.hellboy_detective_draw` / `hellboy_anung_start` drive him (session,
  adapter, script) and the dispatcher does nothing. `'hellboy'` in `dsl_heroes` (D1): the dispatcher runs his triggers
  `detective_draw` / `anung_discard_move` at `begin_turn`, and the wrappers become no-ops (`False` / return), so nothing
  fires twice. `medusa_gaze` stays in `DRIVEN_BY_THE_ENGINE`: the AI, the session and the search decide when it
  fires and on whom and run it through `Game.use_ability` (section 15). `events.run_trigger` runs a trigger on
  request; tests pin that both modes give the same state.
- Turn bookkeeping (`fx.attacked`, `fx.turn_start_pos`, `fx.taken`) is recorded only when an interpreted hero's
  effects file reads it (`events.tracked`: `attacked_this_turn` / `combat_damage_dealt`, `moved_this_turn`,
  `actions_taken_this_turn` / `no_attack_as_first_action`), so a game of heroes that never ask saves like before.
- `card_discarded` carries `cause`; `Game.end_turn`'s hand-limit discard uses `cause="hand_limit"` and Wildfire's
  `cause_not: hand_limit` leaves such a burning card in the discard pile (Ivan, 28/10).
- `no_attack_as_first_action` (Pact Of Freedom) is enforced in `Game.can_attack` / `Game.attack` through `fx.may_attack`
  (`game.turn == player and fx.taken == 0`); the human side is blocked by the panel in E1.
- `fx.parked` is persisted inside `fx` (`parked`) and the session resumes those runs at the panel (section 14).
- ONGOING slot: `fx.ongoing[player]` = `{"card_id"}` (DSL card) or `{"card_id": None, "bonus", "label"}` (the bonus
  `Game.add_combat_bonus` has always stored; saved in the old `combat_bonus` key). `Game.combat_bonus*` are views
  over it. `ongoing.resolve_scheme` plays a DSL scheme: the player's active ONGOING is replaced BEFORE the new
  card's ops run (so the new rules are not yet in force), the card leaves hand/discard while it resolves, then stays in
  play (ONGOING) or goes to the discard pile. Rules and statuses of a card in play are read from the card
  (`ongoing.active_modifiers`, `rules`, `rule_total`), never copied.
- Wired rules: `no_attack_as_first_action`, `max_hand_size` (`Game.end_turn` via `fx.hand_limit`), `no_gain_actions` and the `cannot_gain_actions`
  status (`fx.can_gain_actions`). `effect_damage_bonus` is exposed by
  `ongoing.rule_total` for the damage code (C2).
- `put_in_hand` is C4's (`effects/ops_info.py`); Wildfire's return uses it.


## 13. Combat ops and modifiers (C2: `effects/ops_combat.py`, `effects/modifiers.py`, `combat_flow.py`)

- Rules `dsl_immediately` / `dsl_during` / `dsl_after` come after the legacy rules; the legacy rules (feint, planned
  recklessness, On Earth, boosts, `*_after`) step aside for a card whose owner's hero is in `fx.dsl_heroes`. Each run
  lives in `CombatFlow.runs` (`"moment:side"`, finished ones too) and is saved under `flow.to_dict()["dsl"]`, which is
  absent when nothing DSL happened. `PendingChoice.from_dict` accepts `kind="effect"` (key + request).
- Default choosers (`ops_combat.default_choosers`): a bot's controller (`ControllerChooser`); for a controller with
  `human = True` (HumanProxy) a `TableChooser`: it declines every optional (nothing is paid), leaves optional picks
  empty and refuses a forced pick (`NotImplementedError`, needs the panel, E1) - the engine never pays or picks out of
  the human's hand. A bot without its own `choose_effect` decides an optional that costs cards with `worth_paying`: pay
  when the damage avoided is at least 3 per card or would kill the hero (`optional` passes `cost_cards`, `at_stake`
  and `hp` in the request).
- Ivan's ruling (28/10): effects resolve in timing order (IMMEDIATELY before DURING; same timing, the defender first) and
  a value never drops below 0 at EACH step: Flame Lash (1) vs Arcane Dampener (-3) is 0, then its DURING boost +3 makes 3.
- `flow.choosers` (player -> Chooser) overrides that; a `PanelChooser` makes the flow stop with an
  `Await(PendingChoice("effect"))`, answered with `flow.resume(list)`.
- Values: each side keeps a running total (never below 0). `modify_value` adds; `set_value` with a computed amount
  ("the value becomes N": On Earth, Shock And Awe) replaces the PRINTED part and leaves bonuses (Fight Or Flight,
  extras); `set_value` with `ignore: true` ("ignore its value": Incinerate) zeroes the whole total, bonuses too.
- `cancel_effects` marks the side as cancelled (the legacy semantic: what already resolved stays) unless the card is
  `uncancelable`. `may_boost` cards ask a hand BOOST at the end of their DURING, either side; a card without a BOOST
  value is refused. `combat.can_boost/deck_boost` read the data (index by CardID, `modifiers.card_effects`).
- Statuses (`fx.statuses`, op `status`) expire through `fx.emit("start_of_turn" | "end_of_turn" | "after_maneuver",
  player)` (`modifiers.expire_on_event`, before `events.dispatch`). Modifiers of kind `status`, `rule`
  (`effect_damage_bonus`, `no_gain_actions`) and `redirect_damage` are read from `fx.modifiers` (loose ones,
  `modifiers.add_modifier` / `remove_modifiers`) AND from the ONGOING card in play (`modifiers._modifier_entries` over
  `ongoing.active_modifiers`; C3 never copies them), so a Counterhex Shield or a Pact played as a scheme is enforced. `modify_value` modifiers are NOT read here: the ONGOING bonus reaches
  combat through `Game.combat_bonus_parts` (C3 makes it a view of the ONGOING slot).
- Hooks (bodies in modifiers.py): `adjust_damage` (effect damage only: immune statuses, then +N), `can_draw`,
  `can_gain_actions`, `can_force_discard`, `can_move` (also consulted by `Game.legal_moves`). `fx.acting` is the
  player whose op is running (`damage`, `move`, `place`, `swap`, `discard` set it). `None` means no DSL op is running:
  for `adjust_damage` that is an effect of the legacy engine path (Medusa's gaze...), treated as the enemy's; for
  `can_move` it is the player's own maneuver, which is never an enemy effect (legacy-path effects that move enemy
  fighters do not exist). A discard that is the cost of an `optional` is voluntary and never vetoed.
- Known gap: FATEFUL BARGAINS (and any redirect passive) only acts on DSL `damage` ops; Medusa's damage is one since
  C5, effect damage from the legacy path of the other heroes onto Baba is not redirected until D1.
- `cancel_effects` on a CardRef that names a side of the combat (`opponent_card`, `attack_card`, `defense_card`,
  `this`) marks that side cancelled even when no card was played there (a Feint against no defense), the record the
  engine has always kept; a `$var` that resolves to nothing does nothing.
- `redirect_damage`: the op registers the redirection for the combat and it is applied in the DAMAGE phase (a
  non-optional one; an optional combat redirect raises NotImplementedError, it needs a pause inside DAMAGE). Passives
  and ONGOING `redirect_damage` act on effect damage inside the `damage` op, asking the optional ones through the
  chooser of the passive's owner.
- `next_attack_bonus` is consumed by the first attack of that player (`CombatFlow._reveal`).
- Not covered: the `scheme` moment (C3), the `boost` moment of a card used as a boost, `until` events other than
  the turn events for `status` statuses (the ONGOING `until`s are C3's).

## 14. E1 human choice infrastructure (`session_choices.py`, `Session`)

- One pause mechanism. The panel shows exactly one decision of the human at a time, `Session._paused()`, in this
  order: the pending combat stopped inside a card effect (`Pending.flow`, a `CombatFlow` whose `PanelChooser` raised
  `Await(PendingChoice("effect"))`, C2), an effect outside combat (`Session.free_effect`, an `EffectRun`) and the
  ability triggers a chooser parked (`game.fx.parked`, C3), oldest first. `Session.effect_run` is the `EffectRun` of
  that pause; its `awaiting` is the `ChoiceRequest` on `btn_choice_1..6`. Event `CHOICE {"i": 1..6}` answers: a
  single pick answers at once; multi-pick requests toggle options (numbered in click order) plus a Confirm button;
  more than 6 options page with a "Mas" button. The answer goes through `flow.resume(list)` and the session keeps
  driving the flow (`_drive_flow`: the bot's effect decisions through `ControllerChooser`, boosts as the synchronous
  `legacy_chooser` does, the human's boost being the card the table read before) or through `run.resume(list)` and
  `run.run`; the next pause re-shows the buttons, the end closes the combat (`_after_combat`) or the effect.
- Combat: `Game.begin_attack` does what `Game.attack` does before the cards resolve (checks, action, `attacked`
  event, the defense) and returns the `CombatFlow`; the session drives it. At a pause the bot's changes so far
  (moves, a boost to the discard) are projected on the table, so a save taken there matches what `--resume` reads;
  the played cards are held by the flow (in no zone: `read_bot_hand` never puts them back in the hand or the deck).
- `Session.play_effect(run)` is the public entry point E2 calls for the human's cards outside combat (schemes): it
  runs the `EffectRun` with `{bot: ControllerChooser, human: PanelChooser}` and leaves it waiting at the panel.
- Triggers: the session sets `game.fx.choosers` to the same pair, so a trigger that asks the human parks its run
  (`fx.parked`, persisted inside the game's `fx` as `parked`) and the panel surfaces it; answered runs leave the
  list. Search clones copy `fx.choosers` (EffectState.copy): D1/D2 must give the search its own choosers before a
  DSL hero of the human has triggers, or those runs park inside the clones.
- Rollback: every engine step that may stop halfway inside an effect (`_resolve_combat`, a `CHOICE` answer,
  `play_effect`) runs under a snapshot of the whole save (`Session.to_dict`); a `RuleError` restores it
  (`load_dict`) and says "Illegal action", any other exception restores it and propagates. Nothing half-applied
  stays, the action is not spent.
- Save format: `pending.flow` (the `CombatFlow.to_dict()`) and `pending.combat` (what finishing it needs: flip,
  human_guid, bot_seen, alive_before, before, boost) only while a combat is stopped; top-level `effect` only while a
  free-standing effect waits; `look_granted` only when true; `game.fx.parked` only when non-empty. Old saves load
  unchanged and the golden saves are byte-identical. `--resume` repeats the prompt and the buttons.
- UX rules (Ivan): choice buttons are hidden (`active=false`, not greyed) unless a choice is pending; while one is
  pending every other action button is greyed and the event is refused. `btn_look` is hidden and refused unless a
  card granted the look: `session_choices.grants_look` reads the card's DSL effects (any moment with a `look_hand`
  on the opponent: Confront Any Demon or God, Advanced Psychometry, Every Possible Angle, Remove A Painful Memory)
  when the human's combat card resolves or their scheme is recognized; the conditions around the op are not
  evaluated. The grant ends when the look is taken (`_look_hand`), when the human starts another action or when
  the bot's turn goes on; a grant given by the human's last action holds the end of the turn one button.
- Restrictions on the human (`session_choices.RESTRICTIONS`, `fx_query`: a missing query allows the action):
  `may_attack` hides the attack buttons and refuses the event (Pact Of Freedom); `can_draw` makes the Maneuver skip
  the draw and `can_gain_actions` makes a scheme's actions not count (Cold Iron And Holy Water), both said in the
  chat; a fighter `can_move` refuses keeps the engine's space when the table moves it. Each reason is told once
  while it lasts.
- `lua.set_panel(..., labels={id: text})` sets button texts through `panel.UI.setValue(id, text)`; to be verified
  live (relies on `UI.setValue` working on a Button).

## 15. Medusa on the interpreter (C5)

- `effects/state.py`: `INTERPRETED_HEROES = {"medusa"}`. `Game.__init__` derives `fx.dsl_heroes` from the heroes in
  play; persist omits the set when it equals that default and fills it on load (an old save of Medusa vs Hellboy
  loads with Medusa interpreted; an explicit choice away from the default, e.g. `set()`, is written as it is). The
  goldens of f4c26ca are byte-identical.
- Decisions stay where they were, the interpreter does the work (`effects/driven.py`). The AI planner, the session
  and the search decide when the gaze fires and on whom (`pick_ability_target`, the search move `("ability", fid)`)
  and which fighter A Momentary Glance hits (`Act.target`); `Game.use_ability(player, "medusa_gaze", target)` and
  `Game.play_scheme(..., target=)` hand those answers to the run as presets (`PresetChooser`: the preset answers
  requests of its kind, the rest go to the normal chooser). A preset that the effect could not pick is a RuleError
  raised before the action is spent (`driven.fighter_options`). D2 replaces the presets by the chooser deciding
  inside the search.
- Winged Frenzy's moves and placement go through the normal choosers: `EffectAI._space` defers an own-piece `move`
  to `MedusaAI.choose_move` (the planned destination, else the kiting/harpy rules) and a dead own piece's placement
  to `choose_placement` (the planned spot), so the controller is called exactly as often and in the same order as
  the legacy engine (the rng is only touched through those calls). The one ruled divergence (Ivan, 28/10): the
  return of a defeated Harpy is mandatory; a `choose_placement` that answers None gets the first free space of
  Medusa's zone. The AIs never answer None, so no golden changed.
- The human's forced discards keep the table route: a `discard` op where the human picks from their own hand goes
  through `Game.force_discard` (HumanProxy owes it, settled at "End action"), never through a chooser that would
  list the human's cards; a bot's own-hand discard goes through `choose_discard` with the card's title as the reason.
- Deleted: `_medusa_after`, `_optional_move`, `check_scheme`, the Medusa branch of `resolve_scheme`, the flow rules
  `feint` / `second_shot` / `medusa_after`, `Game.medusa_ability`. Verbatim copies live in tests/legacy_medusa.py
  as the oracle of tests/test_medusa_dsl_diff.py (`legacy(monkeypatch)` rebuilds the pre-C5 engine).

## 16. The bot's box hero on the interpreter (D1)

- `effects/state.py`: `BOT_INTERPRETED_HEROES = {hellboy, abe-sapien, baba-yaga, liz-sherman}` are interpreted only
  for the player the bot controls (`default_dsl_heroes(game)` reads `game.bot_player`; `Game.new` sets it after the
  bot is known, persist derives the same default on load). Medusa stays in `INTERPRETED_HEROES` for either side.
  The human's box hero keeps the legacy table path (text in `human_effects`, Horseshoes / On Earth / Flame Lash's
  action applied by `_hellboy_after` / `_liz_after`) until E2, so the goldens of 71e43bb are byte-identical and the
  human's panel path is exactly as E1 left it. An old save of a box bot loads interpreted; an explicit
  `dsl_heroes: []` in a save stays off and the bot's cards are then only announced as unresolved
  (`bot_card_outside_the_interpreter`, the one AFTER rule left for the bot).
- Deleted: `bot_card_after`, `_announce_bot_card`, `text_parts`, `CODED_MOMENTS` (verbatim copies in
  tests/legacy_combat.py). The flow differential of tests/test_combat_flow_diff.py now plays the box heroes on the
  HUMAN side only; the bot's side is pinned by tests/test_d1_bot_cards.py (every combat card of the four heroes,
  state and chat line), not by a byte-identical oracle: where the legacy path was incomplete the behaviour changed
  (bot Flame Lash's bottom-card boost now applied, Out Of Time boosted from the bot's hand on either side,
  Incinerate asked to the rival as a real choice instead of an "your option" note after the damage, every other
  moment applied by the engine instead of "the bot ignores this effect").
- Boosts: `legacy_chooser` asks the controller of a bot's interpreted card (`choose_combat_boost`) like it did for
  Medusa; `MedusaAI.choose_combat_boost` and the search's `SearchController.choose_combat_boost` value a DEFENSE boost
  by the damage it spares (Out Of Time).
- Narration (`effects/narrate.py`): a run of the bot's box-hero card snapshots the public state when it starts
  (`run.flags["before"]`, JSON-safe, so a pause of the human survives a save) and, when it ends, `run_moment` adds
  one line (in the catalog's language) to `result.applied` (`<card>: <changes>` or `<card>: no effect`): hit points, deaths, returns
  to the board, moves, draws (counted, never named), discards (named: public), public returns to the bot's hand
  (Wildfire, Ward And Prepare), cards put to the deck face down (counted), actions gained, the turn ended, statuses,
  cancellations, value changes, redirections and a look at the human's hand. Medusa's cards stay silent, as C5 left
  them (the C5 oracle compares `applied`).
- `EffectAI`: an optional redirect (FATEFUL BARGAINS) is decided by `hp_change` of both candidates (the blow's
  `amount` travels in the request); losing an own sidekick now costs `KILL_SIDEKICK`, so a lethal blow stays with
  Baba. `ops_core._cost_context` gives the ATTACKER a stake too (the damage the defense blocks, and what the target
  would still have left), so `worth_paying` is the one policy for both sides.
- Perfect Shot: the plugin `abe:perfect_shot` is registered; the prediction belongs to the moment the card is
  played (E3: the bot announces it, the human gets buttons) and is read from `flags["prediction"]` of the
  IMMEDIATELY run; until E3 the bot plays it face down (no +2).
- `PresetChooser` answers the first request of its kind and then steps aside (B.P.R.D. Utility Belt picks twice);
  `driven.fighter_options` skips player-scoped statuses. `EffectState.copy()` never carries `choosers` or `parked`:
  search clones and `blind_clone` decide with their own controllers.
- Search: `adapter._advance` leaves Hellboy's start of turn to the dispatcher when he is interpreted (the bot's
  Hellboy): no `anung` moves are enumerated for a discard the engine already made.

## 17. Schemes and abilities of any interpreted hero in the bots (D2)

- Schemes of a box hero are decided INSIDE the card, by a chooser, while it runs: `Game.play_scheme(..., choosers=)`
  (`driven.preset_choosers(game, owner, by_kind, base)`) hands the run the choosers of the caller; nothing is
  preset. Medusa keeps C5's presets (the planned target of A Momentary Glance, the frenzy policy through
  `SearchController.choose_move`), so her controller-call order and rng are byte-identical
  (tests/test_medusa_dsl_diff.py, goldens unchanged).
- Heuristic (`MedusaAI.scheme_acts` -> `scheme_act`): one act per scheme title of the bot's hand, valued by playing
  the card on a blind clone with EffectAI deciding inside (`EffectAI.scheme_outcome`, the same rules the real play
  uses): `material_delta` (hit points by weight, kills, the ONGOING that enters or leaves both slots) + CARD_VALUE per
  card drawn - keep_value per card given up - CARD_VALUE for the card itself + ACTION_VALUE per action it grants.
  `Act.sim` is the expected state (`apply_expected` returns a clone of it) and a simulated win scores +DEATH
  (`MedusaAI.outcome`; the old code took any finished game as the bot's death, Medusa's expected sims never finish
  a game). The act's kind is `"scheme"`; the session says "The bot plays <title>" like a glance or a frenzy.
- Search (`adapter._scheme_moves`): `("scheme", title, None, variant)` per title of an interpreted hero's hand,
  with `variant` in `SCHEME_VARIANTS = ("greedy", "safe")` when the card's ops ask something (`scheme_variants`:
  a move/place/swap/revive/summon, an optional, a choose_effect, a choose, a search_deck or any selector with a
  `chooser`) and a single `None` line otherwise (Crown Of Flame, Counterhex Shield). At most `SCHEME_MOVES_KEEP = 6`
  scheme moves per node, the safe lines dropped first. `apply` plays the card with `SyntheticChooser(variant)` for
  the mover and `SyntheticChooser("greedy")` for the rival; `IsmctsMedusa.to_act` turns the move into
  `Act("scheme", variant=...)` and `MedusaAI.execute` plays it on the real game with that same chooser for the bot
  (`scheme_choosers`: what the search evaluated) and the rival's usual chooser (its controller, or the panel in a
  session). A hero outside `fx.dsl_heroes` (the human's box hero until E2) still plays no scheme in the search.
- `SyntheticChooser` policies `greedy` / `safe`, each from the answering player's point of view: greedy brings an
  own piece to a strike spot (else nearest to the foes), a rival piece within the own hero's reach, pays costs and
  takes the first options; safe moves an own piece away, a rival piece out of reach, declines costs and takes the
  last options. Both hit the enemy that pays most (kill, hero, weakest), heal who needs it most, give up the
  cheapest cards (`card_worth`) and take the best, and never draw into exhaustion. A rival-hand pick goes through
  `ControllerChooser._from_rival_hand` (only what a look showed), so the live bot never ranks unseen cards; in the
  search the game is determinized, so a chooser there only ever sees the sampled hand (test with `HandSpy`).
- The ONGOING slot is valued once, `ongoing.worth(game, player)` in hit points: +1 per point of value on the
  owner's combat cards (Fight Or Flight), +0.5 per immunity status (Counterhex Shield: 1.5), +0.5 per point of
  effect damage bonus (Pact Of Mortality); rules that bind both players (Pact Of Freedom / Secrecy / Time, Peace's
  trigger) count 0. `EffectAI.evaluate` / `material` add `W_MEDUSA_HP * worth(me) - W_HERO * worth(rival)`;
  the search's `_side_value` adds `EvalWeights.ongoing * worth / hero.max_hp`. Replacing one ONGOING with another
  (`ongoing.enter_play`, one per player) is therefore scored as the trade.
- Abilities: the start-of-turn triggers of the box heroes (Hellboy's detective draw / ANUNG discard and move, Liz's
  Wildfire bottom discard) fire through `events.dispatch` at `Game.begin_turn`, in the simulator's loop, the
  session and inside `adapter._advance` (no hand-coded step; the bot's Hellboy enumerates no `anung` moves). Abe's
  tokens and Baba's pacts are event triggers (`combat_damage_dealt`, `attacked`, `end_of_turn`, `damage_taken`):
  the search now emits `attacked` when an attack card is committed (`apply("attack_card")`, as
  `Game._declare_attack` does), so `attacked_this_turn` (Pact Of Peace) and UNCANNY INTUITION's spend fire inside
  the tree. Decisions of those triggers go to the controllers (`SearchController` in the search, EffectAI live).
- A search clone gets its own rng at `determinize` (a shuffle inside a simulated effect, Pact Of Secrecy, never
  moves the live game's rng).
- Liz (Ivan, 29/10): the bot leaves a burning card at the bottom of its deck when a card lets it (Pyrotechnics:
  `EffectAI._cards` prefers a card of the returning tag for a bottom return, `_order` puts it last, the request
  carries `position`); the optional is accepted because `evaluate` counts a returning card at the bottom as kept
  (`keep_value + BOUNCE_BONUS`). `returning_tag(slug)` reads it from the hero's triggers (a `card_discarded` from
  the deck with a tag filter), nothing is hard-coded. `blind_clone` never leaves a returning card at the bottom of
  the shuffled own deck: the bot does not know its bottom card unless it put it there, so only what a simulated
  effect puts there counts.
- Open: a bot scheme that asks the human something (Pact Of Secrecy's "keep 2" of the human) returns the Await from
  `MedusaAI.execute`; the session does not drive it yet (E2's `Session.play_effect` for the bot side).

## 18. The bot's effects on the real table (D3, `sparring/session_bot_effects.py`)

- Projection by diff: `snapshot(session)` (JSON-safe) is taken before each bot step (a combat, from
  `_resolve_combat`; an action of its turn, in `_bot_continue`; the turn change, in `_turn_change_debt`) and
  `project(session, before)` queues F1 builders for what changed, in the step's one combined script (queue domain
  `fx`, so no read of the session flushes them early), then says it. A combat paused at the panel keeps the snapshot
  in `Pending.combat["fx"]` (saved), so a `--resume` still projects; the turn change keeps it in `fx_unprojected`.
- What is projected: the human's miniatures a bot effect moved or returned (`move_piece` by GUID, one attempt, else
  "move it yourself"); the bot's Hellboy form (`set_state` of the miniature state the table shows, `flip_token` of the
  `ability` token, `ping_objects` of token and miniature; Ivan: ping on both); ability counters that have a token
  in `data/tts` (`take_token_copy` of the source per point gained, `remove_token` of the last copy per point spent,
  GUIDs kept in `Session.token_copies`, saved; `token_spot` in the configuration, else beside the bot's deck); the
  bot's own cards: hand -> deck (`hand_to_deck`, the one builder that takes cards out of the bot's hand zone, at the
  bottom when the engine put them at the tail, else shuffled), discard -> deck (`card_to_deck_bottom` per card at
  the tail, else `shuffle_into_deck` by GUID), discard -> hand (`return_card_to_hand`), and cards the engine took
  from its deck outside a draw (Read The Bones) become draws (`drawn`): the real order of the deck is unknown.
  `fx_in_flight` keeps the reconciliation from re-adopting a card the same script is moving off the pile or hand.
- The human's cards are the human's. A card the engine discarded from their hand by name (Confront lost, Remove A
  Painful Memory) is owed through `pending_discard["cards"]`: "Put X in your discard pile", `sync_human` keeps it in the
  engine discard until the table shows it, `_discard_done` waits for it. A random discard from their hand is
  theirs to pick (`ops_core._table_settles`: `force_discard`, the usual owe): the virtual hand never names a
  placeholder. Hand -> deck is said only for cards the bot knew (seen, or the known top: Every Possible Angle,
  "Put X on top of your deck"), the rest is counted; `sync_human` never pads the virtual hand with a
  card known to be on top of the deck unless the deck shrank.
- `look_hand` reads the real hand exactly when the op runs: `Game.hand_reader` is installed by the session
  (`read_human_hand`: one `read_hand` message of the human seat, the virtual hand becomes those cards) and only
  `ops_info._look_hand` calls it; `Game.clone` never carries it. Tripwires: no read of the human seat across a bot
  turn and a combat without a look card; a look is exactly one read.
- A bot scheme that asks the human (Pact Of Secrecy) is parked by `ongoing.resolve_scheme` with
  `run.flags["scheme"]`; `_bot_continue` shows the choice and waits, the answer finishes the card
  (`_finish_bot_scheme`: `finish_scheme`, then the bot's turn goes on). `_bot_cards_in_play` keeps that card, the
  ONGOING in play and the flow's played cards out of the hand the table shows. Placing the bot's ONGOING card on the
  table is still open (D2).
- Narration: every interpreted card of the bot is narrated, Medusa's too (Ivan, 29/10); the C5 oracles compare the
  chat and `applied` without those lines. `narrate.record` writes one line per card: "no effect" never repeats
  and never hides a moment that did something.
- Costs: a look adds one message; bot Liz's Wildfire (a discard and a move at the start of her turn) adds one
  before her first action; everything else rides in the step's script.

## 19. The human's box hero on the interpreter, in table mode (E2, `effects/table.py`, `sparring/session_effects.py`)

- `effects/state.py`: `INTERPRETED_HEROES` holds Medusa and the four box heroes for both sides (`BOT_INTERPRETED_HEROES`
  is gone). Old saves load interpreted (the default is derived, never written); an explicit `dsl_heroes` in a save
  is kept. The legacy human path (`human_card_after`, `_hellboy_after`, `_liz_after`, `after_text`) left production:
  verbatim copies live in tests/legacy_medusa.py and the legacy rig (`legacy(monkeypatch, keep=...)`) installs them;
  `keep` leaves the box heroes interpreted so the Medusa twins compare only Medusa. The goldens of E2
  (tests/golden/sim.json, game_save.json) moved because the simulated Hellboy's cards now resolve (Glimpse's draw
  and shuffle, Confront's discard, Right Hand Of Doom's move...); the pre-E2 goldens the legacy engine reproduces are
  frozen under tests/golden/legacy/. The session goldens are byte-identical.
- Table mode is what the engine already knew: the player whose controller decides at the table
  (`Controller.human`, `table.table_player`). A simulation or a search clone has none, so there every card is fully
  resolved by the controllers. In table mode an op that needs what only the human holds leaves a JSON-safe note in
  `run.flags["table"]` instead of acting, and the session says it (`table.lines`, "on the table: ..."): a pick out of
  their own hand (`discard` of all / at random / their choice goes through `Game.force_discard` and the owed
  discard; `choose`, `return_to_deck` from the hand are notes), the order of their deck (`search_deck`: Read The
  Bones), the destination of their own miniature when they decide it (`move`, `place`; `revive` / `summon` set the
  fighter alive with a provisional space and note where it goes; the table sync reads the real one). Everything
  else runs in the engine: damage and heals (the dials follow), statuses and rules on the bot, values and cancels,
  draws (counted placeholders, "You draw N: do it on the table"), the bot's discards the bot chooses, the bot's hand and
  deck moves (projected by `session_bot_effects` as the bot's own are), the bot's pieces the human relocates (space
  buttons; projected like any bot move; a rival's effect that moves the human's piece still runs in the engine, D3).
- The table player's start-of-turn ability triggers (Hellboy's draw / ANUNG discard and move, Wildfire's bottom
  card) are not run by the engine (`table.start_of_turn_is_physical`): they read the real deck or an unknown
  discard, so the session says them and the table sync reconciles (`_announce_human_start`). Their other triggers
  run (Wildfire's return, Abe's tokens, the Pacts' end-of-turn damage) and are narrated to the human through
  `fx.said` ("Your ability: WILDFIRE RETURN: Fireball returns to your hand"), drained at the end of the button.
- Flame Lash: the real bottom card the human puts in the discard (the E1 boost wait) is staged at the bottom of the
  virtual deck (`session_effects.stage_bottom_card`), so the card's own `discard` op takes exactly it (and Wildfire
  returns it when it burns). The narration counts a run's deck discards (`run.flags["deck_discards"]`) apart from
  hand discards without ever reading the human's hand.
- Schemes: `Session._apply_human_scheme` runs the recognized card through `ongoing.resolve_scheme` with the panel
  as the human's chooser (`session_effects.play_scheme`); a pause parks the run (saved: `fx.parked`, with the step's
  snapshots in `flags["step"]`, so `--resume` continues it) and `Session._effect_done` closes the step
  (`session_effects.finish`: narration "Aplico <card>: ...", the ONGOING that entered play, the bot's discards, the
  projection of the bot's side, the dials, the deaths). An ONGOING of the human stays physically on their discard
  pile while in play: `sync_human` never re-adopts the card in play, and the chat says when it leaves play (the
  bot's turn change, or a combat: `session_bot_effects` reports it instead of asking for a discard).
- Narration: every interpreted run is narrated now, the bot's into `result.applied` ("Aplicado: ..."), the other
  player's into `result.human_effects` ("Your card: ..."), with the table notes at the end; a card that returns from
  the discard pile to a hand is "returns to your/its hand" for either player. `project(..., cause)` labels what the human
  must do on the table by whose effect it is ("bot effect", "combat effects", "effect of <card>").
- Panel: an optional single pick (`min 0, max 1`: "move up to N") answers on the click, "None" picks none.
  "Cancel" while a card asks is the answer that does nothing ("No" to an optional, nothing picked when none is
  required); a forced pick cannot be cancelled (the card is played). The FATEFUL BARGAINS prompt names the blow
  ("Koschei takes the damage (N) instead of Baba Yaga?"); it is asked only when the bot's effect damage reaches Baba
  with Koschei in her zone (the passive's condition), also at the bot's turn start (a parked trigger stops
  `_bot_continue` until answered).
- Restrictions: a physical draw under Cold Iron (the hand grew while `fx.can_draw` is false) is warned once and
  counted (the table wins; TTS cannot block a draw). A BOOST 0 card put in the discard during the Maneuver is
  warned (`maneuver_baseline`, saved). `Game.maneuver` checks the boost card and the movers before spending.
- Ivan's answers (29/10): the ONGOING zone (`human_ongoing_spot` / `bot_ongoing_spot`, below the combat zones): the
  human's ONGOING scheme is recognized on their spot (`recognize_scheme`; snapshot `ongoing_human` / `ongoing_bot`,
  builder `read_cards_at`) and owed to the discard pile when it leaves play (`session_bot_effects.left_play`); the
  bot's goes face up on its spot (`place_card_face_up`, projected by diff) and to its discard pile when it leaves
  play (the spot is in the discard scope). Without the spots the discard-pile route stays, with one warning. The
  human's start-of-turn ability (`start_of_turn_ability`) gates the panel: `Session.ability_wait` (saved) hides
  every button but End action and the hit points and refuses the rest until End action. Wildfire's return is
  folded into the card's line (`narrate._fold_triggers`: "you discard Fireball (Wildfire returns it to your hand)").
- E3's hook: `session_effects.human_chooser(session)` is the chooser of the human's decisions (the panel); the
  hidden-information cards wrap it. `look_hand` by the human runs in the engine (the human's `KnownHand` of the
  bot); the legacy look button (`_grant_look_for`) is for a hero outside the interpreter.

## 20. Hidden-information cards at the live table, both sides (E3, `sparring/session_hidden.py`)

- The human looks at the bot's hand exactly when the interpreter runs the `look_hand` op of their card (the
  human's hero in `fx.dsl_heroes`, what E2 switches on; E1's grant-a-button route stays for a hero outside it,
  `_grant_look_for` steps aside otherwise). `Game.hand_reader` is the one hook: asked for the bot's hand it marks
  the step (`note_look`) and, when the button ends (`after_step`, before the composite goes out), the bot's hand
  goes face up in the row at `bot_row_spot` (config; Look at bot's hand keeps `look_spot`) and is pinged (`ping_points`), in the same script. The card's conditions
  (Confront only when lost, Advanced Psychometry only when adjacent, Remove A Painful Memory's choose only with an
  ONGOING in play) are therefore the engine's, which closes the E1 backlog note.
- Two row modes, saved in `look["mode"]`: `pick` when the run paused on a `cards` request of the human over the
  bot's hand (`bot_hand_request`: Confront's discard, Every Possible Angle's return, Remove A Painful Memory's
  choose), `reveal` otherwise (Advanced Psychometry, Remove A Painful Memory without a Pact). A pick is answered by
  a ping on the card (`LOOK_PING`, allowed during the pause) or by its panel button (the bot's cards are named:
  `option_label` reads the `of` player's deck); `close_row` then follows the engine: the chosen card to the
  discard slot (`bot_discarded` grows at once so the same script's reconciliation never moves it twice), to the top
  of the bot's deck (`resolve_hand_row(deck_guid=)`, `putObject`) or back to the hand when the bot kept it, the rest
  back to the hand, one post-check (`_row_closed`: a failure marks the table dirty and asks by hand). A reveal
  closes with End action or Cancel (everything back); a ping on it is refused. `--resume` re-arms the panel
  row and repeats the prompt of the mode.
- Remove A Painful Memory by the human: the bot's "discard it or take 2" is its own `optional` (EffectAI decides);
  the row says which. By the bot: the human's `optional` carries `discards` (the named card) and `else_damage`
  (`ops_core._choice_context`), so the buttons read "Discard <card>" / "Coger 2" and the prompt names the trade.
- Perfect Shot: the plugin `abe:perfect_shot` ASKS its owner (an `effect` request with `op: predict`, options 0..7
  and `FACE_DOWN` = 8) and keeps the answer in `flags["prediction"]` (None: face down, no +2). The live session
  answers it through `PredictionChooser` with what was decided when the card was played: the human at Reveal,
  before the bot chooses its defense (`Pending.predict` holds the request, `_paused` reports `"predict"`, the
  answer continues `_reveal`; buttons "Valor 0".."Valor 7" and "Boca abajo", saved and resumable); the bot when
  it places the card (`bot_attack_placed`: `ai_effects.predict_value`, the card turned face up and the prediction
  announced, `Pending.prediction` saved). `predict_value` uses only the rival's defense cards a look showed
  (`KnownHand`) or the public composition of their deck minus their discard pile, never a hand. A Perfect Shot the
  human plays face up is public: the bot's defense knows it (Ivan, 29/10).
- UNCANNY INTUITION: `effects.events.attack_revealed(game, target)` reads the hero's `attacked` trigger that
  `reveal`s `attack_card` and evaluates its condition (an active token) on the engine; no card or hero name. Bot
  attacking the human's Abe: the card is placed face down (the face-down reader identifies it) and flipped face up
  in the same script, named in the chat. Human attacking the bot's Abe: the chat says it at Attack; at Reveal
  `session_hidden.declare_attack` keeps the engine's order (Ivan, 29/10): the `attacked` event first (the token is
  spent, the card drawn and dealt to the table, so it may be the defense; `Pending.declared` keeps it to once and
  `begin_attack(attacked=False)` does not raise it again), then the identified attack card is the ONE card
  `choose_defense(..., attack_card=)` may know (`MedusaAI`: a single-value distribution; `SearchController`: the
  known card in the search's `pending`). Headless, `Game._declare_attack` does the same: event, then a defense that
  gets `attack_card` when the ability revealed it. `EffectState.interprets(player)` is the one "hero on the
  interpreter" helper (combat flow, AI, session).
- The row survives a partial table failure: `_look_shown` rebuilds only `ids`/`guids`/`spots`, so `mode` and
  `purpose` stay and a ping still answers the engine's request; a card the table left in the hand is picked by its
  button and reaches the pile through the reconciliation ("was still in its hand"); no card out at all drops the row
  and leaves the buttons. `purpose == "discard"` plus `ai_effects.bounces_back` names Wildfire when the bot keeps a
  burning card the human made it discard.
- Bot Shock And Awe and the human's Fleeting Moments / Confront are covered by the existing routes: the human's own
  pick goes through `pending_discard` (`_table_settles`), the bot's random discard is the run's memoized rng and
  reaches the table through the reconciliation.
- Costs: the row, its pings and its closing ride the step's script (a Reveal that opens the row stays within the
  D3 budget, the ping that closes a combat is at most 2 messages, the human's prediction click is 1).

## 21. TTS translators (`sparring/session_translators.py`, phases 1 to 3)

Applying a card effect to the real table used to be inferred from the before/after diff of `session_bot_effects`
(`project()` / `snapshot()`) plus per-title patches in `session.py` (Crown Of Flame, Fight Or Flight, "Pancakes!").
The ops are data (`OPS`, `effects/ops_core.py`); the table side has the same shape: a registry of translators, one
function per op type, each with two variants.

- Registry: `TRANSLATORS[op] = Translator(mode, bot, human)`, filled with `@register(op, mode=..., human=...)` on the
  bot variant. `translate(session, intent, Ctx(cause, before, bot_discard))` looks the op up, asks `mode(session,
  intent)` which variant applies (`"bot"`, `"human"` or None when the intent is not about the human's table, or about
  nothing a human could move) and returns the checks to run after the step's composite went out, or None when the op
  has no translator (the caller keeps its path).
- Variants. `bot`: the bot moves the objects itself (a Lua write through `Session._w`, said in the chat); its check
  falls back to the human variant when the table refuses, so a failed write never stalls the game. `human`: the
  human acts by hand; the variant says what to move and relies on the flows that wait for it (`pending_discard`
  settled at "End action", the table sync, the manual draw, `Done`). A human variant never adds a press to an op
  that never had one.
- Intents: an op that touches the table reports `{"op", ...}` through `effects.table.intent(game, ...)` into
  `fx.intents` (transient, None in a clone, enabled by `Session._attach_choosers`). `project()` drains them at its
  first line (also when it has nothing to project: no stale intent reaches the next step) and hands each to its
  translator. The diff is the final consistency check and nothing else: it decides *what changed*; an intent is
  honoured only for the cards or pieces the diff confirms (`session_bot_effects._groups`: the ops' own, merged by
  position, then one inferred intent with no position for what no op reported: a push, a resume that lost the log).

| op | intent | bot variant | human variant | chosen by |
|----|--------|-------------|---------------|-----------|
| `draw` (the human's owed draws, `_deal_owed_draws`) | built by the session | `Session._deal_human_cards`: `deal_cards` from their deck to their seat | "You draw N cards: do it on the table" | `human_deck_guid` set |
| `discard`, zone `hand` (`_owe_discard`) | `n`, `reason`, `all` | the whole-hand discard (Crown Of Flame): `_discard_human_hand`, then the human variant for what the table could not move | `pending_discard` + "Discard N card(s)" | `all`: the op is `pick: "all"` on the human's hand (`fx.whole_hand`, no card title) |
| `discard`, zone `hand`, named cards (diff) | `cards` | none | `pending_discard["cards"]` + "Put X from your hand in your discard pile" | always human |
| `discard`, zone `in_play` (the human's ONGOING left play) | `card` | ping on the card, chat why, `ongoing_hold` seconds, `card_to_discard` to their pile | "move it from your ONGOING zone to your discard pile" (or "stays in your discard pile" without a spot) | `human_ongoing_spot` set |
| `move`, `place`, `swap`, `revive`, `summon` (a human miniature a bot effect put elsewhere) | `fid`, `owner` | `move_piece` by GUID, "I moved it myself" | "I could not move its miniature, move it yourself" | always bot (their own pieces are moved by hand: `session_moves`, table notes) |
| `return_to_deck`, the bot's hand or discard | `player`, `zone`, `cards` (deck order), `position` | `hand_to_deck` / `card_to_deck_bottom` per card / `shuffle_into_deck` by GUID | "I could not move X ...: do it yourself" | always bot |
| `return_to_deck`, the human's discard | same | by GUID with their deck GUID and identity (Ivan 29/10); `session_pile` has them moved by hand first (31/10) and only notes them | "Put X from your discard pile at the bottom / on top of / into your deck" | `human_deck_guid` set |
| `return_to_deck`, the human's hand (a card the bot picked) | same | none | "Put X from your hand on top of / at the bottom of / into your deck and shuffle" | always human (their hand is theirs) |
| `put_in_hand`, the bot's discard | `player`, `zone`, `cards` | `return_card_to_hand` by GUID | "I could not return X to the bot's hand: put it there yourself" | always bot |
| `put_in_hand`, the human's discard | same | none | "Pick up X from your discard pile into your hand" | always human |
| `search_deck` (the bot's own deck) | `player`, `cards`; translated with `n` from the diff | the engine counts them as draws from the top of the real deck; "The bot takes N from its deck" | the same line (nothing for a human to move) | the bot's deck only |
| `counter` (the bot's ability tokens, Abe's Intuition) | `player`, `name` | one `take_token_copy` per point gained, `remove_token` per point spent | "I could not take out / remove the token...: place / remove it yourself" | the counter has a token in the hero table |
| `form` (Hellboy's, inferred from the counter) | `player`, `form` | miniature state, flipped token, ping | "change its miniature to that form yourself" | the bot's hero has forms |
| `ongoing` (a scheme enters play: `ongoing.finish_scheme`, `enter_play`) | `player`, `card`, `replaces` | the bot's: face up on `bot_ongoing_spot` | the bot's without a spot or when the table refuses; the human's: "stays in play (replaces X): leave it in your ONGOING zone" | the bot's: `bot_ongoing_spot` set; the human's: always human |

- The ONGOING leaving play (Pact Of Freedom when Baba Yaga takes 2+ combat damage, any expiry): the card is read on
  `human_ongoing_spot` (it must be there exactly once), pinged with `ping_objects`, the reason is said (flagged
  `shown`, sent before the pause), `ongoing_hold` seconds pass (`lua.hold` inside the TTS script in a batch, a sleep
  otherwise; 0 = no pause, `config/table.json` uses 1.5) and `lua.card_to_discard` lays it face up on the pile. A
  zone that cannot be read, a card not found or found twice, no identity, a refused write: the old manual announcement.
- Without a translator, on purpose. `damage`, `heal`, `set_hp`: the dials mirror the engine's HP after every step
  (`Session._write_dials`, verified, with the dial debt of a failed write); that is a state mirror, not the work of
  one op, and writing it from the projection would write every dial twice. `look_hand`, `reveal`, `look_deck`: the
  look rows (`session_hidden`) start from the op itself through `Game.hand_reader`, and their failure has its own
  fallback (the card is picked by its button). `choose`, `search_deck` and `return_to_deck` of the human's own hand
  are table notes (`effects.table`): the human acts and the sync validates. `draw`/`discard` of the bot, its pieces,
  `status`, `modify_value`, `gain_action`... change no object.
- Phase 3, the per-title patches. `session._owe_discard` no longer asks whether the reason is Crown Of Flame: the
  `discard` op that takes a whole hand (`pick: "all"`) leaves `fx.whole_hand` set while the human's controller is owed
  the discard, and the intent carries `all`. The legacy scheme path of a hero outside `fx.dsl_heroes` (an old save with
  the interpreter off: `combat.resolve_scheme`, `Session._apply_human_scheme`, `_resolve_human_scheme`) reads the
  card's data (`ongoing.scheme_traits(slug, title)`: the ONGOING `modify_value` bonus, the cards it draws, whether it
  discards the whole hand, how many effects it makes you choose and what one heals) instead of comparing titles, so
  the three cards (and any other with the same shape) keep the chat lines and the engine effects they had. For a hero
  the interpreter runs there was never a patch: the ops and the translators above are the whole path.

## 22. Donatello (TMNT): inventions, removal from the game and a few additive capabilities

All additive; nothing of the other heroes changes (the goldens are byte-identical).

- **Card `invention`** (`effects/inventions.py`): `{"modifiers": [Modifier], "triggers": [Trigger]}`, same grammar as `ongoing` without `until`. When a card that has one is played (a combat card when the combat ends, `CombatFlow._enter(DONE)`; a scheme when its ops end, `ongoing.finish_scheme`) it is tucked, not discarded: `PlayerState.tucked`, saved under `players[i].tucked` only when non-empty. Its `modify_value` modifiers add to the owner's attacks / defenses (`type: attack | defense` = played as an attack / as a defense; no `type` = both), through `Game.attack_bonus_parts`, `Game.defense_bonus_parts` and `Game.attack_bonus`; its triggers are dispatched by `events._handle` with the card as `card_id`. `ongoing.worth` adds `inventions.worth` so the AI and the search value them. The card is tucked after it resolves, so its own bonus does not apply to it.
- **`card_played` event**, normalized since C3 but never emitted before, is now emitted by `ongoing.begin_scheme` for every scheme played by an interpreted hero (before its ops and before the card is tucked).
- **`remove_from_game`** (`cards: CardSel` in the discard pile, optional `as`): `Game.remove_from_game` moves the cards to `PlayerState.removed` (saved when non-empty). `PlayerState.gone` = discard + tucked + removed is what the unseen pool of the rival, `Model`, `KnownHand`, `unseen_copies` and the search's `determinize` leave out. Table intent `{"op": "remove", "player", "cards"}`.
- **`CardFilter.type_in`** (list of types), **Amount `{"count_of": CardRef}`** (how many cards a binding holds), **`gain_action.amount`** accepts any Amount.
- **`cancel_effects.moments: ["after"]`** cancels only the AFTER COMBAT of the card (`CombatCtx.cancelled_after`, saved in the flow's `ctx` when non-empty); the other moments of that card still run. Respects `uncancelable`.
- **`move.as`** binds the fighters it moved and records, per mover, the opposing fighters it may have passed through (`run.flags["passed"]`); the FighterSel filter **`passed_by: $mover`** selects them. A move the engine did not see (the human walks their miniature) leaves every candidate in place so the human answers.
- **`look_deck` / `return_to_deck` bottom of the human's own deck** in table mode leave notes (`look_deck`, `deck_to_bottom`): their deck is virtual, the human does it by hand and the engine never names their top card. `optional` whose only op puts the top card of the owner's deck at the bottom sends `bury` (the card id) to a bot's request, so `EffectAI` can compare it with the average card still to come.
- **Table translators**: `tuck` and `remove` (`session_translators`). Bot: one `discard_cards` write to `bot_tuck_spot` / `bot_removed_spot` (config; cards laid side by side), falling back to the human variant if the spot is missing or the table refuses. Human: the chat says to tuck / set aside by hand. `Session.sync_human`, `_adopt_extra_discards`, `adopt_table` and `_bot_cards_in_play` leave tucked and removed cards alone, so a card physically still on a discard pile is never taken back.
- **INVENTIVE (a)** is a hero trigger (`inventive`, event `after_maneuver`): the bot's `Game.maneuver` already emits the event, and `Session._maneuver` emits it for the human so the panel can ask. `session_choices.prompt_text` shows `choice.prompt.ability.<trigger id>` for an optional of a trigger that has such a tag.
- **Other shared-code changes**: `combat.is_medusa_card` compares with Medusa's own cards (the TMNT decks share her CardIDs); `hero_table.table_defaults` accepts overlapping CardID ranges when the deck images differ; `tools/import_save` ignores TTS colour markup in nicknames (`[6f2176]Donatello`); `EffectAI` and `SyntheticChooser` remove the cheapest cards for the purpose `remove`; `ai_medusa` card hints (`INVENTION_KEEP`, `INVENTION_PLAY`, `FREE_BOOST`, Donatello's `AFTER_BONUS` entries).
