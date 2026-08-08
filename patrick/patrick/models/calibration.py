"""Isotonic calibration + causal threshold search (VIX_CALIBRATED_THRESHOLD) --
measured gain outside the STRESS regime (+0.026 F1_UP_FORT, +0.062 F1_DOWN_FORT),
but hurts during STRESS (-0.188 F1_UP_FORT): disabled by default, enable
knowingly."""
from __future__ import annotations

import numpy as np
from sklearn.calibration import CalibratedClassifierCV

from patrick.validation.metrics import metrics

DEFAULT_THRESHOLDS = np.arange(0.30, 0.71, 0.05)


def calibrate_classifier(base_clf, X_tr: np.ndarray, y_tr: np.ndarray, cv: int = 3):
    cal = CalibratedClassifierCV(base_clf, method="isotonic", cv=cv)
    cal.fit(X_tr, y_tr)
    return cal


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
