"""Phase 2 (feature/guida-features-full) -- extends the two NON-parametric
vol_models (heston_proxy, vrp_proxy -- already short/long rolling windows,
no global parameter) to a curated subset of Guida (short, long) pairs. The
parametric family (EGARCH/Kalman/HMM/AR/MA/ARMA/ARIMA) is deliberately left
untouched: their "lookback" is a globally fit model order/parameter set, not
a rolling window -- the Guida lookback taxonomy does not map onto them (see
`vol_models.py` module docstring addition).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features.vol_models import GUIDA_VOL_PROXY_PAIRS, build_vol_model_features_base


def _series(n=1200, seed=4) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(np.cumsum(rng.normal(0, 1, n)) + 100)


def test_build_vol_model_features_base_default_unchanged_without_guida_windows():
    s = _series()
    df = build_vol_model_features_base(s, prefix="px", models=["heston_proxy", "vrp_proxy"])
    assert set(df.columns) == {"px_heston_theta", "px_heston_spread", "px_vrp_proxy_truncated"}


def test_build_vol_model_features_base_guida_windows_adds_curated_pairs():
    s = _series()
    df = build_vol_model_features_base(s, prefix="px", models=["heston_proxy", "vrp_proxy"],
                                        guida_windows=[10, 22, 44, 66, 252, 504])
    for short, long_ in GUIDA_VOL_PROXY_PAIRS:
        assert f"px_heston_theta_{short}_{long_}d" in df.columns
        assert f"px_heston_spread_{short}_{long_}d" in df.columns
        assert f"px_vrp_proxy_{short}_{long_}d" in df.columns
    # base (non-suffixed) columns still present
    assert "px_heston_theta" in df.columns
    assert "px_vrp_proxy_truncated" in df.columns
