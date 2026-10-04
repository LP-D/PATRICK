"""Cotations factices partagées par les tests du fonds : aucun réseau.

Importé par les fichiers `test_fund_*.py` (le dossier `tests/` est sur le
chemin d'import, comme `conftest`)."""
from __future__ import annotations

import datetime as dt
import json
import re

import numpy as np
import pandas as pd

from patrick.fund import prices, service

IDX = pd.bdate_range("2025-06-02", "2026-10-02")
# symbole -> (devise brute, prix de départ, dérive quotidienne)
FAKE = {
    "AAPL": ("USD", 200.0, 0.4), "MC.PA": ("EUR", 700.0, 0.5), "TTE.PA": ("EUR", 60.0, 0.05),
    "VOD.L": ("GBp", 70.0, 0.02), "EURUSD=X": ("USD", 1.10, 0.0004), "EURGBP=X": ("GBP", 0.85, 0.0),
    "ESZ26.CME": ("USD", 6000.0, 3.0), "^GSPC": ("USD", 6000.0, 3.0), "CLM26.NYM": ("USD", 70.0, 0.05),
    "CL=F": ("USD", 70.0, 0.05),
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
                       "volume": 5_000_000.0, "dividend": 0.0, "split": 0.0}, index=IDX)
    return df, ccy


def install(monkeypatch) -> None:
    CALLS.clear()
    for cache in ("_FAILED_UNTIL", "_RATE_CACHE"):          # caches de module : jamais partagés entre tests
        getattr(prices, cache, {}).clear()
    monkeypatch.setattr(prices, "download_bars", fake_download)
    monkeypatch.delenv("FRED_API_KEY", raising=False)


def freeze_today(monkeypatch) -> None:
    """Fige « aujourd'hui » au 2026-01-16 pour les tests de routes (les contrats expirent sinon avec le temps)."""
    monkeypatch.setattr(service, "current_date", lambda: TODAY)


def make_strategy(client, name="Macro CTO", **kw) -> str:
    body = {"name": name, "wrapper": "CTO", "initial_capital": 100_000, "opened_on": "2026-01-05", **kw}
    resp = client.post("/api/fund/strategies", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["strategy_id"]


def place(client, strategy_id, **kw) -> dict:
    body = {"instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4, "date": "2026-01-07", **kw}
    resp = client.post(f"/api/fund/strategies/{strategy_id}/orders", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def json_script(html: str, script_id: str):
    match = re.search(rf'<script id="{script_id}" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert match, script_id
    return json.loads(match.group(1))
