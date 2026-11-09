# Yennefer & Triss (The Witcher: Realms Fall)

Playable by the bot and by the human, either side, against every other hero (both variants). Data read from the real card images (sheet 176 for the 30 cards, sheet 3 index 51 and 52 for the two character cards of the tournament savegame) on 2026-11-09.

## The design: one deck, two variants, each an ordinary hero plus one sidekick

The character cards say it: "At the beginning of the game, choose Yennefer or Triss to be your hero." The chosen heroine is the HERO (ranged, 14 HP, move 2); the other is the SIDEKICK (ranged, 6 HP, move 2, one piece). There are two character cards in the deck object of the save (351: Yennefer as the hero, 352: Triss as the hero) and each prints ONLY its own heroine's ability.

The engine already models "one hero plus sidekicks", so no new structure was added. The choice is the **variant**: two ordinary HeroDefs over the same deck.

| Variant | slug | hero | sidekick | ability | character card |
|---|---|---|---|---|---|
| Yennefer is the hero | `yennefer-triss` | Yennefer (14) | Triss (6) | SORCERESS OF VENGERBERG | 351 |
| Triss is the hero | `triss-yennefer` | Triss (14) | Yennefer (6) | MERIGOLD THE FEARLESS | 352 |

Why this and not a "form" (Hellboy's) or two hero fighters: a form changes during the game by a counter, here the choice is made once, before the game; two hero fighters would break every `game.hero(player)` caller (272 uses of fighter ids, the win condition, the AI's hero model). Two HeroDefs cost nothing in the engine: the card bands (`fighter`: Yennefer / Triss / any) follow who is the hero and who the sidekick, the 14 / 6 life, the abilities, the saves (the slug is saved with the game, so a resume keeps the variant) and the matrix (each variant is a hero of its own) all work as for any hero with a sidekick. The cost is paid in the table layer, because the two variants share one bag, one deck, one CardID range and one set of images:

- `tools/import_hero.py`: the overlay's `tts` block (`bag_name`, `character_cards`, `character_card_id`) and `memory_slug` (both variants read unmatched-memory's `yennefer-triss`); `tools/import_save.py` finds the bag named "Yennefer & Triss", the deck with two character cards (`deck_sheet(characters=2, character=351|352)`), the hero miniature (a Custom_Model) and the sidekick token (a Custom_Token) with the same name (`--check` passes).
- `Game.new` refuses two heroes whose fighter ids overlap, so the two variants can never face each other (they are the same deck).
- `hero_detect`: the deck cannot tell the variants apart; `_by_hero_piece` uses the HERO miniature that is out of the bag (see Pending for the panel question that Iván asked for).

### What the savegame says (read 2026-11-09, GUIDs of `data/tts/*.json`)

Bag `2b339c` (inner `eaf05e`): deck `7b2a33` (32 cards), two Custom_Models tinted with the heroine's colour (the hero miniatures: `cd27f6` "[384A60]Yennefer", `d1b3b9` "[F19638]Triss", no script), two Custom_Tokens (the sidekick pieces: `de2677` "Yennefer", `905f88` "Triss", single faced: `ImageSecondaryURL` is empty) and four life dials (Custom_Models with MAX_VALUE: 14 "Hero Health": Yennefer `d4701d`, Triss `799107`; 6 "Sidekick health": Yennefer `4dbc76`, Triss `00da50`). Iván described the sidekick as one double-sided token; **the save holds two separate single-faced tokens**, so the data uses them as two pieces (one per variant). To confirm live (`docs/live-checklist.md`).

## Cards (as implemented; identical in both variants)

