"""L3 (garde-fou de robustesse, pas un nettoyage ponctuel) : un `run` laissé
`running` par un worker mort (kill -9, crash, bascule de conteneur -- cf.
AUDIT_ENVIRONNEMENT.md) ne doit plus jamais rester bloqué indéfiniment. Testé
en démarrant réellement `run_worker_loop` (pas en appelant
`db.reap_orphaned_runs` isolément) -- sans file de job, donc rapide (pas de
pipeline réel exécuté), contrairement à `test_worker.py` qui est marqué
`slow`.
"""
from __future__ import annotations

from patrick.tracking import db as trackdb
from patrick import worker as worker_module


def _insert_running_run(conn, run_id: str, hours_ago: float) -> None:
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    with conn:
        conn.execute(
            "INSERT INTO run (run_id, started_at, status, target, horizon, snapshot_id, "
            "config_json, config_hash, git_sha, seed, lib_versions) VALUES "
            "(?, datetime('now', ?), 'running', '^TEST', 5, 'snap1', '{}', 'cfg', 'sha', 42, '{}')",
            (run_id, f"-{hours_ago} hours"),
        )


def test_run_worker_loop_reaps_orphaned_running_run_at_startup(tmp_path, monkeypatch):
    """A `run` stuck 'running' well past any realistic single-run duration
    (2h, vs. `db.reap_orphaned_runs`'s default 1h age gate) must flip to
    'failed' with the exact reason the moment a new worker starts, even
    with no job ever queued."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)
    _insert_running_run(conn, "orphan_old", hours_ago=2)
    conn.close()

    worker_module.run_worker_loop(poll_interval=0.05, idle_timeout=0.01)

    conn = trackdb.connect(db_path)
    row = conn.execute("SELECT status, error, finished_at FROM run WHERE run_id = 'orphan_old'").fetchone()
    conn.close()
    assert row[0] == "failed"
    assert row[1] == "orphaned: no matching process at worker startup"
    assert row[2] is not None


def test_run_worker_loop_does_not_reap_a_recently_started_run(tmp_path, monkeypatch):
    """The age gate matters: `run_manager.ensure_worker_running` documents
    that two workers can briefly, legitimately overlap -- a run only a
    minute old must not be mistaken for orphaned just because a new worker
    happened to start."""
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    conn = trackdb.connect(db_path)
    _insert_running_run(conn, "orphan_recent", hours_ago=0.01)  # ~36s ago
    conn.close()

    worker_module.run_worker_loop(poll_interval=0.05, idle_timeout=0.01)

    conn = trackdb.connect(db_path)
    row = conn.execute("SELECT status FROM run WHERE run_id = 'orphan_recent'").fetchone()
    conn.close()
    assert row[0] == "running"
