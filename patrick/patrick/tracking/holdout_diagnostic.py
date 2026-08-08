"""Audit report (correction session), C4 -- READ-ONLY holdout diagnostic:
`fold_metric[split='holdout']` (Phase 2.1) is only populated for the
winning trial (`is_best=1`), never for the whole SCAN grid, making any
test/holdout rank correlation impossible (audit, section E: n=1, not
computable). `holdout_diagnostic` (migration 0004) stores the holdout score
of ALL trials in the grid in a SEPARATE table, to enable this diagnostic.

STRUCTURAL, NON-NEGOTIABLE CONSTRAINT: this module must NEVER be imported
by `patrick/selection/*`, `patrick/pipeline/leaderboard.py`, or
`patrick/tuning/*` -- the holdout must never influence a config choice,
only document it after the fact. Guaranteed by
`tests/test_holdout_diagnostic_isolation.py` (static inspection of these
modules' imports), not just by convention.
"""
from __future__ import annotations

import sqlite3

import numpy as np
from scipy import stats


def write_holdout_diagnostic(conn: sqlite3.Connection, trial_id: int, metrics: dict) -> None:
    rows = [(trial_id, name, float(value))
            for name, value in metrics.items() if value is not None and value == value]  # excludes NaN
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO holdout_diagnostic (trial_id, metric, value) VALUES (?, ?, ?)",
            rows,
        )


def read_holdout_diagnostic_for_run(conn: sqlite3.Connection, run_id: str,
                                     metric: str = "F1_dir") -> list[dict]:
    """READ ONLY, for reporting/diagnostics -- must never be called from
    selection/the leaderboard/tuning (see module docstring)."""
    rows = conn.execute(
        "SELECT hd.trial_id, hd.value FROM holdout_diagnostic hd "
        "JOIN trial t ON t.trial_id = hd.trial_id "
        "WHERE t.run_id = ? AND hd.metric = ?",
        (run_id, metric),
    ).fetchall()
    return [{"trial_id": r[0], "value": r[1]} for r in rows]


def spearman_test_vs_holdout(conn: sqlite3.Connection, run_id: str, metric: str = "F1_dir") -> dict:
    """Spearman rank correlation between this run's trial ranking on TEST
    (`fold_metric[split='test']` averaged per trial) and on HOLDOUT
    (`holdout_diagnostic`) -- a generalization diagnostic for the selection
    procedure (audit report, section E), displayed READ-ONLY (report),
    never used to choose a config."""
    test_rows = conn.execute(
        "SELECT trial_id, AVG(value) FROM fold_metric "
        "WHERE split = 'test' AND metric = ? AND trial_id IN "
        "(SELECT trial_id FROM trial WHERE run_id = ?) GROUP BY trial_id",
        (metric, run_id),
    ).fetchall()
    test_map = dict(test_rows)
    holdout_map = {r["trial_id"]: r["value"] for r in read_holdout_diagnostic_for_run(conn, run_id, metric)}

    common = sorted(set(test_map) & set(holdout_map))
    if len(common) < 3:
        return {"rho": float("nan"), "p_value": float("nan"), "n_trials": len(common)}

    test_vals = [test_map[t] for t in common]
    holdout_vals = [holdout_map[t] for t in common]
    rho, p = stats.spearmanr(test_vals, holdout_vals)
    rho = float(rho) if np.isfinite(rho) else float("nan")
    p = float(p) if np.isfinite(p) else float("nan")
    return {"rho": rho, "p_value": p, "n_trials": len(common)}
