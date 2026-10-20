"""Notification de fin de run : bouton cloche sur toutes les pages, chaînes livrées en FR et EN, script chargé une fois."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from patrick.webapp.app import app
from patrick.webapp.i18n_notify import NOTIFY_STRINGS


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    return TestClient(app)


def _i18n(html: str) -> dict:
    return json.loads(re.search(r'<script id="i18n-data" type="application/json">(.*?)</script>', html, re.DOTALL).group(1))


@pytest.mark.parametrize("path", ["/", "/runs", "/diagnostics", "/risque", "/donnees"])
def test_every_page_carries_the_bell_and_its_strings(client, path):
    html = client.get(path).text
    assert 'id="notify-toggle"' in html and html.count("/static/run_notify.js") == 1
    data = _i18n(html)
    assert set(NOTIFY_STRINGS) <= set(data) and "{name}" in data["nt_done"]


def test_strings_exist_in_both_languages_with_the_same_placeholders():
    for key, tr in NOTIFY_STRINGS.items():
        assert tr["fr"] and tr["en"], key
        assert set(re.findall(r"\{(\w+)\}", tr["fr"])) == set(re.findall(r"\{(\w+)\}", tr["en"])), key


def test_language_follows_the_query_parameter(client):
    assert _i18n(client.get("/?lang=en").text)["nt_toggle_off"] == NOTIFY_STRINGS["nt_toggle_off"]["en"]
    assert _i18n(client.get("/?lang=fr").text)["nt_toggle_off"] == NOTIFY_STRINGS["nt_toggle_off"]["fr"]


def test_script_never_renders_server_text_as_html():
    src = (Path(__file__).resolve().parents[1] / "patrick" / "webapp" / "static" / "run_notify.js").read_text(encoding="utf-8")
    assert "innerHTML" not in src and "insertAdjacentHTML" not in src and "document.write" not in src
