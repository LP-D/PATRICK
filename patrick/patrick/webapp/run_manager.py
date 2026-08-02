"""Client léger de la file de jobs (Phase 3.1) côté process web.

L'exécution réelle du pipeline a lieu dans un process worker séparé
(`patrick worker`, cf. `patrick/worker.py`) ; ce module ne fait plus que lire
et écrire la table `job` (cf. `tracking/jobs.py`) et s'assurer qu'un worker
tourne. Remplace l'ancien `RunState`/thread interne au process web
(BackgroundTasks-like) : tuer le process web pendant un run ne perd plus le
run, un redémarrage retrouve l'état en relisant `job` plutôt qu'un état perdu
en mémoire.
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
    """Nom de run généré = slug(cible) + numéro de séquence (1 + nombre de
    runs déjà enregistrés pour cette cible, tout statut confondu). Seule
    règle de nommage du produit (cf. spec batch-run-launch §2) -- jamais de
    saisie libre, ni en soumission simple, ni en batch, ni en relance."""
    conn = _connect()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM run WHERE target = ?", (target_symbol,)
        ).fetchone()[0]
    finally:
        conn.close()
    return f"{forms.slug_target(target_symbol)}_{count + 1}"

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
    """Enfile la config comme nouveau job et s'assure qu'un worker existe pour
    la consommer. Ne lance plus rien "tout de suite" en mémoire : la
    transition queued -> running est décidée par le worker (process séparé),
    donc immédiatement après cet appel le job est toujours 'queued' même s'il
    n'y a aucun autre run actif (le worker le réclame en général en moins
    d'une seconde, cf. `poll_interval`)."""
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
    """Relance `patrick worker` en process séparé et détaché si aucun worker
    vivant n'est détecté (heartbeat absent ou périmé). Un léger recouvrement
    entre deux appels concurrents est possible (pas de verrou distribué) mais
    sans conséquence : `claim_next_job` est atomique, deux workers ne peuvent
    jamais exécuter le même job — au pire l'un des deux s'arrête vite, faute
    de jobs à réclamer."""
    conn = _connect()
    try:
        if jobs_db.worker_is_alive(conn):
            return
        # Réserve immédiatement le rôle de worker actif (heartbeat placeholder,
        # pid=0) avant même de spawner le process séparé : celui-ci met
        # plusieurs secondes à importer ses dépendances ML avant d'écrire son
        # propre heartbeat (cf. commentaire sur HEARTBEAT_STALE_S) — sans ce
        # jalon, une deuxième soumission arrivant dans cette fenêtre verrait
        # encore "aucun worker vivant" et en relancerait un second en double.
        jobs_db.write_heartbeat(conn, pid=0)
    finally:
        conn.close()
    idle_timeout = float(os.environ.get(_IDLE_TIMEOUT_ENV, _DEFAULT_IDLE_TIMEOUT_S))
    _spawn_worker(idle_timeout)


def _spawn_worker(idle_timeout: float) -> None:
    cmd = [sys.executable, "-m", "patrick.cli", "worker", "--idle-timeout", str(idle_timeout)]
    kwargs: dict = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True  # survit à la mort du process web (nouveau groupe de process)
    else:
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        )
    subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **kwargs,
    )
