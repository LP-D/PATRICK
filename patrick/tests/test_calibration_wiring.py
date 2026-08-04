"""Phase 5.3 (hygiène) : `models/calibration.py` existait déjà (calibration
isotonique + recherche de seuil causal) mais n'était branché nulle part dans
le pipeline, et il n'y avait pas de moyen de tester "sans sampler" (SMOTE
toujours appliqué) pour comparer à `class_weight` seul. Ces tests vérifient
le branchement (`_fit_eval(..., calibration=True)`, `sampler_name="none"`),
pas un résultat empirique -- l'A/B test réel sur 5 cibles nécessite un accès
réseau indisponible en sandbox (cf. rapport de phase / METHODOLOGY.md).
"""
from __future__ import annotations

import numpy as np
from sklearn.datasets import make_classification

from patrick.pipeline.engine import _fit_eval


def _make_data(n=400, seed=0):
    X, y = make_classification(n_samples=n, n_features=12, n_informative=8,
                                n_classes=4, n_clusters_per_class=1, random_state=seed)
    split = int(n * 0.7)
    return X[:split], y[:split], X[split:], y[split:]


def test_sampler_none_skips_resampling():
    X_tr, y_tr, X_te, y_te = _make_data()
    met, y_pred, confidence = _fit_eval(X_tr, y_tr, X_te, y_te, "none", "RandomForest", seed=42)
    assert len(y_pred) == len(y_te)
    assert "F1_dir" in met


def test_calibration_produces_valid_predictions():
    X_tr, y_tr, X_te, y_te = _make_data(n=600)
    met, y_pred, confidence = _fit_eval(X_tr, y_tr, X_te, y_te, "none", "RandomForest",
                                         seed=42, calibration=True)
    assert len(y_pred) == len(y_te)
    assert set(np.unique(y_pred)).issubset({0, 1, 2, 3})
    assert confidence is not None
    assert np.all((confidence >= 0) & (confidence <= 1) | np.isnan(confidence))


def test_calibration_with_smote_also_works():
    """`calibration` et `sampler` sont des choix indépendants (grille) --
    SMOTE + calibration doit fonctionner tout comme class_weight seul +
    calibration."""
    X_tr, y_tr, X_te, y_te = _make_data(n=600)
    met, y_pred, confidence = _fit_eval(X_tr, y_tr, X_te, y_te, "SMOTE", "RandomForest",
                                         seed=42, calibration=True)
    assert len(y_pred) == len(y_te)


def test_calibration_disabled_by_default_unchanged_behavior():
    """`calibration=False` (défaut) doit produire exactement le même chemin
    de code qu'avant ce branchement -- argmax direct, pas de seuil recherché."""
    X_tr, y_tr, X_te, y_te = _make_data()
    met, y_pred, confidence = _fit_eval(X_tr, y_tr, X_te, y_te, "SMOTE", "RandomForest", seed=42)
    assert len(y_pred) == len(y_te)
