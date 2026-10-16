"""`XGBClassifier` qui accepte des étiquettes non consécutives.

XGBoost exige que les étiquettes d'entraînement soient exactement 0..K-1 (`Invalid classes inferred from unique values of y. Expected:
[0 1 2], got [0 2 3]`). Or un pli d'entraînement peut très bien ne contenir que trois des quatre classes (série lissée ou publiée
chaque mois : la classe « baisse faible » y est vide) : le run entier plantait, y compris dans les pilotes de sélection de variables.

Ici les étiquettes sont encodées avant l'ajustement et décodées à la prédiction ; `classes_` redonne les étiquettes d'origine, dans l'ordre
des colonnes de `predict_proba`, comme le font les autres algorithmes (LightGBM, RandomForest, CatBoost)."""
from __future__ import annotations

import numpy as np
from xgboost import XGBClassifier


class AnyLabelXGBClassifier(XGBClassifier):
    _label_classes = None
    _fitting = False

    @property
    def classes_(self) -> np.ndarray:
        if self._label_classes is not None and not self._fitting:
            return self._label_classes
        return np.arange(self.n_classes_)

    def fit(self, X, y, **kwargs):
        y = np.asarray(y).ravel()
        self._label_classes = np.unique(y)
        encoded = np.searchsorted(self._label_classes, y)
        self._fitting = True                      # XGBoost vérifie ses propres `classes_` (0..K-1) pendant l'ajustement
        try:
            super().fit(X, encoded, **kwargs)
        finally:
            self._fitting = False
        return self

    def predict(self, X, **kwargs):
        encoded = np.asarray(super().predict(X, **kwargs)).astype(int).ravel()
        return self._label_classes[encoded]
