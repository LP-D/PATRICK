"""Création rapide des stratégies par classe d'actifs depuis /fonds : API /api/fund/asset-classes*, section de la page. Aucun réseau."""
from __future__ import annotations

import re

import fund_support as fs
import pytest
from fastapi.testclient import TestClient
from test_fund_selection import World

from patrick.fund import asset_classes, autopilot, store
from patrick.tracking import db as trackdb
from patrick.webapp.app import app

SIGNALS = [("2026-01-14", 3, 0.6), ("2026-01-15", 0, 0.6)]
XSS = "<script>alert(1)</script>"


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


def strategies() -> dict[str, dict]:
    conn = trackdb.connect()
    try:
        return {s["name"]: s for s in store.list_strategies(conn)}
    finally:
        conn.close()


def test_the_fonds_page_offers_the_quick_creation_with_every_class_checked(client):
    html = client.get("/fonds").text

    assert 'id="fund-classes"' in html and 'data-act="classes-preview"' in html and 'data-act="classes-create"' in html
    for name in asset_classes.CLASSES:
        assert f'value="{name}" data-cls-field' in html and "checked" in html.split(f'value="{name}"')[1][:80]
    assert 'name="capital"' in html and 'value="10000000"' in html and 'name="horizons"' in html and 'value="1"' in html


def test_the_quick_creation_offers_every_selection_level(client):
    html = client.get("/fonds").text

    select = html.split('<select name="tier" data-cls-field>', 1)[1].split("</select>", 1)[0]
    assert sorted(re.findall(r'<option value="(\w+)"', select)) == ["auc", "bh", "dm", "large", "strict"]


def test_the_class_list_shows_the_strategy_each_class_already_has(client):
    mine = fs.make_strategy(client, name="Systematic Future")

    body = client.get("/api/fund/asset-classes").json()

    classes = {c["name"]: c for c in body["classes"]}
    assert set(classes) == set(asset_classes.CLASSES) and classes["Future"]["strategy_id"] == mine
    assert classes["Devises"]["strategy_id"] is None and classes["Future"]["groups"] == list(asset_classes.CLASSES["Future"])
    assert body["defaults"] == {"horizons": [1], "tier": "strict", "gross": 1.0, "capital": 10_000_000, "family": "systematic",
                                "max_models": None}


def test_preview_counts_the_candidates_and_writes_nothing(client, world):
    world.cell("GC=F", 1, live=SIGNALS)
    world.cell("CL=F", 1, live=SIGNALS)
    world.cell("GC=F", 5, live=SIGNALS)

    rows = client.post("/api/fund/asset-classes/preview", json={"classes": ["Future"]}).json()["rows"]

    assert [(r["class"], r["candidates"], r["strategy_id"]) for r in rows] == [("Future", 2, None)]
    assert strategies() == {}


def test_preview_html_is_escaped_and_follows_the_query(client, world):
    world.cell("GC=F", 1, live=SIGNALS)
    world.cell("GC=F", 5, live=SIGNALS)

    one = client.get("/api/fund/asset-classes/preview.html?classes=Future&horizons=1").text
    both = client.get("/api/fund/asset-classes/preview.html?classes=Future&horizons=1,5").text

    assert 'data-class="Future"' in one and 'data-class="Devises"' not in one
    assert 'data-candidates="1"' in one and 'data-candidates="2"' in both
    hostile = client.get("/api/fund/asset-classes/preview.html?classes=" + XSS)
    assert hostile.status_code == 400 and hostile.headers["content-type"].startswith("application/json")   # jamais rendu en HTML
    assert client.get("/api/fund/asset-classes/preview.html?capital=beaucoup").status_code == 400
    assert client.get("/api/fund/asset-classes/preview.html?classes=Nulle%20part").status_code == 400


def test_create_makes_one_strategy_per_class_and_is_idempotent(client, world, monkeypatch):
    started: list[list[str]] = []
    monkeypatch.setattr(autopilot, "start_cycles", lambda ids, db_path=None: started.append(list(ids)))
    world.cell("GC=F", 1, live=SIGNALS)
    body = {"classes": ["Future", "Devises"], "capital": 10_000_000, "run": True}

    first = client.post("/api/fund/asset-classes", json=body)
    second = client.post("/api/fund/asset-classes", json=body)

    assert first.status_code == 200, first.text
    rows = {r["class"]: r for r in first.json()["rows"]}
    assert rows["Future"]["created"] and rows["Devises"]["created"] and first.json()["cycle_started"] is True
    made = strategies()
    assert set(made) == {"Systematic Future", "Systematic Devises"}
    assert made["Systematic Future"]["initial_capital"] == 10_000_000 and made["Systematic Future"]["wrapper"] == "CTO"
    assert [r["created"] for r in second.json()["rows"]] == [False, False] and len(strategies()) == 2
    assert sorted(started[0]) == sorted(r["strategy_id"] for r in rows.values())


