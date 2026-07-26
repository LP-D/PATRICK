"""Métriques du schéma 4 classes (direction + amplitude) — reprend `metrics()` de
VIX_FINAL_ML_SCAN, avec le fix `ravel()` (bug CatBoost `unhashable numpy.ndarray`,
cf. PR #31 sur LP-D/claude) câblé dès l'origine plutôt qu'ajouté après coup.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import accuracy_score, f1_score

_DIR_MAP = {0: "DOWN", 1: "DOWN", 2: "UP", 3: "UP"}


def metrics(y_true, y_pred) -> dict:
    # [FIX] CatBoostClassifier.predict() renvoie un tableau 2D (n,1) pour le
    # multiclasse -> itérer dessus donne des sous-tableaux non hashables comme clé
    # de dict. Ravel systématique, quel que soit l'algo.
    y_true = np.asarray(y_true).ravel()
    y_pred = np.asarray(y_pred).ravel()

    yd_t = [_DIR_MAP[y] for y in y_true]
    yd_p = [_DIR_MAP[y] for y in y_pred]
    m = {
        "F1_4cls": round(f1_score(y_true, y_pred, average="macro", zero_division=0), 4),
        "Acc_dir": round(accuracy_score(yd_t, yd_p), 4),
        "F1_dir": round(f1_score(yd_t, yd_p, average="macro", zero_division=0), 4),
    }
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
