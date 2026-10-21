"""Explorateur de variables (`patrick/analysis/features_explorer.py`, `/variables`)."""
from __future__ import annotations

import pytest
from analysis_support import seed_run
from fastapi.testclient import TestClient

from patrick.analysis import features_explorer as fx
from patrick.analysis import registry
from patrick.tracking import db as trackdb
from patrick.webapp.app import app


@pytest.mark.parametrize("name, expected", [
    ("IDX_GSPC_zscore_10d", "IDX_GSPC"), ("CL_ret_1d", "CL"), ("PCE_Price_Index_ret_5d", "PCE_Price_Index"), ("CPI_kalman_filtered", "CPI"),
    ("DX_Y.NYB_heston_spread__prod__US10Y_Rate_rsi_14d", "DX_Y.NYB"), ("Core_CPI_lag10", "Core_CPI"), ("GDP", "GDP"), ("MAR_vs_ma10", "MAR"),
])
def test_base_series_cuts_at_the_first_transformation(name, expected):
    assert fx.base_series(name) == expected


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    registry.clear_cache()
    conn, info = seed_run(tmp_path, monkeypatch, run_id="r1")
    trackdb.save_feature_stability(conn, "r1", 0.5, 4, {"CL_ret_1d": 1.0, "IDX_GSPC_zscore_10d": 0.5})
    # second run sur une autre cible, mêmes variables
    import json

    from patrick.webapp.forms import default_config_dict
    cfg = default_config_dict()
    cfg["objective"].update({"target_symbol": "OTH", "horizons": [1], "regimes": ["GLOBAL"]})
    trackdb.create_run(conn, "r2", "OTH", 1, info["snapshot_id"], json.dumps(cfg), "h", "sha", 1)
    tid = trackdb.create_trial(conn, "r2", "GLOBAL", "XGBoost", "SMOTE", 3, "shap")
    trackdb.mark_best_trial(conn, tid)
    trackdb.finish_run(conn, "r2", status="done", n_trials=1)
    trackdb.save_feature_stability(conn, "r2", 0.9, 4, {"CL_ret_1d": 0.75, "OTH_hurst_100d": 1.0})
    yield conn
    registry.clear_cache()


def test_overview_aggregates_runs_targets_and_families(seeded):
    d = fx.overview(seeded)
    by = {r["feature"]: r for r in d["features"]}
    assert d["n_features"] == 3 and d["n_runs"] == 2
    assert by["CL_ret_1d"]["runs"] == 2 and by["CL_ret_1d"]["targets"] == 2 and by["CL_ret_1d"]["mean_freq"] == pytest.approx(0.875)
    assert by["CL_ret_1d"]["always"] == 1 and by["CL_ret_1d"]["family"] == "momentum" and by["CL_ret_1d"]["series"] == "CL"
    assert d["features"][0]["feature"] == "CL_ret_1d"                                  # tri : plus de runs d'abord
    assert d["jaccard"]["n"] == 2 and d["jaccard"]["mean"] == pytest.approx(0.7) and d["jaccard"]["share_low"] == 0.0
    assert sum(f["share"] for f in d["families"]) == pytest.approx(1.0)
    assert {r["target"] for r in d["matrix"]["rows"]} == {"TST", "OTH"}
    assert all(sum(r["shares"].values()) == pytest.approx(1.0) for r in d["matrix"]["rows"])


def test_archived_and_failed_runs_are_ignored(seeded):
    seeded.execute("UPDATE run SET is_archived = 1 WHERE run_id = 'r2'")
    seeded.commit()
    assert fx.overview(seeded)["n_runs"] == 1


def test_detail_lists_runs_with_their_best_trial(seeded):
    d = fx.feature_detail(seeded, "CL_ret_1d")
    assert d["n_runs"] == 2 and d["targets"] == ["OTH", "TST"]
    assert d["runs"][0]["freq"] == 1.0 and d["runs"][0]["algo"] == "XGBoost" and d["runs"][0]["n_features"] == 8
    assert fx.feature_detail(seeded, "nope")["runs"] == []


def test_variables_pages_and_api(seeded):
    c = TestClient(app)
    assert c.get("/variables").status_code == 200
    body = c.get("/api/variables/overview").json()
    assert body["n_features"] == 3
    assert c.get("/api/variables/detail?feature=CL_ret_1d").json()["n_runs"] == 2
    assert c.get("/api/variables/detail?feature=").status_code in (400, 422)
