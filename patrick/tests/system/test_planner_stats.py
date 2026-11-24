"""Fin de job du worker : statistiques du planificateur SQLite rafraîchies (`PRAGMA optimize` borné), sans jamais faire échouer le job."""
from __future__ import annotations

from patrick.tracking import db as trackdb


def test_the_planner_statistics_are_refreshed_after_a_job_without_ever_failing_it(tmp_path):
    import sqlite3

    from patrick.system import worker

    conn = trackdb.connect(str(tmp_path / "p.db"))
    assert worker.refresh_planner_stats(conn) is True
    conn.close()
    closed = sqlite3.connect(":memory:")
    closed.close()
    assert worker.refresh_planner_stats(closed) is False          # base inutilisable : un message, jamais une exception
