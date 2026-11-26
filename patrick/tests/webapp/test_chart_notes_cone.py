"""Notes libres datées sur la courbe (VI24) et cône de prévision (VI1), du 26/11."""
from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from patrick.tracking import chart_notes
from patrick.tracking import db as trackdb
from patrick.webapp import app as app_module
from patrick.webapp.app import _forecast_cone, app


def test_notes_are_added_listed_shown_as_chart_events_and_deleted():
    client = TestClient(app)
    added = client.post("/api/chart-notes/%5EGSPC", json={"day": "2026-11-20", "text": "Annonce de la Fed"}).json()
    assert added["day"] == "2026-11-20"
    assert client.post("/api/chart-notes/%5EGSPC", json={"day": "hier", "text": "x"}).status_code == 400
    assert client.post("/api/chart-notes/%5EGSPC", json={"day": "2026-11-20", "text": "x" * 200}).status_code == 400
    notes = client.get("/api/chart-notes/%5EGSPC").json()["notes"]
    assert [n["text"] for n in notes] == ["Annonce de la Fed"]
    (event,) = chart_notes.as_events(notes)
    assert event["kind"] == "note" and event["label"].startswith("✎")
    assert client.delete(f"/api/chart-notes/%5EGSPC/{added['note_id']}").json()["deleted"] is True
    conn = trackdb.connect()
    try:
        assert chart_notes.list_notes(conn, "^GSPC") == []
    finally:
        conn.close()


def test_the_cone_uses_the_har_forecast_or_the_trailing_volatility():
    idx = pd.bdate_range("2023-01-02", periods=400)
    closes = list(100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, 0.01, 400))))
    cone = _forecast_cone({"closes": closes, "dates": [d.strftime("%Y-%m-%d") for d in idx]})
    assert cone["basis"] in ("har", "trailing") and 0.003 < cone["sigma"] < 0.03
    assert _forecast_cone({"closes": closes[:50], "dates": [d.strftime("%Y-%m-%d") for d in idx[:50]]}) is None


def test_the_asset_stats_api_carries_the_cone_and_notes(monkeypatch):
    idx = pd.bdate_range("2023-01-02", periods=300)
    closes = list(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, 300))))
    monkeypatch.setattr(app_module.market_data, "price_history", lambda s, src, period: {"closes": closes, "dates": [d.strftime("%Y-%m-%d") for d in idx]})
    client = TestClient(app)
    client.post("/api/chart-notes/%5EGSPC", json={"day": "2024-01-05", "text": "Repère"})
    data = client.get("/api/asset-stats/%5EGSPC?events=1").json()
    assert data["cone"]["sigma"] > 0 and any(e["kind"] == "note" for e in data["events"])
