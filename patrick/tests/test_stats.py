"""Requêtes de validité statistique sur la base (Phase 2.2/2.4) —
patrick.tracking.stats."""
from __future__ import annotations

import numpy as np

from patrick.tracking import db
from patrick.tracking import stats as trackstats


def _make_run_with_trials(conn, run_id: str, target: str, horizon: int, n_trials: int) -> list[int]:
    db.upsert_snapshot(conn, f"snap_{run_id}", f"hash_{run_id}", None, None, None)
    db.create_run(conn, run_id, target, horizon, f"snap_{run_id}", "{}", "cfg", "sha", 42)
    return [db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
            for _ in range(n_trials)]


def test_count_cumulative_trials_sums_across_runs(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run_with_trials(conn, "run1", "^VIX", 5, 3)
    _make_run_with_trials(conn, "run2", "^VIX", 5, 4)
    _make_run_with_trials(conn, "run3", "^VIX", 10, 2)  # autre horizon
    _make_run_with_trials(conn, "run4", "AAPL", 5, 5)  # autre cible

    assert trackstats.count_cumulative_trials(conn, "^VIX", horizon=5) == 7
    assert trackstats.count_cumulative_trials(conn, "^VIX") == 9  # tous horizons
    assert trackstats.count_cumulative_trials(conn, "AAPL", horizon=5) == 5
    assert trackstats.count_cumulative_trials(conn, "NONEXISTENT") == 0
    conn.close()


def test_pbo_for_target_empty_history_returns_nan(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    out = trackstats.pbo_for_target(conn, "^VIX", 5, "GLOBAL")
    assert np.isnan(out["pbo"])
    assert out["n_trials"] == 0
    conn.close()


def test_pbo_for_target_builds_matrix_from_fold_metrics(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    trial_ids = _make_run_with_trials(conn, "run1", "^VIX", 5, 6)
    rng = np.random.default_rng(0)
    for tid in trial_ids:
        for fold in range(1, 9):  # 8 folds -> pair, pas de recadrage nécessaire
            db.add_fold_metrics(conn, tid, fold, "test", {"F1_dir": float(rng.normal(0.5, 0.05))})

    out = trackstats.pbo_for_target(conn, "^VIX", 5, "GLOBAL")
    assert out["n_trials"] == 6
    assert out["n_blocks"] == 8
    assert not np.isnan(out["pbo"])
    conn.close()


def test_pbo_for_target_excludes_trials_with_incomplete_folds(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    trial_ids = _make_run_with_trials(conn, "run1", "^VIX", 5, 3)
    for fold in range(1, 5):
        db.add_fold_metrics(conn, trial_ids[0], fold, "test", {"F1_dir": 0.5})
        db.add_fold_metrics(conn, trial_ids[1], fold, "test", {"F1_dir": 0.5})
    # trial_ids[2] n'a qu'un seul fold -> exclu de la matrice (pivot dropna)
    db.add_fold_metrics(conn, trial_ids[2], 1, "test", {"F1_dir": 0.5})

    out = trackstats.pbo_for_target(conn, "^VIX", 5, "GLOBAL")
    assert out["n_trials"] == 2
    conn.close()
