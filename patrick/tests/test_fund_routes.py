"""API /api/fund/* de bout en bout par FastAPI, base isolée, cotations factices (aucun réseau)."""
from __future__ import annotations

import json

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick.webapp import fund_routes
from patrick.webapp.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


JSON = {"Content-Type": "application/json"}


def strategy(client, **kw):
    body = {"name": "Macro CTO", "wrapper": "CTO", "initial_capital": 100_000, "opened_on": "2026-01-05", **kw}
    resp = client.post("/api/fund/strategies", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["strategy_id"]


def equity(**kw):
    return {"instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4, "date": "2026-01-07", **kw}


def test_strategy_lifecycle(client):
    sid = strategy(client)
    detail = client.get(f"/api/fund/strategies/{sid}/detail")
    assert detail.status_code == 200 and detail.json()["kpis"]["nav"] == 100_000
    assert client.patch(f"/api/fund/strategies/{sid}", json={"name": "Renommée"}).json() == {"ok": True}
    assert client.get(f"/api/fund/strategies/{sid}/detail").json()["strategy"]["name"] == "Renommée"
    assert client.get("/api/fund/overview").json()["fund"]["n_strategies"] == 1
    client.patch(f"/api/fund/strategies/{sid}", json={"archived": True})
    assert client.get("/api/fund/overview").json()["fund"]["n_strategies"] == 0
    assert client.delete(f"/api/fund/strategies/{sid}").json() == {"ok": True}
    assert client.get(f"/api/fund/strategies/{sid}/detail").status_code == 404
    assert client.delete(f"/api/fund/strategies/{sid}").status_code == 404
    assert client.patch(f"/api/fund/strategies/{sid}", json={"name": "x"}).status_code == 404


def test_invalid_input_is_a_400_with_the_reason(client):
    assert client.post("/api/fund/strategies", json={"name": "", "wrapper": "CTO", "initial_capital": 1,
                                                     "opened_on": "2026-01-05"}).status_code == 400
    resp = client.post("/api/fund/strategies", json={"name": "PEA", "wrapper": "PEA", "initial_capital": 200_000,
                                                     "opened_on": "2026-01-05"})
    assert resp.status_code == 400 and "plafond" in resp.json()["detail"]
    assert client.post("/api/fund/strategies", content=b"not json", headers=JSON).status_code == 400
    assert client.post("/api/fund/strategies", content=b"[1]", headers=JSON).status_code == 400
    sid = strategy(client)
    assert client.patch(f"/api/fund/strategies/{sid}", json={"name": " "}).status_code == 400


def test_quote_never_writes_and_explains_refusals(client):
    sid = strategy(client)
    ok = client.post("/api/fund/quote", json={"strategy_id": sid, **equity()}).json()
    assert ok["ok"] and ok["preview"]["quantity"] == 4 and ok["preview"]["fees"]["seed"]
    refused = client.post("/api/fund/quote", json={"strategy_id": sid, **equity(side="short")}).json()
    assert not refused["ok"] and any("découvert" in m for m in refused["blocking"])
    assert client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"] == []


def test_place_order_uses_the_quoted_seed_and_a_refusal_is_a_422_with_the_blocking_list(client):
    sid = strategy(client)
    q = client.post("/api/fund/quote", json={"strategy_id": sid, **equity()}).json()["preview"]
    placed = client.post(f"/api/fund/strategies/{sid}/orders",
                         json={**equity(), "fee_seed": q["fees"]["seed"], "position_id": q["position_id"]})
    assert placed.status_code == 200
    assert placed.json()["preview"]["fees"]["total"] == q["fees"]["total"] and placed.json()["order_id"]
    refused = client.post(f"/api/fund/strategies/{sid}/orders", json=equity(quantity=100_000))
    assert refused.status_code == 422
    assert any("insuffisant" in m for m in refused.json()["detail"]["blocking"])
    assert client.post(f"/api/fund/strategies/{sid}/orders", json=equity(symbol="ZZZZ")).status_code == 422
    assert client.post(f"/api/fund/strategies/{sid}/orders", json={"instrument_kind": "bond"}).status_code == 400
    assert client.post("/api/fund/strategies/str_missing/orders", json=equity()).status_code == 400
    assert len(client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"]) == 1


def test_correct_adjust_and_delete_a_position(client):
    sid = strategy(client)
    opened = client.post(f"/api/fund/strategies/{sid}/orders", json=equity()).json()
    pid = opened["preview"]["position_id"]
    fixed = client.patch(f"/api/fund/orders/{opened['order_id']}", json={"quantity": 6, "date": "2026-01-07"})
    assert fixed.status_code == 200 and fixed.json()["preview"]["quantity"] == 6
    reduce = client.post(f"/api/fund/strategies/{sid}/orders",
                         json={"action": "reduce", "position_id": pid, "quantity": 2, "date": "2026-01-09"})
    assert reduce.status_code == 200
    assert client.patch(f"/api/fund/orders/{reduce.json()['order_id']}", json={"quantity": 1}).status_code == 400
    assert client.patch("/api/fund/orders/9999", json={"quantity": 1}).status_code == 400
    assert client.patch(f"/api/fund/orders/{opened['order_id']}", json={"quantity": 1_000_000}).status_code == 422
    detail = client.get(f"/api/fund/strategies/{sid}/detail").json()
    assert detail["positions"][0]["quantity"] == 4
    assert client.delete(f"/api/fund/positions/{pid}").json() == {"ok": True}
    assert client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"] == []
    assert client.delete(f"/api/fund/positions/{pid}").status_code == 404


def test_instrument_search_and_futures_catalog(client, monkeypatch):
    seen = []

    def fake_search(query, kind):
        seen.append((query, kind))
        return [{"symbol": "MC.PA", "name": "LVMH", "exchange": "Paris", "type": "EQUITY"}]
    monkeypatch.setattr(fund_routes, "search_symbols", fake_search)
    assert client.get("/api/fund/instruments/search?q=l").json() == {"results": []} and seen == []
    found = client.get("/api/fund/instruments/search?q=lvmh&kind=etf").json()
    assert found["results"][0]["symbol"] == "MC.PA" and seen == [("lvmh", "etf")]
    catalog = client.get("/api/fund/futures/catalog").json()["futures"]
    es = next(f for f in catalog if f["root"] == "ES")
    assert es["multiplier"] == 50 and es["contracts"][0]["label"] == "H26"       # au 2026-01-16 (mars 2026)
    assert es["contracts"][0]["symbol"] == "ESH26.CME"


def test_search_symbols_filters_yahoo_quotes_by_kind(monkeypatch):
    quotes = [{"symbol": "MC.PA", "shortname": "LVMH", "exchDisp": "Paris", "quoteType": "EQUITY"},
              {"symbol": "CW8.PA", "longname": "MSCI World", "quoteType": "ETF"},
              {"symbol": "^GSPC", "shortname": "S&P 500", "quoteType": "INDEX"},
              {"symbol": "AAA", "quoteType": "OPTION"}, {"quoteType": "EQUITY"}]
    monkeypatch.setattr(fund_routes.symbols, "yahoo_search", lambda q: quotes)
    assert [r["symbol"] for r in fund_routes.search_symbols("x", "equity")] == ["MC.PA"]
    assert [r["symbol"] for r in fund_routes.search_symbols("x", "etf")] == ["CW8.PA"]
    assert [r["symbol"] for r in fund_routes.search_symbols("x", "cfd")] == ["MC.PA", "CW8.PA", "^GSPC"]
    assert fund_routes.search_symbols("x", "equity")[0] == {"symbol": "MC.PA", "name": "LVMH", "exchange": "Paris",
                                                           "type": "EQUITY"}


@pytest.fixture
def lenient(tmp_path, monkeypatch):
    """Client qui renvoie un 500 au lieu de relancer l'exception du serveur."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app, raise_server_exceptions=False)


def test_malformed_values_in_a_json_body_are_a_400_or_422_never_a_500(lenient):
    client = lenient
    base = {"name": "Macro", "wrapper": "CTO", "initial_capital": 100_000, "opened_on": "2026-01-05"}
    for patch in ({"name": 5}, {"name": ["a"]}, {"wrapper": ["CTO"]}, {"initial_capital": [1]},
                  {"opened_on": ["2026-01-05"]}, {"opened_on": None}, {"opened_on": "n'importe quoi"}):
        resp = client.post("/api/fund/strategies", json={**base, **patch})
        assert resp.status_code == 400, (patch, resp.status_code, resp.text)
    sid = strategy(client)
    for patch in ({"name": 5}, {"name": ["x"]}, {"name": {"a": 1}}):
        assert client.patch(f"/api/fund/strategies/{sid}", json=patch).status_code == 400, patch
    for patch in ({"date": "nope"}, {"fee_seed": "abc"}, {"spec": "abc"}, {"spec": [1]}, {"note": {"a": 1}},
                  {"position_id": ["p"]}):
        resp = client.post(f"/api/fund/strategies/{sid}/orders", json={**equity(fees_mode="estimated"), **patch})
        assert resp.status_code in (400, 422), (patch, resp.status_code, resp.text)
    for patch in ({"date": "nope"}, {"fee_seed": "abc"}, {"spec": "abc"}, {"spec": [1]}, {"note": {"a": 1}},
                  {"position_id": ["p"]}, {"strategy_id": ["x"]}):      # l'aperçu lit la stratégie dans le corps
        quoted = client.post("/api/fund/quote", json={"strategy_id": sid, **equity(fees_mode="estimated"), **patch})
        assert quoted.status_code == 200 and quoted.json()["ok"] is False, (patch, quoted.text)
    assert client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"] == []


def test_json_routes_refuse_a_body_that_is_not_declared_as_json(client):
    """Un POST « simple » (text/plain) venu d'un autre site ne doit rien écrire : 415."""
    sid = strategy(client)
    plain = {"Content-Type": "text/plain"}
    body = json.dumps({"strategy_id": sid, **equity()})
    assert client.post("/api/fund/quote", content=body, headers=plain).status_code == 415
    assert client.post(f"/api/fund/strategies/{sid}/orders", content=body, headers=plain).status_code == 415
    assert client.post("/api/fund/strategies", content=json.dumps({"name": "x", "wrapper": "CTO", "initial_capital": 1,
                                                                   "opened_on": "2026-01-05"}),
                       headers=plain).status_code == 415
    assert client.patch(f"/api/fund/strategies/{sid}", content=json.dumps({"name": "y"}), headers=plain).status_code == 415
    assert client.patch("/api/fund/orders/1", content=json.dumps({"quantity": 1}), headers=plain).status_code == 415
    assert client.post(f"/api/fund/strategies/{sid}/orders", content=b"{}", headers={}).status_code == 415
    assert client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"] == []
    ok = client.post("/api/fund/quote", content=body, headers={"Content-Type": "application/json; charset=utf-8"})
    assert ok.status_code == 200 and ok.json()["ok"]


def test_the_listed_contracts_of_one_root_have_their_own_route(client):
    resp = client.get("/api/fund/futures/ES/contracts")
    assert resp.status_code == 200
    data = resp.json()
    assert data["root"] == "ES" and data["contracts"][0]["symbol"] == "ESH26.CME" and len(data["contracts"]) >= 4
    assert client.get("/api/fund/futures/XX/contracts").status_code == 404
