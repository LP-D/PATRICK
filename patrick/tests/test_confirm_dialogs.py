"""Plus aucune boîte native `confirm` : une boîte de la page, partagée (base_v2.html + static/confirm.js)."""
from __future__ import annotations

import re
from pathlib import Path

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick import webapp
from patrick.webapp.app import app

WEBAPP = Path(webapp.__file__).parent
NATIVE_CONFIRM = re.compile(r"(?<![\w.])(?:window\.)?(?:confirm|prompt|alert)\(")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def test_no_native_browser_dialog_remains_in_templates_and_scripts():
    offenders = {}
    for path in [*WEBAPP.glob("templates/*.html"), *WEBAPP.glob("static/*.js")]:
        hits = NATIVE_CONFIRM.findall(path.read_text(encoding="utf-8"))
        if hits:
            offenders[path.name] = hits
    assert offenders == {}


def test_a_delete_form_asks_through_the_page_not_through_an_inline_handler():
    runs = (WEBAPP / "templates" / "runs.html").read_text(encoding="utf-8")
    assert re.search(r'<form[^>]*action="/runs/\{\{ r\.run_id \}\}/delete"[^>]*data-confirm="[^"]+"', runs)
    assert "onsubmit" not in runs


@pytest.mark.parametrize("url", ["/simulate", "/fonds", "/runs", "/patrimoine"])
def test_every_page_carries_the_shared_confirmation_dialog_and_its_script(client, url):
    html = client.get(url).text
    assert '<dialog id="confirm-dialog" class="modal"' in html
    assert 'id="confirm-message"' in html and 'id="confirm-ok"' in html
    assert '<script src="/static/confirm.js"></script>' in html
    assert "Confirmation" in html and "Annuler" in html and 'data-default-label="Confirmer"' in html
    english = client.get(f"{url}?lang=en").text
    assert "Cancel" in english and 'data-default-label="Confirm"' in english


def test_the_shared_script_exposes_the_dialog_helpers_and_handles_data_confirm_forms(client):
    js = client.get("/static/confirm.js").text
    assert "window.patrickDialog" in js and "form[data-confirm]" in js
    wealth = client.get("/static/wealth.js").text
    assert "patrickDialog.confirm" in wealth


def test_the_launch_page_shows_run_control_errors_in_a_banner(client):
    html = client.get("/ml").text
    assert re.search(r'<[^>]*id="run-control-error"[^>]*class="[^"]*banner-error[^"]*hidden', html) or \
        re.search(r'<[^>]*id="run-control-error"[^>]*class="[^"]*hidden[^"]*banner-error', html)
    assert 'role="alert"' in html.split('id="run-control-error"')[1].split(">")[0]
