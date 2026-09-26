"""Meta-labeling (Lopez de Prado, AFML ch. 3.6) on the stored out-of-sample
predictions (roadmap bloc 3).

The primary model gives the side (its direction call). A secondary
("meta") model estimates P(the primary call is right) from what was known
at decision time, and only calls with a high enough meta probability are
kept -- trading recall for precision, and giving a bet size.

Walk-forward without look-ahead: at prediction t, the meta model is
(re)fitted on the earlier predictions whose OUTCOME WAS ALREADY KNOWN --
their horizon had elapsed: `i + horizon <= t` in rows (predictions are
consecutive sessions within a fold). Its features are available at t:
- |P(up) - 0.5| (strength of the directional probability),
- the predicted class's confidence,
- the primary's rolling hit rate over its last `hit_window` resolved calls.

Logistic regression, deliberately simple: a few hundred resolved calls
cannot support more, and the question is whether the primary's confidence
carries information about its own accuracy.
"""
from __future__ import annotations

import math

import numpy as np
from sklearn.linear_model import LogisticRegression

UP_CLASSES = (2, 3)


def _correct(y_pred: np.ndarray, y_true: np.ndarray) -> np.ndarray:
    return (np.isin(y_pred, UP_CLASSES) == np.isin(y_true, UP_CLASSES)).astype(int)


def meta_label_sequence(y_pred, y_true, p_up, confidence, horizon: int, min_train: int = 100,
                        refit_every: int = 20, hit_window: int = 50, threshold: float | None = None) -> dict:
    """`threshold=None` (default): a call is kept when its meta probability
    exceeds the primary's own hit rate on the calls resolved so far -- a
    fixed 0.5 would keep nearly everything as soon as the primary is right
    more often than not, filtering nothing."""
    y_pred = np.asarray(y_pred, dtype=float).astype(int)
    y_true = np.asarray(y_true, dtype=float).astype(int)
    p_up = np.asarray(p_up, dtype=float)
    conf = np.asarray(confidence, dtype=float)
    n = len(y_pred)
    correct = _correct(y_pred, y_true)
    strength = np.abs(p_up - 0.5)
    conf = np.where(np.isfinite(conf), conf, 0.5)

    hit_rate = np.full(n, np.nan)
    for t in range(n):
        known = correct[max(0, t - horizon - hit_window + 1):max(0, t - horizon + 1)]
        hit_rate[t] = known.mean() if len(known) else np.nan
    features = np.column_stack([strength, conf, np.nan_to_num(hit_rate, nan=0.5)])

    meta_p = np.full(n, np.nan)
    thr = np.full(n, np.nan)
    model = None
    last_fit = -refit_every
    for t in range(n):
        n_known = t - horizon + 1          # rows 0..t-horizon have a known outcome at t
        if n_known < min_train:
            continue
        if model is None or t - last_fit >= refit_every:
            y_fit = correct[:n_known]
            if len(np.unique(y_fit)) < 2:
                continue
            model = LogisticRegression(C=1.0, max_iter=200).fit(features[:n_known], y_fit)
            last_fit = t
        meta_p[t] = model.predict_proba(features[t:t + 1])[0, 1]
        thr[t] = correct[:n_known].mean() if threshold is None else threshold

    evaluated = np.isfinite(meta_p)
    kept = evaluated & (meta_p > thr)
    return {
        "meta_p": meta_p, "kept": kept, "n": n, "n_evaluated": int(evaluated.sum()), "n_kept": int(kept.sum()),
        "accuracy_all": float(correct[evaluated].mean()) if evaluated.any() else math.nan,
        "accuracy_kept": float(correct[kept].mean()) if kept.any() else math.nan,
        "kept_share": float(kept.sum() / evaluated.sum()) if evaluated.any() else math.nan,
        "threshold": threshold,
    }
