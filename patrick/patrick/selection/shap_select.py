"""SHAP selection (the project's default method — beats RFE and LASSO in
direct testing in VIX_FEATURE_SELECTION). Includes the multiclass SHAP axis
fix used throughout the project."""
from __future__ import annotations

import numpy as np
import shap

from patrick.models.xgb_labels import AnyLabelXGBClassifier as XGBClassifier
from patrick.selection._common import SELECTION_N_JOBS, prefilter_pool, rank_top


def shap_rank(X_tr: np.ndarray, y_tr: np.ndarray, pool_names: list[str], top_n: int,
              prefilter: int, shap_sample: int = 500, seed: int = 42, recent: bool = False) -> list[int]:
    """`recent` (méthode 2, ADR 0008) : l'importance est mesurée sur les `shap_sample` lignes les plus RÉCENTES de l'entraînement.
    Avec une fenêtre croissante, les premières lignes datent de 2000-2002 : elles ne disent rien du régime actuel."""
    keep = prefilter_pool(X_tr, y_tr, prefilter, seed)
    Xk = X_tr[:, keep]
    pilot = XGBClassifier(n_estimators=80, max_depth=4, learning_rate=0.1,
                           objective="multi:softprob", eval_metric="mlogloss",
                           random_state=seed, n_jobs=SELECTION_N_JOBS, verbosity=0)
    pilot.fit(Xk, y_tr)
    rows = Xk[-min(shap_sample, len(Xk)):] if recent else Xk[:min(shap_sample, len(Xk))]
    sv = np.abs(np.array(shap.TreeExplainer(pilot).shap_values(rows)))
    nfk = Xk.shape[1]
    # [FIX] multiclass shap_values can return (n_classes, n_obs, n_features) OR
    # (n_obs, n_features, n_classes) depending on the version — the feature axis
    # is located by its size rather than assuming a fixed order.
    feat_axes = [ax for ax in range(sv.ndim) if sv.shape[ax] == nfk]
    if len(feat_axes) == 1:
        arr = sv.mean(axis=tuple(ax for ax in range(sv.ndim) if ax != feat_axes[0]))
    else:
        arr = np.asarray(pilot.feature_importances_)
    order = rank_top(arr, top_n)
    return list(keep[order])
