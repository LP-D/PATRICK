"""Diebold-Mariano test (1995): does the predictive accuracy of two models
differ significantly, or is the observed gap consistent with sampling
noise? Original formulation uses squared loss (regression) — generalized
here to 0/1 loss (misclassified = 1, correct = 0), adapted to this
project's 4-class classification target. H0: both models have the same
predictive accuracy.
"""
from __future__ import annotations

import numpy as np
from scipy import stats


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> dict:
    """`loss_a`: candidate model's loss, `loss_b`: comparison baseline's loss,
    aligned observation by observation (same order, same length). `h`:
    forecast horizon — the loss-difference series can be autocorrelated up
    to lag h-1 (overlapping label windows), the test variance accounts for
    this rather than assuming independence.

    `dm_stat` < 0: the candidate has a lower (better) mean loss than the
    baseline. `p_value`: two-sided, H0 = equal accuracy."""
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    n = len(d)
    if n < 10:
        return {"dm_stat": np.nan, "p_value": np.nan, "n_obs": n, "mean_loss_diff": np.nan}

    d_mean = float(np.mean(d))

    var_d = float(np.var(d, ddof=0))
    for lag in range(1, max(h - 1, 0) + 1):
        if lag >= n:
            break
        cov = float(np.cov(d[:-lag], d[lag:], ddof=0)[0, 1])
        var_d += 2 * cov
    var_d = max(var_d, 1e-12)

    dm_stat = d_mean / np.sqrt(var_d / n)
    if not np.isfinite(dm_stat):
        dm_stat = 0.0
    p_value = float(2 * (1 - stats.norm.cdf(abs(dm_stat))))
    return {
        "dm_stat": round(float(dm_stat), 4),
        "p_value": round(p_value, 4),
        "n_obs": n,
        "mean_loss_diff": round(d_mean, 6),
    }

