"""Meta-labeling on stored OOS predictions (roadmap bloc 3)."""
from __future__ import annotations

import numpy as np

from patrick.validation import meta_labeling as ml


def _primary(n, informative, seed):
    rng = np.random.default_rng(seed)
    conf = rng.uniform(0.3, 0.9, n)
    p_right = np.where(conf > 0.6, 0.75, 0.5) if informative else np.full(n, 0.6)
    right = rng.uniform(0, 1, n) < p_right
    y_true = rng.choice([0, 3], n)
    y_pred = np.where(right, y_true, 3 - y_true)
    p_up = np.where(y_pred == 3, 0.5 + (conf - 0.3) / 1.2, 0.5 - (conf - 0.3) / 1.2)
    return y_pred, y_true, p_up, conf


def test_meta_filter_improves_precision_when_confidence_is_informative():
    out = ml.meta_label_sequence(*_primary(3000, True, 0), horizon=5)
    assert out["accuracy_kept"] > out["accuracy_all"] + 0.05
    assert 0.1 < out["kept_share"] < 0.9


def test_no_information_no_free_lunch():
    out = ml.meta_label_sequence(*_primary(3000, False, 1), horizon=5)
    assert abs(out["accuracy_kept"] - out["accuracy_all"]) < 0.03


def test_no_look_ahead_future_outcomes_cannot_change_a_past_meta_probability():
    y_pred, y_true, p_up, conf = _primary(800, True, 2)
    a = ml.meta_label_sequence(y_pred, y_true, p_up, conf, horizon=5)["meta_p"]
    y_true2 = y_true.copy()
    y_true2[600:] = 3 - y_true2[600:]           # rewrite outcomes from row 600 on
    b = ml.meta_label_sequence(y_pred, y_true2, p_up, conf, horizon=5)["meta_p"]
    # rows < 600 + horizon never saw the rewritten outcomes
    np.testing.assert_array_equal(np.nan_to_num(a[:605], nan=-1), np.nan_to_num(b[:605], nan=-1))


def test_too_short_history_evaluates_nothing():
    out = ml.meta_label_sequence(*_primary(50, True, 3), horizon=5)
    assert out["n_evaluated"] == 0 and np.isnan(out["accuracy_all"])


def test_run_page_reports_meta_labeling(tmp_path, monkeypatch):
    import json

    import pandas as pd
    from fastapi.testclient import TestClient

    from patrick.tracking import db, history
    from patrick.webapp.app import app

    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(conn, "s", "h", None, None, None)
    db.create_run(conn, "r", "^T", 5, "s", json.dumps({"validation": {"scheme": "walkforward"}}), "c", "g", 1)
    tid = db.create_trial(conn, "r", "GLOBAL", "XGBoost", "none", 5, "shap")
    db.mark_best_trial(conn, tid)
    y_pred, y_true, p_up, conf = _primary(600, True, 7)
    ts = [str(d.date()) for d in pd.bdate_range("2023-01-02", periods=600)]
    db.add_predictions(conn, tid, 1, "test", ts, y_true=y_true, y_pred=y_pred, y_proba=conf, p_up=p_up)
    db.finish_run(conn, "r", "done", n_trials=1)
    m = history.meta_labeling_for_trial(conn, tid, 5)
    assert m["available"] and m["n_kept"] > 0
    assert "Meta-labeling" in TestClient(app).get("/runs/r/detail").text
