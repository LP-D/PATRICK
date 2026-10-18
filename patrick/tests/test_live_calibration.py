"""P(hausse) du jour réellement calibrée.

Constat (2026-10-18) : la calibration (`models.calibration`) ne touchait que les prédictions du walk-forward ; le modèle exporté,
refit sur tout l'historique, n'était pas calibré, donc la `p_up` écrite par `predict_live` était un score brut (et, avec SMOTE,
sur de mauvaises probabilités de base). L'export ajoute désormais un calibrateur, ajusté comme dans le walk-forward (ajustement |
trou | calibration sur des lignes réelles, jamais les lignes rééchantillonnées), que `predict_live` applique à `p_up` et signale
(`prediction.p_up_calibrated`) ; Black-Litterman ne lit que ces probabilités-là.
"""
from __future__ import annotations

import json

import joblib
import numpy as np
import pandas as pd

from patrick.config.schema import RunConfig
from patrick.tracking import db as trackdb
from patrick.tracking.export import export_best_model


def _pool(n=900, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    pool = pd.DataFrame({"TGT": 100 + np.cumsum(rng.normal(0, 1, n))}, index=idx)
    for j in range(6):
        pool[f"f{j}"] = rng.normal(0, 0.01, n)
    return pool


def _config(calibration: bool, method: str = "isotonic") -> RunConfig:
    return RunConfig.model_validate({
        "objective": {"target_symbol": "^TGT", "horizons": [1]},
        "selection": {"method": "shap", "n_features_grid": [4], "shap_sample": 100},
        "features": {"pool_prefilter": 10},
        "models": {"calibration": calibration, "calibration_method": method},
    })


BEST = {"horizon": 1, "regime": "GLOBAL", "N": 4, "sampler": "none", "algo": "XGBoost"}


def _export(tmp_path, config, pool=None):
    pool = _pool() if pool is None else pool
    feature_pool = [c for c in pool.columns if c != "TGT"]
    path = export_best_model(pool, "TGT", feature_pool, config, BEST, str(tmp_path))
    return path, joblib.load(path)


def test_export_stores_a_calibrator_when_the_run_calibrates(tmp_path):
    path, bundle = _export(tmp_path, _config(True))
    cal = bundle["calibrator"]
    X = np.zeros((3, len(bundle["feature_names"])))
    proba = cal.predict_proba(X)
    assert proba.shape == (3, len(cal.classes_)) and np.allclose(proba.sum(axis=1), 1.0)
    meta = json.loads(open(path.replace(".joblib", "_meta.json"), encoding="utf-8").read())
    assert meta["calibration"]["method"] == "isotonic" and meta["calibration"]["n_calibration_rows"] > 0


def test_the_raw_model_stays_in_the_bundle_for_explanations(tmp_path):
    _, bundle = _export(tmp_path, _config(True))
    assert hasattr(bundle["model"], "feature_importances_")              # un arbre brut, pas un enrobage


def test_platt_scaling_is_honoured(tmp_path):
    path, bundle = _export(tmp_path, _config(True, "sigmoid"))
    assert "calibrator" in bundle
    assert json.loads(open(path.replace(".joblib", "_meta.json"), encoding="utf-8").read())["calibration"]["method"] == "sigmoid"


def test_no_calibrator_when_the_run_does_not_calibrate(tmp_path):
    path, bundle = _export(tmp_path, _config(False))
    assert "calibrator" not in bundle
    assert "calibration" not in json.loads(open(path.replace(".joblib", "_meta.json"), encoding="utf-8").read())


def test_a_history_too_short_to_split_exports_without_a_calibrator(tmp_path):
    _, bundle = _export(tmp_path, _config(True), pool=_pool(n=70))
    assert "calibrator" not in bundle


def test_the_calibrator_never_sees_the_rows_the_model_was_fitted_on():
    from patrick.models import calibration as cal_lib

    split = cal_lib.calibration_split(900, gap=1)
    assert split.fit_end < split.cal_start < split.thr_start < split.n


# --- prédiction du jour -----------------------------------------------------------------------------------------------------

class _FixedCalibrator:
    """Probabilités connues d'avance : P(hausse) = classes 2 + 3 = 0,25 + 0,40."""
    classes_ = np.array([0, 1, 2, 3])

    def predict_proba(self, X):
        return np.tile([0.10, 0.25, 0.25, 0.40], (len(X), 1))


def _live(tmp_path, monkeypatch, with_calibrator: bool):
    from patrick import predict as predict_module

    pool = _pool()
    feature_pool = [c for c in pool.columns if c != "TGT"]
    config = _config(True)
    path = export_best_model(pool, "TGT", feature_pool, config, BEST, str(tmp_path))
    bundle = joblib.load(path)
    bundle["model"].fit(np.random.default_rng(0).normal(size=(80, 4)), np.arange(80) % 4)
    if with_calibrator:
        bundle["calibrator"] = _FixedCalibrator()
    else:
        bundle.pop("calibrator", None)
    joblib.dump(bundle, path)

    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    trackdb.upsert_snapshot(conn, "s", "h", 0, 0, None)
    trackdb.create_run(conn, "r", target="^TGT", horizon=1, snapshot_id="s",
                       config_json=config.model_dump_json(), config_hash="h", git_sha="g", seed=42)
    tid = trackdb.create_trial(conn, "r", "GLOBAL", "XGBoost", "none", 4, "shap")
    trackdb.mark_best_trial(conn, tid, artifact_path=path)
    conn.close()
    monkeypatch.setattr(predict_module, "ingest", lambda *a, **k: pool)
    monkeypatch.setattr(predict_module, "build_full_feature_pool", lambda raw, *a, **k: raw)
    predict_module.predict_live("r", db_path=db_path)
    conn = trackdb.connect(db_path)
    try:
        return conn.execute("SELECT p_up, p_up_calibrated FROM prediction WHERE split = 'live' ORDER BY ts DESC").fetchall()
    finally:
        conn.close()


def test_live_p_up_comes_from_the_calibrator_and_is_flagged(tmp_path, monkeypatch):
    rows = _live(tmp_path, monkeypatch, with_calibrator=True)
    assert rows and rows[0][0] == np.float64(0.65) or abs(rows[0][0] - 0.65) < 1e-9
    assert rows[0][1] == 1


def test_without_a_calibrator_the_live_p_up_is_raw_and_not_flagged(tmp_path, monkeypatch):
    rows = _live(tmp_path, monkeypatch, with_calibrator=False)
    assert rows and 0.0 <= rows[0][0] <= 1.0
    assert not rows[0][1]


def test_walk_forward_predictions_are_not_flagged_as_live_calibrated(tmp_path):
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.upsert_snapshot(conn, "s", "h", 0, 0, None)
    trackdb.create_run(conn, "r", target="^T", horizon=1, snapshot_id="s", config_json="{}", config_hash="h",
                       git_sha="g", seed=1)
    tid = trackdb.create_trial(conn, "r", "GLOBAL", "XGBoost", "none", 4, "shap")
    trackdb.add_predictions(conn, tid, 1, "test", ["2020-01-01"], [1], [2], [0.5], p_up=[0.6])
    assert conn.execute("SELECT p_up_calibrated FROM prediction").fetchone()[0] is None
    trackdb.add_predictions(conn, tid, 0, "live", ["2020-01-02"], [None], [2], [0.5], p_up=[0.6], p_up_calibrated=True)
    assert conn.execute("SELECT p_up_calibrated FROM prediction WHERE split = 'live'").fetchone()[0] == 1
