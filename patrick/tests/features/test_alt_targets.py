"""Modules optionnels : étiquettes barrière triple (`features/triple_barrier.py`) et différenciation fractionnaire (`features/fracdiff.py`)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.features import fracdiff as fd
from patrick.features import triple_barrier as tb


def _path(values, start="2024-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def _flat_with_vol(n=60, seed=0):
    rng = np.random.default_rng(seed)
    return _path(100 * np.cumprod(1 + rng.normal(0, 0.01, n)))


# ------------------------------------------------------------------------------------------------------- barrière triple
def test_upper_barrier_touched_first_gives_plus_one_and_the_exit_date():
    close = _flat_with_vol(80)
    vol = pd.Series(0.01, index=close.index)
    px = close.copy()
    px.iloc[40:] = px.iloc[39] * np.array([1.0, 1.0, 1.03] + [1.03] * (len(px) - 43))              # +3 % à la 3e séance suivante
    out = tb.triple_barrier_labels(px, horizon=10, vol=vol, pt=2.0, sl=2.0)
    row = out.loc[px.index[39]]
    assert row["label"] == 1 and row["barrier"] == "upper" and row["bars"] == 3 and row["t1"] == px.index[42] and row["ret"] == pytest.approx(0.03)


def test_lower_barrier_and_vertical_barrier():
    vol = pd.Series(0.01, index=_path(range(1, 40)).index)
    down = _path([100.0] * 10 + [97.0] * 29)
    out = tb.triple_barrier_labels(down, horizon=5, vol=vol.reindex(down.index).fillna(0.01), pt=2.0, sl=2.0)
    assert out.iloc[5]["label"] == -1 and out.iloc[5]["barrier"] == "lower"
    calm = _path(np.linspace(100, 100.5, 40))
    v = tb.triple_barrier_labels(calm, horizon=5, vol=pd.Series(0.02, index=calm.index), pt=2.0, sl=2.0)
    assert (v["barrier"] == "vertical").all() and (v["label"] == 1).all() and (v["bars"] == 5).all()
    z = tb.triple_barrier_labels(calm, horizon=5, vol=pd.Series(0.02, index=calm.index), pt=2.0, sl=2.0, vertical_label="zero")
    assert (z["label"] == 0).all()


def test_last_events_without_a_full_window_are_not_labelled():
    close = _flat_with_vol(60)
    out = tb.triple_barrier_labels(close, horizon=7)
    assert out.index.max() <= close.index[-8] and (out["t1"] > out.index).all() and (out["bars"] <= 7).all()
    assert out.index.min() >= close.index[4]                                                          # volatilité inconnue avant quelques séances


def test_labels_do_not_depend_on_prices_after_the_exit_date():
    close = _flat_with_vol(120, seed=3)
    base = tb.triple_barrier_labels(close, horizon=10)
    altered = close.copy()
    altered.iloc[100:] = altered.iloc[100:] * 5
    other = tb.triple_barrier_labels(altered, horizon=10)
    early = base.index[base["t1"] < close.index[100]]
    pd.testing.assert_frame_equal(base.loc[early], other.loc[early])
    assert len(early) > 50


def test_volatility_uses_only_the_past():
    close = _flat_with_vol(100, seed=4)
    full = tb.daily_volatility(close)
    cut = tb.daily_volatility(close.iloc[:60])
    assert full.iloc[59] == pytest.approx(cut.iloc[59])


def test_barrier_can_be_disabled_and_arguments_are_validated():
    close = _flat_with_vol(120, seed=5)
    vol = pd.Series(0.004, index=close.index)
    both = tb.triple_barrier_labels(close, 10, vol=vol, pt=1.0, sl=1.0)
    only_down = tb.triple_barrier_labels(close, 10, vol=vol, pt=0.0, sl=1.0)
    assert (both["barrier"] == "upper").any() and not (only_down["barrier"] == "upper").any()
    for kwargs in ({"horizon": 0}, {"horizon": 5, "vertical_label": "x"}, {"horizon": 5, "pt": -1.0}):
        with pytest.raises(ValueError):
            tb.triple_barrier_labels(close, **kwargs)
    with pytest.raises(ValueError):
        tb.triple_barrier_labels(_path([100, 0, 100, 100, 100, 100, 100, 100]), 3)


def test_label_balance_sums_to_one():
    out = tb.triple_barrier_labels(_flat_with_vol(300, seed=6), horizon=10)
    bal = tb.label_balance(out)
    assert bal["n"] == len(out) and sum(bal["label"].values()) == pytest.approx(1.0) and sum(bal["barrier"].values()) == pytest.approx(1.0)
    assert tb.label_balance(out.iloc[:0])["n"] == 0


# ------------------------------------------------------------------------------------------- différenciation fractionnaire
def test_weights_match_the_known_binomial_coefficients():
    assert fd.ffd_weights(0.0).tolist() == [1.0]
    assert fd.ffd_weights(1.0).tolist() == [-1.0, 1.0]
    w = fd.ffd_weights(0.5, threshold=1e-3)
    assert w[-1] == 1.0 and w[-2] == pytest.approx(-0.5) and w[-3] == pytest.approx(-0.125) and w[-4] == pytest.approx(-0.0625)
    with pytest.raises(ValueError):
        fd.ffd_weights(-0.1)
    assert len(fd.ffd_weights(0.3, 1e-5)) > len(fd.ffd_weights(0.3, 1e-2))                           # seuil plus fin = fenêtre plus longue


def test_frac_diff_endpoints_are_the_level_and_the_difference():
    s = pd.Series(np.cumsum(np.random.default_rng(1).normal(0, 1, 300)) + 50, index=pd.bdate_range("2020-01-01", periods=300))
    pd.testing.assert_series_equal(fd.frac_diff_ffd(s, 0.0), s)
    one = fd.frac_diff_ffd(s, 1.0)
    pd.testing.assert_series_equal(one, s.diff().dropna())
    half = fd.frac_diff_ffd(s, 0.5, 1e-3)
    width = len(fd.ffd_weights(0.5, 1e-3))
    assert len(half) == len(s) - width + 1 and half.index[0] == s.index[width - 1]
    assert fd.frac_diff_ffd(s.iloc[:5], 0.5).empty


def test_frac_diff_uses_only_the_past():
    s = pd.Series(np.cumsum(np.random.default_rng(2).normal(0, 1, 400)) + 100, index=pd.bdate_range("2020-01-01", periods=400))
    base = fd.frac_diff_ffd(s, 0.4)
    altered = s.copy()
    altered.iloc[300:] += 25
    other = fd.frac_diff_ffd(altered, 0.4)
    assert np.allclose(base.loc[:s.index[299]], other.loc[:s.index[299]]) and not np.allclose(base.iloc[-1], other.iloc[-1])


def test_min_stationary_d_for_a_random_walk_and_for_a_stationary_series():
    rng = np.random.default_rng(7)
    walk = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, 1800))), index=pd.bdate_range("2015-01-01", periods=1800))
    res = fd.min_stationary_d(walk)
    assert res["d"] is not None and 0.0 < res["d"] <= 1.0
    corrs = [t["corr"] for t in res["tried"] if t["corr"] is not None]
    assert corrs == sorted(corrs, reverse=True) or len(corrs) < 3                                      # plus d est grand, moins la série ressemble au niveau
    ar = pd.Series(100 + np.cumsum(rng.normal(0, 1, 1800)) * 0 + rng.normal(0, 1, 1800), index=walk.index)
    assert fd.min_stationary_d(ar, log=False)["d"] == 0.0
    short = fd.min_stationary_d(walk.iloc[:150])
    assert short["d"] is None and all(t["pvalue"] is None for t in short["tried"] if t["n"] < 200)
