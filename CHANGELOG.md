# Changelog

## 0.9.0 · 2026-11-19

Changes since 0.8.0.

### AI
- **Turn plans** (Hard difficulty, ISMCTS with the new evaluation): before acting, the search compares its own line with a pressure plan (the best blow now) and, with two actions left, hitting and then withdrawing. Each plan is played on 16 shared deals through the rival's reply (two turns, four when the bot trails with the shorter deck) and replaces the tree's action only when its gain is clear: above its own noise and above how much the tree preferred its action. The decision journal records the three scores, the gains and the plan chosen.
- With no blow left in the turn, the comparison spends the remaining action on the same unboosted withdrawal for every plan instead of a random move.
- Fixed: a plan could skip the scheme that draws the only defence card (Sinbad's Regroup), and a hit-and-withdraw plan overrode a scheme the tree clearly preferred (Ciri against Doctor Strange, turn 15 of the 18/11 game: Cloak of Levitation cancelled the attack).
- Regression position from the 18/11 Ciri vs Doctor Strange game.

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
- Desktop launcher: a Difficulty choice replaces the AI select (Easy = heuristic bot, Normal = ISMCTS with the 0.7 evaluation, Hard = ISMCTS with the new evaluation, the default).
- Hellboy plays at most one card on a pure movement turn.
- Echo's kill chance comes from the known cards and the unseen pool; the bot skips the attack above 25 %.
- **New ISMCTS evaluation by default** (F-AI-EVAL-RESOLUTION, with `--ai ismcts`): sides and cards measured in hit points, an exhaustion race that no longer rewards ending the game, the deck priced near its cards, threat per fighter, the face-down attack drawn from the dealt hand. `--ai-eval old` (and `eval=old` in `ai_duel`) keeps the evaluation of 0.7. Weights set under `ai_eval` in the config JSON now apply on top of the new evaluation.
- **The bot keeps its last defence card** (F-AI-DISCARD-DEFENSE): the hand-limit discard, the discards a card effect asks for and the discards inside the search give up an ordinary card instead of the only card able to defend; a defence card is the dearest maneuver boost when it is the last one. Unbridled rage spends it only for the blow that wins the game, and prices the damage the rival really takes (Luke Cage).
- Cards of a defeated sidekick are given up first only when no card left in the deck or hand can bring it back (Winged Frenzy, Deathless, Pact Of Mortality, Secure The Scene, Unyielding Hordes, Recruit To The Ring).
- The search is faster again on hands full of schemes: the verdict "this scheme only spends cards" is memoized (Baba Yaga: about a third more iterations on the first decision of a game, 308 to 409-416 in the measured position).
- Fixed: the search could model the same rival card twice in a hand and crash on the hand-limit discard (it fell back to the heuristic); No, Really, I'm a Doctor left the revealed card counted in Strange's hand instead of on top of his deck.
- Regression positions from the live games of 17 November (Sinbad keeps Regroup; Liz maneuvers in near ties, informational).
- The rival-reach estimate counts the extra space a VOYAGE card adds when Sinbad spends it as his maneuver boost (Voyage Home moves him 2).
- `ai_duel`: the two configurations of a duel no longer share the search's cached maneuver lists, which had mixed their results. Measured again with this fix (200 iterations, swapped seats), the new evaluation beats the 0.7 one: Ciri vs Sinbad 66 % (128 games), Sinbad vs Liz 75 % (40), Medusa vs Daredevil 81 % (32).

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
- Daredevil (human): a BLIND BOOST card goes from the top of the deck to the discard pile and is no longer asked for "from your hand"; the game could get stuck waiting for it after Devil of Hell's Kitchen shuffled it back. His ability ("2 or fewer cards in your hand") reads the real hand on the table; Man Without Fear still gives its own blind boost. A card the bot was waiting for that a later effect moved into the deck no longer blocks End action (the chat says so).

### Docs and tests
- Hero docs with the owner's rulings, DSL sections 40-43, card identity, live checklist, README and `features.json` updated.
- Matrix tests pair the new heroes against the rest of the roster.
- Stale tests fixed (decision journal in the fake session, heroes missing from unmatched-memory listed as pending); the search time tests check the budget is kept and hold iteration floors measured on 18 November.
