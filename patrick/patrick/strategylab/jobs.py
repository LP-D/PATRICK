"""Études de stratégies en tâche de fond (un fil par étude) avec avancement ; le dernier résultat de chaque type d'étude est écrit sur disque
(`<racine de données>/strategylab/last_<type>.json`) et se relit après un redémarrage. Une seule étude à la fois par type : relancer pendant qu'elle tourne
renvoie la même tâche. Le téléchargement des cours (Yahoo) est ce qui prend du temps ; l'évaluation, elle, dure quelques secondes."""
from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from patrick import paths
from patrick.strategylab import core, events, prices

log = logging.getLogger(__name__)
KEEP = 20
KINDS = ("event", "straddle")


@dataclass
class Job:
    id: str
    kind: str
    status: str = "running"          # running | done | error
    fraction: float = 0.0
    message: str = ""
    error: str | None = None
    started: float = 0.0
    finished: float | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def last_path(kind: str) -> Path:
    if kind not in KINDS:
        raise core.StrategyError("Type d'étude inconnu.")
    return paths.data_root() / "strategylab" / f"last_{kind}.json"


def save_last(kind: str, result: dict) -> None:
    path = last_path(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{secrets.token_hex(3)}.tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def load_last(kind: str) -> dict | None:
    path = last_path(kind)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _run(job: Job, runner: Callable[[Callable[[float, str], None]], dict]) -> None:
    def progress(fraction: float, message: str) -> None:
        job.fraction, job.message = float(fraction), message

    try:
        result = runner(progress)
        save_last(job.kind, result)
        job.status, job.fraction, job.message = "done", 1.0, ""
    except (core.StrategyError, events.EventsError, prices.PricesError) as exc:
        job.status, job.error = "error", str(exc)
    except Exception as exc:
        log.exception("étude de stratégie en échec")
        job.status, job.error = "error", f"Erreur de calcul : {type(exc).__name__}: {exc}"
    finally:
        job.finished = time.time()


def start(kind: str, runner: Callable[[Callable[[float, str], None]], dict]) -> Job:
    if kind not in KINDS:
        raise core.StrategyError("Type d'étude inconnu.")
    with _lock:
        for job in _jobs.values():
            if job.kind == kind and job.status == "running":
                return job
        job = Job(id=secrets.token_hex(6), kind=kind, started=time.time())
        _jobs[job.id] = job
        for old in sorted((j for j in _jobs.values() if j.status != "running"), key=lambda j: j.started)[:-KEEP]:
            _jobs.pop(old.id, None)
    threading.Thread(target=_run, args=(job, runner), name=f"strategylab-{job.id}", daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def snapshot(job: Job) -> dict:
    d = asdict(job)
    d["elapsed"] = round((job.finished or time.time()) - job.started, 1)
    return d
