"""Phase 7 (interface) -- READ-ONLY queries for browsing the history of runs
already persisted in the database: no new model computation, no influence on
a run in progress. Serves `webapp/app.py` (`/runs`, `/runs/{id}`,
`/targets/{ticker}`, `/universe`, `/` -- Phase 8 synthesis) -- the same
validity components (PBO, Diebold-Mariano, FDR, feature stability, holdout
diagnostic) as `tracking/report.py`/`tracking/stats.py`, never reimplemented:
recomputed on the fly on request (no cache), so always up to date with the
target's latest run -- unlike `report.py`, which can only display
holdout/DM/PBO for a run launched from the web interface (a limitation of
the `job.result_json` mechanism), these queries also work for a CLI
`patrick run`/`patrick resume`: `dm_result` (migration 0009) and
`fold_metric[split='holdout']` are written by `pipeline/engine.py`
independently of any `job_id`.
"""
from __future__ import annotations

import json
import sqlite3

from sklearn.metrics import precision_recall_fscore_support

from patrick.config import defaults as D
from patrick.selection import stability as stability_module
from patrick.tracking import db as trackdb
from patrick.tracking import holdout_diagnostic as trackholdout
from patrick.tracking import stats as trackstats
from patrick.validation.cpcv import n_paths as cpcv_n_paths
from patrick.validation.cpcv import path_performance_distribution

# Direction encoding of the 4-class (direction x amplitude) target scheme --
# same convention as `validation.metrics._DIR_MAP` (not imported: that name
# is underscore-private to that module, and this is a 4-entry labeling fact,
# not logic worth coupling two modules over).
_CLASS_DIRECTION = {0: "DOWN", 1: "DOWN", 2: "UP", 3: "UP"}
_CLASS_AMPLITUDE = {0: "FORT", 1: "FAIBLE", 2: "FAIBLE", 3: "FORT"}
_MIN_DIRECTION_SAMPLES = 10  # same threshold as metrics.py's own FORT/FAIBLE breakdown


def _config_field(config_json: str | None, *path, default=None):
    if not config_json:
        return default
    try:
        node = json.loads(config_json)
    except (TypeError, ValueError):
        return default
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return node if node is not None else default


def _run_scheme(config_json: str | None) -> str:
    return _config_field(config_json, "validation", "scheme", default="walkforward")


def _run_name(config_json: str | None) -> str | None:
    return _config_field(config_json, "name")


def _best_trial_id(conn: sqlite3.Connection, run_id: str) -> int | None:
    row = conn.execute(
        "SELECT trial_id FROM trial WHERE run_id = ? AND is_best = 1 LIMIT 1", (run_id,)
    ).fetchone()
    return row[0] if row else None


