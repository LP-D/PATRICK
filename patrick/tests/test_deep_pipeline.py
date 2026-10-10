"""Deep learning dans le pipeline : un run complet sur données synthétiques (sans réseau) avec un MLP et un GRU, puis les garde-fous de
configuration. Même gabarit que `test_alpha_pipeline.py` : seul `ingest()` est remplacé, tout le reste tourne pour de vrai."""
from __future__ import annotations

import os
import sqlite3

import joblib
import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

pytest.importorskip("torch")

from patrick.config.schema import DeepConfig, RunConfig  # noqa: E402
from patrick.data.store import DataStore  # noqa: E402
from patrick.models import registry  # noqa: E402
from patrick.models.deep import DeepClassifier  # noqa: E402
from patrick.pipeline import engine as engine_module  # noqa: E402


def _raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    market = np.cumsum(rng.normal(0.0004, 0.01, n))
    df = pd.DataFrame({"IDX_TEST": 50 * np.exp(market + np.cumsum(rng.normal(0, 0.004, n)))}, index=idx)
    df["SPX_LIKE"] = 3000 * np.exp(market)
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _config(tmp_path, **models) -> RunConfig:
    return RunConfig.model_validate({
        "name": "dl_smoke",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"]},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"}, "start_date": "2015-01-01"},
        "features": {"families": ["technical", "spike", "macro"], "pool_prefilter": 60},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [6], "shap_sample": 200},
        "sampler": {"candidates": ["none"]},
        "models": {"algos": ["MLP", "GRU"],
                   "deep": {"epochs": 6, "hidden_size": 16, "n_layers": 1, "lookback": 5, "patience": 0, "batch_size": 64},
                   **models},
        "tuning": {"enabled": True, "top_k": 2, "n_trials": 2, "cv_splits": 2,
                   "optuna_bounds": {"MLP": {"hidden_size": [8, 24], "n_layers": [1, 1]}, "GRU": {"hidden_size": [8, 24], "n_layers": [1, 1],
                                                                                              "lookback": [4, 6]}}},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42}})


@pytest.mark.slow
def test_a_run_with_a_mlp_and_a_gru_goes_through_scan_tuning_holdout_and_export(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: _raw())
    db = str(tmp_path / "patrick.db")

    result = engine_module.run_pipeline(cfg, store=DataStore(root=str(tmp_path / "store")), db_path=db)

    board = result["leaderboard"]
    assert len(board) > 0 and board["F1_dir"].between(0, 1).all()
    assert {"MLP", "GRU"} <= set(board["algo"])
    assert os.path.exists(result["model_path"])
    bundle = joblib.load(result["model_path"])
    assert isinstance(bundle["model"], DeepClassifier) and bundle["model"].arch in ("MLP", "GRU")
    conn = sqlite3.connect(db)
    algos = {r[0] for r in conn.execute("SELECT DISTINCT algo FROM trial")}
    config_json = conn.execute("SELECT config_json FROM run").fetchone()[0]
    conn.close()
    assert algos <= {"MLP", "GRU"} and algos
    assert '"deep":{' in config_json and '"epochs":6' in config_json
    assert registry.get_classifier("MLP").epochs == 6                  # réglages du run restés actifs pour le processus


def test_a_run_without_torch_is_refused_before_any_download(tmp_path, monkeypatch):
    from patrick.models import deep
    monkeypatch.setattr(deep, "torch_available", lambda: False)
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: pytest.fail("aucun téléchargement avant le refus"))
    with pytest.raises(deep.DeepUnavailableError, match="PyTorch"):
        engine_module.run_pipeline(_config(tmp_path), store=DataStore(root=str(tmp_path / "store")), db_path=str(tmp_path / "p.db"))


# --------------------------------------------------------------------------- configuration


def test_a_machine_learning_config_keeps_the_exact_hash_it_had_before_deep_learning_existed():
    """Valeurs relevées avec le code d'AVANT l'ajout de `models.deep` (reprise des runs existants, noms d'études Optuna)."""
    base = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}})
    assert base.models.deep is None and base.family == "ml"
    assert engine_module._config_hash(base) == "10dbbb82cda90307"
    other = RunConfig.model_validate({"objective": {"target_symbol": "^GSPC", "horizons": [1, 5]},
                                      "models": {"algos": ["XGBoost", "LightGBM"]}, "tuning": {"n_trials": 7}})
    assert engine_module._config_hash(other) == "7c62b00dd1c4c530"
    with_deep = RunConfig.model_validate({"objective": {"target_symbol": "^VIX"}, "models": {"algos": ["MLP"], "deep": {}},
                                          "sampler": {"candidates": ["none"]}})
    assert with_deep.family == "dl" and engine_module._config_hash(with_deep) != engine_module._config_hash(base)


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
