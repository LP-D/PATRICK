"""Champion / challenger, database layer (migration 0025).

One model "in title" per (target, horizon). Without an explicit `champion`
row yet, the incumbent is the model the app already uses today: the latest
'done' run of that (target, horizon) with an exported best trial
(`implicit=True`) -- the first duel then crowns explicitly.

A replaced champion or a rejected challenger keeps only its descriptive
record in `model_archive` (features, algorithm, parameters, walk-forward /
holdout metrics, duel scores, live track record, config); `prune_run` then
deletes its heavy rows and model files, in short transactions (a worker may
be writing at the same time). `trial_registry` is never pruned: the DSR
n_trials must keep counting every configuration ever tested. The duel
itself lives in `pipeline/champion_duel.py`.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time

_CLASS_UP = {2, 3}  # 4-class index -> UP (UP_FAIBLE, UP_FORT), as in history._CLASS_DIRECTION
_PRUNE_BATCH = 2000


def current(conn: sqlite3.Connection, target: str, horizon: int,
            exclude_run_ids=()) -> dict | None:
    """The model in title for (target, horizon): the explicit `champion` row,
    else the implicit incumbent (latest 'done' run with an exported best
    trial, `exclude_run_ids` left out -- the run being evaluated must not
    compete against itself). None if neither exists."""
    row = conn.execute(
        "SELECT run_id, trial_id, reason, promoted_at, holdout_f1_dir FROM champion "
        "WHERE target = ? AND horizon = ?", (target, horizon)).fetchone()
    if row is not None and row[0] not in exclude_run_ids:
        return {"run_id": row[0], "trial_id": row[1], "reason": row[2], "promoted_at": row[3],
                "holdout_f1_dir": row[4], "implicit": False}
    excluded = list(exclude_run_ids)
    placeholders = ",".join("?" * len(excluded))
    not_excluded = f"AND r.run_id NOT IN ({placeholders}) " if excluded else ""
    row = conn.execute(
        "SELECT r.run_id, t.trial_id FROM run r JOIN trial t ON t.run_id = r.run_id "
        "WHERE r.target = ? AND r.horizon = ? AND r.status = 'done' "
        "AND t.is_best = 1 AND t.artifact_path IS NOT NULL "
        f"{not_excluded}"
        "ORDER BY r.started_at DESC, t.trial_id DESC LIMIT 1",
        (target, horizon, *excluded)).fetchone()
    if row is None:
        return None
    return {"run_id": row[0], "trial_id": row[1], "reason": "implicit_latest", "promoted_at": None,
            "holdout_f1_dir": None, "implicit": True}


def promote(conn: sqlite3.Connection, target: str, horizon: int, run_id: str, trial_id: int,
            reason: str, holdout_f1_dir: float | None = None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO champion (target, horizon, run_id, trial_id, reason, holdout_f1_dir) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(target, horizon) DO UPDATE SET "
            "run_id = excluded.run_id, trial_id = excluded.trial_id, reason = excluded.reason, "
            "holdout_f1_dir = excluded.holdout_f1_dir, promoted_at = datetime('now')",
            (target, horizon, run_id, trial_id, reason, holdout_f1_dir))


def best_trial(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT trial_id, regime, algo, sampler, n_features, params_json, artifact_path FROM trial "
        "WHERE run_id = ? AND is_best = 1 ORDER BY trial_id DESC LIMIT 1", (run_id,)).fetchone()
    if row is None:
        return None
    keys = ("trial_id", "regime", "algo", "sampler", "n_features", "params_json", "artifact_path")
    return dict(zip(keys, row))


def model_meta(artifact_path: str | None) -> dict:
    """The meta json written next to the exported model
    (`tracking.export.export_best_model`), {} if absent."""
    if not artifact_path:
        return {}
    meta_path = artifact_path[: -len(".joblib")] + "_meta.json"
    if not os.path.exists(meta_path):
        return {}
    with open(meta_path, encoding="utf-8") as f:
        return json.load(f)


def _metrics(conn: sqlite3.Connection, trial_id: int, split: str) -> dict:
    return {metric: value for metric, value in conn.execute(
        "SELECT metric, AVG(value) FROM fold_metric WHERE trial_id = ? AND split = ? GROUP BY metric",
        (trial_id, split))}


def _live_record(conn: sqlite3.Connection, trial_id: int) -> dict:
    """Live track record: `y_true` of a live row is binary (1.0 = the price
    went up, see predict.py) while `y_pred` is the 4-class index."""
    rows = conn.execute("SELECT y_pred, y_true FROM prediction WHERE trial_id = ? AND split = 'live'",
                        (trial_id,)).fetchall()
    resolved = [(int(p), float(t)) for p, t in rows if p is not None and t is not None]
    hits = sum((p in _CLASS_UP) == (t > 0.5) for p, t in resolved)
    return {"n_predictions": len(rows), "n_resolved": len(resolved),
            "hit_rate": (hits / len(resolved)) if resolved else None}


def archive(conn: sqlite3.Connection, run_id: str, role: str, duel: dict | None = None) -> int:
    """Descriptive record of a run's best model, before it is pruned.
    `role`: 'replaced_champion' | 'rejected_challenger' | 'superseded'."""
    run = conn.execute(
        "SELECT target, horizon, started_at, finished_at, snapshot_id, git_sha, config_json "
        "FROM run WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"Run not found: {run_id}")
    target, horizon, started_at, finished_at, snapshot_id, git_sha, config_json = run
    trial = best_trial(conn, run_id) or {}
    meta = model_meta(trial.get("artifact_path"))
    params = meta.get("best_params")
    if params is None and trial.get("params_json"):
        params = json.loads(trial["params_json"])
    trial_id = trial.get("trial_id")
    with conn:
        cur = conn.execute(
            "INSERT INTO model_archive (target, horizon, run_id, trial_id, role, run_started_at, "
            "run_finished_at, snapshot_id, git_sha, algo, sampler, regime, n_features, "
            "feature_names_json, params_json, wf_metrics_json, holdout_metrics_json, duel_json, "
            "live_json, config_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (target, horizon, run_id, trial_id, role, started_at, finished_at, snapshot_id, git_sha,
             trial.get("algo"), trial.get("sampler"), trial.get("regime"), trial.get("n_features"),
             json.dumps(meta.get("feature_names")) if meta.get("feature_names") is not None else None,
             json.dumps(params) if params is not None else None,
             json.dumps(_metrics(conn, trial_id, "test")) if trial_id else None,
             json.dumps(_metrics(conn, trial_id, "holdout")) if trial_id else None,
             json.dumps(duel) if duel is not None else None,
             json.dumps(_live_record(conn, trial_id)) if trial_id else None,
             config_json))
    return cur.lastrowid


def _delete_in_batches(conn: sqlite3.Connection, table: str, column: str, value) -> int:
    total = 0
    while True:
        with conn:
            n = conn.execute(
                f"DELETE FROM {table} WHERE rowid IN "
                f"(SELECT rowid FROM {table} WHERE {column} = ? LIMIT {_PRUNE_BATCH})", (value,)).rowcount
        total += n
        if n < _PRUNE_BATCH:
            return total
        time.sleep(0.01)  # lets a concurrent writer (worker) take the lock in between


def prune_run(conn: sqlite3.Connection, run_id: str) -> dict:
    """Deletes a run's heavy rows and model files, never its `trial_registry`
    entries. Refuses the champion in title."""
    if conn.execute("SELECT 1 FROM champion WHERE run_id = ?", (run_id,)).fetchone():
        raise ValueError(f"{run_id} is a champion in title: never pruned")
    trials = conn.execute("SELECT trial_id, artifact_path FROM trial WHERE run_id = ?", (run_id,)).fetchall()
    counts = dict.fromkeys(("prediction", "fold_metric", "holdout_diagnostic", "simulation"), 0)
    for trial_id, _path in trials:
        for table in counts:
            counts[table] += _delete_in_batches(conn, table, "trial_id", trial_id)
    for table in ("trial", "baseline_metric", "dm_result", "feature_stability",
                  "run_feature_stability", "run_phase_timing", "run"):
        counts[table] = _delete_in_batches(conn, table, "run_id", run_id)
    for _trial_id, path in trials:
        for file_path in (path, path[: -len(".joblib")] + "_meta.json" if path else None):
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
    with conn:
        conn.execute("UPDATE model_archive SET pruned = 1 WHERE run_id = ?", (run_id,))
    return counts


def plan_initialization(conn: sqlite3.Connection) -> list[dict]:
    """`patrick champions init`: for each (target, horizon) having exported
    models, the one kept in title -- the explicit champion if any, else the
    latest (what the app already uses) -- and the others to supersede.
    Existing runs are not dueled retroactively: replaying every old
    configuration on a common holdout would cost hours of training."""
    pairs = conn.execute(
        "SELECT DISTINCT r.target, r.horizon FROM run r JOIN trial t ON t.run_id = r.run_id "
        "WHERE r.status = 'done' AND t.is_best = 1 AND t.artifact_path IS NOT NULL "
        "ORDER BY r.target, r.horizon").fetchall()
    plan = []
    for target, horizon in pairs:
        keep = current(conn, target, horizon)
        others = [r[0] for r in conn.execute(
            "SELECT DISTINCT r.run_id FROM run r JOIN trial t ON t.run_id = r.run_id "
            "WHERE r.target = ? AND r.horizon = ? AND r.status = 'done' AND t.is_best = 1 "
            "AND t.artifact_path IS NOT NULL AND r.run_id != ? ORDER BY r.started_at",
            (target, horizon, keep["run_id"]))]
        plan.append({"target": target, "horizon": horizon, "keep": keep["run_id"],
                     "keep_trial": keep["trial_id"], "explicit": not keep["implicit"], "supersede": others})
    return plan


def apply_initialization(conn: sqlite3.Connection, plan: list[dict]) -> dict:
    promoted = superseded = 0
    for item in plan:
        if not item["explicit"]:
            promote(conn, item["target"], item["horizon"], item["keep"], item["keep_trial"],
                    reason="initial_latest")
            promoted += 1
        for run_id in item["supersede"]:
            archive(conn, run_id, role="superseded")
            prune_run(conn, run_id)
            superseded += 1
    return {"promoted": promoted, "superseded": superseded}


def list_champions(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT c.target, c.horizon, c.run_id, c.trial_id, c.reason, c.promoted_at, c.holdout_f1_dir, "
        "t.algo, t.n_features FROM champion c LEFT JOIN trial t ON t.trial_id = c.trial_id "
        "ORDER BY c.target, c.horizon").fetchall()
    keys = ("target", "horizon", "run_id", "trial_id", "reason", "promoted_at", "holdout_f1_dir",
            "algo", "n_features")
    return [dict(zip(keys, r)) for r in rows]


def list_archive(conn: sqlite3.Connection, target: str | None = None, horizon: int | None = None) -> list[dict]:
    where, params = [], []
    if target is not None:
        where.append("target = ?")
        params.append(target)
    if horizon is not None:
        where.append("horizon = ?")
        params.append(horizon)
    sql = ("SELECT archive_id, target, horizon, run_id, role, decided_at, algo, n_features, "
           "wf_metrics_json, duel_json FROM model_archive"
           + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY decided_at DESC, archive_id DESC")
    keys = ("archive_id", "target", "horizon", "run_id", "role", "decided_at", "algo", "n_features",
            "wf_metrics_json", "duel_json")
    return [dict(zip(keys, r)) for r in conn.execute(sql, params).fetchall()]
