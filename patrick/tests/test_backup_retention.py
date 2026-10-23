"""Plafond du nombre de sauvegardes, détection des copies incomplètes, saut de la copie avant mise à jour.

La base réelle pèse des dizaines de Go : sans plafond, la rétention de 30 jours et une copie à chaque mise à jour ont
rempli le disque (250 Go de sauvegardes dont 62 fichiers interrompus, le 2026-10-23). Bases légères sous `tmp_path`
uniquement, jamais le fichier réel.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from patrick import paths
from patrick.desktop import update
from patrick.tracking import backup
from patrick.tracking import db as trackdb


@pytest.fixture
def source(tmp_path) -> str:
    path = tmp_path / "patrick.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE t (x BLOB)")
    conn.executemany("INSERT INTO t VALUES (?)", [(os.urandom(1500),) for _ in range(60)])
    conn.commit()
    conn.close()
    return str(path)


def _stamp(days_ago: float = 0, hours_ago: float = 0) -> str:
    return (datetime.now() - timedelta(days=days_ago, hours=hours_ago)).strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005


def _name(stamp: str) -> str:
    return f"patrick_backup_{stamp}.db"


def _names(folder: Path, pattern: str = "patrick_backup_*") -> list[str]:
    return sorted(p.name for p in folder.glob(pattern))


def _make(source: str, dest: Path, stamp: str) -> Path:
    return backup.backup_database(source, str(dest), timestamp=stamp, retention_days=0, keep=0)


def _truncated_copy(original: Path, target: Path) -> Path:
    """Ce que laisse une sauvegarde interrompue : l'en-tête annonce toutes les pages, le fichier n'en a que la moitié."""
    shutil.copy(original, target)
    data = target.read_bytes()
    target.write_bytes(data[: len(data) // 2])
    return target


def _age(path: Path, seconds: float) -> None:
    ts = time.time() - seconds
    os.utime(path, (ts, ts))


def test_default_cap_is_three():
    assert backup.DEFAULT_KEEP_COUNT == 3


def test_only_the_newest_complete_copies_are_kept(tmp_path, source):
    dest = tmp_path / "backups"
    stamps = [_stamp(days_ago=d) for d in (5, 4, 3, 2, 1)]
    for s in stamps:
        _make(source, dest, s)                       # keep=0 : plafond désactivé
    assert len(_names(dest, "patrick_backup_*.db")) == 5

    new = _stamp()
    backup.backup_database(source, str(dest), timestamp=new, retention_days=0, keep=3)

    assert _names(dest, "patrick_backup_*.db") == sorted(_name(s) for s in [*stamps[-2:], new])


def test_default_call_applies_the_cap(tmp_path, source):
    dest = tmp_path / "backups"
    for d in (6, 5, 4, 3, 2):
        backup.backup_database(source, str(dest), timestamp=_stamp(days_ago=d), retention_days=0)
    assert len(_names(dest, "patrick_backup_*.db")) == backup.DEFAULT_KEEP_COUNT


def test_sidecar_files_follow_their_backup(tmp_path, source):
    dest = tmp_path / "backups"
    oldest = _make(source, dest, _stamp(days_ago=4))
    (dest / (oldest.name + "-wal")).write_bytes(b"")
    (dest / (oldest.name + "-shm")).write_bytes(b"")
    _make(source, dest, _stamp(days_ago=3))
    backup.backup_database(source, str(dest), timestamp=_stamp(), retention_days=0, keep=2)
    assert not oldest.exists()
    assert _names(dest, "*-wal") == [] and _names(dest, "*-shm") == []


def test_incomplete_copy_is_not_counted_and_is_removed_when_stale(tmp_path, source):
    dest = tmp_path / "backups"
    good = [_make(source, dest, _stamp(days_ago=d)) for d in (3, 2)]
    bad = _truncated_copy(good[0], dest / _name(_stamp(days_ago=1)))     # le nom le plus récent
    _age(bad, 7200)

    removed = backup._purge_excess_backups(dest, keep=2)

    assert removed == [bad]
    assert _names(dest, "patrick_backup_*.db") == sorted(p.name for p in good)   # elle n'a pas chassé une bonne copie


def test_recent_incomplete_copy_may_be_a_running_backup(tmp_path, source):
    dest = tmp_path / "backups"
    good = [_make(source, dest, _stamp(days_ago=d)) for d in (3, 2)]
    running = _truncated_copy(good[0], dest / _name(_stamp()))

    assert backup._purge_excess_backups(dest, keep=2) == []
    assert running.exists()


def test_stale_part_files_and_orphan_sidecars_go_but_fresh_or_foreign_files_stay(tmp_path):
    dest = tmp_path / "backups"
    dest.mkdir()
    stale_part = dest / "patrick_backup_20260101_000000.db.part"
    fresh_part = dest / "patrick_backup_20260102_000000.db.part"
    orphan = dest / "patrick_backup_20260103_000000.db-journal"
    foreign = dest / "patrick_backup_notes.txt"
    for p in (stale_part, fresh_part, orphan, foreign):
        p.write_bytes(b"x")
    for p in (stale_part, orphan, foreign):
        _age(p, 7200)

    removed = backup._purge_excess_backups(dest, keep=3)

    assert sorted(p.name for p in removed) == sorted([stale_part.name, orphan.name])
    assert fresh_part.exists() and foreign.exists()


def test_cap_disabled_with_zero_even_for_stale_files(tmp_path, source):
    dest = tmp_path / "backups"
    for d in (4, 3, 2, 1):
        _make(source, dest, _stamp(days_ago=d))
    assert backup._purge_excess_backups(dest, keep=0) == []
    assert len(_names(dest, "patrick_backup_*.db")) == 4


def test_is_complete_backup(tmp_path, source):
    dest = tmp_path / "backups"
    good = _make(source, dest, _stamp())
    assert backup.is_complete_backup(good)
    assert not backup.is_complete_backup(_truncated_copy(good, tmp_path / "moitie.db"))
    empty = tmp_path / "vide.db"
    empty.write_bytes(b"")
    text = tmp_path / "texte.db"
    text.write_bytes(b"pas une base sqlite " * 300)
    assert not backup.is_complete_backup(empty)
    assert not backup.is_complete_backup(text)
    assert not backup.is_complete_backup(tmp_path / "absent.db")


def test_backup_is_written_under_a_part_name_then_renamed(tmp_path, source):
    dest = tmp_path / "backups"
    path = backup.backup_database(source, str(dest), retention_days=0)
    assert backup.is_complete_backup(path)
    assert _names(dest, "*.part") == []


def test_failed_backup_leaves_neither_a_final_nor_a_part_file(tmp_path):
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"pas une base sqlite " * 400)
    dest = tmp_path / "backups"
    with pytest.raises(sqlite3.Error):
        backup.backup_database(str(junk), str(dest), timestamp="20260901_000000", retention_days=0)
    assert _names(dest) == []


def test_latest_backup_age_uses_the_newest_complete_copy(tmp_path, source):
    dest = tmp_path / "backups"
    assert backup.latest_backup_age(dest) is None                       # dossier absent
    _make(source, dest, _stamp(hours_ago=30))
    assert timedelta(hours=29.9) < backup.latest_backup_age(dest) < timedelta(hours=30.1)
    newest = _make(source, dest, _stamp(hours_ago=5))
    _truncated_copy(newest, dest / _name(_stamp(hours_ago=1)))           # plus récente mais incomplète
    assert timedelta(hours=4.9) < backup.latest_backup_age(dest) < timedelta(hours=5.1)


@pytest.fixture
def update_env(tmp_path, source, monkeypatch):
    dest = tmp_path / "backups"
    monkeypatch.setattr(paths, "backups_dir", lambda: dest)
    monkeypatch.setattr(trackdb, "default_db_path", lambda: source)
    calls: list = []

    class Done:
        returncode = 0
        stdout = "copie faite"
        stderr = ""

    monkeypatch.setattr(update.runtime, "run_hidden", lambda cmd, **kw: calls.append(cmd) or Done())
    monkeypatch.setattr(update.runtime, "console_python", lambda: "python")
    monkeypatch.setattr(update.runtime, "log_dir", lambda: tmp_path / "logs")
    return dest, calls


def test_update_without_any_backup_makes_one(update_env, source, tmp_path):
    _, calls = update_env
    assert update._backup_database(tmp_path / "projet") == (0, "copie faite")
    assert len(calls) == 1


def test_update_skips_the_copy_when_a_recent_backup_exists(update_env, source, tmp_path):
    dest, calls = update_env
    _make(source, dest, _stamp(hours_ago=2))
    code, message = update._backup_database(tmp_path / "projet")
    assert code == 0 and "récente" in message
    assert calls == []


def test_update_makes_a_copy_when_the_last_one_is_old(update_env, source, tmp_path):
    dest, calls = update_env
    _make(source, dest, _stamp(hours_ago=backup.RECENT_BACKUP_HOURS + 2))
    assert update._backup_database(tmp_path / "projet")[0] == 0
    assert len(calls) == 1


def test_update_ignores_a_recent_but_incomplete_copy(update_env, source, tmp_path):
    dest, calls = update_env
    old = _make(source, dest, _stamp(days_ago=3))
    _truncated_copy(old, dest / _name(_stamp(hours_ago=1)))
    update._backup_database(tmp_path / "projet")
    assert len(calls) == 1
