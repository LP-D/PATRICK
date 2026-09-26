"""Roadmap bloc 3 -- long-cycle features for the 252/504/756-day horizons.

The default technical lookbacks stop at 60 days (returns 1-20, z-score
10-60, MA ratio 10-50): a model asked about the direction over one to
three years only sees month-scale information. The `long_cycle` family
(opt-in, off by default: the existing pool and every golden run stay
unchanged) adds the documented long-horizon predictors:
- 1-, 2- and 3-year returns (long-term reversal, De Bondt & Thaler 1985);
- 12-1 momentum (Jegadeesh & Titman 1993: 12 months skipping the last one);
- 1- and 3-year z-scores and the position inside the 1- and 3-year range
  (52-week high anchoring, George & Hwang 2004), centred on 0 so the
  engine's NaN -> 0 imputation reads "middle of the range", not "at the low";
- drawdown from the running maximum;
- short/long volatility ratio (21 vs 252 days).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.audit_speed import classify_feature
from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.features import long_cycle
from patrick.pipeline import engine
from patrick.webapp import forms


def _prices(n=1200, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n))), index=idx, name="X")


def test_every_value_at_t_uses_only_prices_up_to_t():
    s = _prices()
    full = long_cycle.build_long_cycle_features(s, prefix="X")
    t = 1000
    shocked = s.copy()
    shocked.iloc[t + 1:] *= np.linspace(0.3, 3.0, len(s) - t - 1)
    cut = long_cycle.build_long_cycle_features(shocked, prefix="X")
    pd.testing.assert_frame_equal(full.iloc[:t + 1], cut.iloc[:t + 1])
    assert not full.iloc[t + 1:].equals(cut.iloc[t + 1:])


def test_values_on_hand_computable_series():
    idx = pd.bdate_range("2015-01-01", periods=800)
    s = pd.Series(np.exp(0.001 * np.arange(800)), index=idx)   # +0.1 %/day, log-linear, monotone
    f = long_cycle.build_long_cycle_features(s, prefix="X")
    last = f.iloc[-1]
    assert last["X_lc_ret_252d"] == pytest.approx(np.exp(0.252) - 1)
    assert last["X_lc_ret_756d"] == pytest.approx(np.exp(0.756) - 1)
    assert last["X_lc_mom_12_1"] == pytest.approx(np.exp(0.001 * 231) - 1)
    assert last["X_lc_rangepos_252d"] == pytest.approx(0.5)     # at the 1-year high
    assert last["X_lc_dd_ath"] == pytest.approx(0.0)
    assert f["X_lc_ret_756d"].iloc[:756].isna().all()           # full window required
    assert f["X_lc_ret_756d"].iloc[756:].notna().all()


def test_drawdown_range_and_signed_series():
    idx = pd.bdate_range("2015-01-01", periods=600)
    peak_then_half = pd.Series(np.r_[np.linspace(50, 100, 300), np.linspace(100, 50, 300)], index=idx)
    f = long_cycle.build_long_cycle_features(peak_then_half, prefix="P")
    assert f["P_lc_dd_ath"].iloc[-1] == pytest.approx(-0.5)
    assert f["P_lc_rangepos_252d"].iloc[-1] == pytest.approx(-0.5)   # at the 1-year low

    spread = pd.Series(np.sin(np.arange(900) / 40.0), index=pd.bdate_range("2015-01-01", periods=900))
    g = long_cycle.build_long_cycle_features(spread, prefix="S")
    # a series crossing zero has no meaningful drawdown ratio: missing, never +-inf
    assert g["S_lc_dd_ath"][spread <= 0].isna().all()
    assert np.isfinite(g.to_numpy()[~np.isnan(g.to_numpy())]).all()
    assert g["S_lc_rangepos_252d"].dropna().between(-0.5, 0.5).all()


def test_flat_window_is_missing_not_infinite():
    s = pd.Series(1.0, index=pd.bdate_range("2015-01-01", periods=400))
    f = long_cycle.build_long_cycle_features(s, prefix="F")
    assert f["F_lc_rangepos_252d"].iloc[260:].isna().all()
    assert f["F_lc_zscore_252d"].iloc[260:].isna().all()
    assert f["F_lc_volratio_21_252"].iloc[260:].isna().all()


def _config(families):
    return RunConfig.model_validate({
        "objective": {"target_symbol": "^T", "horizons": [5]},
        "features": {"families": families, "vol_models": []},
    })


def test_engine_adds_the_family_only_when_selected(monkeypatch):
    monkeypatch.setattr(engine, "download_ohlc", lambda *a, **k: None)
    raw = pd.DataFrame({"T": _prices(900).to_numpy(), "U": _prices(900, seed=4).to_numpy()},
                       index=pd.bdate_range("2015-01-01", periods=900))
    off = engine._build_base_feature_pool(raw, _config(["technical"]), "T")
    on = engine._build_base_feature_pool(raw, _config(["technical", "long_cycle"]), "T")
    added = set(on.columns) - set(off.columns)
    assert added and all("_lc_" in c for c in added)
    assert {"T_lc_ret_252d", "U_lc_ret_252d"} <= added
    assert "long_cycle" not in D.DEFAULT_FEATURE_FAMILIES
    assert "long_cycle" in forms.ALL_FEATURE_FAMILIES


def test_speed_audit_classifies_the_family():
    assert classify_feature("GSPC_lc_ret_252d") == "long_cycle"
    assert classify_feature("GSPC_lc_zscore_756d") == "long_cycle"
    assert classify_feature("GSPC_ret_20d") == "technical"
