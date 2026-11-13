"""Panneau d'une stratégie : attribution, témoins, journal des remplacements, plafonds de risque (rendu serveur)."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest
from fastapi.testclient import TestClient
from test_fund_selection import World

from patrick.fund import autopilot, store
from patrick.tracking import db as trackdb
from patrick.webapp.app import app

SIGNALS = [("2026-01-12", 3, 0.6), ("2026-01-13", 3, 0.6), ("2026-01-15", 0, 0.6)]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def _piloted(tmp_path, monkeypatch) -> str:
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    world = World(conn, monkeypatch)
    for target in ("AAPL", "^GSPC"):
        world.cell(target, 3, live=SIGNALS)
    sid = store.create_strategy(conn, "Pilote", "CTO", 100_000, "2026-01-05")
    autopilot.configure(conn, sid, {"max_class_share": 0.6})
    autopilot.run(conn, sid, dt.date(2026, 1, 15))
    autopilot.run(conn, sid, dt.date(2026, 1, 16))
    world.cell("AAPL", 3, live=SIGNALS, suffix="_b")              # un nouveau champion : l'ancien modèle est remplacé
    autopilot.run(conn, sid, dt.date(2026, 1, 16))
    conn.close()
    return sid


def test_the_panel_shows_attribution_witnesses_the_journal_and_the_risk_settings(client, tmp_path, monkeypatch):
    sid = _piloted(tmp_path, monkeypatch)

    panel = client.get(f"/api/fund/strategies/{sid}/panel")

    assert panel.status_code == 200
    for text in ("vient le résultat", "Par modèle (règle)", "Par sens", "Témoins : les mêmes ordres",
                 "Toujours acheteur", "Pile ou face", "Modèles remplacés", "Part max par classe", "Arrêt si repli sous le plus haut"):
        assert text in panel.text, text
    assert 'name="max_class_share"' in panel.text and 'value="60"' in panel.text
    assert client.get(f"/api/fund/strategies/{sid}/panel", headers={"Accept-Language": "en"}).status_code == 200


def test_an_empty_strategy_shows_none_of_the_reading_blocks(client):
    sid = fs.make_strategy(client)

    panel = client.get(f"/api/fund/strategies/{sid}/panel")

    assert panel.status_code == 200
    for text in ("vient le résultat", "Témoins : les mêmes ordres", "Modèles remplacés"):
        assert text not in panel.text