def test_create_without_run_starts_no_cycle(client, world, monkeypatch):
    started: list = []
    monkeypatch.setattr(autopilot, "start_cycles", lambda ids, db_path=None: started.append(ids))

    out = client.post("/api/fund/asset-classes", json={"classes": ["Crypto"], "run": False}).json()

    assert out["cycle_started"] is False and started == []


def test_create_validates_its_input_and_requires_json(client):
    assert client.post("/api/fund/asset-classes", content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    for bad in ({"classes": ["Nulle part"]}, {"capital": -1}, {"tier": "folle"}, {"horizons": [0]}, {"family": "AV"},
                {"gross": 9}, {"max_models": 0}, {"split": "partout"}, {"family": "pea", "classes": ["Future"]},
                {"split": "tiers", "tiers": ["large"]}, {"family": "pea", "capital": 10_000_000}):
        res = client.post("/api/fund/asset-classes", json=bad)
        assert res.status_code == 400, (bad, res.text)
    assert strategies() == {}


def test_start_cycles_runs_each_strategy_one_after_the_other_and_survives_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    seen: list[str] = []

    def fake_run(conn, strategy_id, today=None):
        seen.append(strategy_id)
        if strategy_id == "str_b":
            raise RuntimeError("boum")
        return {}
    monkeypatch.setattr(autopilot, "run", fake_run)

    thread = autopilot.start_cycles(["str_a", "str_b", "str_c"])
    thread.join(timeout=30)

    assert seen == ["str_a", "str_b", "str_c"] and not thread.is_alive()


# --- une seule carte de création : gamme (Systematic, CTO, PEA, réels) et découpage (par classe, par preuve) ---------------


def test_the_page_has_one_creation_card_with_every_family_and_the_pea_classes_marked(client):
    html = client.get("/fonds").text

    card = html.split('id="fund-create"', 1)[1].split("</details>", 1)[0]
    family = card.split('<select name="family" id="fund-family">', 1)[1].split("</select>", 1)[0]
    assert re.findall(r'<option value="(\w+)"', family) == ["systematic", "cto", "pea", "real"]
    assert 'data-capital="150000"' in family and 'data-capital="10000000"' in family
    assert 'id="fund-classes"' in card and 'id="fund-real"' in card and 'data-act="real-create"' in card       # les fonds réels dans la même carte
    assert 'name="split"' in card and 'value="tiers"' in card and 'name="tier_pick" value="dm"' in card
    assert 'data-families="systematic cto pea"><input type="checkbox" name="class" value="Actions France"' in card
    assert 'data-families="systematic cto"><input type="checkbox" name="class" value="Future"' in card
    assert html.count("<details class=\"card") == html.count("<details class=\"card fund-create\"")         # plus de carte à part


def test_the_classes_api_lists_the_classes_of_a_family(client):
    body = client.get("/api/fund/asset-classes?family=pea").json()

    assert [c["name"] for c in body["classes"]] == ["Actions France", "Actions Europe"]
    assert body["families"]["pea"] == {"prefix": "PEA", "wrapper": "PEA", "allow_short": False, "capital": store.PEA_DEPOSIT_CAP_EUR,
                                       "classes": ["Actions France", "Actions Europe"]}
    assert client.get("/api/fund/asset-classes?family=AV").status_code == 400


def test_create_follows_the_family_with_its_capital_and_its_short_rule(client, world, monkeypatch):
    monkeypatch.setattr(autopilot, "start_cycles", lambda ids, db_path=None: None)

    out = client.post("/api/fund/asset-classes", json={"family": "pea", "tier": "large", "run": False})

    assert out.status_code == 200, out.text
    made = strategies()
    assert set(made) == {"PEA Actions France", "PEA Actions Europe"}
    assert made["PEA Actions France"]["wrapper"] == "PEA" and made["PEA Actions France"]["initial_capital"] == store.PEA_DEPOSIT_CAP_EUR


def test_the_split_by_evidence_creates_one_strategy_per_tier_in_the_family(client, world, monkeypatch):
    monkeypatch.setattr(autopilot, "start_cycles", lambda ids, db_path=None: None)

    preview = client.get("/api/fund/asset-classes/preview.html?family=cto&split=tiers&tiers=dm,bh").text
    out = client.post("/api/fund/asset-classes", json={"family": "cto", "split": "tiers", "tiers": ["dm"], "run": False}).json()

    assert "CTO Diebold-Mariano" in preview and "CTO Benjamini-Hochberg" in preview and 'data-class="Future"' not in preview
    assert [(r["tier"], r["name"], r["created"]) for r in out["rows"]] == [("dm", "CTO Diebold-Mariano", True)]
    conn = trackdb.connect()
    settings = store.get_autopilot(conn, out["rows"][0]["strategy_id"])["settings"]
    conn.close()
    assert (settings["tier"], settings["allow_short"], settings["groups"]) == ("dm", False, None)

