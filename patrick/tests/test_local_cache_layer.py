"""Local cache layer ported from feature/replay-cache-universe (7373b4f): SHAP
explanations of recorded predictions persisted in SQLite (additive schema,
outside `migrate()`), keyed by (trial, prediction date, data snapshot, code).

Not ported, on purpose:
- `features/feature_cache.py` (full pool keyed by snapshot + a hand-bumped
  FEATURE_CACHE_VERSION): superseded on main by `features/pool_cache.py`,
  whose key folds in a hash of the feature source code;
- `data/series_store.py` (per-series Parquet written at every ingestion):
  nothing reads it -- it would double the data lake's disk growth for no use.

Every test below was checked against a mutant (see the commit message).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.tracking import cache_tables
from patrick.tracking import db as trackdb


def _config() -> RunConfig:
    return RunConfig.model_validate({
        "name": "cache_test",
        "objective": {"target_symbol": "^TEST", "horizons": [5]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI"}},
    })


def _trial(conn) -> int:
    trackdb.upsert_snapshot(conn, "snapA", "h", 1, 1, "api")
    trackdb.create_run(conn, "r1", target="^TEST", horizon=5, snapshot_id="snapA",
                       config_json="{}", config_hash="x", git_sha="x", seed=1)
    with conn:
        cur = conn.execute("INSERT INTO trial (run_id, regime, algo, sampler, n_features, selector, params_json) "
                           "VALUES ('r1', 'GLOBAL', 'XGBoost', 'SMOTE', 5, 'shap', '{}')")
    return cur.lastrowid


def test_shap_cache_roundtrip_and_snapshot_isolation(conn):
    trial_id = _trial(conn)
    assert cache_tables.get_cached_shap(conn, trial_id, "2026-01-02", "snapA", "c1") is None
    payload = {"base_value": 0.1, "contributions": [{"name": "f", "value": 1.0, "shap": 0.2}]}
    cache_tables.save_cached_shap(conn, trial_id, "2026-01-02", "snapA", "c1", payload)
    assert cache_tables.get_cached_shap(conn, trial_id, "2026-01-02", "snapA", "c1") == payload
    assert cache_tables.get_cached_shap(conn, trial_id, "2026-01-02", "snapB", "c1") is None
    assert cache_tables.get_cached_shap(conn, trial_id, "2026-01-03", "snapA", "c1") is None


def test_shap_cache_is_invalidated_by_a_code_change(conn):
    trial_id = _trial(conn)
    cache_tables.save_cached_shap(conn, trial_id, "2026-01-02", "snapA", "old_code", {"x": 1})
    assert cache_tables.get_cached_shap(conn, trial_id, "2026-01-02", "snapA", "new_code") is None


def test_cache_schema_is_additive_and_leaves_schema_version_untouched(conn):
    before = conn.execute("SELECT COUNT(*), MAX(version) FROM schema_version").fetchone()
    cache_tables.ensure_cache_schema(conn)
    cache_tables.ensure_cache_schema(conn)  # idempotent
    after = conn.execute("SELECT COUNT(*), MAX(version) FROM schema_version").fetchone()
    assert before == after


def test_shap_cache_rows_cascade_with_their_trial(conn):
    trial_id = _trial(conn)
    cache_tables.save_cached_shap(conn, trial_id, "2026-01-02", "snapA", "c1", {"x": 1})
    with conn:
        conn.execute("DELETE FROM trial WHERE trial_id = ?", (trial_id,))
    assert conn.execute("SELECT COUNT(*) FROM shap_explanation_cache").fetchone()[0] == 0


def _patch_explain(monkeypatch, explain_module, trial_id, raw):
    monkeypatch.setattr(explain_module, "_find_best_trial_for_horizon",
                        lambda c, t, h: {"run_id": "r1", "trial_id": trial_id, "artifact_path": "x"})
    monkeypatch.setattr(explain_module.trackdb, "latest_prediction_for_trial",
                        lambda c, tid: {"ts": "2020-01-10", "y_pred": 1, "split": "test", "y_proba": 0.5})
    monkeypatch.setattr(explain_module.joblib, "load", lambda p: {
        "model": None, "scaler": None, "feature_pool": [], "feature_names": [], "target_col": "IDX_TEST"})
    monkeypatch.setattr(explain_module.trackdb, "get_run",
                        lambda c, rid: {"config_json": _config().model_dump_json(), "snapshot_id": "snapA"})
    monkeypatch.setattr(explain_module, "_load_snapshot_for_prediction", lambda *a, **k: raw)


def _raw_with_snapshot(snapshot_id: str) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=50)
    raw = pd.DataFrame({"IDX_TEST": np.arange(50, dtype=float), "NFCI": np.linspace(0, 1, 50)}, index=idx)
    raw.attrs["snapshot_id"] = snapshot_id
    return raw


def test_explain_uses_shap_cache_on_second_call(tmp_path, monkeypatch):
    """Second page open for the same (trial, ts, snapshot, code) returns the
    persisted explanation without rebuilding the feature pool."""
    from patrick import explain as explain_module

    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    trial_id = _trial(conn)
    cache_tables.save_cached_shap(conn, trial_id, "2020-01-10", "snapA",
                                  explain_module.EXPLANATION_CODE_HASH, {"cached": True})
    conn.close()
    _patch_explain(monkeypatch, explain_module, trial_id, _raw_with_snapshot("snapA"))
    monkeypatch.setattr(explain_module, "build_full_feature_pool",
                        lambda *a, **k: pytest.fail("feature pool must not be rebuilt on a SHAP cache hit"))
    assert explain_module.explain_last_prediction("^TEST", 5, db_path=db_path) == {"cached": True}


def test_explain_ignores_a_payload_cached_for_another_snapshot(tmp_path, monkeypatch):
    from patrick import explain as explain_module

    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    trial_id = _trial(conn)
    cache_tables.save_cached_shap(conn, trial_id, "2020-01-10", "snapA",
                                  explain_module.EXPLANATION_CODE_HASH, {"cached": True})
    conn.close()
    _patch_explain(monkeypatch, explain_module, trial_id, _raw_with_snapshot("snapB"))
    rebuilt = []

    def fake_pool(*a, **k):
        rebuilt.append(True)
        return pd.DataFrame()                     # empty pool -> explain returns None after the rebuild

    monkeypatch.setattr(explain_module, "build_full_feature_pool", fake_pool)
    assert explain_module.explain_last_prediction("^TEST", 5, db_path=db_path) is None
    assert rebuilt == [True]


def test_explanation_code_hash_covers_the_feature_code():
    from patrick import explain as explain_module
    from patrick.features import pool_cache

    assert explain_module._explanation_code_hash() == explain_module.EXPLANATION_CODE_HASH
    original = pool_cache.FEATURE_CODE_HASH
    try:
        explain_module.FEATURE_CODE_HASH = "different"
        assert explain_module._explanation_code_hash() != explain_module.EXPLANATION_CODE_HASH
    finally:
        explain_module.FEATURE_CODE_HASH = original
