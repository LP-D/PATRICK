"""`patrick champions init|list|history`: simulation by default, never
applied while a run is in progress (the deletions must not compete with a
worker writing to the database)."""
from __future__ import annotations

import json

from typer.testing import CliRunner

from patrick.cli import app
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db


def _seed(tmp_path, db_path: str) -> None:
    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    for run_id, started in (("old", "-2 days"), ("new", "-1 day")):
        trackdb.create_run(conn, run_id, target="^TEST", horizon=5, snapshot_id="snap1",
                           config_json="{}", config_hash="h", git_sha="sha", seed=42)
        with conn:
            conn.execute("UPDATE run SET status = 'done', started_at = datetime('now', ?) WHERE run_id = ?",
                         (started, run_id))
        tid = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "SMOTE", 3, "shap")
        path = str(tmp_path / f"{run_id}.joblib")
        open(path, "wb").close()
        with open(path[: -len(".joblib")] + "_meta.json", "w") as f:
            json.dump({"feature_names": ["a"]}, f)
        trackdb.mark_best_trial(conn, tid, artifact_path=path)
    conn.close()


def _runs(db_path: str) -> set[str]:
    conn = trackdb.connect(db_path)
    try:
        return {r[0] for r in conn.execute("SELECT run_id FROM run")}
    finally:
        conn.close()


def test_init_is_a_simulation_by_default(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    _seed(tmp_path, db_path)

    result = CliRunner().invoke(app, ["champions", "init"])

    assert result.exit_code == 0, result.output
    assert "garde new" in result.output and "Rien n'a été modifié" in result.output
    assert _runs(db_path) == {"old", "new"}


def test_init_apply_keeps_the_latest_and_lists_it(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    _seed(tmp_path, db_path)

    result = CliRunner().invoke(app, ["champions", "init", "--apply"])

    assert result.exit_code == 0, result.output
    assert _runs(db_path) == {"new"}
    listing = CliRunner().invoke(app, ["champions", "list"])
    assert "new" in listing.output and "initial_latest" in listing.output
    history = CliRunner().invoke(app, ["champions", "history", "--target", "^TEST"])
    assert "superseded" in history.output and "old" in history.output


def test_init_apply_is_refused_while_a_worker_is_alive(tmp_path, monkeypatch):
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    _seed(tmp_path, db_path)
    conn = trackdb.connect(db_path)
    jobs_db.write_heartbeat(conn, pid=12345)
    conn.close()

    result = CliRunner().invoke(app, ["champions", "init", "--apply"])

    assert result.exit_code == 1
    assert "refusée" in result.output
    assert _runs(db_path) == {"old", "new"}
