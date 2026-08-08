"""Metrics for the 4-class scheme (direction + amplitude) — reuses
`metrics()` from VIX_FINAL_ML_SCAN, with the `ravel()` fix (CatBoost
`unhashable numpy.ndarray` bug, see PR #31 on LP-D/claude) wired in from the
start rather than bolted on afterward.

Phase 0.7: balanced accuracy, MCC and AUC (ovr) added as primary metrics —
raw accuracy (`Acc_dir`, kept for compatibility) is misleading on imbalanced
classes (60% majority -> "80% accuracy" while learning nothing). F1_dir
remains the pipeline's ranking/tuning metric (continuity with the original
VIX project's F1_dir≈0.610 reference); balanced accuracy/MCC/AUC are always
computed and displayed alongside, never silently substituted for F1_dir.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, f1_score,
                              matthews_corrcoef, roc_auc_score)

_DIR_MAP = {0: "DOWN", 1: "DOWN", 2: "UP", 3: "UP"}
_ALL_CLASSES = [0, 1, 2, 3]


def metrics(y_true, y_pred, y_proba: np.ndarray | None = None) -> dict:
    # [FIX] CatBoostClassifier.predict() returns a 2D array (n,1) for
    # multiclass -> iterating over it gives unhashable sub-arrays as dict
    # keys. Systematic ravel, regardless of the algo.
    y_true = np.asarray(y_true).ravel()
    y_pred = np.asarray(y_pred).ravel()

    yd_t = [_DIR_MAP[y] for y in y_true]
    yd_p = [_DIR_MAP[y] for y in y_pred]
    m = {
        "F1_4cls": round(f1_score(y_true, y_pred, average="macro", zero_division=0), 4),
        "Acc_dir": round(accuracy_score(yd_t, yd_p), 4),
        "F1_dir": round(f1_score(yd_t, yd_p, average="macro", zero_division=0), 4),
        "BalAcc_4cls": round(balanced_accuracy_score(y_true, y_pred), 4),
        "MCC_4cls": round(matthews_corrcoef(y_true, y_pred), 4),
    }

    # AUC (one-vs-rest, macro): requires probabilities and at least 2 classes
    # actually present in y_true — otherwise (fold too small, rare regime)
    # NaN rather than an exception that would abort the whole scan.
    if y_proba is not None and len(np.unique(y_true)) >= 2:
        try:
            m["AUC_ovr_4cls"] = round(
                roc_auc_score(y_true, y_proba, multi_class="ovr",
                               average="macro", labels=_ALL_CLASSES),
                4,
            )
        except ValueError:
            m["AUC_ovr_4cls"] = np.nan
    else:
        m["AUC_ovr_4cls"] = np.nan

    ui = [i for i, y in enumerate(y_true) if _DIR_MAP[y] == "UP"]
    di = [i for i, y in enumerate(y_true) if _DIR_MAP[y] == "DOWN"]
    if len(ui) >= 10:
        yt = ["FORT" if y_true[i] == 3 else "FAIBLE" for i in ui]
        yp = ["FORT" if y_pred[i] == 3 else "FAIBLE" for i in ui]
        m["F1_UP_FORT"] = round(f1_score(yt, yp, pos_label="FORT", average="binary",
                                          zero_division=0), 4)
    else:
        m["F1_UP_FORT"] = np.nan
    if len(di) >= 10:
        yt = ["FORT" if y_true[i] == 0 else "FAIBLE" for i in di]
        yp = ["FORT" if y_pred[i] == 0 else "FAIBLE" for i in di]
        m["F1_DOWN_FORT"] = round(f1_score(yt, yp, pos_label="FORT", average="binary",
                                            zero_division=0), 4)
    else:
        m["F1_DOWN_FORT"] = np.nan
    return m
