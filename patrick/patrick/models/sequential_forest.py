"""Phase 6.2 (P6.2) -- forêt aléatoire à bootstrap séquentiel : remplace le
bootstrap uniforme interne de `sklearn.ensemble.RandomForestClassifier`
(chaque arbre tiré indépendamment, ignorant le chevauchement des labels) par
un tirage séquentiel qui favorise les observations les moins concurrentes
avec le tirage en cours (`models/uniqueness.py::sequential_bootstrap`).

`n_estimators` réduit par défaut (100, contre 200 pour la forêt standard,
`models/registry.py`) : le tirage séquentiel coûte O(n_obs x n_bars) PAR
ARBRE (contre O(n_obs) pour un bootstrap uniforme) -- un nombre d'arbres plus
élevé resterait correct mais deviendrait rapidement impraticable sur de
grands folds. Compromis assumé, documenté (cf. rapport P6.2)."""
from __future__ import annotations

import numpy as np
from sklearn.tree import DecisionTreeClassifier

from patrick.models.uniqueness import sequential_bootstrap

DEFAULT_N_ESTIMATORS = 100


class SequentialBootstrapRandomForestClassifier:
    """Interface minimale compatible `fit`/`predict`/`predict_proba` (pas un
    sous-classement sklearn complet -- pas besoin de `get_params`/`clone`
    ici, cf. usage direct dans `pipeline/engine.py::_fit_eval`)."""

    def __init__(self, n_estimators: int = DEFAULT_N_ESTIMATORS, max_depth: int = 6,
                 min_samples_leaf: int = 5, max_features: str | int | float = "sqrt",
                 seed: int = 42):
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.max_features = max_features
        self.seed = seed
        self.trees_: list[DecisionTreeClassifier] = []
        self.classes_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray, ind_matrix: np.ndarray,
            sample_weight: np.ndarray | None = None) -> "SequentialBootstrapRandomForestClassifier":
        self.classes_ = np.unique(y)
        self.trees_ = []
        rng = np.random.default_rng(self.seed)
        for _ in range(self.n_estimators):
            phi = sequential_bootstrap(ind_matrix, sample_length=len(y), rng=rng)
            Xb, yb = X[phi], y[phi]
            wb = sample_weight[phi] if sample_weight is not None else None
            tree = DecisionTreeClassifier(
                max_depth=self.max_depth, min_samples_leaf=self.min_samples_leaf,
                max_features=self.max_features,
                random_state=int(rng.integers(0, 2**31 - 1)),
            )
            tree.fit(Xb, yb, sample_weight=wb)
            self.trees_.append(tree)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if not self.trees_:
            raise RuntimeError("modèle non entraîné (appeler .fit() d'abord).")
        n_classes = len(self.classes_)
        probs = np.zeros((X.shape[0], n_classes))
        for tree in self.trees_:
            tree_proba = tree.predict_proba(X)
            aligned = np.zeros((X.shape[0], n_classes))
            for col, cls in enumerate(tree.classes_):
                aligned[:, np.searchsorted(self.classes_, cls)] = tree_proba[:, col]
            probs += aligned
        return probs / len(self.trees_)

    def predict(self, X: np.ndarray) -> np.ndarray:
        proba = self.predict_proba(X)
        return self.classes_[np.argmax(proba, axis=1)]
