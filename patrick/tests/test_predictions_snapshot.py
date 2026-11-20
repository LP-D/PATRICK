"""Tableau de /predictions : lu dans un instantané enregistré, JAMAIS calculé à l'ouverture de la page (3 minutes sur la vraie base).

Recalculé en tâche de fond (fin d'actualisation live, tâche de nuit, démarrage si absent ou vieux), servi tel quel en attendant."""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import patrick.webapp.app as webapp
from patrick import live_refresh
from patrick.tracking import db
from patrick.webapp import predictions_snapshot as snap

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _seed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", "{}", "cfghash", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_predictions(conn, trial_id, fold_index=None, split="live", ts=["2026-11-19T00:00:00"],
                       y_true=[None], y_pred=[3], y_proba=[0.71])
    db.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()
    return str(tmp_path / "patrick.db")


def _payload(computed_at=NOW, marker=(1, "2026-11-19T00:00:00")):
    return {"version": snap.VERSION, "computed_at": computed_at.isoformat(), "live_marker": marker}


@pytest.mark.parametrize("age, same_marker, live_running, expected", [
    (timedelta(hours=1), True, False, False),          # frais, rien de nouveau
    (timedelta(hours=25), True, False, True),          # plus de 24 h : recalcul même sans nouveau signal
    (timedelta(hours=2), False, False, True),          # de nouveaux signaux live sont apparus
    (timedelta(minutes=10), False, False, False),      # ... mais pas plus d'un recalcul toutes les 30 min
    (timedelta(hours=2), False, True, False),          # ... et jamais pendant une actualisation (elle déclenche le sien à sa fin)
])
def test_refresh_policy(age, same_marker, live_running, expected):
    payload = _payload(computed_at=NOW - age)
    marker_now = payload["live_marker"] if same_marker else (2, "2026-11-20T00:00:00")
    assert snap.needs_refresh(payload, marker_now, NOW, live_running) is expected


def test_no_snapshot_always_needs_a_refresh():
    assert snap.needs_refresh(None, (0, None), NOW, live_running=True) is True


def test_snapshot_roundtrip_and_other_versions_are_ignored(tmp_path):
    path = str(tmp_path / "patrick.db")
    assert snap.load(path) is None
    snap.save({**_payload(), "directional": {"groups": [], "horizons": [1, 5]}}, path)
    assert snap.load(path)["directional"]["horizons"] == [1, 5]
    assert snap.snapshot_path(path).parent == tmp_path                 # à côté de la base qu'il résume
    snap.save({**_payload(), "version": snap.VERSION + 1}, path)       # forme du tableau changée : l'ancien instantané ne sert plus
    assert snap.load(path) is None


def test_first_build_is_waited_for_then_reused_without_recomputing(tmp_path, monkeypatch):
    path = _seed(tmp_path, monkeypatch)
    calls = []
    real = snap.compute
    monkeypatch.setattr(snap, "compute", lambda db_path=None: calls.append(1) or real(db_path))

    first = snap.get(path, wait_first=30)
    again = snap.get(path, wait_first=30)

    assert first is not None and first["directional"]["groups"] and again["computed_at"] == first["computed_at"]
    assert len(calls) == 1                                              # le second affichage ne recalcule rien


def test_a_request_during_a_refresh_triggers_exactly_one_more_pass(tmp_path, monkeypatch):
    path = str(tmp_path / "patrick.db")
    started, release, runs = threading.Event(), threading.Event(), []

    def slow_refresh(db_path=None):
        runs.append(1)
        started.set()
        release.wait(5)

    monkeypatch.setattr(snap, "refresh_sync", slow_refresh)
    snap.request_refresh(path)
    assert started.wait(5)
    snap.request_refresh(path)                                          # les données ont bougé pendant le calcul
    snap.request_refresh(path)                                          # ... une fois, pas deux
    release.set()
    deadline = time.monotonic() + 5
    while snap.status(path)["running"] and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(runs) == 2 and snap.status(path)["running"] is False


