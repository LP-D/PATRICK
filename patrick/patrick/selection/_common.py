"""Pre-filter shared by the 3 selection methods: reduces a potentially huge
feature pool to `prefilter` columns by XGBoost importance, before applying
the final method (SHAP/RFE/LASSO) -- identical across the 3, to isolate the
effect of the final method (VIX_FEATURE_SELECTION)."""
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
