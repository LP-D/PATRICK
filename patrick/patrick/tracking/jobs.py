"""File d'attente de jobs (Phase 3.1) — persistée dans la table `job` (cf.
migration `0002_jobs.sql`), consommée par un worker en process séparé
(`patrick/worker.py`) qui interroge cette table en boucle, plutôt qu'un thread
interne au process web (BackgroundTasks-like, ancien `run_manager.py`) : tuer
le process web pendant un run ne perd plus le run.
"""
from __future__ import annotations

import json
import sqlite3
import uuid

# Un heartbeat plus vieux que ça -> worker considéré mort (`ensure_worker_running`
# en relance un). Le worker rafraîchit son heartbeat à chaque itération de la
# boucle ET pendant l'exécution d'un run (throttlé à ~1/s, cf. worker.py), mais
# l'import de ses dépendances ML (xgboost/shap/arch/...) avant même d'entrer
# dans sa boucle prend déjà ~5s à froid -> marge large pour ne pas confondre
# "worker en train de démarrer" et "worker mort" (ce qui ferait spawner un
# second worker en double, cf. `ensure_worker_running`).
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
    """Réclame le plus ancien job en attente de façon atomique : `BEGIN
    IMMEDIATE` prend le verrou d'écriture avant même de lire, donc deux
    workers qui appellent ceci en même temps ne peuvent jamais réclamer le
    même job (le second bloque jusqu'à ce que le premier commit/rollback, puis
    ne trouve plus de job 'queued' à cette place)."""
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
    """Jobs restés 'running' au-delà de `max_age_s` -> leur worker est mort sans
    avoir pu marquer l'échec (kill -9, crash, coupure de courant) : on les
    repasse en erreur plutôt que de les laisser bloquer la file indéfiniment.
    Appelé au démarrage de `run_worker_loop`, jamais pendant une exécution en
    cours (un run légitimement long ne doit pas être fauché par son propre
    worker)."""
    with conn:
        cur = conn.execute(
            "UPDATE job SET status = 'error', finished_at = datetime('now'), "
            "error = 'worker interrompu (process mort)' "
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
