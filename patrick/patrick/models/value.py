"""Objectif « valeur exacte » (2026-11-24) : prédire le rendement de la cible à l'horizon, pas sa classe.

Intégré au pipeline comme une variante du modèle, pas comme un moteur à part : `ValueModel` est un régresseur (arbres ou réseau) qui
expose aussi `predict_proba` sur les 4 classes habituelles. Ces probabilités viennent de la distribution de ses ERREURS HORS ÉCHANTILLON
(prévision conforme par découpage) : on ajuste d'abord le régresseur sur le début de l'entraînement, on mesure ses erreurs sur la fin
(après un trou de `gap` lignes : le recouvrement des labels à horizon h), puis on le réajuste sur tout l'entraînement. Pour une ligne,
P(classe k) = part des erreurs e telles que « rendement prédit + e » tombe dans l'intervalle de la classe k (bornes q25 / 0 / q75 de son
régime, `features/target.py`). Tout l'aval (prédictions, baselines, Diebold-Mariano, duels de champions, signaux live) lit donc ces
modèles comme les autres, et leurs mesures de direction (AUC, Brier) restent comparables -- en plus de leurs mesures propres :

- `IC` : corrélation de rang (Spearman) entre rendement prédit et réalisé -- le critère de classement par défaut ;
- `R2_oos` : 1 − Σ(r − r̂)² / Σ r², la part de l'erreur quadratique gagnée sur la prévision « rendement nul » (> 0 : bat la marche
  aléatoire ; Campbell et Thompson, 2008) ;
- `MAE`, `RMSE` (en points de rendement) et `Hit_sign` (part des signes justes, lignes nulles exclues).

Le rééchantillonnage (SMOTE...) et l'empilement n'existent pas pour cet objectif (`RunConfig._check_value_task`) ; la sélection de
variables et la découverte d'interactions restent celles du run (sur les classes de direction) : documenté comme une simplification.
"""
from __future__ import annotations

import numpy as np
from scipy.stats import spearmanr
from sklearn.base import BaseEstimator

from patrick.models import calibration as calibration_lib
from patrick.models import registry

CLASSES = np.array([0, 1, 2, 3])
RESIDUAL_FRAC = 0.25          # part de l'entraînement (la fin) qui mesure les erreurs hors échantillon
MAX_RESIDUALS = 2000          # au-delà, les plus récentes (mémoire n x m de `predict_proba`)
PSEUDO_COUNT = 0.5            # lissage : aucune classe à probabilité exactement nulle (log-loss, Brier)
VALUE_METRICS = ("IC", "R2_oos", "MAE", "RMSE", "Hit_sign")

_DROP_FOR_REGRESSION = ("sampler", "gap", "class_weight", "auto_class_weights", "eval_metric", "objective", "loss_function", "stack")


def get_regressor(algo: str, seed: int = 42, **overrides):
    """Régresseur de l'algorithme `algo`, mêmes hyperparamètres par défaut que le classifieur du même nom (`models/registry.py`)."""
    deep = overrides.pop("deep", None)
    overrides = {k: v for k, v in overrides.items() if k not in _DROP_FOR_REGRESSION}
    if algo in registry.DL_ALGOS:
        from patrick.models.deep import build_deep_regressor
        return build_deep_regressor(algo, seed=seed, **{**registry._DEEP_ACTIVE, **(deep or {}), **overrides})
    n_jobs = registry.MODEL_N_JOBS
    if algo == "XGBoost":
        from xgboost import XGBRegressor
        params = {"n_estimators": 200, "max_depth": 4, "learning_rate": 0.05, "subsample": 0.8, "colsample_bytree": 0.8,
                  "min_child_weight": 3, "objective": "reg:pseudohubererror", "random_state": seed, "n_jobs": n_jobs, "verbosity": 0}
        params.update(overrides)
        return XGBRegressor(**params)
    if algo == "LightGBM":
        from lightgbm import LGBMRegressor
        params = {"n_estimators": 200, "max_depth": 5, "learning_rate": 0.05, "num_leaves": 31, "min_child_samples": 10,
                  "subsample": 0.8, "objective": "huber", "random_state": seed, "verbose": -1, "n_jobs": n_jobs}
        params.update(overrides)
        return LGBMRegressor(**params)
    if algo == "RandomForest":
        from sklearn.ensemble import RandomForestRegressor
        params = {"n_estimators": 200, "max_depth": 6, "min_samples_leaf": 5, "random_state": seed, "n_jobs": n_jobs}
        params.update(overrides)
        return RandomForestRegressor(**params)
    if algo == "GradientBoosting":
        from sklearn.ensemble import GradientBoostingRegressor
        params = {"n_estimators": 200, "learning_rate": 0.05, "max_depth": 4, "min_samples_leaf": 10, "subsample": 0.8,
                  "loss": "huber", "random_state": seed}
        params.update(overrides)
        return GradientBoostingRegressor(**params)
    if algo == "CatBoost":
        from catboost import CatBoostRegressor
        params = {"iterations": 200, "depth": 6, "learning_rate": 0.05, "loss_function": "RMSE", "random_state": seed,
                  "verbose": False, "allow_writing_files": False, "thread_count": n_jobs}
        params.update(overrides)
        return CatBoostRegressor(**params)
    raise ValueError(f"Algorithme sans version « valeur exacte » : '{algo}'")


