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
from patrick.webapp import forms
from patrick.webapp.app import app


def test_commodities_page_returns_200():
    client = TestClient(app)
    resp = client.get("/commodities")
    assert resp.status_code == 200


def test_asset_statistics_explanations_are_clickable():
    response = TestClient(app).get("/commodities")
    assert 'data-term="asset_statistics"' in response.text
    assert 'data-term="asset_bar_windows"' in response.text
    assert "Fenêtres exprimées en barres de la série" not in response.text


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
    assert 'data-symbol="GC=F"' in resp.text
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


def test_macro_page_shows_every_fred_series_sectioned_by_domain():
    resp = TestClient(app).get("/macro")
    assert resp.status_code == 200
    text = resp.text
    for _, series in D.macro_page_sections():
        for sid, label in series:
            assert f'data-symbol="{sid}"' in text
            assert label in text
    assert text.count('class="card asset-panel"') == len(D.DEFAULT_UNIVERSE_FRED_SERIES)
    # Headline indicators first, then the domains in order.
    order = [text.index(f'id="macro-{key}"') for key, _ in D.macro_page_sections()]
    assert order == sorted(order)


def test_macro_page_tags_training_only_series():
    text = TestClient(app).get("/macro").text
    gdp_panel = text[text.index('data-symbol="GDP"'):text.index('data-symbol="GDP"') + 400]
    real_gdp_panel = text[text.index('data-symbol="GDPC1"'):text.index('data-symbol="GDPC1"') + 400]
    assert 'class="tag"' not in gdp_panel          # targetable
    assert 'class="tag"' in real_gdp_panel         # training data only


def test_asset_stats_api_serves_display_only_macro_series(monkeypatch):
    import pandas as pd
    from patrick.webapp import market_data

    def fake(symbol, source, period="5y"):
        assert source == "fred"
        dates = pd.bdate_range("2020-01-01", periods=200)
        return {"dates": [d.strftime("%Y-%m-%d") for d in dates],
                "closes": [100.0 + 0.05 * i for i in range(200)]}

    monkeypatch.setattr(market_data, "price_history", fake)
    client = TestClient(app)
    assert client.get("/api/asset-stats/GDPC1").status_code == 200
    assert client.get("/api/asset-stats/NOT_A_FRED_SERIES").status_code == 404
    assert "GDPC1" not in forms.TARGET_SOURCE_BY_SYMBOL


def test_slow_fred_series_are_fetched_over_their_whole_history(monkeypatch):
    import pandas as pd
    from patrick.webapp import market_data

    periods = {}

    def fake(symbol, source, period="5y"):
        periods[symbol] = period
        dates = pd.bdate_range("2020-01-01", periods=60)
        return {"dates": [d.strftime("%Y-%m-%d") for d in dates], "closes": [1.0 + i for i in range(60)]}

    monkeypatch.setattr(market_data, "price_history", fake)
    client = TestClient(app)
    for symbol in ("GDP", "UNRATE", "DGS10", "NFCI", "GC=F"):
        assert client.get(f"/api/asset-stats/{symbol}").status_code == 200
    assert periods == {"GDP": "max", "UNRATE": "max", "DGS10": "5y", "NFCI": "5y", "GC=F": "5y"}


def test_fred_price_history_is_cached_between_page_loads(monkeypatch):
    import pandas as pd
    from patrick.webapp import market_data

    calls = []

    def fake_reader(symbol, source, start, end):
        calls.append(symbol)
        return pd.Series([1.0, 2.0, 3.0], index=pd.bdate_range("2026-01-01", periods=3), name=symbol)

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr(market_data.web, "DataReader", fake_reader)
    market_data._fred_cache.clear()
    first = market_data.price_history("GDPC1", "fred", "5y")
    second = market_data.price_history("GDPC1", "fred", "5y")
    assert first == second and first["closes"] == [1.0, 2.0, 3.0]
    assert calls == ["GDPC1"]
    market_data._fred_cache.clear()


def test_commodities_and_macro_reachable_from_nav():
    client = TestClient(app)
    resp = client.get("/")
    assert 'href="/commodities"' in resp.text
    assert 'href="/macro"' in resp.text
