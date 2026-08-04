"""Sélection RFE (wrapper) — testée dans VIX_FEATURE_SELECTION, légèrement
derrière SHAP (F1_dir 0.579 vs 0.597 sur la config de référence)."""
from __future__ import annotations

import numpy as np
from sklearn.feature_selection import RFE
from sklearn.linear_model import LogisticRegression

from patrick.selection._common import prefilter_pool


def rfe_rank(X_tr: np.ndarray, y_tr: np.ndarray, top_n: int, prefilter: int,
             step: float = 0.1, seed: int = 42) -> np.ndarray:
    keep = prefilter_pool(X_tr, y_tr, prefilter, seed)
    Xk = X_tr[:, keep]
    est = LogisticRegression(max_iter=200, random_state=seed)
    sel = RFE(est, n_features_to_select=min(top_n, Xk.shape[1]), step=step).fit(Xk, y_tr)
    return keep[np.where(sel.support_)[0]]
