"""Ensemble de confiance de modèles et SPA de Hansen sur une paire cible × horizon (FO1/FO2 du 25/11)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from patrick.tracking import db as trackdb
from patrick.validation import model_set

N = 200


def _seed(skills: dict[str, float], champion: str | None = None):
    rng = np.random.default_rng(3)
    conn = trackdb.connect()
    trackdb.upsert_snapshot(conn, "snap", "h", None, None, None)
    ts = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2025-01-01", periods=N)]
    up = rng.random(N) < 0.5
    y_true = np.where(up, 3.0, 0.0)
    for i, (run_id, skill) in enumerate(skills.items()):
        trackdb.create_run(conn, run_id, "^GSPC", 1, "snap", "{}", f"cfg{i}", "sha", i)
        trial = trackdb.create_trial(conn, run_id, "GLOBAL", "XGBoost", "none", 8, "shap")
        trackdb.mark_best_trial(conn, trial)
        noise = rng.normal(0, 0.08, N)
        p_up = np.clip(0.5 + np.where(up, skill, -skill) + noise, 0.01, 0.99)
        trackdb.add_predictions(conn, trial, fold_index=None, split="holdout", ts=ts, y_true=list(y_true), y_pred=list(np.where(p_up > 0.5, 3, 0)),
                                y_proba=list(p_up), p_up=list(p_up))
        trackdb.finish_run(conn, run_id, status="done", n_trials=1)
    if champion:
        conn.execute("INSERT INTO champion (target, horizon, run_id, trial_id, reason) SELECT '^GSPC', 1, run_id, trial_id, 'test' "
                     "FROM trial WHERE run_id = ? AND is_best = 1", (champion,))
    conn.commit()
    return conn


def test_a_clearly_better_model_is_alone_in_the_set_and_beats_chance():
    conn = _seed({"good": 0.25, "coin1": 0.0, "coin2": 0.0}, champion="good")
    try:
        out = model_set.evaluate(conn, "^GSPC", 1, reps=300)
    finally:
        conn.close()
    assert out["n_models"] == 3 and out["n_obs"] == N
    assert out["mcs"]["included"] == ["good"] and out["mcs"]["champion_in"] is True
    assert out["spa"]["p_consistent"] < 0.05 and out["spa"]["best"] == "good"


def test_models_without_skill_are_indistinguishable_and_do_not_beat_chance():
    conn = _seed({"a": 0.0, "b": 0.0, "c": 0.0}, champion="a")
    try:
        out = model_set.evaluate(conn, "^GSPC", 1, reps=300)
    finally:
        conn.close()
    assert len(out["mcs"]["included"]) >= 2 and out["spa"]["p_consistent"] > 0.05


def test_a_single_model_is_not_compared_and_the_page_section_renders():
    conn = _seed({"seul": 0.1}, champion="seul")
    conn.close()
    out = model_set.evaluate(trackdb.connect(), "^GSPC", 1)
    assert out["mcs"] is None and "il en faut deux" in out["reason"]
    text = TestClient(__import__("patrick.webapp.app", fromlist=["app"]).app).get("/fragments/model-set/%5EGSPC").text
    assert "il en faut deux" in text or "need two" in text
