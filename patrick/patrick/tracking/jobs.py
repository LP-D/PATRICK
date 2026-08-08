"""Job queue (Phase 3.1) — persisted in the `job` table (see migration
`0002_jobs.sql`), consumed by a worker in a separate process
(`patrick/worker.py`) that polls this table in a loop, rather than a thread
internal to the web process (BackgroundTasks-like, the old `run_manager.py`):
killing the web process during a run no longer loses the run.
"""
from __future__ import annotations

import json
import sqlite3
import uuid

# A heartbeat older than this -> worker considered dead (`ensure_worker_running`
# relaunches one). The worker refreshes its heartbeat on every loop iteration
# AND during a run's execution (throttled to ~1/s, see worker.py), but
# importing its ML dependencies (xgboost/shap/arch/...) even before entering
# its loop already takes ~5s cold -> generous margin to avoid confusing
# "worker starting up" with "worker dead" (which would spawn a duplicate
# second worker, see `ensure_worker_running`).
HEARTBEAT_STALE_S = 30.0

_JOB_COLUMNS = [
    "job_id", "config_json", "status", "created_at", "started_at", "finished_at",
    "error", "result_json", "phase", "progress_done", "progress_total", "log_tail",
]


def enqueue_job(conn: sqlite3.Connection, config_json: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with conn:
        conn.execute(
            "INSERT INTO job (job_id, config_json, status) VALUES (?, ?, 'queued')",
            (job_id, config_json),
        )
    return job_id


def claim_next_job(conn: sqlite3.Connection, worker_pid: int) -> dict | None:
    """Claims the oldest queued job atomically: `BEGIN IMMEDIATE` takes the
    write lock even before reading, so two workers calling this at the same
    time can never claim the same job (the second one blocks until the first
    commits/rolls back, then finds no more 'queued' job in that spot)."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT job_id, config_json FROM job WHERE status = 'queued' "
            "ORDER BY created_at LIMIT 1"
        ).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return None
        job_id, config_json = row
        conn.execute(
            "UPDATE job SET status = 'running', started_at = datetime('now'), "
            "worker_pid = ? WHERE job_id = ?",
            (worker_pid, job_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"job_id": job_id, "config_json": config_json}


def update_job_progress(conn: sqlite3.Connection, job_id: str, phase: str | None = None,
                         progress_done: int | None = None, progress_total: int | None = None,
                         log_tail: list[str] | None = None) -> None:
    fields, params = [], []
    if phase is not None:
        fields.append("phase = ?")
        params.append(phase)
    if progress_done is not None:
        fields.append("progress_done = ?")
        params.append(progress_done)
    if progress_total is not None:
        fields.append("progress_total = ?")
        params.append(progress_total)
    if log_tail is not None:
        fields.append("log_tail = ?")
        params.append(json.dumps(log_tail[-200:]))
    if not fields:
        return
    params.append(job_id)
    with conn:
        conn.execute(f"UPDATE job SET {', '.join(fields)} WHERE job_id = ?", params)


def finish_job(conn: sqlite3.Connection, job_id: str, status: str,
                result_json: str | None = None, error: str | None = None) -> None:
    with conn:
        conn.execute(
            "UPDATE job SET status = ?, finished_at = datetime('now'), "
            "result_json = ?, error = ? WHERE job_id = ?",
            (status, result_json, error, job_id),
        )


def _row_to_dict(row) -> dict:
    d = dict(zip(_JOB_COLUMNS, row))
    d["log_tail"] = json.loads(d["log_tail"]) if d["log_tail"] else []
    return d


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT {', '.join(_JOB_COLUMNS)} FROM job WHERE job_id = ?", (job_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_queued_job_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT job_id FROM job WHERE status = 'queued' ORDER BY created_at"
    ).fetchall()
    return [r[0] for r in rows]


def active_job(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        f"SELECT {', '.join(_JOB_COLUMNS)} FROM job WHERE status = 'running' "
        "ORDER BY started_at LIMIT 1"
    ).fetchone()
    return _row_to_dict(row) if row else None


def reap_stale_running_jobs(conn: sqlite3.Connection, max_age_s: float = 3600.0) -> int:
    """Jobs left 'running' beyond `max_age_s` -> their worker died without
    being able to mark the failure (kill -9, crash, power loss): they are
    switched to error rather than left blocking the queue indefinitely.
    Called at `run_worker_loop` startup, never during an ongoing execution (a
    legitimately long run must not be cut down by its own worker)."""
    with conn:
        cur = conn.execute(
            "UPDATE job SET status = 'error', finished_at = datetime('now'), "
            "error = 'worker interrupted (process died)' "
            "WHERE status = 'running' AND "
            "(julianday('now') - julianday(started_at)) * 86400 > ?",
            (max_age_s,),
        )
    return cur.rowcount


def write_heartbeat(conn: sqlite3.Connection, pid: int) -> None:
    with conn:
        conn.execute(
            "INSERT INTO worker_heartbeat (id, pid, updated_at) VALUES (1, ?, datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET pid = excluded.pid, updated_at = excluded.updated_at",
            (pid,),
        )


def worker_is_alive(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT (julianday('now') - julianday(updated_at)) * 86400 "
        "FROM worker_heartbeat WHERE id = 1"
    ).fetchone()
    return row is not None and row[0] is not None and row[0] < HEARTBEAT_STALE_S
