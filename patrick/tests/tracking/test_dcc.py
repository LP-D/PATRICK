"""A2 : DCC-GARCH -- covariance du lendemain, corrélations qui évoluent."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.tracking import covariance, dcc


def _two_regimes(n=900, seed=2):
    """Deux actifs décorrélés, puis très corrélés et plus volatils sur les 150 derniers jours (une « crise »)."""
    rng = np.random.default_rng(seed)
    rows = []
    for t in range(n):
        rho, vol = (0.9, 0.025) if t >= n - 150 else (0.0, 0.01)
        c = np.array([[1, rho], [rho, 1]]) * vol ** 2
        rows.append(rng.multivariate_normal([0, 0], c))
    idx = pd.bdate_range("2022-01-03", periods=n)
    return pd.DataFrame(rows, index=idx, columns=["A", "B"])


def test_dcc_sees_the_recent_crisis_correlation_that_a_full_sample_estimate_dilutes():
    r = _two_regimes()
    cov, params = dcc.dcc_covariance(r)
    corr_dcc = cov.loc["A", "B"] / np.sqrt(cov.loc["A", "A"] * cov.loc["B", "B"])
    corr_full = r.corr().loc["A", "B"]
    assert corr_dcc > 0.6 > corr_full                                   # le DCC suit la crise, l'échantillon complet la dilue
    assert 0 <= params["a"] and 0 <= params["b"] and params["persistence"] < 1
    assert np.sqrt(cov.loc["A", "A"]) == pytest.approx(0.025, rel=0.5)  # volatilité prévue proche de celle de la crise


def test_point_in_time_covariance_accepts_the_dcc_estimator():
    r = _two_regimes()
    prices = {c: 100 * (1 + r[c]).cumprod() for c in r.columns}
    cov = covariance.point_in_time_covariance(prices, r.index[-1], estimator="dcc")
    assert cov.attrs["estimator"] == "dcc" and "a" in cov.attrs["dcc"] and cov.shape == (2, 2)
    with pytest.raises(ValueError):
        dcc.dcc_covariance(r.iloc[:100])
