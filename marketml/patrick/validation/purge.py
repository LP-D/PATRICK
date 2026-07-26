"""Purging (VIX_PURGED_CV) : une ligne de train dont la fenêtre de label (horizon
jours ouvrés en avant) chevauche la coupure de fold doit être retirée du train,
sinon elle contient une information sur la période de test — la fuite mesurée
dans le projet était négligeable (delta F1_dir≈-0.002) mais l'option reste câblée.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_would_purge(all_dates: pd.DatetimeIndex, base_index: pd.DatetimeIndex,
                         horizon: int, cut_date) -> pd.Series:
    """Pour chaque date de `base_index` (typiquement l'index du train du fold),
    calcule si sa fenêtre de label (horizon jours ouvrés plus loin dans
    `all_dates`, l'index complet de l'historique) atteint ou dépasse `cut_date`."""
    pos = {d: i for i, d in enumerate(all_dates)}

    def fwd_date(d):
        i = pos.get(d)
        if i is None:
            return d
        j = min(i + horizon, len(all_dates) - 1)
        return all_dates[j]

    would_purge = pd.Series(
        [fwd_date(d) >= cut_date for d in base_index], index=base_index
    )
    return would_purge


def purge_mask(full_index: pd.DatetimeIndex, train_mask: np.ndarray,
               all_dates: pd.DatetimeIndex, horizon: int, cut_date) -> np.ndarray:
    """Retire de `train_mask` (booléen aligné sur `full_index`) les lignes dont la
    fenêtre de label chevauche `cut_date`. Ne modifie que les positions déjà à True."""
    train_dates = full_index[train_mask]
    would_purge = compute_would_purge(all_dates, train_dates, horizon, cut_date)
    out = train_mask.copy()
    out[np.where(train_mask)[0]] = ~would_purge.values
    return out
