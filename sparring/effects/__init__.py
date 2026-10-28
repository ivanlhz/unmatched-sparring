"""Effects interpreter for the card DSL (docs/effects-dsl.md).

Modules: model (load the JSON), select (selectors, amounts, conditions), choose (decisions and who makes them),
run (re-entrant EffectRun), ops_core (the op registry), state (EffectState, the `Game.fx` hook target).
Nothing here is imported by the engine except `state`, so heroes outside `fx.dsl_heroes` never touch it."""
