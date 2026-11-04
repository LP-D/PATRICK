"""Éviction automatique du cache de volatilité en fin de job (ADR 0009, mise à jour du 04/11/2026).

`vol_model_cache` n'avait pas de plafond : 751 678 entrées en onze jours, une base de 69 Go et trois sauvegardes de 65 Go.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from typer.testing import CliRunner

from patrick import cache_eviction, worker
from patrick.storage_cli import storage_app
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db

TODAY = date(2026, 11, 4)


def _snap(days_ago: int, key: str = "raw_AAA") -> str:
    return f"{(TODAY - timedelta(days=days_ago)).isoformat()}__{key}__abc123"


@pytest.fixture
def conn(tmp_path):
    c = trackdb.connect(str(tmp_path / "patrick.db"))
    yield c
    c.close()


def _fill(conn, snapshot_ids, per_snapshot=3):
    for sid in snapshot_ids:
        for i in range(per_snapshot):
            trackdb.save_cached_vol_model(conn, sid, f"T{i}", "egarch", 100, 200, "h", [0.1, 0.2, None])


def _snapshots(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT DISTINCT snapshot_id FROM vol_model_cache")}


def test_old_snapshots_go_recent_and_undated_ones_stay(conn):
    odd = ["snap_1", "0001-pas-une-date", ""]
    _fill(conn, [_snap(0), _snap(1), _snap(3), _snap(4), _snap(10), *odd])

    removed = cache_eviction.evict_vol_cache(conn, 3, today=TODAY)

    assert removed == 2 * 3                                            # 4 et 10 jours : strictement avant la limite
    assert _snapshots(conn) == {_snap(0), _snap(1), _snap(3), *odd}


def test_dry_run_counts_without_deleting(conn):
    _fill(conn, [_snap(0), _snap(9)])
    assert cache_eviction.evict_vol_cache(conn, 3, dry_run=True, today=TODAY) == 3
    assert len(_snapshots(conn)) == 2


@pytest.mark.parametrize("days", [0, -1])
def test_zero_or_negative_disables_the_eviction(conn, days):
    _fill(conn, [_snap(0), _snap(40)])
    assert cache_eviction.evict_vol_cache(conn, days, today=TODAY) == 0
    assert len(_snapshots(conn)) == 2


@pytest.mark.parametrize("chunk", [1, 2, 4, 100])
def test_it_loops_over_chunks_until_nothing_is_left_to_remove(conn, chunk):
    _fill(conn, [_snap(5), _snap(6)], per_snapshot=2)                   # 4 lignes à retirer : 4 = 2 x 2, 4 x 1, 1 x 4
    _fill(conn, [_snap(0)])
    assert cache_eviction.evict_vol_cache(conn, 3, chunk=chunk, today=TODAY) == 4
    assert _snapshots(conn) == {_snap(0)}


def test_keep_days_comes_from_the_setting_with_a_safe_default(monkeypatch):
    def keep(value):
        monkeypatch.setattr(cache_eviction.settings, "load", lambda: {} if value is None else {"vol_cache_keep_days": value})
        return cache_eviction.vol_cache_keep_days()

    assert keep(None) == cache_eviction.DEFAULT_VOL_CACHE_KEEP_DAYS == 3
    assert keep(7) == 7 and keep("5") == 5 and keep(2.9) == 2
    assert keep(0) == 0 and keep(-4) == 0
    assert keep("beaucoup") == 3


def test_the_setting_is_used_when_no_value_is_given(conn, monkeypatch):
    monkeypatch.setattr(cache_eviction.settings, "load", lambda: {"vol_cache_keep_days": 1})
    _fill(conn, [_snap(0), _snap(1), _snap(2)])
    assert cache_eviction.evict_vol_cache(conn, today=TODAY) == 3
    assert _snapshots(conn) == {_snap(0), _snap(1)}


def test_the_end_of_job_tidying_evicts_the_cache_and_prints_it(conn, monkeypatch, capsys):
    monkeypatch.setattr(worker.prediction_archive, "archive_job_runs", lambda *_a, **_k: [])
    monkeypatch.setattr(cache_eviction, "evict_feature_cache", lambda *_a, **_k: {"removed_files": 0})
    monkeypatch.setattr(cache_eviction.settings, "load", dict)
    today = date.today()  # noqa: DTZ011
    _fill(conn, [f"{today.isoformat()}__raw_AAA__h", f"{(today - timedelta(days=30)).isoformat()}__raw_AAA__h"])

    worker._tidy_storage(conn, "job-1")

    assert _snapshots(conn) == {f"{today.isoformat()}__raw_AAA__h"}
    assert "cache de volatilité" in capsys.readouterr().out


def test_a_failing_eviction_never_fails_the_worker(conn, monkeypatch, capsys):
    monkeypatch.setattr(worker.prediction_archive, "archive_job_runs", lambda *_a, **_k: [])
    monkeypatch.setattr(cache_eviction, "evict_feature_cache", lambda *_a, **_k: {"removed_files": 0})

    def boom(*_a, **_k):
        raise RuntimeError("base verrouillée")

    monkeypatch.setattr(cache_eviction, "evict_vol_cache", boom)
    worker._tidy_storage(conn, "job-1")                                 # ne lève pas
    assert "base verrouillée" in capsys.readouterr().out


def test_the_storage_command_evicts_by_hand_and_refuses_beside_a_live_worker(tmp_path, monkeypatch):
    db = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db)
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    c = trackdb.connect(db)
    _fill(c, [_snap(0), _snap(60)])
    # la date de référence est celle du jour : on remplace les identifiants du test par des dates relatives à aujourd'hui
    today = date.today()  # noqa: DTZ011
    c.execute("UPDATE vol_model_cache SET snapshot_id = ? WHERE snapshot_id = ?", (f"{today.isoformat()}__raw_AAA__h", _snap(0)))
    c.execute("UPDATE vol_model_cache SET snapshot_id = ? WHERE snapshot_id = ?",
              (f"{(today - timedelta(days=60)).isoformat()}__raw_AAA__h", _snap(60)))
    c.commit()

    dry = CliRunner().invoke(storage_app, ["evict", "--feature-cache-gb", "150", "--vol-cache-days", "3", "--dry-run"])
    assert dry.exit_code == 0 and "vol_model_cache" in dry.output
    assert c.execute("SELECT COUNT(*) FROM vol_model_cache").fetchone()[0] == 6

    done = CliRunner().invoke(storage_app, ["evict", "--feature-cache-gb", "150", "--vol-cache-days", "3"])
    assert done.exit_code == 0
    assert c.execute("SELECT COUNT(*) FROM vol_model_cache").fetchone()[0] == 3

    jobs_db.write_heartbeat(c, pid=os.getpid())
    c.close()
    refused = CliRunner().invoke(storage_app, ["evict", "--feature-cache-gb", "150", "--vol-cache-days", "3"])
    assert refused.exit_code == 2 and "worker" in refused.output