def _fit(model, X, r, sample_weight):
    if sample_weight is not None and len(sample_weight) == len(X):
        try:
            return model.fit(X, r, sample_weight=sample_weight)
        except TypeError:
            pass
    return model.fit(X, r)


def class_proba(r_hat: np.ndarray, residuals: np.ndarray, lo, hi) -> np.ndarray:
    """Probabilités (n, 4) des classes DOWN_FORT / DOWN_FAIBLE / UP_FAIBLE / UP_FORT d'un rendement prédit `r_hat`, d'après la
    distribution des erreurs `residuals` ; `lo` / `hi` : bornes q25 / q75 de chaque ligne (scalaires ou tableaux de longueur n)."""
    r_hat = np.asarray(r_hat, dtype=float).ravel()
    res = np.sort(np.asarray(residuals, dtype=float).ravel())
    lo = np.broadcast_to(np.asarray(lo, dtype=float), r_hat.shape)
    hi = np.broadcast_to(np.asarray(hi, dtype=float), r_hat.shape)
    m = len(res)
    if m == 0:
        out = np.zeros((len(r_hat), 4))
        out[np.arange(len(r_hat)), np.searchsorted([0.0, 0.0, 0.0], r_hat)] = 1.0
        return out

    def below(x):                                    # nombre d'erreurs e avec r_hat + e < x
        return np.searchsorted(res, x - r_hat, side="left").astype(float)

    c_lo, c_0, c_hi = below(lo), below(np.zeros_like(r_hat)), below(hi)
    # Mêmes règles que `features/target.py::classify`, y compris les cas dégénérés (q25 > 0 ou q75 < 0) : chaque erreur dans une seule classe.
    top_0 = np.maximum(c_0, c_lo)
    top = np.maximum(c_hi, top_0)
    counts = np.stack([c_lo, np.maximum(c_0 - c_lo, 0), np.maximum(c_hi - top_0, 0), m - top], axis=1)
    counts = counts + PSEUDO_COUNT
    return counts / counts.sum(axis=1, keepdims=True)


