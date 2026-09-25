"""Chantier feature/drift-psi-infrastructure: on-demand PSI drift check
built on the training-time reference persisted by `tracking.export.export_best_model`
(migration 0019) and `explain.py`'s EXISTING feature-reconstruction path
(`ingest(force=False)` + `build_base_feature_pool`/`build_parametric_pool`)
-- deliberately no parallel data path or new "current snapshot" table (see
this branch's own report for why: `explain.py::explain_last_prediction`
already proved there is no persisted per-prediction feature-vector store
to reuse instead).

Structure mirrors `test_explain.py`: a real (tiny) `run_pipeline`, `ingest`
monkeypatched to synthetic data so the test needs no network.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick import explain as explain_module
from patrick.config.schema import RunConfig
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module
from patrick.tracking import db as trackdb
from patrick.validation import drift

TARGET_SYMBOL = "^TEST_DRIFT"
HORIZON = 5
TARGET_COL = clean_symbol(TARGET_SYMBOL)


def _synthetic_raw(n=1500, seed=0, shift_after: int | None = None, shift_size: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({TARGET_COL: target}, index=idx)
    spx = 3000 + np.cumsum(rng.normal(0, 5, n))
    nfci = np.cumsum(rng.normal(0, 0.02, n))
    t10y2y = np.cumsum(rng.normal(0, 0.01, n))
    if shift_after is not None:
        # Large, permanent level+scale shift on every raw input from
        # `shift_after` onward -- simulates a real data-drift event
        # propagating into every feature derived from these columns.
        spx = spx.copy()
        spx[shift_after:] = spx[shift_after:] * 5 + shift_size
        nfci = nfci.copy()
        nfci[shift_after:] = nfci[shift_after:] * 5 + shift_size
        t10y2y = t10y2y.copy()
        t10y2y[shift_after:] = t10y2y[shift_after:] * 5 + shift_size
    df["SPX_LIKE"] = spx
    df["NFCI"] = nfci
    df["T10Y2Y"] = t10y2y
    return df


def _tiny_config(tmp_path, out_subdir: str = "runs") -> RunConfig:
    raw_yaml = {
        "name": "drift_test",
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
        "output": {"dir": str(tmp_path / out_subdir), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


@pytest.mark.slow  # full pipeline run (x2), same order of magnitude as test_explain.py
def test_export_best_model_rewrites_drift_reference_not_duplicates_on_refit(tmp_path, monkeypatch):
    """Running the pipeline TWICE for the SAME (target, horizon) -- a
    re-train -- must leave exactly ONE drift_feature_reference row per
    selected feature, never two: the reference is only meaningful as of
    the latest training window."""
    raw = _synthetic_raw()
    monkeypatch.setattr(
        engine_module, "ingest",
        lambda objective, universe, store=None, force=False, data_quality=None: raw)

    db_path = str(tmp_path / "patrick.db")
    store = DataStore(root=str(tmp_path / "store"))

    result1 = engine_module.run_pipeline(_tiny_config(tmp_path, "runs1"), store=store, db_path=db_path)
    assert result1["model_path"] is not None

    conn = trackdb.connect(db_path)
    rows_after_first = conn.execute(
        "SELECT feature FROM drift_feature_reference WHERE symbol = ? AND horizon = ?",
        (TARGET_SYMBOL, HORIZON)).fetchall()
    conn.close()
    assert len(rows_after_first) > 0  # something was actually persisted

    result2 = engine_module.run_pipeline(_tiny_config(tmp_path, "runs2"), store=store, db_path=db_path)
    assert result2["model_path"] is not None

    conn = trackdb.connect(db_path)
    counts = conn.execute(
        "SELECT feature, count(*) FROM drift_feature_reference "
        "WHERE symbol = ? AND horizon = ? GROUP BY feature",
        (TARGET_SYMBOL, HORIZON)).fetchall()
    conn.close()
    assert len(counts) > 0
    assert all(count == 1 for _feature, count in counts)  # rewritten, never accumulated


# Raw input columns `_synthetic_raw` shifts -- every feature derived from
# one of them (and only those: the target's own features are never shifted)
# must be flagged as significant drift.
DRIFTED_INPUTS = ("SPX_LIKE", "NFCI", "T10Y2Y")


def _derived_from_drifted_input(feature: str) -> bool:
    return any(feature.startswith(col) for col in DRIFTED_INPUTS) and TARGET_COL not in feature


@pytest.mark.slow
def test_compute_drift_for_ticker_horizon_detects_simulated_drift_and_records_history(tmp_path, monkeypatch):
    """On-demand call against data that has genuinely drifted since
    training: every exported feature derived from a shifted input must
    cross the 'significant' PSI threshold, and a history row must be
    written per computed feature. A second successive call must not
    duplicate the reference (still one row per feature) while the history
    keeps growing (one more row per feature, not overwritten).

    No feature pinning: the exported feature set is the pipeline's own
    selection, which is now identical across machines at identical seed
    (`tests/test_selection_determinism.py` -- CPU-independent tie-break,
    fixed thread count). The previous version pinned the exported features
    through a monkeypatch because Linux and Windows selected different
    models (RandomForest N=8 vs XGBoost N=5): that masked the
    non-determinism instead of removing it."""
    clean_raw = _synthetic_raw()
    monkeypatch.setattr(
        engine_module, "ingest",
        lambda objective, universe, store=None, force=False, data_quality=None: clean_raw)

    db_path = str(tmp_path / "patrick.db")
    store = DataStore(root=str(tmp_path / "store"))
    result = engine_module.run_pipeline(_tiny_config(tmp_path), store=store, db_path=db_path)
    assert result["model_path"] is not None

    conn = trackdb.connect(db_path)
    reference_count_before = conn.execute(
        "SELECT count(*) FROM drift_feature_reference WHERE symbol = ? AND horizon = ?",
        (TARGET_SYMBOL, HORIZON)).fetchone()[0]
    conn.close()
    assert reference_count_before > 0

    # Recent data has drifted hard: SPX_LIKE/NFCI/T10Y2Y all rescaled+shifted
    # over their final 200 rows -- large enough that at least one derived
    # feature's recent window must diverge sharply from the training-time
    # reference computed on `clean_raw` above.
    drifted_raw = _synthetic_raw(shift_after=1300, shift_size=5000.0)
    monkeypatch.setattr(
        explain_module, "ingest",
        lambda objective, universe, store=None, data_quality=None: drifted_raw)

    first = explain_module.compute_drift_for_ticker_horizon(
        TARGET_SYMBOL, HORIZON, db_path=db_path, store=store)
    assert first is not None
    drifted = {f: info for f, info in first.items() if _derived_from_drifted_input(f)}
    assert drifted, f"no exported feature derives from a shifted input: {sorted(first)}"
    assert all(info["status"] == "significant" for info in drifted.values()), first

    conn = trackdb.connect(db_path)
    reference_count_after_first_call = conn.execute(
        "SELECT count(*) FROM drift_feature_reference WHERE symbol = ? AND horizon = ?",
        (TARGET_SYMBOL, HORIZON)).fetchone()[0]
    history_count_after_first_call = conn.execute(
        "SELECT count(*) FROM drift_psi_history WHERE symbol = ? AND horizon = ?",
        (TARGET_SYMBOL, HORIZON)).fetchone()[0]
    conn.close()
    assert reference_count_after_first_call == reference_count_before
    assert history_count_after_first_call == len(first)

    second = explain_module.compute_drift_for_ticker_horizon(
        TARGET_SYMBOL, HORIZON, db_path=db_path, store=store)
    assert second is not None

    conn = trackdb.connect(db_path)
    reference_count_after_second_call = conn.execute(
        "SELECT count(*) FROM drift_feature_reference WHERE symbol = ? AND horizon = ?",
        (TARGET_SYMBOL, HORIZON)).fetchone()[0]
    history_count_after_second_call = conn.execute(
        "SELECT count(*) FROM drift_psi_history WHERE symbol = ? AND horizon = ?",
        (TARGET_SYMBOL, HORIZON)).fetchone()[0]
    conn.close()
    # Reference untouched by on-demand calls -- only export_best_model writes it.
    assert reference_count_after_second_call == reference_count_before
    # History strictly grows -- one more row per feature, nothing overwritten.
    assert history_count_after_second_call == history_count_after_first_call + len(second)


def test_compute_drift_for_ticker_horizon_returns_none_without_a_persisted_reference(tmp_path):
    """No reference ever written for this (target, horizon) (e.g. trained
    before this feature existed, or never trained at all) -> None, not a
    crash or an empty-but-truthy result."""
    out = explain_module.compute_drift_for_ticker_horizon(
        "no-such-target", 5, db_path=str(tmp_path / "patrick.db"))
    assert out is None


def test_decile_reference_ignores_rolling_window_warmup_nans():
    """Any rolling-window feature (`_100d`, `_20d`, `ma10`...) starts with
    warm-up NaNs in the training window `export_best_model` hands to
    `decile_reference`. Those NaNs must be ignored, not collapse the
    reference into the single catch-all bin -- which made
    `psi_from_reference` return 0.0 for ANY shift, however large."""
    rng = np.random.default_rng(0)
    values = rng.normal(0, 1, 1000)
    with_warmup = values.copy()
    with_warmup[:20] = np.nan

    reference = drift.decile_reference(with_warmup)

    assert reference == drift.decile_reference(values[20:])  # NaNs ignored, nothing else changes
    assert len(reference["expected_pct"]) == 10
    shifted = values[:30] + 50.0
    assert drift.psi_from_reference(reference, shifted) > drift.PSI_ALERT_THRESHOLD
