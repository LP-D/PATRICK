"""« Calculer une fois » -- costly feature pools cached on disk, keyed by
(data vintage, fold): the base pool (fold-independent) and the parametric
pool per fit cut (`fit_end_idx`/`test_end_idx`).

Before: every run recomputed the base pool from scratch (~50-90 s on the real
^GSPC universe), and every `/targets` SHAP explanation, drift check and live
prediction rebuilt the FULL pool, parametric models included (~33 s measured
on BTC-USD), even for a snapshot already processed a minute earlier.

The key covers everything the result depends on: the raw frame's CONTENT
(its vintage -- a revised snapshot is a different key), the feature
configuration, the fit cut, and a hash of the feature source code (a fix
to a feature function invalidates every cached pool automatically).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.features import pool_cache
from patrick.pipeline import engine as engine_module


def _raw(n=400, seed=0, bump=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    df = pd.DataFrame({"IDX_T": 100 + np.cumsum(rng.normal(0, 1, n))}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n)) + bump
    return df


def _config(**features):
    return RunConfig.model_validate({
        "objective": {"target_symbol": "^T", "horizons": [5]},
        "features": {"families": ["technical", "spike", "vol_models"], "vol_models": ["kalman"], **features},
    })


@pytest.fixture
def counting(monkeypatch):
    calls = {"technical": 0, "spike_param": 0}
    real_tech = engine_module.technical.build_technical_features
    real_spike = engine_module.spike.build_spike_features_parametric

    def tech(*a, **k):
        calls["technical"] += 1
        return real_tech(*a, **k)

    def spike_param(*a, **k):
        calls["spike_param"] += 1
        return real_spike(*a, **k)

    monkeypatch.setattr(engine_module.technical, "build_technical_features", tech)
    monkeypatch.setattr(engine_module.spike, "build_spike_features_parametric", spike_param)
    monkeypatch.setattr(engine_module, "download_ohlc", lambda *a, **k: None)
    return calls


def test_base_pool_is_computed_once_per_vintage_and_config(counting):
    raw, config = _raw(), _config()
    first = engine_module.build_base_feature_pool(raw, config, "IDX_T")
    n_calls = counting["technical"]
    second = engine_module.build_base_feature_pool(raw, config, "IDX_T")
    assert counting["technical"] == n_calls
    pd.testing.assert_frame_equal(first, second)


def test_a_revised_vintage_or_another_config_is_recomputed(counting):
    engine_module.build_base_feature_pool(_raw(), _config(), "IDX_T")
    n_calls = counting["technical"]
    engine_module.build_base_feature_pool(_raw(bump=1e-6), _config(), "IDX_T")
    assert counting["technical"] > n_calls
    n_calls = counting["technical"]
    engine_module.build_base_feature_pool(_raw(), _config(technical_lookbacks={"returns_windows": [1, 2]}), "IDX_T")
    assert counting["technical"] > n_calls


def test_parametric_pool_is_cached_per_fit_cut(counting):
    raw, config = _raw(), _config()
    a = engine_module.build_parametric_pool(raw, config, fit_end_idx=200, test_end_idx=300)
    n_calls = counting["spike_param"]
    b = engine_module.build_parametric_pool(raw, config, fit_end_idx=200, test_end_idx=300)
    assert counting["spike_param"] == n_calls
    pd.testing.assert_frame_equal(a, b)
    engine_module.build_parametric_pool(raw, config, fit_end_idx=250, test_end_idx=300)
    assert counting["spike_param"] > n_calls


def test_feature_code_change_invalidates_the_cache(counting, monkeypatch):
    raw, config = _raw(), _config()
    engine_module.build_base_feature_pool(raw, config, "IDX_T")
    n_calls = counting["technical"]
    monkeypatch.setattr(pool_cache, "FEATURE_CODE_HASH", "different-code")
    engine_module.build_base_feature_pool(raw, config, "IDX_T")
    assert counting["technical"] > n_calls


def test_cache_can_be_disabled(counting, monkeypatch):
    monkeypatch.setenv("PATRICK_FEATURE_CACHE", "0")
    raw, config = _raw(), _config()
    engine_module.build_base_feature_pool(raw, config, "IDX_T")
    n_calls = counting["technical"]
    engine_module.build_base_feature_pool(raw, config, "IDX_T")
    assert counting["technical"] == 2 * n_calls
