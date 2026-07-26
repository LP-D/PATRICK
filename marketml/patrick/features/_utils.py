"""Utilitaires partagés par les modules de features.

`Series.pct_change()` renvoie +/-inf (pas NaN) quand la valeur précédente est
nulle ou traverse zéro — `dropna()` seul ne les retire pas. Rencontré en
conditions réelles sur T10Y2Y (inversion de la courbe des taux, passe par zéro)
et EFFR (proche de 0 pendant le ZIRP 2020-2021), ce qui plantait
`GaussianHMM.fit()` (ValueError: Input contains infinity) et polluait les
autres features basées sur les rendements. Toute fonction qui calcule un
rendement doit passer par `safe_pct_change` plutôt que par `.pct_change()` direct.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def safe_pct_change(series: pd.Series, periods: int = 1) -> pd.Series:
    return series.pct_change(periods).replace([np.inf, -np.inf], np.nan)