def test_a_page_request_does_not_stack_a_second_pass_on_a_running_one(tmp_path, monkeypatch):
    path = str(tmp_path / "patrick.db")
    started, release, runs = threading.Event(), threading.Event(), []

    def slow_refresh(db_path=None):
        runs.append(1)
        started.set()
        release.wait(5)

    monkeypatch.setattr(snap, "refresh_sync", slow_refresh)
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    db.connect(path).close()
    snap.get(path)                                                      # aucun instantané : lance le premier calcul
    assert started.wait(5)
    for _ in range(3):
        snap.get(path)                                                  # des ouvertures de page pendant le calcul : aucun calcul de plus
    release.set()
    deadline = time.monotonic() + 5
    while snap.status(path)["running"] and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(runs) == 1


def test_the_fragment_is_served_from_the_snapshot_and_never_computes_on_open(tmp_path, monkeypatch):
    path = _seed(tmp_path, monkeypatch)
    snap.refresh_sync(path)                                             # ce que fait la nuit, ou la fin d'une actualisation

    def boom(*args, **kwargs):
        raise AssertionError("le tableau ne doit pas être recalculé à l'ouverture de la page")

    monkeypatch.setattr(webapp, "_predictions_overview", boom)
    client = TestClient(webapp.app)
    for url in ("/fragments/predictions", "/fragments/predictions?kind=alpha", "/fragments/predictions-horizon"):
        response = client.get(url)
        assert response.status_code == 200, url
    html = client.get("/fragments/predictions").text
    assert "^VIX" in html or "VIX" in html and "Tableau calculé le" in html


def test_a_stale_snapshot_is_served_at_once_and_refreshed_in_the_background(tmp_path, monkeypatch):
    path = _seed(tmp_path, monkeypatch)
    payload = snap.compute(path)
    payload["computed_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()   # vieux de deux jours
    snap.save(payload, path)
    requested = []
    monkeypatch.setattr(snap, "request_refresh", lambda db_path=None, rerun_if_running=True: requested.append(1) or True)
    monkeypatch.setattr(webapp, "_predictions_overview", lambda *a, **k: (_ for _ in ()).throw(AssertionError("calcul à l'ouverture")))

    response = TestClient(webapp.app).get("/fragments/predictions")

    assert response.status_code == 200 and "Tableau calculé le" in response.text
    assert requested == [1]


def test_first_computation_answers_202_with_a_message_instead_of_blocking(tmp_path, monkeypatch):
    path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    db.connect(path).close()
    release = threading.Event()
    monkeypatch.setattr(snap, "refresh_sync", lambda db_path=None: release.wait(5))
    monkeypatch.setattr(snap, "FIRST_BUILD_WAIT_S", 0.0)

    response = TestClient(webapp.app).get("/fragments/predictions")
    release.set()

    assert response.status_code == 202 and "Le tableau se prépare" in response.text


def test_market_state_is_recomputed_at_each_view_not_frozen_in_the_snapshot():
    market = {"class": "equities_us", "open_args": (None, None), "open_now": True}
    cell = {"ts": "2026-11-19T00:00:00", "market": market, "market_closed": False}
    overview = {"groups": [{"group": "g", "assets": [{"symbol": "^GSPC", "cells": {1: cell}}]}], "horizons": [1]}

    webapp._refresh_time_dependent(overview, datetime(2026, 11, 21, 15, 0, tzinfo=UTC))      # samedi
    assert market["open_now"] is False and cell["market_closed"] is True
    webapp._refresh_time_dependent(overview, datetime(2026, 11, 19, 15, 0, tzinfo=UTC))      # jeudi, séance en cours
    assert market["open_now"] is True and cell["market_closed"] is False


def test_the_end_of_a_pass_and_the_nightly_task_refresh_the_snapshot_in_their_own_process(tmp_path, monkeypatch):
    path = _seed(tmp_path, monkeypatch)

    live_refresh.refresh_predictions_snapshot(path, background=False)    # tâche de nuit : dans ce processus
    first = snap.load(path)
    assert first is not None and first["directional"]["groups"]

    assert snap.refresh_if_stale_sync(path) is False                     # rien de nouveau : pas de second calcul de 3 minutes

    conn = db.connect(path)                                              # un nouveau signal live apparaît
    trial_id = conn.execute("SELECT trial_id FROM trial").fetchone()[0]
    db.add_predictions(conn, trial_id, fold_index=None, split="live", ts=["2026-11-20T00:00:00"],
                       y_true=[None], y_pred=[2], y_proba=[0.6])
    conn.close()
    assert snap.refresh_if_stale_sync(path) is True
    assert snap.load(path)["computed_at"] != first["computed_at"]
