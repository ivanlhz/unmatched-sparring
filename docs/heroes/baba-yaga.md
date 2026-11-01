# Baba Yaga (Hellboy box)

Data read from the real cards of the tournament save (sheet 331, 8x4, and character card 332) on 28/10/2026.
Files: `data/heroes/overlay/baba-yaga.json` (CardID sheet), `data/heroes/baba-yaga.json` (generated HeroDef),
`data/heroes/effects/baba-yaga.json` (structured effects), `tests/test_hero_baba_yaga_data.py`.

## Summary

- Baba Yaga: 13 life, movement 2, ranged. Standee (Custom_Assetbundle `3de904`).
- Koschei: 1 sidekick, 3 life, melee, movement 2 (the hero's). Round token (Custom_Token `e0c176`).
  Starts on the board (1 on the board, 0 in reserve), on the player's start space. Returns to the table with
  Deathless (next to Baba Yaga, life 3) or Pact Of Mortality (in Baba Yaga's zone, life 3).
- Ability FATEFUL BARGAINS: if they share a zone, the effect damage Baba Yaga was going to take can be taken by
  Koschei (optional). In the overlay it is a `redirect_effect_damage` passive; the engine did not apply it yet at the time.
- No forms or counters. CardID = 33100 + idx (deck DeckIDs in the save), character card 33200.
- Deck: 30 cards. Baba Yaga 16 (The Time For Deals Is Done x2, Iron Teeth x2, Read The Bones x3, Foul Journey x3,
  Bound In Blood x2, 5 Pacts x1), Koschei 2 (Death's Release), ANY 12 (Remove A Painful Memory x2, Hasten Towards
  Death x2, Out Of Time x2, Deathless x3, Exploit x2).

## The Pacts (question 4 of the plan, settled with the cards)

Each Pact has an immediate effect, an ONGOING paragraph and the same discard condition: "Discard this immediately if
Baba Yaga takes 2 or more combat damage".

| Pact | Immediate | ONGOING |
|---|---|---|
| Freedom | Draw 2 cards. Place a hero in any space. | Players cannot attack as their first action each turn. |
| Mortality | Return a defeated fighter to any space in Baba Yaga's zone. Set their health to 3. | Increase all effect damage by 1, except for damage from exhaustion. |
| Peace | Deal 1 damage to each other fighter in Baba Yaga's zone. Gain 1 action. | At the end of each turn, deal 1 damage to each hero that attacked. |
| Secrecy | All players draw up to 2 cards, then shuffle all but 2 cards from their hand into their deck. | Players have a maximum hand size of 3. |
| Time | Each player shuffles up to 2 cards from their discard pile into their deck. | Players cannot gain actions. |

In the DSL: `persistent_scheme` with `ongoing` (`rule` or `trigger` ops) and `until` (2+ combat damage to Baba Yaga).
Four titles (9 cards) ask "if you have an active ongoing scheme" (Iron Teeth, Foul Journey, Remove A
Painful Memory, The Time For Deals Is Done): the condition is `has_active_scheme`.

## Decisions

1. card_base 33100 and not 18700: the loose deck cards carry key 187 of the original mod, but the engine uses the
   deck's DeckIDs (like Hellboy with 19700). The real identity is the FaceURL.
2. FATEFUL BARGAINS and Bound In Blood share the `redirect_damage` primitive (optional effect / mandatory combat):
   two uses, so a primitive and not a plugin.
3. The plan's `baba:remove_painful_memory` plugin is not needed: `look_hand` + `choose_n` (with `bind`) +
   `optional` with an `else` branch decided by the rival. What remains (which card to choose, discard or take the damage) is AI.
4. The ONGOINGs are global rule modifiers, not fighter statuses: a new `rule` primitive with four values
   (no_attack_as_first_action, effect_damage_bonus, max_hand_size, no_gain_actions) and an end_of_turn `trigger` for Pact
   Of Peace.
5. Out Of Time asks for two small primitives, `boost` (boost this card during the combat) and `end_turn`.
6. A `pact` tag on the 5 scheme cards in case a counter or the AI wants to tell them apart.

## New primitives requested

`redirect_damage`, `rule`, `trigger`, `boost`, `end_turn`. Plus new arguments on ops of the vocabulary:
`persistent_scheme.ongoing/until`, `optional.else`, `choose_n.from/up_to/bind`, `for_each` over players with
`$player`, `draw.up_to`, `discard` with target `active_scheme`. Exact semantics in `primitives_needed` of the effects
file.

## Coverage

16/16 titles (30/30 cards) with primitives; 0 plugins. Hidden information: Remove A Painful Memory (rival hand),
Read The Bones (own deck), Pact Of Secrecy (hands after the effect), and the draws of Pact Of Freedom and Exploit; the
bot's protocol for each one is in `hidden_info`.

## Discrepancies with unmatched-memory (the card wins)

- Deathless: "as close to Baba Yaga as possible" (memory: "Baba Yaha").
- Pact Of Mortality: "Set their health to 3" (memory: "healt").
- Read The Bones: "Randomly put the rest on the bottom" (memory: "put rest").
- Ability: "FATEFUL BARGAINS" without a "!" (corrected in the overlay with `ability`).
- The five Pacts: memory only has the immediate effect; the ONGOING and the discard condition are missing.
- Corrected in the HeroDef: the overlay sheet entries carry `text` with the real text (Read The Bones,
  Deathless and the 5 Pacts) and `tools/import_hero.py` prefers it to memory's (`entry.get("text") or card_text(src)`,
  the same convention as Liz's branch).

Life, movement, attack type, values, boosts and copies match the cards.

## Ivan's decisions (28/10)

- 'takes 2 or more combat damage' is within a single combat; if Bound In Blood diverts the damage to Koschei, Baba Yaga does not take it and the Pact continues.
- only one ONGOING can be active per player: playing a new one replaces the active one (it goes to the discard). The Time For Deals Is Done discards that one.
- E3 (29/10): Remove A Painful Memory played by the human: the bot lays its hand face up (row + ping); with an active Pact of the human's, they choose by ping or button and the bot decides alone between discarding that card or taking 2 (the chat says which); without a Pact, it is only looked at. Played by the bot: the bot names the card seen and the human answers with the buttons 'Discard <card>' / 'Take 2'.
- Pact Of Secrecy 'draw up to 2': each player chooses how many (0-2).
- Pact Of Mortality 'Return a defeated fighter' applies to any defeated fighter, the rival's too.
- Iron Teeth and The Time For Deals Is Done also damage Koschei, as the text says.
- Deathless: if Koschei is defeated he returns as close as possible to Baba Yaga with 3 life; if alive, he moves as close as possible to her and his life becomes 3 (the card says so).
- Pact Of Freedom: 'hero' is always the main character; 'fighter' is hero or sidekick. Any hero, own or rival's, is placed, never a sidekick.

## Open questions

- None.
