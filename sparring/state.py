from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import Callable

from .board import Board
from .cards import Card, can_be_boost
from .controller import Controller
from .effects import inventions, ongoing
from .effects.state import EffectState, default_dsl_heroes
from .heroes import DEFAULT_HAND_LIMIT, DEFAULT_START_HAND, HeroDef, load_hero
from .i18n import t

HAND_LIMIT = DEFAULT_HAND_LIMIT       # the defaults; a hero's own sizes are `Game.start_hand` / `Game.hand_cap`
START_HAND = DEFAULT_START_HAND
EXHAUST_DAMAGE = 2
DETECTIVE = "OCCULT DETECTIVE"      # names of Hellboy's forms exactly as in data/heroes/hellboy.json
ANUNG = "ANUNG UN RAMA"             # (the session's announcements use them; the rule lives in the data)
DEFAULT_HEROES = ("medusa", "hellboy")     # (bot hero, human hero)


class RuleError(Exception):
    pass


@dataclass
class Fighter:
    fid: str
    name: str
    owner: int
    hero: bool
    hp: float
    max_hp: int
    move: int
    ranged: bool
    pos: int | None = None
    alive: bool = True
    died_at: int | None = None     # space where it fell: an HP mistake is undone by putting it back there


@dataclass
class KnownHand:
    """What a player knows about the RIVAL's hand and deck top, learned only through card effects.

    Only legitimately seen cards enter (`observe`, `add`, `set_top`), never the real human hand. Every seen card is
    forgotten (`forget`) when it leaves the rival hand by any route; `Game.card_left_hand` is the single place that
    does it, so a seen card that is gone is never counted as playable. Search (F09) samples the hidden hand with
    `Game.hidden_hand`: the known cards fixed and the rest drawn from the multiset of cards not seen in a public pile.

    Three levels of certainty:
    - `seen`: certainly in the rival hand (looked at, or revealed).
    - `possible` with `possible_lo`..`possible_hi`: cards that were seen but may have left face down (Glimpse Of
      Hell, Pyrotechnics, Pact Of Secrecy); between lo and hi of them are still in the hand. They stay in the
      sampling pool, no longer as certainty.
    - `top_of_deck`: the rival deck's known prefix, top first (Every Possible Angle puts a chosen card on top)."""
    seen: list[int] = field(default_factory=list)       # CardID of the seen cards still in the rival hand
    turn_no: int | None = None                          # turn when it was looked at (information ages)
    possible: list[int] = field(default_factory=list)   # seen cards that may have left face down
    possible_lo: int = 0
    possible_hi: int = 0
    top_of_deck: list[int] = field(default_factory=list)

    def observe(self, cards: list[Card], turn_no: int) -> None:
        """Replaces what was known: a new look is the complete snapshot of the hand at that moment."""
        self.seen = [c.card_id for c in cards]
        self.possible, self.possible_lo, self.possible_hi = [], 0, 0
        self.turn_no = turn_no if self.seen else None

    def add(self, card: Card, turn_no: int) -> None:
        """A concrete card came into view in the rival hand (Wildfire: the burning card returns)."""
        self.seen.append(card.card_id)
        if self.turn_no is None:
            self.turn_no = turn_no

    def forget(self, card: Card) -> bool:
        """Discounts ONE copy of that card (two Second Shot seen, one played: one left). True if it was known."""
        try:
            self.seen.remove(card.card_id)
            found = True
        except ValueError:
            found = False
        if not found and card.card_id in self.possible:     # it was in the hand: one fewer of the possible ones
            self.possible.remove(card.card_id)
            self.possible_lo, self.possible_hi = max(0, self.possible_lo - 1), max(0, self.possible_hi - 1)
            found = True
            self._settle()
        if not self.seen and not self.possible:
            self.turn_no = None
        return found

    def degrade(self, removed: int, hand_after: int) -> None:
        """`removed` cards left the rival hand face down (it now has `hand_after`): which ones is unknown, so
        everything seen becomes "possible" with the count bounds that follow."""
        pool = self.seen + self.possible
        if not pool or removed <= 0:
            return
        certain = len(self.seen) + self.possible_lo
        in_hand_max = len(self.seen) + self.possible_hi
        self.possible = pool
        self.possible_lo = max(0, certain - removed)
        self.possible_hi = max(self.possible_lo, min(len(pool), hand_after, in_hand_max))
        self.seen = []
        self._settle()

    def _settle(self) -> None:
        """Bounds that pin the set down: all of them certainly in (promote), none in (drop)."""
        n = len(self.possible)
        self.possible_hi = min(self.possible_hi, n)
        self.possible_lo = min(self.possible_lo, self.possible_hi)
        if self.possible_hi == 0:
            self.possible, self.possible_lo = [], 0
        elif self.possible_lo == n:
            self.seen, self.possible, self.possible_lo, self.possible_hi = self.seen + self.possible, [], 0, 0

    def clear(self) -> None:
        self.seen, self.turn_no = [], None
        self.possible, self.possible_lo, self.possible_hi = [], 0, 0

    # ---- known deck top
    def set_top(self, ids: list[int]) -> None:
        self.top_of_deck = list(ids)

    def push_top(self, ids: list[int]) -> None:
        """`ids` (top first) were put on top of the deck in plain sight."""
        self.top_of_deck = list(ids) + self.top_of_deck

    def drop_top(self, card_id: int) -> None:
        """A card left the deck by a route that is not a draw: it is no longer part of the known prefix."""
        if card_id in self.top_of_deck:
            self.top_of_deck.remove(card_id)

    def clear_top(self) -> None:
        self.top_of_deck = []

    def drawn(self, card: Card, turn_no: int) -> None:
        """The rival drew `card`; if it was the known top, it is now a seen card in their hand."""
        if self.possible:        # a blind draw may bring back one of them; the identity is not looked at
            self.possible_hi = min(len(self.possible), self.possible_hi + 1)
        if not self.top_of_deck:
            return
        if self.top_of_deck[0] == card.card_id:
            self.top_of_deck.pop(0)
            self.add(card, turn_no)
        else:
            self.top_of_deck = []        # an unknown card was on top: the known prefix cannot be trusted

    def cards(self, rival: "PlayerState") -> list[Card]:
        """The seen cards that can still be in the rival hand. Defends against routes that move cards without
        notice (table reconciliation, adoption): what is already in their discard (public) is out, per copy. It
        never looks at the rival hand or deck."""
        return self._resolve(self.seen, rival)

    def possible_cards(self, rival: "PlayerState") -> list[Card]:
        return self._resolve(self.possible, rival)

    def top(self, rival: "PlayerState") -> list[Card]:
        """The known prefix of the rival deck as cards, top first."""
        by_id = {c.card_id: c for c in rival.full_set}
        return [by_id[i] for i in self.top_of_deck if i in by_id]

    @staticmethod
    def _resolve(ids: list[int], rival: "PlayerState") -> list[Card]:
        by_id = {c.card_id: c for c in rival.full_set}
        public = {c.card_id for c in rival.gone}
        return [by_id[i] for i in ids if i in by_id and i not in public]

    def copy(self) -> "KnownHand":
        return KnownHand(list(self.seen), self.turn_no, list(self.possible), self.possible_lo, self.possible_hi,
                         list(self.top_of_deck))

    def is_empty(self) -> bool:
        return not (self.seen or self.possible or self.top_of_deck)

    def to_dict(self) -> dict:
        """Only what is non-empty, so a game that never looked at a hand saves byte-identical to before."""
        out: dict = {}
        if self.seen:
            out["seen"] = list(self.seen)
        if self.seen or self.possible:
            out["turn_no"] = self.turn_no
        if self.possible:
            out["possible"] = {"ids": list(self.possible), "lo": self.possible_lo, "hi": self.possible_hi}
        if self.top_of_deck:
            out["top"] = list(self.top_of_deck)
        return out

    @classmethod
    def from_dict(cls, raw: dict | None) -> "KnownHand":
        raw = raw or {}
        poss = raw.get("possible") or {}
        return cls([int(i) for i in raw.get("seen", [])], raw.get("turn_no"), [int(i) for i in poss.get("ids", [])],
                   int(poss.get("lo", 0)), int(poss.get("hi", 0)), [int(i) for i in raw.get("top", [])])


