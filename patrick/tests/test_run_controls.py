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


def test_run_eta_requires_measurable_progress_and_caps_completed_work():
    assert run_manager._estimated_remaining_s(100, 0, 10) is None
    assert run_manager._estimated_remaining_s(100, 1, 10) is None
    assert run_manager._estimated_remaining_s(100, 2, 10) == 400
    assert run_manager._estimated_remaining_s(0, 2, 10) is None
    assert run_manager._estimated_remaining_s(100, 10, 10) is None
    assert run_manager._estimated_remaining_s(100, 12, 10) is None
    assert run_manager._estimated_remaining_s(100, 2, 0) is None
    assert run_manager._eta_confidence(2, 10) == "low"
    assert run_manager._eta_confidence(5, 10) == "moderate"
    assert run_manager._eta_confidence(10, 10) is None


def test_job_view_exposes_eta_and_caps_progress(monkeypatch):
    monkeypatch.setattr(run_manager, "_elapsed_s", lambda _: 100.0)
    job = {
        "job_id": "active",
        "config_json": '{"name":"test"}',
        "status": "running",
        "pause_requested": 0,
        "phase": "scan",
        "progress_done": 3,
        "progress_total": 10,
        "log_tail": [],
        "error": None,
    }

    view = run_manager._job_view(job, None)
    assert view["progress"] == {"done": 3, "total": 10}
    assert view["estimated_remaining_s"] == 233
    assert view["eta_confidence"] == "low"

    job["progress_done"] = 20
    view = run_manager._job_view(job, None)
    assert view["progress"] == {"done": 10, "total": 10}
    assert view["estimated_remaining_s"] is None
    assert view["eta_confidence"] is None


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


def _queue_ids(client) -> list[str]:
    return [q["id"] for q in client.get("/api/run-state").json()["queue"]]


def test_launch_dashboard_queue_is_a_collapsible_list_without_confirm_dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    html = TestClient(app).get("/launch").text
    assert 'id="queue-toggle"' in html
    assert 'aria-controls="queue-list"' in html
    # Le nombre et le prochain run sont résumés ; les noms ne sont pas répétés.
    assert 'id="queue-summary"' in html
    # Plus de fenêtre `confirm()` du navigateur sur « Vider la file ».
    clear_button = html[html.index('id="clear-queue-btn"'):].split(">", 1)[0]
    assert "data-confirm" not in clear_button
    stop_button = html[html.index('id="stop-run-btn"'):].split(">", 1)[0]
    assert "data-confirm" not in stop_button


def test_reorder_queue_changes_worker_claim_order(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect()
    ids = [jobs.enqueue_job(conn, json.dumps({"name": n})) for n in ("a", "b", "c", "d")]
    _running_job(conn, "active")
    client = TestClient(app)
    assert _queue_ids(client) == ids

    a, b, c, d = ids
    response = client.post("/api/queue/reorder", json={"order": [c, a, d, b]})
    assert response.status_code == 200
    assert [q["id"] for q in response.json()["queue"]] == [c, a, d, b]
    assert [q["queue_position"] for q in response.json()["queue"]] == [1, 2, 3, 4]
    assert _queue_ids(client) == [c, a, d, b]

    # Le worker réclame dans le nouvel ordre ; le run actif n'est pas touché.
    assert jobs.claim_next_job(conn, 999)["job_id"] == c
    assert jobs.claim_next_job(conn, 999)["job_id"] == a
    assert client.get("/api/run-state").json()["active_run"]["id"] == "active"
    conn.close()


def test_reorder_queue_keeps_new_jobs_last_and_survives_repeated_moves(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect()
    a, b, c = [jobs.enqueue_job(conn, json.dumps({"name": n})) for n in "abc"]
    client = TestClient(app)
    for order in ([c, b, a], [b, a, c], [a, c, b]):
        client.post("/api/queue/reorder", json={"order": order})
        assert _queue_ids(client) == order
    # Un run lancé ensuite passe après toute la file réordonnée.
    late = jobs.enqueue_job(conn, json.dumps({"name": "late"}))
    assert _queue_ids(client) == [a, c, b, late]
    conn.close()


def test_reorder_queue_ignores_stale_ids_and_appends_unlisted_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect()
    a, b, c = [jobs.enqueue_job(conn, json.dumps({"name": n})) for n in "abc"]
    conn.close()
    client = TestClient(app)
    # `ghost` n'est plus en file, `a` est oublié (lancé entre-temps côté client).
    client.post("/api/queue/reorder", json={"order": [c, "ghost", b, b]})
    assert _queue_ids(client) == [c, b, a]


def test_reorder_queue_rejects_malformed_body(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    client = TestClient(app)
    assert client.post("/api/queue/reorder", json={"order": "x"}).status_code == 400
    assert client.post("/api/queue/reorder", json={"order": [1, 2]}).status_code == 400
    assert client.post("/api/queue/reorder", json={}).status_code == 400
    assert client.post("/api/queue/reorder", content=b"nope").status_code == 400
    assert client.post("/api/queue/reorder", json={"order": []}).json() == {"queue": []}


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
