"""Score de robustesse d'un run (FO8 du 25/11)."""
from __future__ import annotations

from patrick.validation import robustness


def _detail(**kw):
    base = {"dm_result": {"p_value": 0.01, "worse": False}, "target_fdr": {"significant": True},
            "pbo": {"pbo": 0.2, "reliability": {"ok": True}}, "sizes": {"holdout": {"n_eff": 60}}, "suspect": None}
    return {**base, **kw}


def test_every_piece_of_evidence_gives_a_full_score():
    out = robustness.score(_detail(), {"placebo_verdict": "stable", "alignment_reason": None})
    assert out["score"] == 100 and out["grade"] == "solid" and all(p["ok"] for p in out["parts"])


def test_a_worse_model_a_leaking_placebo_and_few_observations_lose_their_points():
    out = robustness.score(_detail(dm_result={"p_value": 0.01, "worse": True}, sizes={"holdout": {"n_eff": 12}}),
                           {"placebo_verdict": "same_day"})
    lost = {p["key"] for p in out["parts"] if not p["ok"]}
    assert lost == {"dm", "placebo", "n_eff"} and out["score"] == 40 and out["grade"] == "weak"


def test_missing_evidence_is_neither_won_nor_hidden():
    out = robustness.score({"is_cpcv": True}, {})
    assert out["score"] == 10 and {p["key"] for p in out["parts"] if p["ok"] is None} >= {"dm", "placebo", "pbo", "n_eff"}
