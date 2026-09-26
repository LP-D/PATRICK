"""feature/nav-categories-registry -- `webapp/nav_registry.py` est la SEULE
source de la nav laterale (`base_v2.html`) : 4 categories fixes (PILOTAGE /
CLASSES D'ACTIFS / SIMULATION / PATRIMOINE), aucune page orpheline, aucun
lien de nav code en dur. Meme style que test_webapp_security_regressions.py :
vraies routes FastAPI + vrais templates Jinja, base SQLite isolee via
PATRICK_DB_PATH, pas de reseau (yfinance/fondamentaux monkeypatches)."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from patrick.data.sources import fundamentals_source
from patrick.validation import equity_sufficiency
from patrick.webapp import i18n, nav_registry
from patrick.webapp.app import app

TEMPLATES_DIR = Path(nav_registry.__file__).resolve().parent / "templates"

EXPECTED_CATEGORIES = ["pilotage", "classes_actifs", "simulation", "patrimoine"]


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    # /launch et /equities appellent yfinance (badge de suffisance) et les
    # fondamentaux -- stubs identiques a test_equity_asset_class.py.
    monkeypatch.setattr(
        equity_sufficiency.yfinance_source, "download_one",
        lambda symbol, start: pd.Series(np.arange(100, dtype=float)),
    )
    monkeypatch.setattr(fundamentals_source, "fetch_fundamentals",
                        lambda symbol: pd.DataFrame(columns=["fiscalDateEnding", "metric", "value"]))


def _app_get_paths() -> set[str]:
    return {
        r.path for r in app.routes
        if isinstance(r, APIRoute) and "GET" in r.methods
    }


# ---------------------------------------------------------------------------
# Structure du registre
# ---------------------------------------------------------------------------

def test_categories_are_the_four_fixed_ones_in_order():
    assert [c.key for c in nav_registry.CATEGORIES] == EXPECTED_CATEGORIES
    assert [c.label for c in nav_registry.CATEGORIES] == [
        "PILOTAGE", "CLASSES D'ACTIFS", "SIMULATION", "PATRIMOINE",
    ]


def test_every_entry_belongs_to_a_known_category():
    for entry in nav_registry.NAV_ENTRIES:
        assert entry.category in EXPECTED_CATEGORIES, entry


def test_no_duplicate_slug():
    slugs = [e.slug for e in nav_registry.NAV_ENTRIES]
    assert len(slugs) == len(set(slugs)), slugs


def test_no_duplicate_url_or_child_route():
    owned = [e.url for e in nav_registry.NAV_ENTRIES]
    owned += [c for e in nav_registry.NAV_ENTRIES for c in e.child_routes]
    assert len(owned) == len(set(owned)), owned


def test_no_duplicate_order_within_a_category():
    for cat in EXPECTED_CATEGORIES:
        orders = [e.order for e in nav_registry.NAV_ENTRIES if e.category == cat]
        assert len(orders) == len(set(orders)), (cat, orders)


# ---------------------------------------------------------------------------
# Resolution des routes / pages orphelines
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entry", nav_registry.NAV_ENTRIES, ids=lambda e: e.slug)
def test_every_registry_url_resolves(entry):
    resp = TestClient(app).get(entry.url)
    assert resp.status_code == 200, (entry.url, resp.status_code)


def test_every_registry_route_is_declared_on_the_app():
    paths = _app_get_paths()
    for entry in nav_registry.NAV_ENTRIES:
        assert entry.url in paths, entry.url
        for child in entry.child_routes:
            assert child in paths, child


def test_child_route_target_page_resolves():
    """Route enfant parametree : une cible connue de l'univers doit rendre."""
    resp = TestClient(app).get("/targets/^VIX")
    assert resp.status_code == 200


def test_no_orphan_page_route():
    """Toute route GET de l'app est soit une page du registre (url ou route
    enfant), soit declaree non-page (API/JSON/fichier/redirect). Ajouter une
    page sans passer par le registre fait echouer ce test."""
    registered = set(nav_registry.registered_routes())
    orphans = sorted(
        p for p in _app_get_paths()
        if p not in registered and not nav_registry.is_non_page_route(p)
    )
    assert orphans == []


def test_non_page_declarations_do_not_shadow_registry_pages():
    for route in nav_registry.registered_routes():
        assert not nav_registry.is_non_page_route(route), route


# ---------------------------------------------------------------------------
# Rendu de la sidebar
# ---------------------------------------------------------------------------

def _sidebar(html: str) -> str:
    m = re.search(r'<nav class="sidebar-nav".*?</nav>', html, re.DOTALL)
    assert m is not None, "sidebar-nav introuvable"
    return m.group(0)


