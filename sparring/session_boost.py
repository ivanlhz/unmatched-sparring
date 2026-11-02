"""Does the human's free BOOST survive the rival's card? (Turtle power!, Second Shot, Out Of Time, Flame Lash...)

The boost of a `may_boost` card is a DURING effect of the card. The human puts the boost card on the table BEFORE the
engine runs the combat (`Session._await_boost`), so the panel has to know in advance whether the rival's IMMEDIATELY
(Feint, Planned Recklessness as Occult Detective, Ward And Prepare, Break something...) takes that effect off the card.
The engine alone decides that, with the same rules it uses when the combat really runs: a dry run on a CLONE of the game
(`Game.clone`: no table reads, no panel, the bots decide with their own controllers; the shared RNG is put back
afterwards, so the real combat draws exactly what it would have drawn) that stops when the combat enters
DURING and asks whether the human's side is cancelled there. A cancel of only the AFTER effects (Short circuit) leaves
the DURING boost where it was; a cancel of DURING and AFTER (Break something) or of everything removes it. The clone
never touches the session: the real combat runs afterwards from the untouched game."""
from __future__ import annotations

from .combat_flow import Phase, legacy_chooser


def offered(session, p, human_card) -> bool:
    """True when the human's card still has its DURING effects (the boost) when the combat reaches DURING; False when
    the rival's card cancels them. Any failure of the dry run answers True: the real combat then says what is wrong,
    as it always did."""
    g = session.game.clone()
    rng_state = g.rng.getstate()                   # the clone shares the live RNG: the real combat must draw the same
    session.make_known(human_card, game=g)
    att, tgt = g.fighters[p.attacker.fid], g.fighters[p.target.fid]
    value = session.pending_value
    try:
        if p.kind == "human_attacks":
            flow = g.begin_attack(att, tgt, human_card, p.bot_card, values=(value, 0), attacked=False)
        else:
            flow = g.begin_attack(att, tgt, p.bot_card, human_card, values=(0, value), attacked=False)
        decide = legacy_chooser(g, flow, None, session.human)
        while flow.phase is not Phase.DURING and not flow.done:
            if (wait := flow.step()) is not None:
                flow.resume(decide(wait.choice))
        if p.kind == "human_attacks" and flow.atk_card is not human_card:       # The Mists of Munnopor discarded it
            return False
        return flow.done or not flow.is_cancelled("atk" if p.kind == "human_attacks" else "def")
    except Exception:                              # any failure of the dry run: the real combat says what is wrong
        return True
    finally:
        g.rng.setstate(rng_state)
