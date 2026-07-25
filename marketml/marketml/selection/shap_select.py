"""Sélection SHAP (méthode par défaut du projet — bat RFE et LASSO en test direct
dans VIX_FEATURE_SELECTION). Inclut le fix d'axe SHAP multiclasse utilisé partout
dans le projet."""
from __future__ import annotations

import numpy as np
import shap
from xgboost import XGBClassifier

from marketml.selection._common import prefilter_pool


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
    # [FIX] shap_values multiclasse peut renvoyer (n_classes, n_obs, n_features) OU
    # (n_obs, n_features, n_classes) selon la version — on repère l'axe des features
    # par sa taille plutôt que de supposer un ordre fixe.
    feat_axes = [ax for ax in range(sv.ndim) if sv.shape[ax] == nfk]
    if len(feat_axes) == 1:
        arr = sv.mean(axis=tuple(ax for ax in range(sv.ndim) if ax != feat_axes[0]))
    else:
        arr = np.asarray(pilot.feature_importances_)
    order = np.argsort(np.asarray(arr).ravel())[::-1][:top_n]
    return list(keep[order])
