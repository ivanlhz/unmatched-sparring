"""C4 review hardening: the bot's chooser over the rival hand is blind without a look, own-pile ranking is own only,
and a blind re-draw never pushes the possible count past its bound."""
from sparring.effects.choose import ChoiceRequest, ControllerChooser
from sparring.effects.run import Ctx, EffectRun

from test_effects_info import look, mk, set_hand, ScriptedChooser

BLIND_OPS = [{"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 1, "chooser": "owner"}}]


def test_blind_pick_among_the_rival_hand_is_the_same_position_whatever_the_cards(bprd):
    """No look_hand: the same seed picks the same POSITION for different human hands (identities cannot rank)."""
    picked = []
    for titles in (("Leap Away", "Concussion Device", "Secure The Scene", "Advanced Psychometry"),
                   ("Counterhex Shield", "B.P.R.D. Utility Belt", "Cold Iron And Holy Water", "Ward And Prepare")):
        g = mk(bprd, "hellboy", "abe-sapien", seed=5)
        hand = set_hand(g, 1, *titles)
        EffectRun(BLIND_OPS, Ctx(owner=0, this_fid="hellboy")).run(g, ControllerChooser())
        picked.append(hand.index(g.players[1].discard[-1]))
    assert picked[0] == picked[1]


def test_seen_pick_ignores_a_stronger_unseen_card(bprd):
    g = mk(bprd, "hellboy", "abe-sapien")
    hand = set_hand(g, 1, "Leap Away", "Concussion Device")
    look(g)
    g.players[1].hand.append(newcomer := next(c for c in g.players[1].deck if c.type == "scheme"))
    g.players[1].deck.remove(newcomer)
    EffectRun(BLIND_OPS, Ctx(owner=0, this_fid="hellboy")).run(g, ControllerChooser())
    assert g.players[1].discard[-1] in hand


def test_rival_pile_requests_are_not_ranked_by_value(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    options = [c.card_id for c in g.players[1].deck[:5]]
    req = ChoiceRequest("cards", 0, options, 1, 1, extra={"zone": "deck", "purpose": "search", "of": 1})
    assert ControllerChooser().choose(g, req) == [options[0]]


def test_a_blind_redraw_cannot_exceed_the_possible_bound(bprd):
    g = mk(bprd, "baba-yaga", "abe-sapien")
    set_hand(g, 1, "Faster. Stronger.", "Secure The Scene", "Leap Away", "Concussion Device", "Advanced Psychometry")
    look(g)

    class NoDraw:
        def choose(self, game, req):
            return [0] if req.kind == "amount" else list(req.options[:req.min])

    EffectRun.for_card("baba-yaga", "Pact Of Secrecy", "scheme", Ctx(owner=0, this_fid="baba")).run(g, NoDraw())
    known, st = g.players[0].known, g.players[1]
    back = next(c for c in st.deck if c.card_id in known.possible)
    st.deck.remove(back)
    st.deck.insert(0, back)
    g.draw(1)
    assert sum(1 for c in st.hand if c.card_id in known.possible) <= known.possible_hi
