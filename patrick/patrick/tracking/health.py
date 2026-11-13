"""Santé de la plateforme en une page (`/sante`) : ce qui doit tourner tout seul tourne-t-il ?

Chaque contrôle rend `{"key", "status", "value", "detail"}` avec `status` parmi `ok`, `warning`, `error`, `unknown`. Lecture seule ; un
contrôle en panne devient `unknown`, il n'empêche jamais les autres de s'afficher. Les libellés sont dans `webapp/i18n_health.py`
(`hl_<key>`), les valeurs sont des faits bruts (dates, nombres) mis en forme par le gabarit.
"""
from __future__ import annotations

import csv
import io
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from patrick import paths
from patrick.tracking import backup, pooled_signal, relaunch_stats

TASK_PREFIX = "Patrick"                 # tâches planifiées installées par `scripts/schtasks_*.ps1` et par l'installeur
BACKUP_WARN_HOURS, BACKUP_ERROR_HOURS = 36, 96
SIGNAL_WARN_HOURS, SIGNAL_ERROR_HOURS = 48, 120
POOLED_WARN_DAYS = 10
DRIFT_WARN_SHARE = 0.25
FREE_WARN_GB, FREE_ERROR_GB = 50, 15
HEARTBEAT_WARN_MINUTES = 15


def _check(key: str, status: str, value=None, detail=None) -> dict:
    return {"key": key, "status": status, "value": value, "detail": detail}


