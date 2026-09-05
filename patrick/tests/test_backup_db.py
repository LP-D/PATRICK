"""Phase 6 -- sauvegarde périodique de la base SQLite (`patrick.tracking.backup`).

TDD sur la logique Python de la sauvegarde (pas sur la tâche planifiée
elle-même, qui est de la config système Windows -- voir
`scripts/schtasks_daily_dbbackup.ps1`, non testable ici et volontairement
non exécuté). Chaque test crée sa propre base SQLite légère sous `tmp_path`
-- jamais la vraie base de production (`~/.patrick/patrick.db`, ~4 Go)."""
from __future__ import annotations

import json
import re
import sqlite3
import time

import pytest

from patrick.tracking import backup
from patrick.tracking import db


def _make_populated_db(path: str) -> sqlite3.Connection:
    """Base de test avec au moins une table peuplée via `tracking/db.py`
    (comme le fait `tests/test_history.py::_make_run`), pas des INSERT bruts
    -- pour exercer le même chemin de code que la production (migrations
    incluses, WAL actif)."""
    conn = db.connect(path)
    db.upsert_snapshot(conn, "snap_1", "hash_1", 10, 5, "api")
    db.create_run(conn, "run_1", "^VIX", 5, "snap_1",
                   json.dumps({"name": "run_1"}), "cfghash", "sha123", 42)
    db.create_run(conn, "run_2", "^GSPC", 10, "snap_1",
                   json.dumps({"name": "run_2"}), "cfghash", "sha123", 7)
    db.finish_run(conn, "run_1", status="done", n_trials=3)
    return conn


def test_backup_database_creates_timestamped_file_in_dest_dir(tmp_path):
    source_path = str(tmp_path / "patrick.db")
    conn = _make_populated_db(source_path)
    conn.close()

    dest_dir = tmp_path / "backups"
    dest_path = backup.backup_database(source_path, str(dest_dir), timestamp="20260905_161500")

    assert dest_path.exists()
    assert dest_path.parent == dest_dir
    assert dest_path.name == "patrick_backup_20260905_161500.db"


def test_backup_database_default_timestamp_matches_expected_pattern(tmp_path):
    source_path = str(tmp_path / "patrick.db")
    _make_populated_db(source_path).close()

    dest_path = backup.backup_database(source_path, str(tmp_path / "backups"))

    assert re.match(r"^patrick_backup_\d{8}_\d{6}\.db$", dest_path.name)


def test_backup_database_creates_backup_dir_if_missing(tmp_path):
    source_path = str(tmp_path / "patrick.db")
    _make_populated_db(source_path).close()

    dest_dir = tmp_path / "does" / "not" / "exist" / "yet"
    assert not dest_dir.exists()

    dest_path = backup.backup_database(source_path, str(dest_dir))

    assert dest_dir.exists()
    assert dest_path.exists()


def test_backup_database_raises_if_source_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup.backup_database(str(tmp_path / "does_not_exist.db"), str(tmp_path / "backups"))


def test_backup_restoration_real_query_matches_source_data(tmp_path):
    """Test de restauration RÉEL (pas une démo manuelle) : sauvegarde d'une
    DB de test peuplée, puis ouverture de la copie produite via une NOUVELLE
    connexion sqlite3 et exécution d'une requête pour confirmer qu'elle est
    utilisable et contient les mêmes données que la source."""
    source_path = str(tmp_path / "patrick.db")
    source_conn = _make_populated_db(source_path)
    source_run_count = source_conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
    source_rows = source_conn.execute(
        "SELECT run_id, target, horizon, status FROM run ORDER BY run_id").fetchall()
    source_conn.close()
    assert source_run_count == 2  # sanity check sur la fixture elle-meme

    dest_path = backup.backup_database(source_path, str(tmp_path / "backups"))

    # Nouvelle connexion, independante de celle utilisee pour ecrire/sauvegarder.
    restored_conn = sqlite3.connect(str(dest_path))
    try:
        restored_run_count = restored_conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
        restored_rows = restored_conn.execute(
            "SELECT run_id, target, horizon, status FROM run ORDER BY run_id").fetchall()
        # La copie est une base independante et coherente (pas juste un fichier
        # .db partiel a cote d'un -wal non checkpointe) : integrity_check passe.
        integrity = restored_conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        restored_conn.close()

    assert restored_run_count == source_run_count == 2
    assert restored_rows == source_rows
    assert integrity == "ok"


def test_backup_restoration_survives_concurrent_writer_on_source(tmp_path):
    """Le scenario que shutil.copy gererait mal : une connexion source reste
    ouverte (WAL actif, ecriture en cours) pendant la sauvegarde. L'API
    sqlite3.Connection.backup() doit malgre tout produire une copie
    coherente et interrogeable."""
    source_path = str(tmp_path / "patrick.db")
    source_conn = _make_populated_db(source_path)

    # Ecriture supplementaire laissee "en vol" cote source, connexion non fermee,
    # pour simuler un worker actif pendant la sauvegarde.
    db.upsert_snapshot(source_conn, "snap_2", "hash_2", 1, 1, "api")
    db.create_run(source_conn, "run_3", "^DJI", 1, "snap_2",
                   json.dumps({"name": "run_3"}), "cfghash", "sha123", 1)

    try:
        dest_path = backup.backup_database(source_path, str(tmp_path / "backups"))

        restored_conn = sqlite3.connect(str(dest_path))
        try:
            count = restored_conn.execute("SELECT COUNT(*) FROM run").fetchone()[0]
            run_ids = {r[0] for r in restored_conn.execute("SELECT run_id FROM run").fetchall()}
        finally:
            restored_conn.close()
    finally:
        source_conn.close()

    assert count == 3
    assert run_ids == {"run_1", "run_2", "run_3"}
