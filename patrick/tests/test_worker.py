"""Critère de sortie Phase 3.1 : tuer le process web pendant un run ne perd
pas le run — le worker (`patrick/worker.py`), process séparé qui ne parle au
process web qu'à travers la table `job` (SQLite), le termine tout seul.

Vérifié ici sans jamais démarrer de process web/FastAPI/TestClient : un job
est enfilé directement en base, puis un vrai `patrick worker` (process séparé,
`subprocess.Popen`, pas un thread ni un appel de fonction en process) le
réclame et le termine — la seule chose partagée entre "web" et "worker" est le
fichier SQLite, jamais un objet en mémoire.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db
from patrick import worker as worker_module

# Rapport de correction, D1 : les deux tests lancent un vrai sous-processus
# `patrick worker` (76s/69s mesurés) -- exclus par défaut, cf. pyproject.toml.
pytestmark = pytest.mark.slow

TARGET_SYMBOL = "^TEST"


def _synthetic_raw_no_floor(n=1500, seed=0) -> pd.DataFrame:
    """Cf. `test_pipeline_smoke.py::_synthetic_raw_no_floor` — sans le
    `.clip(min=-10)` qui fige la cible sur un plancher pendant de longues
    séries et casse le filtre `flat_thr`."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _tiny_config(tmp_path) -> RunConfig:
    raw_yaml = {
        "name": "worker_test",
        "objective": {"target_symbol": TARGET_SYMBOL, "horizons": [5], "regimes": ["GLOBAL"]},
        "universe": {
            "yf_tickers": ["SPX_LIKE"],
            "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
            "start_date": "2015-01-01",
        },
        "features": {
            "families": ["technical", "interactions", "spike", "vol_models", "macro"],
            "interact_top_base": 15, "interact_top_pairs": 8, "interact_final_n": 6,
            "pool_prefilter": 60,
        },
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": True, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    DataStore(root=str(tmp_path / "store")).save(f"raw_{TARGET_SYMBOL}", _synthetic_raw_no_floor())


def test_run_worker_loop_finishes_job_without_any_web_process(tmp_path):
    """La boucle du worker (appelée directement ici, dans CE process, mais
    sans qu'aucun code web/FastAPI n'existe ou ne tourne à un moment
    quelconque du test) traite un job enfilé en base et écrit son résultat —
    prouve que l'exécution ne dépend en rien d'un process web vivant."""
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    job_id = jobs_db.enqueue_job(conn, _tiny_config(tmp_path).model_dump_json())
    conn.close()

    worker_module.run_worker_loop(poll_interval=0.2, idle_timeout=2.0)

    conn = trackdb.connect(db_path)
    job = jobs_db.get_job(conn, job_id)
    conn.close()
    assert job["status"] == "done", job
    result = json.loads(job["result_json"])
    assert result["final_best"] is not None
    assert result["n_evaluations"] > 0


def test_real_worker_subprocess_survives_without_web_server(tmp_path):
    """Comme ci-dessus mais avec un vrai `patrick worker` en process séparé
    (`subprocess.Popen`, exactement ce que lance `run_manager.
    ensure_worker_running` en production) : le job termine alors même
    qu'aucun process web n'a jamais existé pendant toute la durée du run, pas
    seulement "pas appelé" — un process OS distinct, qui ne connaît le job que
    via le fichier SQLite partagé."""
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    job_id = jobs_db.enqueue_job(conn, _tiny_config(tmp_path).model_dump_json())
    conn.close()

    proc = subprocess.run(
        [sys.executable, "-m", "patrick.cli", "worker", "--idle-timeout", "2", "--poll-interval", "0.2"],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    conn = trackdb.connect(db_path)
    job = jobs_db.get_job(conn, job_id)
    conn.close()
    assert job["status"] == "done", (job, proc.stdout, proc.stderr)
