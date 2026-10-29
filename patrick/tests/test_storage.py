"""Stockage et vitesse d'entraînement (ADR 0009) : archivage des prédictions du scan, index, caches comprimés et évincés."""
from __future__ import annotations

import os
import time

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from patrick import cache_eviction
from patrick.features import pool_cache
from patrick.storage_cli import storage_app
from patrick.tracking import db as trackdb
from patrick.tracking import jobs as jobs_db
from patrick.tracking import prediction_archive as archive


def _seed(conn, n_trials=8, rows_per_split=6):
    """Un run terminé, `n_trials` essais (F1_dir moyen croissant avec le numéro d'essai), le dernier marqué meilleur, des prédictions
    test / holdout / live pour chacun."""
    trackdb.upsert_snapshot(conn, "snap", "hash", 0, 1, "api")
    trackdb.create_run(conn, "r1", target="AAA", horizon=1, snapshot_id="snap", config_json="{}", config_hash="x", git_sha="x", seed=1)
    trial_ids = []
    for i in range(n_trials):
        tid = trackdb.create_trial(conn, "r1", "GLOBAL", "XGBoost", "none", 5 + i, "shap")
        trial_ids.append(tid)
        trackdb.add_fold_metrics(conn, tid, 1, "test", {"F1_dir": 0.40 + 0.01 * i})
        trackdb.add_fold_metrics(conn, tid, 2, "test", {"F1_dir": 0.42 + 0.01 * i})
        for split, fold in (("test", 1), ("holdout", 0), ("live", 0)):
            ts = [f"2026-0{fold + 1}-{d:02d}" if split != "live" else f"2026-10-{d:02d}" for d in range(1, rows_per_split + 1)]
            trackdb.add_predictions(conn, tid, fold_index=fold, split=split, ts=ts,
                                    y_true=[1.0] * rows_per_split if split != "live" else [None] * rows_per_split,
                                    y_pred=[float(i % 4)] * rows_per_split, y_proba=[0.5] * rows_per_split, p_up=[0.6] * rows_per_split)
    trackdb.mark_best_trial(conn, trial_ids[-1])
    trackdb.finish_run(conn, "r1", status="done", n_trials=n_trials)
    return trial_ids


def _count(conn, split=None, trial_ids=None):
    sql, params = "SELECT COUNT(*) FROM prediction WHERE 1=1", []
    if split:
        sql += " AND split = ?"
        params.append(split)
    if trial_ids:
        sql += f" AND trial_id IN ({','.join('?' for _ in trial_ids)})"
        params += list(trial_ids)
    return conn.execute(sql, params).fetchone()[0]


@pytest.fixture
def conn(tmp_path):
    c = trackdb.connect(str(tmp_path / "patrick.db"))
    yield c
    c.close()


# --------------------------------------------------------------------------- prédictions du scan

def test_the_best_trial_and_the_top_k_stay_in_the_database(conn):
    trial_ids = _seed(conn)
    keep = archive.keep_trials(conn, "r1", top_k=2)
    assert keep == {trial_ids[-1], trial_ids[-2]}                              # le meilleur est aussi le premier du top : 2 essais en tout
    assert archive.keep_trials(conn, "r1", top_k=0) == {trial_ids[-1]}
    conn.execute("UPDATE trial SET is_best = 0")
    conn.execute("UPDATE trial SET is_best = 1 WHERE trial_id = ?", (trial_ids[0],))        # un meilleur essai de score moyen reste gardé
    assert archive.keep_trials(conn, "r1", top_k=2) == {trial_ids[0], trial_ids[-1], trial_ids[-2]}


def test_archiving_moves_scan_predictions_of_the_other_trials_to_parquet_and_touches_nothing_else(conn, tmp_path):
    trial_ids = _seed(conn)
    before = {s: _count(conn, s) for s in ("test", "holdout", "live")}
    res = archive.archive_run(conn, "r1", top_k=2, root=tmp_path / "arch")
    others = trial_ids[:-2]
    assert res["trials"] == len(others) and res["rows"] == res["deleted"] == len(others) * 6
    assert _count(conn, "test", others) == 0 and _count(conn, "test", trial_ids[-2:]) == 2 * 6
    assert {s: _count(conn, s) for s in ("holdout", "live")} == {s: before[s] for s in ("holdout", "live")}      # jamais touchés
    assert conn.execute("SELECT COUNT(*) FROM fold_metric WHERE split = 'test'").fetchone()[0] == len(trial_ids) * 2   # le PBO s'appuie dessus
    frame = pd.read_parquet(res["path"])
    assert len(frame) == res["rows"] and set(frame["trial_id"]) == set(others) and set(frame["split"]) == {"test"}


