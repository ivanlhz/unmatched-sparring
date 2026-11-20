# Combat as a state machine (pure refactor)

Module: `sparring/combat_flow.py`. `combat.resolve_combat` is a synchronous facade over it. Behaviour is identical to
the previous hard-coded function; `tests/legacy_combat.py` keeps a verbatim copy of that function and
`tests/test_combat_flow_diff.py` checks the two agree over whole simulated games (5x4 hero pairs, `DIFF_SEEDS` seeds
each, default 3) and over hand-built scenarios.

## Binding constraints

- The save key stays `"boost_wait"`: both golden saves contain `"pending": {..., "boost_wait": null}`. The pending
  choice is stored under the same key; null stays null.
- `tests/test_review9.py` and `tests/test_review10.py` read `pending.boost_wait["stuck"|"hand"|"deck"|"card"]` and
  `saved["pending"]["boost_wait"][...]`. The new format stays flat, with a read-only compatibility property.
- The session must not start the flow at "Reveal": the action is spent and the cards leave the hand only at
  "Continue" (`g.attack` -> `use_action`, reach check after `sync_positions`). RuleError rollback and
  `_cancel_stuck_boost` depend on that. In this delivery the session keeps the wait as a `PendingChoice` and at
  "Continue" runs the flow from DECLARED with the answer supplied up front. Real pauses with the game already mutated
  belong to the human-choices phase.

## API

```python
class Phase(str, Enum): DECLARED, CARDS_SET, REVEALED, IMMEDIATELY, DURING, DAMAGE, AFTER, DONE

@dataclass
class PendingChoice:           # kind ("boost" only), player, card_id, deck, extra (caller-owned JSON-safe data)
    def to_dict(self) -> dict  # flat: {"kind","player","card","deck", **extra}
    @classmethod
    def from_dict(cls, raw, *, default_player, deck_of)   # also translates the old format (no "kind"); KeyError if invalid

@dataclass(frozen=True) class Await:  choice: PendingChoice
@dataclass(frozen=True) class Side:   name ("def"|"atk"), fighter, card, rival
@dataclass(frozen=True) class Rule:   name, phase, side, match, run, when_cancelled
RULES: list[Rule]                     # module level, registered by @rule(...) in declaration order

class CombatFlow:
    phase, side_idx, ctx, result, played, answers, pending, after_open, def_bonus_parts, values, sides
    step() -> Await | None            # one unit: a phase hook or the handler of the current side
    run() -> Await | None             # steps until Await or DONE
    drive(choose) -> None             # run to the end answering each Await with choose(choice)
    resume(card | None)               # stores the answer under "phase:side:rule"; clears pending
    answer(rule_name) -> (bool, Card | None)
    to_dict() / from_dict(game, raw)
```

Handler rules: the first matching rule wins per phase and side; registration order reproduces the old if/elif chains.
A cancelled side is skipped unless `when_cancelled=True`; cancellation is checked when that side's turn comes (a
defender Feint cancels the attacker before it resolves). Handlers are re-entrant: they return `Await` BEFORE mutating
anything; after `resume` the same handler runs again and finds its answer in `answers`.

A handler may swap the attacker's card while it runs (`replace_attack_card`). With `back_to_hand` (Sleight Of Hand, section 27 of
docs/effects-dsl.md) it happens inside the attacker's own IMMEDIATELY: the flow drops that side's finished-to-be run and sets `flow.again`,
so `step()` leaves `side_idx` where it is and the same side runs its IMMEDIATELY again, now with the new card. `again` is consumed in the
same step (never saved).

Engine hooks (code moved from the old function):

| Phase | What happens |
|---|---|
| DECLARED -> CARDS_SET | checks, `take_from_hand`, `played` |
| CARDS_SET -> REVEALED | values, hero passive, ONGOING from `combat_bonus_parts` (Fight Or Flight is only read here; it is added in `resolve_scheme`) |
| DAMAGE | the `def_parts` text (no attacker handler reads it), then damage and the result totals |
| entering AFTER | `after_open = game.winner is None`, decided once |
| entering DONE | played cards go to the discard |

Rules, in order:

| Phase | Rule | Side | Behaviour |
|---|---|---|---|
| IMMEDIATELY | planned_recklessness | any | PLANNED: effect_shield, cancels the other side unless form is ANUNG |
| DURING | on_earth_value | def | `when_cancelled`; both branches (cancelled or not) |
| DURING | boost_this_attack | atk | `can_boost(card)`: Await(boost, deck=deck_boost(card)); on answer skip `_check_boost` if deck |
| AFTER | bot_card_outside_the_interpreter | any | owner is `game.bot_player` and its hero is NOT interpreted (only a save that switched it off): the text is noted as unresolved |
| AFTER | human_card_after | any | the human's card of a hero outside the interpreter: `_hellboy_after` / `_liz_after`, else the text goes to `human_effects` |
| IMMEDIATELY / DURING / AFTER | dsl_* | any | a card of a hero in `fx.dsl_heroes` (Medusa since C5; the bot's box hero since D1): the effects interpreter |

C5 removed Medusa's own rules (`feint`, `second_shot`, `medusa_after`): her cards go through `dsl_*`. The verbatim
copies live in tests/legacy_medusa.py, the oracle of tests/test_medusa_dsl_diff.py. D1 removed `bot_card_after`
(`_announce_bot_card`, `CODED_MOMENTS`, verbatim in tests/legacy_combat.py): the bot's box hero goes through `dsl_*`
and `effects/narrate.py` writes what each run did into `result.applied`. `legacy_chooser` asks the bot's controller
for the boost of any of its interpreted cards (docs/effects-dsl.md section 16).

## Synchronous facade

```python
def resolve_combat(game, att, tgt, atk_card, def_card, values=(0, 0), boost=None) -> CombatResult:
    from .combat_flow import CombatFlow, legacy_chooser
    flow = CombatFlow(game, att, tgt, atk_card, def_card, values)
    flow.drive(legacy_chooser(game, flow, boost))
    return flow.result
```

`legacy_chooser`: the boost choice of a Medusa card goes to `game.controllers[player].choose_combat_boost(game,
flow.ctx)` (the same `CombatCtx` object as before, so `ai_medusa.py` and `search/adapter.py` read the same values);
any other card answers with the prefilled `boost` or None. The signature is unchanged for `state.attack`,
`search/adapter.py`, the sim and the AI. `CombatCtx`, `CombatResult` and `_side_cards` stay in `combat.py`.

## Session

Only `Pending.boost_wait` moves to a `PendingChoice` now.

- `Pending.wait: PendingChoice | None`; `boost_wait` is a read-only property returning `wait.to_dict()` (or None).
  Writing through the property would be silently lost, so mutations go through `p.wait.extra[...]`.
- `_await_boost` builds `PendingChoice("boost", human, card_id, deck_boost(card), {guid, baseline, hand, stuck})`.
- `to_dict` writes `"boost_wait": None if p.wait is None else p.wait.to_dict()`.
- `_load_boost_wait` is a translator: a dict without `"kind"` is the old format (player = human, `deck` recomputed from
  the card); same validations, still `KeyError("boost_wait")`.
- Left for the human-choices phase: `pending_discard`, `moving`, `placing`, `bot_stage`, `setup.stage`, `dial_debt`,
  `_wild_credit`, and the bot's `choose_move`/`force_discard` in AFTER.
- E1: the session no longer calls `Game.attack`; `Game.begin_attack` returns the flow and `Session._drive_flow` runs
  it. A `PendingChoice("effect")` of the human stops it: the flow is saved as `pending.flow` (with `pending.combat`,
  what `_after_combat` needs) and answered through `flow.resume(list)` from the choice buttons. A `RuleError`
  anywhere in that drive restores the save snapshot taken before it. See docs/effects-dsl.md section 14.

## Flow serialization

`to_dict`: phase, side_idx, after_open, values, ctx values and cancelled (sorted), fighter ids, attack/defense card ids,
`played` as `[owner, id]`, def_bonus_parts, answers, the awaiting key, pending, and the result (boost card id, parts
lists, applied, bot_notes, human_effects). `from_dict` looks cards up by id in `game.players[p].full_set` (played cards
are outside the hand mid-combat; the flow holds them and DONE discards them).

## Deviations from the first design

- `resolve_combat` body is 4 lines: the answer loop lives in `CombatFlow.drive`.
- `CombatFlow.answer` takes the rule name; the key `"phase:side:rule"` is built from the flow's current position.
  The flow also stores `await_key` so `resume` knows where to store the answer.
- `after_open` starts as `None` (not yet decided) instead of False.
- `CombatFlow.sides` and `card_by_id` are public (the chooser and the tests use them).
- `PendingChoice.from_dict` is generic (extras are kept verbatim); the strict validation of the boost extras stays in
  the session translator.

## Risks and how they are covered

- Defender/attacker order: fixed `[def, atk]` list from `_side_cards`; tested.
- Second Shot in DURING before the human's boost: attacker rules run after `on_earth_value`; the bot's
  `choose_combat_boost` gets the same ctx; the human boost enters as an answer, never through the controller.
- AFTER only without a winner: `after_open` is evaluated on entering AFTER and serialized; a death mid-AFTER does not
  stop the attacker's side, as before.
- Game over mid-combat: DAMAGE can set the winner; DONE always discards the played cards.
- RuleError half-way: same exception at the same point; the session restores state as before.
- Circular imports: `combat_flow` imports from `combat`; `combat` imports `combat_flow` inside the function.
- ISMCTS cost: rules are a module-level list, no copies; measured with `tests/test_search_*.py`.

## DSL rules (C2)

After the legacy rules, `dsl_immediately`, `dsl_during` and `dsl_after` match a side whose owner's hero is in `game.fx.dsl_heroes`; the legacy rules do not match those cards. `dsl_during` also asks the free BOOST of `may_boost` cards, for either side. `PendingChoice` has a second kind, `"effect"` (key + request of the paused EffectRun), and `flow.to_dict()` gains a `"dsl"` key only when an interpreter run, value change or redirection exists. See docs/effects-dsl.md section 12.

### Boosts (Houdini, docs/effects-dsl.md section 27)

`dsl_during` asks one boost per card allowed (`may_boost`, `max_boosts`, or `allow_boost` for the rival's card): the first prompt is
filed under `<phase>:<side>:dsl_during`, the next under `...:dsl_during:<n>` (`PendingChoice.extra["n"]`), and the combat keeps the ids
it was boosted with (`CombatFlow.boosted`). Every boost card spent runs its `boost` moment as `boost:<side>:<n>` in `flow.runs`; while
it is paused `await_key` is `boost:<side>:<n>:dsl_during` so `awaiting_run` finds it. `to_dict()["dsl"]` also carries `boost_granted`,
`boosted` and `deferred_loss` (the owner of a hero the combat damage defeated while a `defers_defeat` card was in play: the loss is
settled when the flow reaches DONE). `replace_combatant` swaps who fights (Smoke And Mirrors) and rebuilds the sides.


## Double attack (Battle of Legends, Volume Two)

Ivan's rules (20/11/2026): (1) the card's first part is the main attack, a normal combat; (2) the second part is a second attack against
the same defender, and the defender may defend it too; (3) it is an AFTER COMBAT effect of the card, so Feint (or anything that cancels the
card's effects) stops it; (4) a fighter moved in the first combat (Skirmish) does not stop it, even out of range or out of the zone; (5) the
timing order holds: IMMEDIATELY, DURING, AFTER, the defender's effect first at equal timing. The DSL is docs/effects-dsl.md section 45.

How it is built (one place: `CombatFlow`):

- The attacker's AFTER op `second_attack` only records `flow.second_attack = {"value", "card"}` (saved in `dsl`). A cancelled side never runs its
  AFTER, so a Feint, `cancel_effects` or `cancelled_after` stop it without any extra code; the defender's AFTER of the first combat already
  ran, because the defender goes first.
- `flow.second_due` (finished, a value recorded, the game not over, both fighters alive) and `flow.second_flow(def_card)` build the second
  attack as a combat of its own: `CombatFlow(..., second=value)`. It never checks reach or zone (rule 4), takes no action, raises no `attacked`
  event, does not take the attacker's card from the hand again, and the attacker's side has no handler (no effects, no BOOST: it is damage
  only). The defender's side is a normal side: the card it plays (or none) takes part with its IMMEDIATELY, DURING (its own free BOOST) and AFTER.
  Its attack total is the recorded value plus the persistent attack bonuses (hero passive, a fighter's `attack_bonus` status), not a "next attack" bonus.
- `combat.resolve_combat` (the synchronous callers: bot turns, the search, the sim) asks `choose_second_defense` of the defender's controller
  (`Controller`, defaults to `choose_defense` against a face-up attack) and drives the second flow; its result hangs from the first as
  `result.second`. The live session drives the two flows itself (docs/combat-flow.md "Session" above and the table section below).
- The second flow serializes with `"second": value`; the first, with `second_attack` inside `dsl`.
- The chat says the queued attack (`narr.second_attack`) in the card's line and the second combat's own result with `cf.second_attack`.

### Pending Ivan (double attack, nothing ruled; the most literal reading is implemented)

1. **BOOST on the second attack**: not allowed. The card's "may BOOST" is a DURING effect of the first part, already resolved; the second attack
   is "an attack of value N", so the attacker has no effects at all in it. The defender's card played against it keeps its own free BOOST (Out Of Time).
2. **Which combat "won / lost" refers to**: the first. The second combat does not emit `combat_lost` nor `after_attack`, so tallies such as
   "combats lost this turn" count the card once. Effects of the defender's second card that read "if you won the combat" read the second combat
   (it is the combat that card is in).
3. **Passives**: the hero's attack bonus passives (Achilles' +2) and persistent fighter statuses apply to the second attack (it is an attack by that
   fighter); a "your next attack" bonus does not (the first part used it).
4. **The defender's second card**: its IMMEDIATELY, DURING and AFTER effects apply normally (it is a defense card played in a combat). A Feint against the
   second attack cancels nothing (the attacker's card has no effects left there).
5. **No defender card**: the second attack is undefended. **Defeated by the first part**: if the game ended, nothing more happens; if the defender
   fighter (a sidekick) fell, there is nobody to attack and the second attack is lost; likewise if the attacker fell in the AFTER effects.
6. **Action count**: one action for the whole card; the second attack costs none and does not raise `attacked` again (so effects that trigger on
   being attacked, or tokens they spend, fire once).
7. **Order against the first combat's end events**: the second attack is played after the first flow is DONE, so `after_combat` of the first combat
   fires before it (a trigger on "after you attack" does not wait for the second part).
8. **Where the second part goes in the AFTER list**: when the op is reached; the attacker's other AFTER ops of the same card are not delayed by it
   (the second combat itself is played when the AFTER phase of both sides is over).
9. **Reach**: not checked again (Ivan's rule 4); this includes a defender that is out of reach for reasons other than a move.

### Double attack at the table (session)

`Pending.second` (`{"value", "card"}`, saved under `"second"`) marks the pending combat as the second attack of an already played card. `Session._after_combat`
ends the first combat as always (result, discards, dials) and, if `flow.second_due`, calls `_begin_second_attack` instead of "combat.after":

- the human attacks: a `human_attacks` pending; the bot reads its hand, chooses with `ai.choose_second_defense` (the value is public) and places its
  defense face down (`_place_bot_card(..., second=...)`, so a late reply is recovered into the same pending); the human presses Reveal with no card down;
- the bot attacks: a `bot_attacks` pending whose `bot_card` is the bot's card already played; the human puts a defense face down (or none) and presses Reveal.
  The human's defense may carry its own free BOOST (Out Of Time): `session_boost.offered` dry-runs the second flow;
- `_reveal` does not ask for an attack card in a `human_attacks` second (a leftover of the first part on the table is ignored; any other card of theirs is
  refused), `_resolve_combat` builds `CombatFlow(..., second=value)` (`_second_flow`) instead of `begin_attack` (no action, no `attacked` event), Cancel says the
  card is played and the second part cannot be taken back, and the flow ends in `_after_combat` like any other (a second attack never starts a third).
- Chat strings: `second.*`, `cancel.second_attack`, `err.second_no_card`, `cf.second_attack`, `narr.second_attack` (English in en.json, Spanish in es.json).

### Double attack in the AIs (`sparring/ai_double.py`)

- **Reading the data**: `has_second` / `second_value(game, owner, card, defense_value)` evaluate the card's AFTER ops for a given printed value of the rival's card
  (None: no card): a plain amount, the `if test: card on opponent_card` of Wukong ("the rival defended"), the `{attr: value, of: opponent_card}` of Bloody Requiem. Any other
  condition counts as not met, so an unknown card is never overvalued.
- **Heuristic, attacking**: `attack_outcome` adds `second_part` to the expected damage and the kill chance of every defense value the rival may answer the first part with:
  the damage left in the target after the first part, against a new defense drawn from the same distribution; both parts count for the value of the act.
- **Heuristic, defending**: `MedusaAI.choose_second_defense` is `_choose_defense(second=value)`: the value is exact (plus the attacker's passives), the attacker's card has no effects
  left, so there is nothing to sample.
- **Search**: the rollouts play the second attack through the engine (`resolve_combat`); the defender of the rollout is `SearchController.choose_second_defense`, the card that spares the
  most damage for what it is worth (`greedy_defense`). Live, `IsmctsMedusa.choose_second_defense` decides with the heuristic's exact-value choice (a search would only replay the first part).
- **Decision log**: the `plan` line of an attack with a double-attack card has `chosen.second_attack.value` (against no defense, a defense of 2 and of 4); the `defense` line of a second
  part has `chosen.second_attack` (its value) and, for the search, `via: "heuristic (exact second-attack value)"`.
- Not modelled: that the rival's first defense may be a Feint (it would stop the second part): the defense distribution carries values only.

