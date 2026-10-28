"""EffectState: everything the DSL adds to a Game, kept in `game.fx`.

Hooks (`adjust_damage`, `can_draw`, `can_gain_actions`, `emit`) are called by `Game` at fixed points. In C1 they
are no-ops; later phases fill them in without touching state.py again. They run on every clone used by ISMCTS,
so they must stay cheap."""
from __future__ import annotations


class EffectState:
    __slots__ = ("statuses", "ongoing", "counters", "modifiers", "dsl_heroes", "turn_start_pos", "attacked", "acting")

    def __init__(self) -> None:
        self.statuses: list[dict] = []                   # active status effects (name, target, until, amount)
        self.ongoing: list[dict | None] = [None, None]   # the ONE permanent scheme in play per player: {"card_id": int}
        self.counters: list[dict[str, int]] = [{}, {}]   # ability counters per player (intuition tokens, rage...)
        self.modifiers: list[dict] = []                  # active rule modifiers (max hand size, damage bonus...)
        self.dsl_heroes: set[str] = set()                # hero slugs whose cards the interpreter resolves
        self.turn_start_pos: dict[str, int] = {}         # fid -> space at the start of the turn (moved_this_turn)
        self.attacked: list[str] = []                    # fids that attacked this turn
        self.acting: int | None = None                   # player whose effect op is running right now (transient)

    # hooks: the bodies live in effects/modifiers.py; the guards keep the flag-off path free
    def adjust_damage(self, fighter, n, source):
        if not (self.statuses or self.modifiers):
            return n
        from .modifiers import adjust_damage
        return adjust_damage(self, fighter, n, source)

    def can_draw(self, player: int) -> bool:
        if not (self.statuses or self.modifiers):
            return True
        from .modifiers import can_draw
        return can_draw(self, player)

    def can_gain_actions(self, player: int) -> bool:
        if not (self.statuses or self.modifiers):
            return True
        from .modifiers import can_gain_actions
        return can_gain_actions(self, player)

    def can_force_discard(self, player: int, source_player: int) -> bool:
        """False vetoes a discard that `source_player` forces on `player` (Counterhex Shield)."""
        if not (self.statuses or self.modifiers):
            return True
        from .modifiers import can_force_discard
        return can_force_discard(self, player, source_player)

    def can_move(self, fighter) -> bool:
        """False when a status keeps `fighter` where it is (Burning Barrier, Counterhex Shield vs. enemy effects)."""
        if not (self.statuses or self.modifiers):
            return True
        from .modifiers import can_move
        return can_move(self, fighter)

    def emit(self, name, *args) -> None:
        if self.statuses and name in ("start_of_turn", "end_of_turn", "after_maneuver"):
            from .modifiers import expire_on_event      # C3 replaces this body with the full event dispatch
            expire_on_event(self, name, *args)

    # ongoing slot
    def ongoing_card_id(self, player: int) -> int | None:
        slot = self.ongoing[player]
        return None if slot is None else slot["card_id"]

    def set_ongoing(self, player: int, card_id: int) -> int | None:
        """Puts a scheme in play. Ivan's ruling (28/10): one per player, the new one replaces the old.
        Returns the replaced card id (or None)."""
        old = self.ongoing_card_id(player)
        self.ongoing[player] = {"card_id": card_id}
        return old

    def take_ongoing(self, player: int) -> int | None:
        old = self.ongoing_card_id(player)
        self.ongoing[player] = None
        return old

    # counters
    def counter_value(self, player: int, name: str, default: int = 0) -> int:
        return self.counters[player].get(name, default)

    def set_counter(self, player: int, name: str, value: int) -> None:
        self.counters[player][name] = value

    # clone / persist
    def is_empty(self) -> bool:
        return not (self.statuses or any(self.ongoing) or any(self.counters) or self.modifiers or self.dsl_heroes
                    or self.turn_start_pos or self.attacked)

    def copy(self) -> "EffectState":
        c = EffectState()
        if self.is_empty():
            return c
        c.statuses = [dict(s) for s in self.statuses]
        c.ongoing = [None if s is None else dict(s) for s in self.ongoing]
        c.counters = [dict(x) for x in self.counters]
        c.modifiers = [dict(m) for m in self.modifiers]
        c.dsl_heroes = set(self.dsl_heroes)
        c.turn_start_pos = dict(self.turn_start_pos)
        c.attacked = list(self.attacked)
        return c

    def to_dict(self) -> dict:
        """Only the non-empty parts, so a game without effects saves byte-identical to before."""
        out: dict = {}
        if self.statuses:
            out["statuses"] = [dict(s) for s in self.statuses]
        if any(self.ongoing):
            out["ongoing"] = [None if s is None else dict(s) for s in self.ongoing]
        if any(self.counters):
            out["counters"] = [dict(x) for x in self.counters]
        if self.modifiers:
            out["modifiers"] = [dict(m) for m in self.modifiers]
        if self.dsl_heroes:
            out["dsl_heroes"] = sorted(self.dsl_heroes)
        if self.turn_start_pos:
            out["turn_start_pos"] = dict(self.turn_start_pos)
        if self.attacked:
            out["attacked"] = list(self.attacked)
        return out

    @classmethod
    def from_dict(cls, raw: dict | None) -> "EffectState":
        fx = cls()
        raw = raw or {}
        fx.statuses = [dict(s) for s in raw.get("statuses", [])]
        fx.ongoing = [None if s is None else {"card_id": int(s["card_id"])} for s in raw.get("ongoing", [None, None])]
        fx.counters = [{str(k): int(v) for k, v in side.items()} for side in raw.get("counters", [{}, {}])]
        fx.modifiers = [dict(m) for m in raw.get("modifiers", [])]
        fx.dsl_heroes = set(raw.get("dsl_heroes", []))
        fx.turn_start_pos = {str(k): int(v) for k, v in raw.get("turn_start_pos", {}).items()}
        fx.attacked = list(raw.get("attacked", []))
        return fx