@dataclass
class PlayerState:
    hero: HeroDef
    deck: list[Card]
    full_set: list[Card]
    hand: list[Card] = field(default_factory=list)
    discard: list[Card] = field(default_factory=list)
    known: KnownHand = field(default_factory=KnownHand)   # what THIS player knows of the rival's hand
    tucked: list[Card] = field(default_factory=list)      # inventions tucked under the hero card (Donatello): public, in force
    removed: list[Card] = field(default_factory=list)     # removed from the game: public and gone for good

    @property
    def hero_name(self) -> str:
        return self.hero.name

    @property
    def gone(self) -> list[Card]:
        """Every card of the set that is public and in no hidden pile: the discard pile, the tucked inventions and the
        cards removed from the game. What the rival's unseen pool and the deck count leave out."""
        if not (self.tucked or self.removed):
            return self.discard
        return self.discard + self.tucked + self.removed


class Game:
    def __init__(self, board: Board, fighters: list[Fighter], players: list[PlayerState], rng: random.Random,
                 controllers: dict[int, Controller] | None = None, first: int = 0,
                 start_spaces: dict[int, int] | None = None):
        self.board = board
        self.fighters = {f.fid: f for f in fighters}
        self.players = players
        self.rng = rng
        self.controllers = controllers or {}
        self.start_spaces = start_spaces or {}
        self.turn = first
        self.turn_no = 1
        self.actions_left = 2
        self.winner: int | None = None
        self.bot_player: int | None = None     # who the bot plays: its not yet coded effects are not resolved by the human
        self.effect_shield: dict[int, int] = {}
        self.drawn = [0, 0]
        self.draw_events = [0, 0]      # cards drawn since the start, never reset (`drawn` is: the deal settles it); for the game log
        self.phantom_draws = 0   # draws the AI expects when simulating (unknown cards), never in a real game
        # the live session's reader of a hand `look_hand` wants (the real table hand, D3); None = the engine's hand.
        # Never copied into clones: a simulation determinizes and must not read the table.
        self.hand_reader: Callable[[int], list[Card]] | None = None
        self.log: list[str] = []
        self.fx = EffectState()    # DSL interpreter state and hooks (docs/effects-dsl.md); inert unless fx.dsl_heroes
        self.fx.dsl_heroes = default_dsl_heroes(self)   # the bot is not known yet: Game.new recomputes it
        self.fx.attach(self)

    @classmethod
    def new(cls, board: Board, seed: int, controllers: dict[int, Controller] | None = None,
            bot_player: int = 0, starts: tuple[str, str] = ("1", "2"),
            heroes: tuple[str, str] = DEFAULT_HEROES) -> "Game":
        """`heroes`: (slug of `bot_player`'s hero, slug of the other); each comes from data/heroes/<slug>.json.
        `starts`: starting space of each one's map, in that same order."""
        rng = random.Random(seed)
        other = 1 - bot_player
        defs = {bot_player: load_hero(heroes[0]), other: load_hero(heroes[1])}
        if defs[bot_player].fid == defs[other].fid:
            raise RuleError(t("err.same_hero", slug=heroes[0]))
        players: list[PlayerState | None] = [None, None]
        for owner, h in defs.items():
            players[owner] = PlayerState(h, [], h.deck())
        start_spaces = {bot_player: board.starts[starts[0]], other: board.starts[starts[1]]}
        fighters, taken = [], set()
        for owner in (bot_player, other):
            for spec in defs[owner].fighters():
                if not spec.on_board:       # starts in reserve: off the board until an effect summons it
                    fighters.append(Fighter(spec.fid, spec.name, owner, spec.hero, spec.hp, spec.hp, spec.move,
                                            spec.ranged, None, alive=False))
                    continue
                pos = board.nearest_free(start_spaces[owner], taken, zone_of=start_spaces[owner])
                taken.add(pos)
                fighters.append(Fighter(spec.fid, spec.name, owner, spec.hero, spec.hp, spec.hp, spec.move,
                                        spec.ranged, pos))
        for p in players:
            p.deck = list(p.full_set)
            rng.shuffle(p.deck)
        game = cls(board, fighters, players, rng, controllers, first=rng.randrange(2), start_spaces=start_spaces)
        game.bot_player = bot_player
        game.fx.dsl_heroes = default_dsl_heroes(game)
        for pl in (0, 1):
            game.draw(pl, game.start_hand(pl), log=False)
        game.drawn = [0, 0]
        return game

    def clone(self) -> "Game":
        g = Game.__new__(Game)
        g.board, g.rng, g.controllers, g.start_spaces = self.board, self.rng, self.controllers, self.start_spaces
        g.fighters = {k: replace(f) for k, f in self.fighters.items()}
        g.players = [PlayerState(p.hero, list(p.deck), p.full_set, list(p.hand), list(p.discard), p.known.copy(),
                                 list(p.tucked), list(p.removed))
                     for p in self.players]
        g.turn, g.turn_no, g.actions_left, g.winner = self.turn, self.turn_no, self.actions_left, self.winner
        g.bot_player = self.bot_player
        g.effect_shield = dict(self.effect_shield)
        g.drawn = [0, 0]
        g.draw_events = [0, 0]
        g.phantom_draws = self.phantom_draws
        g.hand_reader = None                   # a clone never reads the table: it looks at its determinized hand
        g.log = []
        g.fx = self.fx.copy()
        g.fx.attach(g)
        return g

    # queries
    def own(self, player: int, alive_only: bool = True) -> list[Fighter]:
        return [f for f in self.fighters.values() if f.owner == player and (f.alive or not alive_only)]

    def foes(self, player: int) -> list[Fighter]:
        return self.own(1 - player)

    def hero(self, player: int) -> Fighter:
        return next(f for f in self.fighters.values() if f.owner == player and f.hero)

    def hero_named(self, name: str) -> Fighter:
        return next(f for f in self.fighters.values() if f.hero and f.name == name)

    def hero_def(self, player: int) -> HeroDef:
        return self.players[player].hero

    def card_of(self, card_id: int, owner: int) -> Card | None:
        """The card `card_id` of `owner`'s deck. Never look a card up by its bare CardID: Medusa and the TMNT heroes share
        17600-17629, so an id means a card only together with the player it belongs to (docs/card-identity.md). The
        rival's deck is the fallback, for a card that changed hands (a card taken from the rival's discard pile)."""
        for p in (self.players[owner], self.players[1 - owner]):
            for c in p.full_set:
                if c.card_id == card_id:
                    return c
        return None

    def cards_by_id(self, owner: int) -> dict[int, Card]:
        """CardID -> card for a request about `owner`'s cards: both decks, `owner`'s own winning where ids collide."""
        out = {c.card_id: c for c in self.players[1 - owner].full_set}
        out.update((c.card_id, c) for c in self.players[owner].full_set)
        return out

    def start_hand(self, player: int) -> int:
        """Cards of the opening hand (and of a mulligan): 5, or what the hero's card says (Michelangelo: 3)."""
        return self.players[player].hero.hand_start

    def hand_cap(self, player: int) -> int:
        """Most cards `player` keeps at the end of the turn: 7, or what the hero's card says (Michelangelo: 3)."""
        return self.players[player].hero.hand_max

    def occupied(self, player: int) -> set[int]:
        return {f.pos for f in self.own(player)}

    def zone_mates(self, fighter: Fighter) -> list[Fighter]:
        return [f for f in self.fighters.values()
                if f.alive and f is not fighter and self.board.share_zone(fighter.pos, f.pos)]

    def counter(self, player: int, name: str) -> int:
        """Hero counter (Hellboy: destinies): cards with its tag in its pile."""
        c = self.players[player].hero.counters[name]
        pile = self.players[player].discard if c.pile == "discard" else []
        return sum(1 for card in pile if c.tag in card.tags)

    def counters(self, player: int) -> dict[str, int]:
        return {name: self.counter(player, name) for name in self.players[player].hero.counters}

    def destiny_count(self, player: int) -> int:
        return self.counter(player, "destiny") if "destiny" in self.players[player].hero.counters else 0

    def form(self, player: int) -> str | None:
        forms = self.players[player].hero.forms
        if forms is None:
            return None
        return forms.of(self.counter(player, forms.counter))

    def triggers(self, player: int, when: str) -> list[dict]:
        """Hero triggers active now: those of that moment whose form (if they require one) is the current one."""
        form = self.form(player)
        return [t for t in self.players[player].hero.triggers
                if t.get("when") == when and t.get("form", form) == form]

    def attack_bonus_parts(self, fighter: Fighter, target: Fighter | None = None) -> list[tuple[int, str]]:
        """(bonus, tag) of each active attack passive of the hero (Hellboy in ANUNG UN RAMA: (2, 'ANUNG UN RAMA')),
        plus the board's high ground when the `target` it hits is known."""
        parts = (self.players[fighter.owner].hero.attack_bonuses(self.form(fighter.owner), fighter.hero)
                 + self.combat_bonus_parts(fighter.owner) + inventions.bonus_parts(self, fighter.owner, "attack"))
        high = self.board.attack_bonus(fighter.pos, target.pos) if target is not None else 0
        return parts + [(high, t("cf.high_ground"))] if high else parts

    def defense_bonus_parts(self, player: int) -> list[tuple[int, str]]:
        """(bonus, label) added to the card `player` defends with: the live ONGOING and the tucked inventions."""
        return self.combat_bonus_parts(player) + inventions.bonus_parts(self, player, "defense")

    def defense_bonus_total(self, player: int) -> int:
        return sum(n for n, _ in self.defense_bonus_parts(player))

    @property
    def combat_bonus(self) -> list[list[tuple[int, str]]]:
        """(bonus, label) of each player's live ONGOING, to ALL their combat cards: a view over `fx.ongoing`."""
        return [self.combat_bonus_parts(0), self.combat_bonus_parts(1)]

    @combat_bonus.setter
    def combat_bonus(self, sides) -> None:
        ongoing.set_legacy_all(self, sides)

    def add_combat_bonus(self, player: int, n: int, label: str) -> str | None:
        """A scheme with ONGOING "add n to the value of your combat cards" enters play. Ivan's ruling (28/10): only one
        active ONGOING per player, the new one replaces the old. Returns the label of the replaced one (or None)."""
        return ongoing.set_legacy(self, player, n, label)

    def combat_bonus_parts(self, player: int) -> list[tuple[int, str]]:
        """(bonus, label) of `player`'s live ONGOING (at most one)."""
        return ongoing.bonus_parts(self, player)

    def combat_bonus_total(self, player: int) -> int:
        return sum(n for n, _ in self.combat_bonus_parts(player))

    def attack_bonus(self, fighter: Fighter, target: Fighter | None = None) -> int:
        """Bonus of `fighter`'s NEXT attack (used by the AI to measure threats; with `target`, the high ground too). A scheme's ONGOING expires when its
        owner's turn begins: if it is not their turn now, that bonus no longer reaches their next attack."""
        passives = self.players[fighter.owner].hero.attack_bonus(self.form(fighter.owner), fighter.hero)
        tucked = sum(n for n, _ in inventions.bonus_parts(self, fighter.owner, "attack"))
        high = self.board.attack_bonus(fighter.pos, target.pos) if target is not None else 0
        return passives + tucked + high + (self.combat_bonus_total(fighter.owner) if self.turn == fighter.owner else 0)

    def legal_moves(self, fighter: Fighter, steps: int, through_enemies: bool = False) -> set[int]:
        if not self.fx.can_move(fighter):
            return {fighter.pos}
        return self.board.reachable(fighter.pos, steps, self.occupied(fighter.owner) - {fighter.pos},
                                    self.occupied(1 - fighter.owner), through_enemies)

    def can_attack(self, attacker: Fighter, target: Fighter) -> bool:
        return (attacker.alive and target.alive and attacker.owner != target.owner
                and self.fx.may_attack(attacker.owner)
                and self.board.can_reach_target(attacker.pos, target.pos, attacker.ranged))

    # known hand of the rival (effect "look at the hand"): see KnownHand
    def observe_hand(self, viewer: int, cards: list[Card]) -> None:
        """`viewer` has just seen the rival's whole hand through a card effect."""
        self.players[viewer].known.observe(cards, self.turn_no)

    def card_left_hand(self, owner: int, card: Card) -> None:
        """A card has left `owner`'s hand (played, discarded, lost): their rival stops counting on it."""
        self.players[1 - owner].known.forget(card)

    def hidden_hand(self, viewer: int, hand_size: int | None = None) -> tuple[list[Card], list[Card], int]:
        """To sample `viewer`'s rival hand without cheating: (known cards, multiset of candidates
        for the rest, how many are left to draw). The candidates are the rival's cards that are in no
        public pile (discard) nor among the known ones; deck and hand are indistinguishable from outside."""
        rival = self.players[1 - viewer]
        known = self.players[viewer].known.cards(rival)
        size = len(rival.hand) if hand_size is None else hand_size
        pool = list(rival.full_set)
        for c in (*rival.gone, *known):
            if c in pool:
                pool.remove(c)
        return list(known), pool, max(0, size - len(known))

    # mutations
    def move_fighter(self, fighter: Fighter, dest: int, steps: int, through_enemies: bool = False) -> None:
        if dest == fighter.pos:
            return
        if dest not in self.legal_moves(fighter, steps, through_enemies):
            raise RuleError(t("err.illegal_move", fid=fighter.fid, dest=dest, steps=steps))
        fighter.pos = dest

    def place_fighter(self, fighter: Fighter, dest: int) -> None:
        """Puts the fighter on any empty space (a placement, not a move: no path, no range)."""
        if dest == fighter.pos:
            return
        taken = {o.pos for o in self.fighters.values() if o.alive and o is not fighter}
        if dest not in self.board.spaces or dest in taken or not self.fx.can_move(fighter):
            raise RuleError(t("err.illegal_place", fid=fighter.fid, dest=dest))
        fighter.pos = dest

    def damage(self, fighter: Fighter, n: float, source: str = "effect", by: Fighter | None = None) -> float:
        if not fighter.alive or n <= 0:
            return 0
        if source == "effect" and self.effect_shield.get(fighter.owner) == self.turn_no:
            self.log.append(f"{fighter.fid}: effect damage prevented")
            return 0
        n = self.fx.adjust_damage(fighter, n, source)
        if n <= 0:
            return 0
        fighter.hp -= n
        self.log.append(f"{fighter.fid} -{n} ({fighter.hp:g} hp)")
        self.fx.on_damage(fighter, n, source, by)
        if fighter.hp <= 0:
            fighter.died_at = fighter.pos if fighter.pos is not None else fighter.died_at
            fighter.alive, fighter.pos = False, None
            if fighter.hero:
                self.winner = 1 - fighter.owner
            self.fx.emit("fighter_defeated", fighter)
        return n

    def remove_from_game(self, player: int, card: Card) -> None:
        """A card of the discard pile leaves the game for good (Donatello's inventions): public, nothing brings it back."""
        self.players[player].discard.remove(card)
        self.players[player].removed.append(card)

    def heal(self, fighter: Fighter, n: int) -> None:
        if fighter.alive:
            fighter.hp = min(fighter.max_hp, fighter.hp + n)

    def draw(self, player: int, n: int = 1, log: bool = True) -> list[Card]:
        p, drawn = self.players[player], []
        if not self.fx.can_draw(player):
            return drawn
        for _ in range(n):
            if not p.deck:
                for f in self.own(player):
                    self.damage(f, EXHAUST_DAMAGE, "exhaustion")
                continue
            card = p.deck.pop(0)
            p.hand.append(card)
            drawn.append(card)
            self.drawn[player] += 1
            self.draw_events[player] += 1
            self.players[1 - player].known.drawn(card, self.turn_no)
        if log and drawn:
            self.log.append(f"P{player} draws {len(drawn)}")
        return drawn

    def take_from_hand(self, player: int, card: Card) -> None:
        """Takes the card out of the hand to play it (combat); it goes to the discard when the combat ends."""
        self.players[player].hand.remove(card)
        self.card_left_hand(player, card)

    def discard_card(self, player: int, card: Card, played: bool = False, cause: str | None = None) -> None:
        """`played`: the card is being used (a scheme), not discarded by an effect: no `card_discarded` event.
        `cause`: why it was discarded when that matters to a trigger ("hand_limit": Wildfire does not return it)."""
        self.take_from_hand(player, card)
        self.players[player].discard.append(card)
        if not played:
            self.fx.emit("card_discarded", player, card, "hand", cause)

    def force_discard(self, player: int, n: int, reason: str, source: int | None = None,
                      cause: str | None = None) -> list[Card]:
        hand = self.players[player].hand
        n = min(n, len(hand))
        if not n:
            return []
        if not self.fx.can_force_discard(player, player if source is None else source):
            return []
        self.fx.emit("force_discard", player, n)
        chosen = self.controllers[player].choose_discard(self, player, n, reason)[:n]
        for c in chosen:
            self.discard_card(player, c, cause=cause)
        return chosen

    def grant_actions(self, n: int) -> None:
        if not self.fx.can_gain_actions(self.turn):
            return
        self.actions_left += n

    # turn
    def begin_turn(self) -> list[tuple[int, str]]:
        """Starts the turn of `self.turn`: 2 actions and its ONGOING schemes expire. Returns what expired."""
        self.actions_left = 2
        expired = ongoing.expiring_parts(self, self.turn)
        ongoing.expire_legacy(self, self.turn)
        self.fx.emit("start_of_turn", self.turn)
        return expired

    def use_action(self) -> None:
        if self.actions_left <= 0:
            raise RuleError(t("err.no_actions"))
        self.actions_left -= 1
        self.fx.count_action()

    def end_turn(self) -> None:
        self.fx.emit("end_of_turn", self.turn)
        hand = self.players[self.turn].hand
        limit = self.fx.hand_limit(self.turn, self.hand_cap(self.turn))
        if len(hand) > limit:
            self.force_discard(self.turn, len(hand) - limit, t("cause.hand_limit"), cause="hand_limit")
        self.turn = 1 - self.turn
        self.turn_no += 1

    # actions
    def maneuver(self, player: int, moves: dict[str, int], boost_card: Card | None = None) -> None:
        """Checked before anything is spent: the boost card and the movers (a RuleError leaves the game as it was)."""
        if boost_card is not None and not can_be_boost(boost_card):
            raise RuleError(t("err.no_boost_value", title=boost_card.title))
        for fid in moves:
            f = self.fighters.get(fid)
            if f is None or f.owner != player or not f.alive:
                raise RuleError(t("err.cannot_move", fid=fid))
        self.use_action()
        alive0 = {fid for fid, f in self.fighters.items() if f.alive}
        self.draw(player)    # exhaustion can kill fighters (and end the game) before they are moved
        if self.winner is not None:
            return
        moves = {fid: d for fid, d in moves.items() if fid not in alive0 or self.fighters[fid].alive}
        extra = 0
        if boost_card is not None:
            extra = boost_card.boost
            self.discard_card(player, boost_card)
            self.fx.emit("card_boosted", player, boost_card)
            self.fx.boost_effects(player, boost_card)       # its BOOSTED WITH resolves before anything moves
            if self.winner is not None:
                return
            moves = {fid: d for fid, d in moves.items() if self.fighters[fid].alive}      # Misdirection may have felled a mover
        placing = boost_card is not None and self.fx.hero_rule(player, "maneuver_boost_places_hero")
        for fid, dest in moves.items():
            f = self.fighters[fid]
            if placing and f.hero:
                self.place_fighter(f, dest)       # ESCAPE ARTIST: boosting, the hero goes to any space instead of moving
            else:
                self.move_fighter(f, dest, f.move + extra)
        self.fx.emit("after_maneuver", player)

    def play_scheme(self, player: int, fighter: Fighter, card: Card, target: Fighter | None = None,
                    choosers: dict | None = None):
        """`target`: the fighter the scheme hits when its effect picks one (A Momentary Glance: the AI plans it).
        `choosers` (player -> effects Chooser): who answers the card's other decisions; None = the controllers (and
        the panel, in a session). A hero of `fx.dsl_heroes` resolves the card through the interpreter (and returns
        the Await of a chooser that paused it); any other keeps the legacy path (the human resolves the text, the
        engine the ONGOING bonus)."""
        if not card.is_scheme or not card.usable_by(fighter.name) or card not in self.players[player].hand:
            raise RuleError(t("err.cannot_play", title=card.title, fid=fighter.fid))
        if self.players[player].hero.slug in self.fx.dsl_heroes:
            from .effects.driven import play_scheme
            return play_scheme(self, player, fighter, card, target, choosers)
        from .combat import resolve_scheme
        self.use_action()
        self.discard_card(player, card, played=True)
        resolve_scheme(self, player, fighter, card)
        return None

    @staticmethod
    def check_attack_card(fighter: Fighter, card: Card) -> None:
        if not card.can_attack:
            raise RuleError(t("err.not_attack_type", title=card.title, type=card.type))
        if not card.usable_by(fighter.name):
            raise RuleError(t("err.wrong_fighter", title=card.title, fighter=card.fighter, name=fighter.name))

    @staticmethod
    def check_defense_card(fighter: Fighter, card: Card) -> None:
        if not card.can_defend:
            raise RuleError(t("err.not_defense_type", title=card.title, type=card.type))
        if not card.usable_by(fighter.name):
            raise RuleError(t("err.wrong_fighter", title=card.title, fighter=card.fighter, name=fighter.name))

    def attack(self, attacker: Fighter, target: Fighter, card: Card, def_card="ask",
               values: tuple[int, int] = (0, 0), boost: Card | None = None):
        """Transactional: validates reach and both cards before spending the action."""
        from .combat import resolve_combat
        def_card = self._declare_attack(attacker, target, card, def_card)
        return resolve_combat(self, attacker, target, card, def_card, values, boost)

    def begin_attack(self, attacker: Fighter, target: Fighter, card: Card, def_card="ask",
                     values: tuple[int, int] = (0, 0), attacked: bool = True) -> "CombatFlow":
        """Like `attack`, but returns the combat as a flow the caller drives step by step (the session stops it at the
        panel when a card effect asks the human something). The action is already spent when it returns.
        `attacked=False`: the caller already raised the `attacked` event (the live session does, before the bot's
        defense is placed on the table)."""
        from .combat_flow import CombatFlow
        def_card = self._declare_attack(attacker, target, card, def_card, attacked)
        return CombatFlow(self, attacker, target, card, def_card, values)

    def _declare_attack(self, attacker: Fighter, target: Fighter, card: Card, def_card, attacked: bool = True) -> Card | None:
        """Everything before the cards resolve: checks, the action, the `attacked` event and the defense choice. The
        event comes first (UNCANNY INTUITION spends a token and draws before the defense, so the drawn card may be
        it) and a defense asked after an attack a rule turns face up is the one choice that may know the card."""
        if not self.fx.may_attack(attacker.owner):
            raise RuleError(t("err.cannot_attack_first", fid=attacker.fid))
        if not self.can_attack(attacker, target):
            raise RuleError(t("err.out_of_reach", attacker=attacker.fid, target=target.fid))
        self.check_attack_card(attacker, card)
        if card not in self.players[attacker.owner].hand:
            raise RuleError(t("err.not_in_hand", title=card.title, fid=attacker.fid))
        if def_card not in ("ask", None):
            self.check_defense_card(target, def_card)
            if def_card not in self.players[target.owner].hand:
                raise RuleError(t("err.not_in_hand", title=def_card.title, fid=target.fid))
        self.use_action()
        from .effects.events import attack_revealed
        revealed = attacked and attack_revealed(self, target)      # judged before the trigger spends the token
        if attacked:
            self.fx.emit("attacked", attacker, target, card)
        if def_card == "ask":
            ctrl = self.controllers[target.owner]
            def_card = ctrl.choose_defense(self, attacker, target, attack_card=card) if revealed \
                else ctrl.choose_defense(self, attacker, target)
        return def_card

    # start-of-turn abilities
    def use_ability(self, player: int, trigger_id: str, target: Fighter | None = None):
        """Runs one ability trigger of `player`'s hero through the interpreter now, aimed at `target` (Medusa's gaze:
        the AI or the session decides when and on whom; the dispatcher leaves it to them). RuleError if `target` is
        not one the trigger may pick."""
        from .effects.driven import use_ability
        return use_ability(self, player, trigger_id, target)

    def hellboy_anung_start(self, player: int, card: Card, dest: int | None) -> None:
        if "hellboy" in self.fx.dsl_heroes:      # the DSL trigger anung_discard_move already ran at begin_turn
            return
        self.discard_card(player, card)
        if dest is not None:
            self.move_fighter(self.hero_named("Hellboy"), dest, card.boost)

    def hellboy_detective_draw(self, player: int) -> bool:
        """Start-of-turn draw at the rival's start space: the `draw` trigger active in the current form (Hellboy in
        OCCULT DETECTIVE: 2 cards) with the condition `hero_on_rival_start`; how many, the data say."""
        if "hellboy" in self.fx.dsl_heroes:      # the DSL trigger detective_draw already ran at begin_turn
            return False
        hero = self.hero(player)
        for t in self.triggers(player, "start_of_turn"):
            if t.get("effect") != "draw" or t.get("condition") != "hero_on_rival_start":
                continue
            if hero.alive and hero.pos == self.start_spaces[1 - player]:
                self.draw(player, int(t["n"]))
                return True
        return False
