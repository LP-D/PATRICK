"""Texte minimal : les aides statiques passent derrière un « ? » (`static/help.js`). Le comportement est côté navigateur ;
ces gardes vérifient ce qui peut l'être sans navigateur : le script est chargé sur toutes les pages, le CSS cache les aides avant
son passage, la chaîne d'accessibilité est traduite, et le motif ARIA d'ouverture est posé."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrick.webapp import i18n
from patrick.webapp.app import app

WEBAPP = Path(i18n.__file__).resolve().parent
JS = (WEBAPP / "static" / "help.js").read_text(encoding="utf-8")
GLOSSARY_JS = (WEBAPP / "static" / "glossary.js").read_text(encoding="utf-8")
CSS = (WEBAPP / "static" / "patrick.css").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))


@pytest.mark.parametrize("path", ["/", "/ml", "/runs", "/reglages", "/portfolio"])
def test_every_page_loads_the_help_script_and_the_pending_guard(path):
    html = TestClient(app).get(path).text
    assert '<script src="/static/help.js"></script>' in html
    assert 'classList.add("help-pending")' in html
    # help.js doit passer après glossary.js (il ne capte que ses propres boutons `.help-q`, jamais `.info-icon`).
    assert html.index("/static/glossary.js") < html.index("/static/help.js")


def test_the_help_script_never_touches_the_glossary_buttons():
    assert 'closest(".help-q")' in JS
    assert "info-icon" not in JS


def test_dynamic_status_messages_are_protected():
    for guard in ('hasAttribute("aria-live")', 'hasAttribute("role")', 'hasAttribute("data-keep")', "el.id"):
        assert guard in JS, guard
    # l'opt-in explicite pour un texte d'aide réécrit par un script
    assert 'data-help") === "fold"' in JS


def test_the_css_hides_help_before_the_script_runs_and_styles_the_question_mark():
    assert ".help-folded { display: none !important; }" in CSS
    assert re.search(r"\.help-pending :is\(\.hint, \.page-subtitle", CSS)
    assert ".help-q::before" in CSS and ".help-pop" in CSS


def test_the_selector_lists_of_the_script_and_the_css_agree():
    js = re.search(r'var STATIC = "(.*?)";', JS, re.DOTALL).group(1)
    js = re.sub(r'"\s*\+\s*"', "", js)
    css = re.search(r"\.help-pending :is\((.*?)\):is\(", CSS).group(1)
    assert [s.strip() for s in js.split(", ") if s.strip()] == [s.strip() for s in css.split(", ") if s.strip()]


def test_the_accessible_name_is_translated_in_the_browser_strings():
    assert i18n.js_strings("fr")["help_aria"] == "Aide"
    assert i18n.js_strings("en")["help_aria"] == "Help"



def test_a_short_sentence_stays_visible_instead_of_hiding_behind_a_question_mark():
    limit = int(re.search(r"var INLINE_MAX = (\d+);", JS).group(1))
    assert 80 <= limit <= 160                       # une phrase courte, pas un paragraphe
    assert "length > (el.closest(\"[data-help-host]\") ? INLINE_CARD_MAX : INLINE_MAX)" in JS   # `eligible` ne replie que le plus long
    card = int(re.search(r"var INLINE_CARD_MAX = (\d+);", JS).group(1))
    assert limit <= card <= 200                     # une carte de profil garde sa description, toutes ou aucune
    assert "INLINE_PAREN_MAX" in JS                 # idem pour « Libellé (explication) »


def test_data_and_hover_bubbles_are_never_folded():
    skip = re.search(r'var SKIP_INSIDE = (.*?);', JS, re.DOTALL).group(1)
    # `.pop-content` / `.pred-pop` : la bulle de survol des prédictions recopie son contenu (predictions_pop.js) ;
    # `td, th, summary` : une cellule ou un résumé porte des données (durée d'historique, dates), jamais de l'aide.
    for selector in (".pop-content", ".pred-pop", "td", "th", "summary"):
        assert selector in skip, selector


def test_help_outside_any_panel_joins_the_page_title_and_identical_texts_are_shown_once():
    assert "function pageTitle" in JS and "return pageTitle(el)" in JS
    assert "seen[key]" in JS


def test_the_glossary_merges_its_icons_one_per_block_and_one_per_title():
    assert "function mergeIcons" in GLOSSARY_JS
    for needle in ("details.adv", ".adv-title", "#selection-method-info", "neighbourIcon", "glossary-multi"):
        assert needle in GLOSSARY_JS, needle
    assert ".glossary-multi" in CSS