def test_restore_puts_back_exactly_what_was_archived(conn, tmp_path):
    _seed(conn)
    snapshot = conn.execute("SELECT trial_id, ts, fold_index, split, y_true, y_pred, y_proba, path_id, p_up FROM prediction ORDER BY 1, 2, 4").fetchall()
    archive.archive_run(conn, "r1", top_k=1, root=tmp_path / "arch")
    assert len(conn.execute("SELECT 1 FROM prediction").fetchall()) < len(snapshot)
    assert archive.restore_run(conn, "r1", tmp_path / "arch") > 0
    again = conn.execute("SELECT trial_id, ts, fold_index, split, y_true, y_pred, y_proba, path_id, p_up FROM prediction ORDER BY 1, 2, 4").fetchall()
    assert again == snapshot


def test_a_dry_run_changes_nothing_and_a_second_run_finds_nothing(conn, tmp_path):
    _seed(conn)
    total = _count(conn)
    dry = archive.archive_run(conn, "r1", top_k=1, root=tmp_path / "arch", dry_run=True)
    assert dry["rows"] > 0 and dry["deleted"] == 0 and _count(conn) == total and not (tmp_path / "arch").exists()
    archive.archive_run(conn, "r1", top_k=1, root=tmp_path / "arch")
    again = archive.archive_run(conn, "r1", top_k=1, root=tmp_path / "arch")
    assert again["rows"] == 0 and again["deleted"] == 0


def test_nothing_is_deleted_when_the_archive_cannot_be_verified(conn, tmp_path, monkeypatch):
    _seed(conn)
    total = _count(conn)
    monkeypatch.setattr(archive, "_write_parquet", lambda frame, path: len(frame) - 1)
    with pytest.raises(RuntimeError, match="incomplète"):
        archive.archive_run(conn, "r1", top_k=1, root=tmp_path / "arch")
    assert _count(conn) == total


def test_the_automatic_archiving_respects_the_kill_switch_and_never_raises(conn, tmp_path, monkeypatch):
    _seed(conn)
    conn.execute("UPDATE run SET job_id = 'job1'")
    conn.commit()
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv(archive.ENV_KEEP_ALL, "1")
    assert archive.archive_job_runs(conn, "job1") == []
    monkeypatch.delenv(archive.ENV_KEEP_ALL)
    monkeypatch.setattr(archive, "archive_runs", lambda *a, **k: (_ for _ in ()).throw(OSError("disque plein")))
    assert archive.archive_job_runs(conn, "job1") == []


def test_only_finished_runs_are_listed_for_archiving(conn):
    _seed(conn)
    trackdb.create_run(conn, "r2", target="BBB", horizon=1, snapshot_id="snap", config_json="{}", config_hash="x", git_sha="x", seed=1)
    assert archive.finished_run_ids(conn) == ["r1"]


# --------------------------------------------------------------------------- index

