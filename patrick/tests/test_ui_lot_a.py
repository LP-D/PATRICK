"""Lot A de l'audit de l'interface (inspiré d'un site vitrine, 2026-11-04) : menu en blocs, deux niveaux de boutons, cartes arrondies,
pastilles de filtre, onglets de section numérotés, bouton retour en haut."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from page_support import FullPageClient as TestClient

from patrick.tracking import db
from patrick.webapp import i18n, nav_registry
from patrick.webapp.app import BASE_DIR, app

STATIC = BASE_DIR / "static"
CSS = (STATIC / "patrick.css").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", json.dumps({"name": "demo", "validation": {"scheme": "walkforward"}}), "cfg", "sha", 42)
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()
    return TestClient(app)


def _panel(html: str) -> str:
    return re.search(r'<div class="mega-panel".*?</div>\s*</div>\s*</div>\s*</div>', html, re.DOTALL).group(0)


# ---------------------------------------------------------------- menu en blocs
def test_mega_menu_lists_every_registry_entry_once(client):
    html = client.get("/").text
    hrefs = re.findall(r'<li><a href="([^"]+)"', _panel(html))
    assert sorted(hrefs) == sorted(e.url for e in nav_registry.NAV_ENTRIES)


def test_mega_menu_is_a_disclosure_button_closed_at_load(client):
    html = client.get("/").text
    assert re.search(r'<button type="button" class="mega-trigger" id="mega-trigger" aria-expanded="false" aria-controls="mega-panel"', html)
    assert re.search(r'<div class="mega-panel" id="mega-panel"[^>]* hidden>', html)


@pytest.mark.parametrize("path, category", [("/", "pilotage"), ("/ml", "modeles"), ("/universe", "classes_actifs"),
                                            ("/simulate", "simulation"), ("/patrimoine", "patrimoine")])
def test_mega_menu_feature_card_follows_the_current_category(client, path, category):
    html = client.get(path).text
    feature = re.search(r'<div class="mega-feature">(.*?)</div>', html, re.DOTALL).group(1)
    assert i18n.translator("fr")(f"nav_cat_desc_{category}") in feature
    assert 'class="mega-col is-current"' in html
    first = nav_registry.entries_for(category)[0]
    assert f'href="{first.url}"' in feature


def test_every_category_has_a_description_in_both_languages():
    for cat in nav_registry.CATEGORIES:
        entry = i18n.STRINGS[f"nav_cat_desc_{cat.key}"]
        assert entry["fr"] and entry["en"] and entry["fr"] != entry["en"]


def test_mega_menu_is_translated(client):
    client.cookies.set("patrick_lang", "en")
    html = client.get("/").text
    assert "Browse" in html and "Open Overview" in html and "Follow your models" in html


# ---------------------------------------------------------------- bouton retour en haut
def test_back_to_top_button_is_hidden_until_the_page_scrolls(client):
    html = client.get("/").text
    assert re.search(r'<button type="button" class="to-top" id="to-top" aria-label="Retour en haut de la page"[^>]* hidden>', html)
    assert ".to-top[hidden] { display: none; }" in CSS and ".to-top.is-visible" in CSS


# ---------------------------------------------------------------- boutons, cartes, pastilles, onglets
def test_buttons_have_two_levels_and_share_the_control_radius():
    # design v4 « Terminal » (ADR 0019) : boutons en rectangles arrondis de 6 px (--radius), comme les champs ; les pastilles restent aux filtres
    for selector in ("button.primary, .btn {", ".btn-secondary, button.secondary {"):
        block = CSS[CSS.index(selector):CSS.index("}", CSS.index(selector))]
        assert "border-radius: var(--radius)" in block, selector
    assert "--radius: 6px" in CSS
    assert ".btn-arrow::after" in CSS and "mask:" in CSS


def test_main_actions_carry_the_arrow(client):
    assert "primary btn-arrow" in client.get("/ml").text
    assert "primary btn-arrow" in client.get("/runs/run1").text


def test_cards_use_the_panel_radius_and_the_shadow_token():
    card = CSS[CSS.index("\n.card {"):CSS.index("\n}", CSS.index("\n.card {"))]
    assert "var(--radius-card)" in card and "var(--shadow-card)" in card
    # v4 : panneaux en aplat (ombre nulle dans les trois thèmes), rayon de 10 px
    assert "--radius-card: 10px" in CSS and CSS.count("--shadow-card:") == 3          # sombre, clair, clair automatique


def test_filter_tabs_are_independent_pills():
    tabs = CSS[CSS.index(".kind-tab {"):CSS.index("}", CSS.index(".kind-tab {"))]
    assert "var(--radius-pill)" in tabs
    assert ".kind-tab.active { background: var(--brand);" in CSS


def test_section_index_tabs_are_numbered_and_track_the_current_section(client):
    assert 'content: counter(sec, decimal-leading-zero)' in CSS
    assert '.section-index a[aria-current="true"]' in CSS
    html = client.get("/runs/run1").text
    assert 'class="section-index"' in html                       # la numérotation est portée par le CSS : aucun numéro en dur
    assert not re.search(r'class="section-index".*?>\s*0\d', html, re.DOTALL)


# ---------------------------------------------------------------- script
@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js absent")
def test_shell_script_parses():
    done = subprocess.run(["node", "--check", str(Path(STATIC / "shell.js"))], capture_output=True, text=True, timeout=60, check=False)
    assert done.returncode == 0, done.stderr
