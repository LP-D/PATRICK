from __future__ import annotations

import json
import os
import sqlite3

import pytest

from patrick.tracking import db


def test_connect_creates_db_with_wal_and_migrates(tmp_path):
    path = str(tmp_path / "patrick.db")
    conn = db.connect(path)

    assert os.path.exists(path)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"snapshot", "run", "trial", "fold_metric", "baseline_metric",
            "prediction", "schema_version"}.issubset(tables)
    conn.close()


def test_migrate_is_idempotent(tmp_path):
    path = str(tmp_path / "patrick.db")
    conn1 = db.connect(path)
    version1 = conn1.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    conn1.close()

    conn2 = db.connect(path)  # reconnecte, remigre -> ne doit rien casser
    version2 = conn2.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert version1 == version2
    row_count = conn2.execute("SELECT count(*) FROM schema_version").fetchone()[0]
    n_migrations = len(list(db.MIGRATIONS_DIR.glob("*.sql")))
    assert row_count == n_migrations  # une ligne par migration, aucune rejouée deux fois
    conn2.close()


def test_migrate_tolerates_tables_created_under_a_prior_migration_numbering(tmp_path):
    """Real incident, not hypothetical: `0011_phase9_tracking.sql` was
    numbered `0010_phase9_tracking.sql` before an earlier renumbering
    (collision with this project's own `0010_dm_result_kind.sql`). A
    database that applied it under the old number has `phase9_snapshot`/
    `phase9_journal` on disk but no `schema_version` row recording version
    11 -- reproduced here by creating those tables directly and connecting
    to a schema_version stuck below 11, without ever running the actual
    migration script under either number."""
    path = str(tmp_path / "patrick.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    # Genuinely apply 0001..0009 (real scripts, not faked schema_version rows)
    # so dependent tables (e.g. `run`, `dm_result` from 0009) actually exist
    # -- migration 0010 rebuilds `dm_result` and would fail on a hollow fake.
    for script in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        version = int(script.name.split("_", 1)[0])
        if version >= 10:
            continue
        conn.executescript(script.read_text())
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()
    conn.execute(
        "CREATE TABLE phase9_snapshot (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "snapshot_name TEXT NOT NULL, payload_json TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE phase9_journal (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "action TEXT NOT NULL, actor TEXT NOT NULL DEFAULT 'system', "
        "before_json TEXT, after_json TEXT, reason TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.commit()
    conn.close()

    conn = db.connect(path)  # must not raise sqlite3.OperationalError: table phase9_snapshot already exists
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    n_migrations = len(list(db.MIGRATIONS_DIR.glob("*.sql")))
    assert applied == set(range(1, n_migrations + 1))  # every version now recorded, none skipped forever
    # dm_result went through its real 0010 rebuild (kind column present) --
    # not silently skipped just because phase9's table-existence check fired.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dm_result)")}
    assert "kind" in cols
    conn.close()


def test_migrate_skips_phase9_tables_individually_when_schema_version_stops_just_below_0011(tmp_path):
    """Isolated reproduction of the specific claim under investigation:
    `phase9_snapshot`/`phase9_journal` genuinely present on disk,
    `schema_version` capped at exactly 10 (the real-world value: this is
    the OLD phase9-as-0010 numbering, not the real 0010_dm_result_kind.sql,
    which never ran) -- deliberately narrower than
    `test_migrate_repairs_dm_result_kind_when_watermark_absorbed_it_under_old_phase9_numbering`
    below (which also asserts on dm_result/kind): this one only asserts on
    phase9 itself, so a regression there can't hide behind an unrelated
    dm_result assertion passing."""
    path = str(tmp_path / "patrick.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    for script in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        version = int(script.name.split("_", 1)[0])
        if version >= 10:
            continue
        conn.executescript(script.read_text())
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.execute(
        "CREATE TABLE phase9_snapshot (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "snapshot_name TEXT NOT NULL, payload_json TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE phase9_journal (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "action TEXT NOT NULL, actor TEXT NOT NULL DEFAULT 'system', "
        "before_json TEXT, after_json TEXT, reason TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    # A pre-existing row -- if the guard fails and 0011 re-runs its
    # CREATE TABLE, this row is either wiped (table recreated) or the
    # connect() call below raises before we even get to check.
    conn.execute(
        "INSERT INTO phase9_snapshot (snapshot_name, payload_json) VALUES ('pre-existing', '{}')"
    )
    conn.execute("INSERT INTO schema_version (version) VALUES (10)")
    conn.commit()
    conn.close()

    conn = db.connect(path)  # must not raise sqlite3.OperationalError: table phase9_snapshot already exists
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    assert 11 in applied  # phase9 recorded as applied, not skipped forever like dm_result_kind used to be
    names = conn.execute(
        "SELECT snapshot_name FROM phase9_snapshot ORDER BY id"
    ).fetchall()
    assert names == [("pre-existing",)]  # table left untouched, not recreated/wiped
    conn.close()


def test_migrate_repairs_dm_result_kind_when_watermark_absorbed_it_under_old_phase9_numbering(tmp_path):
    """Distinct instance of the same renumbering fallout covered by the test
    above, but worse: here `schema_version` genuinely records version 10 --
    not for the real `0010_dm_result_kind.sql`, but for the OLD
    `phase9_tracking` content that used to be numbered 0010 before the
    renumbering to 0011. The watermark (`version <= current`) then skips the
    real 0010 forever, since 10 already "looks done" -- `dm_result` is left
    on its pre-migration shape (no `kind` column) with no path back, unless
    migration 0012 (`0012_dm_result_kind_repair.sql`) catches it."""
    path = str(tmp_path / "patrick.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    for script in sorted(db.MIGRATIONS_DIR.glob("*.sql")):
        version = int(script.name.split("_", 1)[0])
        if version >= 10:
            continue
        conn.executescript(script.read_text())
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.execute(
        "CREATE TABLE phase9_snapshot (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "snapshot_name TEXT NOT NULL, payload_json TEXT NOT NULL, "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE phase9_journal (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "action TEXT NOT NULL, actor TEXT NOT NULL DEFAULT 'system', "
        "before_json TEXT, after_json TEXT, reason TEXT NOT NULL DEFAULT '', "
        "created_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    # The row that makes this the exact real-world case: version 10 recorded
    # for the OLD phase9 content, not for dm_result_kind, which never ran.
    conn.execute("INSERT INTO schema_version (version) VALUES (10)")
    conn.commit()
    conn.close()

    conn = db.connect(path)  # must not raise, must not skip dm_result_kind's fix forever
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dm_result)")}
    assert "kind" in cols
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    n_migrations = len(list(db.MIGRATIONS_DIR.glob("*.sql")))
    assert applied == set(range(1, n_migrations + 1))
    conn.close()


def test_migrate_repair_is_a_noop_when_dm_result_already_has_kind_column(tmp_path):
    """The common, healthy case: 0010_dm_result_kind.sql already ran
    normally. Migration 0012 must not rebuild dm_result a second time --
    verified by writing a row through the real save_dm_result() (which
    depends on the (run_id, kind) PRIMARY KEY for its ON CONFLICT clause)
    and confirming it survives a reconnect/remigrate untouched."""
    path = str(tmp_path / "patrick.db")
    conn = db.connect(path)
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", "{}", "cfg1", "sha", 42)
    db.save_dm_result(conn, "run1", {"baseline": "BASELINE_majority", "dm_stat": 1.2, "p_value": 0.05})
    conn.close()

    conn = db.connect(path)  # reconnect/remigrate -- must not raise, must not touch dm_result
    row = conn.execute("SELECT baseline, kind FROM dm_result WHERE run_id = 'run1'").fetchone()
    assert row == ("BASELINE_majority", "class_specific")
    conn.close()


def test_full_write_path_snapshot_run_trial_fold_metric_prediction(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))

    db.upsert_snapshot(conn, "snap1", "hash1", n_tickers=10, n_fred_series=2, fred_source="api")
    db.create_run(conn, "run1", target="^VIX", horizon=5, snapshot_id="snap1",
                   config_json=json.dumps({"a": 1}), config_hash="cfg1",
                   git_sha="deadbeef", seed=42)
    trial_id = db.create_trial(conn, run_id="run1", regime="GLOBAL", algo="RandomForest",
                                sampler="SMOTE", n_features=8, selector="shap")
    assert isinstance(trial_id, int)

    db.add_fold_metrics(conn, trial_id, fold_index=1, split="test",
                         metrics={"F1_dir": 0.61, "Acc_dir": 0.6, "AUC_ovr_4cls": float("nan")})
    db.add_baseline_metrics(conn, "run1", baseline="BASELINE_majority", split="test",
                             metrics={"F1_dir": 0.33})
    db.add_predictions(conn, trial_id, fold_index=1, split="test",
                        ts=["2020-01-01", "2020-01-02"], y_true=[1, 0], y_pred=[1, 1],
                        y_proba=[0.7, 0.4])
    db.finish_run(conn, "run1", status="done", n_trials=1)

    fm = conn.execute("SELECT metric, value FROM fold_metric WHERE trial_id = ?",
                       (trial_id,)).fetchall()
    assert ("F1_dir", 0.61) in fm
    # la métrique NaN (AUC absent pour ce fold) ne doit pas polluer la table
    assert not any(m == "AUC_ovr_4cls" for m, _ in fm)

    bm = conn.execute("SELECT value FROM baseline_metric WHERE run_id='run1'").fetchall()
    assert bm == [(0.33,)]

    preds = conn.execute("SELECT ts, y_true, y_pred, y_proba FROM prediction "
                          "WHERE trial_id = ? ORDER BY ts", (trial_id,)).fetchall()
    assert preds == [("2020-01-01", 1.0, 1.0, 0.7), ("2020-01-02", 0.0, 1.0, 0.4)]

    run_row = conn.execute("SELECT status, n_trials, finished_at FROM run WHERE run_id='run1'").fetchone()
    assert run_row[0] == "done" and run_row[1] == 1 and run_row[2] is not None

    conn.close()


def test_trial_deletion_cascades_to_fold_metric_and_prediction(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "run1", "^VIX", 5, "snap1", "{}", "cfg1", "sha", 42)
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.5})
    db.add_predictions(conn, trial_id, 1, "test", ["2020-01-01"], [1], [1])

    with conn:
        conn.execute("DELETE FROM trial WHERE trial_id = ?", (trial_id,))

    assert conn.execute("SELECT count(*) FROM fold_metric").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM prediction").fetchone()[0] == 0
    conn.close()


def test_run_requires_existing_snapshot_foreign_key(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    with pytest.raises(sqlite3.IntegrityError):
        db.create_run(conn, "run1", "^VIX", 5, "does_not_exist", "{}", "cfg1", "sha", 42)
    conn.close()


def test_library_versions_returns_valid_json():
    versions = json.loads(db.library_versions())
    assert "python" in versions
    assert "numpy" in versions


def test_current_git_sha_does_not_raise_outside_git_repo(tmp_path):
    sha = db.current_git_sha(cwd=str(tmp_path))
    assert isinstance(sha, str) and len(sha) > 0
