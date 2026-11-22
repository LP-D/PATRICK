"""Phase 2 (feature/guida-features-full) -- RSI (Wilder) and the 14-lookback
Guida window grid applied to `features/technical.py`. TDD: the expected RSI
values below are computed BY HAND (see comment) from Wilder's original
recursive formula, independently of `patrick.features.technical.rsi`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.config.defaults import GUIDA_LOOKBACKS
from patrick.features.technical import build_technical_features, rsi


def test_rsi_matches_hand_computed_wilder_values():
    """Prices: [10, 11, 12, 11, 13, 12, 14], period=3.
    Deltas (index1..6): +1, +1, -1, +2, -1, +2
    gains:   1, 1, 0, 2, 0, 2   losses: 0, 0, 1, 0, 1, 0
    Seed (SMA of first 3 deltas, index1..3): avg_gain=2/3, avg_loss=1/3
      -> t=3 (the seed itself, Wilder's first defined value): RS=2
         -> RSI=100-100/3=66.667...
    Wilder recursion avg_x_t = (avg_x_{t-1}*(period-1) + x_t) / period:
      t=4: avg_gain=10/9,  avg_loss=2/9   -> RS=5        -> RSI=100-100/6=83.333...
      t=5: avg_gain=20/27, avg_loss=13/27 -> RS=20/13    -> RSI=100-1300/33=60.606...
      t=6: avg_gain=94/81, avg_loss=26/81 -> RS=47/13    -> RSI=100-1300/60=78.333...
    """
    prices = pd.Series([10, 11, 12, 11, 13, 12, 14], dtype=float)
    df = rsi(prices, windows=[3])
    assert list(df.columns) == ["rsi_3d"]
    out = df["rsi_3d"]

    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[2])  # not enough history yet
    assert out.iloc[3] == pytest.approx(66.666667, abs=1e-4)  # seed value
    assert out.iloc[4] == pytest.approx(83.333333, abs=1e-4)
    assert out.iloc[5] == pytest.approx(60.606061, abs=1e-4)
    assert out.iloc[6] == pytest.approx(78.333333, abs=1e-4)


def test_rsi_is_100_on_a_strictly_increasing_window_and_50_on_a_flat_one():
    up = pd.Series(np.arange(1.0, 20.0))  # strictly increasing -> avg_loss == 0
    out_up = rsi(up, windows=[5])["rsi_5d"]
    assert (out_up.dropna() == 100.0).all()

    flat = pd.Series([5.0] * 20)  # perfectly flat -> avg_gain == avg_loss == 0
    out_flat = rsi(flat, windows=[5])["rsi_5d"]
    assert (out_flat.dropna() == 50.0).all()


def test_rsi_supports_multiple_windows_like_the_other_technical_functions():
    s = pd.Series(np.cumsum(np.random.default_rng(0).normal(0, 1, 100)) + 100)
    df = rsi(s, windows=[7, 14])
    assert set(df.columns) == {"rsi_7d", "rsi_14d"}
    assert df["rsi_7d"].dropna().between(0, 100).all()
    assert df["rsi_14d"].dropna().between(0, 100).all()


def test_build_technical_features_includes_rsi_by_default():
    s = pd.Series(np.cumsum(np.random.default_rng(1).normal(0, 1, 60)) + 50)
    df = build_technical_features(s, prefix="px")
    assert "px_rsi_14d" in df.columns


def test_build_technical_features_guida_windows_extends_every_paramble_function():
    """When `guida_windows` is passed, returns/zscore/ma_ratio/rolling_vol/rsi
    (all already `windows=`-parameterized) must each grow to include every
    Guida lookback, merged (deduplicated) with their own small defaults --
    reusing the existing `windows=` mechanism, no new per-function logic."""
    s = pd.Series(np.cumsum(np.random.default_rng(2).normal(0, 1, 1200)) + 100)
    default_df = build_technical_features(s, prefix="px")
    guida_df = build_technical_features(s, prefix="px", guida_windows=GUIDA_LOOKBACKS)

    for w in GUIDA_LOOKBACKS:
        assert f"px_ret_{w}d" in guida_df.columns
        assert f"px_zscore_{w}d" in guida_df.columns
        assert f"px_vs_ma{w}" in guida_df.columns
        assert f"px_vol_{w}d" in guida_df.columns
        assert f"px_rsi_{w}d" in guida_df.columns

    # Guida-off behavior must be exactly unchanged (backward compatible).
    assert list(default_df.columns) == [c for c in default_df.columns]
    assert set(default_df.columns).issubset(set(guida_df.columns))
    assert len(guida_df.columns) > len(default_df.columns)
