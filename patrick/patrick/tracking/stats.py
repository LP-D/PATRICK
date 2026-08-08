"""Statistical validity queries (Phase 2) on the `patrick.db` database —
bridge between `patrick.validation`'s pure functions (dsr/pbo/diebold_mariano,
which know nothing about SQLite) and the persisted run history (Phase 1).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from patrick.validation.fdr import benjamini_hochberg
from patrick.validation.pbo import compute_pbo
from patrick.validation.pbo_reliability import pbo_reliability


def count_cumulative_trials(conn: sqlite3.Connection, target: str, horizon: int | None = None) -> int:
    """Total number of trials (`trial`) run for this target, across the whole
    run history — not just the current run (Phase 2.2). It is this number,
    not a single run's, that must correct a Sharpe/PBO: searching for the
    best config across 50 successive runs amounts to having tried far more
    than a single isolated run would suggest."""
    if horizon is not None:
        row = conn.execute(
            "SELECT COUNT(*) FROM trial JOIN run ON trial.run_id = run.run_id "
            "WHERE run.target = ? AND run.horizon = ?",
            (target, horizon),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM trial JOIN run ON trial.run_id = run.run_id "
            "WHERE run.target = ?",
            (target,),
        ).fetchone()
    return int(row[0]) if row else 0


def pbo_for_target(conn: sqlite3.Connection, target: str, horizon: int, regime: str,
                    metric: str = "F1_dir") -> dict:
    """PBO (see `validation.pbo.compute_pbo`) over all historical trials of a
    given (target, horizon, regime) — not just the current run's: the longer
    the run history, the more significant the estimate. Trials with
    incomplete folds (crash, fold too short) are excluded from the matrix
    rather than force-filled, to avoid skewing the per-block IS/OOS
    averages."""
    rows = conn.execute(
        "SELECT trial.trial_id, fold_metric.fold_index, fold_metric.value "
        "FROM trial "
        "JOIN run ON trial.run_id = run.run_id "
        "JOIN fold_metric ON fold_metric.trial_id = trial.trial_id "
        "WHERE run.target = ? AND run.horizon = ? AND trial.regime = ? "
        "AND fold_metric.split = 'test' AND fold_metric.metric = ?",
        (target, horizon, regime, metric),
    ).fetchall()
    if not rows:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": 0, "n_blocks": 0, "mean_logit": np.nan}

    df = pd.DataFrame(rows, columns=["trial_id", "fold_index", "value"])
    pivot = df.pivot_table(index="trial_id", columns="fold_index", values="value").dropna()
    if pivot.empty:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": 0, "n_blocks": 0, "mean_logit": np.nan,
                "reliability": pbo_reliability(np.empty((0, 0)))}
    result = compute_pbo(pivot.values)
    # Correction report, C5 -- reliability diagnostic computed separately
    # (see `validation/pbo_reliability.py`, imports/does not modify
    # `compute_pbo`): bootstrap confidence interval + explicit refusal below
    # a minimum block count -- a single isolated PBO point is not
    # interpretable on its own (see audit report, section E).
    result["reliability"] = pbo_reliability(pivot.values)
    return result


def pbo_for_target_cpcv(conn: sqlite3.Connection, target: str, horizon: int, regime: str,
                         metric: str = "F1_dir") -> dict:
    """Phase 6.1 (P6.1) -- PBO wired to CPCV backtest PATHS
    (`validation/cpcv.py::path_assignment`) rather than walk-forward blocks
    -- this component's main reason for existing: with `n_groups=7`/
    `k_test_groups=2` by default, 6 paths are ALWAYS available per (target,
    horizon, regime) as soon as a single CPCV run has run, versus
    potentially fewer than `MIN_BLOCKS` walk-forward blocks (guard C5) on a
    still-short run history. Same mechanism as `pbo_for_target`
    (`compute_pbo` unmodified, see C5), just a different source:
    `split='test_path'` (fold_index=path), written by
    `pipeline/engine.py::_run_cpcv_scan`, never mixed with the per-
    combination metrics (`split='test'`, fold_index=combination)."""
    rows = conn.execute(
        "SELECT trial.trial_id, fold_metric.fold_index, fold_metric.value "
        "FROM trial "
        "JOIN run ON trial.run_id = run.run_id "
        "JOIN fold_metric ON fold_metric.trial_id = trial.trial_id "
        "WHERE run.target = ? AND run.horizon = ? AND trial.regime = ? "
        "AND fold_metric.split = 'test_path' AND fold_metric.metric = ?",
        (target, horizon, regime, metric),
    ).fetchall()
    if not rows:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": 0, "n_blocks": 0, "mean_logit": np.nan,
                "reliability": pbo_reliability(np.empty((0, 0)))}

    df = pd.DataFrame(rows, columns=["trial_id", "fold_index", "value"])
    pivot = df.pivot_table(index="trial_id", columns="fold_index", values="value").dropna()
    if pivot.empty:
        return {"pbo": np.nan, "n_combinations": 0, "n_trials": 0, "n_blocks": 0, "mean_logit": np.nan,
                "reliability": pbo_reliability(np.empty((0, 0)))}
    result = compute_pbo(pivot.values)
    result["reliability"] = pbo_reliability(pivot.values)
    return result


def fdr_across_targets(conn: sqlite3.Connection, alpha: float = 0.10,
                        kind: str = "class_specific") -> dict:
    """Phase 6.4 (P6.4) -- FDR correction (Benjamini-Hochberg) across ALL
    targets that have a Diebold-Mariano result in the run history
    (`dm_result`, migration 0009): for each target, the BEST (smallest) DM
    p-value obtained across any of its runs is kept -- trying several
    targets and keeping only the best raises the same multiple-testing
    problem as trying several configs on a single target (section 4,
    METHODOLOGY.md), this time at the target level. `compute_pbo`/
    `benjamini_hochberg` themselves are never modified here (same discipline
    as C5/P6.1) -- only the source query changes.

    `kind` (Phase X5, migration 0010): filters on `"class_specific"`
    (default -- each target's own asset-class-specific comparison, the MAIN
    result) or `"common"` (class-agnostic persistence, a secondary
    comparison allowing classes to be checked against each other on an equal
    footing) -- never both mixed into the same MIN, which would pit two
    comparisons of a different nature against each other for the same
    target."""
    rows = conn.execute(
        "SELECT run.target, MIN(dm_result.p_value) FROM dm_result "
        "JOIN run ON dm_result.run_id = run.run_id "
        "WHERE dm_result.kind = ? "
        "GROUP BY run.target",
        (kind,),
    ).fetchall()
    p_values = {target: p for target, p in rows}
    return benjamini_hochberg(p_values, alpha=alpha)