def _avg_metric(conn: sqlite3.Connection, trial_id: int, splits: tuple[str, ...],
                 metric: str = "F1_dir") -> float | None:
    placeholders = ",".join("?" for _ in splits)
    row = conn.execute(
        f"SELECT AVG(value) FROM fold_metric WHERE trial_id = ? AND split IN ({placeholders}) "
        "AND metric = ?",
        (trial_id, *splits, metric),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


def _dm_result_for_run(conn: sqlite3.Connection, run_id: str, kind: str = "class_specific") -> dict | None:
    """Phase X5 (migration 0010): a walk-forward run now has TWO `dm_result`
    rows (class_specific + common) -- `kind` selects which one,
    `"class_specific"` by default (the MAIN result shown everywhere except
    on explicit request for the common comparison)."""
    row = conn.execute(
        "SELECT baseline, dm_stat, p_value, computed_at FROM dm_result WHERE run_id = ? AND kind = ?",
        (run_id, kind),
    ).fetchone()
    if row is None:
        return None
    return {"baseline": row[0], "dm_stat": row[1], "p_value": row[2], "computed_at": row[3]}


def phase_breakdown_for_run(conn: sqlite3.Connection, run_id: str) -> dict:
    """P8.2 perf instrumentation -- wall-time breakdown for one run_id from
    `run_phase_timing` (migration 0016), sourced by
    `pipeline/engine.py::run_pipeline`'s `db.record_phase_timing()` calls.
    Answers "where does the wall time go" directly from the database
    instead of a manual DB read-out after the fact (see the 2026-08-23
    performance investigation).

    `duration_s`/`occurrences` are summed per phase (a phase can occur more
    than once per run_id -- `tuning` runs once per top-config, see the
    migration's docstring), ordered by duration descending so the dominant
    phase reads first without client-side sorting.

    `unaccounted_s` = `run_total_s` (`run.finished_at` - `run.started_at`)
    minus the sum of all recorded phase durations: the 4 instrumented
    phases do NOT necessarily cover the whole run (model export, holdout
    diagnostic, and the walk-forward folds' lazy per-fold pool builds
    beyond the first are not separately instrumented, see the migration's
    "known limitation" note) -- reported explicitly rather than implying
    full coverage. `None` for a run still `running` (no `finished_at` yet)
    or unknown."""
    run_row = conn.execute(
        "SELECT started_at, finished_at FROM run WHERE run_id = ?", (run_id,)
    ).fetchone()
    run_total_s = None
    if run_row and run_row[0] and run_row[1]:
        row = conn.execute(
            "SELECT strftime('%s', ?) - strftime('%s', ?)", (run_row[1], run_row[0])
        ).fetchone()
        run_total_s = row[0]

    rows = conn.execute(
        "SELECT phase, "
        "SUM(strftime('%s', finished_at) - strftime('%s', started_at)) AS duration_s, "
        "COUNT(*) AS occurrences "
        "FROM run_phase_timing WHERE run_id = ? "
        "GROUP BY phase ORDER BY duration_s DESC",
        (run_id,),
    ).fetchall()
    phases = [{"phase": phase, "duration_s": duration_s, "occurrences": occurrences}
              for phase, duration_s, occurrences in rows]

    unaccounted_s = None
    if run_total_s is not None:
        unaccounted_s = run_total_s - sum(p["duration_s"] for p in phases)

    return {"run_total_s": run_total_s, "unaccounted_s": unaccounted_s, "phases": phases}


def list_runs(conn: sqlite3.Connection, *, target: str | None = None,
              status: str | None = None, scheme: str | None = None,
              limit: int = 200) -> list[dict]:
    """P7.1 -- `/runs` browser: one row per run, most recent first. `scheme`
    filters after reading (not a `run` column, only present in
    `config_json`) -- acceptable, a single local user's history stays
    modestly sized."""
    clauses, params = [], []
    if target:
        clauses.append("run.target = ?")
        params.append(target)
    if status:
        clauses.append("run.status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT run.run_id, run.target, run.horizon, run.status, run.started_at, "
        f"run.finished_at, run.n_trials, run.config_json, dm.p_value "
        f"FROM run LEFT JOIN dm_result dm ON dm.run_id = run.run_id AND dm.kind = 'class_specific' "
        f"{where} ORDER BY run.started_at DESC, run.rowid DESC LIMIT ?",
        (*params, limit),
    ).fetchall()

    out = []
    for run_id, tgt, horizon, status_, started_at, finished_at, n_trials, config_json, dm_p in rows:
        run_scheme = _run_scheme(config_json)
        if scheme and run_scheme != scheme:
            continue
        best_id = _best_trial_id(conn, run_id)
        best_f1 = (_avg_metric(conn, best_id, ("test", "test_path")) if best_id is not None else None)
        out.append({
            "run_id": run_id, "target": tgt, "horizon": horizon, "status": status_,
            "started_at": started_at, "finished_at": finished_at, "n_trials": n_trials,
            "name": _run_name(config_json), "scheme": run_scheme,
            "best_f1_dir": best_f1, "dm_p_value": dm_p,
        })
    return out


def list_distinct_targets(conn: sqlite3.Connection) -> list[dict]:
    """Targets with at least one run in the database, with counts -- feeds
    the `/runs` filter and the `/universe` table (joined with
    `DEFAULT_TARGET_GROUPS`, see `universe_overview`)."""
    rows = conn.execute(
        "SELECT target, COUNT(*), SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END), "
        "MAX(started_at) FROM run GROUP BY target ORDER BY MAX(started_at) DESC"
    ).fetchall()
    return [{"target": t, "n_runs": n, "n_done": n_done, "last_started_at": last}
            for t, n, n_done, last in rows]


def _trials_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT trial_id, regime, algo, sampler, n_features, selector, is_best "
        "FROM trial WHERE run_id = ? ORDER BY is_best DESC, trial_id", (run_id,),
    ).fetchall()
    trials = []
    for trial_id, regime, algo, sampler, n_features, selector, is_best in rows:
        trials.append({
            "trial_id": trial_id, "regime": regime, "algo": algo, "sampler": sampler,
            "n_features": n_features, "selector": selector, "is_best": bool(is_best),
            "test_f1_dir": _avg_metric(conn, trial_id, ("test", "test_path")),
            "holdout_f1_dir": _avg_metric(conn, trial_id, ("holdout",)),
        })
    return trials


def _baselines_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT baseline, metric, value FROM baseline_metric "
        "WHERE run_id = ? AND split = 'test' ORDER BY baseline, metric", (run_id,),
    ).fetchall()
    out: dict[str, dict[str, float]] = {}
    for baseline, metric, value in rows:
        out.setdefault(baseline, {})[metric] = value
    return [{"baseline": b, "metrics": m} for b, m in out.items()]


def _path_distribution_for_trial(conn: sqlite3.Connection, trial_id: int) -> dict | None:
    rows = conn.execute(
        "SELECT value FROM fold_metric WHERE trial_id = ? AND split = 'test_path' AND metric = 'F1_dir'",
        (trial_id,),
    ).fetchall()
    if not rows:
        return None
    return path_performance_distribution({i: v for i, (v,) in enumerate(rows)})


