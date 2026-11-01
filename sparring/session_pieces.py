"""Piece identity: a miniature or token is found by GUID AND checked by who it is (docs/card-identity.md, "Piece identity").

The data gives every piece a GUID, but the tournament save gives the SAME one (4fdf31) to Abe Sapien's and Donatello's
miniatures, each inside its own bag. TTS keeps GUIDs unique, so when both are out the second one gets a new random GUID
and the configured one would make the session follow the other hero's piece. So the object at a configured GUID is read
with its name (TTS colour tags stripped, "[6f2176]Donatello" -> "donatello") and compared with the nicknames of the
fighters in play:

- it carries ANOTHER fighter's name: the GUID is that fighter's, not this one's;
- or nothing is there: the piece may be out under a new GUID.

In both cases the loose object that carries this fighter's own name is looked for (one read). If exactly one is found
its GUID replaces the configured one for the rest of the session and is saved with it (`resolved_pieces`); the player
reads one line. An object with no name, or a name that is nobody's in play, is trusted: the GUID wins."""
from __future__ import annotations

import re

from . import i18n
from .tts import lua

_TAGS = re.compile(r"\[[A-Za-z0-9\-/]*\]")      # the same class as the Lua side (find_pieces_by_name)
PIECE_TYPES = ("Custom_Model", "Custom_Assetbundle", "Custom_Token", "Figurine")   # what the miniatures and tokens of data/tts are


def is_piece_type(kind) -> bool:
    return isinstance(kind, str) and (kind in PIECE_TYPES or kind.startswith("Figurine"))
t = i18n.t


def plain_name(name) -> str:
    """The name as the player reads it: no TTS colour/style tags, lower case, single spaces."""
    return " ".join(_TAGS.sub("", name if isinstance(name, str) else "").split()).casefold()


def expected_names(session) -> dict[str, str]:
    """fid -> plain name its piece must carry (the fighter's nickname)."""
    return {fid: plain_name(session.cfg.nicknames[fid]) for fid in session.cfg.pieces if fid in session.cfg.nicknames}


def read(session) -> dict:
    """One read: what lies at every GUID the configuration (as resolved so far) knows."""
    guids = sorted({g for fid in session.cfg.pieces for g in session._guids(fid)})
    found = session.client.call_lua(lua.piece_spaces_by_guid(session.game.board, guids))
    return found if isinstance(found, dict) else {}


def problems(session, found: dict) -> dict[str, str | None]:
    """fid -> the fighter whose piece sits at its GUID instead (None: nothing is there) for every fid whose GUIDs hold
    no piece of its own."""
    names, out = expected_names(session), {}
    for fid, own in names.items():
        owners, hit = [], False
        for g in session._guids(fid):
            info = found.get(g)
            if not (isinstance(info, dict) and info.get("found")):
                continue
            hit, seen = True, plain_name(info.get("name"))
            owners.append(None if seen == own else next((o for o, n in names.items() if n == seen and o != fid), None))
        if not hit:
            out[fid] = None
        elif all(o is not None for o in owners):
            out[fid] = owners[0]
    return out


def resolve(session, found: dict | None = None) -> tuple[bool, list[str]]:
    """Re-points the fighters whose GUID holds someone else's piece (or nothing) to the loose object that carries their
    name. Returns (anything changed, lines for the player)."""
    cfg, names = session.cfg, expected_names(session)
    found = read(session) if found is None else found
    bad = problems(session, found)
    if not bad:
        return False, []
    hits = session.client.call_lua(lua.find_pieces_by_name(sorted({names[f] for f in bad}))) or {}
    hits = hits if isinstance(hits, dict) else {}
    claimed = {g for fid in cfg.pieces if fid not in bad for g in session._guids(fid)}
    changed, notes = False, []
    for fid, owner in sorted(bad.items()):
        rows = hits.get(names[fid])
        cands = sorted({r["guid"] for r in rows if isinstance(r, dict) and isinstance(r.get("guid"), str)
                        and is_piece_type(r.get("type"))}
                       - claimed) if isinstance(rows, list) else []
        guids = session._guids(fid)
        if len(cands) == 1:
            old = next((g for g in guids if isinstance(found.get(g), dict) and found[g].get("found")), guids[0])
            new = [cands[0] if g == old else g for g in guids]
            cfg.pieces[fid] = new[0] if len(new) == 1 else new
            session.resolved_pieces[fid] = new
            claimed.add(cands[0])
            changed = True
            notes.append(t("piece.resolved", name=cfg.nicknames[fid], old=old, new=cands[0],
                           other=cfg.nicknames[owner] if owner else "-"))
        elif owner is not None:
            session._piece_gave_up.add(fid)
            notes.append(t("piece.unresolved", name=cfg.nicknames[fid], guid="/".join(guids),
                           other=cfg.nicknames[owner], found=len(cands)))
    if changed:
        session._snap_spec = None
        session.snap = None
    return changed, notes


def shared_guids(session) -> list[str]:
    """One line per GUID that the data gives to two different pieces or dials in play (checked on the configured GUIDs)."""
    cfg, owners = session.cfg, {}
    for fid in sorted(session.configured_pieces):
        for g in session.configured_pieces[fid]:
            owners.setdefault(g, []).append(cfg.nicknames.get(fid, fid))
    for fid, g in sorted(cfg.dials.items()):
        owners.setdefault(g, []).append(t("piece.dial_of", name=cfg.nicknames.get(fid, fid)))
    return [t("piece.shared", guid=g, names=t("common.and").join(sorted(set(who))))
            for g, who in sorted(owners.items()) if len(set(who)) > 1]


def restore(session, saved) -> None:
    """The resolved GUIDs of a saved game, back on the configuration (malformed entries are ignored)."""
    if not isinstance(saved, dict):
        return
    for fid, guids in saved.items():
        if (fid in session.cfg.pieces and isinstance(guids, list) and guids
                and all(isinstance(g, str) and lua._GUID.fullmatch(g) for g in guids)):
            session.cfg.pieces[fid] = guids[0] if len(guids) == 1 else list(guids)
            session.resolved_pieces[fid] = list(guids)
    session._snap_spec = None
