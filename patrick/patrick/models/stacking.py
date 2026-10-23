"""Empilement (stacking) : N modèles de base DIVERS, puis un méta-modèle qui apprend à pondérer leurs probabilités.

Le nombre N de modèles de base est saisi à la main (formulaire, `models.stacking_n_models`). Ici la rigueur d'entraînement des modèles de
base est volontairement ALLÉGÉE : ni Optuna, ni sélection du meilleur, ni règle de parcimonie. Chaque modèle de base reçoit des
hyperparamètres tirés au hasard dans de larges plages, un sous-ensemble aléatoire de variables et de lignes, sa propre graine : il y a
donc de bons ET de mauvais modèles, et c'est le méta-modèle qui décide de ce qu'il vaut. Un panel uniformément « bon » n'apprendrait rien
au méta-modèle (ses entrées seraient presque identiques).

Ce qui reste strict, parce que c'est là que la fuite temporelle se produit : le méta-modèle n'est appris QUE sur des probabilités
hors-échantillon. Les lignes d'entraînement (chronologiques) sont coupées en deux par le temps : les modèles de base s'ajustent sur la
partie ancienne, prédisent la partie récente (séparées par `gap` lignes, l'horizon, pour qu'aucune fenêtre d'étiquette ne se
chevauche), et le méta-modèle apprend sur ces prédictions. Les modèles de base sont ensuite réajustés sur tout l'entraînement pour
prédire le test. Le rééchantillonnage (SMOTE…) ne touche que les lignes d'ajustement, jamais les lignes du méta-modèle.

`StackingEnsemble` a l'interface d'un classifieur scikit-learn : le moteur le traite comme un algorithme de plus (« Stacking »,
`models.registry.STACK_ALGO`) dans la grille du scan, le holdout, l'export et la prédiction en direct.
"""
from __future__ import annotations

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

STACK_ALGO = "Stacking"
STACK_BASE_ALGOS = ("XGBoost", "LightGBM", "RandomForest", "GradientBoosting", "CatBoost")

# Plages de tirage des hyperparamètres : (bas, haut, échelle log). Plus larges que `DEFAULT_OPTUNA_BOUNDS` à dessein (profondeur 1 =
# modèle faible, pris au sérieux par le méta-modèle comme le modèle fort), mais bornées en taille pour qu'un panel de N modèles reste
# abordable : 2 N ajustements par candidat de la grille.
BASE_RANGES: dict[str, dict[str, tuple[float, float, bool]]] = {
    "XGBoost": {"n_estimators": (30, 200, False), "max_depth": (1, 7, False), "learning_rate": (0.02, 0.3, True),
                "subsample": (0.5, 1.0, False), "colsample_bytree": (0.3, 1.0, False), "min_child_weight": (1, 20, False)},
    "LightGBM": {"n_estimators": (30, 200, False), "max_depth": (1, 7, False), "learning_rate": (0.02, 0.3, True),
                 "num_leaves": (4, 48, False), "min_child_samples": (5, 80, False), "subsample": (0.5, 1.0, False)},
    "RandomForest": {"n_estimators": (40, 160, False), "max_depth": (2, 10, False), "min_samples_leaf": (1, 40, False)},
    "GradientBoosting": {"n_estimators": (30, 150, False), "learning_rate": (0.02, 0.3, True), "max_depth": (1, 5, False),
                         "min_samples_leaf": (1, 40, False), "subsample": (0.5, 1.0, False)},
    "CatBoost": {"iterations": (40, 180, False), "depth": (2, 7, False), "learning_rate": (0.02, 0.3, True)},
}
INT_PARAMS = {"n_estimators", "max_depth", "num_leaves", "min_child_samples", "min_child_weight", "min_samples_leaf", "iterations",
              "depth"}