def run_detail(conn: sqlite3.Connection, run_id: str, fdr_alpha: float = 0.10) -> dict | None:
    """P7.2 -- `/runs/{id}` detail page: same components as `report.py`
    (never recomputed differently), but returned as a Python structure for
    a Jinja template rather than pre-formatted HTML."""
    run = trackdb.get_run(conn, run_id)
    if run is None:
        return None
    config = json.loads(run["config_json"]) if run.get("config_json") else {}
    val_cfg = config.get("validation", {})
    scheme = val_cfg.get("scheme", "walkforward")
    is_cpcv = scheme == "cpcv"

    trials = _trials_for_run(conn, run_id)
    best_trial = next((t for t in trials if t["is_best"]), None)
    path_distributions = ({t["trial_id"]: _path_distribution_for_trial(conn, t["trial_id"])
                            for t in trials} if is_cpcv else {})

    cpcv_info = None
    if is_cpcv:
        n_groups_cfg, k_test_cfg = val_cfg.get("n_groups"), val_cfg.get("k_test_groups")
        cpcv_info = {
            "n_groups": n_groups_cfg, "k_test_groups": k_test_cfg,
            "n_paths": cpcv_n_paths(n_groups_cfg, k_test_cfg) if n_groups_cfg and k_test_cfg else None,
        }

    regime = best_trial["regime"] if best_trial else (trials[0]["regime"] if trials else "GLOBAL")
    pbo = (trackstats.pbo_for_target_cpcv(conn, run["target"], run["horizon"], regime)
           if is_cpcv else trackstats.pbo_for_target(conn, run["target"], run["horizon"], regime))

    dm_result = None if is_cpcv else _dm_result_for_run(conn, run_id)
    holdout_metrics = None if is_cpcv else (best_trial["holdout_f1_dir"] if best_trial else None)
    holdout_diag = trackholdout.spearman_test_vs_holdout(conn, run_id, metric="F1_dir")

    fdr_result = trackstats.fdr_across_targets(conn, alpha=fdr_alpha)
    target_fdr = fdr_result["results"].get(run["target"])

    quality_issues = trackdb.list_data_quality_issues(conn, run["snapshot_id"])
    feature_stability = trackdb.get_feature_stability(conn, run_id)

    return {
        "run": run,
        "config": config,
        "scheme": scheme,
        "is_cpcv": is_cpcv,
        "cpcv_info": cpcv_info,
        "trials": trials,
        "best_trial": best_trial,
        "path_distributions": path_distributions,
        "baselines": _baselines_for_run(conn, run_id),
        "cumulative_trials": trackstats.count_cumulative_trials(conn, run["target"], run["horizon"]),
        "pbo": pbo,
        "pbo_label": "chemins CPCV" if is_cpcv else "blocs walk-forward",
        "dm_result": dm_result,
        "holdout_f1_dir": holdout_metrics,
        "holdout_diag": holdout_diag,
        "fdr_result": fdr_result,
        "target_fdr": target_fdr,
        "data_quality_enabled": config.get("data_quality", {}).get("enabled", True),
        "quality_issues": quality_issues,
        "stability_enabled": config.get("selection", {}).get("track_stability", True),
        "feature_stability": feature_stability,
        "min_mean_jaccard_warning": stability_module.MIN_MEAN_JACCARD_WARNING,
    }


def target_detail(conn: sqlite3.Connection, target: str, fdr_alpha: float = 0.10) -> dict | None:
    """P7.3 -- `/targets/{ticker}` page: aggregated view of the entire run
    history for ONE target (across all horizons/schemes)."""
    runs = conn.execute(
        "SELECT run_id, horizon, status, started_at, finished_at, config_json, n_trials "
        "FROM run WHERE target = ? ORDER BY started_at DESC, rowid DESC", (target,),
    ).fetchall()
    if not runs:
        return None

    run_rows = []
    horizons = set()
    for run_id, horizon, status_, started_at, finished_at, config_json, n_trials in runs:
        horizons.add(horizon)
        best_id = _best_trial_id(conn, run_id)
        best_f1 = (_avg_metric(conn, best_id, ("test", "test_path")) if best_id is not None else None)
        run_rows.append({
            "run_id": run_id, "horizon": horizon, "status": status_,
            "started_at": started_at, "finished_at": finished_at,
            "name": _run_name(config_json), "scheme": _run_scheme(config_json),
            "n_trials": n_trials,
            "best_f1_dir": best_f1, "dm_result": _dm_result_for_run(conn, run_id),
        })

    fdr_result = trackstats.fdr_across_targets(conn, alpha=fdr_alpha)
    target_fdr = fdr_result["results"].get(target)

    pbo_by_horizon = {}
    for horizon in sorted(horizons):
        pbo_by_horizon[horizon] = {
            "walkforward": trackstats.pbo_for_target(conn, target, horizon, "GLOBAL"),
            "cpcv": trackstats.pbo_for_target_cpcv(conn, target, horizon, "GLOBAL"),
        }

    return {
        "target": target,
        "runs": run_rows,
        "n_runs": len(run_rows),
        "cumulative_trials": trackstats.count_cumulative_trials(conn, target),
        "pbo_by_horizon": pbo_by_horizon,
        "fdr_result": fdr_result,
        "target_fdr": target_fdr,
    }


def station_verdict(conn: sqlite3.Connection, fdr_alpha: float = 0.10) -> dict:
    """The only two numbers the product can establish over the ENTIRE
    history: what holds up, and what it cost.

    "What holds up" = targets whose best Diebold-Mariano p-value survives
    the Benjamini-Hochberg correction ACROSS targets. That is the product's
    exit criterion, and also the only honest number at this scale: trying
    550 targets and keeping only the significant one is exactly the bias
    `fdr_across_targets` measures (section 4, METHODOLOGY.md).

    `survivors = None` when no target has a DM result. That is the NOMINAL
    state of a young database, not an edge case: `0 / 0` would read as a
    failure when the measure simply isn't computable yet, and the product
    refuses to print an uninterpretable measure. The caller must
    distinguish the two.

    No new computation: `fdr_across_targets` is the same one `/targets/{t}`
    uses, the counts are direct aggregates. Read-only."""
    fdr = trackstats.fdr_across_targets(conn, alpha=fdr_alpha)
    n_tested = fdr["n_tested"]
    trials = conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0]
    runs, targets = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT target) FROM run"
    ).fetchone()
    return {
        "survivors": fdr["n_bh_significant"] if n_tested else None,
        "n_tested": n_tested,
        "alpha": fdr["alpha"],
        "cumulative_trials": trials,
        "n_runs": runs,
        "n_targets": targets,
    }


