"""Cible alpha vs benchmark : le rendement excédentaire `actif - β * benchmark`
au lieu du rendement brut (jalon 1, brique statistique pure -- aucun branchement
au pipeline). Spécification :
`docs/superpowers/specs/2026-10-06-cible-alpha-beta-point-in-time-design.md`.

Règle de non-fuite : `β_t` n'utilise que les rendements quotidiens jusqu'à *t*
inclus (fenêtre glissante), jamais une estimation sur toute la période. Le
label d'une date *t* utilise `β_t` figé sur toute sa fenêtre d'horizon.

Décalage de séance (`bench_lag`, jalon 2b) : l'ingestion décale d'une barre les
séries qui clôturent après la cible (`data/session_calendar.py`). Le benchmark du
pipeline arrive donc « tel que connu à la décision » (`bench_asof`). Les labels
ont besoin du vrai calendrier (`bench_asof.shift(-bench_lag)`), mais le β utilisé
en *t* ne doit pas connaître le rendement du jour du benchmark si celui-ci
clôture après la décision : on le décale de `bench_lag` barres. `bench_lag = 0`
(défaut) redonne exactement le comportement du jalon 1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.data.session_calendar import session_lag_days
from patrick.data.sources.yfinance_source import clean_symbol
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


def known_beta(asset: pd.Series, bench_asof: pd.Series, bench_lag: int = 0, window: int = DEFAULT_WINDOW,
               min_obs: int = DEFAULT_MIN_OBS) -> pd.Series:
    """β utilisable en *t* : estimé sur le vrai calendrier du benchmark puis
    décalé de `bench_lag` barres (le rendement du jour du benchmark n'est pas connu s'il clôture après la décision)."""
    a, b = _aligned(asset, bench_asof)
    return point_in_time_beta(a, b.shift(-bench_lag), window, min_obs).shift(bench_lag)


def alpha_labels(asset: pd.Series, bench_asof: pd.Series, horizon: int, window: int = DEFAULT_WINDOW,
                 min_obs: int = DEFAULT_MIN_OBS, bench_lag: int = 0) -> pd.Series:
    """Rendement excédentaire à `horizon` jours, sur le vrai calendrier du benchmark, avec le β connu en *t*."""
    a, b = _aligned(asset, bench_asof)
    return alpha_forward_return(a, b.shift(-bench_lag), horizon, known_beta(a, b, bench_lag, window, min_obs))


def alpha_persistence_signal(asset: pd.Series, bench_asof: pd.Series, horizon: int, window: int = DEFAULT_WINDOW,
                             min_obs: int = DEFAULT_MIN_OBS, bench_lag: int = 0) -> pd.Series:
    """Baseline « persistance de l'alpha » : 1 si l'alpha réalisé sur les
    `horizon` jours qui précèdent *t* (avec le β connu en *t*, benchmark tel que
    connu à la décision) est positif, 0 sinon, NaN si inconnu. N'utilise que le passé de *t*."""
    a, b = _aligned(asset, bench_asof)
    beta = known_beta(a, b, bench_lag, window, min_obs)
    past = (a / a.shift(horizon) - 1) - beta * (b / b.shift(horizon) - 1)
    return pd.Series(np.where(past.isna(), np.nan, (past > 0).astype(float)), index=past.index)


def alpha_level_series(asset: pd.Series, bench_asof: pd.Series, window: int = DEFAULT_WINDOW,
                       min_obs: int = DEFAULT_MIN_OBS, bench_lag: int = 0) -> pd.Series:
    """« Niveau » de l'alpha : 100 composé des alphas quotidiens connus
    (`r_actif - β_connu * r_benchmark_connu`). Remplace le prix dans les
    baselines (momentum, marche aléatoire, HAR-RV) d'une cible alpha, qui
    n'ont de sens que sur la grandeur réellement prédite."""
    a, b = _aligned(asset, bench_asof)
    daily = a.pct_change() - known_beta(a, b, bench_lag, window, min_obs) * b.pct_change()
    return 100.0 * (1.0 + daily.fillna(0.0)).cumprod()


def alpha_pair_level(asset: pd.Series, bench_asof: pd.Series, window: int = DEFAULT_WINDOW,
                     min_obs: int = DEFAULT_MIN_OBS, bench_lag: int = 0) -> tuple[pd.Series, pd.Series]:
    """Niveau (base 100) d'un portefeuille long 1 actif / short `β_connu` benchmark, couverture réajustée chaque
    jour, et `β_connu`. Le P&L du jour *t* utilise le rendement du VRAI jour *t* du benchmark (calendrier
    reconstitué) : c'est ce que la position a réellement gagné. Tant que `β` est inconnu, la paire est à plat.
    Sert de « prix » à la simulation d'un modèle d'alpha."""
    a, b = _aligned(asset, bench_asof)
    beta = known_beta(a, b, bench_lag, DEFAULT_WINDOW if window is None else window, min_obs)
    daily = a.pct_change() - beta * b.shift(-bench_lag).pct_change()
    return 100.0 * (1.0 + daily.fillna(0.0)).cumprod(), beta


def build_alpha_target(asset: pd.Series, bench_asof: pd.Series, horizon: int, split_idx: int,
                       window: int = DEFAULT_WINDOW, min_obs: int = DEFAULT_MIN_OBS,
                       flat_thr: float = 0.003, bench_lag: int = 0) -> tuple[pd.Series, pd.Series, dict]:
    """Cible 4 classes (comme `features.target.build_target`) sur le rendement
    excédentaire. Seuils et régimes ajustés sur le train du fold uniquement;
    `split_idx` s'exprime sur l'index commun actif/benchmark."""
    a, b = _aligned(asset, bench_asof)
    alpha = alpha_labels(a, b, horizon, window, min_obs, bench_lag)
    return build_target(a, horizon, split_idx, flat_thr, ret=alpha)


# --------------------------------------------------------------------------- branchement au pipeline

def bench_lag(objective) -> int:
    """Décalage (en barres) appliqué au benchmark par l'ingestion : même règle que `data.ingest._apply_session_lag`."""
    if objective.disable_session_lag:
        return 0
    return session_lag_days(objective.benchmark, "yfinance", objective.target_symbol, objective.target_source)


def run_target(pool: pd.DataFrame, config, target_col: str, horizon: int,
               split_idx: int) -> tuple[pd.Series, pd.Series, dict]:
    """Point d'entrée unique du moteur : (cible, régime, seuils) selon `objective.target_kind`.
    Cible brute : exactement `build_target(pool[target_col], ...)` (comportement historique)."""
    obj = config.objective
    if obj.target_kind != "alpha":
        return build_target(pool[target_col], horizon, split_idx, obj.flat_thr)
    return build_alpha_target(pool[target_col], pool[clean_symbol(obj.benchmark)], horizon, split_idx,
                              flat_thr=obj.flat_thr, bench_lag=bench_lag(obj))


def baseline_price_series(pool: pd.DataFrame, config, target_col: str) -> pd.Series:
    """Série sur laquelle les baselines de prix sont calculées : le prix de la cible, ou le niveau d'alpha."""
    obj = config.objective
    if obj.target_kind != "alpha":
        return pool[target_col]
    return alpha_level_series(pool[target_col], pool[clean_symbol(obj.benchmark)], bench_lag=bench_lag(obj))
