# Wyatt Earp (Stars and Stripes)

Playable by the bot and by the human, either side, against every other hero. Data read from the real card images (sheet 187 of the tournament savegame, character card 401 on sheet 4) on 2026-11-13, then compared with the transcription of Iván's screenshots (unmatched-memory `data/heroes/wyatt-earp.json`, "unverified").

## Summary
- Ranged hero, 15 life, move 2, sidekick **Doc Holliday** (ranged, 8 life, move 2, one of them). Hero fid `wyatt`, sidekick fid `doc`, slug `wyatt-earp`.
- Ability **SHOWDOWN**: "After you attack and win combat, choose one effect. You cannot choose the same effect twice in a turn: draw 1 card; gain 1 free action to attack; move your fighter up to 1 space." Implemented as the hero's own AFTER (`ability.after`, docs/effects-dsl.md section 33) with a `choose_effect` whose three options each close once a turn (`options[].condition`, section 40).
- Deck: 30 cards, `CardID = 18700 + idx`. Restriction band: WYATT EARP on Stand There, Fan The Hammer, Marshal, Gunfight, Bring 'Em To Justice, You Die First; DOC HOLLIDAY on I Have Two Guns, Daisy, In Vino Veritas; ANY on Second Shot, Huckleberry, Better Swear Me In. The deck object in the save holds 31 cards (the 30 plus the character card 401), hence `card_count 31` in the catalog.
- Table: bag `cde243` (inner `494e23`), deck `0e4426`, Wyatt's miniature `aa2509` (an assetbundle) and dial `facfe3` (max 15), Doc Holliday's piece `3f56bb` (a Custom_Token, like Daisy's and The Porter's) and dial `7f71e0` (max 8). No counter dial, no other token, no GUID shared with another hero.

## Card identity
His deck is one of **several on sheet 187** (CustomDeck key 187): Wyatt Earp (deck `0e4426`, character card 401), George Washington (`15548c`, 404) and John Henry (`c3109e`, 403) all use CardIDs 18700-18729 and differ only by FaceURL (loose Hellboy and Baba Yaga cards also carry key 187). Everything in docs/card-identity.md applies: a CardID names a card only together with its owner or the deck image. `data/tts/wyatt-earp.json` carries his images (`deck.identity`) and the detection works on them like for every hero (`tests/test_hero_wyatt_earp_data.py`: the sheet-187 decks share the range but have distinct images; images distinct against the 22 other heroes in both seats, detection in both seats, catalog entry, no shared GUID, `tests/test_wyatt_earp_matrix.py`).

## Check of the transcription against the real cards (asked by Iván)
Every title, value, boost, restriction, copy count and text of the 12 titles (30 cards) and the hero sheet (HP, move, range, ability, Doc Holliday 8 HP / move 2 / ranged) was compared with the card images in the save. **No mismatch**: the 30 cards, the restriction bands, the printed `xN` copies and the texts agree word for word with unmatched-memory. Only the typography of the ability differs: the card prints "twice in a turn" in one sentence and three arrowed lines, unmatched-memory has bullets. The data are pinned by `REAL_CARDS` in `tests/test_hero_wyatt_earp_data.py` (read from the images, not from unmatched-memory).

## Cards (as implemented)

| Title | Type | Value | Boost | Copies | Fighter | Effect |
|---|---|---|---|---|---|---|
| You Just Gonna Stand There And Bleed? | attack | 5 | 1 | 3 | Wyatt | none |
| I Have Two Guns, One For Each Of You | attack | 4 | 1 | 3 | Doc | AFTER: if the rival played a card, damage equal to its printed value to a different opposing fighter in Doc's zone |
| Second Shot | attack | 2 | 1 | 2 | any | DURING: you may BOOST this card |
| Fan The Hammer | attack | 1 | 3 | 2 | Wyatt | AFTER: if the opposing fighter was defeated, the card returns to the hand |
| You're A Daisy If You Do | versatile | 4 | 3 | 2 | Doc | AFTER: draw 2 |
| A Marshal And An Outlaw | versatile | 3 | 2 | 3 | Wyatt | AFTER: defending, draw 1; attacking, the opponent discards 1 card (their choice) |
| I'm Your Huckleberry | versatile | 3 | 2 | 3 | any | AFTER: if you won, 1 damage to an opposing fighter in your fighter's zone |
| Gunfight At The O.K. Corral | versatile | 2 | 3 | 2 | Wyatt | AFTER: 1 damage to any fighter (you), 1 (the opponent), 1 (you), 1 (the opponent) |
| Better Swear Me In | versatile | 2 | 2 | 3 | any | IMMEDIATELY: cancel all effects on the opponent's card; AFTER: reveal the top card of their deck, you may bury it |
| Bring 'Em To Justice | defense | 0 | 2 | 3 | Wyatt | DURING: reveal the top card of their deck, +2 x its BOOST value |
| In Vino Veritas | scheme | - | 3 | 2 | Doc | draw until you have 4 cards; gain 1 free action to attack |
| You Die First | scheme | - | 3 | 2 | Wyatt | move an opposing fighter up to 1 space; gain 1 free action to attack that fighter |

