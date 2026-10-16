"""Un pli d'entraînement peut manquer d'une des quatre classes (série macro lissée) : XGBoost refusait les étiquettes [0, 2, 3], les autres
algorithmes perdaient leur AUC et leur confiance sans erreur (`y_proba[i, y_pred]` indexait par étiquette au lieu de `classes_`)."""
from __future__ import annotations

import numpy as np
import pytest

from patrick.models.registry import get_classifier
from patrick.models.xgb_labels import AnyLabelXGBClassifier
from patrick.pipeline import engine
from patrick.validation.metrics import align_proba


def _data(seed=0, n=500):
    rng = np.random.default_rng(seed)
    y_tr = rng.choice([0, 2, 3], size=n, p=[0.3, 0.4, 0.3])                 # la classe 1 est absente de l'entraînement
    X = rng.normal(size=(n, 6))
    X[y_tr == 3] += 1.0
    X[y_tr == 0] -= 1.0
    y_te = rng.choice([0, 1, 2, 3], size=240)
    Xte = rng.normal(size=(240, 6))
    Xte[y_te == 3] += 1.0
    Xte[y_te == 0] -= 1.0
    return X, y_tr, Xte, y_te


def test_xgboost_accepts_non_consecutive_labels_and_keeps_the_original_ones():
    X, y, Xte, _ = _data()
    clf = get_classifier("XGBoost", seed=0)
    assert isinstance(clf, AnyLabelXGBClassifier)
    clf.fit(X, y)
    assert list(clf.classes_) == [0, 2, 3]
    assert set(np.unique(clf.predict(Xte))) <= {0, 2, 3}
    proba = clf.predict_proba(Xte)
    assert proba.shape == (len(Xte), 3) and np.allclose(proba.sum(axis=1), 1.0)
    assert (clf.predict(Xte) == np.array(clf.classes_)[proba.argmax(axis=1)]).all()      # la colonne k est la classe classes_[k]


def test_xgboost_with_consecutive_labels_behaves_as_before():
    X, _, Xte, _ = _data()
    y = np.random.default_rng(1).choice([0, 1, 2, 3], size=len(X))
    clf = get_classifier("XGBoost", seed=0).fit(X, y)
    assert list(clf.classes_) == [0, 1, 2, 3] and clf.predict_proba(Xte).shape[1] == 4


@pytest.mark.parametrize("algo", ["XGBoost", "LightGBM", "RandomForest", "CatBoost"])
def test_a_missing_class_keeps_the_confidence_and_the_auc(algo):
    X, y_tr, Xte, y_te = _data()
    met, y_pred, confidence, p_up = engine._fit_eval_full(X, y_tr, Xte, y_te, "none", algo, 0, calibration=False)
    assert confidence is not None and len(confidence) == len(y_pred) and np.isfinite(confidence).all()
    clf = get_classifier(algo, seed=0)
    clf.fit(X, y_tr)
    proba, classes = clf.predict_proba(Xte), list(clf.classes_)
    expected = np.array([proba[i, classes.index(p)] for i, p in enumerate(y_pred)])
    assert np.allclose(confidence, expected, atol=1e-9)             # la probabilité de la classe prédite, pas celle d'une autre colonne
    assert np.isfinite(met["AUC_ovr_4cls"])                         # elle ne disparaît plus
    assert p_up is not None and len(p_up) == len(y_te)


def test_align_proba_places_each_column_on_its_class():
    out = align_proba(np.array([[0.2, 0.5, 0.3], [0.6, 0.1, 0.3]]), [0, 2, 3])
    assert out.shape == (2, 4) and out[:, 1].tolist() == [0.0, 0.0]
    assert out[0].tolist() == [0.2, 0.0, 0.5, 0.3] and np.allclose(out.sum(axis=1), 1.0)
    assert align_proba(None, [0, 1]) is None
    full = np.array([[0.1, 0.2, 0.3, 0.4]])
    assert align_proba(full, [0, 1, 2, 3]).tolist() == full.tolist()
