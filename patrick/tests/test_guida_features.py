"""Phase 2 (feature/guida-features-full) -- TDD for the three "estimated"
Guida families (carry, cross-sectional momentum, idiosyncratic volatility)
and for the two documented-absent ones (basis momentum, open-interest MAs).
Every numeric expectation below is derived BY HAND from the construction of
the synthetic input, independently of `patrick.features.guida`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.features import guida


# ---------------------------------------------------------------------------
# Idiosyncratic volatility -- rolling OLS closed form
# ---------------------------------------------------------------------------

def test_rolling_ols_residual_std_matches_hand_computed_residual():
    """x = [0.001, 0.002, 0.003, 0.004] (arithmetic progression -> deviations
    from the mean are symmetric: [-1.5,-0.5,0.5,1.5]*0.001).
    noise = [0.002, -0.002, -0.002, 0.002] is built to be exactly ORTHOGONAL
    to x's deviations over this window (sum(noise)=0 AND
    sum(dev_x * noise)=0 -- -1.5*0.002 -0.5*(-0.002) +0.5*(-0.002) +1.5*0.002
    = -0.003+0.001-0.001+0.003 = 0): OLS therefore recovers beta/alpha
    EXACTLY over this window, so the residual equals `noise` exactly, and
    residual std (pandas default ddof=1) = std([0.002,-0.002,-0.002,0.002])
    = 0.002 * sqrt(4/3) = 0.00230940.
    y = alpha_true + beta_true*x + noise, with alpha_true=0.0005, beta_true=0.8.
    """
    x = pd.Series([0.001, 0.002, 0.003, 0.004])
    noise = pd.Series([0.002, -0.002, -0.002, 0.002])
    y = 0.0005 + 0.8 * x + noise

    resid_std = guida.rolling_ols_residual_std(y, x, window=4)
    assert np.isnan(resid_std.iloc[2])  # not enough history yet
    expected = 0.002 * np.sqrt(4 / 3)
    assert resid_std.iloc[3] == pytest.approx(expected, rel=1e-9)


def _prices_from_returns(returns: list[float], start: float = 100.0) -> pd.Series:
    prices = [start]
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    return pd.Series(prices)


def test_idiosyncratic_volatility_for_group_matches_hand_computed_residual_vol():
    """3-asset synthetic group: B and C are IDENTICAL price paths (so the
    leave-one-out factor for T is exactly their average, i.e. exactly B's
    own return series `x`) -- T's return is built as alpha+beta*x+noise
    using the same exact-orthogonal (x, noise) pair as the test above, so
    T's expected annualized residual vol at the last date is
    0.002*sqrt(4/3)*sqrt(252) (idiosyncratic vol is annualized like the
    other vol-model proxies in this codebase, e.g. `heston_proxy_features`)."""
    x = [0.001, 0.002, 0.003, 0.004]
    noise = [0.002, -0.002, -0.002, 0.002]
    y = [0.0005 + 0.8 * xi + ni for xi, ni in zip(x, noise)]

    raw = pd.DataFrame({
        "B": _prices_from_returns(x),
        "C": _prices_from_returns(x),
        "T": _prices_from_returns(y),
    })

    out = guida.idiosyncratic_volatility_for_group(raw, ["B", "C", "T"], window=4, label="test")
    col = "T_idio_vol_test_4d_estimated"
    assert col in out.columns
    expected = 0.002 * np.sqrt(4 / 3) * np.sqrt(252)
    assert out[col].iloc[4] == pytest.approx(expected, rel=1e-9)


def test_idiosyncratic_volatility_for_group_requires_at_least_three_members():
    raw = pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": [1.0, 2.0, 3.0]})
    out = guida.idiosyncratic_volatility_for_group(raw, ["A", "B"], window=2, label="test")
    assert out.empty


# ---------------------------------------------------------------------------
# Cross-sectional momentum (commodities only)
# ---------------------------------------------------------------------------

def test_cross_sectional_momentum_ranks_three_synthetic_commodities():
    """3 synthetic commodities over a 5d window: A up +10%, B up +5%, C down
    -5% -- expected percentile rank (pandas .rank(pct=True), 3 items):
    worst=1/3, middle=2/3, best=3/3=1.0."""
    idx = pd.bdate_range("2020-01-01", periods=6)
    raw = pd.DataFrame({
        "GC=F": [100, 100, 100, 100, 100, 110.0],   # +10%
        "SI=F": [100, 100, 100, 100, 100, 105.0],   # +5%
        "HG=F": [100, 100, 100, 100, 100, 95.0],    # -5%
    }, index=idx)

    out = guida.cross_sectional_momentum_features(raw, windows=[5])
    last = out.iloc[-1]
    assert last["GC=F_xsect_mom_5d_estimated"] == pytest.approx(1.0)
    assert last["SI=F_xsect_mom_5d_estimated"] == pytest.approx(2 / 3)
    assert last["HG=F_xsect_mom_5d_estimated"] == pytest.approx(1 / 3)


def test_cross_sectional_momentum_skips_groups_with_too_few_members():
    raw = pd.DataFrame({"GC=F": [100.0, 101, 102], "SI=F": [100.0, 99, 98]})
    out = guida.cross_sectional_momentum_features(raw, windows=[1])
    assert out.empty  # only 2 of the ~20 commodity tickers present


# ---------------------------------------------------------------------------
# Carry (EUR/USD only, estimated)
# ---------------------------------------------------------------------------

def test_eurusd_carry_features_hand_computed_rolling_mean_and_change():
    """US3M_Rate = [1.0, 1.5, 2.0, 2.5, 3.0], window=2:
    level_2d (rolling mean of 2): NaN, 1.25, 1.75, 2.25, 2.75
    chg_2d (diff over 2): NaN, NaN, 1.0, 1.0, 1.0"""
    raw = pd.DataFrame({"US3M_Rate": [1.0, 1.5, 2.0, 2.5, 3.0]})
    out = guida.eurusd_carry_features(raw, windows=[2])

    level = out["EURUSD_carry_us_rate_level_2d_estimated"]
    chg = out["EURUSD_carry_us_rate_chg_2d_estimated"]
    assert level.iloc[1] == pytest.approx(1.25)
    assert level.iloc[3] == pytest.approx(2.25)
    assert chg.iloc[2] == pytest.approx(1.0)
    assert chg.iloc[4] == pytest.approx(1.0)


def test_eurusd_carry_features_is_absent_without_the_us_rate_column():
    """Hard data constraint (no EU short rate in the FRED universe either):
    when even the US leg is missing, no column is fabricated."""
    raw = pd.DataFrame({"SOMETHING_ELSE": [1.0, 2.0, 3.0]})
    out = guida.eurusd_carry_features(raw, windows=[2])
    assert out.empty


# ---------------------------------------------------------------------------
# Absent families -- documented, not implemented
# ---------------------------------------------------------------------------

def test_basis_momentum_and_open_interest_are_not_implemented():
    assert not hasattr(guida, "basis_momentum_features")
    assert not hasattr(guida, "open_interest_ma_features")
    assert "basis momentum" in guida.__doc__.lower()
    assert "open" in guida.__doc__.lower() and "interest" in guida.__doc__.lower()


# ---------------------------------------------------------------------------
# `_estimated` metadata convention
# ---------------------------------------------------------------------------

def test_every_column_from_the_estimated_families_carries_the_suffix():
    raw = pd.DataFrame({
        "US3M_Rate": np.linspace(1.0, 3.0, 300),
        **{t: 100 + np.cumsum(np.random.default_rng(i).normal(0, 1, 300))
           for i, t in enumerate(["GC=F", "SI=F", "HG=F"])},
    })
    pool = guida.build_guida_estimated_features(raw)
    assert len(pool.columns) > 0
    assert all(c.endswith("_estimated") for c in pool.columns)
