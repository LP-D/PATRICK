"""Carte des marchés de la page Indices (VI14 du 26/11)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.webapp import alerts
from patrick.webapp.app import app


def test_tiles_are_grouped_by_region_in_time_zone_order(monkeypatch):
    world = {"^GSPC": {"label": "S&P 500", "d1": 0.8, "d5": 2.1}, "^N225": {"label": "Nikkei 225", "d1": -1.2, "d5": -0.4},
             "^FCHI": {"label": "CAC 40", "d1": 0.1, "d5": 0.3}}
    monkeypatch.setattr(alerts, "get_cached", lambda: {"world": world})
    regions = alerts.world_map()
    assert [r["region"] for r in regions] == ["asia", "europe", "americas"]
    assert regions[2]["tiles"][0]["symbol"] == "^GSPC"
    html = TestClient(app).get("/indices").text
    assert "Carte des marchés" in html and "Nikkei 225" in html and "-1,20\xa0%" in html


def test_no_ticker_yet_means_no_map(monkeypatch):
    monkeypatch.setattr(alerts, "get_cached", dict)
    assert alerts.world_map() == []
    assert "Carte des marchés" not in TestClient(app).get("/indices").text


def test_a_closed_market_keeps_its_own_last_session_instead_of_a_copied_zero(tmp_path, monkeypatch):
    import numpy as np
    import pandas as pd

    from patrick.data.sources.yfinance_source import clean_symbol
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    days = pd.bdate_range(end="2026-11-26", periods=12)
    nikkei = np.linspace(100, 111, len(days))                  # Tokyo a coté aujourd'hui : +1 sur la dernière séance
    cac = np.linspace(200, 211, len(days))
    cac[-1] = np.nan                                           # Paris pas encore : la ligne du jour est vide pour lui
    frame = pd.DataFrame({clean_symbol("^N225"): nikkei, clean_symbol("^FCHI"): cac}, index=days)
    monkeypatch.setattr(alerts, "download_batch", lambda tickers, start: frame)
    alerts._compute_once()
    world = alerts.get_cached()["world"]
    assert world["^N225"]["d1"] == round((111 / 110 - 1) * 100, 2) and world["^N225"]["asof"] == "2026-11-26"
    assert world["^FCHI"]["d1"] == round((210 / 209 - 1) * 100, 2) and world["^FCHI"]["asof"] == "2026-11-25"