def test_reindexing_replaces_the_two_prediction_indexes_by_a_partial_live_index(conn):
    _seed(conn)
    names = lambda: {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'prediction'")}
    assert {"idx_pred_path", "idx_pred_split"} <= names() and archive.live_index_hint(conn) == "idx_pred_split"
    archive.reindex_predictions(conn)
    assert "idx_pred_path" not in names() and "idx_pred_split" not in names() and archive.LIVE_INDEX in names()
    assert archive.live_index_hint(conn) == archive.LIVE_INDEX
    rows = conn.execute(f"SELECT trial_id, ts FROM prediction INDEXED BY {archive.live_index_hint(conn)} WHERE split = 'live' ORDER BY ts").fetchall()
    assert len(rows) == _count(conn, "live")
    plan = " ".join(str(r) for r in conn.execute("EXPLAIN QUERY PLAN SELECT COUNT(*), MAX(ts) FROM prediction WHERE split = 'live'"))
    assert archive.LIVE_INDEX in plan                                              # la requête de l'empreinte de cache l'utilise
    archive.reindex_predictions(conn)                                              # idempotent


def test_optimize_planner_creates_statistics(conn):
    _seed(conn)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'sqlite_stat1'").fetchone()[0] == 0
    archive.optimize_planner(conn, 500)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_stat1").fetchone()[0] > 0


# --------------------------------------------------------------------------- cache des modèles de volatilité

def test_vol_cache_entries_are_stored_compressed_and_read_back_identically(conn):
    values = [0.1234567890123, None, 1e-9, 3.0] * 500
    trackdb.save_cached_vol_model(conn, "snap", "AAPL", "egarch", 100, 200, "h", values)
    stored = conn.execute("SELECT result_json FROM vol_model_cache").fetchone()[0]
    assert isinstance(stored, bytes) and len(stored) < len(str(values)) / 2
    assert trackdb.get_cached_vol_model(conn, "snap", "AAPL", "egarch", 100, 200, "h") == values


def test_plain_text_entries_stay_readable_and_can_be_recompressed(conn):
    plain = "[0.5, null, 2.25]"
    conn.execute("INSERT INTO vol_model_cache (snapshot_id, ticker, model, fit_end_idx, test_end_idx, data_hash, result_json) "
                 "VALUES ('s', 'T', 'kalman', 1, 2, 'h', ?)", (plain,))
    conn.commit()
    assert trackdb.get_cached_vol_model(conn, "s", "T", "kalman", 1, 2, "h") == [0.5, None, 2.25]
    out = cache_eviction.recompress_vol_cache(conn, chunk=1)
    assert out["recompressed"] == 1
    assert isinstance(conn.execute("SELECT result_json FROM vol_model_cache").fetchone()[0], bytes)
    assert trackdb.get_cached_vol_model(conn, "s", "T", "kalman", 1, 2, "h") == [0.5, None, 2.25]
    assert cache_eviction.recompress_vol_cache(conn)["recompressed"] == 0         # reprenable : rien à refaire


def test_old_db_cache_entries_are_pruned_by_age(conn):
    for i, age in enumerate((200, 10)):
        conn.execute("INSERT INTO vol_model_cache (snapshot_id, ticker, model, fit_end_idx, test_end_idx, data_hash, result_json, created_at) "
                     "VALUES ('s', 'T', 'm', ?, 2, 'h', '[1]', datetime('now', ?))", (i, f"-{age} days"))
    conn.commit()
    assert cache_eviction.prune_db_caches(conn, 90, dry_run=True)["vol_model_cache"] == 1
    assert conn.execute("SELECT COUNT(*) FROM vol_model_cache").fetchone()[0] == 2
    assert cache_eviction.prune_db_caches(conn, 90, chunk=1)["vol_model_cache"] == 1
    assert [r[0] for r in conn.execute("SELECT fit_end_idx FROM vol_model_cache")] == [1]


# --------------------------------------------------------------------------- cache de variables

def _file(root, name, size, age_s):
    path = root / name[:2] / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


def test_the_feature_cache_evicts_the_least_recently_used_files_first(tmp_path):
    old, mid, new = (_file(tmp_path, "aa1", 100, 30 * 86400), _file(tmp_path, "bb2", 100, 10 * 86400), _file(tmp_path, "cc3", 100, 2 * 86400))
    dry = cache_eviction.evict_feature_cache(150, root=tmp_path, dry_run=True)
    assert dry["removed_files"] == 2 and old.exists() and mid.exists()
    out = cache_eviction.evict_feature_cache(150, root=tmp_path)
    assert out["removed_files"] == 2 and out["removed_bytes"] == 200
    assert not old.exists() and not mid.exists() and new.exists()


def test_a_recent_cache_file_is_never_evicted_and_a_missing_folder_is_fine(tmp_path):
    fresh = _file(tmp_path, "dd4", 100, 10)
    assert cache_eviction.evict_feature_cache(0, root=tmp_path)["removed_files"] == 0 and fresh.exists()
    assert cache_eviction.evict_feature_cache(0, root=tmp_path / "nulle-part")["files"] == 0


def test_pool_cache_is_lossless_smaller_and_marks_files_as_used(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_FEATURE_CACHE_ROOT", str(tmp_path))
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(rng.normal(size=(2000, 30)), columns=[f"f{i}" for i in range(30)], index=pd.bdate_range("2010-01-01", periods=2000))
    frame.iloc[5, 3] = np.nan
    pool_cache.save("abcdef", frame)
    back = pool_cache.load("abcdef")
    pd.testing.assert_frame_equal(back, frame, check_freq=False)                   # sans perte : mêmes float64
    path = pool_cache._path("abcdef")
    snappy = tmp_path / "snappy.parquet"
    frame.to_parquet(snappy)
    assert path.stat().st_size < snappy.stat().st_size
    os.utime(path, (1_000_000_000, 1_000_000_000))
    pool_cache.load("abcdef")
    assert path.stat().st_mtime > time.time() - 60                                 # la lecture marque le fichier comme utilisé


# --------------------------------------------------------------------------- commandes

def test_bulk_maintenance_commands_refuse_to_run_beside_a_live_worker(tmp_path, monkeypatch):
    db = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db)
    conn = trackdb.connect(db)
    _seed(conn)
    jobs_db.write_heartbeat(conn, pid=os.getpid())
    conn.close()
    runner = CliRunner()
    for command in (["archive-predictions"], ["reindex"], ["analyze"], ["compress-caches"]):
        result = runner.invoke(storage_app, command)
        assert result.exit_code == 2 and "worker" in result.output, command
    conn = trackdb.connect(db)
    assert _count(conn, "test") == 8 * 6                                              # rien n'a bougé
    conn.close()


def test_the_archive_command_runs_when_no_worker_is_alive(tmp_path, monkeypatch):
    db = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db)
    monkeypatch.setenv("PATRICK_DATA_ROOT", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    conn = trackdb.connect(db)
    _seed(conn)
    conn.close()
    result = CliRunner().invoke(storage_app, ["archive-predictions", "--top-k", "1"])
    assert result.exit_code == 0 and "r1" in result.output
    conn = trackdb.connect(db)
    assert _count(conn, "test") == 1 * 6                                              # le meilleur (aussi le top-1)
    conn.close()
    report = CliRunner().invoke(storage_app, ["report"])
    assert report.exit_code == 0 and "prédictions" in report.output


def test_float32_mode_gives_the_same_values_on_a_miss_and_on_a_hit_and_halves_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_FEATURE_CACHE_ROOT", str(tmp_path))
    monkeypatch.setenv("PATRICK_FEATURE_CACHE", "1")
    rng = np.random.default_rng(1)
    raw = pd.DataFrame({"p": rng.normal(size=500)}, index=pd.bdate_range("2015-01-01", periods=500))
    pool = pd.DataFrame(rng.normal(size=(500, 40)), columns=[f"f{i}" for i in range(40)], index=raw.index)
    monkeypatch.setenv("PATRICK_FEATURE_CACHE_FLOAT32", "0")
    plain = pool_cache.cached("pool", raw, {"k": 1}, lambda: pool.copy())
    pd.testing.assert_frame_equal(plain, pool, check_freq=False)                      # mode normal : float64 exacts
    plain_size = pool_cache._path(pool_cache.cache_key("pool", raw, {"k": 1})).stat().st_size
    monkeypatch.setenv("PATRICK_FEATURE_CACHE_FLOAT32", "1")
    miss = pool_cache.cached("pool", raw, {"k": 1}, lambda: pool.copy())
    hit = pool_cache.cached("pool", raw, {"k": 1}, lambda: (_ for _ in ()).throw(AssertionError("recalculé")))
    pd.testing.assert_frame_equal(miss, hit, check_freq=False)                         # jamais de différence selon l'état du cache
    assert miss.dtypes.eq("float64").all() and not miss.equals(pool)
    assert np.allclose(miss.to_numpy(), pool.to_numpy(), rtol=1e-6)
    compact_size = pool_cache._path(pool_cache.cache_key("pool", raw, {"k": 1})).stat().st_size
    assert compact_size < plain_size * 0.65
    assert pool_cache.cache_key("pool", raw, {"k": 1}) != (monkeypatch.setenv("PATRICK_FEATURE_CACHE_FLOAT32", "0")
                                                          or pool_cache.cache_key("pool", raw, {"k": 1}))
