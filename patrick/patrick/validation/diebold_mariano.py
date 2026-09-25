"""Diebold-Mariano test (1995): does the predictive accuracy of two models
differ significantly, or is the observed gap consistent with sampling
noise? Original formulation uses squared loss (regression) — generalized
here to 0/1 loss (misclassified = 1, correct = 0), adapted to this
project's 4-class classification target. H0: both models have the same
predictive accuracy.

F04 -- Harvey, Leybourne & Newbold (1997) small-sample correction, always
applied: DM* = DM * sqrt((T + 1 - 2h + h(h-1)/T) / T), referred to a Student
t(T-1) rather than N(0,1). The uncorrected test over-rejects H0 for small T
and h > 1 (HLN 1997, Table 1) -- exactly this pipeline's regime: DM is
evaluated on a SINGLE walk-forward fold (a few hundred rows) at horizons up
to 756 days.

Long-run variance: standard DM estimator (autocovariances around the full
sample mean, divided by T, rectangular window up to lag h-1). That window
can yield a NEGATIVE variance for h > 1; it then falls back to Bartlett
weights (Newey-West, non-negative by construction). A variance still <= 0
while the loss differential is not constant makes the test undefined:
`dm_stat`/`p_value` are NaN ("untestable"), never a clamped denominator that
turns any nonzero mean into p=0.
"""
from __future__ import annotations

import numpy as np
from scipy import stats


def _autocovariances(d: np.ndarray, max_lag: int) -> np.ndarray:
    n = len(d)
    c = d - d.mean()
    return np.array([c @ c / n] + [c[k:] @ c[:-k] / n for k in range(1, max_lag + 1) if k < n])


def _long_run_variance(d: np.ndarray, h: int) -> tuple[float, str]:
    gamma = _autocovariances(d, max(h - 1, 0))
    var = gamma[0] + 2 * gamma[1:].sum()
    if var > 0:
        return float(var), "rectangular"
    lags = np.arange(1, len(gamma))
    weights = 1 - lags / len(gamma)
    return float(gamma[0] + 2 * (weights * gamma[1:]).sum()), "bartlett"


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> dict:
    """`loss_a`: candidate model's loss, `loss_b`: comparison baseline's loss,
    aligned observation by observation (same order, same length). `h`:
    forecast horizon — the loss-difference series can be autocorrelated up
    to lag h-1 (overlapping label windows), the test variance accounts for
    this rather than assuming independence.

    `dm_stat` < 0: the candidate has a lower (better) mean loss than the
    baseline. `p_value`: two-sided, H0 = equal accuracy, HLN-corrected."""
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    n = len(d)
    h = max(int(h), 1)
    nan_result = {"dm_stat": np.nan, "p_value": np.nan, "n_obs": n, "mean_loss_diff": np.nan,
                  "correction": "HLN", "variance_kernel": None}
    if n < 10:
        return nan_result

    d_mean = float(np.mean(d))
    if np.all(d == d[0]):
        # Constant differential: no sampling variability at all. Equal
        # losses -> no evidence against H0; a constant nonzero gap -> the
        # limit of an infinitely significant difference.
        stat = 0.0 if d_mean == 0 else float(np.sign(d_mean) * np.inf)
        return {"dm_stat": stat, "p_value": 1.0 if d_mean == 0 else 0.0, "n_obs": n,
                "mean_loss_diff": round(d_mean, 6), "correction": "HLN", "variance_kernel": None}

    var_d, kernel = _long_run_variance(d, h)
    if not var_d > 0:
        return {**nan_result, "mean_loss_diff": round(d_mean, 6), "variance_kernel": kernel}

    dm = d_mean / np.sqrt(var_d / n)
    hln_factor = np.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 0.0))
    dm_star = float(dm * hln_factor)
    p_value = float(2 * stats.t.sf(abs(dm_star), df=n - 1))
    return {
        "dm_stat": round(dm_star, 4),
        "p_value": round(p_value, 4),
        "n_obs": n,
        "mean_loss_diff": round(d_mean, 6),
        "correction": "HLN",
        "variance_kernel": kernel,
    }
