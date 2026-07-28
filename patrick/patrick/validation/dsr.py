"""Sharpe déflaté — Deflated Sharpe Ratio (Bailey & López de Prado, "The
Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting
and Non-Normality", 2014). Corrige le Sharpe observé du biais de sélection
(le meilleur essai parmi N surestime sa vraie qualité) et de la non-normalité
des rendements (skew/kurtosis, qui élargissent la variance effective du
Sharpe estimé).

Phase 2.3 : le plan le lie explicitement à la Phase 4 ("utilisé dès qu'une
courbe de P&L existe") — il n'y a pas encore de série de rendements réelle
dans ce pipeline (les métriques sont des scores de classification, pas un
P&L). Ce module est donc autonome et testé, mais pas encore appelé depuis
`pipeline/engine.py` : rien à quoi l'appliquer avant le simulateur
d'investissement.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

_EULER_MASCHERONI = 0.5772156649015329


def _sharpe_std_error(n: int, skew: float, kurtosis: float, sr: float) -> float:
    """Écart-type asymptotique du Sharpe estimé (Mertens 2002 / Bailey & López
    de Prado 2012, eq. 5) — se réduit à 1/sqrt(n) sous normalité (skew=0,
    kurtosis=3)."""
    return float(np.sqrt(max((1 - skew * sr + (kurtosis - 1) / 4 * sr ** 2) / max(n - 1, 1), 0.0)))


def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """E[max(SR_1..SR_N)] sous H0 (N essais indépendants, SR ~ N(0, sr_std^2)) —
    approximation par les statistiques d'ordre extrêmes d'un échantillon gaussien
    (Bailey & López de Prado 2014, eq. 6). C'est le "benchmark" que le Sharpe
    observé doit dépasser pour ne pas être expliqué par le simple fait d'avoir
    essayé N configurations."""
    if n_trials <= 1 or sr_std <= 0:
        return 0.0
    return float(sr_std * (
        (1 - _EULER_MASCHERONI) * stats.norm.ppf(1 - 1 / n_trials)
        + _EULER_MASCHERONI * stats.norm.ppf(1 - 1 / (n_trials * np.e))
    ))


def deflated_sharpe_ratio(returns: np.ndarray, n_trials: int, periods_per_year: int = 252,
                           benchmark_sr: float | None = None) -> dict:
    """`returns` : rendements PÉRIODIQUES (pas annualisés) de la stratégie évaluée.
    `n_trials` : nombre d'essais parmi lesquels cette stratégie a été choisie
    comme la meilleure (cf. `tracking.stats.count_cumulative_trials`).
    `benchmark_sr` : Sharpe de référence à dépasser ; par défaut,
    `expected_max_sharpe(n_trials, ...)` (le benchmark standard du papier).

    Retourne un dict avec `dsr` (probabilité que le Sharpe vrai soit positif,
    déflaté) et `p_value` (1 - dsr) ; `sr`/`sr_annualized` le Sharpe brut non
    déflaté, pour comparaison."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < 20:
        return {"sr": np.nan, "sr_annualized": np.nan, "dsr": np.nan, "p_value": np.nan,
                "skew": np.nan, "kurtosis": np.nan, "n_obs": n, "n_trials": n_trials,
                "benchmark_sr": np.nan}

    std = np.std(r, ddof=1)
    sr = float(np.mean(r) / std) if std > 0 else 0.0
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r, fisher=False))  # convention "kurtosis normale" = 3, pas l'excès

    sr0 = benchmark_sr if benchmark_sr is not None else expected_max_sharpe(max(n_trials, 1), _sharpe_std_error(n, skew, kurt, sr))
    sr_std = _sharpe_std_error(n, skew, kurt, sr)

    if sr_std <= 0:
        z, dsr, p_value = np.nan, np.nan, np.nan
    else:
        z = (sr - sr0) / sr_std
        dsr = float(stats.norm.cdf(z))
        p_value = round(1 - dsr, 6)

    return {
        "sr": round(sr, 4),
        "sr_annualized": round(sr * np.sqrt(periods_per_year), 4),
        "dsr": round(dsr, 4) if dsr == dsr else np.nan,
        "p_value": p_value if p_value == p_value else np.nan,
        "skew": round(skew, 4),
        "kurtosis": round(kurt, 4),
        "n_obs": n,
        "n_trials": n_trials,
        "benchmark_sr": round(sr0, 6) if sr0 == sr0 else np.nan,
    }
