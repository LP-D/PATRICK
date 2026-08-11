"""P1/P2 profiling script -- run locally (real network + real cache), not in
a sandbox without access to yfinance.

P1: per-model cumulative time / call count / avg time / % of total, measured
on `build_parametric_pool` for one real walk-forward fold (cold cache) of the
`^VIX` run (`configs/examples/vix_direction.yaml` by default).

P2: exact number of raw columns (tickers) feeding
`build_vol_model_features_parametric` for this run, AFTER the data-quality
gates (not the theoretical universe) -- read directly off `ingest()`'s
output -- plus the number of walk-forward folds (from `validation.n_wf_folds`
in the config), which is the second factor of the real fit count.

Usage (from the `patrick/` directory, with a working internet connection):
    python scripts/profile_vol_models_p1_p2.py
    python scripts/profile_vol_models_p1_p2.py --folds all   # all 5 folds, real (not extrapolated)
    python scripts/profile_vol_models_p1_p2.py --config configs/examples/vix_direction.yaml --folds 0

Cache: always bypassed (`conn=None`) so every model call is a real cold
computation, matching the "cache froid" condition this profiling targets --
even if `~/.patrick` already holds cached ingest data or vol-model results
from a prior run.
"""
from __future__ import annotations

import argparse
import time

import pandas as pd

from patrick.config.schema import RunConfig
from patrick.data import ingest as ingest_module
from patrick.features import vol_models
from patrick.validation.walkforward import build_fold_cuts, describe_folds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/examples/vix_direction.yaml")
    parser.add_argument("--folds", default="0",
                         help="Fold index (0-based) to profile, or 'all' for every fold (real, no extrapolation).")
    args = parser.parse_args()

    config = RunConfig.from_yaml(args.config)

    print(f"[P2] Ingesting '{config.objective.target_symbol}' + universe "
          f"({len(config.universe.yf_tickers)} yfinance + {len(config.universe.fred_series)} FRED "
          f"requested) -- real network call, no cache reuse for this measurement.")
    t_ingest0 = time.perf_counter()
    raw = ingest_module.ingest(config.objective, config.universe, force=True,
                                data_quality=config.data_quality)
    t_ingest = time.perf_counter() - t_ingest0

    n_requested = len(config.universe.yf_tickers) + len(config.universe.fred_series) + 1  # +1 target
    n_effective = len(raw.columns)
    print(f"[P2] Ingestion done in {t_ingest:.1f}s -- rows={len(raw)}, "
          f"requested={n_requested} (target+universe), effective raw.columns AFTER data-quality gates={n_effective}")
    print(f"[P2] Effective columns: {list(raw.columns)}")

    fold_cuts = build_fold_cuts(raw.index, config.validation.n_wf_folds, config.validation.min_train_frac)
    print(f"[P2] n_wf_folds (config) = {config.validation.n_wf_folds}")
    describe_folds(raw.index, fold_cuts)
    print(f"[P2] Total real vol-model fits for the FULL run (cold cache) = "
          f"{n_effective} columns x {config.validation.n_wf_folds} folds x "
          f"{len(vol_models.PARAMETRIC_VOL_MODELS)} models = "
          f"{n_effective * config.validation.n_wf_folds * len(vol_models.PARAMETRIC_VOL_MODELS)}")

    if args.folds == "all":
        fold_indices = list(range(config.validation.n_wf_folds))
    else:
        fold_indices = [int(args.folds)]

    vol_models.enable_profiling(True)
    vol_models.reset_profile()

    for k in fold_indices:
        fit_end_idx = fold_cuts[k]
        test_end_idx = fold_cuts[k + 1] if k + 1 < len(fold_cuts) else None
        print(f"\n[P1] Profiling fold {k+1}/{config.validation.n_wf_folds} "
              f"(fit_end_idx={fit_end_idx}, train rows={fit_end_idx}) -- cold cache, conn=None ...")
        t0 = time.perf_counter()
        for col in raw.columns:
            vol_models.build_vol_model_features_parametric(
                raw[col], prefix=col, fit_end_idx=fit_end_idx, test_end_idx=test_end_idx,
                conn=None, snapshot_id=None)
        elapsed = time.perf_counter() - t0
        print(f"[P1] Fold {k+1} wall time: {elapsed:.1f}s")

    report = vol_models.profile_report()
    pd.set_option("display.float_format", lambda v: f"{v:.3f}")
    print("\n=== P1 report: per-model cumulative time across the fold(s) profiled above ===")
    print(report.to_string(index=False))

    n_folds_profiled = len(fold_indices)
    if n_folds_profiled < config.validation.n_wf_folds:
        factor = config.validation.n_wf_folds / n_folds_profiled
        print(f"\n[EXTRAPOLATION -- NOT a measurement] naive x{factor:.2f} scale-up to "
              f"{config.validation.n_wf_folds} folds (expanding-window folds grow in size, so later "
              "folds are slower than this one -- this is a lower-bound estimate, not a real total):")
        extrapolated = report.copy()
        extrapolated["cumulative_seconds_extrapolated"] = extrapolated["cumulative_seconds"] * factor
        print(extrapolated[["model", "cumulative_seconds", "cumulative_seconds_extrapolated"]].to_string(index=False))


if __name__ == "__main__":
    main()