## Engine additions (all additive, docs/effects-dsl.md section 40)
- **A free action that can only attack.** `Game.free_attacks` (a list: the fighter id each one must attack, `None` = anyone, saved in `persist`, copied by `clone`, emptied by `begin_turn`) marks that many of `actions_left` as attack-only. `Game.use_action(attack_on=fid)` spends a free one first (the one bound to that fighter, then a general one) and then an ordinary one; anything else (`maneuver`, `play_scheme`) needs an ordinary action (`Game.paid_actions`) and raises `RuleError` (`err.only_free_attacks`) before anything is spent. `Game.grant_free_attack(target)` honours `cannot_gain_actions` and the `no_gain_actions` rule. `Game.prune_free_attacks(player)` drops the free actions nobody can use (no card in the hand that attacks a fighter they allow): every loop of the bot ("while actions are left") calls it, so the turn ends instead of looping (heuristic `take_turn`, the search's `take_turn` and `_advance`, the session's bot loop, the scripted rivals of the simulator).
- **`choose_effect.options[].condition`**: an option whose condition does not hold is not offered (and is never asked when none is left). SHOWDOWN uses the counters `showdown_draw`, `showdown_attack`, `showdown_move` (`ability.counters`, 0-1), set to 1 by the option and to 0 by the `showdown_reset` trigger at the owner's start of turn. The request carries `tag: "showdown"` and `attacker` (the fighter that attacked: `ChoiceRequest.extra`, any `choose_effect` with a `tag` in an attack gets it).
- **Fighter filter `except`** (`"filter": {"except": FighterRef}`): "a different opposing fighter" (I Have Two Guns: `{"side": "enemy", "where": {"zone_of": "this"}, "filter": {"except": "opposing"}}`).
- **`move.purpose`** (runtime only, written by a plugin): travels in the request so the bot can tell You Die First's move from any other move of a rival piece.
- **Plugins** (`sparring/effects/plugins_wyatt.py`): `wyatt:free_attack` (the grant), `wyatt:you_die_first` (pick a rival fighter, move it, bind the free attack to it), `wyatt:swear_me_in` (Jill Trent's reveal, then yes/no to bury), `wyatt:bring_to_justice` (`jill:hypnoray` with a factor of 2). The table side is Jill Trent's: `reveal_top` and `deck_order` (the bot's deck is pinned, the human's real deck is buried blind by the bot).
- Table and panel: the narration says "gains 1 free action to attack" (`narr.gain_free*`), the chat after each action says how many actions are left and how many of them are free (`turn.left_free`), a Maneuver or a scheme pressed with only free actions left is refused with a warning (`Session._require_paid_action`), the panel asks SHOWDOWN (`choice.prompt.showdown`) and the burying (`choice.prompt.bury_rival`).

## The loop SHOWDOWN could feed, and its bound
SHOWDOWN can give a free action to attack, and an attack that wins can offer SHOWDOWN again; In Vino Veritas and You Die First give free attacks too. Bounds, all tested (`tests/test_wyatt_earp_effects.py`, `tests/test_wyatt_earp_ai.py`):
1. Each of the three effects is open once a turn (counters), so SHOWDOWN offers at most three times in a turn and the free action only once: from the two ordinary actions a turn is at most 2 + 1 attacks through SHOWDOWN (the chain "free attack, win, free attack, win..." stops at the second win: the free action is already used).
2. In Vino Veritas and You Die First each cost a scheme action and give back one that can only attack, so they cannot be chained into more attacks than the cards in the hand (and each is a card).
3. A free action nothing can use is lost (`prune_free_attacks`), for the bot and the scripted rivals; the human can simply end the turn.
4. The restriction is in the engine, not in the AI: `use_action` refuses a Maneuver or a scheme with only free actions left, and the search (`EngineState._generate_moves`) offers only attacks then.

## Rule decisions (the most literal reading of the card; confirmed by Ivan, see "Decided by Ivan")
1. **SHOWDOWN's trigger**: "after you attack and win combat" is an attack of the owner (Wyatt's or Doc Holliday's, whoever the card is played by) that the owner won (the engine's result: the attacker wins only if combat damage lands), run in the AFTER, before the card's own AFTER, also when the card's effects were cancelled (the ability is the hero's). Defending never triggers it.
2. **"Your fighter"** in "move your fighter up to 1 space" is the fighter that attacked. The owner may move 0.
3. **"Free action to attack"** is an extra action that can only be spent on an attack, with any fighter and any card that can attack. For You Die First it can only attack the fighter that was moved. The free action is spent before an ordinary one, so it never costs more than the action it replaces. It is lost at the end of the turn.
4. **"Draw until you have 4 cards"** is a draw of what the hand lacks after the scheme left it (`{"hand_deficit": 4}`, docs/effects-dsl.md section 40), nothing with 4 or more. With a deck that cannot give them all, each missing card is the usual exhaustion (2 damage to each of the owner's fighters), as for any draw.
5. **I Have Two Guns**: "a different opposing fighter in Doc Holliday's zone" is any other rival in a zone of Doc's space except the fighter of this combat; the damage is the PRINTED value of the rival's card (also when its effects were cancelled, or its value was changed in the combat). No rival card, or nobody else in the zone: no damage. The owner picks the victim.
6. **I'm Your Huckleberry** may hit the fighter of the combat if it is still standing ("an opposing fighter in your fighter's zone").
7. **Gunfight At The O.K. Corral**: four hits of effect damage in the printed order, the owner choosing the 1st and 3rd and the opponent the 2nd and 4th; "any fighter" includes each one's own fighters.
8. **A Marshal And An Outlaw**: the rival chooses the card they discard; the bot's hand is chosen by the bot (the bot's EffectAI), the human's by the human at the table.
9. **Better Swear Me In**: the IMMEDIATELY cancels the rival's effects, and its own AFTER still runs (the card cancels the rival's card, not its own). The top card of the rival's deck is revealed (the engine's deck for the bot, the real deck read from the table for the human) and the owner may put it at the bottom. An empty deck reveals nothing.
10. **Bring 'Em To Justice** adds twice the BOOST of the revealed card to this defense; the value is added in the DURING (a locked value, as Stasis Diffuser's, ignores it).
11. **Fan The Hammer** returns to the hand only if the fighter it fought was defeated (after the damage of the combat); the card then does not reach the discard pile.

