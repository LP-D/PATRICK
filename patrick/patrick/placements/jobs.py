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

from patrick.placements import envelopes, service, store

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
        apply_profile(params, meta)
        labels = {k: f["label"] for k, f in meta["funds"].items()}
        result = service.analyse(navs, labels, meta.get("cash"), params, progress)
        result["dataset"] = {"id": meta["id"], "name": meta["name"]}
        store.save_result(job.dataset_id, result)
        job.status, job.fraction, job.message = "done", 1.0, ""
    except (service.AnalysisError, store.StoreError, envelopes.EnvelopeError) as exc:
        job.status, job.error = "error", str(exc)
    except Exception as exc:
        log.exception("analyse de placements en échec")
        job.status, job.error = "error", f"Erreur de calcul : {type(exc).__name__}: {exc}"
    finally:
        job.finished = time.time()


def apply_profile(params: service.Params, meta: dict) -> service.Params:
    """Complète les paramètres d'analyse avec le profil du jeu de données : enveloppe, versements, bornes, groupes, avoirs, fonds en euros."""
    params.amount = meta["amount"]
    params.rf_annual = meta.get("rf_annual", store.DEFAULT_RF)
    env = meta.get("envelope") or {"kind": "none"}
    params.envelope = envelopes.normalise(env.get("kind", "none"), env.get("overrides"))
    params.contrib = envelopes.contributions(meta.get("contributions"))
    funds = {k: f for k, f in meta["funds"].items() if not f.get("excluded") or k == meta.get("cash")}
    params.bounds = {k: (float(f.get("min") or 0.0), float(f["max"]) if f.get("max") is not None else 1.0)
                     for k, f in funds.items() if f.get("min") is not None or f.get("max") is not None}
    params.euro_keys = tuple(k for k, f in funds.items() if f.get("role") == "euro")
    groups = []
    for g in meta.get("groups") or []:
        keys = list(g.get("keys") or []) or [k for k, f in funds.items() if f.get("category") == g.get("category")]
        if keys:
            groups.append((keys, float(g.get("min") or 0.0), float(g.get("max") if g.get("max") is not None else 1.0), g.get("category") or "sélection"))
    params.groups = groups
    params.holdings = dict(meta.get("holdings") or {})
    params.couple = bool(meta.get("couple"))
    return params


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
