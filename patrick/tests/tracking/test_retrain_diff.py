"""Ce qui a changé entre deux champions successifs (FO18 du 25/11)."""
from __future__ import annotations

import json

from patrick.tracking import db as trackdb
from patrick.tracking import retrain_diff


def test_variables_parameters_and_metrics_are_compared(monkeypatch):
    conn = trackdb.connect()
    try:
        conn.execute("INSERT INTO model_archive (target, horizon, run_id, role, algo, n_features, feature_names_json, params_json, "
                     "wf_metrics_json, holdout_metrics_json) VALUES ('^GSPC', 1, 'old', 'replaced_champion', 'XGBoost', 3, ?, ?, ?, ?)",
                     (json.dumps(["a", "b", "c"]), json.dumps({"depth": 3, "eta": 0.1}), json.dumps({"AUC_dir": 0.52}), json.dumps({"AUC_dir": 0.51})))
        conn.commit()
        monkeypatch.setattr(retrain_diff, "_current", lambda c, t, h: {
            "run_id": "new", "decided_at": "2026-11-20", "algo": "LightGBM", "n_features": 3, "features": ["b", "c", "d"],
            "params": {"depth": 5, "eta": 0.1}, "test": {"AUC_dir": 0.55}, "holdout": {"AUC_dir": 0.53}})
        d = retrain_diff.diff(conn, "^GSPC", 1)
        assert d["features_in"] == ["d"] and d["features_out"] == ["a"] and d["features_kept"] == 2
        assert d["params_changed"] == {"depth": (3, 5)} and d["metrics"]["holdout:AUC_dir"] == (0.51, 0.53)
        assert retrain_diff.diff(conn, "^VIX", 1) is None
    finally:
        conn.close()
