"""Fusion de deux bases `patrick.db` disjointes (`sync_merge.merge_databases`) :
union de la recherche, identifiants d'essai décalés, patrimoine jamais touché.
Bases légères sous `tmp_path`, jamais la vraie."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from patrick import sync_merge
from patrick.tracking import db


def _seed(path: Path, runs: list[str], *, snapshot="snap_1", wealth: str | None = None,
          champion_at: str | None = None, job_status: str | None = None) -> None:
    """Chaque run a 2 essais (ids auto-incrémentés depuis 1 : ils collisionnent entre les deux PC),
    3 prédictions par essai, des métriques de fold et un diagnostic holdout."""
    conn = db.connect(str(path))
    db.upsert_snapshot(conn, snapshot, "hash_" + snapshot, 10, 5, "api")
    for run_id in runs:
        db.create_run(conn, run_id, f"T_{run_id}", 5, snapshot, json.dumps({"name": run_id}), "cfg", "sha", 42)
        for algo in ("lgbm", "xgb"):
            cur = conn.execute(
                "INSERT INTO trial (run_id, regime, algo, sampler, n_features, selector, params_json, is_best, "
                "artifact_path) VALUES (?, 'all', ?, 'tpe', 10, 'shap', '{}', ?, ?)",
                (run_id, algo, 1 if algo == "lgbm" else 0, f"/pc/{run_id}/{algo}.joblib"))
            tid = cur.lastrowid
            for i in range(3):
                conn.execute("INSERT INTO prediction (trial_id, ts, split, y_pred) VALUES (?, ?, 'test', ?)",
                             (tid, f"2026-01-0{i + 1}", float(i)))
            conn.execute("INSERT INTO fold_metric (trial_id, fold_index, split, metric, value) "
                         "VALUES (?, 0, 'test', 'F1_dir', 0.6)", (tid,))
            conn.execute("INSERT INTO holdout_diagnostic (trial_id, metric, value) VALUES (?, 'F1_dir', 0.55)", (tid,))
        conn.execute("INSERT INTO baseline_metric (run_id, baseline, split, metric, value) "
                     "VALUES (?, 'persistence', 'test', 'F1_dir', 0.5)", (run_id,))
        conn.execute("INSERT INTO trial_registry (recorded_at, target, horizon, source, run_id, n_trials, detail) "
                     "VALUES ('2026-10-01 00:00:00', ?, 5, 'scan', ?, 4, 'x')", (f"T_{run_id}", run_id))
    if champion_at and runs:
        tid = conn.execute("SELECT trial_id FROM trial WHERE run_id = ? AND is_best = 1", (runs[0],)).fetchone()[0]
        conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, promoted_at, reason) "
                     "VALUES ('SHARED_T', 5, ?, ?, ?, 'test')", (runs[0], tid, champion_at))
    if wealth:
        conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES (?, ?, 'PEA', 'real')",
                     (wealth, f"compte {wealth}"))
    if job_status:
        conn.execute("INSERT INTO job (job_id, config_json, status, worker_pid) VALUES ('j_remote', '{}', ?, 4242)",
                     (job_status,))
    conn.commit()
    conn.close()


def _q(path: Path, sql: str, *args):
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def _pair(tmp_path: Path, local_runs, remote_runs, **remote_kw):
    local, remote = tmp_path / "local.db", tmp_path / "remote.db"
    _seed(local, local_runs, snapshot="snap_local")
    _seed(remote, remote_runs, snapshot="snap_remote", **remote_kw)
    return local, remote


def test_disjoint_databases_are_united_with_shifted_trial_ids(tmp_path):
    local, remote = _pair(tmp_path, ["a1", "a2"], ["b1", "b2", "b3"])
    local_ids_before = _q(local, "SELECT run_id, trial_id FROM trial ORDER BY trial_id")

    report = sync_merge.merge_databases(str(local), str(remote))

    assert report["new_runs"] == 3 and report["local_only_runs"] == 2
    assert {r[0] for r in _q(local, "SELECT run_id FROM run")} == {"a1", "a2", "b1", "b2", "b3"}
    # Les essais locaux n'ont pas bougé, les importés sont décalés sans collision.
    assert _q(local, "SELECT run_id, trial_id FROM trial WHERE run_id IN ('a1','a2') ORDER BY trial_id") == local_ids_before
    ids = [r[0] for r in _q(local, "SELECT trial_id FROM trial")]
    assert len(ids) == len(set(ids)) == 10
    assert report["trial_offset"] == max(t for _, t in local_ids_before)
    # Tout ce qui renvoie à un essai l'a suivi.
    assert _q(local, "SELECT COUNT(*) FROM prediction")[0][0] == 10 * 3
    assert _q(local, "SELECT COUNT(*) FROM fold_metric")[0][0] == 10
    assert _q(local, "SELECT COUNT(*) FROM holdout_diagnostic")[0][0] == 10
    orphans = _q(local, "SELECT COUNT(*) FROM prediction p LEFT JOIN trial t USING (trial_id) WHERE t.trial_id IS NULL")
    assert orphans == [(0,)]
    # Un essai importé garde ses propres prédictions : b1/lgbm a bien 3 lignes, rattachées à b1.
    assert _q(local, "SELECT COUNT(*) FROM prediction p JOIN trial t USING (trial_id) "
                     "WHERE t.run_id = 'b1' AND t.algo = 'lgbm'") == [(3,)]
    assert _q(local, "SELECT COUNT(*) FROM baseline_metric")[0][0] == 5
    assert _q(local, "SELECT COUNT(*) FROM snapshot")[0][0] == 2


def test_merge_is_idempotent_and_never_touches_an_existing_run(tmp_path):
    local, remote = _pair(tmp_path, ["a1", "common"], ["common", "b1"])
    conn = sqlite3.connect(str(remote))
    conn.execute("UPDATE trial SET algo = 'CHANGED' WHERE run_id = 'common'")
    conn.commit()
    conn.close()

    first = sync_merge.merge_databases(str(local), str(remote))
    snapshot_of_db = _q(local, "SELECT * FROM trial ORDER BY trial_id")
    second = sync_merge.merge_databases(str(local), str(remote))

    assert first["new_runs"] == 1 and second["new_runs"] == 0
    assert _q(local, "SELECT * FROM trial ORDER BY trial_id") == snapshot_of_db
    assert _q(local, "SELECT COUNT(*) FROM trial WHERE algo = 'CHANGED'") == [(0,)]
    assert _q(local, "SELECT COUNT(*) FROM run")[0][0] == 3
    assert _q(local, "SELECT COUNT(*) FROM trial_registry")[0][0] == 3          # pas de doublon au 2e passage


def test_newest_champion_wins_and_follows_its_shifted_trial(tmp_path):
    local, remote = _pair(tmp_path, ["a1"], ["b1"], champion_at="2026-10-05 10:00:00")
    conn = sqlite3.connect(str(local))
    tid = conn.execute("SELECT trial_id FROM trial WHERE run_id = 'a1' AND is_best = 1").fetchone()[0]
    conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, promoted_at, reason) "
                 "VALUES ('SHARED_T', 5, 'a1', ?, '2026-10-01 10:00:00', 'old')", (tid,))
    conn.commit()
    conn.close()

    sync_merge.merge_databases(str(local), str(remote))

    ((run_id, trial_id, reason),) = _q(local, "SELECT run_id, trial_id, reason FROM champion WHERE target = 'SHARED_T'")
    assert (run_id, reason) == ("b1", "test")                                   # le plus récent (distant) gagne
    assert _q(local, "SELECT run_id FROM trial WHERE trial_id = ?", trial_id) == [("b1",)]


def test_older_remote_champion_does_not_replace_the_local_one(tmp_path):
    local, remote = _pair(tmp_path, ["a1"], ["b1"], champion_at="2026-09-01 10:00:00")
    conn = sqlite3.connect(str(local))
    tid = conn.execute("SELECT trial_id FROM trial WHERE run_id = 'a1' AND is_best = 1").fetchone()[0]
    conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, promoted_at, reason) "
                 "VALUES ('SHARED_T', 5, 'a1', ?, '2026-10-01 10:00:00', 'local')", (tid,))
    conn.commit()
    conn.close()

    sync_merge.merge_databases(str(local), str(remote))

    assert _q(local, "SELECT run_id, reason FROM champion WHERE target = 'SHARED_T'") == [("a1", "local")]


def test_personal_tables_are_neither_imported_nor_modified(tmp_path):
    local, remote = _pair(tmp_path, ["a1"], ["b1"], wealth="acc_remote")
    conn = sqlite3.connect(str(local))
    conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES ('acc_local', 'mien', 'CTO', 'real')")
    conn.commit()
    conn.close()

    sync_merge.merge_databases(str(local), str(remote))

    assert _q(local, "SELECT account_id FROM wealth_account") == [("acc_local",)]


def test_imported_jobs_are_never_resumable(tmp_path):
    local, remote = _pair(tmp_path, ["a1"], ["b1"], job_status="running")

    sync_merge.merge_databases(str(local), str(remote))

    assert _q(local, "SELECT status, worker_pid FROM job WHERE job_id = 'j_remote'") == [("error", None)]


def test_merging_into_an_empty_database_copies_everything(tmp_path):
    local, remote = tmp_path / "local.db", tmp_path / "remote.db"
    db.connect(str(local)).close()
    _seed(remote, ["b1", "b2"])

    report = sync_merge.merge_databases(str(local), str(remote))

    assert report["new_runs"] == 2 and report["trial_offset"] == 0
    assert _q(local, "SELECT COUNT(*) FROM prediction")[0][0] == 12


def test_a_failed_merge_writes_nothing(tmp_path, monkeypatch):
    local, remote = _pair(tmp_path, ["a1"], ["b1"])
    before = shutil.copyfile(local, tmp_path / "before.db")

    def boom(conn, off):
        raise RuntimeError("panne en cours de fusion")

    monkeypatch.setattr(sync_merge, "_merge_champions", boom)
    with pytest.raises(RuntimeError, match="panne"):
        sync_merge.merge_databases(str(local), str(remote))

    for table in ("run", "trial", "prediction", "snapshot"):
        assert _q(local, f"SELECT COUNT(*) FROM {table}") == _q(Path(before), f"SELECT COUNT(*) FROM {table}")


def test_different_schemas_are_refused(tmp_path):
    local, remote = _pair(tmp_path, ["a1"], ["b1"])
    conn = sqlite3.connect(str(remote))
    conn.execute("ALTER TABLE trial DROP COLUMN category")
    conn.commit()
    conn.close()

    with pytest.raises(sync_merge.MergeError, match="category"):
        sync_merge.merge_databases(str(local), str(remote))
    assert _q(local, "SELECT COUNT(*) FROM run")[0][0] == 1


def _add_wealth(path: Path, account_id: str, *, movements: int = 1, strategy: str | None = None) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES (?, ?, 'PEA', 'real')",
                 (account_id, f"compte {account_id}"))
    for i in range(movements):
        conn.execute("INSERT INTO wealth_movement (account_id, ts, kind, amount) VALUES (?, ?, 'deposit', ?)",
                     (account_id, f"2026-02-0{i + 1}", 100.0 + i))
    if strategy:
        conn.execute("INSERT INTO fund_strategy (strategy_id, name, wrapper, initial_capital, opened_on) "
                     "VALUES (?, 'ma strategie', 'PEA', 1000, '2026-01-01')", (strategy,))
    conn.commit()
    conn.close()


def test_adopt_personal_tables_replaces_wealth_and_funds_with_the_reference(tmp_path):
    local, remote = _pair(tmp_path, ["a1"], ["b1"])
    _add_wealth(local, "acc_local", movements=2, strategy="str_local")
    _add_wealth(remote, "acc_ref", movements=3, strategy="str_ref")

    counts = sync_merge.adopt_personal_tables(str(local), str(remote))

    assert counts["wealth_account"] == 1 and counts["wealth_movement"] == 3 and counts["fund_strategy"] == 1
    assert _q(local, "SELECT account_id FROM wealth_account") == [("acc_ref",)]
    assert _q(local, "SELECT COUNT(*) FROM wealth_movement WHERE account_id = 'acc_ref'") == [(3,)]
    assert _q(local, "SELECT strategy_id FROM fund_strategy") == [("str_ref",)]
    assert _q(local, "SELECT COUNT(*) FROM run") == [(1,)]                  # la recherche n'est pas touchée


def test_adopt_personal_tables_keeps_the_local_simulations(tmp_path):
    local, remote = _pair(tmp_path, ["a1"], ["b1"])
    tid = _q(local, "SELECT trial_id FROM trial LIMIT 1")[0][0]
    conn = sqlite3.connect(str(local))
    conn.execute("INSERT INTO simulation (simulation_id, trial_id, created_at, params_json) "
                 "VALUES ('sim_local', ?, '2026-01-01', '{}')", (tid,))
    conn.commit()
    conn.close()

    sync_merge.adopt_personal_tables(str(local), str(remote))

    assert _q(local, "SELECT simulation_id FROM simulation") == [("sim_local",)]


def test_adopt_personal_tables_is_atomic(tmp_path, monkeypatch):
    local, remote = _pair(tmp_path, ["a1"], ["b1"])
    _add_wealth(local, "acc_local")
    _add_wealth(remote, "acc_ref")

    real_insert = sync_merge._insert

    def failing(conn, table, **kw):
        if table == "wealth_movement":
            raise RuntimeError("panne")
        return real_insert(conn, table, **kw)

    monkeypatch.setattr(sync_merge, "_insert", failing)
    with pytest.raises(RuntimeError):
        sync_merge.adopt_personal_tables(str(local), str(remote))

    assert _q(local, "SELECT account_id FROM wealth_account") == [("acc_local",)]
    assert _q(local, "SELECT COUNT(*) FROM wealth_movement") == [(1,)]
