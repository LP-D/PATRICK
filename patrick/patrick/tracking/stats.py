"""Statistical validity queries (Phase 2) on the `patrick.db` database —
bridge between `patrick.validation`'s pure functions (dsr/pbo/diebold_mariano,
which know nothing about SQLite) and the persisted run history (Phase 1).
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd

from patrick.config.defaults import DESCRIPTIVE_HORIZONS
from patrick.numeric import is_nan
from patrick.validation.fdr import benjamini_hochberg
from patrick.validation.pbo import compute_pbo
from patrick.validation.pbo_reliability import pbo_reliability


def count_registered_trials(conn: sqlite3.Connection, target: str, horizon: int | None = None) -> int:
    """F03 -- total number of configurations ever evaluated for `target`
    (optionally one horizon), read from the append-only `trial_registry`
    (migration 0021): scan trials, EVERY Optuna trial, simulations, model
    categories -- across the whole run history, deleted runs included."""
    if horizon is not None:
        row = conn.execute(
            "SELECT COALESCE(SUM(n_trials), 0) FROM trial_registry WHERE target = ? AND horizon = ?",
            (target, horizon),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(SUM(n_trials), 0) FROM trial_registry WHERE target = ?", (target,),
        ).fetchone()
    return int(row[0]) if row else 0


def count_cumulative_trials(conn: sqlite3.Connection, target: str, horizon: int | None = None) -> int:
    """Total number of trials run for this target, across the whole run
    history — not just the current run (Phase 2.2). It is this number, not a
    single run's, that must correct a Sharpe/PBO: searching for the best
    config across 50 successive runs amounts to having tried far more than a
    single isolated run would suggest.

    F03: counted from `trial_registry` (see `count_registered_trials`), no
    longer from `trial JOIN run` -- which counted a 100-trial Optuna tuning
    as 1 and lost every trial of a deleted run (ON DELETE CASCADE)."""
    return count_registered_trials(conn, target, horizon)


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
    targets tested in the run history. Trying several targets and keeping
    the significant one raises the same multiple-testing problem as trying
    several configs on one target (section 4, METHODOLOGY.md), at the target
    level. `benjamini_hochberg` itself is unchanged -- only the family and
    the per-target p-value are built here.

    Family (F05): every target with at least one COMPLETED run (`status =
    'done'`, archived runs included -- archiving hides a run, it does not
    un-test it), whatever the validation scheme. A target without a
    Diebold-Mariano p-value (CPCV-only: DM is not computed in that scheme;
    or a walk-forward run whose DM was not computable) enters with p = 1:
    never significant, but counted in m. The family used to be built from
    `dm_result` alone, so CPCV-only targets silently shrank m and loosened
    every other target's threshold.

    Per-target p-value (F05b): Sidak-adjusted minimum over the target's k
    runs, 1 - (1 - p_min)^k -- the minimum of k p-values is not uniform
    under H0; picking it raw rewarded re-running a target until one run
    came out significant. `best_run_p_value` keeps the raw minimum for
    display.

    `kind` (Phase X5, migration 0010): `"class_specific"` (default -- each
    target's own asset-class-specific comparison, the MAIN result) or
    `"common"` (class-agnostic persistence) -- never both mixed.

    Sample (F08, migration 0022): only DM results computed on the terminal
    holdout count. A p-value computed on the last walk-forward fold -- data
    that took part in selecting the model -- is biased towards
    significance: such a target enters untestable (p = 1) and is flagged
    `selection_biased` (every row written before F08 is in that case).

    Descriptive horizons (decision of 2026-09-26, `D.DESCRIPTIVE_HORIZONS`
    = 504/756 days): their runs are outside the family altogether -- a
    target only ever run at those horizons is not "tested", and their
    p-values never enter a target's minimum. Counted in `n_descriptive_runs`.

    Returned counts: `n_tested` = family size m, `n_with_p_value`,
    `n_untestable` (= m - n_with_p_value), `n_selection_biased`,
    `n_descriptive_runs`."""
    descriptive = sorted(DESCRIPTIVE_HORIZONS)
    not_descriptive = f"run.horizon NOT IN ({','.join('?' for _ in descriptive)})"
    family = [t for (t,) in conn.execute(
        f"SELECT DISTINCT target FROM run WHERE status = 'done' AND {not_descriptive} ORDER BY target",
        descriptive)]
    rows = conn.execute(
        "SELECT run.target, MIN(dm_result.p_value), COUNT(dm_result.p_value) FROM dm_result "
        "JOIN run ON dm_result.run_id = run.run_id "
        "WHERE dm_result.kind = ? AND dm_result.p_value IS NOT NULL AND run.status = 'done' "
        f"AND dm_result.sample = 'holdout' AND {not_descriptive} "
        "GROUP BY run.target",
        (kind, *descriptive),
    ).fetchall()
    observed = {target: (float(p_min), int(k)) for target, p_min, k in rows if not is_nan(p_min)}
    biased = {t for (t,) in conn.execute(
        "SELECT DISTINCT run.target FROM dm_result JOIN run ON dm_result.run_id = run.run_id "
        f"WHERE dm_result.kind = ? AND dm_result.sample = 'last_wf_fold' AND run.status = 'done' "
        f"AND {not_descriptive}",
        (kind, *descriptive))} - set(observed)
    n_descriptive_runs = conn.execute(
        f"SELECT COUNT(*) FROM run WHERE status = 'done' AND NOT ({not_descriptive})", descriptive).fetchone()[0]

    p_values: dict[str, float] = {}
    for target in family:
        if target in observed:
            p_min, k = observed[target]
            p_values[target] = p_min if k == 1 else float(-np.expm1(k * np.log1p(-p_min)))
        else:
            p_values[target] = 1.0

    result = benjamini_hochberg(p_values, alpha=alpha)
    for target, r in result["results"].items():
        p_min, k = observed.get(target, (None, 0))
        untestable = target not in observed
        r["untestable"] = untestable
        r["selection_biased"] = target in biased
        r["best_run_p_value"] = p_min
        r["n_runs_with_p_value"] = k
        if untestable:
            r["significant"] = False
    result["n_with_p_value"] = len(observed)
    result["n_untestable"] = result["n_tested"] - len(observed)
    result["n_selection_biased"] = len(biased & set(family))
    result["n_bh_significant"] = sum(1 for r in result["results"].values() if r["significant"])
    result["n_descriptive_runs"] = int(n_descriptive_runs)
    return result
