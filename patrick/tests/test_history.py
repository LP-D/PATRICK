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


def test_latest_predictions_by_target_and_horizon_partitions_by_horizon(tmp_path):
    """`/predictions` (vue d'ensemble) needs one row per (target, horizon),
    not one per target collapsed across horizons like
    `latest_predictions_by_target()` -- ^VIX h=5 and ^VIX h=10 must resolve
    to their OWN latest prediction, not both silently reporting whichever
    of the two happens to win the target-wide "most recent" comparison."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run_h5", "^VIX", 5, status="done")
    trial_h5 = db.create_trial(conn, "run_h5", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.add_predictions(conn, trial_h5, fold_index=None, split="live",
                        ts=["2024-01-01T00:00:00"], y_true=[None], y_pred=[3], y_proba=[0.7])

    _make_run(conn, "run_h10", "^VIX", 10, status="done")
    trial_h10 = db.create_trial(conn, "run_h10", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.add_predictions(conn, trial_h10, fold_index=None, split="live",
                        ts=["2024-02-01T00:00:00"], y_true=[None], y_pred=[0], y_proba=[0.6])

    out = trackhistory.latest_predictions_by_target_and_horizon(conn, ["^VIX"], [5, 10])
    assert set(out.keys()) == {("^VIX", 5), ("^VIX", 10)}
    assert out[("^VIX", 5)]["direction"] == "UP"
    assert out[("^VIX", 5)]["run_id"] == "run_h5"
    assert out[("^VIX", 10)]["direction"] == "DOWN"
    assert out[("^VIX", 10)]["run_id"] == "run_h10"
    # Un horizon sans aucune prediction est simplement absent (pas de cle a moitie remplie).
    assert ("^VIX", 3) not in out
    conn.close()


def test_latest_predictions_by_target_and_horizon_is_not_n_plus_1(tmp_path):
    """Meme discipline de performance que `latest_predictions_by_target()`
    (voir `test_synthesis_overview_latest_prediction_lookup_is_not_n_plus_1`) :
    une seule requete groupee pour tout le produit (target x horizon), pas
    une par paire -- sous-requete correlee, pas ROW_NUMBER() OVER PARTITION
    (mesure plus lente sur la vraie base ~12M lignes, voir docstring de
    `latest_predictions_by_target`)."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    targets = [f"SYM{i}" for i in range(10)]
    horizons = [1, 5, 10]
    for i, target in enumerate(targets):
        for h in horizons:
            run_id = f"run_{i}_{h}"
            _make_run(conn, run_id, target, h, status="done")
            trial_id = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
            db.add_predictions(conn, trial_id, fold_index=None, split="live",
                                ts=["2024-01-01T00:00:00"], y_true=[None], y_pred=[3], y_proba=[0.7])

    queries: list[str] = []
    conn.set_trace_callback(lambda sql: queries.append(sql))
    out = trackhistory.latest_predictions_by_target_and_horizon(conn, targets, horizons)
    conn.set_trace_callback(None)

    assert len(out) == len(targets) * len(horizons)
    per_pair_lookup_queries = [
        q for q in queries
        if "JOIN trial ON trial.trial_id = prediction.trial_id" in q and "WHERE r2.target =" in q
    ]
    assert len(per_pair_lookup_queries) <= 1, (
        f"{len(per_pair_lookup_queries)} per-(target,horizon) prediction lookups for "
        f"{len(targets)}x{len(horizons)} pairs -- expected a single grouped query"
    )
    conn.close()


