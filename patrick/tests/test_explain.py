"""Phase 7 (feature/shap-waterfall) -- `explain.explain_last_prediction`
explains the most recently RECORDED prediction (from the `prediction` table,
whatever its split) of a (target, horizon) with SHAP values computed on the
REAL exported model -- never on the throwaway pilot model used during
feature selection (`selection/shap_select.py`), and never a freshly-forced
live inference (that's `predict.py`'s job): see module docstring for the
full rationale and `docs/PHASE7_SHAP_FEASIBILITY.md` for the measured cost
that justifies computing this on demand rather than precomputing/caching.

Structure mirrors `test_predict_live.py`: a real (tiny) `run_pipeline`,
`ingest` monkeypatched to synthetic data so the test needs no network.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest

from patrick import explain as explain_module
from patrick.config.schema import RunConfig
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module

TARGET_SYMBOL = "^TEST_SHAP"
HORIZON = 5
# `run_pipeline` derives the target's raw column name via
# `clean_symbol(target_symbol)` ("^" -> "IDX_") -- the synthetic frame below
# must use that exact name, not an arbitrary one, or feature-pool
# construction can't find its own target column.
TARGET_COL = clean_symbol(TARGET_SYMBOL)


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({TARGET_COL: target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _tiny_config(tmp_path) -> RunConfig:
    raw_yaml = {
        "name": "explain_test",
        "objective": {"target_symbol": TARGET_SYMBOL, "horizons": [HORIZON], "regimes": ["GLOBAL"]},
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
        "tuning": {"enabled": False, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


@pytest.mark.slow  # full pipeline run, same order of magnitude as test_predict_live.py
def test_explain_last_prediction_is_internally_consistent(tmp_path, monkeypatch):
    raw = _synthetic_raw()
    monkeypatch.setattr(
        engine_module, "ingest",
        lambda objective, universe, store=None, force=False, data_quality=None: raw)

    db_path = str(tmp_path / "patrick.db")
    store = DataStore(root=str(tmp_path / "store"))
    result = engine_module.run_pipeline(_tiny_config(tmp_path), store=store, db_path=db_path)
    assert result["model_path"] is not None

    # explain.py must reconstruct the SAME historical raw series it was
    # trained on to find the exact date of the most recent recorded
    # prediction -- no network call needed (force=False), the point of this
    # module vs. `predict.py`'s live inference.
    monkeypatch.setattr(explain_module, "ingest", lambda objective, universe, store=None, data_quality=None: raw)

    out = explain_module.explain_last_prediction(TARGET_SYMBOL, HORIZON, db_path=db_path, store=store)
    assert out is not None

    assert out["y_pred"] in (0, 1, 2, 3)
    assert out["y_pred_label"] in explain_module.CLASS_NAMES
    assert out["n_features_total"] == len(out["contributions"])
    assert out["n_features_total"] > 0

    # Sorted by |shap| descending.
    abs_shaps = [abs(c["shap"]) for c in out["contributions"]]
    assert abs_shaps == sorted(abs_shaps, reverse=True)

    # Additivity: base + sum(all contributions) == final (this only holds
    # because ALL selected features are returned, never a truncated top-N).
    total = out["base_value"] + sum(c["shap"] for c in out["contributions"])
    assert total == pytest.approx(out["final_value"], abs=1e-6)

    # The explained prediction must actually be on record in the DB.
    conn = sqlite3.connect(db_path)
    run_id = conn.execute("SELECT run_id FROM run WHERE target = ? AND horizon = ?",
                           (TARGET_SYMBOL, HORIZON)).fetchone()[0]
    trial_id = conn.execute("SELECT trial_id FROM trial WHERE run_id = ? AND is_best = 1",
                             (run_id,)).fetchone()[0]
    row = conn.execute("SELECT ts, y_pred FROM prediction WHERE trial_id = ? ORDER BY ts DESC LIMIT 1",
                        (trial_id,)).fetchone()
    conn.close()
    assert row is not None
    assert str(pd.Timestamp(row[0]).date()) == out["ts"]
    assert int(row[1]) == out["y_pred"]


def test_explain_last_prediction_returns_none_for_unknown_target(tmp_path):
    out = explain_module.explain_last_prediction("no-such-target", 5, db_path=str(tmp_path / "patrick.db"))
    assert out is None
