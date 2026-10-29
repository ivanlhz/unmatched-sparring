"""Python side of the effect bridge: turns hero data (`data/tts/<slug>.json`) into batched Lua ops.

Every function returns ops (scripts built by `lua`) meant for `lua.composite`, so a whole effect (a form change, a
revealed hand) still costs one message. Nothing here sends anything. The Lua pieces live at the end of `lua.py`."""
from __future__ import annotations

from ..board import Board
from . import lua
from .hero_table import HeroTable, HeroTableError


def _fighter(table: HeroTable, fid: str):
    try:
        return table.fighters[fid]
    except KeyError:
        raise HeroTableError(f"{table.slug}: unknown fighter {fid!r}") from None


def state_guid(table: HeroTable, fid: str, state_index: int) -> str:
    """GUID of a fighter's miniature while it is in state `state_index` (1-based, in `piece` order)."""
    pieces = _fighter(table, fid).pieces
    if not 1 <= state_index <= len(pieces):
        raise HeroTableError(f"{table.slug}: {fid} has {len(pieces)} state(s), not {state_index}")
    return pieces[state_index - 1]


def token_rot_z(table: HeroTable, token: str, face: str) -> float:
    """Z rotation that shows `face` of a two-faced token, from the data field `token_faces` (flagged verify_live)."""
    try:
        return float(table.token_faces[token]["faces"][face])
    except (KeyError, TypeError, ValueError):
        raise HeroTableError(f"{table.slug}: no rotation for face {face!r} of token {token!r}") from None


def token_source(table: HeroTable, token: str) -> str:
    try:
        return table.tokens[token]
    except KeyError:
        raise HeroTableError(f"{table.slug}: unknown token {token!r}") from None


def form_change_ops(table: HeroTable, fid: str, from_state: int, to_state: int, token: str, face: str,
                    seats: list[str]) -> list[str]:
    """Hellboy's form change as three ops: swap the miniature state, turn the ability token to the new face (only if it
    is not showing it), and ping the token then the miniature (both GUIDs of the miniature are candidates: the new
    one exists after the swap). `from_state`/`to_state` are 1-based state indexes of the fighter."""
    mini = state_guid(table, fid, from_state)
    state_guid(table, fid, to_state)
    return [lua.set_state(mini, to_state),
            lua.set_token_face(token_source(table, token), token_rot_z(table, token, face)),
            lua.ping_objects(seats, [[token_source(table, token)], list(_fighter(table, fid).pieces)])]


def take_token_copy_op(table: HeroTable, token: str, position: tuple[float, float, float]) -> str:
    """One more token from the same source object (Abe's Uncanny Intuition); see `lua.take_token_copy`."""
    return lua.take_token_copy(token_source(table, token), position)


def reveal_hand_ops(card_ids: list[int], spots: list[tuple[float, float, float]], rot_y: float, seat_color: str, *,
                    identity, id_range: tuple[int, int], ping_seats: list[str]) -> list[str]:
    """The bot shows its hand face up (`show_hand_row`) and pings the spots, so the human sees where to look."""
    return [lua.show_hand_row(card_ids, spots, rot_y, seat_color, identity=identity, id_range=id_range),
            lua.ping_points(ping_seats, list(spots)[:lua.MAX_PING_GROUPS])]


def move_human_piece(board: Board, guid: str, space: int, board_guid: str | None = None) -> str:
    """The bot moves a piece of the human by an effect: same movement as any other piece."""
    return lua.move_piece(board, guid, space, board_guid)
