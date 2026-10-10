"""Configuration du deep learning (`DeepConfig`, `ModelsConfig.deep`, bornes Optuna des réseaux) : aucune dépendance à PyTorch, donc
exécutée partout (CI comprise). Le garde-fou du hachage de configuration protège la reprise des runs de machine learning existants."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from patrick.config.schema import DeepConfig, RunConfig
from patrick.pipeline import engine as engine_module


def _hashed_payload(config, monkeypatch) -> bytes:
    """Ce que `_config_hash` donne réellement à SHA-256 (capturé, pas recalculé : on teste l'implémentation, pas une copie)."""
    seen: list[bytes] = []
    real = engine_module.hashlib.sha256
    monkeypatch.setattr(engine_module.hashlib, "sha256", lambda data=b"": (seen.append(data), real(data))[1])
    engine_module._config_hash(config)
    return seen[0]


def test_a_machine_learning_config_hash_never_sees_the_deep_block(monkeypatch):
    """La reprise des runs existants et les noms d'études Optuna reposent sur ce hachage : un run de machine learning ne doit pas voir
    changer sa charge utile parce que `models.deep` existe (valeur `None`)."""
    base = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}})
    assert base.models.deep is None and base.family == "ml"
    payload = _hashed_payload(base, monkeypatch)
    assert b'"deep"' not in payload and b'"models":{"algos"' in payload
    # et la charge utile est exactement celle d'une configuration d'avant : la sortie complète privée de la seule clé « deep »
    assert payload == base.model_dump_json(exclude={"models": {"deep"}, "objective": {"benchmark", "benchmark_source", "target_kind",
                                                                                       "leak_guard", "alignment"}}).encode()


def test_a_deep_config_hash_includes_its_settings_and_differs_from_the_ml_one(monkeypatch):
    base = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}})
    deep = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}, "models": {"algos": ["MLP"], "deep": {}}, "sampler": {"candidates": ["none"]}})
    other = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}, "models": {"algos": ["MLP"], "deep": {"epochs": 7}},
                                      "sampler": {"candidates": ["none"]}})
    assert deep.family == "dl" and b'"deep":{' in _hashed_payload(deep, monkeypatch)
    assert len({engine_module._config_hash(c) for c in (base, deep, other)}) == 3


@pytest.mark.parametrize("bad", [{"hidden_size": 2}, {"dropout": 0.95}, {"learning_rate": 5.0}, {"epochs": 0}, {"device": "tpu"},
                                 {"class_weight": "heavy"}, {"lookback": 1}])
def test_deep_settings_outside_their_bounds_are_refused(bad):
    with pytest.raises(ValidationError):
        DeepConfig(**bad)


def test_window_models_refuse_oversamplers_and_cpcv():
    with pytest.raises(ValidationError, match="sampler"):
        RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}, "models": {"algos": ["GRU"]}, "sampler": {"candidates": ["SMOTE"]}})
    with pytest.raises(ValidationError, match="CPCV"):
        RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}, "models": {"algos": ["LSTM"]}, "sampler": {"candidates": ["none"]},
                                  "validation": {"scheme": "cpcv"}})
    # un MLP lit une ligne à la fois : SMOTE et CPCV lui sont permis
    ok = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}, "models": {"algos": ["MLP"]}, "sampler": {"candidates": ["SMOTE"]},
                                   "validation": {"scheme": "cpcv"}})
    assert ok.family == "dl"


def test_mixed_algorithm_lists_stay_in_the_machine_learning_family():
    cfg = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}, "models": {"algos": ["XGBoost", "MLP"]}})
    assert cfg.family == "ml"


def test_the_optuna_search_space_of_networks_lives_outside_the_tree_defaults():
    import optuna

    from patrick.config import defaults as D
    from patrick.tuning.optuna_runner import suggest_params
    assert not set(D.ALL_DL_ALGOS) & set(D.DEFAULT_OPTUNA_BOUNDS)           # le défaut de tout run reste inchangé
    trial = optuna.create_study().ask()
    params = suggest_params(trial, "GRU", {"GRU": {"hidden_size": [8, 10]}})
    assert set(params) == {"hidden_size", "n_layers", "dropout", "learning_rate", "weight_decay", "lookback"}
    assert 8 <= params["hidden_size"] <= 10
    assert set(suggest_params(optuna.create_study().ask(), "MLP")) == {"hidden_size", "n_layers", "dropout", "learning_rate", "weight_decay"}




def test_a_machine_learning_config_serializes_exactly_as_before_and_a_deep_one_round_trips():
    ml = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}})
    assert "deep" not in ml.model_dump()["models"] and '"deep"' not in ml.model_dump_json()
    deep = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}, "models": {"algos": ["GRU"], "deep": {"epochs": 9}},
                                     "sampler": {"candidates": ["none"]}})
    back = RunConfig.model_validate_json(deep.model_dump_json())
    assert back.models.deep.epochs == 9 and back.family == "dl"
    assert RunConfig.model_validate_json(ml.model_dump_json()).models.deep is None
