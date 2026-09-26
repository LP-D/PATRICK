"""Probability calibration (isotonic or Platt) + causal threshold search
(VIX_CALIBRATED_THRESHOLD) -- measured gain outside the STRESS regime
(+0.026 F1_UP_FORT, +0.062 F1_DOWN_FORT), but hurts during STRESS
(-0.188 F1_UP_FORT): disabled by default, enable knowingly.

Walk-forward discipline (roadmap bloc 3): inside a fold's train, the rows
are split in time -- fit | purge gap | calibration | threshold -- and the
calibration and threshold slices are REAL rows: resampling (SMOTE...)
touches the fit rows only. The Phase 5.3 path calibrated on the resampled
array (wrong class priors) and took the "most recent 15%" of it, which is
where imblearn appends its SYNTHETIC rows; `CalibratedClassifierCV(cv=3)`
also split stratified, not in time. `tests/test_calibration_wf.py`.

Also here: P(up) from class probabilities (classes 2 and 3 = slight and
strong up), Brier score and expected calibration error of that P(up) --
the calibrated probability Black-Litterman v2 needs instead of the
predicted class's confidence.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator

from patrick.validation.metrics import metrics

DEFAULT_THRESHOLDS = np.arange(0.30, 0.71, 0.05)
CALIBRATION_METHODS = ("isotonic", "sigmoid")
UP_CLASSES = (2, 3)


@dataclass(frozen=True)
class CalibrationSplit:
    n: int
    fit_end: int      # fit rows: [0, fit_end)
    cal_start: int    # purge gap: [fit_end, cal_start); calibration: [cal_start, thr_start)
    thr_start: int    # threshold rows: [thr_start, n)


def calibration_split(n: int, frac: float = 0.15, min_rows: int = 20, gap: int = 0,
                      min_fit_rows: int = 40) -> CalibrationSplit | None:
    """Chronological split of a fold's train. The last `frac` of the rows
    (at least 2 x `min_rows`) are held out and halved: calibration map,
    then threshold search -- never the same rows for both (an isotonic map
    is in-sample perfect on the rows it was fitted on). `gap` rows before
    them are dropped (label overlap of horizon-h targets). None when too
    short: no calibration rather than a degenerate one."""
    n_hold = max(int(n * frac), 2 * min_rows)
    fit_end = n - n_hold - max(gap, 0)
    if fit_end < min_fit_rows:
        return None
    cal_start = n - n_hold
    return CalibrationSplit(n=n, fit_end=fit_end, cal_start=cal_start, thr_start=cal_start + n_hold // 2)


def fit_prefit_calibrator(clf, X_cal: np.ndarray, y_cal: np.ndarray, method: str = "isotonic"):
    """Calibrates an already fitted classifier on held-out rows (one-vs-rest
    maps, renormalised)."""
    if method not in CALIBRATION_METHODS:
        raise ValueError(f"unknown calibration method {method!r} ({CALIBRATION_METHODS})")
    return CalibratedClassifierCV(FrozenEstimator(clf), method=method).fit(X_cal, y_cal)


def calibrate_classifier(base_clf, X_tr: np.ndarray, y_tr: np.ndarray, cv: int = 3):
    """Legacy k-fold calibration (kept for external callers; the pipeline
    uses `calibration_split` + `fit_prefit_calibrator`)."""
    cal = CalibratedClassifierCV(base_clf, method="isotonic", cv=cv)
    cal.fit(X_tr, y_tr)
    return cal


def p_up_from_proba(proba: np.ndarray, classes) -> np.ndarray:
    """P(up) = sum of the probabilities of the up classes present in
    `classes` (a class absent from the fit contributes nothing)."""
    classes = list(classes)
    cols = [classes.index(c) for c in UP_CLASSES if c in classes]
    proba = np.asarray(proba, dtype=float)
    return proba[:, cols].sum(axis=1) if cols else np.zeros(len(proba))


def brier_score(p: np.ndarray, y_binary: np.ndarray) -> float:
    p, y = np.asarray(p, dtype=float), np.asarray(y_binary, dtype=float)
    return float(np.mean((p - y) ** 2))


def expected_calibration_error(p: np.ndarray, y_binary: np.ndarray, n_bins: int = 10) -> float:
    """Weighted mean |mean predicted - observed frequency| over equal-width
    probability bins (empty bins skipped)."""
    p, y = np.asarray(p, dtype=float), np.asarray(y_binary, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(ece)


def search_threshold(cal_clf, X_val: np.ndarray, y_val: np.ndarray,
                      thresholds: np.ndarray = DEFAULT_THRESHOLDS) -> tuple[float, float]:
    """Searches, on a chronological validation slice (end of train, never the
    test set), for the threshold that forces the STRONG class (0 or 3) as
    soon as its probability exceeds it, maximizing the average of
    (F1_UP_FORT, F1_DOWN_FORT)."""
    proba = cal_clf.predict_proba(X_val)
    classes = cal_clf.classes_
    best_thr, best_score = float(thresholds[0]), -1.0
    for thr in thresholds:
        pred = []
        for row in proba:
            p_map = dict(zip(classes, row))
            if p_map.get(3, 0.0) >= thr:
                pred.append(3)
            elif p_map.get(0, 0.0) >= thr:
                pred.append(0)
            else:
                pred.append(classes[int(np.argmax(row))])
        met = metrics(y_val, np.array(pred))
        score = np.nanmean([met["F1_UP_FORT"], met["F1_DOWN_FORT"]])
        if score > best_score:
            best_score, best_thr = float(score), float(thr)
    return best_thr, best_score


def predict_with_threshold(cal_clf, X: np.ndarray, threshold: float) -> np.ndarray:
    proba = cal_clf.predict_proba(X)
    classes = cal_clf.classes_
    pred = []
    for row in proba:
        p_map = dict(zip(classes, row))
        if p_map.get(3, 0.0) >= threshold:
            pred.append(3)
        elif p_map.get(0, 0.0) >= threshold:
            pred.append(0)
        else:
            pred.append(classes[int(np.argmax(row))])
    return np.array(pred)
