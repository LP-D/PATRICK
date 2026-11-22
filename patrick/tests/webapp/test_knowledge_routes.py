"""Section Connaissances : parcours, cours, dictionnaire et recherche JSON, en français et en anglais, avec les vrais cours et le vrai dictionnaire."""
from __future__ import annotations

import html as html_lib
import re
import time

import pytest
from fastapi.testclient import TestClient

from patrick.knowledge import courses as C
from patrick.knowledge import dictionary as D
from patrick.webapp import nav_registry
from patrick.webapp.app import app


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))


def _client(lang: str = "fr") -> TestClient:
    client = TestClient(app, base_url="http://localhost")
    client.cookies.set("patrick_lang", lang)
    return client


# ---------------------------------------------------------------- navigation
def test_the_knowledge_section_is_a_sixth_category_with_three_pages():
    assert [c.key for c in nav_registry.CATEGORIES][-1] == "connaissances"
    urls = [e.url for e in nav_registry.NAV_ENTRIES if e.category == "connaissances"]
    assert urls == ["/connaissances", "/connaissances/cours", "/connaissances/dictionnaire"]


@pytest.mark.parametrize("lang, label", [("fr", "CONNAISSANCES"), ("en", "KNOWLEDGE")])
def test_the_section_appears_in_the_sidebar_and_the_command_palette(lang, label):
    html = _client(lang).get("/connaissances").text
    assert label in html and 'href="/connaissances/dictionnaire"' in html and '"url": "/connaissances/dictionnaire"' in html


# ---------------------------------------------------------------- parcours
@pytest.mark.parametrize("lang", ["fr", "en"])
def test_the_hub_shows_three_levels_the_courses_and_the_theme_level_map(lang):
    html = _client(lang).get("/connaissances").text
    assert html.count('class="card kb-level-card') == 3
    assert "/connaissances/cours/econometrie" in html and "/connaissances/cours/evenements-de-resultats" in html
    assert "/connaissances/dictionnaire?theme=risque&amp;niveau=2" in html and "?niveau=1" in html
    assert 'name="q"' in html


# ---------------------------------------------------------------- cours
def test_the_course_list_shows_both_courses_with_reading_time():
    html = html_lib.unescape(_client().get("/connaissances/cours").text)
    assert html.count("kb-course-card") >= 2 and "min de lecture" in html
    assert "L'économétrie d'une série financière" in html and "Les événements de résultats" in html


def test_the_econometrics_course_is_readable_with_outline_formulas_and_linked_entries():
    html = _client().get("/connaissances/cours/econometrie").text
    assert 'id="2-stationnarite-et-racine-unitaire"' in html and 'href="#2-stationnarite-et-racine-unitaire"' in html and 'data-toc="2-stationnarite-et-racine-unitaire"' in html
    assert "<table" in html and "<pre" in html and "Notions de ce cours" in html and "/connaissances/dictionnaire#term-garch_notion" in html


def test_the_earnings_course_typesets_its_formulas_and_has_a_chapter_outline():
    html = _client().get("/connaissances/cours/evenements-de-resultats").text
    assert html.count("<math") > 600 and "tex-unknown" not in html
    assert 'data-toc="partie-i-mesurer-un-evenement"' in html and "chapitre-7-les-sept-tests-d-un-caar" in html


def test_an_english_visitor_is_told_the_course_text_is_french():
    assert "written in French" in _client("en").get("/connaissances/cours/econometrie").text


def test_an_unknown_course_is_a_404():
    assert _client().get("/connaissances/cours/nope").status_code == 404


def test_a_missing_course_folder_shows_a_notice_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "COURSES_DIR", tmp_path / "absent")
    client = _client()
    assert "Cours indisponible" in client.get("/connaissances/cours/econometrie").text
    assert client.get("/connaissances/cours").status_code == 200 and client.get("/connaissances").status_code == 200


# ---------------------------------------------------------------- dictionnaire
@pytest.mark.parametrize("lang, label", [("fr", "Ratio de Sharpe"), ("en", "Sharpe ratio")])
def test_the_dictionary_page_lists_every_entry_in_the_visitors_language(lang, label):
    html = _client(lang).get("/connaissances/dictionnaire").text
    assert len(re.findall(r'<article class="kb-term"', html)) == len(D.all_terms())
    assert 'id="term-sharpe_ratio"' in html and label in html and 'id="term-p_value"' in html


def test_every_anchor_link_of_the_dictionary_points_to_an_entry_and_every_course_link_to_a_chapter():
    html = _client().get("/connaissances/dictionnaire").text
    ids = set(re.findall(r'id="(term-[^"]+)"', html))
    assert len(ids) == len(D.all_terms())
    assert not [h for h in set(re.findall(r'href="#(term-[^"]+)"', html)) if h not in ids]
    for slug, anchor in set(re.findall(r'href="/connaissances/cours/([a-z-]+)#([^"]+)"', html)):
        assert anchor in {h["id"] for h in C.load(slug).toc}, (slug, anchor)


def test_the_dictionary_page_has_filters_the_alphabet_and_typeset_formulas():
    html = _client().get("/connaissances/dictionnaire").text
    assert 'id="kb-search"' in html and 'id="kb-theme"' in html and html.count("data-level=") > 700 and 'data-letter-link="S"' in html
    assert html.count('class="kb-formula"') >= 90 and "<math" in html


def test_the_dictionary_page_is_built_once_and_stays_a_reasonable_size():
    client = _client()
    client.get("/connaissances/dictionnaire")                          # construit la vue
    start = time.perf_counter()
    response = client.get("/connaissances/dictionnaire")
    assert time.perf_counter() - start < 2.0 and len(response.content) < 2_500_000


# ---------------------------------------------------------------- recherche JSON
def test_the_search_api_returns_ranked_entries_with_a_link():
    body = _client().get("/api/dictionary/search", params={"q": "sharpe"}).json()
    assert body["results"][0]["key"] == "sharpe_ratio" and body["results"][0]["url"].endswith("#term-sharpe_ratio")
    assert _client().get("/api/dictionary/search", params={"q": ""}).json()["results"] == []
    assert len(_client().get("/api/dictionary/search", params={"q": "risque", "limit": 3}).json()["results"]) <= 3
