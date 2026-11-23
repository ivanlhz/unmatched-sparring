"""Elektra's 9-dial is read by the fast-mode snapshot from the start of the game. The snapshot's list of dials is built once (and the panel carries
it), so a dial that only became hers at the Resurrect was never read: every check of it failed and the bot paused for dials that were right (Ivan, 23/11)."""
from __future__ import annotations

from sparring.tts import lua
from test_d3_table_effects import build


def test_the_snapshot_reads_elektras_resurrected_dial_before_she_resurrects(tmp_path):
    for bot, human in (("elektra", "medusa"), ("medusa", "elektra")):
        (tmp_path / bot).mkdir()
        session, table, game, fake, cfg, client = build(tmp_path / bot, bot, human, ())
        try:
            flipped = cfg.session_config().flip_dials["elektra"]
            assert flipped not in session.cfg.dials.values()
            spec = session.snapshot_spec()
            assert flipped in spec.dials
            assert flipped in lua.snapshot_lua(spec)
        finally:
            client.close()
            fake.close()
