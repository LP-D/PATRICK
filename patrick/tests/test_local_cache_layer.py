"""Local data/cache layer: per-series Parquet (ticker, vintage), SHAP
explanations persisted in SQLite (additive schema, outside `migrate()`),
versioned feature cache keyed by (snapshot_id, hash(config_features))."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.series_store import SeriesStore
from patrick.features.feature_cache import FeatureCache, feature_config_hash
from patrick.tracking import cache_tables
from patrick.tracking import db as trackdb


def _config(**features) -> RunConfig:
    return RunConfig.model_validate({
        "name": "cache_test",
        "objective": {"target_symbol": "^TEST", "horizons": [5]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI"}},
        "features": features,
    })


def _raw() -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=50)
    return pd.DataFrame({"IDX_TEST": np.arange(50, dtype=float), "NFCI": np.linspace(0, 1, 50)}, index=idx)


class _SpyBuilder:
    def __init__(self):
        self.calls = 0

    def __call__(self, raw, config, target_col, interaction_formulas):
        self.calls += 1
        out = raw.copy()
        out["feat_int"] = np.arange(len(raw), dtype=np.int64)
        return out


# --- feature cache ---------------------------------------------------------

def test_feature_cache_hit_does_not_recompute(tmp_path):
    cache, spy, cfg, raw = FeatureCache(root=str(tmp_path)), _SpyBuilder(), _config(), _raw()
    first = cache.get_or_build(raw, cfg, "IDX_TEST", ["a*b"], "snapA", spy)
    second = cache.get_or_build(raw, cfg, "IDX_TEST", ["a*b"], "snapA", spy)
    assert spy.calls == 1
    pd.testing.assert_frame_equal(first, second, check_freq=False)


def test_feature_cache_invalidated_by_feature_config_change(tmp_path):
    cache, spy, raw = FeatureCache(root=str(tmp_path)), _SpyBuilder(), _raw()
    cache.get_or_build(raw, _config(), "IDX_TEST", [], "snapA", spy)
    cache.get_or_build(raw, _config(enable_guida_features=True), "IDX_TEST", [], "snapA", spy)
    cache.get_or_build(raw, _config(technical_lookbacks={"zscore_windows": [7]}), "IDX_TEST", [], "snapA", spy)
    cache.get_or_build(raw, _config(technical_lookbacks={"ma_ratio_windows": [9]}), "IDX_TEST", [], "snapA", spy)
    assert spy.calls == 4  # same snapshot, 4 distinct feature configs -> 4 builds, no stale reuse


def test_feature_cache_invalidated_by_snapshot_and_formulas(tmp_path):
    cache, spy, cfg, raw = FeatureCache(root=str(tmp_path)), _SpyBuilder(), _config(), _raw()
    cache.get_or_build(raw, cfg, "IDX_TEST", [], "snapA", spy)
    cache.get_or_build(raw, cfg, "IDX_TEST", [], "snapB", spy)
    cache.get_or_build(raw, cfg, "IDX_TEST", ["x*y"], "snapA", spy)
    assert spy.calls == 3


def test_feature_hash_ignores_non_feature_parameters():
    base = _config()
    other = base.model_copy(deep=True)
    other.tuning.n_trials = base.tuning.n_trials + 7
    other.features.pool_prefilter = base.features.pool_prefilter + 1
    assert feature_config_hash(base) == feature_config_hash(other)


# --- per-series Parquet ----------------------------------------------------

def test_series_store_parquet_roundtrip_preserves_dtypes(tmp_path):
    store = SeriesStore(root=str(tmp_path))
    idx = pd.date_range("2021-01-01", periods=10, freq="B", name="Date")
    frame = pd.DataFrame({
        "^VIX": np.linspace(10, 20, 10).astype("float64"),
        "COUNT": np.arange(10, dtype="int64"),
        "RATE": np.linspace(0, 1, 10).astype("float32"),
    }, index=idx)
    assert store.save_frame(frame, vintage="2026-09-22__raw_IDX_VIX__abc") == 3
    for col in frame.columns:
        back = store.load(col, "2026-09-22__raw_IDX_VIX__abc")
        assert back.dtype == frame[col].dtype
        assert isinstance(back.index, pd.DatetimeIndex)
        pd.testing.assert_series_equal(back, frame[col], check_freq=False, check_names=False)
    assert store.list_vintages("^VIX") == ["2026-09-22__raw_IDX_VIX__abc"]


def test_series_store_is_immutable_per_vintage(tmp_path):
    store = SeriesStore(root=str(tmp_path))
    s = pd.Series([1.0, 2.0], index=pd.bdate_range("2021-01-01", periods=2))
    store.save("NFCI", "v1", s)
    store.save("NFCI", "v1", s * 100)  # never overwrites an existing vintage
    store.save("NFCI", "v2", s * 100)
    assert store.load("NFCI", "v1").tolist() == [1.0, 2.0]
    assert store.load("NFCI", "v2").tolist() == [100.0, 200.0]


def test_feature_cache_parquet_roundtrip_preserves_dtypes(tmp_path):
    cache, spy, cfg, raw = FeatureCache(root=str(tmp_path)), _SpyBuilder(), _config(), _raw()
    built = cache.get_or_build(raw, cfg, "IDX_TEST", [], "snapA", spy)
    reloaded = cache.load("snapA", feature_config_hash(cfg, []))
    assert dict(reloaded.dtypes) == dict(built.dtypes)
    pd.testing.assert_frame_equal(reloaded, built, check_freq=False)


# --- SHAP explanations in SQLite -------------------------------------------

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
    assert cache_tables.get_cached_shap(conn, trial_id, "2026-01-02", "snapA") is None
    payload = {"base_value": 0.1, "contributions": [{"name": "f", "value": 1.0, "shap": 0.2}]}
    cache_tables.save_cached_shap(conn, trial_id, "2026-01-02", "snapA", payload)
    assert cache_tables.get_cached_shap(conn, trial_id, "2026-01-02", "snapA") == payload
    assert cache_tables.get_cached_shap(conn, trial_id, "2026-01-02", "snapB") is None


def test_cache_schema_is_additive_and_leaves_schema_version_untouched(conn):
    before = conn.execute("SELECT COUNT(*), MAX(version) FROM schema_version").fetchone()
    cache_tables.ensure_cache_schema(conn)
    cache_tables.ensure_cache_schema(conn)  # idempotent
    after = conn.execute("SELECT COUNT(*), MAX(version) FROM schema_version").fetchone()
    assert before == after


def test_shap_cache_rows_cascade_with_their_trial(conn):
    trial_id = _trial(conn)
    cache_tables.save_cached_shap(conn, trial_id, "2026-01-02", "snapA", {"x": 1})
    with conn:
        conn.execute("DELETE FROM trial WHERE trial_id = ?", (trial_id,))
    assert conn.execute("SELECT COUNT(*) FROM shap_explanation_cache").fetchone()[0] == 0


def test_explain_uses_shap_cache_on_second_call(tmp_path, monkeypatch):
    """Second page open for the same (trial, ts, snapshot) returns the
    persisted explanation without rebuilding the feature pool."""
    from patrick import explain as explain_module

    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    trial_id = _trial(conn)
    conn.close()
    monkeypatch.setattr(explain_module, "_find_best_trial_for_horizon",
                        lambda c, t, h: {"run_id": "r1", "trial_id": trial_id, "artifact_path": "x"})
    monkeypatch.setattr(explain_module.trackdb, "latest_prediction_for_trial",
                        lambda c, tid: {"ts": "2020-01-10", "y_pred": 1, "split": "test", "y_proba": 0.5})
    monkeypatch.setattr(explain_module.joblib, "load", lambda p: {
        "model": None, "scaler": None, "feature_pool": [], "feature_names": [], "target_col": "IDX_TEST"})
    monkeypatch.setattr(explain_module.trackdb, "get_run",
                        lambda c, rid: {"config_json": _config().model_dump_json()})
    raw = _raw()
    raw.attrs["snapshot_id"] = "snapA"
    monkeypatch.setattr(explain_module, "ingest", lambda *a, **k: raw)
    conn = trackdb.connect(db_path)
    cache_tables.save_cached_shap(conn, trial_id, "2020-01-10", "snapA", {"cached": True})
    conn.close()
    monkeypatch.setattr(explain_module, "_cached_full_pool",
                        lambda *a, **k: pytest.fail("feature pool must not be rebuilt on a SHAP cache hit"))
    assert explain_module.explain_last_prediction("^TEST", 5, db_path=db_path) == {"cached": True}
