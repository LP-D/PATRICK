"""Registre des samplers — défaut SMOTE seul (grille des 5 variantes disponible en
option, cf. VIX_FINAL_ML_SCAN)."""
from __future__ import annotations

from imblearn.combine import SMOTEENN, SMOTETomek
from imblearn.over_sampling import ADASYN, SMOTE, BorderlineSMOTE

ALL_SAMPLERS = ("SMOTE", "BorderlineSMOTE", "ADASYN", "SMOTETomek", "SMOTEENN")


def get_sampler(name: str, seed: int = 42):
    registry = {
        "SMOTE": SMOTE(random_state=seed),
        "BorderlineSMOTE": BorderlineSMOTE(random_state=seed, kind="borderline-1"),
        "ADASYN": ADASYN(random_state=seed),
        "SMOTETomek": SMOTETomek(random_state=seed),
        "SMOTEENN": SMOTEENN(random_state=seed),
    }
    if name not in registry:
        raise ValueError(f"Sampler inconnu: '{name}' (attendu: {ALL_SAMPLERS})")
    return registry[name]
