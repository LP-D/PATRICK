"""Vitesse de l'application web : une connexion à une base à jour ne prend pas le verrou d'écriture, et l'empreinte de la
mémoïsation ne bouge pas quand le scan d'un run écrit ses prédictions de plis."""
from __future__ import annotations

import sqlite3
import time

from patrick.tracking import db, memo


def _insert_prediction(conn: sqlite3.Connection, ts: str, split: str, trial_id: int = 1) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")           # l'empreinte ne lit que `prediction` : pas besoin d'un run complet
    conn.execute("INSERT INTO prediction (trial_id, ts, fold_index, split, y_true, y_pred) VALUES (?, ?, 0, ?, 1, 1)",
                 (trial_id, ts, split))
    conn.commit()


def test_connect_to_an_up_to_date_db_does_not_wait_for_a_writer(tmp_path):
    path = str(tmp_path / "patrick.db")
    db.connect(path).close()                            # crée et migre

    writer = sqlite3.connect(path, timeout=30.0)
    writer.execute("BEGIN IMMEDIATE")                   # un worker au milieu d'une transaction d'écriture
    try:
        started = time.monotonic()
        reader = db.connect(path)                       # l'ancien `migrate()` attendait ici jusqu'à `busy_timeout` (30 s)
        elapsed = time.monotonic() - started
        assert elapsed < 5.0
        assert reader.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == len(list(db.MIGRATIONS_DIR.glob("*.sql")))
        reader.close()
    finally:
        writer.rollback()
        writer.close()


def test_connect_still_applies_a_missing_migration(tmp_path):
    path = str(tmp_path / "patrick.db")
    conn = db.connect(path)
    latest = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    conn.execute("DELETE FROM schema_version WHERE version = ?", (latest,))
    conn.commit()
    assert not db._schema_is_current(conn)
    conn.close()

    conn = db.connect(path)                             # la dernière migration est rejouée (idempotente) et enregistrée
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == latest
    assert db._schema_is_current(conn)
    conn.close()


def test_connect_sets_the_wal_friendly_pragmas(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1       # NORMAL
    assert conn.execute("PRAGMA cache_size").fetchone()[0] == -65536
    conn.close()


def test_memo_fingerprint_ignores_scan_predictions_but_follows_live_ones(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    before = memo.fingerprint(conn)

    _insert_prediction(conn, "2026-01-02", "test")
    _insert_prediction(conn, "2026-01-03", "holdout")
    assert memo.fingerprint(conn) == before             # un worker qui écrit des plis ne vide pas le cache

    _insert_prediction(conn, "2026-01-04", "live")
    live = memo.fingerprint(conn)
    assert live != before

    _insert_prediction(conn, "2026-01-04", "live", trial_id=2)         # une 2e prédiction live le même jour
    assert memo.fingerprint(conn) != live
    conn.close()
