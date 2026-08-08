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

from patrick.config.schema import RunConfig
from patrick.features.target import build_target
from patrick.models.registry import get_classifier
from patrick.models.samplers import get_sampler
from patrick.selection.registry import select_features


def export_best_model(pool, target_col: str, feature_pool: list[str], config: RunConfig,
                       best_cfg: dict, out_dir: str, seed: int = 42,
                       interaction_formulas: list[str] | None = None) -> str:
    horizon = int(best_cfg["horizon"])
    regime = best_cfg["regime"]
    n_feat = int(best_cfg["N"])
    sampler_name = best_cfg["sampler"]
    algo = best_cfg["algo"]
    raw_params = best_cfg.get("best_params")
    best_params = ast.literal_eval(raw_params) if raw_params else {}

    split_idx = len(pool) - 1
    target_series, reg_r, _ = build_target(pool[target_col], horizon, split_idx,
                                            config.objective.flat_thr)
    idx = target_series.index
    reg_al = reg_r.reindex(idx).fillna("NORMAL").values
    sel = (reg_al == regime) if regime != "GLOBAL" else np.ones(len(idx), dtype=bool)

    y = target_series.values[sel].astype(int)
    X_pool_df = pool[feature_pool].reindex(idx)
    sc = RobustScaler()
    X = sc.fit_transform(np.nan_to_num(X_pool_df.values[sel]))

    cols = select_features(config.selection.method, X, y, n_feat, config.features.pool_prefilter,
                            seed=seed, shap_sample=config.selection.shap_sample)
    X_n = X[:, cols]
    feat_names = [feature_pool[c] for c in cols]

    try:
        Xr, yr = get_sampler(sampler_name, seed).fit_resample(X_n, y)
    except Exception:
        Xr, yr = X_n, y
    clf = get_classifier(algo, seed=seed, **best_params)
    clf.fit(Xr, yr)

    os.makedirs(out_dir, exist_ok=True)
    model_path = os.path.join(out_dir, f"{config.name}_best_model.joblib")
    # `feature_pool`/`interaction_formulas` (Phase 4.6, `patrick predict
    # --live`): the FULL pool (before selection) and the recipe to rebuild it
    # identically on fresh data -- `scaler.transform` requires the same
    # number of columns, in the same order, as those seen by `.fit`.
    # Interaction formulas are discovered once per run (pilot fold, see
    # `_FoldPoolBuilder`) and without them, `predict --live` cannot reproduce
    # the training pool's interaction columns.
    joblib.dump({"model": clf, "scaler": sc, "feature_names": feat_names,
                 "feature_pool": feature_pool, "interaction_formulas": interaction_formulas or [],
                 "target_col": target_col}, model_path)

    meta = {"horizon": horizon, "regime": regime, "N": n_feat, "sampler": sampler_name,
            "algo": algo, "best_params": best_params, "feature_names": feat_names,
            "feature_pool": feature_pool, "interaction_formulas": interaction_formulas or [],
            "n_train_rows": int(len(y))}
    meta_path = os.path.join(out_dir, f"{config.name}_best_model_meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=1)

    print(f"[EXPORT] winning model ({algo}, h={horizon}d, {regime}, N={n_feat}) -> {model_path}")
    return model_path
