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
from patrick.webapp import forms, run_manager
from patrick.webapp.app import app

# Rapport de correction, D1 : les deux tests lancent un run pipeline complet
# via un vrai worker séparé (~50s chacun mesurés) -- exclus par défaut,
# cf. pyproject.toml.
pytestmark = pytest.mark.slow

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
        "target_symbols": [TARGET_SYMBOL],
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
        "optuna_select_top_k_per_horizon": "on",
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
    assert len(body["runs"]) == 1, body
    run = body["runs"][0]
    # `start_run` enfile désormais toujours en base ('queued') : la transition
    # vers 'running' est décidée par le worker séparé, jamais immédiate.
    assert run["status"] == "queued", run
    run_id = run["run_id"]

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
    form_a["output_dir"] = str(tmp_path / "runs_a")
    resp_a = client.post("/runs", data=form_a)
    assert resp_a.status_code == 200, resp_a.text
    run_a = resp_a.json()["runs"][0]
    assert run_a["status"] == "queued"

    form_b = _form_data(tmp_path)
    form_b["output_dir"] = str(tmp_path / "runs_b")
    resp_b = client.post("/runs", data=form_b)
    assert resp_b.status_code == 200, resp_b.text
    run_b = resp_b.json()["runs"][0]
    assert run_b["status"] == "queued"

    # run_a doit être réclamé par le worker (unique) avant run_b : file FIFO.
    a_status = _wait_for_status(client, run_a["run_id"], not_in={"queued"}, deadline_s=90)
    assert a_status["status"] == "running", a_status

    state = client.get("/api/run-state").json()
    assert state["active_run"]["id"] == run_a["run_id"]
    assert [q["id"] for q in state["queue"]] == [run_b["run_id"]]

    b_status = _wait_for_status(client, run_b["run_id"], not_in={"queued"}, deadline_s=180)
    assert b_status["status"] in ("running", "done"), b_status


def test_batch_submit_queues_one_job_per_target(tmp_path):
    """Sélectionner plusieurs cibles dans le formulaire enfile un job par
    cible, chacun avec un nom/dossier de sortie distinct -- pas de nouvel
    orchestrateur, juste plusieurs jobs pour la même queue FIFO.

    Soumet aussi un `output_dir` explicite : c'est la seule combinaison qui
    exerce le garde-fou anti-collision de `create_run`
    (`len(targets) > 1 and raw_output_dir`) -- sans elle, un dossier partagé
    entre plusieurs cibles écraserait leurs artefacts les uns les autres, et
    rien ne le détecterait."""
    DataStore(root=str(tmp_path / "store")).save("raw_^AORD", _synthetic_raw(seed=1))
    client = TestClient(app)

    base_output_dir = str(tmp_path / "shared_runs")
    form = _form_data(tmp_path)
    form["target_symbols"] = [TARGET_SYMBOL, "^AORD"]
    form["output_dir"] = base_output_dir
    resp = client.post("/runs", data=form)
    assert resp.status_code == 200, resp.text
    runs = resp.json()["runs"]

    assert len(runs) == 2
    assert {r["target"] for r in runs} == {TARGET_SYMBOL, "^AORD"}
    assert len({r["run_id"] for r in runs}) == 2

    # Chaque job existe bien côté serveur, dans un état actif légitime, avec
    # un nom distinct dérivé de SA cible -- pas seulement "la réponse HTTP
    # avait 2 entrées" (assertion trop faible pour détecter un job perdu ou
    # mal routé).
    output_dirs = set()
    for r in runs:
        status = client.get(f"/runs/{r['run_id']}/status").json()
        assert status["status"] in ("queued", "running"), status
        assert status["name"].startswith(forms.slug_target(r["target"])), status

        # Le dossier de sortie réellement persisté (config du job, pas
        # simplement la réponse HTTP) doit être suffixé par le nom généré de
        # CE job, sous le dossier partagé soumis dans le formulaire -- et
        # donc distinct de celui de l'autre cible.
        config = run_manager.get_run_config(r["run_id"])
        expected_dir = f"{base_output_dir}/{status['name']}"
        assert config.output.dir == expected_dir, config.output.dir
        output_dirs.add(config.output.dir)

    assert len(output_dirs) == 2


def test_relaunch_reuses_config_with_fresh_name(tmp_path):
    client = TestClient(app)
    resp = client.post("/runs", data=_form_data(tmp_path))
    run_id = resp.json()["runs"][0]["run_id"]
    _wait_for_status(client, run_id, not_in={"queued", "running"}, deadline_s=240)

    relaunch_resp = client.post(f"/runs/{run_id}/relaunch", follow_redirects=False)
    assert relaunch_resp.status_code == 303, relaunch_resp.text
    new_run_id = relaunch_resp.headers["location"].rsplit("/", 1)[-1]
    assert new_run_id != run_id

    old_config = run_manager.get_run_config(run_id)
    new_config = run_manager.get_run_config(new_run_id)
    assert new_config.objective.target_symbol == old_config.objective.target_symbol
    assert new_config.objective.horizons == old_config.objective.horizons
    assert new_config.name != old_config.name
    assert new_config.name.startswith(forms.slug_target(old_config.objective.target_symbol))


def test_relaunch_404_on_unknown_run():
    client = TestClient(app)
    resp = client.post("/runs/does-not-exist/relaunch")
    assert resp.status_code == 404
