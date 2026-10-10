"""Deep learning dans le pipeline : un run complet sur données synthétiques (sans réseau) avec un MLP et un GRU, puis les garde-fous de
configuration. Même gabarit que `test_alpha_pipeline.py` : seul `ingest()` est remplacé, tout le reste tourne pour de vrai."""
from __future__ import annotations

import os
import sqlite3

import joblib
import numpy as np
import pandas as pd
import pytest

pytest.importorskip("torch")

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.models import registry
from patrick.models.deep import DeepClassifier
from patrick.pipeline import engine as engine_module


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


@pytest.mark.slow
def test_parallel_workers_get_the_run_deep_settings_and_reproduce_the_sequential_result():
    """Les processus de calcul parallèle du scan ne partagent pas l'état du parent : les réglages du run leur sont passés explicitement
    (`deep=` dans `fit_kwargs`), et un réseau à graine fixe donne les mêmes métriques quel que soit le nombre de workers."""
    from patrick.pipeline import parallel
    rng = np.random.default_rng(0)
    X = rng.normal(size=(500, 8))
    y = np.where(X[:, 0] + 0.5 * X[:, 1] > 0.4, 3, np.where(X[:, 0] > 0, 2, np.where(X[:, 1] > 0, 1, 0)))
    deep = {"epochs": 5, "hidden_size": 12, "n_layers": 1, "lookback": 4, "patience": 0, "batch_size": 64}
    tasks = [("fit_eval", (X[:400], y[:400], X[400:], y[400:], "none", algo, 42), {"deep": deep}) for algo in ("MLP", "GRU", "XGBoost")]
    seq = parallel.run_ordered(tasks, 1)
    par = parallel.run_ordered(tasks, 2)
    for (m_seq, p_seq, _c_seq), (m_par, p_par, _c_par) in zip(seq, par, strict=True):
        assert np.array_equal(p_seq, p_par)
        assert m_seq["F1_dir"] == pytest.approx(m_par["F1_dir"], abs=1e-9)
