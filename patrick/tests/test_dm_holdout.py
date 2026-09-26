"""F08 -- the Diebold-Mariano verdict must be computed on data that played no
part in choosing the model.

Found on the real ^GSPC run (2026-09-25): the final DM (p = 0.0002, h=5)
was computed on the LAST walk-forward fold. The winning configuration is
ranked on its mean F1_dir over all walk-forward folds (F07), that fold
included: the model is tested on scores that selected it, so the p-value
is biased towards "significant". The class-specific baseline was also
picked as the best candidate on that same fold.

Fix: DM on the terminal holdout (never used for any choice), against the
class-specific baseline chosen on the last walk-forward fold (selection
data) and the common persistence baseline, both predicted on the holdout.
Without a holdout, the last-fold DM is kept but recorded as
`sample = 'last_wf_fold'` and excluded from the cross-target BH family
(treated as untestable) -- a selection-biased p-value is not evidence.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from patrick.pipeline import engine
from patrick.tracking import db as trackdb
from patrick.tracking import stats as trackstats
from patrick.validation.diebold_mariano import diebold_mariano


def _run(conn, run_id, target):
    trackdb.upsert_snapshot(conn, "snap", "h", 0, 0, None)
    trackdb.create_run(conn, run_id, target=target, horizon=5, snapshot_id="snap",
                        config_json=json.dumps({"validation": {"scheme": "walkforward"}}),
                        config_hash="c", git_sha="g", seed=42)
    trackdb.finish_run(conn, run_id, status="done")


def _dm(p):
    return {"baseline": "BASELINE_persistence", "dm_stat": -2.0, "p_value": p, "n_obs": 250}


def test_dm_rows_record_their_sample_and_legacy_rows_are_last_fold(conn):
    _run(conn, "r1", "^A")
    trackdb.save_dm_result(conn, "r1", _dm(0.01), kind="class_specific", sample="holdout")
    row = conn.execute("SELECT sample, n_obs FROM dm_result WHERE run_id = 'r1'").fetchone()
    assert tuple(row) == ("holdout", 250)

    _run(conn, "legacy", "^B")
    conn.execute("INSERT INTO dm_result (run_id, kind, baseline, dm_stat, p_value) "
                 "VALUES ('legacy', 'class_specific', 'BASELINE_persistence', -1.0, 0.03)")
    assert conn.execute("SELECT sample FROM dm_result WHERE run_id = 'legacy'").fetchone()[0] == "last_wf_fold"


def test_save_dm_result_requires_an_explicit_sample(conn):
    _run(conn, "r1", "^A")
    with pytest.raises(TypeError):
        trackdb.save_dm_result(conn, "r1", _dm(0.01), kind="class_specific")
    with pytest.raises(ValueError):
        trackdb.save_dm_result(conn, "r1", _dm(0.01), kind="class_specific", sample="test")


def test_bh_family_ignores_selection_fold_p_values(conn):
    _run(conn, "a", "^A")
    trackdb.save_dm_result(conn, "a", _dm(0.01), kind="class_specific", sample="holdout")
    _run(conn, "b", "^B")
    trackdb.save_dm_result(conn, "b", _dm(0.0001), kind="class_specific", sample="last_wf_fold")
    fdr = trackstats.fdr_across_targets(conn, alpha=0.10)
    assert fdr["n_tested"] == 2
    assert fdr["n_with_p_value"] == 1
    assert fdr["n_selection_biased"] == 1
    b = fdr["results"]["^B"]
    assert b["untestable"] and b["selection_biased"] and not b["significant"]
    assert fdr["results"]["^A"]["adjusted_p_value"] == pytest.approx(0.02)


def test_holdout_dm_is_computed_on_the_holdout_predictions():
    rng = np.random.default_rng(0)
    y_true = rng.integers(0, 4, 300)
    y_pred = np.where(rng.random(300) < 0.6, y_true, rng.integers(0, 4, 300))
    baselines = {"BASELINE_momentum_20": rng.integers(0, 4, 300),
                 "BASELINE_persistence": rng.integers(0, 4, 300)}
    out = engine._dm_against_baselines(y_true, y_pred, baselines, "BASELINE_momentum_20", horizon=5)
    expected = diebold_mariano((y_pred != y_true).astype(float),
                               (baselines["BASELINE_momentum_20"] != y_true).astype(float), h=5)
    assert out["class_specific"]["baseline"] == "BASELINE_momentum_20"
    assert out["class_specific"]["p_value"] == pytest.approx(expected["p_value"])
    assert out["class_specific"]["n_obs"] == 300
    assert out["common"]["baseline"] == "BASELINE_persistence"


def test_holdout_dm_without_the_chosen_baseline_keeps_the_common_one():
    y = np.array([0, 1, 2, 3] * 20)
    out = engine._dm_against_baselines(y, y, {"BASELINE_persistence": y[::-1].copy()}, None, horizon=1)
    assert out["class_specific"] is None and out["common"] is not None


@pytest.mark.slow
def test_run_pipeline_records_the_dm_on_the_holdout(tmp_path, monkeypatch):
    from test_run_pipeline_golden import _config, _raw

    from patrick.data.store import DataStore
    raw = _raw()
    monkeypatch.setattr(engine, "ingest", lambda *a, **k: raw.copy())
    monkeypatch.setattr(engine, "download_ohlc", lambda *a, **k: None)
    db_path = str(tmp_path / "patrick.db")
    result = engine.run_pipeline(_config(tmp_path, "walkforward"), store=DataStore(root=str(tmp_path / "s")),
                                 db_path=db_path)
    assert result["diebold_mariano"]["sample"] == "holdout"
    conn = trackdb.connect(db_path)
    rows = conn.execute("SELECT kind, sample, n_obs, run_id FROM dm_result").fetchall()
    assert rows and all(r[1] == "holdout" for r in rows)
    n_holdout = conn.execute(
        "SELECT COUNT(*) FROM prediction p JOIN trial t ON p.trial_id = t.trial_id "
        "WHERE t.run_id = ? AND t.is_best = 1 AND p.split = 'holdout'", (rows[0][3],)).fetchone()[0]
    assert n_holdout > 0 and all(r[2] == n_holdout for r in rows)
    conn.close()


def _seed_biased_run(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = trackdb.connect(str(tmp_path / "patrick.db"))
    trackdb.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    trackdb.create_run(conn, "run1", "^VIX", 5, "snap1", json.dumps({"validation": {"scheme": "walkforward"}}),
                        "cfghash", "sha", 42)
    trial_id = trackdb.create_trial(conn, "run1", "GLOBAL", "XGBoost", "SMOTE", 8, "shap")
    trackdb.mark_best_trial(conn, trial_id)
    trackdb.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.6})
    trackdb.add_predictions(conn, trial_id, fold_index=1, split="test", ts=["2024-05-01"],
                            y_true=[3], y_pred=[3], y_proba=[0.7])
    trackdb.save_dm_result(conn, "run1", _dm(0.001), kind="class_specific", sample="last_wf_fold")
    trackdb.finish_run(conn, "run1", status="done", n_trials=1)
    conn.close()


def test_pages_never_call_a_selection_fold_p_value_significant(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from patrick.webapp.app import app
    _seed_biased_run(tmp_path, monkeypatch)
    client = TestClient(app)
    detail = client.get("/runs/run1/detail").text
    assert "fold de sélection" in detail
    assert "significatif (p &lt;" not in detail
    predictions = client.get("/predictions").text
    assert "fold de sélection" in predictions
    assert "status-ok\">p=0.0010" not in predictions
    assert "&lt;span" not in predictions
    runs = client.get("/runs").text
    assert "fold de sélection" in runs


def test_synthesis_flags_a_target_whose_only_dm_is_selection_biased(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from patrick.webapp.app import app
    _seed_biased_run(tmp_path, monkeypatch)
    html_ = TestClient(app).get("/").text
    assert "Fold de sélection (biaisé)" in html_