class ValueModel(BaseEstimator):
    """Régresseur du rendement à l'horizon + distribution de ses erreurs hors échantillon (voir le module)."""

    is_value_model = True

    def __init__(self, algo: str = "LightGBM", seed: int = 42, params: dict | None = None):
        self.algo = algo
        self.seed = seed
        self.params = params

    # Les réseaux à fenêtre lisent des lignes consécutives : le suivi live et le pipeline le savent par ces deux attributs.
    @property
    def needs_history(self) -> bool:
        return bool(getattr(getattr(self, "model_", None), "needs_history", False))

    @property
    def window(self) -> int:
        return int(getattr(getattr(self, "model_", None), "window", 1))

    def fit(self, X, y=None, r=None, sample_weight=None, gap: int = 0):
        """`y` : classes de direction (non utilisées, mais gardées pour l'interface) ; `r` : rendements à l'horizon (obligatoire)."""
        if r is None:
            raise ValueError("ValueModel.fit exige les rendements à l'horizon (r)")
        X = np.asarray(X, dtype=float)
        r = np.asarray(r, dtype=float).ravel()
        params = dict(self.params or {})
        split = calibration_lib.calibration_split(len(X), frac=RESIDUAL_FRAC, gap=gap)
        if split is not None:
            probe = get_regressor(self.algo, seed=self.seed, **params)
            sw = None if sample_weight is None else np.asarray(sample_weight)[:split.fit_end]
            _fit(probe, X[:split.fit_end], r[:split.fit_end], sw)
            residuals = r[split.cal_start:] - np.asarray(probe.predict(X[split.cal_start:])).ravel()
            self.residuals_in_sample_ = False
        self.model_ = get_regressor(self.algo, seed=self.seed, **params)
        _fit(self.model_, X, r, sample_weight)
        if split is None:                      # entraînement trop court pour un découpage : erreurs en échantillon (optimistes), signalé
            residuals = r - np.asarray(self.model_.predict(X)).ravel()
            self.residuals_in_sample_ = True
        residuals = residuals[np.isfinite(residuals)]
        self.residuals_ = residuals[-MAX_RESIDUALS:].astype(np.float64)
        self.classes_ = CLASSES
        q = np.nanquantile(r, [0.25, 0.75]) if len(r) else np.array([0.0, 0.0])
        self.bounds_ = (float(min(q[0], 0.0)), float(max(q[1], 0.0)))   # bornes de repli quand l'appelant n'en donne pas
        self.n_features_in_ = X.shape[1]
        return self

    def predict_value(self, X, context: str = "train") -> np.ndarray:
        if self.needs_history:
            return np.asarray(self.model_.predict(X, context=context), dtype=float).ravel()
        return np.asarray(self.model_.predict(X), dtype=float).ravel()

    def predict_proba(self, X, bounds=None, context: str = "train") -> np.ndarray:
        lo, hi = bounds if bounds is not None else self.bounds_
        return class_proba(self.predict_value(X, context=context), self.residuals_, lo, hi)

    def predict(self, X, bounds=None, context: str = "train") -> np.ndarray:
        return CLASSES[np.argmax(self.predict_proba(X, bounds=bounds, context=context), axis=1)]

    def interval(self, X, coverage: float = 0.8, context: str = "train") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """`(prévision, borne basse, borne haute)` de l'intervalle de prévision à `coverage` (quantiles des erreurs hors échantillon)."""
        r_hat = self.predict_value(X, context=context)
        a = (1 - coverage) / 2
        lo, hi = np.quantile(self.residuals_, [a, 1 - a]) if len(self.residuals_) else (0.0, 0.0)
        return r_hat, r_hat + lo, r_hat + hi


def value_metrics(r_true, r_hat) -> dict:
    """Mesures propres à la valeur exacte (voir le module) ; `None` quand elles ne se calculent pas (trop peu de lignes, constantes)."""
    r_true = np.asarray(r_true, dtype=float).ravel()
    r_hat = np.asarray(r_hat, dtype=float).ravel()
    ok = np.isfinite(r_true) & np.isfinite(r_hat)
    r_true, r_hat = r_true[ok], r_hat[ok]
    out = {k: None for k in VALUE_METRICS}
    if len(r_true) < 3:
        return out
    err = r_true - r_hat
    out["MAE"] = float(np.mean(np.abs(err)))
    out["RMSE"] = float(np.sqrt(np.mean(err ** 2)))
    denom = float(np.sum(r_true ** 2))
    out["R2_oos"] = float(1 - np.sum(err ** 2) / denom) if denom > 0 else None
    if np.std(r_hat) > 0 and np.std(r_true) > 0:
        ic = spearmanr(r_hat, r_true).statistic
        out["IC"] = float(ic) if np.isfinite(ic) else None
    nz = (r_true != 0) & (r_hat != 0)
    out["Hit_sign"] = float(np.mean(np.sign(r_true[nz]) == np.sign(r_hat[nz]))) if nz.any() else None
    return out
