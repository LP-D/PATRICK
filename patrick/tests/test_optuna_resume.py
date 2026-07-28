"""Critère de sortie Phase 3.2 : une étude Optuna persistée reprend les essais
déjà faits plutôt que de repartir de zéro (`storage_path`/`study_name`,
`patrick/tuning/optuna_runner.py`) — c'est ce qui permet à `patrick resume` de
ne pas perdre le travail de tuning déjà effectué avant une interruption.
"""
from __future__ import annotations

import optuna
from sklearn.datasets import make_classification

from patrick.tuning.optuna_runner import tune_config


def test_tune_config_resumes_from_persistent_storage(tmp_path):
    X, y = make_classification(n_samples=200, n_features=10, n_informative=6, random_state=0)
    storage_path = str(tmp_path / "optuna.db")
    study_name = "resume_test"

    tune_config(X, y, "RandomForest", "SMOTE", n_trials=3, cv_splits=2, seed=42,
                storage_path=storage_path, study_name=study_name)
    study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{storage_path}")
    assert len(study.trials) == 3

    # Même study_name, n_trials inchangé -> déjà au quota, aucun essai de plus.
    tune_config(X, y, "RandomForest", "SMOTE", n_trials=3, cv_splits=2, seed=42,
                storage_path=storage_path, study_name=study_name)
    study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{storage_path}")
    assert len(study.trials) == 3

    # n_trials augmenté -> seul le solde (2) est relancé, pas 5 nouveaux.
    tune_config(X, y, "RandomForest", "SMOTE", n_trials=5, cv_splits=2, seed=42,
                storage_path=storage_path, study_name=study_name)
    study = optuna.load_study(study_name=study_name, storage=f"sqlite:///{storage_path}")
    assert len(study.trials) == 5


def test_tune_config_without_storage_stays_in_memory(tmp_path):
    """Comportement par défaut (aucun `storage_path`) inchangé : pas de
    fichier créé, chaque appel repart d'une étude vide."""
    X, y = make_classification(n_samples=150, n_features=8, n_informative=5, random_state=1)
    best_params, best_value = tune_config(X, y, "RandomForest", "SMOTE", n_trials=2, cv_splits=2, seed=42)
    assert isinstance(best_params, dict)
    assert 0.0 <= best_value <= 1.0
    assert list(tmp_path.iterdir()) == []
