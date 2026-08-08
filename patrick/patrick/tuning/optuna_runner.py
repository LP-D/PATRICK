"""Optuna hyperparameter search (TPE + MedianPruner, TimeSeriesSplit CV) —
VIX_FINAL_OPTUNA methodology: on this project, fine tuning improved 1 config
out of 10 (average delta -0.0145) — most of the gain comes from model/
feature choice, not fine tuning, but the step remains occasionally useful.
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
    raise ValueError(f"Unknown algo for Optuna: '{algo}'")


def tune_config(X: np.ndarray, y: np.ndarray, algo: str, sampler_name: str,
                 n_trials: int = 100, cv_splits: int = 3, seed: int = 42,
                 storage_path: str | None = None, study_name: str | None = None) -> tuple[dict, float]:
    """`storage_path`/`study_name` (Phase 3.2, `patrick resume`): persists
    the study in a dedicated SQLite file (`optuna.db`, never `patrick.db` —
    Optuna's internal schema changes between versions, must not be coupled
    to the business tables) instead of keeping it in memory.
    `load_if_exists=True` resumes a study already started under this name
    rather than recreating an empty one: an interrupted `patrick run`/
    `patrick resume` (worker killed, process/machine restarted) that
    relaunches the same run resumes the trials already done for this config
    instead of starting from zero. Default behavior (both None) unchanged:
    in-memory study, lost at the end of the call."""
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
            raise ValueError("study_name required when storage_path is provided (identifies the study to resume).")
        study = optuna.create_study(
            direction="maximize", sampler=sampler, pruner=pruner,
            storage=f"sqlite:///{storage_path}", study_name=study_name, load_if_exists=True,
        )
        # Counts ALL trials already in the database (including pruned/failed)
        # for this study, not just this call's -> a resume only relaunches
        # the remaining balance rather than `n_trials` extra trials every time.
        n_remaining = max(n_trials - len(study.trials), 0)
        if n_remaining:
            study.optimize(objective, n_trials=n_remaining, show_progress_bar=False)
    else:
        study = optuna.create_study(direction="maximize", sampler=sampler, pruner=pruner)
        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    return study.best_params, study.best_value
