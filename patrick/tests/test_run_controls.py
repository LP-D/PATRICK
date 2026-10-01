from __future__ import annotations

import io
import json
import threading
import time

from fastapi.testclient import TestClient

from patrick import worker
from patrick.tracking import db, jobs
from patrick.webapp import run_manager
from patrick.webapp.app import app


def _running_job(conn, job_id: str, worker_pid: int = 12345) -> None:
    with conn:
        conn.execute(
            "INSERT INTO job (job_id, config_json, status, worker_pid) "
            "VALUES (?, ?, 'running', ?)",
            (job_id, json.dumps({"name": job_id}), worker_pid),
        )


def test_pause_and_resume_active_job(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect()
    _running_job(conn, "active")
    conn.close()

    client = TestClient(app)
    paused = client.post("/api/jobs/active/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert client.get("/api/run-state").json()["active_run"]["status"] == "paused"

    resumed = client.post("/api/jobs/active/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"


def test_launch_dashboard_renders_queue_and_active_run_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    response = TestClient(app).get("/launch")
    assert response.status_code == 200
    assert 'id="queue-list"' in response.text
    assert 'id="clear-queue-btn"' in response.text
    assert 'id="pause-run-btn"' in response.text
    assert 'id="stop-run-btn"' in response.text


def test_queue_controls_remove_only_queued_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect()
    first = jobs.enqueue_job(conn, '{"name":"first"}')
    second = jobs.enqueue_job(conn, '{"name":"second"}')
    _running_job(conn, "active")
    conn.close()

    client = TestClient(app)
    assert client.delete(f"/api/queue/{first}").json() == {"removed": 1}
    assert client.delete("/api/queue").json() == {"removed": 1}
    assert client.delete(f"/api/queue/{second}").status_code == 409
    assert client.get("/api/run-state").json()["active_run"]["id"] == "active"


def test_stop_terminates_active_worker_and_marks_job_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect()
    _running_job(conn, "active", worker_pid=4321)
    conn.close()
    terminated = []
    monkeypatch.setattr(run_manager, "_terminate_worker", terminated.append)
    monkeypatch.setattr(run_manager, "ensure_worker_running", lambda: None)

    response = TestClient(app).post("/api/jobs/active/stop")
    assert response.status_code == 200, response.text
    assert terminated == [4321]

    conn = db.connect()
    job = jobs.get_job(conn, "active")
    conn.close()
    assert job["status"] == "error"
    assert job["error"] == "Stopped by user."


def test_pause_is_observed_at_next_worker_log_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect()
    _running_job(conn, "active")
    jobs.set_job_paused(conn, "active", True)
    monkeypatch.setattr(worker.sys, "stdout", io.StringIO())
    wrote_line = threading.Event()

    def write_checkpoint():
        worker_conn = db.connect()
        try:
            capture = worker._ProgressCapture(worker_conn, "active", 12345)
            capture.write("checkpoint\n")
            wrote_line.set()
        finally:
            worker_conn.close()

    thread = threading.Thread(target=write_checkpoint)
    thread.start()
    time.sleep(0.1)
    assert not wrote_line.is_set()

    jobs.set_job_paused(conn, "active", False)
    thread.join(timeout=2)
    conn.close()
    assert wrote_line.is_set()
    assert not thread.is_alive()


def test_finished_jobs_clear_and_reset_pause_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect()
    _running_job(conn, "active")
    jobs.set_job_paused(conn, "active", True)
    jobs.finish_job(conn, "active", "done", result_json='{}')
    job = jobs.get_job(conn, "active")
    assert job["status"] == "done"
    assert job["pause_requested"] == 0

    _running_job(conn, "stopped")
    jobs.set_job_paused(conn, "stopped", True)
    assert jobs.finish_user_stopped_job(conn, "stopped") is True
    stopped = jobs.get_job(conn, "stopped")
    assert stopped["status"] == "error"
    assert stopped["pause_requested"] == 0
    conn.close()
