"""Un worker vivant ne doit jamais être pris pour mort (2026-09-27, GSPC_62) :
son battement de cœur n'était rafraîchi qu'à chaque ligne affichée ; dans une
phase silencieuse de plus de 30 s (diagnostic holdout), le serveur l'a cru
mort à la soumission suivante, a lancé un 2e worker, et ce dernier a marqué
'error' / 'failed' un job et ses runs encore en plein calcul (seul critère :
plus d'une heure d'âge). Désormais : battement de cœur par un fil dédié,
indépendant de ce que le pipeline affiche, et un job n'est déclaré abandonné
que si le processus de son worker n'existe plus.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import time

import pytest

from patrick import worker as worker_module
from patrick.config.schema import RunConfig
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", path)
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))
    trackdb.connect(path).close()
    return path


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _insert_running_job(conn, job_id: str, worker_pid: int | None, hours_ago: float) -> None:
    with conn:
        conn.execute(
            "INSERT INTO job (job_id, config_json, status, created_at, started_at, worker_pid) "
            "VALUES (?, '{}', 'running', datetime('now', ?), datetime('now', ?), ?)",
            (job_id, f"-{hours_ago} hours", f"-{hours_ago} hours", worker_pid),
        )


def _insert_running_run(conn, run_id: str, job_id: str | None, hours_ago: float) -> None:
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    with conn:
        conn.execute(
            "INSERT INTO run (run_id, started_at, status, target, horizon, snapshot_id, "
            "config_json, config_hash, git_sha, seed, lib_versions, job_id) VALUES "
            "(?, datetime('now', ?), 'running', '^TEST', 5, 'snap1', '{}', 'cfg', 'sha', 42, '{}', ?)",
            (run_id, f"-{hours_ago} hours", job_id),
        )


def test_pid_alive_distinguishes_live_and_dead_processes():
    import os

    assert jobs_db.pid_alive(os.getpid())
    assert not jobs_db.pid_alive(_dead_pid())
    assert not jobs_db.pid_alive(None)
    assert not jobs_db.pid_alive(0)


def test_old_job_of_a_live_worker_is_not_reaped(db_path):
    import os

    conn = trackdb.connect(db_path)
    _insert_running_job(conn, "live_old", worker_pid=os.getpid(), hours_ago=3)
    assert jobs_db.reap_stale_running_jobs(conn) == 0
    assert jobs_db.get_job(conn, "live_old")["status"] == "running"
    conn.close()


def test_job_of_a_dead_worker_is_reaped_without_waiting_an_hour(db_path):
    conn = trackdb.connect(db_path)
    _insert_running_job(conn, "dead_recent", worker_pid=_dead_pid(), hours_ago=0.01)
    assert jobs_db.reap_stale_running_jobs(conn) == 1
    job = jobs_db.get_job(conn, "dead_recent")
    assert job["status"] == "error"
    assert job["error"] == "worker interrupted (process died)"
    conn.close()


def test_job_without_worker_pid_keeps_the_age_gate(db_path):
    conn = trackdb.connect(db_path)
    _insert_running_job(conn, "legacy_recent", worker_pid=None, hours_ago=0.01)
    _insert_running_job(conn, "legacy_old", worker_pid=None, hours_ago=2)
    assert jobs_db.reap_stale_running_jobs(conn) == 1
    assert jobs_db.get_job(conn, "legacy_recent")["status"] == "running"
    assert jobs_db.get_job(conn, "legacy_old")["status"] == "error"
    conn.close()


def test_runs_of_a_still_running_job_are_not_orphaned(db_path):
    import os

    conn = trackdb.connect(db_path)
    _insert_running_job(conn, "live_job", worker_pid=os.getpid(), hours_ago=3)
    _insert_running_run(conn, "run_of_live_job", job_id="live_job", hours_ago=3)
    _insert_running_job(conn, "dead_job", worker_pid=_dead_pid(), hours_ago=3)
    _insert_running_run(conn, "run_of_dead_job", job_id="dead_job", hours_ago=3)
    conn.close()

    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)

    conn = trackdb.connect(db_path)
    status = dict(conn.execute("SELECT run_id, status FROM run").fetchall())
    conn.close()
    assert status["run_of_live_job"] == "running"
    assert status["run_of_dead_job"] == "failed"


def test_connections_wait_30s_on_a_locked_database(db_path):
    conn = trackdb.connect(db_path)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    finally:
        conn.close()


def test_a_failed_progress_write_does_not_kill_the_worker(db_path, monkeypatch):
    """2026-09-27 : un « database is locked » sur l'écriture de progression
    (simple affichage) a tué deux workers en plein run. Le job doit aller au
    bout de son propre sort (ici : erreur du pipeline), le worker survivre."""
    real_update = jobs_db.update_job_progress
    calls = {"n": 0}

    def flaky_update(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:  # la mise à jour initiale passe, les suivantes échouent
            raise sqlite3.OperationalError("database is locked")
        return real_update(*args, **kwargs)

    def noisy_pipeline(config, **kwargs):
        print("ligne 1")
        print("ligne 2")
        raise ValueError("vraie erreur du pipeline")

    monkeypatch.setattr(worker_module.jobs_db, "update_job_progress", flaky_update)
    monkeypatch.setattr(worker_module, "run_pipeline", noisy_pipeline)
    config = RunConfig.model_validate({
        "name": "lock_test",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"]},
    })
    conn = trackdb.connect(db_path)
    job_id = jobs_db.enqueue_job(conn, config.model_dump_json())
    conn.close()

    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)  # ne lève pas

    conn = trackdb.connect(db_path)
    job = jobs_db.get_job(conn, job_id)
    conn.close()
    assert calls["n"] > 1
    assert job["status"] == "error"
    assert job["error"] == "ValueError: vraie erreur du pipeline"


def test_heartbeat_stays_fresh_during_a_silent_phase(db_path, monkeypatch):
    """Le pipeline n'affiche rien pendant 2,5 s ; avec un seuil de 1 s, le
    worker n'est vu vivant que si un fil dédié entretient le battement."""
    monkeypatch.setattr(worker_module, "_HEARTBEAT_INTERVAL_S", 0.2)
    monkeypatch.setattr(jobs_db, "HEARTBEAT_STALE_S", 1.0)
    seen_alive = []

    def silent_pipeline(config, **kwargs):
        time.sleep(2.5)
        conn = trackdb.connect(db_path)
        try:
            seen_alive.append(jobs_db.worker_is_alive(conn))
        finally:
            conn.close()
        raise ValueError("fin du test")

    monkeypatch.setattr(worker_module, "run_pipeline", silent_pipeline)
    config = RunConfig.model_validate({
        "name": "hb_test",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"]},
    })
    conn = trackdb.connect(db_path)
    jobs_db.enqueue_job(conn, config.model_dump_json())
    conn.close()

    worker_module.run_worker_loop(poll_interval=0.01, idle_timeout=0.01)

    assert seen_alive == [True]
