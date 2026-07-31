"""Découverte d'interactions inter-features (VIX_FINAL_FEATURES) : top-N features
par importance -> paires parmi un sous-ensemble plus restreint -> plusieurs types
d'interaction par paire -> re-sélection des meilleures. Les noms générés
(`A__minus__B`, `A__prod__B`, `A__zrel__B`, ...) suivent la convention déjà en
place dans les features sélectionnées du projet.
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
    """X_df et y doivent déjà être alignés (même ordre de lignes, sans NaN dans y)."""
    Xf = X_df.fillna(0.0)
    base_names = _prefilter_top(Xf.values, y, list(X_df.columns), top_base, seed)
    pair_names = _prefilter_top(Xf[base_names].values, y, base_names, top_pairs, seed)

    candidates = {}
    for i, a in enumerate(pair_names):
        for b in pair_names[i + 1:]:
            for tname, fn in INTERACTION_TYPES.items():
                try:
                    # `ratio`/`zrel` gardent déjà un dénominateur EXACTEMENT nul
                    # (`.replace(0, np.nan)`), mais pas un dénominateur simplement
                    # très petit -- ce cas produit un +-inf réel (pas NaN), que
                    # XGBoost (utilisé par `_prefilter_top` juste après) rejette
                    # sans condition (`Input data contains inf`). Traité comme
                    # une valeur manquante, au même titre que le cas déjà géré.
                    col = fn(X_df[a], X_df[b]).replace([np.inf, -np.inf], np.nan)
                    if col.notna().sum() > 20:
                        candidates[f"{a}__{tname}__{b}"] = col
                except Exception:
                    continue
    if not candidates:
        return pd.DataFrame(index=X_df.index)

    cand_df = pd.DataFrame(candidates, index=X_df.index)
    keep = _prefilter_top(cand_df.fillna(0.0).values, y, list(cand_df.columns), final_n, seed)
    return cand_df[keep]
