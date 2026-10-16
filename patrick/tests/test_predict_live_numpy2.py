"""`predict_live` face à un `predict()` qui renvoie un tableau 2D (n, 1).

CatBoost (multiclasse) renvoie `np.array([[c]])` et non `np.array([c])`. Sous NumPy 2.x,
`int(model.predict(X)[0])` convertit alors un tableau de dimension 1 en scalaire, ce qui lève
`TypeError: only 0-dimensional arrays can be converted to Python scalars` : le signal du jour
n'était plus enregistré. Le modèle est un faux (pas de joblib, pas de pipeline) : seule la
conversion de la sortie de `predict()` est en cause.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sklearn.preprocessing import RobustScaler

from patrick.config.schema import RunConfig


class _CatBoostLikeModel:
    """Même forme de sortie que CatBoostClassifier.predict() en multiclasse : (n, 1)."""

    classes_ = np.array([0, 1, 2, 3])

    def predict(self, X):
        return np.array([[2]])

    def predict_proba(self, X):
        return np.array([[0.1, 0.1, 0.6, 0.2]])


def _pool(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    pool = pd.DataFrame({"TGT": 100 + np.cumsum(rng.normal(0, 1, n))}, index=idx)
    for j in range(6):
        pool[f"f{j}"] = rng.normal(0, 0.01, n)
    return pool


def test_predict_live_accepts_a_2d_predict_output(tmp_path, monkeypatch):
    from patrick import predict as predict_module
    from patrick.tracking import db as trackdb

    # Aucune écriture hors de tmp_path : base, magasin de données et caches sont temporaires.
    db_path = str(tmp_path / "patrick.db")
    monkeypatch.setenv("PATRICK_DB_PATH", db_path)
    monkeypatch.setenv("PATRICK_STORE_ROOT", str(tmp_path / "store"))

    pool = _pool()
    feature_pool = [c for c in pool.columns if c != "TGT"]
    bundle = {"model": _CatBoostLikeModel(), "scaler": RobustScaler().fit(pool[feature_pool].to_numpy()),
              "feature_pool": feature_pool, "feature_names": feature_pool[:4], "target_col": "TGT",
              "interaction_formulas": []}
    config = RunConfig.model_validate({"objective": {"target_symbol": "^TGT", "horizons": [1]},
                                       "selection": {"method": "shap", "n_features_grid": [4], "shap_sample": 100},
                                       "features": {"pool_prefilter": 10}})

    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, "s", "h", 0, 0, None)
    trackdb.create_run(conn, "r", target="^TGT", horizon=1, snapshot_id="s",
                       config_json=config.model_dump_json(), config_hash="h", git_sha="g", seed=42)
    tid = trackdb.create_trial(conn, "r", "GLOBAL", "CatBoost", "none", 4, "shap")
    trackdb.mark_best_trial(conn, tid, artifact_path=str(tmp_path / "model.joblib"))
    conn.close()

    monkeypatch.setattr(predict_module, "joblib", SimpleNamespace(load=lambda path: bundle))
    monkeypatch.setattr(predict_module, "ingest", lambda *a, **k: pool)
    monkeypatch.setattr(predict_module, "build_full_feature_pool", lambda raw, *a, **k: raw)

    out = predict_module.predict_live("r", db_path=db_path)

    assert out["y_pred"] == 2
    assert out["y_proba"] == pytest.approx(0.6)   # probabilité de la classe prédite (colonne de `classes_`)
    assert out["p_up"] == pytest.approx(0.8)      # classes 2 et 3 = hausse