def universe_overview(conn: sqlite3.Connection) -> list[dict]:
    """P7.5 -- `/universe`: joins the configurable target universe
    (`config/defaults.py::DEFAULT_TARGET_GROUPS`, already used by the launch
    form) with the actual run history -- no new data, just the join of the
    two."""
    history = {h["target"]: h for h in list_distinct_targets(conn)}
    groups = []
    for group_name, items in D.DEFAULT_TARGET_GROUPS.items():
        source = "fred" if group_name == D.FRED_TARGET_GROUP else "yfinance"
        symbols = []
        for symbol, label in items:
            h = history.get(symbol)
            symbols.append({
                "symbol": symbol, "label": label, "source": source,
                "n_runs": h["n_runs"] if h else 0,
                "n_done": h["n_done"] if h else 0,
                "last_started_at": h["last_started_at"] if h else None,
            })
        groups.append({"group": group_name, "symbols": symbols})
    return groups


def universe_coverage(conn: sqlite3.Connection) -> dict:
    """P8.1 -- same total/touched/done counts `universe.html` already derives
    itself in a Jinja loop over `universe_overview()`, centralized here so
    the synthesis page doesn't re-derive the same three counters a second
    time (B1.5: reuse, not duplicate)."""
    total = touched = done = 0
    for group in universe_overview(conn):
        for s in group["symbols"]:
            total += 1
            if s["n_runs"]:
                touched += 1
            if s["n_done"]:
                done += 1
    return {"total": total, "touched": touched, "done": done}


def last_inference_at(conn: sqlite3.Connection) -> str | None:
    """P8.1 -- most recent `prediction.ts` across ALL targets/splits, the
    single "as of" freshness marker for the coverage banner. `None` on an
    empty `prediction` table (nominal state of a young database, not an
    error)."""
    row = conn.execute("SELECT MAX(ts) FROM prediction").fetchone()
    return row[0] if row else None


def latest_prediction_for_target(conn: sqlite3.Connection, target: str) -> dict | None:
    """P8.1 -- most recent prediction row for this target, across all its
    runs/trials. `split='live'` (Phase 4.6, `patrick predict --live`)
    preferred when present, since it is the only split representing an
    actual forward-looking call -- falls back to the most recent `test`/
    `holdout` row otherwise, never presented as live when it is not.
    `None` if the target has no prediction row at all yet."""
    row = conn.execute(
        "SELECT prediction.ts, prediction.split, prediction.y_pred, prediction.y_proba, "
        "trial.trial_id, run.run_id, run.horizon "
        "FROM prediction "
        "JOIN trial ON trial.trial_id = prediction.trial_id "
        "JOIN run ON run.run_id = trial.run_id "
        "WHERE run.target = ? "
        "ORDER BY (prediction.split = 'live') DESC, prediction.ts DESC LIMIT 1",
        (target,),
    ).fetchone()
    if row is None:
        return None
    ts, split, y_pred, y_proba, trial_id, run_id, horizon = row
    cls = int(round(y_pred))
    return {
        "ts": ts, "split": split, "trial_id": trial_id, "run_id": run_id, "horizon": horizon,
        "direction": _CLASS_DIRECTION.get(cls, "?"),
        "amplitude": _CLASS_AMPLITUDE.get(cls, "?"),
        "confidence": y_proba,
    }


def latest_predictions_by_target(conn: sqlite3.Connection, targets: list[str]) -> dict[str, dict]:
    """P8.1 perf fix -- grouped equivalent of calling
    `latest_prediction_for_target()` once per target: same rule (prefer
    `split='live'`, else most recent `test`/`holdout` row), same per-target
    dict shape, but ONE query for the whole target list instead of one
    round trip each. `synthesis_overview()` was doing the latter -- fine on
    a small dev DB, but O(n_targets) round trips against the real ~2.2 GB /
    12M-row-`prediction` database made `/` hang (regression test:
    `test_synthesis_overview_latest_prediction_lookup_is_not_n_plus_1` in
    `tests/test_history.py`).

    A first version used `ROW_NUMBER() OVER (PARTITION BY run.target ORDER
    BY ...)` -- correct, and cheap on the test-scale DB, but MEASURABLY
    WORSE on the real one: ranking must sort every matching prediction row
    across every requested target before it can discard everything but
    rn=1, so it forces a full sort over a large slice of a 12M-row table
    instead of the cheap `ORDER BY ... LIMIT 1` per-target short-circuit
    the old per-target version got from `idx_run_target`. Below instead
    uses a correlated subquery per target (still ONE round trip: SQLite
    evaluates it as part of a single prepared statement) so each target
    keeps its own indexed `ORDER BY ... LIMIT 1` plan -- measured 3.3s for
    all targets with real predictions on the production DB, vs 50s+
    (timeout) for the old per-target loop. The outer join-back to
    `prediction`/`trial`/`run` via `rowid` reconstitutes the full row
    without repeating the ranking logic.

    Returns a dict keyed by target; a target with no prediction row at all
    is simply absent (same as the old function returning `None` for it)."""
    if not targets:
        return {}
    placeholders = ",".join("?" for _ in targets)
    rows = conn.execute(
        "WITH target_list AS (SELECT DISTINCT target FROM run "
        f"                    WHERE target IN ({placeholders})), "
        "winner AS ("
        "  SELECT tl.target, ("
        "    SELECT p.rowid FROM prediction p "
        "    JOIN trial t2 ON t2.trial_id = p.trial_id "
        "    JOIN run r2 ON r2.run_id = t2.run_id "
        "    WHERE r2.target = tl.target "
        "    ORDER BY (p.split = 'live') DESC, p.ts DESC LIMIT 1"
        "  ) AS pred_rowid "
        "  FROM target_list tl"
        ") "
        "SELECT winner.target, prediction.ts, prediction.split, prediction.y_pred, prediction.y_proba, "
        "       trial.trial_id, run.run_id, run.horizon "
        "FROM winner "
        "JOIN prediction ON prediction.rowid = winner.pred_rowid "
        "JOIN trial ON trial.trial_id = prediction.trial_id "
        "JOIN run ON run.run_id = trial.run_id",
        tuple(targets),
    ).fetchall()
    out: dict[str, dict] = {}
    for target, ts, split, y_pred, y_proba, trial_id, run_id, horizon in rows:
        cls = int(round(y_pred))
        out[target] = {
            "ts": ts, "split": split, "trial_id": trial_id, "run_id": run_id, "horizon": horizon,
            "direction": _CLASS_DIRECTION.get(cls, "?"),
            "amplitude": _CLASS_AMPLITUDE.get(cls, "?"),
            "confidence": y_proba,
        }
    return out


