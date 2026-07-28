"""Test de fumée bout-en-bout de la vue web du simulateur (Phase 4.7),
équivalent à `test_webapp_smoke.py` pour les runs : formulaire -> AJAX ->
résultats, mais ici pour /simulate. Pas de réseau, pas de worker séparé --
la simulation elle-même est un calcul synchrone rapide (lecture DB), pas un
run ML, donc pas besoin de file de jobs ici.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.data.store import DataStore
from patrick.tracking import db as trackdb
from patrick.webapp.app import app

TARGET = "^TEST"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))


@pytest.fixture
def seeded_run(tmp_path):
    db_path = str(tmp_path / "patrick.db")
    store_root = str(tmp_path / "store")
    n, horizon = 300, 5

    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.default_rng(0)
    price = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame({"IDX_TEST": price}, index=idx)
    store = DataStore(root=store_root)
    snapshot_id = store.save(f"raw_{TARGET}", df)

    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, snapshot_id, data_hash="x", n_tickers=0, n_fred_series=0, fred_source="api")
    run_id = "sim_web_run"
    trackdb.create_run(conn, run_id, target=TARGET, horizon=horizon, snapshot_id=snapshot_id,
                        config_json='{"name": "sim_web_run"}', config_hash="h", git_sha="s", seed=0)
    trial_id = trackdb.create_trial(conn, run_id, regime="GLOBAL", algo="X", sampler="none",
                                     n_features=1, selector="shap")
    trackdb.mark_best_trial(conn, trial_id)

    ts_list, y_pred_list, y_proba_list, y_true_list = [], [], [], []
    for i in range(20, n - horizon, horizon):
        fut_ret = price[i + horizon] / price[i] - 1
        up = fut_ret > 0
        ts_list.append(str(idx[i]))
        y_pred_list.append(3 if up else 0)
        y_proba_list.append(0.8)
        y_true_list.append(3 if up else 0)
    trackdb.add_predictions(conn, trial_id, fold_index=1, split="test", ts=ts_list,
                             y_true=y_true_list, y_pred=y_pred_list, y_proba=y_proba_list)
    trackdb.finish_run(conn, run_id, "done", n_trials=1)
    conn.close()
    return run_id, trial_id


def test_simulate_page_lists_done_run(seeded_run):
    run_id, _ = seeded_run
    client = TestClient(app)
    resp = client.get("/simulate")
    assert resp.status_code == 200
    assert run_id in resp.text


def test_api_list_trials_returns_best_trial(seeded_run):
    run_id, trial_id = seeded_run
    client = TestClient(app)
    resp = client.get(f"/api/runs/{run_id}/trials")
    assert resp.status_code == 200
    trials = resp.json()["trials"]
    assert len(trials) == 1
    assert trials[0]["trial_id"] == trial_id
    assert trials[0]["is_best"] is True


def test_api_simulate_end_to_end(seeded_run):
    run_id, trial_id = seeded_run
    client = TestClient(app)

    resp = client.post("/api/simulate", json={
        "trial_id": trial_id,
        "params": {"position_mode": "threshold", "threshold": 0.55, "asset_class": "us_large_cap"},
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert len(data["equity_curve"]) > 10
    assert "break_even_cost_bps" in data["strategy"]
    assert data["n_simulation_configs_on_target"] == 1
    simulation_id = data["simulation_id"]

    resp2 = client.get(f"/api/simulate/{simulation_id}")
    assert resp2.status_code == 200
    stored = resp2.json()
    assert stored["trial_id"] == trial_id
    assert stored["result"]["ok"] is True

    # une deuxième simulation sur la même cible incrémente le compteur
    # anti-surapprentissage (Phase 4.5) -- jamais caché.
    resp3 = client.post("/api/simulate", json={"trial_id": trial_id, "params": {}})
    assert resp3.json()["n_simulation_configs_on_target"] == 2


def test_api_simulate_unknown_trial_returns_404(seeded_run):
    client = TestClient(app)
    resp = client.post("/api/simulate", json={"trial_id": 999999, "params": {}})
    assert resp.status_code == 404