def _groups(sidebar_html: str) -> list[tuple[str, list[str]]]:
    """[(en-tete, [hrefs...]), ...] dans l'ordre du rendu."""
    out = []
    for g in re.finditer(r'<div class="sidebar-nav-group"[^>]*>(.*?)</div>', sidebar_html, re.DOTALL):
        body = g.group(1)
        heading = re.search(r'class="sidebar-nav-heading"[^>]*>([^<]*)<', body)
        hrefs = re.findall(r'<a href="([^"]+)"', body)
        out.append((heading.group(1).strip() if heading else None, hrefs))
    return out


def test_sidebar_is_grouped_by_category_with_section_headings():
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    groups = _groups(_sidebar(resp.text))

    expected = []
    for cat in nav_registry.CATEGORIES:
        entries = nav_registry.entries_for(cat.key)
        if entries:
            expected.append((cat.label.replace("'", "&#39;"), [e.url for e in entries]))
    assert groups == expected

    headings = [h for h, _ in groups]
    assert headings[0] == "PILOTAGE"
    assert "CLASSES D&#39;ACTIFS" in headings


def test_empty_category_is_not_rendered(monkeypatch):
    """Une categorie sans entree ne produit ni section ni en-tete -- teste sur
    un registre reduit, independamment du contenu courant de NAV_ENTRIES."""
    subset = tuple(e for e in nav_registry.NAV_ENTRIES if e.category != "simulation")
    monkeypatch.setattr(nav_registry, "NAV_ENTRIES", subset)
    keys = [s["key"] for s in nav_registry.nav_sections("/")]
    assert "simulation" not in keys
    resp = TestClient(app).get("/")
    side = _sidebar(resp.text)
    assert 'id="nav-cat-simulation"' not in side
    assert 'href="/simulate"' not in side


def test_patrimoine_category_lists_accounts_and_movements():
    """Roadmap bloc 4 : PATRIMOINE n'est plus vide -- comptes et mouvements,
    URLs a plat pour qu'une seule entree s'allume a la fois."""
    side = _sidebar(TestClient(app).get("/").text)
    assert 'id="nav-cat-patrimoine"' in side
    assert 'href="/patrimoine"' in side and 'href="/mouvements"' in side
    current = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"',
                         _sidebar(TestClient(app).get("/mouvements").text))
    assert current == ["/mouvements"]


def test_sidebar_links_all_registry_entries_exactly_once():
    resp = TestClient(app).get("/")
    hrefs = re.findall(r'<a href="([^"]+)"', _sidebar(resp.text))
    assert sorted(hrefs) == sorted(e.url for e in nav_registry.NAV_ENTRIES)


@pytest.mark.parametrize("path, expected_current", [
    ("/", "/"),
    ("/launch", "/launch"),
    ("/runs", "/runs"),
    ("/commodities", "/commodities"),
    ("/simulate", "/simulate"),
    ("/portfolio", "/portfolio"),
    ("/phase9", "/phase9"),
])
def test_sidebar_active_state_follows_current_route(path, expected_current):
    resp = TestClient(app).get(path)
    assert resp.status_code == 200
    current = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', _sidebar(resp.text))
    assert current == [expected_current]


def test_active_state_rule_matches_legacy_prefix_behaviour():
    """Regle historique de base_v2.html, conservee a l'identique : `/` exact,
    les autres par prefixe (donc /runs/{id}/detail allume Historique,
    /targets/{ticker} n'allume rien)."""
    by_slug = {e.slug: e for e in nav_registry.NAV_ENTRIES}
    assert nav_registry.is_active(by_slug["synthese"], "/")
    assert not nav_registry.is_active(by_slug["synthese"], "/runs")
    assert nav_registry.is_active(by_slug["runs"], "/runs/abc/detail")
    assert not any(nav_registry.is_active(e, "/targets/^VIX") for e in nav_registry.NAV_ENTRIES)


def test_base_template_has_no_hardcoded_nav_link():
    """Anti-duplication : la nav laterale ne contient plus aucun href en dur,
    tout vient du registre."""
    src = (TEMPLATES_DIR / "base_v2.html").read_text(encoding="utf-8")
    m = re.search(r'<nav class="sidebar-nav".*?</nav>', src, re.DOTALL)
    assert m is not None
    assert 'href="/' not in m.group(0)


def test_no_other_template_defines_a_sidebar_nav():
    for tpl in TEMPLATES_DIR.glob("*.html"):
        if tpl.name == "base_v2.html":
            continue
        assert "sidebar-nav" not in tpl.read_text(encoding="utf-8"), tpl.name


def test_sidebar_labels_are_translated():
    client = TestClient(app)
    client.cookies.set(i18n.LANG_COOKIE, "en")
    resp = client.get("/")
    side = _sidebar(resp.text)
    assert ">Overview<" in side
    assert "ASSET CLASSES" in side
