"""Test de fumée de l'interface web : `ingest()` est monkeypatché (même
donnée synthétique que `test_pipeline_smoke.py`, pas de réseau) ; le reste
(formulaire -> RunConfig -> run en arrière-plan -> polling -> résultats) tourne
pour de vrai via `TestClient`.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.pipeline import engine as engine_module
from patrick.webapp import run_manager
from patrick.webapp.app import app


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 15 + np.cumsum(rng.normal(0, 0.5, n)).clip(min=-10)
    df = pd.DataFrame({"IDX_VIX": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


@pytest.fixture(autouse=True)
def _clean_runs():
    run_manager._RUNS.clear()
    yield
    run_manager._RUNS.clear()


def _form_data(tmp_path) -> dict:
    return {
        "name": "smoke_web_test",
        "target_symbol": "^VIX",
        "horizons": "3,5",
        "flat_thr": "0.003",
        "regimes": "GLOBAL",
        "start_date": "2015-01-01",
        "yf_coverage": "0.85",
        "interact_top_base": "15",
        "interact_top_pairs": "8",
        "interact_final_n": "6",
        "pool_prefilter": "60",
        "n_wf_folds": "2",
        "min_train_frac": "0.5",
        "min_train_rows": "100",
        "min_test_rows": "20",
        "selection_method": "shap",
        "n_features_grid": "5,8",
        "shap_sample": "200",
        "tuning_enabled": "on",
        "top_k": "2",
        "n_trials": "3",
        "cv_splits": "2",
        "output_dir": str(tmp_path / "runs"),
        "seed": "42",
        "families": ["technical", "interactions", "spike", "vol_models", "macro"],
        "vol_models": ["egarch", "kalman"],
        "sampler_candidates": ["SMOTE"],
        "algos": ["RandomForest", "XGBoost"],
    }


def test_run_via_web_form_end_to_end(tmp_path, monkeypatch):
    def fake_ingest(objective, universe, store=None, force=False):
        return _synthetic_raw()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)

    client = TestClient(app)
    resp = client.post("/runs", data=_form_data(tmp_path), follow_redirects=False)
    assert resp.status_code == 303, resp.text
    run_id = resp.headers["location"].rsplit("/", 1)[-1]

    deadline = time.time() + 120
    status = None
    while time.time() < deadline:
        status = client.get(f"/runs/{run_id}/status").json()
        if status["status"] != "running":
            break
        time.sleep(0.5)
    assert status is not None and status["status"] == "done", status

    results = client.get(f"/runs/{run_id}/results").json()
    assert results["n_evaluations"] > 0
    assert results["final_best"] is not None
    assert "best_model" in results["artifacts"]
    assert "leaderboard_csv" in results["artifacts"]

    download = client.get(f"/runs/{run_id}/download/best_model")
    assert download.status_code == 200
