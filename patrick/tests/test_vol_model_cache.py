"""Cache non-regression (count-based) + strict result identity for the
vol-model cache (EGARCH/Kalman/HMM/..., migration 0015) -- same discipline
as test_selection_cache.py for the SHAP cache: the count-based
non-regression tests come first, the strict identity test (the most
important one, run BEFORE any gain measurement) comes last.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.features import vol_models
from patrick.tracking import db as trackdb


def _synthetic_series(n=800, seed=0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(100 + np.cumsum(rng.normal(0, 1.0, n)), index=idx, name="TICK")


@pytest.fixture
def conn(tmp_path):
    return trackdb.connect(str(tmp_path / "patrick.db"))


def _counting_wrapper(monkeypatch, func_name: str) -> dict:
    """Wraps the REAL underlying model function (still does real work, not
    a stub -- the identity test below needs the real computation anyway) so
    a call count can be asserted. Patched on the module, not captured by
    reference: `_PARAMETRIC_MODELS`'s lambdas look up the name in the
    module's globals at call time, so this is picked up correctly."""
    calls = {"n": 0}
    original = getattr(vol_models, func_name)

    def _wrapped(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(vol_models, func_name, _wrapped)
    return calls


def test_second_call_with_identical_key_does_not_recompute(conn, monkeypatch):
    calls = _counting_wrapper(monkeypatch, "egarch_conditional_vol")
    s = _synthetic_series()

    r1 = vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 500, None)
    r2 = vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 500, None)

    assert calls["n"] == 1, "second call should have been served from cache"
    pd.testing.assert_frame_equal(r1, r2)


def test_different_snapshot_id_triggers_a_distinct_computation(conn, monkeypatch):
    calls = _counting_wrapper(monkeypatch, "egarch_conditional_vol")
    s = _synthetic_series()

    vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 500, None)
    vol_models._cached_parametric_model(conn, "snap2", "TICK", "egarch", s, 500, None)

    assert calls["n"] == 2, "different snapshot_id must not share a cache entry"


def test_different_fit_end_idx_triggers_a_distinct_computation(conn, monkeypatch):
    """The real-world case this cache targets: a walk-forward fold's
    fit_end_idx changes every fold (expanding window) -- must never be
    mistaken for the same key."""
    calls = _counting_wrapper(monkeypatch, "egarch_conditional_vol")
    s = _synthetic_series()

    vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 500, None)
    vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 600, None)

    assert calls["n"] == 2, "different fit_end_idx must not share a cache entry"


def test_different_model_triggers_a_distinct_computation(conn, monkeypatch):
    """Negative case across models, not just across keys of the same
    model: egarch and kalman sharing the same snapshot/ticker/fit_end_idx
    must not collapse into one cache entry."""
    egarch_calls = _counting_wrapper(monkeypatch, "egarch_conditional_vol")
    kalman_calls = _counting_wrapper(monkeypatch, "kalman_filtered_level")
    s = _synthetic_series()

    r_egarch = vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 500, None)
    r_kalman = vol_models._cached_parametric_model(conn, "snap1", "TICK", "kalman", s, 500, None)

    assert egarch_calls["n"] == 1
    assert kalman_calls["n"] == 1
    assert list(r_egarch.columns) != list(r_kalman.columns)


def test_data_hash_distinguishes_different_series_content_at_same_indices(conn, monkeypatch):
    """S2's stated rationale for data_hash, exercised directly: two calls
    with the SAME fit_end_idx/test_end_idx/snapshot_id/ticker but DIFFERENT
    series content (e.g. after a data correction) must not share a cache
    entry."""
    calls = _counting_wrapper(monkeypatch, "egarch_conditional_vol")
    s1 = _synthetic_series(seed=1)
    s2 = _synthetic_series(seed=2)

    vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s1, 500, None)
    vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s2, 500, None)

    assert calls["n"] == 2, "different series content must not share a cache entry"


def test_cached_result_is_byte_identical_to_a_fresh_computation(conn, monkeypatch):
    """The most important test of this workstream, run BEFORE any gain
    measurement (never the reverse): a cache hit must return EXACTLY what a
    cold computation would have produced -- not just faster, not just
    "close enough". Verified two ways: cold-vs-warm, AND a third,
    independent cache-miss call (different snapshot_id, same series/config)
    confirming the cached value matches what the real, uncached function
    actually produces for this input."""
    calls = _counting_wrapper(monkeypatch, "egarch_conditional_vol")
    s = _synthetic_series(seed=7)

    cold = vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 500, None)
    assert calls["n"] == 1

    warm = vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 500, None)
    assert calls["n"] == 1, "second call must have hit the cache, not recomputed"
    pd.testing.assert_frame_equal(warm, cold)

    independent = vol_models._cached_parametric_model(conn, "snap_independent", "TICK", "egarch", s, 500, None)
    assert calls["n"] == 2
    pd.testing.assert_frame_equal(independent, cold)


def test_cached_result_preserves_float_dtype_when_the_underlying_fit_failed(conn, monkeypatch):
    """Bug found 2026-08-23 (real GSPC re-run, `HY_OAS_egarch_vol` and
    `SP500_Level_egarch_vol` both all-NaN and `object` dtype): a failed fit
    (`egarch_conditional_vol`'s own `except` path) returns
    `pd.Series(np.nan, ...)` -- correctly `float64`, no crash on a cold
    call. But the cache WRITE path (`_cached_parametric_model` below)
    converts every NaN to a Python `None` before JSON-serializing into
    `vol_model_cache` (`None if pd.isna(v) else float(v)`), and the READ
    path reconstructed the cached list directly
    (`pd.DataFrame({col_name: cached}, index=...)`) with no explicit
    dtype -- a list of Python `None` makes pandas infer `object`, not
    `float64`. Downstream, `pipeline/engine.py::_finite_features()` calls
    `np.isinf()` on the assembled feature matrix, which raises `TypeError`
    on an `object`-dtype column -- silent on the FIRST (cold) call, crashes
    on the SECOND (any future cache hit against this same key), forever,
    once the poisoned entry is written. Reproduced here by forcing the
    underlying fit to always fail, rather than relying on real EGARCH
    non-convergence (flaky/slow, and not the point under test -- the bug is
    in the cache round-trip, not in why the fit failed)."""
    def _always_fails(series, *args, **kwargs):
        return pd.Series(np.nan, index=series.index, name="egarch_vol")
    monkeypatch.setattr(vol_models, "egarch_conditional_vol", _always_fails)
    s = _synthetic_series()

    cold = vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 500, None)
    warm = vol_models._cached_parametric_model(conn, "snap1", "TICK", "egarch", s, 500, None)

    assert cold["egarch_vol"].dtype.kind == "f", f"cold call: unexpected dtype {cold['egarch_vol'].dtype}"
    assert warm["egarch_vol"].dtype.kind == "f", (
        f"cache-hit call returned dtype {warm['egarch_vol'].dtype!r} instead of a float dtype -- "
        "np.isinf() on this raises TypeError downstream in "
        "pipeline/engine.py::_finite_features()"
    )
    pd.testing.assert_frame_equal(warm, cold)
