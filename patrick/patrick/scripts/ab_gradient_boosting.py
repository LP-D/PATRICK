"""A/B test: GradientBoosting in the scan grid — keep or remove?

P3 profiling shows GradientBoosting consumes 61% of scan time (5.298s/fit
vs 0.233s for LightGBM). This script runs the ACTUAL scan loop on the VIX
reference config and compares per-algo performance to determine if
GradientBoosting's predictive value justifies its time cost.

Experiment design:
  - Uses real engine code paths (_select, _fit_eval, _FoldContext)
  - Full N_features_grid [5-15], all 5 folds, 1 sampler (SMOTE)
  - Restricted to 1 horizon (h=5d, the VIX reference) for speed
  - Single run: all 5 algos evaluated on the same (fold, N, features)
  - No Optuna (scan-only comparison)

Reports:
  AB3a — Per-algo mean metrics (F1_dir, BalAcc_4cls, MCC_4cls)
  AB3b — Win rates: how often each algo is the best per (fold, N)
  AB3c — F1_dir loss if GradientBoosting is removed from the grid
  AB3d — Time savings estimate (extrapolated to full 6-horizon config)

Usage (user machine, needs network):
    cd patrick
    python -m patrick.scripts.ab_gradient_boosting

    # Or with a different horizon:
    python -m patrick.scripts.ab_gradient_boosting --horizon 10

    # Or query an existing database first (AB1):
    python -m patrick.scripts.ab_gradient_boosting --db-only ~/.patrick/patrick.db.backup-cleanup-20260809
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd


# ── AB1: query existing database ────────────────────────────────────────────

def ab1_query_db(db_path: str) -> bool:
    """Query an existing patrick.db for per-algo trial metrics.
    Returns True if enough data was found to draw conclusions."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT t.algo,
               COUNT(DISTINCT t.trial_id) AS n_trials,
               COUNT(fm.rowid) AS n_folds,
               ROUND(AVG(fm.value), 4) AS avg_f1_dir,
               ROUND(MAX(fm.value), 4) AS best_f1_dir,
               ROUND(MIN(fm.value), 4) AS worst_f1_dir
        FROM trial t
        JOIN fold_metric fm ON fm.trial_id = t.trial_id
        WHERE fm.metric = 'F1_dir' AND fm.split = 'test'
        GROUP BY t.algo
        ORDER BY avg_f1_dir DESC;
    """
    rows = conn.execute(sql).fetchall()
    conn.close()

    if not rows:
        print("[AB1] Aucune donnée trial/fold_metric trouvée dans la base.")
        return False

    print("\n" + "=" * 78)
    print("AB1 — EXISTING TRIAL DATA PER ALGO")
    print("=" * 78)
    print(f"{'Algo':<22s} {'Trials':>7s} {'Folds':>7s} "
          f"{'Avg F1_dir':>11s} {'Best':>7s} {'Worst':>7s}")
    print("-" * 78)
    for r in rows:
        print(f"{r['algo']:<22s} {r['n_trials']:>7d} {r['n_folds']:>7d} "
              f"{r['avg_f1_dir']:>11.4f} {r['best_f1_dir']:>7.4f} {r['worst_f1_dir']:>7.4f}")

    win_sql = """
        WITH ranked AS (
            SELECT t.algo, r.horizon, t.n_features, fm.fold_index,
                   fm.value AS f1_dir,
                   RANK() OVER (
                       PARTITION BY r.horizon, t.n_features, fm.fold_index
                       ORDER BY fm.value DESC
                   ) AS rnk
            FROM trial t
            JOIN run r ON r.run_id = t.run_id
            JOIN fold_metric fm ON fm.trial_id = t.trial_id
            WHERE fm.metric = 'F1_dir' AND fm.split = 'test'
        )
        SELECT algo, COUNT(*) AS wins
        FROM ranked WHERE rnk = 1
        GROUP BY algo
        ORDER BY wins DESC;
    """
    conn2 = sqlite3.connect(db_path)
    conn2.row_factory = sqlite3.Row
    win_rows = conn2.execute(win_sql).fetchall()
    conn2.close()

    if win_rows:
        total_wins = sum(r["wins"] for r in win_rows)
        print(f"\n{'Algo':<22s} {'Wins':>7s} {'Win%':>7s}")
        print("-" * 40)
        for r in win_rows:
            pct = 100.0 * r["wins"] / total_wins if total_wins else 0
            print(f"{r['algo']:<22s} {r['wins']:>7d} {pct:>6.1f}%")

    print("\n[AB1] Si ces résultats sont concluants, AB2 est inutile.")
    print("       Sinon, relancer sans --db-only pour l'expérience A/B complète.")
    return True


# ── AB2: live A/B experiment ────────────────────────────────────────────────

def ab2_run_experiment(horizon: int = 5):
    from sklearn.preprocessing import RobustScaler

    from patrick.config.schema import RunConfig
    from patrick.data.ingest import ingest
    from patrick.data.sources.yfinance_source import clean_symbol
    from patrick.data.store import DataStore
    from patrick.features.target import build_target
    from patrick.pipeline.engine import (
        _FoldContext,
        _FoldPoolBuilder,
        _finite_features,
        _finite_scaled,
        _select,
        _fit_eval,
        _walk_forward_span,
        build_base_feature_pool,
    )
    from patrick.validation.metrics import metrics as compute_metrics
    from patrick.validation.walkforward import build_fold_cuts

    config_path = Path(__file__).resolve().parents[2] / "configs" / "examples" / "vix_direction.yaml"
    config = RunConfig.from_yaml(str(config_path))
    seed = config.output.seed

    print(f"[AB2] Config: {config.name}")
    print(f"[AB2] Horizon: h={horizon}d (1 sur {len(config.objective.horizons)} du config)")
    print(f"[AB2] Algos: {config.models.algos}")
    print(f"[AB2] N_features_grid: {config.selection.n_features_grid}")
    print(f"[AB2] Folds: {config.validation.n_wf_folds}")
    print(f"[AB2] Sampler: {config.sampler.candidates}")
    n_combos = (config.validation.n_wf_folds
                * len(config.selection.n_features_grid)
                * len(config.sampler.candidates))
    print(f"[AB2] Total combos (fold × N × sampler): {n_combos}")
    print(f"[AB2] Total fits: {n_combos * len(config.models.algos)}")
    print()

    # ── Data ingestion + feature building ──
    t0 = time.time()
    print("[DATA] Ingestion...")
    store = DataStore()
    raw = ingest(config.objective, config.universe, store, force=False,
                 data_quality=config.data_quality)
    target_col = clean_symbol(config.objective.target_symbol)
    print(f"[DATA] {raw.shape[0]} rows × {raw.shape[1]} columns ({time.time()-t0:.1f}s)")

    print("[FEATURES] Building base pool...")
    base_pool = build_base_feature_pool(raw, config, target_col)
    print(f"[FEATURES] Base pool: {base_pool.shape[1]} columns ({time.time()-t0:.1f}s)")

    all_dates_full = raw.index
    n_wf = _walk_forward_span(all_dates_full, config.validation.holdout_months,
                               config.validation.min_train_frac)
    all_dates = all_dates_full[:n_wf]
    fold_cuts = build_fold_cuts(all_dates, config.validation.n_wf_folds,
                                 config.validation.min_train_frac)

    pool_builder = _FoldPoolBuilder(raw, config, target_col, base_pool, fold_cuts)
    feature_pool = [c for c in pool_builder.get(fold_cuts[0]).columns if c != target_col]
    print(f"[FEATURES] Full pool (fold 1): {len(feature_pool)} columns ({time.time()-t0:.1f}s)")

    ctx = _FoldContext(pool_builder, target_col, feature_pool, config, all_dates, fold_cuts)

    # ── Scan: all 5 algos, record per (fold, N, algo) ──
    print(f"\n[SCAN] Running h={horizon}d, {config.validation.n_wf_folds} folds × "
          f"{len(config.selection.n_features_grid)} N × "
          f"{len(config.sampler.candidates)} samplers × "
          f"{len(config.models.algos)} algos...")

    results: list[dict] = []
    algo_times: dict[str, list[float]] = defaultdict(list)

    for k in range(config.validation.n_wf_folds):
        for regime in config.objective.regimes:
            fd = ctx.prepare(horizon, k, regime, want_baselines=False)
            if fd is None:
                print(f"  fold{k+1} regime={regime}: skipped (insufficient data)")
                continue

            for n_feat in config.selection.n_features_grid:
                cols = _select(config, fd.X_tr, fd.y_tr, n_feat, seed)
                X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]

                for sampler_name in config.sampler.candidates:
                    for algo in config.models.algos:
                        t_algo = time.perf_counter()
                        met, y_pred, confidence = _fit_eval(
                            X_tr_n, fd.y_tr, X_te_n, fd.y_te,
                            sampler_name, algo, seed,
                            calibration=config.models.calibration,
                            sample_weight=fd.sample_weight,
                            ind_matrix=fd.ind_matrix,
                            uniqueness_weights_enabled=config.sampling.uniqueness_weights)
                        dt = time.perf_counter() - t_algo
                        algo_times[algo].append(dt)

                        results.append({
                            "fold": k + 1, "regime": regime,
                            "N": n_feat, "sampler": sampler_name,
                            "algo": algo, "time_s": dt, **met,
                        })

        print(f"  fold{k+1}: done ({time.time()-t0:.0f}s)")

    t_scan = time.time() - t0
    print(f"\n[SCAN] {len(results)} evaluations in {t_scan/60:.1f}min")

    # ── AB3: Analysis & Report ──
    df = pd.DataFrame(results)

    print("\n" + "=" * 90)
    print("AB3a — PER-ALGO MEAN METRICS (averaged over all fold × N × sampler combos)")
    print("=" * 90)
    agg = df.groupby("algo").agg(
        n_evals=("F1_dir", "count"),
        F1_dir_mean=("F1_dir", "mean"),
        F1_dir_std=("F1_dir", "std"),
        BalAcc_mean=("BalAcc_4cls", "mean"),
        MCC_mean=("MCC_4cls", "mean"),
        time_mean_s=("time_s", "mean"),
    ).sort_values("F1_dir_mean", ascending=False)

    print(f"{'Algo':<22s} {'Evals':>6s} {'F1_dir':>9s} {'±std':>7s} "
          f"{'BalAcc':>8s} {'MCC':>7s} {'t/fit(s)':>9s}")
    print("-" * 90)
    for algo, row in agg.iterrows():
        print(f"{algo:<22s} {int(row['n_evals']):>6d} "
              f"{row['F1_dir_mean']:>9.4f} {row['F1_dir_std']:>7.4f} "
              f"{row['BalAcc_mean']:>8.4f} {row['MCC_mean']:>7.4f} "
              f"{row['time_mean_s']:>9.3f}")

    # ── Win rates ──
    print("\n" + "=" * 90)
    print("AB3b — WIN RATES (best F1_dir per fold × N combo)")
    print("=" * 90)

    combo_keys = ["fold", "regime", "N", "sampler"]
    best_per_combo = df.loc[df.groupby(combo_keys)["F1_dir"].idxmax()]
    win_counts = best_per_combo["algo"].value_counts()
    total_combos = len(best_per_combo)

    print(f"{'Algo':<22s} {'Wins':>6s} {'Win%':>7s}")
    print("-" * 40)
    for algo in config.models.algos:
        w = win_counts.get(algo, 0)
        pct = 100.0 * w / total_combos if total_combos else 0
        print(f"{algo:<22s} {w:>6d} {pct:>6.1f}%")

    gb_wins = win_counts.get("GradientBoosting", 0)

    # ── F1_dir loss without GradientBoosting ──
    print("\n" + "=" * 90)
    print("AB3c — F1_dir LOSS IF GradientBoosting IS REMOVED")
    print("=" * 90)

    df_with = df.copy()
    df_without = df[df["algo"] != "GradientBoosting"].copy()

    best_with = df_with.loc[df_with.groupby(combo_keys)["F1_dir"].idxmax()]
    best_without = df_without.loc[df_without.groupby(combo_keys)["F1_dir"].idxmax()]

    merged = best_with[combo_keys + ["F1_dir"]].merge(
        best_without[combo_keys + ["F1_dir"]],
        on=combo_keys, suffixes=("_5algo", "_4algo"),
    )
    merged["delta"] = merged["F1_dir_4algo"] - merged["F1_dir_5algo"]

    mean_best_5 = merged["F1_dir_5algo"].mean()
    mean_best_4 = merged["F1_dir_4algo"].mean()
    mean_delta = merged["delta"].mean()
    n_loss = (merged["delta"] < -0.001).sum()
    n_same = ((merged["delta"] >= -0.001) & (merged["delta"] <= 0.001)).sum()
    n_gain = (merged["delta"] > 0.001).sum()

    print(f"  Mean best F1_dir (5 algos): {mean_best_5:.4f}")
    print(f"  Mean best F1_dir (4 algos): {mean_best_4:.4f}")
    print(f"  Mean delta (4 - 5):         {mean_delta:+.4f}")
    print(f"  Combos where 4-algo is worse (delta < -0.001): {n_loss}/{total_combos}")
    print(f"  Combos where 4-algo is same  (|delta| <= 0.001): {n_same}/{total_combos}")
    print(f"  Combos where 4-algo is better (delta > 0.001): {n_gain}/{total_combos}")

    # When GB wins, how much margin vs 2nd best?
    if gb_wins > 0:
        gb_margins = []
        for _, grp in df_with.groupby(combo_keys):
            grp_sorted = grp.sort_values("F1_dir", ascending=False)
            if grp_sorted.iloc[0]["algo"] == "GradientBoosting" and len(grp_sorted) > 1:
                margin = grp_sorted.iloc[0]["F1_dir"] - grp_sorted.iloc[1]["F1_dir"]
                gb_margins.append(margin)
        if gb_margins:
            print(f"\n  When GB wins ({len(gb_margins)} combos):")
            print(f"    Mean margin vs 2nd best: {np.mean(gb_margins):+.4f}")
            print(f"    Max margin:              {np.max(gb_margins):+.4f}")
            print(f"    Min margin:              {np.min(gb_margins):+.4f}")

    # ── Time savings ──
    print("\n" + "=" * 90)
    print("AB3d — TIME SAVINGS ESTIMATE")
    print("=" * 90)

    gb_time = sum(algo_times.get("GradientBoosting", []))
    total_time = sum(t for ts in algo_times.values() for t in ts)
    gb_frac = gb_time / total_time if total_time else 0

    print(f"  GradientBoosting total time this run: {gb_time:.1f}s "
          f"({gb_frac*100:.0f}% of scan)")
    print(f"  Other 4 algos total time:             {total_time - gb_time:.1f}s")

    n_horizons = len(config.objective.horizons)
    extrapolated_total = total_time * n_horizons
    extrapolated_savings = gb_time * n_horizons

    print(f"\n  Extrapolation to full {n_horizons}-horizon config:")
    print(f"    Scan time with 5 algos:    ~{extrapolated_total/60:.0f}min")
    print(f"    Scan time with 4 algos:    ~{(extrapolated_total - extrapolated_savings)/60:.0f}min")
    print(f"    Time saved:                ~{extrapolated_savings/60:.0f}min ({gb_frac*100:.0f}%)")

    # ── Verdict ──
    print("\n" + "=" * 90)
    print("AB3 — VERDICT")
    print("=" * 90)

    gb_avg = agg.loc["GradientBoosting", "F1_dir_mean"] if "GradientBoosting" in agg.index else 0
    gb_rank = list(agg.index).index("GradientBoosting") + 1 if "GradientBoosting" in agg.index else 0
    gb_win_pct = 100.0 * gb_wins / total_combos if total_combos else 0

    if gb_win_pct < 5 and abs(mean_delta) < 0.005:
        verdict = "REMOVE"
        reason = (f"GradientBoosting wins {gb_win_pct:.1f}% of combos, "
                  f"F1_dir loss is {mean_delta:+.4f} (negligible), "
                  f"saves {gb_frac*100:.0f}% of scan time.")
    elif gb_win_pct < 15 and abs(mean_delta) < 0.01:
        verdict = "MAKE OPTIONAL (disabled by default)"
        reason = (f"GradientBoosting wins {gb_win_pct:.1f}% of combos, "
                  f"F1_dir loss is {mean_delta:+.4f} (marginal), "
                  f"saves {gb_frac*100:.0f}% of scan time.")
    else:
        verdict = "KEEP"
        reason = (f"GradientBoosting wins {gb_win_pct:.1f}% of combos "
                  f"with a non-negligible F1_dir loss of {mean_delta:+.4f}.")

    print(f"  Recommendation: {verdict}")
    print(f"  Rationale: {reason}")
    print(f"  GB mean F1_dir: {gb_avg:.4f} (rank {gb_rank}/{len(agg)})")
    print(f"  GB win rate: {gb_wins}/{total_combos} ({gb_win_pct:.1f}%)")
    print(f"  F1_dir delta without GB: {mean_delta:+.4f}")
    print(f"  Time cost: {gb_frac*100:.0f}% of scan")

    return verdict


def main():
    parser = argparse.ArgumentParser(
        description="A/B test: GradientBoosting in the scan grid")
    parser.add_argument("--db-only", type=str, default=None,
                        help="AB1: query an existing patrick.db instead of running the experiment")
    parser.add_argument("--horizon", type=int, default=5,
                        help="Horizon to test (default: 5)")
    args = parser.parse_args()

    if args.db_only:
        path = Path(args.db_only).expanduser()
        if not path.exists():
            print(f"[ERREUR] Base introuvable: {path}")
            sys.exit(1)
        ab1_query_db(str(path))
    else:
        ab2_run_experiment(horizon=args.horizon)


if __name__ == "__main__":
    main()
