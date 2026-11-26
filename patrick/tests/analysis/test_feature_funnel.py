"""Entonnoir de sélection des variables d'un run (VI8 du 26/11)."""
from __future__ import annotations

from patrick.analysis import feature_funnel


def test_the_funnel_goes_from_the_universe_to_the_retained_features():
    meta = {"feature_names": ["tech_rsi14", "vol_garch", "macro_t10y", "tech_mom20"],
            "feature_pool": [f"f{i}" for i in range(1500)],
            "universe_reduction": {"kept": ["A", "B", "C"], "dropped": {"D": "corr 0.97 avec A"}, "not_eligible": ["E"]}}
    out = feature_funnel.funnel(meta)
    assert [(s["key"], s["n"]) for s in out["steps"]] == [("series", 5), ("series_kept", 4), ("pool", 1500), ("selected", 4)]
    assert out["families"][0] == {"family": "tech", "n": 2}
    assert out["steps"][2]["width"] == 100.0 and 4 <= out["steps"][-1]["width"] < 40      # échelle logarithmique : 4 reste visible


def test_without_reduction_or_meta_the_funnel_is_shorter_or_absent():
    assert [s["key"] for s in feature_funnel.funnel({"feature_names": ["a"], "feature_pool": ["a", "b"]})["steps"]] == ["pool", "selected"]
    assert feature_funnel.funnel({}) is None and feature_funnel.funnel(None) is None
