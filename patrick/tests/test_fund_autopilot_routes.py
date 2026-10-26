"""Pilote automatique du fonds : API /api/fund/strategies/{id}/autopilot*, bloc du panneau /fonds. Aucun réseau."""
from __future__ import annotations

import fund_support as fs
import pytest
from fastapi.testclient import TestClient
from test_fund_selection import World

from patrick.fund import systematic
from patrick.tracking import db as trackdb
from patrick.webapp.app import app

XSS = "<script>alert(1)</script>"
UP, DOWN = 3, 0
SIGNALS = [("2026-01-14", UP, 0.6), ("2026-01-15", DOWN, 0.6), ("2026-01-16", UP, 0.6)]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


@pytest.fixture
def world(client, monkeypatch):
    conn = trackdb.connect()
    yield World(conn, monkeypatch)
    conn.close()


def url(sid: str, tail: str = "") -> str:
    return f"/api/fund/strategies/{sid}/autopilot{tail}"


# --------------------------------------------------------------------------- état, réglages

def test_status_of_a_strategy_without_autopilot_shows_the_defaults(client):
    sid = fs.make_strategy(client)

    body = client.get(url(sid)).json()

    assert body["enabled"] is False and body["last_run"] is None and body["rules"] == []
    assert body["settings"]["tier"] == "strict" and body["settings"]["gross"] == 1.0 and body["settings"]["allow_short"] is True


def test_unknown_strategy_is_a_404(client):
    assert client.get(url("str_inconnue")).status_code == 404
    assert client.put(url("str_inconnue"), json={}).status_code == 400            # configure : erreur de saisie
    assert client.delete(url("str_inconnue")).status_code == 404


def test_put_enables_the_autopilot_with_validated_settings(client):
    sid = fs.make_strategy(client)

    ok = client.put(url(sid), json={"tier": "large", "gross": 0.5, "max_models": 12, "allow_short": False})

    assert ok.status_code == 200 and ok.json()["enabled"] is True
    status = client.get(url(sid)).json()
    assert status["enabled"] is True and status["settings"]["tier"] == "large" and status["settings"]["gross"] == 0.5
    bad = client.put(url(sid), json={"gross": 9})
    assert bad.status_code == 400 and "gross" in bad.json()["detail"]


def test_writes_require_a_json_content_type(client):
    sid = fs.make_strategy(client)

    for call in (client.put(url(sid), content="{}", headers={"Content-Type": "text/plain"}),
                 client.post(url(sid, "/run"), content="{}", headers={"Content-Type": "text/plain"}),
                 client.post(url(sid, "/preview"), content="{}", headers={"Content-Type": "text/plain"})):
        assert call.status_code == 415


# --------------------------------------------------------------------------- aperçu

def test_preview_lists_the_selected_models_and_the_exclusions_without_saving(client, world):
    world.cell("AAPL", 3, live=SIGNALS)
    world.cell("ZZZ", 3, live=SIGNALS)
    sid = fs.make_strategy(client)

    body = client.post(url(sid, "/preview"), json={"gross": 0.5}).json()

    assert [m["target"] for m in body["selected"]] == ["AAPL"]
    assert body["selected"][0]["notional"] == pytest.approx(body["capital"] * 0.5, abs=0.05)
    assert [(e["target"], e["code"]) for e in body["excluded"]] == [("ZZZ", "no_quotes")]
    assert body["excluded_summary"] == [{"code": "no_quotes", "label": "cotation indisponible", "n": 1}]
    assert client.get(url(sid)).json()["enabled"] is False                          # rien n'est enregistré
    assert systematic.list_rules(trackdb.connect(), sid) == []


def test_preview_html_is_escaped_and_follows_the_query_settings(client, world):
    world.cell("AAPL", 3, live=SIGNALS, dm_p=0.9, bh=(False, 0.9))                  # écarté en strict, retenu en large
    world.cell(XSS, 3, live=SIGNALS)
    sid = fs.make_strategy(client)

    strict = client.get(url(sid, "/preview.html")).text
    large = client.get(url(sid, "/preview.html?tier=large&gross=0.5&max_models=5&allow_short=0")).text

    assert 'data-model="AAPL 3"' not in strict and 'data-model="AAPL 3"' in large
    assert XSS not in strict + large and "&lt;script&gt;" in strict + large       # la cible hostile est écrasée par Jinja
    assert client.get(url(sid, "/preview.html?gross=beaucoup")).status_code == 400


# --------------------------------------------------------------------------- cycle

def test_run_creates_the_rules_and_the_status_reports_them(client, world):
    world.cell("AAPL", 3, live=SIGNALS)
    sid = fs.make_strategy(client)
    client.put(url(sid), json={})

    report = client.post(url(sid, "/run"), json={}).json()

    assert report["selected"] == 1 and len(report["created"]) == 1 and report["rules"] == 1
    status = client.get(url(sid)).json()
    assert status["last_run"]["selected"] == 1 and status["last_run"]["day"] == "2026-01-16"
    (rule,) = status["rules"]
    assert rule["name"] == "Auto · AAPL h3" and rule["config"]["managed"]["by"] == "autopilot"


