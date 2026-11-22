"""Cible alpha, jalon 2b : un run complet sur données synthétiques (sans réseau). `ingest()` est remplacé par une
fonction qui renvoie un cadre synthétique; tout le reste (features, walk-forward, sélection, grille, Optuna, export,
baselines) tourne pour de vrai."""
from __future__ import annotations

import os
import sqlite3

import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module

pytestmark = pytest.mark.slow


def _raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    market = np.cumsum(rng.normal(0.0004, 0.01, n))
    df = pd.DataFrame({"SPX_LIKE": 3000 * np.exp(market)}, index=idx)
    df["IDX_TEST"] = 50 * np.exp(1.4 * market + np.cumsum(rng.normal(0, 0.006, n)))   # β ≈ 1,4 sur le « marché »
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _config(tmp_path, **objective) -> RunConfig:
    return RunConfig.model_validate({
        "name": "alpha_smoke",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"], "target_kind": "alpha",
                      "benchmark": "SPX_LIKE", **objective},
        "universe": {"yf_tickers": ["SPX_LIKE"], "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
                     "start_date": "2015-01-01"},
        "features": {"families": ["technical", "interactions", "spike", "vol_models", "macro"],
                     "interact_top_base": 15, "interact_top_pairs": 8, "interact_final_n": 6, "pool_prefilter": 60},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": True, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42}})


def test_alpha_pipeline_runs_end_to_end_and_keeps_its_own_label(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: _raw())
    db = str(tmp_path / "patrick.db")

    result = engine_module.run_pipeline(cfg, store=DataStore(root=str(tmp_path / "store")), db_path=db)

    assert len(result["leaderboard"]) > 0 and result["leaderboard"]["F1_dir"].between(0, 1).all()
    assert os.path.exists(result["model_path"])
    conn = sqlite3.connect(db)
    targets = {r[0] for r in conn.execute("SELECT DISTINCT target FROM run")}
    registry = {r[0] for r in conn.execute("SELECT DISTINCT target FROM trial_registry")}
    config_json = conn.execute("SELECT config_json FROM run").fetchone()[0]
    conn.close()
    assert targets == {"^TEST__alpha_SPX_LIKE"}                   # jamais le symbole nu
    assert registry == {"^TEST__alpha_SPX_LIKE"}                  # le registre d'essais (DSR) a sa propre famille
    assert '"target_kind":"alpha"' in config_json and '"benchmark":"SPX_LIKE"' in config_json


def test_alpha_baselines_are_computed_on_the_alpha_level_not_on_the_price(tmp_path, monkeypatch):
    """Les baselines de prix (momentum, marche aléatoire, HAR-RV) d'une cible alpha doivent lire le niveau d'alpha."""
    from patrick.validation import baselines as bl
    seen: list[pd.Series] = []
    real = bl.compute_baselines

    def spy(price_series, *a, **k):
        seen.append(price_series.copy())
        return real(price_series, *a, **k)

    monkeypatch.setattr(engine_module, "compute_baselines", spy)
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: _raw())
    engine_module.run_pipeline(_config(tmp_path), store=DataStore(root=str(tmp_path / "store")),
                               db_path=str(tmp_path / "patrick.db"))

    assert seen
    raw = _raw()
    assert not any(np.allclose(s.dropna().values[:50], raw["IDX_TEST"].values[:50]) for s in seen)   # pas le prix brut
    assert all(abs(float(s.iloc[0]) - 100.0) < 1e-9 for s in seen)                                    # niveau d'alpha : base 100
