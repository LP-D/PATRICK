"""D22 : la série d'une stratégie en JSON, pour la superposer à une autre (base 100) sur le graphique de /fonds. Aucun réseau."""
from __future__ import annotations

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick.fund import store
from patrick.tracking import db as trackdb
from patrick.webapp.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def test_a_strategy_series_is_served_as_daily_net_values(client, tmp_path):
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    sid = store.create_strategy(conn, "Fonds A", "CTO", 100_000, "2026-01-05")
    conn.close()

    out = client.get(f"/api/fund/strategies/{sid}/series").json()

    assert out["strategy_id"] == sid and out["name"] == "Fonds A"
    assert out["series"] and all(set(p) == {"t", "nav"} for p in out["series"])
    assert out["series"][0]["nav"] == pytest.approx(100_000)          # aucun ordre : la valeur reste le capital


def test_an_unknown_strategy_is_a_404(client):
    assert client.get("/api/fund/strategies/inconnue/series").status_code == 404


def test_the_panel_offers_the_comparison_select(client, tmp_path):
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    sid = store.create_strategy(conn, "Fonds A", "CTO", 100_000, "2026-01-05")
    conn.close()
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert 'id="fund-compare-select"' in html and f'data-self="{sid}"' in html and 'id="fund-chart-dd"' in html
