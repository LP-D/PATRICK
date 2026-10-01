"""Integration guard for the glossary search controls and client-side lookup."""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from patrick.webapp.app import app

WEBAPP_DIR = Path(__file__).resolve().parents[1] / "patrick" / "webapp"


def test_glossary_popover_exposes_accessible_search_controls():
    template = (WEBAPP_DIR / "templates" / "base_v2.html").read_text(encoding="utf-8")

    assert 'id="glossary-search-input"' in template
    assert 'for="glossary-search-input"' in template
    assert 'id="glossary-search-status" class="glossary-search-status" role="status" aria-live="polite"' in template
    assert 'id="glossary-search-results"' in template
    assert 'id="glossary-labels"' in template


def test_glossary_popover_renders_localized_terms_and_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    response = TestClient(app).get("/")

    assert response.status_code == 200
    glossary_match = re.search(
        r'<script id="glossary-data" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    labels_match = re.search(
        r'<script id="glossary-labels" type="application/json">(.*?)</script>',
        response.text,
        re.DOTALL,
    )
    assert glossary_match and labels_match
    glossary = json.loads(glossary_match.group(1))
    labels = json.loads(labels_match.group(1))
    assert glossary["technical"]
    assert labels["data_quality_enabled"]


def test_glossary_search_matches_labels_and_definitions_without_html_injection():
    script = (WEBAPP_DIR / "static" / "glossary.js").read_text(encoding="utf-8")

    assert 'termLabel(term) + " " + term + " " + GLOSSARY[term]' in script
    assert 'normalize("NFD")' in script
    assert "label.textContent = termLabel(term)" in script
    assert "excerpt.textContent = GLOSSARY[term]" in script
    assert "innerHTML" not in script
