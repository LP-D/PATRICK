"""Lightweight job-queue client (Phase 3.1) on the web process side.

The pipeline's actual execution happens in a separate worker process
(`patrick worker`, see `patrick/worker.py`); this module now only reads and
writes the `job` table (see `tracking/jobs.py`) and ensures a worker is
running. Replaces the old web-process-internal `RunState`/thread
(BackgroundTasks-like): killing the web process during a run no longer
loses the run, a restart recovers the state by re-reading `job` rather than
a state lost in memory.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

from patrick.config.schema import RunConfig
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db
from patrick.webapp import forms

_IDLE_TIMEOUT_ENV = "PATRICK_WORKER_IDLE_TIMEOUT"
_DEFAULT_IDLE_TIMEOUT_S = 600.0


def _connect():
    return trackdb.connect(trackdb.default_db_path())



def next_run_name(target_symbol: str) -> str:
    """Generated run name = slug(target) + sequence number. The base counter
    comes from the `run` table (1 + number of runs already recorded for this
    target), but a job that is merely queued (`queued`) or running
    (`running`) has no `run` row yet -- invisible to this count until the
    pipeline has actually started. Without the check below, two jobs for the
    same target submitted before the first one starts would receive the
    same name, hence the same `output.dir`/Optuna `study_name`: silent
    artifact overwrite and involuntary resumption of an Optuna study (see
    pipeline/engine.py:1038, 1075 -- load_if_exists=True on a study_name
    derived from the name). So this also steps back from any name already
    held by a job still queued or running for this same target."""
    conn = _connect()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM run WHERE target = ?", (target_symbol,)
        ).fetchone()[0]
        claimed_names = set()
        for (config_json,) in conn.execute(
            "SELECT config_json FROM job WHERE status IN ('queued', 'running')"
        ).fetchall():
            cfg = json.loads(config_json)
            if cfg.get("objective", {}).get("target_symbol") == target_symbol:
                claimed_names.add(cfg.get("name"))
    finally:
        conn.close()
    slug = forms.slug_target(target_symbol)
    n = count + 1
    name = f"{slug}_{n}"
    while name in claimed_names:
        n += 1
        name = f"{slug}_{n}"
    return name

def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def _elapsed_s(job: dict) -> float:
    start = _parse_dt(job["started_at"]) or _parse_dt(job["created_at"])
    if start is None:
        return 0.0
    end = _parse_dt(job["finished_at"]) or datetime.now(timezone.utc)
    return (end - start).total_seconds()


def _job_view(job: dict, queue_position: int | None) -> dict:
    name = None
    try:
        name = json.loads(job["config_json"]).get("name")
    except (TypeError, ValueError, AttributeError):
        pass
    return {
        "id": job["job_id"],
        "name": name,
        "status": job["status"],  # queued | running | done | error
        "phase": job["phase"],
        "progress": {"done": job["progress_done"], "total": job["progress_total"]},
        "log_tail": job["log_tail"],
        "error": job["error"],
        "elapsed_s": _elapsed_s(job),
        "queue_position": queue_position,
    }


def start_run(config: RunConfig) -> dict:
    """Enqueues the config as a new job and ensures a worker exists to
    consume it. No longer launches anything "right away" in memory: the
    queued -> running transition is decided by the worker (separate
    process), so immediately after this call the job is still 'queued' even
    if there is no other active run (the worker generally claims it in
    under a second, see `poll_interval`)."""
    conn = _connect()
    try:
        job_id = jobs_db.enqueue_job(conn, config.model_dump_json())
        queue_ids = jobs_db.list_queued_job_ids(conn)
        queue_position = queue_ids.index(job_id) + 1 if job_id in queue_ids else None
        job = jobs_db.get_job(conn, job_id)
    finally:
        conn.close()
    ensure_worker_running()
    return _job_view(job, queue_position)


def get_run(run_id: str) -> dict | None:
    conn = _connect()
    try:
        job = jobs_db.get_job(conn, run_id)
        if job is None:
            return None
        queue_position = None
        if job["status"] == "queued":
            queue_ids = jobs_db.list_queued_job_ids(conn)
            queue_position = queue_ids.index(run_id) + 1 if run_id in queue_ids else None
        return _job_view(job, queue_position)
    finally:
        conn.close()


def get_run_config(run_id: str) -> RunConfig | None:
    conn = _connect()
    try:
        job = jobs_db.get_job(conn, run_id)
        return RunConfig.model_validate_json(job["config_json"]) if job else None
    finally:
        conn.close()


def get_run_result(run_id: str) -> dict | None:
    conn = _connect()
    try:
        job = jobs_db.get_job(conn, run_id)
        if job is None or job["status"] != "done" or not job["result_json"]:
            return None
        return json.loads(job["result_json"])
    finally:
        conn.close()


def active_run() -> dict | None:
    conn = _connect()
    try:
        job = jobs_db.active_job(conn)
        return _job_view(job, None) if job else None
    finally:
        conn.close()


def queued_runs() -> list[dict]:
    conn = _connect()
    try:
        ids = jobs_db.list_queued_job_ids(conn)
        views = []
        for pos, job_id in enumerate(ids, start=1):
            job = jobs_db.get_job(conn, job_id)
            if job is not None:
                views.append(_job_view(job, pos))
        return views
    finally:
        conn.close()


def ensure_worker_running() -> None:
    """Relaunches `patrick worker` as a separate, detached process if no
    live worker is detected (heartbeat missing or stale). A slight overlap
    between two concurrent calls is possible (no distributed lock) but
    harmless: `claim_next_job` is atomic, two workers can never execute the
    same job — at worst one of the two stops quickly, finding no jobs left
    to claim."""
    conn = _connect()
    try:
        if jobs_db.worker_is_alive(conn):
            return
        # Immediately reserves the active-worker role (heartbeat placeholder,
        # pid=0) even before spawning the separate process: the latter takes
        # several seconds to import its ML dependencies before writing its
        # own heartbeat (see comment on HEARTBEAT_STALE_S) — without this
        # marker, a second submission arriving in this window would still
        # see "no live worker" and would relaunch a duplicate second one.
        jobs_db.write_heartbeat(conn, pid=0)
    finally:
        conn.close()
    idle_timeout = float(os.environ.get(_IDLE_TIMEOUT_ENV, _DEFAULT_IDLE_TIMEOUT_S))
    _spawn_worker(idle_timeout)


def _spawn_worker(idle_timeout: float) -> None:
    cmd = [sys.executable, "-m", "patrick.cli", "worker", "--idle-timeout", str(idle_timeout)]
    kwargs: dict = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True  # survives the web process's death (new process group)
    else:
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        )
    subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **kwargs,
    )
