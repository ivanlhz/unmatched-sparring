"""Yennenga's Archers at the live table (docs/heroes/yennenga.md): their life is told by the face of the token.

Ivan, 2026-11-20: each Archer is a two-sided token, a small yellow "2" in the corner is 2 health, no number is 1 health, and it is flipped as it
is hurt (there is no dial). The engine is the authority; `data/tts/yennenga.json` gives the Z rotation of each face (`faces`, verify live).
- The BOT's Archers: whenever the engine's life of one changes (a hit, a heal, a return from defeat at 2) the bot turns the piece to the face of
  that life, only if it is not there already, and says it in the chat. At the start of a game every Archer is put on the "2" face.
- The HUMAN's Archers: the human flips them. Each look reads their rotation; when the face disagrees with the engine's life the chat asks the
  human to flip it and pings the piece (once per disagreement). Neither side is trusted silently."""
from __future__ import annotations

from .i18n import t
from .session_translators import DOMAIN, ERRORS
from .tts import lua
from .tts.hero_table import HeroTableError, load_hero_table
from .tts.lua import ChatKind


def _faces(session) -> dict[str, dict]:
    """fid -> {life: Z rotation} of every Archer-like piece of the two heroes whose table data gives faces."""
    out = {}
    for player in (session.bot, session.human):
        try:
            table = load_hero_table(session.game.hero_def(player).slug)
        except HeroTableError:
            continue
        out.update({fid: f.faces for fid, f in table.fighters.items() if f.faces and fid in session.game.fighters})
    return out


def _life_of(faces: dict, rot_z: float) -> int:
    """The life whose face is nearest to this rotation."""
    def gap(k):
        d = abs((rot_z - faces[k]) % 360)
        return min(d, 360 - d)
    return int(min(faces, key=gap))


def track(session, announce: bool = False) -> None:
    """Puts the bot's Archers on the face of their life and checks the human's. `announce`: the start of a game or a resume (the bot's
    pieces are written even if nothing changed; the human's disagreements are said again)."""
    faces = _faces(session)
    if not faces:
        return
    game = session.game
    said = session.__dict__.setdefault("_archer_state", {})
    warned = session.__dict__.setdefault("_archer_warned", {})
    if announce:
        said.clear()
        warned.clear()
    sets, reads, names, written = {}, {}, {}, {}
    for fid, face in faces.items():
        f = game.fighters[fid]
        guids = session._guids(fid)
        if not f.alive or not guids:
            said.pop(fid, None)
            continue
        names[fid] = getattr(game, "nicknames", {}).get(fid, f.name)
        life = int(f.hp)
        if f.owner == session.human:
            reads[guids[0]] = fid
        elif said.get(fid) != life and str(life) in face:
            sets[guids[0]] = face[str(life)]
            written[guids[0]] = fid
    if not sets and not reads:
        return
    script = lua.archer_faces(sets, list(reads))
    op = session._w(script, DOMAIN)

    def check() -> None:
        try:
            res = op.result or {}
        except ERRORS:
            session.say(t("archer.failed"), ChatKind.WARNING)
            return
        done = res.get("set") if isinstance(res.get("set"), dict) else {}
        for guid, fid in written.items():
            info = done.get(guid) or {}
            if info.get("found") is False:
                session.say(t("archer.missing", name=names[fid]), ChatKind.WARNING)
                continue
            said[fid] = int(game.fighters[fid].hp)
            if info.get("flipped"):
                session.say(t("archer.flipped", name=names[fid], life=said[fid]), ChatKind.ABILITY)
        seen = res.get("read") if isinstance(res.get("read"), dict) else {}
        for guid, fid in reads.items():
            if guid not in seen:
                continue
            face, life = _life_of(faces[fid], float(seen[guid])), int(game.fighters[fid].hp)
            if face == life:
                warned.pop(fid, None)
            elif warned.get(fid) != (life, face):
                warned[fid] = (life, face)
                session.say(t("archer.human_flip", name=names[fid], life=life, shows=face), ChatKind.WARNING)
                session._w(lua.ping_objects([session.cfg.bot_seat, session.cfg.human_seat], [[guid]]), "misc")
    session._post.append(check)
