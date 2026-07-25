"""Test de fumée bout-en-bout du pipeline complet, sans réseau : `ingest()` est
monkeypatché pour renvoyer des données synthétiques (le sandbox de dev n'a pas
accès à yfinance/FRED), tout le reste (features avancées, walk-forward, sélection,
grille, Optuna, export) tourne pour de vrai. La vérification avec de vraies
données (doit retrouver F1_dir≈0.610±0.025 sur `configs/examples/vix_direction.yaml`)
doit être relancée par un humain sur une machine avec accès réseau.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from marketml.config.schema import RunConfig
from marketml.data.store import DataStore
from marketml.pipeline import engine as engine_module


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 15 + np.cumsum(rng.normal(0, 0.5, n)).clip(min=-10)
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


@pytest.fixture
def tiny_config(tmp_path) -> RunConfig:
    raw_yaml = {
        "name": "smoke_test",
        "objective": {
            "target_symbol": "^TEST",
            "horizons": [3, 5],
            "regimes": ["GLOBAL"],
        },
        "universe": {
            "yf_tickers": ["SPX_LIKE"],
            "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
            "start_date": "2015-01-01",
        },
        "features": {
            "families": ["technical", "interactions", "spike", "vol_models", "macro"],
            "interact_top_base": 15,
            "interact_top_pairs": 8,
            "interact_final_n": 6,
            "pool_prefilter": 60,
        },
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": True, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


def test_pipeline_runs_end_to_end_on_synthetic_data(tiny_config, monkeypatch):
    def fake_ingest(objective, universe, store=None, force=False):
        return _synthetic_raw()

    monkeypatch.setattr(engine_module, "ingest", fake_ingest)

    result = engine_module.run_pipeline(tiny_config, store=DataStore(root=str(
        tiny_config.output.dir) + "_store"))

    board = result["leaderboard"]
    assert len(board) > 0
    assert set(["horizon", "fold", "regime", "N", "sampler", "algo", "F1_dir"]).issubset(board.columns)
    assert board["F1_dir"].between(0, 1).all()

    assert result["final_best"] is not None
    assert result["model_path"] is not None
    import os
    assert os.path.exists(result["model_path"])
