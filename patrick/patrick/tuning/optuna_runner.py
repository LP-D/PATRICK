"""Recherche d'hyperparamètres Optuna (TPE + MedianPruner, CV TimeSeriesSplit) —
méthodologie de VIX_FINAL_OPTUNA : sur ce projet, le tuning fin a amélioré 1
config sur 10 (delta moyen -0.0145) — l'essentiel du gain vient du choix
modèle/features, pas du réglage fin, mais l'étape reste utile ponctuellement.
"""
from __future__ import annotations

import numpy as np
import optuna
from sklearn.model_selection import TimeSeriesSplit

from patrick.models.registry import get_classifier
from patrick.models.samplers import get_sampler
from patrick.validation.metrics import metrics

optuna.logging.set_verbosity(optuna.logging.WARNING)


def suggest_params(trial: optuna.Trial, algo: str) -> dict:
    if algo == "XGBoost":
        return dict(
            n_estimators=trial.suggest_int("n_estimators", 100, 400),
            max_depth=trial.suggest_int("max_depth", 3, 8),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            subsample=trial.suggest_float("subsample", 0.6, 1.0),
            colsample_bytree=trial.suggest_float("colsample_bytree", 0.6, 1.0),
            min_child_weight=trial.suggest_int("min_child_weight", 1, 10),
        )
    if algo == "LightGBM":
        return dict(
            n_estimators=trial.suggest_int("n_estimators", 100, 400),
            max_depth=trial.suggest_int("max_depth", 3, 8),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            num_leaves=trial.suggest_int("num_leaves", 15, 63),
            min_child_samples=trial.suggest_int("min_child_samples", 5, 50),
            subsample=trial.suggest_float("subsample", 0.6, 1.0),
        )
    if algo == "RandomForest":
        return dict(
            n_estimators=trial.suggest_int("n_estimators", 100, 500),
            max_depth=trial.suggest_int("max_depth", 3, 10),
            min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 20),
        )
    if algo == "GradientBoosting":
        return dict(
            n_estimators=trial.suggest_int("n_estimators", 100, 400),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            max_depth=trial.suggest_int("max_depth", 3, 8),
            min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 20),
            subsample=trial.suggest_float("subsample", 0.6, 1.0),
        )
    if algo == "CatBoost":
        return dict(
            iterations=trial.suggest_int("iterations", 100, 400),
            depth=trial.suggest_int("depth", 3, 8),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
        )
    raise ValueError(f"Algo inconnu pour Optuna: '{algo}'")


def tune_config(X: np.ndarray, y: np.ndarray, algo: str, sampler_name: str,
                 n_trials: int = 100, cv_splits: int = 3, seed: int = 42,
                 storage_path: str | None = None, study_name: str | None = None) -> tuple[dict, float]:
    """`storage_path`/`study_name` (Phase 3.2, `patrick resume`) : persiste
    l'étude dans un fichier SQLite dédié (`optuna.db`, jamais `patrick.db` —
    le schéma interne d'Optuna change entre versions, ne doit pas être couplé
    aux tables métier) au lieu de la garder en mémoire. `load_if_exists=True`
    reprend une étude déjà entamée sous ce nom plutôt que d'en recréer une
    vide : un `patrick run`/`patrick resume` interrompu (worker tué,
    process/machine redémarré) qui relance le même run reprend les essais déjà
    faits pour cette config au lieu de repartir de zéro. Comportement par
    défaut (les deux None) inchangé : étude en mémoire, perdue à la fin de
    l'appel."""
    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial, algo)
        tscv = TimeSeriesSplit(n_splits=cv_splits)
        scores = []
        for i, (tr_idx, va_idx) in enumerate(tscv.split(X)):
            X_tr, X_va = X[tr_idx], X[va_idx]
            y_tr, y_va = y[tr_idx], y[va_idx]
            try:
                Xr, yr = get_sampler(sampler_name, seed).fit_resample(X_tr, y_tr)
            except Exception:
                Xr, yr = X_tr, y_tr
            clf = get_classifier(algo, seed=seed, **params)
            clf.fit(Xr, yr)
            met = metrics(y_va, clf.predict(X_va))
            scores.append(met["F1_dir"])
            trial.report(float(np.mean(scores)), i)
            if trial.should_prune():
                raise optuna.TrialPruned()
        return float(np.mean(scores))

    sampler = optuna.samplers.TPESampler(seed=seed)
    pruner = optuna.pruners.MedianPruner()
    if storage_path:
        if not study_name:
            raise ValueError("study_name requis quand storage_path est fourni (identifie l'étude à reprendre).")
        study = optuna.create_study(
            direction="maximize", sampler=sampler, pruner=pruner,
            storage=f"sqlite:///{storage_path}", study_name=study_name, load_if_exists=True,
        )
        # Compte TOUS les essais déjà en base (y compris élagués/échoués) pour
        # cette étude, pas seulement ceux de cet appel -> une reprise ne relance
        # que le solde plutôt que `n_trials` essais en plus à chaque fois.
        n_remaining = max(n_trials - len(study.trials), 0)
        if n_remaining:
            study.optimize(objective, n_trials=n_remaining, show_progress_bar=False)
    else:
        study = optuna.create_study(direction="maximize", sampler=sampler, pruner=pruner)
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return study.best_params, study.best_value