FEATURE_FRACTION = (0.4, 1.0)          # part des variables sélectionnées vue par un modèle de base
ROW_FRACTION = (0.6, 1.0)              # part des lignes d'ajustement vue par un modèle de base
MIN_ROWS = 40                          # lignes minimales de chaque côté de la coupe (ajustement / méta-modèle)
DEFAULT_OOF_FRAC = 0.3
DEFAULT_META_C = 0.1                   # méta-modèle fortement régularisé : N x 4 entrées pour quelques centaines de lignes


def draw_base_specs(n_models: int, algos, seed: int, n_features: int) -> list[dict]:
    """Les `n_models` modèles de base : `algos` en tournée, hyperparamètres, variables et lignes tirés au hasard (graine `seed`, donc
    reproductible : même N, mêmes algorithmes, même graine = même panel)."""
    algos = [a for a in algos if a in BASE_RANGES]
    if not algos:
        raise ValueError(f"l'empilement exige au moins un algorithme à arbres parmi {', '.join(STACK_BASE_ALGOS)}")
    rng = np.random.default_rng(int(seed))
    specs = []
    for i in range(int(n_models)):
        algo = algos[i % len(algos)]
        params = {}
        for name, (lo, hi, log) in BASE_RANGES[algo].items():
            value = float(np.exp(rng.uniform(np.log(lo), np.log(hi)))) if log else float(rng.uniform(lo, hi))
            params[name] = round(value) if name in INT_PARAMS else round(value, 5)
        n_cols = max(min(3, n_features), round(rng.uniform(*FEATURE_FRACTION) * n_features))
        columns = np.sort(rng.choice(n_features, size=min(n_cols, n_features), replace=False)).tolist()
        specs.append({"algo": algo, "params": params, "columns": columns, "row_frac": round(float(rng.uniform(*ROW_FRACTION)), 3),
                      "seed": int(seed) * 1009 + i})
    return specs


def _aligned_proba(model, X: np.ndarray, classes: np.ndarray) -> np.ndarray:
    """`predict_proba` de `model` réordonné sur `classes` (0 pour une classe que le modèle n'a pas vue : une tranche d'entraînement peut
    ne pas contenir les quatre classes)."""
    proba = np.asarray(model.predict_proba(X), dtype=float)
    own = list(getattr(model, "classes_", range(proba.shape[1])))
    out = np.zeros((len(X), len(classes)))
    for column, label in enumerate(own):
        position = np.flatnonzero(classes == label)
        if len(position):
            out[:, position[0]] = proba[:, column]
    return out