def latest_predictions_by_target_and_horizon(conn: sqlite3.Connection, targets: list[str],
                                              horizons: list[int]) -> dict[tuple[str, int], dict]:
    """`/predictions` (universe-wide overview): same rule and same grouped-
    query discipline as `latest_predictions_by_target()` above (prefer
    `split='live'`, else most recent `test`/`holdout` row; ONE correlated
    subquery per partition key, not `ROW_NUMBER() OVER PARTITION` -- see
    that function's docstring for why the latter is measurably worse on
    the real ~12M-row `prediction` table), just partitioned by
    `(target, horizon)` instead of `target` alone: `run` is already scoped
    one row per horizon (Phase 1.2 schema), so a target's OWN h=5 and h=10
    runs must resolve independently, not have one silently shadow the
    other under a target-wide "most recent" comparison.

    Returns a dict keyed by `(target, horizon)` tuple; a pair with no
    prediction row at all is simply absent."""
    if not targets or not horizons:
        return {}
    target_placeholders = ",".join("?" for _ in targets)
    horizon_placeholders = ",".join("?" for _ in horizons)
    rows = conn.execute(
        "WITH target_horizon_list AS ("
        "  SELECT DISTINCT run.target, run.horizon FROM run "
        f"   WHERE run.target IN ({target_placeholders}) AND run.horizon IN ({horizon_placeholders})"
        "), "
        "winner AS ("
        "  SELECT thl.target, thl.horizon, ("
        "    SELECT p.rowid FROM prediction p "
        "    JOIN trial t2 ON t2.trial_id = p.trial_id "
        "    JOIN run r2 ON r2.run_id = t2.run_id "
        "    WHERE r2.target = thl.target AND r2.horizon = thl.horizon "
        "    ORDER BY (p.split = 'live') DESC, p.ts DESC LIMIT 1"
        "  ) AS pred_rowid "
        "  FROM target_horizon_list thl"
        ") "
        "SELECT winner.target, winner.horizon, prediction.ts, prediction.split, prediction.y_pred, "
        "       prediction.y_proba, trial.trial_id, run.run_id "
        "FROM winner "
        "JOIN prediction ON prediction.rowid = winner.pred_rowid "
        "JOIN trial ON trial.trial_id = prediction.trial_id "
        "JOIN run ON run.run_id = trial.run_id",
        tuple(targets) + tuple(horizons),
    ).fetchall()
    out: dict[tuple[str, int], dict] = {}
    for target, horizon, ts, split, y_pred, y_proba, trial_id, run_id in rows:
        cls = int(round(y_pred))
        out[(target, horizon)] = {
            "ts": ts, "split": split, "trial_id": trial_id, "run_id": run_id, "horizon": horizon,
            "direction": _CLASS_DIRECTION.get(cls, "?"),
            "amplitude": _CLASS_AMPLITUDE.get(cls, "?"),
            "confidence": y_proba,
        }
    return out


