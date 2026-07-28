"""Métriques du schéma 4 classes (direction + amplitude) — reprend `metrics()` de
VIX_FINAL_ML_SCAN, avec le fix `ravel()` (bug CatBoost `unhashable numpy.ndarray`,
cf. PR #31 sur LP-D/claude) câblé dès l'origine plutôt qu'ajouté après coup.

Phase 0.7 : balanced accuracy, MCC et AUC (ovr) ajoutées comme métriques
primaires — l'accuracy brute (`Acc_dir`, conservée pour compatibilité) est
trompeuse sur des classes déséquilibrées (majoritaire à 60% -> "80% accuracy" sans
rien apprendre). F1_dir reste la métrique de tri/tuning du pipeline (continuité
avec la référence F1_dir≈0.610 du projet VIX d'origine) ; balanced accuracy/MCC/AUC
sont calculées systématiquement et affichées à côté, pas silencieusement
substituées à F1_dir.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, f1_score,
                              matthews_corrcoef, roc_auc_score)

_DIR_MAP = {0: "DOWN", 1: "DOWN", 2: "UP", 3: "UP"}
_ALL_CLASSES = [0, 1, 2, 3]


def metrics(y_true, y_pred, y_proba: np.ndarray | None = None) -> dict:
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
        "BalAcc_4cls": round(balanced_accuracy_score(y_true, y_pred), 4),
        "MCC_4cls": round(matthews_corrcoef(y_true, y_pred), 4),
    }

    # AUC (one-vs-rest, macro) : nécessite des probabilités et au moins 2 classes
    # réellement présentes dans y_true — sinon (fold trop petit, régime rare) NaN
    # plutôt qu'une exception qui interromprait tout le scan.
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
