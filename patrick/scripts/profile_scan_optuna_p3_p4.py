"""P3/P4 profiling script -- run locally (real network + real cache), not in
a sandbox without access to yfinance.

Follows the P1/P2 finding (`profile_vol_models_p1_p2.py`): `vol_models`
parametric fitting (EGARCH/Kalman/HMM) only accounts for ~0.25% of a full
run's wall time (~150s out of the 58724.9s observed on `vix_direction.yaml`,
5 folds). This script decomposes the real bottleneck instead -- the scan
(`pipeline/engine.py:999-1057`) and Optuna tuning (`engine.py:1114-1156`)
blocks, which together drive ~10650 tree-ensemble fits + ~330 SHAP
selections on the full run, against 90 vol_models fits.

P3 (scan decomposition): measures `engine._select` (SHAP feature selection)
and `engine._fit_eval` (model fit + eval) SEPARATELY, on the real N_features
grid x algos grid, for ONE horizon and ONE fold -- a representative slice
(`config.selection.n_features_grid` x `config.models.algos` combinations,
e.g. 11 x 5 = 55 fits + 11 selections), not the full 6x5x11x5 = 1650-fit
scan (which would itself take a large fraction of the multi-hour run this
script exists to avoid).

P4 (Optuna decomposition): measures `tune_config`'s real per-trial cost by
running a REDUCED number of trials (`--optuna-trials`, default 15, not the
config's 100) on the config.tuning's last fold (matches production: Optuna
always tunes on `last_fold`, the largest expanding-window train set --
`engine.py:1142`), then re-opening the persisted Optuna study to read each
trial's `datetime_start`/`datetime_complete` (no modification to
`tune_config` itself -- pure post-hoc read of what it already persists via
`storage_path`/`study_name`).

Both blocks reuse the project's OWN `engine._select`/`engine._fit_eval`/
`tune_config` functions unmodified (light instrumentation, not a
reimplementation) -- so a divergence between this script's numbers and a
real run can only come from the reduced sample size, never from a different
code path.

Caveats (same spirit as P1/P2's extrapolation warning):
- The scan is measured on a SINGLE fold (`--fold`, default 0 like P1/P2).
  Expanding-window folds grow train size over time, so later folds are
  slower -- this is a LOWER-bound estimate for later folds, not a real
  per-fold-averaged total.
- The scan is measured on a SINGLE horizon (`--horizon`, default: the
  middle of `config.objective.horizons`, same choice `engine.py` itself
  makes for the interaction-discovery pilot fold). Different horizons
  reindex the same feature pool differently (different target/train size
  after `build_target`) but do not change the SHAP/fit cost order of
  magnitude -- treated here as representative, not identical.
- Optuna's per-trial cost is measured over `--optuna-trials` trials
  (10-20 recommended), not the real 100 -- `MedianPruner` is active in both
  cases, so pruned (shorter) trials are part of the real mix measured here
  too, not excluded.
- `_select`'s cache (`trackdb.get_cached_selection`, migration 0014) is a
  guaranteed MISS here: this script always connects to a FRESH temporary
  SQLite db (`--db-path` default: a new tempfile), never the run's real
  `patrick.db` -- every measurement is a real cold computation, matching
  the "cache froid" condition of P1/P2.

Confirms directly from the executed code path (`selection/shap_select.py:21`):
`shap.TreeExplainer(pilot)` is used for SHAP selection, NOT `KernelExplainer`
(TreeExplainer is exact and fast for tree ensembles; KernelExplainer is a
much slower model-agnostic approximation) -- this was flagged as
"never confirmed directly in the executed code" in an earlier diagnostic;
confirmed here by direct read of the call site actually exercised by
`engine._select` -> `select_features` -> `shap_rank`.

Usage (from the `patrick/` directory, with a working internet connection):
    python scripts/profile_scan_optuna_p3_p4.py
    python scripts/profile_scan_optuna_p3_p4.py --config configs/examples/vix_direction.yaml \\
        --fold 0 --horizon 5 --optuna-trials 20
"""
from __future__ import annotations

import argparse
import os
import tempfile
import time

import optuna
import pandas as pd

from patrick.config.schema import RunConfig
from patrick.data.ingest import ingest
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.pipeline import engine
from patrick.tracking import db as trackdb
from patrick.tuning.optuna_runner import tune_config
from patrick.validation.walkforward import build_fold_cuts, describe_folds

