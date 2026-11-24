"""Objectif « valeur exacte » (2026-11-24) : un run complet sur données synthétiques (sans réseau), comme pour l'alpha. `ingest()` est
remplacé par un cadre synthétique ; features, walk-forward, sélection, grille, Optuna, contrôle final, export et duel tournent pour de vrai."""
from __future__ import annotations

import json
import os
import sqlite3

import joblib
import numpy as np
import pandas as pd
import pytest

from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module

pytestmark = pytest.mark.slow


def _raw(n=1500, seed=3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    macro = np.cumsum(rng.normal(0, 0.02, n))
    # la cible dérive avec un indicateur décalé : un signal faible mais réel pour la régression
    drift = 0.0006 * np.sign(np.r_[0.0, np.diff(macro)])
    df = pd.DataFrame({"IDX_TEST": 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.01, n)))}, index=idx)
    df["NFCI"] = macro
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _config(tmp_path, algos=("LightGBM", "RandomForest"), **selection) -> RunConfig:
    return RunConfig.model_validate({
        "name": "value_smoke",
        "objective": {"target_symbol": "^TEST", "horizons": [5], "regimes": ["GLOBAL"], "task": "value"},
        "universe": {"yf_tickers": [], "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"}, "start_date": "2015-01-01"},
        "features": {"families": ["technical", "macro"], "pool_prefilter": 40},
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5], "shap_sample": 150, "criterion": "IC", **selection},
        "sampler": {"candidates": ["SMOTE"]},             # remplacé par « none » : un régresseur n'a pas de classes à rééquilibrer
        "models": {"algos": list(algos)},
        "tuning": {"enabled": True, "top_k": 1, "n_trials": 2, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42}})


def test_value_config_rules(tmp_path):
    cfg = _config(tmp_path)
    assert cfg.objective.task == "value" and cfg.sampler.candidates == ["none"]
    assert cfg.objective.run_label() == "^TEST__val" and cfg.objective.raw_cache_key() == "raw_^TEST"
    with pytest.raises(ValueError, match="critères IC"):
        RunConfig.model_validate({"name": "d", "objective": {"target_symbol": "^TEST"}, "selection": {"criterion": "IC"}})
    with pytest.raises(ValueError, match="empilement"):
        RunConfig.model_validate({"name": "v", "objective": {"target_symbol": "^TEST", "task": "value"},
                                  "models": {"algos": ["XGBoost", "LightGBM"], "stacking": True}})
    # un modèle de direction garde le hachage d'avant le champ
    plain = RunConfig.model_validate({"name": "d", "objective": {"target_symbol": "^TEST"}})
    assert '"task"' not in plain.model_dump_json(exclude={"objective": {"task"}})
    assert engine_module._config_hash(plain) == engine_module._config_hash(
        RunConfig.model_validate(json.loads(plain.model_dump_json(exclude={"objective": {"task"}}))))


def test_value_pipeline_runs_end_to_end_with_its_own_label_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: _raw())
    db = str(tmp_path / "patrick.db")
    result = engine_module.run_pipeline(_config(tmp_path), store=DataStore(root=str(tmp_path / "store")), db_path=db)

    board = result["leaderboard"]
    ics = board["IC"].dropna()                                   # les lignes des baselines (repères naïfs) n'ont pas d'IC
    assert len(ics) > 0 and ics.between(-1, 1).all()
    assert board.loc[ics.index, "AUC_dir"].between(0, 1).all()    # probabilités de classes déduites des erreurs : l'aval reste commun
    assert os.path.exists(result["model_path"])
    bundle = joblib.load(result["model_path"])
    model = bundle["model"]
    assert getattr(model, "is_value_model", False) and len(model.residuals_) > 0 and "calibrator" not in bundle

    conn = sqlite3.connect(db)
    targets = {r[0] for r in conn.execute("SELECT DISTINCT target FROM run")}
    champion = conn.execute("SELECT target FROM champion").fetchall()
    holdout_ic = conn.execute("SELECT COUNT(*) FROM fold_metric WHERE split = 'holdout' AND metric = 'IC'").fetchone()[0]
    conn.close()
    assert targets == {"^TEST__val"}                              # sa propre catégorie : jamais mêlée aux modèles de direction
    assert champion and all(t == "^TEST__val" for (t,) in champion)
    assert holdout_ic >= 1


def test_value_pipeline_trains_a_deep_regressor(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: _raw(n=1100))
    cfg = _config(tmp_path, algos=("MLP",))
    cfg.models.deep = cfg.models.deep or None
    cfg.tuning.enabled = False
    result = engine_module.run_pipeline(cfg, store=DataStore(root=str(tmp_path / "store")), db_path=str(tmp_path / "patrick.db"))
    model = joblib.load(result["model_path"])["model"]
    assert model.is_value_model and type(model.model_).__name__ == "DeepRegressor"
    assert np.isfinite(model.predict_value(np.zeros((3, model.n_features_in_)))).all()


def test_live_prediction_of_a_value_champion_records_the_forecast(tmp_path, monkeypatch):
    from patrick.live import predict as predict_module

    raw_v1 = _raw()
    monkeypatch.setattr(engine_module, "ingest", lambda *a, **k: raw_v1)
    db = str(tmp_path / "patrick.db")
    store = DataStore(root=str(tmp_path / "store"))
    cfg = _config(tmp_path, algos=("LightGBM",))
    cfg.tuning.enabled = False
    engine_module.run_pipeline(cfg, store=store, db_path=db)
    conn = sqlite3.connect(db)
    run_id = conn.execute("SELECT run_id FROM run").fetchone()[0]
    conn.close()

    rng = np.random.default_rng(9)
    extra = pd.bdate_range(raw_v1.index[-1] + pd.offsets.BDay(1), periods=5)
    tail = raw_v1.iloc[[-1] * 5].set_axis(extra) * np.exp(rng.normal(0, 0.005, (5, raw_v1.shape[1])))
    raw_v2 = pd.concat([raw_v1, tail])
    monkeypatch.setattr(predict_module, "ingest", lambda *a, **k: raw_v2)
    live = predict_module.predict_live(run_id, db_path=db, store=store)
    assert live["y_pred"] in (0, 1, 2, 3)
    conn = sqlite3.connect(db)
    value = conn.execute("SELECT y_value, p_up FROM prediction WHERE split = 'live' AND trial_id = ? AND ts = ?",
                         (live["trial_id"], live["ts"])).fetchone()
    conn.close()
    assert value is not None and value[0] is not None and abs(value[0]) < 0.5 and 0 <= value[1] <= 1
