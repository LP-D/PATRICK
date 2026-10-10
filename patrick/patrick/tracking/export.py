"""Export of the winning model: retrained on 100% of the available history
(like VIX_PRODUCTION — no test set to protect once the config has been
validated by the walk-forward scan), serialized with its scaler and selected
features.

Inference on the last unlabeled row (the "real" prediction for today) is not
included here — that's a separate `patrick predict` command, to be built
once the production-deployment need becomes concrete.
"""
from __future__ import annotations

import ast
import json
import os

import joblib
import numpy as np
from sklearn.preprocessing import RobustScaler

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.features.alpha_target import run_target
from patrick.features.sanitize import finite_features, finite_scaled
from patrick.models.registry import get_classifier
from patrick.selection.registry import select_features
from patrick.tuning.optuna_runner import safe_resample


def scale_selected(scaler: RobustScaler, values: np.ndarray, columns: list[int]) -> np.ndarray:
    """`scaler.transform(full)[:, columns]` computed from those columns
    alone: RobustScaler is column-wise (`(x - center_) / scale_`), so the
    result is identical while predict/explain only rebuild the features the
    model selected (and the raw series they come from) instead of the whole
    pool the scaler was fit on."""
    out = np.array(values, dtype=float, copy=True)
    if scaler.with_centering:
        out -= scaler.center_[columns]
    if scaler.with_scaling:
        out /= scaler.scale_[columns]
    return out


def export_best_model(pool, target_col: str, feature_pool: list[str], config: RunConfig,
                       best_cfg: dict, out_dir: str, seed: int = 42,
                       interaction_formulas: list[str] | None = None,
                       conn=None, symbol: str | None = None,
                       universe_reduction: dict | None = None) -> str:
    """`universe_reduction`: the whole-history reduction decision the
    caller already applied to `feature_pool` (kept/dropped series,
    threshold) -- recorded in the bundle and the meta json, never applied
    here. None = no reduction (key absent from both).

    `conn`/`symbol` (feature/drift-psi-infrastructure): when both are
    given, persists a PSI reference (`validation.drift.decile_reference`)
    for every SELECTED feature, keyed by (symbol, horizon, feature) --
    REPLACED at each call, never accumulated (`tracking.db.save_drift_reference`
    is an upsert), since a feature's reference is only meaningful as of the
    LATEST training window. Uses the RAW (pre-`RobustScaler`) training-window
    values already computed below for the real fit -- no second feature
    pass, no parallel data path. Optional and backward compatible: omitted
    (the default), this function's behavior is unchanged from before this
    parameter existed."""
    horizon = int(best_cfg["horizon"])
    regime = best_cfg["regime"]
    n_feat = int(best_cfg["N"])
    sampler_name = best_cfg["sampler"]
    algo = best_cfg["algo"]
    raw_params = best_cfg.get("best_params")
    best_params = ast.literal_eval(raw_params) if raw_params else {}

    split_idx = len(pool) - 1
    target_series, reg_r, _ = run_target(pool, config, target_col, horizon, split_idx)
    idx = target_series.index
    reg_al = reg_r.reindex(idx).fillna("NORMAL").values
    sel = (reg_al == regime) if regime != "GLOBAL" else np.ones(len(idx), dtype=bool)

    y = target_series.values[sel].astype(int)
    X_pool_df = pool[feature_pool].reindex(idx)
    sc = RobustScaler()
    X = finite_scaled(sc.fit_transform(finite_features(X_pool_df.values[sel], "export")), "export")

    cols = select_features(config.selection.method, X, y, n_feat, config.features.pool_prefilter,
                            seed=seed, shap_sample=config.selection.shap_sample)
    X_n = X[:, cols]
    feat_names = [feature_pool[c] for c in cols]

    Xr, yr = safe_resample(sampler_name, seed, X_n, y)
    clf = get_classifier(algo, seed=seed, **best_params)
    clf.fit(Xr, yr)
    if getattr(clf, "is_deep", False):
        # Réseau : réglages complets consignés (ceux du run + ceux d'Optuna). Rejouer ce champion plus tard, depuis un autre run (duel de
        # champions), reconstruit le MÊME réseau, pas celui qu'un autre jeu de réglages donnerait.
        best_params = {**{k: v for k, v in clf.get_params().items() if k in D.DEFAULT_DEEP}, **best_params}

    if conn is not None and symbol is not None:
        from patrick.tracking import db as trackdb
        from patrick.validation.drift import decile_reference

        raw_feature_values = X_pool_df[feat_names].values[sel]  # pre-scaling, matches on-demand reconstruction
        for i, feature in enumerate(feat_names):
            reference = decile_reference(raw_feature_values[:, i])
            trackdb.save_drift_reference(conn, symbol, horizon, feature, reference)

    os.makedirs(out_dir, exist_ok=True)
    # Fix report [per-horizon export]: horizon is always part of the filename
    # -- a multi-horizon `patrick run` calls this once PER horizon (see
    # `run_pipeline`'s `final_best_by_horizon` loop), and a shared
    # `<name>_best_model.joblib` would have the last-exported horizon
    # silently overwrite every other one on disk. Older runs (pre-fix) wrote
    # the horizon-less name -- untouched here, never rewritten, so their
    # already-recorded `trial.artifact_path` in the DB keeps resolving
    # (nothing re-derives that path from this convention, see predict.py).
    model_path = os.path.join(out_dir, f"{config.name}_best_model_h{horizon}.joblib")
    # `feature_pool`/`interaction_formulas` (Phase 4.6, `patrick predict
    # --live`): the FULL pool (before selection) and the recipe to rebuild it
    # identically on fresh data -- `scaler.transform` requires the same
    # number of columns, in the same order, as those seen by `.fit`.
    # Interaction formulas are discovered once per run (pilot fold, see
    # `_FoldPoolBuilder`) and without them, `predict --live` cannot reproduce
    # the training pool's interaction columns.
    bundle = {"model": clf, "scaler": sc, "feature_names": feat_names,
              "feature_pool": feature_pool, "interaction_formulas": interaction_formulas or [],
              "target_col": target_col}
    meta = {"horizon": horizon, "regime": regime, "N": n_feat, "sampler": sampler_name,
            "algo": algo, "best_params": best_params, "feature_names": feat_names,
            "feature_pool": feature_pool, "interaction_formulas": interaction_formulas or [],
            "n_train_rows": len(y)}
    if universe_reduction is not None:
        bundle["universe_reduction"] = meta["universe_reduction"] = universe_reduction
    joblib.dump(bundle, model_path)
    # Derived from `model_path` (not a second independent f-string) so it
    # stays in sync with whatever convention is above -- `worker.py`'s
    # `_summarize_result` re-derives this same meta path the same way
    # (`model_path[:-len(".joblib")] + "_meta.json"`).
    meta_path = model_path[: -len(".joblib")] + "_meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=1)

    print(f"[EXPORT] winning model ({algo}, h={horizon}d, {regime}, N={n_feat}) -> {model_path}")
    return model_path
