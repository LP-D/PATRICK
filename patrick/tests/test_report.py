"""Critère de sortie Phase 3.3 : `patrick report` génère un export HTML d'un
run à partir de la seule base SQLite (config, essais, baselines,
reproductibilité — et validité statistique Phase 2 quand le run vient d'un
job web, cf. `run.job_id`)."""
from __future__ import annotations

import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db
from patrick.tracking import report as report_module
from patrick import worker as worker_module

# Rapport de correction, D1 : les deux tests de ce fichier lancent un run
# pipeline complet (73s/70s mesurés) -- exclus par défaut, cf. pyproject.toml.
pytestmark = pytest.mark.slow

TARGET_SYMBOL = "^TEST"


def _synthetic_raw_no_floor(n=1500, seed=0) -> pd.DataFrame:
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
        "name": "report_test",
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


def test_report_for_cli_run_without_job_id(tmp_path, monkeypatch):
    """Un run lancé en CLI (`patrick run`) n'a pas de `job_id` -> le rapport
    l'indique clairement plutôt que d'afficher des chiffres inventés."""
    def fake_ingest(objective, universe, store=None, force=False, data_quality=None):
        return _synthetic_raw_no_floor()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)
    db_path = str(tmp_path / "patrick.db")

    engine_module.run_pipeline(
        _tiny_config(tmp_path), store=DataStore(root=str(tmp_path / "store")), db_path=db_path)

    conn = sqlite3.connect(db_path)
    run_id = conn.execute("SELECT run_id FROM run LIMIT 1").fetchone()[0]
    conn.close()

    output_path = str(tmp_path / "report.html")
    result_path = report_module.save_report(run_id, output_path=output_path, db_path=db_path)
    assert result_path == output_path

    content = open(output_path, encoding="utf-8").read()
    assert run_id in content
    assert "report_test" in content
    assert "Non disponible" in content  # pas de job_id -> stats Phase 2 absentes, pas inventées
    assert "<table" in content
    # Rapport d'audit, C4 : contrairement à holdout/DM/PBO (job-scopés
    # ci-dessus), le diagnostic test-vs-holdout est lu directement en base --
    # disponible même pour un run CLI sans job_id.
    assert "corrélation de rang test vs holdout" in content


def test_report_for_web_run_includes_phase2_stats(tmp_path):
    """Un run lancé via un job (interface web) a un `job_id` -> le rapport
    inclut holdout/DM/PBO/essais cumulés, persistés dans `job.result_json`."""
    db_path = str(tmp_path / "patrick.db")
    store_root = str(tmp_path / "store")
    DataStore(root=store_root).save(f"raw_{TARGET_SYMBOL}", _synthetic_raw_no_floor())

    import os
    os.environ["PATRICK_DB_PATH"] = db_path
    os.environ["PATRICK_STORE_ROOT"] = store_root
    try:
        conn = trackdb.connect(db_path)
        job_id = jobs_db.enqueue_job(conn, _tiny_config(tmp_path).model_dump_json())
        conn.close()

        worker_module.run_worker_loop(poll_interval=0.2, idle_timeout=2.0)

        conn = sqlite3.connect(db_path)
        job = conn.execute("SELECT status FROM job WHERE job_id = ?", (job_id,)).fetchone()
        assert job is not None and job[0] == "done"
        run_id = conn.execute("SELECT run_id FROM run WHERE job_id = ?", (job_id,)).fetchone()[0]
        conn.close()

        output_path = str(tmp_path / "report_web.html")
        report_module.save_report(run_id, output_path=output_path, db_path=db_path)
        content = open(output_path, encoding="utf-8").read()
        assert "Diebold-Mariano" in content
        assert "Essais cumulés" in content
        assert "Non disponible" not in content
    finally:
        del os.environ["PATRICK_DB_PATH"]
        del os.environ["PATRICK_STORE_ROOT"]
