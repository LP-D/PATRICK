"""Conformal direction sets (roadmap bloc 3) -- validity checked by
simulation, not assumed."""
from __future__ import annotations

import numpy as np
import pytest

from patrick.validation import conformal


def _calibrated(n, seed):
    rng = np.random.default_rng(seed)
    p = rng.uniform(0, 1, n)
    return p, (rng.uniform(0, 1, n) < p).astype(int)


def test_split_conformal_covers_at_the_nominal_rate_when_exchangeable():
    p, y = _calibrated(4000, 0)
    out = conformal.direction_sets(p, y, alpha=0.2, method="split")
    assert out["coverage"] == pytest.approx(0.8, abs=0.03)
    assert 0 < out["no_call_rate"] < 1


def test_aci_restores_long_run_coverage_under_a_regime_shift():
    p, y = _calibrated(4000, 1)
    y[2000:] = 1 - y[2000:]   # the model becomes wrong half-way
    split = conformal.direction_sets(p, y, alpha=0.2, method="split", window=500)
    aci = conformal.direction_sets(p, y, alpha=0.2, method="aci", gamma=0.02, window=500)
    assert abs(aci["coverage"] - 0.8) < abs(split["coverage"] - 0.8)
    assert aci["coverage"] == pytest.approx(0.8, abs=0.03)


def test_an_uninformative_model_never_makes_a_call():
    y = np.random.default_rng(2).integers(0, 2, 500)
    out = conformal.direction_sets(np.full(500, 0.5), y, alpha=0.2)
    assert out["no_call_rate"] == 1.0 and out["n_called"] == 0


def test_no_call_before_enough_past_scores_and_bad_method():
    p, y = _calibrated(100, 3)
    out = conformal.direction_sets(p, y, alpha=0.2, min_calibration=30)
    assert out["contains_up"][:30].all() and out["contains_down"][:30].all()
    with pytest.raises(ValueError):
        conformal.direction_sets(p, y, method="bootstrap")


def test_run_page_shows_conformal_sets_from_stored_p_up(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient

    from patrick.tracking import db, history
    from patrick.webapp.app import app

    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "p.db"))
    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(conn, "s", "h", None, None, None)
    db.create_run(conn, "r", "^T", 5, "s", json.dumps({"validation": {"scheme": "walkforward"}}), "c", "g", 1)
    tid = db.create_trial(conn, "r", "GLOBAL", "XGBoost", "none", 5, "shap")
    db.mark_best_trial(conn, tid)
    p, y = _calibrated(300, 9)
    ts = [str(d.date()) for d in __import__("pandas").bdate_range("2024-01-01", periods=300)]
    db.add_predictions(conn, tid, 1, "test", ts, y_true=[3 if v else 0 for v in y], y_pred=[3] * 300,
                       y_proba=[0.6] * 300, p_up=p)
    db.finish_run(conn, "r", "done", n_trials=1)
    c = history.conformal_for_trial(conn, tid)
    assert c["available"] and c["n"] == 300 and 0.7 < c["aci"]["coverage"] < 0.9
    page = TestClient(app).get("/runs/r/detail").text
    assert "Prédiction conforme" in page and "Couverture (ACI)" in page

    tid2 = db.create_trial(conn, "r", "GLOBAL", "LightGBM", "none", 5, "shap")
    db.add_predictions(conn, tid2, 1, "test", ts[:10], y_true=[3] * 10, y_pred=[3] * 10)
    assert history.conformal_for_trial(conn, tid2)["available"] is False


def test_live_rows_binary_outcome_is_read_as_a_direction_not_a_class(tmp_path):
    """split='live' stores y_true as BINARY realised direction (1.0 up /
    0.0 down, predict.py), test/holdout as the 4-class index: a live 1.0 is
    an UP, not class 1 (DOWN_FAIBLE)."""
    from patrick.tracking import db, history

    conn = db.connect(str(tmp_path / "p.db"))
    db.upsert_snapshot(conn, "s", "h", None, None, None)
    db.create_run(conn, "r", "^T", 5, "s", "{}", "c", "g", 1)
    tid = db.create_trial(conn, "r", "GLOBAL", "XGBoost", "none", 5, "shap")
    import pandas as pd
    ts = [str(d.date()) for d in pd.bdate_range("2024-01-01", periods=80)]
    db.add_predictions(conn, tid, 0, "live", ts, y_true=[1.0] * 80, y_pred=[3] * 80, y_proba=[0.9] * 80,
                       p_up=[0.9] * 80)
    c = history.conformal_for_trial(conn, tid, min_predictions=60)
    assert c["base_rate_up"] == 1.0
