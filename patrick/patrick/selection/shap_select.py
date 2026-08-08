"""SHAP selection (the project's default method — beats RFE and LASSO in
direct testing in VIX_FEATURE_SELECTION). Includes the multiclass SHAP axis
fix used throughout the project."""
from __future__ import annotations

import numpy as np
import shap
from xgboost import XGBClassifier

from patrick.selection._common import prefilter_pool


def shap_rank(X_tr: np.ndarray, y_tr: np.ndarray, pool_names: list[str], top_n: int,
              prefilter: int, shap_sample: int = 500, seed: int = 42) -> list[int]:
    keep = prefilter_pool(X_tr, y_tr, prefilter, seed)
    Xk = X_tr[:, keep]
    pilot = XGBClassifier(n_estimators=80, max_depth=4, learning_rate=0.1,
                           objective="multi:softprob", eval_metric="mlogloss",
                           random_state=seed, n_jobs=-1, verbosity=0)
    pilot.fit(Xk, y_tr)
    sv = np.abs(np.array(shap.TreeExplainer(pilot).shap_values(Xk[:min(shap_sample, len(Xk))])))
    nfk = Xk.shape[1]
    # [FIX] multiclass shap_values can return (n_classes, n_obs, n_features) OR
    # (n_obs, n_features, n_classes) depending on the version — the feature axis
    # is located by its size rather than assuming a fixed order.
    feat_axes = [ax for ax in range(sv.ndim) if sv.shape[ax] == nfk]
    if len(feat_axes) == 1:
        arr = sv.mean(axis=tuple(ax for ax in range(sv.ndim) if ax != feat_axes[0]))
    else:
        arr = np.asarray(pilot.feature_importances_)
    order = np.argsort(np.asarray(arr).ravel())[::-1][:top_n]
    return list(keep[order])
