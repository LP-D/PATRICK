"""Phase 7 (interface) -- `patrick.tracking.history`, requêtes lecture seule
pour les pages `/runs`, `/runs/{id}`, `/targets/{ticker}`, `/universe`."""
from __future__ import annotations

import json

from patrick.tracking import db
from patrick.tracking import history as trackhistory


def _make_run(conn, run_id: str, target: str, horizon: int, *, config: dict | None = None,
              status: str = "running") -> None:
    config = config or {"name": run_id, "validation": {"scheme": "walkforward"}}
    db.upsert_snapshot(conn, f"snap_{run_id}", f"hash_{run_id}", None, None, None)
    db.create_run(conn, run_id, target, horizon, f"snap_{run_id}",
                   json.dumps(config), "cfghash", "sha", 42)
    if status != "running":
        db.finish_run(conn, run_id, status=status, n_trials=1)


def test_list_runs_empty(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    assert trackhistory.list_runs(conn) == []
    conn.close()


def test_list_runs_returns_most_recent_first_with_scheme_and_name(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, config={"name": "premier", "validation": {"scheme": "walkforward"}},
               status="done")
    _make_run(conn, "run2", "^VIX", 5, config={"name": "second", "validation": {"scheme": "cpcv"}},
               status="done")
    runs = trackhistory.list_runs(conn)
    assert [r["run_id"] for r in runs] == ["run2", "run1"]
    assert runs[0]["scheme"] == "cpcv"
    assert runs[0]["name"] == "second"
    assert runs[1]["scheme"] == "walkforward"
    conn.close()


def test_list_runs_filters_by_target_status_and_scheme(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, config={"name": "a", "validation": {"scheme": "walkforward"}}, status="done")
    _make_run(conn, "run2", "AAPL", 5, config={"name": "b", "validation": {"scheme": "cpcv"}}, status="running")
    assert [r["run_id"] for r in trackhistory.list_runs(conn, target="^VIX")] == ["run1"]
    assert [r["run_id"] for r in trackhistory.list_runs(conn, status="running")] == ["run2"]
    assert [r["run_id"] for r in trackhistory.list_runs(conn, scheme="cpcv")] == ["run2"]
    conn.close()


def test_list_runs_reports_best_trial_f1_and_dm_p_value(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    db.add_fold_metrics(conn, trial_id, 1, "test", {"F1_dir": 0.62})
    db.add_fold_metrics(conn, trial_id, 2, "test", {"F1_dir": 0.58})
    db.save_dm_result(conn, "run1", {"baseline": "majority", "dm_stat": 2.1, "p_value": 0.03})

    runs = trackhistory.list_runs(conn)
    assert runs[0]["best_f1_dir"] == 0.60
    assert runs[0]["dm_p_value"] == 0.03
    conn.close()


def test_list_distinct_targets_counts_runs_and_done(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    _make_run(conn, "run2", "^VIX", 10, status="running")
    _make_run(conn, "run3", "AAPL", 5, status="done")
    targets = {t["target"]: t for t in trackhistory.list_distinct_targets(conn)}
    assert targets["^VIX"]["n_runs"] == 2
    assert targets["^VIX"]["n_done"] == 1
    assert targets["AAPL"]["n_runs"] == 1
    conn.close()


def test_run_detail_returns_none_for_unknown_run(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    assert trackhistory.run_detail(conn, "nope") is None
    conn.close()


def test_run_detail_walkforward_structure(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    for fold in (1, 2):
        db.add_fold_metrics(conn, trial_id, fold, "test", {"F1_dir": 0.6})
    db.add_fold_metrics(conn, trial_id, 0, "holdout", {"F1_dir": 0.55})
    db.save_dm_result(conn, "run1", {"baseline": "majority", "dm_stat": 2.1, "p_value": 0.03})

    detail = trackhistory.run_detail(conn, "run1")
    assert detail["scheme"] == "walkforward"
    assert detail["is_cpcv"] is False
    assert detail["cpcv_info"] is None
    assert len(detail["trials"]) == 1
    assert detail["best_trial"]["trial_id"] == trial_id
    assert detail["holdout_f1_dir"] == 0.55
    assert detail["dm_result"]["p_value"] == 0.03
    assert detail["target_fdr"] is not None
    assert detail["target_fdr"]["p_value"] == 0.03
    conn.close()


def test_run_detail_cpcv_skips_dm_and_holdout(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5,
               config={"name": "c", "validation": {"scheme": "cpcv", "n_groups": 7, "k_test_groups": 2}},
               status="done")
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    for path_id in range(6):
        db.add_fold_metrics(conn, trial_id, path_id, "test_path", {"F1_dir": 0.5 + path_id * 0.01})

    detail = trackhistory.run_detail(conn, "run1")
    assert detail["is_cpcv"] is True
    assert detail["cpcv_info"]["n_paths"] == 6
    assert detail["dm_result"] is None
    assert detail["holdout_f1_dir"] is None
    assert detail["path_distributions"][trial_id]["n_paths"] == 6
    conn.close()


def test_target_detail_returns_none_when_no_history(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    assert trackhistory.target_detail(conn, "^VIX") is None
    conn.close()


def test_target_detail_aggregates_across_runs(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    _make_run(conn, "run2", "^VIX", 10, status="done")
    detail = trackhistory.target_detail(conn, "^VIX")
    assert detail["target"] == "^VIX"
    assert detail["n_runs"] == 2
    assert 5 in detail["pbo_by_horizon"]
    assert 10 in detail["pbo_by_horizon"]
    conn.close()


def test_universe_overview_marks_known_symbol_with_history(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    groups = trackhistory.universe_overview(conn)
    flat = {s["symbol"]: s for g in groups for s in g["symbols"]}
    assert "^VIX" in flat
    assert flat["^VIX"]["n_runs"] == 1
    assert flat["^VIX"]["n_done"] == 1
    other = next(s for s in flat.values() if s["symbol"] != "^VIX")
    assert other["n_runs"] == 0
    conn.close()
