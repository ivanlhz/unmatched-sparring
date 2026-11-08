# Card identity: the shared CardID range

In the tournament savegame Medusa, the four TMNT turtles (Leonardo, Donatello, Michelangelo, Raphael), Doctor Strange, Bigfoot, Daredevil, Luke Cage, Bullseye and Tomoe Gozen
are all DeckID 176, so all eleven decks have CardIDs 17600-17629 (Daredevil's has 22 cards: 17600-17621). Only the deck image (FaceURL, BackURL of the CustomDeck,
`deck.identity` in `data/tts/<slug>.json`) tells them apart. Any pairing of the nineteen heroes works at the table, in both seats,
including Medusa against a turtle and a turtle against a turtle (`tests/test_tmnt_matrix.py`), and Doctor Strange against each of
them (`tests/test_doctor_strange_matrix.py`; only the
30 deck cards overlap, his character card is 337). The rule is one sentence:

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

## What a new hero in sheet 176 must follow (Daredevil was the last one)

1. `data/tts/<slug>.json` with its own `deck.identity` (the images of its deck object), not Medusa's or another turtle's.
2. Never `card.card_id in range(...)`, `card_id == X` or a dict keyed by CardID built from both players. Use `game.card_of`,
   `game.cards_by_id(owner)` or `players[side].full_set`.
3. A new Lua builder takes `id_range` and `identity` together and filters with `_ours_lua`.
4. A new ChoiceRequest is created through `EffectRun.ask` (it adds `card_owner`); one created by hand passes the owner.
5. Add the slug to the matrix (`HEROES` in `tests/test_tmnt_matrix.py`); the matrix is the proof.

Daredevil (`tests/test_hero_daredevil_data.py`, `tests/test_daredevil_matrix.py`) also shares the sheet but has 22 playing cards: his CardIDs are 17600-17621 (`HeroDef.deck_size`), his deck object holds 23 cards with the character card 338, and his images are his own (`deck.identity` in `data/tts/daredevil.json`).
Bigfoot (`tests/test_hero_bigfoot_data.py`, `tests/test_bigfoot_matrix.py`) follows these rules like Doctor Strange: his own `deck.identity` in
`data/tts/bigfoot.json`, and a matrix against the other ten heroes of the project in both seats.

