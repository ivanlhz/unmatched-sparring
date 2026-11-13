import collections, sys
sys.path.insert(0, "/workspace")
from sparring import sim
from sparring.search.controller import make_bot_ai
tally = collections.Counter()
for foe in ("hellboy", "medusa", "sinbad"):
    for seed in (1, 2):
        ai = make_bot_ai({"ai": "ismcts", "iterations": 30})
        trace = []
        out = sim.play(seed, bot_hero="philippa", human_hero=foe, medusa=ai, max_turns=30, trace=trace, rival="chaser")
        text = "\n".join(trace)
        for t in ("Owlform", "Lightning bolt", "Chain lightning", "Regicide", "Spellbreaker", "Cunning", "Redanian plot", "Paralyzing fetters", "Blinding dust", "Do my bidding", "Polymorphy", "Backup plan", "Spymaster"):
            tally[t] += text.count(t)
        print(foe, seed, "winner", out.winner, "turns", out.turns, "fallbacks", getattr(ai, "fallbacks", None), flush=True)
print(dict(tally))