def _hours_since(stamp: str | None, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp).replace(" ", "T"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (now - when).total_seconds() / 3600.0


def _graded(hours: float | None, warn: float, error: float) -> str:
    if hours is None:
        return "error"
    return "ok" if hours < warn else ("warning" if hours < error else "error")


def scheduled_tasks(run=subprocess.run) -> list[dict]:
    """Tâches planifiées Windows dont le nom commence par `TASK_PREFIX` : `[{name, status, last_run, last_result, next_run}]`.
    `[]` hors de Windows ou si `schtasks` ne répond pas. Les colonnes sont lues par position (leurs titres sont traduits par Windows)."""
    try:
        done = run(["schtasks", "/Query", "/FO", "CSV", "/V", "/NH"], capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return []
    raw = done.stdout or b""
    text = raw if isinstance(raw, str) else raw.decode("cp850", errors="replace")      # page de codes de la console Windows
    out = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < 8:
            continue
        name = row[1].strip().lstrip("\\")
        if name.lower().startswith(TASK_PREFIX.lower()):
            out.append({"name": name, "next_run": row[2].strip(), "status": row[3].strip(), "last_run": row[5].strip(),
                        "last_result": row[6].strip()})
    return out


def _tasks(run) -> dict:
    tasks = scheduled_tasks(run)
    if not tasks:
        return _check("tasks", "unknown", 0, [])
    failed = [t for t in tasks if t["last_result"] not in ("0", "267009", "267011")]      # 0 = réussi ; 267009 = en cours ; 267011 = jamais lancée
    return _check("tasks", "warning" if failed else "ok", len(tasks), tasks)


def _backup(now: datetime) -> dict:
    age = backup.latest_backup_age(now=now.astimezone().replace(tzinfo=None))      # les noms de fichiers portent l'heure locale
    hours = age.total_seconds() / 3600.0 if age is not None else None
    return _check("backup", _graded(hours, BACKUP_WARN_HOURS, BACKUP_ERROR_HOURS), None if hours is None else round(hours, 1))


def _signals(conn: sqlite3.Connection, now: datetime) -> dict:
    # la clé primaire (trial_id, ts) : un MAX par champion, jamais un parcours de toutes les lignes `live`
    row = conn.execute(
        "SELECT MAX((SELECT MAX(ts) FROM prediction p WHERE p.trial_id = c.trial_id AND p.split = 'live')), COUNT(*) FROM champion c").fetchone()
    if not row[1]:
        return _check("signals", "unknown", None, 0)
    hours = _hours_since(row[0], now)
    # un signal porte la date de sa séance (minuit) : 48 h couvrent un week-end court sans alarme
    return _check("signals", _graded(hours, SIGNAL_WARN_HOURS + 48, SIGNAL_ERROR_HOURS + 48), str(row[0])[:10] if row[0] else None, int(row[1]))


def _live_failures(conn: sqlite3.Connection) -> dict:
    n = conn.execute("SELECT COUNT(*) FROM live_failure WHERE last_at >= datetime('now', '-2 days')").fetchone()[0]
    lost = relaunch_stats.lost_series(conn)
    return _check("live_failures", "ok" if not n else ("error" if lost else "warning"), int(n), lost[:5])


def _job_errors(conn: sqlite3.Connection) -> dict:
    n = conn.execute("SELECT COUNT(*) FROM job WHERE status = 'error' AND finished_at >= datetime('now', '-7 days') "
                     "AND COALESCE(error, '') NOT LIKE 'Stopped by user%'").fetchone()[0]
    return _check("job_errors", "ok" if not n else "warning", int(n))


def _pooled(conn: sqlite3.Connection, now: datetime) -> dict:
    summary = pooled_signal.summary(conn)
    if summary is None:
        return _check("pooled", "warning", None)
    hours = _hours_since(summary["computed_at"], now)
    days = None if hours is None else hours / 24.0
    return _check("pooled", "ok" if days is not None and days < POOLED_WARN_DAYS else "warning", None if days is None else round(days, 1),
                  {"n_tested": summary["n_tested"], "n_significant": summary["n_significant"]})


def _drift(conn: sqlite3.Connection) -> dict:
    champions = conn.execute("SELECT COUNT(*) FROM champion").fetchone()[0]
    measured = conn.execute("SELECT COUNT(*) FROM (SELECT DISTINCT symbol, horizon FROM drift_psi_history)").fetchone()[0]
    if not champions:
        return _check("drift", "unknown", 0, 0)
    share = measured / champions
    return _check("drift", "ok" if share >= DRIFT_WARN_SHARE else "warning", int(measured), int(champions))


def _worker(conn: sqlite3.Connection, now: datetime) -> dict:
    busy = conn.execute("SELECT COUNT(*) FROM job WHERE status IN ('queued', 'running')").fetchone()[0]
    row = conn.execute("SELECT updated_at FROM worker_heartbeat WHERE id = 1").fetchone()
    hours = _hours_since(row[0], now) if row else None
    minutes = None if hours is None else round(hours * 60, 1)
    if not busy:
        return _check("worker", "ok", minutes, 0)
    alive = minutes is not None and minutes < HEARTBEAT_WARN_MINUTES
    return _check("worker", "ok" if alive else "error", minutes, int(busy))


def _disk(db_file: str | None) -> dict:
    db = Path(db_file or paths.db_path())
    size_gb = db.stat().st_size / 1e9 if db.exists() else 0.0
    free_gb = shutil.disk_usage(db.parent if db.parent.exists() else Path.home()).free / 1e9
    status = "ok" if free_gb >= FREE_WARN_GB else ("warning" if free_gb >= FREE_ERROR_GB else "error")
    return _check("disk", status, round(free_gb, 1), round(size_gb, 1))


def checks(conn: sqlite3.Connection, now: datetime | None = None, run=subprocess.run, db_file: str | None = None) -> list[dict]:
    """Tous les contrôles, dans l'ordre de la page."""
    now = now or datetime.now(UTC)
    readers = (("tasks", lambda: _tasks(run)), ("backup", lambda: _backup(now)), ("signals", lambda: _signals(conn, now)),
               ("live_failures", lambda: _live_failures(conn)), ("job_errors", lambda: _job_errors(conn)),
               ("worker", lambda: _worker(conn, now)), ("pooled", lambda: _pooled(conn, now)), ("drift", lambda: _drift(conn)),
               ("disk", lambda: _disk(db_file)))
    out = []
    for key, read in readers:
        try:
            out.append(read())
        except Exception as exc:  # noqa: BLE001 -- un contrôle en panne ne masque jamais les autres
            out.append(_check(key, "unknown", None, f"{type(exc).__name__}: {exc}"))
    return out


def overall(items: list[dict]) -> str:
    """Le pire état de la page (`unknown` ne compte pas comme une alerte)."""
    for level in ("error", "warning"):
        if any(i["status"] == level for i in items):
            return level
    return "ok"
