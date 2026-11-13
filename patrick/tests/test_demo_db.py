"""La base de démonstration (`scripts/make_demo_db.py`) se construit, et toutes les pages de la navigation s'ouvrent dessus."""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrick.tracking import db as trackdb
from patrick.tracking import live_board
from patrick.webapp import analysis_routes, nav_registry
from patrick.webapp.app import app

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_demo_db.py"
TODAY = dt.date(2026, 11, 13)


def _module():
    spec = importlib.util.spec_from_file_location("make_demo_db", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("demo") / "patrick.db")
    module = _module()
    return path, module.build(path, TODAY), module


def test_the_demo_database_has_champions_judged_live_results_and_a_pooled_signal(demo):
    path, done, module = demo
    assert done["runs"] == done["champions"] == len(module.TARGETS) * len(module.HORIZONS) == 30

    conn = trackdb.connect(path)
    try:
        board = live_board.board(conn, TODAY)
        assert board["total"]["n"] > 1000 and 0.4 < board["total"]["rate"] < 0.7
        assert {r["key"] for r in board["by_class"]} >= {"equities_us", "equities_europe", "fx", "futures"}
        assert len(board["consensus"]) == len(module.TARGETS)
        assert conn.execute("SELECT COUNT(*), SUM(significant) FROM pooled_signal").fetchone()[0] == 30
    finally:
        conn.close()


def test_the_script_refuses_to_overwrite_a_file(demo, capsys):
    path, _, module = demo
    assert module.main([path]) == 1 and "existe déjà" in capsys.readouterr().out


def test_every_navigation_page_opens_on_the_demo_database(demo, monkeypatch):
    path, _, _ = demo
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    analysis_routes._forget("live_board")
    client = TestClient(app)
    urls = sorted({e.url for e in (*nav_registry.NAV_ENTRIES, *nav_registry.UTILITY_ENTRIES)})

    failed = {url: status for url in urls if (status := client.get(url).status_code) != 200}

    assert failed == {} and len(urls) > 25
    assert "Résultat réel" in client.get("/reel").text and "Avis d" in client.get("/reel").text
