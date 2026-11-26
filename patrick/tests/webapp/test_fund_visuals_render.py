"""Visuels d'un fonds affichés pour de vrai (26/11) : treemap des positions (VI2), corrélation (VI4), nuage risque / rendement (VI6)."""
from __future__ import annotations

import re

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick.webapp.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def test_panel_draws_one_tile_per_open_position_and_offers_the_correlation(client):
    sid = fs.make_strategy(client)
    fs.place(client, sid, instrument_kind="equity", symbol="AAPL", quantity=10)
    fs.place(client, sid, instrument_kind="equity", symbol="MC.PA", quantity=4)
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert 'class="fund-treemap"' in html
    tiles = re.findall(r'class="tm-tile tm-(?:up|down)" style="left: ([\d.]+)%; top: ([\d.]+)%; width: ([\d.]+)%; height: ([\d.]+)%', html)
    assert len(tiles) == 2
    assert abs(sum(float(w) * float(h) for _, _, w, h in tiles) - 100 * 100) < 5     # les tuiles couvrent toute la boîte
    assert f'data-corr-url="/fragments/fund-correlation/{sid}"' in html
    assert client.get(f"/fragments/fund-correlation/{sid}").status_code == 200


def test_overview_places_each_strategy_on_the_risk_return_scatter(client):
    for name, symbol in (("Actions US", "AAPL"), ("Luxe", "MC.PA")):
        sid = fs.make_strategy(client, name=name)
        fs.place(client, sid, instrument_kind="equity", symbol=symbol, quantity=10)
    html = client.get("/fragments/fund-overview").text
    assert 'class="fund-scatter"' in html
    assert html.count('<g class="sc-dot') == 2 and "Actions US" in html and "Luxe" in html


def test_correlation_reads_the_prices_the_fund_already_stores(client):
    import numpy as np
    import pandas as pd

    from patrick.fund import prices
    from patrick.tracking import db as trackdb
    sid = fs.make_strategy(client)
    fs.place(client, sid, instrument_kind="equity", symbol="AAPL", quantity=10)
    fs.place(client, sid, instrument_kind="equity", symbol="MC.PA", quantity=4)
    days = pd.bdate_range(end="2026-01-15", periods=200)
    rng = np.random.default_rng(3)
    common = rng.normal(0, 0.01, len(days)).cumsum()
    conn = trackdb.connect()
    try:
        for sym, noise in (("AAPL", 0.002), ("MC.PA", 0.003)):
            close = 100 * np.exp(common + rng.normal(0, noise, len(days)))
            df = pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0, "dividend": 0.0, "split": 0.0},
                              index=days)
            prices.save_bars(conn, sym, df, "USD", replace=True)
    finally:
        conn.close()
    html = client.get(f"/fragments/fund-correlation/{sid}").text
    assert 'class="corr-grid"' in html and html.count('class="corr-cell corr-pos"') == 4
