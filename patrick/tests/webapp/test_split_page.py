"""Page « Écrans côte à côte » (`/split`) : cadre serveur, liste des pages, mode intégré des volets et fonctions pures de `static/split.js`."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrick.tracking import db
from patrick.webapp import nav_registry
from patrick.webapp.app import app

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "patrick" / "webapp" / "static"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    return TestClient(app)


def _pages(html: str) -> list[dict]:
    return json.loads(re.search(r'<script id="split-pages" type="application/json">(.*?)</script>', html, re.DOTALL).group(1))


def test_split_page_frame_lists_the_layouts_and_the_pages(tmp_path, monkeypatch):
    html = _client(tmp_path, monkeypatch).get("/split").text
    assert 'id="split-app"' in html and 'id="split-stage"' in html
    assert len(re.findall(r'class="split-layout-btn"', html)) == 7
    urls = [p["url"] for p in _pages(html)]
    assert "/predictions" in urls and "/universe" in urls and "/reglages" in urls
    assert "/split" not in urls                       # un volet ne peut pas s'afficher lui-même
    assert len(urls) == len(set(urls))


def test_split_is_a_navigation_entry_and_a_registered_route():
    assert "/split" in nav_registry.registered_routes()
    entry = next(e for e in nav_registry.NAV_ENTRIES if e.slug == "split")
    assert entry.category == "pilotage" and entry.label_key == "nav_split"


def test_split_page_is_listed_in_the_sidebar_and_translated(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert 'href="/split"' in client.get("/").text
    fr = client.get("/split").text
    en = client.get("/split", cookies={"patrick_lang": "en"}).text
    assert "Écrans côte à côte" in fr and "Side-by-side screens" in en


def test_pages_embedded_in_a_pane_hide_the_application_chrome():
    base = (ROOT / "patrick" / "webapp" / "templates" / "base_v2.html").read_text(encoding="utf-8")
    assert 'window.top.location.pathname === "/split"' in base and 'setAttribute("data-embed"' in base
    css = (STATIC / "patrick.css").read_text(encoding="utf-8")
    assert ':root[data-embed] .sidebar' in css and ':root[data-embed] .topbar' in css


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_split_pure_functions_under_node():
    done = subprocess.run(["node", str(ROOT / "tests" / "js" / "split.test.js")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, f"{done.stdout}\n{done.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_split_script_parses():
    done = subprocess.run(["node", "--check", str(STATIC / "split.js")], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
