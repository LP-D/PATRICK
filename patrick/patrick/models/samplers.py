"""Registre des samplers — défaut SMOTE seul (grille des 5 variantes disponible en
option, cf. VIX_FINAL_ML_SCAN).

`"none"` (Phase 5.3) : pseudo-sampler qui ne rééchantillonne rien -- pour
comparer SMOTE (suréchantillonnage) à `class_weight="balanced"` SEUL (déjà le
défaut de LightGBM/RandomForest/CatBoost dans `models/registry.py`, pas
XGBoost/GradientBoosting qui n'ont pas d'équivalent sklearn natif). Sans cette
option, il était impossible de tester "class_weight seul" via la grille
`sampler.candidates` existante : chaque config passait forcément par un
suréchantillonneur SMOTE-famille."""
from __future__ import annotations

from imblearn.combine import SMOTEENN, SMOTETomek
from imblearn.over_sampling import ADASYN, SMOTE, BorderlineSMOTE

ALL_SAMPLERS = ("SMOTE", "BorderlineSMOTE", "ADASYN", "SMOTETomek", "SMOTEENN", "none")


class _NoResample:
    """Interface `fit_resample` minimale, sans rééchantillonnage -- laisse
    `class_weight="balanced"` (déjà réglé par défaut sur les classifieurs qui
    le supportent) faire seul le travail de rééquilibrage."""

    def fit_resample(self, X, y):
        return X, y


def get_sampler(name: str, seed: int = 42):
    registry = {
        "SMOTE": SMOTE(random_state=seed),
        "BorderlineSMOTE": BorderlineSMOTE(random_state=seed, kind="borderline-1"),
        "ADASYN": ADASYN(random_state=seed),
        "SMOTETomek": SMOTETomek(random_state=seed),
        "SMOTEENN": SMOTEENN(random_state=seed),
        "none": _NoResample(),
    }
    if name not in registry:
        raise ValueError(f"Sampler inconnu: '{name}' (attendu: {ALL_SAMPLERS})")
    return registry[name]
