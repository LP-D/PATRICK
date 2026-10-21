"""Coque de l'interface (audit du 2026-10-21) : fichiers statiques versionnés et mis en cache, fil de localisation unique dans la barre du
haut (pages enfants comprises), dates de tableau jamais coupées."""
from __future__ import annotations

import html as html_lib
import json
import re

import pytest
from page_support import FullPageClient as TestClient

from patrick.tracking import db
from patrick.webapp import nav_registry
from patrick.webapp.app import _ASSET_VERSIONS, BASE_DIR, app, asset


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", json.dumps({"name": "demo", "validation": {"scheme": "walkforward"}}), "cfg", "sha", 42)
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()
    return TestClient(app)


# ---------------------------------------------------------------- fichiers statiques
def test_asset_urls_carry_a_version_that_follows_the_file(tmp_path, monkeypatch):
    url = asset("shell.js")
    assert re.fullmatch(r"/static/shell\.js\?v=[0-9a-f]{8}", url)
    assert asset("shell.js") == url                                   # stable tant que le fichier ne change pas
    assert asset("n-existe-pas.js") == "/static/n-existe-pas.js"      # fichier absent : URL nue, pas d'erreur
    # une modification du fichier change l'empreinte
    probe = BASE_DIR / "static" / "_probe_version.js"
    try:
        probe.write_text("a", encoding="utf-8")
        first = asset("_probe_version.js")
        probe.write_text("bb", encoding="utf-8")
        assert asset("_probe_version.js") != first
    finally:
        probe.unlink(missing_ok=True)
        _ASSET_VERSIONS.pop("_probe_version.js", None)


def test_every_page_script_and_stylesheet_is_versioned(client):
    html = client.get("/").text
    refs = re.findall(r'(?:src|href)="(/static/[^"]+\.(?:js|css))[^"]*"', html)
    assert refs, "la page doit charger des scripts"
    assert all(re.search(r'(?:src|href)="' + re.escape(r) + r'\?v=[0-9a-f]{8}"', html) for r in refs)


def test_versioned_static_files_are_cached_forever_and_bare_urls_are_revalidated(client):
    versioned = client.get(asset("patrick.css"))
    assert versioned.status_code == 200
    assert "immutable" in versioned.headers["cache-control"] and "max-age=31536000" in versioned.headers["cache-control"]
    assert client.get("/static/patrick.css").headers["cache-control"] == "no-cache"          # ancien marque-page : revalidé
    font = client.get("/static/fonts/inter-latin.woff2")
    assert "immutable" in font.headers["cache-control"]
    assert client.get("/static/absent.js?v=abc").status_code == 404


# ---------------------------------------------------------------- fil de localisation
def _crumbs(html: str) -> str:
    block = re.search(r'<div class="topbar-crumbs">(.*?)</div>', html, re.DOTALL).group(1)
    return html_lib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", block)).strip())


def test_no_page_body_carries_its_own_breadcrumb(client):
    for path in ("/", "/runs", "/predictions", "/universe", "/macro", "/portfolio", "/data-freshness", "/runs/run1", "/targets/%5EVIX"):
        assert 'class="breadcrumb"' not in client.get(path).text, path


def test_child_pages_extend_the_top_bar_trail(client):
    target = client.get("/targets/%5EVIX").text
    assert _crumbs(target).endswith("Univers ^VIX")
    assert re.search(r'<a class="crumb-entry" href="/universe">', target)
    run = _crumbs(client.get("/runs/run1/detail").text)
    assert "Historique" in run and "^VIX" in run and run.endswith("run1")


def test_child_pages_light_up_their_navigation_entry(client):
    sidebar = re.search(r'<aside class="sidebar".*?</aside>', client.get("/targets/%5EVIX").text, re.DOTALL).group(0)
    assert re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', sidebar) == ["/universe"]


def test_top_level_pages_have_a_two_level_trail(client):
    for entry in nav_registry.NAV_ENTRIES:
        if entry.url in ("/",):
            continue
        trail = _crumbs(client.get(entry.url).text)
        assert len(trail.split()) >= 2, (entry.url, trail)


# ---------------------------------------------------------------- tableaux
def test_dates_in_data_tables_never_wrap(client):
    html = client.get("/targets/%5EVIX").text
    cells = re.findall(r'<td class="nowrap">(\d{4}-\d{2}-\d{2}[ 0-9:]*)</td>', html)
    assert cells, "la date de lancement d'un run doit être protégée contre le retour à la ligne"
