"""Un ajustement ARIMA divergent (non-stationnaire / non-inversible) rend des résidus astronomiques : `XLV_arima_resid`
valait 1.7e297 dans le pool de la cible T10YIE, ce qui a fait refuser la matrice par XGBoost (voir
`tests/test_float32_range.py`). La feature est maintenant mise à « manquante » à la source.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features import vol_models


def _series(n=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=n)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)


def test_a_healthy_fit_keeps_its_residuals():
    out = vol_models.arima_resid(_series())
    assert out.notna().sum() > 300
    assert np.abs(out.dropna()).max() < 1.0


def test_a_diverged_fit_is_set_to_missing(monkeypatch, capsys):
    s = _series()

    class FakeResult:
        def __init__(self, n):
            self.resid = np.concatenate([np.full(n - 1, 1e-3), [1.7e297]])

        def apply(self, values):
            return FakeResult(len(values))

    class FakeArima:
        def __init__(self, values, order):
            self.n = len(values)

        def fit(self):
            return FakeResult(self.n)

    import statsmodels.tsa.arima.model as arima_model
    monkeypatch.setattr(arima_model, "ARIMA", FakeArima)

    out = vol_models.arima_resid(s)

    assert out.isna().all()
    assert "diverged fit" in capsys.readouterr().out
