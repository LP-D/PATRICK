"""S5/S6: the SHAP/RFE/LASSO selection cache added to `_select()`
(`pipeline/engine.py`) -- keyed by (target, horizon, snapshot_id, data_hash,
selector_config_hash, see migration 0014). S5 proves it actually avoids
recomputation (by call count, not timing) without becoming overly
aggressive (a genuinely different key must still recompute). S6 proves the
cached result is byte-identical to a fresh computation -- the one test that
matters most here: a cache that's fast but silently wrong would be worse
than no cache at all.
"""
from __future__ import annotations

import numpy as np
import pytest

from patrick.config.schema import ObjectiveConfig, RunConfig
from patrick.pipeline import engine as engine_module
from patrick.tracking import db as trackdb


def _tiny_config(**overrides) -> RunConfig:
    raw = {"objective": {"target_symbol": "^TEST"}, **overrides}
    return RunConfig.model_validate(raw)


def _synthetic_xy(n_rows=300, n_cols=30, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n_rows, n_cols))
    y = rng.integers(0, 4, size=n_rows)
    return X, y


@pytest.fixture
def conn(tmp_path):
    return trackdb.connect(str(tmp_path / "patrick.db"))


@pytest.fixture
def counting_select_features(monkeypatch):
    """Wraps the REAL select_features() (still does real work, not a stub)
    so a call count can be asserted without the test only proving a mock
    was invoked -- S6's identity check needs the real computation anyway."""
    calls = {"n": 0}
    original = engine_module.select_features

    def _wrapped(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(engine_module, "select_features", _wrapped)
    return calls


def test_second_call_with_identical_key_does_not_recompute(conn, counting_select_features):
    """S5: two successive 'grid points' sharing the same (target, horizon,
    snapshot_id, data, selector config) -- exactly the sampler x algo
    redundancy this cache targets -- must trigger exactly one real
    selection computation."""
    X_tr, y_tr = _synthetic_xy()
    config = _tiny_config()

    cols1 = engine_module._select(conn, "^VIX", 5, "snap1", config, X_tr, y_tr, 5, seed=42)
    cols2 = engine_module._select(conn, "^VIX", 5, "snap1", config, X_tr, y_tr, 5, seed=42)

    assert counting_select_features["n"] == 1, "second call should have been served from cache"
    assert cols1 == cols2


def test_different_snapshot_id_triggers_a_distinct_computation(conn, counting_select_features):
    """S5 negative: the cache must not be so aggressive that two genuinely
    different snapshots collapse into one -- distinct snapshot_id (same
    data/config otherwise) must NOT hit the same cache entry."""
    X_tr, y_tr = _synthetic_xy()
    config = _tiny_config()

    engine_module._select(conn, "^VIX", 5, "snap1", config, X_tr, y_tr, 5, seed=42)
    engine_module._select(conn, "^VIX", 5, "snap2", config, X_tr, y_tr, 5, seed=42)

    assert counting_select_features["n"] == 2, "different snapshot_id must not share a cache entry"


def test_different_selector_config_hash_triggers_a_distinct_computation(conn, counting_select_features):
    """S5 negative, second case: same data/snapshot, but a selector
    parameter that DOES influence the result (n_feat) differs -- must also
    recompute, not reuse the first n_feat's selection under a different N."""
    X_tr, y_tr = _synthetic_xy()
    config = _tiny_config()

    engine_module._select(conn, "^VIX", 5, "snap1", config, X_tr, y_tr, 5, seed=42)
    engine_module._select(conn, "^VIX", 5, "snap1", config, X_tr, y_tr, 8, seed=42)  # n_feat differs

    assert counting_select_features["n"] == 2, "a different n_feat must not share a cache entry"


def test_cached_result_is_byte_identical_to_a_fresh_computation(conn, counting_select_features):
    """S6, the most important test of this workstream: the cache must not
    just be fast on a hit, it must return EXACTLY what a cold computation
    would have produced -- same selected column indices, same order."""
    X_tr, y_tr = _synthetic_xy(seed=7)
    config = _tiny_config()

    cols_cold = engine_module._select(conn, "^VIX", 5, "snap1", config, X_tr, y_tr, 6, seed=42)
    assert counting_select_features["n"] == 1

    cols_warm = engine_module._select(conn, "^VIX", 5, "snap1", config, X_tr, y_tr, 6, seed=42)
    assert counting_select_features["n"] == 1, "second call must have hit the cache, not recomputed"

    assert cols_warm == cols_cold, "cached selection differs from the fresh computation -- silent corruption"

    # Independent re-derivation, not a self-comparison: a THIRD, fresh call
    # (different snapshot_id -> forced cache miss) on the SAME (X_tr, y_tr,
    # config) must select the exact same columns, confirming the cached
    # value isn't just internally consistent with itself but matches what
    # the real, uncached selector actually produces for this input.
    cols_independent = engine_module._select(conn, "^VIX", 5, "snap_independent",
                                               config, X_tr, y_tr, 6, seed=42)
    assert counting_select_features["n"] == 2
    assert cols_independent == cols_cold
