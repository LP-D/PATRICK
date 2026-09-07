"""Phase 2 (feature/guida-features-full) -- extends `features/spike.py`'s
already-parameterizable rolling estimators (semivariance, skew) to the 14
Guida lookbacks. Hurst is intentionally NOT extended to all 14 (see
`HURST_GUIDA_SUBSET` docstring in spike.py: its rolling `.apply` is
O(n*window), 14 full windows including up to 756d would dominate scan time
for a family already documented as "no clean signal" -- a small subset is
added instead, not the full grid).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.defaults import GUIDA_LOOKBACKS
from patrick.features.spike import HURST_GUIDA_SUBSET, build_spike_features_base


def _series(n=1200, seed=3) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(np.cumsum(rng.normal(0, 1, n)) + 100)


def test_build_spike_features_base_default_is_unchanged_without_guida_windows():
    s = _series()
    df = build_spike_features_base(s, prefix="px")
    assert set(df.columns) == {"px_hurst_100d", "px_semivar_20d", "px_skew_20d"}


def test_build_spike_features_base_guida_windows_extends_semivar_and_skew_fully():
    s = _series()
    df = build_spike_features_base(s, prefix="px", guida_windows=GUIDA_LOOKBACKS)
    for w in GUIDA_LOOKBACKS:
        assert f"px_semivar_{w}d" in df.columns
        assert f"px_skew_{w}d" in df.columns


def test_build_spike_features_base_guida_windows_extends_hurst_only_on_the_reduced_subset():
    s = _series()
    df = build_spike_features_base(s, prefix="px", guida_windows=GUIDA_LOOKBACKS)
    for w in HURST_GUIDA_SUBSET:
        assert f"px_hurst_{w}d" in df.columns
    # the expensive full grid must NOT have been computed for hurst
    non_subset = [w for w in GUIDA_LOOKBACKS if w not in HURST_GUIDA_SUBSET and w != 100]
    for w in non_subset:
        assert f"px_hurst_{w}d" not in df.columns
