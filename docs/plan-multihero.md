# Plan: a bot adaptable to any hero (27/10/2026)

Design by Opus (read only). Pending approval by Iván; not to be touched until F05 (Medusa vs Hellboy playable) is stable.

## Idea
The engine, the combat skeleton, the session, saving and the TTS bridge stay. What is specific to each hero moves to:
- `data/heroes/<slug>.json` (HeroDef: life, movement, melee/ranged, sidekicks with a count, forms, counters, triggers, passives), imported from unmatched-memory + a hand-written overlay.
- `data/heroes/<slug>.cards.json` with structured effects per moment (immediately/during/after/scheme/ongoing).
- An interpreter of reusable primitives in `sparring/effects/` (damage, heal, draw, discard, move, place, revive, cancel, modify value, statuses, counters, permanent schemes, look at the rival's hand, choose N, optional). Rule: a primitive only enters if 2+ cards use it; anything else is a per-hero Python plugin.
- Human choices through the panel (option/target buttons) with a persisted PendingEffect that can be replayed on resume; movements stay physical.
- Generic AI (`sparring/ai/`): rival hand model, action generator, evaluation by simulating effects on a clone, per-hero tuning in `data/ai/<slug>.json`. MedusaAI stays as the reference until the generic one equals it in the simulator (±3 points over 500 games).
- TTS config per hero in `data/tts/<slug>.json`; `config/table.json` gains `bot_hero`/`human_hero` (medusa/hellboy by default).
- Uncoded cards: the bot announces the text and plays them only by value/boost; nothing breaks as the roster grows.

## Feasibility of the Hellboy box (Hellboy, Abe Sapien, Baba Yaga, Liz Sherman)
- Cards: 49/55 (89 %) with primitives, 52/55 (95 %) with the hidden-information protocol.
- Abilities: Hellboy and Baba Yaga with data; Abe and Liz with a plugin.
- 5 plugins: abe:perfect_shot, baba:remove_painful_memory, liz:incinerate, abe:uncanny_intuition, liz:wildfire.
- Medusa: 100 % with primitives.

## Steps (each with the suite green and Medusa vs Hellboy working)
0. Pin the current behaviour with golden tests (simulator, FakeTTS session transcript, save round trip).
1. HeroDef + loader without changing behaviour.
2. Build the game from HeroDef.
3. Forms and counters from data.
4. Effects interpreter (not wired yet).
5. Medusa in the DSL (differential test against the current code).
6. Hellboy in the DSL + generic combat.
7. Choices through the panel + resuming mid-effect.
8. Generic triggers.
9. Generic counters and dials.
10. Generic config.
11. Generic AI behind a flag, gated by the simulator.
12. Generic scripted rival + simulation matrix.
13. The rest of the Hellboy box (data, 5 plugins, permanent schemes, looking at the hand, face-up attack) + a supervised live game per hero.
14. Full roster with an effect coverage report.

## Risks
Resuming mid-effect; refactoring session.py (1588 lines); a weaker generic AI; gaps in the unmatched-memory data (fighter restrictions, destiny/burning tags, the texts of the Pacts); mapping CardID sheets by hand.

## Questions for Iván
1. Abe's agents: how many start on the board and how many in reserve.
2. Liz's burning cards (the 15).
3. Fighter restrictions of Abe, Baba Yaga and Liz: from the TTS sheet as with Hellboy?
4. The permanent text of each of Baba Yaga's Pacts.
5. May the bot read your hand only when a card says "look at the rival's hand"?
6. Choices with buttons and physical movements: fine?
7. Do the other heroes come from the same TTS mod?
8. Form change when the bot plays Hellboy: does it change the miniature itself or ask you to?
9. Is the MedusaAI level enough as a base for all, or per-hero tuning from the start?
10. Maps: only B.P.R.D. HQ or also Azuchi and the rest?
