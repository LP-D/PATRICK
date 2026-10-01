"""Job queue (Phase 3.1) — persisted in the `job` table (see migration
`0002_jobs.sql`), consumed by a worker in a separate process
(`patrick/worker.py`) that polls this table in a loop, rather than a thread
internal to the web process (BackgroundTasks-like, the old `run_manager.py`):
killing the web process during a run no longer loses the run.
"""
from __future__ import annotations

import ctypes
import json
import os
import sqlite3
import uuid

# A heartbeat older than this -> worker considered dead (`ensure_worker_running`
# relaunches one). The worker refreshes its heartbeat from a dedicated thread
# every few seconds (`worker._HEARTBEAT_INTERVAL_S`), whatever the pipeline
# prints -- it used to depend on printed lines, and a silent phase of more
# than 30s made a live worker look dead (2026-09-27, GSPC_62). Importing its
# ML dependencies (xgboost/shap/arch/...) before the thread starts already
# takes ~5s cold -> generous margin to avoid confusing "worker starting up"
# with "worker dead" (which would spawn a duplicate second worker, see
# `ensure_worker_running`).
HEARTBEAT_STALE_S = 30.0

_JOB_COLUMNS = [
    "job_id", "config_json", "status", "created_at", "started_at", "finished_at",
    "error", "result_json", "phase", "progress_done", "progress_total", "log_tail",
    "worker_pid", "pause_requested",
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


def set_job_paused(conn: sqlite3.Connection, job_id: str, paused: bool) -> bool:
    with conn:
        cur = conn.execute(
            "UPDATE job SET pause_requested = ? WHERE job_id = ? AND status = 'running'",
            (int(paused), job_id),
        )
    return cur.rowcount == 1


def delete_queued_job(conn: sqlite3.Connection, job_id: str) -> bool:
    with conn:
        cur = conn.execute(
            "DELETE FROM job WHERE job_id = ? AND status = 'queued'", (job_id,)
        )
    return cur.rowcount == 1


def clear_queued_jobs(conn: sqlite3.Connection) -> int:
    with conn:
        cur = conn.execute("DELETE FROM job WHERE status = 'queued'")
    return cur.rowcount


def pause_requested(conn: sqlite3.Connection, job_id: str) -> bool:
    row = conn.execute(
        "SELECT pause_requested FROM job WHERE job_id = ? AND status = 'running'",
        (job_id,),
    ).fetchone()
    return bool(row and row[0])


def finish_user_stopped_job(conn: sqlite3.Connection, job_id: str) -> bool:
    error = "Stopped by user."
    with conn:
        cur = conn.execute(
            "UPDATE job SET status = 'error', finished_at = datetime('now'), error = ? "
            "WHERE job_id = ? AND status = 'running'",
            (error, job_id),
        )
        if cur.rowcount:
            conn.execute(
                "UPDATE run SET status = 'failed', finished_at = datetime('now'), error = ? "
                "WHERE job_id = ? AND status = 'running'",
                (error, job_id),
            )
    return cur.rowcount == 1


def pid_alive(pid: int | None) -> bool:
    """True if a process with this pid currently exists. Never signals the
    process: on Windows `os.kill(pid, 0)` would TERMINATE it, hence the
    OpenProcess/GetExitCodeProcess query."""
    if not pid or pid <= 0:
        return False
    if os.name == "nt":
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: exists, not ours
        try:
            code = wintypes.DWORD()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap_stale_running_jobs(conn: sqlite3.Connection, max_age_s: float = 3600.0) -> int:
    """Jobs left 'running' whose worker process no longer exists (kill -9,
    crash, power loss) are switched to error rather than left blocking the
    queue indefinitely -- as soon as the worker is gone, however recent the
    job. A job whose worker is still alive is never touched, however old: a
    reference run lasts hours, and the former "older than `max_age_s`" rule
    alone marked a live job as dead (2026-09-27, GSPC_62). `max_age_s` only
    still applies to legacy rows without a recorded `worker_pid`.
    Called at `run_worker_loop` startup, never during an ongoing execution."""
    rows = conn.execute(
        "SELECT job_id, worker_pid, (julianday('now') - julianday(started_at)) * 86400 "
        "FROM job WHERE status = 'running'"
    ).fetchall()
    dead = [
        job_id for job_id, worker_pid, age_s in rows
        if (not pid_alive(worker_pid) if worker_pid else (age_s or 0) > max_age_s)
    ]
    with conn:
        for job_id in dead:
            conn.execute(
                "UPDATE job SET status = 'error', finished_at = datetime('now'), "
                "error = 'worker interrupted (process died)' "
                "WHERE job_id = ? AND status = 'running'",
                (job_id,),
            )
    return len(dead)


def write_heartbeat(conn: sqlite3.Connection, pid: int) -> None:
    """Millisecond timestamp: `datetime('now')` truncates to the second while
    `worker_is_alive` reads `julianday('now')` with milliseconds, so the age
    it saw could exceed the real one by up to 1 s (a write at hh:mm:ss.95
    read 0.2 s later looked 1.15 s old) -- the source of the intermittent
    `test_heartbeat_stays_fresh_during_a_silent_phase` failure (1 s threshold)."""
    with conn:
        conn.execute(
            "INSERT INTO worker_heartbeat (id, pid, updated_at) "
            "VALUES (1, ?, strftime('%Y-%m-%d %H:%M:%f', 'now')) "
            "ON CONFLICT(id) DO UPDATE SET pid = excluded.pid, updated_at = excluded.updated_at",
            (pid,),
        )


def worker_is_alive(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT (julianday('now') - julianday(updated_at)) * 86400 "
        "FROM worker_heartbeat WHERE id = 1"
    ).fetchone()
    return row is not None and row[0] is not None and row[0] < HEARTBEAT_STALE_S
