"""Parité de risque (A30) : poids à contributions au risque égales (ERC, Maillard, Roncalli et Teïletche 2010).

La pondération par défaut du pilote est la volatilité inverse : elle ignore les corrélations, donc trois indices américains très corrélés pèsent
trois fois le risque d'un seul. L'ERC égalise la contribution de chaque cible au risque du portefeuille (w_i (Σw)_i), corrélations comprises.
Covariance réduite de Ledoit-Wolf (estimée sur les rendements quotidiens communs, jamais le futur). Approximation assumée : les positions sont
traitées comme toutes acheteuses (le sens change d'un jour à l'autre, la taille non).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_COMMON_DAYS = 120


def erc_weights(cov: np.ndarray, tol: float = 1e-10, max_iter: int = 2000) -> np.ndarray:
    """Poids positifs de somme 1 dont les contributions au risque w_i (Σw)_i sont égales (itérations multiplicatives, convergentes pour une
    matrice définie positive)."""
    cov = np.asarray(cov, dtype=float)
    n = cov.shape[0]
    if n == 1:
        return np.ones(1)
    w = 1.0 / np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    w /= w.sum()
    for _ in range(max_iter):
        rc = w * (cov @ w)
        target = rc.sum() / n
        new = w * np.sqrt(target / np.clip(rc, 1e-30, None))
        new /= new.sum()
        if np.max(np.abs(new - w)) < tol:
            return new
        w = new
    return w


def risk_contributions(w: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """Part de chaque position dans le risque (variance) du portefeuille, somme 1."""
    rc = w * (np.asarray(cov) @ w)
    return rc / rc.sum()


def shrunk_cov(returns: pd.DataFrame) -> np.ndarray | None:
    """Covariance de Ledoit-Wolf des rendements communs (colonnes = cibles) ; None sous `MIN_COMMON_DAYS` jours communs."""
    from sklearn.covariance import LedoitWolf

    common = returns.dropna()
    if len(common) < MIN_COMMON_DAYS or common.shape[1] < 1:
        return None
    return LedoitWolf().fit(common.to_numpy()).covariance_
