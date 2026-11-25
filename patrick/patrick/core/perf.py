"""Conventions communes des mesures de performance (AM2 du 25/11).

Quatre modules redéfinissaient chacun 252 séances, le Sharpe et le Sortino, avec deux définitions différentes du Sortino
(CO4 : `simulate/metrics.py` prenait l'écart-type des seules séances négatives). Ce module porte la référence :

- `TRADING_DAYS` (252) pour une série de jours ouvrés, `CALENDAR_DAYS` (365) pour une série qui contient les week-ends
  (cryptoactif : sept jours sur sept) ; `periods_per_year` choisit d'après l'index (CO5).
- `downside_deviation` : écart à la baisse sur TOUTES les séances, racine de la moyenne des pertes au carré (Sortino & Price).
"""
from __future__ import annotations

import math

import numpy as np

TRADING_DAYS = 252
CALENDAR_DAYS = 365
WEEKEND_SHARE_FOR_CALENDAR = 0.20     # un cryptoactif a ~28,6 % de samedis et dimanches ; une série de change en a 0 à 2 %


def periods_per_year(index=None) -> int:
    """252 pour une série quotidienne de jours ouvrés, 365 si plus de 20 % de ses dates tombent un samedi ou un dimanche.

    Sans index de dates (tableau nu, index entier), 252 : la convention historique de tous les appelants."""
    if index is None or len(index) < 10:
        return TRADING_DAYS
    dow = getattr(index, "dayofweek", None)
    if dow is None:
        return TRADING_DAYS
    weekend = float(np.mean(np.asarray(dow) >= 5))
    return CALENDAR_DAYS if weekend > WEEKEND_SHARE_FOR_CALENDAR else TRADING_DAYS


def downside_deviation(excess) -> float:
    """Écart à la baisse : racine de la moyenne, sur toutes les séances, de min(rendement excédentaire, 0) au carré."""
    r = np.asarray(excess, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return float("nan")
    return math.sqrt(float(np.mean(np.minimum(r, 0.0) ** 2)))
