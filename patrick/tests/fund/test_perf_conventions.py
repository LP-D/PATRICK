"""Conventions communes des mesures de performance (`core/perf.py`, AM2/CO4/CO5 du 25/11)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from patrick.analysis import stats_core
from patrick.core import perf
from patrick.simulate import metrics


def _returns(freq: str, n: int = 500, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, 0.01, n), index=pd.date_range("2020-01-01", periods=n, freq=freq))


def test_sortino_uses_the_downside_deviation_over_every_session():
    """CO4 : l'ancien calcul prenait l'écart-type des seules séances négatives, autour de leur propre moyenne."""
    r = _returns("B")
    dd = np.sqrt(np.mean(np.minimum(r.to_numpy(), 0) ** 2))
    assert metrics.sortino_ratio(r) == pytest.approx(r.mean() / dd * np.sqrt(252))
    assert metrics.sortino_ratio(r) == pytest.approx(stats_core.sortino(r.to_numpy()))
    old = r.mean() / r[r < 0].std(ddof=1) * np.sqrt(252)
    assert old > metrics.sortino_ratio(r)                      # l'ancien ratio était surévalué


def test_a_series_with_weekends_is_annualised_on_365_days_and_a_business_day_one_on_252():
    assert perf.periods_per_year(_returns("D").index) == 365
    assert perf.periods_per_year(_returns("B").index) == 252
    assert perf.periods_per_year(None) == 252
    crypto = _returns("D")
    assert metrics.sharpe_ratio(crypto) == pytest.approx(crypto.mean() / crypto.std(ddof=1) * np.sqrt(365))
    assert metrics.sharpe_ratio(crypto, periods=252) == pytest.approx(crypto.mean() / crypto.std(ddof=1) * np.sqrt(252))


def test_sortino_without_any_loss_is_undefined():
    r = pd.Series([0.01] * 30, index=pd.date_range("2020-01-01", periods=30, freq="B"))
    assert np.isnan(metrics.sortino_ratio(r))
