"""Utilitaires partagés par les modules de features.

`Series.pct_change()` renvoie +/-inf (pas NaN) quand la valeur précédente est
nulle ou traverse zéro — `dropna()` seul ne les retire pas. Rencontré en
conditions réelles sur T10Y2Y (inversion de la courbe des taux, passe par zéro)
et EFFR (proche de 0 pendant le ZIRP 2020-2021), ce qui plantait
`GaussianHMM.fit()` (ValueError: Input contains infinity) et polluait les
autres features basées sur les rendements. Toute fonction qui calcule un
rendement doit passer par `safe_pct_change` plutôt que par `.pct_change()` direct.

Phase 2 : un dénominateur proche de zéro (pas nul) produit un ratio non
infini mais absurdement grand (T10Y2Y à 0.001 : un mouvement de 0.01 point
donne un "rendement" de 1000%) — le remplacement ci-dessus ne l'attrape pas
(ce n'est pas +/-inf), et cette valeur énorme mais finie peut ensuite déborder
en overflow -> inf après mise à l'échelle (RobustScaler) plus loin dans le
pipeline, plantant XGBoost ("Input data contains inf"). Rencontré sur les
proxys Heston/VRP (`vol_models.py`) appliqués à T10Y2Y. Un rendement au-delà
de +/-1000% sur une seule période n'est de toute façon jamais un signal
exploitable ici -> clippé plutôt que laissé exploser.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

_MAX_ABS_RETURN = 10.0  # +/-1000% : au-delà, artefact de dénominateur proche de zéro


def safe_pct_change(series: pd.Series, periods: int = 1) -> pd.Series:
    pct = series.pct_change(periods).replace([np.inf, -np.inf], np.nan)
    return pct.clip(-_MAX_ABS_RETURN, _MAX_ABS_RETURN)
