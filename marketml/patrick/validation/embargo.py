"""Embargo (López de Prado) : au-delà de la purge (retire du train les lignes dont
la fenêtre de LABEL chevauche la coupure), l'embargo retire du TEST les `e`
premières barres qui suivent immédiatement la coupure. Motivation distincte de la
purge : des features à fenêtre glissante (rolling mean/std/EWMA...) calculées juste
après la coupure incluent encore des observations du train dans leur fenêtre, donc
peuvent rester corrélées avec lui même une fois le label "propre" (déjà géré par la
purge). Défaut `e = horizon` (cf. `ValidationConfig.embargo_bars=None` -> dérivé de
l'horizon courant plutôt que codé en dur), cohérent avec l'ordre de grandeur des
fenêtres de feature les plus longues utilisées dans ce projet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def embargo_mask(full_index: pd.DatetimeIndex, mask: np.ndarray, cut_date,
                  embargo_bars: int) -> np.ndarray:
    """Retire de `mask` (typiquement le masque de test, aligné sur `full_index`)
    les `embargo_bars` premières lignes à `cut_date` ou après. Ne modifie que les
    positions déjà à True ; ne touche pas les positions avant `cut_date` (l'embargo
    s'applique au début du test, pas à la fin du train — cf. purge pour ce côté)."""
    if embargo_bars <= 0:
        return mask
    out = mask.copy()
    positions = np.where(mask)[0]
    if len(positions) == 0:
        return out
    dates_at_positions = full_index[positions]
    is_at_or_after_cut = dates_at_positions >= cut_date
    to_drop = positions[is_at_or_after_cut][:embargo_bars]
    out[to_drop] = False
    return out
