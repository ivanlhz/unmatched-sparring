# Card identity: the shared CardID range

In the tournament savegame Medusa and the four TMNT turtles (Leonardo, Donatello, Michelangelo, Raphael) are all DeckID 176, so
all five decks have CardIDs 17600-17629. Only the deck image (FaceURL, BackURL of the CustomDeck, `deck.identity` in
`data/tts/<slug>.json`) tells them apart. Any pairing of the nine heroes works at the table, in both seats, including Medusa
against a turtle and a turtle against a turtle (`tests/test_tmnt_matrix.py`). The rule is one sentence:

> **A CardID means a card only together with its owner (the player's seat) or with the deck image. Never look a card up by a bare CardID.**

## In the engine and the session

- A `Card` is a frozen value (id, title, fighter, type, numbers, text, tags). No two cards of different decks are equal
  (the fighter name differs), so comparing by value (`==`, `in`) is safe; comparing `card_id` alone is not.
- `Game.card_of(card_id, owner)` is the lookup: the owner's deck first, the rival's as a fallback for a card that changed hands.
  `Game.cards_by_id(owner)` is the same as a dict, for a request about `owner`'s cards. `effects.select.find_card(game, id, owner)`
  delegates to it. `PlayerState.full_set` stays the per-player list; build `{card_id: card}` from one player's `full_set`, never
  from `for p in game.players for c in p.full_set`.
- An effect request carries its owner: `ChoiceRequest.card_owner` (set by `EffectRun.ask` from `ctx.owner`; saved with the request).
  The card options of a request belong to `extra["of"]` (set by `select_cards`). Panels, prompts and the bot's choosers use
  these two, never a scan of both decks (`session_choices.request_card`, `card_titles(game, ids, owner)`,
  `EffectAI._locate`, `ControllerChooser._cards`).
- `combat.is_medusa_card(card)` is "the card is one of Medusa's" by value against her deck, not by range or title.
  `modifiers.side_of` also compares by value.
- Saves store CardIDs per player (`players[i].deck/hand/discard/tucked/removed`) and resolve them against that player's
  `full_set` on load; combat flows also save `boost_owner`. Nothing in a save is a bare CardID without a place.

## At the table (Lua and the session)

- Every table read comes from a place that belongs to a side: a seat's hand, a side's discard zone, a side's combat spot,
  ongoing spot, deck spot, tuck / removed spot. The session resolves the ids it gets against the deck of that side
  (`st = game.players[side]`, `by_id = {c.card_id: c for c in st.full_set}`).
- Every Lua builder that searches or moves cards takes the side's `id_range` AND its `identity` (`lua._ours_lua`): a card is
  "ours" only if its CardID is in the range and the image of its deck is one of the identities. `Session._identity(side)`
  gives the pairs for `"bot"` or `"human"`; always pass the side that matches the range (`bot_card_ids` with
  `_identity()`, `human_card_ids` with `_identity("human")`). A builder with a range and no identity is a defect.
- `hero_table.table_defaults` accepts equal CardID ranges when the two decks have different images and refuses them when the
  images overlap too. Hero detection (`hero_detect`, `lua.table_heroes`) uses range plus image.

## What a new hero in sheet 176 must follow (Raphael was the last one)

1. `data/tts/<slug>.json` with its own `deck.identity` (the images of its deck object), not Medusa's or another turtle's.
2. Never `card.card_id in range(...)`, `card_id == X` or a dict keyed by CardID built from both players. Use `game.card_of`,
   `game.cards_by_id(owner)` or `players[side].full_set`.
3. A new Lua builder takes `id_range` and `identity` together and filters with `_ours_lua`.
4. A new ChoiceRequest is created through `EffectRun.ask` (it adds `card_owner`); one created by hand passes the owner.
5. Add the slug to the matrix (`HEROES` in `tests/test_tmnt_matrix.py`); the matrix is the proof.
