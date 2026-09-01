"""Route tests for `/api/asset-stats/{symbol}` (feature/ticker-stats-panel) --
the endpoint `asset_stats.js` calls per asset on `/commodities` and
`/macro`. Same data-access path as the pre-existing `/api/preview/{symbol}`
(`market_data.price_history`, resolved through
`forms.TARGET_SOURCE_BY_SYMBOL`) monkeypatched here so the test never hits
yfinance/FRED -- matches how `webapp/asset_stats.py::compute_stats` is unit
tested directly in `test_asset_stats.py` without going through the route at
all; this file only checks the route's plumbing (symbol resolution, 404,
JSON shape)."""
from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from patrick.webapp import market_data
from patrick.webapp.app import app


def _fake_price_history(symbol, source, period="5y"):
    dates = pd.bdate_range("2020-01-01", periods=200)
    closes = [100.0 + 0.05 * i for i in range(200)]
    return {"dates": [d.strftime("%Y-%m-%d") for d in dates], "closes": closes}


def test_asset_stats_api_unknown_symbol_404():
    client = TestClient(app)
    resp = client.get("/api/asset-stats/NOT_A_REAL_SYMBOL")
    assert resp.status_code == 404


def test_asset_stats_api_returns_computed_stats_for_known_symbol(monkeypatch):
    monkeypatch.setattr(market_data, "price_history", _fake_price_history)
    client = TestClient(app)
    resp = client.get("/api/asset-stats/GC=F")
    assert resp.status_code == 200
    data = resp.json()
    assert data["n_obs"] == 200
    assert data["insufficient_history"] is False
    assert "1" in data["returns"]
    assert data["zscore_60d"] is not None
    assert data["volatility"] is not None


def test_asset_stats_api_works_for_fred_symbol(monkeypatch):
    monkeypatch.setattr(market_data, "price_history", _fake_price_history)
    client = TestClient(app)
    resp = client.get("/api/asset-stats/DGS10")
    assert resp.status_code == 200


def test_asset_stats_api_passes_through_upstream_error(monkeypatch):
    def _erroring(symbol, source, period="5y"):
        return {"dates": [], "closes": [], "error": "network down"}

    monkeypatch.setattr(market_data, "price_history", _erroring)
    client = TestClient(app)
    resp = client.get("/api/asset-stats/GC=F")
    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] == "network down"
    assert data["insufficient_history"] is True
