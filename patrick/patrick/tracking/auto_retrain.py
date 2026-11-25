"""Ré-entraînement automatique (FO9 du 25/11) : la nuit met elle-même en file les runs conseillés, dans un budget hebdomadaire.

Le lot « runs conseillés » (`webapp/launch_batches.recommended`) classe, par cible, le réentraînement qui vaut le plus son temps de
calcul (dérive, champion ancien, signal regroupé, suggestion du conseiller). Jusqu'ici il fallait l'ouvrir et cliquer. Ici :

- réglage `auto_retrain_per_week` (0 par défaut : rien ne part sans qu'on l'ait demandé) ;
- à chaque passage (`patrick retrain auto`, dernière étape de la nuit), on compte les jobs déjà mis en file par ce mécanisme sur les
  7 derniers jours (`relaunch_log.source = 'auto'`) et on met en file les premiers conseillés jusqu'au budget ;
- chaque configuration passe par les mêmes validations que le formulaire ; une configuration refusée est sautée, pas bloquante.
"""
from __future__ import annotations

import sqlite3

from patrick.core import settings

KEY_BUDGET = "auto_retrain_per_week"
SOURCE = "auto"


def weekly_budget() -> int:
    try:
        return max(0, int(float(settings.load().get(KEY_BUDGET, 0) or 0)))
    except (TypeError, ValueError):
        return 0


def used_this_week(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM relaunch_log WHERE source = ? AND created_at >= datetime('now', '-7 days')",
                            (SOURCE,)).fetchone()[0])


def plan(conn: sqlite3.Connection, budget: int, recommended: list[dict]) -> list[dict]:
    """Les conseillés à lancer maintenant : les premiers de la liste, dans ce qui reste du budget de la semaine."""
    left = max(0, budget - used_this_week(conn))
    return recommended[:left]


def run(budget: int | None = None, dry_run: bool = False) -> dict:
    """Met en file ce que le budget permet. Retourne `{budget, used, queued: [...], skipped: [...]}`."""
    budget = weekly_budget() if budget is None else max(0, int(budget))
    out: dict = {"budget": budget, "used": 0, "queued": [], "skipped": []}
    if budget == 0:
        return out
    from patrick.tracking import data_health
    from patrick.tracking import db as trackdb
    from patrick.webapp import launch_batches, run_manager

    conn = trackdb.connect()
    try:
        out["used"] = used_this_week(conn)
        if out["used"] >= budget:
            return out
        history = data_health.history_depths()
        todo = plan(conn, budget, launch_batches.recommended(conn, history))
        configs = []
        for item in todo:
            config, errors = launch_batches.build_recommended_config(conn, item["run_id"], item["key"], history)
            if config is None:
                out["skipped"].append({"target": item["target"], "reason": "; ".join(errors)[:200]})
            else:
                configs.append((item, config))
    finally:
        conn.close()
    for item, config in configs:
        if dry_run:
            out["queued"].append({"target": item["target"], "key": item["key"], "job_id": None})
            continue
        job = run_manager.start_run(config)
        launch_batches.note_relaunch(job["id"], item["run_id"], item["key"], SOURCE)
        out["queued"].append({"target": item["target"], "key": item["key"], "job_id": job["id"]})
    return out
