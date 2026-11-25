"""Explication en clair d'une prédiction (FO17 du 25/11)."""
from __future__ import annotations

from patrick.live.explain import plain_summary


def test_the_summary_keeps_the_strongest_pushes_and_brakes():
    contributions = [{"name": "or_ret1", "value": 0.012, "shap": 0.31}, {"name": "vix", "value": 14.2, "shap": -0.2},
                     {"name": "rsi", "value": 61.0, "shap": 0.1}, {"name": "dxy", "value": 104.0, "shap": -0.05},
                     {"name": "mom", "value": 0.4, "shap": 0.02}, {"name": "x", "value": 1.0, "shap": 0.01}]
    out = plain_summary(contributions)
    assert [c["name"] for c in out["for"]] == ["or_ret1", "rsi", "mom"] and [c["name"] for c in out["against"]] == ["vix", "dxy"]
    assert plain_summary([]) == {"for": [], "against": []}
