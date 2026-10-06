"""Règles automatiques du fonds (chantier 3, jalon 2) : API /api/fund/*, panneau /fonds. Aucun réseau."""
from __future__ import annotations

import fund_support as fs
import pytest
from fastapi.testclient import TestClient
from test_fund_systematic import _config, _model

from patrick.fund import systematic
from patrick.tracking import db as trackdb
from patrick.webapp.app import app

XSS = "<script>alert(1)</script>"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


@pytest.fixture
def trial_id(client):
    conn = trackdb.connect()
    tid = _model(conn)
    conn.execute("UPDATE run SET status = 'done' WHERE run_id = 'run1'")
    conn.execute("UPDATE trial SET is_best = 1 WHERE trial_id = ?", (tid,))
    conn.commit()
    conn.close()
    return tid


def create(client, sid, tid, name="ML seuils", **kw):
    return client.post(f"/api/fund/strategies/{sid}/rules", json={"name": name, "config": _config(tid, **kw)})


# --------------------------------------------------------------------------- modèles disponibles

def test_models_endpoint_is_empty_without_any_signal(client):
    assert client.get("/api/fund/models").json() == {"models": []}


def test_models_endpoint_lists_best_trials_with_their_signal_segments(client, trial_id):
    models = client.get("/api/fund/models").json()["models"]

    assert len(models) == 1
    m = models[0]
    assert (m["trial_id"], m["target"], m["horizon"], m["algo"]) == (trial_id, "^GSPC", 5, "XGBoost")
    assert m["segments"] == {"holdout": 9} and m["champion"] is False


def test_models_endpoint_flags_the_champion_and_skips_trials_without_signals(client, trial_id):
    conn = trackdb.connect()
    conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, reason) VALUES ('^GSPC', 5, 'run1', ?, 'first')",
                 (trial_id,))
    other = trackdb.create_trial(conn, "run1", "GLOBAL", "XGBoost", "SMOTE", 3, "shap")
    conn.execute("UPDATE trial SET is_best = 1 WHERE trial_id = ?", (other,))
    conn.commit()
    conn.close()

    models = client.get("/api/fund/models").json()["models"]

    assert [m["trial_id"] for m in models] == [trial_id] and models[0]["champion"] is True


# --------------------------------------------------------------------------- règles

def test_create_list_apply_delete_a_rule_end_to_end(client, trial_id):
    sid = fs.make_strategy(client)

    created = create(client, sid, trial_id)
    assert created.status_code == 200, created.text
    rule_id = created.json()["rule_id"]
    listed = client.get(f"/api/fund/strategies/{sid}/rules").json()["rules"]
    assert [(r["rule_id"], r["n_orders"]) for r in listed] == [(rule_id, 0)]

    applied = client.post(f"/api/fund/rules/{rule_id}/apply", json={})
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert len(body["placed"]) == 5 and body["refused"] == [] and body["already"] == 0
    assert client.get(f"/api/fund/strategies/{sid}/rules").json()["rules"][0]["n_orders"] == 5
    again = client.post(f"/api/fund/rules/{rule_id}/apply", json={}).json()
    assert again["placed"] == [] and again["already"] == 5

    assert client.delete(f"/api/fund/rules/{rule_id}").json() == {"ok": True}
    assert client.get(f"/api/fund/strategies/{sid}/rules").json()["rules"] == []
    assert len(client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"]) == 5   # les ordres passés restent


def test_create_rule_rejects_bad_input_with_a_readable_400(client, trial_id):
    sid = fs.make_strategy(client)

    bad = create(client, sid, trial_id, enter=0.4)
    assert bad.status_code == 400 and "enter" in bad.json()["detail"]
    missing = create(client, sid, 999)
    assert missing.status_code == 400 and "essai" in missing.json()["detail"]
    nostrat = client.post("/api/fund/strategies/str_absent/rules", json={"name": "x", "config": _config(trial_id)})
    assert nostrat.status_code == 400 and "stratégie" in nostrat.json()["detail"]


def test_rule_writes_require_a_json_content_type(client, trial_id):
    sid = fs.make_strategy(client)
    resp = client.post(f"/api/fund/strategies/{sid}/rules", content='{"name": "x"}', headers={"Content-Type": "text/plain"})
    assert resp.status_code == 415
    rule_id = create(client, sid, trial_id).json()["rule_id"]
    assert client.post(f"/api/fund/rules/{rule_id}/apply", content="{}",
                       headers={"Content-Type": "text/plain"}).status_code == 415


def test_unknown_rule_is_a_404_on_delete_and_a_400_on_apply(client):
    assert client.delete("/api/fund/rules/rule_absent").status_code == 404
    resp = client.post("/api/fund/rules/rule_absent/apply", json={})
    assert resp.status_code == 400 and "règle" in resp.json()["detail"]


def test_deleting_a_strategy_deletes_its_rules(client, trial_id):
    sid = fs.make_strategy(client)
    create(client, sid, trial_id)
    client.delete(f"/api/fund/strategies/{sid}")
    conn = trackdb.connect()
    assert conn.execute("SELECT COUNT(*) FROM fund_rule").fetchone()[0] == 0
    conn.close()


# --------------------------------------------------------------------------- panneau /fonds

def test_panel_without_rule_offers_the_creation_form_with_the_available_models(client, trial_id):
    sid = fs.make_strategy(client)
    html = client.get(f"/api/fund/strategies/{sid}/panel").text

    assert "Règles automatiques" in html and 'data-form="rule"' in html
    assert f'<option value="{trial_id}"' in html and "^GSPC" in html
    assert "Aucune règle" in html


def test_panel_lists_a_rule_with_its_actions_and_escapes_its_name(client, trial_id):
    sid = fs.make_strategy(client)
    rule_id = create(client, sid, trial_id, name=XSS).json()["rule_id"]
    html = client.get(f"/api/fund/strategies/{sid}/panel").text

    assert XSS not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert f'data-act="apply-rule" data-rule-id="{rule_id}"' in html
    assert f'data-act="delete-rule" data-rule-id="{rule_id}"' in html
    assert "0,6" in html or "0.6" in html                                   # seuil d'entrée affiché


def test_panel_warns_when_models_are_missing(client):
    sid = fs.make_strategy(client)
    assert "Aucun modèle avec signaux" in client.get(f"/api/fund/strategies/{sid}/panel").text


def test_rule_helpers_are_importable_from_the_module():
    assert callable(systematic.available_models) and callable(systematic.delete_rule)