def direction_metrics_by_target_and_horizon(conn: sqlite3.Connection, targets: list[str],
                                             horizons: list[int]) -> dict[tuple[str, int], dict | None]:
    """`/predictions` (universe-wide overview): same grouping strategy and
    correlated-subquery discipline as `direction_metrics_by_target()`
    above, partitioned by `(target, horizon)` instead of `target` alone --
    see that function's docstring for the full performance rationale (one
    round trip resolving target->(run_id, trial_id), one flat IN-list for
    predictions, one flat GROUP BY for AUC).

    Also resolves each pair's Diebold-Mariano result (`dm_result`,
    `kind='class_specific'` -- same default `_dm_result_for_run()` uses,
    same value `run_detail.html`/`target_detail()` actually display)
    inline: `run_id` is already known per pair from step 1, so this is one
    more flat IN-list query, not a second N+1.
    This is what feeds `/predictions`' ok/warning badge -- same "ok" if
    `p_value < 0.05` semantics already used on `run_detail.html`, not a
    new threshold invented for this page. `dm_result` is `None` when the
    resolved run has none yet (CPCV runs skip DM entirely, see
    `run_detail.html`)."""
    if not targets or not horizons:
        return {}
    target_placeholders = ",".join("?" for _ in targets)
    horizon_placeholders = ",".join("?" for _ in horizons)
    resolved = conn.execute(
        "WITH target_horizon_list AS ("
        "  SELECT DISTINCT run.target, run.horizon FROM run "
        f"   WHERE run.target IN ({target_placeholders}) AND run.horizon IN ({horizon_placeholders})"
        ") "
        "SELECT thl.target, thl.horizon, run.run_id, trial.trial_id "
        "FROM target_horizon_list thl "
        "JOIN run ON run.run_id = ("
        "  SELECT run_id FROM run WHERE run.target = thl.target AND run.horizon = thl.horizon "
        "  AND run.status = 'done' ORDER BY started_at DESC, rowid DESC LIMIT 1"
        ") "
        "JOIN trial ON trial.run_id = run.run_id AND trial.is_best = 1",
        tuple(targets) + tuple(horizons),
    ).fetchall()
    if not resolved:
        return {}

    pair_by_key = {(target, horizon): (run_id, trial_id) for target, horizon, run_id, trial_id in resolved}
    trial_ids = [trial_id for _, _, _, trial_id in resolved]
    run_ids = [run_id for _, _, run_id, _ in resolved]
    trial_placeholders = ",".join("?" for _ in trial_ids)
    run_placeholders = ",".join("?" for _ in run_ids)

    pred_rows = conn.execute(
        f"SELECT trial_id, split, y_true, y_pred FROM prediction INDEXED BY sqlite_autoindex_prediction_1 "
        f"WHERE trial_id IN ({trial_placeholders}) AND split IN ('test', 'holdout') "
        "AND y_true IS NOT NULL",
        tuple(trial_ids),
    ).fetchall()
    by_trial_split: dict[int, dict[str, list[tuple[float, float]]]] = {}
    for trial_id, split, y_true, y_pred in pred_rows:
        by_trial_split.setdefault(trial_id, {}).setdefault(split, []).append((y_true, y_pred))

    auc_rows = conn.execute(
        f"SELECT trial_id, AVG(value) FROM fold_metric "
        f"WHERE trial_id IN ({trial_placeholders}) AND split IN ('test', 'test_path') "
        "AND metric = 'AUC_ovr_4cls' GROUP BY trial_id",
        tuple(trial_ids),
    ).fetchall()
    auc_by_trial = dict(auc_rows)

    dm_rows = conn.execute(
        f"SELECT run_id, baseline, p_value FROM dm_result "
        f"WHERE run_id IN ({run_placeholders}) AND kind = 'class_specific'",
        tuple(run_ids),
    ).fetchall()
    dm_by_run = {run_id: {"baseline": baseline, "p_value": p_value} for run_id, baseline, p_value in dm_rows}

    out: dict[tuple[str, int], dict | None] = {}
    for key, (run_id, trial_id) in pair_by_key.items():
        splits = by_trial_split.get(trial_id, {})
        rows = splits.get("test") or []
        split_used = "test"
        if not rows:
            rows = splits.get("holdout") or []
            split_used = "holdout"
        if not rows:
            out[key] = None
            continue

        y_true = [_CLASS_DIRECTION[int(round(t))] for t, _ in rows]
        y_pred = [_CLASS_DIRECTION[int(round(p))] for _, p in rows]
        counts = {"UP": y_true.count("UP"), "DOWN": y_true.count("DOWN")}
        precision, recall, f1, support = precision_recall_fscore_support(
            y_true, y_pred, labels=["DOWN", "UP"], average=None, zero_division=0,
        )
        by_direction: dict[str, dict | None] = {}
        for i, direction in enumerate(["DOWN", "UP"]):
            if counts[direction] < _MIN_DIRECTION_SAMPLES:
                by_direction[direction] = None
                continue
            by_direction[direction] = {
                "n": int(support[i]), "precision": round(float(precision[i]), 4),
                "recall": round(float(recall[i]), 4), "f1": round(float(f1[i]), 4),
            }
        out[key] = {
            "run_id": run_id, "trial_id": trial_id, "split_used": split_used, "n": len(rows),
            "n_up": counts["UP"], "n_down": counts["DOWN"],
            "by_direction": by_direction,
            "auc_overall": auc_by_trial.get(trial_id),
            "dm_result": dm_by_run.get(run_id),
        }
    return out