def test_direction_metrics_by_target_and_horizon_partitions_by_horizon(tmp_path):
    """Meme correction que `latest_predictions_by_target_and_horizon` mais
    pour la fiabilite (F1 par direction) : chaque horizon doit resoudre son
    PROPRE dernier run 'done', pas le plus recent du ticker tous horizons
    confondus. Inclut aussi le resultat Diebold-Mariano (p_value/baseline)
    du run resolu -- c'est ce qui alimente le badge ok/warning de
    /predictions, meme semantique que run_detail.html ("ok" si p < 0.05)."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run_h5", "^VIX", 5, status="done")
    trial_h5 = db.create_trial(conn, "run_h5", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_h5)
    db.add_predictions(conn, trial_h5, fold_index=1, split="test",
                        ts=["2024-01-01", "2024-01-02"], y_true=[3, 0], y_pred=[3, 0], y_proba=[0.7, 0.7])
    db.save_dm_result(conn, "run_h5", {"baseline": "majority", "dm_stat": 2.1, "p_value": 0.03})

    _make_run(conn, "run_h10", "^VIX", 10, status="done")
    trial_h10 = db.create_trial(conn, "run_h10", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_h10)
    db.add_predictions(conn, trial_h10, fold_index=1, split="test",
                        ts=["2024-01-01", "2024-01-02"], y_true=[3, 0], y_pred=[0, 0], y_proba=[0.6, 0.6])
    db.save_dm_result(conn, "run_h10", {"baseline": "majority", "dm_stat": 0.5, "p_value": 0.42})

    out = trackhistory.direction_metrics_by_target_and_horizon(conn, ["^VIX"], [5, 10])
    assert set(out.keys()) == {("^VIX", 5), ("^VIX", 10)}
    assert out[("^VIX", 5)]["run_id"] == "run_h5"
    assert out[("^VIX", 5)]["dm_result"]["p_value"] == 0.03
    assert out[("^VIX", 10)]["run_id"] == "run_h10"
    assert out[("^VIX", 10)]["dm_result"]["p_value"] == 0.42
    conn.close()


def test_direction_metrics_by_target_and_horizon_is_not_n_plus_1(tmp_path):
    """Meme discipline de performance que
    `test_synthesis_overview_direction_metrics_lookup_is_not_n_plus_1`,
    etendue a (target, horizon)."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    targets = [f"SYM{i}" for i in range(10)]
    horizons = [1, 5, 10]
    for i, target in enumerate(targets):
        for h in horizons:
            run_id = f"run_{i}_{h}"
            _make_run(conn, run_id, target, h, status="done")
            trial_id = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
            db.mark_best_trial(conn, trial_id)
            db.add_predictions(conn, trial_id, fold_index=1, split="test",
                                ts=["2024-01-01", "2024-01-02"], y_true=[3, 0], y_pred=[3, 0],
                                y_proba=[0.7, 0.7])

    queries: list[str] = []
    conn.set_trace_callback(lambda sql: queries.append(sql))
    out = trackhistory.direction_metrics_by_target_and_horizon(conn, targets, horizons)
    conn.set_trace_callback(None)

    assert len(out) == len(targets) * len(horizons)
    per_pair_run_lookups = [q for q in queries if "run.target = thl.target AND run.horizon = thl.horizon" in q]
    assert len(per_pair_run_lookups) <= 1, (
        f"{len(per_pair_run_lookups)} per-(target,horizon) run lookups for "
        f"{len(targets)}x{len(horizons)} pairs -- expected a single grouped query"
    )
    conn.close()


# --- Phase 3 (suivi prediction -> realise) : live_hit_rate_by_target_and_horizon ---
# TDD : ces tests sont ecrits AVANT l'implementation de la fonction (elle
# n'existe pas encore dans tracking/history.py au moment ou ce bloc est
# ajoute) -- ils doivent d'abord echouer avec AttributeError, puis passer une
# fois la fonction ecrite, sur des proportions hit/miss connues a l'avance.

def _add_live_prediction(conn, trial_id: int, ts: str, *, y_pred: int, y_true: float | None,
                          y_proba: float | None = 0.6) -> None:
    db.add_predictions(conn, trial_id, fold_index=None, split="live",
                        ts=[ts], y_true=[y_true], y_pred=[y_pred], y_proba=[y_proba])


