"""Mise à jour pendant un entraînement depuis /reglages (demande du 25/11)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from patrick.desktop import update
from patrick.webapp.app import app
from patrick.webapp.routes import settings as settings_routes


def test_without_a_mode_the_page_is_told_a_training_runs(monkeypatch):
    monkeypatch.setattr(settings_routes.runtime, "worker_running", lambda: True)
    spawned = []
    monkeypatch.setattr(settings_routes, "spawn_relaunch", lambda **kw: spawned.append(kw))
    client = TestClient(app)
    assert client.post("/api/app/update/apply").status_code == 409 and spawned == []


def test_after_run_schedules_and_now_relaunches_with_the_worker_stopped(monkeypatch):
    monkeypatch.setattr(settings_routes.runtime, "worker_running", lambda: True)
    spawned = []
    monkeypatch.setattr(settings_routes, "spawn_relaunch", lambda **kw: spawned.append(kw))
    client = TestClient(app)
    update.clear_pending()
    assert client.post("/api/app/update/apply", json={"mode": "after_run"}).json()["scheduled"] is True
    assert update.pending() is not None and spawned == []
    update.clear_pending()
    assert client.post("/api/app/update/apply", json={"mode": "now"}).json()["ok"] is True
    assert spawned == [{"do_update": True, "stop_worker": True}]


def test_without_training_the_update_starts_right_away(monkeypatch):
    monkeypatch.setattr(settings_routes.runtime, "worker_running", lambda: False)
    spawned = []
    monkeypatch.setattr(settings_routes, "spawn_relaunch", lambda **kw: spawned.append(kw))
    assert TestClient(app).post("/api/app/update/apply").json()["ok"] is True
    assert spawned == [{"do_update": True, "stop_worker": False}]
