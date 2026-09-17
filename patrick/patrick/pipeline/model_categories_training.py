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
  block) runs per fold, on that fold's own regime-labeled rows.
- "stacking": strict out-of-fold within each fold's own TRAIN portion only
  -- an internal TEMPORAL split (never K-fold-random, see `_oof_split`),
  base algorithms fit on the earlier slice, meta-model trained ONLY on their
  predictions on the later (out-of-fold) slice. Base algorithms are then
  refit on the fold's FULL train for the real test-set inference (standard
  stacking practice) -- the anti-leakage guarantee is about the META-MODEL's
  training data, not about the final test-time base-model fit/predict step
  (which is the same train->test boundary every other category already
  respects).

Deliberately ADDITIVE and reuses `pipeline.engine`'s existing per-fold
primitives (`_FoldContext`, `_fit_eval`, `_select`) as building blocks
rather than re-implementing fold/purge/embargo/scaling logic a second time.
Optuna budget for per_regime/stacking is HALVED relative to the global scan
(`_reduced_n_trials`) -- decision of judgment call, flagged: these two
categories already multiply cost by n_regimes/n_base_algos per fold: an
identical tuning budget would multiply total cost rather than merely add to
it; halve first, revisit if real run time proves disproportionate.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from patrick.features.regime_detection import check_regime_fragmentation, detect_regime
from patrick.pipeline.engine import _fit_eval, _select, _FoldContext
from patrick.pipeline.leaderboard import Leaderboard
from patrick.tracking.model_categories import CategoryResult
from patrick.validation.metrics import metrics


def _reduced_n_trials(base_n_trials: int, min_trials: int = 5) -> int:
    return max(min_trials, base_n_trials // 2)


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


def train_per_regime_category(ctx: _FoldContext, raw_price_series: pd.Series, horizon: int,
                               n_wf_folds: int, base_cfg: dict,
                               seed: int) -> tuple[CategoryResult, dict]:
    """One sub-model per regime label, per fold -- bundled into a SINGLE
    artifact (the returned `CategoryResult` + `sub_models`, a
    {fold_idx: {regime_label: fitted_classifier}} routing table), not N
    separate runs. `raw_price_series`: the target's raw price/level series
    (same one CHANTIER A's `detect_regime` expects), aligned on
    `ctx.all_dates`."""
    fold_metrics: list[float] = []
    fold_losses: list[np.ndarray] = []
    sub_models: dict[int, dict] = {}

    for k in range(n_wf_folds):
        cut = ctx.fold_cuts[k]
        nxt = ctx.fold_cuts[k + 1]
        nxt_date = ctx.all_dates[nxt - 1]

        # Causal regime detection FOR THIS FOLD ONLY: fit_end_idx is this
        # fold's own train/test cut, never the global series end -- the
        # order explicitly required (detect regime, THEN route, per fold,
        # before evaluating that fold's test set).
        regime_result = detect_regime(raw_price_series, n_states="auto",
                                       threshold_mode="quantile", seed=seed, fit_end_idx=cut)
        regime_series = regime_result.regime

        fold_window = regime_series[regime_series.index <= nxt_date].dropna()
        if fold_window.empty:
            continue
        # Garde-fou de fragmentation (CHANTIER A) -- blocage dur, a
        # l'interieur de CE fold (pas une verification globale en amont).
        check_regime_fragmentation(fold_window, horizon)

        y_te_parts, y_pred_parts = [], []
        fold_sub_models = {}
        for regime_label in sorted(fold_window.unique()):
            fd = ctx.prepare(horizon, k, regime_label, external_regime_series=regime_series)
            if fd is None:
                continue
            cols = _select(ctx.pool_builder.conn, ctx.target_col, horizon,
                            ctx.pool_builder.snapshot_id, ctx.config, fd.X_tr, fd.y_tr,
                            base_cfg["n_feat"], seed)
            X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
            met, y_pred, _ = _fit_eval(X_tr_n, fd.y_tr, X_te_n, fd.y_te,
                                        base_cfg["sampler"], base_cfg["algo"], seed)
            y_te_parts.append(fd.y_te)
            y_pred_parts.append(y_pred)
            fold_sub_models[regime_label] = {"cols": cols, "metrics": met}

        if not y_te_parts:
            continue
        y_te_all = np.concatenate(y_te_parts)
        y_pred_all = np.concatenate(y_pred_parts)
        fold_metrics.append(metrics(y_te_all, y_pred_all)["F1_dir"])
        fold_losses.append((y_te_all != y_pred_all).astype(float))
        sub_models[k] = fold_sub_models

    fold_loss = np.concatenate(fold_losses) if fold_losses else np.array([])
    result = CategoryResult(category="per_regime", label=f"{base_cfg['algo']}_per_regime",
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


def train_stacking_category(ctx: _FoldContext, horizon: int, n_wf_folds: int,
                             base_algos: list[str], n_feat: int, sampler_name: str,
                             seed: int, oof_frac: float = 0.2) -> CategoryResult:
    """Meta-model (`LogisticRegression`) trained ONLY on out-of-fold base
    predictions (see `_oof_split`/module docstring for the anti-leakage
    guarantee). Consumes `models.stacking`'s existing `base_algos` list
    (`config.models.algos`, the same pool every other category already
    uses) rather than inventing a new one -- the flag existed in the schema
    but was never wired into `engine.py` before this chantier (verified by
    grep before writing this module)."""
    fold_metrics: list[float] = []
    fold_losses: list[np.ndarray] = []

    for k in range(n_wf_folds):
        fd = ctx.prepare(horizon, k, "GLOBAL")
        if fd is None:
            continue
        split = _oof_split(len(fd.y_tr), oof_frac)
        if split is None:
            continue

        cols = _select(ctx.pool_builder.conn, ctx.target_col, horizon,
                        ctx.pool_builder.snapshot_id, ctx.config, fd.X_tr, fd.y_tr, n_feat, seed)
        X_tr_n, X_te_n = fd.X_tr[:, cols], fd.X_te[:, cols]
        X_base, y_base = X_tr_n[:split], fd.y_tr[:split]
        X_oof, y_oof = X_tr_n[split:], fd.y_tr[split:]

        oof_preds = []
        for algo in base_algos:
            _, y_pred_oof, _ = _fit_eval(X_base, y_base, X_oof, y_oof, sampler_name, algo, seed)
            oof_preds.append(y_pred_oof)
        meta_X_oof = np.column_stack(oof_preds)
        meta_model = LogisticRegression(max_iter=1000, random_state=seed)
        meta_model.fit(meta_X_oof, y_oof)

        # Base algos refit on the FULL fold train (base+oof) for the real
        # test-set inference -- standard stacking practice, a separate
        # train->test boundary from the meta-training leakage guarantee
        # above (see module docstring).
        test_preds = []
        for algo in base_algos:
            _, y_pred_test, _ = _fit_eval(X_tr_n, fd.y_tr, X_te_n, fd.y_te, sampler_name, algo, seed)
            test_preds.append(y_pred_test)
        meta_X_test = np.column_stack(test_preds)
        y_pred_final = meta_model.predict(meta_X_test)

        fold_metrics.append(metrics(fd.y_te, y_pred_final)["F1_dir"])
        fold_losses.append((fd.y_te != y_pred_final).astype(float))

    fold_loss = np.concatenate(fold_losses) if fold_losses else np.array([])
    return CategoryResult(category="stacking", label=f"stack_{'_'.join(base_algos)}",
                           fold_metric=np.array(fold_metrics), fold_loss=fold_loss)
