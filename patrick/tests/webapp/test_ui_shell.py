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
    for path in ("/", "/runs", "/predictions", "/universe", "/macro", "/portfolio", "/data-quality", "/runs/run1", "/targets/%5EVIX"):
        assert 'class="breadcrumb"' not in client.get(path).text, path


def test_child_pages_extend_the_top_bar_trail(client):
    target = client.get("/targets/%5EVIX").text
    assert _crumbs(target).endswith("Univers Volatilité · VIX (S&P 500)")
    assert re.search(r'<a class="crumb-entry" href="/universe">', target)
    run = _crumbs(client.get("/runs/run1/detail").text)
    assert "Historique" in run and "VIX (S&P 500)" in run and run.endswith("run1")


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


def test_templates_keep_only_data_driven_inline_styles():
    """Design v3 : un `style="…"` en ligne ne sert qu'à une largeur calculée par les données ; le reste va dans `patrick.css` (jetons)."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "patrick" / "webapp" / "templates"
    inline = {p.name: p.read_text(encoding="utf-8").count('style="') for p in root.glob("*.html")}
    # knowledge_hub.html : --share (hauteur d'une marche) et --heat (intensité d'une case) sont calculés à partir des nombres de notions
    assert {k: v for k, v in inline.items() if v} == {"_fund_overview.html": 1, "analysis.html": 1, "knowledge_hub.html": 2}


def test_shell_offers_pins_machine_chip_and_shortcut_help(client):
    page = client.get("/placements").text
    assert 'id="pin-toggle"' in page and 'aria-pressed="false"' in page
    assert 'id="sidebar-pins"' in page and 'id="pins-list"' in page
    assert 'id="machine-chip"' in page and 'id="kbd-help"' in page
    i18n = json.loads(re.search(r'<script id="i18n-data" type="application/json">(.*?)</script>', page, re.DOTALL).group(1))
    for key in ("pin_add", "pin_remove", "pins_title", "recent_title", "chip_queue", "dur_short_h"):
        assert i18n.get(key), key
    shell = (BASE_DIR / "static" / "shell.js").read_text(encoding="utf-8")
    assert "patrick-pins" in shell and "patrick-recent" in shell and "/api/run-state" in shell


# ---------------------------------------------------------------- barre du haut à 320 px (WCAG 2.2, critère 1.4.10 « Reflow »)
def test_topbar_groups_secondary_buttons_in_an_overflow_menu(client):
    """≤ 480 px : Vocabulaire, Réglages, Santé, Diagnostics, la cloche et le thème passent dans le menu « Plus d'actions » (la barre
    débordait de 36 px à 320 px). Au-delà, l'enveloppe est `display: contents` : la barre reste identique."""
    page = client.get("/").text
    bar = page[page.index('<div class="topbar-actions">'):page.index("</header>")]
    btn = re.search(r'<button[^>]*id="topbar-more-btn"[^>]*>', bar).group(0)
    assert 'aria-expanded="false"' in btn and 'aria-controls="topbar-more"' in btn and 'aria-label="' in btn
    menu = bar[bar.index('id="topbar-more"'):]
    for hook in ('id="nav-vocabulary"', 'id="nav-settings"', 'id="nav-health"', 'id="nav-diagnostics"', 'id="notify-toggle"',
                 'id="theme-toggle"'):
        assert hook in menu, hook
    # la palette (loupe) et l'épingle restent dans la barre, avant le bouton du menu
    assert bar.index('id="pin-toggle"') < bar.index('id="cmdk-open"') < bar.index('id="topbar-more-btn"')
    css = (BASE_DIR / "static" / "patrick.css").read_text(encoding="utf-8")
    assert re.search(r"\.topbar-more\s*\{\s*display:\s*contents", css)
    assert "#nav-vocabulary, #nav-settings, #nav-diagnostics { display: none; }" not in css   # plus aucun bouton retiré sans recours
    assert "topbar-more-btn" in (BASE_DIR / "static" / "shell.js").read_text(encoding="utf-8")


def test_topbar_trail_keeps_its_room_on_a_narrow_desktop():
    """1024 px, rail ouvert : la loupe gardait 280 px et le fil de localisation tombait à 1 px, son texte passant sous la puce. Les
    libellés de la loupe et de la puce se replient (une ligne visible) et les actions cèdent leur place avant le fil."""
    css = (BASE_DIR / "static" / "patrick.css").read_text(encoding="utf-8")

    def rule(selector: str) -> str:
        start = css.index("\n" + selector + " {")
        return css[start:css.index("}", start)]

    assert "min-width" not in rule(".search-trigger")
    assert "flex-shrink: 10000" in rule(".topbar-actions")
    for selector in (".search-trigger .search-label", ".machine-chip-text"):
        assert "-webkit-line-clamp: 1" in rule(selector) and "min-width: 0" in rule(selector), selector
