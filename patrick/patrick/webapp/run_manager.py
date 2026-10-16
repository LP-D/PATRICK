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
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db
from patrick.webapp import forms

_IDLE_TIMEOUT_ENV = "PATRICK_WORKER_IDLE_TIMEOUT"
_DEFAULT_IDLE_TIMEOUT_S = 600.0


def _connect():
    return trackdb.connect(trackdb.default_db_path())



def next_run_name(target_symbol: str) -> str:
    """Generated run name = slug(target) + sequence number, which only ever goes UP.

    The number is 1 + the largest of: the runs already recorded for this target (`run` table) and the highest `slug_N` ever carried by
    a run OR a job (every status) of this target. The `job` table is what makes it monotonic: a challenger that loses its champion duel
    is pruned (`tracking/champions.py::prune_run`), and a run deleted from the history disappears too, but their job stays. Counting
    `run` rows alone made the number fall back and be handed out again (IRX_2 and MUB_2 each named four different jobs, all writing
    to the same `output.dir` and Optuna `study_name` -- silent artifact overwrite and involuntary resumption of a study, see
    pipeline/engine.py `load_if_exists=True`). A name held by a job still queued or running is covered by the same rule."""
    slug = forms.slug_target(target_symbol)
    numbered = re.compile(rf"^{re.escape(slug)}_(\d+)$")
    used: set[str] = set()
    highest = 0

    def note(config_json: str | None) -> None:
        nonlocal highest
        try:
            cfg = json.loads(config_json or "{}")
        except (TypeError, ValueError):
            return
        if not isinstance(cfg, dict):
            return
        name = cfg.get("name")
        if isinstance(name, str):
            used.add(name)
            match = numbered.match(name)
            if match:
                highest = max(highest, int(match.group(1)))

    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM run WHERE target = ?", (target_symbol,)).fetchone()[0]
        # Préfiltre SQL : seuls les jobs dont un nom commence par « slug_ » (tolère les espaces du JSON) ; le contrôle exact est refait en Python.
        like = "%\"name\":%\"" + slug.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "\\_%"
        for (config_json,) in conn.execute("SELECT config_json FROM job WHERE config_json LIKE ? ESCAPE '\\'", (like,)).fetchall():
            try:
                same_target = (json.loads(config_json).get("objective") or {}).get("target_symbol") == target_symbol
            except (TypeError, ValueError, AttributeError):
                continue
            if same_target:
                note(config_json)
        for (config_json,) in conn.execute("SELECT config_json FROM run WHERE target = ?", (target_symbol,)).fetchall():
            note(config_json)
    finally:
        conn.close()
    n = max(count, highest) + 1
    name = f"{slug}_{n}"
    while name in used:
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


