"""Verrou entre processus : un vrai second processus tient le verrou, celui-ci doit attendre puis renoncer."""
from __future__ import annotations

import sqlite3
import time

import pytest
from lock_support import Holder

from patrick.system import interprocess_lock as il


def test_a_free_lock_is_taken_and_released(tmp_path):
    path = tmp_path / "x.lock"
    with il.file_lock(path):
        pass
    with il.file_lock(path):                 # relâché : repris sans attendre
        pass


def test_a_lock_held_by_another_process_times_out(tmp_path):
    path = tmp_path / "x.lock"
    with Holder(path):
        started = time.monotonic()
        with pytest.raises(il.LockTimeout), il.file_lock(path, timeout_s=0.6, poll_s=0.1):
            pass
        assert time.monotonic() - started >= 0.5
    with il.file_lock(path):                 # l'autre processus a fini : le verrou est libre
        pass


def test_the_lock_is_freed_when_the_holder_dies(tmp_path):
    path = tmp_path / "x.lock"
    holder = Holder(path).__enter__()
    holder.proc.kill()                       # tué sans rien relâcher : le système libère le verrou
    holder.proc.wait(timeout=30)
    with il.file_lock(path, timeout_s=5, poll_s=0.1):
        pass


def test_the_locked_file_stays_readable_by_others(tmp_path):
    path = tmp_path / "x.lock"
    with Holder(path):
        assert path.read_bytes() == b""      # l'octet verrouillé est au-delà de la fin : une copie n'est jamais bloquée


def test_sqlite_file_names_the_database_or_none_in_memory(tmp_path):
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    assert il.sqlite_file(conn) == str(db)
    assert il.sqlite_file(sqlite3.connect(":memory:")) is None
