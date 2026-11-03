"""Dépendance dans le temps d'une série : ACF, PACF, Ljung-Box (sur x et sur x^2, ce dernier est le test de McLeod-Li), ARCH-LM d'Engle, et test BDS
(non-linéarité résiduelle). Les trois premiers viennent de `exploration.studies.memory` (une seule implémentation) ; le BDS est ajouté ici."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from patrick.exploration import studies as S

BDS_MAX_OBS = 2000        # le BDS compare toutes les paires de points : coût en n^2, on garde les observations les plus récentes
BDS_ALPHA = 0.05


def bds_test(x: pd.Series, max_dim: int = 5, distance: float = 1.5, alpha: float = BDS_ALPHA) -> dict:
    """Test BDS (Brock-Dechert-Scheinkman 1996) : H0 = les observations sont indépendantes et identiquement distribuées. Appliqué aux résidus
    d'un modèle linéaire (ou aux résidus standardisés d'un GARCH), un rejet révèle une structure NON LINÉAIRE que le modèle n'a pas capturée.
    `distance` : seuil epsilon exprimé en écarts-types. Le rejet global est corrigé de Bonferroni sur les dimensions testées."""
    from statsmodels.tsa.stattools import bds

    v = pd.Series(x).replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    if len(v) < 100:
        raise ValueError("Pas assez d'observations pour le test BDS (minimum 100).")
    used = v[-BDS_MAX_OBS:]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stat, pvalue = bds(used, max_dim=max_dim, distance=distance)
    rows = [{"dim": int(d), "stat": float(s), "pvalue": float(p)} for d, s, p in zip(range(2, max_dim + 1), np.atleast_1d(stat), np.atleast_1d(pvalue), strict=True)]
    adjusted = min(1.0, min(r["pvalue"] for r in rows) * len(rows))
    return {"rows": rows, "n_obs": len(used), "distance": distance, "min_pvalue_adjusted": adjusted, "rejects_iid": bool(adjusted < alpha)}


def dependence_summary(x: pd.Series, nlags: int = 20) -> dict:
    """ACF/PACF de x et de x^2, Ljung-Box de x et de x^2 (McLeod-Li), ARCH-LM, et BDS de x."""
    base = S.memory(pd.Series(x).dropna(), nlags)
    try:
        base["bds"] = bds_test(x)
    except ValueError as exc:
        base["bds"] = {"error": str(exc)}
    return base
