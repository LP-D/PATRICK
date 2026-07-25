"""Pré-filtre partagé par les 3 méthodes de sélection : réduit un pool potentiellement
énorme de features à `prefilter` colonnes par importance XGBoost, avant d'appliquer
la méthode finale (SHAP/RFE/LASSO) — identique pour les 3, pour isoler l'effet de la
méthode finale (VIX_FEATURE_SELECTION)."""
from __future__ import annotations

import numpy as np
from xgboost import XGBClassifier


def prefilter_pool(X_tr: np.ndarray, y_tr: np.ndarray, prefilter: int, seed: int = 42) -> np.ndarray:
    nf = X_tr.shape[1]
    if nf <= prefilter:
        return np.arange(nf)
    pf = XGBClassifier(n_estimators=60, max_depth=4, learning_rate=0.1,
                        objective="multi:softprob", eval_metric="mlogloss",
                        random_state=seed, n_jobs=-1, verbosity=0)
    pf.fit(X_tr, y_tr)
    return np.argsort(pf.feature_importances_)[::-1][:prefilter]
