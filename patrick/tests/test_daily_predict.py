"""Phase 2 (inférence programmée quotidienne) -- `scripts/daily_predict.py`.

Deux choses testées, TDD :

1. `find_predictable_candidates` : sélectionne, pour chaque (target, horizon),
   le run `status='done'` le plus récent dont le trial gagnant (`is_best=1`)
   a un `artifact_path` non vide ET dont le fichier existe réellement sur
   disque -- pas seulement "la DB dit qu'il y a un modèle exporté" (audit
   réel sur `~/.patrick/patrick.db` : de nombreuses lignes `trial.artifact_path`
   pointent vers des fichiers qui n'existent plus).
2. `run_daily_predictions` : agrège succès/échecs sur une liste de candidats,
   `predict_live` mocké -- une exception sur un item ne doit JAMAIS empêcher
   le traitement des suivants, et le résumé doit compter les deux
   correctement.

Le script vit dans `patrick/scripts/` (comme `profile_scan_optuna_p3_p4.py`),
hors du package `patrick` -- chargé ici par chemin de fichier
(`importlib.util`), pas par un `import patrick.scripts.daily_predict`
classique (le module n'est pas dans `patrick/patrick/`).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from patrick.tracking import db as trackdb

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "daily_predict.py"


def _load_daily_predict_module():
    spec = importlib.util.spec_from_file_location("daily_predict", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    # dataclasses (3.14) resolves type hints via sys.modules[cls.__module__] --
    # must be registered BEFORE exec_module, same as a normal import would do.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


daily_predict = _load_daily_predict_module()


def _make_run_with_trial(conn, run_id, target, horizon, status="done",
                          artifact_path="model.joblib", finished_at=None):
    trackdb.upsert_snapshot(conn, "snap", data_hash="hash", n_tickers=1, n_fred_series=0,
                             fred_source=None)
    trackdb.create_run(conn, run_id, target, horizon, snapshot_id="snap",
                        config_json=json.dumps({"name": run_id}), config_hash="h",
                        git_sha="deadbeef", seed=42)
    trial_id = trackdb.create_trial(conn, run_id, regime="GLOBAL", algo="XGBoost",
                                     sampler="SMOTE", n_features=8, selector="shap")
    trackdb.mark_best_trial(conn, trial_id, artifact_path=artifact_path)
    trackdb.finish_run(conn, run_id, status=status, n_trials=1)
    if finished_at is not None:
        with conn:
            conn.execute("UPDATE run SET finished_at = ? WHERE run_id = ?", (finished_at, run_id))
    return trial_id


# ------------------------------------------------------------------
# 1. find_predictable_candidates
# ------------------------------------------------------------------

def test_find_predictable_candidates_requires_done_status(tmp_path):
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    model_file = tmp_path / "model_running.joblib"
    model_file.write_bytes(b"fake")
    _make_run_with_trial(conn, "run_running", "^GSPC", 1, status="running",
                          artifact_path=str(model_file))
    conn.close()

    conn = trackdb.connect(db_path)
    candidates = daily_predict.find_predictable_candidates(conn, base_dir=str(tmp_path))
    conn.close()

    assert candidates == []


def test_find_predictable_candidates_requires_artifact_file_to_actually_exist(tmp_path):
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    # artifact_path recorded in DB, but no file at that path (reproduces the
    # real production DB state found in the audit: stale artifact_path after
    # the runs/ directory was cleaned up).
    _make_run_with_trial(conn, "run_missing_file", "^VIX", 5, status="done",
                          artifact_path="does_not_exist.joblib")
    conn.close()

    conn = trackdb.connect(db_path)
    candidates = daily_predict.find_predictable_candidates(conn, base_dir=str(tmp_path))
    conn.close()

    assert candidates == []


def test_find_predictable_candidates_keeps_most_recent_done_run_per_pair(tmp_path):
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)

    old_model = tmp_path / "old.joblib"
    old_model.write_bytes(b"fake")
    new_model = tmp_path / "new.joblib"
    new_model.write_bytes(b"fake")

    _make_run_with_trial(conn, "run_old", "^GSPC", 1, status="done",
                          artifact_path=str(old_model), finished_at="2026-01-01 00:00:00")
    _make_run_with_trial(conn, "run_new", "^GSPC", 1, status="done",
                          artifact_path=str(new_model), finished_at="2026-06-01 00:00:00")
    conn.close()

    conn = trackdb.connect(db_path)
    candidates = daily_predict.find_predictable_candidates(conn, base_dir=str(tmp_path))
    conn.close()

    assert len(candidates) == 1
    assert candidates[0].run_id == "run_new"


def test_find_predictable_candidates_resolves_relative_artifact_path_against_base_dir(tmp_path):
    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    (tmp_path / "runs" / "mon_run").mkdir(parents=True)
    (tmp_path / "runs" / "mon_run" / "GSPC_1_best_model.joblib").write_bytes(b"fake")
    _make_run_with_trial(conn, "run_gspc", "^GSPC", 1, status="done",
                          artifact_path="runs/mon_run/GSPC_1_best_model.joblib")
    conn.close()

    conn = trackdb.connect(db_path)
    candidates = daily_predict.find_predictable_candidates(conn, base_dir=str(tmp_path))
    conn.close()

    assert len(candidates) == 1
    assert candidates[0].target == "^GSPC"
    assert candidates[0].horizon == 1


# ------------------------------------------------------------------
# 2. run_daily_predictions -- aggregation & per-item error isolation
# ------------------------------------------------------------------

def _candidate(target, horizon, run_id):
    return daily_predict.PredictCandidate(target=target, horizon=horizon, run_id=run_id,
                                           trial_id=1, artifact_path="x.joblib")


def test_run_daily_predictions_counts_success_and_failure_and_does_not_stop_on_error():
    candidates = [_candidate("^FAIL", 1, "run_fail"), _candidate("^OK", 5, "run_ok")]
    calls = []

    def fake_predict_live(run_id, db_path=None):
        calls.append(run_id)
        if run_id == "run_fail":
            raise ValueError("Training pool columns missing from the fresh data")
        return {"run_id": run_id, "trial_id": 1, "ts": "2026-09-05", "y_pred": 2,
                "y_proba": 0.71, "n_outcomes_updated": 0}

    summary = daily_predict.run_daily_predictions(candidates, predict_live_fn=fake_predict_live,
                                                    db_path="unused.db")

    # BOTH candidates were attempted -- the first one raising did not stop the loop.
    assert calls == ["run_fail", "run_ok"]

    assert len(summary.outcomes) == 2
    assert len(summary.successes) == 1
    assert len(summary.failures) == 1
    assert summary.successes[0].candidate.run_id == "run_ok"
    assert summary.failures[0].candidate.run_id == "run_fail"
    assert "Training pool columns missing" in summary.failures[0].error
    assert summary.successes[0].detail["y_pred"] == 2


def test_run_daily_predictions_all_success():
    candidates = [_candidate("^A", 1, "run_a"), _candidate("^B", 2, "run_b")]

    def fake_predict_live(run_id, db_path=None):
        return {"run_id": run_id, "trial_id": 1, "ts": "2026-09-05", "y_pred": 0,
                "y_proba": 0.5, "n_outcomes_updated": 0}

    summary = daily_predict.run_daily_predictions(candidates, predict_live_fn=fake_predict_live)
    assert len(summary.successes) == 2
    assert len(summary.failures) == 0


def test_run_daily_predictions_all_failure_still_reports_each_one():
    candidates = [_candidate("^A", 1, "run_a"), _candidate("^B", 2, "run_b")]

    def fake_predict_live(run_id, db_path=None):
        raise RuntimeError(f"boom on {run_id}")

    summary = daily_predict.run_daily_predictions(candidates, predict_live_fn=fake_predict_live)
    assert len(summary.successes) == 0
    assert len(summary.failures) == 2
    assert {f.candidate.run_id for f in summary.failures} == {"run_a", "run_b"}
    assert summary.failures[0].error == "boom on run_a"
    assert summary.failures[1].error == "boom on run_b"


def test_run_daily_predictions_empty_candidate_list():
    summary = daily_predict.run_daily_predictions([], predict_live_fn=lambda run_id, db_path=None: {})
    assert summary.outcomes == []
    assert summary.successes == []
    assert summary.failures == []


# ------------------------------------------------------------------
# Drift policy of 2026-09-26: the nightly job re-measures stale PSIs
# ------------------------------------------------------------------

def test_nightly_drift_remeasures_only_stale_or_unmeasured_pairs(tmp_path):
    import datetime as dt

    db_path = str(tmp_path / "patrick.db")
    conn = trackdb.connect(db_path)
    with conn:
        conn.execute("INSERT INTO drift_psi_history (symbol, horizon, feature, computed_at, psi) "
                     "VALUES ('^GSPC', 1, 'f', '2026-09-24 22:10:00', 0.01)")
        conn.execute("INSERT INTO drift_psi_history (symbol, horizon, feature, computed_at, psi) "
                     "VALUES ('^VIX', 5, 'f', '2026-09-01 22:10:00', 0.01)")
    conn.close()
    cands = [daily_predict.PredictCandidate("^GSPC", 1, "r1", 1, "a"),
             daily_predict.PredictCandidate("^VIX", 5, "r2", 2, "b"),
             daily_predict.PredictCandidate("BTC-USD", 20, "r3", 3, "c"),
             daily_predict.PredictCandidate("GC=F", 5, "r4", 4, "d")]
    measured = []

    def fake_measure(target, horizon, db_path=None):
        measured.append((target, horizon))
        if target == "GC=F":
            raise RuntimeError("no reference")
        return {"f": {"psi": 0.1}}

    report = daily_predict.remeasure_stale_drift(cands, db_path=db_path, measure_fn=fake_measure,
                                                 today=dt.date(2026, 9, 26), limit=10)
    assert measured == [("^VIX", 5), ("BTC-USD", 20), ("GC=F", 5)]      # ^GSPC measured 2 days ago
    assert report == {"measured": 2, "failed": 1, "skipped_fresh": 1, "deferred": 0}

    measured.clear()
    report = daily_predict.remeasure_stale_drift(cands, db_path=db_path, measure_fn=fake_measure,
                                                 today=dt.date(2026, 9, 26), limit=1)
    assert len(measured) == 1 and report["deferred"] == 2
