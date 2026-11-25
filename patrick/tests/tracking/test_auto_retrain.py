"""Ré-entraînement automatique dans un budget hebdomadaire (FO9 du 25/11)."""
from __future__ import annotations

from patrick.tracking import auto_retrain
from patrick.tracking import db as trackdb


def _items(n):
    return [{"run_id": f"r{i}", "target": f"T{i}", "key": "more_trials"} for i in range(n)]


def test_the_plan_never_exceeds_what_is_left_of_the_weekly_budget():
    conn = trackdb.connect()
    try:
        assert len(auto_retrain.plan(conn, 3, _items(10))) == 3
        conn.execute("INSERT INTO relaunch_log (job_id, parent_run_id, suggestion_key, source) VALUES ('j1', 'r', 'k', 'auto')")
        conn.execute("INSERT INTO relaunch_log (job_id, parent_run_id, suggestion_key, source) VALUES ('j2', 'r', 'k', 'batch')")
        conn.execute("INSERT INTO relaunch_log (job_id, parent_run_id, suggestion_key, source, created_at) "
                     "VALUES ('j3', 'r', 'k', 'auto', datetime('now', '-8 days'))")
        conn.commit()
        assert auto_retrain.used_this_week(conn) == 1                       # un lancement manuel et un d'il y a 8 jours ne comptent pas
        assert [i["target"] for i in auto_retrain.plan(conn, 3, _items(10))] == ["T0", "T1"]
    finally:
        conn.close()


def test_disabled_by_default_nothing_is_queued():
    out = auto_retrain.run()
    assert out == {"budget": 0, "used": 0, "queued": [], "skipped": []}
