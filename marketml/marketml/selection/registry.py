"""Registre unifié des méthodes de sélection de features — défaut SHAP (leçon du
projet : bat RFE et LASSO en test direct sur la config de référence)."""
from __future__ import annotations

import numpy as np

from marketml.selection.lasso_select import lasso_rank
from marketml.selection.rfe_select import rfe_rank
from marketml.selection.shap_select import shap_rank

SELECTION_METHODS = ("shap", "rfe", "lasso")


def select_features(method: str, X_tr: np.ndarray, y_tr: np.ndarray, top_n: int,
                     prefilter: int, seed: int = 42, shap_sample: int = 500) -> list[int]:
    if method == "shap":
        return shap_rank(X_tr, y_tr, [], top_n, prefilter, shap_sample=shap_sample, seed=seed)
    if method == "rfe":
        return list(rfe_rank(X_tr, y_tr, top_n, prefilter, seed=seed))
    if method == "lasso":
        return list(lasso_rank(X_tr, y_tr, top_n, prefilter, seed=seed))
    raise ValueError(f"Méthode de sélection inconnue: '{method}' (attendu: {SELECTION_METHODS})")