def _estimated_remaining_s(elapsed_s: float, progress_done: int, progress_total: int) -> int | None:
    """Estimate remaining time from scan progress once a useful sample exists."""
    if elapsed_s <= 0 or progress_total <= 0 or progress_done <= 0 or progress_done >= progress_total:
        return None
    min_sample = max(2, (progress_total + 9) // 10)
    if progress_done < min_sample:
        return None
    return max(0, round(elapsed_s / progress_done * (progress_total - progress_done)))


def _eta_confidence(progress_done: int, progress_total: int) -> str | None:
    """Describe sample size, not statistical certainty, for the rough ETA."""
    if progress_total <= 0 or progress_done <= 0 or progress_done >= progress_total:
        return None
    if progress_done < max(5, (progress_total + 3) // 4):
        return "low"
    return "moderate"


def _job_identity(config_json: str | None) -> tuple[str | None, str | None, str]:
    """(nom, cible, famille) d'un job d'après sa configuration brute -- sans validation Pydantic : la file entière est relue toutes
    les quelques secondes par la carte « en cours et file d'attente ». Famille : « rl » (`"kind": "rl"`), « dl » (tous les algorithmes
    sont des réseaux, comme `RunConfig.family`) ou « ml »."""
    try:
        cfg = json.loads(config_json)
    except (TypeError, ValueError):
        return None, None, "ml"
    if not isinstance(cfg, dict):
        return None, None, "ml"
    objective = cfg.get("objective")
    target = objective.get("target_symbol") if isinstance(objective, dict) else None
    if cfg.get("kind") == "rl":
        kind = "rl"
    else:
        models = cfg.get("models")
        algos = models.get("algos") if isinstance(models, dict) else None
        kind = "dl" if algos and all(a in D.ALL_DL_ALGOS for a in algos) else "ml"
    return cfg.get("name"), target, kind


def _job_view(job: dict, queue_position: int | None) -> dict:
    name, target, kind = _job_identity(job["config_json"])
    paused = job["status"] == "running" and bool(job.get("pause_requested"))
    progress_total = max(0, int(job["progress_total"] or 0))
    progress_done = max(0, int(job["progress_done"] or 0))
    if progress_total:
        progress_done = min(progress_done, progress_total)
    elapsed_s = _elapsed_s(job)
    return {
        "id": job["job_id"],
        "name": name,
        "target": target,
        "kind": kind,                                     # ml | dl | rl
        "status": "paused" if paused else job["status"],  # queued | running | paused | done | error
        "paused": paused,
        "phase": job["phase"],
        "progress": {"done": progress_done, "total": progress_total},
        "log_tail": job["log_tail"],
        "error": job["error"],
        "elapsed_s": elapsed_s,
        "estimated_remaining_s": _estimated_remaining_s(elapsed_s, progress_done, progress_total),
        "eta_confidence": _eta_confidence(progress_done, progress_total),
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


def get_job_config_dict(run_id: str) -> dict | None:
    """Configuration brute d'un job (ML, DL ou RL : `kind`, `models.deep`...), `None` si le job n'existe pas."""
    conn = _connect()
    try:
        job = jobs_db.get_job(conn, run_id)
    finally:
        conn.close()
    if job is None:
        return None
    try:
        return json.loads(job["config_json"])
    except (TypeError, ValueError):
        return None


def get_run_kind(run_id: str) -> str | None:
    """« rl » pour un job de reinforcement learning, « ml » sinon (arbres ou réseaux), `None` si le job n'existe pas."""
    raw = get_job_config_dict(run_id)
    return None if raw is None else ("rl" if raw.get("kind") == "rl" else "ml")


def get_run_config(run_id: str) -> RunConfig | None:
    """Configuration d'un job de classification (ML ou DL). Un job RL n'a pas de `RunConfig` : `None` (voir `get_job_config_dict`)."""
    if get_run_kind(run_id) in (None, "rl"):
        return None
    conn = _connect()
    try:
        job = jobs_db.get_job(conn, run_id)
        return RunConfig.model_validate_json(job["config_json"]) if job else None
    finally:
        conn.close()


def next_rl_run_name(target_symbol: str) -> str:
    """Nom d'un run RL : `<cible>_rl_<n>`, n = premier numéro libre parmi les jobs RL déjà créés (quel que soit leur état)."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT config_json FROM job WHERE config_json LIKE ?", ('%"kind":"rl"%',)).fetchall()
    finally:
        conn.close()
    taken = set()
    for (config_json,) in rows:
        try:
            taken.add(json.loads(config_json).get("name"))
        except (TypeError, ValueError):
            continue
    slug = forms.slug_target(target_symbol)
    n = 1
    while f"{slug}_rl_{n}" in taken:
        n += 1
    return f"{slug}_rl_{n}"


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


def set_active_run_paused(job_id: str, paused: bool) -> dict | None:
    conn = _connect()
    try:
        if not jobs_db.set_job_paused(conn, job_id, paused):
            return None
        job = jobs_db.get_job(conn, job_id)
        return _job_view(job, None) if job else None
    finally:
        conn.close()


def remove_queued_run(job_id: str) -> bool:
    conn = _connect()
    try:
        return jobs_db.delete_queued_job(conn, job_id)
    finally:
        conn.close()


def reorder_queued_runs(order: list[str]) -> list[dict]:
    conn = _connect()
    try:
        jobs_db.reorder_queued_jobs(conn, order)
    finally:
        conn.close()
    return queued_runs()


def clear_queued_runs() -> int:
    conn = _connect()
    try:
        return jobs_db.clear_queued_jobs(conn)
    finally:
        conn.close()


def _terminate_worker(pid: int) -> None:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True, timeout=15, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Expiration du délai d'arrêt du worker {pid}.") from exc
        if result.returncode and jobs_db.pid_alive(pid):
            detail = result.stderr.strip() or result.stdout.strip() or "taskkill failed"
            raise RuntimeError(f"Impossible d'arrêter le worker {pid} : {detail}")
    elif jobs_db.pid_alive(pid):
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return

    deadline = time.monotonic() + 10
    while jobs_db.pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    if jobs_db.pid_alive(pid):
        raise RuntimeError(f"Le worker {pid} ne s'est pas arrêté après le signal.")


def stop_active_run(job_id: str) -> bool:
    conn = _connect()
    try:
        job = jobs_db.get_job(conn, job_id)
        if job is None or job["status"] != "running":
            return False
        pid = job.get("worker_pid")
        if not pid or pid <= 0:
            raise RuntimeError("Le PID du worker actif est indisponible.")
        _terminate_worker(pid)
        jobs_db.clear_heartbeat(conn, pid)       # le worker est mort : son pouls ne doit plus empêcher d'en relancer un
        stopped = jobs_db.finish_user_stopped_job(conn, job_id)
    finally:
        conn.close()
    if queued_runs():
        ensure_worker_running()
    return stopped


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
