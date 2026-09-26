"""The N2 invariant ("a ±inf in the feature pool never reaches a model",
`test_inf_features.py`) was only enforced on the SCAN paths (walk-forward,
holdout, CPCV). The three paths that run AFTER the scan still used bare
`np.nan_to_num` -- ±inf -> ±1.797e308 -> overflow through `RobustScaler` ->
XGBoost "Input data contains `inf`":

- `tracking/export.py::export_best_model` (refit of the winner on the full
  history -- the last step of every run: a run could complete its whole
  scan, then crash at export);
- `predict.py::predict_live` (daily scoring);
- `explain.py::explain_last_prediction` (SHAP waterfall).

A feature that is finite on every fold but infinite somewhere in the full
history (typically a ratio whose denominator hits ~0 on a date that falls in
no test fold, or in the final rows that only the full-history refit sees)
reaches only these paths.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.config.schema import RunConfig
from patrick.tracking.export import export_best_model


def _pool_with_inf(n=400, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    price = 100 + np.cumsum(rng.normal(0, 1, n))
    pool = pd.DataFrame({"TGT": price}, index=idx)
    for j in range(6):
        pool[f"f{j}"] = rng.normal(0, 0.01, n)
    pool.loc[idx[37], "f2"] = np.inf
    pool.loc[idx[211], "f4"] = -np.inf
    return pool


def test_export_best_model_survives_an_infinite_feature_cell(tmp_path):
    pool = _pool_with_inf()
    feature_pool = [c for c in pool.columns if c != "TGT"]
    config = RunConfig.model_validate({
        "objective": {"target_symbol": "^TGT", "horizons": [1]},
        "selection": {"method": "shap", "n_features_grid": [4], "shap_sample": 100},
        "features": {"pool_prefilter": 10},
    })
    best_cfg = {"horizon": 1, "regime": "GLOBAL", "N": 4, "sampler": "none", "algo": "XGBoost"}
    path = export_best_model(pool, "TGT", feature_pool, config, best_cfg, str(tmp_path))
    assert path.endswith(".joblib")


def test_predict_live_row_with_an_infinite_feature_is_scored(tmp_path, monkeypatch):
    import joblib

    from patrick import predict as predict_module
    from patrick.tracking import db as trackdb

    pool = _pool_with_inf()
    pool.iloc[-1, pool.columns.get_loc("f2")] = np.inf
    feature_pool = [c for c in pool.columns if c != "TGT"]
    config = RunConfig.model_validate({
        "objective": {"target_symbol": "^TGT", "horizons": [1]},
        "selection": {"method": "shap", "n_features_grid": [4], "shap_sample": 100},
        "features": {"pool_prefilter": 10},
    })
    best_cfg = {"horizon": 1, "regime": "GLOBAL", "N": 4, "sampler": "none", "algo": "XGBoost"}
    finite_pool = pool.replace([np.inf, -np.inf], np.nan)
    path = export_best_model(finite_pool, "TGT", feature_pool, config, best_cfg, str(tmp_path))
    bundle = joblib.load(path)
    bundle["feature_names"] = feature_pool[:4]
    bundle["model"].fit(np.random.default_rng(0).normal(size=(40, 4)), np.arange(40) % 4)
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
    seen = []
    model_cls = type(bundle["model"])
    real_predict = model_cls.predict

    def _spy(self, X, *a, **k):
        seen.append(np.asarray(X, dtype=float).copy())
        return real_predict(self, X, *a, **k)

    monkeypatch.setattr(model_cls, "predict", _spy)
    predict_module.predict_live("r", db_path=db_path)

    last = pool[feature_pool].iloc[[-1]].to_numpy(dtype=float)
    expected = bundle["scaler"].transform(np.where(np.isfinite(last), last, 0.0))[:, :4]
    assert seen and np.isfinite(seen[0]).all()
    np.testing.assert_allclose(seen[0], expected)