class StackingEnsemble(BaseEstimator, ClassifierMixin):
    is_stack = True          # `explain.py` : pas d'explication « arbres » (TreeExplainer), les valeurs de Shapley sont estimées par permutation
    window = 1               # une ligne par observation (comme `proba_function` d'un réseau sans fenêtre)

    def __init__(self, n_models: int = 12, algos=("XGBoost", "LightGBM"), seed: int = 42, sampler: str = "none", gap: int = 0,
                 oof_frac: float = DEFAULT_OOF_FRAC, meta_c: float = DEFAULT_META_C):
        self.n_models = n_models
        self.algos = algos
        self.seed = seed
        self.sampler = sampler
        self.gap = gap
        self.oof_frac = oof_frac
        self.meta_c = meta_c

    # ---- apprentissage
    def _fit_base(self, spec: dict, X: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None):
        """Un modèle de base sur la tranche (X, y) : lignes tirées, sous-ensemble de variables, rééchantillonnage, ajustement."""
        from patrick.models.registry import get_classifier
        from patrick.tuning.optuna_runner import safe_resample

        rng = np.random.default_rng(spec["seed"])
        n = len(y)
        rows = np.sort(rng.choice(n, size=max(min(MIN_ROWS, n), round(spec["row_frac"] * n)), replace=False))
        Xs, ys = X[rows][:, spec["columns"]], y[rows]
        Xs, ys = safe_resample(self.sampler, spec["seed"], Xs, ys)
        clf = get_classifier(spec["algo"], seed=spec["seed"], **spec["params"])
        if sample_weight is not None and len(Xs) == len(rows):
            try:
                clf.fit(Xs, ys, sample_weight=np.asarray(sample_weight)[rows])
                return clf
            except TypeError:
                pass
        clf.fit(Xs, ys)
        return clf

    def _base_probas(self, models, X: np.ndarray) -> list[np.ndarray]:
        return [_aligned_proba(m, X[:, spec["columns"]], self.classes_) for m, spec in zip(models, self.specs_, strict=True)]

    def _stack_inputs(self, models, X: np.ndarray) -> np.ndarray:
        return np.hstack(self._base_probas(models, X))

    def fit(self, X, y, sample_weight=None):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y).ravel()
        self.classes_ = np.unique(y)
        self.specs_ = draw_base_specs(self.n_models, self.algos, self.seed, X.shape[1])
        n = len(y)
        split = round(n * (1.0 - self.oof_frac))
        base_end = split - max(int(self.gap), 0)
        self.meta_ = None
        self.meta_scaler_ = None
        self.stacked_ = False
        if (base_end >= MIN_ROWS and n - split >= MIN_ROWS and len(np.unique(y[:base_end])) >= 2
                and len(np.unique(y[split:])) >= 2):
            weights = None if sample_weight is None else np.asarray(sample_weight)
            probe = [self._fit_base(spec, X[:base_end], y[:base_end], None if weights is None else weights[:base_end])
                     for spec in self.specs_]
            Z = self._stack_inputs(probe, X[split:])
            self.meta_scaler_ = StandardScaler().fit(Z)
            self.meta_ = LogisticRegression(C=self.meta_c, max_iter=2000).fit(self.meta_scaler_.transform(Z), y[split:])
            self.stacked_ = True
        # Les modèles de test voient tout l'entraînement ; faute de place pour un méta-modèle, ils sont simplement moyennés.
        self.models_ = [self._fit_base(spec, X, y, None if sample_weight is None else np.asarray(sample_weight))
                        for spec in self.specs_]
        return self

    # ---- inférence
    def predict_proba(self, X) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if self.meta_ is None:
            return np.mean(self._base_probas(self.models_, X), axis=0)
        raw = self.meta_.predict_proba(self.meta_scaler_.transform(self._stack_inputs(self.models_, X)))
        out = np.zeros((len(X), len(self.classes_)))
        for column, label in enumerate(self.meta_.classes_):
            out[:, int(np.flatnonzero(self.classes_ == label)[0])] = raw[:, column]
        return out

    def predict(self, X) -> np.ndarray:
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]

    def proba_function(self, _X_hist: np.ndarray, class_index: int):
        """Fonction `X (n, variables) -> probabilité de la classe d'indice `class_index`` pour `shap.PermutationExplainer` (même contrat que
        `models/deep.py`, où `_X_hist` est la fenêtre des lignes précédentes ; ici sans effet : le modèle lit une ligne à la fois)."""
        return lambda X: self.predict_proba(np.asarray(X, dtype=float))[:, class_index]

    def settings(self) -> dict:
        """Les réglages qui reconstruisent le même panel (consignés à l'export : un champion rejoué plus tard, depuis un autre run, retrouve
        SON nombre de modèles et SES algorithmes, pas ceux du run qui le rejoue)."""
        return {"n_models": int(self.n_models), "algos": [str(a) for a in self.algos], "oof_frac": float(self.oof_frac),
                "meta_c": float(self.meta_c)}


def build_stacking(seed: int = 42, **settings) -> StackingEnsemble:
    """Le classifieur d'empilement pour `registry.get_classifier` : `settings` = `n_models`, `algos`, `oof_frac`, `meta_c` (réglages du run) et,
    posés par le moteur, `sampler` et `gap` (rééchantillonneur de la grille, horizon)."""
    return StackingEnsemble(seed=seed, **settings)
