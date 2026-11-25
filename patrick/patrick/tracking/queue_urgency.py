"""Tri de la file d'attente par urgence (AM9 du 25/11) : le bouton « Trier par urgence » de la file range les jobs en attente.

Urgence d'un job = celle de sa cible la plus en retard parmi ses horizons :

1. une paire cible × horizon sans champion passe d'abord (l'univers a un trou) ;
2. puis le champion le plus ancien (jours depuis sa promotion) ;
3. à égalité, l'ordre d'arrivée est gardé.

Le tri ne fait que réécrire l'ordre (`jobs.reorder_queued_jobs`, que tout worker lit déjà) : aucun job n'est ajouté ni retiré, et
l'ordre reste modifiable à la main ensuite. Un job dont la configuration est illisible garde sa place relative, en fin de liste."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

from patrick.tracking import jobs as jobs_db

NO_CHAMPION_DAYS = 10_000.0           # « jamais entraîné » passe devant tout champion, même très ancien


def _targets(config_json: str | None) -> list[tuple[str, int]]:
    try:
        cfg = json.loads(config_json or "{}")
    except (TypeError, ValueError):
        return []
    obj = cfg.get("objective") or {}
    symbol = obj.get("target_symbol")
    if not isinstance(symbol, str):
        return []
    horizons = obj.get("horizons") or ([obj["horizon"]] if obj.get("horizon") is not None else [])
    out = []
    for h in horizons:
        try:
            out.append((symbol, int(h)))
        except (TypeError, ValueError):
            continue
    return out


def urgency_days(conn: sqlite3.Connection, config_json: str | None, today: dt.date | None = None) -> float | None:
    """Jours de retard de la paire la plus en retard du job (None : configuration illisible)."""
    pairs = _targets(config_json)
    if not pairs:
        return None
    today = today or dt.date.today()  # noqa: DTZ011 -- jours calendaires locaux, comme la date de promotion lue
    worst = 0.0
    for target, horizon in pairs:
        row = conn.execute("SELECT promoted_at FROM champion WHERE target = ? AND horizon = ?", (target, horizon)).fetchone()
        if row is None or not row[0]:
            return NO_CHAMPION_DAYS
        try:
            promoted = dt.date.fromisoformat(str(row[0])[:10])
        except ValueError:
            return NO_CHAMPION_DAYS
        worst = max(worst, float((today - promoted).days))
    return worst


def sorted_queue(conn: sqlite3.Connection, today: dt.date | None = None) -> list[str]:
    """Identifiants des jobs en attente, du plus urgent au moins urgent (ordre d'arrivée à égalité)."""
    rows = conn.execute("SELECT job_id, config_json FROM job WHERE status = 'queued' ORDER BY created_at, rowid").fetchall()
    scored = []
    for rank, (job_id, cfg) in enumerate(rows):
        days = urgency_days(conn, cfg, today)
        scored.append((-(days if days is not None else -1.0), rank, job_id))
    return [job_id for _, _, job_id in sorted(scored)]


def sort_queue_by_urgency(conn: sqlite3.Connection, today: dt.date | None = None) -> list[str]:
    """Range la file et renvoie le nouvel ordre."""
    return jobs_db.reorder_queued_jobs(conn, sorted_queue(conn, today))