# Observed on the real `vix_direction.yaml` run this script exists to
# decompose (5 folds, full scan + Optuna) -- printed alongside this script's
# extrapolation for direct comparison, not used in any computation.
REFERENCE_FULL_RUN_SECONDS = 58724.9


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default="configs/examples/vix_direction.yaml")
    parser.add_argument("--fold", type=int, default=0,
                         help="Fold index (0-based) to profile the SCAN block on (default: 0, like P1/P2).")
    parser.add_argument("--horizon", type=int, default=None,
                         help="Horizon to profile the SCAN block on (default: the middle of "
                              "config.objective.horizons, same choice engine.py makes for the "
                              "interaction-discovery pilot).")
    parser.add_argument("--optuna-trials", type=int, default=15,
                         help="Number of REAL Optuna trials to run for the P4 per-trial measurement "
                              "(default 15; the real config asks for 100 -- this extrapolates).")
    parser.add_argument("--db-path", default=None,
                         help="Path to a FRESH SQLite db for this script's own measurements "
                              "(default: a new tempfile -- never the run's real patrick.db, so "
                              "_select's cache is always a real miss).")
    args = parser.parse_args()

    config = RunConfig.from_yaml(args.config)
    seed = config.output.seed
    target_col = clean_symbol(config.objective.target_symbol)
    horizon = args.horizon or config.objective.horizons[len(config.objective.horizons) // 2]
    regime = config.objective.regimes[0]

    db_path = args.db_path or os.path.join(tempfile.mkdtemp(prefix="patrick_profile_p3p4_"), "patrick.db")
    optuna_storage_path = os.path.join(os.path.dirname(db_path), "optuna.db")
    print(f"[P3/P4] Fresh measurement db: {db_path}")
    print(f"[P3/P4] Config: {args.config} -- horizon={horizon}d, fold={args.fold}, regime={regime}")

    print("[P3/P4] Ingesting (real network call, cache reused if already present in the "
          "default DataStore -- ingestion itself is not what's being measured here)...")
    t0 = time.perf_counter()
    raw = ingest(config.objective, config.universe, data_quality=config.data_quality)
    print(f"[P3/P4] Ingestion done in {time.perf_counter()-t0:.1f}s -- rows={len(raw)}, "
          f"columns={len(raw.columns)}")

    conn = trackdb.connect(db_path)
    snapshot_id, data_hash, n_tickers, n_fred, fred_src, quality_issues = engine._snapshot_context(raw)
    trackdb.upsert_snapshot(conn, snapshot_id, data_hash, n_tickers, n_fred, fred_src)
    trackdb.add_data_quality_issues(conn, snapshot_id, quality_issues)

    print("[P3/P4] Building the base pool (once, shared by all folds -- see P1/P2, cheap)...")
    t0 = time.perf_counter()
    base_pool = engine.build_base_feature_pool(raw, config, target_col)
    print(f"[P3/P4] Base pool: {base_pool.shape[1]} columns ({time.perf_counter()-t0:.1f}s)")

    n_wf = engine._walk_forward_span(raw.index, config.validation.holdout_months,
                                      config.validation.min_train_frac)
    all_dates = raw.index[:n_wf]
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds, config.validation.min_train_frac)
    describe_folds(all_dates, fold_cuts)

    print("[P3/P4] Building the fold pool (base+parametric+interactions -- see P1/P2, cheap; "
          "cached per fold, reused below)...")
    t0 = time.perf_counter()
    pool_builder = engine._FoldPoolBuilder(raw, config, target_col, base_pool, fold_cuts,
                                            conn=conn, snapshot_id=snapshot_id)
    feature_pool = [c for c in pool_builder.get(fold_cuts[0]).columns if c != target_col]
    print(f"[P3/P4] Full pool (fold 1): {len(feature_pool)} columns ({time.perf_counter()-t0:.1f}s)")

    ctx = engine._FoldContext(pool_builder, target_col, feature_pool, config, all_dates, fold_cuts)

    # ============================================================
    # P3 -- SCAN decomposition: engine._select (SHAP) vs engine._fit_eval
    # (model fit+eval), on the real N_features x algos grid, ONE horizon x
    # ONE fold (representative slice, not the full 6x5x11x5 scan).
    # ============================================================
    fd = ctx.prepare(horizon, args.fold, regime, want_baselines=False)
    if fd is None:
        raise SystemExit(f"Fold {args.fold} / horizon {horizon}d / regime {regime} excluded "
                          "(insufficient train/test rows) -- pick a different --fold/--horizon.")

    print(f"\n[P3] Scanning n_features_grid={config.selection.n_features_grid} x "
          f"algos={config.models.algos} x samplers={config.sampler.candidates} "
          f"on h={horizon}d fold={args.fold+1} (cold selection cache)...")

    select_times: list[float] = []
    fit_times: dict[str, list[float]] = {algo: [] for algo in config.models.algos}

    for n_feat in config.selection.n_features_grid:
        t0 = time.perf_counter()
        cols = engine._select(conn, target_col, horizon, snapshot_id, config, fd.X_tr, fd.y_tr, n_feat, seed)
        select_times.append(time.perf_counter() - t0)
        X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]

        for sampler_name in config.sampler.candidates:
            for algo in config.models.algos:
                t0 = time.perf_counter()
                engine._fit_eval(X_tr_n, fd.y_tr, X_te_n, fd.y_te, sampler_name, algo, seed,
                                  calibration=config.models.calibration,
                                  sample_weight=fd.sample_weight, ind_matrix=fd.ind_matrix,
                                  uniqueness_weights_enabled=config.sampling.uniqueness_weights)
                fit_times[algo].append(time.perf_counter() - t0)
        print(f"  [P3] N={n_feat}: selection + {len(config.models.algos)} fits done "
              f"[{sum(select_times):.0f}s selection, {sum(sum(v) for v in fit_times.values()):.0f}s fits so far]")

    n_feat_grid = len(config.selection.n_features_grid)
    n_samplers = len(config.sampler.candidates)
    n_algos = len(config.models.algos)

    rows = [{
        "step": "_select (SHAP, TreeExplainer)", "n_calls": n_feat_grid,
        "cumulative_seconds": sum(select_times),
        "avg_seconds_per_call": sum(select_times) / n_feat_grid,
    }]
    for algo, times in fit_times.items():
        rows.append({
            "step": f"_fit_eval[{algo}]", "n_calls": len(times),
            "cumulative_seconds": sum(times),
            "avg_seconds_per_call": sum(times) / len(times) if times else float("nan"),
        })
    p3_report = pd.DataFrame(rows)
    p3_total = p3_report["cumulative_seconds"].sum()
    p3_report["pct_of_scan_slice"] = 100 * p3_report["cumulative_seconds"] / p3_total
    pd.set_option("display.float_format", lambda v: f"{v:.3f}")
    print("\n=== P3 report: SHAP selection vs per-algo fit+eval, this slice "
          f"(h={horizon}d, fold={args.fold+1}, {n_feat_grid} N x {n_algos} algos x {n_samplers} sampler) ===")
    print(p3_report.to_string(index=False))

    n_horizons = len(config.objective.horizons)
    n_folds = config.validation.n_wf_folds
    n_regimes = len(config.objective.regimes)
    full_scan_multiplier = n_horizons * n_folds * n_regimes
    avg_select = sum(select_times) / n_feat_grid
    avg_fit_by_algo = {a: (sum(t) / len(t) if t else 0.0) for a, t in fit_times.items()}

    full_select_calls = full_scan_multiplier * n_feat_grid
    full_select_seconds = avg_select * full_select_calls
    full_fit_calls = full_scan_multiplier * n_feat_grid * n_samplers * n_algos
    full_fit_seconds = sum(avg_fit_by_algo.values()) * n_samplers * full_scan_multiplier * n_feat_grid

    print(f"\n[EXTRAPOLATION -- NOT a measurement] naive scale-up to the full scan "
          f"({n_horizons} horizons x {n_folds} folds x {n_regimes} regime(s) x {n_feat_grid} N x "
          f"{n_algos} algos x {n_samplers} sampler) -- ignores expanding-window fold growth "
          "(this slice's fold is likely smaller/faster than later folds) and cross-horizon "
          "differences (single-horizon slice):")
    print(f"  _select   : {full_select_calls} calls x {avg_select:.3f}s avg = {full_select_seconds:.1f}s "
          f"({full_select_seconds/3600:.2f}h)")
    print(f"  _fit_eval : {full_fit_calls} calls, {full_fit_seconds:.1f}s "
          f"({full_fit_seconds/3600:.2f}h) total across algos")
    p3_full_estimate = full_select_seconds + full_fit_seconds
    print(f"  SCAN total estimate: {p3_full_estimate:.1f}s ({p3_full_estimate/3600:.2f}h)")

    # ============================================================
    # P4 -- OPTUNA decomposition: real per-trial cost on a REDUCED trial
    # budget, on the LAST fold (matches production: engine.py:1142 always
    # tunes on `last_fold`, the largest expanding-window train set).
    # ============================================================
    last_fold = config.validation.n_wf_folds - 1
    fd_last = ctx.prepare(horizon, last_fold, regime, want_baselines=False)
    if fd_last is None:
        raise SystemExit(f"Last fold {last_fold} / horizon {horizon}d excluded -- cannot profile Optuna.")

    n_feat_optuna = config.selection.n_features_grid[len(config.selection.n_features_grid) // 2]
    algo_optuna = config.models.algos[0]
    sampler_optuna = config.sampler.candidates[0]
    print(f"\n[P4] Optuna: {args.optuna_trials} real trials (config asks for "
          f"{config.tuning.n_trials}) on h={horizon}d last_fold={last_fold+1}, "
          f"N={n_feat_optuna}, algo={algo_optuna}, sampler={sampler_optuna}, "
          f"cv_splits={config.tuning.cv_splits} (MedianPruner active, same as production)...")

    cols = engine._select(conn, target_col, horizon, snapshot_id, config,
                           fd_last.X_tr, fd_last.y_tr, n_feat_optuna, seed)
    X_tr_n = fd_last.X_tr[:, cols]

    study_name = f"profile_p4_{config.name}_h{horizon}_N{n_feat_optuna}_{algo_optuna}"
    t0 = time.perf_counter()
    best_params, best_cv = tune_config(X_tr_n, fd_last.y_tr, algo_optuna, sampler_optuna,
                                        n_trials=args.optuna_trials, cv_splits=config.tuning.cv_splits,
                                        seed=seed, storage_path=optuna_storage_path, study_name=study_name)
    wall = time.perf_counter() - t0
    print(f"[P4] {args.optuna_trials} trials in {wall:.1f}s -- best cv_F1_dir={best_cv:.4f}")

    study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{optuna_storage_path}")
    trial_durations = [
        (t.datetime_complete - t.datetime_start).total_seconds()
        for t in study.trials if t.datetime_start is not None and t.datetime_complete is not None
    ]
    n_pruned = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.PRUNED)
    avg_trial = sum(trial_durations) / len(trial_durations) if trial_durations else float("nan")

    p4_report = pd.DataFrame([{
        "step": f"Optuna trial [{algo_optuna}]", "n_calls": len(trial_durations),
        "n_pruned": n_pruned, "cumulative_seconds": sum(trial_durations),
        "avg_seconds_per_call": avg_trial,
    }])
    print(f"\n=== P4 report: per-trial cost ({algo_optuna}, N={n_feat_optuna}, cv_splits="
          f"{config.tuning.cv_splits}) ===")
    print(p4_report.to_string(index=False))

    n_configs_full = n_horizons * config.tuning.top_k if config.tuning.optuna_select_top_k_per_horizon \
        else config.tuning.top_k
    full_optuna_trials = n_configs_full * config.tuning.n_trials
    full_optuna_seconds = avg_trial * full_optuna_trials

    print(f"\n[EXTRAPOLATION -- NOT a measurement] naive scale-up to the full Optuna budget "
          f"({n_configs_full} configs [{'top_k=' + str(config.tuning.top_k) + ' per horizon x ' + str(n_horizons) + ' horizons' if config.tuning.optuna_select_top_k_per_horizon else 'top_k=' + str(config.tuning.top_k) + ' global'}] "
          f"x {config.tuning.n_trials} trials) -- assumes every config's average trial cost "
          f"matches this single (algo, N) measurement, which varies by algo/N/fold in reality:")
    print(f"  Optuna total estimate: {full_optuna_trials} trials x {avg_trial:.3f}s avg = "
          f"{full_optuna_seconds:.1f}s ({full_optuna_seconds/3600:.2f}h)")

    grand_total = p3_full_estimate + full_optuna_seconds
    print(f"\n=== GRAND TOTAL (scan + Optuna estimate) ===")
    print(f"  {grand_total:.1f}s ({grand_total/3600:.2f}h)")
    print(f"  Reference (real vix_direction.yaml run, 5 folds): "
          f"{REFERENCE_FULL_RUN_SECONDS:.1f}s ({REFERENCE_FULL_RUN_SECONDS/3600:.2f}h)")
    print(f"  Ratio estimate/reference: {grand_total/REFERENCE_FULL_RUN_SECONDS:.2f}x")


if __name__ == "__main__":
    main()
