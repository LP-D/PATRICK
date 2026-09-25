"""`explain.py` must rebuild the feature row from the data snapshot the
explained prediction was actually computed on -- never from "whatever the
data lake holds last" (same defect as the one fixed for `/simulate`, which
already loads `run.snapshot_id`).

Before the fix, `explain_last_prediction` called `ingest(force=False)`,
which returns the LATEST snapshot stored under `raw_<target>`: once a newer
ingestion (revised FRED values, Yahoo dividend/split adjustments) has been
saved, a historical test/holdout prediction was explained with features the
model never saw. And on a cold data lake, `ingest` silently fell through to
a network download.
"""
from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
import pytest

from patrick import explain as explain_module
from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.tracking import db as trackdb

TARGET = "^SNAP"
KEY = f"raw_{TARGET}"


class _Captured(Exception):
    pass


def _frame(end: str, level: float) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", end)
    return pd.DataFrame({"IDX_SNAP": np.linspace(level, level + 10, len(idx))}, index=idx)


def _setup(tmp_path, prediction_ts: str, split: str):
    store = DataStore(root=str(tmp_path / "store"))
    snap_a = store.save(KEY, _frame("2021-06-30", 100.0))
    store.save(KEY, _frame("2021-12-31", 500.0))

    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    config = RunConfig.model_validate({"objective": {"target_symbol": TARGET, "horizons": [1]}})
    trackdb.upsert_snapshot(conn, snap_a, "hash", 0, 0, None)
    trackdb.create_run(conn, "r1", target=TARGET, horizon=1, snapshot_id=snap_a,
                        config_json=config.model_dump_json(), config_hash="h", git_sha="g", seed=42)
    trackdb.finish_run(conn, "r1", status="done")
    tid = trackdb.create_trial(conn, "r1", "GLOBAL", "XGBoost", "SMOTE", 1, "shap")
    artifact = tmp_path / "bundle.joblib"
    joblib.dump({"model": None, "scaler": None, "feature_pool": [], "feature_names": [],
                 "target_col": "IDX_SNAP"}, artifact)
    trackdb.mark_best_trial(conn, tid, artifact_path=str(artifact))
    trackdb.add_predictions(conn, tid, fold_index=1, split=split, ts=[prediction_ts],
                             y_true=[1], y_pred=[2], y_proba=[0.6])
    conn.close()
    return store, db_path, snap_a


def _capture_raw(monkeypatch):
    seen = {}

    def _spy(raw, config, target_col, interaction_formulas=None):
        seen["raw"] = raw
        raise _Captured

    monkeypatch.setattr(explain_module, "build_full_feature_pool", _spy)
    monkeypatch.setattr(explain_module, "ingest",
                        lambda *a, **k: pytest.fail("explain must never call ingest()"), raising=False)
    return seen


def test_historical_prediction_is_explained_on_the_run_snapshot(tmp_path, monkeypatch):
    store, db_path, snap_a = _setup(tmp_path, "2021-03-01", "test")
    seen = _capture_raw(monkeypatch)
    with pytest.raises(_Captured):
        explain_module.explain_last_prediction(TARGET, 1, db_path=db_path, store=store)
    assert seen["raw"].attrs["snapshot_id"] == snap_a
    assert seen["raw"].index.max() == pd.Timestamp("2021-06-30")


def test_live_prediction_after_the_run_snapshot_uses_the_earliest_snapshot_covering_it(tmp_path, monkeypatch):
    store, db_path, snap_a = _setup(tmp_path, "2021-09-01", "live")
    seen = _capture_raw(monkeypatch)
    with pytest.raises(_Captured):
        explain_module.explain_last_prediction(TARGET, 1, db_path=db_path, store=store)
    assert seen["raw"].attrs["snapshot_id"] != snap_a
    assert seen["raw"].index.max() == pd.Timestamp("2021-12-31")


def test_missing_snapshot_returns_none_instead_of_downloading(tmp_path, monkeypatch):
    store, db_path, _ = _setup(tmp_path, "2021-03-01", "test")
    empty_store = DataStore(root=str(tmp_path / "empty_store"))
    _capture_raw(monkeypatch)
    assert explain_module.explain_last_prediction(TARGET, 1, db_path=db_path, store=empty_store) is None
