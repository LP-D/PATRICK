"""Création rapide des stratégies par classe d'actifs depuis /fonds : API /api/fund/asset-classes*, section de la page. Aucun réseau."""
from __future__ import annotations

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


def test_the_class_list_shows_the_strategy_each_class_already_has(client):
    mine = fs.make_strategy(client, name="Systematic Future")

    body = client.get("/api/fund/asset-classes").json()

    classes = {c["name"]: c for c in body["classes"]}
    assert set(classes) == set(asset_classes.CLASSES) and classes["Future"]["strategy_id"] == mine
    assert classes["Devises"]["strategy_id"] is None and classes["Future"]["groups"] == list(asset_classes.CLASSES["Future"])
    assert body["defaults"] == {"horizons": [1], "tier": "large", "gross": 1.0, "capital": 10_000_000, "wrapper": "CTO",
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
    for bad in ({"classes": ["Nulle part"]}, {"capital": -1}, {"tier": "folle"}, {"horizons": [0]}, {"wrapper": "AV"},
                {"gross": 9}, {"max_models": 0}):
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
