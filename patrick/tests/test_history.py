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


def test_synthesis_overview_latest_prediction_lookup_is_not_n_plus_1(tmp_path):
    """P8 bug report: `/` hung for 50s+ against the real local DB (~2.2 GB,
    550 targets). Root cause traced (faulthandler stack dump, bypassing the
    web layer entirely) to `latest_prediction_for_target()` being called
    once per target inside `synthesis_overview()`'s loop -- a database round
    trip per target instead of one grouped query. `/phase9` and `/universe`
    responded in <0.1s against the same DB, so the DB/connection itself
    isn't the bottleneck -- the per-target query count is.

    Regression guard: count the queries actually sent to sqlite (`sqlite3.
    Connection.set_trace_callback`) during a single `synthesis_overview()`
    call. `set_trace_callback` reports the EXPANDED SQL (parameter values
    inlined, e.g. `run.target = 'SYM3'`, not `run.target = ?`) -- matched
    below by the `WHERE run.target =` prefix rather than a literal `?`.
    That WHERE clause is unique to the old per-target lookup --
    `direction_metrics_for_target()` (a separate, NOT-yet-fixed N+1 in the
    same loop, see history.py) queries `prediction` too but with a
    different WHERE clause (`trial_id = ...`), so this filter isolates just
    the query under test."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    n_targets = 40
    for i in range(n_targets):
        target = f"SYM{i}"
        _make_run(conn, f"run{i}", target, 5, status="done")
        trial_id = db.create_trial(conn, f"run{i}", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
        db.add_predictions(conn, trial_id, fold_index=None, split="live",
                            ts=["2024-01-01T00:00:00"], y_true=[None], y_pred=[3], y_proba=[0.8])

    queries: list[str] = []
    conn.set_trace_callback(lambda sql: queries.append(sql))
    trackhistory.synthesis_overview(conn)
    conn.set_trace_callback(None)

    per_target_lookup_queries = [
        q for q in queries
        if "JOIN trial ON trial.trial_id = prediction.trial_id" in q and "WHERE run.target =" in q
    ]
    assert len(per_target_lookup_queries) <= 1, (
        f"{len(per_target_lookup_queries)} per-target prediction lookups for {n_targets} targets "
        "-- expected a single grouped query, not one round trip per target"
    )
    conn.close()


def test_synthesis_overview_direction_metrics_lookup_is_not_n_plus_1(tmp_path):
    """Same shape of bug as `latest_prediction_for_target`, flagged
    separately in that fix's commit and now confirmed to be the function
    still blocking `/` end-to-end against the real DB once the first N+1
    was fixed (faulthandler stack dump landed on
    `direction_metrics_for_target()`, line ~500, not the already-fixed
    lookup).

    Worse pattern than the first case: THREE sequential queries per target,
    not one -- (1) latest 'done' run for the target, (2) that run's
    is_best trial (`_best_trial_id`, shared helper), (3) test predictions
    for that trial, with a conditional 4th query falling back to 'holdout'
    predictions if (3) returns nothing. Isolated below via the run lookup's
    literal SQL (`SELECT run_id FROM run WHERE target =`), unique to this
    function -- `list_distinct_targets` uses a different `status = 'done'`
    shape (a CASE WHEN, not a WHERE), and `list_runs`'s own `_best_trial_id`/
    `_avg_metric` calls (for `recent_runs`, same `synthesis_overview()`
    call) never touch `run_id FROM run WHERE target =` at all, so they
    don't leak into this count."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    n_targets = 40
    for i in range(n_targets):
        target = f"SYM{i}"
        run_id = f"run{i}"
        _make_run(conn, run_id, target, 5, status="done")
        trial_id = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
        db.mark_best_trial(conn, trial_id)
        db.add_predictions(conn, trial_id, fold_index=1, split="test",
                            ts=["2024-01-01", "2024-01-02"], y_true=[3, 0], y_pred=[3, 0],
                            y_proba=[0.7, 0.7])

    queries: list[str] = []
    conn.set_trace_callback(lambda sql: queries.append(sql))
    trackhistory.synthesis_overview(conn)
    conn.set_trace_callback(None)

    per_target_run_lookups = [q for q in queries if "SELECT run_id FROM run WHERE target =" in q]
    assert len(per_target_run_lookups) <= 1, (
        f"{len(per_target_run_lookups)} per-target run lookups for {n_targets} targets "
        "-- expected a single grouped query, not one round trip per target"
    )
    conn.close()


