"""A29 : une sauvegarde se restaure -- ouverte en lecture seule absolue, schéma et tables clés comparés à la base vivante."""
from __future__ import annotations

import sqlite3

from patrick.tracking import backup_verify
from patrick.tracking import db as trackdb


def _live(tmp_path):
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.upsert_snapshot(conn, "s", "h", None, None, None)
    trackdb.create_run(conn, "r1", target="AAPL", horizon=1, snapshot_id="s", config_json="{}", config_hash="c", git_sha="g", seed=1)
    tid = trackdb.create_trial(conn, "r1", "GLOBAL", "XGBoost", "none", 3, "shap")
    conn.execute("INSERT INTO prediction (trial_id, ts, split, y_pred) VALUES (?, '2026-01-02', 'live', 3)", (tid,))
    conn.commit()
    return conn


def _backup(live, folder, name="patrick_backup_20260101_000000.db"):
    folder.mkdir(exist_ok=True)
    dest = sqlite3.connect(folder / name)
    live.backup(dest)
    dest.close()
    return folder / name


def test_a_fresh_backup_passes_every_check_and_leaves_no_file_beside_it(tmp_path):
    live = _live(tmp_path)
    path = _backup(live, tmp_path / "backups")
    report = backup_verify.verify(path, live)
    assert report["ok"], report["checks"]
    assert {c["name"] for c in report["checks"]} >= {"complete", "schema", "table:run", "table:prediction", "tail"}
    assert sorted(p.name for p in (tmp_path / "backups").iterdir()) == [path.name]       # immutable : ni -wal ni -shm


def test_a_truncated_backup_or_one_that_lost_rows_fails(tmp_path):
    live = _live(tmp_path)
    path = _backup(live, tmp_path / "backups")
    data = path.read_bytes()
    bad = tmp_path / "backups" / "patrick_backup_20260102_000000.db"
    bad.write_bytes(data[: len(data) // 2])
    assert backup_verify.verify(bad, live)["ok"] is False
    live.execute("DELETE FROM prediction")
    live.commit()
    path2 = _backup(live, tmp_path / "b2")
    live.execute("INSERT INTO prediction (trial_id, ts, split, y_pred) SELECT trial_id, '2026-01-03', 'live', 3 FROM trial")
    live.commit()
    assert backup_verify.verify(path2, live)["ok"] is False                               # 0 prédiction dans la sauvegarde, 1 en vrai


def test_latest_backup_ignores_incomplete_files(tmp_path):
    live = _live(tmp_path)
    good = _backup(live, tmp_path / "backups", "patrick_backup_20260101_000000.db")
    (tmp_path / "backups" / "patrick_backup_20260105_000000.db").write_bytes(b"SQLite format 3\x00" + b"x" * 50)
    assert backup_verify.latest_backup(tmp_path / "backups") == good
