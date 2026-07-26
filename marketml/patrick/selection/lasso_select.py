"""Sélection LASSO (embedded) — testée dans VIX_FEATURE_SELECTION, la plus faible
des trois sur la config de référence (F1_dir 0.572)."""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

from patrick.selection._common import prefilter_pool


def lasso_rank(X_tr: np.ndarray, y_tr: np.ndarray, top_n: int, prefilter: int,
               C: float = 0.5, seed: int = 42) -> np.ndarray:
    keep = prefilter_pool(X_tr, y_tr, prefilter, seed)
    Xk = X_tr[:, keep]
    est = LogisticRegression(penalty="l1", solver="saga", C=C, max_iter=1000,
                              random_state=seed, n_jobs=-1)
    est.fit(Xk, y_tr)
    importance = np.abs(est.coef_).mean(axis=0)
    order = np.argsort(importance)[::-1][:top_n]
    return keep[order]
