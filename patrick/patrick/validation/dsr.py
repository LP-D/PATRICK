"""Deflated Sharpe Ratio (Bailey & López de Prado, "The Deflated Sharpe
Ratio: Correcting for Selection Bias, Backtest Overfitting and
Non-Normality", 2014). Corrects the observed Sharpe for selection bias (the
best trial among N overestimates its true quality) and return non-normality
(skew/kurtosis, which widen the estimated Sharpe's effective variance).

Phase 2.3: the original plan explicitly ties it to Phase 4 ("used as soon as
a P&L curve exists") — there is not yet a real return series in this
pipeline (the metrics are classification scores, not a P&L). This module is
therefore standalone and tested, but not yet called from
`pipeline/engine.py`: nothing to apply it to before the investment
simulator.
"""
from __future__ import annotations

import numpy as np
from scipy import stats

_EULER_MASCHERONI = 0.5772156649015329


def _sharpe_std_error(n: int, skew: float, kurtosis: float, sr: float) -> float:
    """Asymptotic standard error of the estimated Sharpe (Mertens 2002 /
    Bailey & López de Prado 2012, eq. 5) — reduces to 1/sqrt(n) under
    normality (skew=0, kurtosis=3)."""
    return float(np.sqrt(max((1 - skew * sr + (kurtosis - 1) / 4 * sr ** 2) / max(n - 1, 1), 0.0)))


def expected_max_sharpe(n_trials: int, sr_std: float) -> float:
    """E[max(SR_1..SR_N)] under H0 (N independent trials, SR ~ N(0, sr_std^2))
    -- approximated via the extreme order statistics of a Gaussian sample
    (Bailey & López de Prado 2014, eq. 6). This is the "benchmark" the
    observed Sharpe must beat to not be explained by the mere fact of having
    tried N configurations."""
    if n_trials <= 1 or sr_std <= 0:
        return 0.0
    return float(sr_std * (
        (1 - _EULER_MASCHERONI) * stats.norm.ppf(1 - 1 / n_trials)
        + _EULER_MASCHERONI * stats.norm.ppf(1 - 1 / (n_trials * np.e))
    ))


def deflated_sharpe_ratio(returns: np.ndarray, n_trials: int, periods_per_year: int = 252,
                           benchmark_sr: float | None = None) -> dict:
    """`returns`: PERIODIC (not annualized) returns of the evaluated strategy.
    `n_trials`: number of trials among which this strategy was chosen as the
    best one (see `tracking.stats.count_cumulative_trials`).
    `benchmark_sr`: reference Sharpe to beat; defaults to
    `expected_max_sharpe(n_trials, ...)` (the paper's standard benchmark).

    Returns a dict with `dsr` (probability that the true Sharpe is positive,
    deflated) and `p_value` (1 - dsr); `sr`/`sr_annualized` the raw,
    non-deflated Sharpe, for comparison."""
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
    kurt = float(stats.kurtosis(r, fisher=False))  # "normal kurtosis" convention = 3, not excess kurtosis

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
