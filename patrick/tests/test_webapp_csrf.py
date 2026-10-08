"""Garde globale des requêtes (`webapp/security.py`) : aucune route d'écriture ne doit être pilotable par une page web
d'un autre site (CSRF), et aucune réponse ne doit être lisible via un nom d'hôte hostile (DNS rebinding)."""
from __future__ import annotations

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from patrick.webapp import security
from patrick.webapp.app import app

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
CROSS_SITE = {"origin": "http://evil.example", "sec-fetch-site": "cross-site", "content-type": "text/plain"}
SAME_ORIGIN = {"origin": "http://127.0.0.1:8000", "sec-fetch-site": "same-origin"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    return TestClient(app, base_url="http://127.0.0.1:8000")


def _write_routes() -> list[tuple[str, str]]:
    out = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods & set(WRITE_METHODS)):
                out.append((method, re.sub(r"\{[^}]+\}", "x", route.path)))
    return out


def test_the_app_has_write_routes_to_protect():
    routes = _write_routes()
    assert len(routes) > 20
    for prefix in ("/runs", "/api/wealth", "/api/fund", "/api/settings", "/api/app"):
        assert any(path.startswith(prefix) for _, path in routes), prefix


@pytest.mark.parametrize("method, path", _write_routes(), ids=lambda v: v)
def test_every_write_route_refuses_a_cross_site_request(client, method, path):
    """Le middleware précède le routage : une route ajoutée demain est protégée sans y penser."""
    resp = client.request(method, path, content='{"jobs": 1}', headers=CROSS_SITE)
    assert resp.status_code == 403, (method, path, resp.status_code)


@pytest.mark.parametrize("headers", [
    {"origin": "null"},
    {"origin": "http://127.0.0.1.evil.example:8000"},
    {"origin": "http://localhost:8000"},                                         # autre nom d'hôte : autre origine
    {"sec-fetch-site": "same-site"},
    {"sec-fetch-site": "cross-site"},
])
def test_each_cross_site_signal_is_refused_on_a_write(client, headers):
    assert client.post("/api/settings/scan-jobs", json={"jobs": 1}, headers=headers).status_code == 403


def test_same_origin_writes_and_clients_without_browser_headers_pass(client):
    assert client.post("/api/settings/scan-jobs", json={"jobs": 1}, headers=SAME_ORIGIN).status_code == 200
    assert client.post("/api/settings/scan-jobs", json={"jobs": 1}).status_code == 200      # curl / script
    assert client.post("/api/settings/scan-jobs", json={"jobs": 1},
                       headers={"sec-fetch-site": "none"}).status_code == 200              # barre d'adresse


def test_form_posts_from_the_app_itself_pass(client):
    resp = client.post("/set-lang/fr", headers=SAME_ORIGIN, follow_redirects=False)
    assert resp.status_code != 403


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example:8000", "192.168.1.5:8000", "testserver"])
def test_a_foreign_host_name_is_refused_even_for_reads(client, monkeypatch, host):
    monkeypatch.delenv(security.ENV_EXTRA_HOSTS, raising=False)
    assert client.get("/", headers={"host": host}).status_code == 403
    assert client.get("/api/settings", headers={"host": host}).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8123", "localhost:8000", "LOCALHOST", "[::1]:8000"])
def test_local_host_names_are_accepted(client, host):
    assert client.get("/api/settings", headers={"host": host}).status_code == 200


def test_extra_hosts_come_from_the_environment(client, monkeypatch):
    monkeypatch.setenv(security.ENV_EXTRA_HOSTS, "patrick.maison , autre")
    assert client.get("/api/settings", headers={"host": "patrick.maison:8000"}).status_code == 200
    assert client.get("/api/settings", headers={"host": "inconnu"}).status_code == 403


def test_api_reads_from_another_site_are_refused_but_page_navigation_is_not(client):
    """Un lien depuis un autre site vers une page reste possible (rien n'est modifié ni lisible par l'appelant) ;
    un `fetch` d'API venu d'ailleurs est refusé."""
    nav = {"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate"}
    assert client.get("/api/settings", headers=nav).status_code == 403
    assert client.get("/", headers=nav).status_code == 200
    assert client.get("/static/patrick.css", headers=nav).status_code == 200


def test_check_is_a_pure_function():
    ok = {"host": "127.0.0.1:8000"}
    assert security.check("POST", "/runs", ok) is None
    assert security.check("POST", "/runs", {**ok, "origin": "http://127.0.0.1:8000"}) is None
    assert security.check("POST", "/runs", {**ok, "origin": "http://evil.example"}) is not None
    assert security.check("GET", "/", {**ok, "sec-fetch-site": "cross-site"}) is None
    assert security.check("GET", "/", {"host": "evil.example"}) is not None
    assert security.check("GET", "/", {}) is not None                                     # pas de Host : refusé
