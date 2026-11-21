"""Études du laboratoire en tâche de fond (un fil par étude) avec avancement, et historique des études sur disque pour les comparer.

    <racine de données>/strategylab/runs/<id>.json   résultat complet d'une étude
    <racine de données>/strategylab/runs/index.json  résumé de chaque étude (nom, date, modèle, indicateurs clés, courbe allégée)

Une seule étude à la fois : relancer pendant qu'une étude tourne renvoie la même tâche (le téléchargement des cours est le plus long, deux études
en parallèle se gêneraient). L'historique garde les `KEEP_RUNS` plus récentes ; une étude épinglée n'est jamais supprimée.
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from patrick import paths
from patrick.strategylab import (
    backtest,
    data,
    events,
    indicators,
    rules,
    service,
    templates,
)

log = logging.getLogger(__name__)
KEEP_JOBS = 20
KEEP_RUNS = 40
RUN_ID = re.compile(r"^[a-f0-9]{12}$")
USER_ERRORS = (service.StudyError, data.DataError, events.EventsError, backtest.BacktestError, rules.RuleError, indicators.IndicatorError,
               templates.TemplateError)


@dataclass
class Job:
    id: str
    status: str = "running"          # running | done | error
    fraction: float = 0.0
    message: str = ""
    error: str | None = None
    run_id: str | None = None
    started: float = 0.0
    finished: float | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_index_lock = threading.Lock()


def runs_dir() -> Path:
    return paths.data_root() / "strategylab" / "runs"


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{secrets.token_hex(3)}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def _read_index() -> list[dict]:
    path = runs_dir() / "index.json"
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _summary(run_id: str, result: dict) -> dict:
    s, spec = result["summary"], result["spec"]
    series = result["series"]
    step = max(1, len(series["dates"]) // 300)
    return {"id": run_id, "name": spec["name"], "created": result["generated_at"], "template": spec["template"], "symbols": spec["symbols"][:8],
            "n_symbols": len(spec["symbols"]), "start": result["period"]["start"], "end": result["period"]["end"], "pinned": False,
            "cagr": s.get("cagr"), "sharpe": s.get("sharpe"), "max_dd": s.get("max_dd"), "vol": s.get("vol"), "pnl": s.get("pnl"),
            "verdict": result["verdict"]["state"], "trades": result["trade_stats"].get("count", 0),
            "curve": {"dates": series["dates"][::step], "equity": [v / series["equity"][0] if v is not None and series["equity"][0] else None for v in series["equity"][::step]]}}


def save_run(result: dict) -> str:
    run_id = secrets.token_hex(6)
    _write(runs_dir() / f"{run_id}.json", result)
    with _index_lock:
        index = [_summary(run_id, result)] + _read_index()
        keep, drop = [], []
        for row in index:
            (keep if row.get("pinned") or len([k for k in keep if not k.get("pinned")]) < KEEP_RUNS else drop).append(row)
        for row in drop:
            (runs_dir() / f"{row['id']}.json").unlink(missing_ok=True)
        _write(runs_dir() / "index.json", keep)
    return run_id


def list_runs() -> list[dict]:
    return _read_index()


def load_run(run_id: str) -> dict | None:
    if not RUN_ID.match(run_id or ""):
        return None
    path = runs_dir() / f"{run_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def update_run(run_id: str, *, name: str | None = None, pinned: bool | None = None) -> dict:
    if not RUN_ID.match(run_id or ""):
        raise service.StudyError("Étude inconnue.")
    with _index_lock:
        index = _read_index()
        row = next((r for r in index if r["id"] == run_id), None)
        if row is None:
            raise service.StudyError("Étude inconnue.")
        if name is not None:
            row["name"] = name.strip()[:80] or row["name"]
        if pinned is not None:
            row["pinned"] = bool(pinned)
        _write(runs_dir() / "index.json", index)
    return row


def delete_run(run_id: str) -> None:
    if not RUN_ID.match(run_id or ""):
        raise service.StudyError("Étude inconnue.")
    with _index_lock:
        index = [r for r in _read_index() if r["id"] != run_id]
        _write(runs_dir() / "index.json", index)
    (runs_dir() / f"{run_id}.json").unlink(missing_ok=True)


def _run(job: Job, runner: Callable[[Callable[[float, str], None]], dict]) -> None:
    def progress(fraction: float, message: str) -> None:
        job.fraction, job.message = float(fraction), message

    try:
        result = runner(progress)
        job.run_id = save_run(result)
        job.status, job.fraction, job.message = "done", 1.0, ""
    except USER_ERRORS as exc:
        job.status, job.error = "error", str(exc)
    except Exception as exc:
        log.exception("étude de stratégie en échec")
        job.status, job.error = "error", f"Erreur de calcul : {type(exc).__name__}: {exc}"
    finally:
        job.finished = time.time()


def start(runner: Callable[[Callable[[float, str], None]], dict]) -> Job:
    with _lock:
        for job in _jobs.values():
            if job.status == "running":
                return job
        job = Job(id=secrets.token_hex(6), started=time.time())
        _jobs[job.id] = job
        for old in sorted((j for j in _jobs.values() if j.status != "running"), key=lambda j: j.started)[:-KEEP_JOBS]:
            _jobs.pop(old.id, None)
    threading.Thread(target=_run, args=(job, runner), name=f"strategylab-{job.id}", daemon=True).start()
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def snapshot(job: Job) -> dict:
    d = asdict(job)
    d["elapsed"] = round((job.finished or time.time()) - job.started, 1)
    return d


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
