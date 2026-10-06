"""Page /fonds et API : règle pilotée par un modèle d'alpha (paire couverte). Aucun réseau."""
from __future__ import annotations

import fund_support as fs
import pytest
from fastapi.testclient import TestClient
from test_fund_alpha_rules import _alpha_model, _config

from patrick.tracking import db as trackdb
from patrick.webapp.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


@pytest.fixture
def trial_id(client):
    conn = trackdb.connect()
    tid = _alpha_model(conn)
    conn.close()
    return tid


def test_models_endpoint_describes_an_alpha_model(client, trial_id):
    (m,) = client.get("/api/fund/models").json()["models"]
    assert (m["kind"], m["asset"], m["benchmark"]) == ("alpha", "AAPL", "^GSPC")


def test_create_apply_an_alpha_rule_through_the_api_places_pairs(client, trial_id):
    sid = fs.make_strategy(client)

    created = client.post(f"/api/fund/strategies/{sid}/rules", json={"name": "Alpha couvert", "config": _config(trial_id)})
    assert created.status_code == 200, created.text
    rule_id = created.json()["rule_id"]
    applied = client.post(f"/api/fund/rules/{rule_id}/apply", json={}).json()

    assert applied["refused"] == [] and len(applied["placed"]) == 5
    assert all(len(p["order_ids"]) == 2 for p in applied["placed"])
    orders = client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"]
    assert {o["symbol"] for o in orders} == {"AAPL", "^GSPC"} and len(orders) == 10


def test_an_alpha_rule_without_a_hedge_is_a_readable_400(client, trial_id):
    sid = fs.make_strategy(client)
    config = {k: v for k, v in _config(trial_id).items() if k != "hedge"}
    resp = client.post(f"/api/fund/strategies/{sid}/rules", json={"name": "x", "config": config})
    assert resp.status_code == 400 and "couverture" in resp.json()["detail"]


def test_the_panel_offers_the_alpha_model_and_the_hedge_fields(client, trial_id):
    sid = fs.make_strategy(client)
    html = client.get(f"/api/fund/strategies/{sid}/panel").text

    assert f'<option value="{trial_id}"' in html and 'data-kind="alpha"' in html
    assert 'data-asset="AAPL"' in html and 'data-benchmark="^GSPC"' in html
    assert 'name="hedge_symbol"' in html and 'name="hedge_leverage"' in html and "data-alpha-only" in html
    assert "α" in html                                              # l'option se reconnaît comme modèle d'alpha


def test_the_panel_shows_the_hedge_of_an_existing_rule(client, trial_id):
    sid = fs.make_strategy(client)
    client.post(f"/api/fund/strategies/{sid}/rules", json={"name": "Alpha couvert", "config": _config(trial_id)})
    html = client.get(f"/api/fund/strategies/{sid}/panel").text

    assert "couvert contre ^GSPC" in html and "AAPL" in html
    assert client.get(f"/api/fund/strategies/{sid}/panel?lang=en").text.count("hedged against ^GSPC") == 1


def test_no_untranslated_key_leaks_into_the_alpha_panel(client, trial_id):
    sid = fs.make_strategy(client)
    for lang in ("fr", "en"):
        html = client.get(f"/api/fund/strategies/{sid}/panel?lang={lang}").text
        assert "fund_rule_hedge" not in html and "fund_rule_alpha" not in html
