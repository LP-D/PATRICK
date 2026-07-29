"""Test de fumée de l'interface web : le pipeline tourne pour de vrai, dans un
vrai `patrick worker` en process séparé (Phase 3.1) — pas de réseau : au lieu
de monkeypatcher `ingest()` (invisible pour un process séparé, qui ne partage
aucun état Python avec le process de test), on pré-remplit le cache disque du
`DataStore` avec la même donnée synthétique que `test_pipeline_smoke.py` ;
`ingest()` la retrouve normalement via son chemin de cache habituel, que ce
soit exécuté en process ou dans le worker séparé.

Chaque test isole sa propre base SQLite et son propre data lake sur
`tmp_path` via les variables d'environnement `PATRICK_DB_PATH`/
`PATRICK_STORE_ROOT` (lues à chaque appel, pas figées à l'import — cf.
`tracking.db.default_db_path`/`data.store._default_store_dir`), sans quoi
tous les tests partageraient la vraie base `~/.patrick/patrick.db`.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.data.store import DataStore
from patrick.webapp.app import app

TARGET_SYMBOL = "^VIX"


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
def _isolated_env(tmp_path, monkeypatch):
    """Base + data lake dédiés à ce test, et arrêt automatique rapide du
    worker séparé une fois la file vide (pas de process fantôme entre tests)."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    monkeypatch.setenv("PATRICK_WORKER_IDLE_TIMEOUT", "8")
    DataStore(root=str(tmp_path / "store")).save(f"raw_{TARGET_SYMBOL}", _synthetic_raw())


def _form_data(tmp_path) -> dict:
    return {
        "name": "smoke_web_test",
        "target_symbol": TARGET_SYMBOL,
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
        "optuna_trials_per_horizon": "on",
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


def _wait_for_status(client, run_id, *, not_in: set[str], deadline_s: float) -> dict:
    deadline = time.time() + deadline_s
    status = None
    while time.time() < deadline:
        status = client.get(f"/runs/{run_id}/status").json()
        if status["status"] not in not_in:
            return status
        time.sleep(0.5)
    assert status is not None, "aucune réponse du serveur"
    raise AssertionError(f"délai dépassé, statut encore {status['status']!r}: {status}")


def test_run_via_web_form_end_to_end(tmp_path):
    client = TestClient(app)
    resp = client.post("/runs", data=_form_data(tmp_path))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # `start_run` enfile désormais toujours en base ('queued') : la transition
    # vers 'running' est décidée par le worker séparé, jamais immédiate.
    assert body["status"] == "queued", body
    run_id = body["run_id"]

    status = _wait_for_status(client, run_id, not_in={"queued", "running"}, deadline_s=240)
    assert status["status"] == "done", status

    results = client.get(f"/runs/{run_id}/results").json()
    assert results["n_evaluations"] > 0
    assert results["final_best"] is not None
    assert "best_model" in results["artifacts"]
    assert "leaderboard_csv" in results["artifacts"]

    download = client.get(f"/runs/{run_id}/download/best_model")
    assert download.status_code == 200


def test_second_run_queues_then_auto_starts(tmp_path):
    """Un run soumis pendant qu'un autre tourne/attend n'est jamais rejeté
    (pas de 409) mais mis en file d'attente, puis démarré automatiquement dès
    que l'actif se termine (le worker séparé les traite un par un, FIFO)."""
    client = TestClient(app)

    form_a = _form_data(tmp_path)
    form_a["name"] = "run_a"
    form_a["output_dir"] = str(tmp_path / "runs_a")
    resp_a = client.post("/runs", data=form_a)
    assert resp_a.status_code == 200, resp_a.text
    run_a = resp_a.json()
    assert run_a["status"] == "queued"

    form_b = _form_data(tmp_path)
    form_b["name"] = "run_b"
    form_b["output_dir"] = str(tmp_path / "runs_b")
    resp_b = client.post("/runs", data=form_b)
    assert resp_b.status_code == 200, resp_b.text
    run_b = resp_b.json()
    assert run_b["status"] == "queued"

    # run_a doit être réclamé par le worker (unique) avant run_b : file FIFO.
    a_status = _wait_for_status(client, run_a["run_id"], not_in={"queued"}, deadline_s=90)
    assert a_status["status"] == "running", a_status

    state = client.get("/api/run-state").json()
    assert state["active_run"]["id"] == run_a["run_id"]
    assert [q["id"] for q in state["queue"]] == [run_b["run_id"]]

    b_status = _wait_for_status(client, run_b["run_id"], not_in={"queued"}, deadline_s=180)
    assert b_status["status"] in ("running", "done"), b_status
