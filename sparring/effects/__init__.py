"""Effects interpreter for the card DSL (docs/effects-dsl.md).

Modules: model (load the JSON), select (selectors, amounts, conditions), choose (decisions and who makes them),
run (re-entrant EffectRun), ops_core (the op registry), state (EffectState, the `Game.fx` hook target), driven
(abilities and schemes the engine's callers drive with decisions taken up front).
The engine imports `state` and `ongoing` at load time and the rest lazily, so heroes outside `fx.dsl_heroes` never
run through it."""
