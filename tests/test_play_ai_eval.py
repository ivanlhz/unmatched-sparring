"""`play.py --ai-eval new`: the evaluation of F-AI-EVAL-RESOLUTION reaches the controller, and the journal header and the game log say which one plays."""
from __future__ import annotations

from types import SimpleNamespace

from sparring import decision_log
from sparring.ai_medusa import MedusaAI
from sparring.play import ai_config
from sparring.search.adapter import RESOLUTION, EvalWeights
from sparring.search.controller import make_bot_ai

CFG = SimpleNamespace(raw={"ai": "ismcts", "ai_time_budget": 3})


def test_without_the_option_the_configuration_is_untouched():
    assert ai_config(CFG, None, None) == CFG.raw == ai_config(CFG, None, None, "old")
    ai = make_bot_ai(ai_config(CFG, None, None), 0)
    assert ai.weights == EvalWeights() and ai.explicit == frozenset()
    assert decision_log.ai_info(ai)["eval"] == "old" and decision_log.ai_label(ai).endswith("eval=old)")


def test_the_new_evaluation_reaches_the_controller_and_is_named_in_the_header_and_the_log_line():
    ai = make_bot_ai(ai_config(CFG, None, None, "new"), 0)
    assert ai.weights == EvalWeights(**RESOLUTION) and ai.explicit == frozenset()
    assert decision_log.ai_info(ai)["eval"] == "new" and "eval=new" in decision_log.ai_label(ai)
    assert "ai_eval" not in CFG.raw                           # the configuration object is not modified


def test_a_weight_the_json_sets_wins_over_the_new_evaluation():
    cfg = SimpleNamespace(raw={"ai": "ismcts", "ai_eval": {"deck_hp": 0.5}})
    ai = make_bot_ai(ai_config(cfg, None, None, "new"), 0)
    assert ai.weights.deck_hp == 0.5 and ai.weights.card_hp == RESOLUTION["card_hp"]
    assert decision_log.ai_info(ai)["eval"] == "custom"


def test_the_heuristic_has_no_evaluation_to_name():
    assert decision_log.ai_info(MedusaAI(0)) == {"ai": "heuristic"}


def test_a_hero_profile_beats_the_new_evaluation_but_not_what_the_json_sets():
    from sparring.search.adapter import hero_weights
    ai = make_bot_ai(ai_config(CFG, None, None, "new"), 0)
    assert hero_weights(ai.weights, "doctor-strange", ai.explicit).caution == 0.3
    cfg = SimpleNamespace(raw={"ai": "ismcts", "ai_eval": {"caution": 0.5}})        # the JSON sets the very value that RESOLUTION has
    ai = make_bot_ai(ai_config(cfg, None, None, "new"), 0)
    assert hero_weights(ai.weights, "doctor-strange", ai.explicit).caution == 0.5
