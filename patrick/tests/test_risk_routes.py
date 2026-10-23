"""Page `/risque` et API `/api/risque/*` : lecture seule, paramètres bornés, cache court, aucune écriture dans le registre patrimoine."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from test_portfolio_risk import _prices

from patrick.tracking import db as trackdb
from patrick.wealth import ledger
from patrick.webapp import risk_routes
from patrick.webapp.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    series = _prices()
    monkeypatch.setattr(risk_routes.wealth_prices, "make_provider", lambda *a, **k: (lambda s: series.get(s)))
    risk_routes._cache.clear()
    risk_routes._provider = None
    conn = trackdb.connect()
    acc = ledger.create_account(conn, "PEA test", "PEA", "real")
    ledger.add_movement(conn, acc, {"ts": "2019-01-02", "kind": "deposit", "amount": 50_000})
    for sym, qty in (("A0", 100), ("A1", 80), ("A2", 60), ("A3", 40)):
        ledger.add_movement(conn, acc, {"ts": "2019-01-03", "kind": "buy", "symbol": sym, "quantity": qty, "price": float(series[sym].iloc[1])})
    conn.close()
    yield TestClient(app), acc
    risk_routes._cache.clear()
    risk_routes._provider = None


def _movement_count(acc: str) -> int:
    conn = trackdb.connect()
    try:
        return len(ledger.list_movements(conn, acc))
    finally:
        conn.close()


def test_page_and_navigation_entry(client):
    c, _ = client
    r = c.get("/risque")
    assert r.status_code == 200 and "rk-root" in r.text and 'href="/risque"' in c.get("/").text


def test_report_api_returns_finite_sections(client):
    c, acc = client
    before = _movement_count(acc)
    r = c.get("/api/risque/report?source=real&lookback=500")
    assert r.status_code == 200 and "NaN" not in r.text
    d = r.json()
    assert d["available"] and d["n_days"] == 500 and len(d["contributions"]) == 4 and len(d["stress"]) == 6 and len(d["var"]) == 4
    assert d["risky_share"] == pytest.approx(d["covered_weight"]) and 0 < d["risky_share"] <= 1
    assert _movement_count(acc) == before                                                            # lecture seule
    one = c.get(f"/api/risque/report?source={acc}&lookback=0").json()
    assert one["available"] and one["n_days"] > 500
    empty = c.get("/api/risque/report?source=fictive").json()
    assert empty["available"] is False and empty["risky_share"] == 0


def test_backtest_and_rebalance_api(client):
    c, _ = client
    bt = c.get("/api/risque/backtest?source=real&lookback=252&rebalance=21&cost=10")
    assert bt.status_code == 200 and "NaN" not in bt.text
    d = bt.json()
    assert d["available"] and [m["method"] for m in d["methods"]] == ["equal", "inv_vol", "hrp", "current"]
    gaps = c.get("/api/risque/rebalance?source=real&method=equal&tolerance=0.05&cost=10").json()
    assert gaps["available"] and len(gaps["rows"]) == 4 and abs(sum(r["gap"] for r in gaps["rows"])) < 1e-9


def test_parameters_are_validated(client):
    c, _ = client
    assert c.get("/api/risque/backtest?lookback=5").status_code == 422
    assert c.get("/api/risque/backtest?rebalance=0").status_code == 422
    assert c.get("/api/risque/backtest?cost=-1").status_code == 422
    assert c.get("/api/risque/report?lookback=-3").status_code == 422
    assert c.get("/api/risque/rebalance?method=magic").status_code == 422
    assert c.get("/api/risque/rebalance?tolerance=0.9").status_code == 422


def test_sources_lists_accounts_and_results_are_cached(client, monkeypatch):
    c, acc = client
    assert [s["account_id"] for s in c.get("/api/risque/sources").json()] == [acc]
    calls = []
    real = risk_routes.pr.risk_report
    monkeypatch.setattr(risk_routes.pr, "risk_report", lambda *a, **k: calls.append(1) or real(*a, **k))
    c.get("/api/risque/report?source=real&lookback=300")
    c.get("/api/risque/report?source=real&lookback=300")
    c.get("/api/risque/report?source=real&lookback=301")
    assert len(calls) == 2


def test_the_three_calls_of_a_page_share_one_price_provider(client, monkeypatch):
    c, _ = client
    made = []
    series = _prices()
    monkeypatch.setattr(risk_routes.wealth_prices, "make_provider", lambda *a, **k: made.append(1) or (lambda s: series.get(s)))
    risk_routes._provider = None
    for url in ("/api/risque/report?source=real", "/api/risque/backtest?source=real", "/api/risque/rebalance?source=real&method=equal"):
        assert c.get(url).status_code == 200
    assert made == [1]
    risk_routes._provider = (risk_routes._provider[0] - risk_routes.PROVIDER_TTL_S - 1, risk_routes._provider[1])
    c.get("/api/risque/report?source=real&lookback=333")
    assert made == [1, 1]
