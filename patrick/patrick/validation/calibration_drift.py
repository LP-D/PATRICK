"""Dérive de la calibration en réel : le Brier de P(hausse) en réel comparé à celui du holdout.

Un modèle peut garder sa direction et perdre sa calibration (ses probabilités deviennent trop sûres, ou trop timides) : les règles à seuils
sur P(hausse) et le dimensionnement en dépendent. On compare le Brier moyen des signaux réels déjà jugés à celui du holdout, avec l'erreur-type
des pertes réelles (signaux quotidiens chevauchant l'horizon : effectif n / h, comme le reste du projet). « Dégradée » = le Brier réel dépasse
celui du holdout de plus de deux erreurs-types.
"""
from __future__ import annotations

import math

import numpy as np

MIN_LIVE = 20


def calibration_drift(p_live, y_live, holdout_brier: float | None, horizon: int = 1) -> dict | None:
    """`p_live` : P(hausse) des signaux réels jugés ; `y_live` : 1 si hausse, 0 sinon. None sous `MIN_LIVE` signaux ou sans Brier holdout."""
    if holdout_brier is None or not math.isfinite(holdout_brier):
        return None
    p = np.asarray(p_live, dtype=float)
    y = np.asarray(y_live, dtype=float)
    ok = np.isfinite(p) & np.isfinite(y)
    if ok.sum() < MIN_LIVE:
        return None
    losses = (p[ok] - y[ok]) ** 2
    n_eff = max(ok.sum() / max(int(horizon), 1), 2.0)
    se = float(losses.std(ddof=1) / math.sqrt(n_eff))
    live = float(losses.mean())
    drift = live - float(holdout_brier)
    return {"live_brier": round(live, 4), "holdout_brier": round(float(holdout_brier), 4), "drift": round(drift, 4),
            "se": round(se, 4), "n_live": int(ok.sum()), "degraded": bool(drift > 2 * se)}
