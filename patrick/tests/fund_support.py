"""Cotations factices partagées par les tests du fonds : aucun réseau.

Importé par les fichiers `test_fund_*.py` (le dossier `tests/` est sur le
chemin d'import, comme `conftest`)."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from patrick.fund import prices

IDX = pd.bdate_range("2025-06-02", "2026-10-02")
# symbole -> (devise brute, prix de départ, dérive quotidienne)
FAKE = {
    "AAPL": ("USD", 200.0, 0.4), "MC.PA": ("EUR", 700.0, 0.5), "TTE.PA": ("EUR", 60.0, 0.05),
    "VOD.L": ("GBp", 70.0, 0.02), "EURUSD=X": ("USD", 1.10, 0.0004), "EURGBP=X": ("GBP", 0.85, 0.0),
    "ESZ26.CME": ("USD", 6000.0, 3.0), "^GSPC": ("USD", 6000.0, 3.0),
}
TODAY = dt.date(2026, 1, 16)
CALLS: list[tuple[str, str | None]] = []


def day_index(day: str) -> int:
    return list(IDX).index(pd.Timestamp(day))


def price_on(symbol: str, day: str) -> float:
    _, p0, drift = FAKE[symbol]
    return p0 + drift * day_index(day)


def fx_on(day: str) -> float:
    """Euros par dollar : inverse du cours EURUSD=X."""
    return 1.0 / price_on("EURUSD=X", day)


def fake_download(symbol, start=None):
    CALLS.append((symbol, start))
    if symbol not in FAKE:
        return None, None
    ccy, p0, drift = FAKE[symbol]
    close = p0 + drift * np.arange(len(IDX))
    df = pd.DataFrame({"open": close, "high": close * 1.002, "low": close * 0.998, "close": close,
                       "volume": 5_000_000.0, "dividend": 0.0}, index=IDX)
    return df, ccy


def install(monkeypatch) -> None:
    CALLS.clear()
    monkeypatch.setattr(prices, "download_bars", fake_download)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
