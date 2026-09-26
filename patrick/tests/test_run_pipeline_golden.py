"""Golden master of `run_pipeline` -- the safety net of its refactor (532
lines split into phases). Captures EVERYTHING a run produces that does not
depend on wall-clock time or random identifiers: leaderboard, tuned rows,
final/best configs, holdout, Diebold-Mariano, PBO, cumulative trials, and the
full content of every table the run writes (trials, fold metrics,
predictions, registry, DM results, stability), plus the exported model's
predictions on a fixed matrix.

The golden file was generated BEFORE the refactor, from the post-F01..F07
code (`PATRICK_UPDATE_GOLDEN=1`); the refactored `run_pipeline` must
reproduce it bit for bit (floats compared after rounding to 10 decimals).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module
from patrick.tracking import db as trackdb

pytestmark = pytest.mark.slow

GOLDEN_DIR = Path(__file__).parent / "golden"


def _raw(n=1100, seed=7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-01", periods=n)
    df = pd.DataFrame({"IDX_GOLD": 100 + np.cumsum(rng.normal(0.02, 1, n))}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    return df


def _config(tmp_path, scheme: str) -> RunConfig:
    return RunConfig.model_validate({
        "name": f"golden_{scheme}",
        "objective": {"target_symbol": "^GOLD", "horizons": [3, 5], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI"}, "start_date": "2016-01-01"},
        "features": {"families": ["technical", "interactions", "spike", "vol_models", "macro"],
                     "vol_models": ["kalman"], "interact_top_base": 10, "interact_top_pairs": 5,
                     "interact_final_n": 4, "pool_prefilter": 40},
        "validation": {"scheme": scheme, "n_wf_folds": 3, "min_train_frac": 0.5, "holdout_months": 12,
                       "n_groups": 5, "k_test_groups": 2},
        "selection": {"method": "shap", "n_features_grid": [4, 6], "shap_sample": 80},
        "sampler": {"candidates": ["SMOTE", "none"]},
        "models": {"algos": ["XGBoost", "LightGBM"]},
        "tuning": {"enabled": scheme == "walkforward", "top_k": 1, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "out"), "seed": 42},
    })


def _norm(obj):
    if isinstance(obj, dict):
        return {str(k): _norm(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_norm(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        return None if not np.isfinite(obj) else round(float(obj), 10)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, pd.DataFrame):
        return _norm(obj.to_dict("records"))
    return obj


def _table(conn, sql: str) -> str:
    rows = [_norm(list(r)) for r in conn.execute(sql).fetchall()]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def _capture(result: dict, db_path: str, model_paths: dict) -> dict:
    conn = trackdb.connect(db_path)
    runs = {rid: h for rid, h in conn.execute("SELECT run_id, horizon FROM run")}
    run_key = "CASE " + " ".join(f"WHEN run.run_id = '{rid}' THEN 'h{h}'" for rid, h in runs.items()) + " END"
    tables = {
        "trial": _table(conn, f"SELECT {run_key}, trial.regime, trial.algo, trial.sampler, trial.n_features, "
                               "trial.selector, trial.params_json, trial.is_best, trial.category FROM trial JOIN run ON trial.run_id = run.run_id "
                               "ORDER BY trial.trial_id"),
        "fold_metric": _table(conn, "SELECT trial_id, fold_index, split, metric, value FROM fold_metric "
                                    "ORDER BY trial_id, fold_index, split, metric"),
        "prediction": _table(conn, "SELECT trial_id, ts, fold_index, split, y_true, y_pred, y_proba, path_id "
                                   "FROM prediction ORDER BY trial_id, ts, path_id, split"),
        "registry": _table(conn, f"SELECT {run_key}, trial_registry.source, trial_registry.n_trials FROM trial_registry "
                                 "JOIN run ON trial_registry.run_id = run.run_id ORDER BY trial_registry.registry_id"),
        "dm_result": _table(conn, f"SELECT {run_key}, dm_result.kind, dm_result.baseline, dm_result.dm_stat, dm_result.p_value "
                                  "FROM dm_result JOIN run ON dm_result.run_id = run.run_id ORDER BY 1, 2, 3"),
        "baseline_metric": _table(conn, f"SELECT {run_key}, baseline_metric.baseline, baseline_metric.split, baseline_metric.metric, "
                                        "baseline_metric.value FROM baseline_metric "
                                        "JOIN run ON baseline_metric.run_id = run.run_id ORDER BY 1, 2, 3, 4"),
        "feature_stability": _table(conn, f"SELECT {run_key}, feature_stability.feature, feature_stability.selection_freq "
                                          "FROM feature_stability JOIN run ON feature_stability.run_id = run.run_id "
                                          "ORDER BY 1, 2"),
        "holdout_diagnostic": _table(conn, "SELECT * FROM holdout_diagnostic ORDER BY 1, 2"),
        "phases": _table(conn, f"SELECT {run_key}, run_phase_timing.phase FROM run_phase_timing "
                               "JOIN run ON run_phase_timing.run_id = run.run_id "
                               "ORDER BY run_phase_timing.phase_timing_id"),
        "run_status": _table(conn, f"SELECT {run_key}, status, n_trials FROM run ORDER BY 1"),
    }
    conn.close()
    X = np.random.default_rng(0).normal(size=(12, 6))
    exported = {}
    for h, path in sorted(model_paths.items()):
        bundle = joblib.load(path)
        n = len(bundle["feature_names"])
        exported[f"h{h}"] = {"features": bundle["feature_names"],
                             "proba": _norm(bundle["model"].predict_proba(X[:, :n]).tolist())}
    keep = ("final_best", "best_before_tuning", "holdout", "diebold_mariano", "cumulative_trials",
            "pbo", "holdout_diagnostic")
    return {
        "result": _norm({k: result.get(k) for k in keep}),
        "leaderboard": hashlib.sha256(json.dumps(_norm(result["leaderboard"]), sort_keys=True).encode()).hexdigest(),
        "tuned": hashlib.sha256(json.dumps(_norm(result["tuned"]), sort_keys=True).encode()).hexdigest(),
        "tables": tables,
        "exported": exported,
    }


@pytest.mark.parametrize("scheme", ["walkforward", "cpcv"])
def test_run_pipeline_matches_its_golden_master(tmp_path, monkeypatch, scheme):
    raw = _raw()
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: raw.copy())
    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)
    db_path = str(tmp_path / "patrick.db")
    result = engine_module.run_pipeline(_config(tmp_path, scheme), store=DataStore(root=str(tmp_path / "s")),
                                        db_path=db_path)
    captured = _capture(result, db_path, result["model_paths"])
    golden_path = GOLDEN_DIR / f"run_pipeline_{scheme}.json"
    if os.environ.get("PATRICK_UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(exist_ok=True)
        golden_path.write_text(json.dumps(captured, indent=1, sort_keys=True))
        pytest.skip("golden master regenerated")
    golden = json.loads(golden_path.read_text())
    assert captured["result"] == golden["result"]
    assert captured["leaderboard"] == golden["leaderboard"]
    assert captured["tuned"] == golden["tuned"]
    assert captured["tables"] == golden["tables"]
    assert captured["exported"] == golden["exported"]
