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
  "during": [{"id": "<name>", "condition": Condition, "ops": [Op]}],
  "after": [{"id": "<name>", "condition": Condition, "ops": [Op]}],
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
- `ability.during`: the hero's own DURING COMBAT effects (section 29), run in the DURING of every combat in which the owner played a card.
- `ability.after`: the hero's own AFTER COMBAT effects, the same shape and the same rules as `during` (section 33): run in the AFTER of every combat in which the owner played a card, before the card's own AFTER ops, even when the card's effects were cancelled.
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
- `max_boosts` (optional, 2 or more, with `may_boost`): how many cards the owner may BOOST this card with ("You may BOOST this card
  twice", Houdini's The Big Reveal). The combat asks once per boost, the next only if the previous one was made.
- `defers_defeat` (optional): played in a combat, the defeat of its owner's hero by that combat's damage does not end the game yet:
  the loss waits until the AFTER effects are done (All Part of the Show). `look_shield` (optional): held in the hand, it lets its
  owner cancel a look at their hand (A Magician Never Reveals His Secrets). See section 27.
- `adjacent_only` (optional, attacks only): the card can only target a fighter adjacent to its attacker; the engine refuses it against any other target for the human's attack and the bot never offers it (section 35).
- `face_up` (optional, attacks only): the card is played face up, so the defender's choice may know it (section 35).
- `uncancelable` (optional, false by default): `cancel_effects` does not erase the effects of this card.
- `effects`: the five moments, always present and always lists (empty if there is nothing), plus the optional `unboosted` (only with `may_boost`: the DURING ops for when its owner did not BOOST, run right after that question; section 31):
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

Object with any of: `any: true` | `zone_of: FighterRef` | `no_zone_of: FighterRef` (sharing no zone with that fighter's space) | `adjacent_to: FighterRef` | `space_of: FighterRef`
| `nearest_to: FighterRef` | `next_to_nearest_foe: FighterRef` (section 30) | `start_space_of: PlayerSel` | `start: true` (any starting space of the board) | `empty: bool` (default true for placing). FighterRef is
a `role` string (`this`, `hero`, `opposing`, `attacker`, `defender`, `$var`).

### 2.4 Cards (CardSel and CardRef)

CardRef (string): `this` (the card being resolved), `opponent_card`, `attack_card`, `defense_card`, `$var`.

CardSel (object):

| field | values | meaning |
|---|---|---|
| `zone` | `hand`, `discard`, `deck`, `in_play` | required. `in_play`: permanent schemes on the table |
| `player` | PlayerSel | required |
| `filter` | see below | |
| `pick` | `chosen` (default), `all`, `random`, `top`, `bottom`, `last` | `chosen`: `chooser` chooses. `random`: chance (there is no "random" chooser). `top`/`bottom`: only in `deck` (the hand has no order). `last`: only in `discard`, the cards that reached the pile most recently, newest first (section 29) |
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
  `damage_dealt_this_combat`, `damage_taken_this_combat`, `combats_lost_this_turn`, `combats_won_this_turn`, `maneuvers_this_turn`.

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
| `no_zone_with_turn_start` | `fighter: FighterRef` | the fighter's space shares no zone with the space it started the turn on (not having moved is not it; section 32) |
| `played_as` | `side: attack | defense` | how `this` was played |
| `compare` | `left: Amount`, `op: < <= == >= > !=`, `right: Amount` | |
| `effects_canceled` | `card: CardRef` | a cancellation of this combat took effects off that card |
| `plugin` | `id`, `key` | computed by the plugin |

There are never conditions in strings.

### 2.10 Events (Event)

`{"event": "<name>", ...}`. They serve for the `when` of triggers, the `until` of statuses and permanent schemes.

| event | fields | binds |
|---|---|---|
| `start_of_turn` | `player` (default `owner`; `any`) | |
| `end_of_turn` | `player` (default `any`), `unless_attacked` (section 37) | |
| `after_maneuver` | `player` | |
| `after_attack` | `fighter: FighterSel` | `$attacker`, `$target` |
| `after_scheme` | `player` | |
| `attacked` | `target: FighterSel` | `$attacker`, `$target`, `attack_card` |
| `combat_damage_dealt` | `by: FighterSel` | `$by`, `$to`, `$amount` |
| `damage_taken` | `target: FighterSel`, `damage: effect | combat | any`, `min` | `$target`, `$amount` |
| `card_discarded` | `player`, `from: [hand, deck]`, `cause_not: hand_limit`?, `by: opponent`?, `filter: CardFilter` | `$card` |
| `card_boosted` | `player`, `filter: CardFilter` | `$card` |
| `card_played` | `player`, `filter` | `$card` |
| `fighter_defeated` | `fighter: FighterSel` | `$fighter` |
| `combat_lost` | `player` (default `owner`; `any`) | `$fighter` |
| `after_combat` | `player` (default `owner`; `any`), `fighter: FighterSel` | `$fighter`, `$card` |
| `left_zone` | `fighter: FighterSel` | `$fighter` (section 35) |

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
| `choose_effect` | `options: [{label, ops}]`, `amount` | `distinct`, `chooser`, `tag` | choose EFFECTS; `distinct` forbids repeating; `tag` (a name) travels in the request so a bot can recognise what the options are about (`gadget`, section 33) |
| `move` | `target`, `amount`, `up_to` | `through_enemies`, `through_sidekicks` (section 35), `chooser` | `chooser` decides the destination (default `owner`, also for rival fighters: replaces the old `push`) |
| `place` | `target`, `where: SpaceSel` | `chooser` | teleport |
| `swap` | `target`, `with: FighterSel` | `chooser` | |
| `revive` | `target` (with `state: defeated`), `where`, `hp` | `chooser` | brings back a defeated fighter |
| `summon` | `name`, `where` | `hp`, `chooser` | takes a sidekick out of the reserve (`reserve` of the HeroDef); without a reserve it does nothing |
| `cancel_effects` | `card: CardRef` | `moments` (`immediately`/`during`/`after`) | respects `uncancelable`; with `moments` only those |
| `modify_value` | `card: CardRef`, `amount` | | adds (negative subtracts); never drops below 0 |
| `set_value` | `card` and `amount` or `ignore: true` | | `amount`: the printed value becomes N (bonuses stay); `ignore: true`: "ignore its value", the total value becomes 0 (Incinerate) |
| `boost` | `card: CardRef` | `chooser` | boosts that card now (discards the top card of its owner's deck). For the card's own free "may BOOST", `may_boost` is used |
| `allow_boost` | `card: CardRef` | | "Your opponent may BOOST their card": that card's side is asked for the free BOOST of `may_boost` cards in DURING even if the card has none (An Illusion Of My Own Design) |
| `defeat` | `target: FighterSel` | `chooser` | the fighter is defeated outright, with no damage (nothing that stops or changes damage applies): the price of "defeat a Red Rider" (Eredin's Icy Guile and Foul Purpose, a `cost` of an `optional`; it cannot be paid with nobody to defeat); see section 37 |
| `cap_combat_damage` | `target: FighterSel`, `amount` | `chooser` | "X cannot take more than N combat damage this combat" (Tomoe Gozen's Deeds Of Valor, a DURING op); see section 35 |
| `consider_won` | | | "You are considered to have won this combat" (Bullseye's Arrogant But Effective): the owner's side becomes the combat's winner for every later condition and for the turn's tally; see section 31 |
| `lock_value` | `card: CardRef` | | "the value of that card is equal to its printed value and cannot be changed" (Jill Trent's Stasis Diffuser, section 33): the side's total goes back to the card's printed value and every later change of it in this combat is ignored |
| `status` | `name`, `until: Event` and `target: FighterSel` or `player: PlayerSel` | `amount` | see the status table |
| `counter` | `name` and `delta` or `set` | `player` | clipped to the min/max of `ability.counters` |
| `gain_action` | `amount` | `player` | blocked by `cannot_gain_actions` and the `no_gain_actions` rule |
| `spend_action` | `amount` | | "Spend an additional action" (The Savage She-Hulk): the owner's turn loses that many actions, as an action taken would. Meant as an `optional` `cost`: `optional` does not offer it unless the owner is the player whose turn it is and has that many actions LEFT (the attack's own action is already spent when DURING runs); see section 34 |
| `end_turn` | | | |
| `look_hand` | `player` | | the owner sees `player`'s hand now (see 6) |
| `reveal` | `cards: CardSel | CardRef`, `to: PlayerSel` | | show cards |
| `look_deck` | `player`, `amount`, `as` | `from: top | bottom` | look without moving |
| `search_deck` | `player`, `look: int | "all"`, `take: {amount, up_to?, filter?}`, `to: hand`, `rest: bottom_random | bottom_ordered | top_ordered | shuffle` | `chooser`, `as` | Read The Bones, Prophecy, Lady of the Lake |
| `return_to_deck` | `cards`, `position: top | bottom | shuffle` | `order: PlayerSel` | from the hand, the discard or the rival's hand to its owner's deck |
| `shuffle_deck` | `player` (`all` allowed) | | shuffles those players' decks ("all players shuffle their decks"); see section 26 |
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
| `attack_bonus` | fighter (`amount`) | +amount to every attack of that fighter while it lasts (Nunchaku) |

### Modifiers (`ongoing.modifiers` and `ability.passives`)

`{"kind": ..., ...}`; passives additionally carry `id` and, optionally, `while: Condition`, `optional`, `chooser`.

| kind | args | |
|---|---|---|
| `modify_value` | `cards: {player, type?, fighter?}`, `amount` | continuous +N to the cards that meet it (ANUNG +2 to Hellboy's attacks; Fight Or Flight +1) |
| `rule` | `rule`, `amount`? | `no_attack_as_first_action`, `effect_damage_bonus` (`amount`; not to exhaustion), `max_hand_size` (`amount`), `no_gain_actions`, `maneuver_boost_places_hero` (ESCAPE ARTIST), `combat_damage_reduction` (`amount`; Luke Cage, section 30) |
| `status` | like the `status` op without `until`; `target: "hero"` on a fighter status (section 37) | while the card stays in play |
| `redirect_damage` | like the op, with `optional` and `chooser` | FATEFUL BARGAINS. It is the only place where `optional` is a field and not an op: a modifier contains no ops to wrap |
| `may_boost` | `fighter: FighterSel` | that fighter may boost its attacks (King Arthur) |
| `plugin` | `id` | |

## 4. Moments and triggers

- `immediately`, `during`, `after`: combat ops. The engine resolves defender and then attacker at each moment;
  `cancel_effects` in IMMEDIATELY empties the three moments of the rival card (except `uncancelable`).
- `scheme`: when the scheme is played. If the card has `ongoing`, after the ops it stays in play: its `modifiers` hold and
  its `triggers` fire until `until`; then it goes to the discard. Ivan's rule (28/10): there is only one active ONGOING
  at a time (one per player); playing another replaces the active one (it goes to the discard).
- `boost`: when the card is used as a boost (section 27): the card's own ops, run for the player who spends it, before its value
  is added (a combat boost, Iván 2/11) or right after it is discarded (a Maneuver boost).
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
- Not covered: the `scheme` moment (C3), `until` events other than
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
| `put_in_hand`, the human's discard, a card the ENGINE picked (`pick: random`, intent `engine: true`: Insight of the Ancients) | same | `pile_card_to_hand` by GUID + CardID + the human's deck image into their seat's hand; "I put X from your discard pile into your hand" | "Pick up X from your discard pile into your hand" (also when the move fails) | the bot, if the human has a deck GUID |
| `put_in_hand`, the human's discard, a card the human picked | same | none | "Pick up X from your discard pile into your hand" | always human |
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


## 22. Leonardo (TMNT box, `data/heroes/effects/leonardo.json`)

Three additions to the DSL, all additive; every card of the box fits the existing ops otherwise.

- Amount `{"stat": "zones", "fighter": FighterRef}`: how many zones the fighter's space belongs to (`Board.zones`), 0 for a
  fighter off the board or fallen. "If the opposing fighter is in fewer zones than Splinter" is a `compare` of two of them
  (Wise beyond his years, Spatial awareness; the latter also tests `exists` on the opposing fighter so a fallen one draws nothing).
- SpaceSel flag `other: true`: a space other than the one the mover stands on ("in another space in their zone": `place` with
  `{"zone_of": "$adjacent", "other": true}` inside a `for_each` over the adjacent fighters).
- `as` on `swap`: binds the two fighters that swapped (an empty list when nothing swapped), so "if he does, they both recover
  2 health" is `heal` on `{"role": "$swapped", "pick": "all"}`. A `swap` of two miniatures of the table player leaves the swap to
  them (table note `tbl.swap`, like `move`); the engine positions follow the table sync.
- TEAM TACTICS is an ordinary start-of-turn trigger (an `optional` around a `move` of `{"side": "any"}`). For the bot it runs through
  `events.dispatch`; for the human `table.start_of_turn_is_physical` leaves it to the table and `fx.ability.team_tactics` is the
  text the panel waits on.
- Decks that share a CardID (the TMNT heroes and Medusa are all DeckID 176): see docs/card-identity.md; `select.find_card(game, id, owner)`
  and `card_ref` work per owner, a bound (`$var`) card is looked up from the effect owner first.
## 23. Donatello (TMNT): inventions, removal from the game and a few additive capabilities

All additive; nothing of the other heroes changes (the goldens are byte-identical).

- **Card `invention`** (`effects/inventions.py`): `{"modifiers": [Modifier], "triggers": [Trigger]}`, same grammar as `ongoing` without `until`. When a card that has one is played (a combat card when the combat ends, `CombatFlow._enter(DONE)`; a scheme when its ops end, `ongoing.finish_scheme`) it is tucked, not discarded: `PlayerState.tucked`, saved under `players[i].tucked` only when non-empty. Its `modify_value` modifiers add to the owner's attacks / defenses (`type: attack | defense` = played as an attack / as a defense; no `type` = both), through `Game.attack_bonus_parts`, `Game.defense_bonus_parts` and `Game.attack_bonus`; its triggers are dispatched by `events._handle` with the card as `card_id`. `ongoing.worth` adds `inventions.worth` so the AI and the search value them. The card is tucked after it resolves, so its own bonus does not apply to it.
- **`card_played` event**, normalized since C3 but never emitted before, is now emitted by `ongoing.begin_scheme` for every scheme played by an interpreted hero (before its ops and before the card is tucked).
- **`remove_from_game`** (`cards: CardSel` in the discard pile, optional `as`): `Game.remove_from_game` moves the cards to `PlayerState.removed` (saved when non-empty). `PlayerState.gone` = discard + tucked + removed is what the unseen pool of the rival, `Model`, `KnownHand`, `unseen_copies` and the search's `determinize` leave out. Table intent `{"op": "remove", "player", "cards"}`.
- **`CardFilter.type_in`** (list of types), **Amount `{"count_of": CardRef}`** (how many cards a binding holds), **`gain_action.amount`** accepts any Amount.
- **`cancel_effects.moments`**: see section 25 (one mechanism for Donatello's Short circuit and Raphael's Break something): `["after"]` alone cancels only the AFTER COMBAT (`CombatCtx.cancelled_after`, saved in the flow's `ctx` when non-empty); other lists go to `late_cancelled` / `cancelled` as described there. Respects `uncancelable`.
- **`move.as`** binds the fighters it moved and records, per mover, the opposing fighters it may have passed through (`run.flags["passed"]`); the FighterSel filter **`passed_by: $mover`** selects them. A move the engine did not see (the human walks their miniature) leaves every candidate in place so the human answers.
- **`look_deck` / `return_to_deck` bottom of the human's own deck** in table mode leave notes (`look_deck`, `deck_to_bottom`): their deck is virtual, the human does it by hand and the engine never names their top card. `optional` whose only op puts the top card of the owner's deck at the bottom sends `bury` (the card id) to a bot's request, so `EffectAI` can compare it with the average card still to come.
- **Table translators**: `tuck` and `remove` (`session_translators`). Bot: one `discard_cards` write to `bot_tuck_spot` / `bot_removed_spot` (config; cards laid side by side), falling back to the human variant if the spot is missing or the table refuses. Human: the chat says to tuck / set aside by hand. `Session.sync_human`, `_adopt_extra_discards`, `adopt_table` and `_bot_cards_in_play` leave tucked and removed cards alone, so a card physically still on a discard pile is never taken back.
- **INVENTIVE (a)** is a hero trigger (`inventive`, event `after_maneuver`): the bot's `Game.maneuver` already emits the event, and `Session._maneuver` emits it for the human so the panel can ask. `session_choices.prompt_text` shows `choice.prompt.ability.<trigger id>` for an optional of a trigger that has such a tag.
- **Look at the top card of any deck** (The future of Ninjutsu, Ivan 7/11): plugin `donatello:future_of_ninjutsu` + plugin condition `own_deck` (`effects/plugins_donatello.py`, imported at the bottom of `ops_core` with the other plugins). It asks two `effect` requests with `extra["future"]`: `"deck"` (0 own, 1 rival's; the bot's `own_top` only when the owner is the engine's player; never the rival's top card) and `"peek"` (0 leave, 1 bottom; `top` = CardID seen, `deck_of` = whose deck). The rival's top card is the engine's own (the bot's deck) or `Game.deck_reader(player)` (the human's real deck, set by the session only with a `human_deck_guid`; never in a clone). It leaves the intent `future_look` {player, card, position}: the session's translator (`session_peek`, listed in `DIRECT_OPS`) says it and, for the human's deck at the bottom, moves the card (`lua.deck_top_to_bottom`, which checks the CardID of the card it took and puts it back on top with `mismatch` when it is not the one read). When the human looks at the bot's deck the session shows the card in the row (`Session.peek`, `lua.deck_card_to_spot`; a lone last card goes back face down to the deck's spot with `lua.card_home`) and `Session.peek_pins` keeps the order they chose through every reread of the bot's hand (`read_bot_hand` -> `session_peek.engine_order`).
- **Other shared-code changes**: `combat.is_medusa_card` and the CardID lookups follow docs/card-identity.md; `tools/import_save` ignores TTS colour markup in nicknames (`[6f2176]Donatello`); `EffectAI` and `SyntheticChooser` remove the cheapest cards for the purpose `remove`; `ai_medusa` card hints (`INVENTION_KEEP`, `INVENTION_PLAY`, `FREE_BOOST`, Donatello's `AFTER_BONUS` entries).

## 24. Michelangelo (additive extensions)

- Events: `after_scheme` (`player`) fires when a DSL scheme is finished (`ongoing.finish_scheme`); `after_attack` is now emitted by the engine when a combat reaches DONE (the played cards are already in the discard).
- Amount `{"stat": "other_cards_played_this_turn", "player"?}`: cards the player played on their own turn (attack, scheme; defenses on the rival's turn are not recorded, CONFIRMED by Ivan 2026-11-07) without counting the card being resolved. Recorded only when a loaded hero's data names the stat (`events.TRACKS`, `fx.played`, saved only when non-zero).
- Status `attack_bonus` (fighter scope, needs `amount`): every attack the fighter makes while it lasts gets +amount (`next_attack_bonus` is consumed by the first attack).
- `optional` with a `return_to_deck` cost from the hand is only offered when the hand can pay it; the bot's request carries `gains_action` or `cancels` so the AI can price it.
- HeroDef `hand` ({start, max}): per-hero opening hand and end-of-turn hand limit (defaults 5 and 7).

## 25. Raphael (TMNT): per-turn combat results, partial cancellation, returning a card played

Everything here is additive: no existing file reads these words, so the five earlier heroes behave as before. They close gaps 16, 19, 22 and part of 12 of section 9.

- **Event `combat_lost`** (`{"event": "combat_lost", "player": "owner"|"opponent"|"any"}`; binds `$fighter`, the fighter that lost): raised by `CombatFlow._damage` right after the combat damage, before the AFTER COMBAT effects. The loser is the defender when the attacker dealt at least 1 damage, else the attacker (a tie is lost by the attacker: the engine's `won` is "dealt damage").
- **Stat `combats_lost_this_turn`** (`{"stat": "combats_lost_this_turn", "player": ...}`): combats that player lost in the CURRENT turn, whoever's turn it is (reset at `start_of_turn`). `fx.lost` (`[n0, n1]`) is recorded only when a hero's effects name the event or the stat (`events.TRACKS["lost"]`) and saved only when non-zero. "First time this turn" is `compare ... == 1` inside a `combat_lost` trigger: the count has already gone up when the trigger runs. `gain_action` for a player whose turn it is not does nothing, which is how ANGER ISSUES ("on each of your turns") ignores a defense lost on the rival's turn.
- **`cancel_effects.moments`** (optional list of `immediately`, `during`, `after`): cancels only those moments of the card. Without `immediately`, if that side's IMMEDIATELY has not resolved yet (a defender cancelling the attacker's card: the defender resolves first) the side goes to `CombatFlow.late_cancelled` and keeps its IMMEDIATELY; otherwise it is a plain cancellation. `uncancelable` cards are untouched. Saved in `flow.to_dict()["dsl"]` as `late_cancelled` and `cancel_hits`. `moments == ["after"]` is the one exception: it goes to `CombatCtx.cancelled_after`, so the card's IMMEDIATELY and DURING still run (Donatello's Short circuit).
- **Test `effects_canceled`** (`{"test": "effects_canceled", "card": "opponent_card"}`): a cancellation of this combat really took effects off that card (`flow.cancel_hits`: the card had ops in the cancelled moments or a `may_boost`, and was not uncancelable). A vanilla card, no card, or Incinerate gives false.
- **Fighter filter `adjacent_to_any`** (`"filter": {"adjacent_to_any": FighterSel}`): the fighter is next to at least one other living fighter the selector designates (relative to the owner): "each opposing fighter adjacent to at least one friendly fighter" is `{"side": "enemy", "filter": {"adjacent_to_any": {"side": "own"}}, "pick": "all"}`.
- **`return_to_deck` of `this` inside a combat**: a CardRef naming a card played in this combat resolves to the zone `combat`; the card leaves `flow.played` (so it does not go to the discard pile at the end) and goes to the deck. The table intent is reported with zone `discard` so the existing translators move it by GUID; for the human the chat says "Put X from your combat zone into your deck and shuffle it" (`raphael.combat_to_deck`).
- **Plugin `raphael:unbridled_rage`** (`args: {"types": [...], "per_card": 2}`): "Discard any number of defense or versatile cards. Add +2 to this card's value for each." The bot asks its controller a `cards` request with `min 0` and `purpose: "bonus"` (the default answer, for any chooser that has no opinion, is none); `EffectAI._bonus_discards` picks the number of cheapest-to-keep cards that maximises the blow's value minus the cards' keep value. In table mode the human is asked a `cards` request (`zone: "discard"`, `table_discard`, options = their defense/versatile cards not yet in the pile): the session tells them to put the cards they give up in their discard pile and press Done, reads the pile by CardID (`session_rage.verdict`) and answers with the valid ones; the plugin then makes each card known in the virtual hand (`effects.table.make_known`) and discards it. The engine never sees their hand.
- **1v1 meaning of Adventures wording**: "friendly" is Raphael and Casey Jones; the only rival is the opponent.
- **Same CardID range as Medusa**: Raphael's deck is sheet 176 like Medusa's; see docs/card-identity.md.


## 26. Doctor Strange (Brains and Brawn): after each combat, blind boosts, replacing the rival's card

Everything here is additive: no existing file reads these words, so the nine earlier heroes behave as before.

- **Event `after_combat`** (`{"event": "after_combat", "player": "owner"|"opponent"|"any", "fighter": FighterSel}`; binds `$fighter`, the fighter that played, and `$card`, the card it played): raised by `CombatFlow._enter(DONE)` once per card played in the combat, after the played cards reached their discard piles (a card a combat effect sent elsewhere is no longer there) and before `after_attack`; not raised when the game ended. `fighter: hero` limits it to the owner's hero: DARK PACT is "if Doctor Strange played a card", and a card his sidekick played does not count. A defense with no card raises nothing.
- **Op `shuffle_deck`** (`player`, `all` allowed): the engine's player's deck gets a memoized permutation and the rival forgets what it knew of that top card; the table player's real deck is shuffled by them (a table note, `tbl.shuffle_deck`) and the bot shuffles its own pile on the table (translator `shuffle_deck`).
- **SpaceSel `start: true`**: any starting space of the board (`Board.starts`), free ones only unless `empty: false`. "In another starting space" is the same selector after the first fighter was placed (it holds its space now).
- **Amount `{"combat_value": CardRef}`**: the running total value of that card's side in the combat that is running (boosts and bonuses included), 0 outside a combat. Seven Suns' "if the value of this card is above 7" is a `compare` of it, evaluated after its blind boosts.
- **Fighter filter `is_or_adjacent_to`** (`"filter": {"is_or_adjacent_to": "hero"}`): the fighter itself or one next to the referenced fighter ("Dr. Strange or a friendly fighter adjacent to him").
- **`CombatFlow.replace_attack_card(card | None, back_to_hand=False)`**: the attacker's card is replaced inside the running combat, before its side's effects ran (the defender resolves first, so a defender's IMMEDIATELY meets the attacker's IMMEDIATELY still ahead). The old card goes to its owner's discard pile, the new one takes its place in `played`, `ctx`, `result` and `sides` (saved in the flow's own fields: `atk_card`, `played`), and the bonuses of the attack stay. `None` leaves the card in place, worth nothing and cancelled. `back_to_hand=True` (Houdini's Sleight Of Hand, section 27) is for the attacker's own IMMEDIATELY: the old card returns to its owner's hand instead of the discard pile, the new card is taken from that hand and the rival learns the old one is there.
- **Plugins** (`sparring/effects/plugins_strange.py`):
  - `strange:blind_boost` (`args: {"times": N, "ignore_above"?}`): the owner DECLARES first how many blind boosts, 0..N (one `amount` request with `blind_count`, `times`, `margin`, `value`, `limit`, `attacking`, `target` for `EffectAI`; no stopping afterwards), then that many cards come off the top of the deck (public, event `card_discarded` from the deck) and their BOOST is added to the card's value; a deck with fewer cards gives what it has. The table player's count is answered on the panel, then the bot moves the real top cards to their discard pile (`session_blind`, Lua `deck_top_to_discard`) and passes the CardIDs it read to the plugin in `run.flags["blind_cards"]`; if the table refuses, a `cards` request (`pile_mode: blind`, exactly the count) asks them to lay the cards by hand.
  - `strange:mists_of_munnopor`: the attacker's deck is revealed from the top until an attack or versatile card the attacking fighter may play; the rest go to the bottom in a memoized random order (`reveal_deck` intent: the bot's chat names them) and the flow replaces the card. The table player gets a `cards` request (`pile_mode: play`) and plays the card they find at their combat spot.
  - `strange:reveal_to_top` (`args: {"as": name}`): the owner picks a card of the hand (request `purpose: reveal_top`, `missing` = the hit points the owner's fighters lack, for `EffectAI`), it goes on top of the deck, the rival learns it is the top card and the card is bound for the heal. The table player lays it on their discard pile (`pile_mode: reveal`) and the bot moves it on top of their deck (`stack_top` intent).
- **`optional` context `pact`**: an optional whose ops are a `damage` on the owner's own fighter, a `return_to_deck` of a card reference to the bottom and a `draw` sends `{"fighter", "damage", "card", "draws"}` to its chooser (`ops_core._pact_context`). `default_answer` declines it; `EffectAI._dark_pact` decides (docs/heroes/doctor-strange.md).
- **Whole hand into the deck for the table player** (`return_to_deck` of `{"zone": "hand", "pick": "all"}` to `shuffle`): the engine moves its virtual hand into its virtual deck and shuffles; the intent `hand_to_deck_all` has the bot put their seat's hand into their deck (`return_hand_to_deck` + `shuffle_deck`) before the draws that follow are dealt.
- **Table side** (`session_rage`, `session_pile`, `session_translators`): the pile modes `blind`, `reveal` and `play` next to Raphael's `rage`; the translators `stack_top`, `reveal_deck`, `shuffle_deck`, `hand_to_deck_all` and `combat_card_to_bottom` (DARK PACT paid by the human: the card at their combat spot goes to the bottom of their deck by GUID before the draw). A trigger a human's decision parks right after a combat is shown by `Session._after_combat` and the combat's closing line is held back until it is answered.
- **Same CardID range as Medusa and the turtles**: see docs/card-identity.md.

## 27. Houdini: the BOOSTED WITH moment, several boosts, placing the hero on a boosted Maneuver

Houdini is the first hero whose cards do something when they are spent as a BOOST. Everything here is additive: no earlier effects file
uses these words.

- **The `boost` moment of a card** runs when the card is spent as a boost. In a combat (`combat_flow.dsl_during`, `ops_combat.run_boost_moment`)
  it runs inside the boosting side's DURING as an effect of the boosting player, BEFORE the boost value is added (Iván 2/11: every boost card is discarded, their effects run as a chain, each resolved in full before the next, then the values are added and the combat resolves; `flow.boost_valued` records that they were) (`Ctx.moment ==
  "boost"`, run label `boost`, key `boost:<side>:<n>` in `flow.runs`, so a pause inside it survives `CombatFlow.to_dict`). In a Maneuver
  (`Game.maneuver` -> `EffectState.boost_effects` -> `events.run_boost`) it runs right after the boost card is discarded and before the
  movers move, like a trigger: a run a chooser pauses is parked, the human's is narrated. A boost that is not made runs nothing; a card with
  an empty `boost` moment costs nothing. `gain_action` only gives the action to the player whose turn it is, which is the printed "if it's your
  turn" of And The Beautiful Bess!.
- **Event `card_boosted`** (`{"event": "card_boosted", "player": "owner"|"opponent"|"any", "filter"?}`, binds `$card`): emitted at the same
  moment, for triggers that react to any boost.
- **`max_boosts`** (with `may_boost`): the DURING asks for a boost up to that many times. The 2nd prompt is a `PendingChoice("boost", ...,
  extra={"n": 1})`, answered under the key `<phase>:<side>:dsl_during:1`. The cards a side was boosted with are kept in `CombatFlow.boosted`
  (`side -> [card ids]`, saved in `dsl`), which the plugin `houdini:return_boosted` (The Big Reveal's AFTER) reads.
- **`allow_boost`** puts the side of the named card in `CombatFlow.boost_granted` (saved in `dsl`): its DURING asks for one boost even without
  `may_boost`. A side whose effects were cancelled before DURING runs no DURING and gets none.
- **`defers_defeat`**: `CombatFlow._damage` takes back the `winner` the combat damage set when the victim is a hero and its owner plays such a
  card (not cancelled), and keeps `flow.deferred_loss` (the owner, saved in `dsl`). The AFTER phase opens as usual (the defender's first, so
  All Part of the Show's `revive`); when the flow reaches DONE a hero still down loses the game then (`_settle_deferred_defeat`).
- **`look_shield`**: `look_hand` on a hand that holds such a card (the bot's: known; the human's: not read, so the human is asked on the panel
  if the card is not in their discard pile) asks its owner whether to reveal it. Revealed: the card is shown (the looker now knows it), nothing
  else is looked at and the looker's later pick among the cards they were to see fizzles (`run.flags["look_cancelled"]`).
- **Rule `maneuver_boost_places_hero`** (ESCAPE ARTIST, `ability.passives`): in a Maneuver that spends a boost card the hero's destination is
  any empty space (`Game.place_fighter`: a placement, no path, no range; `fx.can_move` still applies) and the sidekicks move as normal with
  the boost added. `Game.maneuver` reads it through `fx.hero_rule`, so the heuristic AI (`MedusaAI.maneuver_acts`), the search
  (`EngineState._hero_options`) and the live bot all use the same rule. The human places the miniature by hand and the table sync reads it.
- **`card_discarded` with `by: opponent`**: the discard happened while the rival's effect was running (`fx.acting`), not by the owner's own hand
  limit or choice. And The Beautiful Bess! is a hero trigger on it (`and_the_beautiful_bess`): a card in the hand that reacts to being discarded.
- **Plugins**: `houdini:replace_combatant` (Smoke And Mirrors: after the swap the other fighter of Houdini and Bess takes the place of the one
  that played the card, attacking or defending: `CombatFlow.replace_combatant` rebuilds the sides and the rival's card is aimed at the new
  fighter) and `houdini:return_boosted` (The Big Reveal: choose one of the boosted cards still in the discard pile and `put_in_hand` it).
- **Plugin `houdini:sleight_of_hand`** (Sleight Of Hand's IMMEDIATELY): at the attacker's own IMMEDIATELY the owner may return the card to the hand and play a different attack or versatile card the attacking fighter can play (never a card with the same title). One `cards` request (`purpose: swap_attack`, `zone: hand`, `sleight: {fighter, target, old, atk_value, def_value}` for `EffectAI._swap_attack`; empty = keep) for the bot and for a game without a table player; the table player gets a yes/no (`optional` with `sleight`) and then a `cards` request with `pile_mode: play`, `sleight: true`, the same read-back of their combat spot as the Mists (`session_rage`, `session_pile._settle_play`: the old card goes back to their hand by GUID). The flow replaces the card with `back_to_hand=True`, drops the run `immediately:atk` and sets `flow.again`, so the same side runs its IMMEDIATELY once more with the new card (`CombatFlow.step` does not advance the side). `default_answer` and the synthetic choosers decline (`purpose: swap_attack` is like `bonus`: empty). The bot's table translation is `session_sleight.bot_swap` (not an intent: the session compares the flow's attack card with the one on the table after the reveal).
- **AI**: `ai_medusa.boost_effect_value` reads the `boost` moment of a card (cards drawn, action gained, health healed or dealt, a look at the
  rival's hand that strips a card) and prices it; the combat boost choice, the Maneuver boost choice (`maneuver_acts`), the expected state after a
  Maneuver (`apply_expected`), the attack and defense evaluation of `may_boost` cards (`free_boosts`, up to `max_boosts` cards) and the search's
  boost variants and combat boost all use it.

## 28. Bigfoot: an optional draw at the end of the turn, a scheme by a sidekick, a move the human makes by hand first

No new event or op: Bigfoot is written with what already existed (`end_of_turn` trigger with an `optional` that `draw`s, a `not exists` condition on the
zone of the hero, `moved_this_turn`, `move` / `place` with `through_enemies`). Small additive pieces of the engine came with him:

- **A free optional draw** (an `optional` with no `cost` whose ops are all `draw` for the owner) sends `draws: n` and `draws_at: <event of the trigger>` in the
  request context (`ops_core._choice_context`). `EffectAI._free_draw` answers it for a bot: at the END of the turn (`draws_at == "end_of_turn"`) it
  refuses when the deck holds fewer cards than the draw (exhaustion) or the hand is already at its limit; anywhere else (OCCULT DETECTIVE, start of the
  turn) it always takes it, as before.
- **The fighter that plays a scheme at the table.** `session_effects.play_scheme` used to run every human scheme as the hero's; it now takes the fighter
  the card is restricted to (`ai_medusa.scheme_fighter`, the helper the bot already used): Jackalope Horns' `this` is the Jackalope. If nobody alive can
  play the card it is refused with a chat line (`scheme.no_fighter`), never played by the hero.
- **`await_destination`** (optional boolean on `move`): the human's own miniature is asked like a rival's (a `space` request: the chat says what to move,
  the panel shows Done, the bot validates the table and applies the move) instead of being left to the table as a note. Use it when a later op of the same
  effect depends on where the fighter ends (Jackalope Horns: "then deal 2 damage to a fighter adjacent to the Jackalope"). Without it a move by hand is a
  note and the engine does not know the destination until the table is read.
- **Prompt of a choice "adjacent to X"**: a `fighter` request whose selector has `where: {adjacent_to: ...}` carries `near` (the anchor's id) and the panel
  says "Choose a fighter adjacent to <name>" (`choice.prompt.fighter_adjacent`).
- **Chat line of a placement by hand** (`ops_core._note_where`): the references of `where` are resolved to who they are now (the owner's hero stays "hero",
  any other fighter, `this` included, is named), so a sidekick's "this fighter's zone" is not "your hero's zone".
- **Two life dials with one GUID** (Lobster Johnson / The Jackalope) are told apart by name at the first dial write: `docs/card-identity.md`, "Piece identity".

## 29. Daredevil (Hell's Kitchen): the hero's own DURING effects, a deck of 22, the last cards of the pile

Everything here is additive: no earlier effects file uses these words, so the other heroes behave as before.

- **`ability.during`** (list of `{id, condition?, ops}`; `Ability.during` in `schema.json`, `HeroEffects.ability_during`): DURING COMBAT effects of the HERO, not of a card. `ops_combat.run_moment` composes the DURING ops of every card the hero plays with them (`during_with_ability`): each effect runs under its `condition` (Daredevil: `hand_size <= 2`, counted after the card left the hand). When the card has DURING ops of its own and the ability applies, the ability's ops run first, always (Iván 2026-11-07: no order choice, no prompt). A side whose card effects were cancelled still gets the ability (`combat_flow.dsl_during_hero_ability`: a rule with `when_cancelled` that only matches a cancelled side of a hero that has `ability.during`); the card's own ops are dropped in that case. A defender with no card has no side, so no ability.
- **CardSel `pick: last`** (discard only): the `amount` cards that most recently reached the pile, newest first (`PlayerState.discard` only ever appends, so the order is the order of arrival). Devil of Hell's Kitchen: `return_to_deck` of `{"zone": "discard", "pick": "last", "amount": 4}` plus `this`, both to `shuffle`: the card and the top four of the pile, 5 in all.
- **`HeroDef.deck_size`** (`deck.size` in the generated HeroDef, absent for the usual 30): the number of playing cards. `heroes._validate` checks the sheet against it, `hero_table` checks the CardID range (`card_base .. card_base + deck_size - 1`) and `tools/import_save.deck_sheet(deck, size)` finds such a deck. The character card is not one of them: the deck object in the save holds `deck_size + 1` cards.
- **`EffectRun.ask(..., confirm=True)`**: a single forced option is still asked (the table player has to press it). Take A Knee for the human: the one button lets the bot move the real top card of their deck.
- **Plugins** (`sparring/effects/plugins_daredevil.py`): `daredevil:blind_boost` is `strange:blind_boost` under Daredevil's id (a plugin id carries its hero's fid; `args.ability: true` marks the ability's request for the chat), `daredevil:take_a_knee` (discard the top card, bind it with `args.as`; the engine's player reads its deck, the table player presses one button and the bot moves the card). The shared half is `plugins_strange.discard_top(run, game, owner, count)`.
- **`pick_fighters` with `pick: all` over a path nobody saw** (`passed_by` after the human moved their miniature by hand): the human is asked which fighters were passed (a `fighter` request, `min 0`, `max` = the candidates, multi-pick with the confirm button) instead of every candidate being hit. Through Adversity: `move hero up to 4 through_enemies as mover`, then `damage 1` to `{side: enemy, filter: {passed_by: $mover}, pick: all}`.
- **Table side** (`session_blind`): the request flag `top_discard` goes through the same declared-count path as the BLIND BOOST (`is_count`, `declared`: the bot moves the top card to the human's pile by `deck_top_to_discard`, says it in the chat as `knee.auto`, and the run reads the CardID from `run.flags["blind_cards"]`); a refused table falls back to the `cards` request of the BLIND BOOST (`pile_mode: blind`).
- **Same CardID range as the other sheet-176 decks**: see docs/card-identity.md.

## 30. Luke Cage: a combat damage reduction, a space next to the nearest foe, crossing the mover's own side

Written with the ops that already existed (`move` with `as`, `damage` with `passed_by`, `swap`, `place`, `return_to_deck`, `end_turn`, `set_value`, `stat: damage_taken_this_combat`). Small additive pieces:

- **Passive rule `combat_damage_reduction`** (`amount`, in `ability.passives`): the hero's combat damage is cut by `amount` before it lands, never below 0 (Luke Cage: 2). Only the hero himself, only combat damage (never effect damage, exhaustion or `set_hp`). `Game.combat_damage_taken(victim, blow)` (reads `fx.combat_damage_reduction`) is the one place: `CombatFlow._damage` uses it, so the damage that lands is the reduced one everywhere downstream (`result.damage`, who won, `stat: damage_taken_this_combat`, the dial) and the chat says how much was taken off (`cf.reduced`); the AI's damage estimates (attack outcome, defense evaluation, two-hit threat, combat boost, the search's boost) go through it too. The winner is named by the damage that landed, so a blow the reduction cut to 0 is a win for the defender.
- **SpaceSel `next_to_nearest_foe: FighterRef`**: the free spaces adjacent to the opposing fighter nearest to that fighter (`board.span`, "nearest" is spatial); with several tied, adjacent to any of them. The fighter itself may stay where it is if it is already adjacent. Chat texts `tbl.where.next_to_foe` / `moves.where.next_to_foe`.
- **`move` records the mover's own side as crossed** (`run.flags["passed"]`, read by the FighterSel filter `passed_by`): a mover may always cross its own side, so those fighters on some path of at most `amount` spaces are recorded besides the opposing ones (those only with `through_enemies`). Power Man: `move` the opposing fighter (`as: mover`), then `damage` the rival's fighters `passed_by: $mover` (`side: enemy`, `pick: all`). Donatello's Party wagon! is unaffected (`side: enemy` leaves its own side out).
- **Plugin `luke:replace_combatant`** (Got My Back?): Houdini's `replace_combatant` under Luke Cage's fid (the validator demands the prefix); `ops_core._choice_context` and the AI (`EffectAI._swap_combatant`, which now counts the 2 less) treat both ids alike.

## 31. Bullseye: a reach in spaces, the tally of combats won, "considered to have won", a declined BOOST

Everything here is additive: no earlier effects file or HeroDef uses these words, so the fourteen earlier heroes behave as before.

- **HeroDef `reach_spaces`** (overlay key `reach_spaces`, `HeroDef.reach_spaces`, `FighterSpec.reach`, `Fighter.reach`; 0 = the usual rule): the hero also attacks anyone up to that many spaces away, whatever the zones. It is data, not an effect: `Board.can_reach_target(a, b, ranged, reach)` adds `spaces_apart(a, b) <= reach` (spaces counted along the printed adjacency, never through passages or one-way edges; no line of sight needed) to the usual rule: adjacent, or a ranged fighter sharing a zone, or within the reach whatever the zones. A ranged hero keeps his zone shot beyond the reach. `Game.can_attack` (and so the human's attack at the panel), the bot's positioning (`strike_spots`, `position_value`, `approach_acts`, `reach_dests`, the search's `strike_spots`) and the effects chooser pass the fighter's `reach`. Bullseye's is 5; another hero that "attacks up to N spaces away, ignoring zones" (Ms. Marvel) only needs its own number in its overlay.
- **Stat `combats_won_this_turn`** (`{"stat": "combats_won_this_turn", "player": ...}`): combats that player won in the CURRENT turn, whoever's turn it is (reset at `start_of_turn`), for the combats that already ended: the damage of the combat being resolved is dealt after DURING, so IMMEDIATELY and DURING read "already won". `fx.won` (`[n0, n1]`) is recorded only when a hero's effects name the stat or `consider_won` (`events.TRACKS["won"]`) and saved only when non-zero. It is counted next to `combat_lost` (the winner is the other player): the engine's "won" is "dealt damage" for the attacker and "took none" for the defender, a tie being won by the defender.
- **Op `consider_won`** (no arguments): at the card's AFTER the owner's side becomes the winner of the combat (`CombatFlow.considered_won`, saved in `dsl`; `CombatFlow.won_by(side)` is the one reading it): the AFTER effects that resolve later read `combat_result` from it, and the tally moves (the rival's win becomes the owner's, and likewise the losses when something counts them). The damage already dealt is not undone. A side that already won is left alone. The chat says it (`narr.considered_won`).
- **`effects.unboosted`** (optional list of ops on a card with `may_boost`): what happens when the owner does not BOOST. After the free BOOST question (and only when the owner declined it or had no card to boost with) the ops run, still in the DURING, as the moment `unboosted` (`CombatFlow` run key `unboosted:<side>`). A card cancelled before DURING has no BOOST question and runs nothing. I Never Miss: `draw 1`. The validator demands `may_boost` for it.
- **SpaceSel `no_zone_of: FighterRef`**: the spaces that share no zone with the fighter's space (Tactical Retreat: `{"no_zone_of": "hero", "other": true}` in a `place`). The chat for a placement by hand names it (`tbl.where.no_zone*`, `moves.where.no_zone`).
- **Same CardID range as Medusa, the turtles, Doctor Strange and Bigfoot**: see docs/card-identity.md.
- **Hero detection**: `lua.MAX_HERO_RANGES` (the most CardID ranges one table read takes) went from 12 to 24: the thirteenth hero with TTS data made every detection fall back to Medusa / Hellboy.

## 32. Golden Bat: a Maneuver tally, a zone test against the turn's start, a look that takes nothing

Everything here is additive: no earlier effects file or HeroDef uses these words, so the earlier heroes behave as before.

- **Stat `maneuvers_this_turn`** (`{"stat": "maneuvers_this_turn", "player": ...}`): Maneuver actions that player has taken in the CURRENT turn (0 for the player whose turn it is not). `fx.maneuvers`, reset at `start_of_turn`, saved only when non-zero and recorded only when a hero's effects name the stat (`events.TRACKS["maneuvers"]`). `EffectState.count_maneuver()` is called by `Game.maneuver` (the bot, the search and every simulation) and by the session's Maneuver button, right after `use_action`: the action counts when its draw is not prevented (a Cold Iron draw block: it does not count) and also from an empty deck (an exhaustion draw). `EffectState.maneuvered(player)` is the predicate the engine reads.
- **HeroDef passive `attack_bonus` with `"unless": "maneuver"`**: the +2 of THE FIRST SUPERHERO. `HeroDef.attack_bonuses(form, is_hero, maneuvered)` drops such a passive once the owner has maneuvered this turn; `Game.attack_bonus_parts` (the combat reveal) and `Game.attack_bonus` (the bot's estimates of its next attack, the threat of an opposing Golden Bat) pass `fx.maneuvered(owner)`. The matching `ability.passives` entry of the effects file (`modify_value` + `while` compare on the stat) documents it, as Hellboy's ANUNG UN RAMA does; the interpreter does not apply `ability.passives` of kind `modify_value`.
- **Test `no_zone_with_turn_start`** (`fighter: FighterRef`): the fighter stands on a space that shares no zone with the space it was on when the turn started (`fx.turn_start_pos`, recorded when a hero's effects name `moved_this_turn` or this test). A fighter that has not moved is not "sharing no zones" (it shares all of its own). Like a Flash of Golden Light: DURING, `set_value this 4`.
- **`search_deck` with `take.amount` 0**: a look that takes nothing asks no question and returns the cards it looked at to the deck in the order the chooser picks (`rest: top_ordered`). The order request carries `of` (the deck's owner) when the cards are not the chooser's own, so the panel names the rival's cards and the bot (`EffectAI._order`) puts them worst first. When the chooser is the human and the cards are the bot's top cards (`position: top`, 2 to 6 cards), the session does not show buttons named after the cards: the cards are laid face up on the table and the human stacks them on the bot's deck (`sparring/session_order.py`; the answer is the order read from the deck top, top first, after checking it is exactly the cards laid). Sight Beyond Sight: look at the top 3 of the opponent's deck and put them back in any order.
- **A human's real deck and `search_deck` (a look that takes nothing, `rest: top_ordered`)**: the bot reads the top N cards through `Game.deck_reader(player, N)` (the Jill Trent reader), orders them with the usual `order` request, sets them as the owner's `KnownHand.top_of_deck` (erased by the next draw, discard or shuffle) and emits the intent `deck_order` {player, seen, top, bottom: null, owner}: the table reorders the real deck blind (`lua.deck_reorder`, Iván 2026-11-08), the chat says only how many cards were reordered (`order.blind`), the engine's placeholder deck is untouched and nothing is announced as revealed. Any other `search_deck` on a real deck, or a table that cannot be read, reads nothing and leaves the note `look_foreign_deck` (`tbl.look_foreign_deck`).
- **Alpine Fortress at the table (`session_bot_effects._bot_cards`)**: a bot card that goes discard -> deck (shuffle) and is drawn in the same step (the scheme shuffles one in and then draws 2) is a `return_to_deck` intent whose card ends in the hand. It is now translated as a shuffle into the real deck (`drawn_back`) instead of a discard -> hand move, so the physical draws that follow deal from the shuffled deck and the table's hand count agrees with the engine's.

## 33. Jill Trent: gadgets, the hero's own AFTER effects, a frozen value, a status that lasts one combat, revealing deck cards

Everything here is additive: no earlier effects file or HeroDef uses these words, so the earlier heroes behave as before.

- **GADGETOLOGY** is written with what existed plus two small pieces: the ability counter `gadget` (`ability.counters`: 0 = none yet, 1 = Hypnoray Blaster, 2 = Ultrabiotic Tonic), a `start_of_turn` trigger whose op is a mandatory `choose_effect` that `counter`-sets it, and conditions `counter` (`min`/`max`) wherever a card reads "your active gadget". The trigger is run by the engine for both seats (`table.start_of_turn_is_physical` no longer counts a trigger made only of `optional`, `draw`, `choose_effect` and `counter` as one the human does on the table): the human sees two buttons, the bot decides with `EffectAI._gadget` (the request carries the tag).
- **`ability.after`** (`HeroEffects.ability_after`, `Ability.after` in `schema.json`): like `ability.during`, `ops_combat.run_moment` composes the hero's AFTER effects with the card's (`during_with_ability`: the ability first, under its `condition`). The gadgets are on the hero, so a card whose effects were cancelled (all of them, or only the AFTER ones) still gets them: `combat_flow.dsl_after` keeps running a side whose `cancelled_after` is set when the hero has `ability.after`, and the rule `dsl_after_hero_ability` (`when_cancelled`) does the same for a fully cancelled side. "Whenever Jill attacks" is `{"all": [{"test": "exists", "fighters": {"role": "this", "kind": "hero"}}, {"test": "played_as", "side": "attack"}, ...]}`: the hero and not a sidekick, an attack and not a defense.
- **Printed values**: `{"attr": "value", "of": "this"}` / `"opponent_card"` is the number printed on the card (never the running value), 0 when there is no card (a defender who played none).
- **Op `lock_value`** (`card`): `modifiers.lock_value` sets the side's total to the card's printed value and adds the side to `CombatFlow.value_locked` (saved in `dsl`); `add_value` and `set_value` (so `modify_value`, `set_value`, a BOOST, an ONGOING bonus applied later) ignore a locked side for the rest of the combat. The boost cards are still discarded and their own effects still run. Stasis Diffuser: `lock_value` on `opponent_card` at IMMEDIATELY.
- **Status expiry `after_attack`**: `{"event": "after_attack", "fighter": {"side": "any"}}` as the `until` of a status expires it when the combat is over, after every AFTER effect (`EffectState.emit` expires statuses on it; `_DEFAULT_PLAYER` says any). Indestructible Cloth: `immune_to_effect_damage` on `this` until the end of the combat (`end_of_turn` would last the whole turn).
- **`choose_effect.tag`**: see the ops table.
- **Plugins** (`sparring/effects/plugins_jill.py`; the deck cards revealed are the engine's for the engine's player and the table's, read through `Game.deck_reader(player, n)`, for the table player; a table that cannot be read shows nothing and the effect does nothing):
  - `jill:hypnoray`: reveal the top card of the opponent's deck and add its BOOST to the owner's card value (`modifiers.add_value`, so a locked side ignores it). Hypnoray Blaster and Sisters In Arms use it.
  - `jill:reveal_tops` + plugin test `higher_boost` (Battle of Wits): reveal both top cards and compare their BOOST values (kept as numbers: bound cards resolve against the owner's deck, which can share CardIDs with the rival's).
  - `jill:insightful_deduction`: reveal the top 3 cards of the opponent's deck, ask the owner which goes to the bottom (a `cards` request, `purpose: bottom`, `of` = the deck's owner) and the order of the rest (an `order` request), and reorder the engine's deck; the bot's choice buries the rival's best card (`card_worth`) and leaves the weakest on top.
- **Table side**: intents `reveal_top` {player, viewer, cards} (a chat line naming the revealed cards, nothing moves) and `deck_order` {player, seen, top, bottom, owner} (`sparring/session_jill.py`): the human's choice for the bot's deck is pinned in `Session.peek_pins` (the engine order the table never had); the bot's choice for the human's deck is done by the bot, blind: `lua.deck_reorder(deck, seen, top, bottom)` checks the top is still `seen`, takes those cards off with `takeObject` (instant, the remainder looked up again after each take because the last card of a deck is a loose Card), puts the `bottom` card in with the remainder turned over and the `top` cards on top in reverse, all face down, and replies with a readback (`order`, `last`, `quantity` = `was`); the translator checks it, says "reordered the top N" (`order.blind`, `order.blind_bottom`) and never a card name, and on a mismatch or a table that refuses it forgets `known.top_of_deck` and says `order.blind_failed`. The reorder does not change the deck count, so the snapshot (`human_deck_qty`) sees nothing; `_human_cards` skips the `seen` cards of a human `deck_order` when it looks for known cards that went from the hand to the deck, or the chat would name them. `lua.peek_deck_top(..., count=N)` reads the top N CardIDs (`ids`) for the bot's read of the human's deck; `session_peek.read_top(session, player, n)` is the `Game.deck_reader`. Both ops are in `session_bot_effects.DIRECT_OPS`.
- **Same CardID range as the other sheet-176 decks**: see docs/card-identity.md.

## 34. She-Hulk (Brains and Brawn): an action as a price, a start-of-turn throw, the opponent's deck milled

Everything here is additive: no earlier effects file or HeroDef uses these words, so the earlier heroes behave as before.

- **Op `spend_action`** (`amount`): the turn's remaining actions go down by `amount` (`Game.use_action`). It is written as the `cost` of an `optional` (The Savage She-Hulk: `optional` with `cost: [spend_action 1]` and `ops: [set_value this 9]`). `ops_core._can_pay` refuses it unless it is the owner's turn and `actions_left >= amount` (an attack's action is spent before DURING, so the card needs a second one), and the option is then not asked at all. `_choice_context` sends the combat context a bot prices it with (`action_buys`: the `gain` the `set_value` adds over the printed value, both totals, whether the owner attacks and the target): `EffectAI._action_for_value` pays when the damage it adds is worth more than `ACTION_PRICE` (two `ACTION_VALUE`) and never as a defender. The chat says it (`narr.spend_actions`).
- **Plugin `shehulk:throw`** (JUST THROW SOMETHING, a start-of-turn trigger with `condition: exists enemy in her zone`): the owner picks a card of their hand to discard, or none (a `cards` request with `purpose: "throw"` and `targets`, min 0 max 1), the card is discarded and bound (`args.as`) and the next ops deal its BOOST to an enemy fighter in her zone. `EffectAI._card_to_throw` picks the card whose blow on the best target beats its keep value by `THROW_MARGIN` (a kill included), or none. The human's start-of-turn ability reads their real hand, so it is theirs on the table (`table.start_of_turn_is_physical`; the chat text is `fx.ability.throw_something`, the panel waits for End action); the plugin only runs for a hand the engine knows (the bot's, a simulation, a search clone). The bot says what it did at the start of its turn (`shehulk.throw`, `Session._throw_start_text`).
- **Plugin `shehulk:mill`** (Lady Justice: "Discard the top card of your opponent's deck. Increase the value of this card by twice that card's boost value"): discards the top card of the OPPONENT's deck and binds it (`args.as`) for `modify_value ... {"attr": "boost", "of": "$milled", "times": 2}`. The bot's deck is the engine's. The human's is on the table: the plugin asks them the one-button `amount` request of Take A Knee (`top_discard`, plus `rival_deck: true` for the wording `choice.prompt.top_discard_rival`), the session's bot moves their real top card to their discard pile and the plugin reads its CardID (`session_blind`, `plugins_strange.discard_top(run, game, owner, count, **ask_extra)`); if the table refuses, the `cards` request of the BLIND BOOST fallback (`pile_mode: blind`) asks them to lay it by hand, worded by `blind.instruction_rival`. An empty deck discards nothing and binds nothing (the value stays 0).
- **SpaceSel `start: true` in the table notes**: a placement of the human's own miniature "on a starting space" is said as such (`tbl.where.start`) instead of "where the card says" (Jennifer Walters, Esq.).
- **Same CardID range as Medusa, the turtles, Doctor Strange, Bigfoot and the Hell's Kitchen heroes**: see docs/card-identity.md.

## 35. Tomoe Gozen: leaving a zone, an adjacent-only face-up attack, a combat damage cap, moving through sidekicks, a card back to the hand

Everything here is additive: no earlier effects file or HeroDef uses these words, so the earlier heroes behave as before.

- **Event `left_zone`** (`{"event": "left_zone", "fighter": FighterSel}`; binds `$fighter`, the fighter that moved): raised by `Game.departed(fighter, origin)` after a MOVE of a fighter that the engine sees: a walk (`Game.walk`: a Maneuver, the `move` op of anyone's effect, a hand move read from the table). Placements (`Game.place_fighter`, the `place` op) and a `swap` call `departed(..., moved=False)` and raise nothing (Iván, 2026-11-08); a move the human makes by hand is read in `Session.sync_positions` and raised there (`Session._departed_by_hand`, which also says the damage in the chat and writes the life dials). It matches the trigger of the hero that owns the ability when the moved fighter satisfies `fighter` (relative to the owner: `{"side": "enemy", "kind": "hero"}` is "an opposing hero") AND stood in a zone of the owner's hero's space before the move and shares none with it now (`events.left_zone_of`); the owner's hero moving herself never matches and a defeated hero has no ability. ATTACK OF OPPORTUNITY: `damage` 1 to `$fighter`. Neither a placement nor a swap (with her or anyone) fires it.
- **Bot pricing of a departure**: `events.departure_damage(game, fighter, dest)` (`EffectState.departure_damage`) is the damage the rival hero's `left_zone` triggers (their `damage` ops with an integer amount) would deal `fighter` if it went to `dest`; `MedusaAI.hazard_cost` (a destination chosen for an effect's move) and `MedusaAI.exit_cost` (the hero's Maneuver destinations) count it like a hazard edge.
- **Card flags `adjacent_only` and `face_up`** (`CardEffects.adjacent_only`, `CardEffects.face_up`; `modifiers.adjacent_only(card)`, `modifiers.plays_face_up(card)`): Witness My Last Battle. `Game.attack_card_reaches(attacker, target, card)` is "the card may be played against that target" (false for an adjacent-only card against a fighter that is not next to the attacker, along the printed adjacency); `Game.check_attack_target` raises `RuleError` (`err.adjacent_only`) and `Game._declare_attack` and the human's Reveal (`Session`) call it, while the bot's attack options (`MedusaAI.attack_acts`, the search's `_attack_titles` and `to_act`) never offer the card against a target out of reach. A face-up card is shown to the defense like UNCANNY INTUITION's attack: `Game._declare_attack` passes it to `choose_defense(attack_card=...)`, `session_hidden.declare_attack` returns it for the bot's defense (chat `hidden.card_face_up`) and `bot_attack_placed` flips the bot's card (chat `hidden.bot_card_face_up`). The search's determinization (`EngineState.determinize`) puts a face-up attack in the attacker's sampled hand.
- **Op `cap_combat_damage`** (`target`, `amount`; a DURING op): registers a cap for THIS combat (`CombatFlow.damage_caps`, fighter id -> amount, saved in `dsl`): `CombatFlow._damage` cuts the combat damage that lands on the fighter to at most `amount`, after the hero's own reduction (Luke Cage's passive). Effect damage and exhaustion are never capped; several caps on one fighter: the lowest holds; a card whose effects were cancelled registers none. The chat says it (`cf.capped`, `narr.damage_cap`). The bot's defense evaluation caps the expected damage of Deeds Of Valor (`ai_medusa.DEEDS_CAP`).
- **`move.through_sidekicks`** (`boolean`): the mover may cross the rival's sidekicks (never the rival's hero) and never end on one. The interpreter turns it into the third value of `through`: `False`, `True` (`through_enemies`: every rival fighter) or `"sidekicks"`; `Game.legal_moves(fighter, steps, through)`, `Game.hazard_edges` and `ops_core._passed_through` read it (`Game.passable_enemy_spaces`, `Board.reachable(..., passable=...)`), and the requests, the bot's chooser and the chat (`moves.through_sidekicks`, `tbl.through_sidekicks`, `moves.no_path_sidekicks`) carry the string.
- **`put_in_hand` of a card played in the running combat** (`{"op": "put_in_hand", "cards": "this"}` in an AFTER): like `return_to_deck` of `this` (section 25) the card leaves `flow.played` (so it does not go to the discard pile) and goes to its owner's hand; the table intent is reported with zone `discard` (the translators move it by GUID; for the human the chat says "<title> vuelve a tu mano") and the rival learns the card is in that hand (it was face up). Five Against Thousands: `optional` with a `cost` of one card discarded from the hand. The interpreter tells the bot's chooser (`returns_card` in the request) so `EffectAI._returns_card_pays` weighs the card that comes back against the least useful one of the hand.
- **Same CardID range as the other sheet-176 decks**: see docs/card-identity.md. Her life dial has Donatello's GUID (`ca8e35`, the third cross-hero collision of the save, told apart by the dial's name like the Lobster / Jackalope one).

## 36. Ciri (The Witcher: Steel & Silver): tiers read from a pile counter, a conditional rule, "within N spaces", a deck search by what a card is

Everything here is additive: no earlier effects file or HeroDef uses these words, so the earlier heroes behave as before.

- **The SOURCE is a HeroDef pile counter** (overlay `counters.source` = `{"pile": "discard", "tag": "source"}`, tag `source` on the 13 cards with the orb): the Source cards in Ciri's discard pile, read with `{"test": "counter", "name": "source", "min": n}` exactly like Hellboy's destinies (section 12). A card with several numbered orbs applies the HIGHEST tier the Source reaches: the data writes it as an `if` / `else` chain from the highest threshold down (the validator needs nothing new). The Source is read when the moment resolves, before the card in play reaches the discard pile.
- **Passive rule `cards_uncancelable`** (`{"kind": "rule", "rule": "cards_uncancelable", "while": Condition}`): no effect of a card of the hero's deck (the sidekick's included, whoever plays it) can be canceled while `while` holds (UNCONTAINABLE POWER: SOURCE 7). `modifiers.is_uncancelable(card, game=None)` answers it: the card's own `uncancelable` flag, or, given the `game`, the owner's rule (`modifiers.hero_rule_holds`: the passive's `while` evaluated for the owner). `cancel_effects`, the legacy `_cancel_rival` and the bot's `_cancellable_moments` (what a cancel would still erase) all pass the game, so the bot never spends a Parry on a card that cannot be canceled. `while` is optional (a rule without one always holds).
- **Fighter filter `within`** (`"filter": {"within": {"of": FighterRef, "spaces": N}}`): the fighter is at most N spaces from the referenced fighter, counted along the printed adjacency (`Board.spaces_apart`, what a reach in spaces measures: section 31), whatever the zones. "An opposing fighter within 3 spaces of Ciri" is `{"side": "enemy", "filter": {"within": {"of": "hero", "spaces": 3}}}`.
- **Plugin `ciri:channel_the_source`** (Channel the source: "discard any number of Source cards from your hand, +2 to this card's value for each"): Raphael's Unbridled rage with another filter. Both are `plugins_raphael.discard_for_bonus(run, game, per_card, wanted, plugin_id, **ask_extra)`; the request carries `tag: "source"` so the human's panel names the cards that do not qualify (`session_rage`: `rage.instruction_source`, `rage.wrong_source`).
- **`search_deck` by what a card is**: with a `take.filter`, the intent `search_deck` carries `exact: true` and the CardIDs found. For the bot's own deck the table takes THOSE cards out of the real deck by CardID and deck image into the bot's hand (`session_search.take`, builder `lua_search.deck_card_to_hand`), says them in the chat (the card is revealed) and says so when the table refuses; without a filter (Baba Yaga's "look at 5") nothing changes: the cards are dealt from the top of the real deck. The human's own search stays a table note (they search their deck by hand, show the card and shuffle).
- **A Source dial on the table** (`counter_dials.source` of `data/tts/ciri.json`, `source_dial` of the session configuration, `session_source`): mirrors the counter like Hellboy's destiny dial, for Ciri on either side, through the same `_put_dials` (verified write, a dial the human touched by hand is respected, dial debt). A game without Ciri has no such dial.
- **Unicorn ally's ONGOING** needs no new op: a trigger `after_attack` with `{"side": "any"}` (every combat has one fighter of each player in it) draws, and a trigger `end_of_turn` with a `hand_size` condition discards the ONGOING (`discard` of `zone: in_play`). The `until` is `fighter_defeated` of the owner's hero: the data has no "until never", and Ciri's defeat ends the game.
## 37. Eredin: an ability that is the absence of the sidekicks, the price of a fighter, two cards that change what can be played

Everything here is additive: no earlier effects file or HeroDef uses these words, so the earlier heroes behave as before. Eredin is the first hero with four identical sidekicks (the Red Riders, 1 hit point each, none in reserve) and the first whose card text depends on them being gone.

- **ENRAGED** ("While all of your Red Riders are defeated"): a state derived from the roster, not a counter or a form. In a card it is the plain condition `{"not": {"test": "exists", "fighters": {"side": "own", "kind": "sidekick"}}}` (Backhand, Icy Guile, Wild Hunt, Portal Defense). The engine reads the same definition in `sparring/enraged.py` for what is not a card effect, through the HeroDef passive `{"id": "king_of_the_wild_hunt", "effect": "enraged", "combat_bonus": 1, "move": 3}` (overlay `passives`): `enraged.bonus_parts` is added to the value of EVERY combat card its owner plays (`Game.attack_bonus_parts`, `Game.defense_bonus_parts`, `Game.attack_bonus`: the combat chat shows "KING OF THE WILD HUNT (+1)"), whichever fighter plays it; the hero's move value is `move` while enraged (`Fighter.move` follows the roster: `enraged.sync_move`, called by `Game.defeat` / `Game.damage` when a fighter falls, by the `revive` op, by `persist.apply_game` and by the session when it puts a fighter back by hand). A Red Rider that falls in the MIDDLE of a combat (the price of Icy Guile) adds the bonus to the card in play at once (`enraged.reach_combat`); a Red Rider that returns in the middle of one does not take it back (open question in docs/heroes/eredin.md). The `ability.passives` entry of the effects file is only documentation (a `modify_value` with `while`, like Golden Bat's).
- **Op `defeat`** (`target`; schema `Ops`): `Game.defeat(fighter)` takes the hit points to 0 and the fighter falls (`died_at`, `fighter_defeated` event) without going through `Game.damage`: no `immune_to_effect_damage`, no `effect_damage_bonus`, no `damage_taken` event. It exists for "defeat a Red Rider" as the `cost` of an `optional` (`ops_core._can_pay` refuses it with no candidate, so the option is not asked). The bot prices it (`ai_effects.EffectAI._fighter_pays`: the damage the combat swings for "ignore the value", few Red Riders left for "return this card", and the rage the last one brings); the request carries `defeats` {fighters, returns, ignores}.
- **`until` flag `unless_attacked`** (on `end_of_turn`): the event only matches at the end of a turn in which the owner did not attack (`game.fx.attacked` is empty). Might Of The Aen Elle: `until {"event": "end_of_turn", "player": "owner", "unless_attacked": true}`; the card protects Eredin through the rival's turn when he attacked and the next turn of the owner decides again. The word is tracked (`events.TRACKS`) so a game without it saves as before.
- **`target: "hero"` on an ONGOING `status` modifier**: the status belongs to the hero of the card's owner (`modifiers._modifier_entries` gives the entry the hero's `fid`): `{"kind": "status", "name": "immune_to_effect_damage", "target": "hero"}` is "Eredin does not take damage except combat damage or from exhaustion" (exhaustion and `set_hp` are not `effect` damage).
- **Card tags** (overlay `tags`, `Card.tags`): `attack_if_enraged` (Implacable, a defense: "If Eredin is ENRAGED, you may play this card as an attack") and `any_space_if_enraged` (Foul Purpose: "If Eredin is ENRAGED, you may play this card face-up to target a fighter in any space"). `enraged.may_attack_with(game, player, card)` replaces `Card.can_attack` where the engine decides what a hero may attack with (`Game.check_attack_card`, `MedusaAI.attack_acts`, the search's `_attack_titles` and `to_act`); `Game.can_attack(attacker, target, card)` and `Game.attack_card_reaches` do not hold an enraged `any_space_if_enraged` card to the attacker's reach; `Game.can_declare_attack` lets the table player NAME a far target before the card is on the table (their hand is virtual) and the Reveal refuses it when the card played does not reach. `modifiers.plays_face_up(card, game, attacker, target)` also answers true for that card against a target out of the usual reach: the defense is chosen knowing it (the hidden-information route of Witness My Last Battle); in reach it is played like any attack.
- **Plugins** (`sparring/effects/plugins_eredin.py`): `eredin:replace_combatant` is Houdini's mechanism (Portal Defense: swap with an adjacent friendly fighter, which is now the defender; `luke:replace_combatant` is the same) and `eredin:opponent_card` is a plugin TEST (`{"test": "plugin", "id": "eredin:opponent_card", "key": "has_immediately"}`): the rival's card has an IMMEDIATELY effect in its printed text (Brutal Strike). The validator counts a plugin used by a `test` as used.
- **`revive.await_destination`** (boolean, like `move`'s): the table player's own fighter is not left to a note but asked (a `space` request, `near_opposing` in it names the combat's other fighter), and the bot reads the miniature's real space when they press Done; Unyielding Hordes needs it because its DURING counts the fighters next to the target. The Hazard source: an ONGOING `immune_to_effect_damage` status with `target: hero` (Might Of The Aen Elle) also stops `hazard` damage (`modifiers.adjust_damage`); a status from an op does not.
- **Table**: the human's Red Rider that comes back (Unyielding Hordes) is placed by hand BEFORE the DURING (see above); `session_translators._moved_piece` never moves a fighter the human was told to place (`game.placing`). A random card of the BOT's hand put on top of its deck (Backhand) is put on top on the table (`lua.hand_to_deck` without `bottom` or `shuffle`; `_bot_position` returns `top` only when the engine's deck really starts with it); the human's own random card goes by hand (a table note). The panel names the four Red Riders by their miniatures (Maxwell, Aleksei, Adrian, Norman: `choices.option_label` uses `Game.nicknames` only when several options share a name). Their tokens are Custom_Token in the save, which real TTS reports as "Tile": nothing that reads or moves a piece filters on the type.
- **Same CardID range as the other sheet-176 decks**: see docs/card-identity.md.
