"""D8 : la volatilité prévue s'affiche à part sur la page d'un actif (HAR contre glissante, QLIKE), jamais avec les directions."""
from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from patrick.webapp import market_data
from patrick.webapp.app import app


def _history(symbol, source, period="1y"):
    rng = np.random.default_rng(1)
    n = 800
    var, r = np.empty(n), np.empty(n)
    var[0] = 1e-4
    for t in range(n):
        if t:
            var[t] = 2e-6 + 0.12 * r[t - 1] ** 2 + 0.86 * var[t - 1]
        r[t] = np.sqrt(var[t]) * rng.standard_normal()
    close = 100 * np.exp(np.cumsum(r))
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2023-01-02", periods=n)]
    return {"dates": dates, "closes": list(close), "opens": list(close * 0.999), "highs": list(close * (1 + 2 * np.sqrt(var))),
            "lows": list(close * (1 - 2 * np.sqrt(var)))}


def test_the_fragment_shows_the_forecast_the_trailing_volatility_and_the_qlike_gain(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    monkeypatch.setattr(market_data, "price_history", _history)
    html = TestClient(app).get("/fragments/vol-forecast/%5EGSPC").text
    assert "HAR" in html and "Garman-Klass" in html and "QLIKE" in html


def test_a_target_page_has_the_volatility_section_apart_from_the_signals(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    html = TestClient(app).get("/targets/%5EGSPC").text
    assert 'id="volatilite"' in html and "/fragments/vol-forecast/" in html
    assert html.index('id="signaux"') < html.index('id="volatilite"')
