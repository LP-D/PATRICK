"""Critère de sortie Phase 4.6 : `patrick predict --live` score le modèle déjà
exporté d'un run sur les données les plus récentes, écrit la prédiction dans
`prediction` (split='live', y_true NULL) AVANT de connaître le résultat, et
complète `y_true` des prédictions live passées une fois leur horizon écoulé --
sans jamais ré-entraîner ni resélectionner quoi que ce soit.
"""
from __future__ import annotations

import os
import sqlite3

import numpy as np
import pandas as pd
import pytest

from patrick import predict as predict_module
from patrick.config.schema import RunConfig
from patrick.data.store import DataStore
from patrick.pipeline import engine as engine_module

TARGET_SYMBOL = "^TEST"
HORIZON = 5


def _synthetic_raw(n=1500, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    target = 100 + np.cumsum(rng.normal(0, 0.5, n))
    df = pd.DataFrame({"IDX_TEST": target}, index=idx)
    df["SPX_LIKE"] = 3000 + np.cumsum(rng.normal(0, 5, n))
    df["NFCI"] = np.cumsum(rng.normal(0, 0.02, n))
    df["T10Y2Y"] = np.cumsum(rng.normal(0, 0.01, n))
    return df


def _extend_raw(df: pd.DataFrame, extra_days: int, seed: int) -> pd.DataFrame:
    """Prolonge `df` de `extra_days` lignes déterministes -- même préfixe
    garanti (contrairement à relancer `_synthetic_raw` avec un `n` différent),
    pour simuler "des jours passent et de nouvelles données arrivent" sans
    changer l'historique déjà vu."""
    rng = np.random.default_rng(seed)
    new_idx = pd.bdate_range(df.index[-1] + pd.tseries.offsets.BDay(1), periods=extra_days)
    last = df.iloc[-1]
    new_df = pd.DataFrame({
        "IDX_TEST": last["IDX_TEST"] + np.cumsum(rng.normal(0, 0.5, extra_days)),
        "SPX_LIKE": last["SPX_LIKE"] + np.cumsum(rng.normal(0, 5, extra_days)),
        "NFCI": last["NFCI"] + np.cumsum(rng.normal(0, 0.02, extra_days)),
        "T10Y2Y": last["T10Y2Y"] + np.cumsum(rng.normal(0, 0.01, extra_days)),
    }, index=new_idx)
    return pd.concat([df, new_df])


def _tiny_config(tmp_path) -> RunConfig:
    raw_yaml = {
        "name": "predict_live_test",
        "objective": {"target_symbol": TARGET_SYMBOL, "horizons": [HORIZON], "regimes": ["GLOBAL"]},
        "universe": {
            "yf_tickers": ["SPX_LIKE"],
            "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
            "start_date": "2015-01-01",
        },
        "features": {
            "families": ["technical", "interactions", "spike", "vol_models", "macro"],
            "interact_top_base": 15, "interact_top_pairs": 8, "interact_final_n": 6,
            "pool_prefilter": 60,
        },
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": False, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


@pytest.mark.slow  # ~69s mesuré (rapport de correction, D1) : run pipeline complet + 2 appels predict_live
def test_predict_live_writes_then_backfills_outcome(tmp_path, monkeypatch):
    raw_v1 = _synthetic_raw()
    monkeypatch.setattr(engine_module, "ingest", lambda objective, universe, store=None, force=False, data_quality=None: raw_v1)

    db_path = str(tmp_path / "patrick.db")
    store = DataStore(root=str(tmp_path / "store"))
    result = engine_module.run_pipeline(_tiny_config(tmp_path), store=store, db_path=db_path)
    assert result["model_path"] is not None

    conn = sqlite3.connect(db_path)
    run_id = conn.execute("SELECT run_id FROM run WHERE horizon = ?", (HORIZON,)).fetchone()[0]
    conn.close()

    raw_v2 = _extend_raw(raw_v1, extra_days=10, seed=1)
    monkeypatch.setattr(predict_module, "ingest", lambda objective, universe, store=None, force=False, data_quality=None: raw_v2)

    live1 = predict_module.predict_live(run_id, db_path=db_path, store=store)
    assert live1["y_pred"] in (0, 1, 2, 3)
    assert 0.0 <= live1["y_proba"] <= 1.0
    assert live1["n_outcomes_updated"] == 0  # horizon pas encore écoulé pour cette toute nouvelle prédiction

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT y_true, split FROM prediction WHERE trial_id = ? AND ts = ?",
        (live1["trial_id"], live1["ts"]),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[1] == "live"
    assert row[0] is None  # résultat pas encore connu

    raw_v3 = _extend_raw(raw_v2, extra_days=10, seed=2)
    monkeypatch.setattr(predict_module, "ingest", lambda objective, universe, store=None, force=False, data_quality=None: raw_v3)

    live2 = predict_module.predict_live(run_id, db_path=db_path, store=store)
    assert live2["n_outcomes_updated"] == 1  # la prédiction de live1 est désormais résolue

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT y_true FROM prediction WHERE trial_id = ? AND ts = ?",
        (live1["trial_id"], live1["ts"]),
    ).fetchone()
    conn.close()
    assert row[0] in (0.0, 1.0)


def test_predict_live_unknown_run_raises(tmp_path):
    with pytest.raises(ValueError):
        predict_module.predict_live("no-such-run", db_path=str(tmp_path / "patrick.db"))


def _multi_horizon_config(tmp_path) -> RunConfig:
    raw_yaml = {
        "name": "predict_live_multi_horizon_test",
        "objective": {"target_symbol": TARGET_SYMBOL, "horizons": [3, HORIZON], "regimes": ["GLOBAL"]},
        "universe": {
            "yf_tickers": ["SPX_LIKE"],
            "fred_series": {"NFCI": "NFCI", "T10Y2Y": "T10Y2Y"},
            "start_date": "2015-01-01",
        },
        "features": {
            "families": ["technical", "interactions", "spike", "vol_models", "macro"],
            "interact_top_base": 15, "interact_top_pairs": 8, "interact_final_n": 6,
            "pool_prefilter": 60,
        },
        "validation": {"n_wf_folds": 2, "min_train_frac": 0.5},
        "selection": {"method": "shap", "n_features_grid": [5, 8], "shap_sample": 200},
        "sampler": {"candidates": ["SMOTE"]},
        "models": {"algos": ["RandomForest", "XGBoost"]},
        "tuning": {"enabled": False, "top_k": 2, "n_trials": 3, "cv_splits": 2},
        "output": {"dir": str(tmp_path / "runs_multi"), "seed": 42},
    }
    return RunConfig.model_validate(raw_yaml)


@pytest.mark.slow
def test_predict_live_works_for_every_horizon_in_a_multi_horizon_run(tmp_path, monkeypatch):
    """Rapport d'audit -- confirmé : avant correction, un `patrick run`
    multi-horizons ne marquait `is_best=1` QUE sur le trial du gagnant
    global -- `predict_live(run_id)` sur le run_id d'un AUTRE horizon (table
    `run`, un run_id distinct par horizon, cf. Phase 1.2) levait
    systématiquement `ValueError("No exported model (winning trial) for run
    {run_id}.")`. `patrick predict --run-id <id> --live` était donc cassé
    pour tout horizon sauf celui du gagnant global, sur tout run
    multi-horizons -- reproduit et corrigé ici avec 2 horizons (3j, 5j)."""
    raw_v1 = _synthetic_raw()
    monkeypatch.setattr(
        engine_module, "ingest",
        lambda objective, universe, store=None, force=False, data_quality=None: raw_v1)

    db_path = str(tmp_path / "patrick_multi.db")
    store = DataStore(root=str(tmp_path / "store_multi"))
    result = engine_module.run_pipeline(_multi_horizon_config(tmp_path), store=store, db_path=db_path)
    assert set(result["model_paths"].keys()) == {3, HORIZON}

    conn = sqlite3.connect(db_path)
    run_ids = dict(conn.execute("SELECT horizon, run_id FROM run").fetchall())
    conn.close()
    assert set(run_ids.keys()) == {3, HORIZON}

    monkeypatch.setattr(
        predict_module, "ingest",
        lambda objective, universe, store=None, force=False, data_quality=None: raw_v1)

    for horizon, run_id in run_ids.items():
        live = predict_module.predict_live(run_id, db_path=db_path, store=store)
        assert live["y_pred"] in (0, 1, 2, 3)
        assert 0.0 <= live["y_proba"] <= 1.0


@pytest.mark.slow
def test_predict_live_still_works_for_legacy_pre_fix_artifact_path(tmp_path, monkeypatch):
    """Compatibilité ascendante (rapport de correction, étape 3) : un run
    exporté par l'ANCIEN code (un seul fichier `<name>_best_model.joblib`,
    sans suffixe `_h<horizon>`) doit continuer à fonctionner avec
    `predict_live` après ce correctif -- rien côté lecture (`predict.py`)
    ne redérive un chemin de fichier depuis une convention de nommage, tout
    passe par `trial.artifact_path` tel qu'enregistré à l'export. Simulé ici
    en renommant le fichier fraîchement exporté vers l'ANCIENNE convention
    et en mettant à jour `artifact_path` en conséquence, pour reproduire
    l'état d'un run historique déjà en base avant ce correctif (ces runs-là
    ne seront jamais réexportés sous la nouvelle convention)."""
    raw_v1 = _synthetic_raw()
    monkeypatch.setattr(
        engine_module, "ingest",
        lambda objective, universe, store=None, force=False, data_quality=None: raw_v1)

    db_path = str(tmp_path / "patrick_legacy.db")
    store = DataStore(root=str(tmp_path / "store_legacy"))
    config = _tiny_config(tmp_path)
    result = engine_module.run_pipeline(config, store=store, db_path=db_path)
    new_path = result["model_path"]
    assert new_path is not None and os.path.exists(new_path)

    legacy_path = os.path.join(config.output.dir, f"{config.name}_best_model.joblib")
    os.replace(new_path, legacy_path)

    conn = sqlite3.connect(db_path)
    run_id = conn.execute("SELECT run_id FROM run WHERE horizon = ?", (HORIZON,)).fetchone()[0]
    conn.execute("UPDATE trial SET artifact_path = ? WHERE run_id = ? AND is_best = 1",
                 (legacy_path, run_id))
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        predict_module, "ingest",
        lambda objective, universe, store=None, force=False, data_quality=None: raw_v1)

    live = predict_module.predict_live(run_id, db_path=db_path, store=store)
    assert live["y_pred"] in (0, 1, 2, 3)
    assert 0.0 <= live["y_proba"] <= 1.0