def direction_metrics_by_target(conn: sqlite3.Connection, targets: list[str]) -> dict[str, dict | None]:
    """P8.1 perf fix -- grouped equivalent of calling
    `direction_metrics_for_target()` once per target. Same result shape
    and same rules, but O(1) round trips instead of O(n_targets) --
    confirmed as the query still blocking `/` end-to-end once
    `latest_prediction_for_target()`'s own N+1 was fixed separately
    (faulthandler dump landed here; regression test:
    `test_synthesis_overview_direction_metrics_lookup_is_not_n_plus_1`).

    WORSE shape than the other N+1: `direction_metrics_for_target()` did
    THREE sequential queries per target (latest done run, its best trial,
    then test predictions -- with a conditional 4th for the holdout
    fallback), not one. Grouping strategy:

    1. One correlated-subquery-per-target lookup (same winning pattern as
       `latest_predictions_by_target()`, for the same reason: window
       functions would force a full sort, this keeps each target's own
       indexed `ORDER BY started_at DESC LIMIT 1` plan) resolves
       target -> (run_id, trial_id) in a single round trip.
    2. ALL test+holdout prediction rows for every resolved trial_id in one
       IN-list query (no correlation needed here: trial_id is already
       known, it's a flat filter) -- the per-trial test-vs-holdout choice
       moves to a `groupby` in Python, same fallback rule as before (use
       test rows if any exist, else holdout), just no longer one query
       per decision.
    3. ALL AUC_ovr_4cls averages for those trial_ids in one GROUP BY query
       instead of one `_avg_metric()` call per target.

    The sklearn `precision_recall_fscore_support` call itself stays
    per-target in Python (CPU-bound, not a DB round trip -- it was never
    part of the bottleneck; the faulthandler dumps that found this
    function stuck were always inside a `conn.execute(...)` call, not
    inside sklearn)."""
    if not targets:
        return {}
    placeholders = ",".join("?" for _ in targets)
    resolved = conn.execute(
        "WITH target_list AS (SELECT DISTINCT target FROM run "
        f"                    WHERE target IN ({placeholders})) "
        "SELECT tl.target, run.run_id, trial.trial_id "
        "FROM target_list tl "
        "JOIN run ON run.run_id = ("
        "  SELECT run_id FROM run WHERE run.target = tl.target AND run.status = 'done' "
        "  ORDER BY started_at DESC, rowid DESC LIMIT 1"
        ") "
        "JOIN trial ON trial.run_id = run.run_id AND trial.is_best = 1",
        tuple(targets),
    ).fetchall()
    if not resolved:
        return {}

    trial_by_target = {target: (run_id, trial_id) for target, run_id, trial_id in resolved}
    trial_ids = [trial_id for _, _, trial_id in resolved]
    trial_placeholders = ",".join("?" for _ in trial_ids)

    # INDEXED BY: without it, the query planner picks idx_pred_split
    # (`split IN (...)`) over the trial_id-leading primary key -- driving
    # from `split` scans most of the table (test/holdout together are the
    # bulk of 12M rows) and filters trial_id as a residual check, instead
    # of the other way around. Measured on the real DB: unindexed forced a
    # 15s+ hang (same query, no LIMIT to bail out early unlike the
    # single-row lookups in latest_predictions_by_target); forcing the PK
    # index -- the same fix a human DBA would reach for first, short of the
    # ANALYZE this database has never had (`sqlite_stat1` absent, out of
    # scope for this pass, see "/" build report) -- brought it to 0.01s.
    # `sqlite_autoindex_prediction_1` is SQLite's own name for `prediction`'s
    # first (only) auto-generated index, backing the `(trial_id, ts)`
    # PRIMARY KEY declared in migrations/0001_initial.sql -- stable as long
    # as that PK's column order doesn't change.
    pred_rows = conn.execute(
        f"SELECT trial_id, split, y_true, y_pred FROM prediction INDEXED BY sqlite_autoindex_prediction_1 "
        f"WHERE trial_id IN ({trial_placeholders}) AND split IN ('test', 'holdout') "
        "AND y_true IS NOT NULL",
        tuple(trial_ids),
    ).fetchall()
    by_trial_split: dict[int, dict[str, list[tuple[float, float]]]] = {}
    for trial_id, split, y_true, y_pred in pred_rows:
        by_trial_split.setdefault(trial_id, {}).setdefault(split, []).append((y_true, y_pred))

    auc_rows = conn.execute(
        f"SELECT trial_id, AVG(value) FROM fold_metric "
        f"WHERE trial_id IN ({trial_placeholders}) AND split IN ('test', 'test_path') "
        "AND metric = 'AUC_ovr_4cls' GROUP BY trial_id",
        tuple(trial_ids),
    ).fetchall()
    auc_by_trial = dict(auc_rows)

    out: dict[str, dict | None] = {}
    for target, (run_id, trial_id) in trial_by_target.items():
        splits = by_trial_split.get(trial_id, {})
        rows = splits.get("test") or []
        split_used = "test"
        if not rows:
            rows = splits.get("holdout") or []
            split_used = "holdout"
        if not rows:
            out[target] = None
            continue

        y_true = [_CLASS_DIRECTION[int(round(t))] for t, _ in rows]
        y_pred = [_CLASS_DIRECTION[int(round(p))] for _, p in rows]
        counts = {"UP": y_true.count("UP"), "DOWN": y_true.count("DOWN")}
        precision, recall, f1, support = precision_recall_fscore_support(
            y_true, y_pred, labels=["DOWN", "UP"], average=None, zero_division=0,
        )
        by_direction: dict[str, dict | None] = {}
        for i, direction in enumerate(["DOWN", "UP"]):
            if counts[direction] < _MIN_DIRECTION_SAMPLES:
                by_direction[direction] = None
                continue
            by_direction[direction] = {
                "n": int(support[i]), "precision": round(float(precision[i]), 4),
                "recall": round(float(recall[i]), 4), "f1": round(float(f1[i]), 4),
            }
        out[target] = {
            "run_id": run_id, "trial_id": trial_id, "split_used": split_used, "n": len(rows),
            "n_up": counts["UP"], "n_down": counts["DOWN"],
            "by_direction": by_direction,
            "auc_overall": auc_by_trial.get(trial_id),
            "auc_note": ("non calculable par direction : la probabilité stockée est celle de la classe "
                         "prédite, pas P(hausse) -- pas une valeur de classement valide pour un AUC "
                         "par direction."),
        }
    return out


