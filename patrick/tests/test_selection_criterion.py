"""Critère de sélection `selection.criterion` (AUC de direction par défaut, F1 pour les runs d'avant) et métriques de direction du moteur."""
from __future__ import annotations

import json

import numpy as np
import pytest

from patrick.config.schema import RunConfig
from patrick.pipeline import engine
from patrick.pipeline.leaderboard import Leaderboard


def _config(**selection) -> RunConfig:
    return RunConfig.model_validate({"objective": {"target_symbol": "^GSPC"}, "selection": selection})


def test_new_runs_select_by_auc_and_old_stored_runs_keep_f1():
    assert _config().selection.criterion == "AUC_dir"
    stored = json.loads(_config().model_dump_json())
    del stored["selection"]["criterion"]                                  # un run enregistré avant le champ
    assert RunConfig.from_stored_json(json.dumps(stored)).selection.criterion == "F1_dir"


def _hashed_payload(monkeypatch, config) -> str:
    """Le texte exact que `_config_hash` fait hacher pour `config`."""
    import hashlib

    seen: list[bytes] = []
    real = hashlib.sha256
    monkeypatch.setattr(engine.hashlib, "sha256", lambda data: (seen.append(data), real(data))[1])
    engine._config_hash(config)
    return seen[0].decode()


def test_the_legacy_criterion_keeps_the_hash_of_runs_that_predate_the_field(monkeypatch):
    """`F1_dir` (tout run d'avant le champ, relu par `from_stored_json`) reste hors du hachage : une reprise garde ses études Optuna."""
    assert '"criterion"' not in _hashed_payload(monkeypatch, _config(criterion="F1_dir"))
    assert '"criterion":"AUC_dir"' in _hashed_payload(monkeypatch, _config(criterion="AUC_dir"))
    both = _hashed_payload(monkeypatch, _config(criterion="F1_dir", one_se_rule=False))
    assert '"criterion"' not in both and '"one_se_rule"' not in both


def test_cpcv_keeps_f1_whatever_the_configuration_says():
    config = RunConfig.model_validate({"objective": {"target_symbol": "^GSPC"}, "validation": {"scheme": "cpcv"}})
    assert config.selection.criterion == "AUC_dir" and engine._criterion(config) == "F1_dir"
    assert engine._criterion(_config()) == "AUC_dir"


def test_the_leaderboard_ranks_on_the_criterion_and_still_carries_f1():
    board = Leaderboard()
    for fold, (f1_a, auc_a, f1_b, auc_b) in enumerate([(0.55, 0.50, 0.50, 0.58), (0.56, 0.51, 0.49, 0.57)], start=1):
        board.add(horizon=1, regime="GLOBAL", N=5, sampler="SMOTE", algo="A", fold=fold, F1_dir=f1_a, AUC_dir=auc_a)
        board.add(horizon=1, regime="GLOBAL", N=5, sampler="SMOTE", algo="B", fold=fold, F1_dir=f1_b, AUC_dir=auc_b)
    assert board.best(metric="F1_dir")["algo"] == "A"
    best = board.best(metric="AUC_dir")
    assert best["algo"] == "B" and best["F1_dir"] == pytest.approx(0.495) and best["AUC_dir"] == pytest.approx(0.575)


def test_usable_metric_falls_back_when_no_probabilities_exist():
    board = Leaderboard()
    board.add(horizon=1, regime="GLOBAL", N=5, sampler="none", algo="A", fold=1, F1_dir=0.5)
    board.add(horizon=1, regime="GLOBAL", N=5, sampler="none", algo="A", fold=2, F1_dir=0.5, AUC_dir=float("nan"))
    assert board.usable_metric("AUC_dir") == "F1_dir"
    board.add(horizon=1, regime="GLOBAL", N=5, sampler="none", algo="A", fold=3, F1_dir=0.5, AUC_dir=0.6)
    assert board.usable_metric("AUC_dir") == "AUC_dir"


def test_higher_ignores_missing_values():
    assert engine._higher({"AUC_dir": 0.6}, {"AUC_dir": 0.5}, "AUC_dir")
    assert not engine._higher({"AUC_dir": 0.4}, {"AUC_dir": 0.5}, "AUC_dir")
    assert not engine._higher({"AUC_dir": float("nan")}, {"AUC_dir": 0.5}, "AUC_dir")
    assert engine._higher({"AUC_dir": 0.4}, {"AUC_dir": float("nan")}, "AUC_dir")


def _four_class_data(n=400, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 4))
    score = X[:, 0] + 0.5 * rng.normal(size=n)
    y = np.digitize(score, np.quantile(score, [0.25, 0.5, 0.75]))
    return X, y


def test_every_evaluation_reports_the_direction_metrics():
    X, y = _four_class_data()
    met, _pred, _conf, p_up = engine._fit_eval_full(X[:300], y[:300], X[300:], y[300:], "none", "RandomForest", 1)
    assert p_up is not None
    assert {"AUC_dir", "F1_dir_p", "Acc_dir_p", "F1_dir", "Brier_up"} <= set(met)
    assert 0.55 < met["AUC_dir"] <= 1.0                                   # le signal est réel : l'AUC de direction le voit


def test_optuna_can_tune_on_the_direction_auc(tmp_path):
    from patrick.tuning.optuna_runner import tune_config

    X, y = _four_class_data(500)
    params, value = tune_config(X, y, "RandomForest", "none", n_trials=2, cv_splits=2, seed=3, criterion="AUC_dir")
    assert params and 0.5 <= value <= 1.0
