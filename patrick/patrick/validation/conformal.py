"""Conformal prediction on the predicted direction (roadmap bloc 3).

Input: a time-ordered sequence of OUT-OF-SAMPLE P(up) (walk-forward test
folds, holdout, live -- `prediction.p_up`) and the realised direction.
Output: for each prediction, a prediction SET over {down, up} at
miscoverage alpha:
- {up} or {down}: the model's call is conformally supported;
- {down, up}: "no call" -- the model cannot tell the direction at that
  confidence level;
- {} : both directions rejected (possible with ACI when alpha_t > 1 -- read
  as no call too).

Nonconformity score of an observation: 1 - p(realised direction)
(p(up) = P(up), p(down) = 1 - P(up)). The threshold for prediction t is the
conformal quantile of the scores of the predictions BEFORE t only
(`window` most recent) -- they are genuinely out-of-sample for their own
models, so no data is reused.

Validity: split conformal guarantees marginal coverage >= 1 - alpha under
exchangeability, which a financial time series does not satisfy. Adaptive
Conformal Inference (Gibbs & Candes 2021, `method="aci"`) updates the level
online, alpha_{t+1} = alpha_t + gamma (alpha - err_t), and guarantees the
LONG-RUN coverage error goes to 0 for any sequence (|mean err - alpha| <=
(max(alpha_1, 1 - alpha_1) + gamma) / (gamma T)). Empirical coverage is
always reported next to the nominal one -- never assumed.
"""
from __future__ import annotations

import math

import numpy as np


def _scores(p_up: np.ndarray, y_up: np.ndarray) -> np.ndarray:
    return np.where(y_up == 1, 1.0 - p_up, p_up)


def _conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    """ceil((n + 1)(1 - alpha)) / n empirical quantile; +inf when the level
    exceeds 1 (not enough calibration scores: the set is everything)."""
    n = len(scores)
    if n == 0 or alpha <= 0:
        return math.inf
    if alpha >= 1:
        return -math.inf
    k = math.ceil((n + 1) * (1 - alpha))
    if k > n:
        return math.inf
    return float(np.sort(scores)[k - 1])


def direction_sets(p_up, y_up, alpha: float = 0.2, method: str = "split", gamma: float = 0.01,
                   window: int | None = 500, min_calibration: int = 30) -> dict:
    """Sequential conformal sets. Predictions before `min_calibration` past
    scores exist get the full set (no call). Returns per-step arrays and a
    summary (empirical coverage, no-call rate, accuracy when a single
    direction is called)."""
    if method not in ("split", "aci"):
        raise ValueError(f"unknown method {method!r} (split | aci)")
    p = np.clip(np.asarray(p_up, dtype=float), 0.0, 1.0)
    y = np.asarray(y_up, dtype=int)
    n = len(p)
    contains_up = np.ones(n, dtype=bool)
    contains_down = np.ones(n, dtype=bool)
    alpha_t = np.full(n, float(alpha))
    scores = _scores(p, y)
    a = float(alpha)
    for t in range(n):
        past = scores[max(0, t - window):t] if window else scores[:t]
        alpha_t[t] = a
        if len(past) >= min_calibration:
            q = _conformal_quantile(past, a)
            contains_up[t] = (1.0 - p[t]) <= q
            contains_down[t] = p[t] <= q
        covered = contains_up[t] if y[t] == 1 else contains_down[t]
        if method == "aci" and len(past) >= min_calibration:
            a = a + gamma * (alpha - (0.0 if covered else 1.0))
    covered = np.where(y == 1, contains_up, contains_down)
    single = contains_up ^ contains_down
    call_up = contains_up & ~contains_down
    n_single = int(single.sum())
    return {
        "contains_up": contains_up, "contains_down": contains_down, "alpha_t": alpha_t,
        "coverage": float(covered.mean()) if n else math.nan,
        "nominal": 1.0 - alpha,
        "no_call_rate": float((~single).mean()) if n else math.nan,
        "n": n, "n_called": n_single,
        "called_accuracy": float((call_up[single] == (y[single] == 1)).mean()) if n_single else math.nan,
        "method": method,
    }