def direction_metrics_for_target(conn: sqlite3.Connection, target: str) -> dict | None:
    """P8.1 -- precision/recall/F1 split by direction (DOWN vs UP, not
    collapsed to a macro average) for the most recent completed run's best
    trial, recomputed live from the `prediction` table (`split='test'`,
    falling back to `'holdout'`) -- same read-only-on-request philosophy as
    the rest of this module. Not stored anywhere: `fold_metric` only ever
    persisted the DOWN/UP-collapsed macro average (`F1_dir`/`Acc_dir`),
    never the two classes separately.

    AUC per direction is deliberately NOT computed: `prediction.y_proba`
    holds the confidence of the PREDICTED class (`pipeline/engine.py`:
    `confidence = y_proba[arange(n), y_pred]`), not P(UP) -- not a valid
    ranking score for a fixed positive class, and a fabricated per-direction
    AUC from it would be a wrong number presented as a real one. `auc_note`
    carries this explanation instead; `auc_overall` returns the real
    aggregate `AUC_ovr_4cls` (computed correctly at training time, on the
    full probability matrix, before it collapses to per-row confidence for
    storage) for context, unsplit.

    Returns `None` if no completed run exists for this target yet, or if
    neither split has any labeled row. A direction with fewer than
    `_MIN_DIRECTION_SAMPLES` rows reports `None` for that direction rather
    than an unstable F1 on a handful of points (same threshold already used
    by `validation.metrics.metrics()` for its own FORT/FAIBLE breakdown)."""
    run_row = conn.execute(
        "SELECT run_id FROM run WHERE target = ? AND status = 'done' "
        "ORDER BY started_at DESC, rowid DESC LIMIT 1", (target,),
    ).fetchone()
    if run_row is None:
        return None
    run_id = run_row[0]
    trial_id = _best_trial_id(conn, run_id)
    if trial_id is None:
        return None

    rows = conn.execute(
        "SELECT y_true, y_pred FROM prediction WHERE trial_id = ? AND split = 'test' AND y_true IS NOT NULL",
        (trial_id,),
    ).fetchall()
    split_used = "test"
    if not rows:
        rows = conn.execute(
            "SELECT y_true, y_pred FROM prediction WHERE trial_id = ? AND split = 'holdout' AND y_true IS NOT NULL",
            (trial_id,),
        ).fetchall()
        split_used = "holdout"
    if not rows:
        return None

    y_true = [_CLASS_DIRECTION[int(round(t))] for t, _ in rows]
    y_pred = [_CLASS_DIRECTION[int(round(p))] for _, p in rows]

    counts = {"UP": y_true.count("UP"), "DOWN": y_true.count("DOWN")}
    # Each direction's threshold is independent: AAPL with 10 UP / 8 DOWN
    # rows must still show UP's real F1, not blank out both because DOWN
    # alone is thin. `precision_recall_fscore_support` is computed once
    # (needs both labels present to be meaningful either way) and then
    # gated into `by_direction` per direction below.
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=["DOWN", "UP"], average=None, zero_division=0,
    )
    by_direction: dict[str, dict | None] = {}
    for i, direction in enumerate(["DOWN", "UP"]):
        if counts[direction] < _MIN_DIRECTION_SAMPLES:
            by_direction[direction] = None
            continue
        by_direction[direction] = {
            "n": int(support[i]), "precision": round(float(precision[i]), 4),
            "recall": round(float(recall[i]), 4), "f1": round(float(f1[i]), 4),
        }

    return {
        "run_id": run_id, "trial_id": trial_id, "split_used": split_used, "n": len(rows),
        "n_up": counts["UP"], "n_down": counts["DOWN"],
        "by_direction": by_direction,
        "auc_overall": _avg_metric(conn, trial_id, ("test", "test_path"), metric="AUC_ovr_4cls"),
        "auc_note": ("non calculable par direction : la probabilité stockée est celle de la classe "
                     "prédite, pas P(hausse) -- pas une valeur de classement valide pour un AUC "
                     "par direction."),
    }


def synthesis_overview(conn: sqlite3.Connection, alpha: float = 0.10) -> dict:
    """P8 -- `/` (synthesis dashboard): assembles the five sections from
    already-existing, already-tested queries (`station_verdict`,
    `universe_coverage`, `trackstats.fdr_across_targets`, `list_runs`) plus
    the two new per-target ones above -- no page cache, called fresh on
    every request like every other page in this module.

    Per-target label comes from `DEFAULT_TARGET_GROUPS` (same source as
    `universe_overview`/the launch form), falling back to the raw symbol for
    a target no longer in the configured universe (a run can outlive a
    config edit).

    Regime classification (`phase9.classify_regime_daily`) is deliberately
    ABSENT from this structure: confirmed by exhaustive search to never run
    in production (no caller anywhere outside `phase9.py`'s own tests, no
    table stores a regime label) -- the template renders its own explicit
    empty state rather than this function simulating a value that does not
    exist. See DASHBOARD_B1-B2.md."""
    symbol_labels = {s["symbol"]: s["label"] for g in universe_overview(conn) for s in g["symbols"]}

    targets = list_distinct_targets(conn)
    fdr = trackstats.fdr_across_targets(conn, alpha=alpha)
    fdr_results = fdr["results"]

    quality_rows = []
    for t in targets:
        target = t["target"]
        q = fdr_results.get(target)
        quality_rows.append({
            "target": target, "label": symbol_labels.get(target, target),
            "p_value": q["p_value"] if q else None,
            "adjusted_p_value": q["adjusted_p_value"] if q else None,
            "significant": q["significant"] if q else None,
            "testable": q is not None,
        })

    prediction_rows = []
    metric_rows = []
    # Grouped lookups (one query each, not one per target) -- see
    # latest_predictions_by_target()/direction_metrics_by_target()'s
    # docstrings and the two test_synthesis_overview_*_is_not_n_plus_1
    # regression tests. Both used to be called once per target inside this
    # loop.
    target_names = [t["target"] for t in targets]
    latest_preds = latest_predictions_by_target(conn, target_names)
    direction_metrics = direction_metrics_by_target(conn, target_names)
    for t in targets:
        target = t["target"]
        label = symbol_labels.get(target, target)
        pred = latest_preds.get(target)
        prediction_rows.append({"target": target, "label": label, "prediction": pred})
        dm = direction_metrics.get(target)
        metric_rows.append({"target": target, "label": label, "metrics": dm})

    return {
        "coverage": {
            **universe_coverage(conn),
            "last_inference_at": last_inference_at(conn),
        },
        "verdict": station_verdict(conn, fdr_alpha=alpha),
        "quality_rows": quality_rows,
        "fdr_alpha": alpha,
        "fdr_n_tested": fdr["n_tested"],
        "prediction_rows": prediction_rows,
        "metric_rows": metric_rows,
        "recent_runs": list_runs(conn, limit=8),
    }