def test_live_hit_rate_by_target_and_horizon_computes_known_proportion(tmp_path):
    """3 hits / 2 miss connus a l'avance (voir predict.py : y_true du split
    'live' est BINAIRE -- 1.0=UP/0.0=DOWN -- alors que y_pred reste la
    classe 4-classes 0..3 ; un hit = (y_pred >= 2) == bool(y_true))."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    _add_live_prediction(conn, trial_id, "2024-01-01", y_pred=3, y_true=1.0)  # hit (UP/UP)
    _add_live_prediction(conn, trial_id, "2024-01-02", y_pred=0, y_true=0.0)  # hit (DOWN/DOWN)
    _add_live_prediction(conn, trial_id, "2024-01-03", y_pred=2, y_true=1.0)  # hit (UP/UP)
    _add_live_prediction(conn, trial_id, "2024-01-04", y_pred=3, y_true=0.0)  # miss (UP/DOWN)
    _add_live_prediction(conn, trial_id, "2024-01-05", y_pred=0, y_true=1.0)  # miss (DOWN/UP)

    out = trackhistory.live_hit_rate_by_target_and_horizon(conn, ["^VIX"], [5])
    result = out[("^VIX", 5)]
    assert result["n"] == 5
    assert result["n_hits"] == 3
    assert result["hit_rate"] == 0.6
    conn.close()


def test_live_hit_rate_by_target_and_horizon_excludes_unbackfilled(tmp_path):
    """Une prediction 'live' pas encore backfillee (y_true IS NULL, cf.
    predict.py::predict_live avant que l'horizon ne soit ecoule) ne doit ni
    compter dans n, ni dans le calcul -- seul le resultat REALISE compte."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    _add_live_prediction(conn, trial_id, "2024-01-01", y_pred=3, y_true=1.0)  # hit
    _add_live_prediction(conn, trial_id, "2024-01-02", y_pred=3, y_true=None)  # pas encore connu

    out = trackhistory.live_hit_rate_by_target_and_horizon(conn, ["^VIX"], [5])
    result = out[("^VIX", 5)]
    assert result["n"] == 1
    assert result["hit_rate"] == 1.0
    conn.close()


def test_live_hit_rate_by_target_and_horizon_respects_window(tmp_path):
    """Fenetre glissante : seules les `window` predictions live les plus
    RECENTES (par ts) avec resultat connu entrent dans le calcul -- pas tout
    l'historique."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    trial_id = db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_id)
    # 3 plus anciennes : toutes miss. 2 plus recentes : toutes hit.
    _add_live_prediction(conn, trial_id, "2024-01-01", y_pred=3, y_true=0.0)  # miss (ancien)
    _add_live_prediction(conn, trial_id, "2024-01-02", y_pred=3, y_true=0.0)  # miss (ancien)
    _add_live_prediction(conn, trial_id, "2024-01-03", y_pred=3, y_true=0.0)  # miss (ancien)
    _add_live_prediction(conn, trial_id, "2024-01-04", y_pred=3, y_true=1.0)  # hit (recent)
    _add_live_prediction(conn, trial_id, "2024-01-05", y_pred=3, y_true=1.0)  # hit (recent)

    out = trackhistory.live_hit_rate_by_target_and_horizon(conn, ["^VIX"], [5], window=2)
    result = out[("^VIX", 5)]
    assert result["n"] == 2
    assert result["n_hits"] == 2
    assert result["hit_rate"] == 1.0
    assert result["window"] == 2
    conn.close()


def test_live_hit_rate_by_target_and_horizon_partitions_by_horizon(tmp_path):
    """Meme cible, deux horizons distincts : chaque (cible, horizon) doit
    resoudre ses PROPRES predictions live, pas celles de l'autre horizon."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run_h5", "^VIX", 5, status="done")
    trial_h5 = db.create_trial(conn, "run_h5", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_h5)
    _add_live_prediction(conn, trial_h5, "2024-01-01", y_pred=3, y_true=1.0)  # hit

    _make_run(conn, "run_h10", "^VIX", 10, status="done")
    trial_h10 = db.create_trial(conn, "run_h10", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    db.mark_best_trial(conn, trial_h10)
    _add_live_prediction(conn, trial_h10, "2024-01-01", y_pred=3, y_true=0.0)  # miss

    out = trackhistory.live_hit_rate_by_target_and_horizon(conn, ["^VIX"], [5, 10])
    assert out[("^VIX", 5)]["hit_rate"] == 1.0
    assert out[("^VIX", 10)]["hit_rate"] == 0.0
    conn.close()


def test_live_hit_rate_by_target_and_horizon_none_when_no_live_predictions(tmp_path):
    """Un couple (cible, horizon) avec un run/trial mais aucune prediction
    live backfillee retourne None (present, distinct d'une cle absente pour
    un couple sans run du tout) -- meme convention que
    `direction_metrics_by_target_and_horizon`."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    _make_run(conn, "run1", "^VIX", 5, status="done")
    db.create_trial(conn, "run1", "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
    # Pas de mark_best_trial : aucune prediction live n'a jamais ete ecrite.

    out = trackhistory.live_hit_rate_by_target_and_horizon(conn, ["^VIX"], [5])
    assert ("^VIX", 5) not in out or out[("^VIX", 5)] is None
    # Couple totalement inconnu (aucun run) : absent.
    assert ("AAPL", 5) not in trackhistory.live_hit_rate_by_target_and_horizon(conn, ["AAPL"], [5])
    conn.close()


def test_live_hit_rate_by_target_and_horizon_is_not_n_plus_1(tmp_path):
    """Meme discipline de performance NON NEGOCIABLE que les fonctions
    voisines (`direction_metrics_by_target_and_horizon`,
    `latest_predictions_by_target_and_horizon`) : une requete de resolution
    (target,horizon)->trial_id, puis UNE requete groupee `trial_id IN (...)`
    pour recuperer toutes les lignes live -- jamais une requete par paire,
    jamais de ROW_NUMBER() OVER (PARTITION BY ...)."""
    conn = db.connect(str(tmp_path / "patrick.db"))
    targets = [f"SYM{i}" for i in range(10)]
    horizons = [1, 5, 10]
    for i, target in enumerate(targets):
        for h in horizons:
            run_id = f"run_{i}_{h}"
            _make_run(conn, run_id, target, h, status="done")
            trial_id = db.create_trial(conn, run_id, "GLOBAL", "RandomForest", "SMOTE", 8, "shap")
            db.mark_best_trial(conn, trial_id)
            _add_live_prediction(conn, trial_id, "2024-01-01", y_pred=3, y_true=1.0)

    queries: list[str] = []
    conn.set_trace_callback(lambda sql: queries.append(sql))
    out = trackhistory.live_hit_rate_by_target_and_horizon(conn, targets, horizons)
    conn.set_trace_callback(None)

    assert len(out) == len(targets) * len(horizons)
    assert all(v is not None for v in out.values())
    prediction_queries = [q for q in queries if "FROM prediction" in q]
    assert len(prediction_queries) <= 1, (
        f"{len(prediction_queries)} queries touching `prediction` for "
        f"{len(targets)}x{len(horizons)} pairs -- expected a single grouped fetch"
    )
    window_function_queries = [q for q in queries if "OVER" in q.upper() and "PARTITION" in q.upper()]
    assert not window_function_queries, "ROW_NUMBER()/PARTITION BY forbidden per CLAUDE.md perf discipline"
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