| Title | Band | Type | Value | Boost | Copies | Effect |
|---|---|---|---|---|---|---|
| Incinerate | Yennefer | attack | 7 | 2 | 3 | Cannot be canceled. DURING: the opponent may discard 2 cards to ignore its value (Liz Sherman's card, word for word) |
| Echoing blast | any | attack | 3 | 1 | 3 | AFTER: if you won, it returns to your hand |
| Portal to anywhere | any | attack | 1 | 2 | 3 | AFTER: place a fighter of the combat in any space; gain 1 action |
| Merigold's Hailstorm | Triss | attack | 4 | 3 | 2 | AFTER: the OPPONENT chooses one: they discard 2 cards / 3 damage to their hero / they discard the top 4 cards of their deck |
| Telepathy | any | versatile | 3 | 1 | 3 | IMMEDIATELY: the opponent may discard 1 card; if they do not, cancel all effects on their card |
| Quick and ready | any | versatile | 2 | 2 | 2 | AFTER: place your fighter in any space in their zone; draw 1 |
| Ball lightning | any | versatile | 3 | 1 | 3 | AFTER: won: the opponent discards 1; otherwise both discard 1 |
| Paralyzing fetters | any | defense | 2 | 2 | 3 | IMMEDIATELY: the value of the opponent's card is its printed value and cannot be changed (Jill Trent's Stasis Diffuser) |
| Magical barrier | any | defense | 4 | 3 | 3 | IMMEDIATELY: your fighter recovers 1 health |
| Advisor to the king | any | scheme | - | 2 | 3 | Each of your fighters recovers 1; draw 1. ONGOING: your BOOST values are +1; discard it at the end of your turn if you did not attack |
| Lodge of sorceresses | any | scheme | - | 2 | 2 | Each player reveals a card of their hand and draws its BOOST value in cards; whoever drew most (all tied) deals that much damage to their own hero |