Bullseye (Hell's Kitchen, character card 339) is the tenth deck of sheet 176 (`tests/test_hero_bullseye_data.py`, `tests/test_bullseye_matrix.py`): his own `deck.identity` in `data/tts/bullseye.json`, a matrix against the other fourteen heroes in both seats, and `SHARING` in `tests/test_card_identity.py`.

Golden Bat (Adventures: Tales to Amaze, character card 345) is the eleventh deck of sheet 176 (`tests/test_hero_golden_bat_data.py`, `tests/test_golden_bat_matrix.py`): his own `deck.identity` in `data/tts/golden-bat.json`, a matrix against the other eighteen heroes in both seats, and `SHARING` in `tests/test_card_identity.py`.


Dr. Jill Trent (Tales to Amaze, character card 348, slug `jill-trent`) is another deck of sheet 176 (`tests/test_hero_jill_trent_data.py`, `tests/test_jill_trent_matrix.py`): her own `deck.identity` in `data/tts/jill-trent.json`, a matrix against the other eighteen heroes in both seats, and `SHARING` in `tests/test_card_identity.py`. The catalog files her under `dr-jill-trent-science-sleuth`; the project slug is the shorter one.

She-Hulk (Brains and Brawn, character card 336) is another deck of sheet 176 (`tests/test_hero_she_hulk_data.py`, `tests/test_she_hulk_matrix.py`): her own `deck.identity` in `data/tts/she-hulk.json`, a matrix against the other eighteen heroes in both seats, and `SHARING` in `tests/test_card_identity.py`.

Tomoe Gozen (Sun's Origin, character card 354) is another deck of sheet 176 (`tests/test_hero_tomoe_gozen_data.py`, `tests/test_tomoe_gozen_matrix.py`): her own `deck.identity` in `data/tts/tomoe-gozen.json`, a matrix against the other eighteen heroes in both seats, and `SHARING` in `tests/test_card_identity.py`. Her life dial also shares a GUID with Donatello's (`ca8e35`): see "Piece identity" below.

## Houdini needs none of this

Houdini's deck is sheet 178 (CardIDs 17800-17829) with the character card on a sheet of its own (177, CardID 17700); no other hero of
`data/tts` has a CardID in 177xx-178xx, and `deck.identity` holds only the playing cards' image. The catalog lists both images for the
bag (`card_ids` 17700..17829), `tests/test_hero_houdini_data.py` pins that his range, images and GUIDs are nobody else's, and
`tests/test_houdini_matrix.py` plays him against the nine other heroes in both seats. The per-owner lookups above still apply to him like
to everyone else.

## Piece identity (miniatures and tokens)

Cards are told apart by value (above); pieces by GUID **and name**. The tournament save gives Abe Sapien's and Donatello's
miniatures the same GUID (`4fdf31`, each inside its own bag; the only cross-hero collision in `data/tts/*.json`, pinned by
`tests/test_piece_identity.py`). TTS keeps GUIDs unique, so when both are on the table the second one out of its bag gets a
new random GUID and the configured one would make the session follow the other hero's piece.

A third collision is a miniature: Daisy's token in Jill Trent's bag and Abe Sapien's agent Carla are both `0bf463` (`tests/test_piece_identity.py` pins it; the Abe vs Jill matrix plays it in both seats). The same machinery tells them apart by name ("Daisy" / "Carla").

The save has a second collision, of a dial: The Jackalope's and Lobster Johnson's life dials are both `18c384`. `session_pieces.resolve_dials` tells
them apart by the dial's name (`lua.find_dials_by_name`) before the first dial write, saves the result (`resolved_dials`) and, when it cannot, says so
and neither writes nor checks that dial; see docs/heroes/bigfoot.md and `tests/test_dial_identity.py`.

The third collision is a dial too: Tomoe Gozen's life dial has Donatello's GUID `ca8e35` (the save reuses it for Chupacabra's and Little Red's as well; every one of them is a Custom_Model named after its hero). The same `resolve_dials` handles it by name (pinned by `tests/test_piece_identity.py`; `tests/test_tomoe_gozen_matrix.py` plays the pair in both seats).

`sparring/session_pieces.py` handles it for any piece (miniature or token, any hero):

- The object at a configured GUID is read with its name; TTS colour tags are stripped (`[6f2176]Donatello` -> `donatello`)
  and it is compared with the nicknames of the fighters in play. A piece whose name is ANOTHER fighter's, or a GUID with
  nothing at it, is "not mine". An object with no name, or a name nobody in play has, is trusted: the GUID wins.
- Then the loose objects (not decks, cards or bags) are searched for the fighter's own name
  (`lua.find_pieces_by_name`, read only). Exactly one candidate, not claimed by another fighter, replaces the GUID in
  `session.cfg.pieces` for the rest of the game; the player reads one `piece.resolved` line. None or several: the GUID
  stays, one `piece.unresolved` line, no second search for that fighter until the next start / resume / adopt.
- When: at start, at `--resume` (after the saved resolutions are restored), on adopt (the table wins), and on any table read
  that finds a foreign name at a GUID (a piece that came out of its bag later). `play.py` also runs it before building the
  panel, whose snapshot carries the GUID list.
- Persistence: `resolved_pieces` (fid -> GUIDs) in the session file. The save's fingerprint keeps using the GUIDs of the data
  (`Session.configured_pieces`), so a resolution never makes a save look like another table.
- At start-up `shared_guids` warns (`piece.shared`) when two pieces or dials in play have the same GUID in the data.
- Fake table: `tests/test_d3_table_effects.build` models TTS (`reassigned_guid`): a GUID given twice by the data is given
  once; the next object gets a new one. The restored human-attacks and passive matrices run Abe vs Donatello in both seats
  on it with no per-test workaround.

Limits: dials are not resolved by name (a life dial carries no hero name); a shared dial GUID would only be warned about. A
piece with several states (Hellboy) replaces the state GUID that was found, keeping the others.

## Renumbered DeckIDs and character cards

TTS renumbers the DeckID of a deck that spawns beside another with the same one (Medusa and Michelangelo both ship 176; Michelangelo's lands at 177xx). The bot finds each hero's deck by image identity and card index (`CardID % 100`), reads the DeckID it really has and keeps the shift per side (`bot_card_shift` / `human_card_shift`, saved in the session as `card_shifts`); every CardID range of the session and every CardID of the engine's decks carries it.

Character cards (Medusa 302, Bigfoot 309, the turtles 363/364/366/368) live under CustomDeck key "3" and are matched by their exact CardID. If TTS ever renumbered that sheet, `take_character_cards` would miss them. The same goes for Houdini's character card 17700, which sits in the 177 namespace.
