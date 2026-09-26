"""Pre-filter shared by the 3 selection methods: reduces a potentially huge
feature pool to `prefilter` columns by XGBoost importance, before applying
the final method (SHAP/RFE/LASSO) -- identical across the 3, to isolate the
effect of the final method (VIX_FEATURE_SELECTION).

Cross-platform reproducibility (see `tests/test_selection_determinism.py`):
every ranking in `selection/` and `features/interactions.py` goes through
`rank_top` (score descending, ties broken by ascending column index -- never
`np.argsort`'s default quicksort, whose tie order follows the CPU's SIMD
dispatch), and every selection estimator runs on `SELECTION_N_JOBS` threads
(never `-1`, whose histogram reduction order follows the machine's core
count and shifts importances at float precision)."""
from __future__ import annotations

import numpy as np
from xgboost import XGBClassifier

# Fixed, machine-independent thread count for the selection estimators. Any
# fixed value is reproducible for a given library build; 2 keeps some
# parallelism on the prefilter (the costliest selection step) without the
# oversubscription documented for MODEL_N_JOBS in `models/registry.py`.
SELECTION_N_JOBS = 2

# Bumped whenever the ranking rule changes: part of the selection cache key
# (`pipeline/engine.py::_selector_config_hash`), so selections computed under
# the previous, CPU-dependent rule are never served again.
RANKING_VERSION = "stable-index-tiebreak-v1"


def rank_top(scores, top_n: int) -> np.ndarray:
    """Indices of the `top_n` highest `scores`, ties broken by ascending
    index, NaN ranked last -- a total order that depends on the values only,
    not on the sort implementation."""
    s = np.asarray(scores, dtype=float).ravel()
    key = np.where(np.isnan(s), -np.inf, s)
    order = np.lexsort((np.arange(len(s)), -key))
    return order[:top_n]


def prefilter_pool(X_tr: np.ndarray, y_tr: np.ndarray, prefilter: int, seed: int = 42) -> np.ndarray:
    nf = X_tr.shape[1]
    if nf <= prefilter:
        return np.arange(nf)
    pf = XGBClassifier(n_estimators=60, max_depth=4, learning_rate=0.1,
                        objective="multi:softprob", eval_metric="mlogloss",
                        random_state=seed, n_jobs=SELECTION_N_JOBS, verbosity=0)
    pf.fit(X_tr, y_tr)
    return rank_top(pf.feature_importances_, prefilter)
