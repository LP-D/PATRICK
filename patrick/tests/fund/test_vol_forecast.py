"""A1 / A5 : prévision du niveau de volatilité (HAR-RV sur la variance de Garman-Klass) pour dimensionner les fonds."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.fund import vol_forecast as vf


def _garch_bars(n=900, seed=3):
    """Cours OHLC d'un GARCH(1,1) : volatilité en grappes, que le HAR doit suivre mieux qu'une moyenne de 60 jours."""
    rng = np.random.default_rng(seed)
    var, r = np.empty(n), np.empty(n)
    var[0] = 1e-4
    for t in range(n):
        if t:
            var[t] = 2e-6 + 0.12 * r[t - 1] ** 2 + 0.86 * var[t - 1]
        r[t] = np.sqrt(var[t]) * rng.standard_normal()
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.r_[100, close[:-1]] * np.exp(rng.normal(0, 0.1, n) * np.sqrt(var))
    hi = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.6, n)) * np.sqrt(var))
    lo = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.6, n)) * np.sqrt(var))
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close}, index=idx), np.sqrt(var)


def test_garman_klass_variance_is_rescaled_to_the_close_to_close_scale():
    df, _ = _garch_bars()
    v = vf.daily_variance(df)
    r2 = np.log(df["close"]).diff() ** 2
    assert v.dropna().mean() == pytest.approx(r2.dropna().mean(), rel=0.05)
    assert v.dropna().std() < r2.dropna().std()                         # bien moins bruitée qu'un rendement au carré
    no_ohlc = vf.daily_variance(df[["close"]])
    assert no_ohlc.dropna().equals(r2.dropna().rename("variance"))


def test_the_har_forecast_tracks_the_true_volatility_and_beats_the_trailing_one_in_qlike():
    df, true_sigma = _garch_bars()
    out = vf.har_sigma(df)
    assert out and 0.3 < out["sigma"] / true_sigma[-1] < 3 and out["trailing"] > 0 and 0 < out["persistence"] < 1.2
    ev = vf.evaluate(df)
    assert ev["n"] > 100 and ev["skill"] > 0                            # le HAR prévoit mieux que la volatilité glissante


def test_the_forecast_is_causal_and_needs_enough_history():
    df, _ = _garch_bars()
    cut = df.index[700]
    assert vf.har_sigma(df, cut)["as_of"] == cut.strftime("%Y-%m-%d")
    assert vf.har_sigma(df.iloc[:100]) is None and vf.evaluate(df.iloc[:300]) is None


def test_the_autopilot_accepts_the_har_volatility_and_refuses_an_unknown_model():
    from patrick.fund import autopilot, store
    assert autopilot.Settings.from_dict({"vol_model": "har"}).vol_model == "har"
    assert autopilot.Settings.from_dict({}).vol_model == "trailing" and autopilot.Settings().to_dict()["vol_model"] == "trailing"
    with pytest.raises(store.FundError, match="vol_model"):
        autopilot.Settings.from_dict({"vol_model": "garch"})