def test_run_on_a_strategy_without_autopilot_is_a_400(client):
    sid = fs.make_strategy(client)

    res = client.post(url(sid, "/run"), json={})

    assert res.status_code == 400 and "pilote" in res.json()["detail"]


def test_delete_disables_the_autopilot_and_removes_its_rules(client, world):
    world.cell("AAPL", 3, live=SIGNALS)
    sid = fs.make_strategy(client)
    client.put(url(sid), json={})
    client.post(url(sid, "/run"), json={})

    out = client.delete(url(sid))

    assert out.status_code == 200 and out.json() == {"removed_rules": 1}
    assert client.get(url(sid)).json()["enabled"] is False and client.get(url(sid)).json()["rules"] == []


# --------------------------------------------------------------------------- panneau

def test_the_panel_offers_the_autopilot_and_keeps_manual_rules_apart(client, world):
    world.cell("AAPL", 3, live=SIGNALS)
    sid = fs.make_strategy(client)

    off = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert 'data-act="auto-preview"' in off and 'data-act="auto-save"' in off
    assert 'data-act="auto-run"' not in off and 'data-act="auto-off"' not in off

    client.put(url(sid), json={})
    client.post(url(sid, "/run"), json={})
    on = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert 'data-act="auto-run"' in on and 'data-act="auto-off"' in on
    assert 'class="fund-auto-rule"' in on and 'title="AAPL"' in on and "h3 · XGBoost" in on     # listée dans le bloc du pilote
    assert on.count('class="fund-rule"') == 0                              # et pas dans le tableau des règles manuelles


def test_the_model_selector_lists_every_model_by_name_with_its_p_value(client, world):
    world.cell("AAPL", 1, live=SIGNALS, dm_p=0.012)
    world.cell("GC=F", 1, live=SIGNALS, dm_p=None)
    world.cell("^GSPC", 3, live=SIGNALS, dm_p=0.4, f1=0.99)                   # suspect : visible mais désactivé
    sid = fs.make_strategy(client)

    html = client.get(f"/api/fund/strategies/{sid}/rule-form").text

    assert "Apple · h1 (p = 0.012)" in html                                   # le nom, pas le symbole ; la p entre parenthèses
    assert "Future · Or · h1<" in html                                        # pas de p : rien entre parenthèses
    assert 'data-symbol="AAPL"' in html and 'data-kind-hint="equity"' in html and 'data-kind-hint="cfd"' in html
    assert html.index("Apple · h1") < html.index("Future · Or · h1") < html.index("Indice")    # triés par nom
    assert "(p = 0.400)" in html and "disabled" in html.split("(p = 0.400)")[0].rsplit("<option", 1)[1]
    assert 'name="signal_mode"' in html and 'name="follow_champion"' in html and "fund_rule_follow" not in html


def test_an_empty_max_models_in_the_preview_address_means_no_cap(client, world):
    for i in range(3):
        world.cell(f"T{i}", 3, live=SIGNALS)
    world.cell("AAPL", 3, live=SIGNALS)
    sid = fs.make_strategy(client)

    capped = client.get(url(sid, "/preview.html?max_models=1")).text
    unlimited = client.get(url(sid, "/preview.html?max_models=")).text

    assert "Au-delà du nombre maximal" in capped and "Au-delà du nombre maximal" not in unlimited


def test_the_panel_does_not_compute_the_model_list(client, world, monkeypatch):
    """La liste de tous les modèles est la partie lente : le panneau s'affiche sans elle, le formulaire se charge à part."""
    world.cell("AAPL", 1, live=SIGNALS)
    sid = fs.make_strategy(client)

    def boom(conn, limit=5000):
        raise AssertionError("le panneau ne doit pas calculer les modèles")
    monkeypatch.setattr(systematic, "available_models", boom)

    assert client.get(f"/api/fund/strategies/{sid}/panel").status_code == 200


def test_the_model_list_is_cached_until_the_runs_or_champions_change(client, world, monkeypatch):
    world.cell("AAPL", 1, live=SIGNALS)
    sid = fs.make_strategy(client)
    calls: list[int] = []
    real = systematic.available_models

    def counting(conn, limit=5000):
        calls.append(1)
        return real(conn, limit)
    monkeypatch.setattr(systematic, "available_models", counting)

    first = client.get(f"/api/fund/strategies/{sid}/rule-form").text
    second = client.get(f"/api/fund/strategies/{sid}/rule-form").text
    assert len(calls) == 1 and first == second                                 # la deuxième ouverture ne recalcule rien

    world.cell("GC=F", 1, live=SIGNALS)                                       # un nouveau champion : liste recalculée tout de suite
    third = client.get(f"/api/fund/strategies/{sid}/rule-form").text
    assert len(calls) == 2 and "Future · Or" in third


def test_the_model_list_never_offers_a_fred_series(client, world):
    from patrick.config import defaults as D
    fred = next(sym for sym, _, src in D.DEFAULT_TARGET_CHOICES if src == "fred")
    world.cell(fred, 1, live=SIGNALS)
    world.cell("AAPL", 1, live=SIGNALS)

    models = client.get("/api/fund/models").json()["models"]

    assert [m["target"] for m in models] == ["AAPL"]
