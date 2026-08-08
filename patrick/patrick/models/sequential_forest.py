"""Phase 6.2 (P6.2) -- sequential-bootstrap random forest: replaces
`sklearn.ensemble.RandomForestClassifier`'s internal uniform bootstrap
(each tree drawn independently, ignoring label overlap) with a sequential
draw that favors observations least concurrent with the draw in progress
(`models/uniqueness.py::sequential_bootstrap`).

`n_estimators` reduced by default (100, versus 200 for the standard forest,
`models/registry.py`): the sequential draw costs O(n_obs x n_bars) PER TREE
(versus O(n_obs) for a uniform bootstrap) -- a higher tree count would
remain correct but would quickly become impractical on large folds.
Accepted, documented trade-off (see the P6.2 report)."""
from __future__ import annotations

import numpy as np
from sklearn.tree import DecisionTreeClassifier

from patrick.models.uniqueness import sequential_bootstrap

DEFAULT_N_ESTIMATORS = 100


class SequentialBootstrapRandomForestClassifier:
    """Minimal `fit`/`predict`/`predict_proba` interface (not a full sklearn
    subclass -- no need for `get_params`/`clone` here, see the direct usage
    in `pipeline/engine.py::_fit_eval`)."""

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
            raise RuntimeError("model not trained (call .fit() first).")
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
