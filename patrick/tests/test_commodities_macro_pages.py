"""Route tests for the two new stats pages (feature/ticker-stats-panel):
`/commodities` (config/defaults.py::DEFAULT_TARGET_GROUPS "Matières
premières (futures)") and `/macro` ("Macro (FRED)"). Same style as
`test_history_webapp_smoke.py`: render the real Jinja templates through a
real FastAPI route, no seeded DB needed here (these pages list the STATIC
target-group config, not run history) -- and crucially NO network call:
the page itself only renders per-asset panel skeletons, actual price/stats
data is fetched client-side by `asset_stats.js` against
`/api/asset-stats/{symbol}` (tested separately, with `market_data`
monkeypatched, in `test_asset_stats_api.py`). A route that did the 20/43
yfinance+FRED fetches server-side would make this suite network-dependent
and slow -- exactly what the AJAX split avoids."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.config import defaults as D
from patrick.webapp.app import app
from patrick.webapp import forms


def test_commodities_page_returns_200():
    client = TestClient(app)
    resp = client.get("/commodities")
    assert resp.status_code == 200


def test_commodities_page_lists_every_asset_label_and_symbol():
    client = TestClient(app)
    resp = client.get("/commodities")
    for symbol, label in D.DEFAULT_TARGET_GROUPS["Matières premières (futures)"]:
        assert label in resp.text
        assert symbol in resp.text


def test_commodities_page_has_one_stats_panel_per_asset():
    client = TestClient(app)
    resp = client.get("/commodities")
    n_assets = len(D.DEFAULT_TARGET_GROUPS["Matières premières (futures)"])
    assert resp.text.count("asset-panel") >= n_assets
    # Each panel must carry its own symbol so `asset_stats.js` knows which
    # `/api/asset-stats/{symbol}` to call.
    slug = forms.slug_target("GC=F")
    assert f'data-symbol="GC=F"' in resp.text
    assert f'id="asset-{slug}"' in resp.text


def test_macro_page_returns_200():
    client = TestClient(app)
    resp = client.get("/macro")
    assert resp.status_code == 200


def test_macro_page_lists_every_asset_label_and_symbol():
    client = TestClient(app)
    resp = client.get("/macro")
    for symbol, label in D.DEFAULT_TARGET_GROUPS[D.FRED_TARGET_GROUP]:
        assert label in resp.text
        assert symbol in resp.text


def test_macro_page_has_one_stats_panel_per_asset():
    client = TestClient(app)
    resp = client.get("/macro")
    n_assets = len(D.DEFAULT_TARGET_GROUPS[D.FRED_TARGET_GROUP])
    assert resp.text.count("asset-panel") >= n_assets


def test_commodities_and_macro_reachable_from_nav():
    client = TestClient(app)
    resp = client.get("/")
    assert 'href="/commodities"' in resp.text
    assert 'href="/macro"' in resp.text
