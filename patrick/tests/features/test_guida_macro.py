"""Phase 2 (feature/guida-features-full) -- `features/macro.py` had a single
hardcoded return window (5d) and a single hardcoded vol window (20d):
extended to the 14 Guida lookbacks via `guida_windows`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.config.defaults import GUIDA_LOOKBACKS
from patrick.features.macro import build_macro_features


def _df(n=1200, seed=5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"NFCI": np.cumsum(rng.normal(0, 0.02, n))})


def test_build_macro_features_default_is_unchanged_without_guida_windows():
    df = build_macro_features(_df(), ["NFCI"])
    assert set(df.columns) == {"NFCI_level", "NFCI_ret_5d", "NFCI_vol_20d",
                                "NFCI_lag1", "NFCI_lag5", "NFCI_lag10"}


def test_build_macro_features_guida_windows_extends_ret_and_vol():
    df = build_macro_features(_df(), ["NFCI"], guida_windows=GUIDA_LOOKBACKS)
    for w in GUIDA_LOOKBACKS:
        assert f"NFCI_ret_{w}d" in df.columns
        assert f"NFCI_vol_{w}d" in df.columns
    # original fixed columns still present (backward compatible superset)
    assert "NFCI_ret_5d" in df.columns
    assert "NFCI_vol_20d" in df.columns
