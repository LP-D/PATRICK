"""Rapport mensuel d'un fonds (FO14) et stress tests de ses positions ouvertes (FO15), du 25/11."""
from __future__ import annotations

import fund_support as fs
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from test_fund_insight import DAY1, _piloted, _snapshot
from test_fund_selection import World

from patrick.fund import monthly_report


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


@pytest.fixture
def world(conn, monkeypatch):
    return World(conn, monkeypatch)


def _history(drop_2008: float):
    idx = pd.bdate_range("1999-01-01", "2026-01-30")
    s = pd.Series(np.linspace(100, 300, len(idx)), index=idx)
    s.loc["2007-10-10":"2009-03-09"] *= (1 + drop_2008)
    return lambda symbol: s


def test_open_positions_are_replayed_on_past_crises(conn, world):
    sid = _piloted(conn, world)
    rows = monthly_report.stress(_snapshot(conn, sid), price_of=_history(-0.5))
    gfc = next(r for r in rows if r["key"] == "gfc")
    assert gfc["sufficient"] and gfc["label"].startswith("crise financière")
    assert gfc["return_total"] > 0                       # le pilote est vendeur des deux cellules : une chute de 50 % lui profite


def test_the_monthly_report_lists_performance_attribution_orders_and_stress(conn, world):
    sid = _piloted(conn, world)
    title, lines = monthly_report.report_lines(conn, sid, "2026-01", today=DAY1, price_of=_history(-0.5))
    text = "\n".join(lines)
    assert "2026-01" in title and "PERFORMANCE" in text and "ATTRIBUTION" in text and "STRESS TESTS" in text
    assert "ORDRES DU MOIS (2)" in text and "POSITIONS OUVERTES (2)" in text
    pdf = monthly_report.report_pdf(conn, sid, "2026-01", today=DAY1, price_of=_history(-0.5))
    assert pdf.startswith(b"%PDF")


def test_the_report_route_refuses_a_bad_month_and_an_unknown_fund(conn, world):
    sid = _piloted(conn, world)
    client = TestClient(__import__("patrick.webapp.app", fromlist=["app"]).app)
    assert client.get(f"/api/fund/strategies/{sid}/report.pdf?month=2026-1").status_code == 400
    assert client.get("/api/fund/strategies/inconnue/report.pdf?month=2026-01").status_code == 404
