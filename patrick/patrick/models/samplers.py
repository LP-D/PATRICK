"""Sampler registry — SMOTE alone by default (the grid of 5 available
variants is optional, see VIX_FINAL_ML_SCAN).

`"none"` (Phase 5.3): a pseudo-sampler that resamples nothing -- to compare
SMOTE (oversampling) against `class_weight="balanced"` ALONE (already the
default for LightGBM/RandomForest/CatBoost in `models/registry.py`, not
XGBoost/GradientBoosting which have no native sklearn equivalent). Without
this option, it was impossible to test "class_weight alone" via the
existing `sampler.candidates` grid: every config necessarily went through
a SMOTE-family oversampler."""
from __future__ import annotations

from imblearn.combine import SMOTEENN, SMOTETomek
from imblearn.over_sampling import ADASYN, SMOTE, BorderlineSMOTE

ALL_SAMPLERS = ("SMOTE", "BorderlineSMOTE", "ADASYN", "SMOTETomek", "SMOTEENN", "none")


class _NoResample:
    """Minimal `fit_resample` interface, with no resampling -- leaves
    `class_weight="balanced"` (already set by default on the classifiers
    that support it) to do the rebalancing work alone."""

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
        raise ValueError(f"Unknown sampler: '{name}' (expected: {ALL_SAMPLERS})")
    return registry[name]
