"""Wires the 3 model categories (CHANTIER B, feature/model-categories-
comparison) into REAL per-fold training -- follow-up to
`tracking/model_categories.py` (the statistical comparison layer, delivered
first with simulated candidates; this module produces the real ones).

- "global": the EXISTING grid scan's own winning config for this horizon,
  read directly from its already-computed `Leaderboard` rows
  (`extract_global_category_result`) -- no retraining, and
  `pipeline/engine.py`'s scan loop is NOT modified by this chantier: a run
  with this phase disabled is bit-identical to before this chantier existed.
- "per_regime": CHANTIER A's causal HMM regime label
  (`features/regime_detection.py::detect_regime`), detected INSIDE each
  walk-forward fold with `fit_end_idx` set to THAT fold's own train/test cut
  -- never a single regime detection computed once upfront for the whole
  series. The fragmentation guardrail (`check_regime_fragmentation`, hard
  block) runs per fold, on that fold's own regime-labeled rows. EACH regime
  label runs its OWN full grid scan (n_features x sampler x algo) across the
  folds where it is present, then its own full-budget Optuna tuning
  (`_scan_and_tune`) -- independent of global's winning config, never
  reused from it (revision: an earlier version forced per_regime to reuse
  global's winning config and halved the Optuna budget; both reverted --
  see git history -- there is no shared-cost notion between categories: the
  user only ever runs one category at a time, so "global"'s own choices
  have no bearing on what's optimal for a REGIME-FILTERED subset of the
  data, which can genuinely favor a different N/sampler/algo).
- "stacking": strict out-of-fold within each fold's own TRAIN portion only
  -- an internal TEMPORAL split (never K-fold-random, see `_oof_split`),
  base algorithms fit on the earlier slice, meta-model trained ONLY on their
  predictions on the later (out-of-fold) slice. Base algorithms are then
  refit on the fold's FULL train for the real test-set inference (standard
  stacking practice) -- the anti-leakage guarantee is about the META-MODEL's
  training data, not about the final test-time base-model fit/predict step
  (which is the same train->test boundary every other category already
  respects). The stack's OWN (n_features, sampler) is grid-scanned on the
  OOF meta-accuracy (independent of global), and each base algo is then
  Optuna-tuned at full budget on the OOF-training portion.

Deliberately ADDITIVE and reuses `pipeline.engine`'s existing per-fold
primitives (`_FoldContext`, `_fit_eval`, `_select`) as building blocks
rather than re-implementing fold/purge/embargo/scaling logic a second time.
`tune_config`/Optuna storage reuses the exact same mechanism `run_pipeline`
itself uses (`tuning/optuna_runner.py`, one SQLite study file per config,
resumable) -- study names are namespaced with the category (and regime
label, for per_regime) so they never collide with `run_pipeline`'s own
"global" studies for the same (horizon, N, sampler, algo).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from patrick.features.regime_detection import (
    REGIME_LABELS,
    check_regime_fragmentation,
    detect_regime,
)
from patrick.pipeline.engine import _config_hash, _fit_eval, _select, _FoldContext
from patrick.pipeline.leaderboard import Leaderboard
from patrick.tracking.model_categories import CategoryResult
from patrick.tuning.optuna_runner import tune_config
from patrick.validation.metrics import metrics


def extract_global_category_result(ctx: _FoldContext, board: Leaderboard, horizon: int,
                                     n_wf_folds: int, best_cfg: dict, seed: int) -> CategoryResult:
    """`fold_metric` (F1_dir per fold) is read directly from the EXISTING
    scan's own rows for the winning (horizon, N, sampler, algo) config at
    regime="GLOBAL" -- no retraining needed for that part, `board.rows`
    already has it. `fold_loss` (0/1 loss per TEST OBSERVATION, concatenated
    across folds) is NOT available in `board.rows` (only aggregate metrics
    are) and per_regime/stacking's own `fold_loss` is observation-level (see
    their docstrings) -- `diebold_mariano`'s elementwise loss-difference
    requires matching granularity across categories (caught by this
    module's own integration test: an earlier fold-level version of this
    function broke the pairwise DM comparison with a shape mismatch). A
    small, single-config per-fold re-evaluation (identical to what
    per_regime/stacking already do) keeps granularity consistent, at the
    cost of one extra `_fit_eval` per fold for this one already-known-best
    config -- negligible next to the grid scan that already ran."""
    rows = [r for r in board.rows if r.get("horizon") == horizon and r.get("N") == best_cfg["n_feat"]
            and r.get("sampler") == best_cfg["sampler"] and r.get("algo") == best_cfg["algo"]
            and r.get("regime") == "GLOBAL"]
    fold_metric = np.array([r["F1_dir"] for r in sorted(rows, key=lambda r: r["fold"])])

    fold_losses = []
    for k in range(n_wf_folds):
        fd = ctx.prepare(horizon, k, "GLOBAL")
        if fd is None:
            continue
        cols = _select(ctx.pool_builder.conn, ctx.target_col, horizon, ctx.pool_builder.snapshot_id,
                        ctx.config, fd.X_tr, fd.y_tr, best_cfg["n_feat"], seed)
        X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
        _, y_pred, _ = _fit_eval(X_tr_n, fd.y_tr, X_te_n, fd.y_te, best_cfg["sampler"], best_cfg["algo"], seed)
        fold_losses.append((fd.y_te != y_pred).astype(float))
    fold_loss = np.concatenate(fold_losses) if fold_losses else np.array([])

    return CategoryResult(category="global", label=f"{best_cfg['algo']}_global",
                           fold_metric=fold_metric, fold_loss=fold_loss)


def _grid_scan_best_config(fold_data: list, config, n_feat_grid: list[int], samplers: list[str],
                            algos: list[str], seed: int, conn, target_col: str, horizon: int,
                            snapshot_id: str) -> dict:
    """Own full grid scan (n_features x sampler x algo), independent of any
    other category's winning config -- mean F1_dir across the folds in
    `fold_data` (a list of (fold_idx, FoldData)) picks the winner. Same grid
    dimensions `run_pipeline`'s own scan uses (`config.selection.
    n_features_grid`/`config.sampler.candidates`/`config.models.algos`),
    just restricted to whatever subset of folds `fold_data` covers (a
    regime's own folds for per_regime, every fold for stacking)."""
    best = None
    for n_feat in n_feat_grid:
        for sampler_name in samplers:
            for algo in algos:
                fold_f1 = []
                for _, fd in fold_data:
                    cols = _select(conn, target_col, horizon, snapshot_id, config, fd.X_tr, fd.y_tr, n_feat, seed)
                    X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
                    met, _, _ = _fit_eval(X_tr_n, fd.y_tr, X_te_n, fd.y_te, sampler_name, algo, seed)
                    fold_f1.append(met["F1_dir"])
                mean_f1 = float(np.mean(fold_f1)) if fold_f1 else -1.0
                if best is None or mean_f1 > best["mean_f1"]:
                    best = {"n_feat": n_feat, "sampler": sampler_name, "algo": algo, "mean_f1": mean_f1}
    return best


def train_per_regime_category(ctx: _FoldContext, raw_price_series: pd.Series, horizon: int,
                               n_wf_folds: int, config, seed: int) -> tuple[CategoryResult, dict]:
    """One sub-model per regime label -- each regime label runs its OWN
    full grid scan + full-budget Optuna tuning across the folds where it is
    present (see module docstring), bundled into a SINGLE artifact (the
    returned `CategoryResult` + `sub_models`, a
    {regime_label: {"config": ..., "params": ...}} routing table), not N
    separate runs. `raw_price_series`: the target's raw price/level series
    (same one CHANTIER A's `detect_regime` expects), aligned on
    `ctx.all_dates`."""
    conn, snapshot_id, target_col = ctx.pool_builder.conn, ctx.pool_builder.snapshot_id, ctx.target_col
    config_hash = _config_hash(config)
    os.makedirs(config.output.dir, exist_ok=True)
    optuna_storage_path = os.path.join(config.output.dir, "optuna_categories.db")

    # Pass 1: causal regime detection PER FOLD (fit_end_idx = that fold's
    # own cut), guardrail, then fold data collected PER REGIME LABEL --
    # never a single detection computed once upfront for the whole series.
    fold_data_by_label: dict[str, list] = {label: [] for label in REGIME_LABELS}
    for k in range(n_wf_folds):
        cut = ctx.fold_cuts[k]
        nxt_date = ctx.all_dates[ctx.fold_cuts[k + 1] - 1]
        regime_result = detect_regime(raw_price_series, n_states="auto",
                                       threshold_mode="quantile", seed=seed, fit_end_idx=cut)
        regime_series = regime_result.regime
        fold_window = regime_series[regime_series.index <= nxt_date].dropna()
        if fold_window.empty:
            continue
        check_regime_fragmentation(fold_window, horizon)  # blocage dur, a l'interieur de CE fold

        for regime_label in sorted(fold_window.unique()):
            fd = ctx.prepare(horizon, k, regime_label, external_regime_series=regime_series)
            if fd is not None:
                fold_data_by_label[regime_label].append((k, fd))

    fold_metrics: list[float] = []
    fold_losses: list[np.ndarray] = []
    sub_models: dict[str, dict] = {}

    for regime_label, fold_data in fold_data_by_label.items():
        if not fold_data:
            continue
        winner = _grid_scan_best_config(fold_data, config, config.selection.n_features_grid,
                                         config.sampler.candidates, config.models.algos, seed,
                                         conn, target_col, horizon, snapshot_id)

        last_k, last_fd = fold_data[-1]
        cols = _select(conn, target_col, horizon, snapshot_id, config, last_fd.X_tr, last_fd.y_tr,
                        winner["n_feat"], seed)
        X_tr_n = last_fd.X_tr[:, cols]
        study_name = f"{config.name}_{config_hash}_catB_per_regime_{regime_label}_h{horizon}_N{winner['n_feat']}_{winner['sampler']}_{winner['algo']}"
        best_params, _ = tune_config(X_tr_n, last_fd.y_tr, winner["algo"], winner["sampler"],
                                      n_trials=config.tuning.n_trials, cv_splits=config.tuning.cv_splits,
                                      seed=seed, storage_path=optuna_storage_path, study_name=study_name,
                                      bounds=config.tuning.optuna_bounds)

        y_te_parts, y_pred_parts = [], []
        for k, fd in fold_data:
            cols = _select(conn, target_col, horizon, snapshot_id, config, fd.X_tr, fd.y_tr,
                            winner["n_feat"], seed)
            X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
            _, y_pred, _ = _fit_eval(X_tr_n, fd.y_tr, X_te_n, fd.y_te, winner["sampler"], winner["algo"],
                                      seed, **best_params)
            y_te_parts.append(fd.y_te)
            y_pred_parts.append(y_pred)

        y_te_all, y_pred_all = np.concatenate(y_te_parts), np.concatenate(y_pred_parts)
        fold_metrics.append(metrics(y_te_all, y_pred_all)["F1_dir"])
        fold_losses.append((y_te_all != y_pred_all).astype(float))
        sub_models[regime_label] = {"config": winner, "params": best_params}

    fold_loss = np.concatenate(fold_losses) if fold_losses else np.array([])
    result = CategoryResult(category="per_regime", label="per_regime",
                             fold_metric=np.array(fold_metrics), fold_loss=fold_loss)
    return result, sub_models


def _oof_split(n_train: int, oof_frac: float = 0.2, min_oof: int = 20) -> int | None:
    """Position splitting a fold's train rows (already chronological) into
    base-train (earlier) / out-of-fold (later) -- a TEMPORAL split, never a
    random K-fold (which would let a base model's own out-of-order
    "future" leak into meta-training). Returns None when the fold's train
    is too small for a meaningful internal split."""
    n_oof = max(int(n_train * oof_frac), min_oof)
    if n_oof >= n_train - min_oof:
        return None
    return n_train - n_oof


def train_stacking_category(ctx: _FoldContext, horizon: int, n_wf_folds: int, config,
                             seed: int, oof_frac: float = 0.2) -> CategoryResult:
    """Meta-model (`LogisticRegression`) trained ONLY on out-of-fold base
    predictions (see `_oof_split`/module docstring for the anti-leakage
    guarantee). The stack's own (n_features, sampler) is grid-scanned on
    OOF meta-accuracy (`_grid_scan_best_config`-equivalent, inlined below
    since the scan metric here is the STACK's, not a single algo's), fully
    independent of global's winning config. Each base algo
    (`config.models.algos` -- the flag existed in the schema but was never
    wired into `engine.py` before this chantier, verified by grep before
    writing this module) is then Optuna-tuned at FULL budget on the
    OOF-training portion."""
    conn, snapshot_id, target_col = ctx.pool_builder.conn, ctx.pool_builder.snapshot_id, ctx.target_col
    config_hash = _config_hash(config)
    os.makedirs(config.output.dir, exist_ok=True)
    optuna_storage_path = os.path.join(config.output.dir, "optuna_categories.db")
    base_algos = config.models.algos

    fold_prep = []
    for k in range(n_wf_folds):
        fd = ctx.prepare(horizon, k, "GLOBAL")
        if fd is None:
            continue
        split = _oof_split(len(fd.y_tr), oof_frac)
        if split is None:
            continue
        fold_prep.append((k, fd, split))
    if not fold_prep:
        return CategoryResult(category="stacking", label=f"stack_{'_'.join(base_algos)}",
                               fold_metric=np.array([]), fold_loss=np.array([]))

    # Scan the stack's OWN (n_features, sampler): OOF meta-accuracy (default
    # hyperparameters at this stage, tuning comes after the winner is
    # picked -- same two-phase structure as global's scan-then-tune).
    best = None
    for n_feat in config.selection.n_features_grid:
        for sampler_name in config.sampler.candidates:
            fold_f1 = []
            for k, fd, split in fold_prep:
                cols = _select(conn, target_col, horizon, snapshot_id, config, fd.X_tr, fd.y_tr, n_feat, seed)
                X_tr_n = fd.X_tr[:, cols]
                X_base, y_base = X_tr_n[:split], fd.y_tr[:split]
                X_oof, y_oof = X_tr_n[split:], fd.y_tr[split:]
                oof_preds = [_fit_eval(X_base, y_base, X_oof, y_oof, sampler_name, algo, seed)[1]
                             for algo in base_algos]
                meta_X_oof = np.column_stack(oof_preds)
                meta = LogisticRegression(max_iter=1000, random_state=seed).fit(meta_X_oof, y_oof)
                fold_f1.append(metrics(y_oof, meta.predict(meta_X_oof))["F1_dir"])
            mean_f1 = float(np.mean(fold_f1)) if fold_f1 else -1.0
            if best is None or mean_f1 > best["mean_f1"]:
                best = {"n_feat": n_feat, "sampler": sampler_name, "mean_f1": mean_f1}

    # Optuna-tune EACH base algo at full budget, on the LAST fold's
    # OOF-training portion (X_base/y_base) -- mirrors global's "tune on the
    # last fold's train" convention.
    last_k, last_fd, last_split = fold_prep[-1]
    cols = _select(conn, target_col, horizon, snapshot_id, config, last_fd.X_tr, last_fd.y_tr,
                    best["n_feat"], seed)
    X_base_last = last_fd.X_tr[:, cols][:last_split]
    y_base_last = last_fd.y_tr[:last_split]
    tuned_params: dict[str, dict] = {}
    for algo in base_algos:
        study_name = f"{config.name}_{config_hash}_catB_stacking_h{horizon}_N{best['n_feat']}_{best['sampler']}_{algo}"
        best_params, _ = tune_config(X_base_last, y_base_last, algo, best["sampler"],
                                      n_trials=config.tuning.n_trials, cv_splits=config.tuning.cv_splits,
                                      seed=seed, storage_path=optuna_storage_path, study_name=study_name,
                                      bounds=config.tuning.optuna_bounds)
        tuned_params[algo] = best_params

    fold_metrics: list[float] = []
    fold_losses: list[np.ndarray] = []
    for k, fd, split in fold_prep:
        cols = _select(conn, target_col, horizon, snapshot_id, config, fd.X_tr, fd.y_tr, best["n_feat"], seed)
        X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
        X_base, y_base = X_tr_n[:split], fd.y_tr[:split]
        X_oof, y_oof = X_tr_n[split:], fd.y_tr[split:]

        oof_preds = [_fit_eval(X_base, y_base, X_oof, y_oof, best["sampler"], algo, seed,
                                **tuned_params[algo])[1]
                     for algo in base_algos]
        meta_model = LogisticRegression(max_iter=1000, random_state=seed)
        meta_model.fit(np.column_stack(oof_preds), y_oof)

        # Base algos refit (tuned params) on the FULL fold train for the
        # real test-set inference -- separate train->test boundary from the
        # meta-training leakage guarantee above (see module docstring).
        test_preds = [_fit_eval(X_tr_n, fd.y_tr, X_te_n, fd.y_te, best["sampler"], algo, seed,
                                 **tuned_params[algo])[1]
                      for algo in base_algos]
        y_pred_final = meta_model.predict(np.column_stack(test_preds))

        fold_metrics.append(metrics(fd.y_te, y_pred_final)["F1_dir"])
        fold_losses.append((fd.y_te != y_pred_final).astype(float))

    fold_loss = np.concatenate(fold_losses) if fold_losses else np.array([])
    return CategoryResult(category="stacking", label=f"stack_{'_'.join(base_algos)}",
                           fold_metric=np.array(fold_metrics), fold_loss=fold_loss)