## Decided by Ivan (2026-11-13)
Ivan confirmed all the readings implemented above:
1. **Free action to attack** is attack-only (and, for You Die First, only against the fighter that was moved).
2. **SHOWDOWN applies to Doc Holliday's attacks** (you attack: the player).
3. **Your fighter** (the move option) is the fighter that attacked.
4. **I'm Your Huckleberry** may hit the opposing fighter of the combat.
5. **SHOWDOWN resolves before the card's own AFTER.**
6. **In Vino Veritas with a short deck** pays the usual exhaustion for each card the deck cannot give.

## Pending Ivan
1. **Doc Holliday's table piece** (`3f56bb`, a Custom_Token) is found like Daisy's and The Porter's: to check live.

## AI
- Profile from the data (`ai_profile`): Wyatt `hero`, ranged; Doc Holliday `striker`, ranged. Name-based values live in `sparring/ai_wyatt.py`.
- **SHOWDOWN** (`ai_wyatt.pick_showdown`, called by `EffectAI._effect` for `tag: showdown`): each open effect is priced in the evaluation's units and the best is taken (a tie: the first printed). The draw is an average unseen card (worth less than nothing when the hand is at its limit and no action is left); the free action is the best net value of an attack the hand can still make from where the fighters stand (`MedusaAI.attack_outcome`), or less than nothing when nothing can use it; the move is the gain in `position_value` of the best step for the fighter that attacked. The search's rollouts use `rollout_showdown` (greedy: the free action when the hand can use it, else the draw; safe: the draw).
- `MedusaAI.attack_outcome` adds `ai_wyatt.after_value` (Daisy's two cards, the Marshal's strip or draw, Huckleberry's hit, Fan The Hammer's return, Two Guns' second target, the look of Better Swear Me In) and `showdown_edge` (winning is worth the draw of the first open effect), `eval_defense` prices Bring 'Em To Justice as twice the average BOOST of the rival's deck.
- **Free actions in the plans**: `MedusaAI.candidates` offers only attacks on the allowed fighters when only free actions are left; `plan`, `take_turn`, `apply_expected` (an attack spends the free action), `scheme_act` (a free action nothing can use is worth nothing), the search (`EngineState`: the attack spends it, only attacks are generated, the signature of the cache holds it, `_advance` prunes) and the session's bot loop know it.
- **You Die First**: `die_first_fighter` and `die_first_dest` choose the rival the hand can strike best once moved (or left) and the space it is struck from; **Better Swear Me In** buries the revealed card when it is worth more to the rival than the average card they still hold (`bury_rival`, the same judgement as the future of Ninjutsu).

## Strength (simulator, heuristic AI, bprd-hq)
`python -m sparring.sim`, the bot's hero against the scripted rival (it chases and attacks, plays no schemes and resolves no text effects: only a sanity check of the pairing, never a balance statement). Bot's Wyatt, 10 games each, seed 100: Hellboy 10-0, Medusa 10-0, Leonardo 9-1, zero crashes. With the search AI (`--ai ismcts --iterations 40`): Hellboy 2-1 and Leonardo 4-0 in the first games.

## Tests
`tests/test_hero_wyatt_earp_data.py` (data, card identity, the transcription check), `tests/test_wyatt_earp_effects.py` (SHOWDOWN and its bound, the free action, every card, the schemes), `tests/test_wyatt_earp_ai.py` (the SHOWDOWN choice, free actions in the heuristic and the search, the cards' valuation), `tests/test_wyatt_earp_human.py` (FakeTTS, the panel: the three effects as buttons, the refused Maneuver, In Vino Veritas dealing, You Die First on the bot's fighters, the bot's deck revealed and buried, the bot's Wyatt playing against a human), `tests/test_wyatt_earp_matrix.py` (full games against all 22 other heroes in both seats, passive and attacking human, headless with the heuristic and the search AI).
