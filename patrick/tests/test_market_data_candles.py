"""`market_data.price_history` : bougies et volumes en plus des clôtures (yfinance), sans réseau (le fournisseur est simulé)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.webapp import market_data


class _Ticker:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def history(self, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        return self._frame


def _frame() -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-05", periods=5, tz="America/New_York")
    return pd.DataFrame({
        "Open": [10.0, 11.0, 12.0, np.nan, 14.0], "High": [11.0, 12.0, 13.0, 14.0, 15.0], "Low": [9.0, 10.0, 11.0, 12.0, 13.0],
        "Close": [10.5, 11.5, np.nan, 13.5, 14.5], "Volume": [100, 200, 300, np.nan, 500],
    }, index=idx)


def test_yfinance_history_returns_candles_and_volumes_aligned_on_the_closes(monkeypatch):
    monkeypatch.setattr(market_data.yf, "Ticker", lambda symbol: _Ticker(_frame()))
    out = market_data.price_history("^TEST", "yfinance", "1mo")
    n = len(out["closes"])
    assert n == 4                                   # la ligne sans clôture est écartée
    for key in ("opens", "highs", "lows", "volumes"):
        assert len(out[key]) == n, key
    assert out["highs"] == [11.0, 12.0, 14.0, 15.0]
    assert out["opens"][2] is None                  # case vide : null, pas de crash
    assert out["volumes"] == [100, 200, None, 500]


def test_fred_history_has_no_candles(monkeypatch):
    series = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2026-01-01", "2026-02-01", "2026-03-01"]))
    monkeypatch.setattr(market_data.web, "DataReader", lambda *a, **k: series)
    monkeypatch.delenv(market_data.FRED_API_KEY_ENV, raising=False)
    market_data._fred_cache.clear()
    out = market_data.price_history("FAKE", "fred", "1y")
    assert out["closes"] == [1.0, 2.0, 3.0]
    assert not any(k in out for k in ("opens", "highs", "lows", "volumes"))
