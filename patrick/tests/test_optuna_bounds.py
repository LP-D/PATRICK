"""Phase 1 (feature/hyperparams-ui) : la grille de recherche Optuna (bornes
par hyperparametre, `tuning/optuna_runner.py::suggest_params`) etait fixee en
dur, sans aucune surface de configuration -- ni dans `RunConfig`, ni dans le
formulaire web (`webapp/forms.py`/`index.html` exposent deja `n_trials`/
`top_k`/`cv_splits`/`algos`, mais jamais les bornes [low, high] de chaque
hyperparametre a l'interieur d'un algo donne). Ce test verifie que ces bornes
sont desormais parametrables (argument `bounds`, `RunConfig.tuning.
optuna_bounds`) sans changer le comportement PAR DEFAUT : un run existant qui
ne personnalise rien doit tuner EXACTEMENT le meme espace de recherche
qu'avant (`D.DEFAULT_OPTUNA_BOUNDS` == les valeurs historiquement codees en
dur)."""
from __future__ import annotations

import optuna
import pytest
from sklearn.datasets import make_classification

from patrick.config import defaults as D
from patrick.tuning.optuna_runner import suggest_params, tune_config


def _trial(seed: int) -> optuna.Trial:
    study = optuna.create_study(sampler=optuna.samplers.TPESampler(seed=seed))
    return study.ask()


def test_default_bounds_match_the_ranges_historically_hardcoded_in_suggest_params():
    """Fige les valeurs par defaut : si ce test casse, un run qui ne touche
    pas aux bornes changerait quand meme de comportement."""
    assert D.DEFAULT_OPTUNA_BOUNDS["XGBoost"] == {
        "n_estimators": [100, 400], "max_depth": [3, 8], "learning_rate": [0.01, 0.2],
        "subsample": [0.6, 1.0], "colsample_bytree": [0.6, 1.0], "min_child_weight": [1, 10],
    }
    assert D.DEFAULT_OPTUNA_BOUNDS["LightGBM"] == {
        "n_estimators": [100, 400], "max_depth": [3, 8], "learning_rate": [0.01, 0.2],
        "num_leaves": [15, 63], "min_child_samples": [5, 50], "subsample": [0.6, 1.0],
    }
    assert D.DEFAULT_OPTUNA_BOUNDS["RandomForest"] == {
        "n_estimators": [100, 500], "max_depth": [3, 10], "min_samples_leaf": [1, 20],
    }
    assert D.DEFAULT_OPTUNA_BOUNDS["GradientBoosting"] == {
        "n_estimators": [100, 400], "learning_rate": [0.01, 0.2], "max_depth": [3, 8],
        "min_samples_leaf": [1, 20], "subsample": [0.6, 1.0],
    }
    assert D.DEFAULT_OPTUNA_BOUNDS["CatBoost"] == {
        "iterations": [100, 400], "depth": [3, 8], "learning_rate": [0.01, 0.2],
    }


@pytest.mark.parametrize("algo", list(D.OPTUNA_PARAM_SPECS))
def test_suggest_params_without_bounds_argument_stays_within_default_range(algo):
    """Comportement par defaut (aucun `bounds` fourni) inchange."""
    for seed in range(5):
        params = suggest_params(_trial(seed), algo)
        for name, value in params.items():
            lo, hi = D.DEFAULT_OPTUNA_BOUNDS[algo][name]
            assert lo <= value <= hi, f"{algo}.{name}={value} hors [{lo}, {hi}]"


def test_suggest_params_respects_custom_narrow_bounds():
    bounds = {"RandomForest": {"n_estimators": [50, 55], "max_depth": [4, 4], "min_samples_leaf": [2, 2]}}
    for seed in range(5):
        params = suggest_params(_trial(seed), "RandomForest", bounds=bounds)
        assert 50 <= params["n_estimators"] <= 55
        assert params["max_depth"] == 4
        assert params["min_samples_leaf"] == 2


def test_suggest_params_partial_override_falls_back_to_default_for_untouched_params():
    """Un override qui ne precise qu'UN sous-ensemble des hyperparametres
    d'un algo (ici seulement n_estimators pour XGBoost) laisse les autres a
    leur borne par defaut plutot que de planter ou de les mettre a zero."""
    bounds = {"XGBoost": {"n_estimators": [150, 150]}}
    params = suggest_params(_trial(0), "XGBoost", bounds=bounds)
    assert params["n_estimators"] == 150
    lo, hi = D.DEFAULT_OPTUNA_BOUNDS["XGBoost"]["max_depth"]
    assert lo <= params["max_depth"] <= hi


def test_suggest_params_unknown_algo_still_raises():
    with pytest.raises(ValueError):
        suggest_params(_trial(0), "NotAnAlgo")


def test_tune_config_forwards_bounds_to_the_search():
    X, y = make_classification(n_samples=150, n_features=8, n_informative=5, random_state=1)
    bounds = {"RandomForest": {"n_estimators": [30, 32], "max_depth": [2, 2], "min_samples_leaf": [3, 3]}}
    best_params, best_value = tune_config(
        X, y, "RandomForest", "SMOTE", n_trials=3, cv_splits=2, seed=42, bounds=bounds)
    assert 30 <= best_params["n_estimators"] <= 32
    assert best_params["max_depth"] == 2
    assert best_params["min_samples_leaf"] == 3
    assert 0.0 <= best_value <= 1.0


def test_tune_config_without_bounds_argument_stays_in_default_range():
    """Non-regression explicite pour l'appelant existant
    (`pipeline/engine.py`) qui n'a pas encore ete adapte pour passer
    `bounds=` : le comportement par defaut doit rester exactement celui
    d'avant ce changement."""
    X, y = make_classification(n_samples=150, n_features=8, n_informative=5, random_state=1)
    best_params, _ = tune_config(X, y, "RandomForest", "SMOTE", n_trials=2, cv_splits=2, seed=42)
    lo, hi = D.DEFAULT_OPTUNA_BOUNDS["RandomForest"]["n_estimators"]
    assert lo <= best_params["n_estimators"] <= hi
