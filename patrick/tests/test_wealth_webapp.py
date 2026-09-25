"""Roadmap bloc 4 -- /patrimoine, /patrimoine/comptes/{id}, /mouvements and
/api/wealth/* end to end through FastAPI, on an isolated database, with a
dict price provider (no network)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from patrick.wealth import performance
from patrick.webapp import wealth_routes
from patrick.webapp.app import app

DAYS = pd.bdate_range("2024-01-01", periods=200)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    rng = np.random.default_rng(0)
    prices = {
        "MC.PA": pd.Series(700 * np.cumprod(1 + rng.normal(0, 0.01, len(DAYS))), index=DAYS),
        "^STOXX50E": pd.Series(4500 * np.cumprod(1 + rng.normal(0, 0.008, len(DAYS))), index=DAYS),
    }
    monkeypatch.setattr(wealth_routes, "price_provider", lambda: performance.dict_price_provider(prices))
    return TestClient(app)


def _account(client, **kw):
    body = {"name": "PEA test", "kind": "PEA", "mode": "real", "opened_on": "2024-01-01", **kw}
    resp = client.post("/api/wealth/accounts", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["account_id"]


def test_account_lifecycle_and_pages(client):
    acc = _account(client)
    for mv in ({"kind": "deposit", "ts": "2024-01-02", "amount": "10000"},
               {"kind": "buy", "ts": "2024-01-03", "symbol": "MC.PA", "quantity": "5", "price": "700", "fees": "2"}):
        assert client.post(f"/api/wealth/accounts/{acc}/movements", json=mv).status_code == 200

    page = client.get("/patrimoine")
    assert page.status_code == 200 and "PEA test" in page.text and "MC.PA" in page.text
    detail = client.get(f"/patrimoine/comptes/{acc}")
    assert detail.status_code == 200
    assert "Performance (TWR)" in detail.text and "vs ^STOXX50E" in detail.text
    assert 'id="wealth-chart-data"' in detail.text
    assert client.get("/mouvements").status_code == 200


def test_invalid_input_is_a_400_with_the_reason(client):
    acc = _account(client)
    resp = client.post(f"/api/wealth/accounts/{acc}/movements",
                       json={"kind": "buy", "ts": "2024-01-03", "symbol": "MC.PA", "quantity": "0", "price": "1"})
    assert resp.status_code == 400 and "quantité" in resp.json()["detail"]
    assert client.post("/api/wealth/accounts", json={"name": "", "kind": "PEA"}).status_code == 400
    assert client.post("/api/wealth/accounts", content=b"not json").status_code == 400
    assert client.get("/patrimoine/comptes/acc_missing").status_code == 404


def test_csv_import_previews_before_writing(client):
    acc = _account(client)
    csv_text = "date;type;montant\n02/01/2024;versement;1000\n03/01/2024;inconnu;1\n"
    preview = client.post(f"/api/wealth/accounts/{acc}/import", json={"csv": csv_text})
    assert preview.status_code == 200
    assert preview.json()["written"] == 0 and len(preview.json()["rows"]) == 1 and len(preview.json()["errors"]) == 1
    assert "data-movement-id" not in client.get("/mouvements").text
    commit = client.post(f"/api/wealth/accounts/{acc}/import", json={"csv": csv_text, "commit": True})
    assert commit.json()["written"] == 1


def test_drag_and_drop_transfer_rules_through_the_api(client):
    real = _account(client, name="Réel")
    fictive = _account(client, name="Bac à sable", mode="fictive", kind="CTO")
    mid = client.post(f"/api/wealth/accounts/{real}/movements",
                      json={"kind": "deposit", "ts": "2024-01-02", "amount": "500"}).json()["movement_id"]
    assert client.post(f"/api/wealth/movements/{mid}/transfer", json={"account_id": fictive}).json()["action"] == "copied"
    page = client.get(f"/patrimoine/comptes/{fictive}").text
    assert "500,00" in page
    copied = [m for m in client.get("/mouvements").text.split('data-movement-id="')[1:]]
    assert len(copied) == 2
    fictive_mid = mid + 1
    resp = client.post(f"/api/wealth/movements/{fictive_mid}/transfer", json={"account_id": real})
    assert resp.status_code == 400 and "fictif" in resp.json()["detail"]


def test_clone_as_fictive_and_delete(client):
    real = _account(client)
    clone = client.post(f"/api/wealth/accounts/{real}/clone", json={}).json()["account_id"]
    assert "(fictif)" in client.get(f"/patrimoine/comptes/{clone}").text
    assert client.delete(f"/api/wealth/accounts/{clone}").status_code == 200
    assert client.get(f"/patrimoine/comptes/{clone}").status_code == 404


def test_table_cells_render_html_not_escaped_markup(client):
    """Jinja escapes the literal parts of a `~` concatenation as soon as one
    operand is Markup: cells must be built with {% set %} blocks."""
    acc = _account(client)
    client.post(f"/api/wealth/accounts/{acc}/movements",
                json={"kind": "buy", "ts": "2024-01-03", "symbol": "MC.PA", "quantity": "1", "price": "700",
                      "note": "<b>x</b>"})
    for page in (client.get("/patrimoine").text, client.get(f"/patrimoine/comptes/{acc}").text):
        assert "&lt;span" not in page and "&lt;button" not in page
    detail = client.get(f"/patrimoine/comptes/{acc}").text
    assert '<span class="pk-mono">MC.PA</span>' in detail
    assert "&lt;b&gt;x&lt;/b&gt;" in detail
