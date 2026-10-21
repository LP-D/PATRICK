"""Disque de données absent (spec 2026-10-21, §4) : le serveur et le worker refusent de démarrer avec un message clair, une page
ou une API qui en a besoin répond 503 expliqué, et un bandeau le dit sur chaque page. Jamais de repli silencieux sur C:."""
from __future__ import annotations

import pytest
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from patrick import paths
from patrick.cli import app as cli_app
from patrick.webapp import i18n
from patrick.webapp.app import app


@pytest.fixture
def absent(tmp_path, monkeypatch):
    """Racine de données configurée mais absente ; tout le reste isolé sous `tmp_path`."""
    root = tmp_path / "PATRICK DATA"
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(root))
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "pc" / ".patrick" / "settings.json"))
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    return root


@pytest.fixture
def needs_data_routes():
    """Deux routes jetables qui lisent un dossier de la racine de données, comme le ferait une vraie page ou API."""
    def api():
        paths.models_dir()

    def page():
        paths.backups_dir()
        return HTMLResponse("inutile")

    app.add_api_route("/api/_needs-data", api, methods=["GET"])
    app.add_api_route("/_needs-data", page, methods=["GET"], response_class=HTMLResponse)
    yield
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") not in ("/api/_needs-data", "/_needs-data")]


@pytest.mark.parametrize("command", ["serve", "worker"])
def test_serve_and_worker_refuse_to_start_without_the_data_disk(absent, command, monkeypatch):
    import uvicorn

    from patrick import worker as worker_module

    started: list[str] = []                                  # sans garde, ces deux appels bloqueraient le test
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append("serve"))
    monkeypatch.setattr(worker_module, "run_worker_loop", lambda **k: started.append("worker"))

    result = CliRunner().invoke(cli_app, [command])

    assert result.exit_code == 1 and "PATRICK DATA" in result.output and "introuvable" in result.output
    assert started == [] and not absent.exists()


def test_an_api_that_needs_the_data_disk_answers_503_with_the_explained_message(absent, needs_data_routes):
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    fr = client.get("/api/_needs-data")
    en = client.get("/api/_needs-data", cookies={i18n.LANG_COOKIE: "en"})

    assert fr.status_code == 503 and "PATRICK DATA" in fr.json()["error"] and "introuvable" in fr.json()["error"]
    assert en.status_code == 503 and "was not found" in en.json()["error"]
    assert not absent.exists()


def test_a_page_that_needs_the_data_disk_answers_503_with_the_explained_message(absent, needs_data_routes):
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    out = client.get("/_needs-data")

    assert out.status_code == 503 and "PATRICK DATA" in out.text and "introuvable" in out.text


def test_every_page_shows_a_banner_while_the_data_disk_is_missing(absent):
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    fr = client.get("/reglages")
    en = client.get("/reglages", cookies={i18n.LANG_COOKIE: "en"})

    assert fr.status_code == 200 and "data-root-banner" in fr.text and "Disque de données introuvable" in fr.text
    assert "Data disk not found" in en.text


def test_no_banner_when_the_data_root_is_present(absent):
    absent.mkdir()
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    assert "data-root-banner" not in client.get("/reglages").text
