# Changelog

## 0.8.0 · 2026-11-18

Changes since 0.7.2.

### New heroes (bot and human)
- **John Henry**: STEEL-DRIVING MAN track tokens on the board, free walks and paths, 12 cards. Power Through gives the free walk to John Henry only.
- **Rosie the Riveter**: the bot flips, re-orders and pings the four physical upgrade tokens. Merlin Engine is part of her move value and counts in the rival-reach estimate. D-Day and Rapid Development give an attack-only free action.
- **Wyatt Earp**: engine free attacks, SHOWDOWN, the exhaustion draw and a message when a bound action is refused.
- **George Washington** (Stars and Stripes): attack-only free action; Make A Stand compares against the space he started the turn on.
- **Philippa**: Spymaster ruse in both directions (against a human, the bot lays the 4 revealed cards in the row and the human puts 2 in the bot's pile), Blinding Dust, resume mid-ruse.
- **Raptors**: team hero that loses only when all three fall, pack bonus, swarm AI that values zone damage per fighter, Ambush through the shared random-discard flow; Coordinated Attack Pattern asks one question.
- **Chupacabra**: Ambush against a human: the bot names a position, the human lays that card on their pile and presses Done, and the bot reads it.
- Sheet 187 is marked as shared between the heroes that use it (data, docs, tests).

### AI
- Decision journal (F-AI-DECISION-LOG): every bot plan and defence writes a JSON line with its alternatives and a linked outcome.
- New tools: `review_decisions` (surprises and coin flips of a game) and `ai_duel` (bot A vs bot B on shared seeds with swapped seats, Wilson interval, sequential test).
- Regression positions from the live games of 15-16 November.
- Doctor Strange attacks more under ISMCTS (F-STRANGE-AGGRO): his own evaluation profile, caution 0.3.
- The Raptors bot keeps a reserve of cards instead of attacking with its last one.
- The Liz bot: Wildfire and Flame Lash discard the bottom card of the real deck.
- Desktop launcher: a Difficulty choice (Easy = the 0.7 evaluation, `--ai-eval old`; Hard = the new one, the default) for the ISMCTS bot.
- Hellboy plays at most one card on a pure movement turn.
- Echo's kill chance comes from the known cards and the unseen pool; the bot skips the attack above 25 %.

### Rules and flow
- The End action warns once about attack-only actions and gives them up only on a repeat press with no action in between.
- A discard no longer closes a pending move: the AFTER COMBAT walk stays open and a second End action asks for it (F-DISCARD-THEN-MOVE).
- A random discard says how many cards it was drawn from and shows the notice once; a hand of one card has its own wording (F-RANDOM-DISCARD-TEXT).
- Counter dials follow the discard pile for any hero. This generalizes Ciri's Source dial and fixes Sinbad's Voyage dial, which was never written.
- A vetoed discard binds nothing (Ambush under ISMCTS).

### Fixes
- Prepare no longer fails with "reset left the table dirty" when Sinbad is in play (the table snapshot reads the counter dials).
- The bot's scheme narration follows what the card says (shuffle), not where the engine's shuffle left the card.
- Raptors: Echo's dial continues the sidekick column; the audit takes up to 200 presence rows.
- The bot's ruse chat line no longer names the card; Bullseye's dial collision is allowed.

### Docs and tests
- Hero docs with the owner's rulings, DSL sections 40-43, card identity, live checklist, README and `features.json` updated.
- Matrix tests pair the new heroes against the rest of the roster.