## Discrepancies with unmatched-memory
- Advisor to the king prints an ONGOING ("Your BOOST values are +1. Discard this card at the end of your turn if you didn't attack.") that unmatched-memory leaves out. Telepathy has a comma unmatched-memory drops ("If they don't, cancel..."). The overlay carries the printed texts.
- unmatched-memory lists the sidekicks as "Triss" and "Yennefer" with 6 HP, one each: that is the sidekick of either variant. The bands (Incinerate YENNEFER, Merigold's Hailstorm TRISS) are not in unmatched-memory: they are read from the card images.
- Titles, types, values, boosts and copies of all 11 titles match unmatched-memory (30 cards).

## Rules decisions (taken in the owner's absence, the most literal reading)
1. **Only the hero has an ability.** The character card of each variant prints one ability, the sidekick has none. So Yennefer's SORCERESS OF VENGERBERG works only when Yennefer is the hero, Triss's MERIGOLD only when Triss is.
2. **SORCERESS OF VENGERBERG**: "IMMEDIATELY: if Yennefer is attacking, you may BOOST her attack. (This effect cannot be canceled.)" is a free BOOST (the one a `may_boost` card gives, in DURING, one card) on every attack of Yennefer whatever the card; no cancel (Feint, Telepathy) takes it away. Her sidekick Triss attacking does not get it. The hero passive `may_boost` (docs/effects-dsl.md, section 36).
3. **MERIGOLD THE FEARLESS**: after Triss plays ANY scheme (also an ONGOING one and Lodge), the owner deals 2 effect damage to ONE fighter adjacent to Triss of their choice. It is mandatory: if only their own Yennefer is adjacent she takes it ("a fighter"). With nobody adjacent nothing happens. The bot chooses a rival fighter when it can (`EffectAI`).
4. **Merigold's Hailstorm**: the opponent (not the owner) chooses, win or lose. "Deal 3 damage to their hero" is effect damage to the opponent's hero; "discard 2 cards" is the opponent's own choice of cards; "the top 4 cards of their deck" mills what is there (no exhaustion).
5. **Quick and ready**: "their zone" = the zone of the OPPOSING fighter of the combat (the card says "your fighter ... their"). The fighter that played the card goes to an empty space of any zone the opposing fighter's space is in; then draw 1.
6. **Portal to anywhere**: the owner picks ANY fighter of the combat (either side) and any empty space, then gains 1 action.
7. **Telepathy**: the opponent may discard 1 card; if they cannot (empty hand) or will not, the effects of their card are cancelled.
8. **Ball lightning**: each player picks their own discard; a tie the defender wins counts as "not won" for the attacker.
9. **Advisor to the king**: the +1 is the owner's only, on every BOOST value they spend (combat and Maneuver); a card with no BOOST value still cannot be used to boost (the +1 does not make it legal). It is discarded at the end of the owner's turn unless one of their fighters attacked during that turn (a sidekick's attack counts).
10. **Lodge of sorceresses**: the revealed card stays in the hand; the BOOST value read is the PRINTED one (Advisor's +1 is for "BOOST values" spent, not read); the damage is effect damage to the player's own hero and happens after both draws; a player with an empty hand reveals nothing and draws 0. Simultaneous: each choice is made without seeing the other's (the bot picks from its own hand and hit points; the human names their card on the panel, one button per title).
11. **Incinerate, Paralyzing fetters** are Liz Sherman's and Jill Trent's cards, ruled the same way (docs/heroes/liz-sherman.md and jill-trent.md).
12. **Two variants, one game each**: the variants are the same deck and bag: they cannot be the two sides of one game.

## Open questions for Iván
1. Does the SIDEKICK keep the other heroine's ability? Applied: no, only the hero's (the printed character card carries a single ability). Alternative: both abilities always (Yennefer boosts even when she is the sidekick; Triss's trigger needs "Triss plays a scheme", so it would still need her to be the hero).
2. "After Triss plays a scheme": applied to the owner's every scheme while Triss is the hero (the player plays schemes through the hero). Alternative: only when Triss herself (not the player) is chosen as the scheme's fighter.
3. Merigold: the 2 damage is mandatory even on her own sidekick (applied). Alternative: a "may".
4. Quick and ready's "their zone" = the opposing fighter's zone (applied). Alternative: the zone of the opposing PLAYER's hero.
5. Advisor to the king's +1: applied to the BOOST values spent by the owner only, in combats and Maneuvers, not to Lodge's draw count. Alternative: also Lodge ("their card's BOOST value").
6. The sidekick token: the save has two single-faced tokens, Iván describes one double-sided token (see above).
7. Ball lightning: "your opponent discards 1" is the opponent's choice (applied), not the owner's.

## Pending (not done in this batch)
- **The panel question** "which of the two is your hero?" and the table set-up that follows it (the chosen heroine's character card next to the deck and the other out of play, the other heroine's hero miniature put away, the sidekick token) are NOT implemented: they touch the pre-game gate (`player_setup`, `table_reset`, `table_layout`: a closed bag holds all nine objects and fits neither variant's GUID set, a deck pile counts for both variants), the panel and the Lua of the table (`lua.py`), which cannot be verified without a live TTS. Today the variant is chosen by the slug (`--bot-hero yennefer-triss`, `config/table.json` `bot_hero` / `human_hero`) or, with the heroes on "auto", by the hero miniature of the chosen heroine out of the bag next to the deck (`hero_detect._by_hero_piece`; none or both out: a clear message listing the two slugs). The pre-game gate (Preparar) refuses the bag of this hero. The variant is saved with the game (`--resume` keeps it).
- **Physical check of the table against the choice** (character card / miniature / token face disagree): not done (needs the panel flow above).
- Live test (docs/live-checklist.md, section Yennefer & Triss).

## AI
- The AI profile comes from the data (`ai_profile`, per fighter). Card values use the generic machinery (`EffectAI` simulates each scheme and AFTER choice). Specific: `EffectAI._lodge_card` (reveal the card with the biggest BOOST the hero can afford to take twice over, else the smallest); the bot takes Echoing blast back from its combat spot to its hand (`session_sleight.bot_card_back`).
- The bot does not yet price Sorceress' boost as a reason to attack with Yennefer, nor keep Advisor to the king in play by attacking; the free BOOST is decided by the generic boost chooser (a card it can spare).

## Strength (simulator, heuristic AI, bprd-hq, seeds 0-9)
The bot's Yennefer variant and Triss variant against each scripted rival (`python -m sparring.sim`, the rival chases and attacks with its best card), 10 games each over the 19 other heroes, 380 games, zero errors: `yennefer-triss` 164 wins to 26 (Raphael 5-5, Medusa, Baba Yaga, Liz, Michelangelo, Bigfoot, Daredevil, Bullseye 8-2, the rest 9-1 or 10-0); `triss-yennefer` 159 wins to 31 (Medusa 5-5, Raphael 5-5, Liz 6-4, Luke Cage 6-4, Bullseye 7-3, the rest 8-2 or better). Information only. With a scripted human playing the hero and a bot rival the hero loses almost always: the scripted rival neither uses the abilities nor the sidekick. The sim also found a bug of the scripted rival, not of the hero: it chose Tomoe Gozen's Witness My Last Battle against a target that was not adjacent (`hellboy_script.try_attack` now filters by `Game.attack_card_reaches`).

## Tests
`tests/test_hero_yennefer_triss_data.py` (data, both variants, detection by the hero miniature), `tests/test_yennefer_triss_effects.py` (engine, every card and both abilities, both variants), `tests/test_yennefer_triss_human.py` (FakeTTS, panel: the human's boost, Merigold, Lodge, the bot's Hailstorm and Echoing blast, save and resume), `tests/test_yennefer_triss_matrix.py` (both variants against the 19 other heroes in both seats: full session games, an attacking human, headless with the heuristic and the search AI).
