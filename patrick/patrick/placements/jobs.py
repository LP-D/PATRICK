"""Analyses de placements lancées en tâche de fond (un fil de calcul par analyse), avec avancement lisible par la page.

Une analyse dure de quelques secondes à une minute : assez pour ne pas bloquer la requête qui la lance, trop peu pour justifier la file de jobs
des entraînements (qui survit au serveur). L'état vit donc en mémoire ; le RÉSULTAT, lui, est écrit sur disque (`store.save_result`) et se relit
après un redémarrage. Une seule analyse à la fois par jeu de données : relancer pendant qu'elle tourne renvoie la même tâche.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import asdict, dataclass

from patrick.placements import service, store

log = logging.getLogger(__name__)
KEEP = 20


@dataclass
class Job:
    id: str
    dataset_id: str
    status: str = "running"          # running | done | error
    fraction: float = 0.0
    message: str = ""
    error: str | None = None
    started: float = 0.0
    finished: float | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _run(job: Job, params: service.Params) -> None:
    def progress(fraction: float, message: str) -> None:
        job.fraction, job.message = float(fraction), message

    try:
        navs, meta = store.load_navs(job.dataset_id)
        labels = {k: f["label"] for k, f in meta["funds"].items()}
        params.amount = meta["amount"]
        params.rf_annual = meta.get("rf_annual", store.DEFAULT_RF)
        result = service.analyse(navs, labels, meta.get("cash"), params, progress)
        result["dataset"] = {"id": meta["id"], "name": meta["name"]}
        store.save_result(job.dataset_id, result)
        job.status, job.fraction, job.message = "done", 1.0, ""
    except (service.AnalysisError, store.StoreError) as exc:
        job.status, job.error = "error", str(exc)
    except Exception as exc:
        log.exception("analyse de placements en échec")
        job.status, job.error = "error", f"Erreur de calcul : {type(exc).__name__}: {exc}"
    finally:
        job.finished = time.time()


def start(dataset_id: str, params: service.Params) -> Job:
    """Lance l'analyse (ou renvoie celle qui tourne déjà pour ce jeu de données)."""
    with _lock:
        for job in _jobs.values():
            if job.dataset_id == dataset_id and job.status == "running":
                return job
        job = Job(id=secrets.token_hex(6), dataset_id=dataset_id, started=time.time())
        _jobs[job.id] = job
        for old in sorted((j for j in _jobs.values() if j.status != "running"), key=lambda j: j.started)[:-KEEP]:
            _jobs.pop(old.id, None)
    threading.Thread(target=_run, args=(job, params), name=f"placements-{job.id}", daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def snapshot(job: Job) -> dict:
    d = asdict(job)
    d["elapsed"] = round((job.finished or time.time()) - job.started, 1)
    return d
