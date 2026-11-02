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

### Boosts (Houdini, docs/effects-dsl.md section 26)

`dsl_during` asks one boost per card allowed (`may_boost`, `max_boosts`, or `allow_boost` for the rival's card): the first prompt is
filed under `<phase>:<side>:dsl_during`, the next under `...:dsl_during:<n>` (`PendingChoice.extra["n"]`), and the combat keeps the ids
it was boosted with (`CombatFlow.boosted`). Every boost card spent runs its `boost` moment as `boost:<side>:<n>` in `flow.runs`; while
it is paused `await_key` is `boost:<side>:<n>:dsl_during` so `awaiting_run` finds it. `to_dict()["dsl"]` also carries `boost_granted`,
`boosted` and `deferred_loss` (the owner of a hero the combat damage defeated while a `defers_defeat` card was in play: the loss is
settled when the flow reaches DONE). `replace_combatant` swaps who fights (Smoke And Mirrors) and rebuilds the sides.

