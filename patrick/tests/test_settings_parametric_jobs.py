"""Réglage « workers du pool paramétrique » : fichier de réglages, priorité
env > réglage, API de la page Lancer. Le réglage ne change pas le résultat des runs."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from patrick import settings
from patrick.features import parametric_parallel
from patrick.webapp.app import app


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(tmp_path / "settings.json"))
    monkeypatch.delenv(parametric_parallel.ENV_JOBS, raising=False)


def test_default_is_sequential_and_roundtrip():
    assert settings.get_parametric_jobs() == 1
    settings.save({settings.KEY_PARAMETRIC_JOBS: 3})
    assert settings.get_parametric_jobs() == 3
    settings.save({"other": 1})                       # fusion, pas écrasement
    assert settings.get_parametric_jobs() == 3


def test_corrupt_file_falls_back_to_one(tmp_path):
    settings.settings_path().write_text("{not json")
    assert settings.get_parametric_jobs() == 1


def test_resolve_jobs_uses_setting_then_env_wins(monkeypatch):
    cpu = os.cpu_count() or 1
    settings.save({settings.KEY_PARAMETRIC_JOBS: 2})
    assert parametric_parallel.resolve_jobs(10) == min(2, cpu)
    monkeypatch.setenv(parametric_parallel.ENV_JOBS, "1")
    assert parametric_parallel.resolve_jobs(10) == 1


def test_api_get_and_set():
    client = TestClient(app)
    body = client.get("/api/settings").json()
    assert body["parametric_jobs"] == 1 and body["max_parametric_jobs"] >= 1
    assert client.post("/api/settings/parametric-jobs", json={"jobs": 1}).status_code == 200
    assert client.post("/api/settings/parametric-jobs", json={"jobs": 0}).status_code == 400
    assert client.post("/api/settings/parametric-jobs", json={"jobs": 10_000}).status_code == 400
    assert client.post("/api/settings/parametric-jobs", json={"jobs": "x"}).status_code == 400
    assert client.post("/api/settings/parametric-jobs", json={}).status_code == 400


def test_launch_page_shows_the_setting_and_keeps_it_out_of_the_form():
    html = TestClient(app).get("/launch").text
    assert 'id="setting-parametric-jobs"' in html
    assert 'name="parametric' not in html