def test_phase_breakdown_for_run_empty_when_no_timing_recorded(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    breakdown = trackhistory.phase_breakdown_for_run(conn, "run1")
    assert breakdown["phases"] == []
    conn.close()


def test_phase_breakdown_for_run_sums_duration_and_counts_occurrences_per_phase(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")

    db.record_phase_timing(conn, "run1", "ingestion", started_at=0.0, finished_at=10.0)
    db.record_phase_timing(conn, "run1", "pool_construction", started_at=10.0, finished_at=25.0)
    db.record_phase_timing(conn, "run1", "scan", started_at=25.0, finished_at=85.0)
    # tuning happens twice (two top-configs) -- must be summed, not overwritten
    db.record_phase_timing(conn, "run1", "tuning", started_at=85.0, finished_at=115.0)
    db.record_phase_timing(conn, "run1", "tuning", started_at=115.0, finished_at=135.0)

    breakdown = trackhistory.phase_breakdown_for_run(conn, "run1")
    by_phase = {p["phase"]: p for p in breakdown["phases"]}

    assert by_phase["ingestion"]["duration_s"] == 10
    assert by_phase["pool_construction"]["duration_s"] == 15
    assert by_phase["scan"]["duration_s"] == 60
    assert by_phase["tuning"]["duration_s"] == 50  # 30 + 20, summed across 2 occurrences
    assert by_phase["tuning"]["occurrences"] == 2
    assert by_phase["ingestion"]["occurrences"] == 1

    # Ordered by duration descending -- the point of a breakdown is to see
    # the dominant phase first without re-sorting client-side.
    assert [p["phase"] for p in breakdown["phases"]] == ["scan", "tuning", "pool_construction", "ingestion"]
    conn.close()


def test_phase_breakdown_for_run_reports_unaccounted_time_against_run_total(tmp_path):
    """The 4 instrumented phases don't necessarily cover 100% of a run's
    wall time (model export, holdout diagnostic, etc. aren't instrumented)
    -- phase_breakdown_for_run must say so rather than imply full coverage."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    db.record_phase_timing(conn, "run1", "scan", started_at=0.0, finished_at=60.0)

    breakdown = trackhistory.phase_breakdown_for_run(conn, "run1")
    assert breakdown["run_total_s"] is not None
    assert breakdown["unaccounted_s"] == breakdown["run_total_s"] - 60
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


def _set_started_at(conn, run_id: str, started_at: str) -> None:
    """Test-only helper: `create_run()` always stamps `datetime('now')`
    (db.py), giving every run in a fast test the SAME second-resolution
    timestamp -- useless for asserting chronological ordering. Backdates a
    run's `started_at` directly so successive runs can be seeded with
    distinct, controlled timestamps."""
    conn.execute("UPDATE run SET started_at = ? WHERE run_id = ?", (started_at, run_id))
    conn.commit()


def test_phase_timing_drift_for_target_empty_when_no_runs(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    assert trackhistory.phase_timing_drift_for_target(conn, "^VIX") == []
    conn.close()


def test_phase_timing_drift_for_target_empty_when_runs_have_no_phase_timing(tmp_path):
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    assert trackhistory.phase_timing_drift_for_target(conn, "^VIX") == []
    conn.close()


def test_phase_timing_drift_for_target_orders_points_chronologically_across_runs(tmp_path):
    """P9 -- seed 3 successive runs for the same ticker, inserted OUT of
    chronological order on purpose (run3 first) with distinct `started_at`
    and distinct per-phase durations. The function must return one point
    per (run, phase), ordered by `started_at` ascending (oldest run first)
    regardless of insertion/run_id order -- ready to plot as a time series
    without client-side re-sorting."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run3", "^VIX", 5, status="done")
    _set_started_at(conn, "run3", "2026-01-03 00:00:00")
    db.record_phase_timing(conn, "run3", "scan", started_at=0.0, finished_at=90.0)
    db.record_phase_timing(conn, "run3", "tuning", started_at=90.0, finished_at=110.0)

    _make_run(conn, "run1", "^VIX", 5, status="done")
    _set_started_at(conn, "run1", "2026-01-01 00:00:00")
    db.record_phase_timing(conn, "run1", "scan", started_at=0.0, finished_at=60.0)
    db.record_phase_timing(conn, "run1", "tuning", started_at=60.0, finished_at=90.0)

    _make_run(conn, "run2", "^VIX", 5, status="done")
    _set_started_at(conn, "run2", "2026-01-02 00:00:00")
    db.record_phase_timing(conn, "run2", "scan", started_at=0.0, finished_at=75.0)
    db.record_phase_timing(conn, "run2", "tuning", started_at=75.0, finished_at=100.0)

    # A different ticker's run must never leak into this ticker's drift.
    _make_run(conn, "other", "AAPL", 5, status="done")
    db.record_phase_timing(conn, "other", "scan", started_at=0.0, finished_at=999.0)

    points = trackhistory.phase_timing_drift_for_target(conn, "^VIX")

    assert [p["run_id"] for p in points] == ["run1", "run1", "run2", "run2", "run3", "run3"]
    assert [p["started_at"] for p in points] == [
        "2026-01-01 00:00:00", "2026-01-01 00:00:00",
        "2026-01-02 00:00:00", "2026-01-02 00:00:00",
        "2026-01-03 00:00:00", "2026-01-03 00:00:00",
    ]
    by_run_phase = {(p["run_id"], p["phase"]): p["duration_s"] for p in points}
    assert by_run_phase[("run1", "scan")] == 60
    assert by_run_phase[("run1", "tuning")] == 30
    assert by_run_phase[("run2", "scan")] == 75
    assert by_run_phase[("run2", "tuning")] == 25
    assert by_run_phase[("run3", "scan")] == 90
    assert by_run_phase[("run3", "tuning")] == 20
    conn.close()


def test_phase_timing_drift_for_target_sums_multiple_occurrences_of_same_phase(tmp_path):
    """`tuning` (and in principle any phase) can occur more than once per
    run_id -- same rule as `phase_breakdown_for_run` -- must be summed into
    ONE point per (run, phase), not returned as separate rows."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    _set_started_at(conn, "run1", "2026-01-01 00:00:00")
    db.record_phase_timing(conn, "run1", "tuning", started_at=0.0, finished_at=20.0)
    db.record_phase_timing(conn, "run1", "tuning", started_at=20.0, finished_at=45.0)

    points = trackhistory.phase_timing_drift_for_target(conn, "^VIX")
    assert len(points) == 1
    assert points[0]["phase"] == "tuning"
    assert points[0]["duration_s"] == 45
    conn.close()
