"""Cross-feature interaction discovery (VIX_FINAL_FEATURES): top-N features
by importance -> pairs among a narrower subset -> several interaction types
per pair -> re-selection of the best ones. The generated names
(`A__minus__B`, `A__prod__B`, `A__zrel__B`, ...) follow the convention
already in place in the project's selected features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

INTERACTION_TYPES = {
    "minus": lambda a, b: a - b,
    "prod": lambda a, b: a * b,
    "ratio": lambda a, b: a / b.replace(0, np.nan),
    "sum": lambda a, b: a + b,
    "zrel": lambda a, b: (a - b) / b.rolling(60).std().replace(0, np.nan),
    "corr20": lambda a, b: a.rolling(20).corr(b),
}


def apply_interaction(fn, a: pd.Series, b: pd.Series) -> pd.Series:
    """Correction report, N2 -- the ONLY authorized application point for
    `INTERACTION_TYPES` functions, so the anti-inf guard can no longer be
    forgotten by a caller.

    `ratio`/`zrel` already neutralize a denominator that is EXACTLY zero
    (`.replace(0, np.nan)`), but not a denominator that is merely very
    small: that case produces a real ±inf (not a NaN), which XGBoost
    rejects unconditionally ("Input data contains `inf`"). The guard used
    to live only in `discover_interactions`, whereas the formulas retained
    on the pilot fold are then APPLIED to the other folds
    (`_apply_interaction_formulas`, pipeline/engine.py) -- exactly where
    the denominator can become ~0 when it was well-behaved on the pilot.
    That was the path reproduced in production. A ±inf has no numerical
    meaning here: treated as a missing value, the same as a zero
    denominator."""
    return fn(a, b).replace([np.inf, -np.inf], np.nan)


def _prefilter_top(X: np.ndarray, y: np.ndarray, names: list[str], top_n: int,
                    seed: int = 42) -> list[str]:
    top_n = min(top_n, len(names))
    pf = XGBClassifier(n_estimators=80, max_depth=4, learning_rate=0.1,
                        objective="multi:softprob", eval_metric="mlogloss",
                        random_state=seed, n_jobs=-1, verbosity=0)
    pf.fit(X, y)
    order = np.argsort(pf.feature_importances_)[::-1][:top_n]
    return [names[i] for i in order]


def discover_interactions(X_df: pd.DataFrame, y: np.ndarray, top_base: int = 40,
                           top_pairs: int = 20, final_n: int = 30,
                           seed: int = 42) -> pd.DataFrame:
    """X_df and y must already be aligned (same row order, no NaN in y)."""
    Xf = X_df.fillna(0.0)
    base_names = _prefilter_top(Xf.values, y, list(X_df.columns), top_base, seed)
    pair_names = _prefilter_top(Xf[base_names].values, y, base_names, top_pairs, seed)

    candidates = {}
    for i, a in enumerate(pair_names):
        for b in pair_names[i + 1:]:
            for tname, fn in INTERACTION_TYPES.items():
                try:
                    col = apply_interaction(fn, X_df[a], X_df[b])
                    if col.notna().sum() > 20:
                        candidates[f"{a}__{tname}__{b}"] = col
                except Exception:
                    continue
    if not candidates:
        return pd.DataFrame(index=X_df.index)

    cand_df = pd.DataFrame(candidates, index=X_df.index)
    keep = _prefilter_top(cand_df.fillna(0.0).values, y, list(cand_df.columns), final_n, seed)
    return cand_df[keep]
