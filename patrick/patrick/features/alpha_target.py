"""Cible alpha vs benchmark : le rendement excédentaire `actif - β * benchmark`
au lieu du rendement brut (jalon 1, brique statistique pure -- aucun branchement
au pipeline). Spécification :
`docs/superpowers/specs/2026-10-06-cible-alpha-beta-point-in-time-design.md`.

Règle de non-fuite : `β_t` n'utilise que les rendements quotidiens jusqu'à *t*
inclus (fenêtre glissante), jamais une estimation sur toute la période. Le
label d'une date *t* utilise `β_t` figé sur toute sa fenêtre d'horizon.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.features.target import build_target

DEFAULT_WINDOW = 252
DEFAULT_MIN_OBS = 60


def _aligned(asset: pd.Series, bench: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Les deux séries sur leurs dates communes (calendriers de places différents)."""
    idx = asset.index.intersection(bench.index)
    return asset.reindex(idx), bench.reindex(idx)


def point_in_time_beta(asset: pd.Series, bench: pd.Series, window: int = DEFAULT_WINDOW,
                       min_obs: int = DEFAULT_MIN_OBS) -> pd.Series:
    """`β_t = cov(r_a, r_b) / var(r_b)` sur les `window` derniers rendements
    quotidiens se terminant à *t* inclus; NaN tant que moins de `min_obs`
    rendements sont disponibles. Entrées : niveaux de prix."""
    a, b = _aligned(asset, bench)
    ra, rb = a.pct_change(), b.pct_change()
    beta = ra.rolling(window, min_periods=min_obs).cov(rb) / rb.rolling(window, min_periods=min_obs).var()
    return beta.replace([np.inf, -np.inf], np.nan)


def alpha_forward_return(asset: pd.Series, bench: pd.Series, horizon: int, beta: pd.Series) -> pd.Series:
    """`(P^a_{t+h}/P^a_t - 1) - β_t * (P^b_{t+h}/P^b_t - 1)` ; NaN sur les `horizon` derniers points."""
    a, b = _aligned(asset, bench)
    forward_a = a.shift(-horizon) / a - 1
    forward_b = b.shift(-horizon) / b - 1
    return forward_a - beta.reindex(a.index) * forward_b


def alpha_persistence_signal(asset: pd.Series, bench: pd.Series, horizon: int, window: int = DEFAULT_WINDOW,
                             min_obs: int = DEFAULT_MIN_OBS) -> pd.Series:
    """Baseline « persistance de l'alpha » : 1 si l'alpha réalisé sur les
    `horizon` jours qui précèdent *t* (avec `β_t`) est positif, 0 sinon, NaN si
    inconnu. N'utilise que le passé de *t*."""
    a, b = _aligned(asset, bench)
    beta = point_in_time_beta(a, b, window, min_obs)
    past = (a / a.shift(horizon) - 1) - beta * (b / b.shift(horizon) - 1)
    return pd.Series(np.where(past.isna(), np.nan, (past > 0).astype(float)), index=past.index)


def build_alpha_target(asset: pd.Series, bench: pd.Series, horizon: int, split_idx: int,
                       window: int = DEFAULT_WINDOW, min_obs: int = DEFAULT_MIN_OBS,
                       flat_thr: float = 0.003) -> tuple[pd.Series, pd.Series, dict]:
    """Cible 4 classes (comme `features.target.build_target`) sur le rendement
    excédentaire. Seuils et régimes ajustés sur le train du fold uniquement;
    `split_idx` s'exprime sur l'index commun actif/benchmark."""
    a, b = _aligned(asset, bench)
    alpha = alpha_forward_return(a, b, horizon, point_in_time_beta(a, b, window, min_obs))
    return build_target(a, horizon, split_idx, flat_thr, ret=alpha)
